"""
teacher.capture - recognising the assistant's answer
====================================================
The answer comes back as plain text from one of three places: what the typing recipe read off the screen, a text the user
SHARED into the app from the assistant (it lands in the inbox as `shared_*.txt`), or the clipboard (the user copied the
answer). This module only classifies and picks; it never installs anything - a pack found here goes through the pack system's
normal review and the user's own «بله».
"""

import hashlib
import os

from pack_system import intake

__all__ = ["classify", "sha16", "pick", "newest_shared_text", "MAX_TEXT_CHARS"]

MAX_TEXT_CHARS = 400_000
SHARED_PREFIX = "shared_"


def sha16(text):
    return hashlib.sha256(str(text).encode("utf-8", "replace")).hexdigest()[:16]


def classify(text):
    """'pack' (code.v1 / lang.v1), 'other_pack' (a pack of another format version), 'extension' (ext.v1), or 'text'."""
    if not isinstance(text, str) or not text.strip():
        return "empty"
    schema = None
    if "PACK" in text or "code.v" in text or "lang.v" in text:
        schema = intake.declared_schema(text)
    if schema in ("code.v1", "lang.v1"):
        return "pack"
    if schema:
        return "other_pack"
    if "ext.v1" in text and '"schema"' in text:
        return "extension"
    return "text"


def pick(kind, candidates, request_sha=""):
    """Choose from `[(source, text), ...]` (best source first).

    Returns `(source, text, klass, skipped)` where `skipped` lists `(source, reason)` for the candidates that were not usable,
    so the chat can tell the user exactly why nothing was found. A candidate equal to the request we sent is never taken (after the
    "copy and open" route the clipboard still holds OUR request)."""
    skipped = []
    best = None
    for source, text in candidates:
        if not isinstance(text, str) or not text.strip():
            skipped.append((source, "empty"))
            continue
        text = text[:MAX_TEXT_CHARS]
        if request_sha and sha16(text) == request_sha:
            skipped.append((source, "is_the_request"))
            continue
        klass = classify(text)
        if kind in ("code", "lang"):
            if klass in ("pack", "other_pack"):
                return source, text, klass, skipped
            skipped.append((source, "no_pack"))
            continue
        if best is None:
            best = (source, text, klass)
    if best is not None and kind == "ask":
        return best[0], best[1], best[2], skipped
    return None, "", "", skipped


def newest_shared_text(inbox_dir, newer_than):
    """The newest `shared_*.txt` of the inbox modified after `newer_than` (epoch seconds): `(name, text)` or None. Never raises."""
    try:
        names = [n for n in os.listdir(inbox_dir) if n.startswith(SHARED_PREFIX) and n.endswith(".txt")]
    except OSError:
        return None
    best = None
    for name in names[:200]:
        path = os.path.join(inbox_dir, name)
        try:
            if os.path.islink(path) or not os.path.isfile(path):
                continue
            mtime = os.path.getmtime(path)
            if mtime >= newer_than and (best is None or mtime > best[0]) and os.path.getsize(path) <= MAX_TEXT_CHARS * 4:
                best = (mtime, name, path)
        except OSError:
            continue
    if best is None:
        return None
    try:
        with open(best[2], "rb") as handle:
            return best[1], handle.read(MAX_TEXT_CHARS * 4).decode("utf-8", "replace")
    except OSError:
        return None
