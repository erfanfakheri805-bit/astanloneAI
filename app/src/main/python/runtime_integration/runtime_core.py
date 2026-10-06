"""
Runtime integration - RuntimeCore (Prompt 910)
==============================================
`RuntimeCore` is `Core` plus one thing: after every `process_input()` it asks
the read-only bridge (`runtime_integration/bridge.py`) to describe the turn
that just finished and keeps the answer as `last_runtime_result`.

It is a subclass, not an edit of `Core.process_input()`, on purpose: the real
entry points (`interface/server.py` `run()`, `android_entry.start()`) build a
`RuntimeCore`, so every message from the app or the server reaches the bridge,
while `Core` itself - its `process_input()`, its goal handler, and every test
or caller that builds a plain `Core` - stays exactly as it was.

What RuntimeCore adds around `Core.process_input()`:

  before   resets the per-turn scratch (`_turn_state`) that `Core`'s
           `_handle_conversation()` fills in (which branch produced the reply,
           and the relevance / reference / topic it already computed)
  call     `Core.process_input()` - unchanged, returns the reply untouched
  after    works out the route (empty / AEL / goal / conversation) with the
           same pure helpers Core's own routing uses (`InputSystem.normalize`,
           `Parser.parse`, `is_goal_oriented`), builds the bridge result, and
           clears the scratch

The reply returned to the caller is the very string `Core.process_input()`
produced; nothing the bridge does can change it, raise into it, or alter any
stored state. If building the result fails, `last_runtime_result` becomes the
bridge's minimal `bridge_error` result and the reply is still returned.
"""

import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.core import Core
from planning.goal_detection import is_goal_oriented
from runtime_integration import bridge
from runtime_integration.final_runtime_assessment import build_final_runtime_assessment
from runtime_growth import runtime_growth_cycle


def _independent(value):
    """Independent copy of plain dict/list/tuple data (the handoff is JSON-safe),
    so a caller can never reach the stored result through what it was given."""
    if isinstance(value, dict):
        return {k: _independent(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_independent(v) for v in value]
    if isinstance(value, tuple):
        return tuple(_independent(v) for v in value)
    return value


_ANDROID_ENTRY = []  # one cached lookup of the Android entry module (or None)


def _android_entry_module():
    """The `android_entry` module if it can be imported (cached; importing it only
    defines names - the server is started solely by `start()`), else None."""
    if not _ANDROID_ENTRY:
        try:
            import importlib
            _ANDROID_ENTRY.append(importlib.import_module("android_entry"))
        except Exception:  # noqa: BLE001
            _ANDROID_ENTRY.append(None)
    return _ANDROID_ENTRY[0]


class RuntimeCore(Core):
    # The structured runtime-integration result for the most recent
    # process_input() call; None until the first message.
    last_runtime_result = None
    # Prompt 928: the latest controlled reasoning consumption result (plain-data
    # copy), or None. Descriptive only: never executed, never a mutation of the
    # handoff.
    _last_reasoning_consumption_result = None
    # Prompt 929: the latest non-actionable reasoning decision candidate (plain-data
    # copy), or None. Never executed.
    _last_reasoning_decision_candidate = None
    # Prompt 931: the latest reasoning decision validation result (plain-data copy),
    # or None. Never actionable, never executed.
    _last_reasoning_decision_validation = None
    # Prompt 932: the latest decision eligibility state (plain-data copy), or None.
    # Descriptive only: never actionable, never executed.
    _last_reasoning_decision_eligibility = None
    # Prompt 933: the latest controlled reasoning checkpoint (plain-data copy), or
    # None. Descriptive only: never actionable, never executed.
    _last_controlled_reasoning_checkpoint = None
    # Prompt 934: the latest controlled reasoning snapshot (plain-data deep copy), or
    # None. Descriptive only: never actionable, never executed.
    _last_controlled_reasoning_snapshot = None
    # Prompt 935: the latest controlled reasoning runtime-readiness result (plain-data
    # copy), or None. Descriptive only: never actionable, never executed.
    _last_controlled_reasoning_runtime_ready = None
    # Prompt 936: the latest final runtime integration checkpoint (plain-data copy),
    # or None. Descriptive only: never actionable, never executed.
    _last_final_runtime_integration_checkpoint = None
    # Prompt 937: the latest final runtime integration boundary validation (fresh
    # plain-data copy), or None. Descriptive only: never actionable, never executed,
    # never read by process_input(), replies, execution, upgrades, learning or
    # capabilities.
    _last_final_runtime_integration_boundary_validation = None
    # Prompt 938: the latest final runtime assessment (fresh plain-data copy), or
    # None. Descriptive only: never actionable, never executed, never read by
    # process_input(), replies, learning, upgrades, capabilities, reasoning
    # execution or Android behavior.
    _last_final_runtime_assessment = None
    # Prompt 953: the latest controlled runtime-growth cycle result (fresh plain-data
    # copy), or None until the first run_controlled_runtime_growth() call. Descriptive
    # only: not permission, authorization, approval, persistence or source
    # modification; never read by process_input(), replies, learning, upgrades,
    # capabilities, reasoning execution or Android behavior, and not reset per turn.
    _last_controlled_runtime_growth = None

    def process_input(self, raw_text):
        previous_analysis = self.last_nlu_analysis
        self._turn_state = {
            "source": None,
            "turns_available_before": len(self.context.get_recent_turns()),
        }
        # Prompt 919: a previous turn's result (and its reasoning handoff) must
        # never stay exposed for this turn; it is replaced when the turn ends,
        # and stays None if Core raises before that.
        self.last_runtime_result = None
        # Prompt 928: same for the stored consumption result.
        self._last_reasoning_consumption_result = None
        self._last_reasoning_decision_candidate = None  # Prompt 929
        self._last_reasoning_decision_validation = None  # Prompt 931
        self._last_reasoning_decision_eligibility = None  # Prompt 932
        self._last_controlled_reasoning_checkpoint = None  # Prompt 933
        self._last_controlled_reasoning_snapshot = None  # Prompt 934
        self._last_controlled_reasoning_runtime_ready = None  # Prompt 935
        self._last_final_runtime_integration_checkpoint = None  # Prompt 936
        self._last_final_runtime_integration_boundary_validation = None  # Prompt 937
        self._last_final_runtime_assessment = None  # Prompt 938
        try:
            reply = super().process_input(raw_text)
            self._record_runtime_result(raw_text, previous_analysis)
            self._store_reasoning_consumption_result()
            self._store_reasoning_decision_candidate()
            self._store_reasoning_decision_validation()
            self._store_reasoning_decision_eligibility()
            self._store_controlled_reasoning_checkpoint()
            self._store_controlled_reasoning_snapshot()
            self._store_controlled_reasoning_runtime_ready()
            self._store_final_runtime_integration_checkpoint()
            self._store_final_runtime_integration_boundary_validation()
            self._store_final_runtime_assessment()
            return reply
        finally:
            self._turn_state = None

    def _handle_ael(self, text):
        """Core's own AEL handler, unchanged; this only watches what the
        existing interpreter reports for each instruction (kind, success) so
        the bridge can say whether TEACH/RELATE really ran. The reply is
        exactly the string Core produces."""
        real_run = self.ael.run

        def watching_run(source):
            results = real_run(source)
            try:
                (self._turn_state or {})["ael_results"] = [
                    {"kind": r.instruction.kind if r.instruction is not None else None,
                     "success": r.success is True} for r in results]
            except Exception:  # noqa: BLE001 - observation only
                pass
            return results

        # Prompt 915: the interpreter's result only says a RELATE succeeded, not
        # whether the relationship was new. LearningSystem.relate() already
        # returns {"created": bool}; this records that flag (and nothing else)
        # after the call returns, unchanged, so the bridge can tell a new
        # relationship from one that already existed.
        learning = getattr(self, "learning", None)
        real_relate = getattr(learning, "relate", None)
        had_relate = learning is not None and "relate" in getattr(learning, "__dict__", {})
        prior_relate = learning.__dict__.get("relate") if had_relate else None

        def watching_relate(*args, **kwargs):
            outcome = real_relate(*args, **kwargs)
            try:
                created = outcome.get("created") if isinstance(outcome, dict) else None
                state = self._turn_state
                if state is not None:
                    state.setdefault("relate_outcomes", []).append(
                        created if isinstance(created, bool) else None)
            except Exception:  # noqa: BLE001 - observation only
                pass
            return outcome

        self.ael.run = watching_run
        if callable(real_relate):
            learning.relate = watching_relate
        try:
            return super()._handle_ael(text)
        finally:
            self.ael.__dict__.pop("run", None)
            if callable(real_relate):
                if had_relate:
                    learning.__dict__["relate"] = prior_relate
                else:
                    learning.__dict__.pop("relate", None)

    def get_last_runtime_result(self):
        """The runtime-integration result of the most recent process_input()
        (None before the first message). Read-only."""
        return self.last_runtime_result

    def _store_reasoning_consumption_result(self):
        """Prompt 928: keep an independent copy of this turn's valid, successful
        `reasoning_consumption_result` (same validity rule as the effective
        state). Best effort and read-only: the handoff and reply are never
        touched, and anything else leaves the field None."""
        self._last_reasoning_consumption_result = None
        try:
            result = self.last_runtime_result
            reasoning = result.get("reasoning") if isinstance(result, dict) else None
            if not isinstance(reasoning, dict):
                return
            consumed = reasoning.get("reasoning_consumption_result")
            if bridge.reasoning_effective_consumption_state(
                    reasoning.get("reasoning_handoff"), consumed) == bridge.CONSUMPTION_CONSUMED:
                self._last_reasoning_consumption_result = _independent(consumed)
        except Exception:  # noqa: BLE001 - observation must never affect a reply
            self._last_reasoning_consumption_result = None

    def get_last_reasoning_consumption_result(self):
        """Prompt 928: an independent plain-data copy of the latest turn's
        successful reasoning consumption result, or None when that turn had
        none (no reasoning, unavailable, or Core raised). Never exposes the
        stored dict and never raises."""
        try:
            stored = self._last_reasoning_consumption_result
            return _independent(stored) if isinstance(stored, dict) else None
        except Exception:  # noqa: BLE001
            return None

    def _store_reasoning_decision_candidate(self):
        """Prompt 929: keep an independent copy of this turn's valid decision
        candidate, only when this turn's consumption is effectively "consumed".
        Best effort and read-only; anything else leaves the field None."""
        self._last_reasoning_decision_candidate = None
        try:
            result = self.last_runtime_result
            reasoning = result.get("reasoning") if isinstance(result, dict) else None
            if not isinstance(reasoning, dict):
                return
            candidate = reasoning.get("reasoning_decision_candidate")
            if (bridge.reasoning_effective_consumption_state(
                    reasoning.get("reasoning_handoff"),
                    reasoning.get("reasoning_consumption_result")) == bridge.CONSUMPTION_CONSUMED
                    and isinstance(candidate, dict) and candidate.get("available") is True
                    and candidate.get("status") == bridge.DECISION_CANDIDATE
                    and candidate.get("actionable") is False and candidate.get("executed") is False):
                self._last_reasoning_decision_candidate = _independent(candidate)
        except Exception:  # noqa: BLE001 - observation must never affect a reply
            self._last_reasoning_decision_candidate = None

    def get_last_reasoning_decision_candidate(self):
        """Prompt 929: an independent plain-data copy of the latest turn's
        decision candidate, or None when that turn had none. Never exposes the
        stored dict and never raises."""
        try:
            stored = self._last_reasoning_decision_candidate
            return _independent(stored) if isinstance(stored, dict) else None
        except Exception:  # noqa: BLE001
            return None

    def _store_reasoning_decision_validation(self):
        """Prompt 931: when this turn's reasoning section carries a decision
        candidate, validate it with the existing bridge helper and keep an
        independent copy of the result (valid or invalid). Best effort and
        read-only; no candidate, or any failure, leaves the field None."""
        self._last_reasoning_decision_validation = None
        try:
            result = self.last_runtime_result
            reasoning = result.get("reasoning") if isinstance(result, dict) else None
            if not isinstance(reasoning, dict):
                return
            candidate = reasoning.get("reasoning_decision_candidate")
            if not isinstance(candidate, dict):
                return
            validation = bridge.validate_reasoning_decision_candidate(candidate)
            if (isinstance(validation, dict) and validation.get("actionable") is False
                    and validation.get("executed") is False):
                self._last_reasoning_decision_validation = _independent(validation)
        except Exception:  # noqa: BLE001 - observation must never affect a reply
            self._last_reasoning_decision_validation = None

    def get_last_reasoning_decision_validation(self):
        """Prompt 931: an independent plain-data copy of the latest turn's
        decision validation result, or None when that turn had none. Never
        exposes the stored dict and never raises."""
        try:
            stored = self._last_reasoning_decision_validation
            return _independent(stored) if isinstance(stored, dict) else None
        except Exception:  # noqa: BLE001
            return None

    def _store_reasoning_decision_eligibility(self):
        """Prompt 932: derive the eligibility state from the validation stored
        for this turn (same existing bridge gate) and keep an independent copy.
        No stored validation, or any failure, leaves the field None."""
        self._last_reasoning_decision_eligibility = None
        try:
            validation = self._last_reasoning_decision_validation
            if not isinstance(validation, dict):
                return
            eligibility = bridge.reasoning_decision_eligibility(validation)
            if (isinstance(eligibility, dict) and eligibility.get("actionable") is False
                    and eligibility.get("executed") is False):
                self._last_reasoning_decision_eligibility = _independent(eligibility)
        except Exception:  # noqa: BLE001 - observation must never affect a reply
            self._last_reasoning_decision_eligibility = None

    def get_last_reasoning_decision_eligibility(self):
        """Prompt 932: an independent plain-data copy of the latest turn's
        decision eligibility state, or None when that turn had none. Never
        exposes the stored dict and never raises."""
        try:
            stored = self._last_reasoning_decision_eligibility
            return _independent(stored) if isinstance(stored, dict) else None
        except Exception:  # noqa: BLE001
            return None

    def _store_controlled_reasoning_checkpoint(self):
        """Prompt 933: when this turn's reasoning section carries every state
        object of the controlled chain (handoff, consumption result, decision
        candidate, validation, eligibility), compute the checkpoint with the
        bridge helper and keep an independent copy. Best effort and read-only;
        anything missing, or any failure, leaves the field None."""
        self._last_controlled_reasoning_checkpoint = None
        try:
            result = self.last_runtime_result
            reasoning = result.get("reasoning") if isinstance(result, dict) else None
            if not isinstance(reasoning, dict):
                return
            parts = [reasoning.get(k) for k in (
                "reasoning_handoff", "reasoning_consumption_result",
                "reasoning_decision_candidate", "reasoning_decision_validation",
                "reasoning_decision_eligibility")]
            if not all(isinstance(p, dict) for p in parts):
                return
            checkpoint = bridge.controlled_reasoning_checkpoint(*parts)
            if (isinstance(checkpoint, dict) and checkpoint.get("actionable") is False
                    and checkpoint.get("executed") is False):
                self._last_controlled_reasoning_checkpoint = _independent(checkpoint)
        except Exception:  # noqa: BLE001 - observation must never affect a reply
            self._last_controlled_reasoning_checkpoint = None

    def get_last_controlled_reasoning_checkpoint(self):
        """Prompt 933: an independent plain-data copy of the latest turn's
        controlled reasoning checkpoint, or None when that turn had none. Never
        exposes the stored dict and never raises."""
        try:
            stored = self._last_controlled_reasoning_checkpoint
            return _independent(stored) if isinstance(stored, dict) else None
        except Exception:  # noqa: BLE001
            return None

    def _store_controlled_reasoning_snapshot(self):
        """Prompt 934: when this turn's reasoning section carries every
        controlled state object (handoff, consumption result, decision candidate,
        validation, eligibility, checkpoint), build the snapshot with the bridge
        helper and keep an independent copy. Best effort and read-only; anything
        missing, or any failure, leaves the field None."""
        self._last_controlled_reasoning_snapshot = None
        try:
            result = self.last_runtime_result
            reasoning = result.get("reasoning") if isinstance(result, dict) else None
            if not isinstance(reasoning, dict):
                return
            parts = [reasoning.get(k) for k in (
                "reasoning_handoff", "reasoning_consumption_result",
                "reasoning_decision_candidate", "reasoning_decision_validation",
                "reasoning_decision_eligibility", "controlled_reasoning_checkpoint")]
            if not all(isinstance(p, dict) for p in parts):
                return
            snapshot = bridge.build_controlled_reasoning_snapshot(*parts)
            if (isinstance(snapshot, dict) and snapshot.get("actionable") is False
                    and snapshot.get("executed") is False):
                self._last_controlled_reasoning_snapshot = _independent(snapshot)
        except Exception:  # noqa: BLE001 - observation must never affect a reply
            self._last_controlled_reasoning_snapshot = None

    def get_last_controlled_reasoning_snapshot(self):
        """Prompt 934: an independent plain-data deep copy of the latest turn's
        controlled reasoning snapshot, or None when that turn had none. Never
        exposes the stored dict and never raises."""
        try:
            stored = self._last_controlled_reasoning_snapshot
            return _independent(stored) if isinstance(stored, dict) else None
        except Exception:  # noqa: BLE001
            return None

    def _store_controlled_reasoning_runtime_ready(self):
        """Prompt 935: once this turn's snapshot is stored, compute the structural
        readiness result with the bridge helper and keep an independent copy.
        No stored snapshot, or any failure, leaves the field None."""
        self._last_controlled_reasoning_runtime_ready = None
        try:
            snapshot = self._last_controlled_reasoning_snapshot
            if not isinstance(snapshot, dict):
                return
            ready = bridge.controlled_reasoning_runtime_ready(snapshot)
            if (isinstance(ready, dict) and ready.get("actionable") is False
                    and ready.get("executed") is False):
                self._last_controlled_reasoning_runtime_ready = _independent(ready)
        except Exception:  # noqa: BLE001 - observation must never affect a reply
            self._last_controlled_reasoning_runtime_ready = None

    def get_last_controlled_reasoning_runtime_ready(self):
        """Prompt 935: an independent plain-data copy of the latest turn's
        runtime-readiness result, or None when that turn had none. Never
        exposes the stored dict and never raises."""
        try:
            stored = self._last_controlled_reasoning_runtime_ready
            return _independent(stored) if isinstance(stored, dict) else None
        except Exception:  # noqa: BLE001
            return None

    def _store_final_runtime_integration_checkpoint(self):
        """Prompt 936: once this turn's snapshot and runtime-readiness result are
        stored, compute the final integration checkpoint with the bridge helper
        and keep an independent copy. Either one missing, or any failure,
        leaves the field None."""
        self._last_final_runtime_integration_checkpoint = None
        try:
            snapshot = self._last_controlled_reasoning_snapshot
            ready = self._last_controlled_reasoning_runtime_ready
            if not (isinstance(snapshot, dict) and isinstance(ready, dict)):
                return
            checkpoint = bridge.final_runtime_integration_checkpoint(snapshot, ready)
            if (isinstance(checkpoint, dict) and checkpoint.get("actionable") is False
                    and checkpoint.get("executed") is False):
                self._last_final_runtime_integration_checkpoint = _independent(checkpoint)
        except Exception:  # noqa: BLE001 - observation must never affect a reply
            self._last_final_runtime_integration_checkpoint = None

    def get_last_final_runtime_integration_checkpoint(self):
        """Prompt 936: an independent plain-data copy of the latest turn's final
        runtime integration checkpoint, or None when that turn had none. Never
        exposes the stored dict and never raises."""
        try:
            stored = self._last_final_runtime_integration_checkpoint
            return _independent(stored) if isinstance(stored, dict) else None
        except Exception:  # noqa: BLE001
            return None

    def _runtime_boundary_evidence(self):
        """Prompt 937: read-only evidence for the boundary validation, taken from
        what this instance really wires and from what the bridge observed for the
        latest turn. Nothing is called that runs a model, learning, a capability, an
        upgrade or the Android server; an area whose evidence cannot be read is simply
        left out (the validation reports it as missing)."""
        result = self.last_runtime_result if isinstance(self.last_runtime_result, dict) else {}

        def section(key):
            value = result.get(key)
            return value if isinstance(value, dict) else {}

        def flags(exists, connected, activated, capable):
            return {"exists": exists is True, "connected_to_runtime_core": connected is True,
                    "activated_in_runtime_path": activated is True,
                    "execution_capable": capable is True}

        def reasoning():
            names = ("build_controlled_reasoning_snapshot", "controlled_reasoning_runtime_ready",
                     "final_runtime_integration_checkpoint")
            cp = self._last_final_runtime_integration_checkpoint
            return flags(
                all(callable(getattr(bridge, n, None)) for n in names),
                callable(getattr(self, "_store_final_runtime_integration_checkpoint", None))
                and callable(getattr(self, "get_last_final_runtime_integration_checkpoint", None)),
                isinstance(cp, dict) and cp.get("status") == bridge.INTEGRATION_READY
                and cp.get("ready") is True, False)

        def local_model():
            li = self.language_intelligence
            exists = (callable(getattr(li, "check_model_readiness", None))
                      and callable(getattr(self, "use_local_language_model", None)))
            ready = section("local_model").get("real_backend_connected") is True
            return flags(exists, exists and isinstance(getattr(li, "backend_kind", None), str)
                         and callable(getattr(self, "get_local_model_readiness", None)),
                         ready, ready)

        def memory():
            exists = self.memory is not None and self.context is not None
            active = section("memory_context").get("memory_available") is True
            return flags(exists, exists and callable(getattr(self.context, "get_recent_turns", None)),
                         active, active)

        def ael_learning():
            learning = section("learning")
            exists = self.ael is not None and self.learning is not None
            active = (learning.get("learning_requested") is True
                      and learning.get("learning_available") is True)
            return flags(exists, exists and callable(getattr(self.ael, "run", None))
                         and callable(getattr(self.learning, "relate", None)),
                         active, active and learning.get(
                             "learning_performed_by_existing_runtime") is True)

        def capability():
            exists = self.capabilities is not None
            return flags(exists, exists and callable(getattr(self.capabilities, "all", None)),
                         section("capability").get("identified") is True, False)

        def upgrade():
            exists = self.upgrades is not None
            return flags(exists, exists and getattr(self.ael, "upgrade_system", None) is self.upgrades,
                         False, False)

        def android():
            module = _android_entry_module()
            exists = module is not None and callable(getattr(module, "start", None))
            running = exists and getattr(module, "_server", None) is not None
            return flags(exists, exists and getattr(module, "RuntimeCore", None) is RuntimeCore,
                         running, running)

        evidence = {}
        for name, build in (("controlled_reasoning_integration", reasoning),
                            ("local_model_runtime", local_model), ("memory_runtime", memory),
                            ("AEL_learning_runtime", ael_learning),
                            ("capability_runtime", capability), ("upgrade_runtime", upgrade),
                            ("android_runtime_bridge", android)):
            try:
                evidence[name] = build()
            except Exception:  # noqa: BLE001 - observation only
                pass
        return evidence

    def _store_final_runtime_integration_boundary_validation(self):
        """Prompt 937: classify the existing runtime integration with the bridge
        helper and keep an independent copy. Observation only; any failure leaves
        the field None."""
        self._last_final_runtime_integration_boundary_validation = None
        try:
            validation = bridge.final_runtime_integration_boundary_validation(
                self._runtime_boundary_evidence())
            if (isinstance(validation, dict) and validation.get("actionable") is False
                    and validation.get("executed") is False):
                self._last_final_runtime_integration_boundary_validation = _independent(validation)
        except Exception:  # noqa: BLE001 - observation must never affect a reply
            self._last_final_runtime_integration_boundary_validation = None

    def get_last_final_runtime_integration_boundary_validation(self):
        """Prompt 937: an independent plain-data copy of the latest turn's final
        runtime integration boundary validation, or None when that turn had none.
        Never exposes the stored dict and never raises."""
        try:
            stored = self._last_final_runtime_integration_boundary_validation
            return _independent(stored) if isinstance(stored, dict) else None
        except Exception:  # noqa: BLE001
            return None

    def _store_final_runtime_assessment(self):
        """Prompt 938: assess the latest boundary validation together with this
        turn's readiness result and snapshot (all already stored, read-only) and
        keep an independent copy. Missing inputs yield the assessment's own
        "not_verified" result; any failure leaves the field None."""
        self._last_final_runtime_assessment = None
        try:
            assessment = build_final_runtime_assessment(
                self._last_final_runtime_integration_boundary_validation,
                self._last_controlled_reasoning_runtime_ready,
                self._last_controlled_reasoning_snapshot)
            if (isinstance(assessment, dict) and assessment.get("actionable") is False
                    and assessment.get("executed") is False):
                self._last_final_runtime_assessment = _independent(assessment)
        except Exception:  # noqa: BLE001 - observation must never affect a reply
            self._last_final_runtime_assessment = None

    def get_last_final_runtime_assessment(self):
        """Prompt 938: an independent plain-data copy of the latest turn's final
        runtime assessment, or None when that turn had none. Never exposes the
        stored dict and never raises."""
        try:
            stored = self._last_final_runtime_assessment
            return _independent(stored) if isinstance(stored, dict) else None
        except Exception:  # noqa: BLE001
            return None

    def run_controlled_runtime_growth(self, request_data):
        """Prompt 953: run the Prompt 952 controlled growth cycle on `request_data`
        (the sole orchestrator - no growth stage is called from here), keep an
        independent copy as the latest controlled growth result and return another
        independent copy. Pure in-memory: no files, database, persistence or
        source change. Never raises; the cycle's own fixed unavailable result is
        returned for anything it rejects."""
        result = runtime_growth_cycle.run_controlled_runtime_growth_cycle(request_data)
        self._last_controlled_runtime_growth = _independent(result)
        return _independent(result)

    def get_last_controlled_runtime_growth(self):
        """Prompt 953: an independent copy of the latest controlled growth result,
        or None before the first run_controlled_runtime_growth() call. Never
        exposes the stored object."""
        stored = self._last_controlled_runtime_growth
        return None if stored is None else _independent(stored)

    def get_last_runtime_observation(self):
        """Prompt 938: the runtime observation extras for the latest turn, under
        their own keys: {"final_runtime_assessment": copy-or-None}. Kept apart from
        `last_runtime_result`, whose exact key set Prompt 910 pins. Read-only."""
        return {"final_runtime_assessment": self.get_last_final_runtime_assessment()}

    def get_last_reasoning_handoff(self):
        """Prompt 918: the descriptive reasoning handoff (request + decision)
        for the most recent turn, taken from `last_runtime_result`; a safe
        `available: False` stand-in when that turn had none. Read-only: it is
        not consumed by Core and executes nothing. Prompt 920: the caller gets an
        independent copy, so mutating it never changes the stored result."""
        result = self.last_runtime_result
        reasoning = result.get("reasoning") if isinstance(result, dict) else None
        if isinstance(reasoning, dict) and isinstance(reasoning.get("reasoning_handoff"), dict):
            return _independent(reasoning["reasoning_handoff"])
        if isinstance(reasoning, dict) and reasoning.get("reason"):
            return bridge.unavailable_reasoning_handoff(reasoning["reason"])
        return bridge.unavailable_reasoning_handoff()

    def _turn_route(self, text):
        """(route, source) for a normalized message, from the same pure
        helpers Core's own routing uses; a conversation turn's source is
        whatever _handle_conversation() labelled it with."""
        if not text:
            return bridge.ROUTE_EMPTY, bridge.SOURCE_EMPTY_INPUT
        if self.parser.parse(text).kind == "ael":
            return bridge.ROUTE_AEL, bridge.SOURCE_AEL
        if is_goal_oriented(text):
            return bridge.ROUTE_GOAL, bridge.SOURCE_GOAL
        source = (self._turn_state or {}).get("source") or bridge.SOURCE_UNKNOWN
        return bridge.ROUTE_CONVERSATION, source

    def _record_runtime_result(self, raw_text, previous_analysis):
        """Build and keep the result for the turn that just finished. Best
        effort and read-only: any failure yields the bridge's minimal safe
        result and never affects the reply, the context or stored state."""
        try:
            state = self._turn_state or {}
            text = self.input_system.normalize(raw_text)
            route, source = self._turn_route(text)
            analysis = self.last_nlu_analysis
            # last_nlu_analysis is only replaced when this very turn reached
            # the NLU step; otherwise it is the previous turn's object.
            if analysis is previous_analysis:
                analysis = None
            self.last_runtime_result = bridge.build_runtime_result({
                "raw_input": raw_text,
                "text": text,
                "route": route,
                "response_source": source,
                "existing_runtime_effects": (
                    state.get("effects") if route == bridge.ROUTE_CONVERSATION else None),
                "analysis": analysis,
                "read_only_analyzer": lambda t: self.persian_nlu.pipeline.analyze(t, self.nlu_context),
                "nlu_context": self.nlu_context,
                "memory": {
                    "turns_available_before": state.get("turns_available_before", 0),
                    "relevant_context": state.get("relevant_context"),
                    "resolved_reference": state.get("resolved_reference"),
                    "active_topic": state.get("active_topic"),
                },
                "ael_results": (state.get("ael_results") if route == bridge.ROUTE_AEL else None),
                "relate_outcomes": (state.get("relate_outcomes", [])
                                    if route == bridge.ROUTE_AEL else None),
                "learning_available": getattr(self, "learning", None) is not None,
                "capability_rows": self.capabilities.all(),
                "model_readiness": self.get_local_model_readiness(),
                "backend_kind": self.language_intelligence.backend_kind,
            })
        except Exception:  # noqa: BLE001 - observation must never affect a reply
            self.last_runtime_result = bridge.error_runtime_result()
