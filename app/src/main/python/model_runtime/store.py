"""
model_runtime.store - the persistent model registry
===================================================
`<root>/registry.json` holds `{"schema": 1, "models": {model_id: entry}}`.

* Writes are atomic (temp file in the same directory -> flush -> fsync ->
  `os.replace`); an exception in between leaves the previous registry intact.
* Loading is STRICT. A registry that does not parse or does not validate is
  moved aside to `registry.corrupt.<n>` and reported to the caller - it is
  never silently reset or half-trusted.
* Model files live in `<root>/files/<model_id>/<version>/model.bin`; both path
  components are validated with the same patterns the card uses.
Creating the directories happens on the first write, never at import time.
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Dict, Optional, Tuple

from .card import CardError, parse_card

__all__ = ["STATES", "ModelStore", "validate_entry", "RegistryProblem", "MODEL_FILE_NAME"]

STATES = ("registered", "downloading", "downloaded", "verified", "compatible", "usable", "failed")
MODEL_FILE_NAME = "model.bin"
MAX_REGISTRY_BYTES = 4 * 2 ** 20
MAX_MODELS = 200
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,63}$")
_VERSION_RE = re.compile(r"^[0-9A-Za-z._-]{1,32}$")
_ENTRY_KEYS = {"card", "state", "origin", "license_ack", "reasons", "stage", "file", "smoke", "registered_at", "updated_at"}


class RegistryProblem(Exception):
    pass


def _num(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value == value and abs(value) != float("inf")


def validate_entry(model_id: str, entry: object) -> dict:
    """Return a clean copy of a registry entry or raise `RegistryProblem`."""
    if type(entry) is not dict or not _ENTRY_KEYS >= set(entry) or not {"card", "state", "origin"} <= set(entry):
        raise RegistryProblem("entry_keys")
    try:
        card = parse_card(entry["card"])
    except CardError:
        raise RegistryProblem("entry_card") from None
    if card.model_id != model_id:
        raise RegistryProblem("entry_id_mismatch")
    if entry["state"] not in STATES or entry["origin"] not in ("user", "bundled"):
        raise RegistryProblem("entry_state")
    reasons = entry.get("reasons", [])
    if type(reasons) is not list or len(reasons) > 20 or not all(isinstance(r, str) and len(r) <= 80 for r in reasons):
        raise RegistryProblem("entry_reasons")
    stage = entry.get("stage", "")
    if not isinstance(stage, str) or len(stage) > 30:
        raise RegistryProblem("entry_stage")
    ack = entry.get("license_ack", False)
    if not isinstance(ack, bool):
        raise RegistryProblem("entry_ack")
    file_info = entry.get("file")
    if file_info is not None:
        if type(file_info) is not dict or set(file_info) != {"rel", "size", "mtime_ns"}:
            raise RegistryProblem("entry_file")
        expected = "files/%s/%s/%s" % (card.model_id, card.version, MODEL_FILE_NAME)
        if file_info["rel"] != expected or isinstance(file_info["size"], bool) or not isinstance(file_info["size"], int) \
                or isinstance(file_info["mtime_ns"], bool) or not isinstance(file_info["mtime_ns"], int):
            raise RegistryProblem("entry_file")
    smoke = entry.get("smoke")
    if smoke is not None:
        if type(smoke) is not dict or set(smoke) != {"ok", "details", "excerpt", "at", "runtime"} \
                or not isinstance(smoke["ok"], bool) or not _num(smoke["at"]) \
                or not all(isinstance(smoke[k], str) and len(smoke[k]) <= 200 for k in ("details", "excerpt", "runtime")):
            raise RegistryProblem("entry_smoke")
    for key in ("registered_at", "updated_at"):
        if not _num(entry.get(key, 0.0)):
            raise RegistryProblem("entry_time")
    clean = {"card": card.to_dict(), "state": entry["state"], "origin": entry["origin"], "license_ack": ack,
             "reasons": list(reasons), "stage": stage, "file": file_info, "smoke": smoke,
             "registered_at": float(entry.get("registered_at", 0.0)), "updated_at": float(entry.get("updated_at", 0.0))}
    if clean["state"] in ("downloaded", "verified", "compatible", "usable") and file_info is None:
        raise RegistryProblem("entry_file_missing")
    if clean["state"] == "usable" and (smoke is None or not smoke["ok"]):
        raise RegistryProblem("entry_usable_without_smoke")
    return clean


class ModelStore:
    def __init__(self, root: str) -> None:
        if not isinstance(root, (str, os.PathLike)) or not str(root):
            raise ValueError("root must be a path")
        self.root = os.fspath(root)
        self.registry_path = os.path.join(self.root, "registry.json")

    # ---- paths ------------------------------------------------------------

    def model_dir(self, model_id: str, version: str) -> str:
        if not _ID_RE.match(model_id) or not _VERSION_RE.match(version):
            raise ValueError("unsafe model path component")
        return os.path.join(self.root, "files", model_id, version)

    def model_file(self, model_id: str, version: str) -> str:
        return os.path.join(self.model_dir(model_id, version), MODEL_FILE_NAME)

    @staticmethod
    def relative_file(model_id: str, version: str) -> str:
        return "files/%s/%s/%s" % (model_id, version, MODEL_FILE_NAME)

    @property
    def rejected_dir(self) -> str:
        return os.path.join(self.root, ".rejected")

    # ---- registry ---------------------------------------------------------

    def load(self) -> Tuple[Dict[str, dict], Optional[dict]]:
        """(models, recovery). `recovery` is None normally, or a dict describing a corrupt registry that was set aside."""
        path = self.registry_path
        if not os.path.exists(path):
            return {}, None
        try:
            if os.path.islink(path) or os.path.getsize(path) > MAX_REGISTRY_BYTES:
                raise RegistryProblem("file")
            with open(path, "rb") as handle:
                payload = json.loads(handle.read().decode("utf-8"))
            if type(payload) is not dict or set(payload) != {"schema", "models"} or payload["schema"] != 1 \
                    or type(payload["models"]) is not dict or len(payload["models"]) > MAX_MODELS:
                raise RegistryProblem("structure")
            return {mid: validate_entry(mid, entry) for mid, entry in payload["models"].items()}, None
        except (RegistryProblem, ValueError, OSError, RecursionError):
            return {}, self._set_aside()

    def _set_aside(self) -> dict:
        number = 1
        while os.path.exists("%s.corrupt.%d" % (self.registry_path, number)):
            number += 1
        target = "%s.corrupt.%d" % (self.registry_path, number)
        try:
            os.replace(self.registry_path, target)
        except OSError:
            target = ""
        return {"moved_to": os.path.basename(target) if target else "", "at": time.time()}

    def save(self, models: Dict[str, dict]) -> None:
        os.makedirs(self.root, exist_ok=True)
        data = json.dumps({"schema": 1, "models": models}, ensure_ascii=False, sort_keys=True, indent=1).encode("utf-8")
        temp = "%s.%d.tmp" % (self.registry_path, os.getpid())
        try:
            with open(temp, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, self.registry_path)
        except BaseException:
            try:
                os.unlink(temp)
            except OSError:
                pass
            raise
        try:
            fd = os.open(self.root, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        except OSError:
            pass
