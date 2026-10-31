"""
pack_system.store - the packs on disk: state file, installed versions, proposals
================================================================================
Layout under `<files dir>/packs/`:

    state.json                          which version of which pack is active, boot bookkeeping (written atomically)
    audit.jsonl                         hash-chained history (brain_hub.audit.HubAudit)
    store/<id>/<version>/manifest.json  the canonical manifest WITHOUT source texts (+ the file hashes)
    store/<id>/<version>/files/...      the files exactly as installed (made read-only)
    proposals/<qid>.json                a validated, scanned package waiting for the user's yes (expires after a day)
    staging/                            temp folders; swept at start
    data/<id>/                          the pack's own writable folder (settings, caches, downloaded results)

Nothing is created until something is written. A damaged `state.json` is set aside (`.corrupt.N`) and the app starts
with an empty state - installed files stay on disk and can be re-adopted by installing the pack again.
"""

import json
import os
import re
import threading
import time

from . import limits
from .errors import PackError
from .fsutil import (make_readonly, read_json_bounded, remove_tree, set_aside, sha256_text, write_json_atomic,
                     write_text_atomic)

STATE_SCHEMA = 1
_MAX_STATE_BYTES = 2_000_000


def default_state():
    return {"schema": STATE_SCHEMA, "packs": {}, "last_good": {},
            "boot": {"pending": None, "crashes": 0, "safe_level": 0, "safe_reason": "", "last_good_ts": None},
            "restart_needed": []}


def _valid_state(obj):
    if not isinstance(obj, dict) or obj.get("schema") != STATE_SCHEMA:
        return False
    if not isinstance(obj.get("packs"), dict) or not isinstance(obj.get("last_good"), dict) or not isinstance(obj.get("boot"), dict):
        return False
    for pid, rec in obj["packs"].items():
        if not isinstance(pid, str) or not limits.ID_RE.match(pid) or not isinstance(rec, dict):
            return False
        if rec.get("kind") not in limits.SCHEMAS or not isinstance(rec.get("versions"), dict):
            return False
        active = rec.get("active")
        if active is not None and str(active) not in rec["versions"]:
            return False
    return True


class PackStore:
    def __init__(self, root, clock=time.time):
        self.root = os.path.abspath(os.fspath(root))
        self.clock = clock
        self._lock = threading.RLock()
        self._state = None
        self.recovery = ""

    # ---- paths ----------------------------------------------------------------------------------------------------
    def p(self, *parts):
        return os.path.join(self.root, *parts)

    @property
    def state_path(self):
        return self.p("state.json")

    def version_dir(self, pid, version):
        return self.p("store", pid, str(int(version)))

    def files_dir(self, pid, version):
        return os.path.join(self.version_dir(pid, version), "files")

    def data_dir(self, pid):
        return self.p("data", pid)

    # ---- state ----------------------------------------------------------------------------------------------------
    @property
    def state(self):
        with self._lock:
            if self._state is None:
                self._state = self._load()
            return self._state

    def _load(self):
        try:
            obj = read_json_bounded(self.state_path, _MAX_STATE_BYTES)
        except FileNotFoundError:
            return default_state()
        except (ValueError, OSError):
            obj = None
        if _valid_state(obj):
            obj.setdefault("restart_needed", [])
            for key, value in default_state()["boot"].items():
                obj["boot"].setdefault(key, value)
            return obj
        self.recovery = set_aside(self.state_path) or "unreadable"
        return default_state()

    def save(self):
        with self._lock:
            if self._state is not None:
                write_json_atomic(self.state_path, self._state)

    def reload(self):
        with self._lock:
            self._state = None
            return self.state

    # ---- reading --------------------------------------------------------------------------------------------------
    def pack(self, pid):
        return self.state["packs"].get(pid)

    def read_manifest(self, pid, version):
        """The stored canonical manifest (without file texts), or None."""
        try:
            m = read_json_bounded(os.path.join(self.version_dir(pid, version), "manifest.json"), 3_000_000)
        except (OSError, ValueError):
            return None
        return m if isinstance(m, dict) and m.get("id") == pid else None

    def read_file(self, pid, version, rel):
        path = os.path.join(self.files_dir(pid, version), *rel.split("/"))
        if os.path.islink(path) or not os.path.isfile(path):
            raise FileNotFoundError(rel)
        with open(path, "rb") as handle:
            return handle.read(limits.MAX_FILE_BYTES + 1).decode("utf-8")

    def verify(self, pid, version):
        """(True, '') when every file of the installed version matches its recorded hash, else (False, reason)."""
        m = self.read_manifest(pid, version)
        if m is None:
            return False, "manifest_missing"
        if m.get("schema") == limits.LANG_SCHEMA:
            data = self._lang_data(pid, version)
            return (True, "") if data is not None and sha256_text(json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"))) == m.get("data_sha256") else (False, "data_changed")
        hashes = m.get("file_hashes")
        if not isinstance(hashes, dict) or not hashes:
            return False, "hashes_missing"
        for rel, expected in hashes.items():
            try:
                text = self.read_file(pid, version, rel)
            except (OSError, UnicodeDecodeError):
                return False, "file_missing:%s" % rel[:40]
            if sha256_text(text) != expected:
                return False, "file_changed:%s" % rel[:40]
        return True, ""

    def _lang_data(self, pid, version):
        try:
            data = read_json_bounded(os.path.join(self.version_dir(pid, version), "data.json"), limits.MAX_LANG_BYTES * 2)
        except (OSError, ValueError):
            return None
        return data if isinstance(data, list) else None

    def lang_entries(self, pid, version):
        data = self._lang_data(pid, version)
        return data or []

    # ---- installing -------------------------------------------------------------------------------------------------
    def install(self, manifest, origin="chat"):
        """Write one validated manifest as an installed (not yet active) version. Returns 'installed' or 'exists'."""
        pid, version = manifest["id"], manifest["version"]
        with self._lock:
            target = self.version_dir(pid, version)
            if os.path.isdir(target):
                old = self.read_manifest(pid, version)
                if old is not None and old.get("fingerprint") == manifest["fingerprint"]:
                    self._record_version(manifest, origin)
                    return "exists"
                raise PackError("E_PACK_VERSION_EXISTS", "نسخهٔ %d از «%s» از قبل با محتوای دیگری نصب شده است؛ شمارهٔ نسخه را بالا ببر." % (version, pid))
            staging = self.p("staging", "%s-%d-%s" % (pid, version, os.urandom(4).hex()))
            try:
                os.makedirs(staging)
                if manifest["schema"] == limits.CODE_SCHEMA:
                    for rel, text in manifest["files"].items():
                        write_text_atomic(os.path.join(staging, "files", *rel.split("/")), text)
                    stored = {k: v for k, v in manifest.items() if k != "files"}
                    stored["files"] = sorted(manifest["files"])
                else:
                    data = manifest["qa"]
                    write_text_atomic(os.path.join(staging, "data.json"), json.dumps(data, ensure_ascii=False, sort_keys=True))
                    stored = {k: v for k, v in manifest.items() if k != "qa"}
                    stored["qa_count"] = len(data)
                    stored["data_sha256"] = sha256_text(json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":")))
                write_text_atomic(os.path.join(staging, "manifest.json"), json.dumps(stored, ensure_ascii=False, sort_keys=True, indent=1) + "\n")
                make_readonly(staging)
                os.makedirs(os.path.dirname(target), exist_ok=True)
                os.replace(staging, target)
            except BaseException:
                remove_tree(staging)
                raise
            self._record_version(manifest, origin)
            self.save()
            return "installed"

    def _record_version(self, manifest, origin):
        pid, version = manifest["id"], manifest["version"]
        rec = self.state["packs"].setdefault(pid, {"kind": manifest["schema"], "title": manifest["title"], "active": None,
                                                    "enabled": True, "quarantined": None, "failures": 0, "versions": {}})
        rec["kind"], rec["title"] = manifest["schema"], manifest["title"]
        rec["versions"][str(version)] = {
            "fingerprint": manifest["fingerprint"], "installed": round(float(self.clock()), 3), "origin": str(origin)[:20],
            "bytes": manifest.get("total_bytes", 0), "permissions": list(manifest.get("permissions") or ()),
            "replaces": list(manifest.get("replaces") or ()), "risky": bool(manifest.get("risky")),
            "description": manifest.get("description", "")[:200], "title": manifest["title"]}

    def prune(self, pid):
        """Keep only the newest KEEP_VERSIONS versions (never the active or last-good one)."""
        with self._lock:
            rec = self.pack(pid)
            if rec is None:
                return []
            keep = {str(rec["active"])} if rec.get("active") is not None else set()
            if self.state["last_good"].get(pid) is not None:
                keep.add(str(self.state["last_good"][pid]))
            ordered = sorted(rec["versions"], key=int, reverse=True)
            removed = []
            for ver in ordered[limits.KEEP_VERSIONS:]:
                if ver in keep:
                    continue
                if remove_tree(self.version_dir(pid, ver)):
                    rec["versions"].pop(ver, None)
                    removed.append(int(ver))
            if removed:
                self.save()
            return removed

    def remove_pack(self, pid):
        with self._lock:
            self.state["packs"].pop(pid, None)
            self.state["last_good"].pop(pid, None)
            self.state["restart_needed"] = [p for p in self.state["restart_needed"] if p != pid]
            ok = remove_tree(self.p("store", pid))
            self.save()
            return ok

    # ---- proposals -------------------------------------------------------------------------------------------------
    def save_proposal(self, manifest, origin, extra):
        qid = "q" + os.urandom(6).hex()
        record = {"proposal_id": qid, "ts": round(float(self.clock()), 3), "origin": str(origin)[:20], "manifest": manifest,
                  "extra": extra}
        write_text_atomic(self.p("proposals", qid + ".json"), json.dumps(record, ensure_ascii=False, sort_keys=True))
        return qid

    def load_proposal(self, qid):
        if not isinstance(qid, str) or not limits.PROPOSAL_RE.match(qid):
            return None
        try:
            rec = read_json_bounded(self.p("proposals", qid + ".json"), 3_000_000)
        except (OSError, ValueError):
            return None
        if not isinstance(rec, dict) or rec.get("proposal_id") != qid or not isinstance(rec.get("manifest"), dict):
            return None
        if self.clock() - float(rec.get("ts") or 0) > limits.PROPOSAL_TTL_SECONDS:
            self.delete_proposal(qid)
            return None
        return rec

    def delete_proposal(self, qid):
        if isinstance(qid, str) and limits.PROPOSAL_RE.match(qid):
            try:
                os.unlink(self.p("proposals", qid + ".json"))
            except OSError:
                pass

    def pending_proposals(self):
        out = []
        directory = self.p("proposals")
        try:
            names = sorted(os.listdir(directory))
        except OSError:
            return out
        for name in names:
            m = re.match(r"^(q[0-9a-f]{8,24})\.json$", name)
            if m:
                rec = self.load_proposal(m.group(1))
                if rec is not None:
                    out.append(rec)
        return out

    def trim_proposals(self):
        """Keep the newest MAX_PENDING_PROPOSALS proposals (older ones are deleted)."""
        rows = sorted(self.pending_proposals(), key=lambda r: r["ts"], reverse=True)
        for rec in rows[limits.MAX_PENDING_PROPOSALS:]:
            self.delete_proposal(rec["proposal_id"])

    def sweep(self):
        """Remove half-written staging folders (a crash in the middle of an install)."""
        directory = self.p("staging")
        try:
            names = os.listdir(directory)
        except OSError:
            return 0
        count = 0
        for name in names:
            if remove_tree(os.path.join(directory, name)):
                count += 1
        return count


__all__ = ["PackStore", "default_state", "STATE_SCHEMA"]
