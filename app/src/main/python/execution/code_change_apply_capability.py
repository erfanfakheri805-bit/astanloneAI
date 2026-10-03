"""
Execution - Built-in Capability: code_change_apply
=======================================================
A real, working `Capability` (execution/capability.py) that connects
the existing `code_change_plan` capability (code_change_plan_capability.py)
to the existing `text_file_edit` capability (text_file_edit_capability.py):
it re-plans the exact same one-fragment text change `code_change_plan`
already knows how to plan, and applies it - by calling
`text_file_edit`'s own, unmodified handler - only when that plan comes
back `ready_to_apply`.

    path (string), old_text (string), new_text (string)
        -> Capability("code_change_apply")
        -> {path, requested_path, success, change_applied,
            change_metadata}

Maximal reuse, not a second file-edit system:
  - `code_change_plan_capability.make_code_change_plan_handler` is
    called directly, unchanged, to obtain the exact same structured
    plan (`target_fragment`/`replacement`/`validation_status`/
    `analysis_summary`/`ready_to_apply`) a caller would get from
    calling `code_change_plan` on its own - this module never
    re-implements the fragment-occurrence check, the AST-based
    analysis, or the safe-path/`.py`-only validation those already
    perform. `code_change_plan_capability.py` (and, transitively,
    `code_analysis_capability.py`, `text_file_read_capability.py`,
    `python_inspector.py`) are unmodified by this addition.
  - The change is applied - i.e. the file is actually written - only
    by calling `text_file_edit_capability.make_text_file_edit_handler`
    directly, unchanged, and only in the one branch where the plan
    just produced is `ready_to_apply`. This module never opens the
    target file for writing itself, never duplicates
    `text_file_edit`'s own allowed-directory/exact-fragment/write
    logic, and never calls any write path other than that one existing
    handler. `text_file_edit_capability.py` is unmodified by this
    addition, and its own `CAPABILITY_NAME` is reused (imported, not
    duplicated) wherever this module needs to refer to it.
  - Because both reused handlers independently perform the same
    underlying allowed-directory containment check (via
    `text_file_read_capability._resolve_allowed_dirs`/
    `_is_within_allowed_dirs`, imported by each of them, never
    reimplemented here), an unsafe path is rejected the first time it
    is ever evaluated - inside `code_change_plan`'s own reused
    handler, before `text_file_edit`'s handler is ever reached, so an
    unsafe path never gets anywhere near a write.

"Apply only when ready_to_apply is true" is enforced structurally, not
by convention: `text_file_edit`'s handler is called from exactly one
`if plan["ready_to_apply"]:` branch, and nothing else in this module
ever calls it. When the plan is not ready (missing/ambiguous fragment,
or the file is not currently valid Python source), this handler
returns a `{..., success: False, change_applied: False, ...}` result -
carrying the plan's own `validation_status`/`analysis_summary` as
`change_metadata` so a caller can see *why* - and the file is left
completely untouched, exactly as `code_change_plan` alone already
guarantees. Only the underlying safety preconditions
`code_change_plan`/`text_file_edit` already raise for (an unsafe path,
a non-`.py` file, a missing file, an empty/non-string `old_text`, ...)
are still raised here, unchanged - this module adds no new raising
behavior, and a raised precondition failure never reaches (and so
never applies) either reused handler's write path.

Exactly one change is planned and, at most, applied per call: this
handler accepts a single `path`/`old_text`/`new_text` input (the same
shape `code_change_plan` and `text_file_edit` already accept) and
calls `text_file_edit`'s handler at most once, never in a loop and
never for more than the one fragment the caller asked about. There is
no retry of any kind here - a plan that is not ready, or a write that
raises, is reported (or, for a raised precondition, propagated exactly
as the reused handler already raises it) and this handler returns;
nothing in this module calls either reused handler a second time for
the same request. The modified Python file is never imported, run, or
otherwise executed by this module - applying a change here only ever
means the one `str.replace`-based text write `text_file_edit`'s own
handler already performs.

Strictly reuses only what already exists: no `eval()`, no `exec()`, no
shell command, no `subprocess`, no network call, no external API, and
no new dependency anywhere in this module.

Nothing in this module executes on import, registers itself into any
registry automatically, or applies a change for any file beyond the
one path a caller explicitly asks about. `create_code_change_apply_capability`
only *builds* a `Capability` object; `register_code_change_apply_capability`
only calls the existing, unchanged `ExecutableCapabilityRegistry.register`
(or `CapabilityHandlerRegistry.register_capability`) with it - same
"no execution without an explicit handler, no automatic discovery"
rule the rest of execution/ already follows.
"""

from .capability import Capability
from .code_change_plan_capability import make_code_change_plan_handler
from .text_file_edit_capability import (
    CAPABILITY_NAME as TEXT_FILE_EDIT_CAPABILITY_NAME,
    make_text_file_edit_handler,
)
from .text_file_read_capability import DEFAULT_MAX_BYTES

CAPABILITY_NAME = "code_change_apply"

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "required": True},
        "old_text": {"type": "string", "required": True},
        "new_text": {"type": "string", "required": True},
    },
    "additionalProperties": False,
}

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {"type": "string"},
        "requested_path": {"type": "string"},
        "success": {"type": "boolean"},
        "change_applied": {"type": "boolean"},
        "change_metadata": {"type": "object"},
    },
}


def make_code_change_apply_handler(allowed_dirs=None, max_bytes=DEFAULT_MAX_BYTES):
    """Build the plain handler callable `Capability("code_change_apply")`
    is constructed with. Kept separate from
    `create_code_change_apply_capability` so a caller who only wants
    the bare callable (e.g. to register directly with
    `CapabilityHandlerRegistry`, no `Capability` wrapper involved) can
    get one without going through `Capability` at all.

    `allowed_dirs`/`max_bytes`, if given, are forwarded unchanged into
    the reused `code_change_plan` handler (which itself forwards them,
    unchanged, into `code_analysis`/`text_file_read`); `allowed_dirs`
    is also forwarded unchanged into the reused `text_file_edit`
    handler, so both reused handlers agree on exactly the same set of
    allowed directories for a single call - never a different,
    independently-resolved set for the plan step than for the apply
    step.
    """
    plan_handler = make_code_change_plan_handler(allowed_dirs=allowed_dirs, max_bytes=max_bytes)
    edit_handler = make_text_file_edit_handler(allowed_dirs=allowed_dirs)

    def handler(data):
        # Re-validated here only so a caller of the bare handler (not
        # going through `Capability.validate_input`) still gets the
        # same clear, immediate error `code_change_plan`'s own handler
        # already raises for these - never a new rule, the exact same
        # checks already made there.
        old_text = data.get("old_text") if isinstance(data, dict) else None
        new_text = data.get("new_text") if isinstance(data, dict) else None
        if not isinstance(old_text, str) or not old_text:
            raise ValueError("old_text must be a non-empty string.")
        if not isinstance(new_text, str):
            raise ValueError("new_text must be a string.")

        # Reused, unmodified: safe-path/.py-only validation, the
        # AST-based analysis, and the exact-one-occurrence fragment
        # check, exactly as a standalone `code_change_plan` call would
        # produce. Any unsafe precondition (path outside the allowed
        # directories, non-.py file, missing file, ...) raises here
        # exactly as it already would for a direct `code_change_plan`
        # call - before `text_file_edit`'s handler is ever reached.
        plan = plan_handler(data)

        if not plan["ready_to_apply"]:
            # Exactly the "apply only when ready_to_apply is true"
            # rule, enforced structurally: `edit_handler` is simply
            # never called on this path, so the file is left
            # completely untouched. Reported, not raised - same
            # "report, don't crash, for a substantive judgement"
            # convention `code_change_plan` itself already follows.
            return {
                "path": plan["path"],
                "requested_path": plan["requested_path"],
                "success": False,
                "change_applied": False,
                "change_metadata": {
                    "target_fragment": plan["target_fragment"],
                    "replacement": plan["replacement"],
                    "validation_status": plan["validation_status"],
                    "analysis_summary": plan["analysis_summary"],
                },
            }

        # Exactly one validated change, applied by calling
        # `text_file_edit`'s own, unmodified handler once - never a
        # second, differently-behaving write path, and never called
        # more than this one time for this one request.
        edit_result = edit_handler(data)

        return {
            "path": edit_result["path"],
            "requested_path": edit_result["requested_path"],
            "success": bool(edit_result["success"]),
            "change_applied": bool(edit_result["success"]),
            "change_metadata": {
                "target_fragment": plan["target_fragment"],
                "replacement": plan["replacement"],
                "occurrences_replaced": edit_result["occurrences_replaced"],
                "characters_removed": edit_result["characters_removed"],
                "characters_added": edit_result["characters_added"],
                "character_count_before": edit_result["character_count_before"],
                "character_count_after": edit_result["character_count_after"],
                "byte_size": edit_result["byte_size"],
            },
        }

    return handler


def create_code_change_apply_capability(allowed_dirs=None, max_bytes=DEFAULT_MAX_BYTES):
    """Build (but do not register anywhere) one `Capability` instance
    for `code_change_apply`. Never calls the handler; same "construct,
    don't execute" convention `Capability.__init__` itself already
    follows."""
    handler = make_code_change_apply_handler(allowed_dirs=allowed_dirs, max_bytes=max_bytes)
    return Capability(
        CAPABILITY_NAME,
        handler,
        description=(
            "Plan one exact-fragment text change to an existing Python "
            "(.py) file using the existing code_change_plan capability, "
            "then apply it - by calling the existing text_file_edit "
            "capability's own handler - only if that plan reports "
            "ready_to_apply; never applies more than one validated "
            "change per call, and leaves the file untouched if the plan "
            "is not ready."
        ),
        input_schema=INPUT_SCHEMA,
        output_schema=OUTPUT_SCHEMA,
        metadata={
            "category": "file_output",
            "read_only": False,
            "local_only": True,
            "applies_via": TEXT_FILE_EDIT_CAPABILITY_NAME,
        },
    )


def register_code_change_apply_capability(
    registry, allowed_dirs=None, max_bytes=DEFAULT_MAX_BYTES, enabled=True,
):
    """Build a fresh `code_change_apply` `Capability` and register it
    into `registry` - an `ExecutableCapabilityRegistry`
    (execution/executable_registry.py) or a `CapabilityHandlerRegistry`
    (execution/capability_handlers.py), both of which already expose a
    `register`/`register_capability` method that accepts a `Capability`
    object unchanged. Never registers into any registry the caller
    didn't explicitly hand in, and never registers more than once on
    its own initiative - calling this twice against the same registry
    raises exactly the same "duplicate name" error either registry
    already raises for that case. Returns the `Capability` that was
    registered."""
    capability = create_code_change_apply_capability(allowed_dirs=allowed_dirs, max_bytes=max_bytes)
    if hasattr(registry, "register_capability"):
        registry.register_capability(capability)
    else:
        registry.register(capability, enabled=enabled)
    return capability
