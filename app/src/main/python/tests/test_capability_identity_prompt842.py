"""
Prompt 842 - capability identity and versioning focused tests.

Run (from app/src/main/python/):
    python -m unittest tests.test_capability_identity_prompt842 -v
"""

import copy
import inspect
import json
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from capabilities import capability_identity as ci
from capabilities import capability_registry as cr
from capabilities.capability_identity import (
    parse_capability_version as parse,
    compare_capability_versions as cmp_v,
    build_capability_identity as ident,
    compare_capability_identities as cmp_i,
    classify_capability_descriptors as classify,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def desc(**over):
    d = {"name": "text_summary", "version": 2, "purpose": "Summarise supplied text.",
         "inputs": ["text"], "outputs": ["summary"], "constraints": ["No network access."],
         "enabled": False}
    d.update(over)
    return d


def codes(result):
    return [e["code"] for e in result["errors"]]


class IntSub(int):
    pass


class StrSub(str):
    pass


class DictSub(dict):
    pass


class VersionParseTests(unittest.TestCase):
    def test_valid_versions(self):
        for v in (1, 2, 10, 999, cr.MAX_VERSION):
            r = parse(v)
            self.assertEqual(r, {"version": 1, "valid": True, "number": v, "errors": [],
                                 "truncated": False, "executed": False})

    def test_key_order(self):
        self.assertEqual(list(parse(1)), ["version", "valid", "number", "errors",
                                          "truncated", "executed"])

    def test_wrong_types(self):
        for bad in (True, False, 1.0, 2.5, "1", "1.0", "v1", " 1", "", None, [1], (1,), {},
                    b"1", IntSub(1), 1 + 0j, object()):
            r = parse(bad)
            self.assertFalse(r["valid"], repr(bad))
            self.assertIsNone(r["number"])
            self.assertEqual(r["errors"], [{"code": ci.ERR_VERSION_TYPE, "where": "version"}])

    def test_out_of_range(self):
        for bad in (0, -1, -100, cr.MAX_VERSION + 1, 10 ** 30):
            r = parse(bad)
            self.assertFalse(r["valid"], repr(bad))
            self.assertEqual(codes(r), [ci.ERR_VERSION_RANGE])

    def test_nothing_is_coerced(self):
        self.assertFalse(parse("3")["valid"])
        self.assertFalse(parse(3.0)["valid"])

    def test_agrees_with_registry_validator(self):
        for v in (0, 1, 5, cr.MAX_VERSION, cr.MAX_VERSION + 1, True, "1", 1.0, None, IntSub(2)):
            reg_ok = cr.validate_capability_descriptor(desc(version=v))["valid"]
            self.assertEqual(parse(v)["valid"], reg_ok, repr(v))

    def test_deterministic_and_fresh(self):
        a, b = parse("x"), parse("x")
        self.assertEqual(a, b)
        self.assertIsNot(a, b)
        self.assertIsNot(a["errors"], b["errors"])
        a["errors"].clear()
        self.assertTrue(parse("x")["errors"])

    def test_json_safe(self):
        json.dumps(parse(1))
        json.dumps(parse("x"))


class VersionCompareTests(unittest.TestCase):
    def test_relations(self):
        self.assertEqual(cmp_v(2, 2)["relation"], "equal")
        self.assertEqual(cmp_v(3, 2)["relation"], "newer")
        self.assertEqual(cmp_v(2, 3)["relation"], "older")

    def test_numeric_not_lexical(self):
        self.assertEqual(cmp_v(10, 9)["relation"], "newer")
        self.assertEqual(cmp_v(9, 10)["relation"], "older")
        self.assertEqual(cmp_v(100, 20)["relation"], "newer")

    def test_bounds(self):
        self.assertEqual(cmp_v(cr.MAX_VERSION, 1)["relation"], "newer")
        self.assertEqual(cmp_v(1, cr.MAX_VERSION)["relation"], "older")

    def test_result_shape(self):
        r = cmp_v(3, 2)
        self.assertEqual(r, {"version": 1, "valid": True, "relation": "newer", "left": 3,
                             "right": 2, "errors": [], "truncated": False, "executed": False})
        self.assertEqual(list(r), ["version", "valid", "relation", "left", "right", "errors",
                                   "truncated", "executed"])

    def test_antisymmetry(self):
        flip = {"newer": "older", "older": "newer", "equal": "equal"}
        for a in (1, 2, 7, 50):
            for b in (1, 2, 7, 50):
                self.assertEqual(cmp_v(a, b)["relation"], flip[cmp_v(b, a)["relation"]])

    def test_transitivity(self):
        self.assertEqual(cmp_v(1, 2)["relation"], "older")
        self.assertEqual(cmp_v(2, 3)["relation"], "older")
        self.assertEqual(cmp_v(1, 3)["relation"], "older")

    def test_invalid_left_right_both(self):
        r = cmp_v("1", 2)
        self.assertFalse(r["valid"])
        self.assertIsNone(r["relation"])
        self.assertIsNone(r["left"])
        self.assertIsNone(r["right"])
        self.assertEqual(r["errors"], [{"code": ci.ERR_VERSION_TYPE, "where": "left"}])
        self.assertEqual(cmp_v(2, 0)["errors"], [{"code": ci.ERR_VERSION_RANGE, "where": "right"}])
        r = cmp_v(None, True)
        self.assertEqual([e["where"] for e in r["errors"]], ["left", "right"])

    def test_deterministic_fresh_json(self):
        a, b = cmp_v(1, 2), cmp_v(1, 2)
        self.assertEqual(a, b)
        self.assertIsNot(a, b)
        json.dumps(a)
        json.dumps(cmp_v("x", "y"))


class IdentityTests(unittest.TestCase):
    def test_identity_of_valid_descriptor(self):
        r = ident(desc())
        self.assertEqual(r, {"version": 1, "valid": True, "identity": {"name": "text_summary"},
                             "errors": [], "truncated": False, "executed": False})
        self.assertEqual(list(r), ["version", "valid", "identity", "errors", "truncated", "executed"])

    def test_identity_ignores_everything_but_name(self):
        base = ident(desc())["identity"]
        for change in ({"version": 9}, {"purpose": "Other."}, {"inputs": []},
                       {"outputs": ["x"]}, {"constraints": []}, {"enabled": True}):
            self.assertEqual(ident(desc(**change))["identity"], base, change)

    def test_invalid_descriptor_has_no_identity(self):
        for bad in (None, {}, [], "text_summary", desc(name="Text"), desc(name=" text"),
                    desc(version="1"), desc(handler="x"), desc(outputs=[]), DictSub(desc())):
            r = ident(bad)
            self.assertFalse(r["valid"], repr(bad))
            self.assertIsNone(r["identity"])
            self.assertTrue(r["errors"])
            self.assertTrue(all(e["where"].startswith("descriptor") for e in r["errors"]))

    def test_error_codes_come_from_registry_validator(self):
        r = ident(desc(version=0))
        self.assertEqual(r["errors"], [{"code": cr.ERR_INVALID_VERSION, "where": "descriptor.version"}])

    def test_identity_is_fresh(self):
        d = desc()
        a, b = ident(d), ident(d)
        self.assertIsNot(a["identity"], b["identity"])
        a["identity"]["name"] = "hacked"
        self.assertEqual(ident(d)["identity"], {"name": "text_summary"})
        self.assertEqual(d["name"], "text_summary")

    def test_input_not_modified(self):
        d = desc()
        before = copy.deepcopy(d)
        ident(d)
        cmp_i(d, d)
        classify(d, d)
        self.assertEqual(d, before)


class IdentityComparisonTests(unittest.TestCase):
    def test_same_and_different(self):
        self.assertEqual(cmp_i(desc(), desc(version=5))["relation"], "same")
        self.assertEqual(cmp_i(desc(), desc(name="file_reader"))["relation"], "different")

    def test_no_fuzzy_matching(self):
        base = desc(name="text_summary")
        for other in ("text_summar", "text_summary2", "text_summary_", "summary_text", "text"):
            self.assertEqual(cmp_i(base, desc(name=other))["relation"], "different", other)

    def test_case_and_whitespace_variants_are_invalid_not_same(self):
        for other in ("Text_Summary", "TEXT_SUMMARY", "text_summary ", " text_summary",
                      "text-summary", "text summary"):
            r = cmp_i(desc(), desc(name=other))
            self.assertFalse(r["valid"], repr(other))
            self.assertIsNone(r["relation"])
            self.assertEqual([e["where"] for e in r["errors"]], ["right.name"])

    def test_invalid_sides(self):
        r = cmp_i(None, desc(version=0))
        self.assertEqual(r["errors"], [{"code": cr.ERR_NOT_DICT, "where": "left.descriptor"},
                                       {"code": cr.ERR_INVALID_VERSION, "where": "right.version"}])
        self.assertEqual(list(r), ["version", "valid", "relation", "errors", "truncated", "executed"])

    def test_symmetric(self):
        a, b = desc(), desc(name="other_cap")
        self.assertEqual(cmp_i(a, b)["relation"], cmp_i(b, a)["relation"])


class ClassificationTests(unittest.TestCase):
    EXISTING = desc(version=2)

    def test_same_version_identical(self):
        r = classify(self.EXISTING, desc(version=2))
        self.assertEqual(r, {"version": 1, "classification": "same_version", "identity_match": True,
                             "version_relation": "equal", "content_identical": True,
                             "existing_name": "text_summary", "candidate_name": "text_summary",
                             "errors": [], "truncated": False, "executed": False})
        self.assertEqual(list(r), ["version", "classification", "identity_match", "version_relation",
                                   "content_identical", "existing_name", "candidate_name", "errors",
                                   "truncated", "executed"])

    def test_same_version_different_content(self):
        for change in ({"purpose": "Other."}, {"inputs": []}, {"outputs": ["x"]},
                       {"constraints": []}, {"enabled": True}):
            r = classify(self.EXISTING, desc(version=2, **change))
            self.assertEqual(r["classification"], "same_version", change)
            self.assertIs(r["content_identical"], False, change)

    def test_newer(self):
        r = classify(self.EXISTING, desc(version=3))
        self.assertEqual((r["classification"], r["version_relation"], r["identity_match"]),
                         ("newer_version", "newer", True))
        self.assertIs(r["content_identical"], False)
        self.assertEqual(classify(self.EXISTING, desc(version=10))["classification"], "newer_version")

    def test_older(self):
        r = classify(self.EXISTING, desc(version=1))
        self.assertEqual((r["classification"], r["version_relation"]), ("older_version", "older"))
        self.assertEqual(classify(desc(version=10), desc(version=9))["classification"], "older_version")

    def test_different_identity(self):
        for v in (1, 2, 3):
            r = classify(self.EXISTING, desc(name="file_reader", version=v))
            self.assertEqual(r["classification"], "different_identity")
            self.assertIs(r["identity_match"], False)
            self.assertIsNone(r["version_relation"])
            self.assertIsNone(r["content_identical"])
            self.assertEqual((r["existing_name"], r["candidate_name"]), ("text_summary", "file_reader"))

    def test_invalid_existing_or_candidate(self):
        bads = (None, {}, "x", [], desc(name="Bad"), desc(version="2"), desc(version=0),
                desc(handler="x"), desc(outputs=[]), desc(enabled=1), DictSub(desc()))
        for bad in bads:
            for args in ((bad, desc()), (desc(), bad)):
                r = classify(*args)
                self.assertEqual(r["classification"], "invalid", repr(bad))
                self.assertIsNone(r["identity_match"])
                self.assertIsNone(r["version_relation"])
                self.assertIsNone(r["content_identical"])
                self.assertIsNone(r["existing_name"])
                self.assertIsNone(r["candidate_name"])
                self.assertTrue(r["errors"])

    def test_invalid_error_locations(self):
        r = classify(desc(version=0), desc(name="Bad"))
        self.assertEqual(r["errors"], [{"code": cr.ERR_INVALID_VERSION, "where": "existing.version"},
                                       {"code": cr.ERR_INVALID_NAME, "where": "candidate.name"}])

    def test_malformed_version_is_invalid_not_ordered(self):
        r = classify(desc(), desc(version="3"))
        self.assertEqual(r["classification"], "invalid")
        r = classify(desc(), desc(version=True))
        self.assertEqual(r["classification"], "invalid")

    def test_classification_values_are_closed_set(self):
        cases = [(desc(), desc()), (desc(), desc(version=3)), (desc(), desc(version=1)),
                 (desc(), desc(name="other")), (None, None)]
        seen = {classify(a, b)["classification"] for a, b in cases}
        self.assertEqual(seen, set(ci.CLASSIFICATIONS))

    def test_errors_bounded(self):
        bad = desc(inputs=[1] * 16, outputs=[1] * 16, constraints=[1] * 16)
        r = classify(bad, bad)
        self.assertLessEqual(len(r["errors"]), cr.MAX_ERRORS)
        self.assertTrue(r["truncated"])

    def test_deterministic_fresh_json(self):
        a, b = classify(self.EXISTING, desc(version=3)), classify(self.EXISTING, desc(version=3))
        self.assertEqual(a, b)
        self.assertIsNot(a, b)
        self.assertIsNot(a["errors"], b["errors"])
        json.dumps(a)
        json.dumps(classify(None, None))

    def test_hostile_input_never_raises(self):
        class Boom(dict):
            def __iter__(self):
                raise RuntimeError("boom")
        for fn, args in ((classify, (Boom(), desc())), (classify, (desc(), Boom())),
                         (cmp_i, (Boom(), Boom())), (ident, (Boom(),))):
            r = fn(*args)
            self.assertFalse(r.get("valid", False))

    def test_huge_input_bounded(self):
        big = desc(inputs=["a%d" % n for n in range(100000)])
        r = classify(big, desc())
        self.assertEqual(r["classification"], "invalid")
        self.assertLessEqual(len(r["errors"]), cr.MAX_ERRORS)

    def test_inputs_not_modified(self):
        a, b = desc(), desc(version=3)
        ca, cb = copy.deepcopy(a), copy.deepcopy(b)
        classify(a, b)
        self.assertEqual((a, b), (ca, cb))


class NoSideEffectTests(unittest.TestCase):
    def test_registry_is_not_touched_or_required(self):
        reg = cr.CapabilityRegistry()
        reg.register(desc(version=2))
        before = reg.list_capabilities()
        classify(desc(version=2), desc(version=5))
        classify(reg.lookup("text_summary")["descriptor"], desc(version=1))
        self.assertEqual(reg.list_capabilities(), before)
        self.assertEqual(len(reg), 1)

    def test_classification_does_not_register_replace_or_execute(self):
        reg = cr.CapabilityRegistry()
        reg.register(desc(version=2))
        r = classify(reg.lookup("text_summary")["descriptor"], desc(version=3))
        self.assertEqual(r["classification"], "newer_version")
        self.assertFalse(r["executed"])
        self.assertEqual(reg.lookup("text_summary")["descriptor"]["version"], 2)
        # the registry itself still refuses the newer version as a conflict (Prompt 841)
        self.assertEqual(reg.register(desc(version=3))["reason"], "conflict")

    def test_no_state_in_module(self):
        for name, value in vars(ci).items():
            if name.startswith("__"):
                continue
            self.assertNotIsInstance(value, (dict, list, set), name)

    def test_executed_always_false(self):
        for r in (parse(1), parse("x"), cmp_v(1, 2), cmp_v("x", 1), ident(desc()), ident(None),
                  cmp_i(desc(), desc()), classify(desc(), desc()), classify(None, None)):
            self.assertIs(r["executed"], False)


class BoundaryTests(unittest.TestCase):
    def test_only_expected_imports(self):
        import ast
        tree = ast.parse(inspect.getsource(ci))
        imports = [(type(n).__name__, n.module, n.level, sorted(a.name for a in n.names))
                   for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
        self.assertEqual(imports, [("ImportFrom", "capability_registry", 1,
                                    ["MAX_ERRORS", "MAX_VERSION", "validate_capability_descriptor"])])

    def test_no_execution_loading_or_io(self):
        body = inspect.getsource(ci).split('"""', 2)[2]
        for banned in ("importlib", "__import__", "exec(", "eval(", "subprocess", "socket",
                       "urllib", "requests", "open(", "os.", "sys.", "from core", "import core",
                       "memory", "ael", "random", "time.", "datetime"):
            self.assertNotIn(banned, body, banned)

    def test_core_memory_ael_do_not_reference_identity_layer(self):
        for folder in ("core", "memory", "ael", "reasoning", "understanding", "planning", "agent"):
            for dirpath, _dirs, files in os.walk(os.path.join(ROOT, folder)):
                for f in files:
                    if f.endswith(".py"):
                        with open(os.path.join(dirpath, f), encoding="utf-8") as fh:
                            text = fh.read()
                        for needle in ("capability_identity", "capabilities.capability_registry",
                                       "import capability_registry", "capabilities import capability_registry"):
                            self.assertNotIn(needle, text, f)


class BackwardCompatibilityTests(unittest.TestCase):
    PUBLIC_841 = ("validate_capability_descriptor", "CapabilityRegistry", "DESCRIPTOR_FIELDS",
                  "REGISTRY_VERSION", "MAX_NAME_LENGTH", "MAX_TEXT_LENGTH", "MAX_CONSTRAINT_LENGTH",
                  "MAX_ITEMS", "MAX_VERSION", "MAX_ERRORS", "MAX_FIELDS", "MAX_CAPABILITIES")

    def test_registry_module_public_surface_preserved(self):
        for name in self.PUBLIC_841:
            self.assertTrue(hasattr(cr, name), name)
        self.assertEqual(cr.DESCRIPTOR_FIELDS, ("name", "version", "purpose", "inputs", "outputs",
                                                "constraints", "enabled"))
        self.assertEqual((cr.REGISTRY_VERSION, cr.MAX_VERSION, cr.MAX_CAPABILITIES), (1, 1000000, 256))
        self.assertEqual([n for n in dir(cr.CapabilityRegistry) if not n.startswith("_")],
                         ["list_capabilities", "lookup", "register"])

    def test_registry_does_not_import_identity_layer(self):
        self.assertNotIn("capability_identity", inspect.getsource(cr))

    def test_registry_behaviour_unchanged(self):
        reg = cr.CapabilityRegistry()
        self.assertEqual(reg.register(desc())["status"], "registered")
        self.assertEqual(reg.register(desc())["reason"], "duplicate")
        self.assertEqual(reg.register(desc(version=3))["reason"], "conflict")
        self.assertEqual(reg.register(desc(version="2"))["reason"], "malformed")
        self.assertEqual(reg.lookup("text_summary")["descriptor"], desc())
        self.assertEqual(reg.lookup("TEXT_SUMMARY")["found"], False)
        self.assertEqual(reg.list_capabilities()["count"], 1)

    def test_prompt841_tests_still_present(self):
        self.assertTrue(os.path.exists(os.path.join(ROOT, "tests", "test_capability_registry_prompt841.py")))

    def test_older_capability_modules_preserved(self):
        from capabilities import capability_system as cs
        self.assertEqual(len(cs.PLANNED_CAPABILITIES), 8)
        with open(os.path.join(ROOT, "capabilities", "__init__.py"), "rb") as fh:
            self.assertEqual(fh.read().strip(), b"")

    def test_reasoning_apis_preserved(self):
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
