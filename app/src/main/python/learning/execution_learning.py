"""
Execution Learning
====================
`ExecutionLearning` turns an already-produced `ExecutionResult`
(execution/execution_result.py) into a `LearningRecord`
(learning/learning_record.py) describing what happened - one small,
read-only translation step:

    ExecutionResult -> ExecutionLearning.create_record() -> LearningRecord
    ExecutionResult -> ExecutionLearning.learn_from_execution(result, store)
        -> create_record() -> store.add()  -> stored LearningRecord (or None)

This is deliberately observation only. `create_record` never re-runs,
mutates, or inspects anything beyond the `ExecutionResult` it's
handed, and never stores the `LearningRecord` it builds - a separate
caller decides that (directly, via `learning/learning_record_store.py`,
or through this class's own `learn_from_execution` convenience
wrapper below). Neither method touches a plan, capability, skill, or
code file. Same "build the data, let the caller decide what to do with
it" boundary `learning/learning_input.py`'s `build_learning_inputs`
already keeps between the Understanding Engine and the Learning
Engine.
"""

from execution.execution_result import ExecutionResult, STATUS_COMPLETED, STATUS_FAILED

from .learning_record import LearningRecord
from .learning_record_store import LearningRecordStore

# Identifies the execution system as the source of every record this
# class builds - a fixed, deterministic value (never derived from the
# ExecutionResult itself, which has no notion of "source").
SOURCE_EXECUTION_SYSTEM = "execution_system"

OUTCOME_SUCCESS = "success"
OUTCOME_FAILURE = "failure"

# Deterministic, status-only confidence values (requirement: "a
# deterministic value based only on the execution status") - never
# derived from output/error content, timing, or anything else that
# could vary between two otherwise-identical results.
CONFIDENCE_SUCCESS = 1.0
CONFIDENCE_FAILURE = 0.0


class ExecutionLearning:
    """Stateless: holds no data of its own between calls."""

    def create_record(self, execution_result):
        """Build a `LearningRecord` describing `execution_result`, or
        `None` for invalid input.

        `None` is returned - never raised - when `execution_result`
        isn't an `ExecutionResult` at all, or when its `status` is
        neither `STATUS_COMPLETED` nor `STATUS_FAILED` (a still-
        pending/running/cancelled result isn't yet a definite
        "success" or "failure" to learn from - same "don't guess a
        deliberate answer" reasoning `LearningDecisionEngine.decide`
        already applies to its own reason codes).

        `source` is always `SOURCE_EXECUTION_SYSTEM` - it identifies
        *this* execution system as the origin, not any one particular
        run. `pattern` is the capability name a `CapabilityOutput` was
        attached under (`execution_result.capability_outputs`), when
        one exists; otherwise it falls back to a plain
        `"step:<step_id>"` pattern, so there is always something
        structured to group records by even when no capability output
        was attached. `outcome` is `"success"`/`"failure"`, and
        `confidence` is the fixed, status-only value above - never
        derived from `output`/`error` content.

        Never mutates `execution_result` in any way, and never stores
        the record it returns - the caller decides whether/where to
        keep it (e.g. `LearningRecordStore.add`).
        """
        if not isinstance(execution_result, ExecutionResult):
            return None

        if execution_result.status == STATUS_COMPLETED:
            outcome = OUTCOME_SUCCESS
            confidence = CONFIDENCE_SUCCESS
        elif execution_result.status == STATUS_FAILED:
            outcome = OUTCOME_FAILURE
            confidence = CONFIDENCE_FAILURE
        else:
            return None

        capability_names = list(execution_result.capability_outputs.keys())
        pattern = capability_names[0] if capability_names else f"step:{execution_result.step_id}"

        metadata = {
            "plan_id": execution_result.plan_id,
            "step_id": execution_result.step_id,
            "execution_id": execution_result.execution_id,
        }
        if outcome == OUTCOME_FAILURE and execution_result.error is not None:
            metadata["error"] = str(execution_result.error)

        return LearningRecord(
            source=SOURCE_EXECUTION_SYSTEM,
            pattern=pattern,
            outcome=outcome,
            confidence=confidence,
            metadata=metadata,
        )

    def learn_from_execution(self, execution_result, store):
        """Convenience wrapper: build a record via `create_record` and,
        if one was actually built, add it to the existing `store` (an
        already-constructed `LearningRecordStore` - this never creates
        one of its own).

        Returns `None` - and adds nothing - when `create_record`
        itself returns `None` for `execution_result` (invalid input, or
        a status that isn't a definite success/failure). Otherwise
        returns whatever `store.add(record)` returns: the stored
        `LearningRecord` on success, or `None` if the store itself
        rejected it (e.g. a colliding `record_id` - see
        `LearningRecordStore.add`) - this method never overrides that
        store's own accept/reject decision.

        Never mutates `execution_result`, never constructs a new
        `LearningRecordStore`, and never touches a plan, capability,
        skill, or code file.
        """
        record = self.create_record(execution_result)
        if record is None:
            return None
        return store.add(record)
