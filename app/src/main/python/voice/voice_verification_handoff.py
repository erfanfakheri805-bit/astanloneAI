"""
Voice Verification Execution Handoff (Prompt 810, Section 10 - Jarvis Final: Voice, Integration & Controlled Improvement)
========================================================================================================================
A small deterministic handoff that connects the EXISTING `VoiceVerificationDecision` (Prompt 809) to the EXISTING `VoiceVerificationPlan` (Prompt 800).
It only DESCRIBES whether a plan may be handed on; it executes nothing. It follows the immutable result/decision conventions of Prompts 799, 808 and 809.

    create_voice_verification_handoff(decision, plan) -> VoiceVerificationHandoff(approved, profile_id, failure_codes)

PLAN CONTRACT NOTE
The existing `VoiceVerificationPlan` stores its values directly (`request_id`, `profile_id`, `verification_mode`) and has no `request` attribute, so the
profile match compares `decision.profile_id` with the plan's own public `plan.profile_id`. No plan or request contract is changed.

RULES (checked in this order; only public properties are read, private internals are never inspected)
1. `decision` must be exactly a `VoiceVerificationDecision` and `plan` exactly a `VoiceVerificationPlan` (subclass-free `type(...) is` checks; None, dicts,
   look-alikes and objects that spoof `__class__` are invalid). Otherwise `VOICE_VERIFICATION_HANDOFF_INVALID_INPUT`; nothing is read from either object.
2. A decision whose `approved` is exactly False gives `VOICE_VERIFICATION_HANDOFF_REJECTED_DECISION`. The plan is not read and no approved handoff exists.
3. A decision whose `approved` is neither exactly True nor exactly False, an approved decision whose `profile_id` is not an exact non-empty `str`, a plan whose
   `profile_id` is not an exact non-empty `str`, or any public read that raises gives `VOICE_VERIFICATION_HANDOFF_INVALID_INPUT`.
4. An approved decision whose `profile_id` differs from `plan.profile_id` (exact string comparison, nothing normalized) gives
   `VOICE_VERIFICATION_HANDOFF_PROFILE_MISMATCH`.
5. Otherwise the handoff is APPROVED with `profile_id` exactly the decision's string and no failure codes.
Approval means only that the decision and the plan name the same profile. Nothing is executed, dispatched or verified.

FAILURE CODES (stable, prefix `VOICE_VERIFICATION_HANDOFF_`): `INVALID_INPUT`, `REJECTED_DECISION`, `PROFILE_MISMATCH`. A rejected handoff has exactly one code and
`profile_id` None.

HANDOFF
`VoiceVerificationHandoff` holds ONLY `approved`, `profile_id` and `failure_codes` (tuple of str). It keeps neither the decision nor the plan. It is
immutable, not subclassable, cannot be constructed directly, compares and hashes by value (exact type only), `to_dict()` returns FRESH plain data,
copy/deepcopy return the same object and pickling is refused (`TypeError`). Handoffs are deterministic and never raise for bad inputs.

WHAT THIS MODULE DOES NOT DO
It never calls the executor, the dispatch step, the pipeline or the batch runner, never touches any profile store, and performs no voice recognition, verification, matching,
biometrics, embeddings, ML models or audio processing. No microphone, networking, filesystem, persistence, database, external AI, cloud service, Android
API, clock or randomness, no module-level mutable state and no automatic execution. It changes no earlier module and is not wired into
`process_input()`, Core, the Planner, the Agent Loop, Android or any other section.
"""

from .voice_verification_decision import VoiceVerificationDecision
from .voice_verification_plan import VoiceVerificationPlan

FAILURE_INVALID_INPUT = "VOICE_VERIFICATION_HANDOFF_INVALID_INPUT"
FAILURE_REJECTED_DECISION = "VOICE_VERIFICATION_HANDOFF_REJECTED_DECISION"
FAILURE_PROFILE_MISMATCH = "VOICE_VERIFICATION_HANDOFF_PROFILE_MISMATCH"
FAILURE_CODES = (FAILURE_INVALID_INPUT, FAILURE_REJECTED_DECISION, FAILURE_PROFILE_MISMATCH)

_CREATE_TOKEN = object()


class VoiceVerificationHandoff:
    """Immutable handoff outcome. Obtain it only from `create_voice_verification_handoff()`."""

    __slots__ = ("_approved", "_profile_id", "_failure_codes")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("VoiceVerificationHandoff cannot be subclassed.")

    def __init__(self, _token, approved, profile_id, failure_codes):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use create_voice_verification_handoff() to obtain a VoiceVerificationHandoff.")
        object.__setattr__(self, "_approved", approved)
        object.__setattr__(self, "_profile_id", profile_id)
        object.__setattr__(self, "_failure_codes", tuple(failure_codes))

    def __setattr__(self, key, value):
        raise AttributeError("VoiceVerificationHandoff is immutable.")

    def __delattr__(self, key):
        raise AttributeError("VoiceVerificationHandoff is immutable.")

    @property
    def approved(self):
        return self._approved

    @property
    def profile_id(self):
        """The shared profile id when approved, otherwise None."""
        return self._profile_id

    @property
    def failure_codes(self):
        """Tuple of failure code strings (empty when approved)."""
        return self._failure_codes

    def to_dict(self):
        """Fresh plain data: {"approved", "profile_id", "failure_codes"}. Mutating it never affects this handoff."""
        return {"approved": self._approved, "profile_id": self._profile_id, "failure_codes": list(self._failure_codes)}

    def _key(self):
        return (self._approved, self._profile_id, self._failure_codes)

    def __eq__(self, other):
        if type(other) is not VoiceVerificationHandoff:
            return NotImplemented
        return self._key() == other._key()

    def __hash__(self):
        return hash(self._key())

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("VoiceVerificationHandoff is not pickled; use to_dict() to serialize it.")

    def __repr__(self):
        return "VoiceVerificationHandoff(approved=%r, profile_id=%r, failure_codes=%r)" % self._key()


def _rejected(code):
    return VoiceVerificationHandoff(_CREATE_TOKEN, False, None, (code,))


def create_voice_verification_handoff(decision, plan):
    """Describe whether `plan` may be handed on under `decision`. Executes nothing and performs no I/O of any kind.
    Deterministic, never raises for bad inputs, changes nothing it is given. Returns a `VoiceVerificationHandoff`."""
    if type(decision) is not VoiceVerificationDecision or type(plan) is not VoiceVerificationPlan:
        return _rejected(FAILURE_INVALID_INPUT)
    try:
        approved = decision.approved
        if approved is False:
            return _rejected(FAILURE_REJECTED_DECISION)
        if approved is not True:
            return _rejected(FAILURE_INVALID_INPUT)
        decision_profile_id = decision.profile_id
        plan_profile_id = plan.profile_id
    except Exception:
        return _rejected(FAILURE_INVALID_INPUT)
    if type(decision_profile_id) is not str or decision_profile_id == "" or type(plan_profile_id) is not str or plan_profile_id == "":
        return _rejected(FAILURE_INVALID_INPUT)
    if decision_profile_id != plan_profile_id:
        return _rejected(FAILURE_PROFILE_MISMATCH)
    return VoiceVerificationHandoff(_CREATE_TOKEN, True, decision_profile_id, ())
