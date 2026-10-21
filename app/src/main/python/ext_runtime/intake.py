"""
Extension runtime - package intake
==================================
Turns the bytes/text a user hands over (pasted JSON from a chat, a .json file, or a small .zip with `manifest.json`
and an optional `ext.py`) into a manifest object, enforcing the size, hash, path and type rules before anything is
parsed further. Nothing is executed and nothing is written to disk here.
"""

import hashlib
import io
import json
import re
import zipfile

from . import limits
from .errors import PackageError

_ZIP_ALLOWED = {"manifest.json": limits.MAX_PACKAGE_BYTES, "ext.py": limits.MAX_SOURCE_BYTES}
_MAX_RATIO = 200
_FENCE_RE = re.compile(r"```[A-Za-z0-9_-]*\s*\n(.*?)```", re.DOTALL)
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")


def sha256_hex(data):
    return hashlib.sha256(data).hexdigest()


def _reject_dupes(pairs):
    out = {}
    for k, v in pairs:
        if k in out:
            raise PackageError(f"duplicate key {k!r} in the package JSON", code="E_PACKAGE_JSON")
        out[k] = v
    return out


def _bad_constant(name):
    raise PackageError(f"{name} is not valid in a package", code="E_PACKAGE_JSON")


def _loads(text):
    try:
        return json.loads(text, object_pairs_hook=_reject_dupes, parse_constant=_bad_constant)
    except PackageError:
        raise
    except (ValueError, RecursionError) as e:
        raise PackageError(f"the package is not valid JSON: {str(e)[:120]}", code="E_PACKAGE_JSON") from None


def _decode(data):
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise PackageError("the package must be UTF-8 text", code="E_PACKAGE_JSON") from None
    return text[1:] if text.startswith("\ufeff") else text


def _read_zip(data):
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, OSError, ValueError):
        raise PackageError("the file looks like a ZIP but cannot be opened", code="E_PACKAGE_ZIP") from None
    with zf:
        infos = zf.infolist()
        if not 1 <= len(infos) <= len(_ZIP_ALLOWED):
            raise PackageError("a package ZIP holds manifest.json and optionally ext.py", code="E_PACKAGE_ZIP")
        seen, files = set(), {}
        for info in infos:
            name = info.filename
            if name in seen:
                raise PackageError(f"duplicate entry {name!r}", code="E_PACKAGE_ZIP")
            seen.add(name)
            if name not in _ZIP_ALLOWED or info.is_dir():
                raise PackageError(f"unexpected entry {name!r} (only manifest.json and ext.py are allowed; no folders, no paths)", code="E_PACKAGE_ZIP")
            if info.flag_bits & 0x1:
                raise PackageError("encrypted entries are not accepted", code="E_PACKAGE_ZIP")
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise PackageError("links inside a package are not accepted", code="E_PACKAGE_ZIP")
            limit = _ZIP_ALLOWED[name]
            if info.file_size > limit or info.file_size > _MAX_RATIO * max(info.compress_size, 1) + 4096:
                raise PackageError(f"entry {name!r} is too large or suspiciously compressed", code="E_PACKAGE_SIZE")
            with zf.open(info) as f:
                body = f.read(limit + 1)
            if len(body) > limit:
                raise PackageError(f"entry {name!r} is larger than {limit} bytes", code="E_PACKAGE_SIZE")
            files[name] = body
    if "manifest.json" not in files:
        raise PackageError("the ZIP has no manifest.json", code="E_PACKAGE_ZIP")
    return files


def parse_package(data, expected_sha256=None):
    """(manifest_object, source_or_None, package_sha256). Raises PackageError. The manifest is NOT validated yet."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    if not isinstance(data, (bytes, bytearray)):
        raise PackageError("a package must be text or bytes", code="E_PACKAGE_TYPE")
    data = bytes(data)
    if not data.strip():
        raise PackageError("the package is empty", code="E_PACKAGE_EMPTY")
    if len(data) > limits.MAX_PACKAGE_BYTES:
        raise PackageError(f"the package is larger than {limits.MAX_PACKAGE_BYTES} bytes", code="E_PACKAGE_SIZE")
    digest = sha256_hex(data)
    if expected_sha256 is not None:
        want = str(expected_sha256).strip().lower()
        if not _SHA_RE.match(want):
            raise PackageError("the expected SHA-256 is not 64 hex characters", code="E_PACKAGE_HASH")
        if want != digest:
            raise PackageError("the package SHA-256 does not match the expected value (the file is not the one you meant)", code="E_PACKAGE_HASH")
    source = None
    if data[:4] == b"PK\x03\x04":
        files = _read_zip(data)
        obj = _loads(_decode(files["manifest.json"]))
        if "ext.py" in files:
            source = _decode(files["ext.py"])
    else:
        text = _decode(data).strip()
        m = _FENCE_RE.search(text)
        if m and not text.startswith("{"):
            text = m.group(1).strip()
        obj = _loads(text)
    if not isinstance(obj, dict):
        raise PackageError("the package JSON must be an object", code="E_PACKAGE_JSON")
    return obj, source, digest


def _balanced_object(text, start):
    depth, in_str, esc = 0, False, False
    for i in range(start, min(len(text), start + limits.MAX_PACKAGE_BYTES)):
        c = text[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


_MAX_CANDIDATES = 12          # how many "{" a bare search may try (a hostile message full of braces must not stall the app)


def find_package_in_text(text):
    """The JSON text of an `ext.v1` package inside a chat message (fenced or bare), or None.

    A fenced block wins. Otherwise every mention of the schema is tried, so a sentence such as "here is your ext.v1
    package: {...}" does not hide the object that follows it; the search is bounded."""
    if not isinstance(text, str) or limits.EXT_SCHEMA not in text:
        return None
    for m in _FENCE_RE.finditer(text):
        body = m.group(1).strip()
        if body.startswith("{") and limits.EXT_SCHEMA in body:
            return body
    tried, pos = 0, 0
    while tried < _MAX_CANDIDATES:
        idx = text.find(limits.EXT_SCHEMA, pos)
        if idx == -1:
            break
        start = text.rfind("{", 0, idx)
        while start != -1 and tried < _MAX_CANDIDATES:
            tried += 1
            obj = _balanced_object(text, start)
            if obj and limits.EXT_SCHEMA in obj:
                return obj
            start = text.rfind("{", 0, start)
        pos = idx + len(limits.EXT_SCHEMA)
    return None
