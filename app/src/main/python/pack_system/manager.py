"""
pack_system.manager - propose -> approve -> activate -> roll back, for `code.v1` and `lang.v1` packs
===================================================================================================
Every state change goes through here and every change that matters is the user's explicit decision:

    propose(source)        parse, validate, scan; a good package becomes a PENDING proposal. NOTHING is installed,
                           imported or executed.
    approve(proposal_id, user_approved=True[, confirm_risky=True])
                           install the files (atomic, read-only, hash-recorded), make the version active, load it
                           (hot: new/updated packs; at the next start: packs that REPLACE existing app modules), run
                           the pack's own `selftest(api)` when it has one - and go back to the previous version if the
                           load or the self-test fails.
    rollback / disable / enable / remove
    activate_all()         start-up: verify hashes, install the import overlay, import every active pack. A pack that
                           fails is quarantined (kept, not loaded) and the app starts without it.

Methods never raise for a user-level problem; they return plain dicts with `status` and, for failures, `code` and
`message_fa`. History is a hash-chained audit (`packs/audit.jsonl`).
"""

import importlib
import os
import sys
import threading
import time

from brain_hub.audit import HubAudit

from . import limits, manifest as manifest_mod, overlay, scan as scan_mod
from .api import PackAPI
from .errors import PackError
from .registry import REGISTRY, interrupt_thread
from .store import PackStore

__all__ = ["PackManager"]


def _fail(code, message_fa, **extra):
    out = {"status": "failed", "code": code, "message_fa": message_fa}
    out.update(extra)
    return out


class PackManager:
    def __init__(self, root, clock=time.time, registry=REGISTRY, audit=None):
        self.store = PackStore(root, clock)
        self.clock = clock
        self.registry = registry
        self.audit = audit or HubAudit(os.path.join(self.store.root, "audit.jsonl"), clock)
        self._lock = threading.RLock()
        self._live = {}                     # pack id -> {module: (file, is_package, pack id)} currently importable
        self.loaded = {}                    # pack id -> version imported and registered in this process
        self.boot_report = None
        self._lang = None
        self.registry.on_failure = self._on_runtime_failure

    @property
    def lang(self):
        """The retrieval service over this manager's language packs (built on first use)."""
        if self._lang is None:
            from .lang import LangService
            self._lang = LangService(self)
        return self._lang

    # ================================================================== reading
    @property
    def state(self):
        return self.store.state

    def exists(self):
        return os.path.isdir(self.store.root)

    def list(self):
        """One plain row per installed pack."""
        rows = []
        restart = set(self.state["restart_needed"])
        for pid, rec in sorted(self.state["packs"].items()):
            active = rec.get("active")
            info = rec["versions"].get(str(active), {}) if active is not None else {}
            if rec.get("quarantined"):
                label = "quarantined"
            elif not rec.get("enabled", True):
                label = "disabled"
            elif active is None:
                label = "inactive"
            elif pid in restart:
                label = "pending_restart"
            else:
                label = "active"
            rows.append({"pack_id": pid, "kind": rec["kind"], "title": rec.get("title") or pid, "state": label,
                         "active_version": active, "versions": sorted((int(v) for v in rec["versions"])),
                         "permissions": list(info.get("permissions") or ()), "replaces": list(info.get("replaces") or ()),
                         "description": info.get("description", ""), "risky": bool(info.get("risky")),
                         "failures": rec.get("failures", 0), "quarantine": rec.get("quarantined"),
                         "loaded": self.loaded.get(pid)})
        return rows

    def get(self, pid):
        for row in self.list():
            if row["pack_id"] == pid:
                return row
        return None

    def find(self, text):
        """The pack whose id or title appears in `text` as whole words (the longest match), else None."""
        from .lang import normalize_fa
        padded = " %s " % normalize_fa(str(text).replace("_", " "))
        best = None
        for row in self.list():
            for name in (row["pack_id"], row["title"]):
                key = normalize_fa(str(name).replace("_", " "))
                if len(key) >= 3 and (" %s " % key) in padded and (best is None or len(key) > best[0]):
                    best = (len(key), row)
        return best[1] if best else None

    def pending(self):
        out = []
        for rec in self.store.pending_proposals():
            m = rec["manifest"]
            out.append({"proposal_id": rec["proposal_id"], "pack_id": m["id"], "kind": m["schema"], "version": m["version"], "title": m["title"]})
        return out

    def history(self, pid=None, limit=15):
        rows = [e for e in self.audit.entries() if pid is None or e.get("subject") == pid]
        return rows[-max(1, min(int(limit), 100)):]

    def restart_needed(self):
        return list(self.state["restart_needed"])

    def safe_mode(self):
        boot = self.state["boot"]
        return {"level": boot.get("safe_level", 0), "reason": boot.get("safe_reason", ""), "crashes": boot.get("crashes", 0)}

    def summary(self):
        rows = self.list()
        return {"installed": len(rows), "active": sum(1 for r in rows if r["state"] == "active"),
                "disabled": sum(1 for r in rows if r["state"] == "disabled"),
                "quarantined": sum(1 for r in rows if r["state"] == "quarantined"),
                "pending_restart": len(self.state["restart_needed"]), "pending_proposals": len(self.pending()),
                "safe_mode": self.safe_mode(), "state_recovery": self.store.recovery, "audit": self.audit.verify() if os.path.exists(self.audit.path) else None}

    # ================================================================== propose
    def _raw(self, source):
        from . import intake
        if isinstance(source, dict):
            return source
        found = intake.parse_bytes(source) if isinstance(source, (bytes, bytearray)) else intake.find_pack_in_text(source)
        if found is None:
            raise PackError("E_PACK_NONE", "در این ورودی بستهٔ code.v1 یا lang.v1 پیدا نشد.")
        return found[1]

    def propose(self, source, origin="chat"):
        try:
            m = manifest_mod.normalize(self._raw(source))
            warnings, report = [], None
            if m["schema"] == limits.CODE_SCHEMA:
                report = scan_mod.scan_pack(m)
                if not report.ok:
                    first = report.blocks[0]
                    self.audit.append("pack.rejected", m["id"], {"code": first.code, "line": first.line, "n": len(report.blocks)})
                    return {"status": "rejected", "code": first.code, "message_fa": first.message_fa, "pack_id": m["id"],
                            "findings": [f.to_dict() for f in report.blocks[:8]]}
                warnings = [f.to_dict() for f in report.warnings[:8]]
            rec = self.store.pack(m["id"])
            action = "create"
            if rec is not None:
                if rec["kind"] != m["schema"]:
                    raise PackError("E_PACK_KIND_CHANGE", "بستهٔ «%s» از نوع دیگری نصب شده است؛ نام دیگری بده." % m["id"])
                action = "update"
                same = [v for v, info in rec["versions"].items() if info.get("fingerprint") == m["fingerprint"]]
                if same:
                    return {"status": "noop_identical", "pack_id": m["id"], "version": int(same[0]), "title": m["title"],
                            "active": rec.get("active") == int(same[0])}
                newest = max(int(v) for v in rec["versions"])
                if m["version"] <= newest:
                    raise PackError("E_PACK_VERSION_OLD", "نسخهٔ بسته (%d) باید از جدیدترین نسخهٔ نصب‌شده (%d) بزرگ‌تر باشد." % (m["version"], newest))
            elif len(self.state["packs"]) >= limits.MAX_PACKS:
                raise PackError("E_PACK_LIMIT", "حداکثر %d بسته می‌شود نصب کرد؛ اول یکی را حذف کن." % limits.MAX_PACKS)
            qid = self.store.save_proposal(m, origin, {"warnings": warnings})
            self.store.trim_proposals()
            self.audit.append("pack.proposed", m["id"], {"version": m["version"], "kind": m["schema"], "bytes": m["total_bytes"],
                                                         "risky": m["risky"], "origin": origin, "warnings": len(warnings)})
            samples = [{"q": e["q"][0][:80], "a": e["a"][:110]} for e in (m.get("qa") or ())[:2]]
            return {"status": "pending_approval", "proposal_id": qid, "pack_id": m["id"], "kind": m["schema"], "action": action,
                    "samples": samples, "phrasings": sum(len(e["q"]) for e in (m.get("qa") or ())),
                    "planned_version": m["version"], "title": m["title"], "description": m["description"],
                    "permissions": m["permissions"], "replaces": m["replaces"], "risky": m["risky"],
                    "files": sorted(m.get("files") or ()), "bytes": m["total_bytes"], "qa_count": len(m.get("qa") or ()),
                    "warnings": warnings, "restart_needed": bool(m["replaces"]), "notes_fa": m.get("notes_fa", ""),
                    "created_by": m.get("created_by", "")}
        except PackError as exc:
            self.audit.append("pack.rejected", "", {"code": exc.code})
            return exc.to_dict()
        except OSError as exc:
            return _fail("E_PACK_IO", "نوشتن در حافظهٔ برنامه ناموفق بود؛ چیزی تغییر نکرد.", detail=type(exc).__name__)

    def decline(self, proposal_id):
        rec = self.store.load_proposal(proposal_id)
        self.store.delete_proposal(proposal_id)
        if rec is not None:
            self.audit.append("pack.declined", rec["manifest"]["id"], {"version": rec["manifest"]["version"]})
        return {"status": "declined", "proposal_id": str(proposal_id)[:30]}

    # ================================================================== approve
    def approve(self, proposal_id, *, user_approved=False, confirm_risky=False):
        if user_approved is not True:
            return {"status": "approval_required", "proposal_id": str(proposal_id)[:30]}
        rec = self.store.load_proposal(proposal_id)
        if rec is None:
            return _fail("E_PACK_NO_PROPOSAL", "این پیشنهاد دیگر وجود ندارد یا منقضی شده است؛ بسته را دوباره بفرست.")
        try:
            m = manifest_mod.normalize(rec["manifest"])           # nothing stored is trusted: validate and scan again
            if m["schema"] == limits.CODE_SCHEMA and not scan_mod.scan_pack(m).ok:
                raise PackError("E_PACK_SCAN", "بررسی امنیتی کد در لحظهٔ نصب رد شد.")
        except PackError as exc:
            self.store.delete_proposal(proposal_id)
            return exc.to_dict()
        if m["risky"] and confirm_risky is not True:
            return {"status": "confirm_required", "proposal_id": proposal_id, "pack_id": m["id"], "risky": True,
                    "permissions": [p for p in m["permissions"] if p in limits.RISKY_PERMISSIONS], "replaces": m["replaces"]}
        with self._lock:
            pid, version = m["id"], m["version"]
            previous = (self.store.pack(pid) or {}).get("active")
            try:
                status = self.store.install(m, origin=rec.get("origin", "chat"))
            except PackError as exc:
                return exc.to_dict()
            except OSError as exc:
                return _fail("E_PACK_IO", "نصب روی حافظه ناموفق بود؛ چیزی فعال نشد.", detail=type(exc).__name__)
            ok, why = self.store.verify(pid, version)
            if not ok:
                self.audit.append("pack.install_failed", pid, {"version": version, "why": why})
                return _fail("E_PACK_VERIFY", "فایل‌های نصب‌شده با هش ثبت‌شده نمی‌خوانند (%s)؛ چیزی فعال نشد." % why)
            state_rec = self.store.pack(pid)
            state_rec.update({"active": version, "enabled": True, "quarantined": None, "failures": 0})
            self.store.save()
            self.audit.append("pack.installed", pid, {"version": version, "kind": m["schema"], "status": status, "bytes": m["total_bytes"]})
            result = self._activate(pid, version, previous)
            if result.get("status") != "applied":
                return result
            self.store.delete_proposal(proposal_id)
            self.store.prune(pid)
            result.update({"pack_id": pid, "version": version, "title": m["title"], "kind": m["schema"], "previous_version": previous})
            return result

    # ================================================================== activation
    def _restore(self, pid, previous):
        rec = self.store.pack(pid)
        if rec is None:
            return
        rec["active"] = previous
        if previous is None:
            rec["enabled"] = False
        self.store.save()

    def _activate(self, pid, version, previous):
        """Make `version` live in this process (or mark that a restart is needed). Returns an 'applied' / 'failed' dict."""
        rec = self.store.pack(pid)
        stored = self.store.read_manifest(pid, version) or {}
        if rec["kind"] == limits.LANG_SCHEMA:
            self.registry.lang_version += 1
            self.audit.append("pack.activated", pid, {"version": version, "hot": True})
            return {"status": "applied", "hot": True, "restart_needed": False}
        replaces = list(stored.get("replaces") or ())
        if replaces:                                              # modules of the app itself: the next start loads them
            self._note_restart(pid)
            self.audit.append("pack.activated", pid, {"version": version, "hot": False, "replaces": len(replaces)})
            return {"status": "applied", "hot": False, "restart_needed": True}
        problem = self._hot_load(pid, version)
        if problem:
            self._unload(pid)
            self._restore(pid, previous)
            if previous is not None and rec.get("enabled", True):
                self._hot_load(pid, previous)
            self.audit.append("pack.activation_failed", pid, {"version": version, "why": problem[:80]})
            return _fail("E_PACK_ACTIVATION", "بسته بارگذاری یا آزمون نشد و برگردانده شد: %s" % problem[:120], rolled_back_to=previous)
        self._clear_restart(pid)
        self.state["last_good"][pid] = version                    # it imported, registered and passed its own test in this process
        self.store.save()
        self.audit.append("pack.activated", pid, {"version": version, "hot": True})
        return {"status": "applied", "hot": True, "restart_needed": False}

    def _note_restart(self, pid):
        if pid not in self.state["restart_needed"]:
            self.state["restart_needed"].append(pid)
            self.store.save()

    def _clear_restart(self, pid):
        if pid in self.state["restart_needed"]:
            self.state["restart_needed"] = [p for p in self.state["restart_needed"] if p != pid]
            self.store.save()

    def _purge_modules(self, pid):
        for name in [n for n in list(sys.modules) if n == pid or n.startswith(pid + ".")]:
            sys.modules.pop(name, None)

    def _unload(self, pid):
        self.registry.unregister_pack(pid)
        self._purge_modules(pid)
        self._live.pop(pid, None)
        self.loaded.pop(pid, None)
        overlay.install_mapping(self._merged())

    def _merged(self):
        merged = {}
        for mapping in self._live.values():
            merged.update(mapping)
        return merged

    def _mapping_for(self, pid, version):
        stored = self.store.read_manifest(pid, version) or {}
        return overlay.build_mapping(pid, self.store.files_dir(pid, version), stored.get("files") or ())

    def _run_selftest(self, fn, api):
        box = {}

        def target():
            try:
                box["r"] = fn(api)
            except BaseException as exc:                       # the pack's own test; report, never propagate
                box["e"] = exc
        thread = threading.Thread(target=target, daemon=True)
        thread.start()
        thread.join(limits.SELFTEST_SECONDS)
        if thread.is_alive():
            interrupt_thread(thread)
            return "selftest timeout"
        if "e" in box:
            return "selftest %s: %s" % (type(box["e"]).__name__, str(box["e"])[:100])
        return "selftest returned False" if box.get("r") is False else ""

    def _hot_load(self, pid, version):
        """Import and register one pack version. Returns '' on success, else a short reason."""
        self.registry.unregister_pack(pid)
        self._purge_modules(pid)
        stored = self.store.read_manifest(pid, version)
        if stored is None:
            return "manifest_missing"
        self._live[pid] = self._mapping_for(pid, version)
        overlay.install_mapping(self._merged())
        entry = stored.get("entry") or ""
        api = PackAPI(pid, version, stored.get("permissions") or (), self.store, self.registry, self.clock)
        try:
            if entry:
                module = importlib.import_module(entry)
                register = getattr(module, "register", None)
                if callable(register):
                    register(api)
                selftest = getattr(module, "selftest", None)
                if callable(selftest):
                    why = self._run_selftest(selftest, api)
                    if why:
                        return why
        except BaseException as exc:                           # includes SystemExit from a careless pack
            if isinstance(exc, KeyboardInterrupt):
                raise
            return "%s: %s" % (type(exc).__name__, str(exc)[:100])
        self.loaded[pid] = version
        return ""

    # ================================================================== start-up
    def activate_all(self, *, at_boot=True):
        """Verify and load every active code pack.

        At boot (called once, before the app's own modules are imported) every pack is loaded. Later (`at_boot=False`:
        leaving safe mode, a lazily created manager) a pack that REPLACES app modules is not loaded - those modules are
        already imported - and is listed as waiting for a restart instead."""
        report = {"loaded": [], "failed": [], "skipped": [], "restart": []}
        with self._lock:
            self.store.sweep()
            wanted = []
            for pid, rec in sorted(self.state["packs"].items()):
                if rec["kind"] != limits.CODE_SCHEMA or rec.get("active") is None:
                    continue
                if not rec.get("enabled", True) or rec.get("quarantined"):
                    report["skipped"].append(pid)
                    continue
                if not at_boot and pid in self.loaded and self.loaded[pid] == rec["active"]:
                    continue
                ok, why = self.store.verify(pid, rec["active"])
                if not ok:
                    self._quarantine(pid, "verify:" + why)
                    report["failed"].append({"pack_id": pid, "why": "verify:" + why})
                    continue
                stored = self.store.read_manifest(pid, rec["active"]) or {}
                if not at_boot and stored.get("replaces"):
                    self._note_restart(pid)
                    report["restart"].append(pid)
                    continue
                self._live[pid] = self._mapping_for(pid, rec["active"])
                wanted.append((pid, rec["active"]))
            overlay.install_mapping(self._merged())
            if at_boot:
                self.state["restart_needed"] = []
            for pid, version in wanted:
                problem = self._hot_load(pid, version)
                if problem:
                    self._unload(pid)
                    self._quarantine(pid, problem)
                    report["failed"].append({"pack_id": pid, "why": problem[:80]})
                else:
                    report["loaded"].append({"pack_id": pid, "version": version})
            self.store.save()
        self.boot_report = report
        return report

    # ================================================================== failure handling
    def _quarantine(self, pid, reason):
        rec = self.store.pack(pid)
        if rec is None:
            return
        rec["quarantined"] = {"reason": str(reason)[:120], "ts": round(float(self.clock()), 3)}
        self.store.save()
        self.audit.append("pack.quarantined", pid, {"reason": str(reason)[:80]})

    def _on_runtime_failure(self, pid, reason):
        with self._lock:
            rec = self.store.pack(pid)
            if rec is None or not rec.get("enabled", True):
                return
            rec["failures"] = rec.get("failures", 0) + 1
            rec["enabled"] = False
            self.store.save()
            self.registry.unregister_pack(pid)
            self.audit.append("pack.auto_disabled", pid, {"reason": reason, "last": self.registry.last_error.get(pid, "")[:80]})

    # ================================================================== rollback / switches
    def rollback(self, pid, to_version=None):
        with self._lock:
            rec = self.store.pack(pid)
            if rec is None:
                return _fail("E_PACK_NOT_FOUND", "چنین بسته‌ای نصب نیست.")
            current = rec.get("active")
            versions = sorted(int(v) for v in rec["versions"])
            if to_version is None:
                older = [v for v in versions if current is None or v < current]
                if not older:
                    return _fail("E_PACK_NO_PREVIOUS", "نسخهٔ قدیمی‌تری برای برگشتن نیست.")
                to_version = older[-1]
            if to_version not in versions:
                return _fail("E_PACK_NO_VERSION", "نسخهٔ %s از این بسته نصب نیست." % to_version)
            ok, why = self.store.verify(pid, to_version)
            if not ok:
                return _fail("E_PACK_VERIFY", "نسخهٔ %d سالم نیست (%s)." % (to_version, why))
            rec["active"], rec["enabled"], rec["quarantined"], rec["failures"] = to_version, True, None, 0
            self.store.save()
            if rec["kind"] == limits.CODE_SCHEMA:
                self._unload(pid)
            result = self._activate(pid, to_version, current)
            if result.get("status") != "applied":
                return result
            self.audit.append("pack.rolled_back", pid, {"from": current, "to": to_version})
            result.update({"status": "rolled_back", "pack_id": pid, "from_version": current, "to_version": to_version})
            return result

    def disable(self, pid):
        with self._lock:
            rec = self.store.pack(pid)
            if rec is None:
                return _fail("E_PACK_NOT_FOUND", "چنین بسته‌ای نصب نیست.")
            rec["enabled"] = False
            self.store.save()
            replaced = bool((self.store.read_manifest(pid, rec["active"]) or {}).get("replaces")) if rec.get("active") is not None else False
            if rec["kind"] == limits.CODE_SCHEMA:
                self._unload(pid)
            else:
                self.registry.lang_version += 1
            if replaced:
                self._note_restart(pid)
            self.audit.append("pack.disabled", pid, {})
            return {"status": "disabled", "pack_id": pid, "title": rec.get("title") or pid, "restart_needed": replaced}

    def enable(self, pid, *, user_approved=False):
        if user_approved is not True:
            return {"status": "approval_required", "pack_id": str(pid)[:40]}
        with self._lock:
            rec = self.store.pack(pid)
            if rec is None or rec.get("active") is None:
                return _fail("E_PACK_NOT_FOUND", "چنین بستهٔ فعال‌شدنی‌ای نیست.")
            ok, why = self.store.verify(pid, rec["active"])
            if not ok:
                return _fail("E_PACK_VERIFY", "فایل‌های بسته سالم نیستند (%s)." % why)
            rec.update({"enabled": True, "quarantined": None, "failures": 0})
            self.store.save()
            result = self._activate(pid, rec["active"], rec["active"])
            if result.get("status") == "applied":
                self.audit.append("pack.enabled", pid, {"version": rec["active"]})
                result.update({"status": "enabled", "pack_id": pid, "title": rec.get("title") or pid})
            return result

    def remove(self, pid, *, user_approved=False):
        if user_approved is not True:
            return {"status": "approval_required", "pack_id": str(pid)[:40]}
        with self._lock:
            rec = self.store.pack(pid)
            if rec is None:
                return _fail("E_PACK_NOT_FOUND", "چنین بسته‌ای نصب نیست.")
            title = rec.get("title") or pid
            replaced = any((self.store.read_manifest(pid, v) or {}).get("replaces") for v in rec["versions"]) if rec["kind"] == limits.CODE_SCHEMA else False
            if rec["kind"] == limits.CODE_SCHEMA:
                self._unload(pid)
            else:
                self.registry.lang_version += 1
            self.store.remove_pack(pid)
            self.audit.append("pack.removed", pid, {})
            return {"status": "removed", "pack_id": pid, "title": title, "restart_needed": replaced}

    # ================================================================== boot bookkeeping (see boot.py)
    def mark_good(self):
        with self._lock:
            boot = self.state["boot"]
            boot["pending"], boot["crashes"], boot["last_good_ts"] = None, 0, round(float(self.clock()), 3)
            self.state["last_good"] = {pid: rec["active"] for pid, rec in self.state["packs"].items()
                                       if rec.get("active") is not None and rec.get("enabled", True) and not rec.get("quarantined")}
            self.store.save()

    def leave_safe_mode(self):
        with self._lock:
            boot = self.state["boot"]
            boot.update({"safe_level": 0, "safe_reason": "", "crashes": 0})
            self.store.save()
            self.audit.append("pack.safe_mode_left", "", {})
            return {"status": "left"}
