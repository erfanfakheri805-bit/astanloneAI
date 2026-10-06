"""
Understanding - meaning resolution bridge (Prompt 832)
======================================================
Resolves ONLY the references a message states explicitly, using what the
existing NLU stack already produced (the Prompt 831 semantic view, which
carries the Prompt 827 context reference). Cues it understands are the
ones the context block already detected: "again" (دوباره, مجددا, یه بار
دیگه ...), a pointer back (همونو, همون, قبلی, مثل قبل ...) and a
continuation marker (و, پس, ولی ...). Nothing is detected here and nothing
is invented: the bridge only reports what those cues point at.

  resolve_references(subject, context=None)

`subject` is an `NLUAnalysis` or a semantic view dict. `context` is an
optional `NLUConversationContext`, only READ (`turn_at`) to confirm that the
referenced turn still exists and to report its intent / text.

Result (always the same keys, in this order):

  {"version", "status", "reason", "cues", "continuation",
   "primary_intent", "effective_intent", "inherited_intent",
   "referenced_turn", "referenced"}

  status   "none"        no reference cue in the message
           "resolved"    a cue points at an existing earlier turn
           "unresolved"  a cue is present but nothing can be pointed at
                         (first turn / after a context reset / turn already
                         dropped from the bounded context)
           "ambiguous"   the available facts contradict each other; nothing
                         is trusted beyond the message's own intent
  reason   None, or one of: "no_previous_turn", "referenced_turn_unavailable",
           "context_mismatch", "invalid_reference"
  cues     subset of ["again", "reference", "continuation"], in that order
  referenced   None, or {"turn_index", "intent", "text"} of the earlier turn
               (only when `context` was given and still retains it; text is
               cut at MAX_TEXT_CHARS)

`inherited_intent` and `referenced_turn` are copied from the view and kept
only for "resolved". For every other status they are None and
`effective_intent` is the message's own primary intent.

Bounded (fixed small output), JSON-safe, deterministic, never raises, never
modifies the analysis, view or context, and always returns a fresh dict.
Pure stdlib; no Memory, AEL, Core, storage or learning.
"""

from .nlu_semantic_view import build_semantic_view, semantic_view_from_normalized

RESOLUTION_VERSION = 1
MAX_TEXT_CHARS = 200

STATUS_NONE = "none"
STATUS_RESOLVED = "resolved"
STATUS_UNRESOLVED = "unresolved"
STATUS_AMBIGUOUS = "ambiguous"

REASON_NO_PREVIOUS_TURN = "no_previous_turn"
REASON_TURN_UNAVAILABLE = "referenced_turn_unavailable"
REASON_CONTEXT_MISMATCH = "context_mismatch"
REASON_INVALID_REFERENCE = "invalid_reference"

CUE_AGAIN = "again"
CUE_REFERENCE = "reference"
CUE_CONTINUATION = "continuation"


def empty_resolution():
    return {
        "version": RESOLUTION_VERSION, "status": STATUS_NONE, "reason": None,
        "cues": [], "continuation": None,
        "primary_intent": "unknown", "effective_intent": "unknown",
        "inherited_intent": None, "referenced_turn": None, "referenced": None,
    }


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_view(subject):
    return (isinstance(subject, dict) and isinstance(subject.get("intent"), dict)
            and isinstance(subject.get("context"), dict))


def _as_view(subject):
    if _is_view(subject):
        return subject
    if isinstance(subject, dict):          # a normalized() dict
        return semantic_view_from_normalized(subject)
    return build_semantic_view(subject)


def _turn(context, index):
    """The retained turn with absolute `index`, or None. Never raises."""
    try:
        return context.turn_at(index) if context is not None else None
    except Exception:
        return None


def resolve_references(subject, context=None):
    """Resolve the explicit references of `subject` (see module docstring)."""
    out = empty_resolution()
    try:
        view = _as_view(subject)
        intent = view.get("intent") if isinstance(view.get("intent"), dict) else {}
        ctx = view.get("context") if isinstance(view.get("context"), dict) else {}
        primary = intent.get("primary") if isinstance(intent.get("primary"), str) else "unknown"
        out["primary_intent"] = out["effective_intent"] = primary

        cues = []
        if ctx.get("again") is True:
            cues.append(CUE_AGAIN)
        if ctx.get("refers_to_previous") is True:
            cues.append(CUE_REFERENCE)
        marker = ctx.get("continuation")
        if isinstance(marker, str) and marker:
            cues.append(CUE_CONTINUATION)
            out["continuation"] = marker
        out["cues"] = cues
        if not cues:
            return out

        turn_index = ctx.get("turn_index")
        ref_turn = ctx.get("referenced_turn")
        inherited = ctx.get("inherited_intent")
        if not _is_int(ref_turn):
            out["status"], out["reason"] = STATUS_UNRESOLVED, REASON_NO_PREVIOUS_TURN
            return out
        if (_is_int(turn_index) and ref_turn >= turn_index) or ref_turn < 0 \
                or (inherited is not None and not isinstance(inherited, str)):
            out["status"], out["reason"] = STATUS_AMBIGUOUS, REASON_INVALID_REFERENCE
            return out

        referenced = None
        if context is not None:
            turn = _turn(context, ref_turn)
            if turn is None:
                out["status"], out["reason"] = STATUS_UNRESOLVED, REASON_TURN_UNAVAILABLE
                return out
            t_intent = getattr(turn, "intent", None)
            t_text = getattr(turn, "normalized_text", None)
            if isinstance(inherited, str) and t_intent != inherited:
                out["status"], out["reason"] = STATUS_AMBIGUOUS, REASON_CONTEXT_MISMATCH
                return out
            referenced = {"turn_index": ref_turn,
                          "intent": t_intent if isinstance(t_intent, str) else None,
                          "text": t_text[:MAX_TEXT_CHARS] if isinstance(t_text, str) else None}

        out["status"] = STATUS_RESOLVED
        out["referenced_turn"] = ref_turn
        out["referenced"] = referenced
        if isinstance(inherited, str):
            out["inherited_intent"] = inherited
            out["effective_intent"] = inherited
        return out
    except Exception:  # pragma: no cover - defensive: the bridge is optional
        return empty_resolution()
