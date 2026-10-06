"""
Prompt 844 - capability validation foundation focused tests.

Run (from app/src/main/python/):
    python -m unittest tests.test_capability_validation_prompt844 -v
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

from capabilities import capability_identity as ci
from capabilities import capability_lifecycle as cl
from capabilities import capability_registry as cr
from capabilities import capability_validation as cv
from capabilities.capability_validation import validate_capability as validate

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATES = ["defined", "validated", "enabled", "disabled", "deprecated"]
KEYS = ["valid", "errors", "name", "version", "identity_valid", "version_valid",
        "lifecycle_valid", "truncated", "execution_allowed", "executed"]


def desc(**over):
    d = {"name": "text_summary", "version": 2, "purpose": "Summarise supplied text.",
         "inputs": ["text"], "outputs": ["summary"], "constraints": ["No network access."],
         "enabled": False}
    d.update(over)
    return d


def err(code, where):
    return {"code": code, "where": where}


class StrSub(str):
    pass


class DictSub(dict):
    pass


class ValidDescriptorTests(unittest.TestCase):
    def test_valid_without_lifecycle(self):
        r = validate(desc())
        self.assertEqual(r, {"valid": True, "errors": [], "name": "text_summary", "version": 2,
                             "identity_valid": True, "version_valid": True, "lifecycle_valid": None,
                             "truncated": False, "execution_allowed": False, "executed": False})
        self.assertEqual(list(r), KEYS)

    def test_valid_with_every_lifecycle_state(self):
        for s in STATES:
            r = validate(desc(), s)
            self.assertTrue(r["valid"], s)
            self.assertIs(r["lifecycle_valid"], True)
            self.assertEqual(r["errors"], [])
            self.assertEqual(list(r), KEYS)

    def test_lifecycle_keyword_form(self):
        self.assertEqual(validate(desc(), lifecycle_state="enabled"), validate(desc(), "enabled"))

    def test_valid_variants(self):
        for d in (desc(inputs=[], constraints=[]), desc(enabled=True), desc(version=1),
                  desc(version=cr.MAX_VERSION), desc(name="a" * 64), desc(name="a1_b2")):
            r = validate(d)
            self.assertTrue(r["valid"], d["name"])
            self.assertEqual((r["name"], r["version"]), (d["name"], d["version"]))

    def test_flags_are_booleans(self):
        r = validate(desc(), "defined")
        for key in ("valid", "identity_valid", "version_valid", "lifecycle_valid"):
            self.assertIs(type(r[key]), bool, key)

    def test_valid_result_still_not_executable(self):
        r = validate(desc(enabled=True), "enabled")
        self.assertTrue(r["valid"])
        self.assertIs(r["execution_allowed"], False)
        self.assertIs(r["executed"], False)

    def test_json_safe(self):
        json.dumps(validate(desc(), "enabled"))
        json.dumps(validate(None, None))


class MalformedDescriptorTests(unittest.TestCase):
    CASES = [None, 1, "x", [], (), set(), {}, DictSub(desc()),
             desc(name="Bad"), desc(name=""), desc(name=" x"), desc(name=5), desc(name=StrSub("ok")),
             desc(version=0), desc(version="1"), desc(version=True),
             desc(purpose=""), desc(purpose=" x"), desc(purpose=None),
             desc(inputs="a"), desc(inputs=["Bad"]), desc(inputs=["a", "a"]),
             desc(outputs=[]), desc(outputs=None), desc(constraints=[" x"]),
             desc(enabled=1), desc(enabled="yes"),
             desc(handler="x"), desc(tool="x"), desc(execution_allowed=False), desc(state="defined")]

    def test_never_valid_and_never_raises(self):
        for d in self.CASES:
            r = validate(d)
            self.assertFalse(r["valid"], repr(d))
            self.assertEqual(list(r), KEYS)
            self.assertTrue(r["errors"])
            self.assertIs(r["execution_allowed"], False)
            self.assertIs(r["executed"], False)

    def test_errors_are_the_prompt841_errors_unchanged(self):
        for d in self.CASES:
            self.assertEqual(validate(d)["errors"], cr.validate_capability_descriptor(d)["errors"], repr(d))
            self.assertEqual(validate(d)["truncated"], cr.validate_capability_descriptor(d)["truncated"])

    def test_valid_agrees_with_registry_validator(self):
        for d in self.CASES + [desc()]:
            self.assertEqual(validate(d)["valid"], cr.validate_capability_descriptor(d)["valid"])

    def test_non_dict_has_no_flags_true(self):
        for d in (None, 1, "x", [], DictSub(desc())):
            r = validate(d)
            self.assertEqual((r["name"], r["version"]), (None, None))
            self.assertEqual((r["identity_valid"], r["version_valid"]), (False, False))
            self.assertEqual(r["errors"], [err("descriptor_not_dict", "descriptor")])

    def test_empty_dict(self):
        r = validate({})
        self.assertEqual([e["code"] for e in r["errors"]], ["missing_field"] * 7)
        self.assertEqual((r["identity_valid"], r["version_valid"], r["name"], r["version"]),
                         (False, False, None, None))

    def test_missing_fields_each(self):
        for field in cr.DESCRIPTOR_FIELDS:
            d = desc()
            del d[field]
            r = validate(d)
            self.assertFalse(r["valid"])
            self.assertEqual(r["errors"], [err("missing_field", field)])
            self.assertEqual(r["identity_valid"], field != "name")
            self.assertEqual(r["version_valid"], field != "version")

    def test_flags_are_independent(self):
        r = validate(desc(purpose=""))
        self.assertEqual((r["valid"], r["identity_valid"], r["version_valid"]), (False, True, True))
        self.assertEqual((r["name"], r["version"]), ("text_summary", 2))
        r = validate(desc(handler="x"))
        self.assertEqual((r["valid"], r["identity_valid"], r["version_valid"]), (False, True, True))
        self.assertEqual(r["errors"], [err("unexpected_field", "handler")])

    def test_invalid_name_not_echoed_nothing_normalised(self):
        for bad in ("Text_Summary", " text_summary", "text_summary ", "text-summary", "TEXT"):
            r = validate(desc(name=bad))
            self.assertIsNone(r["name"], repr(bad))
            self.assertFalse(r["identity_valid"])
            self.assertEqual(r["errors"], [err("invalid_name", "name")])
            self.assertEqual(r["version"], 2)

    def test_extra_fields_not_kept(self):
        r = validate(desc(handler="x", tool="y"))
        self.assertNotIn("handler", r)
        self.assertNotIn("tool", r)
        self.assertEqual(list(r), KEYS)

    def test_hostile_object_never_raises(self):
        class Boom(dict):
            def __iter__(self):
                raise RuntimeError("boom")
        r = validate(Boom())
        self.assertFalse(r["valid"])
        self.assertEqual(list(r), KEYS)
        d = desc()
        d["purpose"] = object()
        self.assertFalse(validate(d, "enabled")["valid"])

    def test_internal_failure_is_contained(self):
        original = cv.validate_capability_descriptor
        try:
            cv.validate_capability_descriptor = lambda d: 1 / 0
            r = validate(desc(), "enabled")
        finally:
            cv.validate_capability_descriptor = original
        self.assertEqual(r, {"valid": False, "errors": [err("validation_error", "descriptor")],
                             "name": None, "version": None, "identity_valid": False,
                             "version_valid": False, "lifecycle_valid": None, "truncated": False,
                             "execution_allowed": False, "executed": False})


class InvalidVersionTests(unittest.TestCase):
    def test_bad_versions(self):
        for bad in (0, -1, cr.MAX_VERSION + 1, True, False, 1.0, "1", "v1", None, [1], StrSub("1")):
            r = validate(desc(version=bad))
            self.assertFalse(r["valid"], repr(bad))
            self.assertFalse(r["version_valid"], repr(bad))
            self.assertIsNone(r["version"])
            self.assertTrue(r["identity_valid"])
            self.assertEqual(r["name"], "text_summary")
            self.assertEqual(r["errors"], [err("invalid_version", "version")])

    def test_version_flag_matches_prompt842(self):
        for v in (0, 1, 2, 999, cr.MAX_VERSION, cr.MAX_VERSION + 1, True, "1", 1.5, None):
            self.assertEqual(validate(desc(version=v))["version_valid"], ci.parse_capability_version(v)["valid"])

    def test_missing_version(self):
        d = desc()
        del d["version"]
        r = validate(d)
        self.assertEqual((r["version_valid"], r["version"]), (False, None))
        self.assertEqual(r["errors"], [err("missing_field", "version")])

    def test_version_not_normalised(self):
        self.assertFalse(validate(desc(version="2"))["version_valid"])
        self.assertFalse(validate(desc(version=2.0))["version_valid"])

    def test_newer_older_versions_all_valid(self):
        for v in (1, 2, 3, 100):
            self.assertTrue(validate(desc(version=v))["valid"])


class LifecycleStateTests(unittest.TestCase):
    BAD_TYPES = [None, 1, True, 1.5, b"enabled", ["enabled"], {"enabled"}, StrSub("enabled"), object()]
    UNKNOWN = ["", "Enabled", "ENABLED", " enabled", "enabled ", "active", "removed", "x" * 100000]

    def test_bad_type_states(self):
        for bad in self.BAD_TYPES:
            r = validate(desc(), bad)
            self.assertFalse(r["valid"], repr(bad))
            self.assertIs(r["lifecycle_valid"], False)
            self.assertEqual(r["errors"], [err("invalid_state_type", "lifecycle_state")])
            # the descriptor itself is still reported as fine
            self.assertEqual((r["identity_valid"], r["version_valid"]), (True, True))
            self.assertEqual((r["name"], r["version"]), ("text_summary", 2))

    def test_unknown_states(self):
        for bad in self.UNKNOWN:
            r = validate(desc(), bad)
            self.assertFalse(r["valid"])
            self.assertIs(r["lifecycle_valid"], False)
            self.assertEqual(r["errors"], [err("unknown_state", "lifecycle_state")])

    def test_explicit_none_is_invalid_but_omitted_is_not_checked(self):
        self.assertIs(validate(desc())["lifecycle_valid"], None)
        self.assertTrue(validate(desc())["valid"])
        r = validate(desc(), None)
        self.assertIs(r["lifecycle_valid"], False)
        self.assertFalse(r["valid"])

    def test_lifecycle_codes_come_from_prompt843(self):
        for bad in self.BAD_TYPES + self.UNKNOWN:
            code = cl.validate_lifecycle_state(bad)["errors"][0]["code"]
            self.assertEqual(validate(desc(), bad)["errors"][0]["code"], code)

    def test_state_not_inferred_or_cross_checked(self):
        for d in (desc(enabled=True), desc(enabled=False), desc(name="deprecated"), desc(version=1)):
            for s in STATES:
                self.assertTrue(validate(d, s)["valid"], (d, s))

    def test_lifecycle_does_not_affect_other_flags(self):
        base = validate(desc(purpose=""))
        with_state = validate(desc(purpose=""), "enabled")
        for key in ("name", "version", "identity_valid", "version_valid"):
            self.assertEqual(base[key], with_state[key], key)
        self.assertIs(with_state["lifecycle_valid"], True)
        self.assertFalse(with_state["valid"])

    def test_transition_names_are_not_states(self):
        self.assertFalse(validate(desc(), "defined->validated")["valid"])


class CombinedFailureTests(unittest.TestCase):
    def test_descriptor_and_lifecycle_failures_together(self):
        r = validate(desc(version=0, purpose=""), "nope")
        self.assertFalse(r["valid"])
        self.assertEqual(r["errors"], [err("invalid_version", "version"),
                                       err("invalid_purpose", "purpose"),
                                       err("unknown_state", "lifecycle_state")])
        self.assertEqual((r["identity_valid"], r["version_valid"], r["lifecycle_valid"]),
                         (True, False, False))
        self.assertEqual((r["name"], r["version"]), ("text_summary", None))

    def test_everything_wrong(self):
        r = validate(desc(name="Bad", version="x", outputs=[], handler=1), None)
        self.assertFalse(r["valid"])
        self.assertEqual([e["where"] for e in r["errors"]],
                         ["handler", "name", "version", "outputs", "lifecycle_state"])
        self.assertEqual((r["name"], r["version"]), (None, None))
        self.assertEqual((r["identity_valid"], r["version_valid"], r["lifecycle_valid"]),
                         (False, False, False))

    def test_non_dict_with_bad_state(self):
        r = validate(None, "nope")
        self.assertEqual(r["errors"], [err("descriptor_not_dict", "descriptor"),
                                       err("unknown_state", "lifecycle_state")])
        self.assertEqual((r["identity_valid"], r["version_valid"], r["lifecycle_valid"]),
                         (False, False, False))

    def test_non_dict_with_good_state(self):
        r = validate(None, "enabled")
        self.assertFalse(r["valid"])
        self.assertIs(r["lifecycle_valid"], True)

    def test_errors_ordered_descriptor_then_lifecycle(self):
        r = validate(desc(purpose=""), "nope")
        self.assertEqual(r["errors"][-1]["where"], "lifecycle_state")

    def test_errors_bounded_and_lifecycle_flag_still_correct(self):
        bad = desc(inputs=[1] * 16, outputs=[1] * 16, constraints=[1] * 16, purpose="", name="Bad",
                   version=0, enabled=1, handler=1)
        r = validate(bad, "nope")
        self.assertLessEqual(len(r["errors"]), cr.MAX_ERRORS)
        self.assertTrue(r["truncated"])
        self.assertIs(r["lifecycle_valid"], False)
        self.assertFalse(r["valid"])

    def test_huge_input_bounded(self):
        big = desc(inputs=["a%d" % n for n in range(100000)])
        r = validate(big, "x" * 100000)
        self.assertFalse(r["valid"])
        self.assertLessEqual(len(r["errors"]), cr.MAX_ERRORS)

    def test_exhaustive_agreement_with_layers(self):
        descriptors = [desc(), desc(version=0), desc(name="Bad"), desc(purpose=""), None, {}]
        states = STATES + ["nope", None, 3]
        for d, s in itertools.product(descriptors, states):
            r = validate(d, s)
            expected = (cr.validate_capability_descriptor(d)["valid"]
                        and cl.validate_lifecycle_state(s)["valid"])
            self.assertEqual(r["valid"], expected, (d, s))
            self.assertEqual(r["lifecycle_valid"], cl.validate_lifecycle_state(s)["valid"])


class NoSideEffectTests(unittest.TestCase):
    def test_inputs_not_modified(self):
        d = desc()
        before = copy.deepcopy(d)
        validate(d, "enabled")
        validate(desc(version=0), "nope")
        self.assertEqual(d, before)

    def test_results_deterministic_and_fresh(self):
        a, b = validate(desc(version=0), "nope"), validate(desc(version=0), "nope")
        self.assertEqual(a, b)
        self.assertIsNot(a, b)
        self.assertIsNot(a["errors"], b["errors"])
        a["errors"].clear()
        a["valid"] = True
        self.assertFalse(validate(desc(version=0), "nope")["valid"])
        self.assertTrue(validate(desc(version=0), "nope")["errors"])

    def test_result_does_not_alias_descriptor(self):
        d = desc()
        r = validate(d)
        d["name"] = "changed"
        self.assertEqual(r["name"], "text_summary")

    def test_registry_not_touched(self):
        reg = cr.CapabilityRegistry()
        reg.register(desc())
        before = reg.list_capabilities()
        validate(desc(version=3), "enabled")
        validate(desc(name="other_cap"), "validated")
        self.assertEqual(reg.list_capabilities(), before)
        self.assertEqual(len(reg), 1)

    def test_validation_does_not_register_or_allow_registration(self):
        reg = cr.CapabilityRegistry()
        r = validate(desc())
        self.assertTrue(r["valid"])
        self.assertEqual(len(reg), 0)

    def test_executed_flags_always_false(self):
        for d, s in itertools.product([desc(), desc(enabled=True), None, {}], STATES + [None]):
            r = validate(d, s)
            self.assertIs(r["execution_allowed"], False)
            self.assertIs(r["executed"], False)

    def test_no_module_level_state(self):
        for name, value in vars(cv).items():
            if name.startswith("__"):
                continue
            self.assertNotIsInstance(value, (dict, list, set), name)

    def test_single_public_function(self):
        public = [n for n, v in vars(cv).items() if inspect.isfunction(v) and not n.startswith("_")
                  and v.__module__ == cv.__name__]
        self.assertEqual(public, ["validate_capability"])


class BoundaryTests(unittest.TestCase):
    def test_imports_are_exactly_the_three_existing_layers(self):
        tree = ast.parse(inspect.getsource(cv))
        imports = sorted((n.module, n.level, tuple(sorted(a.name for a in n.names)))
                         for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom)))
        self.assertEqual(imports, [
            ("capability_identity", 1, ("build_capability_identity", "parse_capability_version")),
            ("capability_lifecycle", 1, ("validate_lifecycle_state",)),
            ("capability_registry", 1, ("MAX_ERRORS", "validate_capability_descriptor")),
        ])

    def test_no_execution_loading_or_io(self):
        body = inspect.getsource(cv).split('"""', 2)[2]
        for banned in ("importlib", "__import__", "exec(", "eval(", "subprocess", "socket", "urllib",
                       "requests", "open(", "os.", "sys.", "random", "time.", "datetime",
                       "CapabilityRegistry", ".register(", "global "):
            self.assertNotIn(banned, body, banned)

    def test_other_layers_do_not_reference_validation(self):
        for folder in ("core", "memory", "ael", "reasoning", "understanding", "planning", "agent",
                       "execution"):
            for dirpath, _dirs, files in os.walk(os.path.join(ROOT, folder)):
                for f in files:
                    if f.endswith(".py"):
                        with open(os.path.join(dirpath, f), encoding="utf-8") as fh:
                            text = fh.read()
                        for needle in ("capabilities.capability_validation", "import capability_validation",
                                       "capabilities import capability_validation"):
                            self.assertNotIn(needle, text, f)
        for module in (cr, ci, cl):
            self.assertNotIn("capability_validation", inspect.getsource(module))


class BackwardCompatibilityTests(unittest.TestCase):
    def test_registry_unchanged(self):
        self.assertEqual(cr.DESCRIPTOR_FIELDS, ("name", "version", "purpose", "inputs", "outputs",
                                                "constraints", "enabled"))
        self.assertEqual([n for n in dir(cr.CapabilityRegistry) if not n.startswith("_")],
                         ["list_capabilities", "lookup", "register"])
        reg = cr.CapabilityRegistry()
        self.assertEqual(reg.register(desc())["status"], "registered")
        self.assertEqual(reg.register(desc())["reason"], "duplicate")
        self.assertEqual(reg.register(desc(version=3))["reason"], "conflict")
        self.assertEqual(reg.register(desc(version="2"))["reason"], "malformed")
        self.assertEqual(reg.lookup("text_summary")["descriptor"], desc())
        self.assertEqual(reg.list_capabilities()["count"], 1)

    def test_identity_and_version_unchanged(self):
        self.assertEqual(ci.build_capability_identity(desc())["identity"], {"name": "text_summary"})
        self.assertEqual(ci.parse_capability_version(2)["number"], 2)
        self.assertFalse(ci.parse_capability_version("2")["valid"])
        self.assertEqual(ci.compare_capability_versions(3, 2)["relation"], "newer")
        self.assertEqual(ci.classify_capability_descriptors(desc(), desc(version=3))["classification"],
                         "newer_version")
        self.assertEqual(ci.compare_capability_identities(desc(), desc(name="other"))["relation"],
                         "different")

    def test_lifecycle_unchanged(self):
        self.assertEqual(cl.list_lifecycle_states()["states"], STATES)
        self.assertEqual(cl.list_lifecycle_transitions()["count"], 9)
        self.assertTrue(cl.evaluate_lifecycle_transition("defined", "validated")["allowed"])
        self.assertFalse(cl.evaluate_lifecycle_transition("defined", "enabled")["allowed"])
        self.assertEqual(cl.get_allowed_next_states("deprecated")["next_states"], [])
        self.assertEqual(cl.validate_lifecycle_state("enabled")["state"], "enabled")

    def test_descriptor_structure_unchanged(self):
        self.assertEqual(cr.validate_capability_descriptor(desc(lifecycle_state="enabled"))["errors"],
                         [err("unexpected_field", "lifecycle_state")])

    def test_earlier_tests_present(self):
        for name in ("test_capability_registry_prompt841.py", "test_capability_identity_prompt842.py",
                     "test_capability_lifecycle_prompt843.py", "test_capability_boundary_prompt840.py"):
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


if __name__ == "__main__":
    unittest.main()
