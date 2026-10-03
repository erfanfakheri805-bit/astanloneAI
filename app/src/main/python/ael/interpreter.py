"""
AEL Interpreter
================
Executes validated AEL instructions by calling into the Learning,
Skill, Upgrade, and Reasoning systems. The interpreter never touches
storage directly - it only orchestrates calls to the systems that own
that responsibility.

`upgrade_system`, `reasoning_engine`, and `memory` are optional so the
interpreter can still be constructed and exercised in isolation (e.g.
to test TEACH/RELATE/SKILL alone) without wiring the entire
application. An instruction that needs a system that wasn't supplied
fails with a clear, structured error rather than raising.
"""

from .ael_parser import parse_program
from .validator import validate


class ExecutionResult:
    def __init__(self, instruction, success, message):
        self.instruction = instruction
        self.success = success
        self.message = message

    def to_dict(self):
        return {
            "instruction": self.instruction.to_dict() if self.instruction else None,
            "success": self.success,
            "message": self.message,
        }


class AELInterpreter:
    def __init__(self, learning_system, skill_system, upgrade_system=None,
                 reasoning_engine=None, memory=None, rule_registry=None):
        self.learning_system = learning_system
        self.skill_system = skill_system
        self.upgrade_system = upgrade_system
        self.reasoning_engine = reasoning_engine
        self.memory = memory
        # Optional, like upgrade_system/reasoning_engine above - RULE fails
        # with a clear structured error (not a crash) if no registry was
        # supplied (see _execute_rule below), same pattern as
        # _execute_upgrade when upgrade_system is missing.
        self.rule_registry = rule_registry

    def run(self, source):
        """Parse + validate + execute an AEL program (one or more lines).
        Returns a list of ExecutionResult, one per instruction."""
        results = []
        try:
            instructions = parse_program(source)
        except Exception as e:
            return [ExecutionResult(None, False, f"AEL syntax error: {e}")]

        if not instructions:
            return [ExecutionResult(None, False, "No AEL instructions found.")]

        for instruction in instructions:
            check = validate(instruction)
            if not check:
                results.append(ExecutionResult(instruction, False, "; ".join(check.errors)))
                continue
            results.append(self._execute(instruction))
        return results

    def _execute(self, instruction):
        handlers = {
            "TEACH": self._execute_teach,
            "RELATE": self._execute_relate,
            "SKILL": self._execute_skill,
            "ASK": self._execute_ask,
            "UPGRADE": self._execute_upgrade,
            "ROLLBACK": self._execute_rollback,
            "RULE": self._execute_rule,
        }
        handler = handlers.get(instruction.kind)
        if not handler:
            return ExecutionResult(instruction, False, f"No handler for {instruction.kind}")
        try:
            return handler(instruction)
        except Exception as e:
            if self.memory:
                self.memory.log_error(
                    operation=f"ael:{instruction.kind}",
                    message=str(e),
                    context=str(instruction.to_dict()),
                )
            return ExecutionResult(instruction, False, f"Execution error: {e}")

    def _execute_teach(self, instruction):
        entry = self.learning_system.teach(instruction.args["name"], instruction.args["description"])
        return ExecutionResult(instruction, True, f"Learned concept '{entry['name']}'.")

    def _execute_relate(self, instruction):
        outcome = self.learning_system.relate(
            instruction.args["from"], instruction.args["to"], instruction.args["relation"]
        )
        message = (
            f"Related '{instruction.args['from']}' -> '{instruction.args['to']}' "
            f"as '{instruction.args['relation']}'."
        )
        if not outcome["created"]:
            message += " (Already known - no duplicate stored.)"
        if outcome["contradiction"]:
            c = outcome["contradiction"]
            message += (
                f" NOTE: this conflicts with existing knowledge - "
                f"'{c['from_name']}' is already recorded as '{c['relation_type']}' "
                f"'{c['to_name']}'."
            )
        return ExecutionResult(instruction, True, message)

    def _execute_skill(self, instruction):
        self.skill_system.add_skill(
            name=instruction.args["name"],
            description=f"Learned via AEL: responds to {instruction.args['keywords']}",
            trigger={"type": "keyword", "keywords": instruction.args["keywords"]},
            response=instruction.args["response"],
            source="ael",
        )
        return ExecutionResult(instruction, True, f"Skill '{instruction.args['name']}' installed.")

    def _execute_ask(self, instruction):
        name = instruction.args["name"]
        info = self.learning_system.recall(name)
        if not info:
            return ExecutionResult(instruction, True, f"I don't know anything about '{name}' yet.")

        lines = [f"{name}: {info['description'] or '(no description yet)'}"]
        for rel in info["relationships"]["outgoing"]:
            lines.append(f"  {name} {rel['relation_type']} {rel['to_name']}")
        for rel in info["relationships"]["incoming"]:
            lines.append(f"  {rel['from_name']} {rel['relation_type']} {name}")

        if self.reasoning_engine:
            for rel_a, rel_b in self.reasoning_engine.contradictions_for(name):
                lines.append(
                    f"  NOTE: conflicting info toward '{rel_a['to_name']}' - both "
                    f"'{rel_a['relation_type']}' and '{rel_b['relation_type']}' are recorded."
                )

        return ExecutionResult(instruction, True, "\n".join(lines))

    def _execute_upgrade(self, instruction):
        if not self.upgrade_system:
            return ExecutionResult(instruction, False, "Upgrade system is not available.")
        result = self.upgrade_system.propose_upgrade(
            instruction.args["name"], instruction.args["description"]
        )
        record = result["upgrade"]
        return ExecutionResult(
            instruction, True,
            f"Upgrade '{record['name']}' -> status: {record['status']} (stage: {record['stage']}).",
        )

    def _execute_rollback(self, instruction):
        if not self.upgrade_system:
            return ExecutionResult(instruction, False, "Upgrade system is not available.")
        version_id = int(instruction.args["version_id"])
        target = self.upgrade_system.versions.rollback_to(version_id)
        if not target:
            return ExecutionResult(instruction, False, f"No version found with id {version_id}.")
        return ExecutionResult(
            instruction, True,
            f"Rolled back to version '{target['version_label']}' (id {version_id}).",
        )

    def _execute_rule(self, instruction):
        if not self.rule_registry:
            return ExecutionResult(instruction, False, "Rule registry is not available.")
        try:
            record = self.rule_registry.register(
                name=instruction.args["name"],
                premises=[tuple(c) for c in instruction.args["conditions"]],
                conclusion=tuple(instruction.args["conclusion"]),
                source="ael",
            )
        except ValueError as e:
            return ExecutionResult(instruction, False, f"Invalid rule: {e}")
        conditions_text = " AND ".join(f"{a} {r} {b}" for a, r, b in record["conditions"])
        c_from, c_rel, c_to = record["conclusion"]
        return ExecutionResult(
            instruction, True,
            f"Rule '{record['name']}' registered (id {record['id']}, version {record['version']}): "
            f"IF {conditions_text} THEN {c_from} {c_rel} {c_to}.",
        )
