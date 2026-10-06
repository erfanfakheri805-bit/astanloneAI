"""
Understanding - semantic slot relations (Prompt 830)
====================================================
A small, deterministic layer on top of the Prompt 829 slots. It reports
only the relationships that the message STATES EXPLICITLY, so later
stages (Reasoning, Memory, AEL) do not have to re-read the text to know
which slot belongs to what. Nothing is inferred, completed or guessed:
when an explicit link is not clearly there, no relation is produced.

Relation kinds (only these four):

  name_ownership  an existing `name` slot that directly follows an explicit
                  owner phrase at the start of the message
                  ("من عرفان هستم" -> owner "من"; "اسم من علی" -> owner
                  "اسم من"). relation = "has_name".
  key_value       a `key_value` slot read as an assignment: subject = key,
                  value = value. relation = "assigned".
  request_target  the existing `request` block when it has BOTH an action
                  and an argument: subject = action, value = argument.
                  relation = "targets".
  quoted_target   a `quoted` slot that is, by itself (optionally followed by
                  the particle "را"/"رو"), the whole argument of a
                  request. subject = action, value = the quoted text.
                  relation = "targets".

Every relation is a dict with the same keys:

  kind      one of the four above
  subject   the owner phrase / key / action, exactly as written
  relation  "has_name" | "assigned" | "targets"
  value     the related text, exactly as in the slot / request block
  slot      index into the slots `items` list for the slot the relation
            reads (None for request_target)
  start     start offset of the value in the normalized text (None when
            it cannot be located exactly)
  end       end offset (exclusive), or None

Skipped, never guessed (counted in `ambiguous` where a candidate existed)
  * name slot without a literal owner phrase right before the name
  * request with a prohibition ("don't ..."): the target of a prohibition
    is not restated as a plain target
  * the same key assigned two DIFFERENT values: neither is reported
  * an argument holding several quoted slots, none of them the whole argument
  * request with no action or no argument (missing, nothing to report)

Bounds: at most MAX_RELATIONS relations; `truncated` says when more were
dropped. Output order: name_ownership, then key_value / request_target /
quoted_target in text order.

Pure, deterministic, stdlib only. Reads text, slots and the request block,
stores nothing, touches no Memory, and changes none of its inputs. Output
is JSON-safe plain data and always a fresh object. Relations are additive
information: the primary intent, entities, facts and slots are never
changed.
"""

from .nlu_slots import (
    KIND_NAME, KIND_QUOTED, KIND_KEY_VALUE, extract_slots_from_analysis,
)
from .persian_nlu import _NAME_PREFIXES

RELATIONS_VERSION = 1
MAX_RELATIONS = 16

REL_NAME_OWNERSHIP = "name_ownership"
REL_KEY_VALUE = "key_value"
REL_REQUEST_TARGET = "request_target"
REL_QUOTED_TARGET = "quoted_target"

PRED_HAS_NAME = "has_name"
PRED_ASSIGNED = "assigned"
PRED_TARGETS = "targets"

# Owner phrases that may precede an explicit name: the existing name-rule
# prefixes plus the plain first-person "من" of "من X هستم".
_OWNER_PHRASES = tuple(sorted(("من",) + tuple(_NAME_PREFIXES),
                              key=lambda p: (-len(p), p)))
_OBJECT_PARTICLES = ("را", "رو")


def empty_relations():
    return {"version": RELATIONS_VERSION, "items": [], "count": 0,
            "truncated": False, "ambiguous": 0}


def _relation(kind, subject, relation, value, slot, start, end):
    return {"kind": kind, "subject": subject, "relation": relation,
            "value": value, "slot": slot, "start": start, "end": end}


def _valid_slots(slots):
    if not isinstance(slots, dict) or not isinstance(slots.get("items"), list):
        return []
    return [s for s in slots["items"] if isinstance(s, dict)]


def _name_relation(text, items):
    for index, s in enumerate(items):
        if s.get("kind") != KIND_NAME:
            continue
        name = s.get("value")
        if not isinstance(name, str) or not name:
            return None
        for owner in _OWNER_PHRASES:
            head = owner + " "
            if text.startswith(head) and text[len(head):].startswith(name):
                start = len(head)
                return _relation(REL_NAME_OWNERSHIP, owner, PRED_HAS_NAME, name,
                                 index, start, start + len(name))
        return None
    return None


def _locate(text, value, after=0):
    pos = text.find(value, after)
    if pos < 0:
        return None, None
    return pos, pos + len(value)


def _argument_quoted(argument, slot_indexes, items, text):
    """(index, quoted_slot, n_candidates): the quoted slot that is the whole
    argument, if any; n_candidates counts quoted slots found in it."""
    core = argument
    for p in _OBJECT_PARTICLES:
        if core.endswith(" " + p):
            core = core[:-len(p)].rstrip()
            break
    candidates = 0
    exact = None
    for i in slot_indexes:
        s = items[i]
        a, b = s.get("start"), s.get("end")
        if not (isinstance(a, int) and isinstance(b, int)):
            continue
        # the slot's quote marks sit right around the content [a, b)
        if a < 1 or b >= len(text):
            continue
        wrapped = text[a - 1:b + 1]
        if wrapped in argument:
            candidates += 1
            if wrapped == core:
                exact = (i, s)
    return exact, candidates


def extract_relations(text, slots, request=None):
    """Relations from a normalized message `text`, its Prompt 829 `slots`
    dict and the optional `request` structure block. Never raises; bad
    input gives no relations."""
    out = empty_relations()
    items = _valid_slots(slots)
    if not isinstance(text, str) or not text:
        return out
    rels = []
    ambiguous = 0

    name_rel = _name_relation(text, items)
    if name_rel is not None:
        rels.append(name_rel)

    body = []   # key_value / request_target / quoted_target, sorted by position

    # key_value: assignments, skipping keys assigned conflicting values
    kv = [(i, s) for i, s in enumerate(items) if s.get("kind") == KIND_KEY_VALUE
          and isinstance(s.get("key"), str) and isinstance(s.get("value"), str)]
    values_by_key = {}
    for _i, s in kv:
        values_by_key.setdefault(s["key"], set()).add(s["value"])
    conflicting = {k for k, v in values_by_key.items() if len(v) > 1}
    ambiguous += len(conflicting)
    for i, s in kv:
        if s["key"] in conflicting:
            continue
        a, b = s.get("start"), s.get("end")
        start, end = (None, None)
        if isinstance(a, int) and isinstance(b, int) and 0 <= a < b <= len(text):
            start, end = _locate(text, s["value"], a)
            if end is not None and end > b:
                start, end = None, None
        body.append((a if isinstance(a, int) else len(text), 1,
                     _relation(REL_KEY_VALUE, s["key"], PRED_ASSIGNED, s["value"],
                               i, start, end)))

    # request_target / quoted_target
    if isinstance(request, dict) and request.get("present", True) is not False:
        action, argument = request.get("action"), request.get("argument")
        if (isinstance(action, str) and action.strip()
                and isinstance(argument, str) and argument.strip()):
            if request.get("prohibition") is True:
                ambiguous += 1
            else:
                marker = request.get("marker")
                after = len(marker) if isinstance(marker, str) and text.startswith(marker) else 0
                a_start, a_end = _locate(text, argument, after)
                pos = a_start if a_start is not None else len(text)
                body.append((pos, 0, _relation(REL_REQUEST_TARGET, action, PRED_TARGETS,
                                               argument, None, a_start, a_end)))
                quoted_ix = [i for i, s in enumerate(items) if s.get("kind") == KIND_QUOTED]
                exact, candidates = _argument_quoted(argument, quoted_ix, items, text)
                if exact is not None and candidates == 1:
                    i, s = exact
                    body.append((pos, 2, _relation(REL_QUOTED_TARGET, action, PRED_TARGETS,
                                                   s["value"], i, s.get("start"), s.get("end"))))
                elif candidates > 1:
                    ambiguous += 1

    body.sort(key=lambda t: (t[0], t[1]))
    rels.extend(r for _p, _o, r in body)

    truncated = len(rels) > MAX_RELATIONS
    rels = rels[:MAX_RELATIONS]
    out["items"] = rels
    out["count"] = len(rels)
    out["truncated"] = truncated
    out["ambiguous"] = ambiguous
    return out


def extract_relations_from_analysis(analysis, slots=None):
    """Relations for an `NLUAnalysis` (or anything analysis-like). Uses
    `analysis.result.normalized_text`, the Prompt 829 slots (computed here
    when not passed) and `analysis.structure["request"]`; never raises and
    never modifies the analysis."""
    try:
        if slots is None:
            slots = extract_slots_from_analysis(analysis)
        result = getattr(analysis, "result", None)
        structure = getattr(analysis, "structure", None)
        request = structure.get("request") if isinstance(structure, dict) else None
        return extract_relations(getattr(result, "normalized_text", None), slots, request)
    except Exception:  # pragma: no cover - defensive: relations are optional
        return empty_relations()
