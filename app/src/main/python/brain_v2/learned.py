"""
brain_v2.learned - answers the app keeps, to give them again WITHOUT the internet (the first offline layer)
=========================================================================================================
When the cloud brain has answered a question, the app may keep that question and answer on the phone
(`<hub root>/brain_v2/learned.json`, private, atomic). Asked again - the same words, in the same order, give or take polite filler
words («لطفاً», «خب», «بگو») - it answers at once, offline, and says it is an answer it kept (and how old it is).

This is deliberately NOT a search engine and not "understanding": it only recognises a question it has seen before, and it keeps
only what is safe to repeat. A question is kept only if

* it is a real question (not a request to write something: a repeated request deserves a fresh text),
* it carries no secret or personal detail (`privacy`), is not about the user himself («اسم من») or about the assistant («تو کی هستی»),
  is not about "now" (prices, weather, news, today's date - the answer would be stale), and does not lean on the previous turn
  («و پایتختش؟», «این یعنی چه؟»),
* it is specific enough (3+ words besides filler) and the answer arrived complete (not cut by the length limit), is not an apology or
  a refusal, and is not itself a counter-question.

There is no fuzzy matching: the words that differ must be filler words from a short closed list. A different content word, a
different number or a different order is a different question and goes to the cloud brain again. The store is bounded (200 answers,
the least recently used leave first), can be switched off, wiped, and one answer can be dropped («این جواب غلط بود»).
"""

import threading
import time
from dataclasses import dataclass

from self_builder import fa_text

from . import privacy, store

__all__ = ["LearnedReplies", "Hit", "Kept", "tokens", "core", "eligible", "age_label", "MAX_ITEMS", "MAX_ANSWER_CHARS", "FILE_NAME"]

FILE_NAME = "learned.json"
MAX_ITEMS = 200
MAX_QUESTION_CHARS = 300
MAX_ANSWER_CHARS = 3000
MAX_BYTES = 1_000_000
MIN_CORE_WORDS = 3
MAX_TOKENS = 80                     # what `_valid_item` accepts when the file is read back: `keep` must never write more than that
MAX_TOKEN_CHARS = 40
_CLARIFY_MAX_CHARS = 240

_CANON = {"چیه": "چیست", "کیه": "کیست", "کجاس": "کجاست", "میشه": "میشود", "هست": "است", "هستش": "است", "چقدره": "چقدر", "چجوری": "چگونه",
          "چطوری": "چگونه", "چطور": "چگونه", "کدوم": "کدام", "بگید": "بگو"}
# words that may differ between two askings of the same question (politeness, interjections, "tell me")
_FILLER = frozenset({"لطفا", "لطفاً", "خب", "خوب", "ببینم", "بگو", "ممنون", "مرسی", "سلام", "جان", "عزیزم", "دقیقا", "دقیقاً", "واقعا", "واقعاً",
                     "اصلا", "اصلاً", "آخه", "راستی", "اوه", "هان", "هی", "بفرمایید", "بفرما", "ببخشید", "لطف", "میشه", "میشود", "ممکنه", "ممکن"})
_QUESTION_WORDS = frozenset({"چیست", "چه", "چرا", "چگونه", "کی", "کجا", "کجاست", "کدام", "چند", "چقدر", "آیا", "چی", "کیست", "معنی", "یعنی",
                             "توضیح", "فرق", "تفاوت"})
_CREATIVE = frozenset({"بنویس", "بساز", "تولید", "شعر", "داستان", "جوک", "لطیفه", "ایمیل", "نامه", "متن", "ترجمه", "خلاصه", "بازنویسی", "اصلاح",
                       "کد", "برنامه", "بکش", "طراحی", "نقاشی", "ایده", "پیشنهاد", "انشا", "مقاله", "شرح", "فهرست"})
_PERSONAL = frozenset({"من", "مرا", "منو", "ما", "خودم", "خودمو", "اسمم", "نامم", "مال", "واسم", "برایم", "برام", "دوستم", "همسرم", "مادرم", "پدرم",
                       "شهرم", "محلم", "خونم", "گوشیم", "حسابم", "کارتم", "رمزم", "شمارم", "آدرسم", "سنم", "دخترم", "پسرم", "کارم", "برادرم",
                       "خواهرم", "رئیسم", "معلمم", "دوستام", "بچهام", "بچم"})
_ABOUT_ASSISTANT = frozenset({"تو", "شما", "خودت", "اسمت", "نامت", "توانی", "تونی", "بلدی", "هستی", "هستید", "سازنده", "سازندهات", "اسمتون"})
_TIMELY = frozenset({"امسال", "پارسال", "امروز", "الان", "اکنون", "همینالان", "فردا", "دیروز", "امشب", "دیشب", "اخیرا", "اخبار", "خبر", "قیمت", "نرخ",
                     "دلار", "یورو", "طلا", "سکه", "بیتکوین", "هوا", "دما", "ساعت", "تاریخ", "جاری", "فعلی", "کنونی", "جدیدترین", "نتیجه", "رییس",
                     "رئیس", "وزیر", "نخست", "پیشبینی", "امروزه", "هماکنون", "لحظه", "زنده", "بازار", "سهام", "فعلا", "فعلاً", "اخیر"})
_DEICTIC = frozenset({"این", "آن", "اون", "همین", "همان", "همون", "اینها", "آنها", "اونها", "اینا", "اونا", "او", "اینو", "اونو", "اینجا", "آنجا",
                      "اونجا", "قبلی", "بعدی", "پیشین", "بالا", "پایین", "دوباره", "باز", "ادامه", "بیشتر", "کوتاهتر", "بلندتر", "مثلش", "همینطور"})
_CONTEXT_FIRST = frozenset({"و", "پس", "بعدش", "بعد", "ولی", "اما", "یعنی", "حالا", "خب", "اگه", "اگر"})
# common nouns that end in «ش» and are therefore not the pronoun suffix of «پایتختش»
_SH_NOUNS = frozenset({"آموزش", "ورزش", "دانش", "پژوهش", "افزایش", "کاهش", "بخش", "نمایش", "کوشش", "بینش", "گرایش", "روش", "سفارش", "پرورش", "پوشش",
                       "خواهش", "نگارش", "شورش", "فروش", "گزارش", "ارزش", "کنش", "واکنش", "رویش", "جوشش", "بارش", "آرامش", "آسایش", "کشش",
                       "نوشتهش", "گردش", "پرداخت", "ساخت", "پخش", "رقص", "خوابش", "آزمایش", "پیمایش", "پالایش", "ستایش", "نیایش", "سنجش"})
_BAD_ANSWER_STARTS = ("متاسفم", "متأسفم", "ببخشید", "عذر میخواهم", "نمیتوانم", "نمیدانم", "من نمیتوانم", "من نمیدانم", "به عنوان یک مدل",
                      "من یک مدل", "من یک هوش", "i'm sorry", "i am sorry", "i cannot", "i can't", "as an ai", "sorry", "unfortunately", "i don't know")
_UNSURE_ANYWHERE = ("نمیتوانم", "نمیدانم", "اطلاعاتی ندارم", "دسترسی ندارم", "اطلاعاتدقیقی ندارم")


@dataclass(frozen=True)
class Hit:
    answer: str
    age_s: float
    uses: int
    exact: bool          # False when only filler words differed from the question that was kept
    key: tuple


@dataclass(frozen=True)
class Kept:
    ok: bool
    reason: str = ""     # why not (see `eligible`) - "" when kept
    key: tuple = ()


def tokens(text):
    """The words of a question in the form used for matching (canonical Persian, colloquial endings unified)."""
    return tuple(_CANON.get(t, t) for t in fa_text.words(text))


def _key(token):
    return fa_text.key(token)


_FILLER_KEYS = frozenset(_key(w) for w in _FILLER)


def core(toks):
    """The words of a question without filler - two questions with the same core are the same question."""
    return tuple(t for t in toks if _key(t) not in _FILLER_KEYS)


def _keys(words):
    return frozenset(_key(w) for w in words)


_K_QUESTION, _K_CREATIVE, _K_PERSONAL, _K_ASSISTANT = _keys(_QUESTION_WORDS), _keys(_CREATIVE), _keys(_PERSONAL), _keys(_ABOUT_ASSISTANT)
_K_TIMELY, _K_DEICTIC, _K_CONTEXT_FIRST, _K_SH = _keys(_TIMELY), _keys(_DEICTIC), _keys(_CONTEXT_FIRST), _keys(_SH_NOUNS)


def _leans_on_context(toks):
    if _key(toks[0]) in _K_CONTEXT_FIRST:
        return True
    return any(len(t) >= 4 and t.endswith("ش") and _key(t) not in _K_SH for t in toks)


def eligible(question, answer):
    """(True, "") when a question and its answer may be kept, else (False, reason). The reasons are stable words used by tests and logs."""
    question, answer = str(question or "").strip(), str(answer or "").strip()
    if not question or not answer:
        return False, "empty"
    if len(question) > MAX_QUESTION_CHARS or len(answer) > MAX_ANSWER_CHARS:
        return False, "too_long"
    if not privacy.check(question, True).ok or not privacy.check(answer, True).ok:
        return False, "secret"
    if not privacy.check(question, False).ok:
        return False, "private"
    toks = tokens(question)
    if len(toks) > MAX_TOKENS or any(len(t) > MAX_TOKEN_CHARS for t in toks):
        return False, "too_long"
    body = core(toks)
    if len(body) < MIN_CORE_WORDS:
        return False, "length"
    keys = {_key(t) for t in body}
    if "؟" not in question and "?" not in question and not keys & _K_QUESTION:
        return False, "not_a_question"
    if keys & _K_CREATIVE:
        return False, "creative"
    if keys & _K_PERSONAL:
        return False, "personal"
    if keys & _K_ASSISTANT:
        return False, "assistant"
    if keys & _K_TIMELY:
        return False, "timely"
    if keys & _K_DEICTIC or _leans_on_context(body):
        return False, "context"
    head = _key(answer[:80])
    if any(head.startswith(_key(p)) for p in _BAD_ANSWER_STARTS) or any(_key(p) in head for p in _UNSURE_ANYWHERE):
        return False, "unsure_answer"
    if answer.rstrip()[-1:] in ("؟", "?") and len(answer) < _CLARIFY_MAX_CHARS:
        return False, "counter_question"
    return True, ""


def age_label(age_s):
    """A short Persian phrase for how old an answer is."""
    d = fa_text.to_fa_digits
    age = max(0, int(age_s))
    if age < 90:
        return "همین الان"
    if age < 3600:
        return "%s دقیقه پیش" % d(str(age // 60))
    if age < 86400:
        return "%s ساعت پیش" % d(str(age // 3600))
    if age < 86400 * 60:
        return "%s روز پیش" % d(str(age // 86400))
    return "%s ماه پیش" % d(str(age // (86400 * 30)))


def _valid_item(item):
    return (isinstance(item, dict) and set(item) == {"q", "a", "ts", "last", "uses"} and isinstance(item["q"], list)
            and 0 < len(item["q"]) <= MAX_TOKENS and all(isinstance(w, str) and 0 < len(w) <= MAX_TOKEN_CHARS for w in item["q"])
            and isinstance(item["a"], str)
            and 0 < len(item["a"]) <= MAX_ANSWER_CHARS
            and all(not isinstance(item[k], bool) and isinstance(item[k], (int, float)) for k in ("ts", "last", "uses")))


class LearnedReplies:
    def __init__(self, path, clock=time.time):
        self.path = path
        self._clock = clock
        self._lock = threading.RLock()
        self._items = None
        self.recovery = None

    # ------------------------------------------------------------------ storage
    def _load(self):
        if self._items is not None:
            return self._items
        items = []
        try:
            doc = store.read_json(self.path, MAX_BYTES)
            if not isinstance(doc, dict) or doc.get("schema") != 1 or not isinstance(doc.get("items"), list) \
                    or not all(_valid_item(i) for i in doc["items"]):
                raise ValueError("structure")
            items = [dict(i, q=list(i["q"])) for i in doc["items"]][-MAX_ITEMS:]
        except FileNotFoundError:
            pass
        except (ValueError, OSError):
            self.recovery = {"moved_to": store.set_aside(self.path), "at": float(self._clock())}
        self._items = items
        return items

    def _save(self, items):
        store.write_private_json(self.path, {"schema": 1, "items": items})
        self._items = items

    def count(self):
        with self._lock:
            return len(self._load())

    # ------------------------------------------------------------------ the memory
    def find(self, question):
        """A `Hit` for a question kept before (same words, filler aside), else None. Touches the item (recently used)."""
        toks = tokens(question)
        body = core(toks)
        if len(body) < MIN_CORE_WORDS:
            return None
        with self._lock:
            items = self._load()
            best = None
            for item in items:
                if core(tuple(item["q"])) == body and (best is None or item["last"] > best["last"]):
                    best = item
            if best is None:
                return None
            now = float(self._clock())
            age = max(0.0, now - best["ts"])
            best["last"], best["uses"] = now, best["uses"] + 1
            try:
                self._save(items)
            except OSError:
                pass                                   # a failed touch must never lose the answer
            return Hit(best["a"], age, best["uses"], tuple(best["q"]) == toks, tuple(best["q"]))

    def keep(self, question, answer):
        """Keep an answer if the question is eligible. Never raises. `Kept(ok, reason, key)`."""
        ok, why = eligible(question, answer)
        if not ok:
            return Kept(False, why)
        toks = tokens(question)
        body = core(toks)
        now = float(self._clock())
        with self._lock:
            items = [i for i in self._load() if core(tuple(i["q"])) != body]
            items.append({"q": list(toks), "a": str(answer).strip(), "ts": now, "last": now, "uses": 0})
            if len(items) > MAX_ITEMS:
                items.sort(key=lambda i: i["last"])
                items = items[-MAX_ITEMS:]
            try:
                self._save(items)
            except OSError:
                return Kept(False, "write_failed")
        return Kept(True, "", tuple(toks))

    def drop(self, key):
        """Forget the one answer whose question words are `key` (a `Hit.key` / `Kept.key`). True when something was removed."""
        key = tuple(key or ())
        if not key:
            return False
        with self._lock:
            items = self._load()
            kept = [i for i in items if tuple(i["q"]) != key]
            if len(kept) == len(items):
                return False
            try:
                self._save(kept)
            except OSError:
                return False
            return True

    def clear(self):
        """Forget every kept answer; returns how many."""
        with self._lock:
            n = len(self._load())
            store.remove(self.path)
            self._items = []
            return n
