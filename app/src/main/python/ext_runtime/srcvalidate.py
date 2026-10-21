"""
Extension runtime - static validation of extension source
=========================================================
An extension is a tiny pure function written in a restricted subset of Python. This module decides, from the
syntax tree alone, whether a source text belongs to that subset. It never runs the code.

The subset is an ALLOWLIST: every node type that is not named here is refused. In particular there are no classes,
no imports except `math`, no attribute access except an allowlisted set of method names (and `math.<name>`), no
names that start with an underscore (so nothing can reach `__class__`, `__globals__`, `__builtins__` ...), no
generators/yield/async, no `global`/`with`/`del`/`assert`, no starred expressions, no `str.format`, no decorators.
Whatever passes is then rewritten by instrument.py and executed against the guards in guards.py.
"""

import ast
import io
import re
import tokenize

from . import guards, limits
from .errors import SourceRejected

_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_SPEC_RE = re.compile(r"^[<>^=]?[+\- ]?[0-9]{0,3}[,_]?(\.[0-9]{1,3})?[bdeEfFgGsxXo%]?$")
_BIDI = set(range(0x202A, 0x202F)) | set(range(0x2066, 0x206A))
EXCEPTION_NAMES = frozenset(("ValueError", "TypeError", "ZeroDivisionError", "KeyError", "IndexError", "Exception", "OverflowError"))
_ANNOTATION_NAMES = frozenset(("int", "float", "str", "bool", "list", "dict", "tuple", "set"))
_BINOPS = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow, ast.LShift, ast.RShift,
           ast.BitOr, ast.BitAnd, ast.BitXor)
_UNARY = (ast.Not, ast.USub, ast.UAdd, ast.Invert)
_CMPOPS = (ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.Is, ast.IsNot, ast.In, ast.NotIn)
_CONVERSIONS = (-1, 115, 114, 97)

_probe_hooks, _probe_ns = guards.make_runtime(guards.Budget(), ctx=object(), granted=frozenset(limits.OPTIONAL_PERMISSIONS))
BUILTIN_NAMES = frozenset(_probe_ns) - frozenset(limits.HELPER_TO_PERMISSION)
del _probe_hooks, _probe_ns


class _Report:
    def __init__(self):
        self.issues = []
        self.functions = {}
        self.math_imports = []
        self.imports_math = False
        self.helpers_used = set()
        self.nodes = 0

    @property
    def ok(self):
        return not self.issues

    def add(self, code, node, message):
        if len(self.issues) < 40:
            self.issues.append({"code": code, "line": int(getattr(node, "lineno", 0) or 0), "message": message})


def _ident_ok(rep, name, node, what):
    if not isinstance(name, str) or not _NAME_RE.match(name):
        rep.add("identifier", node, f"{what} {name!r}: names must be ASCII letters/digits/underscore and start with a letter "
                                    "(a leading underscore is reserved)")
        return False
    return True


class _Checker:
    def __init__(self, rep):
        self.rep = rep
        self.stores = set()
        self.loads = []
        self.in_func = False
        self.loop_depth = 0

    # ---------------------------------------------------------------- helpers
    def bad(self, node, what):
        self.rep.add("syntax_not_allowed", node, f"{what} is not allowed in an extension")

    def expr(self, node):
        if node is not None:
            self._visit(node)

    def exprs(self, nodes):
        for n in nodes:
            self.expr(n)

    def target(self, node):
        if isinstance(node, ast.Name):
            if _ident_ok(self.rep, node.id, node, "variable"):
                self.stores.add(node.id)
        elif isinstance(node, (ast.Tuple, ast.List)):
            for e in node.elts:
                self.target(e)
        elif isinstance(node, ast.Subscript):
            if isinstance(node.slice, ast.Slice):
                self.rep.add("slice_assignment", node, "assigning to a slice is not allowed (assign items one by one)")
            self._visit(node.value)
            self._visit(node.slice)
        else:
            self.rep.add("assignment_target", node, f"cannot assign to {type(node).__name__}")

    def annotation(self, node):
        if node is None:
            return
        if isinstance(node, ast.Name):
            if node.id not in _ANNOTATION_NAMES:
                self.rep.add("annotation", node, f"type annotation {node.id!r} is not allowed (use int, float, str, bool, list, dict, tuple, set)")
        elif isinstance(node, ast.Constant):
            if node.value is not None and not isinstance(node.value, str):
                self.rep.add("annotation", node, "unsupported annotation")
        elif isinstance(node, ast.Subscript):
            self.annotation(node.value)
            self.annotation(node.slice)
        elif isinstance(node, (ast.Tuple, ast.List)):
            for e in node.elts:
                self.annotation(e)
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
            self.annotation(node.left)
            self.annotation(node.right)
        else:
            self.rep.add("annotation", node, "unsupported annotation")

    def arguments(self, args, node, is_lambda):
        if args.posonlyargs or args.kwonlyargs or args.vararg or args.kwarg:
            self.rep.add("arguments", node, "only plain positional-or-keyword parameters are allowed")
        for a in args.args:
            if _ident_ok(self.rep, a.arg, a, "parameter"):
                self.stores.add(a.arg)
            if a.annotation is not None:
                self.annotation(a.annotation)
        self.exprs(args.defaults)

    # ---------------------------------------------------------------- dispatch
    def _visit(self, node):
        self.rep.nodes += 1
        method = getattr(self, "v_" + type(node).__name__, None)
        if method is None:
            self.bad(node, type(node).__name__)
            return
        method(node)

    def body(self, stmts):
        for s in stmts:
            self._visit(s)

    # ---------------------------------------------------------------- statements
    def v_Expr(self, n):
        self.expr(n.value)

    def v_Pass(self, n):
        pass

    def v_Break(self, n):
        if not self.loop_depth:
            self.rep.add("control_flow", n, "'break' outside a loop")

    def v_Continue(self, n):
        if not self.loop_depth:
            self.rep.add("control_flow", n, "'continue' outside a loop")

    def v_Return(self, n):
        if not self.in_func:
            self.rep.add("control_flow", n, "'return' outside a function")
        self.expr(n.value)

    def v_Assign(self, n):
        for t in n.targets:
            self.target(t)
        self.expr(n.value)

    def v_AnnAssign(self, n):
        if n.value is None or not isinstance(n.target, ast.Name):
            self.rep.add("assignment_target", n, "an annotated assignment needs a name and a value")
            return
        self.annotation(n.annotation)
        self.target(n.target)
        self.expr(n.value)

    def v_AugAssign(self, n):
        if not isinstance(n.op, _BINOPS):
            self.bad(n, type(n.op).__name__)
        if isinstance(n.target, ast.Name):
            self.loads.append((n.target.id, n))
        self.target(n.target)
        self.expr(n.value)

    def v_If(self, n):
        self.expr(n.test)
        self.body(n.body)
        self.body(n.orelse)

    def v_For(self, n):
        self.target(n.target)
        self.expr(n.iter)
        self.loop_depth += 1
        self.body(n.body)
        self.loop_depth -= 1
        self.body(n.orelse)

    def v_While(self, n):
        self.expr(n.test)
        self.loop_depth += 1
        self.body(n.body)
        self.loop_depth -= 1
        self.body(n.orelse)

    def v_Raise(self, n):
        if n.cause is not None:
            self.rep.add("raise", n, "'raise ... from ...' is not allowed")
        e = n.exc
        if e is None:
            return
        if not (isinstance(e, ast.Call) and isinstance(e.func, ast.Name) and e.func.id in EXCEPTION_NAMES
                and len(e.args) <= 1 and not e.keywords):
            self.rep.add("raise", n, "raise one of: " + ", ".join(sorted(EXCEPTION_NAMES)) + " with at most one message argument")
            return
        self.exprs(e.args)

    def v_Try(self, n):
        if n.finalbody or n.orelse:
            self.rep.add("try", n, "'finally' and 'else' clauses on try are not allowed")
        if not n.handlers:
            self.rep.add("try", n, "try needs at least one except clause")
        self.body(n.body)
        for h in n.handlers:
            self.rep.nodes += 1
            t = h.type
            names = [t] if isinstance(t, ast.Name) else (list(t.elts) if isinstance(t, ast.Tuple) else None)
            if names is None or not all(isinstance(x, ast.Name) and x.id in EXCEPTION_NAMES for x in names):
                self.rep.add("except", h, "an except clause must name allowed exceptions: " + ", ".join(sorted(EXCEPTION_NAMES)))
            if h.name is not None and _ident_ok(self.rep, h.name, h, "exception variable"):
                self.stores.add(h.name)
            self.body(h.body)

    def v_Import(self, n):
        for a in n.names:
            if a.name != "math" or a.asname is not None:
                self.rep.add("import", n, f"import {a.name!r} is not allowed (only 'import math')")
            else:
                self.rep.imports_math = True
        if self.in_func or self.loop_depth:
            self.rep.add("import", n, "imports belong at the top of the file")

    def v_ImportFrom(self, n):
        if n.module != "math" or n.level:
            self.rep.add("import", n, "only 'from math import ...' is allowed")
            return
        for a in n.names:
            if a.name not in guards.MATH_NAMES or a.asname is not None:
                self.rep.add("import", n, f"math.{a.name} is not available (available: {', '.join(sorted(guards.MATH_NAMES))})")
            else:
                self.rep.math_imports.append(a.name)
                self.stores.add(a.name)
        if self.in_func:
            self.rep.add("import", n, "imports belong at the top of the file")

    def v_FunctionDef(self, n):
        if self.in_func:
            self.rep.add("nested_def", n, "nested functions are not allowed (use a lambda or a top-level function)")
            return
        if n.decorator_list:
            self.rep.add("decorator", n, "decorators are not allowed")
        if _ident_ok(self.rep, n.name, n, "function"):
            self.stores.add(n.name)
        self.annotation(n.returns)
        self.arguments(n.args, n, False)
        self.rep.functions[n.name] = [a.arg for a in n.args.args]
        self.in_func = True
        self.body(n.body)
        self.in_func = False

    # ---------------------------------------------------------------- expressions
    def v_Constant(self, n):
        v = n.value
        if isinstance(v, bool) or v is None:
            return
        if isinstance(v, str):
            if len(v) > limits.MAX_STRING_CONSTANT:
                self.rep.add("constant", n, "string constant too long")
        elif isinstance(v, int):
            if v.bit_length() > limits.MAX_INT_CONSTANT_BITS:
                self.rep.add("constant", n, "integer constant too large")
        elif isinstance(v, float):
            if v != v or v in (float("inf"), float("-inf")):
                self.rep.add("constant", n, "non-finite float constants are not allowed (use math.inf / math.nan)")
        else:
            self.bad(n, f"a {type(v).__name__} constant")

    def v_Name(self, n):
        if not isinstance(n.ctx, ast.Load):
            self.rep.add("syntax_not_allowed", n, "unexpected name context")
            return
        if _ident_ok(self.rep, n.id, n, "name"):
            self.loads.append((n.id, n))

    def v_Attribute(self, n):
        v = n.value
        if isinstance(v, ast.Name) and v.id == "math" and n.attr in guards.MATH_NAMES and isinstance(n.ctx, ast.Load):
            self.loads.append(("math", n))
            return
        self.rep.add("attribute", n, f"attribute access '.{n.attr}' is only allowed as a method call with an allowlisted name "
                                     "(or math.<name>)")

    def v_Call(self, n):
        f = n.func
        if isinstance(f, ast.Attribute):
            v = f.value
            if isinstance(v, ast.Name) and v.id == "math":
                if f.attr not in guards.MATH_NAMES:
                    self.rep.add("attribute", f, f"math.{f.attr} is not available")
                self.loads.append(("math", f))
            elif f.attr not in guards.ALL_METHOD_NAMES:
                self.rep.add("attribute", f, f"method '.{f.attr}()' is not allowed (allowed methods are the safe str/list/dict/set methods)")
                self.expr(v)
            else:
                self.expr(v)
        else:
            self.expr(f)
        for a in n.args:
            if isinstance(a, ast.Starred):
                self.bad(a, "star-arguments")
            else:
                self.expr(a)
        for kw in n.keywords:
            if kw.arg is None:
                self.bad(kw.value, "double-star arguments")
            elif _ident_ok(self.rep, kw.arg, kw.value, "keyword"):
                self.expr(kw.value)

    def v_BinOp(self, n):
        if not isinstance(n.op, _BINOPS):
            self.bad(n, "this operator")
        if isinstance(n.op, ast.Mod) and (isinstance(n.left, ast.JoinedStr) or (isinstance(n.left, ast.Constant) and isinstance(n.left.value, str))):
            self.rep.add("string_format", n, "'text' % values formatting is not allowed: use an f-string")
        self.expr(n.left)
        self.expr(n.right)

    def v_UnaryOp(self, n):
        if not isinstance(n.op, _UNARY):
            self.bad(n, "this operator")
        self.expr(n.operand)

    def v_BoolOp(self, n):
        self.exprs(n.values)

    def v_Compare(self, n):
        if not all(isinstance(o, _CMPOPS) for o in n.ops):
            self.bad(n, "this comparison")
        self.expr(n.left)
        self.exprs(n.comparators)

    def v_IfExp(self, n):
        self.expr(n.test)
        self.expr(n.body)
        self.expr(n.orelse)

    def v_Lambda(self, n):
        saved = self.in_func
        self.arguments(n.args, n, True)
        self.in_func = True
        self.expr(n.body)
        self.in_func = saved

    def v_List(self, n):
        self.exprs(n.elts)

    v_Tuple = v_List
    v_Set = v_List

    def v_Dict(self, n):
        for k, v in zip(n.keys, n.values):
            if k is None:
                self.bad(v, "dictionary unpacking")
            else:
                self.expr(k)
            self.expr(v)

    def v_Subscript(self, n):
        self.expr(n.value)
        self.expr(n.slice)

    def v_Slice(self, n):
        self.expr(n.lower)
        self.expr(n.upper)
        self.expr(n.step)

    def comprehension(self, n, elts):
        for g in n.generators:
            self.rep.nodes += 1
            if g.is_async:
                self.bad(g.iter, "async comprehension")
            self.target(g.target)
            self.expr(g.iter)
            self.exprs(g.ifs)
        self.exprs(elts)

    def v_ListComp(self, n):
        self.comprehension(n, [n.elt])

    v_SetComp = v_ListComp
    v_GeneratorExp = v_ListComp

    def v_DictComp(self, n):
        self.comprehension(n, [n.key, n.value])

    def v_JoinedStr(self, n):
        for v in n.values:
            self.rep.nodes += 1
            if isinstance(v, ast.Constant):
                continue
            if not isinstance(v, ast.FormattedValue) or v.conversion not in _CONVERSIONS:
                self.bad(v, "this f-string part")
                continue
            self.expr(v.value)
            spec = v.format_spec
            if spec is not None:
                if not (isinstance(spec, ast.JoinedStr) and all(isinstance(x, ast.Constant) and isinstance(x.value, str) for x in spec.values)):
                    self.rep.add("format_spec", v, "an f-string format spec must be a plain constant such as .2f or >10")
                elif not _SPEC_RE.match("".join(x.value for x in spec.values)):
                    self.rep.add("format_spec", v, "this f-string format spec is not allowed (width up to 999, precision up to 999)")


def _prescan(source, rep):
    if not isinstance(source, str):
        rep.add("source", None, "the source must be text")
        return False
    if len(source.encode("utf-8", "replace")) > limits.MAX_SOURCE_BYTES:
        rep.add("size", None, f"the source is larger than {limits.MAX_SOURCE_BYTES} bytes")
        return False
    for i, ch in enumerate(source):
        c = ord(ch)
        if c == 0 or (c < 32 and ch not in "\n\r\t") or c == 0x7F or c in _BIDI or 0xD800 <= c <= 0xDFFF:
            line = source.count("\n", 0, i) + 1
            rep.issues.append({"code": "character", "line": line,
                               "message": f"control or bidirectional-override character U+{c:04X} is not allowed"})
            return False
    try:        # Python folds look-alike letters into ASCII names (U+1D43 -> a): the author's text must not hide that
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type == tokenize.NAME and not tok.string.isascii():
                rep.issues.append({"code": "identifier", "line": tok.start[0],
                                   "message": f"identifier {tok.string!r} contains non-ASCII letters (only ASCII names are allowed; Persian text belongs in strings)"})
                return False
    except (tokenize.TokenError, SyntaxError, ValueError):
        pass                                          # the parser reports malformed source itself
    return True


def _measure(tree, rep):
    stack = [(tree, 1)]
    count = 0
    while stack:
        node, depth = stack.pop()
        count += 1
        if depth > limits.MAX_AST_DEPTH:
            rep.add("depth", node, "the code is nested too deeply")
            return False
        if count > limits.MAX_AST_NODES:
            rep.add("size", node, f"the code has more than {limits.MAX_AST_NODES} syntax nodes")
            return False
        for child in ast.iter_child_nodes(node):
            stack.append((child, depth + 1))
    return True


def validate_source(source, input_names, entry="run"):
    """Validate one extension source. Returns (report, tree-or-None); tree is returned only when the report is clean."""
    rep = _Report()
    if not _prescan(source, rep):
        return rep, None
    try:
        tree = ast.parse(source, mode="exec")
    except SyntaxError as e:
        rep.issues.append({"code": "syntax", "line": int(e.lineno or 0), "message": f"syntax error: {e.msg}"})
        return rep, None
    except (ValueError, RecursionError, MemoryError):
        rep.issues.append({"code": "syntax", "line": 0, "message": "the source cannot be parsed (too deeply nested?)"})
        return rep, None
    if not _measure(tree, rep):
        return rep, None
    checker = _Checker(rep)
    for stmt in tree.body:
        if not isinstance(stmt, (ast.FunctionDef, ast.Import, ast.ImportFrom, ast.Assign, ast.Expr, ast.AnnAssign)):
            rep.add("top_level", stmt, "only imports, assignments and function definitions are allowed at the top level")
            continue
        if isinstance(stmt, ast.Expr) and not (isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str)):
            rep.add("top_level", stmt, "only a docstring may be a bare expression at the top level")
            continue
        checker._visit(stmt)
    known = checker.stores | BUILTIN_NAMES | set(limits.HELPER_TO_PERMISSION) | ({"math"} if rep.imports_math or rep.math_imports else set())
    for name, node in checker.loads:
        if name == "math" and not rep.imports_math:
            rep.add("import", node, "'math' is used but 'import math' is missing")
        elif name not in known:
            rep.add("unknown_name", node, f"name {name!r} is not defined (extensions cannot use open, eval, getattr, type, print, ...)")
        elif name in limits.HELPER_TO_PERMISSION and name not in checker.stores:
            rep.helpers_used.add(name)
    if entry not in rep.functions:
        rep.add("entry", None, f"the source must define a top-level function named {entry!r}")
    elif sorted(rep.functions[entry]) != sorted(input_names):
        rep.add("entry", None, f"{entry}() must take exactly the declared inputs {sorted(input_names)}, but takes {sorted(rep.functions[entry])}")
    return rep, (tree if rep.ok else None)
