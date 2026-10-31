"""
Persian conversation brain - self-knowledge: which sentence is about the assistant itself, and what it really has
================================================================================================================
`classify(norm, toks)` says whether a Persian sentence asks about the assistant itself (what it can do, whether it has a Persian
brain, whether it can upgrade itself, hear speech, use the internet or other apps) - a closed, deterministic cascade over normalized
tokens like `hub_intents`, with no table of whole sentences. It is only consulted for a sentence that nothing else in the app
handled (see `PersianBrain._dispatch`), so it never takes over an existing command; and it runs BEFORE the language model, because a
small model asked "who are you?" answers as the model it is («من مدل گوگل هستم»), which would be a false statement about this app.

`snapshot(hub, packs, teacher)` reads what THIS phone's app really has right now (a language model that passed its checks, packs, the
assistant apps found on the phone, the native doors the APK declares, the internet switch) and `hub_messages_self` words the answer
from it. Nothing here changes anything; it only explains.
"""

from teacher import assistants as _assistants

from . import hub_messages_self as HS
from . import hub_state
from . import lexicon as lx

ABOUT, BRAIN, UPGRADE, VOICE, OUTSIDE = "about", "brain", "upgrade", "voice", "outside"
KINDS = (ABOUT, BRAIN, UPGRADE, VOICE, OUTSIDE)

MAX_CHARS = 240
UNKNOWN_KEY = "persian_brain.unknown_note.v1"
UNKNOWN_QUIET_SECONDS = 15 * 60

# ------------------------------------------------------------------ word lists (tokens as normalization writes them)
_ABILITY = lx.phrases("می تونی", "میتونی", "می توانی", "میتوانی", "می تونید", "میتونید", "می توانید", "میتوانید", "بلدی", "بلدید",
                      "از دستت بر میاد", "از دستت برمیاد", "از دستت بر می آید", "امکانش هست", "می شه", "میشه", "می شود", "قادری")
_WHICH = lx.word_set("چه چی چیا کدام کدوم")
_KAR_STEMS = ("کار", "کمک", "چیز")
_CAP_STEMS = ("توانایی", "قابلیت", "امکانات", "امکان")
_POSSESSIVE = frozenset({"هات", "هایت", "ت", "تو", "هاتو", "هایی"})
_ATTACHED_POSSESSIVE = frozenset({"ت", "تو", "تون", "تان"})            # «امکاناتت», «قابلیتتون»: the possessive is part of the word
_WHAT_IS = lx.word_set("چیه چیست چیا چیاست کدومه کدامند کدومن چی")
_IDENTITY = lx.phrases("تو کی هستی", "تو کی هستی", "تو کیستی", "تو چی هستی", "تو چه هستی", "تو که هستی", "خودت را معرفی کن",
                       "خودتو معرفی کن", "خودت رو معرفی کن", "خودت را توضیح بده", "درباره خودت بگو", "درباره ی خودت بگو",
                       "از خودت بگو", "خودت را بشناسان")
_HELP_ME = lx.phrases("بهم کمک", "به من کمک", "کمکم کنی", "کمکم می کنی", "کمکم میکنی", "کمک کنی")

_SELF = frozenset({"خودت", "خودتو", "خودتون", "خودتان"})
_UP_STEMS = ("ارتقا", "ارتقاء", "آپگرید", "اپگرید", "آپدیت", "اپدیت", "تغییر", "عوض", "ویرایش", "بهتر", "قوی", "هوشمند", "باهوش",
             "بزرگ", "کامل", "تکمیل", "پیشرفت", "رشد")
_UP_VERBS = lx.word_set("بده بدی بدید کن بکن کنی بکنی کنید میکنی میدی بشو شو شی شید بشی بساز بنویس")
_UP_VERB_PHRASES = lx.phrases("می کنی", "می دی", "می کنید")
_UP_PHRASES = lx.phrases("هوشمندتر شو", "هوشمند تر شو", "باهوش تر شو", "باهوشتر شو", "قوی تر شو", "قویتر شو", "بهتر شو", "پیشرفت کن",
                         "رشد کن", "بزرگ تر شو", "آپگرید شو", "ارتقا پیدا کن", "باهوش بشو", "هوشمند بشو")

_VOICE_OBJECT = frozenset({"صدام", "صدامو", "صدایم", "صدامون", "حرفام", "حرفامو", "حرفمو", "حرفایم"})
_VOICE_OBJECT_PHRASES = lx.phrases("صدا من", "صدای من", "با صدا")
_HEAR = frozenset({"بشنوی", "میشنوی", "بشنو"})
_HEAR_PHRASES = lx.phrases("می شنوی", "گوش بده", "گوش بدی", "گوش می کنی", "گوش میکنی", "گوش می دی", "گوش میدی")
_TALK_PHRASES = lx.phrases("حرف بزنی", "صحبت کنی", "حرف می زنی", "صحبت می کنی", "حرف بزنم", "صحبت کنم")
_WITH_ME = lx.phrases("با من", "با ما")

_OUT_WORDS = frozenset({"گوگل", "اینترنت", "وب", "chatgpt", "claude", "gemini", "کلود", "جمینای"})
_OUT_PHRASES = lx.phrases("برنامه های دیگه", "برنامه های دیگر", "اپ های دیگه", "اپ های دیگر", "هوش مصنوعی دیگه", "هوش مصنوعی دیگر",
                          "دستیار دیگه", "دستیار دیگر", "سایت های دیگه", "از سایت", "توی سایت", "تو سایت", "به سایت")

_BRAIN_WORDS = frozenset({"باهوشی", "هوشمندی", "باهوشید", "هوشمندید"})
_YOU_ARE = lx.word_set("هستی هستید")
_USE = lx.word_set("استفاده داری داره هست")
_UNDERSTAND = lx.phrases("می فهمی", "میفهمی", "می فهمید", "میفهمید", "متوجه می شی", "متوجه میشی", "متوجه می شوی", "می دونی", "میدونی")
_ANYTHING = lx.phrases("هر چیزی", "هر چی", "همه چیز", "همه چی", "هرچی", "هرچیزی")
_HOW = frozenset({"چطور", "چجوری", "چطوری", "چگونه"})
_HOW_VERBS = frozenset({"کنم", "کنیم", "بکنم", "بشی", "بشوی", "بشه", "بشید"})


def _starts(toks, stems):
    return any(t.startswith(s) for t in toks for s in stems)


def _ability(toks):
    return lx.any_phrase(toks, _ABILITY)


def classify(norm, toks):
    """One of KINDS, or None. `norm` is the normalized sentence, `toks` its tokens."""
    if not isinstance(norm, str) or not toks or len(norm) > MAX_CHARS or len(toks) > 24:
        return None
    tset = set(toks)
    ability = _ability(toks)
    if _is_upgrade(toks, tset):
        return UPGRADE
    if _is_voice(toks, tset, ability):
        return VOICE
    if _is_outside(toks, tset, ability):
        return OUTSIDE
    if _is_brain(toks, tset):
        return BRAIN
    if _is_about(toks, tset, ability):
        return ABOUT
    return None


def _is_upgrade(toks, tset):
    if lx.any_phrase(toks, _UP_PHRASES):
        return True
    has_self = bool(tset & _SELF)
    verb = bool(tset & _UP_VERBS) or lx.any_phrase(toks, _UP_VERB_PHRASES)
    # «خودت را ارتقا بده» / «خودت را قوی‌تر کن» / «کد خودت را تغییر بده». «خودت یک کد بنویس» is NOT this (a build request: the gap explains it)
    return has_self and verb and _starts(toks, _UP_STEMS)


def _names_another_assistant(toks, tset):
    return bool(tset & _OUT_WORDS) or lx.any_phrase(toks, _OUT_PHRASES) or _assistants.find_in_tokens(toks) is not None


def _is_voice(toks, tset, ability):
    obj = bool(tset & _VOICE_OBJECT) or lx.any_phrase(toks, _VOICE_OBJECT_PHRASES)
    hear = bool(tset & _HEAR) or lx.any_phrase(toks, _HEAR_PHRASES)
    talk = lx.any_phrase(toks, _TALK_PHRASES)
    if obj and (hear or talk or ability):
        return True                                           # «می‌تونی صدامو بشنوی؟» / «با صدا باهات حرف بزنم؟»
    # «می‌تونی حرف بزنی؟» - but «می‌تونی با ChatGPT حرف بزنی؟» asks about another assistant (that is OUTSIDE)
    return talk and ability and not lx.any_phrase(toks, _WITH_ME) and not _names_another_assistant(toks, tset)


def _is_outside(toks, tset, ability):
    if not ability:
        return False
    return _names_another_assistant(toks, tset)


def _is_brain(toks, tset):
    if "مغز" in tset and tset & {"فارسی", "داری", "داره", "هوش"}:
        return True
    if "فارسی" in tset and lx.any_phrase(toks, _UNDERSTAND | lx.phrases("بلدی", "بلدید")):
        return True
    if lx.any_phrase(toks, _ANYTHING) and lx.any_phrase(toks, _UNDERSTAND | lx.phrases("متوجه")):
        return True                                           # «هر چیزی بگویم می‌فهمی؟»
    if "هوش" in tset and "مصنوعی" in tset and tset & {"داری", "هستی", "هستید", "داره"}:
        return True
    if tset & _BRAIN_WORDS:
        return True
    if "llm" in tset and tset & _USE:
        return True                                           # «LLM داری؟»
    if "مدل" in tset and "زبانی" in tset and tset & _USE:
        return True                                           # «مدل زبانی داری؟»
    if "تو" in tset and _starts(toks, ("مدل",)) and "استفاده" in tset:
        return True                                           # «تو از چه مدلی استفاده می‌کنی؟»
    return bool(tset & _HOW) and _starts(toks, ("هوشمند", "باهوش")) and bool(tset & _HOW_VERBS)   # «چطور هوشمندت کنم؟»


def _cap_with_attached_possessive(toks):
    return any(t.startswith(s) and t[len(s):] in _ATTACHED_POSSESSIVE for t in toks for s in _CAP_STEMS)


def _asks_my_name(toks, tset):
    """«اسم تو چیست؟» / «اسمت چیه؟» / «اسم داری؟» - the assistant's name (never «اسم من چیست؟», which asks about the USER's name)."""
    if "من" in tset or "منو" in tset:
        return False
    named = ("اسم" in tset and "تو" in tset) or bool(tset & {"اسمت", "اسمتو"}) or (_starts(toks, ("اسم",)) and bool(tset & {"داری", "دارید"}))
    return named and bool(tset & (_WHAT_IS | {"داری", "دارید"}))


def _is_about(toks, tset, ability):
    if lx.any_phrase(toks, _IDENTITY) or _asks_my_name(toks, tset):
        return True
    if ability and tset & _WHICH and _starts(toks, _KAR_STEMS):
        return True                                           # «چه کارهایی می‌توانی انجام بدهی؟» / «چه کمکی می‌تونی بکنی؟»
    if tset & {"بلدی", "بلدید"} and tset & _WHICH and len(toks) <= 3:
        return True                                           # «چی بلدی؟»
    if tset & _WHAT_IS and (_starts(toks, _CAP_STEMS) and tset & _POSSESSIVE or _cap_with_attached_possessive(toks)):
        return True                                           # «توانایی‌هات چیه؟» / «قابلیت‌هات چیه؟» / «امکاناتت چیه؟»
    if "تو" in tset and tset & _YOU_ARE and _names_another_assistant(toks, tset):
        return True                                           # «تو ChatGPT هستی؟»
    return ability and lx.any_phrase(toks, _HELP_ME)          # «می‌تونی بهم کمک کنی؟»


# ================================================================== what this app really has
def _model_part(hub):
    out = {"state": "none", "title": "", "reason": ""}
    try:
        models = list(hub.list_models())
    except Exception:
        return out
    usable = [m for m in models if m.usable]
    if usable:
        card = usable[0].card or {}
        return {"state": "usable", "title": str(card.get("title") or usable[0].model_id)[:60], "reason": ""}
    if models:
        first = models[0]
        reasons = set(first.reasons or ())
        if reasons & {"dependency_missing", "no_runtime_for_format", "runtime_hint_unavailable"}:
            reason = "این نسخهٔ برنامه موتورِ اجرای آن قالب را ندارد"
        elif first.state == "failed":
            reason = "آزمونش ناموفق بود"
        else:
            reason = "مراحلِ تأییدش هنوز تمام نشده است"
        card = first.card or {}
        return {"state": "imported", "title": str(card.get("title") or first.model_id)[:60], "reason": reason}
    return out


def snapshot(hub, packs=None, teacher=None, wish=""):
    """A small plain-data view of what the app has right now (see hub_messages_self). Never raises; a part that cannot be read is absent."""
    snap = {"model": {"state": "none", "title": "", "reason": ""}, "packs": {"active": 0, "installed": 0, "safe": False},
            "assistants": [], "native": frozenset(), "internet": False, "wish": wish if isinstance(wish, str) else ""}
    if hub is not None:
        snap["model"] = _model_part(hub)
        try:
            snap["native"] = frozenset(hub.native_features())
        except Exception:
            pass
        try:
            snap["internet"] = bool(hub.permissions.is_granted("network"))
        except Exception:
            pass
    if packs is not None:
        try:
            if packs.exists():
                summary = packs.summary()
                safe = (summary.get("safe_mode") or {}).get("level") or 0
                snap["packs"] = {"active": int(summary.get("active", 0)), "installed": int(summary.get("installed", 0)), "safe": bool(safe)}
        except Exception:
            pass
    if teacher is not None:
        try:
            snap["assistants"] = [{"id": r["id"], "title": r["title"], "installed": bool(r["installed"])} for r in teacher.assistants()]
        except Exception:
            pass
    return snap


REPLIES = {BRAIN: HS.brain, UPGRADE: HS.upgrade, VOICE: HS.voice, OUTSIDE: HS.outside}


def reply(kind, snap, registry=None):
    """The answer for `kind`. `registry` (lines about the tools the assistant built for itself) is only used by ABOUT."""
    if kind == ABOUT:
        return HS.about(snap, registry)
    return REPLIES[kind](snap)


# ================================================================== a question nothing could answer
def _quiet(memory, clock):
    """Was the long «nothing answers» explanation shown a moment ago? (then only a short line is shown) Never raises."""
    try:
        value = memory.get_state(UNKNOWN_KEY)
        now = hub_state._now(clock)
        return isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= now - value <= UNKNOWN_QUIET_SECONDS
    except Exception:
        return False


def unknown(memory, clock, snap, remembered=True):
    """The reply to a question or request that no rule, no taught fact and no language model could answer. The long explanation is shown
    once per quiet period; asked again within 15 minutes, only the short line is."""
    quiet = _quiet(memory, clock)
    if not quiet:
        try:
            memory.set_state(UNKNOWN_KEY, hub_state._now(clock))
        except Exception:
            pass
    return HS.unknown_short(snap, remembered) if quiet else HS.unknown_first(snap, remembered)


__all__ = ["classify", "snapshot", "reply", "unknown", "KINDS", "ABOUT", "BRAIN", "UPGRADE", "VOICE", "OUTSIDE"]
