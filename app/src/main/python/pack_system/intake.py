"""
pack_system.intake - from what the user handed over to ONE plain package dict
=============================================================================
Three shapes are accepted, all bounded and none of them executed:

1. a JSON object with `"schema": "code.v1"` or `"lang.v1"` (pasted in the chat, in a code fence or not);
2. the *text form* that chat assistants write reliably (no JSON string escaping of code):

       === PACK code.v1 ===
       id: my_feature
       version: 1
       title: عنوان
       description: توضیح کوتاه
       permissions: network, model
       replaces: persian_brain.messages
       entry: my_feature.main
       === FILE my_feature/__init__.py ===
       ...source...
       === FILE my_feature/main.py ===
       ...source...
       === END PACK ===

   and, for language data:

       === PACK lang.v1 ===
       id: fa_hello
       version: 1
       title: سلام و احوال‌پرسی
       === QA ===
       q: سلام | درود | سلام علیکم
       a: سلام! خوشحالم که اینجایی.
       === END PACK ===

3. a small ZIP (`manifest.json` with the same fields, plus the files it names), e.g. a file shared into the app.

`find_pack_in_text` returns `(schema, dict)` or None; `parse_bytes` does the same for file contents. Validation of the
*content* (names, sizes, paths, source scan) is `manifest.normalize`, not this module.
"""

import io
import json
import re
import zipfile

from . import limits
from .errors import PackError

_HEAD_RE = re.compile(r"^=== PACK (code\.v1|lang\.v1) ===[ \t]*$")
_FILE_RE = re.compile(r"^=== FILE ([A-Za-z0-9_./-]{1,200}) ===[ \t]*$")
_QA_RE = re.compile(r"^=== QA ===[ \t]*$")
_END_RE = re.compile(r"^=== END PACK ===[ \t]*$")
_SCHEMA_RE = re.compile(r'"schema"\s*:\s*"((?:code|lang)\.v\d{1,4})"')
_HEADER_KEYS = ("id", "version", "title", "description", "permissions", "replaces", "entry", "min_platform", "created_by",
                "notes_fa")
_LIST_KEYS = ("permissions", "replaces")
_ZIP_RATIO = 200


def _is_marker(line):
    s = line.strip()
    return bool(_HEAD_RE.match(s) or _FILE_RE.match(s) or _QA_RE.match(s) or _END_RE.match(s))


def _strip_fences(text):
    """Drop the Markdown code-fence lines (``` or ```lang) an assistant put AROUND the package or around each file:
    a fence that is the first/last line, or that touches a `=== ... ===` marker. A fence in the middle of a source file
    is source and stays."""
    lines = text.splitlines()
    fence = [i for i, ln in enumerate(lines) if ln.strip().startswith("```")]
    drop = set()
    for i in fence:
        prev = next((lines[j] for j in range(i - 1, -1, -1) if lines[j].strip() and j not in drop), None)
        nxt = next((lines[j] for j in range(i + 1, len(lines)) if lines[j].strip()), None)
        if prev is None or nxt is None or _is_marker(prev) or _is_marker(nxt):
            drop.add(i)
    return "\n".join(ln for i, ln in enumerate(lines) if i not in drop)


def declared_schema(text):
    """The schema string a pasted text declares ('code.v1', 'lang.v1', also unknown versions such as 'code.v2'), or None."""
    if not isinstance(text, str) or len(text) > limits.MAX_TEXT_BYTES:
        return None
    for line in text.splitlines():
        m = _HEAD_RE.match(line.strip())
        if m:
            return m.group(1)
    m = _SCHEMA_RE.search(text)
    return m.group(1) if m else None


def _split_list(value):
    return [p.strip() for p in re.split(r"[,،;\s]+", value) if p.strip()]


def parse_text_form(text):
    """The dict of a `=== PACK ... ===` text, or raise PackError. Source text is kept exactly as written."""
    lines = _strip_fences(text).replace("\r\n", "\n").replace("\r", "\n").split("\n")
    start = next((i for i, ln in enumerate(lines) if _HEAD_RE.match(ln.strip())), None)
    if start is None:
        raise PackError("E_PACK_FORMAT", "سرآیند «=== PACK ... ===» در متن پیدا نشد.")
    schema = _HEAD_RE.match(lines[start].strip()).group(1)
    out = {"schema": schema}
    mode, current, buf = "head", None, []
    files, qa = {}, []

    def flush():
        nonlocal current, buf
        if mode == "file" and current is not None:
            if current in files:
                raise PackError("E_PACK_DUPLICATE_FILE", "یک فایل دوبار در بسته آمده است: %s" % current)
            files[current] = "\n".join(buf).strip("\n") + "\n"
        elif mode == "qa" and buf:
            qa.extend(_parse_qa_entries(buf))
        current, buf = None, []

    for raw in lines[start + 1:]:
        stripped = raw.strip()
        if _END_RE.match(stripped):
            flush()
            mode = "done"
            break
        m = _FILE_RE.match(stripped)
        if m and schema == limits.CODE_SCHEMA:
            flush()
            mode, current = "file", m.group(1)
            continue
        if _QA_RE.match(stripped) and schema == limits.LANG_SCHEMA:
            flush()
            mode = "qa"
            continue
        if mode == "head":
            if not stripped:
                continue
            key, sep, value = stripped.partition(":")
            key = key.strip().lower()
            if sep and key in _HEADER_KEYS:
                value = value.strip()
                out[key] = _split_list(value) if key in _LIST_KEYS else value
                continue
            raise PackError("E_PACK_FORMAT", "سطر سرآیند نامعتبر است: «%s». هر سطر باید «کلید: مقدار» باشد." % stripped[:60])
        buf.append(raw)
    else:
        flush()
    if mode == "head":
        flush()
    if schema == limits.CODE_SCHEMA:
        out["files"] = files
    else:
        out["qa"] = qa
    return out


def _parse_qa_entries(lines):
    """Every `q: a | b` + `a: answer (may continue on the next lines)` pair of one `=== QA ===` section, in order."""
    entries, q, a, cur = [], None, [], None

    def close():
        nonlocal q, a, cur
        if q is None and not "".join(a).strip():
            return
        if not q or not "".join(a).strip():
            raise PackError("E_PACK_FORMAT", "هر ورودی «=== QA ===» یک «q:» و یک «a:» لازم دارد.")
        entries.append({"q": q, "a": "\n".join(a).strip()})
        q, a, cur = None, [], None

    for raw in lines:
        s = raw.strip()
        if s.lower().startswith("q:"):
            if cur == "a" or q is not None:
                close()
            q, cur = [p.strip() for p in s[2:].split("|") if p.strip()], "q"
        elif s.lower().startswith("a:"):
            if cur != "q":
                raise PackError("E_PACK_FORMAT", "قبل از هر «a:» باید یک «q:» بیاید.")
            a, cur = [s[2:].strip()], "a"
        elif cur == "a":
            a.append(raw.rstrip())
        elif s:
            raise PackError("E_PACK_FORMAT", "در بلوک «=== QA ===» فقط سطرهای «q:» و «a:» مجازند.")
    close()
    return entries


def _reject_dupes(pairs):
    out = {}
    for k, v in pairs:
        if k in out:
            raise PackError("E_PACK_JSON", "کلید تکراری در JSON بسته: %s" % str(k)[:40])
        out[k] = v
    return out


def _loads(text):
    try:
        return json.loads(text, object_pairs_hook=_reject_dupes)
    except PackError:
        raise
    except (ValueError, RecursionError) as exc:
        raise PackError("E_PACK_JSON", "بسته JSON معتبر نیست: %s" % str(exc)[:100]) from None


def parse_json_text(text):
    """The package dict inside a text that holds a JSON object with a pack schema (first match), or raise PackError."""
    decoder = json.JSONDecoder(object_pairs_hook=_reject_dupes)
    pos, tries = text.find("{"), 0
    while pos != -1 and tries < 8:
        tries += 1
        try:
            obj, _end = decoder.raw_decode(text, pos)
        except PackError:
            raise
        except (ValueError, RecursionError):
            obj = None
        if isinstance(obj, dict) and str(obj.get("schema", "")) in limits.SCHEMAS:
            return obj
        pos = text.find("{", pos + 1)
    raise PackError("E_PACK_FORMAT", "JSON بسته با «schema» برابر code.v1 یا lang.v1 در متن پیدا نشد.")


def find_pack_in_text(text):
    """`(schema, dict)` for a pasted package, or None when the text holds no pack at all. Raises PackError for a damaged one."""
    if not isinstance(text, str) or not text.strip():
        return None
    if len(text) > limits.MAX_TEXT_BYTES:
        raise PackError("E_PACK_TOO_LARGE", "متن بسته بیش از حد بزرگ است (بیشینه %d بایت)." % limits.MAX_TEXT_BYTES)
    schema = declared_schema(text)
    if schema is None:
        return None
    if schema not in limits.SCHEMAS:
        raise PackError("E_PACK_SCHEMA", "این بسته از نسخهٔ دیگری از قالب است (%s)؛ این برنامه فقط code.v1 و lang.v1 را می‌شناسد." % schema)
    if any(_HEAD_RE.match(line.strip()) for line in text.splitlines()):
        return schema, parse_text_form(text)
    return schema, parse_json_text(text)


def _read_zip(data):
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, OSError, ValueError):
        raise PackError("E_PACK_ZIP", "فایل شبیه ZIP است ولی باز نمی‌شود.") from None
    with zf:
        infos = zf.infolist()
        if not 1 <= len(infos) <= limits.MAX_FILES + 1:
            raise PackError("E_PACK_ZIP", "تعداد فایل‌های ZIP بسته نامعتبر است.")
        files, seen, total, manifest = {}, set(), 0, None
        for info in infos:
            name = info.filename
            if name in seen or info.is_dir():
                raise PackError("E_PACK_ZIP", "ورودی تکراری یا پوشه در ZIP: %s" % name[:60])
            seen.add(name)
            if info.flag_bits & 0x1:
                raise PackError("E_PACK_ZIP", "ورودی رمزدار پذیرفته نمی‌شود.")
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise PackError("E_PACK_ZIP", "لینک داخل بسته پذیرفته نمی‌شود.")
            if info.file_size > limits.MAX_FILE_BYTES or info.file_size > _ZIP_RATIO * max(info.compress_size, 1) + 4096:
                raise PackError("E_PACK_ZIP", "اندازهٔ یکی از ورودی‌های ZIP مجاز نیست: %s" % name[:60])
            total += info.file_size
            if total > limits.MAX_TOTAL_BYTES:
                raise PackError("E_PACK_ZIP", "مجموع اندازهٔ ZIP از حد مجاز بیشتر است.")
            raw = zf.read(info)
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                raise PackError("E_PACK_ZIP", "فایل «%s» متن UTF-8 نیست." % name[:60]) from None
            if name == "manifest.json":
                manifest = _loads(text)
            else:
                files[name] = text
    if not isinstance(manifest, dict):
        raise PackError("E_PACK_ZIP", "فایل manifest.json در ZIP نیست.")
    if isinstance(manifest.get("files"), dict) and files:
        raise PackError("E_PACK_ZIP", "فایل‌ها هم در manifest و هم کنار آن آمده‌اند؛ فقط یکی مجاز است.")
    if files:
        manifest["files"] = files
    return manifest


def parse_bytes(data):
    """`(schema, dict)` from file bytes (ZIP, JSON or the text form), or None when nothing in it looks like a pack."""
    if not isinstance(data, (bytes, bytearray)):
        return None
    if len(data) > limits.MAX_TEXT_BYTES:
        raise PackError("E_PACK_TOO_LARGE", "فایل بسته بیش از حد بزرگ است.")
    data = bytes(data)
    if data[:2] == b"PK":
        manifest = _read_zip(data)
        return str(manifest.get("schema", "")), manifest
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    text = text[1:] if text.startswith("\ufeff") else text
    return find_pack_in_text(text)


__all__ = ["declared_schema", "find_pack_in_text", "parse_bytes", "parse_text_form", "parse_json_text"]
