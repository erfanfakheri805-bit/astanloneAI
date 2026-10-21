"""
Extension runtime - trigger patterns
====================================
How a chat sentence selects an extension and fills its inputs, without any model and without running extension
code. A manifest lists trigger patterns such as

    "انعام {bill:number} با {percent:number} درصد"
    "وارونه کن {text:text}"
    "[لطفا] میانگین {values:list_number}"

Items are separated by spaces:  word | alt1|alt2 | [optional] | {slot} / {slot:type} | *  (any words).
Slot types: number, integer, text (a quoted «...» part or an http(s) address is taken verbatim), word, list_number, list_text.
A pattern must consume the WHOLE sentence (after a tiny set of polite filler words is dropped), so an extension
never fires on an unrelated long sentence that merely contains one of its words.
"""

import re

from self_builder import fa_text

from . import limits

SLOT_TYPES = ("number", "integer", "text", "word", "list_number", "list_text")
_DEFAULT_SLOT_FOR_INPUT = {limits.TYPE_NUMBER: "number", limits.TYPE_INTEGER: "integer", limits.TYPE_TEXT: "text",
                           limits.TYPE_LIST_NUMBER: "list_number", limits.TYPE_LIST_TEXT: "list_text"}
_COMPATIBLE = {limits.TYPE_NUMBER: ("number", "integer"), limits.TYPE_INTEGER: ("integer",),
               limits.TYPE_TEXT: ("text", "word"), limits.TYPE_LIST_NUMBER: ("list_number",),
               limits.TYPE_LIST_TEXT: ("list_text",)}
_SLOT_RE = re.compile(r"^\{([a-z][a-z0-9_]{0,29})(?::([a-z_]+))?\}$")
_QUOTE_RE = re.compile(r"«([^»]{1,2000})»|\"([^\"]{1,2000})\"|“([^”]{1,2000})”")
# an address typed in a sentence is kept whole (like a quoted part): its words must not be split at "://" and "."
_URL_RE = re.compile(r"https?://[^\s«»\"“”<>]{1,2000}", re.IGNORECASE)
_QUOTE_OR_URL_RE = re.compile(_QUOTE_RE.pattern + "|" + _URL_RE.pattern, re.IGNORECASE)
_URL_TAIL = ".,;:!?)]}»،؛؟"
_QUOTE_TOKEN = "qqquote{}qqq"          # letters only: the tokenizer would split digits off
_QUOTE_TOKEN_RE = re.compile(r"^qqquote([a-t])qqq$")
_FILLER = frozenset(fa_text.words("لطفا ممنون خب ببین میشه میتونی برام برایم من را رو یه یک آقا جان عزیزم"))


def _lit_tokens(word):
    toks = fa_text.words(word)
    return toks


class PatternError(ValueError):
    pass


class Trigger:
    __slots__ = ("source", "items", "slots", "literals")

    def __init__(self, source, items, slots, literals):
        self.source, self.items, self.slots, self.literals = source, items, slots, literals


def compile_trigger(source, input_types):
    """Compile one trigger pattern against the declared inputs ({name: type}). Raises PatternError."""
    if not isinstance(source, str) or not source.strip():
        raise PatternError("a trigger must be non-empty text")
    if len(source) > limits.MAX_TRIGGER_CHARS:
        raise PatternError(f"a trigger is longer than {limits.MAX_TRIGGER_CHARS} characters")
    items, slots, literals = [], [], 0
    for raw in source.split():
        m = _SLOT_RE.match(raw)
        if m:
            name, stype = m.group(1), m.group(2)
            if name not in input_types:
                raise PatternError(f"slot {{{name}}} is not a declared input")
            if name in slots:
                raise PatternError(f"slot {{{name}}} is used twice in one trigger")
            declared = input_types[name]
            stype = stype or _DEFAULT_SLOT_FOR_INPUT.get(declared)
            if stype is None or stype not in SLOT_TYPES:
                raise PatternError(f"slot {{{name}}}: unsupported slot type for an input of type {declared!r}")
            if stype not in _COMPATIBLE.get(declared, ()):
                raise PatternError(f"slot {{{name}:{stype}}} does not fit the input type {declared!r}")
            slots.append(name)
            items.append(("slot", name, stype))
        elif raw == "*":
            items.append(("any",))
        else:
            optional = raw.startswith("[") and raw.endswith("]")
            body = raw[1:-1] if optional else raw
            if not body or any(c in body for c in "{}[]"):
                raise PatternError(f"bad pattern item {raw!r}")
            alts = set()
            for alt in body.split("|"):
                toks = _lit_tokens(alt)
                if len(toks) != 1:
                    raise PatternError(f"pattern word {alt!r} must be exactly one word")
                if toks[0] not in _FILLER:
                    alts.add(toks[0])
            if not alts:
                continue                                  # a filler word: dropped, like in the sentence
            items.append(("opt" if optional else "lit", frozenset(alts)))
            literals += 0 if optional else 1
    if literals < 1:
        raise PatternError("a trigger needs at least one fixed (non-optional) word, so it cannot match every sentence")
    return Trigger(source.strip(), tuple(items), tuple(slots), literals)


class Prepared:
    __slots__ = ("tokens", "spans", "quotes")

    def __init__(self, tokens, spans, quotes):
        self.tokens, self.spans, self.quotes = tokens, spans, quotes


def prepare(text):
    """Tokenize a user sentence once (quotes set aside, fillers dropped, numbers located)."""
    text = str(text or "")[:limits.MAX_TEXT_INPUT_CHARS]
    quotes = []

    def stash(m):
        if len(quotes) >= 20:
            return m.group(0)
        value = next((g for g in m.groups() if g is not None), None)
        if value is None:                                  # a bare address: trailing punctuation is not part of it
            value = m.group(0).rstrip(_URL_TAIL)
        quotes.append(value)
        return " " + _QUOTE_TOKEN.format(chr(96 + len(quotes))) + " "
    text = _QUOTE_OR_URL_RE.sub(stash, text)
    tokens = [t for t in fa_text.words(text) if t not in _FILLER]
    spans = {s: (e, v) for s, e, v in fa_text.scan_numbers(tokens)}
    return Prepared(tokens, spans, quotes)


def _quote_index(token):
    m = _QUOTE_TOKEN_RE.match(token)
    return ord(m.group(1)) - 97 if m else -1


def _text_value(prep, toks):
    out = []
    for t in toks:
        i = _quote_index(t)
        out.append(prep.quotes[i] if 0 <= i < len(prep.quotes) else t)
    return " ".join(out)


def _walk(items, i, prep, pos, values):
    toks = prep.tokens
    n = len(toks)
    if i == len(items):
        return values if pos == n else None
    item = items[i]
    kind = item[0]
    if kind == "lit":
        if pos < n and toks[pos] in item[1]:
            return _walk(items, i + 1, prep, pos + 1, values)
        return None
    if kind == "opt":
        if pos < n and toks[pos] in item[1]:
            r = _walk(items, i + 1, prep, pos + 1, values)
            if r is not None:
                return r
        return _walk(items, i + 1, prep, pos, values)
    if kind == "any":
        for k in range(0, n - pos + 1):
            r = _walk(items, i + 1, prep, pos + k, values)
            if r is not None:
                return r
        return None
    _, name, stype = item
    if stype in ("number", "integer"):
        span = prep.spans.get(pos)
        if span is None:
            return None
        end, value = span
        if stype == "integer":
            if value != int(value):
                return None
            value = int(value)
        elif value == int(value) and abs(value) < 1e15:
            value = int(value)
        return _walk(items, i + 1, prep, end, {**values, name: value})
    if stype == "word":
        if pos < n and _quote_index(toks[pos]) < 0:
            return _walk(items, i + 1, prep, pos + 1, {**values, name: toks[pos]})
        return None
    if stype == "list_number":
        spans, p = [], pos
        while True:
            span = prep.spans.get(p)
            if span is None:
                break
            spans.append(span)
            p = span[0]
            if p < n and toks[p] == "و" and (p + 1) in prep.spans:
                p += 1
            if len(spans) >= limits.MAX_LIST_INPUT_ITEMS:
                break
        for cnt in range(len(spans), 0, -1):
            nums = [int(v) if v == int(v) and abs(v) < 1e15 else v for _, v in spans[:cnt]]
            end = pos
            for _, __ in spans[:cnt]:
                end = prep.spans[end][0]
                if end < n and toks[end] == "و" and cnt > 1 and (end + 1) in prep.spans:
                    end += 1
            r = _walk(items, i + 1, prep, end, {**values, name: nums})
            if r is not None:
                return r
        return None
    # text / list_text: one or more tokens, shortest first (so a following anchor word can match)
    for k in range(1, n - pos + 1):
        chunk = toks[pos:pos + k]
        value = _text_value(prep, chunk) if stype == "text" else [_text_value(prep, [t]) for t in chunk]
        r = _walk(items, i + 1, prep, pos + k, {**values, name: value})
        if r is not None:
            return r
    return None


def match_trigger(trigger, prep):
    """{slot: value} when the whole sentence fits the trigger, else None."""
    if not prep.tokens:
        return None
    return _walk(trigger.items, 0, prep, 0, {})


def best_match(triggers, prep):
    """Best (index, values, trigger) among compiled triggers, or None. More fixed words win; ties go to the earlier trigger."""
    best = None
    for idx, trig in enumerate(triggers):
        values = match_trigger(trig, prep)
        if values is None:
            continue
        score = (trig.literals, len(values))
        if best is None or score > best[0]:
            best = (score, idx, values, trig)
    return None if best is None else (best[1], best[2], best[3])
