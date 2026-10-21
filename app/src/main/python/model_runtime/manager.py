"""
model_runtime.manager - the honest model lifecycle
==================================================
States: registered -> downloading -> downloaded -> verified -> compatible -> usable (+ failed).

A model becomes `usable` ONLY when every earlier stage really passed:
size + SHA-256 equal the card -> licence policy and a runtime for the format
are available -> a runtime REALLY loaded the file -> a REAL inference smoke
test ran. "Blocked" is not a state; it is the `reasons` list of a status (for
example `dependency_missing` or `license_needs_ack`).

Rules the code enforces (and the tests prove):
* downloads need `approved is True`, the network permission and a licence the
  policy accepts, and go through an injected downloader that must verify the
  hash; a failed or interrupted download leaves no partial file;
* a hash/size mismatch moves the file to `.rejected/` and it is never loaded;
* after a restart a persisted `usable` is trusted only if the file's size and
  mtime are unchanged (checked by `status()`, `list_models()` and `generate()`),
  and `generate()` re-runs the smoke test once per process;
* `generate()` refuses unless the model is `usable`; nothing is ever fabricated.
Every transition is written to the registry atomically and reported to the
optional `audit(kind, subject, detail)` callback.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from .card import CardError, ModelCard, LOCAL_IMPORT, license_policy, parse_card
from .runtimes import (InferenceRuntime, LoadedModel, RuntimeGenerateError, RuntimeLoadError, default_runtimes)
from .store import STATES, ModelStore, validate_entry

__all__ = ["ModelManager", "ModelStatus", "GenerationResult", "StageReport", "PipelineReport", "TRANSITIONS",
           "transition_allowed", "default_downloader"]

TRANSITIONS: Dict[str, frozenset] = {
    "registered": frozenset({"registered", "downloading", "downloaded", "failed"}),
    "downloading": frozenset({"downloaded", "failed", "registered"}),
    "downloaded": frozenset({"downloaded", "verified", "failed", "registered"}),
    "verified": frozenset({"verified", "compatible", "failed", "downloaded", "registered"}),
    "compatible": frozenset({"compatible", "usable", "failed", "verified", "downloaded", "registered"}),
    "usable": frozenset({"usable", "failed", "verified", "downloaded", "registered"}),
    "failed": frozenset({"registered", "downloading", "downloaded"}),
}
_COPY_CHUNK = 1 << 20
_MAX_PROMPT_CHARS = 8000
_MIB = 1024 * 1024

_STATE_TEXT = {
    "registered": ("ثبت شده؛ هنوز فایلی دریافت نشده است.", "Registered; no file has been obtained yet."),
    "downloading": ("در حال دانلود.", "Downloading."),
    "downloaded": ("فایل موجود است ولی هنوز صحت آن تأیید نشده.", "The file is present but not verified yet."),
    "verified": ("صحت فایل (اندازه و SHA-256) تأیید شد؛ هنوز سازگاری، بارگذاری و آزمون استنتاج انجام نشده.",
                 "File integrity (size and SHA-256) is verified; compatibility, loading and the inference test are still pending."),
    "compatible": ("سازگار است؛ هنوز بارگذاری و آزمون استنتاج واقعی انجام نشده.", "Compatible; loading and the real inference test are pending."),
    "usable": ("بارگذاری شد و آزمون استنتاج واقعی را گذراند؛ قابل استفاده است.", "Loaded and passed a real inference test; usable."),
    "failed": ("ناموفق بود؛ قابل استفاده نیست.", "Failed; not usable."),
}
_CODE_TEXT = {
    "invalid_card": ("کارت مدل معتبر نیست.", "The model card is not valid."),
    "unknown_model": ("چنین مدلی ثبت نشده است.", "No such model is registered."),
    "model_id_taken": ("مدلی با همین شناسه و مشخصات متفاوت از قبل ثبت شده است.", "A different model with this id is already registered."),
    "approval_required": ("برای این کار باید خودت صریحاً تأیید کنی.", "This needs your explicit approval."),
    "permission_denied": ("اجازهٔ دسترسی به اینترنت داده نشده است.", "Internet access has not been granted."),
    "license_needs_ack": ("مجوز این مدل نیاز به بازبینی و تأیید صریح تو دارد.", "This model's licence needs your explicit review and acknowledgement."),
    "license_restricted": ("مجوز این مدل استفادهٔ عادی را محدود می‌کند و رد شد.", "This model's licence is restricted and was refused."),
    "license_unknown": ("مجوز این مدل ناشناخته است و رد شد.", "This model's licence is unknown and was refused."),
    "insufficient_space": ("فضای خالی کافی نیست.", "There is not enough free space."),
    "needs_local_file": ("این مدل آدرس اینترنتی ندارد؛ فایل آن را باید خودت وارد کنی.", "This model has no download address; import its file yourself."),
    "illegal_state": ("در وضعیت فعلی این کار ممکن نیست.", "This is not possible in the model's current state."),
    "size_mismatch": ("اندازهٔ فایل با کارت نمی‌خواند و رد شد.", "The file size does not match the card; it was rejected."),
    "hash_mismatch": ("SHA-256 فایل با کارت نمی‌خواند؛ فایل کنار گذاشته شد و هرگز بارگذاری نمی‌شود.",
                      "The file's SHA-256 does not match the card; it was set aside and will never be loaded."),
    "no_runtime_for_format": ("برای این قالب هیچ موتور اجرایی در این برنامه وجود ندارد.", "This app has no engine that can run this format."),
    "dependency_missing": ("موتور لازم روی این دستگاه نصب نیست.", "The required engine is not installed on this device."),
    "runtime_hint_unavailable": ("موتور درخواست‌شده در کارت در دسترس نیست.", "The engine named in the card is not available."),
    "model_file_invalid": ("فایل مدل معتبر نیست.", "The model file is not valid."),
    "model_file_unreadable": ("فایل مدل خوانده نشد.", "The model file could not be read."),
    "engine_load_failed": ("موتور نتوانست مدل را بارگذاری کند.", "The engine could not load the model."),
    "smoke_failed": ("آزمون استنتاج واقعی موفق نبود.", "The real inference test did not pass."),
    "model_not_usable": ("این مدل قابل استفاده نیست؛ باید همهٔ مراحل تأیید را بگذراند.", "This model is not usable; every verification stage has to pass first."),
    "file_changed": ("فایل مدل بعد از تأیید تغییر کرده است؛ باید دوباره تأیید شود.", "The model file changed after verification; it must be verified again."),
    "file_missing": ("فایل مدل پیدا نشد.", "The model file is missing."),
    "interrupted": ("دانلود نیمه‌کاره ماند و دوباره از ابتدا لازم است.", "The download was interrupted and has to start again."),
    "bad_arguments": ("ورودی نامعتبر است.", "The input is not valid."),
    "download_failed": ("دانلود ناموفق بود.", "The download failed."),
    "io_error": ("نوشتن یا خواندن فایل ناموفق بود.", "Reading or writing the file failed."),
    "ok": ("انجام شد.", "Done."),
}


def transition_allowed(old: str, new: str) -> bool:
    return new in TRANSITIONS.get(old, frozenset())


def _text(code: str, state: Optional[str] = None) -> Tuple[str, str]:
    if code in _CODE_TEXT:
        return _CODE_TEXT[code]
    if state in _STATE_TEXT:
        return _STATE_TEXT[state]
    return ("ناموفق بود (%s)." % code, "Failed (%s)." % code)


@dataclass(frozen=True)
class ModelStatus:
    model_id: str
    state: str
    ok: bool
    code: str
    stage: str
    reasons: Tuple[str, ...]
    usable: bool
    message_fa: str
    message_en: str
    card: Optional[dict] = None
    file: Optional[dict] = None
    runtime: str = ""
    license_ack: bool = False          # the user explicitly acknowledged a licence that needs review
    license_policy: str = ""           # permissive | needs_review | restricted | unknown ('' for an unregistered model)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class GenerationResult:
    ok: bool
    code: str
    text: str
    model_id: str
    runtime: str
    message_fa: str
    message_en: str
    elapsed_s: float = 0.0


@dataclass(frozen=True)
class StageReport:
    stage: str
    ok: bool
    code: str


@dataclass(frozen=True)
class PipelineReport:
    model_id: str
    ok: bool
    stages: Tuple[StageReport, ...]
    status: ModelStatus


def default_downloader(gate, policy=None, transport=None) -> Callable:
    """A downloader backed by `net_tools.download_file` (https, permission-gated, hash-verified)."""
    def run(url, dest_root, rel_dest, *, expected_sha256, max_bytes):
        from net_tools import download_file

        return download_file(url, dest_root, rel_dest, gate=gate, expected_sha256=expected_sha256, max_bytes=max_bytes,
                             policy=policy, transport=transport)
    return run


class ModelManager:
    TRANSITIONS = TRANSITIONS

    def __init__(self, root: str, *, runtimes: Optional[Sequence[InferenceRuntime]] = None,
                 downloader: Optional[Callable] = None, gate=None, audit: Optional[Callable[[str, str, dict], None]] = None,
                 clock: Callable[[], float] = time.time, free_space_fn: Callable = shutil.disk_usage) -> None:
        self._store = ModelStore(root)
        self._runtimes: Dict[str, InferenceRuntime] = {}
        for runtime in (runtimes if runtimes is not None else default_runtimes()):
            for fmt in runtime.formats:
                self._runtimes.setdefault(fmt, runtime)
        self._gate, self._audit, self._clock, self._free = gate, audit, clock, free_space_fn
        self._downloader = downloader if downloader is not None else default_downloader(gate)
        self._lock = threading.RLock()
        self._models: Optional[Dict[str, dict]] = None
        self._recovery: Optional[dict] = None
        self._loaded: Dict[str, LoadedModel] = {}
        self._trusted: set = set()

    # ---- plumbing -----------------------------------------------------------

    @property
    def root(self) -> str:
        return self._store.root

    @property
    def registry_recovery(self) -> Optional[dict]:
        """Set when a corrupt registry was found and moved aside (never silently reset)."""
        self._ensure()
        return self._recovery

    def _ensure(self) -> Dict[str, dict]:
        if self._models is None:
            self._models, self._recovery = self._store.load()
            if self._recovery is not None:
                self._note("registry_corrupt", "registry", dict(self._recovery))
        return self._models

    def _note(self, kind: str, subject: str, detail: Optional[dict] = None) -> None:
        if self._audit is not None:
            try:
                self._audit(kind, subject, dict(detail or {}))
            except Exception:
                pass

    def _network_allowed(self) -> bool:
        try:
            return bool(self._gate is not None and self._gate.allowed("network") is True)
        except Exception:
            return False

    def _save(self) -> None:
        try:
            self._store.save(self._ensure())
        except BaseException:
            # memory may now be ahead of the disk: drop it so the next call re-reads the truth (and never reports a
            # state that was not persisted); loaded engines are released because their trust is gone with it
            self._models = None
            self._loaded.clear()
            self._trusted.clear()
            raise

    def _card(self, entry: dict) -> ModelCard:
        return parse_card(entry["card"])

    def _status(self, model_id: str, ok: bool, code: str, *, stage: str = "", reasons: Sequence[str] = ()) -> ModelStatus:
        entry = self._ensure().get(model_id)
        if entry is None:
            fa, en = _text(code if code in _CODE_TEXT else "unknown_model")
            return ModelStatus(model_id, "unregistered", False, code, stage, tuple(reasons), False, fa, en)
        state = entry["state"]
        if code == "ok" or (ok and code not in _CODE_TEXT):
            fa, en = _STATE_TEXT[state]
        else:
            fa, en = _text(code, state)
        card = entry["card"]
        runtime = self._runtimes.get(card["format"])
        return ModelStatus(model_id, state, ok, code, stage or entry.get("stage", ""), tuple(reasons or entry.get("reasons", ())),
                           state == "usable", fa, en, dict(card), dict(entry["file"]) if entry.get("file") else None,
                           runtime.name if runtime else "", bool(entry.get("license_ack")), license_policy(card["license"]))

    def _move(self, model_id: str, new_state: str, *, stage: str = "", reasons: Sequence[str] = ()) -> None:
        entry = self._ensure()[model_id]
        old = entry["state"]
        if not transition_allowed(old, new_state):
            raise ValueError("illegal transition %s -> %s" % (old, new_state))
        if new_state == "usable" and not (entry.get("smoke") or {}).get("ok"):
            raise ValueError("usable requires a passing smoke test")
        entry["state"], entry["stage"], entry["reasons"] = new_state, stage, [str(r)[:80] for r in reasons][:20]
        entry["updated_at"] = float(self._clock())
        validate_entry(model_id, entry)
        self._save()
        self._note("transition", model_id, {"from": old, "to": new_state, "stage": stage, "reasons": list(reasons)})

    def _fail(self, model_id: str, stage: str, code: str) -> ModelStatus:
        entry = self._ensure()[model_id]
        self._loaded.pop(model_id, None)
        self._trusted.discard(model_id)
        if entry["state"] != "failed":
            self._move(model_id, "failed", stage=stage, reasons=[code])
        else:
            entry["stage"], entry["reasons"] = stage, [code]
            self._save()
        return self._status(model_id, False, code, stage=stage, reasons=[code])

    def _refuse(self, model_id: str, code: str, kind: str, reasons: Sequence[str] = ()) -> ModelStatus:
        self._note(kind, model_id, {"code": code})
        return self._status(model_id, False, code, reasons=reasons or [code])

    def _file_path(self, entry: dict) -> str:
        card = self._card(entry)
        return self._store.model_file(card.model_id, card.version)

    def _record_file(self, entry: dict) -> None:
        stat = os.stat(self._file_path(entry))
        card = entry["card"]
        entry["file"] = {"rel": self._store.relative_file(card["model_id"], card["version"]),
                         "size": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns)}

    # ---- registry operations ------------------------------------------------

    def register(self, card_dict: dict, *, origin: str = "user", license_ack: bool = False) -> ModelStatus:
        with self._lock:
            models = self._ensure()
            try:
                card = parse_card(card_dict)
            except CardError as err:
                self._note("register_refused", str(card_dict.get("model_id", "?"))[:64] if isinstance(card_dict, dict) else "?",
                           {"code": err.code, "detail": err.detail})
                fa, en = _text("invalid_card")
                return ModelStatus("", "unregistered", False, "invalid_card", "", (err.code, err.detail), False, fa, en)
            if origin not in ("user", "bundled") or not isinstance(license_ack, bool):
                return ModelStatus(card.model_id, "unregistered", False, "bad_arguments", "", (), False, *_text("bad_arguments"))
            existing = models.get(card.model_id)
            if existing is not None:
                if existing["card"] != card.to_dict():
                    return self._refuse(card.model_id, "model_id_taken", "register_refused")
                if license_ack and not existing["license_ack"]:
                    return self.acknowledge_license(card.model_id)
                return self._status(card.model_id, True, "ok")
            if len(models) >= 200:
                return ModelStatus(card.model_id, "unregistered", False, "bad_arguments", "", ("too_many_models",), False, *_text("bad_arguments"))
            now = float(self._clock())
            models[card.model_id] = {"card": card.to_dict(), "state": "registered", "origin": origin, "license_ack": license_ack,
                                     "reasons": [], "stage": "", "file": None, "smoke": None, "registered_at": now, "updated_at": now}
            self._save()
            self._note("registered", card.model_id, {"origin": origin, "format": card.format, "license": card.license})
            return self._status(card.model_id, True, "ok")

    def acknowledge_license(self, model_id: str) -> ModelStatus:
        """The user's explicit acknowledgement for a licence that needs review (never for restricted/unknown ones)."""
        with self._lock:
            entry = self._ensure().get(model_id)
            if entry is None:
                return self._status(model_id, False, "unknown_model")
            policy = license_policy(entry["card"]["license"])
            if policy != "needs_review":
                return self._refuse(model_id, "illegal_state", "license_ack_refused", [policy])
            entry["license_ack"] = True
            self._save()
            self._note("license_acknowledged", model_id, {"license": entry["card"]["license"]})
            return self._status(model_id, True, "ok")

    def _revalidate(self, model_id: str) -> None:
        """A persisted `usable` that this process has not verified itself is shown only while its file is unchanged
        (size + mtime); a changed or vanished file is demoted right here, so no listing can claim it is usable."""
        entry = self._ensure().get(model_id)
        if entry is None or entry["state"] != "usable" or model_id in self._trusted:
            return
        stale = self._stale(entry)
        if stale:
            entry["file"] = None if stale == "file_missing" else entry["file"]
            self._move(model_id, "downloaded" if stale == "file_changed" else "registered", stage="trust", reasons=[stale])

    def status(self, model_id: str) -> ModelStatus:
        with self._lock:
            self._revalidate(model_id)
            return self._status(model_id, model_id in self._ensure(), "ok" if model_id in self._ensure() else "unknown_model")

    def list_models(self) -> List[ModelStatus]:
        with self._lock:
            for mid in sorted(self._ensure()):
                self._revalidate(mid)
            return [self._status(mid, True, "ok") for mid in sorted(self._ensure())]

    def remove(self, model_id: str) -> ModelStatus:
        with self._lock:
            entry = self._ensure().get(model_id)
            if entry is None:
                return self._status(model_id, False, "unknown_model")
            card = self._card(entry)
            self._loaded.pop(model_id, None)
            self._trusted.discard(model_id)
            directory = self._store.model_dir(card.model_id, card.version)
            shutil.rmtree(directory, ignore_errors=True)
            del self._ensure()[model_id]
            self._save()
            self._note("removed", model_id, {})
            return ModelStatus(model_id, "unregistered", True, "ok", "", (), False, "مدل حذف شد.", "The model was removed.")

    # ---- obtaining the file ---------------------------------------------------

    def _space_ok(self, card: ModelCard) -> bool:
        os.makedirs(self._store.root, exist_ok=True)
        usage = self._free(self._store.root)
        free = int(getattr(usage, "free", None) if getattr(usage, "free", None) is not None else usage[2])
        return free >= card.size_bytes * 1.1 + card.min_free_mb * _MIB

    def download(self, model_id: str, *, approved: bool) -> ModelStatus:
        with self._lock:
            entry = self._ensure().get(model_id)
            if entry is None:
                return self._status(model_id, False, "unknown_model")
            if approved is not True:
                return self._refuse(model_id, "approval_required", "download_refused")
            if entry["state"] not in ("registered", "failed"):
                return self._refuse(model_id, "illegal_state", "download_refused", [entry["state"]])
            card = self._card(entry)
            if card.source_url == LOCAL_IMPORT:
                return self._refuse(model_id, "needs_local_file", "download_refused")
            if not self._network_allowed():
                return self._refuse(model_id, "permission_denied", "download_refused")
            policy = license_policy(card.license)
            if policy == "needs_review" and not entry["license_ack"]:
                return self._refuse(model_id, "license_needs_ack", "download_refused")
            if policy in ("restricted", "unknown"):
                return self._refuse(model_id, "license_" + policy, "download_refused")
            if not self._space_ok(card):
                return self._refuse(model_id, "insufficient_space", "download_refused")
            self._move(model_id, "downloading", stage="download")
            rel = self._store.relative_file(card.model_id, card.version)
            try:
                result = self._downloader(card.source_url, self._store.root, rel, expected_sha256=card.sha256, max_bytes=card.size_bytes)
                ok, code = bool(getattr(result, "ok", False)), str(getattr(result, "code", "download_failed"))
            except Exception:
                ok, code = False, "download_failed"
            path = self._file_path(entry)
            if ok and (not os.path.isfile(path) or os.path.getsize(path) != card.size_bytes):
                self._discard_file(path)
                return self._fail(model_id, "download", "size_mismatch")
            if not ok:
                self._discard_file(path)
                entry = self._ensure()[model_id]
                self._move(model_id, "failed", stage="download", reasons=[code])
                return self._status(model_id, False, "download_failed", stage="download", reasons=[code])
            self._record_file(entry)
            self._move(model_id, "downloaded", stage="download")
            return self._status(model_id, True, "ok", stage="download")

    @staticmethod
    def _discard_file(path: str) -> None:
        for candidate in (path, path + ".partial"):
            try:
                os.unlink(candidate)
            except OSError:
                pass

    def import_local_file(self, model_id: str, src_path: str) -> ModelStatus:
        with self._lock:
            entry = self._ensure().get(model_id)
            if entry is None:
                return self._status(model_id, False, "unknown_model")
            if entry["state"] not in ("registered", "failed"):
                return self._refuse(model_id, "illegal_state", "import_refused", [entry["state"]])
            card = self._card(entry)
            try:
                if not isinstance(src_path, str) or os.path.islink(src_path) or not os.path.isfile(src_path):
                    return self._refuse(model_id, "model_file_invalid", "import_refused", ["not_a_regular_file"])
                if os.path.getsize(src_path) != card.size_bytes:
                    return self._refuse(model_id, "size_mismatch", "import_refused")
            except OSError:
                return self._refuse(model_id, "model_file_unreadable", "import_refused")
            if not self._space_ok(card):
                return self._refuse(model_id, "insufficient_space", "import_refused")
            target = self._file_path(entry)
            partial = target + ".partial"
            copied = 0
            try:
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with open(src_path, "rb") as source, open(partial, "wb") as out:
                    while True:
                        chunk = source.read(_COPY_CHUNK)
                        if not chunk:
                            break
                        copied += len(chunk)
                        if copied > card.size_bytes:
                            raise OSError("source grew while copying")
                        out.write(chunk)
                    out.flush()
                    os.fsync(out.fileno())
                os.replace(partial, target)
            except OSError:
                self._discard_file(target)
                return self._refuse(model_id, "io_error", "import_failed")
            self._record_file(entry)
            self._move(model_id, "downloaded", stage="import")
            return self._status(model_id, True, "ok", stage="import")

    # ---- the verification pipeline -----------------------------------------------

    def verify(self, model_id: str) -> ModelStatus:
        with self._lock:
            entry = self._ensure().get(model_id)
            if entry is None:
                return self._status(model_id, False, "unknown_model")
            if entry["state"] not in ("downloaded", "verified", "compatible", "usable"):
                return self._refuse(model_id, "illegal_state", "verify_refused", [entry["state"]])
            card, path = self._card(entry), self._file_path(entry)
            digest, size = hashlib.sha256(), 0
            try:
                with open(path, "rb") as handle:
                    for chunk in iter(lambda: handle.read(_COPY_CHUNK), b""):
                        digest.update(chunk)
                        size += len(chunk)
            except OSError:
                return self._fail(model_id, "verify", "file_missing")
            if size != card.size_bytes or digest.hexdigest() != card.sha256:
                code = "size_mismatch" if size != card.size_bytes else "hash_mismatch"
                self._quarantine(card, path)
                entry["file"] = None
                return self._fail(model_id, "verify", code)
            self._record_file(entry)
            if entry["state"] != "verified":
                self._move(model_id, "verified", stage="verify")
            else:
                self._save()
            self._loaded.pop(model_id, None)
            self._trusted.discard(model_id)
            return self._status(model_id, True, "ok", stage="verify")

    def _quarantine(self, card: ModelCard, path: str) -> None:
        try:
            os.makedirs(self._store.rejected_dir, exist_ok=True)
            target = os.path.join(self._store.rejected_dir, "%s-%s-%d.bin" % (card.model_id, card.version, int(self._clock())))
            os.replace(path, target)
            self._note("quarantined", card.model_id, {"file": os.path.basename(target)})
        except OSError:
            self._discard_file(path)

    def check_compatibility(self, model_id: str) -> ModelStatus:
        with self._lock:
            entry = self._ensure().get(model_id)
            if entry is None:
                return self._status(model_id, False, "unknown_model")
            if entry["state"] not in ("verified", "compatible", "usable"):
                return self._refuse(model_id, "illegal_state", "compat_refused", [entry["state"]])
            card = self._card(entry)
            reasons: List[str] = []
            policy = license_policy(card.license)
            if policy == "needs_review" and not entry["license_ack"]:
                reasons.append("license_needs_ack")
            elif policy in ("restricted", "unknown"):
                reasons.append("license_" + policy)
            runtime = self._runtimes.get(card.format)
            if runtime is None:
                reasons.append("no_runtime_for_format")
            else:
                if card.runtime_hint and card.runtime_hint != runtime.name:
                    reasons.append("runtime_hint_unavailable")
                availability = runtime.availability()
                if not availability.available:
                    reasons.append(availability.code)
            if reasons:
                entry["stage"], entry["reasons"] = "compatibility", reasons[:20]
                self._save()
                self._note("compat_blocked", model_id, {"reasons": reasons})
                return self._status(model_id, False, reasons[0], stage="compatibility", reasons=reasons)
            if entry["state"] == "verified":
                self._move(model_id, "compatible", stage="compatibility")
            return self._status(model_id, True, "ok", stage="compatibility")

    def load(self, model_id: str) -> ModelStatus:
        with self._lock:
            entry = self._ensure().get(model_id)
            if entry is None:
                return self._status(model_id, False, "unknown_model")
            if entry["state"] not in ("compatible", "usable"):
                return self._refuse(model_id, "illegal_state", "load_refused", [entry["state"]])
            card = self._card(entry)
            runtime = self._runtimes[card.format]
            try:
                self._loaded[model_id] = runtime.load(self._file_path(entry), card)
            except RuntimeLoadError as err:
                return self._fail(model_id, "load", err.code)
            except Exception:
                return self._fail(model_id, "load", "engine_load_failed")
            return self._status(model_id, True, "ok", stage="load")

    def smoke_test(self, model_id: str) -> ModelStatus:
        with self._lock:
            entry = self._ensure().get(model_id)
            if entry is None:
                return self._status(model_id, False, "unknown_model")
            if entry["state"] not in ("compatible", "usable"):
                return self._refuse(model_id, "illegal_state", "smoke_refused", [entry["state"]])
            if model_id not in self._loaded:
                loaded_status = self.load(model_id)
                if not loaded_status.ok:
                    return loaded_status
            card = self._card(entry)
            runtime = self._runtimes[card.format]
            try:
                report = runtime.smoke_test(self._loaded[model_id])
            except Exception:
                return self._fail(model_id, "smoke", "smoke_failed")
            entry["smoke"] = {"ok": bool(report.ok), "details": str(report.details)[:200], "excerpt": str(report.output_excerpt)[:200],
                              "at": float(self._clock()), "runtime": runtime.name}
            if not report.ok:
                return self._fail(model_id, "smoke", "smoke_failed")
            if entry["state"] != "usable":
                self._move(model_id, "usable", stage="smoke")
            else:
                self._save()
            self._trusted.add(model_id)
            return self._status(model_id, True, "ok", stage="smoke")

    def prepare(self, model_id: str) -> PipelineReport:
        """verify -> compatibility -> load -> smoke test, stopping at the first stage that does not pass."""
        stages: List[StageReport] = []
        last = self.status(model_id)
        for name, step in (("verify", self.verify), ("compatibility", self.check_compatibility),
                           ("load", self.load), ("smoke", self.smoke_test)):
            last = step(model_id)
            stages.append(StageReport(name, last.ok, last.code))
            if not last.ok:
                return PipelineReport(model_id, False, tuple(stages), last)
        return PipelineReport(model_id, last.usable, tuple(stages), last)

    # ---- use ---------------------------------------------------------------------

    def generate(self, model_id: str, prompt: str, *, max_tokens: int = 64, seed: int = 0) -> GenerationResult:
        started = time.monotonic()

        def refuse(code: str, runtime: str = "") -> GenerationResult:
            fa, en = _text(code)
            return GenerationResult(False, code, "", model_id, runtime, fa, en, round(time.monotonic() - started, 4))
        with self._lock:
            entry = self._ensure().get(model_id)
            if entry is None:
                return refuse("unknown_model")
            if entry["state"] != "usable":
                return refuse("model_not_usable")
            if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > _MAX_PROMPT_CHARS \
                    or isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or not 1 <= max_tokens <= 512 \
                    or isinstance(seed, bool) or not isinstance(seed, int):
                return refuse("bad_arguments")
            card = self._card(entry)
            runtime = self._runtimes.get(card.format)
            if runtime is None:
                return refuse("no_runtime_for_format")
            if model_id not in self._trusted:
                self._revalidate(model_id)
                if entry["state"] != "usable":
                    return refuse("model_not_usable", runtime.name)
                redo = self.smoke_test(model_id)  # loads the model and re-runs the real inference test once per process
                if not redo.ok:
                    return refuse("model_not_usable", runtime.name)
            try:
                text = runtime.generate(self._loaded[model_id], prompt, max_tokens=max_tokens, seed=seed)
            except RuntimeGenerateError as err:
                self._note("generate_failed", model_id, {"code": err.code})
                return refuse("smoke_failed" if err.code == "not_loaded" else "bad_arguments", runtime.name)
            fa, en = _text("ok")
            return GenerationResult(True, "ok", text, model_id, runtime.name, fa, en, round(time.monotonic() - started, 4))

    def _stale(self, entry: dict) -> str:
        info = entry.get("file")
        try:
            stat = os.stat(self._file_path(entry))
        except OSError:
            return "file_missing"
        if info is None or stat.st_size != info["size"] or stat.st_mtime_ns != info["mtime_ns"]:
            return "file_changed"
        return ""

    def is_usable(self, model_id: str) -> bool:
        with self._lock:
            entry = self._ensure().get(model_id)
            return bool(entry and entry["state"] == "usable")

    def model_path(self, model_id: str) -> str:
        with self._lock:
            entry = self._ensure().get(model_id)
            return self._file_path(entry) if entry else ""

    # ---- restart recovery ----------------------------------------------------------

    def recover(self) -> dict:
        """Run once at start-up: interrupted downloads go back to `registered`, partial/temporary files are removed."""
        with self._lock:
            report = {"interrupted": [], "missing_files": [], "removed_files": []}
            for model_id, entry in sorted(self._ensure().items()):
                card = self._card(entry)
                directory = self._store.model_dir(card.model_id, card.version)
                if os.path.isdir(directory):
                    for name in sorted(os.listdir(directory)):
                        if name.endswith((".partial", ".tmp")):
                            try:
                                os.unlink(os.path.join(directory, name))
                                report["removed_files"].append("%s/%s" % (model_id, name))
                            except OSError:
                                pass
                if entry["state"] == "downloading":
                    entry["file"] = None
                    self._move(model_id, "registered", stage="recover", reasons=["interrupted"])
                    report["interrupted"].append(model_id)
                elif entry["state"] in ("downloaded", "verified", "compatible", "usable") \
                        and not os.path.isfile(self._file_path(entry)):
                    entry["file"], entry["smoke"] = None, None
                    self._move(model_id, "registered", stage="recover", reasons=["file_missing"])
                    report["missing_files"].append(model_id)
            if os.path.isdir(self._store.root):
                for name in sorted(os.listdir(self._store.root)):
                    if name.startswith("registry.json.") and name.endswith(".tmp"):
                        try:
                            os.unlink(os.path.join(self._store.root, name))
                            report["removed_files"].append(name)
                        except OSError:
                            pass
            self._note("recovered", "registry", report)
            return report
