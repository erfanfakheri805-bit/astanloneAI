"""
brain_hub.builtin_tools - the hub's three tool families: the web, local models and Android features
===========================================================================================
`ToolsMixin` is mixed into `HubService`. Each method is a thin, permission-aware, audited wrapper around a package
that already has its own tests (`net_tools`, `model_runtime`, `android_adapters`), so the rules live in ONE place:

* the web: `fetch()` always goes through the user-controlled `network` gate and `net_tools.fetch_text`; the audit
  line keeps the host and path only (never the query string or fragment, which may hold tokens);
* models: nothing is downloaded without `approved is True` AND the network permission; a model file is "usable" only
  after the manager's hash / compatibility / load / smoke-test pipeline passed; a file to import must sit in the hub's
  own `inbox/` folder (a plain file name, never a path);
* Android: permission dialogs are requested only on explicit approval and only for a feature that has an implemented
  action; the answer is observed later, never assumed.

No method here raises for a user-level or I/O problem: failures come back as results with a stable code.
"""

import os
import re
import shutil

from android_adapters import AndroidAdapterLayer, UnknownFeatureError, detect_bridge
from model_runtime import ModelManager, default_runtimes
from model_runtime.manager import GenerationResult, ModelStatus, default_downloader
from net_tools import FetchPolicy, fetch_text, network_status
from net_tools.policy import ParsedUrl, parse_url

__all__ = ["ToolsMixin", "INBOX_DIR", "safe_url_for_log"]

INBOX_DIR = "inbox"
_FILE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
_UNEXPECTED = ("خطای غیرمنتظره‌ای رخ داد؛ چیزی تغییر نکرد.", "An unexpected error happened; nothing was changed.")


def safe_url_for_log(url, policy=None):
    """scheme://host/path (at most 80 chars of path) - no query, no fragment, no credentials; '' when unparsable."""
    try:
        parsed = parse_url(url, policy or FetchPolicy())
    except Exception:
        return ""
    if not isinstance(parsed, ParsedUrl):
        return ""
    path = (parsed.path_query or "/").split("?", 1)[0][:80]
    return "%s://%s%s" % (parsed.scheme, parsed.host, path)


def _model_failure(model_id, code="unexpected_error"):
    return ModelStatus(str(model_id)[:64], "unregistered", False, code, "", (), False, _UNEXPECTED[0], _UNEXPECTED[1])


class ToolsMixin:
    # ================================================================= network
    def network_status(self):
        """What the device itself says about connectivity (never a guess): online / offline / unknown."""
        layer = self._android_layer()
        return network_status(layer.network_probe, self.clock)

    def fetch(self, url, *, source="user"):
        """Read one web page as text through the permission gate. Always returns a `FetchResult` (never raises)."""
        result = fetch_text(url, gate=self.permissions.gate(), policy=self._policy, transport=self._transport)
        self.audit.append("web.fetch", safe_url_for_log(url, self._policy),
                          {"ok": result.ok, "code": result.code, "bytes": result.bytes_read, "source": source,
                           "status": result.status})
        if result.ok:
            self.note_served("tool.web_fetch")
        return result

    # ================================================================= models
    def _model_audit(self, kind, subject, detail):
        self.audit.append("model.%s" % str(kind)[:30], subject, detail)

    def _model_manager(self):
        with self._lock:
            if self._models is None:
                gate = self.permissions.gate()
                downloader = self._model_downloader or default_downloader(gate, self._policy, self._download_transport)
                self._models = ModelManager(os.path.join(self.root, "models"), runtimes=self._model_runtimes,
                                            downloader=downloader, gate=gate, audit=self._model_audit, clock=self.clock,
                                            free_space_fn=self._free_space_fn or shutil.disk_usage)
            return self._models

    def inbox_dir(self, create=False):
        path = os.path.join(self.root, INBOX_DIR)
        if create:
            try:
                os.makedirs(path, exist_ok=True)
            except OSError:
                pass
        return path

    def has_models(self):
        return os.path.isfile(os.path.join(self.root, "models", "registry.json"))

    def list_models(self):
        if not self.has_models():
            return []
        try:
            return list(self._model_manager().list_models())
        except Exception:
            return []

    def model_status(self, model_id):
        try:
            return self._model_manager().status(model_id)
        except Exception:
            return _model_failure(model_id)

    def register_model(self, card, *, license_ack=False):
        try:
            return self._model_manager().register(card, origin="user", license_ack=license_ack is True)
        except Exception:
            return _model_failure((card or {}).get("model_id", "") if isinstance(card, dict) else "")

    def acknowledge_model_license(self, model_id):
        try:
            return self._model_manager().acknowledge_license(model_id)
        except Exception:
            return _model_failure(model_id)

    def download_model(self, model_id, *, approved=False):
        """Download needs `approved is True` (checked again by the manager) and the network permission."""
        try:
            return self._model_manager().download(model_id, approved=approved is True)
        except Exception:
            return _model_failure(model_id)

    def import_model(self, model_id, file_name):
        """Import a file that the user placed in the hub's inbox folder (a plain file name only)."""
        if not isinstance(file_name, str) or not _FILE_NAME_RE.match(file_name):
            return ModelStatus(str(model_id)[:64], "unregistered", False, "bad_arguments", "", (), False,
                               "نام فایل باید فقط یک نام ساده باشد (بدون مسیر).", "The file name must be a plain name (no path).")
        path = os.path.join(self.inbox_dir(), file_name)
        if os.path.islink(path) or not os.path.isfile(path):
            return ModelStatus(str(model_id)[:64], "unregistered", False, "file_missing", "", (), False,
                               "فایل در پوشهٔ ورودی (inbox) پیدا نشد.", "The file was not found in the inbox folder.")
        try:
            return self._model_manager().import_local_file(model_id, path)
        except Exception:
            return _model_failure(model_id)

    def prepare_model(self, model_id):
        """Run the whole pipeline (verify -> compatibility -> load -> real smoke test). Returns a `PipelineReport`."""
        return self._model_manager().prepare(model_id)

    def remove_model(self, model_id):
        try:
            return self._model_manager().remove(model_id)
        except Exception:
            return _model_failure(model_id)

    def ask_model(self, model_id, prompt, *, max_tokens=64):
        """Generate with a USABLE model only. A statistical n-gram model is not an LLM and only continues text."""
        try:
            return self._model_manager().generate(model_id, prompt, max_tokens=max_tokens)
        except Exception:
            return GenerationResult(False, "unexpected_error", "", str(model_id)[:64], "", _UNEXPECTED[0], _UNEXPECTED[1])

    def model_runtimes_info(self):
        """Which inference engines this build can really run: one row per engine, with its exact availability."""
        out = []
        try:
            runtimes = self._model_runtimes if self._model_runtimes is not None else default_runtimes()
            for runtime in runtimes:
                avail = runtime.availability()
                out.append({"name": runtime.name, "formats": list(runtime.formats), "available": bool(avail.available),
                            "code": str(avail.code)[:60], "reason_fa": str(avail.reason_fa)[:200],
                            "reason_en": str(avail.reason_en)[:200], "requires": list(avail.requires)[:5],
                            "description_fa": runtime.description_fa, "description_en": runtime.description_en})
        except Exception:
            return []
        return out

    # ================================================================= Android
    def _android_layer(self):
        with self._lock:
            if self._android is None:
                self._android = AndroidAdapterLayer(self._bridge if self._bridge is not None else detect_bridge())
            return self._android

    def android_statuses(self):
        try:
            return list(self._android_layer().all_statuses())
        except Exception:
            return []

    def android_status(self, feature_id):
        try:
            return self._android_layer().status(feature_id)
        except UnknownFeatureError:
            return None

    def android_request_permission(self, feature_id, *, user_approved=False):
        """Ask Android to show its permission dialog (only with `user_approved is True`; see android_adapters)."""
        try:
            result = self._android_layer().request_permission(feature_id, user_approved=user_approved is True)
        except UnknownFeatureError:
            return None
        self.audit.append("android.permission_request", str(feature_id)[:40],
                          {"dispatched": result.dispatched, "code": result.code, "approved": user_approved is True})
        return result
