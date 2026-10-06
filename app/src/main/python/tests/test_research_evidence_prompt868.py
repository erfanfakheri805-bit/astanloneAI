"""
Prompt 868 - research evidence contract focused tests.

Run (from app/src/main/python/):
    python -m unittest tests.test_research_evidence_prompt868 -v
"""

import ast
import builtins
import copy
import decimal
import fractions
import json
import os
import socket
import subprocess
import sys
import unittest
from unittest import mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research import research_evidence as m
from research.research_evidence import build_research_evidence as build
from research.research_evidence import validate_research_evidence as validate
from research.research_source import build_research_source

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

BUILD_KEYS = ["valid", "errors", "evidence", "execution_allowed", "executed"]
VALIDATE_KEYS = ["valid", "errors", "execution_allowed", "executed"]
EVIDENCE_KEYS = ["version", "evidence_id", "source_id", "claim", "evidence_type",
                 "confidence", "constraints", "execution_allowed"]


def raw(**over):
    d = {"evidence_id": "ev_001", "source_id": "src_1", "claim": "RAG combines retrieval and generation.",
         "evidence_type": "fact", "confidence": 0.75, "constraints": ["peer-reviewed"]}
    d.update(over)
    return d


def good(**over):
    r = build(raw(**over))
    assert r["valid"], r["errors"]
    return r["evidence"]


def codes(result):
    return [e["code"] for e in result["errors"]]


class ValidBuildTests(unittest.TestCase):
    def test_valid_fact_evidence(self):
        r = build(raw())
        self.assertEqual(list(r), BUILD_KEYS)
        self.assertEqual((r["valid"], r["errors"]), (True, []))
        self.assertIs(r["execution_allowed"], False)
        self.assertIs(r["executed"], False)
        e = r["evidence"]
        self.assertEqual(list(e), EVIDENCE_KEYS)
        self.assertEqual(e, {"version": "1", "evidence_id": "ev_001", "source_id": "src_1",
                             "claim": "RAG combines retrieval and generation.",
                             "evidence_type": "fact", "confidence": 0.75,
                             "constraints": ["peer-reviewed"], "execution_allowed": False})
        json.dumps(r)

    def test_all_evidence_types(self):
        self.assertEqual(m.EVIDENCE_TYPES, ("fact", "observation", "user_statement", "learned_record"))
        for t in m.EVIDENCE_TYPES:
            self.assertEqual(good(evidence_type=t)["evidence_type"], t)

    def test_confidence_boundaries_and_values(self):
        for c in (0.0, 1.0, 0.5, 0.0001, 0.9999999, 5e-324):
            e = good(confidence=c)
            self.assertEqual(e["confidence"], c)
            self.assertIs(type(e["confidence"]), float)
        for c in (0, 1):  # exact ints are kept as given, never converted
            self.assertIs(type(good(confidence=c)["confidence"]), int)

    def test_empty_constraints_and_duplicates_kept(self):
        self.assertEqual(good(constraints=[])["constraints"], [])
        self.assertEqual(good(constraints=["a", "a"])["constraints"], ["a", "a"])

    def test_defaults_and_explicit_legal_values(self):
        e = good(version="1", execution_allowed=False)
        self.assertEqual((e["version"], e["execution_allowed"]), ("1", False))

    def test_build_output_validates_and_is_fresh(self):
        src = raw()
        a, b = build(src), build(src)
        self.assertEqual(a, b)
        self.assertIsNot(a["evidence"], b["evidence"])
        self.assertIsNot(a["evidence"]["constraints"], b["evidence"]["constraints"])
        self.assertEqual(validate(a["evidence"])["errors"], [])

    def test_source_id_is_only_a_reference_matching_a_source_contract_id(self):
        s = build_research_source({"source_id": "src_ref", "source_type": "web", "location": "x",
                                   "trust_level": "trusted", "constraints": [], "enabled": False})
        self.assertTrue(s["valid"])
        self.assertTrue(build(raw(source_id=s["source"]["source_id"]))["valid"])
        # an unknown / disabled source id is not looked up or rejected
        self.assertTrue(build(raw(source_id="no_such_source"))["valid"])


class FieldFailureTests(unittest.TestCase):
    def test_invalid_confidence_values(self):
        bad = [-0.0001, 1.0001, 2, -1, 100, 1e308, "0.5", "1", None, [], {}, (0.5,),
               decimal.Decimal("0.5"), fractions.Fraction(1, 2), 0.5 + 0j]
        for c in bad:
            r = build(raw(confidence=c))
            self.assertFalse(r["valid"], repr(c))
            self.assertEqual(codes(r), ["invalid_confidence"], repr(c))
            self.assertIsNone(r["evidence"])

    def test_bool_confidence_rejected(self):
        for c in (True, False):
            self.assertEqual(codes(build(raw(confidence=c))), ["invalid_confidence"])

    def test_nan_and_infinity_rejected(self):
        for c in (float("nan"), float("inf"), float("-inf")):
            self.assertEqual(codes(build(raw(confidence=c))), ["invalid_confidence"])

    def test_float_subclass_rejected(self):
        class F(float):
            pass
        self.assertEqual(codes(build(raw(confidence=F(0.5)))), ["invalid_confidence"])

    def test_invalid_and_missing_ids(self):
        for field in ("evidence_id", "source_id"):
            for bad in ("", " ", " a", "a ", "a\nb", "a\x00", "x" * 65, None, 5, True, [], ["a"]):
                r = build(raw(**{field: bad}))
                self.assertEqual(codes(r), ["invalid_" + field], (field, bad))
            d = raw(); del d[field]
            self.assertEqual(build(d)["errors"], [{"code": "missing_field", "where": field}])
        self.assertTrue(build(raw(evidence_id="x" * 64, source_id="y" * 64))["valid"])

    def test_ids_are_never_generated(self):
        for field in ("evidence_id", "source_id"):
            d = raw(); del d[field]
            r = build(d)
            self.assertFalse(r["valid"])
            self.assertIsNone(r["evidence"])

    def test_invalid_claim(self):
        for bad in ("", " ", " x", "x ", "a\tb", "x" * 501, None, 5, ["claim"], b"claim"):
            self.assertEqual(codes(build(raw(claim=bad))), ["invalid_claim"], repr(bad))
        self.assertTrue(build(raw(claim="x" * 500))["valid"])
        d = raw(); del d["claim"]
        self.assertEqual(codes(build(d)), ["missing_field"])

    def test_invalid_evidence_type(self):
        for bad in ("", "Fact", "FACT", "fact ", "opinion", "learned", None, 1, ["fact"], True):
            self.assertEqual(codes(build(raw(evidence_type=bad))), ["invalid_evidence_type"], repr(bad))
        d = raw(); del d["evidence_type"]
        self.assertEqual(codes(build(d)), ["missing_field"])  # type is never inferred

    def test_invalid_constraints(self):
        for bad in ("a", None, 5, {"a": 1}, ("a",)):
            self.assertEqual(codes(build(raw(constraints=bad))), ["invalid_constraints"], repr(bad))
        for bad in ([""], [" a"], ["a "], [1], [None], ["a", 2], ["x" * 201], ["a\nb"]):
            r = build(raw(constraints=bad))
            self.assertEqual(codes(r), ["invalid_item"], repr(bad))
        r = build(raw(constraints=["ok", 5]))
        self.assertEqual(r["errors"], [{"code": "invalid_item", "where": "constraints[1]"}])
        self.assertEqual(codes(build(raw(constraints=["a"] * 17))), ["too_many_items"])
        self.assertTrue(build(raw(constraints=["a"] * 16))["valid"])
        d = raw(); del d["constraints"]
        self.assertEqual(codes(build(d)), ["missing_field"])

    def test_version_validation(self):
        for bad in ("2", "", "1.0", " 1", 1, 1.0, True, None):
            self.assertEqual(codes(build(raw(version=bad))), ["invalid_version"], repr(bad))

    def test_execution_flag(self):
        for bad in (True, 1, 0, None, "False", "false", []):
            r = build(raw(execution_allowed=bad))
            self.assertEqual(codes(r), ["invalid_execution_allowed"], repr(bad))
            self.assertIsNone(r["evidence"])
            self.assertIs(r["execution_allowed"], False)
            self.assertIs(r["executed"], False)
        self.assertIs(good()["execution_allowed"], False)

    def test_unexpected_fields_rejected_including_executed(self):
        for extra in ("executed", "extra", "source", "content", "trust_level", "location"):
            r = build(raw(**{extra: 1}))
            self.assertEqual(r["errors"], [{"code": "unexpected_field", "where": extra}])
        r = build(raw(**{"": 1}))
        self.assertEqual(r["errors"], [{"code": "unexpected_field", "where": "<field>"}])
        self.assertNotIn("executed", good())


class MalformedAndImmutabilityTests(unittest.TestCase):
    def test_malformed_evidence(self):
        self.assertEqual(build()["errors"], [{"code": "missing_evidence", "where": "evidence"}])
        self.assertEqual(build(None)["errors"][0]["code"], "missing_evidence")
        for bad in ([], "x", 5, True, 1.5, (), [raw()], object()):
            r = build(bad)
            self.assertEqual(r["errors"], [{"code": "evidence_not_dict", "where": "evidence"}])
            self.assertEqual(list(r), BUILD_KEYS)
        self.assertEqual(build({})["errors"][0], {"code": "missing_field", "where": "evidence_id"})
        big = {str(i): i for i in range(17)}
        self.assertEqual(build(big)["errors"], [{"code": "too_many_fields", "where": "evidence"}])
        self.assertEqual(build({1: "a", **raw()})["errors"][0]["code"], "unexpected_field")

    def test_errors_bounded_and_fixed_order(self):
        r = build({"evidence_id": 1, "source_id": 2, "claim": 3, "evidence_type": 4,
                   "confidence": 5, "constraints": 6, "version": 7, "execution_allowed": 8})
        self.assertEqual(codes(r), ["invalid_version", "invalid_evidence_id", "invalid_source_id",
                                    "invalid_claim", "invalid_evidence_type", "invalid_confidence",
                                    "invalid_constraints", "invalid_execution_allowed"])
        self.assertLessEqual(len(build(raw(constraints=[1] * 16))["errors"]), m.MAX_ERRORS)

    def test_build_does_not_mutate_input(self):
        for src in (raw(), raw(confidence=2, constraints=["a", 1]), raw(version="x"), raw(extra=1)):
            before = copy.deepcopy(src)
            build(src)
            self.assertEqual(src, before)

    def test_built_evidence_is_independent_of_input(self):
        src = raw(constraints=["a"])
        e = build(src)["evidence"]
        src["constraints"].append("b")
        src["claim"] = "changed"
        self.assertEqual((e["constraints"], e["claim"]), (["a"], "RAG combines retrieval and generation."))
        e["constraints"].append("z")
        self.assertEqual(src["constraints"], ["a", "b"])

    def test_internal_failure_is_validation_error(self):
        e = good()
        with mock.patch.object(m, "_errors", side_effect=RuntimeError("x")):
            r = build(raw())
            v = validate(e)
        self.assertEqual((r["valid"], r["evidence"], r["errors"]),
                         (False, None, [{"code": "validation_error", "where": "evidence"}]))
        self.assertEqual(v["errors"], [{"code": "validation_error", "where": "evidence"}])
        self.assertEqual((v["execution_allowed"], v["executed"]), (False, False))


class ValidatorTests(unittest.TestCase):
    def test_validate_normalized_evidence(self):
        v = validate(good())
        self.assertEqual(list(v), VALIDATE_KEYS)
        self.assertEqual((v["valid"], v["errors"]), (True, []))
        self.assertIs(v["execution_allowed"], False)
        self.assertIs(v["executed"], False)

    def test_validate_requires_all_eight_keys(self):
        for key in EVIDENCE_KEYS:
            e = good(); del e[key]
            self.assertEqual(validate(e)["errors"], [{"code": "missing_field", "where": key}])

    def test_validate_does_not_default_optional_fields(self):
        self.assertFalse(validate(raw())["valid"])  # raw input is not normalized evidence

    def test_validate_rejects_bad_values_independently(self):
        for key, bad, code in (("version", "2", "invalid_version"),
                               ("evidence_id", "", "invalid_evidence_id"),
                               ("source_id", None, "invalid_source_id"),
                               ("claim", " x", "invalid_claim"),
                               ("evidence_type", "opinion", "invalid_evidence_type"),
                               ("confidence", True, "invalid_confidence"),
                               ("confidence", float("nan"), "invalid_confidence"),
                               ("confidence", 1.5, "invalid_confidence"),
                               ("constraints", "a", "invalid_constraints"),
                               ("execution_allowed", True, "invalid_execution_allowed")):
            e = good(); e[key] = bad
            self.assertEqual(codes(validate(e)), [code], (key, bad))

    def test_validate_rejects_executed_field_and_extras(self):
        e = good(); e["executed"] = False
        self.assertEqual(validate(e)["errors"], [{"code": "unexpected_field", "where": "executed"}])

    def test_validate_malformed_input(self):
        self.assertEqual(validate()["errors"][0]["code"], "missing_evidence")
        for bad in ([], "x", 3, True):
            self.assertEqual(validate(bad)["errors"][0]["code"], "evidence_not_dict")

    def test_validate_does_not_mutate_or_raise(self):
        e = good(); before = copy.deepcopy(e)
        validate(e)
        self.assertEqual(e, before)
        e["constraints"] = [object()]
        self.assertFalse(validate(e)["valid"])

    def test_deterministic(self):
        e = good(); e["confidence"] = -1
        self.assertEqual(validate(e), validate(e))
        self.assertIsNot(validate(e), validate(e))


class IsolationTests(unittest.TestCase):
    def test_no_io_subprocess_or_network(self):
        def forbidden(*a, **k):
            raise AssertionError("forbidden call")
        with mock.patch.object(builtins, "open", forbidden), \
                mock.patch.object(subprocess, "Popen", forbidden), \
                mock.patch.object(socket, "socket", forbidden), \
                mock.patch.object(os, "stat", forbidden):
            r = build(raw())
            validate(r["evidence"])
            build(None)
        self.assertTrue(r["valid"])

    def test_source_imports_and_public_api(self):
        with open(os.path.join(ROOT, "research", "research_evidence.py"), encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        self.assertEqual([(n.module, sorted(a.name for a in n.names))
                          for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)],
                         [("research.research_source", ["MAX_ID_LENGTH", "MAX_ITEMS", "MAX_ITEM_LENGTH"])])
        self.assertFalse([n for n in ast.walk(tree) if isinstance(n, ast.Import)])
        public = sorted(n.name for n in tree.body
                        if isinstance(n, ast.FunctionDef) and not n.name.startswith("_"))
        self.assertEqual(public, ["build_research_evidence", "validate_research_evidence"])

    def test_bounds_match_section_15_contracts(self):
        from research import research_source as s
        self.assertEqual((m.MAX_ID_LENGTH, m.MAX_ITEMS, m.MAX_ITEM_LENGTH),
                         (s.MAX_ID_LENGTH, s.MAX_ITEMS, s.MAX_ITEM_LENGTH))


if __name__ == "__main__":
    unittest.main()
