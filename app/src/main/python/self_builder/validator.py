"""
Self-Builder - static validation of generated modules
=====================================================
The AST allowlist every generated module must pass BEFORE it is ever loaded
(and again every time it is loaded). The source is parsed with `ast.parse`
(parsing only - nothing is executed) and walked against a closed list of
node types; anything else is a violation.

What a valid module looks like
------------------------------
* ASCII text only, <= policy.MAX_SOURCE_BYTES, <= policy.MAX_AST_NODES nodes.
* Top level: assignments of the metadata constants to literals, then exactly
  two function definitions - the archetype's core function and `run`.
* A function has plain positional parameters (no defaults/varargs/annotations/
  decorators) and a body of exactly one `return`.
* Expressions are made only of: + - * on floats, unary minus, numeric/ASCII
  string/bool/None literals, the function's own parameters, the module's
  metadata constants, `{"value": ...}` result dictionaries, and calls to the
  sandbox helpers (helpers.HELPER_NAMES) or to an earlier function of the
  same module.
* NOT allowed, anywhere: imports, attributes, subscripts, loops,
  comprehensions, lambdas, conditionals, try/with, classes, nested defs,
  global/nonlocal, await/yield, f-strings, starred/keyword arguments, names
  starting with "__", and any name that is not listed above.
"""

import ast
import math

from . import helpers, policy
from .errors import ValidationError

ALLOWED_METADATA = {
    policy.ARCHETYPE_UNIT_CONVERSION: ("CAPABILITY_ID", "CAPABILITY_VERSION", "CAPABILITY_KIND", "SCALE", "SHIFT"),
    policy.ARCHETYPE_FORMULA: ("CAPABILITY_ID", "CAPABILITY_VERSION", "CAPABILITY_KIND", "VARIABLES"),
    policy.ARCHETYPE_TEXT_TOOL: ("CAPABILITY_ID", "CAPABILITY_VERSION", "CAPABILITY_KIND", "OPS"),
}
CORE_FUNCTION = {
    policy.ARCHETYPE_UNIT_CONVERSION: "convert",
    policy.ARCHETYPE_FORMULA: "compute",
    policy.ARCHETYPE_TEXT_TOOL: "process",
}

_ALLOWED_EXPR = (ast.BinOp, ast.UnaryOp, ast.Constant, ast.Name, ast.Call, ast.Dict)
_ALLOWED_BINOPS = (ast.Add, ast.Sub, ast.Mult)
_ALLOWED_UNARY = (ast.USub,)


class Report:
    def __init__(self):
        self.violations = []
        self.stats = {"nodes": 0, "bytes": 0, "functions": [], "helpers_used": [], "metadata": []}

    @property
    def ok(self):
        return not self.violations

    def add(self, code, message, node=None):
        self.violations.append({"code": code, "message": message,
                                "line": getattr(node, "lineno", None)})

    def to_dict(self):
        return {"ok": self.ok, "violations": list(self.violations), "stats": dict(self.stats)}


def _literal_ok(node, report, allow_tuple=True):
    """Metadata values: numbers, ASCII strings, bool/None, tuples of those,
    optionally under a unary minus."""
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return _literal_ok(node.operand, report, allow_tuple=False) and isinstance(node.operand, ast.Constant) \
            and isinstance(node.operand.value, (int, float)) and not isinstance(node.operand.value, bool)
    if isinstance(node, ast.Constant):
        return _constant_ok(node, report)
    if isinstance(node, ast.Tuple) and allow_tuple:
        if len(node.elts) > 20:
            report.add("V_LITERAL", "tuple too long", node)
            return False
        return all(isinstance(e, ast.Constant) and _constant_ok(e, report) for e in node.elts)
    report.add("V_LITERAL", f"metadata value must be a literal, got {type(node).__name__}", node)
    return False


def _constant_ok(node, report):
    v = node.value
    if isinstance(v, bool) or v is None:
        return True
    if isinstance(v, (int, float)):
        if isinstance(v, float) and not math.isfinite(v):
            report.add("V_CONSTANT", "non-finite number literal", node)
            return False
        if isinstance(v, int) and abs(v) > 10 ** 15:
            report.add("V_CONSTANT", "integer literal too large", node)
            return False
        return True
    if isinstance(v, str):
        if len(v) > policy.MAX_STRING_CONSTANT or not v.isascii() or not v.isprintable():
            report.add("V_CONSTANT", "string literal must be short printable ASCII", node)
            return False
        return True
    report.add("V_CONSTANT", f"literal type not allowed: {type(v).__name__}", node)
    return False


class _ExprChecker:
    def __init__(self, report, params, constants, callables):
        self.report = report
        self.params = set(params)
        self.constants = set(constants)
        self.callables = set(callables)

    def check(self, node, in_run=False, numeric_only=False):
        """`numeric_only`: the node is an operand of + - * or unary minus, so
        a string/bool/None literal there would be a type trick (e.g.
        "a" * 100000000) and is refused."""
        r = self.report
        if not isinstance(node, _ALLOWED_EXPR):
            r.add("V_NODE", f"expression node not allowed: {type(node).__name__}", node)
            return
        if isinstance(node, ast.BinOp):
            if not isinstance(node.op, _ALLOWED_BINOPS):
                r.add("V_OPERATOR", f"operator not allowed: {type(node.op).__name__}", node)
            self.check(node.left, numeric_only=True)
            self.check(node.right, numeric_only=True)
        elif isinstance(node, ast.UnaryOp):
            if not isinstance(node.op, _ALLOWED_UNARY):
                r.add("V_OPERATOR", f"unary operator not allowed: {type(node.op).__name__}", node)
            self.check(node.operand, numeric_only=True)
        elif isinstance(node, ast.Constant):
            if numeric_only and (isinstance(node.value, (str, bool)) or node.value is None):
                r.add("V_CONSTANT", "only numbers may be used as arithmetic operands", node)
            else:
                _constant_ok(node, r)
        elif isinstance(node, ast.Name):
            if not isinstance(node.ctx, ast.Load):
                r.add("V_NAME", "names may only be read", node)
            elif node.id.startswith("__"):
                r.add("V_NAME", f"dunder name not allowed: {node.id}", node)
            elif node.id not in self.params and node.id not in self.constants:
                r.add("V_NAME", f"name not allowed here: {node.id}", node)
        elif isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                r.add("V_CALL", "only direct calls of helpers/own functions are allowed", node)
            else:
                fid = node.func.id
                if fid in helpers.HELPER_NAMES:
                    if fid not in r.stats["helpers_used"]:
                        r.stats["helpers_used"].append(fid)
                elif fid not in self.callables:
                    r.add("V_CALL", f"call target not allowed: {fid}", node)
            if node.keywords:
                r.add("V_CALL", "keyword arguments are not allowed", node)
            for a in node.args:
                if isinstance(a, ast.Starred):
                    r.add("V_CALL", "starred arguments are not allowed", a)
                else:
                    self.check(a)
            if len(node.args) > 8:
                r.add("V_CALL", "too many arguments", node)
        elif isinstance(node, ast.Dict):
            if not in_run:
                r.add("V_NODE", "dict displays are only allowed in run()", node)
            if len(node.keys) != 1 or not (isinstance(node.keys[0], ast.Constant)
                                           and node.keys[0].value == "value"):
                r.add("V_NODE", "run() must return {\"value\": ...}", node)
            for v in node.values:
                self.check(v)


def check_source(source, kind, expected_id=None, expected_version=None):
    """Validate generated module source. Returns a Report (never raises for
    a violation; raises nothing at all for syntactically broken source - that
    is reported as a violation too)."""
    report = Report()
    if not isinstance(source, str):
        report.add("V_TYPE", "source must be text")
        return report
    raw = source.encode("utf-8", "replace")
    report.stats["bytes"] = len(raw)
    if len(raw) > policy.MAX_SOURCE_BYTES:
        report.add("V_SIZE", f"source larger than {policy.MAX_SOURCE_BYTES} bytes")
        return report
    if not source.isascii():
        report.add("V_ASCII", "source must be ASCII")
        return report
    if kind not in ALLOWED_METADATA:
        report.add("V_KIND", f"unsupported kind {kind!r}")
        return report
    try:
        tree = ast.parse(source, mode="exec")
    except (SyntaxError, ValueError, RecursionError, MemoryError) as e:
        report.add("V_SYNTAX", f"source does not parse: {type(e).__name__}")
        return report

    try:
        count = sum(1 for _ in ast.walk(tree))
    except RecursionError:
        report.add("V_DEPTH", "source nested too deeply")
        return report
    report.stats["nodes"] = count
    if count > policy.MAX_AST_NODES:
        report.add("V_SIZE", f"more than {policy.MAX_AST_NODES} syntax nodes")
        return report

    metadata_expected = list(ALLOWED_METADATA[kind])
    core_name = CORE_FUNCTION[kind]
    seen_metadata = []
    functions = {}
    constants = set(metadata_expected)
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign):
            if len(stmt.targets) != 1 or not isinstance(stmt.targets[0], ast.Name):
                report.add("V_ASSIGN", "only simple constant assignments are allowed", stmt)
                continue
            name = stmt.targets[0].id
            if name not in metadata_expected:
                report.add("V_ASSIGN", f"constant not allowed: {name}", stmt)
                continue
            if name in seen_metadata:
                report.add("V_ASSIGN", f"constant assigned twice: {name}", stmt)
            seen_metadata.append(name)
            _literal_ok(stmt.value, report)
        elif isinstance(stmt, ast.FunctionDef):
            if stmt.name not in (core_name, "run"):
                report.add("V_FUNCTION", f"function not allowed: {stmt.name}", stmt)
                continue
            if stmt.name in functions:
                report.add("V_FUNCTION", f"function defined twice: {stmt.name}", stmt)
                continue
            functions[stmt.name] = stmt
        else:
            report.add("V_STATEMENT", f"top-level statement not allowed: {type(stmt).__name__}", stmt)

    report.stats["metadata"] = list(seen_metadata)
    if seen_metadata != metadata_expected:
        report.add("V_STRUCTURE", f"metadata constants must be exactly {metadata_expected} in order")
    if list(functions) != [core_name, "run"]:
        report.add("V_STRUCTURE", f"functions must be exactly [{core_name}, run] in order")
    report.stats["functions"] = list(functions)

    for fname, fn in functions.items():
        args = fn.args
        if (args.vararg or args.kwarg or args.kwonlyargs or args.defaults or args.kw_defaults
                or args.posonlyargs or fn.decorator_list or fn.returns or getattr(fn, "type_params", None)):
            report.add("V_FUNCTION", f"function {fname} has an unsupported signature", fn)
            continue
        params = [a.arg for a in args.args]
        for a in args.args:
            if a.annotation is not None:
                report.add("V_FUNCTION", "annotations are not allowed", a)
            if a.arg.startswith("__"):
                report.add("V_NAME", f"dunder parameter not allowed: {a.arg}", a)
        if fname == "run":
            if params != ["inputs"]:
                report.add("V_FUNCTION", "run() must take exactly one parameter named 'inputs'", fn)
        else:
            if not params or any(not p.startswith("x_") for p in params):
                report.add("V_FUNCTION", f"{fname}() parameters must be named x_<name>", fn)
        if len(fn.body) != 1 or not isinstance(fn.body[0], ast.Return) or fn.body[0].value is None:
            report.add("V_FUNCTION", f"{fname}() body must be exactly one return statement", fn)
            continue
        if fname == "run" and not isinstance(fn.body[0].value, ast.Dict):
            # the checker below only looks inside a dict display; a bare
            # number / call / name would otherwise slip through unnoticed.
            report.add("V_NODE", "run() must return {\"value\": ...}", fn)
            continue
        callables = [core_name] if fname == "run" else []
        checker = _ExprChecker(report, params, constants, callables)
        try:
            checker.check(fn.body[0].value, in_run=(fname == "run"))
        except RecursionError:
            report.add("V_DEPTH", "expression nested too deeply", fn)

    # metadata cross-checks against what the registry expects
    values = {}
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign) and isinstance(stmt.targets[0], ast.Name) \
                and isinstance(stmt.value, ast.Constant):
            values[stmt.targets[0].id] = stmt.value.value
    if values.get("CAPABILITY_KIND") != kind and "CAPABILITY_KIND" in seen_metadata:
        report.add("V_STRUCTURE", "CAPABILITY_KIND does not match the registry kind")
    if expected_id is not None and values.get("CAPABILITY_ID") != expected_id:
        report.add("V_STRUCTURE", "CAPABILITY_ID does not match the registry id")
    if expected_version is not None and values.get("CAPABILITY_VERSION") != expected_version:
        report.add("V_STRUCTURE", "CAPABILITY_VERSION does not match the registry version")
    return report


def require_valid(source, kind, expected_id=None, expected_version=None):
    """Like check_source but raises ValidationError on any violation."""
    report = check_source(source, kind, expected_id, expected_version)
    if not report.ok:
        first = report.violations[0]
        raise ValidationError(f"{first['code']}: {first['message']}", code="E_VALIDATION",
                              violations=report.violations)
    return report
