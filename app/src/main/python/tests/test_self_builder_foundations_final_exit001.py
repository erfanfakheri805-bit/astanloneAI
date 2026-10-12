"""
FINAL-EXIT-001 - Self-Builder foundations.

Unit tests of the building blocks the controlled capability builder stands on
(self_builder/): the policy, the error types, the Persian text helpers, the math
primitives, the safe expression engine, the unit table, the text operations, the sandbox
helpers, capability specs, the code templates, the AST validator and the sandbox loader.

Expected values come from independent knowledge (physical constants, hand-computed numbers,
Python's own evaluator used as an oracle INSIDE the tests) - never from the code under test.

Run directly:
    python -m unittest tests.test_self_builder_foundations_final_exit001 -v
"""

import ast
import math
import os
import random
import shutil
import sys
import tempfile
import unittest
from fractions import Fraction
from unittest import mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from self_builder import errors, expr, fa_text, helpers, mathcore, policy, sandbox, templates, textops, units, validator
from self_builder import spec as spec_mod
from self_builder.errors import ExprError, PolicyViolation, SandboxError, SelfBuilderError, SpecError, ValidationError


def km_mi(**kw):
    return spec_mod.unit_conversion_spec(units.UNITS["km"], units.UNITS["mi"], **kw)


def make_root():
    root = tempfile.mkdtemp(prefix="sb_found_")
    for d in (policy.SUBDIR_MODULES, policy.SUBDIR_STAGING, policy.SUBDIR_TESTS, policy.SUBDIR_SPECS):
        os.makedirs(os.path.join(root, d))
    return root


def write_file(root, subdir, name, text):
    path = os.path.join(root, subdir, name)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return path


def outcome(fn):
    """('ok', value) or ('err', code) of a numeric call."""
    try:
        return "ok", fn()
    except mathcore.MathFailure as e:
        return "err", e.code


# ============================================================================ policy
class TestPolicy(unittest.TestCase):
    def test_the_archetype_set_is_closed_and_exactly_three(self):
        self.assertEqual(set(policy.SUPPORTED_ARCHETYPES), {"unit_conversion", "formula", "text_tool"})

    def test_only_pure_computation_can_be_granted(self):
        self.assertEqual(policy.GRANTABLE_PERMISSIONS, frozenset({"compute"}))

    def test_known_operations_pass(self):
        for op in policy.ALLOWED_OPERATIONS:
            self.assertEqual(policy.Policy.check_operation(op), op)

    def test_unknown_operations_are_refused(self):
        for op in ("delete_everything", "network", "exec", "write_source", "", None, "stage_files ", "STAGE_FILES"):
            with self.subTest(op=op), self.assertRaises(PolicyViolation) as cm:
                policy.Policy.check_operation(op)
            self.assertEqual(cm.exception.code, "E_POLICY_OPERATION")

    def test_archetype_checks(self):
        for kind in policy.SUPPORTED_ARCHETYPES:
            self.assertEqual(policy.Policy.check_archetype(kind), kind)
        for kind in ("game", "code_generation", "", None, "Formula", "unit-conversion"):
            with self.subTest(kind=kind), self.assertRaises(PolicyViolation) as cm:
                policy.Policy.check_archetype(kind)
            self.assertEqual(cm.exception.code, "E_POLICY_ARCHETYPE")

    def test_permissions(self):
        self.assertEqual(policy.Policy.check_permissions(["compute"]), ["compute"])
        self.assertEqual(policy.Policy.check_permissions(None), [])
        for bad in (["network"], ["compute", "file_write"], ["process"], ["compute", "COMPUTE"], ["import"]):
            with self.subTest(bad=bad), self.assertRaises(PolicyViolation) as cm:
                policy.Policy.check_permissions(bad)
            self.assertEqual(cm.exception.code, "E_POLICY_PERMISSION")

    def test_capability_id_grammar(self):
        for good in ("unit_km_to_mi", "abc", "a" + "b" * 47, "text_count_words", "formula_ab12cd34ef", "x_1_2"):
            with self.subTest(good=good):
                self.assertTrue(policy.is_valid_capability_id(good))
                self.assertEqual(policy.Policy.check_capability_id(good), good)
        for bad in ("", "ab", "1abc", "Abc", "a-b-c", "a b c", "../x", "a/b", "a" * 49, None, 5, "abc.py", "سلام"):
            with self.subTest(bad=bad):
                self.assertFalse(policy.is_valid_capability_id(bad))
                with self.assertRaises(PolicyViolation) as cm:
                    policy.Policy.check_capability_id(bad)
                self.assertEqual(cm.exception.code, "E_POLICY_ID")

    def test_file_names_per_directory(self):
        ok = {
            policy.SUBDIR_MODULES: ["unit_km_to_mi_v1.py", "abc_v1234.py"],
            policy.SUBDIR_TESTS: ["unit_km_to_mi_v1.json"],
            policy.SUBDIR_SPECS: ["unit_km_to_mi_v12.json"],
            policy.SUBDIR_STAGING: ["stg_abc123.py", "stg_abc123.json"],
            policy.SUBDIR_CHECKPOINTS: ["ck_1.json", "ck_123456789.json"],
            policy.SUBDIR_QUARANTINE: ["q_unit_km_to_mi_v1.20260101.py", "q_abc.json"],
        }
        for subdir, names in ok.items():
            for name in names:
                with self.subTest(subdir=subdir, name=name):
                    self.assertEqual(policy.Policy.check_file_name(subdir, name), name)

    def test_file_names_that_must_be_refused(self):
        bad = [
            (policy.SUBDIR_MODULES, "unit_km_to_mi_v1.json"),     # wrong suffix for the directory
            (policy.SUBDIR_MODULES, "unit_km_to_mi_v1.txt"),
            (policy.SUBDIR_MODULES, "unit_km_to_mi.py"),          # no version
            (policy.SUBDIR_MODULES, "ab_v1.py"),                  # id too short
            (policy.SUBDIR_MODULES, "../unit_km_to_mi_v1.py"),
            (policy.SUBDIR_MODULES, "sub/unit_km_to_mi_v1.py"),
            (policy.SUBDIR_MODULES, "unit_km_to_mi_v1.py\x00.txt"),
            (policy.SUBDIR_MODULES, "UNIT_km_v1.py"),
            (policy.SUBDIR_TESTS, "unit_km_to_mi_v1.py"),
            (policy.SUBDIR_STAGING, "unit_km_to_mi_v1.py"),
            (policy.SUBDIR_CHECKPOINTS, "ck_x.json"),
            (policy.SUBDIR_QUARANTINE, "../etc"),
            (policy.SUBDIR_QUARANTINE, "q_a"),                    # too short
            (policy.SUBDIR_MODULES, None),
            (policy.SUBDIR_MODULES, 5),
        ]
        for subdir, name in bad:
            with self.subTest(subdir=subdir, name=name), self.assertRaises(PolicyViolation) as cm:
                policy.Policy.check_file_name(subdir, name)
            self.assertEqual(cm.exception.code, "E_POLICY_NAME")

    def test_quarantined_files_still_need_an_allowed_file_type(self):
        for name in ("q_abc", "q_unit_km_to_mi_v1.py.20260101", "q_unit_km_to_mi_v1.sh", "q_unit_km_to_mi_v1.exe"):
            with self.subTest(name=name), self.assertRaises(PolicyViolation) as cm:
                policy.Policy.check_file_name(policy.SUBDIR_QUARANTINE, name)
            self.assertEqual(cm.exception.code, "E_POLICY_SUFFIX")

    def test_unknown_directories_are_refused(self):
        for subdir in ("etc", "..", "", None, "Modules", "modules/", "data"):
            with self.subTest(subdir=subdir), self.assertRaises(PolicyViolation) as cm:
                policy.Policy.check_file_name(subdir, "unit_km_to_mi_v1.py")
            self.assertEqual(cm.exception.code, "E_POLICY_DIR")

    def test_only_two_root_files_exist(self):
        self.assertEqual(policy.Policy.check_root_file("manifest.json"), "manifest.json")
        self.assertEqual(policy.Policy.check_root_file("self_builder.db"), "self_builder.db")
        for bad in ("evil.py", "memory.db", "../manifest.json", "manifest.JSON", ""):
            with self.subTest(bad=bad), self.assertRaises(PolicyViolation):
                policy.Policy.check_root_file(bad)

    def test_only_py_and_json_suffixes(self):
        self.assertEqual(policy.ALLOWED_SUFFIXES, frozenset({".py", ".json"}))

    def test_resolve_stays_inside_the_root(self):
        root = make_root()
        self.addCleanup(shutil.rmtree, root, True)
        path = policy.Policy.resolve(root, policy.SUBDIR_MODULES, "unit_km_to_mi_v1.py")
        self.assertEqual(path, os.path.join(os.path.realpath(root), "modules", "unit_km_to_mi_v1.py"))
        self.assertEqual(policy.Policy.resolve(root, None, "self_builder.db"),
                         os.path.join(os.path.realpath(root), "self_builder.db"))

    def test_resolve_refuses_a_symlinked_file_and_a_symlinked_directory(self):
        root = make_root()
        self.addCleanup(shutil.rmtree, root, True)
        outside = tempfile.mkdtemp(prefix="sb_outside_")
        self.addCleanup(shutil.rmtree, outside, True)
        target = os.path.join(outside, "x.py")
        open(target, "w").close()
        os.symlink(target, os.path.join(root, "modules", "abc_v1.py"))
        with self.assertRaises(PolicyViolation) as cm:
            policy.Policy.resolve(root, policy.SUBDIR_MODULES, "abc_v1.py")
        self.assertEqual(cm.exception.code, "E_POLICY_SYMLINK")
        shutil.rmtree(os.path.join(root, "specs"))
        os.symlink(outside, os.path.join(root, "specs"))
        with self.assertRaises(PolicyViolation) as cm:
            policy.Policy.resolve(root, policy.SUBDIR_SPECS, "abc_v1.json")
        self.assertEqual(cm.exception.code, "E_POLICY_SYMLINK")

    def test_describe_reports_the_real_constants(self):
        d = policy.Policy.describe()
        self.assertEqual(d["archetypes"], list(policy.SUPPORTED_ARCHETYPES))
        self.assertEqual(d["permissions"], ["compute"])
        self.assertEqual(set(d["directories"]), {"staging", "modules", "tests", "specs", "checkpoints", "quarantine"})
        self.assertEqual(d["limits"]["max_source_bytes"], policy.MAX_SOURCE_BYTES)
        self.assertEqual(d["limits"]["max_capabilities"], policy.MAX_CAPABILITIES)

    def test_limits_are_small_positive_and_finite(self):
        for name in ("MAX_SOURCE_BYTES", "MAX_TESTS_BYTES", "MAX_EXPR_CHARS", "MAX_EXPR_NODES", "MAX_EXPR_DEPTH",
                     "MAX_VARIABLES", "MAX_TEST_CASES", "MAX_CAPABILITIES", "MAX_VERSIONS_PER_CAPABILITY",
                     "MAX_REPAIR_ATTEMPTS", "MAX_REQUEST_CHARS", "MAX_INVOKE_TEXT_CHARS", "MAX_AST_NODES",
                     "MAX_STRING_CONSTANT"):
            value = getattr(policy, name)
            self.assertIsInstance(value, int, name)
            self.assertGreater(value, 0, name)
        self.assertLessEqual(policy.MAX_SOURCE_BYTES, 64_000)
        self.assertTrue(math.isfinite(policy.MAX_RESULT_ABS))
        self.assertLess(policy.MAX_CALL_SECONDS, 5)


# ============================================================================ errors
class TestErrors(unittest.TestCase):
    def test_hierarchy_and_default_codes(self):
        expected = {errors.PolicyViolation: "E_POLICY", errors.SpecError: "E_SPEC", errors.ExprError: "E_EXPR",
                    errors.ValidationError: "E_VALIDATION", errors.SandboxError: "E_SANDBOX",
                    errors.StoreError: "E_STORE", errors.ApplyError: "E_APPLY"}
        for cls, code in expected.items():
            with self.subTest(cls=cls.__name__):
                self.assertTrue(issubclass(cls, SelfBuilderError))
                self.assertEqual(cls().code, code)

    def test_code_detail_and_info(self):
        e = SelfBuilderError("something broke", code="E_X", pos=3, found="(")
        self.assertEqual(e.code, "E_X")
        self.assertEqual(e.detail, "something broke")
        self.assertEqual(str(e), "something broke")
        self.assertEqual(e.to_dict(), {"code": "E_X", "detail": "something broke", "info": {"pos": 3, "found": "("}})

    def test_without_info_or_detail(self):
        e = SpecError()
        self.assertEqual(e.detail, "E_SPEC")
        self.assertEqual(e.to_dict(), {"code": "E_SPEC", "detail": "E_SPEC"})

    def test_instance_code_does_not_leak_into_the_class(self):
        SelfBuilderError("x", code="E_TEMP")
        self.assertEqual(SelfBuilderError.code, "E_SELF_BUILDER")


# ========================================================================== fa_text
class TestFaText(unittest.TestCase):
    def test_canon_maps_arabic_letters_digits_and_separators(self):
        cases = {"كتاب ي": "کتاب ی", "۱۲۳": "123", "٤٥٦": "456", "۲٫۵": "2.5", "۱٬۰۰۰": "1000", "سلاـم": "سلام",
                 "می‌روم": "می روم", "a\u200bb\u200dc": "abc", "a\u200eb": "ab", "": "", None: ""}
        for raw, want in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(fa_text.canon(raw), want)

    def test_words_and_key(self):
        self.assertEqual(fa_text.words("می‌روم ۱۰ KM 2.5"), ["می", "روم", "10", "km", "2.5"])
        self.assertEqual(fa_text.words(""), [])
        self.assertEqual(fa_text.words(None), [])
        self.assertEqual(fa_text.key("سانتی‌متر"), fa_text.key("سانتی متر"))
        self.assertEqual(fa_text.key("سانتی‌متر"), fa_text.key("سانتیمتر"))
        self.assertEqual(fa_text.key("Hello, World!"), "helloworld")
        self.assertNotEqual(fa_text.key("متر"), fa_text.key("سانتیمتر"))

    def test_has_persian_script(self):
        self.assertTrue(fa_text.has_persian_script("hello سلام"))
        self.assertTrue(fa_text.has_persian_script("ك"))
        self.assertFalse(fa_text.has_persian_script("hello 123"))
        self.assertFalse(fa_text.has_persian_script(""))
        self.assertFalse(fa_text.has_persian_script(None))

    def test_parse_number(self):
        for raw, want in (("2", 2.0), ("2.5", 2.5), ("-3", -3.0), ("+4", 4.0), ("۲٫۵", 2.5), ("۱۲", 12.0),
                          ("1 000", 1000.0)):
            with self.subTest(raw=raw):
                self.assertEqual(fa_text.parse_number(raw), want)
        for raw in ("abc", "1e5", "", None, "1.2.3", "--1", "۱۲abc"):
            with self.subTest(raw=raw):
                self.assertIsNone(fa_text.parse_number(raw))

    def test_scan_numbers_digits_and_words(self):
        cases = [
            ("پنج", [(0, 1, 5.0)]),
            ("بیست و پنج", [(0, 3, 25.0)]),
            ("صد و بیست", [(0, 3, 120.0)]),
            ("دویست و پنجاه و سه", [(0, 5, 253.0)]),
            ("دو و نیم", [(0, 3, 2.5)]),
            ("یک و نیم متر", [(0, 3, 1.5)]),
            ("سه هزار و پانصد", [(0, 4, 3500.0)]),
            ("دو میلیون و سیصد هزار", [(0, 5, 2300000.0)]),
            ("هزار", [(0, 1, 1000.0)]),
            ("نیم", [(0, 1, 0.5)]),
            ("2 و نیم", [(0, 3, 2.5)]),
            ("پنج کیلومتر", [(0, 1, 5.0)]),
            ("ده و بیست", [(0, 1, 10.0), (2, 3, 20.0)]),      # "و" only joins decreasing magnitude classes
            ("از ۱۰ تا ۲۰", [(1, 2, 10.0), (3, 4, 20.0)]),
            ("سلام دنیا", []),
            ("", []),
        ]
        for text, want in cases:
            with self.subTest(text=text):
                self.assertEqual(fa_text.scan_numbers(fa_text.words(text)), want)

    def test_format_number(self):
        cases = [(6.213712, "6.213712"), (0.1 + 0.2, "0.3"), (100.0, "100"), (-0.0, "0"), (1234567.891, "1234567.891"),
                 (2.0000004, "2"), (1e-7, "1e-07"), (1.2345678901234567e19, "1.23457e+19"), (-2.5, "-2.5"),
                 (float("nan"), "نامعتبر"), (float("inf"), "نامعتبر"), (None, "")]
        for value, want in cases:
            with self.subTest(value=value):
                self.assertEqual(fa_text.format_number(value), want)
        self.assertEqual(fa_text.format_number(1 / 3, 3), "0.333")

    def test_persian_digit_formatting(self):
        self.assertEqual(fa_text.fa_number(1234.5), "۱۲۳۴٫۵")
        self.assertEqual(fa_text.fa_number(-2), "-۲")
        self.assertEqual(fa_text.fa_number(1.5e20), "۱٫۵×۱۰^۲۰")
        self.assertEqual(fa_text.fa_number(1e-7), "۱×۱۰^-۷")
        self.assertEqual(fa_text.to_fa_digits("12.5"), "۱۲٫۵")
        self.assertEqual(fa_text.fa_number(0), "۰")

    def test_join_fa(self):
        self.assertEqual(fa_text.join_fa(["الف", "ب", "ج"]), "الف، ب و ج")
        self.assertEqual(fa_text.join_fa(["الف", "ب"]), "الف و ب")
        self.assertEqual(fa_text.join_fa(["الف"]), "الف")
        self.assertEqual(fa_text.join_fa([]), "")
        self.assertEqual(fa_text.join_fa(["a", "b"], conj="یا"), "a یا b")


# ========================================================================= mathcore
class TestMathcore(unittest.TestCase):
    def fails(self, fn, code):
        with self.assertRaises(mathcore.MathFailure) as cm:
            fn()
        self.assertEqual(cm.exception.code, code)

    def test_division(self):
        self.assertEqual(mathcore.div(6, 3), 2.0)
        self.assertEqual(mathcore.div(1, 4), 0.25)
        self.fails(lambda: mathcore.div(1, 0), "division_by_zero")
        self.fails(lambda: mathcore.div(1, 0.0), "division_by_zero")
        self.fails(lambda: mathcore.div("a", 1), "bad_input")
        self.fails(lambda: mathcore.div(True, 1), "bad_input")
        self.fails(lambda: mathcore.div(float("inf"), 1), "overflow")
        self.fails(lambda: mathcore.div(1, float("nan")), "overflow")

    def test_power(self):
        self.assertEqual(mathcore.power(2, 10), 1024.0)
        self.assertEqual(mathcore.power(2, -1), 0.5)
        self.assertEqual(mathcore.power(-2, 3), -8.0)
        self.assertEqual(mathcore.power(9, 0.5), 3.0)
        self.assertEqual(mathcore.power(0, 0), 1.0)
        self.fails(lambda: mathcore.power(2, 65), "bad_power")
        self.fails(lambda: mathcore.power(2, -65), "bad_power")
        self.fails(lambda: mathcore.power(0, -1), "division_by_zero")
        self.fails(lambda: mathcore.power(-8, 1 / 3), "domain")
        self.fails(lambda: mathcore.power(1e200, 2), "overflow")
        self.fails(lambda: mathcore.power(10, 64) * 1e300 and mathcore.power(1e300, 64), "overflow")

    def test_roots_logs_and_exponentials(self):
        self.assertEqual(mathcore.sqrt(16), 4.0)
        self.fails(lambda: mathcore.sqrt(-1), "domain")
        self.assertAlmostEqual(mathcore.ln(math.e), 1.0, places=12)
        self.fails(lambda: mathcore.ln(0), "domain")
        self.fails(lambda: mathcore.ln(-5), "domain")
        self.assertAlmostEqual(mathcore.log10(1000), 3.0, places=12)
        self.fails(lambda: mathcore.log10(0), "domain")
        self.assertAlmostEqual(mathcore.exp(1), math.e, places=12)
        self.assertEqual(mathcore.exp(0), 1.0)
        self.fails(lambda: mathcore.exp(701), "overflow")

    def test_trigonometry(self):
        self.assertAlmostEqual(mathcore.sin(math.pi / 2), 1.0, places=12)
        self.assertEqual(mathcore.cos(0), 1.0)
        self.assertAlmostEqual(mathcore.tan(math.pi / 4), 1.0, places=12)
        self.fails(lambda: mathcore.tan(math.pi / 2), "domain")

    def test_rounding_and_extremes(self):
        self.assertEqual(mathcore.absolute(-3.5), 3.5)
        self.assertEqual(mathcore.minimum(3, 1, 2), 1.0)
        self.assertEqual(mathcore.maximum(3, 1, 2), 3.0)
        self.assertEqual(mathcore.floor(-1.5), -2.0)
        self.assertEqual(mathcore.floor(2.9), 2.0)
        self.assertEqual(mathcore.ceil(-1.5), -1.0)
        self.assertEqual(mathcore.ceil(2.1), 3.0)
        self.assertEqual(mathcore.round_to(1234.5678, 2), 1234.57)
        self.assertEqual(mathcore.round_to(1234.5678), 1235.0)
        self.assertEqual(mathcore.round_to(1234.5678, -2), 1200.0)
        self.fails(lambda: mathcore.round_to(1.5, 0.5), "domain")
        self.fails(lambda: mathcore.round_to(1.5, 13), "domain")
        self.fails(lambda: mathcore.minimum(1, "a"), "bad_input")

    def test_finite_guards_every_final_result(self):
        self.assertEqual(mathcore.finite(1e299), 1e299)
        self.assertEqual(mathcore.finite(-5), -5.0)
        for bad in (1e301, -1e301, float("inf"), float("-inf"), float("nan")):
            with self.subTest(bad=bad):
                self.fails(lambda b=bad: mathcore.finite(b), "overflow")

    def test_number_input(self):
        self.assertEqual(mathcore.number_input({"value": 3}, "value"), 3.0)
        self.assertIsInstance(mathcore.number_input({"value": 3}, "value"), float)
        self.fails(lambda: mathcore.number_input({}, "value"), "bad_input")
        self.fails(lambda: mathcore.number_input(None, "value"), "bad_input")
        self.fails(lambda: mathcore.number_input([1], "value"), "bad_input")
        for bad in ("5", True, False, None, [1], {"a": 1}, b"1"):
            with self.subTest(bad=bad):
                self.fails(lambda b=bad: mathcore.number_input({"value": b}, "value"), "bad_input")
        self.fails(lambda: mathcore.number_input({"value": float("nan")}, "value"), "overflow")

    def test_failures_are_arithmetic_errors_with_codes(self):
        e = mathcore.MathFailure("domain", "x")
        self.assertIsInstance(e, ArithmeticError)
        self.assertEqual((e.code, e.detail), ("domain", "x"))
        self.assertEqual(mathcore.MathFailure("domain").detail, "domain")


# ============================================================================== expr
class TestExprEvaluation(unittest.TestCase):
    def ev(self, text, **env):
        return expr.evaluate(expr.parse(text), env)

    def test_precedence_associativity_and_unary_minus(self):
        cases = [("1 + 2 * 3", 7), ("(1 + 2) * 3", 9), ("2 ** 3 ** 2", 512), ("(2 ** 3) ** 2", 64), ("-2 ** 2", -4),
                 ("(-2) ** 2", 4), ("2 ** -1", 0.5), ("10 / 4", 2.5), ("10 - 4 - 3", 3), ("100 / 10 / 5", 2),
                 ("+5", 5), ("--5", 5), ("- - 5", 5), ("2 * -3", -6), ("2 - -3", 5), ("1e3 + .5", 1000.5),
                 ("  7  ", 7), ("2 * 3 ** 2", 18), ("-3 ** 2 + 10", 1), ("1 - 2 + 3", 2), ("8 / 2 * 4", 16)]
        for text, want in cases:
            with self.subTest(text=text):
                self.assertAlmostEqual(self.ev(text), want, places=12)

    def test_functions_and_constants(self):
        cases = [("sqrt(16) + abs(-3)", 7), ("max(1, 5, 3)", 5), ("min(4, 2)", 2), ("max(1, 2, 3, 4)", 4),
                 ("floor(2.7) + ceil(2.1)", 5), ("round(3.14159, 2)", 3.14), ("round(2.6)", 3), ("ln(1)", 0),
                 ("log10(100)", 2), ("exp(0)", 1), ("sin(0)", 0), ("cos(0)", 1), ("tan(0)", 0),
                 ("pi", math.pi), ("PI * 2", 2 * math.pi), ("Sqrt(9)", 3), ("abs(-2) ** 3", 8),
                 ("sqrt(sqrt(16))", 2), ("max(min(1, 2), 0.5)", 1)]
        for text, want in cases:
            with self.subTest(text=text):
                self.assertAlmostEqual(self.ev(text), want, places=12)

    def test_variables_are_case_insensitive_and_read_from_the_environment(self):
        self.assertAlmostEqual(self.ev("pi * r ** 2", r=3), 28.274333882308138, places=12)
        self.assertAlmostEqual(self.ev("W / (H * H)", w=70, h=1.75), 22.857142857142858, places=12)
        self.assertEqual(self.ev("a + a * a", a=2), 6.0)

    def test_numeric_failures_carry_stable_codes(self):
        for text, env, code in (("1 / 0", {}, "division_by_zero"), ("sqrt(-1)", {}, "domain"),
                                ("2 ** 100", {}, "bad_power"), ("(-8) ** 0.5", {}, "domain"),
                                ("a / b", {"a": 1, "b": 0}, "division_by_zero"), ("ln(0)", {}, "domain"),
                                ("x + 1", {}, "bad_input"), ("x + 1", {"x": "5"}, "bad_input"),
                                ("x + 1", {"x": True}, "bad_input")):
            with self.subTest(text=text), self.assertRaises(mathcore.MathFailure) as cm:
                expr.evaluate(expr.parse(text), env)
            self.assertEqual(cm.exception.code, code)

    def test_evaluate_final_rejects_overflow(self):
        with self.assertRaises(mathcore.MathFailure) as cm:
            expr.evaluate_final(expr.parse("1e200 * 1e200"), {})
        self.assertEqual(cm.exception.code, "overflow")
        self.assertEqual(expr.evaluate_final(expr.parse("2 + 2"), {}), 4.0)

    def test_evaluator_agrees_with_pythons_own_arithmetic_on_random_expressions(self):
        rng = random.Random(20260101)
        ops = ["+", "-", "*", "/"]

        def gen(depth):
            if depth == 0 or rng.random() < 0.25:
                return str(rng.randint(1, 9)) if rng.random() < 0.8 else f"{rng.randint(1, 9)}.{rng.randint(0, 9)}"
            r = rng.random()
            if r < 0.15:
                return f"(-{gen(depth - 1)})"
            if r < 0.30:
                return f"({gen(depth - 1)}) ** {rng.randint(0, 3)}"
            return f"({gen(depth - 1)} {rng.choice(ops)} {gen(depth - 1)})"

        checked = divisions = 0
        for _ in range(400):
            text = gen(4)
            try:
                want = eval(text, {"__builtins__": {}}, {})          # the ORACLE: Python's own evaluator
            except ZeroDivisionError:
                with self.assertRaises(mathcore.MathFailure) as cm:
                    expr.evaluate(expr.parse(text), {})
                self.assertEqual(cm.exception.code, "division_by_zero", text)
                divisions += 1
                continue
            if isinstance(want, complex) or abs(want) > 1e12:
                continue
            got = expr.evaluate(expr.parse(text), {})
            self.assertAlmostEqual(got, want, delta=1e-9 * max(1.0, abs(want)), msg=text)
            checked += 1
        self.assertGreater(checked, 250)

    def test_text_without_spaces_and_with_exponent_notation(self):
        self.assertEqual(self.ev("2*3+4"), 10.0)
        self.assertEqual(self.ev("1E2"), 100.0)
        self.assertEqual(self.ev("2e-1"), 0.2)


class TestExprStructure(unittest.TestCase):
    def test_tree_shapes(self):
        self.assertEqual(expr.parse("1 + x"), ["bin", "+", ["num", 1.0], ["var", "x"]])
        self.assertEqual(expr.parse("-pi"), ["neg", ["const", "pi"]])
        self.assertEqual(expr.parse("sqrt(2)"), ["call", "sqrt", [["num", 2.0]]])
        self.assertEqual(expr.parse("2 ** 3 ** 2"),
                         ["bin", "**", ["num", 2.0], ["bin", "**", ["num", 3.0], ["num", 2.0]]])

    def test_variables_functions_constants_and_node_counts(self):
        tree = expr.parse("b + a * b + sqrt(c) + pi")
        self.assertEqual(expr.variables(tree), ["b", "a", "c"])
        self.assertEqual(expr.functions_used(tree), ["sqrt"])
        self.assertEqual(expr.constants_used(tree), ["pi"])
        self.assertEqual(expr.count_nodes(expr.parse("1 + 2")), 3)
        self.assertEqual(expr.count_nodes(expr.parse("-x")), 2)
        self.assertEqual(expr.count_nodes(expr.parse("max(1, 2)")), 3)
        self.assertEqual(expr.variables(expr.parse("2 + 3")), [])

    def test_helper_names_used(self):
        self.assertEqual(expr.helper_names_used(expr.parse("a / b ** 2 + sqrt(c)")),
                         ["_sb_div", "_sb_power", "_sb_sqrt"])
        self.assertEqual(expr.helper_names_used(expr.parse("a + b * c")), [])
        self.assertEqual(expr.helper_names_used(expr.parse("abs(x) + round(x, 1)")), ["_sb_absolute", "_sb_round_to"])

    def test_generated_source_uses_only_operators_literals_parameters_and_helpers(self):
        src = expr.to_source(expr.parse("a / b ** 2 + -c * sqrt(d)"))
        node = ast.parse(src, mode="eval")
        kinds = {type(n).__name__ for n in ast.walk(node)}
        self.assertTrue(kinds <= {"Expression", "BinOp", "UnaryOp", "Call", "Name", "Constant", "Add", "Sub", "Mult",
                                  "USub", "Load"}, kinds)
        names = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
        self.assertEqual(names, {"_sb_div", "_sb_power", "_sb_sqrt", "x_a", "x_b", "x_c", "x_d"})

    def test_generated_source_is_equivalent_to_the_reference_evaluator(self):
        texts = ["a + b * c", "(a + b) * c", "a - b - c", "a / b / c", "-a ** 2", "a ** b ** 2", "sqrt(a * a + b * b)",
                 "abs(a - b) / max(a, b, c)", "round(a / b, 2) + floor(c) - ceil(a)",
                 "ln(abs(a) + 1) + log10(abs(b) + 1) + exp(c / 100)", "sin(a) ** 2 + cos(a) ** 2", "pi * a ** 2",
                 "tan(a / 10)", "min(a, b) - max(b, c)", "(a + b) / (c - c)", "1e3 * a", "-(-a)", "a * -b",
                 "2 ** a", "a ** 0.5"]
        grid = [1.0, 2.0, 3.5, 0.5, 10.0, -1.0, 0.0, 7.25, -2.5]
        for text in texts:
            tree = expr.parse(text)
            src = expr.to_source(tree)
            code = compile(src, "<generated>", "eval")
            for i in range(len(grid)):
                env = {"a": grid[i], "b": grid[(i * 2 + 1) % len(grid)], "c": grid[(i * 5 + 3) % len(grid)]}
                scope = dict(helpers.HELPERS, **{"x_" + k: v for k, v in env.items()})
                reference = outcome(lambda: expr.evaluate(tree, env))
                generated = outcome(lambda: eval(code, {"__builtins__": {}}, scope))
                self.assertEqual(generated, reference, f"{text} with {env}")


class TestExprErrors(unittest.TestCase):
    CASES = [
        ("", "E_EXPR_EMPTY"), ("   ", "E_EXPR_EMPTY"), (None, "E_EXPR_EMPTY"), (5, "E_EXPR_EMPTY"),
        ("1 +", "E_EXPR_SYNTAX_END"), ("(", "E_EXPR_SYNTAX_END"), ("*", "E_EXPR_SYNTAX"), ("1 * * 2", "E_EXPR_SYNTAX"),
        ("(1 + 2", "E_EXPR_PAREN_OPEN"), ("sqrt(4", "E_EXPR_PAREN_OPEN"), ("1 + 2)", "E_EXPR_PAREN_CLOSE"),
        (")", "E_EXPR_PAREN_CLOSE"), ("2 3", "E_EXPR_ADJACENT"), ("2 x", "E_EXPR_ADJACENT"), ("2(3)", "E_EXPR_ADJACENT"),
        ("2pi", "E_EXPR_ADJACENT"), ("x y", "E_EXPR_ADJACENT"),
        ("foo(1)", "E_EXPR_UNKNOWN_FUNC"), ("__import__('os')", "E_EXPR_TOKEN"), ("sqrt", "E_EXPR_RESERVED_NAME"),
        ("sqrt + 1", "E_EXPR_RESERVED_NAME"), ("sqrt()", "E_EXPR_ARITY"), ("sqrt(1, 2)", "E_EXPR_ARITY"),
        ("min(1)", "E_EXPR_ARITY"), ("max(1, 2, 3, 4, 5)", "E_EXPR_ARITY"), ("round(1, 2, 3)", "E_EXPR_ARITY"),
        ("1 $ 2", "E_EXPR_TOKEN"), ("a.b", "E_EXPR_TOKEN"), ("'x'", "E_EXPR_TOKEN"), ("x = 1", "E_EXPR_TOKEN"),
        ("lambda: 1", "E_EXPR_TOKEN"), ("a[0]", "E_EXPR_TOKEN"), ("a if b else c", "E_EXPR_ADJACENT"),
        ("1 % 2", "E_EXPR_TOKEN"), ("1 // 2", "E_EXPR_SYNTAX"), ("a; b", "E_EXPR_TOKEN"), ("`a`", "E_EXPR_TOKEN"),
        ("وزن / قد", "E_EXPR_NON_ASCII_NAME"), ("2 * شعاع", "E_EXPR_NON_ASCII_NAME"),
        ("1e999", "E_EXPR_NUMBER"), ("a" * 25, "E_EXPR_TOO_LONG"), ("1" * 241, "E_EXPR_TOO_LONG"),
        ("(" * 30 + "1" + ")" * 30, "E_EXPR_TOO_COMPLEX"), ("+".join(["1"] * 100), "E_EXPR_TOO_COMPLEX"),
        ("_x + 1", "E_EXPR_TOKEN"), ("__builtins__", "E_EXPR_TOKEN"), ("a + __import__", "E_EXPR_TOKEN"),
    ]

    def test_every_malformed_input_has_its_stable_code(self):
        for text, code in self.CASES:
            with self.subTest(text=(text if not isinstance(text, str) else text[:40])), \
                    self.assertRaises(ExprError) as cm:
                expr.parse(text)
            self.assertEqual(cm.exception.code, code)

    def test_nothing_is_ever_executed(self):
        marker = os.path.join(tempfile.gettempdir(), "sb_expr_should_not_exist_%d" % os.getpid())
        for text in (f"__import__('os').system('touch {marker}')", f"open('{marker}', 'w')", "exec('1')",
                     "().__class__.__bases__", "globals()", "a.__class__"):
            with self.subTest(text=text), self.assertRaises(ExprError):
                expr.parse(text)
        self.assertFalse(os.path.exists(marker))

    def test_error_positions_and_details_are_reported(self):
        with self.assertRaises(ExprError) as cm:
            expr.parse("1 + $")
        self.assertEqual(cm.exception.info["char"], "$")
        self.assertEqual(cm.exception.info["pos"], 4)
        with self.assertRaises(ExprError) as cm:
            expr.parse("foo(1)")
        self.assertEqual(cm.exception.info["name"], "foo")

    def test_names_must_start_with_a_letter(self):
        # a leading underscore is refused at the tokenizer, so no dunder-style name can ever be introduced ...
        for text, pos in (("_x", 0), ("__builtins__ + 1", 0), ("2 * __class__", 4), ("sqrt(_a)", 5)):
            with self.subTest(text=text), self.assertRaises(ExprError) as cm:
                expr.parse(text)
            self.assertEqual((cm.exception.code, cm.exception.info["char"], cm.exception.info["pos"]),
                             ("E_EXPR_TOKEN", "_", pos))
        # ... while underscores inside a name stay fine
        self.assertEqual(expr.variables(expr.parse("a_1 + b__2")), ["a_1", "b__2"])

    def test_limits_are_the_policys(self):
        self.assertEqual(policy.MAX_EXPR_CHARS, 240)
        expr.parse("1" * 240)                                      # exactly at the limit is fine
        expr.parse("(" * 10 + "1" + ")" * 10)                      # within the depth limit
        with self.assertRaises(ExprError) as cm:
            expr.parse("(" * 20 + "1" + ")" * 20)                  # a parenthesis costs two depth levels
        self.assertEqual(cm.exception.code, "E_EXPR_TOO_COMPLEX")
        expr.parse(" + ".join(["x"] * 40))                          # 79 nodes


# ============================================================================== units
class TestUnits(unittest.TestCase):
    def conv(self, a, b, value):
        scale, shift = units.conversion_params(units.UNITS[a], units.UNITS[b])
        return value * scale + shift

    def test_table_is_consistent(self):
        self.assertGreaterEqual(len(units.UNITS), 35)
        for uid, unit in units.UNITS.items():
            with self.subTest(unit=uid):
                self.assertEqual(unit.id, uid)
                self.assertIn(unit.dimension, units.DIMENSION_FA)
                self.assertGreater(unit.factor, 0)
                self.assertTrue(unit.display)
                self.assertEqual(unit.to_dict(), {"id": uid, "dimension": unit.dimension, "display": unit.display})
                self.assertIs(units.lookup_unit(unit.display), units.UNITS[uid])

    def test_every_dimension_is_present(self):
        dims = {u.dimension for u in units.UNITS.values()}
        self.assertEqual(dims, {"length", "mass", "volume", "time", "temperature", "data", "area", "speed"})

    def test_known_physical_constants(self):
        cases = [("mi", "km", 1.609344), ("in", "cm", 2.54), ("lb", "kg", 0.45359237), ("ft", "m", 0.3048),
                 ("gal", "l", 3.785411784), ("h", "min", 60.0), ("day", "h", 24.0), ("week", "day", 7.0),
                 ("gb", "mb", 1024.0), ("byte", "bit", 8.0), ("ha", "m2", 10000.0), ("km2", "ha", 100.0),
                 ("nmi", "m", 1852.0), ("yd", "ft", 3.0), ("t", "kg", 1000.0), ("oz", "g", 28.349523125),
                 ("mph", "mps", 0.44704), ("m3", "l", 1000.0), ("km", "m", 1000.0), ("kg", "g", 1000.0)]
        for a, b, want in cases:
            with self.subTest(a=a, b=b):
                self.assertAlmostEqual(self.conv(a, b, 1.0), want, delta=1e-9 * want)

    def test_speed_and_inverse_values(self):
        self.assertAlmostEqual(self.conv("kmh", "mps", 36.0), 10.0, places=9)
        self.assertAlmostEqual(self.conv("km", "mi", 10.0), 6.2137119223733, places=9)
        self.assertAlmostEqual(self.conv("mi", "km", 26.2), 42.1648128, places=6)

    def test_temperatures_use_offsets(self):
        self.assertAlmostEqual(self.conv("c", "f", 0), 32.0, places=9)
        self.assertAlmostEqual(self.conv("c", "f", 100), 212.0, places=9)
        self.assertAlmostEqual(self.conv("f", "c", 212), 100.0, places=9)
        self.assertAlmostEqual(self.conv("f", "c", -40), -40.0, places=9)
        self.assertAlmostEqual(self.conv("c", "k", 0), 273.15, places=9)
        self.assertAlmostEqual(self.conv("k", "c", 0), -273.15, places=9)
        self.assertAlmostEqual(self.conv("f", "k", 32), 273.15, places=9)
        self.assertAlmostEqual(self.conv("c", "f", 37), 98.6, places=9)

    def test_round_trip_over_every_pair_of_the_same_dimension(self):
        pairs = 0
        for a, ua in units.UNITS.items():
            for b, ub in units.UNITS.items():
                if a == b or ua.dimension != ub.dimension:
                    continue
                for value in (1.0, 37.5, -12.0, 1e6):
                    there = self.conv(a, b, value)
                    back = self.conv(b, a, there)
                    self.assertAlmostEqual(back, value, delta=1e-9 * max(1.0, abs(value)), msg=f"{a}->{b}")
                pairs += 1
        self.assertGreater(pairs, 100)

    def test_different_dimensions_cannot_be_converted(self):
        for a, b in (("km", "kg"), ("c", "m"), ("h", "m"), ("kmh", "km")):
            with self.subTest(a=a, b=b), self.assertRaises(SpecError) as cm:
                units.conversion_params(units.UNITS[a], units.UNITS[b])
            self.assertEqual(cm.exception.code, "E_SPEC_DIMENSION")

    def test_lookup_in_persian_and_latin(self):
        cases = {"کیلومتر": "km", "km": "km", "KM": "km", "Kilometers": "km", "سانتی‌متر": "cm", "سانتی متر": "cm",
                 "سانتیمتر": "cm", "مایل": "mi", "مایل دریایی": "nmi", "فارنهایت": "f", "درجه سلسیوس": "c",
                 "گیگابایت": "gb", "ساعت": "h", "پا": "ft", "feet": "ft", "pound": "lb"}
        for surface, uid in cases.items():
            with self.subTest(surface=surface):
                self.assertEqual(units.lookup_unit(surface).id, uid)
        for unknown in ("قدم", "xyz", "", "ماشین"):
            self.assertIsNone(units.lookup_unit(unknown))

    def test_find_units_prefers_the_longest_match(self):
        found = units.find_units(fa_text.words("۱۰ کیلومتر بر ساعت به مایل بر ساعت"))
        self.assertEqual([(s, e, u.id) for s, e, u in found], [(1, 4, "kmh"), (5, 8, "mph")])
        found = units.find_units(fa_text.words("۵ مایل دریایی"))
        self.assertEqual([(s, e, u.id) for s, e, u in found], [(1, 3, "nmi")])
        found = units.find_units(fa_text.words("10 km to mi"))
        self.assertEqual([(s, u.id) for s, _, u in found], [(1, "km"), (3, "mi")])
        self.assertEqual(units.find_units(["سلام", "دنیا"]), [])

    def test_match_keys_and_names(self):
        self.assertIn(fa_text.key("سانتی متر"), units.match_keys("cm"))
        self.assertIn("cm", units.match_keys("cm"))
        self.assertEqual(units.supported_names(3), [units.UNITS[u].display for u in list(units.UNITS)[:3]])
        self.assertEqual(len(units.supported_names()), len(units.UNITS))


# ============================================================================ textops
class TestTextOps(unittest.TestCase):
    def test_counting(self):
        self.assertEqual(textops.count_words("سلام دنیای زیبا"), 3.0)
        self.assertEqual(textops.count_words("  a   b \n c\t"), 3.0)
        self.assertEqual(textops.count_words(""), 0.0)
        self.assertEqual(textops.count_chars("سلام"), 4.0)
        self.assertEqual(textops.count_chars("a b"), 3.0)
        self.assertEqual(textops.count_chars_no_space("a b\tc\n d"), 4.0)

    def test_reverse_and_case(self):
        self.assertEqual(textops.reverse("abc"), "cba")
        self.assertEqual(textops.reverse(""), "")
        self.assertEqual(textops.reverse("سلام"), "مالس")
        self.assertEqual(textops.upper("aBc سلام"), "ABC سلام")
        self.assertEqual(textops.lower("ABC سلام"), "abc سلام")

    def test_spaces(self):
        self.assertEqual(textops.strip_spaces("  a   b  "), "a b")
        self.assertEqual(textops.strip_spaces("سلام \t دنیا\n"), "سلام دنیا")
        self.assertEqual(textops.remove_spaces(" a b\tc\n"), "abc")

    def test_digits(self):
        self.assertEqual(textops.to_fa_digits("a1b2"), "a۱b۲")
        self.assertEqual(textops.to_fa_digits("0123456789"), "۰۱۲۳۴۵۶۷۸۹")
        self.assertEqual(textops.to_en_digits("۱۲۳٤٥٦"), "123456")
        self.assertEqual(textops.to_en_digits("a۷b"), "a7b")

    def test_persian_orthography(self):
        self.assertEqual(textops.fix_arabic_letters("كتاب ي"), "کتاب ی")
        self.assertEqual(textops.fix_mi_prefix("می خواهم"), "می\u200cخواهم")
        self.assertEqual(textops.fix_mi_prefix("نمی دانم"), "نمی\u200cدانم")
        self.assertEqual(textops.fix_mi_prefix("دمی ببین"), "دمی ببین")        # «می» inside a word is left alone
        self.assertEqual(textops.fix_mi_prefix("امیر می"), "امیر می")           # nothing follows
        self.assertEqual(textops.fix_mi_prefix("می‌خواهم"), "می‌خواهم")         # already correct

    def test_chains_and_numeric_terminals(self):
        self.assertEqual(textops.apply_ops(["strip_spaces", "reverse"], "  ab  c "), "c ba")
        self.assertEqual(textops.apply_ops(["remove_spaces", "count_chars"], "a b c"), 3.0)
        self.assertEqual(textops.apply_ops(["to_en_digits", "remove_spaces"], "۱ ۲ ۳"), "123")
        self.assertEqual(textops.apply_ops([], "same"), "same")

    def test_operation_registry(self):
        self.assertEqual(set(textops.op_ids()), {
            "count_words", "count_chars", "count_chars_no_space", "reverse", "upper", "lower", "strip_spaces",
            "remove_spaces", "to_fa_digits", "to_en_digits", "fix_arabic_letters", "fix_mi_prefix"})
        self.assertEqual(textops.MAX_CHAIN, 3)
        for op in textops.op_ids():
            with self.subTest(op=op):
                self.assertIn(textops.op_kind(op), ("number", "text"))
                self.assertTrue(textops.op_label(op))
                self.assertGreaterEqual(len(textops.OPS[op][3]), 1)
        self.assertEqual({o for o in textops.op_ids() if textops.op_kind(o) == "number"},
                         {"count_words", "count_chars", "count_chars_no_space"})

    def test_text_input_validation(self):
        self.assertEqual(textops.text_input({"text": "سلام"}, "text"), "سلام")
        self.assertEqual(textops.text_input({"text": ""}, "text"), "")
        self.assertEqual(len(textops.text_input({"text": "x" * policy.MAX_INVOKE_TEXT_CHARS}, "text")),
                         policy.MAX_INVOKE_TEXT_CHARS)
        for bad in ({}, None, [], {"text": 5}, {"text": None}, {"text": b"x"}, {"text": "x" * (policy.MAX_INVOKE_TEXT_CHARS + 1)}):
            with self.subTest(bad=str(bad)[:30]), self.assertRaises(mathcore.MathFailure) as cm:
                textops.text_input(bad, "text")
            self.assertEqual(cm.exception.code, "bad_input")


# ============================================================================ helpers
class TestHelpers(unittest.TestCase):
    def test_helper_set_is_exactly_the_reviewed_pure_functions(self):
        expected = {"_sb_div", "_sb_power", "_sb_sqrt", "_sb_absolute", "_sb_minimum", "_sb_maximum", "_sb_floor",
                    "_sb_ceil", "_sb_round_to", "_sb_ln", "_sb_log10", "_sb_exp", "_sb_sin", "_sb_cos", "_sb_tan",
                    "_sb_finite", "_sb_number_input", "_sb_text_input"}
        expected |= {textops.HELPER_PREFIX + op for op in textops.op_ids()}
        self.assertEqual(set(helpers.HELPERS), expected)
        self.assertEqual(helpers.HELPER_NAMES, frozenset(expected))

    def test_every_helper_comes_from_mathcore_or_textops(self):
        for name, fn in helpers.HELPERS.items():
            with self.subTest(name=name):
                self.assertTrue(callable(fn))
                self.assertIn(fn.__module__, ("self_builder.mathcore", "self_builder.textops"))

    def test_every_expression_function_has_its_helper(self):
        for fname, (_lo, _hi, core_name) in expr.FUNCTIONS.items():
            self.assertIn("_sb_" + core_name, helpers.HELPERS, fname)


# ================================================================================ spec
class TestUnitConversionSpec(unittest.TestCase):
    def test_standard_conversion(self):
        s = km_mi()
        self.assertEqual(s["capability_id"], "unit_km_to_mi")
        self.assertEqual(s["kind"], "unit_conversion")
        self.assertEqual(s["title"], "تبدیل کیلومتر به مایل")
        self.assertAlmostEqual(s["scale"], 1000 / 1609.344, places=12)
        self.assertEqual(s["shift"], 0.0)
        self.assertTrue(s["standard"])
        self.assertEqual(s["reference"]["scale"], s["scale"])
        self.assertEqual(s["inputs"], [{"name": "value", "type": "number", "label": "مقدار (کیلومتر)"}])
        self.assertEqual(s["outputs"], [{"name": "value", "type": "number", "label": "مقدار (مایل)"}])
        self.assertEqual(s["permissions"], ["compute"])
        self.assertIn("0.621371192", s["description"])
        spec_mod.validate_spec(s)

    def test_temperature_conversion_has_a_shift(self):
        s = spec_mod.unit_conversion_spec(units.UNITS["c"], units.UNITS["f"])
        self.assertEqual((s["scale"], s["shift"]), (1.8, 32.0))
        self.assertEqual(s["capability_id"], "unit_c_to_f")

    def test_user_factor_that_deviates_is_marked_non_standard(self):
        s = km_mi(factor=0.6)
        self.assertEqual((s["scale"], s["shift"]), (0.6, 0.0))
        self.assertFalse(s["standard"])
        self.assertAlmostEqual(s["reference"]["scale"], 0.621371192237334, places=12)
        same = km_mi(factor=0.621371192237334)
        self.assertTrue(same["standard"])

    def test_custom_units_need_a_factor(self):
        with self.assertRaises(SpecError) as cm:
            spec_mod.unit_conversion_spec(None, units.UNITS["m"], from_name="قدم")
        self.assertEqual(cm.exception.code, "E_SPEC_FACTOR_REQUIRED")
        s = spec_mod.unit_conversion_spec(None, units.UNITS["m"], from_name="قدم", factor=0.75)
        self.assertTrue(s["capability_id"].startswith("unit_c_"))
        self.assertEqual(s["title"], "تبدیل قدم به متر")
        self.assertFalse(s["standard"])
        self.assertIsNone(s["reference"])
        spec_mod.validate_spec(s)

    def test_errors(self):
        def code(**kw):
            with self.assertRaises(SpecError) as cm:
                spec_mod.unit_conversion_spec(**kw)
            return cm.exception.code
        km, mi, kg, c, f = (units.UNITS[u] for u in ("km", "mi", "kg", "c", "f"))
        self.assertEqual(code(from_unit=km, to_unit=km), "E_SPEC_SAME_UNIT")
        self.assertEqual(code(from_unit=None, to_unit=None, from_name="قدم", to_name="قدم", factor=1), "E_SPEC_SAME_UNIT")
        self.assertEqual(code(from_unit=km, to_unit=kg), "E_SPEC_DIMENSION")
        self.assertEqual(code(from_unit=km, to_unit=mi, factor=0), "E_SPEC_FACTOR")
        self.assertEqual(code(from_unit=km, to_unit=mi, factor=1e13), "E_SPEC_FACTOR")
        self.assertEqual(code(from_unit=km, to_unit=mi, factor=1e-13), "E_SPEC_FACTOR")
        self.assertEqual(code(from_unit=km, to_unit=mi, factor=float("nan")), "E_SPEC_NUMBER")
        self.assertEqual(code(from_unit=km, to_unit=mi, factor=float("inf")), "E_SPEC_NUMBER")
        self.assertEqual(code(from_unit=km, to_unit=mi, factor=True), "E_SPEC_NUMBER")
        self.assertEqual(code(from_unit=c, to_unit=f, factor=2.0), "E_SPEC_FACTOR")
        self.assertEqual(code(from_unit=None, to_unit=mi, from_name="  "), "E_SPEC_UNIT")

    def test_factor_across_dimensions_is_allowed_when_given(self):
        s = spec_mod.unit_conversion_spec(units.UNITS["km"], units.UNITS["kg"], factor=2.0)
        self.assertEqual(s["scale"], 2.0)

    def test_examples_are_cleaned_and_limited(self):
        s = km_mi(examples=[{"inputs": {"value": 10}, "expected": 6.2, "tolerance": 0.1}])
        self.assertEqual(s["examples"], [{"inputs": {"value": 10.0}, "expected": 6.2, "tolerance": 0.1}])
        for bad in ([{"inputs": {"value": 10}}], [{"expected": 1}], ["x"], [{"inputs": {"value": "a"}, "expected": 1}],
                    [{"inputs": {"value": 1}, "expected": float("nan")}],
                    [{"inputs": {"value": i}, "expected": i} for i in range(13)]):
            with self.subTest(bad=str(bad)[:40]), self.assertRaises(SpecError) as cm:
                km_mi(examples=bad)
            self.assertIn(cm.exception.code, ("E_SPEC_EXAMPLE", "E_SPEC_NUMBER"))


class TestFormulaSpec(unittest.TestCase):
    def test_basic_formula(self):
        s = spec_mod.formula_spec("مساحت دایره", "pi * r ** 2")
        self.assertEqual(s["kind"], "formula")
        self.assertTrue(s["capability_id"].startswith("formula_"))
        self.assertEqual(len(s["capability_id"]), len("formula_") + 10)
        self.assertEqual([v["name"] for v in s["variables"]], ["r"])
        self.assertEqual(s["tree"], expr.parse("pi * r ** 2"))
        self.assertEqual(s["inputs"], [{"name": "r", "type": "number", "label": "r"}])
        self.assertEqual(s["result_label"], "مساحت دایره")
        self.assertIn("helper:_sb_power", s["dependencies"])
        self.assertIn("helper:_sb_finite", s["dependencies"])
        self.assertEqual(s["dependencies"], sorted(set(s["dependencies"])))
        spec_mod.validate_spec(s)

    def test_labels_aliases_and_order(self):
        s = spec_mod.formula_spec("BMI", "w / (h * h)", variable_labels={"w": "وزن", "h": "قد"})
        self.assertEqual([(v["name"], v["label"]) for v in s["variables"]], [("w", "وزن"), ("h", "قد")])
        self.assertIn(fa_text.key("وزن"), s["variables"][0]["aliases"])
        self.assertIn("w", s["variables"][0]["aliases"])
        s2 = spec_mod.formula_spec("BMI", "w / (h * h)", variable_order=["h", "w"])
        self.assertEqual([v["name"] for v in s2["variables"]], ["h", "w"])
        self.assertEqual(spec_mod.input_names(s2), ["h", "w"])

    def test_positional_examples_follow_the_input_order(self):
        s = spec_mod.formula_spec("BMI", "w / (h * h)", examples=[{"positional": [70, 1.75], "expected": 22.857}])
        self.assertEqual(s["examples"][0]["inputs"], {"w": 70.0, "h": 1.75})
        with self.assertRaises(SpecError) as cm:
            spec_mod.formula_spec("BMI", "w / (h * h)", examples=[{"positional": [70], "expected": 1}])
        self.assertEqual(cm.exception.code, "E_SPEC_EXAMPLE")

    def test_errors(self):
        def code(*a, **kw):
            with self.assertRaises(SelfBuilderError) as cm:
                spec_mod.formula_spec(*a, **kw)
            return cm.exception.code
        self.assertEqual(code("", "a + 1"), "E_SPEC_TITLE")
        self.assertEqual(code("   ", "a + 1"), "E_SPEC_TITLE")
        self.assertEqual(code("ن" * 61, "a + 1"), "E_SPEC_TITLE")
        self.assertEqual(code("ثابت", "2 + 3"), "E_SPEC_NO_VARIABLES")
        names = " + ".join(f"v{i}" for i in range(9))
        self.assertEqual(code("خیلی زیاد", names), "E_SPEC_TOO_MANY_VARIABLES")
        self.assertEqual(code("ترتیب", "a + b", variable_order=["a", "c"]), "E_SPEC_VARIABLES")
        self.assertEqual(code("ترتیب", "a + b", variable_order=["a"]), "E_SPEC_VARIABLES")
        self.assertEqual(code("بد", "a +"), "E_EXPR_SYNTAX_END")
        self.assertEqual(code("بد", "وزن + 1"), "E_EXPR_NON_ASCII_NAME")

    def test_eight_variables_are_the_maximum(self):
        spec_mod.formula_spec("هشت متغیر", " + ".join(f"v{i}" for i in range(8)))


class TestTextToolSpec(unittest.TestCase):
    def test_basic(self):
        s = spec_mod.text_tool_spec(["strip_spaces", "reverse"])
        self.assertEqual(s["capability_id"], "text_strip_spaces_reverse")
        self.assertEqual(s["title"], "حذف فاصله‌های اضافی و معکوس کردن متن")
        self.assertEqual(s["output_kind"], "text")
        self.assertEqual(s["outputs"][0]["type"], "text")
        self.assertEqual(s["inputs"], [{"name": "text", "type": "text", "label": "متن"}])
        self.assertTrue(s["triggers"])
        spec_mod.validate_spec(s)

    def test_numeric_terminal(self):
        s = spec_mod.text_tool_spec(["count_words"])
        self.assertEqual(s["output_kind"], "number")
        self.assertEqual(s["outputs"][0]["type"], "number")
        self.assertEqual(s["capability_id"], "text_count_words")

    def test_long_ids_fall_back_to_a_short_hash(self):
        s = spec_mod.text_tool_spec(["fix_arabic_letters", "fix_mi_prefix", "remove_spaces"])
        self.assertRegex(s["capability_id"], r"^text_[0-9a-f]{12}$")
        self.assertTrue(policy.is_valid_capability_id(s["capability_id"]))

    def test_errors(self):
        for ops in ([], None, ["reverse"] * 4, ["nope"], ["count_words", "reverse"], ["reverse", "count_words", "count_chars"]):
            with self.subTest(ops=ops), self.assertRaises(SpecError) as cm:
                spec_mod.text_tool_spec(ops)
            self.assertEqual(cm.exception.code, "E_SPEC_OPS")
        spec_mod.text_tool_spec(["reverse", "reverse", "count_chars"])          # a number only as the last step


class TestSpecValidationAndFingerprint(unittest.TestCase):
    def test_tampered_specs_are_rejected(self):
        base = spec_mod.formula_spec("مساحت", "pi * r ** 2")
        def mutate(**changes):
            s = dict(base)
            s.update(changes)
            return s
        tests = [
            (mutate(kind="game"), PolicyViolation, "E_POLICY_ARCHETYPE"),
            (mutate(permissions=["compute", "network"]), PolicyViolation, "E_POLICY_PERMISSION"),
            (mutate(capability_id="../evil"), PolicyViolation, "E_POLICY_ID"),
            (mutate(schema=99), SpecError, "E_SPEC_SCHEMA"),
            (mutate(tree=["num", 1.0]), SpecError, "E_SPEC_TREE"),
            (mutate(variables=[{"name": "q", "label": "q", "aliases": []}]), SpecError, "E_SPEC_VARIABLES"),
            (mutate(expression="pi * r ** 2 +"), ExprError, "E_EXPR_SYNTAX_END"),
        ]
        for bad, cls, code in tests:
            with self.subTest(code=code), self.assertRaises(cls) as cm:
                spec_mod.validate_spec(bad)
            self.assertEqual(cm.exception.code, code)
        for field in ("kind", "capability_id", "title", "inputs", "permissions"):
            with self.subTest(missing=field), self.assertRaises(SpecError) as cm:
                spec_mod.validate_spec({k: v for k, v in base.items() if k != field})
            self.assertEqual(cm.exception.code, "E_SPEC_FIELD")
        with self.assertRaises(SpecError):
            spec_mod.validate_spec("not a spec")
        unit = km_mi()
        with self.assertRaises(SpecError) as cm:
            spec_mod.validate_spec(dict(unit, scale=0.0))
        self.assertEqual(cm.exception.code, "E_SPEC_FACTOR")
        text = spec_mod.text_tool_spec(["reverse"])
        with self.assertRaises(SpecError) as cm:
            spec_mod.validate_spec(dict(text, ops=["count_words", "reverse"]))
        self.assertEqual(cm.exception.code, "E_SPEC_OPS")

    def test_fingerprint_covers_behaviour_only(self):
        a = km_mi()
        b = km_mi(title="مبدل من", examples=[{"inputs": {"value": 1}, "expected": 0.62, "tolerance": 0.01}])
        self.assertEqual(spec_mod.spec_fingerprint(a), spec_mod.spec_fingerprint(b))
        self.assertNotEqual(spec_mod.spec_fingerprint(a), spec_mod.spec_fingerprint(km_mi(factor=0.6)))
        self.assertNotEqual(spec_mod.spec_fingerprint(a),
                            spec_mod.spec_fingerprint(spec_mod.unit_conversion_spec(units.UNITS["mi"], units.UNITS["km"])))
        f1 = spec_mod.formula_spec("الف", "a * 2")
        f2 = spec_mod.formula_spec("ب", "a * 2")
        f3 = spec_mod.formula_spec("الف", "a * 3")
        self.assertEqual(spec_mod.spec_fingerprint(f1), spec_mod.spec_fingerprint(f2))
        self.assertNotEqual(spec_mod.spec_fingerprint(f1), spec_mod.spec_fingerprint(f3))
        t1 = spec_mod.text_tool_spec(["strip_spaces", "reverse"])
        t2 = spec_mod.text_tool_spec(["reverse", "strip_spaces"])
        self.assertNotEqual(spec_mod.spec_fingerprint(t1), spec_mod.spec_fingerprint(t2))
        self.assertRegex(spec_mod.spec_fingerprint(t1), r"^[0-9a-f]{64}$")

    def test_canonical_json_is_order_independent(self):
        self.assertEqual(spec_mod.canonical_json({"b": 1, "a": [2, {"d": 1, "c": 2}]}),
                         spec_mod.canonical_json({"a": [2, {"c": 2, "d": 1}], "b": 1}))
        self.assertEqual(spec_mod.sha256_text("abc"),
                         "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")


# ============================================================================ templates
class TestTemplates(unittest.TestCase):
    SPECS = None

    @classmethod
    def setUpClass(cls):
        cls.SPECS = {
            "unit": km_mi(),
            "formula": spec_mod.formula_spec("مساحت دایره", "pi * r ** 2"),
            "formula2": spec_mod.formula_spec("BMI", "w / (h * h)", variable_labels={"w": "وزن", "h": "قد"}),
            "text": spec_mod.text_tool_spec(["strip_spaces", "count_words"]),
        }

    def test_generation_is_deterministic(self):
        for name, spec in self.SPECS.items():
            with self.subTest(name=name):
                self.assertEqual(templates.generate_module(spec, 2), templates.generate_module(spec, 2))
        a = templates.generate_module(self.SPECS["unit"], 1).splitlines()
        b = templates.generate_module(self.SPECS["unit"], 2).splitlines()
        self.assertEqual([i for i, (x, y) in enumerate(zip(a, b)) if x != y], [3])        # only the version line

    def test_unit_module_text(self):
        src = templates.generate_module(self.SPECS["unit"], 3)
        self.assertIn("CAPABILITY_ID = 'unit_km_to_mi'", src)
        self.assertIn("CAPABILITY_VERSION = 3", src)
        self.assertIn("CAPABILITY_KIND = 'unit_conversion'", src)
        self.assertIn("SCALE = " + repr(float(Fraction(1000) / Fraction("1609.344"))), src)
        self.assertIn("SHIFT = 0.0", src)
        self.assertIn("def convert(x_value):", src)
        self.assertIn("def run(inputs):", src)
        self.assertTrue(src.startswith("# Generated by the Self-Builder"))
        self.assertTrue(src.endswith("\n"))
        self.assertTrue(src.isascii())

    def test_generated_modules_have_no_imports_loops_attributes_or_strings_processing(self):
        for name, spec in self.SPECS.items():
            tree = ast.parse(templates.generate_module(spec, 1))
            kinds = {type(n).__name__ for n in ast.walk(tree)}
            with self.subTest(name=name):
                for forbidden in ("Import", "ImportFrom", "For", "While", "Attribute", "Subscript", "Lambda", "ListComp",
                                  "GeneratorExp", "Try", "With", "ClassDef", "Global", "IfExp", "JoinedStr"):
                    self.assertNotIn(forbidden, kinds)
                self.assertEqual([n.name for n in tree.body if isinstance(n, ast.FunctionDef)][-1], "run")

    def test_every_generated_module_passes_the_validator(self):
        for name, spec in self.SPECS.items():
            src = templates.generate_module(spec, 4)
            report = validator.check_source(src, spec["kind"], expected_id=spec["capability_id"], expected_version=4)
            with self.subTest(name=name):
                self.assertTrue(report.ok, report.violations)

    def test_module_for_an_invalid_spec_is_refused(self):
        with self.assertRaises(SelfBuilderError):
            templates.generate_module(dict(self.SPECS["unit"], kind="game"), 1)
        with self.assertRaises(SelfBuilderError):
            templates.generate_module(dict(self.SPECS["unit"], scale=0.0), 1)

    def test_conversion_suite_expectations_come_from_exact_arithmetic(self):
        suite = templates.generate_test_suite(self.SPECS["unit"], 1)
        by_name = {c["name"]: c for c in suite["cases"]}
        self.assertEqual(suite["kind"], "unit_conversion")
        self.assertEqual(suite["version"], 1)
        self.assertEqual(suite["capability_id"], "unit_km_to_mi")
        exact = Fraction(10) * Fraction(1000) / Fraction("1609.344")
        self.assertAlmostEqual(by_name["auto_4"]["inputs"]["value"], 10.0)
        self.assertAlmostEqual(by_name["auto_4"]["expect"]["value"], float(exact), places=10)
        self.assertEqual(by_name["bad_missing"]["expect"], {"error": "bad_input"})
        self.assertEqual(by_name["bad_text"]["expect"], {"error": "bad_input"})
        self.assertEqual(by_name["bad_bool"]["expect"], {"error": "bad_input"})
        self.assertEqual(len({c["name"] for c in suite["cases"]}), len(suite["cases"]))
        self.assertLessEqual(len(suite["cases"]), policy.MAX_TEST_CASES)

    def test_formula_suite_matches_hand_computed_values(self):
        suite = templates.generate_test_suite(self.SPECS["formula"], 1)
        for case in suite["cases"]:
            if "value" in case["expect"] and case["name"].startswith("auto_"):
                r = case["inputs"]["r"]
                self.assertAlmostEqual(case["expect"]["value"], math.pi * r ** 2, delta=1e-9 * max(1.0, abs(math.pi * r * r)))
        # the grid always contains the all-zero point and the negative values
        self.assertTrue(any(c["inputs"] == {"r": 0.0} and c["expect"]["value"] == 0.0 for c in suite["cases"]))
        self.assertTrue(any(c["inputs"]["r"] < 0 for c in suite["cases"] if "r" in c["inputs"]))
        # a division-by-zero case records the expected ERROR instead of a value
        div = templates.generate_test_suite(spec_mod.formula_spec("نسبت", "a / b"), 1)
        errors_ = [c for c in div["cases"] if c["expect"] == {"error": "division_by_zero"}]
        self.assertTrue(errors_)
        for c in errors_:
            self.assertEqual(c["inputs"]["b"], 0.0)

    def test_text_suite_values(self):
        suite = templates.generate_test_suite(self.SPECS["text"], 1)
        by_name = {c["name"]: c for c in suite["cases"]}
        self.assertEqual(by_name["auto_1"]["inputs"], {"text": "سلام دنیا"})
        self.assertEqual(by_name["auto_1"]["expect"]["value"], 2.0)
        self.assertEqual(by_name["auto_0"]["expect"]["value"], 0.0)
        self.assertEqual(by_name["bad_too_long"]["expect"], {"error": "bad_input"})

    def test_user_examples_become_cases_outside_the_cap(self):
        s = km_mi(examples=[{"inputs": {"value": 10}, "expected": 6.2137, "tolerance": 0.001}])
        suite = templates.generate_test_suite(s, 1)
        ex = [c for c in suite["cases"] if c["name"] == "example_0"]
        self.assertEqual(len(ex), 1)
        self.assertEqual(ex[0]["source"], "user")
        self.assertEqual(ex[0]["expect"], {"value": 6.2137, "abs_tol": 0.001, "rel_tol": 0.0})

    def test_check_expectation(self):
        self.assertEqual(templates.check_expectation({"error": "bad_input"}, actual_error="bad_input")[0], True)
        self.assertEqual(templates.check_expectation({"error": "bad_input"}, actual_value=1.0)[0], False)
        self.assertEqual(templates.check_expectation({"error": "bad_input"}, actual_error="domain")[0], False)
        self.assertEqual(templates.check_expectation({"value": 1.0}, actual_error="domain")[0], False)
        self.assertEqual(templates.check_expectation({"value": 1.0, "abs_tol": 1e-9}, actual_value=1.0 + 1e-10)[0], True)
        self.assertEqual(templates.check_expectation({"value": 1.0, "abs_tol": 1e-9}, actual_value=1.001)[0], False)
        self.assertEqual(templates.check_expectation({"value": 100.0, "rel_tol": 1e-6}, actual_value=100.00005)[0], True)
        self.assertEqual(templates.check_expectation({"value": "abc"}, actual_value="abc")[0], True)
        self.assertEqual(templates.check_expectation({"value": "abc"}, actual_value="abd")[0], False)
        self.assertEqual(templates.check_expectation({"value": 1.0}, actual_value=True)[0], False)
        self.assertEqual(templates.check_expectation({"value": 1.0}, actual_value="1")[0], False)
        self.assertEqual(templates.check_expectation({"value": 1.0, "abs_tol": 1.0}, actual_value=float("nan"))[0], False)


# ============================================================================ validator
class TestValidator(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec = km_mi()
        cls.src = templates.generate_module(cls.spec, 1)

    def mutate(self, old, new):
        self.assertIn(old, self.src)
        return self.src.replace(old, new, 1)

    def codes(self, source, kind="unit_conversion", **kw):
        return {v["code"] for v in validator.check_source(source, kind, **kw).violations}

    def test_valid_modules_pass_and_report_statistics(self):
        report = validator.check_source(self.src, "unit_conversion", expected_id="unit_km_to_mi", expected_version=1)
        self.assertTrue(report.ok)
        self.assertEqual(report.stats["functions"], ["convert", "run"])
        self.assertEqual(report.stats["metadata"], ["CAPABILITY_ID", "CAPABILITY_VERSION", "CAPABILITY_KIND", "SCALE", "SHIFT"])
        self.assertIn("_sb_finite", report.stats["helpers_used"])
        self.assertLess(report.stats["nodes"], policy.MAX_AST_NODES)
        self.assertEqual(report.to_dict()["ok"], True)
        validator.require_valid(self.src, "unit_conversion")

    def test_require_valid_raises_with_the_violations(self):
        with self.assertRaises(ValidationError) as cm:
            validator.require_valid("import os\n" + self.src, "unit_conversion")
        self.assertEqual(cm.exception.code, "E_VALIDATION")
        self.assertTrue(cm.exception.info["violations"])

    def test_forbidden_expressions_in_the_core_function(self):
        body = "return _sb_finite(((x_value * SCALE) + SHIFT))"
        cases = {
            "attribute access": ("return x_value.__class__", "V_NODE"),
            "open": ("return open('/etc/passwd')", "V_CALL"),
            "eval": ("return eval('1')", "V_CALL"),
            "exec": ("return exec('1')", "V_CALL"),
            "compile": ("return compile('1', 'x', 'eval')", "V_CALL"),
            "getattr": ("return getattr(x_value, 'real')", "V_CALL"),
            "globals": ("return globals()", "V_CALL"),
            "dunder import": ("return __import__('os')", "V_CALL"),
            "own function": ("return convert(x_value)", "V_CALL"),
            "lambda": ("return (lambda: 1)", "V_NODE"),
            "list comprehension": ("return [i for i in x_value]", "V_NODE"),
            "generator": ("return (i for i in x_value)", "V_NODE"),
            "conditional": ("return x_value if x_value else 0", "V_NODE"),
            "subscript": ("return x_value[0]", "V_NODE"),
            "list display": ("return [x_value]", "V_NODE"),
            "tuple display": ("return (x_value, 1)", "V_NODE"),
            "set display": ("return {x_value}", "V_NODE"),
            "f-string": ("return f'{x_value}'", "V_NODE"),
            "comparison": ("return x_value < 1", "V_NODE"),
            "boolean op": ("return x_value and 1", "V_NODE"),
            "walrus": ("return (y := x_value)", "V_NODE"),
            "await": ("return await x_value", "V_NODE"),
            "yield": ("return (yield)", "V_NODE"),
            "power operator": ("return x_value ** 2", "V_OPERATOR"),
            "true division": ("return x_value / 2", "V_OPERATOR"),
            "floor division": ("return x_value // 2", "V_OPERATOR"),
            "modulo": ("return x_value % 2", "V_OPERATOR"),
            "shift": ("return x_value << 2", "V_OPERATOR"),
            "not": ("return not x_value", "V_OPERATOR"),
            "invert": ("return ~x_value", "V_OPERATOR"),
            "string repetition": ("return 'a' * 100000000", "V_CONSTANT"),
            "none arithmetic": ("return x_value + None", "V_CONSTANT"),
            "bool arithmetic": ("return x_value * True", "V_CONSTANT"),
            "unknown name": ("return secret", "V_NAME"),
            "dunder name": ("return __builtins__", "V_NAME"),
            "keyword argument": ("return _sb_finite(x_value=1.0)", "V_CALL"),
            "starred argument": ("return _sb_finite(*x_value)", "V_CALL"),
            "method call": ("return x_value.real()", "V_CALL"),
            "call of a call": ("return _sb_finite(1.0)(2.0)", "V_CALL"),
            "non-ASCII string": ("return 'سلام'", "V_ASCII"),
            "big string": ("return '" + "a" * 201 + "'", "V_CONSTANT"),
            "dict in core": ("return {'value': 1.0}", "V_NODE"),
            "bytes": ("return b'abc'", "V_CONSTANT"),
            "complex": ("return 1j", "V_CONSTANT"),
            "ellipsis": ("return ...", "V_CONSTANT"),
        }
        for name, (new_body, code) in cases.items():
            with self.subTest(name=name):
                self.assertIn(code, self.codes(self.mutate(body, new_body)))

    def test_forbidden_function_bodies(self):
        sig = "def convert(x_value):\n    return _sb_finite(((x_value * SCALE) + SHIFT))\n"
        bodies = {
            "for loop": "def convert(x_value):\n    for i in x_value:\n        pass\n    return 1.0\n",
            "while loop": "def convert(x_value):\n    while x_value:\n        pass\n    return 1.0\n",
            "try": "def convert(x_value):\n    try:\n        return 1.0\n    except Exception:\n        return 2.0\n",
            "with": "def convert(x_value):\n    with x_value:\n        pass\n    return 1.0\n",
            "assignment": "def convert(x_value):\n    y = x_value\n    return y\n",
            "augmented assignment": "def convert(x_value):\n    x_value += 1.0\n    return x_value\n",
            "nested def": "def convert(x_value):\n    def inner():\n        return 1.0\n    return inner()\n",
            "nested class": "def convert(x_value):\n    class C:\n        pass\n    return 1.0\n",
            "global": "def convert(x_value):\n    global SCALE\n    return 1.0\n",
            "import in body": "def convert(x_value):\n    import os\n    return 1.0\n",
            "assert": "def convert(x_value):\n    assert x_value\n    return 1.0\n",
            "raise": "def convert(x_value):\n    raise ValueError()\n",
            "delete": "def convert(x_value):\n    del x_value\n    return 1.0\n",
            "empty return": "def convert(x_value):\n    return\n",
            "no return": "def convert(x_value):\n    pass\n",
            "two returns": "def convert(x_value):\n    return 1.0\n    return 2.0\n",
        }
        for name, replacement in bodies.items():
            with self.subTest(name=name):
                self.assertIn("V_FUNCTION", self.codes(self.mutate(sig, replacement)))

    def test_forbidden_signatures(self):
        sigs = {
            "default argument": "def convert(x_value=1.0):",
            "varargs": "def convert(*x_value):",
            "kwargs": "def convert(x_value, **x_extra):",
            "keyword only": "def convert(x_value, *, x_k):",
            "positional only": "def convert(x_value, /):",
            "annotation": "def convert(x_value: float):",
            "return annotation": "def convert(x_value) -> float:",
            "decorator": "@staticmethod\ndef convert(x_value):",
            "wrong parameter prefix": "def convert(value):",
            "dunder parameter": "def convert(__x):",
            "no parameters": "def convert():",
        }
        for name, sig in sigs.items():
            with self.subTest(name=name):
                self.assertIn("V_FUNCTION", self.codes(self.mutate("def convert(x_value):", sig)))
        for sig in ("def run(inputs, extra):", "def run(data):", "def run(*inputs):", "def run():"):
            with self.subTest(sig=sig):
                self.assertIn("V_FUNCTION", self.codes(self.mutate("def run(inputs):", sig)))

    def test_forbidden_top_level_structure(self):
        cases = {
            "import": ("import os\n" + self.src, "V_STATEMENT"),
            "from import": ("from os import path\n" + self.src, "V_STATEMENT"),
            "call at top level": (self.src + "\nrun({})\n", "V_STATEMENT"),
            "extra assignment": (self.src.replace("SHIFT = 0.0", "SHIFT = 0.0\nEXTRA = 1"), "V_ASSIGN"),
            "assigned twice": (self.src.replace("SHIFT = 0.0", "SHIFT = 0.0\nSHIFT = 1.0"), "V_ASSIGN"),
            "tuple assignment": (self.src.replace("SHIFT = 0.0", "SHIFT, X = 0.0, 1.0"), "V_ASSIGN"),
            "metadata from a call": (self.src.replace("SHIFT = 0.0", "SHIFT = float('1')"), "V_LITERAL"),
            "metadata from a name": (self.src.replace("SHIFT = 0.0", "SHIFT = SCALE"), "V_LITERAL"),
            "infinite literal": (self.src.replace("SHIFT = 0.0", "SHIFT = 1e999"), "V_CONSTANT"),
            "huge integer": (self.src.replace("SHIFT = 0.0", "SHIFT = 10000000000000000"), "V_CONSTANT"),
            "extra function": (self.src + "\n\ndef evil():\n    return 1.0\n", "V_FUNCTION"),
            "extra class": (self.src + "\n\nclass C:\n    pass\n", "V_STATEMENT"),
            "async function": (self.src + "\n\nasync def a():\n    return 1.0\n", "V_STATEMENT"),
            "function twice": (self.src + "\n\ndef run(inputs):\n    return {'value': 1.0}\n", "V_FUNCTION"),
            "swapped metadata": (self.src.replace("SCALE = 0.621371192237334\nSHIFT = 0.0", "SHIFT = 0.0\nSCALE = 0.621371192237334"),
                                 "V_STRUCTURE"),
            "functions out of order": ("\n".join(self.src.split("\n\n\n")[0:1]) + "\n\n\n" + self.src.split("\n\n\n")[2]
                                       + "\n\n\n" + self.src.split("\n\n\n")[1], "V_STRUCTURE"),
            "missing metadata": (self.src.replace("SHIFT = 0.0\n", ""), "V_STRUCTURE"),
            "docstring statement": (self.src.replace("def convert", '"doc"\ndef convert', 1), "V_STATEMENT"),
        }
        for name, (source, code) in cases.items():
            with self.subTest(name=name):
                self.assertIn(code, self.codes(source))

    def test_metadata_must_match_the_registry(self):
        self.assertIn("V_STRUCTURE", self.codes(self.mutate("CAPABILITY_KIND = 'unit_conversion'", "CAPABILITY_KIND = 'formula'")))
        self.assertIn("V_STRUCTURE", self.codes(self.src, expected_id="unit_other_one"))
        self.assertIn("V_STRUCTURE", self.codes(self.src, expected_version=2))
        self.assertEqual(self.codes(self.src, expected_id="unit_km_to_mi", expected_version=1), set())

    def test_run_must_return_a_value_dictionary(self):
        ret = '    return {"value": convert(_sb_number_input(inputs, "value"))}'
        for name, new in {"other key": '    return {"other": 1.0}', "two keys": '    return {"value": 1.0, "x": 2.0}',
                          "empty dict": "    return {}", "nested dict": '    return {"value": {"value": 1.0}}',
                          "list": "    return [1.0]", "number": "    return 1.0"}.items():
            with self.subTest(name=name):
                self.assertTrue(self.codes(self.mutate(ret, new)))

    def test_limits(self):
        self.assertIn("V_SIZE", self.codes(self.src + "# " + "x" * policy.MAX_SOURCE_BYTES + "\n"))
        self.assertIn("V_ASCII", self.codes(self.src + "# سلام\n"))
        chain = "x_value" + " + 1.0" * 700
        self.assertIn("V_SIZE", self.codes(self.mutate("return _sb_finite(((x_value * SCALE) + SHIFT))", f"return {chain}")))
        self.assertIn("V_SYNTAX", self.codes(self.mutate("return _sb_finite(((x_value * SCALE) + SHIFT))",
                                                         "return " + "(" * 400 + "x_value" + ")" * 400)))
        self.assertIn("V_SYNTAX", self.codes("def convert(:\n"))
        self.assertIn("V_TYPE", self.codes(b"CAPABILITY_ID = 'x'"))
        self.assertIn("V_TYPE", self.codes(None))
        self.assertIn("V_KIND", self.codes(self.src, kind="game"))
        self.assertIn("V_LITERAL", self.codes(self.mutate("SHIFT = 0.0", "SHIFT = (" + ", ".join(["1.0"] * 25) + ")")))

    def test_formula_and_text_modules_have_their_own_shape(self):
        formula = templates.generate_module(spec_mod.formula_spec("مساحت", "pi * r ** 2"), 1)
        self.assertTrue(validator.check_source(formula, "formula").ok)
        self.assertIn("V_STRUCTURE", self.codes(formula, kind="unit_conversion"))
        self.assertIn("V_FUNCTION", self.codes(formula.replace("def compute(x_r):", "def compute(r):"), kind="formula"))
        text = templates.generate_module(spec_mod.text_tool_spec(["reverse"]), 1)
        self.assertTrue(validator.check_source(text, "text_tool").ok)
        self.assertIn("V_CALL", self.codes(text.replace("_sb_text_reverse(x_text)", "x_text.upper()"), kind="text_tool"))
        self.assertIn("V_CALL", self.codes(text.replace("_sb_text_reverse(x_text)", "_sb_text_missing(x_text)"), kind="text_tool"))


# ============================================================================= sandbox
class TestSandbox(unittest.TestCase):
    def setUp(self):
        self.root = make_root()
        self.addCleanup(shutil.rmtree, self.root, True)

    def install(self, spec, version=1, source=None, subdir=policy.SUBDIR_MODULES):
        source = source if source is not None else templates.generate_module(spec, version)
        name = f"{spec['capability_id']}_v{version}.py"
        write_file(self.root, subdir, name, source)
        return name, sandbox.sha256_bytes(source.encode("utf-8"))

    def load(self, spec, version=1, **kw):
        name, digest = self.install(spec, version, **{k: v for k, v in kw.items() if k in ("source", "subdir")})
        return sandbox.load_module(self.root, kw.get("subdir", policy.SUBDIR_MODULES), name, spec["kind"],
                                   spec["capability_id"], version, expected_sha256=kw.get("sha", digest))

    def test_load_and_run_each_archetype(self):
        loaded = self.load(km_mi())
        self.assertEqual(loaded.kind, "unit_conversion")
        out = loaded.run({"value": 10})
        self.assertTrue(out["ok"])
        self.assertAlmostEqual(out["value"], 6.21371192237334, places=10)
        loaded = self.load(spec_mod.formula_spec("BMI", "w / (h * h)"))
        self.assertAlmostEqual(loaded.run({"w": 70, "h": 1.75})["value"], 22.857142857142858, places=12)
        loaded = self.load(spec_mod.text_tool_spec(["strip_spaces", "count_words"]))
        self.assertEqual(loaded.run({"text": "  سلام   دنیا "}), {"ok": True, "value": 2.0})
        loaded = self.load(spec_mod.text_tool_spec(["reverse"]))
        self.assertEqual(loaded.run({"text": "abc"}), {"ok": True, "value": "cba"})

    def test_calls_never_raise_and_use_stable_error_codes(self):
        loaded = self.load(km_mi())
        for inputs, code in (({}, "bad_input"), ({"value": "abc"}, "bad_input"), ({"value": True}, "bad_input"),
                             ({"value": None}, "bad_input"), ({"value": float("nan")}, "overflow"),
                             ({"value": 1e299}, None), ({"value": 1e308}, "overflow"), ({"value": 1e309}, "overflow"), (None, "bad_input"), ("x", "bad_input")):
            with self.subTest(inputs=str(inputs)):
                out = loaded.run(inputs)
                if code is None:
                    self.assertTrue(out["ok"])
                else:
                    self.assertEqual((out["ok"], out["error"]), (False, code))
        formula = self.load(spec_mod.formula_spec("نسبت", "1 / x"))
        self.assertEqual(formula.run({"x": 0})["error"], "division_by_zero")
        self.assertEqual(self.load(spec_mod.formula_spec("ریشه", "sqrt(x)")).run({"x": -4})["error"], "domain")
        self.assertEqual(self.load(spec_mod.formula_spec("توان", "2 ** x")).run({"x": 100})["error"], "bad_power")
        self.assertEqual(self.load(spec_mod.formula_spec("بزرگ", "x * x * x")).run({"x": 1e150})["error"], "overflow")
        text = self.load(spec_mod.text_tool_spec(["reverse"]))
        self.assertEqual(text.run({"text": 5})["error"], "bad_input")
        self.assertEqual(text.run({"text": "x" * (policy.MAX_INVOKE_TEXT_CHARS + 1)})["error"], "bad_input")

    def test_results_that_are_not_plain_numbers_or_text_are_refused(self):
        spec = km_mi()
        template = templates.generate_module(spec, 1)
        for ret, code in (('{"value": True}', "bad_output"), ('{"value": None}', "bad_output")):
            src = template.replace('{"value": convert(_sb_number_input(inputs, "value"))}', ret)
            loaded = self.load(spec, source=src)
            with self.subTest(ret=ret):
                out = loaded.run({"value": 1})
                self.assertEqual((out["ok"], out["error"]), (False, code))
        # a result dictionary with a second key never gets that far: the validator refuses the source
        src = template.replace('{"value": convert(_sb_number_input(inputs, "value"))}', '{"value": 1.0, "extra": 2.0}')
        with self.assertRaises(ValidationError):
            self.load(spec, source=src)

    def test_runtime_exceptions_of_valid_code_are_caught(self):
        spec = km_mi()
        src = templates.generate_module(spec, 1).replace(
            '{"value": convert(_sb_number_input(inputs, "value"))}', '{"value": convert(inputs)}')
        out = self.load(spec, source=src).run({"value": 1})
        self.assertEqual((out["ok"], out["error"], out["detail"]), (False, "exception", "TypeError"))

    def test_slow_calls_report_timeout(self):
        loaded = self.load(km_mi())
        with mock.patch.object(sandbox.time, "perf_counter", side_effect=[0.0, 5.0]):
            out = loaded.run({"value": 1})
        self.assertEqual((out["ok"], out["error"]), (False, "timeout"))

    def test_the_module_namespace_is_closed(self):
        loaded = self.load(km_mi())
        ns = loaded._module.__dict__
        self.assertEqual(ns["__builtins__"], {})
        self.assertNotIn("sb_cap_unit_km_to_mi_v1", sys.modules)
        user_names = {k for k in ns if not k.startswith("__") and not k.startswith("_sb_")}
        self.assertEqual(user_names, {"CAPABILITY_ID", "CAPABILITY_VERSION", "CAPABILITY_KIND", "SCALE", "SHIFT", "convert", "run"})
        self.assertNotIn("open", ns)
        self.assertNotIn("os", ns)

    def test_modules_do_not_share_state(self):
        a = self.load(km_mi())
        b = self.load(spec_mod.unit_conversion_spec(units.UNITS["m"], units.UNITS["ft"]))
        self.assertIsNot(a._module, b._module)
        self.assertIsNot(a._module.__dict__, b._module.__dict__)
        a._module.SCALE = 99.0
        self.assertAlmostEqual(b.run({"value": 1})["value"], 3.280839895013123, places=9)

    def test_loading_twice_gives_independent_equal_modules(self):
        spec = km_mi()
        first, second = self.load(spec), self.load(spec)
        self.assertIsNot(first, second)
        self.assertEqual(first.run({"value": 5}), second.run({"value": 5}))
        self.assertEqual(first.sha256, second.sha256)

    def test_hash_directory_and_file_checks(self):
        spec = km_mi()
        name, digest = self.install(spec)
        with self.assertRaises(SandboxError) as cm:
            sandbox.load_module(self.root, "modules", name, spec["kind"], spec["capability_id"], 1,
                                expected_sha256="0" * 64)
        self.assertEqual(cm.exception.code, "E_SANDBOX_HASH")
        with self.assertRaises(SandboxError) as cm:
            sandbox.load_module(self.root, "tests", name, spec["kind"], spec["capability_id"], 1)
        self.assertEqual(cm.exception.code, "E_SANDBOX_DIR")
        with self.assertRaises(SandboxError) as cm:
            sandbox.load_module(self.root, "modules", "unit_missing_v1.py", spec["kind"], "unit_missing", 1)
        self.assertEqual(cm.exception.code, "E_SANDBOX_READ")
        with self.assertRaises(PolicyViolation):
            sandbox.load_module(self.root, "modules", "../evil.py", spec["kind"], "evil", 1)
        self.assertTrue(sandbox.load_module(self.root, "modules", name, spec["kind"], spec["capability_id"], 1,
                                            expected_sha256=digest))

    def test_staging_is_loadable_too(self):
        spec = km_mi()
        name = "stg_candidate1.py"
        write_file(self.root, policy.SUBDIR_STAGING, name, templates.generate_module(spec, 1))
        self.assertTrue(sandbox.load_module(self.root, policy.SUBDIR_STAGING, name, spec["kind"], spec["capability_id"], 1))

    def test_an_edited_file_is_refused_by_validation_even_without_a_known_hash(self):
        spec = km_mi()
        evil = templates.generate_module(spec, 1) + "\nimport os\n"
        name, _ = self.install(spec, source=evil)
        with self.assertRaises(ValidationError):
            sandbox.load_module(self.root, "modules", name, spec["kind"], spec["capability_id"], 1)
        self.install(spec, source=templates.generate_module(spec, 1) + "# سلام\n")
        with self.assertRaises(ValidationError) as cm:
            sandbox.load_module(self.root, "modules", name, spec["kind"], spec["capability_id"], 1)
        self.assertEqual(cm.exception.info["violations"][0]["code"], "V_ASCII")
        self.install(spec, source=templates.generate_module(spec, 1) + "# " + "x" * policy.MAX_SOURCE_BYTES)
        with self.assertRaises(ValidationError) as cm:
            sandbox.load_module(self.root, "modules", name, spec["kind"], spec["capability_id"], 1)
        self.assertEqual(cm.exception.info["violations"][0]["code"], "V_SIZE")

    def test_id_and_version_in_the_file_must_match_the_registry(self):
        spec = km_mi()
        name, _ = self.install(spec, version=1)
        with self.assertRaises(ValidationError):
            sandbox.load_module(self.root, "modules", name, spec["kind"], spec["capability_id"], 2)
        with self.assertRaises(ValidationError):
            sandbox.load_module(self.root, "modules", name, spec["kind"], "unit_other_thing", 1)

    def test_symlinked_module_files_are_refused(self):
        spec = km_mi()
        real = os.path.join(self.root, "staging", "stg_real.py")
        write_file(self.root, "staging", "stg_real.py", templates.generate_module(spec, 1))
        os.symlink(real, os.path.join(self.root, "modules", "unit_km_to_mi_v1.py"))
        with self.assertRaises(PolicyViolation) as cm:
            sandbox.load_module(self.root, "modules", "unit_km_to_mi_v1.py", spec["kind"], spec["capability_id"], 1)
        self.assertEqual(cm.exception.code, "E_POLICY_SYMLINK")

    def test_running_a_suite(self):
        spec = km_mi()
        loaded = self.load(spec)
        suite = templates.generate_test_suite(spec, 1)
        result = sandbox.run_suite(loaded, suite)
        self.assertTrue(result["ok"], result["failed"])
        self.assertEqual(result["total"], len(suite["cases"]))
        self.assertEqual(result["passed"], result["total"])
        self.assertEqual(result["failed"], [])

    def test_a_wrong_module_fails_the_differential_suite(self):
        spec = km_mi()
        suite = templates.generate_test_suite(spec, 1)
        wrong_src = templates.generate_module(spec, 1).replace("SCALE = 0.621371192237334", "SCALE = 0.62137")
        result = sandbox.run_suite(self.load(spec, source=wrong_src), suite)
        self.assertFalse(result["ok"])
        self.assertTrue(result["failed"])
        self.assertIn("expected", result["failed"][0]["reason"])
        shifted = templates.generate_module(spec, 1).replace("SHIFT = 0.0", "SHIFT = 1.0")
        self.assertFalse(sandbox.run_suite(self.load(spec, source=shifted), suite)["ok"])

    def test_an_empty_suite_never_counts_as_passing(self):
        self.assertFalse(sandbox.run_suite(self.load(km_mi()), {"cases": []})["ok"])
        self.assertFalse(sandbox.run_suite(self.load(km_mi()), {})["ok"])

    def test_user_examples_that_disagree_fail_the_suite(self):
        spec = km_mi(examples=[{"inputs": {"value": 10}, "expected": 7.0, "tolerance": 0.001}])
        result = sandbox.run_suite(self.load(spec), templates.generate_test_suite(spec, 1))
        self.assertFalse(result["ok"])
        self.assertEqual([f["name"] for f in result["failed"]], ["example_0"])
        self.assertEqual(result["failed"][0]["source"], "user")

    def test_sha256_helper(self):
        self.assertEqual(sandbox.sha256_bytes(b"abc"), "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")

    def test_generated_suites_pass_for_every_archetype_through_the_sandbox(self):
        specs = [km_mi(), spec_mod.unit_conversion_spec(units.UNITS["c"], units.UNITS["f"]),
                 spec_mod.formula_spec("مساحت دایره", "pi * r ** 2"),
                 spec_mod.formula_spec("BMI", "w / (h * h)"),
                 spec_mod.formula_spec("ترکیبی", "sqrt(a * a + b * b) + max(a, b) - min(a, b) * 2"),
                 spec_mod.formula_spec("نسبت", "a / (b - 1)"),
                 spec_mod.text_tool_spec(["count_words"]), spec_mod.text_tool_spec(["strip_spaces", "reverse"]),
                 spec_mod.text_tool_spec(["to_en_digits", "remove_spaces", "count_chars"]),
                 spec_mod.text_tool_spec(["fix_arabic_letters", "fix_mi_prefix", "strip_spaces"])]
        for spec in specs:
            with self.subTest(id=spec["capability_id"]):
                loaded = self.load(spec)
                result = sandbox.run_suite(loaded, templates.generate_test_suite(spec, 1))
                self.assertTrue(result["ok"], result["failed"][:2])
                self.assertGreaterEqual(result["total"], 10)


if __name__ == "__main__":
    unittest.main()
