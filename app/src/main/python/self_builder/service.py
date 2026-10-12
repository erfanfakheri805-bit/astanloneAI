"""
Self-Builder - service facade
=============================
The one object the rest of the application talks to. It owns the writable
Self-Builder root, opens it lazily, reconciles it once per process and exposes
build / rollback / invoke / inspect.

Lazy by design
--------------
* `get_service(memory)` only computes where the root would be
  (`<directory of memory.db>/self_builder` - on Android `files_dir/data/
  self_builder`); it touches nothing on disk.
* Reading operations (`capabilities()`, `match()`, `invoke()`) open an EXISTING
  registry and return "nothing" when there is none - they never create one.
* Only `build()` creates the root, the database and the sub-directories, and
  only when a build is really requested. Ordinary conversation therefore never
  writes anything, and the application's own source tree is never written to.

Persistence and restart
-----------------------
Nothing is kept in process memory that is not also on disk: a fresh process
(or the app after being killed and started again) opens the same
`self_builder.db`, runs `loader.reconcile()` once - verifying every active
version against its recorded SHA-256, validating and re-testing it, handling
crash leftovers - and serves exactly what the previous process persisted.
Loaded modules are cached per (capability, version, hash) for speed only.

Integrity at run time
---------------------
A call to a capability whose files fail verification (modified, missing)
does not run them: the version is marked `broken`, its module is
quarantined, the newest healthy older version is restored and used instead
(or the capability is disabled when none is healthy) - and the result says so.
"""

import os
import sqlite3
import threading
import weakref

from . import loader, matcher, mirror, policy, sandbox
from .builder import Builder, ST_APPLIED, ST_FAILED
from .errors import SelfBuilderError, StoreError
from .registry import CAP_ACTIVE, Registry
from .store import Store
from .workspace import Workspace

ROOT_DIRNAME = "self_builder"
_LOCK = threading.Lock()
_SERVICES = weakref.WeakKeyDictionary()


def default_root(memory):
    """Where this application's Self-Builder root lives (nothing is created)."""
    db_path = getattr(memory, "db_path", None)
    if not db_path:
        return None
    return os.path.join(os.path.dirname(os.path.abspath(db_path)), ROOT_DIRNAME)


def get_service(memory):
    """The service for `memory`'s data directory (one per MemorySystem object)."""
    root = default_root(memory)
    if root is None:
        return None
    with _LOCK:
        service = _SERVICES.get(memory)
        if service is None or service.root != root:
            service = SelfBuilderService(root, memory)
            _SERVICES[memory] = service
        return service


def _failure(code, detail, **info):
    return {"status": ST_FAILED, "capability_id": None, "kind": None, "title": None, "upgrade_id": None,
            "stages": [], "attempts": [], "repairs": [], "error": {"code": code, "detail": detail, "info": info},
            "confirmation": None}


class SelfBuilderService:
    def __init__(self, root, memory=None):
        self.root = os.path.abspath(root)
        self._memory_ref = weakref.ref(memory) if memory is not None else None
        self._lock = threading.RLock()
        self._ws = None
        self._store = None
        self._registry = None
        self._builder = None
        self._modules = {}
        self._records_cache = None
        self.startup_report = None
        self.open_error = None

    # ------------------------------------------------------------- lifecycle
    def _memory(self):
        return self._memory_ref() if self._memory_ref is not None else None

    def db_path(self):
        return os.path.join(self.root, policy.ROOT_FILE_DB)

    def exists(self):
        """Is there a persisted registry on disk (no side effects)?"""
        return os.path.isfile(self.db_path())

    def is_open(self):
        return self._builder is not None

    def unavailable(self):
        """None when the registry is usable - or simply does not exist yet (nothing was ever built); else
        {"code", "detail"}: a registry IS on disk but cannot be opened (damaged database, no permission,
        a failed verification). The conversation uses this to say "I cannot tell right now" instead of
        answering as if there were no capabilities. Never creates anything."""
        with self._lock:
            if self._builder is not None or not self.exists():
                return None
            if self._open(create=False):
                return None
            return dict(self.open_error or {"code": "E_STORE_OPEN", "detail": "registry unavailable"})

    def _open(self, create):
        """Open (and reconcile, once) the registry. `create=False` never
        creates anything: returns False when there is no registry yet."""
        with self._lock:
            if self._builder is not None:
                return True
            if not create and not self.exists():
                return False
            store = None
            try:
                ws = Workspace(self.root)
                store = Store(ws.db_path())
                registry = Registry(store)
                builder = Builder(ws, store, registry)
                report = loader.reconcile(ws, store, registry)
            except (sqlite3.DatabaseError, OSError, SelfBuilderError) as e:
                if store is not None:
                    store.close()
                self.open_error = {"code": getattr(e, "code", "E_STORE_OPEN"), "detail": type(e).__name__}
                return False
            self._ws, self._store, self._registry, self._builder = ws, store, registry, builder
            self.startup_report = report
            self.open_error = None
            return True

    def close(self):
        with self._lock:
            if self._store is not None:
                self._store.close()
            self._ws = self._store = self._registry = self._builder = None
            self._modules.clear()
            self._records_cache = None

    # -------------------------------------------------------------- read side
    def _records(self):
        """Every registry record (with spec), cached until the audit log moves."""
        token = self._store.query_one("SELECT COALESCE(MAX(seq), 0) AS s FROM audit_log")["s"]
        if self._records_cache is None or self._records_cache[0] != token:
            self._records_cache = (token, self._registry.list())
        return self._records_cache[1]

    def capabilities(self, include_disabled=True):
        with self._lock:
            if not self._open(create=False):
                return []
            return [dict(r) for r in self._records() if include_disabled or r["status"] == CAP_ACTIVE]

    def capability(self, capability_id):
        with self._lock:
            if not self._open(create=False):
                return None
            return self._registry.get(capability_id)

    def has_active_capabilities(self):
        with self._lock:
            return self._open(create=False) and self._registry.count_active() > 0

    def versions(self, capability_id):
        with self._lock:
            if not self._open(create=False):
                return []
            return self._registry.versions(capability_id)

    def history(self, capability_id=None, limit=20):
        with self._lock:
            if not self._open(create=False):
                return []
            return self._builder.history(capability_id, limit)

    def audit_tail(self, limit=20, capability_id=None):
        with self._lock:
            if not self._open(create=False):
                return []
            return self._store.audit_entries(limit, capability_id)

    def status(self):
        """Plain-data state of the Self-Builder (never creates anything)."""
        with self._lock:
            opened = self._open(create=False)          # first: a failed attempt must show up in `open_error`
            info = {"root": self.root, "exists": self.exists(), "policy": policy.Policy.describe(),
                    "open_error": self.open_error}
            if not opened:
                info.update(capabilities=0, active=0, audit_chain=None, startup=None)
                return info
            ok, bad, count = self._store.verify_audit_chain()
            info.update(capabilities=self._registry.count(), active=self._registry.count_active(),
                        schema_version=self._store.schema_version(), counts=self._store.counts(),
                        audit_chain={"ok": ok, "entries": count, "first_bad_seq": bad},
                        startup=self.startup_report and dict(self.startup_report))
            return info

    def self_check(self):
        """Verify every active version right now (hash, validation, own tests)."""
        with self._lock:
            if not self._open(create=False):
                return {"ok": True, "checked": [], "audit_chain": None}
            checked = []
            for cap in self._registry.list():
                if cap["version"] is None:
                    continue
                row = self._registry.version_row(cap["id"], cap["version"])
                ok, info = loader.verify_version(self._ws, row)
                checked.append({"capability_id": cap["id"], "version": cap["version"], "ok": ok,
                                "error": None if ok else info.get("error"), "tests": info.get("tests")})
            ok_chain, bad, count = self._store.verify_audit_chain()
            return {"ok": all(c["ok"] for c in checked) and ok_chain, "checked": checked,
                    "audit_chain": {"ok": ok_chain, "entries": count, "first_bad_seq": bad}}

    # ------------------------------------------------------------ matching
    def match(self, text):
        """Invocation match of `text` against the registered capabilities
        (or, with no registry, the gap detection for table-unit conversions
        and text tools)."""
        with self._lock:
            records = self._records() if self._open(create=False) else []
        return matcher.match_invocation(text, records)

    def match_question(self, text):
        with self._lock:
            records = self._records() if self._open(create=False) else []
        return matcher.match_capability_question(text, records)

    def find_capability(self, text):
        with self._lock:
            records = self._records() if self._open(create=False) else []
        return matcher.find_by_title(text, records)

    # --------------------------------------------------------------- invoke
    def _load_active(self, capability_id):
        row = self._registry.active_version_row(capability_id)
        if row is None:
            return None, None, None
        key = (capability_id, row["version"], row["module_sha256"])
        loaded = self._modules.get(key)
        if loaded is not None:
            # what runs must be what is registered: re-check the file's hash on every call
            try:
                current = sandbox.sha256_bytes(self._ws.read(policy.SUBDIR_MODULES, row["module_file"],
                                                             policy.MAX_SOURCE_BYTES))
            except (OSError, SelfBuilderError):
                current = None
            if current == row["module_sha256"]:
                return loaded, row, None
            self._modules.pop(key, None)
        ok, info = loader.verify_version(self._ws, row, run_tests=True)
        if ok:
            loaded = sandbox.load_module(self._ws.root, policy.SUBDIR_MODULES, row["module_file"],
                                         row["spec"]["kind"], capability_id, row["version"],
                                         expected_sha256=row["module_sha256"])
            self._modules[key] = loaded
            return loaded, row, None
        # the active version is not trustworthy any more: repair, then use what was restored
        repaired = self._builder.repair_integrity(capability_id, info.get("error"))
        self._after_state_change(capability_id, repaired)
        fallback = {"broken_version": row["version"], "error": info.get("error"),
                    "restored_version": repaired.get("version") if repaired.get("status") == ST_APPLIED
                    and repaired.get("action") == "rollback" else None,
                    "disabled": repaired.get("action") == "disable"}
        row2 = self._registry.active_version_row(capability_id)
        if row2 is None:
            return None, None, fallback
        try:
            loaded = sandbox.load_module(self._ws.root, policy.SUBDIR_MODULES, row2["module_file"],
                                         row2["spec"]["kind"], capability_id, row2["version"],
                                         expected_sha256=row2["module_sha256"])
        except SelfBuilderError:
            return None, None, fallback
        self._modules[(capability_id, row2["version"], row2["module_sha256"])] = loaded
        return loaded, row2, fallback

    def invoke(self, capability_id, inputs):
        """Run the ACTIVE version of a capability. Never raises."""
        with self._lock:
            if not self._open(create=False):
                return {"ok": False, "error": "no_registry", "capability_id": capability_id}
            try:
                loaded, row, fallback = self._load_active(capability_id)
            except SelfBuilderError as e:
                return {"ok": False, "error": e.code, "capability_id": capability_id}
            if loaded is None:
                return {"ok": False, "error": "not_active", "capability_id": capability_id, "fallback": fallback}
            out = loaded.run(inputs)
            try:
                self._registry.record_usage(capability_id, row["version"], out["ok"])
            except sqlite3.Error:
                pass
            result = dict(out)
            result.update(capability_id=capability_id, version=row["version"], kind=row["spec"]["kind"],
                          title=row["spec"]["title"], fallback=fallback)
            return result

    # -------------------------------------------------------------- feedback
    def feedback(self, capability_id, version, polarity, text=None):
        """Record the user's verdict on a capability version ("positive" |
        "negative"). Never creates the registry; False when it cannot be stored."""
        if polarity not in ("positive", "negative"):
            return False
        with self._lock:
            if not self._open(create=False):
                return False
            try:
                self._registry.record_feedback(capability_id, version, polarity, text)
                return True
            except sqlite3.Error:
                return False

    def feedback_summary(self, capability_id, version):
        with self._lock:
            if not self._open(create=False):
                return {}
            return self._registry.feedback_summary(capability_id, version)

    # ---------------------------------------------------------------- change
    def _after_state_change(self, capability_id, result):
        self._records_cache = None
        for key in [k for k in self._modules if k[0] == capability_id]:
            self._modules.pop(key, None)
        memory = self._memory()
        if memory is None or self._registry is None:
            return
        try:
            record = self._registry.get(capability_id) if capability_id else None
            if record is not None:
                if result.get("action") in ("rollback", "disable", "repair") or result.get("broken_version"):
                    mirror.mirror_rollback(memory, record, result)
                result["mirror"] = dict(result.get("mirror") or {}, capability_row=capability_id)
        except Exception as e:  # the mirror never blocks or undoes the real change
            result["mirror"] = {"error": type(e).__name__}

    def build(self, text, request, confirmed=False, upgrade_name=None):
        """Run a READY build request. Creates the registry on first use."""
        with self._lock:
            if not self._open(create=True):
                err = self.open_error or {"code": "E_STORE_OPEN", "detail": "registry unavailable"}
                return _failure(err["code"], err["detail"])
            result = self._builder.build(text, request, confirmed=confirmed)
            cid = result.get("capability_id")
            self._records_cache = None
            if cid:
                for key in [k for k in self._modules if k[0] == cid]:
                    self._modules.pop(key, None)
            memory = self._memory()
            if memory is not None:
                try:
                    record = self._registry.get(cid) if cid else None
                    if record is not None and result["status"] in (ST_APPLIED, "noop_identical"):
                        mirror.mirror_capability(memory, record)
                    upgrade, version = mirror.mirror_upgrade(
                        memory, upgrade_name or cid or "self_builder", text, result, record)
                    result["mirror"] = {"upgrade_id": upgrade["id"], "version_id": version["id"] if version else None,
                                        "capability_row": cid if record is not None else None}
                except Exception as e:
                    result["mirror"] = {"error": type(e).__name__}
            return result

    def rollback(self, capability_id, to_version=None, reason="user_request"):
        with self._lock:
            if not self._open(create=False):
                return _failure("E_ROLLBACK_NO_REGISTRY", "there is no registry")
            result = self._builder.rollback(capability_id, to_version=to_version, reason=reason)
            if result["status"] == ST_APPLIED:
                result.setdefault("action", "rollback")
                self._after_state_change(capability_id, result)
            return result

    def disable(self, capability_id, reason="user_request"):
        with self._lock:
            if not self._open(create=False):
                return _failure("E_DISABLE_NO_REGISTRY", "there is no registry")
            result = self._builder.disable(capability_id, reason=reason)
            if result["status"] == ST_APPLIED:
                self._after_state_change(capability_id, result)
            return result


__all__ = ["SelfBuilderService", "get_service", "default_root", "ROOT_DIRNAME"]
