"""
model_runtime.ngram - a small statistical n-gram language model (NOT an LLM)
============================================================================
This is a plain counting model: it remembers which word followed which short
word sequence in the texts it was trained on and continues a prompt by
sampling from those counts (with back-off to shorter contexts). It has no
understanding, no reasoning and no knowledge beyond its training text; it is
real, deterministic, fully offline and trainable inside the app, and that is
all it claims to be.

* `train_ngram_model(texts, order, max_vocab) -> bytes` - canonical JSON
  (schema "ngram-json/1"), Persian-aware tokenisation (NFC, ZWNJ kept inside
  words, punctuation as separate tokens), bounded sizes.
* `load_ngram_model(bytes) -> NgramModel` - a STRICT loader: size, nesting
  depth, types, id ranges, duplicate keys and NaN/Infinity/float numbers are
  all checked; nothing is ever unpickled or evaluated.
* `NgramModel.generate(prompt, max_tokens, seed)` - deterministic for a seed.
"""

from __future__ import annotations

import json
import random
import re
import unicodedata
from collections import Counter, defaultdict
from typing import Dict, Iterable, List, Optional, Tuple

__all__ = ["SCHEMA", "NgramModel", "NgramModelError", "train_ngram_model", "load_ngram_model", "tokenize", "detokenize"]

SCHEMA = "ngram-json/1"
START, END, UNK = "<s>", "</s>", "<unk>"
SPECIAL = (START, END, UNK)
MAX_MODEL_BYTES = 32 * 2 ** 20
MAX_VOCAB = 50_000
MAX_TOKEN_CHARS = 64
MAX_CONTEXTS = 400_000
MAX_ENTRIES = 1_000_000
MAX_NEXT_PER_CONTEXT = 64
MAX_COUNT = 10 ** 9
MAX_JSON_DEPTH = 6
MAX_TRAIN_CHARS = 8_000_000
MAX_OUTPUT_TOKENS = 512

# word characters: letters/digits, ZWNJ (U+200C) and combining marks such as the Arabic tanwin (U+064B)
_MARKS = "\u0300-\u036f\u0610-\u061a\u064b-\u065f\u0670\u06d6-\u06dc\u06df-\u06e4\u06e7\u06e8\u06ea-\u06ed"
_TOKEN_RE = re.compile(r"[\w\u200c" + _MARKS + r"]+|[^\w\s]", re.UNICODE)
_SENTENCE_RE = re.compile(r"(?<=[.!?؟۔…])\s+|\n+")
_TERMINAL = frozenset(".!?؟۔…")
_NO_SPACE_BEFORE = frozenset(".,;:!?،؛؟۔…)]}»\"'")
_NO_SPACE_AFTER = frozenset("([{«")
_KEYS = frozenset({"schema", "order", "vocab", "contexts"})


class NgramModelError(ValueError):
    """A model file that must not be loaded (`code` is stable, `detail` a short diagnostic)."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__("%s: %s" % (code, detail) if detail else code)
        self.code, self.detail = code, detail


def tokenize(text: str) -> List[str]:
    """NFC-normalised, lower-cased word and punctuation tokens (ZWNJ stays inside words)."""
    text = unicodedata.normalize("NFC", text).lower()
    return [t[:MAX_TOKEN_CHARS] for t in _TOKEN_RE.findall(text)]


def detokenize(tokens: Iterable[str]) -> str:
    out: List[str] = []
    for token in tokens:
        if out and token not in _NO_SPACE_BEFORE and out[-1] not in _NO_SPACE_AFTER:
            out.append(" ")
        out.append(token)
    return "".join(out)


# --------------------------------------------------------------------------- training

def train_ngram_model(texts: Iterable[str], order: int = 3, max_vocab: int = 20000) -> bytes:
    """Count n-grams in `texts` and return the canonical JSON model. Raises ValueError for bad arguments/empty data."""
    if isinstance(order, bool) or not isinstance(order, int) or not 2 <= order <= 5:
        raise ValueError("order must be an integer from 2 to 5")
    if isinstance(max_vocab, bool) or not isinstance(max_vocab, int) or not 16 <= max_vocab <= MAX_VOCAB:
        raise ValueError("max_vocab must be an integer from 16 to %d" % MAX_VOCAB)
    sentences: List[List[str]] = []
    budget = MAX_TRAIN_CHARS
    for text in texts:
        if not isinstance(text, str):
            raise ValueError("training texts must be strings")
        budget -= len(text)
        if budget < 0:
            raise ValueError("training data is too large")
        for part in _SENTENCE_RE.split(text):
            tokens = tokenize(part)
            if tokens:
                sentences.append(tokens)
    if not sentences:
        raise ValueError("no training text")
    freq = Counter(tok for sentence in sentences for tok in sentence)
    kept = [t for t, _n in sorted(freq.items(), key=lambda kv: (-kv[1], kv[0]))[: max_vocab - len(SPECIAL)]]
    vocab = list(SPECIAL) + kept
    index = {tok: i for i, tok in enumerate(vocab)}
    table: Dict[Tuple[int, ...], Counter] = defaultdict(Counter)
    for sentence in sentences:
        ids = [0] * (order - 1) + [index.get(t, 2) for t in sentence] + [1]
        for pos in range(order - 1, len(ids)):
            for k in range(order):
                table[tuple(ids[pos - k:pos]) if k else ()][ids[pos]] += 1
    rows = []
    for ctx, nexts in table.items():
        top = sorted(nexts.items(), key=lambda kv: (-kv[1], kv[0]))[:MAX_NEXT_PER_CONTEXT]
        rows.append((ctx, sorted(top)))
    rows.sort(key=lambda row: (-sum(c for _i, c in row[1]), row[0]))
    del rows[MAX_CONTEXTS:]
    if not any(not ctx for ctx, _n in rows):  # the empty context is the last back-off; never prune it
        rows.append(((), sorted(sorted(table[()].items(), key=lambda kv: (-kv[1], kv[0]))[:MAX_NEXT_PER_CONTEXT])))
    rows.sort(key=lambda row: row[0])
    payload = {"schema": SCHEMA, "order": order, "vocab": vocab,
               "contexts": [[list(ctx), [[i, c] for i, c in nexts]] for ctx, nexts in rows]}
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


# --------------------------------------------------------------------------- strict loading

def _max_depth(data: bytes) -> int:
    depth = best = 0
    in_string = escaped = False
    for byte in data:
        if in_string:
            if escaped:
                escaped = False
            elif byte == 0x5C:
                escaped = True
            elif byte == 0x22:
                in_string = False
        elif byte == 0x22:
            in_string = True
        elif byte in (0x5B, 0x7B):
            depth += 1
            best = max(best, depth)
        elif byte in (0x5D, 0x7D):
            depth -= 1
    return best


def _no_duplicates(pairs):
    seen = {}
    for key, value in pairs:
        if key in seen:
            raise NgramModelError("duplicate_key", str(key)[:40])
        seen[key] = value
    return seen


def _reject_constant(name):
    raise NgramModelError("bad_number", name)


def _reject_float(text):
    raise NgramModelError("bad_number", "float")


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


class NgramModel:
    """A validated, immutable-by-convention model. Build it with `load_ngram_model`."""

    __slots__ = ("order", "vocab", "index", "table")

    def __init__(self, order: int, vocab: List[str], table: Dict[Tuple[int, ...], List[Tuple[int, int]]]) -> None:
        self.order, self.vocab, self.table = order, vocab, table
        self.index = {tok: i for i, tok in enumerate(vocab)}

    def vocabulary(self) -> frozenset:
        return frozenset(self.vocab[len(SPECIAL):])

    def _sample(self, ids: List[int], rng: random.Random, allow_end: bool) -> Optional[int]:
        banned = (0, 2) if allow_end else (0, 1, 2)
        for k in range(self.order - 1, -1, -1):
            entries = self.table.get(tuple(ids[-k:]) if k else ())
            if not entries:
                continue
            choices = [(i, c) for i, c in entries if i not in banned]
            if choices:
                pick = rng.randrange(sum(c for _i, c in choices))
                for i, c in choices:
                    if pick < c:
                        return i
                    pick -= c
        return None

    def generate(self, prompt: str, max_tokens: int = 64, seed: int = 0) -> str:
        """Continue `prompt` with up to `max_tokens` tokens; the same (prompt, seed) always gives the same text."""
        if not isinstance(prompt, str):
            raise ValueError("prompt must be a string")
        if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or not 1 <= max_tokens <= MAX_OUTPUT_TOKENS:
            raise ValueError("max_tokens must be an integer from 1 to %d" % MAX_OUTPUT_TOKENS)
        rng = random.Random(seed)
        words = tokenize(prompt)
        ids = [0] * (self.order - 1)
        if words and words[-1] not in _TERMINAL:  # a finished sentence starts a new one
            ids += [self.index.get(w, 2) for w in words]
        out: List[int] = []
        for _ in range(max_tokens):
            nxt = self._sample(ids, rng, allow_end=bool(out))
            if nxt is None or nxt == 1:
                break
            out.append(nxt)
            ids.append(nxt)
        return detokenize(self.vocab[i] for i in out)


def load_ngram_model(data: bytes) -> NgramModel:
    """Parse and validate a model file. Raises `NgramModelError`; never executes or unpickles anything."""
    if not isinstance(data, (bytes, bytearray)):
        raise NgramModelError("bad_input", "not_bytes")
    if len(data) > MAX_MODEL_BYTES:
        raise NgramModelError("too_large", str(len(data)))
    data = bytes(data)
    if _max_depth(data) > MAX_JSON_DEPTH:
        raise NgramModelError("too_deep")
    try:
        obj = json.loads(data.decode("utf-8"), object_pairs_hook=_no_duplicates, parse_constant=_reject_constant,
                         parse_float=_reject_float)
    except NgramModelError:
        raise
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise NgramModelError("bad_json") from None
    if type(obj) is not dict or set(obj) != _KEYS:
        raise NgramModelError("bad_structure", "keys")
    if obj["schema"] != SCHEMA:
        raise NgramModelError("bad_schema", str(obj["schema"])[:30])
    order = obj["order"]
    if not _is_int(order) or not 2 <= order <= 5:
        raise NgramModelError("bad_field", "order")
    vocab = obj["vocab"]
    if type(vocab) is not list or not len(SPECIAL) <= len(vocab) <= MAX_VOCAB or tuple(vocab[:3]) != SPECIAL:
        raise NgramModelError("bad_field", "vocab")
    for token in vocab:
        if not isinstance(token, str) or not token or len(token) > MAX_TOKEN_CHARS or any(ord(c) < 32 for c in token):
            raise NgramModelError("bad_field", "vocab_token")
    if len(set(vocab)) != len(vocab):
        raise NgramModelError("bad_field", "vocab_duplicate")
    contexts = obj["contexts"]
    if type(contexts) is not list or not 1 <= len(contexts) <= MAX_CONTEXTS:
        raise NgramModelError("bad_field", "contexts")
    size, table = len(vocab), {}
    entries = 0
    for row in contexts:
        if type(row) is not list or len(row) != 2 or type(row[0]) is not list or type(row[1]) is not list:
            raise NgramModelError("bad_structure", "context_row")
        ctx = row[0]
        if len(ctx) > order - 1 or not all(_is_int(i) and 0 <= i < size for i in ctx):
            raise NgramModelError("bad_field", "context_ids")
        nexts = row[1]
        if not 1 <= len(nexts) <= MAX_NEXT_PER_CONTEXT:
            raise NgramModelError("bad_field", "next_count")
        pairs = []
        for pair in nexts:
            if type(pair) is not list or len(pair) != 2 or not _is_int(pair[0]) or not _is_int(pair[1]):
                raise NgramModelError("bad_structure", "next_pair")
            if not 0 <= pair[0] < size or not 1 <= pair[1] <= MAX_COUNT:
                raise NgramModelError("bad_field", "next_values")
            pairs.append((pair[0], pair[1]))
        entries += len(pairs)
        if entries > MAX_ENTRIES:
            raise NgramModelError("too_large", "entries")
        key = tuple(ctx)
        if key in table:
            raise NgramModelError("duplicate_key", "context")
        table[key] = pairs
    if () not in table:
        raise NgramModelError("bad_field", "no_unigram_context")
    return NgramModel(order, vocab, table)
