"""
Understanding - semantic entity / slot foundation (Prompt 829)
==============================================================
Surfaces the simple, EXPLICIT values that are literally present in an
analyzed message as a flat list of "slots", so later stages (Reasoning,
Memory, AEL) can read them without re-parsing text.

Slot kinds (only these four):

  name       the value of the existing `name` entity of the primary result
             (e.g. "من عرفان هستم" -> "عرفان"). Copied, never re-derived.
  quoted     text inside a clear quote pair: "..."  «...»  “...”
  key_value  a clear `key: value` / `key=value` form: one-token key that
             starts with a letter, one-token value or a quoted value
             ("نام: علی", "age=30", 'city: "Tehran"')
  number     a standalone integer or simple decimal (digits are already
             ASCII after Persian normalization): "5", "4.5", "3٫14"

Every slot is a dict with the same keys:

  kind     one of the four above
  key      the key for key_value, else None
  value    the extracted string, exactly as it appears in the normalized
           text (numbers are NOT converted, nothing is rewritten)
  start    start offset in the normalized text (None for name slots)
  end      end offset (exclusive); for key_value it covers the whole
           "key: value", for quoted just the text inside the quotes
  source   "entity" (name slots) or "text"

Ambiguity is skipped, never guessed
  * an odd number of ASCII double quotes -> no ASCII-quoted slots at all
  * quoted text that is empty, blank or longer than MAX_VALUE_LEN
  * numbers glued to letters ("abc123", "v2"), written with a comma
    ("1,000"), or part of a time/date/fraction ("10:30", "2024-05-06",
    "1/2", "1.2.3")
  * "key:" forms whose key does not start with a letter ("10:30") or
    whose value starts with "/" (URLs) or is empty
  * a number inside a quoted or key_value slot is not repeated as a
    separate number slot; a quoted value used as a key_value value is
    not repeated as a separate quoted slot

Bounds: only the first MAX_TEXT_CHARS characters are scanned (cut at a
word boundary) and at most MAX_SLOTS slots are returned; `truncated` says
when either bound dropped something.

Pure, deterministic, stdlib only. Reads text and entities, stores nothing,
touches no Memory. Output is JSON-safe plain data. Slots are additive
information: the primary intent, entities and facts are never changed.
"""

import re

SLOTS_VERSION = 1
MAX_SLOTS = 16
MAX_TEXT_CHARS = 1000
MAX_VALUE_LEN = 80
MAX_KEY_LEN = 32
MAX_KV_VALUE_LEN = 64

KIND_NAME = "name"
KIND_QUOTED = "quoted"
KIND_KEY_VALUE = "key_value"
KIND_NUMBER = "number"

_GUILLEMET_RE = re.compile("«([^«»]*)»")
_CURLY_RE = re.compile("“([^“”]*)”")
_KV_RE = re.compile(
    r"(?<!\w)([^\W\d_]\w{0,%d})\s*[:=]\s*(?=\S)" % (MAX_KEY_LEN - 1))
_KV_VALUE_RE = re.compile(r"[^\s\"«»“”:=]{1,%d}" % MAX_KV_VALUE_LEN)
_NUMBER_RE = re.compile(
    r"(?<![\w.,٫])(?<!\d:)(?<!\d[-/])(\d+(?:[.٫]\d+)?)(?![\w]|[.,٫:]\d|:\d|[-/]\d)")
_TRAILING_PUNCT = ".,;!?،؛)"


def empty_slots():
    return {"version": SLOTS_VERSION, "items": [], "count": 0, "truncated": False}


def _slot(kind, key, value, start, end, source):
    return {"kind": kind, "key": key, "value": value,
            "start": start, "end": end, "source": source}


def _bounded_text(text):
    if len(text) <= MAX_TEXT_CHARS:
        return text, False
    cut = text[:MAX_TEXT_CHARS]
    if not text[MAX_TEXT_CHARS].isspace():
        space = cut.rfind(" ")
        cut = cut[:space] if space > 0 else cut
    return cut, True


def _quoted_spans(text):
    """Valid quote pairs as (open_pos, close_pos_exclusive, content_start,
    content_end), sorted by position."""
    spans = []
    for rx in (_GUILLEMET_RE, _CURLY_RE):
        for m in rx.finditer(text):
            spans.append((m.start(), m.end(), m.start(1), m.end(1)))
    positions = [i for i, ch in enumerate(text) if ch == '"']
    if len(positions) % 2 == 0:       # odd count = ambiguous pairing: skip all
        for a, b in zip(positions[0::2], positions[1::2]):
            spans.append((a, b + 1, a + 1, b))
    valid = []
    for o, c, cs, ce in sorted(spans):
        content = text[cs:ce].strip()
        if content and len(content) <= MAX_VALUE_LEN:
            valid.append((o, c, cs, ce))
    return valid


def _overlaps(ranges, start, end):
    return any(start < e and s < end for s, e in ranges)


def extract_slots(text, entities=None):
    """Extract slots from `text` (a normalized message) and the primary
    result's `entities` dict. Never raises; bad input gives no slots."""
    out = empty_slots()
    items = []
    if isinstance(entities, dict):
        name = entities.get("name")
        if isinstance(name, str) and name.strip():
            items.append(_slot(KIND_NAME, None, name, None, None, "entity"))
    truncated = False
    if isinstance(text, str) and text:
        t, truncated = _bounded_text(text)
        taken = []          # ranges already owned by a slot
        text_slots = []
        quoted = _quoted_spans(t)

        # key/value first: it may consume a quoted value.
        consumed_quotes = set()
        for m in _KV_RE.finditer(t):
            key, vstart = m.group(1), m.end()
            if _overlaps(taken, m.start(), vstart):
                continue
            q = next((s for s in quoted if s[0] == vstart), None)
            if q is not None:
                value, end = t[q[2]:q[3]].strip(), q[1]
                consumed_quotes.add(q)
            else:
                vm = _KV_VALUE_RE.match(t, vstart)
                if vm is None or vm.group(0).startswith("/"):
                    continue
                value = vm.group(0).rstrip(_TRAILING_PUNCT)
                end = vm.start() + len(value)
                if not value:
                    continue
            if _overlaps(taken, m.start(), end):
                continue
            taken.append((m.start(), end))
            text_slots.append(_slot(KIND_KEY_VALUE, key, value, m.start(), end, "text"))

        for q in quoted:
            if q in consumed_quotes or _overlaps(taken, q[0], q[1]):
                continue
            taken.append((q[0], q[1]))
            text_slots.append(_slot(KIND_QUOTED, None, t[q[2]:q[3]].strip(), q[2], q[3], "text"))

        for m in _NUMBER_RE.finditer(t):
            if _overlaps(taken, m.start(1), m.end(1)):
                continue
            text_slots.append(_slot(KIND_NUMBER, None, m.group(1), m.start(1), m.end(1), "text"))

        text_slots.sort(key=lambda s: (s["start"], s["end"]))
        items.extend(text_slots)

    if len(items) > MAX_SLOTS:
        items = items[:MAX_SLOTS]
        truncated = True
    out["items"] = items
    out["count"] = len(items)
    out["truncated"] = truncated
    return out


def extract_slots_from_analysis(analysis):
    """Slots for an `NLUAnalysis` (or anything analysis-like). Uses only
    `analysis.result.normalized_text` and `.entities`; never raises."""
    result = getattr(analysis, "result", None)
    return extract_slots(getattr(result, "normalized_text", None),
                         getattr(result, "entities", None))
