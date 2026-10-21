"""
model_runtime.card - the description of one local model, strictly validated
===========================================================================
A `ModelCard` is the user's (or the app's) CLAIM about a model file: where it
comes from, its exact size and SHA-256, its format and its licence. Nothing
in a card makes a model usable - the manager only trusts the file after the
hash, compatibility, load and inference checks have really passed.

`parse_card(dict)` raises `CardError(code, detail)` for anything unexpected
(unknown keys, wrong types, bad ids, non-https sources, absurd sizes), so a
malformed card can never reach the registry.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Mapping, Tuple

__all__ = ["KNOWN_FORMATS", "LOCAL_IMPORT", "ModelCard", "CardError", "parse_card", "license_policy"]

KNOWN_FORMATS: Tuple[str, ...] = ("ngram-json", "gguf", "onnx", "tflite")
LOCAL_IMPORT = "local-import"
MAX_SIZE_BYTES = 8 * 2 ** 30

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,63}$")
_VERSION_RE = re.compile(r"^[0-9A-Za-z._-]{1,32}$")
_SHA_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_LANG_RE = re.compile(r"^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})?$")
_HINT_RE = re.compile(r"^[A-Za-z0-9._-]{1,32}$")
_REQUIRED = ("model_id", "title", "version", "format", "source_url", "sha256", "size_bytes", "license")
_OPTIONAL = {"languages": (), "runtime_hint": "", "min_free_mb": 0, "notes": ""}

_PERMISSIVE = frozenset({"apache-2.0", "mit", "bsd-2-clause", "bsd-3-clause", "isc", "cc0-1.0", "cc-by-4.0", "unlicense"})
_REVIEW_PREFIXES = ("cc-by-sa", "gpl", "agpl", "lgpl", "openrail", "llama", "gemma", "research")
_RESTRICTED = frozenset({"proprietary", "non-commercial"})


class CardError(ValueError):
    """A card that must not be registered; `code` is stable, `detail` is a short diagnostic."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__("%s: %s" % (code, detail) if detail else code)
        self.code, self.detail = code, detail


@dataclass(frozen=True)
class ModelCard:
    model_id: str
    title: str
    version: str
    format: str
    source_url: str
    sha256: str
    size_bytes: int
    license: str
    languages: Tuple[str, ...] = ()
    runtime_hint: str = ""
    min_free_mb: int = 0
    notes: str = ""

    def to_dict(self) -> dict:
        data = asdict(self)
        data["languages"] = list(self.languages)
        return data


def license_policy(license_name: object) -> str:
    """'permissive' | 'needs_review' | 'restricted' | 'unknown' (only permissive is automatically compatible)."""
    if not isinstance(license_name, str):
        return "unknown"
    name = license_name.strip().lower()
    if name in _PERMISSIVE:
        return "permissive"
    if name in _RESTRICTED or name.startswith("cc-by-nc"):
        return "restricted"
    if name.startswith(_REVIEW_PREFIXES):
        return "needs_review"
    return "unknown"


def _text(data: Mapping, key: str, limit: int, *, allow_empty: bool = False) -> str:
    value = data[key]
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise CardError("bad_field", key)
    if len(value) > limit or any(ord(c) < 32 for c in value):
        raise CardError("bad_field", key)
    return value


def _int(data: Mapping, key: str, low: int, high: int) -> int:
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise CardError("bad_field", key)
    return value


def parse_card(data: object) -> ModelCard:
    """Validate a plain dict and return an immutable `ModelCard`; raises `CardError` otherwise."""
    if type(data) is not dict:
        raise CardError("bad_card", "not_a_dict")
    unknown = sorted(str(k) for k in data if k not in _REQUIRED and k not in _OPTIONAL)
    if unknown:
        raise CardError("unknown_field", ",".join(unknown)[:80])
    for key in _REQUIRED:
        if key not in data:
            raise CardError("missing_field", key)
    values = dict(_OPTIONAL)
    values.update(data)
    model_id = values["model_id"]
    if not isinstance(model_id, str) or not _ID_RE.match(model_id):
        raise CardError("bad_field", "model_id")
    version = values["version"]
    if not isinstance(version, str) or not _VERSION_RE.match(version):
        raise CardError("bad_field", "version")
    title = _text(values, "title", 120)
    fmt = values["format"]
    if fmt not in KNOWN_FORMATS:
        raise CardError("unknown_format", str(fmt)[:30])
    source = values["source_url"]
    if not isinstance(source, str):
        raise CardError("bad_field", "source_url")
    if source != LOCAL_IMPORT:
        from net_tools.policy import FetchPolicy, UrlError, parse_url  # local import keeps card parsing dependency-free

        parsed = parse_url(source, FetchPolicy())
        if isinstance(parsed, UrlError):
            raise CardError("bad_source_url", parsed.code)
    sha = values["sha256"]
    if not isinstance(sha, str) or not _SHA_RE.match(sha):
        raise CardError("bad_field", "sha256")
    size = _int(values, "size_bytes", 1, MAX_SIZE_BYTES)
    licence = _text(values, "license", 64)
    languages = values["languages"]
    if not isinstance(languages, (list, tuple)) or len(languages) > 8 or not all(
            isinstance(x, str) and _LANG_RE.match(x) for x in languages):
        raise CardError("bad_field", "languages")
    hint = values["runtime_hint"]
    if not isinstance(hint, str) or (hint and not _HINT_RE.match(hint)):
        raise CardError("bad_field", "runtime_hint")
    min_free = _int(values, "min_free_mb", 0, 1_000_000)
    notes = _text(values, "notes", 500, allow_empty=True)
    return ModelCard(model_id, title, version, fmt, source, sha.lower(), size, licence.strip(),
                     tuple(languages), hint, min_free, notes)
