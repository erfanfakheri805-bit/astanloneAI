"""
Prompt 864 - research source contract focused tests.

Run (from app/src/main/python/):
    python -m unittest tests.test_research_source_prompt864 -v
"""

import ast
import copy
import json
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research import research_source as rs
from research.research_source import build_research_source as build
from research.research_source import validate_research_source as validate

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

BUILD_KEYS = ["valid", "errors", "source", "execution_allowed", "executed"]
VALIDATE_KEYS = ["valid", "errors", "execution_allowed", "executed"]
NORMAL_KEYS = ["version", "source_id", "source_type", "location", "trust_level",
               "constraints", "enabled", "execution_allowed"]
TYPES = ["local_file", "user_input", "learned_record", "web", "api", "external_model"]
LEVELS = ["untrusted", "standard", "trusted"]


def src(**over):
    d = {"source_id": "src_001", "source_type": "local_file", "location": "notes/rag.md",
         "trust_level": "standard", "constraints": ["Read-only."], "enabled": True}
    d.update(over)
    return d


def normal(**over):
    d = dict(src(), version="1", execution_allowed=False)
    d.update(over)
    return d


def codes(result):
    return [(e["code"], e["where"]) for e in result["errors"]]


def check_shape(test, result, keys=BUILD_KEYS):
    test.assertEqual(list(result), keys)
    test.assertIs(result["execution_allowed"], False)
    test.assertIs(result["executed"], False)
    json.dumps(result)


class ValidSourceTests(unittest.TestCase):
    def test_valid_build_has_exact_normal_form(self):
        r = build(src())
        check_shape(self, r)
        self.assertEqual((r["valid"], r["errors"]), (True, []))
        self.assertEqual(list(r["source"]), NORMAL_KEYS)
        self.assertEqual(r["source"]["version"], "1")
        self.assertIs(r["source"]["execution_allowed"], False)

    def test_enum_constants_are_exact(self):
        self.assertEqual(list(rs.SOURCE_TYPES), TYPES)
        self.assertEqual(list(rs.TRUST_LEVELS), LEVELS)

    def test_every_source_type_and_trust_level_accepted(self):
        for t in TYPES:
            for level in LEVELS:
                self.assertTrue(build(src(source_type=t, trust_level=level))["valid"], (t, level))

    def test_both_enabled_values_accepted_and_preserved(self):
        for value in (True, False):
            r = build(src(enabled=value))["source"]
            self.assertIs(r["enabled"], value)
            self.assertIs(r["execution_allowed"], False)

    def test_values_preserved_exactly_location_is_opaque(self):
        loc = "https://example.com/a b?q=1#x"
        r = build(src(source_type="web", location=loc))["source"]
        self.assertEqual(r["location"], loc)
        self.assertEqual(r["constraints"], ["Read-only."])

    def test_optional_version_and_flag_accepted_when_exact(self):
        self.assertTrue(build(src(version="1", execution_allowed=False))["valid"])

    def test_empty_and_duplicate_constraints_allowed(self):
        self.assertTrue(build(src(constraints=[]))["valid"])
        self.assertEqual(build(src(constraints=["a", "a"]))["source"]["constraints"], ["a", "a"])

    def test_normalized_source_validates(self):
        r = validate(normal())
        check_shape(self, r, VALIDATE_KEYS)
        self.assertEqual((r["valid"], r["errors"]), (True, []))
        self.assertTrue(validate(build(src())["source"])["valid"])

    def test_boundary_sizes_accepted(self):
        r = build(src(source_id="x" * rs.MAX_ID_LENGTH, location="l" * rs.MAX_LOCATION_LENGTH,
                      constraints=["c" * rs.MAX_ITEM_LENGTH] * rs.MAX_ITEMS))
        self.assertTrue(r["valid"], r["errors"])


class BuildRejectTests(unittest.TestCase):
    def test_missing_and_non_dict_source(self):
        self.assertEqual(codes(build()), [("missing_source", "source")])
        for bad in ([], "x", 1, (1,), object()):
            r = build(bad)
            check_shape(self, r)
            self.assertEqual(codes(r), [("source_not_dict", "source")])
            self.assertIsNone(r["source"])

    def test_missing_required_fields_are_errors_not_defaults(self):
        for key in ("source_id", "source_type", "location", "trust_level", "constraints",
                    "enabled"):
            d = src()
            del d[key]
            self.assertEqual(codes(build(d)), [("missing_field", key)])

    def test_unexpected_fields_rejected(self):
        self.assertEqual(codes(build(src(extra=1))), [("unexpected_field", "extra")])
        self.assertEqual(codes(build(src(content="data"))), [("unexpected_field", "content")])

    def test_execution_allowed_true_or_non_false_rejected(self):
        for bad in (True, 1, 0, None, "False", []):
            r = build(src(execution_allowed=bad))
            self.assertEqual(codes(r), [("invalid_execution_allowed", "execution_allowed")])
            self.assertIsNone(r["source"])

    def test_invalid_version_rejected(self):
        for bad in ("2", "", 1, None, "1 "):
            self.assertEqual(codes(build(src(version=bad))), [("invalid_version", "version")])

    def test_invalid_text_fields(self):
        bad_values = ("", " x", "x ", "a\nb", "a\x00b", 5, None, ["x"])
        for field in ("source_id", "location"):
            for bad in bad_values:
                self.assertEqual(codes(build(src(**{field: bad}))), [("invalid_" + field, field)],
                                 (field, bad))

    def test_text_length_bounds_and_subclass(self):
        self.assertFalse(build(src(source_id="x" * 65))["valid"])
        self.assertFalse(build(src(location="x" * 501))["valid"])

        class S(str):
            pass
        self.assertEqual(codes(build(src(location=S("ok")))), [("invalid_location", "location")])

    def test_source_type_must_be_exact_member(self):
        for bad in ("File", "LOCAL_FILE", "local file", "file", "", " web", None, 1, ["web"],
                    ("web",)):
            self.assertEqual(codes(build(src(source_type=bad))),
                             [("invalid_source_type", "source_type")], bad)

    def test_trust_level_must_be_exact_member(self):
        for bad in ("Trusted", "TRUSTED", "high", "", "trusted ", None, 1, True):
            self.assertEqual(codes(build(src(trust_level=bad))),
                             [("invalid_trust_level", "trust_level")], bad)

    def test_enabled_must_be_a_real_bool(self):
        for bad in (1, 0, None, "true", "False", [], 1.0):
            self.assertEqual(codes(build(src(enabled=bad))), [("invalid_enabled", "enabled")], bad)

    def test_constraints_malformed_values_rejected(self):
        for bad in ("x", None, ("a",), 1, {"a"}):
            self.assertEqual(codes(build(src(constraints=bad))),
                             [("invalid_constraints", "constraints")])
        for bad in (1, None, "", " x", [], "x" * 201):
            self.assertEqual(codes(build(src(constraints=["ok", bad]))),
                             [("invalid_item", "constraints[1]")])
        self.assertEqual(codes(build(src(constraints=["c"] * 17))),
                         [("too_many_items", "constraints")])

    def test_too_many_fields_bounded(self):
        d = {"k%d" % i: i for i in range(rs.MAX_FIELDS + 1)}
        self.assertEqual(codes(build(d)), [("too_many_fields", "source")])

    def test_errors_ordered_and_bounded(self):
        r = build({"source_id": 1, "source_type": 2, "location": 3, "trust_level": 4,
                   "constraints": 5, "enabled": 6, "junk": 7})
        self.assertEqual([c for c, _ in codes(r)],
                         ["unexpected_field", "invalid_source_id", "invalid_source_type",
                          "invalid_location", "invalid_trust_level", "invalid_constraints",
                          "invalid_enabled"])
        many = build({"k%d" % i: 0 for i in range(rs.MAX_FIELDS)})
        self.assertLessEqual(len(many["errors"]), rs.MAX_ERRORS)

    def test_never_raises_on_hostile_input(self):
        class Boom(dict):
            def __len__(self):
                raise RuntimeError("boom")

        class Evil(str):
            def __eq__(self, other):
                raise RuntimeError("boom")
            __hash__ = str.__hash__
        for bad in (Boom(), {"source_id": Evil("a")}, src(source_type=Evil("web")),
                    src(trust_level=Evil("trusted"))):
            r = build(bad)
            check_shape(self, r)
            self.assertFalse(r["valid"])
            self.assertFalse(validate(bad)["valid"])


class ValidateTests(unittest.TestCase):
    def test_all_eight_fields_required(self):
        for key in NORMAL_KEYS:
            d = normal()
            del d[key]
            self.assertEqual(codes(validate(d)), [("missing_field", key)])

    def test_missing_non_dict_and_extra(self):
        self.assertEqual(codes(validate()), [("missing_source", "source")])
        self.assertEqual(codes(validate([])), [("source_not_dict", "source")])
        self.assertEqual(codes(validate(normal(extra=1))), [("unexpected_field", "extra")])

    def test_flags_and_enums_checked_exactly(self):
        for bad in (True, 0, None, "False"):
            self.assertEqual(codes(validate(normal(execution_allowed=bad))),
                             [("invalid_execution_allowed", "execution_allowed")])
        self.assertEqual(codes(validate(normal(source_type="ftp"))),
                         [("invalid_source_type", "source_type")])
        self.assertEqual(codes(validate(normal(trust_level="full"))),
                         [("invalid_trust_level", "trust_level")])
        self.assertEqual(codes(validate(normal(enabled=1))), [("invalid_enabled", "enabled")])
        self.assertEqual(codes(validate(normal(version="2"))), [("invalid_version", "version")])

    def test_validation_never_repairs_or_mutates(self):
        bad = normal(source_type="WEB", location=" padded ", constraints=["a", 1])
        snap = copy.deepcopy(bad)
        self.assertFalse(validate(bad)["valid"])
        self.assertEqual(bad, snap)


class IsolationTests(unittest.TestCase):
    def test_build_never_mutates_input_and_returns_fresh_structures(self):
        s = src()
        snap = copy.deepcopy(s)
        a, b = build(s), build(s)
        self.assertEqual(s, snap)
        self.assertEqual(a, b)
        self.assertIsNot(a["source"], b["source"])
        self.assertIsNot(a["source"]["constraints"], s["constraints"])
        self.assertIsNot(a["source"]["constraints"], b["source"]["constraints"])
        a["source"]["constraints"].append("mutated")
        self.assertEqual(s, snap)

    def test_no_imports_and_no_io_calls(self):
        with open(os.path.join(ROOT, "research", "research_source.py"), encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        for node in ast.walk(tree):
            self.assertNotIsInstance(node, (ast.Import, ast.ImportFrom))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                self.assertNotIn(node.func.id, {"open", "exec", "eval", "compile", "__import__"})

    def test_public_api(self):
        public = sorted(n for n in dir(rs) if not n.startswith("_") and callable(getattr(rs, n)))
        self.assertEqual(public, ["build_research_source", "validate_research_source"])
        self.assertEqual(rs.SOURCE_VERSION, "1")


if __name__ == "__main__":
    unittest.main()
