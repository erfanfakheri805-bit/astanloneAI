"""
Sandbox
========
Foundation for a safe, isolated environment where a proposed upgrade can
be tested BEFORE it ever touches the running application.

IMPORTANT - honesty about scope:
This foundation stage does not execute or apply arbitrary generated
code. There is no real AI-driven code generation yet for the sandbox to
run. What's built here is the *interface* a future real sandbox will
implement: given an upgrade payload, run it in isolation and return a
structured, trustworthy verdict.

For now, `run` performs static, inspectable checks only (payload shape,
declared fields present, no execution of arbitrary code) and reports a
clearly-labeled simulated result. This keeps the lifecycle wiring real
and testable without pretending the AI can already validate arbitrary
self-generated code safely - that is real future work, not a shortcut
to fake here.
"""


class SandboxResult:
    def __init__(self, passed, details):
        self.passed = passed
        self.details = details

    def to_dict(self):
        return {"passed": self.passed, "details": self.details}


class Sandbox:
    REQUIRED_PAYLOAD_FIELDS = ["name", "description"]

    def run(self, upgrade_payload):
        """Static, non-executing check of an upgrade payload.
        Returns a SandboxResult. No arbitrary code is executed here."""
        missing = [f for f in self.REQUIRED_PAYLOAD_FIELDS if f not in upgrade_payload]
        if missing:
            return SandboxResult(False, f"Missing required fields: {missing}")

        if not isinstance(upgrade_payload.get("name"), str) or not upgrade_payload["name"].strip():
            return SandboxResult(False, "Upgrade name must be a non-empty string.")

        return SandboxResult(
            True,
            "Static validation passed (structural check only - this foundation stage "
            "does not execute generated code in the sandbox).",
        )
