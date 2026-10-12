"""
Self-Builder - using what was built: invocation matching
========================================================
Turns an ordinary Persian sentence into a call of a registered capability, or
says honestly that no registered capability fits ("gap"):

  «۱۰ کیلومتر چند مایل است؟»                  -> unit_km_to_mi(value=10)
  «مساحت دایره با r=3 را حساب کن»              -> formula "مساحت دایره"(r=3)
  «تعداد کلمات را بشمار: سلام دنیای زیبا»      -> text tool (count_words)("سلام دنیای زیبا")

Everything is derived from the capability records themselves (unit keys,
formula title/variable aliases, text-operation chain) - there is no
per-capability code and no response dictionary; a newly built capability is
matchable the moment it is registered.

Result of `match_invocation(text, records)` (plain dict) or None:

  {"status": "invoke",       capability_id, version, inputs, shown_inputs, confidence, evidence}
  {"status": "needs_inputs", capability_id, version, missing: [labels], have: {...}, evidence}
  {"status": "gap",          archetype, slots, value | text, evidence}      (nothing registered fits)
  {"status": "describe",     capability_id}                                 (a question about a capability)
"""

import re

from . import fa_text, policy, request_parser, textops, units
from .registry import CAP_ACTIVE

_GAP_UNIT_WORDS = frozenset({"به", "چند", "چقدر", "چندتا", "میشود", "میشه", "تبدیل", "برابر", "معادل"})
_FORMULA_FILLER = frozenset({"را", "رو", "با", "برای", "من", "یک", "یه", "از", "به", "و", "ی", "که", "این", "آن", "اون",
                             "محاسبه", "حساب", "کن", "کنید", "کنی", "بکن", "بگو", "بده", "چقدر", "چند", "است", "هست",
                             "میشود", "میشه", "چیست", "چیه", "چنده", "میخواهم", "میخوام", "لطفا", "فرمول", "مقدار"})
_HOW_MANY = frozenset({"چند", "چقدر", "چندتا", "چنده"})
_VALUE_FILLER = frozenset({"برابر", "مساوی", "است", "هست", "باشد", "باشه", "با", "میشود", "میشه", "معادل", "برای"})
_QUESTION_ABOUT = frozenset({"چیست", "چیه", "چطور", "چگونه", "فرمول", "توضیح", "نشان", "نشون", "کار", "میکند", "میکنه"})
_DESCRIBE_VERBS = frozenset({"توضیح", "نشان", "نشون", "فرمولش", "چیست", "چیه", "چطور", "چگونه"})
_PAYLOAD_QUOTES = re.compile(r"[«\"“]([^»\"”]{1,%d})[»\"”]" % policy.MAX_INVOKE_TEXT_CHARS)


# ----------------------------------------------------------------- helpers --

def _records_of(records, kind):
    return [r for r in records if r.get("kind") == kind and r.get("status") == CAP_ACTIVE
            and r.get("version") is not None and r.get("spec")]


def _mention_keys(unit_records):
    """key -> unit/custom id for every unit surface form we know."""
    keys = {}
    for uid in units.UNITS:
        for k in units.match_keys(uid):
            keys.setdefault(k, uid)
    for rec in unit_records:
        for side in ("from", "to"):
            ref = rec["spec"][side]
            for k in ref.get("keys", []):
                keys.setdefault(k, ref["id"])
    return keys


def _find_mentions(tokens, keys, max_ngram=4):
    mentions = []
    i = 0
    n = len(tokens)
    while i < n:
        hit = None
        for size in range(min(max_ngram, n - i), 0, -1):
            k = fa_text.key(" ".join(tokens[i:i + size]))
            if k in keys and fa_text.parse_number(tokens[i]) is None:
                hit = (i, i + size, keys[k])
                break
        if hit:
            mentions.append(hit)
            i = hit[1]
        else:
            i += 1
    return mentions


def _number_before(numbers, index, max_gap=1):
    """Number span ending right before token `index` (<= max_gap tokens away)."""
    best = None
    for s, e, v in numbers:
        if e <= index and index - e <= max_gap:
            best = (s, e, v)
    return best


def _number_after(numbers, index, max_gap=1):
    for s, e, v in numbers:
        if s >= index and s - index <= max_gap:
            return (s, e, v)
    return None


# -------------------------------------------------------------------- units --

def _match_unit(text, tokens, numbers, records):
    unit_records = _records_of(records, policy.ARCHETYPE_UNIT_CONVERSION)
    keys = _mention_keys(unit_records)
    mentions = _find_mentions(tokens, keys)
    if len(mentions) < 2 or not numbers:
        return None
    # the unit right after a number is the source, the other mention is the target;
    # a unit that follows "چند / چقدر" ("how many ...") is what is asked for, never the source
    def asked_for(m):
        return m[0] > 0 and tokens[m[0] - 1] in _HOW_MANY

    source = None
    value_span = None
    for m in mentions:
        span = _number_before(numbers, m[0])
        if span is not None and not asked_for(m):
            source, value_span = m, span
            break
    if source is None:   # unusual word order: "کیلومتر ۱۰ چند مایل است"
        for m in mentions:
            span = _number_after(numbers, m[1], max_gap=0)
            if span is not None and not asked_for(m):
                source, value_span = m, span
                break
    if source is None:
        return None
    target = next((m for m in mentions if m is not source and m[2] != source[2]), None)
    if target is None:
        return None
    # the question has to be a conversion question, not "10 km = 6.2 mi" as a statement
    between = set(tokens[min(source[1], target[0]):max(source[1], target[0])]) if source[1] <= target[0] else \
        set(tokens[:source[0]]) | set(tokens[target[1]:source[0]])
    context = set(tokens)
    if not (context & _GAP_UNIT_WORDS) and not (between & _GAP_UNIT_WORDS):
        return None
    value = value_span[2]
    for rec in unit_records:
        spec = rec["spec"]
        if spec["from"]["id"] == source[2] and spec["to"]["id"] == target[2]:
            return {"status": "invoke", "capability_id": rec["id"], "version": rec["version"],
                    "inputs": {"value": value}, "shown_inputs": {"value": value}, "confidence": 0.9,
                    "evidence": ["unit_keys", "number_before_source_unit"]}
    # no capability: is it something the Self-Builder could build?
    from_u, to_u = units.UNITS.get(source[2]), units.UNITS.get(target[2])
    if from_u is not None and to_u is not None and from_u.dimension == to_u.dimension:
        return {"status": "gap", "archetype": policy.ARCHETYPE_UNIT_CONVERSION,
                "slots": {"from_unit": from_u.id, "to_unit": to_u.id}, "value": value,
                "evidence": ["two_table_units", "no_registered_capability"]}
    return None


# ------------------------------------------------------------------ formulas --

def _title_tokens(spec):
    toks = [t for t in fa_text.words(spec["title"]) if t not in _FORMULA_FILLER]
    return toks or fa_text.words(spec["title"])


def _formula_values(variables, tokens, numbers, preset=None, positional=True):
    """Assign the numbers of a sentence to the variables of a formula:
    first the explicitly named ones ("r=3", "شعاع ۳", "وزن برابر ۷۰ است"), then
    (unless `positional` is False) the remaining numbers in order. `preset`
    holds values already known.
    Returns (values by variable name, [variables still missing])."""
    used = set()
    values = dict(preset or {})
    for var in variables:
        if var["name"] in values:
            continue
        aliases = set(var["aliases"]) | {fa_text.key(var["name"])}
        for idx, tok in enumerate(tokens):
            if fa_text.key(tok) not in aliases or fa_text.parse_number(tok) is not None:
                continue
            j = idx + 1
            skipped = 0
            while j < len(tokens) and tokens[j] in _VALUE_FILLER and skipped < 3:
                j += 1
                skipped += 1
            span = next((n for n in numbers if n[0] == j and (n[0], n[1]) not in used), None)
            if span is None and idx > 0:
                span = next((n for n in numbers if n[1] == idx and (n[0], n[1]) not in used), None)
            if span is not None:
                values[var["name"]] = span[2]
                used.add((span[0], span[1]))
                break
    leftovers = [n for n in numbers if (n[0], n[1]) not in used]
    # positional fill for the variables that were not named
    for var in variables:
        if not positional:
            break
        if var["name"] in values:
            continue
        if not leftovers:
            break
        n = leftovers.pop(0)
        values[var["name"]] = n[2]
    missing = [v for v in variables if v["name"] not in values]
    return values, missing


# words that may stand between the numbers of a bare answer («۷۰ و ۱٫۷۵»)
_ANSWER_GLUE = frozenset({"و", "با", "هم", "حدود", "تقریبا", "فقط", "خب", "باشه", "است", "هست", "برابر", "مساوی",
                          "معادل", "میشود", "میشه", "باشد", "بگیر", "فرض", "کن"})


def value_answer(record, text, have=None):
    """Is `text` an ANSWER to «I still need these values» for a registered formula - or a different message that
    merely contains numbers («یک مبدل کیلومتر به مایل بساز …», «۱۰ کیلومتر چند مایل است؟»)?

    * "named": the sentence names a variable and gives its value («قد ۱٫۷۵», «وزن=۷۰ کیلو»);
    * "bare":  the sentence is nothing but numbers (with a unit word or a «و») and not more of them than
               values are missing («۷۰», «۷۰ و ۱٫۷۵»);
    * None:    anything else - the numbers in it are not taken as values.
    Returns {"kind", "values", "missing"} (values/missing as fill_formula_inputs)."""
    spec = record["spec"]
    have = dict(have or {})
    tokens = fa_text.words(text)
    numbers = fa_text.scan_numbers(tokens)
    result = {"kind": None, "values": have, "missing": [v for v in spec["variables"] if v["name"] not in have]}
    if not numbers:
        return result
    named, _ = _formula_values(spec["variables"], tokens, numbers, have, positional=False)
    if len(named) > len(have):
        kind = "named"
    else:
        covered = set()
        for start, end, _value in numbers:
            covered.update(range(start, end))
        for mention in units.find_units(tokens):
            covered.update(range(mention[0], mention[1]))
        rest = [t for i, t in enumerate(tokens) if i not in covered]
        if not all(t in _ANSWER_GLUE for t in rest) or len(numbers) > len(result["missing"]):
            return result
        kind = "bare"
    values, missing = _formula_values(spec["variables"], tokens, numbers, have)
    return {"kind": kind, "values": values, "missing": missing}


def fill_formula_inputs(record, text, have=None):
    """The values for the variables of a registered formula taken from an
    answer such as «r=3», «۳» or «شعاع ۵», merged with what is already known.
    Returns {"values": {name: number}, "missing": [variable dicts]}."""
    spec = record["spec"]
    tokens = fa_text.words(text)
    numbers = fa_text.scan_numbers(tokens)
    values, missing = _formula_values(spec["variables"], tokens, numbers, have)
    return {"values": values, "missing": missing}


def _match_formula(text, tokens, numbers, records):
    best = None
    token_set = set(tokens)
    for rec in _records_of(records, policy.ARCHETYPE_FORMULA):
        spec = rec["spec"]
        wanted = _title_tokens(spec)
        if not wanted:
            continue
        hit = [t for t in wanted if t in token_set]
        if len(hit) < len(wanted):
            continue
        score = (len(hit), len(wanted))
        if best is None or score > best[0]:
            best = (score, rec)
    if best is None:
        return None
    rec = best[1]
    spec = rec["spec"]
    variables = spec["variables"]
    values, missing = _formula_values(variables, tokens, numbers)
    evidence = ["formula_title"]
    asks_about = bool(token_set & _DESCRIBE_VERBS) and not numbers
    if asks_about:
        return {"status": "describe", "capability_id": rec["id"], "version": rec["version"], "evidence": evidence}
    if missing:
        return {"status": "needs_inputs", "capability_id": rec["id"], "version": rec["version"],
                "missing": [v["label"] for v in missing], "missing_names": [v["name"] for v in missing],
                "have": values, "evidence": evidence}
    return {"status": "invoke", "capability_id": rec["id"], "version": rec["version"],
            "inputs": {v["name"]: values[v["name"]] for v in variables},
            "shown_inputs": {v["label"]: values[v["name"]] for v in variables},
            "confidence": 0.85 if len(numbers) == len(variables) else 0.7, "evidence": evidence}


# ---------------------------------------------------------------- text tools --

def split_payload(text):
    """(instruction, payload|None): the text a tool should process is the
    quoted part («...», "...") or what follows the first ':'."""
    m = _PAYLOAD_QUOTES.search(text)
    if m:
        return (text[:m.start()] + " " + text[m.end():]).strip(), m.group(1)
    for sep in (":", "："):
        if sep in text:
            head, _, tail = text.partition(sep)
            tail = tail.strip()
            if tail:
                return head.strip(), tail[:policy.MAX_INVOKE_TEXT_CHARS]
    return text, None


def _match_text_tool(text, records):
    instruction, payload = split_payload(text)
    ops = request_parser.detect_text_ops(instruction)
    if not ops:
        return None
    # a request to BUILD a tool is not a call of one
    markers = request_parser.build_markers(instruction)
    if markers & {"build_verb", "learn", "want_need", "new_capability"}:
        return None
    for rec in _records_of(records, policy.ARCHETYPE_TEXT_TOOL):
        if list(rec["spec"]["ops"]) == ops:
            if payload is None:
                return {"status": "needs_inputs", "capability_id": rec["id"], "version": rec["version"],
                        "missing": ["متن"], "missing_names": ["text"], "have": {}, "evidence": ["text_ops"]}
            return {"status": "invoke", "capability_id": rec["id"], "version": rec["version"],
                    "inputs": {"text": payload}, "shown_inputs": {"text": payload}, "confidence": 0.85,
                    "evidence": ["text_ops", "payload"]}
    if payload is not None and 1 <= len(ops) <= textops.MAX_CHAIN and all(
            textops.op_kind(o) == "text" for o in ops[:-1]):
        return {"status": "gap", "archetype": policy.ARCHETYPE_TEXT_TOOL, "slots": {"ops": ops}, "text": payload,
                "evidence": ["text_ops", "no_registered_capability"]}
    return None


# -------------------------------------------------------------------- public --

def match_invocation(text, records):
    """Match `text` against the registered capability `records` (see
    Registry.get). Returns a plain dict (see module docstring) or None."""
    if not isinstance(text, str) or not text.strip() or len(text) > policy.MAX_REQUEST_CHARS:
        return None
    tokens = fa_text.words(text)
    numbers = fa_text.scan_numbers(tokens)
    for matcher in (lambda: _match_text_tool(text, records),
                    lambda: _match_unit(text, tokens, numbers, records),
                    lambda: _match_formula(text, tokens, numbers, records)):
        found = matcher()
        if found is not None:
            return found
    return None


def match_capability_question(text, records):
    """'آیا تبدیل متر به فوت را بلدی؟' -> the registered capability (or the
    archetype slots) the user is asking about.

    Returns {"status": "have", capability_id, version} | {"status": "missing", archetype, slots} | None."""
    tokens = fa_text.words(text)
    if not tokens:
        return None
    unit_records = _records_of(records, policy.ARCHETYPE_UNIT_CONVERSION)
    mentions = _find_mentions(tokens, _mention_keys(unit_records))
    if len(mentions) >= 2 and ("به" in tokens or "تبدیل" in tokens):
        a, b = mentions[0], mentions[1]
        for rec in unit_records:
            spec = rec["spec"]
            if spec["from"]["id"] == a[2] and spec["to"]["id"] == b[2]:
                return {"status": "have", "capability_id": rec["id"], "version": rec["version"]}
        from_u, to_u = units.UNITS.get(a[2]), units.UNITS.get(b[2])
        if from_u is not None and to_u is not None and from_u.dimension == to_u.dimension:
            return {"status": "missing", "archetype": policy.ARCHETYPE_UNIT_CONVERSION,
                    "slots": {"from_unit": from_u.id, "to_unit": to_u.id}}
        return None
    ops = request_parser.detect_text_ops(text)
    if ops:
        for rec in _records_of(records, policy.ARCHETYPE_TEXT_TOOL):
            if list(rec["spec"]["ops"]) == ops:
                return {"status": "have", "capability_id": rec["id"], "version": rec["version"]}
        return {"status": "missing", "archetype": policy.ARCHETYPE_TEXT_TOOL, "slots": {"ops": ops}}
    token_set = set(tokens)
    for rec in _records_of(records, policy.ARCHETYPE_FORMULA):
        wanted = _title_tokens(rec["spec"])
        if wanted and all(t in token_set for t in wanted):
            return {"status": "have", "capability_id": rec["id"], "version": rec["version"]}
    return None


def find_by_title(text, records):
    """A registered capability whose title (or id) the sentence names - used by
    «جزئیات …» / «برگرد به نسخهٔ قبلی …» commands."""
    key = fa_text.key(text)
    tokens = set(fa_text.words(text))
    best = None
    for rec in records:
        title_key = fa_text.key(rec["title"])
        if rec["id"] in text or (title_key and title_key in key):
            score = len(title_key) + 100
        else:
            wanted = [t for t in fa_text.words(rec["title"]) if t not in _FORMULA_FILLER]
            if not wanted or not all(t in tokens for t in wanted):
                continue
            score = len(" ".join(wanted))
        if best is None or score > best[0]:
            best = (score, rec)
    return best[1] if best else None


__all__ = ["match_invocation", "match_capability_question", "find_by_title", "split_payload",
           "fill_formula_inputs"]
