"""
Prompt 843 - capability lifecycle foundation focused tests.

Run (from app/src/main/python/):
    python -m unittest tests.test_capability_lifecycle_prompt843 -v
"""

import ast
import copy
import inspect
import itertools
import json
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from capabilities import capability_lifecycle as cl
from capabilities import capability_registry as cr
from capabilities import capability_identity as ci
from capabilities.capability_lifecycle import (
    validate_lifecycle_state as vstate,
    evaluate_lifecycle_transition as ev,
    get_allowed_next_states as nxt,
    list_lifecycle_states as lstates,
    list_lifecycle_transitions as ltrans,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

STATES = ["defined", "validated", "enabled", "disabled", "deprecated"]

# Independent statement of the specification (not read from the module).
ALLOWED = {
    ("defined", "validated"), ("defined", "deprecated"),
    ("validated", "enabled"), ("validated", "disabled"), ("validated", "deprecated"),
    ("enabled", "disabled"), ("enabled", "deprecated"),
    ("disabled", "enabled"), ("disabled", "deprecated"),
}

TRANSITION_KEYS = ["version", "allowed", "current", "requested", "reason", "errors",
                   "execution_allowed", "executed"]


def desc(**over):
    d = {"name": "text_summary", "version": 1, "purpose": "Summarise supplied text.",
         "inputs": ["text"], "outputs": ["summary"], "constraints": [], "enabled": False}
    d.update(over)
    return d


class StrSub(str):
    pass


BAD_TYPES = [None, 1, 0, True, False, 1.5, b"defined", ["defined"], ("defined",), {"defined"},
             {"state": "defined"}, object(), StrSub("defined"), StrSub("enabled")]
UNKNOWN = ["", " ", "Defined", "DEFINED", "defined ", " defined", "defined\n", "enable", "enabled2",
           "active", "removed", "disable", "validate", "deprecate", "x" * 17, "x" * 100000,
           "définéd", "defined\x00"]


class StateTests(unittest.TestCase):
    def test_states_list(self):
        r = lstates()
        self.assertEqual(r["states"], STATES)
        self.assertEqual(r["count"], 5)
        self.assertEqual(list(r), ["version", "count", "states", "execution_allowed", "executed"])
        self.assertEqual(cl.LIFECYCLE_STATES, tuple(STATES))

    def test_states_list_is_fresh(self):
        a = lstates()
        a["states"].append("x")
        a["states"].clear()
        self.assertEqual(lstates()["states"], STATES)
        self.assertIsNot(lstates()["states"], lstates()["states"])

    def test_every_state_is_valid(self):
        for s in STATES:
            r = vstate(s)
            self.assertEqual(r, {"version": 1, "valid": True, "state": s, "errors": [],
                                 "execution_allowed": False, "executed": False})
            self.assertEqual(list(r), ["version", "valid", "state", "errors",
                                       "execution_allowed", "executed"])

    def test_bad_types(self):
        for bad in BAD_TYPES:
            r = vstate(bad)
            self.assertFalse(r["valid"], repr(bad))
            self.assertIsNone(r["state"])
            self.assertEqual(r["errors"], [{"code": "invalid_state_type", "where": "state"}])

    def test_unknown_states(self):
        for bad in UNKNOWN:
            r = vstate(bad)
            self.assertFalse(r["valid"], repr(bad[:20]))
            self.assertEqual(r["errors"], [{"code": "unknown_state", "where": "state"}])

    def test_no_normalisation(self):
        for s in STATES:
            self.assertFalse(vstate(s.upper())["valid"])
            self.assertFalse(vstate(s.title())["valid"])
            self.assertFalse(vstate(" " + s)["valid"])
            self.assertFalse(vstate(s + " ")["valid"])

    def test_validation_fresh_and_json(self):
        a, b = vstate("enabled"), vstate("enabled")
        self.assertEqual(a, b)
        self.assertIsNot(a, b)
        self.assertIsNot(a["errors"], b["errors"])
        a["errors"].append("x")
        self.assertEqual(vstate("enabled")["errors"], [])
        json.dumps(vstate("enabled"))
        json.dumps(vstate(None))


class TransitionMatrixTests(unittest.TestCase):
    def test_every_pair_of_states(self):
        self.assertEqual(len(list(itertools.product(STATES, STATES))), 25)
        for cur, req in itertools.product(STATES, STATES):
            r = ev(cur, req)
            self.assertEqual(list(r), TRANSITION_KEYS)
            self.assertEqual((r["current"], r["requested"]), (cur, req))
            self.assertIs(r["allowed"], (cur, req) in ALLOWED, (cur, req))
            self.assertIs(r["execution_allowed"], False)
            self.assertIs(r["executed"], False)

    def test_exactly_nine_allowed(self):
        allowed = [(c, q) for c, q in itertools.product(STATES, STATES) if ev(c, q)["allowed"]]
        self.assertEqual(set(allowed), ALLOWED)
        self.assertEqual(len(allowed), 9)

    def test_each_allowed_transition(self):
        for cur, req in sorted(ALLOWED):
            r = ev(cur, req)
            self.assertEqual(r, {"version": 1, "allowed": True, "current": cur, "requested": req,
                                 "reason": "allowed", "errors": [], "execution_allowed": False,
                                 "executed": False}, (cur, req))

    def test_same_state_rejected(self):
        for s in STATES:
            r = ev(s, s)
            self.assertFalse(r["allowed"])
            self.assertEqual(r["reason"], "same_state")
            self.assertEqual(r["errors"], [{"code": "same_state", "where": "transition"}])

    def test_deprecated_is_terminal(self):
        for req in STATES:
            if req == "deprecated":
                continue
            r = ev("deprecated", req)
            self.assertFalse(r["allowed"])
            self.assertEqual(r["reason"], "terminal_state")
            self.assertEqual(r["errors"], [{"code": "terminal_state", "where": "transition"}])

    def test_other_rejections(self):
        expected_rejected = {
            ("defined", "enabled"), ("defined", "disabled"),
            ("validated", "defined"),
            ("enabled", "defined"), ("enabled", "validated"),
            ("disabled", "defined"), ("disabled", "validated"),
        }
        for cur, req in expected_rejected:
            r = ev(cur, req)
            self.assertFalse(r["allowed"], (cur, req))
            self.assertEqual(r["reason"], "transition_not_allowed", (cur, req))
            self.assertEqual(r["errors"], [{"code": "transition_not_allowed", "where": "transition"}])

    def test_rejection_partition_is_complete(self):
        counts = {"allowed": 0, "same_state": 0, "terminal_state": 0, "transition_not_allowed": 0}
        for cur, req in itertools.product(STATES, STATES):
            counts[ev(cur, req)["reason"]] += 1
        self.assertEqual(counts, {"allowed": 9, "same_state": 5, "terminal_state": 4,
                                  "transition_not_allowed": 7})

    def test_cannot_skip_validation(self):
        self.assertFalse(ev("defined", "enabled")["allowed"])
        self.assertFalse(ev("defined", "disabled")["allowed"])
        self.assertTrue(ev("defined", "validated")["allowed"])
        self.assertTrue(ev("validated", "enabled")["allowed"])

    def test_enable_disable_cycle_allowed_but_not_back_to_validated(self):
        self.assertTrue(ev("enabled", "disabled")["allowed"])
        self.assertTrue(ev("disabled", "enabled")["allowed"])
        self.assertFalse(ev("disabled", "validated")["allowed"])

    def test_every_non_terminal_state_can_be_deprecated(self):
        for s in STATES[:-1]:
            self.assertTrue(ev(s, "deprecated")["allowed"], s)

    def test_deterministic_and_fresh(self):
        a, b = ev("defined", "validated"), ev("defined", "validated")
        self.assertEqual(a, b)
        self.assertIsNot(a, b)
        bad_a, bad_b = ev("defined", "enabled"), ev("defined", "enabled")
        self.assertIsNot(bad_a["errors"], bad_b["errors"])
        bad_a["errors"].clear()
        self.assertTrue(ev("defined", "enabled")["errors"])

    def test_json_safe(self):
        for cur, req in itertools.product(STATES, STATES):
            json.dumps(ev(cur, req))


class MalformedTransitionInputTests(unittest.TestCase):
    def test_bad_current(self):
        for bad in BAD_TYPES:
            r = ev(bad, "validated")
            self.assertFalse(r["allowed"])
            self.assertEqual(r["reason"], "invalid_current_state")
            self.assertIsNone(r["current"])
            self.assertEqual(r["requested"], "validated")
            self.assertEqual(r["errors"], [{"code": "invalid_state_type", "where": "current"}])

    def test_bad_requested(self):
        for bad in BAD_TYPES:
            r = ev("defined", bad)
            self.assertFalse(r["allowed"])
            self.assertEqual(r["reason"], "invalid_requested_state")
            self.assertEqual(r["current"], "defined")
            self.assertIsNone(r["requested"])
            self.assertEqual(r["errors"], [{"code": "invalid_state_type", "where": "requested"}])

    def test_unknown_states(self):
        for bad in UNKNOWN:
            r = ev(bad, "validated")
            self.assertEqual((r["allowed"], r["reason"]), (False, "invalid_current_state"))
            self.assertEqual(r["errors"], [{"code": "unknown_state", "where": "current"}])
            r = ev("defined", bad)
            self.assertEqual((r["allowed"], r["reason"]), (False, "invalid_requested_state"))
            self.assertEqual(r["errors"], [{"code": "unknown_state", "where": "requested"}])

    def test_both_bad(self):
        r = ev(None, "nope")
        self.assertEqual(r["reason"], "invalid_current_state")
        self.assertEqual(r["errors"], [{"code": "invalid_state_type", "where": "current"},
                                       {"code": "unknown_state", "where": "requested"}])
        self.assertIsNone(r["current"])
        self.assertIsNone(r["requested"])

    def test_malformed_never_allowed(self):
        for a, b in itertools.product(BAD_TYPES + UNKNOWN[:6] + STATES, repeat=2):
            if a in STATES and b in STATES and type(a) is str and type(b) is str:
                continue
            self.assertFalse(ev(a, b)["allowed"])

    def test_same_malformed_values_not_same_state(self):
        for bad in (None, "", "nope"):
            self.assertNotEqual(ev(bad, bad)["reason"], "same_state")

    def test_hostile_objects_never_raise(self):
        class Boom:
            def __eq__(self, other):
                raise RuntimeError("boom")
            __hash__ = None

            def __len__(self):
                raise RuntimeError("boom")

        r = ev(Boom(), Boom())
        self.assertFalse(r["allowed"])
        self.assertFalse(vstate(Boom())["valid"])
        self.assertFalse(nxt(Boom())["valid"])

    def test_inputs_not_modified(self):
        data = ["defined", "validated"]
        before = copy.deepcopy(data)
        ev(*data)
        self.assertEqual(data, before)


class NextStatesAndTableTests(unittest.TestCase):
    def test_next_states_match_table(self):
        for cur in STATES:
            r = nxt(cur)
            self.assertTrue(r["valid"])
            self.assertEqual(r["current"], cur)
            self.assertEqual(set(r["next_states"]), {q for c, q in ALLOWED if c == cur})
            self.assertEqual(r["next_states"], [s for s in STATES if (cur, s) in ALLOWED])
            self.assertEqual(r["errors"], [])
            self.assertEqual(list(r), ["version", "valid", "current", "next_states", "errors",
                                       "execution_allowed", "executed"])

    def test_deprecated_has_no_next_states(self):
        self.assertEqual(nxt("deprecated")["next_states"], [])

    def test_next_states_agree_with_evaluation(self):
        for cur, req in itertools.product(STATES, STATES):
            self.assertEqual(req in nxt(cur)["next_states"], ev(cur, req)["allowed"])

    def test_next_states_malformed(self):
        for bad in BAD_TYPES + UNKNOWN:
            r = nxt(bad)
            self.assertFalse(r["valid"])
            self.assertEqual(r["next_states"], [])
            self.assertIsNone(r["current"])
            self.assertEqual(len(r["errors"]), 1)
            self.assertEqual(r["errors"][0]["where"], "current")

    def test_next_states_fresh(self):
        a = nxt("validated")
        a["next_states"].append("x")
        self.assertEqual(nxt("validated")["next_states"], ["enabled", "disabled", "deprecated"])

    def test_transition_list(self):
        r = ltrans()
        self.assertEqual(r["count"], 9)
        self.assertEqual({(t["from"], t["to"]) for t in r["transitions"]}, ALLOWED)
        self.assertEqual(len(r["transitions"]), 9)
        self.assertEqual(list(r), ["version", "count", "transitions", "execution_allowed", "executed"])
        self.assertEqual(list(r["transitions"][0]), ["from", "to"])
        self.assertEqual(r["transitions"][0], {"from": "defined", "to": "validated"})
        json.dumps(r)

    def test_transition_list_fresh(self):
        a = ltrans()
        a["transitions"][0]["to"] = "hacked"
        a["transitions"].clear()
        self.assertEqual(ltrans()["count"], 9)
        self.assertEqual(ltrans()["transitions"][0], {"from": "defined", "to": "validated"})

    def test_module_table_is_immutable(self):
        self.assertIsInstance(cl.LIFECYCLE_STATES, tuple)
        self.assertIsInstance(cl._ALLOWED, tuple)
        for _src, targets in cl._ALLOWED:
            self.assertIsInstance(targets, tuple)


class NoExecutionTests(unittest.TestCase):
    def results(self):
        out = [lstates(), ltrans()]
        for s in STATES + [None, "x"]:
            out += [vstate(s), nxt(s)]
            for t in STATES + [None, "x"]:
                out.append(ev(s, t))
        return out

    def test_execution_flags_always_false(self):
        for r in self.results():
            self.assertIs(r["execution_allowed"], False)
            self.assertIs(r["executed"], False)

    def test_enabled_state_does_not_imply_execution(self):
        r = ev("validated", "enabled")
        self.assertTrue(r["allowed"])
        self.assertIs(r["execution_allowed"], False)
        self.assertIs(r["executed"], False)
        self.assertIs(vstate("enabled")["execution_allowed"], False)
        self.assertIs(nxt("enabled")["execution_allowed"], False)

    def test_stateless_module(self):
        for name, value in vars(cl).items():
            if name.startswith("__"):
                continue
            self.assertNotIsInstance(value, (dict, list, set), name)

    def test_no_state_is_stored_between_calls(self):
        ev("defined", "validated")
        ev("validated", "enabled")
        self.assertEqual(ev("defined", "validated")["allowed"], True)
        self.assertEqual(ev("defined", "enabled")["allowed"], False)

    def test_no_mutating_api(self):
        public = [n for n, v in vars(cl).items() if callable(v) and not n.startswith("_")]
        self.assertEqual(sorted(public), ["evaluate_lifecycle_transition", "get_allowed_next_states",
                                          "list_lifecycle_states", "list_lifecycle_transitions",
                                          "validate_lifecycle_state"])
        for name in public:
            for banned in ("set", "apply", "perform", "register", "enable", "execute", "run", "upgrade",
                           "remove", "replace", "load"):
                self.assertFalse(name.startswith(banned), name)

    def test_functions_take_states_not_descriptors(self):
        d = desc(enabled=True)
        self.assertFalse(vstate(d)["valid"])
        self.assertFalse(ev(d, "validated")["allowed"])
        self.assertFalse(nxt(d)["valid"])

    def test_state_not_inferred_from_descriptor_fields(self):
        # descriptor fields never become states; the lifecycle only accepts exact state strings
        d = desc(name="enabled", purpose="deprecated", version=3, enabled=True)
        for value in (d["name"], d["purpose"]):
            self.assertEqual(vstate(value)["valid"], value in STATES)
        for value in (d["version"], d["enabled"], d["inputs"], d["outputs"]):
            self.assertFalse(vstate(value)["valid"])


class BoundaryTests(unittest.TestCase):
    def test_module_has_no_imports(self):
        tree = ast.parse(inspect.getsource(cl))
        self.assertEqual([n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))], [])

    def test_no_execution_loading_or_io(self):
        body = inspect.getsource(cl).split('"""', 2)[2]
        for banned in ("importlib", "__import__", "exec(", "eval(", "subprocess", "socket", "urllib",
                       "requests", "open(", "os.", "sys.", "random", "time.", "datetime", "global "):
            self.assertNotIn(banned, body, banned)

    def test_other_layers_do_not_reference_lifecycle(self):
        for folder in ("core", "memory", "ael", "reasoning", "understanding", "planning", "agent",
                       "execution"):
            for dirpath, _dirs, files in os.walk(os.path.join(ROOT, folder)):
                for f in files:
                    if f.endswith(".py"):
                        with open(os.path.join(dirpath, f), encoding="utf-8") as fh:
                            text = fh.read()
                            for needle in ("capabilities.capability_lifecycle", "import capability_lifecycle",
                                           "capabilities import capability_lifecycle"):
                                self.assertNotIn(needle, text, f)
        for module in (cr, ci):
            self.assertNotIn("capability_lifecycle", inspect.getsource(module))


class BackwardCompatibilityTests(unittest.TestCase):
    def test_registry_surface_and_behaviour_preserved(self):
        self.assertEqual(cr.DESCRIPTOR_FIELDS, ("name", "version", "purpose", "inputs", "outputs",
                                                "constraints", "enabled"))
        self.assertEqual([n for n in dir(cr.CapabilityRegistry) if not n.startswith("_")],
                         ["list_capabilities", "lookup", "register"])
        reg = cr.CapabilityRegistry()
        self.assertEqual(reg.register(desc())["status"], "registered")
        self.assertEqual(reg.register(desc())["reason"], "duplicate")
        self.assertEqual(reg.register(desc(version=2))["reason"], "conflict")
        self.assertEqual(reg.register(desc(version="1"))["reason"], "malformed")
        self.assertEqual(reg.lookup("text_summary")["descriptor"], desc())
        self.assertEqual(reg.register(desc(**{"enabled": True, "name": "other_cap"}))["status"], "registered")

    def test_registry_unaffected_by_lifecycle_evaluation(self):
        reg = cr.CapabilityRegistry()
        reg.register(desc())
        before = reg.list_capabilities()
        ev("defined", "validated")
        ev("validated", "enabled")
        self.assertEqual(reg.list_capabilities(), before)

    def test_descriptor_structure_unchanged(self):
        self.assertNotIn("state", cr.DESCRIPTOR_FIELDS)
        self.assertNotIn("lifecycle", cr.DESCRIPTOR_FIELDS)
        self.assertEqual(cr.validate_capability_descriptor(desc(state="defined"))["errors"],
                         [{"code": "unexpected_field", "where": "state"}])
        self.assertEqual(cr.validate_capability_descriptor(desc(lifecycle="enabled"))["errors"],
                         [{"code": "unexpected_field", "where": "lifecycle"}])

    def test_identity_layer_preserved(self):
        self.assertEqual(ci.classify_capability_descriptors(desc(), desc(version=2))["classification"],
                         "newer_version")
        self.assertEqual(ci.classify_capability_descriptors(desc(), desc())["classification"],
                         "same_version")
        self.assertEqual(ci.build_capability_identity(desc())["identity"], {"name": "text_summary"})
        self.assertEqual(ci.parse_capability_version("1")["valid"], False)
        self.assertEqual(ci.compare_capability_versions(3, 2)["relation"], "newer")

    def test_earlier_tests_present(self):
        for name in ("test_capability_registry_prompt841.py", "test_capability_identity_prompt842.py",
                     "test_capability_boundary_prompt840.py"):
            self.assertTrue(os.path.exists(os.path.join(ROOT, "tests", name)), name)

    def test_older_capability_modules_preserved(self):
        from capabilities import capability_system as cs
        self.assertEqual(len(cs.PLANNED_CAPABILITIES), 8)
        with open(os.path.join(ROOT, "capabilities", "__init__.py"), "rb") as fh:
            self.assertEqual(fh.read().strip(), b"")

    def test_reasoning_and_nlu_apis_preserved(self):
        from reasoning.capability_contract import build_capability_contract, validate_capability_contract
        from reasoning.capability_integration import integrate_capability_contract, classify_capability_result
        from reasoning.capability_boundary import evaluate_reasoning_capability_boundary as b
        from reasoning.reasoning_decision import decide_reasoning
        from understanding.nlu_pipeline import default_pipeline
        for fn in (build_capability_contract, validate_capability_contract, integrate_capability_contract,
                   classify_capability_result, b, decide_reasoning, default_pipeline):
            self.assertTrue(callable(fn))
        self.assertFalse(b(None)["executed"])
        self.assertEqual(list(b(None)), ["version", "decision_state", "capability_classification",
                                         "contract_valid", "execution_allowed", "next_stage",
                                         "reason", "executed"])


if __name__ == "__main__":
    unittest.main()
