"""
PROMPT 957 - extension runtime: the restricted-Python sandbox.

A user/ChatGPT-supplied extension is executable code, so these tests attack it: every escape and denial-of-service
pattern we could think of must be refused statically or stopped at run time, legitimate code must keep working, and
one call must never influence the next.

Run directly:
    python -m unittest tests.test_ext_runtime_sandbox_prompt957 -v
"""

import os
import sys
import time
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ext_runtime import guards, limits, sandbox, srcvalidate
from ext_runtime.errors import SourceRejected
from ext_runtime.suite import FixtureCtx

STATIC_REJECTED = {
    "import_os": ("import os\ndef run(x):\n    return 1\n", "import"),
    "import_from_os": ("from os import system\ndef run(x):\n    return 1\n", "import"),
    "import_as": ("import math as m\ndef run(x):\n    return 1\n", "import"),
    "relative_import": ("from . import y\ndef run(x):\n    return 1\n", "import"),
    "dunder_import": ("def run(x):\n    return __import__('os')\n", "identifier"),
    "class_attr": ("def run(x):\n    return x.__class__\n", "attribute"),
    "subclasses_chain": ("def run(x):\n    return ().__class__.__bases__[0].__subclasses__()\n", "attribute"),
    "format_method": ("def run(x):\n    return '{0.__class__}'.format(x)\n", "attribute"),
    "format_map": ("def run(x):\n    return '{a}'.format_map(x)\n", "attribute"),
    "getattr": ("def run(x):\n    return getattr(x, 'real')\n", "unknown_name"),
    "setattr": ("def run(x):\n    setattr(x, 'a', 1)\n    return 1\n", "unknown_name"),
    "open": ("def run(x):\n    return open('/etc/passwd').read()\n", "unknown_name"),
    "eval": ("def run(x):\n    return eval('1+1')\n", "unknown_name"),
    "exec": ("def run(x):\n    exec('y=1')\n    return 1\n", "unknown_name"),
    "compile": ("def run(x):\n    return compile('1', 'a', 'eval')\n", "unknown_name"),
    "globals": ("def run(x):\n    return globals()\n", "unknown_name"),
    "vars": ("def run(x):\n    return vars()\n", "unknown_name"),
    "type": ("def run(x):\n    return type(x)\n", "unknown_name"),
    "print": ("def run(x):\n    print(x)\n    return 1\n", "unknown_name"),
    "input": ("def run(x):\n    return input()\n", "unknown_name"),
    "generator_frame": ("def run(x):\n    g = (i for i in [1])\n    return g.gi_frame\n", "attribute"),
    "generator_frame_globals": ("def run(x):\n    g = (i for i in [1])\n    return g.gi_frame.f_globals\n", "attribute"),
    "function_globals": ("def run(x):\n    return run.__globals__\n", "attribute"),
    "lambda_globals": ("def run(x):\n    return (lambda: 0).__globals__\n", "attribute"),
    "method_reference": ("def run(x):\n    return [1].append\n", "attribute"),
    "attribute_assign": ("def run(x):\n    x.a = 1\n    return 1\n", "assignment_target"),
    "math_dunder": ("import math\ndef run(x):\n    return math.__dict__\n", "attribute"),
    "math_unknown_function": ("import math\ndef run(x):\n    return math.ulp(1.0)\n", "attribute"),
    "from_math_unknown": ("from math import ulp\ndef run(x):\n    return 1\n", "import"),
    "math_without_import": ("def run(x):\n    return math.sqrt(4)\n", "import"),
    "class_statement": ("class A:\n    pass\ndef run(x):\n    return 1\n", "top_level"),
    "decorator": ("def d(f):\n    return f\n@d\ndef run(x):\n    return 1\n", "decorator"),
    "async_def": ("async def run(x):\n    return 1\n", "top_level"),
    "yield": ("def run(x):\n    yield 1\n", "syntax_not_allowed"),
    "global_statement": ("def run(x):\n    global y\n    y = 1\n    return y\n", "syntax_not_allowed"),
    "with_statement": ("def run(x):\n    with x:\n        pass\n    return 1\n", "syntax_not_allowed"),
    "del_statement": ("def run(x):\n    y = 1\n    del y\n    return 1\n", "syntax_not_allowed"),
    "assert_statement": ("def run(x):\n    assert x\n    return 1\n", "syntax_not_allowed"),
    "walrus": ("def run(x):\n    return (y := 1)\n", "syntax_not_allowed"),
    "starred_assign": ("def run(x):\n    a, *b = [1, 2, 3]\n    return a\n", "assignment_target"),
    "star_call": ("def run(x):\n    return max(*[1, 2])\n", "syntax_not_allowed"),
    "double_star_call": ("def run(x):\n    return dict(**{'a': 1})\n", "syntax_not_allowed"),
    "matmul": ("def run(x):\n    return x @ x\n", "syntax_not_allowed"),
    "nested_def": ("def run(x):\n    def f():\n        return 1\n    return f()\n", "nested_def"),
    "bare_except": ("def run(x):\n    try:\n        return 1\n    except:\n        return 2\n", "except"),
    "except_base_exception": ("def run(x):\n    try:\n        return 1\n    except BaseException:\n        return 2\n", "except"),
    "try_finally": ("def run(x):\n    try:\n        return 1\n    except ValueError:\n        return 2\n    finally:\n        pass\n", "try"),
    "unicode_lookalike_identifier": ("def run(x):\n    \u1d43 = 1\n    return \u1d43\n", "identifier"),
    "persian_identifier": ("def run(x):\n    \u0645\u062a\u063a\u06cc\u0631 = 1\n    return 1\n", "identifier"),
    "underscore_variable": ("def run(x):\n    _y = 1\n    return _y\n", "identifier"),
    "instrumentation_hook_name": ("def run(x):\n    return _m(x, 'upper')\n", "identifier"),
    "underscore_keyword": ("def run(x):\n    return dict(_a=1)\n", "identifier"),
    "bidi_override": ("def run(x):\n    return 'a\u202eb'\n", "character"),
    "nul_character": ("def run(x):\n    return 'a\x00b'\n", "character"),
    "ljust_huge": ("def run(x):\n    return 'a'.ljust(10**9)\n", "attribute"),
    "encode": ("def run(x):\n    return 'a'.encode()\n", "attribute"),
    "percent_format": ("def run(x):\n    return '%s' % 'a'\n", "string_format"),
    "slice_assignment": ("def run(x):\n    a = [1, 2, 3]\n    a[0:2] = [9] * 5\n    return a\n", "slice_assignment"),
    "fstring_huge_width": ("def run(x):\n    return f'{x:>1000000000}'\n", "format_spec"),
    "fstring_dynamic_spec": ("def run(x):\n    return f'{x:{x}}'\n", "format_spec"),
    "no_entry": ("def other(x):\n    return 1\n", "entry"),
    "wrong_parameters": ("def run(a, b):\n    return 1\n", "entry"),
    "top_level_loop": ("while True:\n    pass\ndef run(x):\n    return 1\n", "top_level"),
    "top_level_call": ("print(1)\ndef run(x):\n    return 1\n", "top_level"),
    "import_inside_function": ("def run(x):\n    import math\n    return math.sqrt(4)\n", "import"),
    "bytes_constant": ("def run(x):\n    return b'abc'\n", "syntax_not_allowed"),
    "complex_constant": ("def run(x):\n    return 1j\n", "syntax_not_allowed"),
    "ellipsis_constant": ("def run(x):\n    return ...\n", "syntax_not_allowed"),
    "infinite_float_constant": ("def run(x):\n    return 1e999\n", "constant"),
    "dict_unpacking": ("def run(x):\n    return {**{'a': 1}}\n", "syntax_not_allowed"),
    "raise_system_exit": ("def run(x):\n    raise SystemExit(1)\n", "raise"),
    "raise_from": ("def run(x):\n    raise ValueError('a') from None\n", "raise"),
    "huge_int_constant": ("def run(x):\n    return 1" + "0" * 1300 + "\n", "constant"),
    "int_constant_beyond_python_limit": ("def run(x):\n    return 1" + "0" * 5000 + "\n", "syntax"),
    "syntax_error": ("def run(x:\n    return 1\n", "syntax"),
    "return_outside_function": ("return 1\ndef run(x):\n    return 1\n", "top_level"),
    "break_outside_loop": ("def run(x):\n    break\n", "control_flow"),
}


def compile_ok(source, inputs=("x",)):
    return sandbox.compile_source(source, list(inputs), "t_ext")


def run_src(source, inputs=None, **kw):
    inputs = {"x": 1} if inputs is None else inputs
    return sandbox.run(compile_ok(source, tuple(inputs)), inputs, **kw)


class TestStaticRejection(unittest.TestCase):
    def test_every_hostile_or_unsupported_source_is_refused_before_it_can_run(self):
        for name, (source, code) in STATIC_REJECTED.items():
            with self.subTest(name):
                with self.assertRaises(SourceRejected) as cm:
                    compile_ok(source)
                codes = {i["code"] for i in cm.exception.issues}
                self.assertIn(code, codes, f"{name}: got {sorted(codes)}")
                self.assertTrue(all("line" in i and "message" in i for i in cm.exception.issues))

    def test_issue_lines_point_at_the_offending_line(self):
        with self.assertRaises(SourceRejected) as cm:
            compile_ok("def run(x):\n    y = 1\n    return y.__class__\n")
        self.assertEqual([i["line"] for i in cm.exception.issues if i["code"] == "attribute"], [3])

    def test_all_problems_are_reported_together(self):
        with self.assertRaises(SourceRejected) as cm:
            compile_ok("import os\ndef run(x):\n    open('f')\n    return x.__class__\n")
        self.assertGreaterEqual(len(cm.exception.issues), 3)

    def test_oversize_and_too_deep_sources_are_refused(self):
        with self.assertRaises(SourceRejected):
            compile_ok("def run(x):\n    return 1\n" + "# " + "a" * limits.MAX_SOURCE_BYTES + "\n")
        deep = "def run(x):\n    return " + "[" * 90 + "1" + "]" * 90 + "\n"
        with self.assertRaises(SourceRejected):
            compile_ok(deep)

    def test_rejection_never_executes_anything(self):
        marker = []
        orig = sandbox.run
        try:
            sandbox.run = lambda *a, **k: marker.append(1)
            with self.assertRaises(SourceRejected):
                compile_ok("import os\ndef run(x):\n    return 1\n")
        finally:
            sandbox.run = orig
        self.assertEqual(marker, [])

    def test_non_text_source_is_refused(self):
        for bad in (None, b"def run(x): return 1", 12, ["def run(x): return 1"]):
            with self.subTest(repr(bad)[:20]):
                with self.assertRaises(SourceRejected):
                    sandbox.compile_source(bad, ["x"], "t")

    def test_the_builtin_namespace_is_exactly_what_is_documented(self):
        expected = {"len", "abs", "divmod", "ord", "chr", "reversed", "enumerate", "zip", "map", "filter", "range", "min", "max", "sum",
                    "sorted", "any", "all", "round", "isinstance", "int", "float", "bool", "str", "list", "tuple", "dict", "set",
                    "ValueError", "TypeError", "ZeroDivisionError", "KeyError", "IndexError", "Exception", "OverflowError", "math",
                    "True", "False", "None", "pad_left", "pad_right"}
        self.assertEqual(set(srcvalidate.BUILTIN_NAMES), expected)
        for dangerous in ("open", "eval", "exec", "compile", "getattr", "type", "globals", "locals", "vars", "__import__", "input", "print", "object"):
            self.assertNotIn(dangerous, srcvalidate.BUILTIN_NAMES)

    def test_method_allowlist_has_no_dunder_and_no_unsafe_formatting_or_padding(self):
        for name in guards.ALL_METHOD_NAMES:
            self.assertFalse(name.startswith("_"), name)
        for banned in ("format", "format_map", "encode", "decode", "translate", "ljust", "rjust", "center", "zfill", "expandtabs", "maketrans"):
            self.assertNotIn(banned, guards.ALL_METHOD_NAMES)


# (source, expected limit kind)
STOPPED_AT_RUNTIME = {
    "while_true": ("def run(x):\n    while True:\n        pass\n", "fuel"),
    "nested_big_loops": ("def run(x):\n    n = 0\n    for i in range(200000):\n        for j in range(200000):\n            n += 1\n    return n\n", "fuel"),
    "string_repeat": ("def run(x):\n    return 'a' * 10**9\n", "size"),
    "list_repeat": ("def run(x):\n    return [0] * 10**9\n", "size"),
    "power_huge": ("def run(x):\n    return 2 ** 10**9\n", "size"),
    "power_big_base": ("def run(x):\n    return 10 ** 100000\n", "size"),
    "shift_huge": ("def run(x):\n    return 1 << 10**9\n", "size"),
    "multiply_big_ints": ("def run(x):\n    y = 3 ** 20000\n    return y * y * y\n", "size"),
    "list_doubling": ("def run(x):\n    y = [0]\n    while True:\n        y = y + y\n", "size"),
    "string_doubling": ("def run(x):\n    y = 'ab'\n    for i in range(100):\n        y += y\n    return 1\n", "size"),
    "extend_self": ("def run(x):\n    y = [0, 1]\n    for i in range(100):\n        y.extend(y)\n    return 1\n", "size"),
    "iadd_self": ("def run(x):\n    y = [0, 1]\n    for i in range(100):\n        y += y\n    return 1\n", "size"),
    "replace_blowup": ("def run(x):\n    s = 'a' * 10000\n    return s.replace('a', 'b' * 10000)\n", "size"),
    "join_blowup": ("def run(x):\n    s = 'a' * 10000\n    return ','.join([s] * 1000)\n", "size"),
    "recursion": ("def run(x):\n    return run(x)\n", "recursion"),
    "lambda_recursion": ("def run(x):\n    f = lambda g: g(g)\n    return f(f)\n", "recursion"),
    "range_huge": ("def run(x):\n    return len(range(10**12))\n", "size"),
    "list_of_huge_range": ("def run(x):\n    return len(list(range(10**7)))\n", "size"),
    "set_union_blowup": ("def run(x):\n    a = set(range(150000))\n    b = set(range(150000, 300000))\n    return len(a | b)\n", "size"),
    "many_big_copies": ("def run(x):\n    a = list(range(150000))\n    keep = []\n    for i in range(100):\n        keep.append(list(a))\n    return len(keep)\n", "fuel"),
    "limit_cannot_be_swallowed": ("def run(x):\n    n = 0\n    while True:\n        try:\n            n += 1\n        except Exception:\n            pass\n", "fuel"),
    "swallow_in_handler_loop": ("def run(x):\n    for i in range(10**6):\n        try:\n            y = [0] * 10**9\n        except ValueError:\n            y = 0\n    return 1\n", "size"),
    "dict_collision_dos": ("def run(x):\n    d = {}\n    for i in range(200000):\n        d[i * 2305843009213693951] = i\n    return len(d)\n", None),
}


class TestRuntimeLimits(unittest.TestCase):
    def test_every_resource_attack_is_stopped_quickly_with_a_limit_error(self):
        for name, (source, kind) in STOPPED_AT_RUNTIME.items():
            with self.subTest(name):
                started = time.monotonic()
                result = run_src(source)
                elapsed = time.monotonic() - started
                self.assertLess(elapsed, 6.0, f"{name} took {elapsed:.1f}s")
                self.assertFalse(result["ok"], name)
                if kind is not None:
                    self.assertEqual(result["error"]["code"], "E_EXT_LIMIT", result)
                    self.assertEqual(result["error"]["kind"], kind, result)
                else:
                    self.assertEqual(result["error"]["code"], "E_EXT_LIMIT", result)

    def test_a_limit_error_is_not_an_extension_error_so_tests_cannot_mistake_it(self):
        result = run_src("def run(x):\n    while True:\n        pass\n")
        self.assertEqual(result["error"]["code"], "E_EXT_LIMIT")
        self.assertNotEqual(result["error"]["code"], "E_EXT_RUNTIME")

    def test_time_budget_stops_slow_code_even_when_fuel_remains(self):
        fake = {"t": 0.0}

        def clock():
            fake["t"] += 0.5
            return fake["t"]
        result = sandbox.run(compile_ok("def run(x):\n    n = 0\n    for i in range(100000):\n        n += i\n    return n\n"), {"x": 1}, clock=clock)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["kind"], "time")

    def test_fuel_is_reported_and_deterministic(self):
        src = "def run(x):\n    return sum(i * i for i in range(100))\n"
        a, b = run_src(src), run_src(src)
        self.assertTrue(a["ok"])
        self.assertEqual(a["value"], 328350)
        self.assertEqual(a["fuel_used"], b["fuel_used"])
        self.assertGreater(a["fuel_used"], 100)

    def test_a_custom_fuel_limit_is_respected(self):
        src = "def run(x):\n    return sum(i for i in range(1000))\n"
        self.assertTrue(run_src(src)["ok"])
        small = sandbox.run(compile_ok(src), {"x": 1}, fuel=200)
        self.assertEqual(small["error"]["kind"], "fuel")

    def test_runtime_exceptions_are_reported_as_extension_errors_with_a_line(self):
        r = run_src("def run(x):\n    y = 1\n    return y / 0\n")
        self.assertEqual((r["error"]["code"], r["error"]["kind"], r["error"]["line"]), ("E_EXT_RUNTIME", "ZeroDivisionError", 3))
        r = run_src("def run(x):\n    return [1, 2][5]\n")
        self.assertEqual(r["error"]["kind"], "IndexError")
        r = run_src("def run(x):\n    return 'a' + 1\n")
        self.assertEqual(r["error"]["kind"], "TypeError")

    def test_a_method_on_the_wrong_type_is_a_type_error_not_an_escape(self):
        r = run_src("def run(x):\n    return x.upper()\n", {"x": 5})
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"]["kind"], "TypeError")

    def test_string_percent_formatting_is_blocked_at_run_time_even_when_the_left_side_is_a_variable(self):
        r = run_src("def run(x):\n    s = 'a%d'\n    return s % 5\n")
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"]["kind"], "TypeError")
        self.assertTrue(run_src("def run(x):\n    return 7 % 3\n")["ok"])

    def test_error_details_are_truncated(self):
        r = run_src("def run(x):\n    raise ValueError('z' * 5000)\n")
        self.assertLessEqual(len(r["error"]["detail"]), limits.MAX_ERROR_DETAIL)


class TestSandboxSemantics(unittest.TestCase):
    """Legitimate code must behave exactly like Python (expected values are hand-computed)."""

    def value(self, source, inputs=None):
        r = run_src(source, inputs)
        self.assertTrue(r["ok"], r)
        return r["value"]

    def test_arithmetic_and_control_flow(self):
        src = ("def run(x):\n    total = 0\n    for i in range(1, x + 1):\n        if i % 2 == 0:\n            continue\n"
               "        total += i\n        if total > 100:\n            break\n    n = 0\n    while n < 5:\n        n += 1\n    return {'t': total, 'n': n}\n")
        self.assertEqual(self.value(src, {"x": 10}), {"t": 25, "n": 5})

    def test_comprehensions_lambda_sorted_min_max_sum(self):
        src = ("def run(x):\n    words = ['pear', 'fig', 'banana']\n    return {'sq': [i * i for i in range(5) if i % 2 == 0],\n"
               "            'by_len': sorted(words, key=lambda w: len(w)),\n            'longest': max(words, key=len),\n"
               "            'shortest': min(words, key=lambda w: len(w)),\n            'dict': {w: len(w) for w in words},\n"
               "            'set': sorted({i % 3 for i in range(10)}), 'sum': sum([1.5, 2.5], 10)}\n")
        self.assertEqual(self.value(src), {"sq": [0, 4, 16], "by_len": ["fig", "pear", "banana"], "longest": "banana", "shortest": "fig",
                                           "dict": {"pear": 4, "fig": 3, "banana": 6}, "set": [0, 1, 2], "sum": 14.0})

    def test_string_methods_and_fstrings_with_persian_text(self):
        src = ("def run(x):\n    s = '  \u0633\u0644\u0627\u0645 \u062f\u0646\u06cc\u0627  '\n    parts = s.strip().split(' ')\n"
               "    return {'rev': ' '.join(reversed(parts)), 'up': 'abc'.upper(), 'n': len(parts), 'f': f'{3.14159:.2f}|{x:>5}|{x!r}',\n"
               "            'rep': 'a-b-c'.replace('-', '+'), 'starts': 'hello'.startswith('he')}\n")
        self.assertEqual(self.value(src, {"x": 42}), {"rev": "\u062f\u0646\u06cc\u0627 \u0633\u0644\u0627\u0645", "up": "ABC", "n": 2,
                                                      "f": "3.14|   42|42", "rep": "a+b+c", "starts": True})

    def test_list_dict_set_methods_and_in_place_operations(self):
        src = ("def run(x):\n    a = [3, 1, 2]\n    a.append(0)\n    a.sort()\n    a += [9]\n    d = {}\n    d['k'] = 1\n    d['k'] += 4\n"
               "    d.setdefault('z', 7)\n    s = set()\n    s.add(2)\n    s |= {5}\n    t = (1, 2)\n    return {'a': a, 'd': d, 's': sorted(s), 't': list(t), 'g': d.get('q', -1), 'i': t.index(2)}\n")
        self.assertEqual(self.value(src), {"a": [0, 1, 2, 3, 9], "d": {"k": 5, "z": 7}, "s": [2, 5], "t": [1, 2], "g": -1, "i": 1})

    def test_subscript_augmented_assignment_evaluates_its_target_once(self):
        src = ("def key(log):\n    log.append(1)\n    return 'a'\n"
               "def run(x):\n    d = {'a': 1}\n    log = []\n    d[key(log)] += 5\n    return [d['a'], len(log)]\n")
        self.assertEqual(self.value(src), [6, 1])

    def test_isinstance_and_type_constructors(self):
        src = ("def run(x):\n    return {'a': isinstance(x, (int, float)), 'b': isinstance('s', str), 'c': isinstance([1], list), 'd': isinstance(x, bool),\n"
               "            'e': int('42') + int(3.9), 'f': float('1.5'), 'g': str(12) + 'a', 'h': bool(0), 'i': list('ab'), 'j': round(2.567, 2), 'k': round(7)}\n")
        self.assertEqual(self.value(src, {"x": 3}), {"a": True, "b": True, "c": True, "d": False, "e": 45, "f": 1.5, "g": "12a", "h": False,
                                                    "i": ["a", "b"], "j": 2.57, "k": 7})

    def test_isinstance_with_a_foreign_type_is_an_error(self):
        r = run_src("def run(x):\n    return isinstance(x, x)\n")
        self.assertFalse(r["ok"])

    def test_math_module_and_from_imports(self):
        src = ("import math\nfrom math import sqrt, pi\ndef run(x):\n    return {'a': math.sqrt(16), 'b': sqrt(9), 'c': round(pi, 4), 'd': math.floor(2.7),\n"
               "            'e': math.factorial(5), 'f': math.gcd(12, 18), 'g': round(math.log(math.e), 6), 'h': math.comb(5, 2), 'i': round(math.hypot(3, 4), 6)}\n")
        self.assertEqual(self.value(src), {"a": 4.0, "b": 3.0, "c": 3.1416, "d": 2, "e": 120, "f": 6, "g": 1.0, "h": 10, "i": 5.0})

    def test_exceptions_can_be_raised_and_caught_by_allowed_names(self):
        src = ("def safe_div(a, b):\n    try:\n        return a / b\n    except ZeroDivisionError:\n        return None\n"
               "def run(x):\n    try:\n        raise ValueError('bad')\n    except (ValueError, KeyError) as e:\n        msg = str(e)\n    return {'q': safe_div(6, 3), 'z': safe_div(1, 0), 'm': msg}\n")
        self.assertEqual(self.value(src), {"q": 2.0, "z": None, "m": "bad"})

    def test_type_annotations_and_docstrings_are_accepted_and_ignored(self):
        src = '"""doc"""\ndef helper(v: float, w: int = 2) -> float:\n    """h"""\n    return v * w\ndef run(x: float) -> float:\n    y: int = 3\n    return helper(x) + y\n'
        self.assertEqual(self.value(src, {"x": 2.5}), 8.0)

    def test_module_level_constants_and_helper_functions_work(self):
        src = "RATES = {'a': 2, 'b': 3}\nNAMES = [k for k in RATES]\ndef run(x):\n    return RATES['b'] * x + len(NAMES)\n"
        self.assertEqual(self.value(src, {"x": 4}), 14)

    def test_pad_helpers_and_range_forms(self):
        src = "def run(x):\n    return [pad_left('7', 3, '0'), pad_right('ab', 4, '.'), list(range(5, 0, -2)), list(range(3))]\n"
        self.assertEqual(self.value(src), ["007", "ab..", [5, 3, 1], [0, 1, 2]])
        self.assertFalse(run_src("def run(x):\n    return pad_left('a', 10**6)\n")["ok"])

    def test_integer_arithmetic_is_exact_within_limits(self):
        self.assertEqual(self.value("def run(x):\n    return 2 ** 200 + 3 ** 5\n"), 2 ** 200 + 243)
        self.assertEqual(self.value("def run(x):\n    return (1 << 70) >> 3\n"), (1 << 70) >> 3)

    def test_each_call_gets_a_fresh_module_so_state_cannot_leak_between_calls(self):
        c = compile_ok("STATE = []\ndef run(x):\n    STATE.append(x)\n    return len(STATE)\n")
        self.assertEqual([sandbox.run(c, {"x": i})["value"] for i in range(3)], [1, 1, 1])

    def test_sandbox_modules_are_isolated_from_each_other_and_from_the_host(self):
        import builtins
        before = set(vars(builtins))
        a = compile_ok("def run(x):\n    return x + 1\n")
        b = compile_ok("def run(x):\n    return x * 10\n")
        self.assertEqual((sandbox.run(a, {"x": 2})["value"], sandbox.run(b, {"x": 2})["value"]), (3, 20))
        self.assertEqual(set(vars(builtins)), before)
        self.assertNotIn("ext_run", sys.modules)

    def test_user_names_cannot_shadow_the_instrumentation(self):
        # an underscore name is refused statically; shadowing a visible builtin is harmless and local to the call
        self.assertEqual(self.value("def run(x):\n    len = 5\n    return len\n"), 5)
        self.assertEqual(self.value("def run(x):\n    return len([1, 2])\n"), 2)


class TestOutputs(unittest.TestCase):
    def result(self, expr):
        return run_src(f"def run(x):\n    return {expr}\n")

    def test_json_data_is_accepted(self):
        r = self.result("{'a': [1, 2.5, 'x', None, True], 'b': {'c': (1, 2)}}")
        self.assertTrue(r["ok"])
        self.assertEqual(r["value"], {"a": [1, 2.5, "x", None, True], "b": {"c": [1, 2]}})

    def test_values_that_are_not_json_data_are_refused(self):
        for expr in ("{1, 2}", "range(3)", "(i for i in [1])", "lambda: 1", "{1: 'a'}", "1e308 * 10", "float('nan')", "'a' * 30000"):
            with self.subTest(expr):
                r = self.result(expr)
                self.assertFalse(r["ok"])
                self.assertIn(r["error"]["code"], ("E_EXT_OUTPUT", "E_EXT_LIMIT", "E_EXT_RUNTIME"))

    def test_too_deep_or_too_long_results_are_refused(self):
        self.assertFalse(self.result("[[[[[[[1]]]]]]]")["ok"])
        self.assertFalse(self.result("list(range(5000))")["ok"])


class TestPermissionHelpers(unittest.TestCase):
    SRC = ("def run(x):\n    store_put('k', x)\n    return {'now': clock_now(), 'v': store_get('k'), 'keys': store_keys(), 'page': web_fetch_text('https://a.test/')}\n")

    def test_helpers_exist_only_when_the_permission_was_granted(self):
        c = compile_ok(self.SRC)
        self.assertEqual(c.helpers_used, {"store_put", "clock_now", "store_get", "store_keys", "web_fetch_text"})
        ctx = FixtureCtx({"clock": 1000, "web": {"https://a.test/": "PAGE"}})
        ok = sandbox.run(c, {"x": 5}, ctx=ctx, granted=frozenset(limits.OPTIONAL_PERMISSIONS))
        self.assertEqual(ok["value"], {"now": 1000.0, "v": 5, "keys": ["k"], "page": "PAGE"})
        for missing in limits.OPTIONAL_PERMISSIONS:
            granted = frozenset(limits.OPTIONAL_PERMISSIONS) - {missing}
            r = sandbox.run(c, {"x": 5}, ctx=FixtureCtx({"web": {"https://a.test/": "P"}}), granted=granted)
            self.assertFalse(r["ok"], missing)
            self.assertEqual(r["error"]["kind"], "NameError", missing)

    def test_no_ctx_means_no_helpers_at_all(self):
        r = sandbox.run(compile_ok("def run(x):\n    return clock_now()\n"), {"x": 1})
        self.assertFalse(r["ok"])

    def test_storage_limits(self):
        c = compile_ok("def run(x):\n    store_put('k', 'a' * 9000)\n    return 1\n")
        r = sandbox.run(c, {"x": 1}, ctx=FixtureCtx(), granted=frozenset({"storage"}))
        self.assertEqual(r["error"]["kind"], "ValueError")
        c = compile_ok("def run(x):\n    store_put('bad key!', 1)\n    return 1\n")
        self.assertEqual(sandbox.run(c, {"x": 1}, ctx=FixtureCtx(), granted=frozenset({"storage"}))["error"]["kind"], "ValueError")

    def test_web_helper_errors_are_catchable_and_carry_no_traceback(self):
        c = compile_ok("def run(x):\n    try:\n        return web_fetch_text('https://nope.test/')\n    except Exception as e:\n        return 'caught'\n")
        r = sandbox.run(c, {"x": 1}, ctx=FixtureCtx(), granted=frozenset({"network"}))
        self.assertEqual(r["value"], "caught")


if __name__ == "__main__":
    unittest.main()
