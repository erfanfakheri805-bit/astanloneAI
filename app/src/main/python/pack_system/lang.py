"""
pack_system.lang - the retrieval layer behind `lang.v1` packs (Persian question -> answer data)
===============================================================================================
A language pack is data: entries `{"q": [phrasings...], "a": "answer"}`. This module turns the active ones into a small
search index and answers a Persian sentence only when one phrasing is *clearly* the same question:

    normalise (Persian/Arabic letters, digits, punctuation, half-spaces)  ->  light stemming  ->  words + word pairs
    -> tf-idf cosine over an inverted index  ->  accept only when the score is high AND clearly ahead of the runner-up
       (a different answer), otherwise say nothing and let the rest of the app decide.

This is honest retrieval: it never composes text, it returns the pack author's answer, and it stays silent when unsure.
Pure Python, standard library only; an index of 20 000 phrasings builds in well under a second.
"""

import math
import re
import threading
import unicodedata

from . import limits

__all__ = ["normalize_fa", "featurize", "LangIndex", "LangMatch", "LangService", "MIN_SCORE", "MARGIN", "MAX_PHRASINGS"]

MIN_SCORE = 0.70
MARGIN = 0.05
MAX_PHRASINGS = 24_000

_MAP = str.maketrans({"ي": "ی", "ى": "ی", "ئ": "ی", "ك": "ک", "ۀ": "ه", "ة": "ه", "ؤ": "و", "أ": "ا", "إ": "ا", "ٱ": "ا",
                      "\u200c": " ", "\u200d": "", "\u200e": " ", "\u200f": " ", "\u0640": "", "\xa0": " "})
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_MARKS = re.compile("[ً-ٰٟۖ-ۭ]")
_PUNCT = re.compile(r"[^\w\s]|_", re.UNICODE)
_SPACES = re.compile(r"\s+")

_STOP = frozenset("""و در به از که این آن را با برای است هست بود باشد یک یه هم تا رو می نمی ام ای هستم هستی هستید هستند
بودم بودی شد شده شود بر هر پس نیز همین همان اون ی آیا مگه""".split())
_COLLOQUIAL = {"چیست": "چی", "چیه": "چی", "کیست": "کی", "کیه": "کی", "کجاست": "کجا", "کجاس": "کجا", "چطوره": "چطور",
               "چگونه": "چطور", "چطوری": "چطور", "کدوم": "کدام", "کدومه": "کدام", "چقدره": "چقدر", "چنده": "چند"}
# (suffix, shortest stem that may remain): single letters are NOT stripped - they collide too often (سلام, ایران, پایتخت)
_SUFFIXES = (("ترین", 3), ("های", 2), ("ها", 2), ("تری", 3), ("تر", 3), ("ان", 4), ("ات", 4), ("ی", 4))
_PREFIXES = ("نمی", "می")


def normalize_fa(text):
    """Lower-cased text with Persian letter forms, Latin digits, no marks and no punctuation, single-spaced."""
    text = unicodedata.normalize("NFKC", str(text)).translate(_MAP).translate(_DIGITS)
    text = _MARKS.sub("", text).lower()
    text = _PUNCT.sub(" ", text)
    return _SPACES.sub(" ", text).strip()


def _stem(token):
    token = _COLLOQUIAL.get(token, token)
    if len(token) >= 5:
        for prefix in _PREFIXES:
            if token.startswith(prefix) and len(token) - len(prefix) >= 3:
                token = token[len(prefix):]
                break
    for suffix, shortest in _SUFFIXES:
        if token.endswith(suffix) and len(token) - len(suffix) >= shortest:
            return token[:-len(suffix)]
    return token


def featurize(text):
    """`(normalised text, [features])`: stems and stem pairs without function words."""
    norm = normalize_fa(text)
    stems = [_stem(t) for t in norm.split() if t not in _STOP]
    feats = ["u:" + s for s in stems]
    feats += ["b:%s %s" % (a, b) for a, b in zip(stems, stems[1:])]
    return norm, feats


class LangMatch:
    __slots__ = ("pack_id", "answer", "score", "question", "entry")

    def __init__(self, pack_id, answer, score, question, entry):
        self.pack_id, self.answer, self.score, self.question, self.entry = pack_id, answer, score, question, entry

    def to_dict(self):
        return {"pack_id": self.pack_id, "answer": self.answer, "score": round(self.score, 3), "question": self.question}


class LangIndex:
    def __init__(self):
        self._docs = []                  # (pack_id, entry no., phrasing, answer)
        self._exact = {}                 # feature sequence of a phrasing -> doc no. (colloquial and formal forms coincide)
        self._postings = {}              # feature -> [(doc no., weight)]
        self._idf = {}
        self.entries = 0
        self.truncated = False

    @property
    def phrasings(self):
        return len(self._docs)

    def build(self, entries):
        """`entries`: iterable of (pack_id, entry no., [phrasings], answer)."""
        docs, feats_per_doc, df = [], [], {}
        for pack_id, number, questions, answer in entries:
            self.entries += 1
            for question in questions:
                if len(docs) >= MAX_PHRASINGS:
                    self.truncated = True
                    break
                norm, feats = featurize(question)
                if not feats:
                    continue
                docs.append((pack_id, number, question, answer))
                self._exact[tuple(feats)] = len(docs) - 1         # the same sentence twice: the later entry (newer pack) wins
                feats_per_doc.append(feats)
                for f in set(feats):
                    df[f] = df.get(f, 0) + 1
        total = max(1, len(docs))
        self._idf = {f: math.log(1.0 + total / n) for f, n in df.items()}
        self._docs = docs
        postings = {}
        for index, feats in enumerate(feats_per_doc):
            counts = {}
            for f in feats:
                counts[f] = counts.get(f, 0) + 1
            weights = {f: (1.0 + math.log(c)) * self._idf[f] for f, c in counts.items()}
            norm = math.sqrt(sum(w * w for w in weights.values())) or 1.0
            for f, w in weights.items():
                postings.setdefault(f, []).append((index, w / norm))
        self._postings = postings
        return self

    def query(self, text):
        """The best `LangMatch`, or None when nothing is clearly the same question."""
        if not self._docs:
            return None
        norm, feats = featurize(text)
        if not feats:
            return None
        exact = self._exact.get(tuple(feats))
        if exact is not None:
            pack_id, number, question, answer = self._docs[exact]
            return LangMatch(pack_id, answer, 1.0, question, number)
        counts = {}
        for f in feats:
            counts[f] = counts.get(f, 0) + 1
        top_idf = math.log(1.0 + len(self._docs))
        weights = {f: (1.0 + math.log(c)) * self._idf.get(f, top_idf) for f, c in counts.items()}
        qnorm = math.sqrt(sum(w * w for w in weights.values())) or 1.0
        scores = {}
        for f, w in weights.items():
            for index, dw in self._postings.get(f, ()):
                scores[index] = scores.get(index, 0.0) + (w / qnorm) * dw
        if not scores:
            return None
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        best_index, best = ranked[0]
        if best < MIN_SCORE:
            return None
        best_doc = self._docs[best_index]
        runner = 0.0
        for index, score in ranked[1:12]:
            other = self._docs[index]
            if (other[0], other[1]) != (best_doc[0], best_doc[1]) and other[3] != best_doc[3]:
                runner = score
                break
        if best - runner < MARGIN:
            return None
        return LangMatch(best_doc[0], best_doc[3], best, best_doc[2], best_doc[1])


class LangService:
    """Builds the index from a manager's active, enabled language packs and rebuilds it when they change."""

    def __init__(self, manager):
        self._manager = manager
        self._lock = threading.Lock()
        self._index = LangIndex()
        self._signature = None

    def _current_signature(self):
        packs = self._manager.state["packs"]
        parts = [(pid, rec.get("active"), bool(rec.get("enabled", True)), bool(rec.get("quarantined")))
                 for pid, rec in sorted(packs.items()) if rec["kind"] == limits.LANG_SCHEMA]
        return (tuple(parts), self._manager.registry.lang_version)

    def _entries(self):
        packs = self._manager.state["packs"]
        live = []
        for pid, rec in packs.items():
            if rec["kind"] != limits.LANG_SCHEMA or rec.get("active") is None or not rec.get("enabled", True) or rec.get("quarantined"):
                continue
            installed = (rec["versions"].get(str(rec["active"])) or {}).get("installed") or 0
            live.append((installed, pid, rec["active"]))
        for _installed, pid, version in sorted(live):          # oldest pack first, so a newer pack overrides an older answer
            for number, item in enumerate(self._manager.store.lang_entries(pid, version)):
                if isinstance(item, dict) and isinstance(item.get("q"), list) and isinstance(item.get("a"), str):
                    yield pid, number, [q for q in item["q"] if isinstance(q, str)], item["a"]

    def index(self):
        signature = self._current_signature()
        with self._lock:
            if signature != self._signature:
                self._index = LangIndex().build(self._entries())
                self._signature = signature
            return self._index

    def answer(self, text):
        """`LangMatch` or None."""
        try:
            return self.index().query(text)
        except Exception:
            return None

    def stats(self):
        idx = self.index()
        return {"entries": idx.entries, "phrasings": idx.phrasings, "truncated": idx.truncated}
