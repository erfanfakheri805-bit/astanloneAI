# Prompt 896 - Section 17: Implementation Approval Decision Contract

Third layer of Section 17 (Controlled Autonomy). New module: `autonomy/implementation_approval_decision.py` (`build_implementation_approval_decision`, `validate_implementation_approval_decision`). Deterministic, read-only, side-effect free. No Section 16 module and no Prompt 894 or 895 production module was changed.

**Prompt 896 creates an approval-decision state, not an approval mechanism.**

## Purpose of the decision contract

It draws a clear boundary between `ready_for_approval` (Prompt 895) and `approved` (which does not exist anywhere in the project). The decision contract records that an approval decision has **not yet been made**. Its only successful state is `pending_approval`.

## The distinctions

- **Eligibility vs approval request** - eligibility (Prompt 894 `eligible`) is a verdict about the data. The approval request (Prompt 895) is a record built from that verdict that says the request may be submitted for approval.
- **Approval request vs approval decision** - the request asks for a decision; the decision contract states the status of that decision. In Prompt 896 that status is always "not made yet".
- **Meaning of `pending_approval`** - an eligible request has been submitted and nobody has decided. It is not `approved`, not `implementation_allowed` and not `execution_allowed`; none of those states exist as a successful result.

## Builder and trust model

The builder takes the Section 16 chain, the Prompt 892 validation result, the Prompt 894 policy, the Prompt 895 approval request, the Prompt 895 validation result and a caller-supplied `decision_id`. Nothing is trusted: the Prompt 892 context validation re-derives the chain verdict, the Prompt 894 builder re-derives the policy, and the Prompt 895 builder re-derives the approval request. A supplied object that differs from the derived one (a forged but individually valid object) gives `context_mismatch`. The approval request must be re-derivable with status `ready_for_approval`, and the supplied validation result must equal the validation of that trusted request.

Result: `{status, decision, execution_allowed, executed}`, both flags `False`; `decision` is set only for `pending_approval`.

## Statuses

`pending_approval` (the only success), `invalid_request`, `invalid_request_validation`, `invalid_policy`, `invalid_approval_request`, `invalid_approval_request_validation`, `context_mismatch`, `unsupported_status`, `invalid_decision_id`, `decision_error`, `validation_error`. There is no `approved` status.

Mapping notes: a broken stage of the chain other than the evolution/implementation request (boundary, readiness, design, contract ...) gives `invalid_request_validation`; a policy that is invalid or not `eligible` (ineligible, blocked, unsupported) gives `invalid_policy`; `improve_or_conflict` gives `unsupported_status`.

## Decision shape

Exactly 14 keys: `version` (int `1`), `decision_id`, `request_id`, `implementation_request_id`, `approval_request_id`, `capability_name`, `operation` (`create`/`improve`), `approval_status` (`pending_approval`), `approval_required` (`True`), `implementation_allowed`, `execution_allowed`, `implementation_started`, `executed` (all `False`) and `reason` (`approval_decision_not_made`). The validator rejects any other value, any extra key, and any permission-like field.

## Why Prompt 896 cannot approve anything

The module emits data only. It has no input that carries an approver, no field that holds an approval and no code path that sets one. There is no user approval, no AEL approval and no automatic approval.

## Why implementation and execution remain disabled

`implementation_allowed`, `implementation_started`, `execution_allowed` and `executed` are always `False`, in every result and in the validator. Nothing is generated, patched, written, registered, installed, executed or self-modified.

## Future controlled approval boundary

A later, separately specified step may define who can decide and how a decision is recorded. It must start from a valid `pending_approval` decision and cannot be reached from Prompt 896. Granting implementation permission and execution permission would be further, separate steps.
