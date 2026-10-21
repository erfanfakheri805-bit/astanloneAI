"""
brain_hub.service - the ONE service the conversation talks to
==============================================================
`HubService` owns, under `<data dir>/brain_hub/`:

    permissions.json     what the user allowed (permissions.py)
    hub_audit.jsonl      hub-level, hash-chained history (audit.py)
    extensions/          the extension manager's database and versioned private files (ext_runtime)
    models/              the model manager's registry and verified model files (model_runtime)
    inbox/               where the user may put a model file to import (a plain file name is all that is accepted)

Nothing is created until something needs to be written: constructing a service, listing, matching or building the
graph on a fresh install touches no disk. On the first use after a start `ensure_started()` runs the recovery the
managers provide (sweep partial writes, re-verify active versions with fallback to an older healthy one, expire old
proposals, check the audit chains), once per process.

Every state-changing call that the user must decide takes `user_approved=...` and refuses unless it is exactly
`True`; the chat layer passes True only after an explicit yes. Methods never raise for user-level or I/O problems.
"""

import os
import threading
import time
import weakref

from net_tools import FetchPolicy

from ext_runtime import hubstore
from ext_runtime.lifecycle import ExtensionManager

from .atomic import set_aside
from .audit import FILE_NAME as AUDIT_FILE, HubAudit
from .permissions import PermissionStore
from .builtin_tools import ToolsMixin

__all__ = ["HubService", "get_hub", "set_hub", "reset_hub", "default_root", "ROOT_DIRNAME", "EXT_DIRNAME"]

ROOT_DIRNAME = "brain_hub"
EXT_DIRNAME = "extensions"
_HUBS = weakref.WeakKeyDictionary()
_HUBS_LOCK = threading.Lock()


def default_root(memory):
    """Where this app's hub lives (nothing is created); None when the memory has no database path."""
    db_path = getattr(memory, "db_path", None)
    if not db_path:
        return None
    return os.path.join(os.path.dirname(os.path.abspath(db_path)), ROOT_DIRNAME)


def _hold(obj):
    if obj is None:
        return lambda: None
    try:
        return weakref.ref(obj)
    except TypeError:                              # not weak-referenceable (a plain dict, say): keep it
        return lambda: obj


def _summary(report):
    """A small, plain-data digest of a manager's recovery report (lists become counts)."""
    if not isinstance(report, dict):
        return report
    return {k: (len(v) if isinstance(v, (list, tuple, set)) else v) for k, v in report.items() if not isinstance(v, dict)}


def _io_error(code="E_HUB_IO"):
    return {"status": "error", "code": code,
            "message_fa": "خواندن یا نوشتن در حافظهٔ برنامه ناموفق بود؛ چیزی تغییر نکرد.",
            "message_en": "Reading or writing the app's storage failed; nothing was changed."}


def _store_unusable(detail=""):
    return {"status": "error", "code": "E_HUB_EXT_STORE", "detail": str(detail)[:80],
            "message_fa": "حافظهٔ افزونه‌ها خراب یا ناخوانا است؛ چیزی نصب یا تغییر نکرد. با «ترمیم حافظهٔ افزونه‌ها» می‌توانی آن را کنار بگذاری و از نو شروع کنی (فایل قدیمی پاک نمی‌شود).",
            "message_en": "The extension store is damaged or unreadable; nothing was installed or changed. 'repair the extension store' sets it aside (the old files are kept) so you can start fresh."}


class HubService(ToolsMixin):
    def __init__(self, root, *, memory=None, clock=time.time, transport=None, download_transport=None, fetch_policy=None,
                 model_runtimes=None, model_downloader=None, free_space_fn=None, bridge=None):
        if not isinstance(root, (str, os.PathLike)) or not str(root):
            raise ValueError("root must be a path")
        self.root = os.path.abspath(os.fspath(root))
        self._memory_ref = _hold(memory)          # a weak reference: the registry below must not keep a MemorySystem alive
        self.clock = clock
        self._lock = threading.RLock()
        self.permissions = PermissionStore(self.root, clock)
        self.audit = HubAudit(os.path.join(self.root, AUDIT_FILE), clock)
        self._policy = fetch_policy if fetch_policy is not None else FetchPolicy()
        self._transport, self._download_transport = transport, download_transport
        self._model_runtimes, self._model_downloader = model_runtimes, model_downloader
        self._free_space_fn, self._bridge = free_space_fn, bridge
        self._ext = None
        self.ext_error = ""
        self._models = None
        self._android = None
        self.startup_report = None
        self._served = {}

    # ================================================================= basics
    @property
    def memory(self):
        """The MemorySystem this hub belongs to (None when it has none, or it no longer exists)."""
        return self._memory_ref()

    def exists(self):
        return os.path.isdir(self.root)

    def note_served(self, node_id):
        """Count a request that was really answered by `node_id` in this process (evidence for the graph)."""
        with self._lock:
            self._served[node_id] = self._served.get(node_id, 0) + 1

    def served_count(self, node_id):
        with self._lock:
            return self._served.get(node_id, 0)

    # ================================================================= start-up recovery
    def ext_root(self):
        return os.path.join(self.root, EXT_DIRNAME)

    def has_extensions(self):
        return os.path.isfile(os.path.join(self.ext_root(), hubstore.HUB_DB))

    def ensure_started(self):
        """Run the recovery once per process, but only when this app has used the hub before (never creates anything)."""
        if self.startup_report is not None or not self.exists():
            return self.startup_report
        return self.startup()

    def startup(self):
        with self._lock:
            if self.startup_report is not None:
                return self.startup_report
            report = {"extensions": None, "models": None, "audit": None, "permissions_recovery": None, "errors": []}
            if self.has_extensions():
                mgr = self._manager()
                if mgr is None:
                    report["errors"].append("extensions:store_unusable")
                else:
                    try:
                        report["extensions"] = _summary(mgr.reconcile())
                    except Exception as exc:
                        report["errors"].append("extensions:%s" % type(exc).__name__)
            if self.has_models():
                try:
                    report["models"] = _summary(self._model_manager().recover())
                except Exception as exc:
                    report["errors"].append("models:%s" % type(exc).__name__)
            self.permissions.is_granted("network")                       # loads (and, if damaged, sets aside) the file
            report["permissions_recovery"] = self.permissions.recovery
            if os.path.exists(self.audit.path):
                report["audit"] = self.audit.verify()
            ext = report["extensions"] or {}
            report["attention"] = bool(report["errors"] or report["permissions_recovery"]
                                       or (report["audit"] and not report["audit"]["ok"])
                                       or any(ext.get(k) for k in ("failed_versions", "fell_back", "disabled", "quarantined")))
            self.startup_report = report
            self.audit.append("hub.started", "", {"attention": report["attention"], "errors": report["errors"]})
            return report

    def close(self):
        with self._lock:
            if self._ext is not None:
                try:
                    self._ext.close()
                except Exception:
                    pass
                self._ext = None

    # ================================================================= extensions
    def _manager(self, create=False):
        """The extension manager, or None when there is none yet or its store cannot be opened (see `ext_error`)."""
        with self._lock:
            if self._ext is None:
                if not create and not self.has_extensions():
                    return None
                try:
                    self._ext = ExtensionManager(self.ext_root(), clock=self.clock, web_fetch=self._ext_web_fetch,
                                                 id_exists=self._id_taken)
                except Exception as exc:                                   # a damaged database is reported, never raised
                    self.ext_error = type(exc).__name__ + (":" + str(getattr(exc, "code", ""))[:30] if getattr(exc, "code", None) else "")
                    return None
                self.ext_error = ""
            return self._ext

    def extension_store_state(self):
        """'absent' (never used) | 'healthy' | 'damaged' (the files exist but the store cannot be opened). Creates nothing."""
        if not self.has_extensions():
            return "absent"
        return "healthy" if self._manager() is not None else "damaged"

    def repair_extension_store(self, *, user_approved=False):
        """Set a DAMAGED extension store aside (renamed to *.corrupt.N, never deleted) so a fresh one can start.

        Needs an explicit yes; a store that opens fine is never touched. Installed extensions are not restored by this:
        their files stay in the set-aside folders for the user (or a support person) to look at."""
        if user_approved is not True:
            return {"status": "approval_required"}
        with self._lock:
            if self._manager() is not None:
                return {"status": "not_damaged", "message_fa": "حافظهٔ افزونه‌ها سالم است؛ چیزی تغییر نکرد.",
                        "message_en": "The extension store is healthy; nothing was changed."}
            if not self.ext_error:                                         # no store at all: nothing is damaged
                return {"status": "nothing_to_repair"}
            moved = []
            for name in ("hub.db", "hub.db-wal", "hub.db-shm", "modules", "manifests"):
                path = os.path.join(self.ext_root(), name)
                if os.path.lexists(path):
                    target = set_aside(path)
                    if not target:
                        self.audit.append("ext.store_repair_failed", name, {"moved": moved})
                        return dict(_io_error(), moved=moved)
                    moved.append(target)
            self.ext_error = ""
            self.audit.append("ext.store_repaired", "", {"moved": moved})
            return {"status": "repaired", "moved": moved,
                    "message_fa": "حافظهٔ خراب کنار گذاشته شد (چیزی پاک نشد). افزونه‌ها را دوباره بفرست تا نصب شوند.",
                    "message_en": "The damaged store was set aside (nothing was deleted). Send the extensions again to install them."}

    def _ext_web_fetch(self, url):
        """The only network door an extension has: the hub's gate, limits and audit, only for extensions granted `network`."""
        result = self.fetch(url, source="extension")
        if not result.ok:
            raise RuntimeError(result.message_fa)
        return result.text

    def _sb(self):
        if self.memory is None:
            return None
        try:
            from self_builder import service as sb_service
            return sb_service.get_service(self.memory)
        except Exception:
            return None

    def _id_taken(self, capability_id):
        sb = self._sb()
        try:
            return sb is not None and sb.capability(capability_id) is not None
        except Exception:
            return False

    def propose_package(self, data, origin="chat"):
        """Validate, compile and test a package; a good one becomes a PENDING proposal (nothing is active yet)."""
        self.ensure_started()
        mgr = self._manager(create=True)
        if mgr is None:
            return _store_unusable(self.ext_error)
        try:
            return mgr.propose(data, origin=origin)
        except OSError:
            return _io_error()
        except Exception as exc:
            return {"status": "error", "code": "E_HUB_INTERNAL", "detail": type(exc).__name__}

    def pending_proposals(self):
        mgr = self._manager()
        try:
            return mgr.pending() if mgr is not None else []
        except Exception:
            return []

    def proposal(self, proposal_id):
        mgr = self._manager()
        try:
            return mgr.proposal(proposal_id) if mgr is not None else None
        except Exception:
            return None

    def approve_proposal(self, proposal_id, *, user_approved=False):
        """Install + activate (verified from disk). Refuses unless the user said yes (`user_approved is True`)."""
        if user_approved is not True:
            return {"status": "approval_required", "proposal_id": str(proposal_id)[:40]}
        mgr = self._manager()
        if mgr is None:
            return {"status": "failed", "code": "E_EXT_NO_PROPOSAL"}
        try:
            return mgr.approve(proposal_id, approver="user")
        except OSError:
            return _io_error()
        except Exception as exc:
            return {"status": "error", "code": "E_HUB_INTERNAL", "detail": type(exc).__name__}

    def decline_proposal(self, proposal_id):
        mgr = self._manager()
        if mgr is None:
            return {"status": "failed", "code": "E_EXT_NO_PROPOSAL"}
        try:
            return mgr.decline(proposal_id)
        except Exception as exc:
            return {"status": "error", "code": "E_HUB_INTERNAL", "detail": type(exc).__name__}

    def extensions(self):
        mgr = self._manager()
        try:
            return mgr.list_capabilities() if mgr is not None else []
        except Exception:
            return []

    def extension(self, capability_id):
        mgr = self._manager()
        try:
            return mgr.get(capability_id) if mgr is not None else None
        except Exception:
            return None

    def find_extension(self, text):
        mgr = self._manager()
        try:
            return mgr.find_capability(text) if mgr is not None else None
        except Exception:
            return None

    def extension_versions(self, capability_id):
        mgr = self._manager()
        try:
            return mgr.versions(capability_id) if mgr is not None else []
        except Exception:
            return []

    def extension_history(self, capability_id=None, limit=15):
        mgr = self._manager()
        try:
            return mgr.history(capability_id, limit) if mgr is not None else []
        except Exception:
            return []

    def match_extension(self, text, include_disabled=False):
        """{"status": none | disabled | needs_inputs | invalid_inputs | invoke, ...} for a chat sentence.
        `disabled` is only ever reported when `include_disabled` is true (a disabled extension is otherwise invisible)."""
        mgr = self._manager()
        if mgr is None:
            return {"status": "none"}
        try:
            return mgr.match(text, include_disabled=bool(include_disabled))
        except Exception:
            return {"status": "none"}

    def invoke_extension(self, capability_id, inputs):
        mgr = self._manager()
        if mgr is None:
            return {"ok": False, "status": "not_found", "capability_id": capability_id}
        try:
            out = mgr.invoke(capability_id, inputs)
        except Exception as exc:
            return {"ok": False, "status": "runtime_error", "capability_id": capability_id,
                    "error": {"detail": type(exc).__name__}}
        if out.get("ok"):
            self.note_served("ext." + str(capability_id))
        return out

    def rollback_extension(self, capability_id, *, to_version=None, user_approved=False):
        if user_approved is not True:
            return {"status": "approval_required", "capability_id": str(capability_id)[:60]}
        mgr = self._manager()
        if mgr is None:
            return {"status": "failed", "code": "E_EXT_NOT_FOUND"}
        try:
            return mgr.rollback(capability_id, to_version=to_version, reason="user request")
        except Exception as exc:
            return {"status": "error", "code": "E_HUB_INTERNAL", "detail": type(exc).__name__}

    def disable_extension(self, capability_id):
        mgr = self._manager()
        if mgr is None:
            return {"status": "failed", "code": "E_EXT_NOT_FOUND"}
        try:
            return mgr.disable(capability_id)
        except Exception as exc:
            return {"status": "error", "code": "E_HUB_INTERNAL", "detail": type(exc).__name__}

    def enable_extension(self, capability_id, *, user_approved=False):
        if user_approved is not True:
            return {"status": "approval_required", "capability_id": str(capability_id)[:60]}
        mgr = self._manager()
        if mgr is None:
            return {"status": "failed", "code": "E_EXT_NOT_FOUND"}
        try:
            return mgr.enable(capability_id)
        except Exception as exc:
            return {"status": "error", "code": "E_HUB_INTERNAL", "detail": type(exc).__name__}

    def grant_extension_permission(self, capability_id, permission, *, user_approved=False):
        if user_approved is not True:
            return {"status": "approval_required", "capability_id": str(capability_id)[:60], "permission": str(permission)[:20]}
        mgr = self._manager()
        if mgr is None:
            return {"status": "failed", "code": "E_EXT_NOT_FOUND"}
        try:
            return mgr.grant(capability_id, permission, by="user")
        except Exception as exc:
            return {"status": "error", "code": "E_HUB_INTERNAL", "detail": type(exc).__name__}

    def revoke_extension_permission(self, capability_id, permission):
        mgr = self._manager()
        if mgr is None:
            return {"status": "failed", "code": "E_EXT_NOT_FOUND"}
        try:
            return mgr.revoke(capability_id, permission, by="user")
        except Exception as exc:
            return {"status": "error", "code": "E_HUB_INTERNAL", "detail": type(exc).__name__}

    # ================================================================= app-level permissions
    def permission_rows(self):
        return self.permissions.describe()

    def grant_permission(self, name, *, user_approved=False):
        change = self.permissions.grant(name, user_approved=user_approved)
        self.audit.append("permission.grant", name, {"ok": change.ok, "code": change.code})
        return change

    def revoke_permission(self, name):
        change = self.permissions.revoke(name)
        self.audit.append("permission.revoke", name, {"ok": change.ok, "code": change.code})
        return change

    # ================================================================= graph / invoker / overview
    def graph(self):
        from .invoker import build_graph
        return build_graph(self)

    def execute(self, node_id, action, params=None, *, user_approved=False):
        from .invoker import execute
        return execute(self, node_id, action, params, user_approved=user_approved)

    def status(self):
        """Plain-data state of the hub for the `status` command (reads only)."""
        info = {"root": self.root, "exists": self.exists(), "extensions": 0, "pending_proposals": 0, "models": 0,
                "permissions": self.permission_rows(), "startup": self.startup_report}
        if self.has_extensions():
            caps = self.extensions()
            info["extensions"] = len(caps)
            info["extensions_active"] = sum(1 for c in caps if c.get("state") == "active")
            info["pending_proposals"] = len(self.pending_proposals())
            mgr = self._manager()
            info["extension_store_error"] = self.ext_error
            try:
                info["extension_store"] = mgr.status() if mgr is not None else None
            except Exception:
                info["extension_store"] = None
        info["models"] = len(self.list_models())
        info["audit"] = self.audit.verify() if os.path.exists(self.audit.path) else None
        return info


# ----------------------------------------------------------------------- module API
def get_hub(memory):
    """The hub of a MemorySystem's data directory (nothing is created on disk); None without a database path."""
    root = default_root(memory)
    if root is None:
        return None
    with _HUBS_LOCK:
        hub = _HUBS.get(memory)
        if hub is None or hub.root != os.path.abspath(root):
            hub = HubService(root, memory=memory)
            _HUBS[memory] = hub
        return hub


def set_hub(memory, hub):
    """Use `hub` for this MemorySystem (embedding code and tests that inject fakes)."""
    with _HUBS_LOCK:
        _HUBS[memory] = hub


def reset_hub(memory):
    with _HUBS_LOCK:
        hub = _HUBS.pop(memory, None)
    if hub is not None:
        hub.close()
