"""
Runtime integration - bridge (Prompt 910)
=========================================
The first point where the Section 12-18 architecture is consumed by the
real runtime path

    MainActivity -> android_entry.start() -> interface/server.py
      -> POST /api/message -> Core.process_input() -> (route) -> reply

without changing that path. After Core has produced its reply, RuntimeCore hands this
module a plain snapshot of THE TURN THAT JUST HAPPENED, and gets back ONE
structured, deterministic, JSON-safe record describing it:

  build_runtime_result(turn) -> result

`runtime_integration/runtime_core.py` (`RuntimeCore`, the class the server and
Android entry points build) calls it; `Core.process_input()` itself is unchanged.

The bridge is a pure observer. It never produces, replaces or alters a reply
(the reply is already final when it runs), never stores anything, never loads a
model, never runs a capability, and never raises. If it cannot build a richer
result it returns a smaller one, and the reply is exactly what it was.

Reuse (nothing is re-implemented here):
  understood input   the NLU analysis Core already made for this message
                     (understanding.nlu_pipeline.NLUAnalysis, Prompts 824-832
                     semantic view). For a turn on which Core made no analysis
                     (skill match, goal, local-model reply, ...), the SAME
                     pipeline is run read-only through the analyzer Core hands
                     over; that call records nothing into the NLU context.
  reasoning          NLUAnalysis.reasoning_input (833) -> build_reasoning_request
                     (834) -> build_reasoning_plan (835) -> decide_reasoning
                     (836/837) -> evaluate_reasoning_capability_boundary (840).
                     No capability spec is supplied, so no contract is built.
  capability         Core's own capability rows (the CapabilitySystem table) are
                     searched for an EXACT, whole-word capability name in the
                     message. Exactly one distinct hit is projected into a
                     Prompt 841 CapabilityRegistry and run through
                     match_capability (845) and select_capability (846). Zero
                     or several hits select nothing. The Prompt 847 execution
                     boundary is NOT evaluated: it needs an explicit lifecycle
                     state and Core's table has none (a state is never inferred
                     from the `enabled` flag).
  memory / context   what Core's conversation pipeline already selected for this
                     message (recent turns, relevant turns, resolved reference,
                     active topic) - never a second selection.
  local model        Core.get_local_model_readiness(): the existing boundary for a
                     future local language model, reported as it is.

Result keys, always in this order:

  version, status, route,
  input, understood_input, reasoning, capability, memory_context,
  response, local_model, execution, learning   (learning: Prompt 913, observe-only)

  status   "enriched"       understanding and reasoning were both built
           "limited"        a section is unavailable (e.g. AEL input)
           "invalid_input"  the message was empty after normalization
           "bridge_error"   the bridge itself failed (reply unaffected)

  execution   {"allowed": False, "executed": False, "capability_executed":
               False, "code_modified": False, "autonomy_chain_executable":
               False, "external_service_used": False, "model_invoked": <bool>,
               "existing_runtime_effects": [...]}
              `allowed`/`executed` describe THIS BRIDGE and capabilities: they
              are the constant False. `existing_runtime_effects` lists what
              Core's pre-existing path itself already did for this turn (e.g.
              an AEL program was interpreted, a goal was created, a statement
              was learned); the bridge neither causes nor changes those.
              `model_invoked` is True only when a configured local model
              produced the reply.

Nothing here executes a capability, modifies code, calls an external service or
AI, or makes the Section 18 autonomy chain executable (that chain is not even
imported). Pure stdlib plus the existing reasoning / capability modules.
"""

import re

from reasoning.reasoning_foundation import build_reasoning_request
from reasoning.reasoning_plan import build_reasoning_plan
from reasoning.reasoning_decision import decide_reasoning
from reasoning.capability_boundary import evaluate_reasoning_capability_boundary
from capabilities.capability_registry import CapabilityRegistry
from capabilities.capability_matching import match_capability
from capabilities.capability_selection import select_capability

RUNTIME_RESULT_VERSION = 1
REASONING_HANDOFF_VERSION = 1

STATUS_ENRICHED = "enriched"
STATUS_LIMITED = "limited"
STATUS_INVALID_INPUT = "invalid_input"
STATUS_BRIDGE_ERROR = "bridge_error"

ROUTE_EMPTY = "empty_input"
ROUTE_AEL = "ael"
ROUTE_GOAL = "goal"
ROUTE_CONVERSATION = "conversation"
ROUTES = (ROUTE_EMPTY, ROUTE_AEL, ROUTE_GOAL, ROUTE_CONVERSATION)

# Where the final reply text came from (one label per existing return point).
SOURCE_EMPTY_INPUT = "empty_input_prompt"
SOURCE_AEL = "ael_interpreter"
SOURCE_GOAL = "goal_creation"
SOURCE_SKILL = "skill"
SOURCE_LOCAL_MODEL = "local_model"
SOURCE_CORRECTION = "correction_acknowledgement"
SOURCE_PERSIAN_FACT = "persian_nlu_fact"
SOURCE_LEARNED = "learned_statement"
SOURCE_REASONING = "reasoning_engine"
SOURCE_KNOWLEDGE = "knowledge_lookup"
SOURCE_PERSIAN_RESPONSE = "persian_nlu_response"
SOURCE_FALLBACK = "deterministic_fallback"
SOURCE_UNKNOWN = "unknown"
SOURCES = (SOURCE_EMPTY_INPUT, SOURCE_AEL, SOURCE_GOAL, SOURCE_SKILL, SOURCE_LOCAL_MODEL,
           SOURCE_CORRECTION, SOURCE_PERSIAN_FACT, SOURCE_LEARNED, SOURCE_REASONING,
           SOURCE_KNOWLEDGE, SOURCE_PERSIAN_RESPONSE, SOURCE_FALLBACK, SOURCE_UNKNOWN)

# What Core's own, pre-existing path already did for the turn, by reply source.
_EXISTING_EFFECTS = {
    SOURCE_AEL: ("ael_program_interpreted",),
    SOURCE_GOAL: ("goal_created", "empty_plan_created"),
    SOURCE_CORRECTION: ("correction_learning_stored",),
    SOURCE_LEARNED: ("knowledge_learned",),
}

MAX_TEXT_CHARS = 200
MAX_PLAN_STEPS = 8
MAX_CANDIDATES = 8
_WORD = re.compile(r"[a-z0-9]+")


# ---------------------------------------------------------------- helpers

def _clip(value, limit=MAX_TEXT_CHARS):
    if not isinstance(value, str):
        return None
    return value if len(value) <= limit else value[:limit]


def _unavailable(reason):
    return {"available": False, "reason": reason}


def _safe(builder, *args):
    """Run one section builder; a failure makes only that section unavailable."""
    try:
        return builder(*args)
    except Exception:  # noqa: BLE001 - the bridge never raises
        return _unavailable("section_error")


# ------------------------------------------------------------------ input

def _input_section(raw_input, text):
    valid = isinstance(text, str) and bool(text)
    return {
        "raw_type": type(raw_input).__name__,
        "normalized_text": _clip(text) if valid else "",
        "length": len(text) if isinstance(text, str) else 0,
        "valid": valid,
    }


# ------------------------------------------------------- understood input

def _obtain_analysis(turn):
    """(analysis, source). Core's own analysis for this turn when it made one,
    else a read-only run of the same pipeline, else (None, reason)."""
    analysis = turn.get("analysis")
    if analysis is not None:
        return analysis, "core_runtime_analysis"
    if turn.get("route") in (ROUTE_CONVERSATION, ROUTE_GOAL):
        analyzer = turn.get("read_only_analyzer")
        text = turn.get("text")
        if callable(analyzer) and isinstance(text, str) and text:
            return analyzer(text), "pipeline_read_only"
        return None, "no_analyzer"
    if turn.get("route") == ROUTE_AEL:
        return None, "ael_input_bypasses_nlu"
    return None, "no_input_to_analyze"


def _understood_section(analysis, source):
    if analysis is None:
        return _unavailable(source)
    view = analysis.semantic_view()
    return {
        "available": True,
        "source": source,
        "intent": dict(view["intent"]),
        "is_question": bool(analysis.is_question),
        "is_request": bool(analysis.is_request),
        "is_negated": bool(analysis.is_negated),
        "is_correction": bool(analysis.is_correction),
        "context_reference": dict(view["context"]),
        "slots": [dict(s) for s in view["slots"]],
        "relations": [dict(r) for r in view["relations"]],
        "bounds": dict(view["bounds"]),
        "component": _clip(analysis.component),
    }


# -------------------------------------------------------------- reasoning

def _reasoning_section(analysis, nlu_context):
    if analysis is None:
        return _unavailable("no_nlu_analysis_for_this_turn")
    reasoning_input = analysis.reasoning_input(nlu_context)
    request = build_reasoning_request(reasoning_input)
    plan = build_reasoning_plan(request)
    decision = decide_reasoning(request)
    boundary = evaluate_reasoning_capability_boundary(decision)
    next_step = decision.get("next_step")
    section = {
        "available": True,
        "reasoning_input_status": reasoning_input.get("status"),
        "missing": list(reasoning_input.get("missing", [])),
        "request_status": request.get("status"),
        "goal": dict(request.get("goal", {})),
        "next_action": dict(request.get("next_action", {})),
        "plan_status": plan.get("status"),
        "plan_step_count": plan.get("step_count"),
        "plan_steps": [
            {"id": s.get("id"), "kind": s.get("kind"), "ref": s.get("ref")}
            for s in plan.get("steps", [])[:MAX_PLAN_STEPS]
        ],
        "decision": decision.get("decision"),
        "decision_reason": decision.get("reason"),
        "next_step": dict(next_step) if isinstance(next_step, dict) else None,
        "capability_boundary": {
            "decision_state": boundary.get("decision_state"),
            "capability_classification": boundary.get("capability_classification"),
            "contract_valid": boundary.get("contract_valid"),
            "next_stage": boundary.get("next_stage"),
            "reason": boundary.get("reason"),
        },
        "executed": False,
    }
    # Prompt 918: the same request/decision, kept together as one explicit,
    # descriptive handoff for later controlled runtime decisions. Nothing
    # consumes it yet and it never executes anything.
    section["reasoning_handoff"] = {
        "version": REASONING_HANDOFF_VERSION,
        "available": True,
        "descriptive_only": True,
        "request": request,  # fresh dict from build_reasoning_request
        "decision": {
            "decision": decision.get("decision"),
            "reason": decision.get("reason"),
            "next_step": dict(next_step) if isinstance(next_step, dict) else None,
        },
        "plan": {"status": plan.get("status"), "step_count": plan.get("step_count")},
        "capability_boundary": {
            "decision_state": boundary.get("decision_state"),
            "next_stage": boundary.get("next_stage"),
            "reason": boundary.get("reason"),
        },
        "executed": False,
        "consumed_by_runtime": False,
    }
    section["reasoning_ready"] = reasoning_handoff_ready(section["reasoning_handoff"])
    section["reasoning_consumption_state"] = reasoning_consumption_state(section["reasoning_handoff"])
    # Prompt 923: read-only observation of the same handoff; nothing is consumed.
    section["reasoning_observation"] = consume_reasoning_handoff_observation(section["reasoning_handoff"])
    # Prompt 924: internal consumption record built from that observation; the
    # handoff itself is still never marked consumed.
    section["reasoning_consumption_record"] = build_reasoning_consumption_record(section["reasoning_handoff"])
    # Prompt 925: independent copy of the handoff's reasoning objects, only for an
    # accepted record. Nothing is executed and the handoff is never consumed.
    section["reasoning_internal_input"] = build_internal_reasoning_input(section["reasoning_handoff"])
    # Prompt 926: runtime-local consumption record for that internal input. It is
    # only a record: the handoff is not marked consumed and nothing is executed.
    section["reasoning_consumption_result"] = consume_internal_reasoning_input(section["reasoning_internal_input"])
    # Prompt 927: the section's consumption state is the effective runtime state
    # (same key and position as before); the handoff itself is never mutated.
    section["reasoning_consumption_state"] = reasoning_effective_consumption_state(
        section["reasoning_handoff"], section["reasoning_consumption_result"])
    # Prompt 929: non-actionable decision candidate from the consumed result.
    section["reasoning_decision_candidate"] = build_reasoning_decision_candidate(
        section["reasoning_consumption_result"])
    # Prompt 930: structural/safety validation of that candidate. Not actionable.
    section["reasoning_decision_validation"] = validate_reasoning_decision_candidate(
        section["reasoning_decision_candidate"])
    # Prompt 932: deterministic eligibility state derived only from that validation.
    section["reasoning_decision_eligibility"] = reasoning_decision_eligibility(
        section["reasoning_decision_validation"])
    # Prompt 933: final structural checkpoint over the whole chain above.
    section["controlled_reasoning_checkpoint"] = controlled_reasoning_checkpoint(
        section["reasoning_handoff"], section["reasoning_consumption_result"],
        section["reasoning_decision_candidate"], section["reasoning_decision_validation"],
        section["reasoning_decision_eligibility"])
    # Prompt 934: read-only snapshot of the whole controlled chain (copies).
    section["controlled_reasoning_snapshot"] = build_controlled_reasoning_snapshot(
        section["reasoning_handoff"], section["reasoning_consumption_result"],
        section["reasoning_decision_candidate"], section["reasoning_decision_validation"],
        section["reasoning_decision_eligibility"], section["controlled_reasoning_checkpoint"])
    # Prompt 935: structural readiness gate over that snapshot; not actionable.
    section["controlled_reasoning_runtime_ready"] = controlled_reasoning_runtime_ready(
        section["controlled_reasoning_snapshot"])
    # Prompt 936: final read-only integration checkpoint; not actionable.
    section["final_runtime_integration_checkpoint"] = final_runtime_integration_checkpoint(
        section["controlled_reasoning_snapshot"], section["controlled_reasoning_runtime_ready"])
    return section


def reasoning_handoff_ready(handoff):
    """Prompt 921: deterministic readiness observation for a reasoning handoff.
    True only for an available, structurally valid, descriptive-only handoff
    that is not executed and not consumed, with a well-formed request and
    decision. It says nothing about whether the request itself is "ready" and
    triggers nothing. Never raises."""
    try:
        if not isinstance(handoff, dict):
            return False
        if handoff.get("version") != REASONING_HANDOFF_VERSION or isinstance(handoff.get("version"), bool):
            return False
        if (handoff.get("available") is not True or handoff.get("descriptive_only") is not True
                or handoff.get("executed") is not False
                or handoff.get("consumed_by_runtime") is not False):
            return False
        request, decision = handoff.get("request"), handoff.get("decision")
        if not isinstance(request, dict) or not isinstance(decision, dict):
            return False
        next_action = request.get("next_action")
        if not (isinstance(request.get("status"), str) and request["status"]
                and isinstance(request.get("goal"), dict)
                and isinstance(next_action, dict) and next_action.get("executed") is False):
            return False
        if not (isinstance(decision.get("decision"), str) and decision["decision"]):
            return False
        return (isinstance(handoff.get("plan"), dict)
                and isinstance(handoff.get("capability_boundary"), dict))
    except Exception:  # noqa: BLE001
        return False


CONSUMPTION_UNAVAILABLE = "unavailable"
CONSUMPTION_READY_UNCONSUMED = "ready_unconsumed"


def reasoning_consumption_state(handoff):
    """Prompt 922: "ready_unconsumed" for a ready handoff that has not been
    consumed, else "unavailable". Pure observation: it consumes nothing and
    changes nothing. Never raises."""
    try:
        if (reasoning_handoff_ready(handoff) is True
                and handoff.get("consumed_by_runtime") is False):
            return CONSUMPTION_READY_UNCONSUMED
    except Exception:  # noqa: BLE001
        pass
    return CONSUMPTION_UNAVAILABLE


OBSERVATION_OBSERVED_READY = "observed_ready"
OBSERVATION_UNAVAILABLE = "unavailable"


def consume_reasoning_handoff_observation(handoff):
    """Prompt 923: deterministic, read-only observation of a reasoning handoff.
    "observed_ready" for a ready, unconsumed, unexecuted handoff (existing
    readiness logic), else "unavailable". Despite the name it consumes
    nothing: the handoff is never modified, never executed, and
    `consumed_by_runtime` is never set. Always returns a fresh dict; never
    raises."""
    ready = False
    try:
        ready = (reasoning_handoff_ready(handoff) is True
                 and handoff.get("consumed_by_runtime") is False
                 and handoff.get("executed") is False)
    except Exception:  # noqa: BLE001
        ready = False
    return {"available": ready,
            "status": OBSERVATION_OBSERVED_READY if ready else OBSERVATION_UNAVAILABLE,
            "consumed": False, "executed": False, "descriptive_only": True}


CONSUMPTION_RECORD_ACCEPTED = "accepted_for_internal_consumption"


def build_reasoning_consumption_record(handoff):
    """Prompt 924: deterministic internal consumption record. Built from the
    read-only observation (Prompt 923): "accepted_for_internal_consumption"
    for an observed-ready handoff, else "unavailable". It is only a record:
    the handoff is never modified or marked consumed, nothing is executed,
    and `consumed` / `executed` are always False. Always returns a fresh
    dict; never raises."""
    accepted = False
    try:
        observation = consume_reasoning_handoff_observation(handoff)
        accepted = (observation.get("available") is True
                    and observation.get("status") == OBSERVATION_OBSERVED_READY)
    except Exception:  # noqa: BLE001
        accepted = False
    return {"available": accepted,
            "status": CONSUMPTION_RECORD_ACCEPTED if accepted else OBSERVATION_UNAVAILABLE,
            "consumed": False, "executed": False, "descriptive_only": True}


INTERNAL_INPUT_READY = "internal_input_ready"


def _plain_copy(value):
    """Independent copy of plain data (dict / list / tuple / scalars) without
    importing anything new."""
    if isinstance(value, dict):
        return {k: _plain_copy(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain_copy(v) for v in value]
    if isinstance(value, tuple):
        return tuple(_plain_copy(v) for v in value)
    return value


def build_internal_reasoning_input(handoff):
    """Prompt 925: controlled internal reasoning input. Proceeds only when the
    Prompt 924 consumption record is accepted (available, status
    "accepted_for_internal_consumption", not consumed, not executed,
    descriptive-only); then returns a fresh dict carrying independent deep
    copies of the handoff's request, decision, plan and capability_boundary.
    Otherwise returns the unavailable stand-in. Nothing is executed, the
    handoff is never modified or marked consumed. Never raises."""
    try:
        record = build_reasoning_consumption_record(handoff)
        if (record.get("available") is True
                and record.get("status") == CONSUMPTION_RECORD_ACCEPTED
                and record.get("consumed") is False and record.get("executed") is False
                and record.get("descriptive_only") is True):
            return {"available": True, "status": INTERNAL_INPUT_READY,
                    "consumed": False, "executed": False, "descriptive_only": True,
                    "request": _plain_copy(handoff["request"]),
                    "decision": _plain_copy(handoff["decision"]),
                    "plan": _plain_copy(handoff["plan"]),
                    "capability_boundary": _plain_copy(handoff["capability_boundary"])}
    except Exception:  # noqa: BLE001
        pass
    return {"available": False, "status": OBSERVATION_UNAVAILABLE,
            "consumed": False, "executed": False, "descriptive_only": True}


INTERNAL_INPUT_CONSUMED = "consumed"


def consume_internal_reasoning_input(internal_input):
    """Prompt 926: controlled, runtime-local consumption of a valid
    `reasoning_internal_input` (Prompt 925). The result IS the consumption
    record: `consumed=True`, `executed=False`, with an independent plain-data
    copy of the internal input under "internal_input". The argument is never
    mutated and nothing is executed. Unavailable, malformed, already-consumed
    or executed input gives the unavailable stand-in. Never raises."""
    try:
        i = internal_input
        if (isinstance(i, dict)
                and i.get("available") is True and i.get("status") == INTERNAL_INPUT_READY
                and i.get("consumed") is False and i.get("executed") is False
                and i.get("descriptive_only") is True
                and all(isinstance(i.get(k), dict)
                        for k in ("request", "decision", "plan", "capability_boundary"))):
            return {"available": True, "status": INTERNAL_INPUT_CONSUMED,
                    "consumed": True, "executed": False, "descriptive_only": True,
                    "internal_input": _plain_copy(i)}
    except Exception:  # noqa: BLE001
        pass
    return {"available": False, "status": OBSERVATION_UNAVAILABLE,
            "consumed": False, "executed": False, "descriptive_only": True}


CONSUMPTION_CONSUMED = "consumed"


def reasoning_effective_consumption_state(handoff, consumption_result=None):
    """Prompt 927: authoritative runtime consumption state, one of
    "unavailable", "ready_unconsumed", "consumed". "consumed" only for a valid
    successful Prompt 926 consumption result (available, status "consumed",
    consumed True, executed False, descriptive-only, carrying a non-executed
    internal input) that accompanies a still-ready, non-executed handoff;
    anything else falls back to `reasoning_consumption_state(handoff)`. The
    handoff is never mutated and nothing is executed. Never raises."""
    try:
        r = consumption_result
        inner = r.get("internal_input") if isinstance(r, dict) else None
        if (isinstance(r, dict)
                and r.get("available") is True and r.get("status") == INTERNAL_INPUT_CONSUMED
                and r.get("consumed") is True and r.get("executed") is False
                and r.get("descriptive_only") is True
                and isinstance(inner, dict) and inner.get("executed") is False
                and reasoning_handoff_ready(handoff) is True):
            return CONSUMPTION_CONSUMED
    except Exception:  # noqa: BLE001
        pass
    return reasoning_consumption_state(handoff)


DECISION_CANDIDATE = "decision_candidate"


def build_reasoning_decision_candidate(consumption_result):
    """Prompt 929: small deterministic decision candidate from a valid
    successful Prompt 926 consumption result (available, status "consumed",
    consumed True, executed False, descriptive-only, with a valid, non-executed
    `internal_input`). Returns a fresh dict with independent copies of the
    decision, plan and capability_boundary. `actionable` and `executed` are
    always False: nothing is executed or invoked. Anything else gives the
    unavailable stand-in. Never raises."""
    try:
        r = consumption_result
        i = r.get("internal_input") if isinstance(r, dict) else None
        if (isinstance(r, dict)
                and r.get("available") is True and r.get("status") == INTERNAL_INPUT_CONSUMED
                and r.get("consumed") is True and r.get("executed") is False
                and r.get("descriptive_only") is True
                and isinstance(i, dict)
                and i.get("available") is True and i.get("status") == INTERNAL_INPUT_READY
                and i.get("consumed") is False and i.get("executed") is False
                and i.get("descriptive_only") is True
                and all(isinstance(i.get(k), dict)
                        for k in ("request", "decision", "plan", "capability_boundary"))):
            return {"available": True, "status": DECISION_CANDIDATE,
                    "actionable": False, "executed": False, "descriptive_only": True,
                    "decision": _plain_copy(i["decision"]),
                    "plan": _plain_copy(i["plan"]),
                    "capability_boundary": _plain_copy(i["capability_boundary"])}
    except Exception:  # noqa: BLE001
        pass
    return {"available": False, "status": OBSERVATION_UNAVAILABLE,
            "actionable": False, "executed": False, "descriptive_only": True}


DECISION_VALIDATED = "validated"
DECISION_INVALID = "invalid"


def validate_reasoning_decision_candidate(candidate):
    """Prompt 930: structural and safety validation of a decision candidate
    (Prompt 929). "validated" / `eligible=True` only for an available
    "decision_candidate" that is not actionable, not executed, descriptive-only
    and carries dict `decision`, `plan` and `capability_boundary`; anything
    else is "invalid" / `eligible=False`. The result is never actionable and
    nothing is executed. The input is never mutated; never raises."""
    try:
        c = candidate
        if (isinstance(c, dict)
                and c.get("available") is True and c.get("status") == DECISION_CANDIDATE
                and c.get("actionable") is False and c.get("executed") is False
                and c.get("descriptive_only") is True
                and all(isinstance(c.get(k), dict) for k in ("decision", "plan", "capability_boundary"))):
            return {"available": True, "status": DECISION_VALIDATED, "eligible": True,
                    "actionable": False, "executed": False, "descriptive_only": True}
    except Exception:  # noqa: BLE001
        pass
    return {"available": False, "status": DECISION_INVALID, "eligible": False,
            "actionable": False, "executed": False, "descriptive_only": True}


DECISION_ELIGIBLE = "eligible"
DECISION_INELIGIBLE = "ineligible"


def reasoning_decision_eligibility(validation):
    """Prompt 932: deterministic eligibility gate over a Prompt 930 validation
    result. "eligible" only for an available, "validated", `eligible=True`,
    non-actionable, non-executed, descriptive-only validation; anything else is
    "ineligible". It looks at nothing else (not the decision, plan or
    capability boundary), never approves or authorizes anything, and the
    result is never actionable or executed. Fresh dict; never mutates or
    raises."""
    try:
        v = validation
        if (isinstance(v, dict)
                and v.get("available") is True and v.get("status") == DECISION_VALIDATED
                and v.get("eligible") is True and v.get("actionable") is False
                and v.get("executed") is False and v.get("descriptive_only") is True):
            return {"available": True, "status": DECISION_ELIGIBLE, "eligible": True,
                    "actionable": False, "executed": False, "descriptive_only": True}
    except Exception:  # noqa: BLE001
        pass
    return {"available": False, "status": DECISION_INELIGIBLE, "eligible": False,
            "actionable": False, "executed": False, "descriptive_only": True}


CHECKPOINT_READY = "controlled_ready"
CHECKPOINT_NOT_READY = "not_ready"


def _state_flags_safe(state, status, extra=None):
    """True for an available dict with the given status, not actionable, not
    executed, descriptive-only (plus any extra exact key/value pairs)."""
    if not (isinstance(state, dict)
            and state.get("available") is True and state.get("status") == status
            and state.get("actionable") is False and state.get("executed") is False
            and state.get("descriptive_only") is True):
        return False
    return all(state.get(k) is v for k, v in (extra or {}).items())


def controlled_reasoning_checkpoint(handoff, consumption_result, decision_candidate,
                                    validation, eligibility):
    """Prompt 933: final structural/runtime-safety checkpoint over the complete
    controlled reasoning state chain. "controlled_ready" / `available=True` only
    when the handoff is ready (existing readiness logic), the consumption result
    is a valid non-executing internal consumption result, the decision candidate
    is structurally valid, the validation is "validated" with `eligible=True`
    and the eligibility is "eligible" with `eligible=True`; otherwise
    "not_ready" / `available=False`, with each validity flag False for its own
    invalid state. It does not inspect the semantic content of the decision,
    plan or capability boundary. It executes, approves and authorizes nothing:
    `actionable` and `executed` are always False and `descriptive_only` always
    True. Inputs are never mutated or consumed; always returns a fresh dict;
    never raises."""
    def _flag(check):
        try:
            return check() is True
        except Exception:  # noqa: BLE001
            return False

    def _consumption_ok():
        r = consumption_result
        inner = r.get("internal_input") if isinstance(r, dict) else None
        return (isinstance(r, dict)
                and r.get("available") is True and r.get("status") == INTERNAL_INPUT_CONSUMED
                and r.get("consumed") is True and r.get("executed") is False
                and r.get("descriptive_only") is True
                and isinstance(inner, dict) and inner.get("executed") is False
                # these results carry no `actionable` key; if one is present it
                # must be exactly False
                and r.get("actionable", False) is False
                and inner.get("actionable", False) is False)

    handoff_ready = _flag(lambda: reasoning_handoff_ready(handoff))
    consumption_valid = _flag(_consumption_ok)
    candidate_valid = _flag(lambda: validate_reasoning_decision_candidate(
        decision_candidate).get("status") == DECISION_VALIDATED)
    validation_valid = _flag(lambda: _state_flags_safe(
        validation, DECISION_VALIDATED, {"eligible": True}))
    eligibility_valid = _flag(lambda: _state_flags_safe(
        eligibility, DECISION_ELIGIBLE, {"eligible": True}))
    ready = (handoff_ready and consumption_valid and candidate_valid
             and validation_valid and eligibility_valid)
    return {"available": ready,
            "status": CHECKPOINT_READY if ready else CHECKPOINT_NOT_READY,
            "handoff_ready": handoff_ready,
            "consumption_valid": consumption_valid,
            "candidate_valid": candidate_valid,
            "validation_valid": validation_valid,
            "eligibility_valid": eligibility_valid,
            "actionable": False, "executed": False, "descriptive_only": True}


SNAPSHOT_READY = "controlled_ready"
SNAPSHOT_NOT_READY = "not_ready"


def build_controlled_reasoning_snapshot(handoff, consumption_result, decision_candidate,
                                        validation, eligibility, checkpoint):
    """Prompt 934: one small, deterministic, read-only snapshot of the complete
    controlled reasoning state. "controlled_ready" / `available=True` only when
    the supplied Prompt 933 checkpoint is a valid "controlled_ready" checkpoint
    (all five validity flags True, not actionable, not executed,
    descriptive-only) and equals what `controlled_reasoning_checkpoint` derives
    from the supplied states; otherwise "not_ready" / `available=False`. No new
    decision logic. Every nested state is an independent copy (None when the
    argument is not a dict). `actionable` and `executed` are always False and
    `descriptive_only` always True; nothing is executed, approved, authorized
    or invoked, and the arguments are never mutated. Fresh dict; never raises."""
    def _copy(state):
        try:
            return _plain_copy(state) if isinstance(state, dict) else None
        except Exception:  # noqa: BLE001
            return None

    ready = False
    try:
        c = checkpoint
        ready = (isinstance(c, dict)
                 and c.get("available") is True and c.get("status") == CHECKPOINT_READY
                 and all(c.get(k) is True for k in (
                     "handoff_ready", "consumption_valid", "candidate_valid",
                     "validation_valid", "eligibility_valid"))
                 and c.get("actionable") is False and c.get("executed") is False
                 and c.get("descriptive_only") is True
                 and c == controlled_reasoning_checkpoint(
                     handoff, consumption_result, decision_candidate, validation, eligibility))
    except Exception:  # noqa: BLE001
        ready = False
    return {"available": ready,
            "status": SNAPSHOT_READY if ready else SNAPSHOT_NOT_READY,
            "handoff": _copy(handoff), "consumption": _copy(consumption_result),
            "decision_candidate": _copy(decision_candidate), "validation": _copy(validation),
            "eligibility": _copy(eligibility), "checkpoint": _copy(checkpoint),
            "actionable": False, "executed": False, "descriptive_only": True}


RUNTIME_READY = "runtime_ready"
RUNTIME_NOT_READY = "runtime_not_ready"


def controlled_reasoning_runtime_ready(snapshot):
    """Prompt 935: deterministic structural readiness gate over a Prompt 934
    controlled reasoning snapshot. "runtime_ready" / `ready=True` only when the
    snapshot has `available=True`, status "controlled_ready", `actionable=False`,
    `executed=False`, `descriptive_only=True` and dict values for handoff,
    consumption, decision_candidate, validation, eligibility and checkpoint;
    anything else is "runtime_not_ready". It answers only whether the state is
    structurally ready for a future consumer: it does not look inside the
    decision, plan, capability boundary or payloads, and it executes, approves,
    authorizes and invokes nothing. `actionable` and `executed` are always
    False. The input is never mutated; fresh dict; never raises."""
    try:
        s = snapshot
        if (isinstance(s, dict)
                and s.get("available") is True and s.get("status") == SNAPSHOT_READY
                and s.get("actionable") is False and s.get("executed") is False
                and s.get("descriptive_only") is True
                and all(isinstance(s.get(k), dict) for k in (
                    "handoff", "consumption", "decision_candidate",
                    "validation", "eligibility", "checkpoint"))):
            return {"available": True, "status": RUNTIME_READY, "ready": True,
                    "actionable": False, "executed": False, "descriptive_only": True}
    except Exception:  # noqa: BLE001
        pass
    return {"available": False, "status": RUNTIME_NOT_READY, "ready": False,
            "actionable": False, "executed": False, "descriptive_only": True}


INTEGRATION_READY = "integration_ready"
INTEGRATION_NOT_READY = "integration_not_ready"


def final_runtime_integration_checkpoint(snapshot, runtime_ready):
    """Prompt 936: final read-only integration checkpoint over a Prompt 934
    snapshot and its Prompt 935 readiness result. "integration_ready" /
    `ready=True` only when the snapshot is an available "controlled_ready"
    dict, the readiness result is an available "runtime_ready" dict with
    `ready=True`, not actionable, not executed and descriptive-only, and that
    readiness result equals what `controlled_reasoning_runtime_ready` derives
    from the snapshot (existing Prompt 934/935 semantics; no new logic).
    Anything else is "integration_not_ready". It does not look inside the
    decision, plan, capability boundary or payloads, and executes, approves,
    authorizes and invokes nothing. `actionable` and `executed` are always
    False. Inputs are never mutated; fresh dict; never raises."""
    try:
        s, r = snapshot, runtime_ready
        if (isinstance(s, dict) and s.get("available") is True
                and s.get("status") == SNAPSHOT_READY
                and isinstance(r, dict)
                and r.get("available") is True and r.get("status") == RUNTIME_READY
                and r.get("ready") is True and r.get("actionable") is False
                and r.get("executed") is False and r.get("descriptive_only") is True
                and r == controlled_reasoning_runtime_ready(s)):
            return {"available": True, "status": INTEGRATION_READY, "ready": True,
                    "actionable": False, "executed": False, "descriptive_only": True}
    except Exception:  # noqa: BLE001
        pass
    return {"available": False, "status": INTEGRATION_NOT_READY, "ready": False,
            "actionable": False, "executed": False, "descriptive_only": True}


BOUNDARY_STRUCTURALLY_INTEGRATED = "structurally_integrated"
BOUNDARY_PARTIALLY_INTEGRATED = "partially_integrated"
BOUNDARY_NOT_INTEGRATED = "not_integrated"
BOUNDARY_AREAS = (
    "controlled_reasoning_integration", "local_model_runtime", "memory_runtime",
    "AEL_learning_runtime", "capability_runtime", "upgrade_runtime", "android_runtime_bridge")
# Areas whose runtime path has no executor at all (the controlled reasoning chain is
# descriptive, the capability registry is never run by the bridge, and the upgrade /
# self-evolution engine is declarative): evidence claiming execution is contradictory.
_BOUNDARY_NON_EXECUTABLE_AREAS = (
    "controlled_reasoning_integration", "capability_runtime", "upgrade_runtime")
_BOUNDARY_FLAGS = ("exists", "connected_to_runtime_core", "activated_in_runtime_path",
                   "execution_capable")


def _boundary_area_result(status, reason, exists=False, connected=False, activated=False,
                          capable=False):
    return {"status": status, "reason": reason, "exists": exists,
            "connected_to_runtime_core": connected, "activated_in_runtime_path": activated,
            "execution_capable": capable, "descriptive_only": not capable}


def _boundary_classify_area(name, evidence):
    """One area: (area result, evidence_was_usable). Strict booleans only."""
    if not isinstance(evidence, dict):
        return _boundary_area_result(BOUNDARY_NOT_INTEGRATED, "missing_evidence"), False
    flags = [evidence.get(k) for k in _BOUNDARY_FLAGS]
    if not all(isinstance(f, bool) for f in flags):
        return _boundary_area_result(BOUNDARY_NOT_INTEGRATED, "malformed_evidence"), False
    exists, connected, activated, capable = flags
    if ((connected and not exists) or (activated and not connected)
            or (capable and not activated)
            or (capable and name in _BOUNDARY_NON_EXECUTABLE_AREAS)):
        return _boundary_area_result(BOUNDARY_NOT_INTEGRATED, "contradictory_evidence"), True
    if not exists:
        return _boundary_area_result(BOUNDARY_NOT_INTEGRATED, "not_present"), True
    if not connected:
        return _boundary_area_result(
            BOUNDARY_PARTIALLY_INTEGRATED, "exists_not_connected_to_runtime_core",
            exists=True), True
    reason = ("execution_capable_in_runtime_path" if capable
              else "activated_not_execution_capable" if activated
              else "connected_not_activated")
    return _boundary_area_result(BOUNDARY_STRUCTURALLY_INTEGRATED, reason, True, True,
                                 activated, capable), True


def _boundary_result(available, status, areas):
    names = BOUNDARY_AREAS
    return {
        "available": available,
        "status": status,
        "structurally_integrated": all(
            areas[n]["status"] == BOUNDARY_STRUCTURALLY_INTEGRATED for n in names),
        "runtime_connected": all(areas[n]["connected_to_runtime_core"] for n in names),
        "execution_capable": all(areas[n]["execution_capable"] for n in names),
        "descriptive_only": True,
        "actionable": False,
        "executed": False,
        "structurally_integrated_areas": [
            n for n in names if areas[n]["status"] == BOUNDARY_STRUCTURALLY_INTEGRATED],
        "activated_areas": [n for n in names if areas[n]["activated_in_runtime_path"]],
        "execution_capable_areas": [n for n in names if areas[n]["execution_capable"]],
        "areas": areas,
    }


def _boundary_safe_state():
    return _boundary_result(
        False, BOUNDARY_NOT_INTEGRATED,
        {n: _boundary_area_result(BOUNDARY_NOT_INTEGRATED, "missing_evidence")
         for n in BOUNDARY_AREAS})


def final_runtime_integration_boundary_validation(evidence=None):
    """Prompt 937: descriptive classification of the EXISTING runtime integration.
    `evidence` maps each area in BOUNDARY_AREAS to a dict of four strict booleans
    that keep four things apart: `exists` (the architecture is in the codebase),
    `connected_to_runtime_core` (RuntimeCore/Core wires it), `activated_in_runtime_path`
    (observed live in the real runtime path) and `execution_capable` (observed able to
    do real work there). Each area is "structurally_integrated" (exists and connected),
    "partially_integrated" (exists, not connected) or "not_integrated" (absent,
    missing/malformed evidence, or contradictory evidence: connected without existing,
    activated without connected, execution_capable without activated, or execution
    claimed for an area with no executor). Existence or connection alone never makes an
    area activated or execution_capable. The overall status is "structurally_integrated"
    only when every area is; a non-dict, empty or wholly unusable `evidence` yields the
    exact safe state (`available` False, everything False). It executes, invokes,
    modifies, grants and enables nothing; `actionable` and `executed` are always False.
    The input is never mutated; the result is a fresh dict; never raises."""
    try:
        if not isinstance(evidence, dict):
            return _boundary_safe_state()
        areas, usable = {}, 0
        for name in BOUNDARY_AREAS:
            areas[name], ok = _boundary_classify_area(name, evidence.get(name))
            usable += 1 if ok else 0
        if usable == 0:
            return _boundary_safe_state()
        statuses = [a["status"] for a in areas.values()]
        if all(s == BOUNDARY_STRUCTURALLY_INTEGRATED for s in statuses):
            status = BOUNDARY_STRUCTURALLY_INTEGRATED
        elif all(s == BOUNDARY_NOT_INTEGRATED for s in statuses):
            status = BOUNDARY_NOT_INTEGRATED
        else:
            status = BOUNDARY_PARTIALLY_INTEGRATED
        return _boundary_result(True, status, areas)
    except Exception:  # noqa: BLE001
        return _boundary_safe_state()


def unavailable_reasoning_handoff(reason="no_reasoning_for_this_turn"):
    """Safe stand-in when a turn has no reasoning section (AEL, goal, empty
    input, bridge error): descriptive, never executed."""
    return {"available": False, "reason": reason, "descriptive_only": True,
            "executed": False, "consumed_by_runtime": False}


# ------------------------------------------------------------- capability

def _row_get(row, key):
    try:
        return row[key]
    except Exception:  # noqa: BLE001
        return None


def _name_words(name):
    return tuple(w for w in name.split("_") if w)


def _find_named_capabilities(text, rows):
    """Capability rows whose full name appears in `text` as a whole-word
    sequence ("code analysis" / "code_analysis" / "Code-Analysis"). Exact
    whole-word matching only: no stemming, alias, fuzzy or semantic match."""
    tokens = tuple(_WORD.findall(text.lower()))
    found = {}
    for row in rows:
        name = _row_get(row, "name")
        if not isinstance(name, str) or not name:
            continue
        words = _name_words(name)
        if not words:
            continue
        size = len(words)
        for i in range(len(tokens) - size + 1):
            if tokens[i:i + size] == words:
                found.setdefault(name, row)
                break
    return [found[n] for n in sorted(found)]


def _project_row(row):
    """Prompt 841 descriptor for one Core capability row. The table has no
    inputs/outputs/constraints, so the projection declares none beyond the one
    output the descriptor rule requires; it is a lookup shape, not a promise
    that anything can run."""
    return {
        "name": _row_get(row, "name"),
        "version": 1,
        "purpose": _row_get(row, "description"),
        "inputs": [],
        "outputs": ["capability_result"],
        "constraints": [],
        "enabled": bool(_row_get(row, "enabled")),
    }


def _capability_base(status, reason):
    return {
        "identified": False,
        "status": status,
        "reason": reason,
        "name": None,
        "version": None,
        "core_enabled": None,
        "core_status": None,
        "candidates": [],
        "selection": None,
        "execution_boundary": "not_evaluated_no_explicit_lifecycle_state",
        "execution_allowed": False,
        "executed": False,
    }


def _capability_section(text, rows):
    if not isinstance(text, str) or not text:
        return _capability_base("none", "no_input")
    if not rows:
        return _capability_base("none", "no_capabilities_registered")
    hits = _find_named_capabilities(text, rows)
    if not hits:
        return _capability_base("none", "no_capability_named")
    names = [_row_get(r, "name") for r in hits]
    if len(hits) > 1:
        section = _capability_base("ambiguous", "multiple_capabilities_named")
        section["candidates"] = names[:MAX_CANDIDATES]
        return section

    row = hits[0]
    section = _capability_base("none", "not_selected")
    section["candidates"] = names
    section["core_enabled"] = bool(_row_get(row, "enabled"))
    section["core_status"] = _row_get(row, "status")

    registry = CapabilityRegistry()
    registration = registry.register(_project_row(row))
    if registration.get("status") != "registered":
        section["status"] = "unresolved"
        section["reason"] = "registry_" + str(registration.get("reason"))
        return section
    match = match_capability({"name": names[0]}, registry)
    selection = select_capability(match)
    section["selection"] = {
        "match_status": match.get("status"),
        "status": selection.get("status"),
        "reason": selection.get("reason"),
        "candidate_count": selection.get("candidate_count"),
    }
    if selection.get("status") == "selected":
        selected = selection["selected"]
        section.update({
            "identified": True,
            "status": "suggested",
            "reason": "exact_name_in_message",
            "name": selected["identity"]["name"],
            "version": selected["version"],
        })
    else:
        section["status"] = "unresolved"
        section["reason"] = "selection_" + str(selection.get("reason"))
    return section


# ---------------------------------------------------------- memory/context

MEMORY_NONE = "no_memory_available"
MEMORY_AVAILABLE_UNUSED = "available_not_used"
MEMORY_USED = "available_and_used"
MEMORY_MALFORMED = "unavailable_malformed_memory"


def _memory_state(available, used, malformed=False):
    """memory_available: earlier turns exist. memory_used: Core's own pipeline
    selected relevant turns or resolved a reference for THIS turn. Neither is
    ever inferred beyond what Core already computed."""
    available, used = bool(available) and not malformed, bool(used) and not malformed
    state = (MEMORY_MALFORMED if malformed else MEMORY_USED if used
             else MEMORY_AVAILABLE_UNUSED if available else MEMORY_NONE)
    return {"memory_available": available, "memory_used": used, "memory_state": state}


def _memory_section(turn):
    raw_state = turn.get("memory")
    malformed = raw_state is not None and not isinstance(raw_state, dict)
    state = raw_state if isinstance(raw_state, dict) else {}
    if malformed:
        section = _empty_memory()
        section.update(_memory_state(False, False, True))
        return section
    relevant = state.get("relevant_context")
    selected = list(getattr(relevant, "selected", None) or [])
    reference = state.get("resolved_reference")
    topic = state.get("active_topic")
    nlu_ctx = turn.get("nlu_context")
    try:
        before = int(state.get("turns_available_before") or 0)
    except (TypeError, ValueError):
        return dict(_empty_memory(), **_memory_state(False, False, True))
    used = bool(selected) or bool(
        reference is not None and getattr(reference, "has_reference", False)
        and not getattr(reference, "ambiguous", False))
    return {
        "turns_available_before": before,
        "relevance_computed": relevant is not None,
        "relevant_turn_count": len(selected),
        "relevant_turn_indexes": [s.get("index") for s in selected if isinstance(s, dict)],
        "reference": (
            {"has_reference": bool(reference.has_reference),
             "ambiguous": bool(reference.ambiguous),
             "reason": _clip(reference.reason)}
            if reference is not None else None),
        "active_topic": _clip(getattr(topic, "topic", None)) if topic is not None else None,
        "nlu_turns_recorded": int(getattr(nlu_ctx, "turn_count", 0) or 0),
        **_memory_state(before > 0, used),
    }


def _empty_memory():
    return {
        "turns_available_before": 0, "relevance_computed": False,
        "relevant_turn_count": 0, "relevant_turn_indexes": [], "reference": None,
        "active_topic": None, "nlu_turns_recorded": 0}


# ------------------------------------------------------------- local model

STATE_NO_LOCAL_MODEL = "unavailable_no_local_model_running"
STATE_LOCAL_MODEL_READY = "available_local_model_ready"


def _local_model_state(ready, generated):
    """The four explicit local-model fields (appended to the section)."""
    return {
        "available": bool(ready),
        "state": STATE_LOCAL_MODEL_READY if ready else STATE_NO_LOCAL_MODEL,
        "generated_by_local_model": bool(generated),
        "model_invoked": bool(generated),
    }


def _local_model_section(turn):
    readiness = turn.get("model_readiness")
    status = getattr(readiness, "status", None)
    ready = bool(getattr(readiness, "ready", False))
    generated = turn.get("response_source") == SOURCE_LOCAL_MODEL
    return {
        "backend_kind": _clip(turn.get("backend_kind")),
        "readiness_status": _clip(status) if isinstance(status, str) else "unknown",
        "error_code": _clip(getattr(readiness, "error_code", None)),
        "real_backend_connected": ready,
        "boundary": "Core.use_local_language_model",
        "generated_this_turn": generated,
        **_local_model_state(ready, generated),
    }


# --------------------------------------------------------------- execution

def _execution_section(source, effects=None):
    if isinstance(effects, (list, tuple)):
        listed = [e for e in effects if isinstance(e, str)][:MAX_CANDIDATES]
    else:
        listed = list(_EXISTING_EFFECTS.get(source, ()))
    return {
        "allowed": False,
        "executed": False,
        "capability_executed": False,
        "code_modified": False,
        "autonomy_chain_executable": False,
        "external_service_used": False,
        "model_invoked": source == SOURCE_LOCAL_MODEL,
        "existing_runtime_effects": listed,
    }


def _response_section(source):
    return {
        "source": source,
        "deterministic_fallback": source == SOURCE_FALLBACK,
        "generated_by_local_model": source == SOURCE_LOCAL_MODEL,
    }


# ---------------------------------------------------------------- learning

LEARNING_NONE = "no_learning_request"
LEARNING_DETECTED = "explicit_learning_request_detected"
LEARNING_UNAVAILABLE = "learning_request_unavailable"
LEARNING_MALFORMED = "unavailable_malformed_learning_input"
# Explicit teaching keywords the existing AEL parser already recognizes.
_TEACH_KEYWORDS = ("TEACH", "RELATE")
# Effects Core's own pre-existing path reports when it itself stored something.
_LEARNING_EFFECTS = ("knowledge_learned", "correction_learning_stored", "personal_fact_stored")


# What the existing runtime did with a detected request (Prompt 914).
OUTCOME_NOT_A_REQUEST = "not_a_learning_request"
OUTCOME_PERFORMED = "performed_by_existing_runtime"
OUTCOME_INTERPRETED = "interpreted_not_performed"
OUTCOME_UNAVAILABLE = "learning_unavailable"
OUTCOME_MALFORMED = "malformed_or_unparsed"


# What the existing runtime did with a RELATE (Prompt 915). Only the existing
# LearningSystem.relate() return value ({"created": bool}) is evidence that a
# relationship is new; an interpreter instruction that merely succeeded is not.
RELATE_NOT_REQUESTED = "not_a_relate_request"
RELATE_CREATED = "new_relationship_created"
RELATE_ALREADY_EXISTED = "relationship_already_existed"
RELATE_UNCONFIRMED = "executed_persistence_unconfirmed"
RELATE_FAILED = "relate_failed_or_malformed"
RELATE_MIXED = "mixed"


def _relate_base(persistence=RELATE_NOT_REQUESTED, requested=0, executed=0, failed=0,
                 created=0, existed=0):
    return {
        "relate_requested": requested > 0,
        "relate_instructions_requested": int(requested),
        "relate_instructions_executed": int(executed),
        "relate_instructions_failed": int(failed),
        "relationships_created": int(created),
        "relationships_already_existed": int(existed),
        "relate_persistence": persistence,
    }


def _relate_observation(text, ael, outcomes):
    """RELATE-only counts from the per-instruction results Core's path produced
    (`ael`: [(kind, success)]) and the `created` flags LearningSystem.relate()
    itself returned (`outcomes`, one per call that returned). Nothing is run
    or inferred: if the flags do not line up with the executed instructions,
    persistence is reported as unconfirmed rather than guessed."""
    results = ael or []
    executed = sum(1 for k, ok in results if k == "RELATE" and ok)
    failed = sum(1 for k, ok in results if k == "RELATE" and not ok)
    words = text.split(None, 1) if isinstance(text, str) else []
    if any(k is None for k, _ in results) and words and words[0] == "RELATE":
        failed += 1  # RELATE that never parsed into an instruction
    requested = executed + failed
    if requested == 0:
        return _relate_base()
    flags = None
    if isinstance(outcomes, (list, tuple)) and all(isinstance(o, bool) for o in outcomes):
        flags = list(outcomes)
    if flags is not None and len(flags) == executed:
        created, existed = sum(1 for o in flags if o), sum(1 for o in flags if not o)
        if executed == 0:
            persistence = RELATE_FAILED
        elif failed == 0 and existed == 0:
            persistence = RELATE_CREATED
        elif failed == 0 and created == 0:
            persistence = RELATE_ALREADY_EXISTED
        else:
            persistence = RELATE_MIXED
        return _relate_base(persistence, requested, executed, failed, created, existed)
    if flags is None and executed == 0:
        return _relate_base(RELATE_FAILED, requested, executed, failed)
    return _relate_base(RELATE_UNCONFIRMED, requested, executed, failed)


def _learning_base(state, available=False, requested=False, kind=None, performed=False,
                   outcome=None, performed_count=0, relate=None):
    return {
        "learning_available": bool(available),
        "learning_requested": bool(requested),
        "learning_state": state,
        "request_kind": kind,
        "learning_executed_by_bridge": False,
        "learning_performed_by_existing_runtime": bool(performed),
        "learning_outcome": outcome or (OUTCOME_PERFORMED if performed else OUTCOME_NOT_A_REQUEST),
        "ael_learning_instructions_performed": int(performed_count),
        **(relate if relate is not None else _relate_base()),
    }


def error_learning_section():
    return _learning_base(LEARNING_MALFORMED, outcome=OUTCOME_MALFORMED)


def _ael_learning_results(raw):
    """Clean per-instruction AEL results Core's own path produced
    ({"kind", "success"}); None when the turn supplied none."""
    if not isinstance(raw, (list, tuple)):
        return None
    cleaned = []
    for item in raw[:MAX_CANDIDATES]:
        if isinstance(item, dict):
            kind = item.get("kind")
            cleaned.append((kind if isinstance(kind, str) else None, item.get("success") is True))
    return cleaned


def _learning_section(turn, analysis, effects):
    """Observe-only. A request is `explicit` only when the user typed an AEL
    TEACH/RELATE statement or Core's own NLU flagged a correction; ordinary
    conversation is never classified as a request. Nothing is ever run.
    `performed` is true only when Core's own path reports it stored something:
    a successful AEL TEACH/RELATE (LearningSystem.teach/relate ran) or one of
    the conversation-path storage effects. Merely interpreting an AEL
    statement, or a failed one, is never reported as learning."""
    text = turn.get("text")
    if text is not None and not isinstance(text, str):
        return error_learning_section()
    available = turn.get("learning_available") is True
    kind = None
    ael = _ael_learning_results(turn.get("ael_results")) if turn.get("route") == ROUTE_AEL else None
    if isinstance(text, str) and text:
        words = text.split(None, 1)
        if turn.get("route") == ROUTE_AEL and words and words[0] in _TEACH_KEYWORDS:
            kind = "ael_" + words[0].lower()
        elif turn.get("route") == ROUTE_AEL and ael:
            later = [k for k, _ in ael if k in _TEACH_KEYWORDS]
            if later:
                kind = "ael_" + later[0].lower()
        elif analysis is not None and getattr(analysis, "is_correction", False) is True:
            kind = "correction"
    ael_done = sum(1 for k, ok in (ael or []) if ok and k in _TEACH_KEYWORDS)
    relate = _relate_observation(text, ael, turn.get("relate_outcomes"))
    if not available and relate["relate_persistence"] in (RELATE_CREATED, RELATE_ALREADY_EXISTED,
                                                           RELATE_MIXED):
        relate = _relate_base(RELATE_UNCONFIRMED, relate["relate_instructions_requested"],
                              relate["relate_instructions_executed"],
                              relate["relate_instructions_failed"])
    performed = ael_done > 0 or any(e in _LEARNING_EFFECTS for e in effects)
    if kind is None:
        return _learning_base(LEARNING_NONE, available, False, None, performed,
                              OUTCOME_PERFORMED if performed else OUTCOME_NOT_A_REQUEST, ael_done,
                              relate)
    state = LEARNING_DETECTED if available else LEARNING_UNAVAILABLE
    if not available:
        outcome = OUTCOME_UNAVAILABLE
    elif performed:
        outcome = OUTCOME_PERFORMED
    elif ael is not None and any(k is None for k, _ in ael):
        outcome = OUTCOME_MALFORMED
    else:
        outcome = OUTCOME_INTERPRETED
    return _learning_base(state, available, True, kind, performed and available, outcome, ael_done,
                          relate)


def _learning_safe(turn, analysis, source):
    try:
        effects = _execution_section(
            source, turn.get("existing_runtime_effects"))["existing_runtime_effects"]
        return _learning_section(turn, analysis, effects)
    except Exception:  # noqa: BLE001
        return error_learning_section()


# ----------------------------------------------------------------- builder

def error_runtime_result(route=ROUTE_CONVERSATION, source=SOURCE_UNKNOWN):
    """The minimal safe result: every section unavailable, nothing allowed."""
    return {
        "version": RUNTIME_RESULT_VERSION,
        "status": STATUS_BRIDGE_ERROR,
        "route": route if route in ROUTES else ROUTE_CONVERSATION,
        "input": {"raw_type": None, "normalized_text": "", "length": 0, "valid": False},
        "understood_input": _unavailable("bridge_error"),
        "reasoning": _unavailable("bridge_error"),
        "capability": _capability_base("none", "bridge_error"),
        "memory_context": dict(_empty_memory(), **_memory_state(False, False)),
        "response": _response_section(source if source in SOURCES else SOURCE_UNKNOWN),
        "local_model": {
            "backend_kind": None, "readiness_status": "unknown", "error_code": None,
            "real_backend_connected": False, "boundary": "Core.use_local_language_model",
            "generated_this_turn": False, **_local_model_state(False, False)},
        "execution": _execution_section(SOURCE_UNKNOWN),
        "learning": _learning_base(LEARNING_NONE),
    }


def build_runtime_result(turn):
    """The structured runtime result for one finished turn. `turn` is a plain
    dict supplied by Core (keys: raw_input, text, route, response_source,
    analysis, read_only_analyzer, nlu_context, memory, capability_rows,
    model_readiness, backend_kind, existing_runtime_effects); anything missing or malformed only makes
    the matching section smaller. Observes only; never raises."""
    try:
        if not isinstance(turn, dict):
            return error_runtime_result()
        route = turn.get("route")
        if route not in ROUTES:
            route = ROUTE_CONVERSATION
        source = turn.get("response_source")
        if source not in SOURCES:
            source = SOURCE_UNKNOWN
        text = turn.get("text")
        input_section = _input_section(turn.get("raw_input"), text)

        if not input_section["valid"]:
            result = error_runtime_result(route, source)
            result["status"] = STATUS_INVALID_INPUT
            result["route"] = ROUTE_EMPTY
            result["input"] = input_section
            result["understood_input"] = _unavailable("no_input_to_analyze")
            result["reasoning"] = _unavailable("no_input_to_analyze")
            result["capability"] = _capability_base("none", "no_input")
            result["memory_context"] = _memory_section(turn)
            result["local_model"] = _local_model_section(dict(turn, response_source=source))
            if text is not None and not isinstance(text, str):
                result["learning"] = error_learning_section()
            return result

        try:
            analysis, analysis_source = _obtain_analysis(turn)
        except Exception:  # noqa: BLE001
            analysis, analysis_source = None, "analysis_error"

        understood = _safe(_understood_section, analysis, analysis_source)
        reasoning = _safe(_reasoning_section, analysis, turn.get("nlu_context"))
        capability = _safe(_capability_section, text, turn.get("capability_rows") or [])
        if "execution_allowed" not in capability:  # builder failed: keep the safe shape
            capability = _capability_base("none", "section_error")

        enriched = understood.get("available") is True and reasoning.get("available") is True
        return {
            "version": RUNTIME_RESULT_VERSION,
            "status": STATUS_ENRICHED if enriched else STATUS_LIMITED,
            "route": route,
            "input": input_section,
            "understood_input": understood,
            "reasoning": reasoning,
            "capability": capability,
            "memory_context": _safe(_memory_section, turn),
            "response": _response_section(source),
            "local_model": _safe(_local_model_section, dict(turn, response_source=source)),
            "execution": _execution_section(source, turn.get("existing_runtime_effects")),
            "learning": _learning_safe(turn, analysis, source),
        }
    except Exception:  # noqa: BLE001 - the bridge never raises
        return error_runtime_result()
