"""
teacher.request - the text the assistant app is asked
=====================================================
Never calls anything: it only builds the message the user's own assistant app receives (through the share sheet, the clipboard
or the typing recipe). Three kinds:

    code   "write me a code.v1 pack that does <wish>"    -> the answer is a pack the app validates, scans and installs only after the user's yes
    lang   "write me a lang.v1 pack about <wish>"        -> Persian question->answer data
    ask    "answer this question: <wish>"                -> a plain answer shown to the user

Every instruction that describes the platform comes from `brain_hub.pack_prompt` (read from the live validator), so the request
cannot drift from what the app really accepts.
"""

import re

from brain_hub import pack_prompt

__all__ = ["KINDS", "build", "clean_wish", "MAX_WISH_CHARS", "make_preface", "make_own_preface"]

KINDS = ("code", "lang", "ask")
MAX_WISH_CHARS = pack_prompt.MAX_REQUEST_CHARS
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f\u202a-\u202e\u2066-\u2069]")


def clean_wish(text):
    text = _CONTROL_RE.sub(" ", str(text or ""))
    return re.sub(r"\s+", " ", text).strip()[:MAX_WISH_CHARS]


def make_preface(assistant_title):
    return ("سلام %s. من «دستیار هوشمند» هستم، برنامه‌ای روی گوشی صاحبم که کارهایی را که خودش بلد نیست از دستیارهای دیگر یاد می‌گیرد. "
            "این پیام را صاحبم خودش فرستاده است. لطفاً دقیقاً مطابق دستورِ پایین جواب بده." % assistant_title)


def make_own_preface():
    """The first lines when the receiver is the app's OWN cloud brain (the user's key): it is told who is asking and why."""
    return ("تو «مغز ابری» برنامهٔ «دستیار هوشمند» روی گوشیِ صاحب‌اش هستی. این پیام را صاحبِ برنامه خودش خواسته و خودِ برنامه می‌فرستد. "
            "لطفاً دقیقاً مطابق دستورِ پایین جواب بده.")


def build(wish, kind="code", assistant_title="دستیار", own_brain=False):
    """`(text, kind)` - the full request for `wish`. Unknown kinds fall back to a plain question."""
    wish = clean_wish(wish)
    if not wish:
        raise ValueError("empty wish")
    if kind not in KINDS:
        kind = "ask"
    preface = make_own_preface() if own_brain else make_preface(assistant_title)
    if kind == "ask":
        body = "\n".join([
            preface,
            "",
            "سؤال: " + wish,
            "",
            "قواعد جواب: فارسی روان و فشرده؛ فقط آنچه از درستی‌اش مطمئنی؛ اگر نمی‌دانی صریح بگو «نمی‌دانم». اگر جواب شامل کد است، کد را در یک بلوک جدا بده.",
        ])
        return body, "ask"
    prompt = pack_prompt.build_prompt(wish, kind)
    return preface + "\n\n" + prompt, kind
