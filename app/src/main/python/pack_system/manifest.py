"""
pack_system.manifest - validate and normalize a package (`code.v1` / `lang.v1`)
===============================================================================
`normalize(raw)` turns the dict `intake` produced into the one canonical, JSON-safe manifest the rest of the pack system
stores and shows, or raises `PackError` with a Persian reason. It checks names, sizes, paths and which module a file may
become; it never imports or runs anything of the package (the source scan is `scan.py`).

Canonical manifest (code.v1):
    schema, kind, id, version, title, description, notes_fa, created_by, min_platform, permissions (sorted),
    replaces (sorted), entry, files {path: text}, file_hashes {path: sha256}, total_bytes, risky, fingerprint
(lang.v1 carries `qa` instead of `files`.)
"""

import importlib.util
import json
import os
import re
import sys

from . import limits
from .errors import PackError
from .fsutil import sha256_text

_BIDI = set(range(0x202A, 0x202F)) | set(range(0x2066, 0x206A)) | {0x200E, 0x200F}
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def clean_line(value, limit, what):
    if not isinstance(value, str):
        raise PackError("E_PACK_FIELD", "فیلد «%s» باید متن باشد." % what)
    value = " ".join(value.split())
    if len(value) > limit:
        raise PackError("E_PACK_FIELD", "فیلد «%s» بیش از %d نویسه است." % (what, limit))
    if any(ord(ch) in _BIDI for ch in value) or _CTRL_RE.search(value):
        raise PackError("E_PACK_FIELD", "فیلد «%s» نویسهٔ کنترلی یا جهت‌دهندهٔ پنهان دارد." % what)
    return value


def clean_block(value, limit, what, allow_newlines=True):
    if not isinstance(value, str):
        raise PackError("E_PACK_FIELD", "فیلد «%s» باید متن باشد." % what)
    value = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(value) > limit:
        raise PackError("E_PACK_FIELD", "فیلد «%s» بیش از %d نویسه است." % (what, limit))
    if any(ord(ch) in _BIDI for ch in value) or _CTRL_RE.search(value) or (not allow_newlines and "\n" in value):
        raise PackError("E_PACK_FIELD", "فیلد «%s» نویسهٔ مجاز ندارد." % what)
    return value


def _reserved_names():
    names = set(getattr(sys, "stdlib_module_names", ()))
    try:
        for entry in os.listdir(_PY_ROOT):
            names.add(entry[:-3] if entry.endswith(".py") else entry)
    except OSError:
        pass
    names.update({"java", "android", "test", "tests", "__main__", "site", "sitecustomize", "usercustomize"})
    return names


def _version(value):
    if isinstance(value, str) and value.strip().isdigit():
        value = int(value.strip())
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= limits.MAX_VERSION:
        raise PackError("E_PACK_VERSION", "«version» باید یک عدد صحیح بین ۱ و %d باشد." % limits.MAX_VERSION)
    return value


def _string_list(value, what, limit=16):
    if value is None or value == "":
        return []
    if isinstance(value, str):
        value = [p for p in re.split(r"[,،;\s]+", value) if p]
    if not isinstance(value, (list, tuple)) or len(value) > limit or not all(isinstance(v, str) for v in value):
        raise PackError("E_PACK_FIELD", "فیلد «%s» باید فهرستی از متن‌ها باشد." % what)
    return [v.strip() for v in value if v.strip()]


def module_of(path):
    """The dotted module a `.py` path stands for (`a/b/__init__.py` -> `a.b`), or ''."""
    if not path.endswith(".py"):
        return ""
    parts = path[:-3].split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _module_exists(name):
    """True when the app itself (or Python) has a module of that name - installed packs do not count."""
    from . import overlay
    parts = name.split(".")
    try:
        search_path = None
        if len(parts) > 1:
            parent = importlib.import_module(".".join(parts[:-1]))
            search_path = getattr(parent, "__path__", None)
            if search_path is None:
                return False
        ours = overlay.finder()
        for finder in list(sys.meta_path):
            find = getattr(finder, "find_spec", None)
            if finder is ours or find is None:
                continue
            try:
                if find(name, search_path) is not None:
                    return True
            except (ImportError, ValueError, AttributeError):
                continue
        return False
    except Exception:
        return False


def _common(raw):
    if not isinstance(raw, dict):
        raise PackError("E_PACK_FORMAT", "بسته باید یک شیء (object) باشد.")
    schema = raw.get("schema")
    if schema not in limits.SCHEMAS:
        raise PackError("E_PACK_SCHEMA", "«schema» باید code.v1 یا lang.v1 باشد.")
    pid = raw.get("id")
    if not isinstance(pid, str) or not limits.ID_RE.match(pid):
        raise PackError("E_PACK_ID", "«id» باید با حرف کوچک انگلیسی شروع شود و فقط حرف کوچک، رقم و _ داشته باشد (۳ تا ۴۰ نویسه).")
    if pid in _reserved_names() or _module_exists(pid):
        raise PackError("E_PACK_ID", "نام «%s» با یک ماژول پایتون یا بخش برنامه یکی است؛ نام دیگری انتخاب کن." % pid)
    out = {
        "schema": schema, "kind": schema, "id": pid, "version": _version(raw.get("version", 1)),
        "title": clean_line(raw.get("title") or pid, limits.MAX_TITLE, "title"),
        "description": clean_block(raw.get("description") or "", limits.MAX_DESC, "description"),
        "notes_fa": clean_block(raw.get("notes_fa") or "", limits.MAX_NOTES, "notes_fa"),
        "created_by": clean_line(str(raw.get("created_by") or "unknown"), 40, "created_by"),
    }
    plat = raw.get("min_platform", 0)
    if isinstance(plat, str) and plat.strip().isdigit():
        plat = int(plat.strip())
    if isinstance(plat, bool) or not isinstance(plat, int) or not 0 <= plat <= 10 ** 6:
        raise PackError("E_PACK_FIELD", "«min_platform» باید عدد باشد.")
    if plat > limits.PLATFORM_LEVEL:
        raise PackError("E_PACK_PLATFORM", "این بسته نسخهٔ %d از پلتفرم را می‌خواهد و این برنامه %d است." % (plat, limits.PLATFORM_LEVEL))
    out["min_platform"] = plat
    return out


def _code(raw, out):
    files = raw.get("files")
    if not isinstance(files, dict) or not files:
        raise PackError("E_PACK_FILES", "یک بستهٔ کد باید دست‌کم یک فایل در «files» داشته باشد.")
    if len(files) > limits.MAX_FILES:
        raise PackError("E_PACK_FILES", "بیش از %d فایل در بسته است." % limits.MAX_FILES)
    perms = _string_list(raw.get("permissions"), "permissions", 12)
    bad = [p for p in perms if p not in limits.PERMISSIONS]
    if bad:
        raise PackError("E_PACK_PERMISSION", "مجوز ناشناخته در بسته: %s (مجاز: %s)." % (bad[0][:30], "، ".join(limits.PERMISSIONS)))
    replaces = _string_list(raw.get("replaces"), "replaces", 12)
    pid, texts, total = out["id"], {}, 0
    for path, text in files.items():
        if not isinstance(path, str) or not limits.FILE_PATH_RE.match(path) or "//" in path:
            raise PackError("E_PACK_PATH", "نام فایل «%s» مجاز نیست (فقط حرف کوچک انگلیسی، رقم، _ و / و پسوند py/json/txt/md)." % str(path)[:60])
        if not isinstance(text, str):
            raise PackError("E_PACK_FILES", "محتوای فایل «%s» باید متن باشد." % path)
        size = len(text.encode("utf-8"))
        if size > limits.MAX_FILE_BYTES:
            raise PackError("E_PACK_FILE_SIZE", "فایل «%s» بیش از %d بایت است." % (path, limits.MAX_FILE_BYTES))
        if "\x00" in text:
            raise PackError("E_PACK_FILES", "فایل «%s» نویسهٔ NUL دارد." % path)
        total += size
        texts[path] = text.replace("\r\n", "\n").replace("\r", "\n")
    if total > limits.MAX_TOTAL_BYTES:
        raise PackError("E_PACK_FILE_SIZE", "مجموع اندازهٔ فایل‌ها از %d بایت بیشتر است." % limits.MAX_TOTAL_BYTES)
    replaced_files = {}
    for mod in replaces:
        if not limits.MODULE_RE.match(mod):
            raise PackError("E_PACK_REPLACES", "نام ماژول «%s» در replaces معتبر نیست." % mod[:60])
        if limits.is_protected(mod):
            raise PackError("E_PACK_PROTECTED", "ماژول «%s» محافظت‌شده است و هیچ بسته‌ای نمی‌تواند آن را عوض کند." % mod)
        rel = mod.replace(".", "/")
        candidates = [rel + ".py", rel + "/__init__.py"]
        found = [c for c in candidates if c in texts]
        if len(found) != 1:
            raise PackError("E_PACK_REPLACES", "برای عوض‌کردن «%s» دقیقاً یک فایل %s لازم است." % (mod, " یا ".join(candidates)))
        if not _module_exists(mod):
            raise PackError("E_PACK_REPLACES", "ماژولی به نام «%s» در برنامه نیست تا عوض شود." % mod)
        replaced_files[found[0]] = mod
    if replaces and "replace_core" not in perms:
        perms.append("replace_core")
    for path in texts:
        top = path.split("/")[0]
        if path.endswith(".py"):
            if path in replaced_files:
                continue
            if top != pid or "/" not in path:
                raise PackError("E_PACK_PATH", "فایل پایتون «%s» باید داخل پوشهٔ «%s/» باشد (یا ماژولی را که در replaces آمده عوض کند)." % (path, pid))
        elif top != pid or "/" not in path:
            raise PackError("E_PACK_PATH", "فایل داده «%s» باید داخل پوشهٔ «%s/» باشد." % (path, pid))
    # every folder of the pack's own package tree is a regular package: a forgotten (empty) __init__.py is added
    for path in list(texts):
        if path.endswith(".py") and path not in replaced_files:
            parts = path.split("/")[:-1]
            for depth in range(1, len(parts) + 1):
                init = "/".join(parts[:depth]) + "/__init__.py"
                if init not in texts:
                    texts[init] = ""
    entry = raw.get("entry") or ""
    if not isinstance(entry, str):
        raise PackError("E_PACK_ENTRY", "«entry» باید متن باشد.")
    entry = entry.strip()
    if not entry:
        for cand in (pid + "/main.py", pid + "/__init__.py"):
            if cand in texts:
                entry = module_of(cand)
                break
    if entry:
        if not limits.MODULE_RE.match(entry) or entry.split(".")[0] != pid:
            raise PackError("E_PACK_ENTRY", "«entry» باید ماژولی داخل بستهٔ «%s» باشد." % pid)
        rel = entry.replace(".", "/")
        if rel + ".py" not in texts and rel + "/__init__.py" not in texts:
            raise PackError("E_PACK_ENTRY", "فایل مربوط به entry «%s» در بسته نیست." % entry)
    perms = sorted(set(perms))
    out.update({"permissions": perms, "replaces": sorted(replaces), "entry": entry, "files": texts,
                "file_hashes": {p: sha256_text(t) for p, t in sorted(texts.items())}, "total_bytes": total,
                "risky": bool(limits.RISKY_PERMISSIONS & set(perms))})
    return out


def _lang(raw, out):
    qa = raw.get("qa")
    if not isinstance(qa, list) or not qa:
        raise PackError("E_PACK_FILES", "یک بستهٔ زبان باید فهرست «qa» (پرسش و پاسخ) داشته باشد.")
    if len(qa) > limits.MAX_QA:
        raise PackError("E_PACK_FILES", "بیش از %d ورودی پرسش و پاسخ در بسته است." % limits.MAX_QA)
    clean, total = [], 0
    for index, item in enumerate(qa):
        if not isinstance(item, dict):
            raise PackError("E_PACK_FIELD", "ورودی شمارهٔ %d از qa باید شیء {q, a} باشد." % (index + 1))
        qs = item.get("q")
        if isinstance(qs, str):
            qs = [qs]
        if not isinstance(qs, list) or not 1 <= len(qs) <= limits.MAX_QUESTIONS_PER_ENTRY:
            raise PackError("E_PACK_FIELD", "ورودی شمارهٔ %d: «q» باید ۱ تا %d پرسش باشد." % (index + 1, limits.MAX_QUESTIONS_PER_ENTRY))
        variants = [clean_line(q, limits.MAX_QUESTION_CHARS, "q") for q in qs]
        variants = [v for v in dict.fromkeys(variants) if v]
        answer = clean_block(item.get("a"), limits.MAX_ANSWER_CHARS, "a")
        if not variants or not answer:
            raise PackError("E_PACK_FIELD", "ورودی شمارهٔ %d: پرسش یا پاسخ خالی است." % (index + 1))
        total += sum(len(v) for v in variants) + len(answer)
        clean.append({"q": variants, "a": answer})
    if total > limits.MAX_LANG_BYTES:
        raise PackError("E_PACK_FILE_SIZE", "حجم داده‌های بستهٔ زبان از حد مجاز بیشتر است.")
    out.update({"qa": clean, "total_bytes": total, "permissions": [], "replaces": [], "entry": "", "risky": False})
    return out


def fingerprint(manifest):
    body = {k: v for k, v in manifest.items() if k != "fingerprint"}
    return sha256_text(json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":")))


def normalize(raw):
    """The canonical manifest of a raw package dict, or PackError."""
    out = _common(raw)
    out = _code(raw, out) if out["schema"] == limits.CODE_SCHEMA else _lang(raw, out)
    out["fingerprint"] = fingerprint(out)
    return out


def public_view(manifest):
    """The manifest without file texts / entries (what lists, audits and chat replies show)."""
    keep = ("schema", "id", "version", "title", "description", "permissions", "replaces", "entry", "created_by",
            "total_bytes", "risky", "fingerprint", "min_platform")
    view = {k: manifest.get(k) for k in keep}
    view["files"] = sorted(manifest.get("files") or ())
    view["qa_count"] = len(manifest.get("qa") or ())
    return view


__all__ = ["normalize", "fingerprint", "public_view", "module_of", "clean_line", "clean_block"]
