"""
Self-Upgrade - Capability Approval Manager
============================================
`ApprovalManager` is the stage after a `HumanApprovalRequest` is built
(self_upgrade.capability_human_approval, Prompt 370): a small,
reliable store for those requests, with exactly two ways a request can
ever leave `PENDING_APPROVAL` - an explicit `approve(request_id)` call
or an explicit `reject(request_id)` call. Both take only a
`request_id`; neither accepts a test result, a confidence score, or
any other capability-quality signal, because none of those are allowed
to influence the decision (see below).

    HumanApprovalRequest (Prompt 370, PENDING_APPROVAL)
        -> ApprovalManager.create_request(...)
        -> stored PENDING_APPROVAL record
        -> ApprovalManager.approve(request_id) / .reject(request_id)
        -> stored APPROVED / REJECTED record

ARCHITECTURAL BOUNDARY (unchanged from Prompt 370, enforced here too):
this manager stores and resolves a human decision - it never makes
one. There is no method here that inspects a capability's test result,
verification status, or anything else and turns that into an approval;
`approve`/`reject` are the only two ways a status ever changes, they
take a bare `request_id`, and they must be called explicitly by
whatever surface (CLI, UI, API) represents an actual human clicking
"approve"/"reject" - nothing in this module ever calls them itself.
This module also never activates a capability, never registers one as
active, never executes generated code, and never modifies project
source; none of those actions exist anywhere in this file.

Reuses, never duplicates:
  - `self_upgrade.capability_human_approval.APPROVAL_STATUS_PENDING/
    APPROVED/REJECTED/INVALID` - the exact same status vocabulary
    Prompt 370 already defined - are imported unchanged rather than
    redefined a second, possibly-diverging way.
  - `memory.memory_system.MemorySystem.set_state`/`get_state` - the
    project's existing generic key-value persistence (used for
    settings/app state) - is reused for storage, keyed
    `capability_approval:<request_id>`, rather than a new table, a new
    migration, or a second database. No new schema is introduced.

State-transition rules (enforced, never bypassed):
    PENDING_APPROVAL -> APPROVED   (only via `approve`)
    PENDING_APPROVAL -> REJECTED   (only via `reject`)
    APPROVED         -> no further transition (no automatic action)
    REJECTED         -> no further transition (no automatic action)
A repeated or invalid transition (approving/rejecting a request that
is already APPROVED/REJECTED, or acting on a `request_id` that was
never created) never changes stored state - it returns a result whose
`status` reflects the actual, unchanged stored state (or `None` if no
such request exists) together with a non-empty `errors` list.

Never raises: any missing/malformed input, or an operation on an
unknown or already-decided request, is reported as a structured result
with `errors`, never as an exception.

`get_stored_record` (Prompt 376) is the one addition on top of the
above: a plain, read-only getter for the *complete* stored record
(not the trimmed `request_id`/`capability_name`/`status`/
`decision_timestamp`/`version`/`errors` shape `get_request` returns),
so a later, separate step (self_upgrade.capability_registration_decision,
Prompt 376) can read fields such as `request_type` and
`registration_plan` off an already-decided request without a second
storage system reaching into `memory` directly. It changes no
behavior of `create_request`/`approve`/`reject`/`get_request`/
`get_status` and adds no new way for a status to change.
"""

import copy
from datetime import datetime, timezone

from self_upgrade.capability_human_approval import (
    APPROVAL_STATUS_PENDING,
    APPROVAL_STATUS_APPROVED,
    APPROVAL_STATUS_REJECTED,
)

_STATE_KEY_PREFIX = "capability_approval:"


def _now():
    return datetime.now(timezone.utc).isoformat()


def _state_key(request_id):
    return f"{_STATE_KEY_PREFIX}{request_id}"


class ApprovalManager:
    """Stores `HumanApprovalRequest` records and resolves them via
    explicit `approve`/`reject` calls only. See module docstring."""

    def __init__(self, memory):
        self.memory = memory

    # ------------------------------------------------------------------
    # Storage helpers - the project's existing generic key-value state
    # table, never a second storage system.
    # ------------------------------------------------------------------
    def _load(self, request_id):
        if not isinstance(request_id, str) or not request_id.strip():
            return None
        return self.memory.get_state(_state_key(request_id))

    def _save(self, record):
        self.memory.set_state(_state_key(record["request_id"]), record)

    @staticmethod
    def _result(record, errors=None):
        record = record or {}
        return {
            "request_id": record.get("request_id"),
            "capability_name": record.get("capability_name"),
            "status": record.get("status"),
            "decision_timestamp": record.get("decision_timestamp"),
            "version": record.get("version"),
            "errors": list(errors or []),
        }

    def _not_found(self, request_id, action):
        return self._result(
            {"request_id": request_id},
            [f"No approval request found for request_id={request_id!r}; "
             f"cannot {action}."],
        )

    # ------------------------------------------------------------------
    # Focused operations (requirement 5)
    # ------------------------------------------------------------------
    def create_request(self, human_approval_request):
        """Store a `HumanApprovalRequest` (self_upgrade.
        capability_human_approval.request_capability_human_approval's
        own, already-built result) as a new, always-`PENDING_APPROVAL`
        record. Only a request whose own `status` is already
        `APPROVAL_STATUS_PENDING` may be admitted - an `INVALID`/
        `BLOCKED` `HumanApprovalRequest`, or a malformed input, is
        rejected here rather than silently stored. Never overwrites an
        existing record for the same `request_id` (its decision, once
        recorded, is never clobbered by a re-create call).

        Always returns the same structured result shape `approve`/
        `reject`/`get_request`/`get_status` return (requirement 9).
        """
        if not isinstance(human_approval_request, dict):
            return self._result(None, ["human_approval_request must be a "
                                        "HumanApprovalRequest dict."])

        request_id = human_approval_request.get("request_id")
        capability_name = human_approval_request.get("capability_name")
        if not isinstance(request_id, str) or not request_id.strip():
            return self._result(None, ["human_approval_request is missing a request_id."])
        if not isinstance(capability_name, str) or not capability_name.strip():
            return self._result({"request_id": request_id},
                                 ["human_approval_request is missing a capability_name."])
        if human_approval_request.get("status") != APPROVAL_STATUS_PENDING:
            return self._result(
                {"request_id": request_id, "capability_name": capability_name},
                [f"Only a PENDING_APPROVAL HumanApprovalRequest can be registered "
                 f"(got status={human_approval_request.get('status')!r})."],
            )

        if self._load(request_id) is not None:
            return self._result(
                self._load(request_id),
                [f"An approval request already exists for request_id={request_id!r}; "
                 "it was not recreated or overwritten."],
            )

        record = copy.deepcopy(human_approval_request)
        record["decision_timestamp"] = None
        self._save(record)
        return self._result(record)

    def get_request(self, request_id):
        """Retrieve the current stored record for `request_id`, or a
        `NOT_FOUND`-style result (empty `status`, non-empty `errors`)
        if none exists. Never mutates anything."""
        record = self._load(request_id)
        if record is None:
            return self._not_found(request_id, "retrieve it")
        return self._result(record)

    def get_status(self, request_id):
        """Same as `get_request`, provided as its own focused
        operation per requirement 5 ('check current approval
        status')."""
        return self.get_request(request_id)

    def get_stored_record(self, request_id):
        """Return a deep copy of the *complete* stored record for
        `request_id` - every field it was created with (Prompt 376:
        e.g. a `RegistrationApprovalRequest`'s `request_type`,
        `registration_plan`, `interface_name`, `target_module`), not
        just the trimmed shape `get_request`/`approve`/`reject`
        return. Returns `None` if no such request exists. Read-only:
        never mutates state, never decides anything, and is not a
        second storage system - it reads the same record `_load`
        already reads."""
        record = self._load(request_id)
        if record is None:
            return None
        return copy.deepcopy(record)

    def approve(self, request_id):
        """Explicitly approve a `PENDING_APPROVAL` request. Takes only
        `request_id` - no test result, confidence score, or any other
        signal is accepted, so approval can never be inferred from
        anything but this one explicit call. A request that is missing,
        already `APPROVED`, or already `REJECTED` is left completely
        unchanged; the result reports its real current status plus a
        non-empty `errors` explaining why nothing changed."""
        return self._decide(request_id, APPROVAL_STATUS_APPROVED, "approve")

    def reject(self, request_id):
        """Explicitly reject a `PENDING_APPROVAL` request. Same
        contract as `approve` (see its docstring), decision inverted."""
        return self._decide(request_id, APPROVAL_STATUS_REJECTED, "reject")

    def _decide(self, request_id, new_status, action):
        record = self._load(request_id)
        if record is None:
            return self._not_found(request_id, action)

        if record.get("status") != APPROVAL_STATUS_PENDING:
            return self._result(
                record,
                [f"Cannot {action} request {request_id!r}: it is already "
                 f"{record.get('status')!r}, not PENDING_APPROVAL. "
                 "APPROVED/REJECTED never transition again."],
            )

        record = copy.deepcopy(record)
        record["status"] = new_status
        record["decision_timestamp"] = _now()
        self._save(record)
        return self._result(record)
