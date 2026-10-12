"""
Self-Builder - safe arithmetic expression engine
================================================
A tiny, closed expression language for the "formula" archetype. It is parsed
by this module's own tokenizer and recursive-descent parser - the text is
never handed to Python's eval/exec/compile - into a small tuple-based tree:

    ["num", float]            ["const", "pi"]          ["var", "r"]
    ["neg", node]             ["bin", op, left, right] (op: + - * / **)
    ["call", "sqrt", [args]]

Strict grammar (ASCII only):

    expr   := term (('+'|'-') term)*
    term   := factor (('*'|'/') factor)*
    factor := ('+'|'-') factor | power
    power  := atom ['**' factor]                  right-associative
    atom   := NUMBER | NAME | NAME '(' expr (',' expr)* ')' | '(' expr ')'

Names are case-insensitive (lower-cased) and must start with a letter - a
leading underscore is rejected, so a user can never introduce a dunder-style
name such as `__builtins__`. `pi` is the only constant. The
allowed functions are in FUNCTIONS. Everything else is rejected with a
stable error code (E_EXPR_*) that repair.py knows how to analyze.

The same tree feeds three things: the reference evaluator (`evaluate`, used
by the Self-Builder's differential tests), the Python source generator
(`to_source`, used by the code templates) and the variable/dependency report.
"""

import math
import re

from . import mathcore, policy
from .errors import ExprError

# name -> (min_args, max_args, mathcore function name)
FUNCTIONS = {
    "sqrt": (1, 1, "sqrt"),
    "abs": (1, 1, "absolute"),
    "min": (2, 4, "minimum"),
    "max": (2, 4, "maximum"),
    "floor": (1, 1, "floor"),
    "ceil": (1, 1, "ceil"),
    "round": (1, 2, "round_to"),
    "ln": (1, 1, "ln"),
    "log10": (1, 1, "log10"),
    "exp": (1, 1, "exp"),
    "sin": (1, 1, "sin"),
    "cos": (1, 1, "cos"),
    "tan": (1, 1, "tan"),
}
CONSTANTS = {"pi": math.pi}
_NAME_MAX = 24

_TOKEN_RE = re.compile(
    r"""
    (?P<WS>\s+)
  | (?P<NUM>(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?)
  | (?P<NAME>[A-Za-z][A-Za-z0-9_]*)
  | (?P<POW>\*\*)
  | (?P<OP>[+\-*/])
  | (?P<LPAREN>\()
  | (?P<RPAREN>\))
  | (?P<COMMA>,)
    """,
    re.VERBOSE,
)


class Token:
    __slots__ = ("type", "value", "pos")

    def __init__(self, type_, value, pos):
        self.type = type_
        self.value = value
        self.pos = pos

    def __repr__(self):
        return f"Token({self.type}, {self.value!r}, {self.pos})"


def tokenize(text):
    if not isinstance(text, str):
        raise ExprError("expression must be text", code="E_EXPR_EMPTY")
    if len(text) > policy.MAX_EXPR_CHARS:
        raise ExprError("expression is too long", code="E_EXPR_TOO_LONG", limit=policy.MAX_EXPR_CHARS)
    tokens = []
    pos = 0
    n = len(text)
    while pos < n:
        m = _TOKEN_RE.match(text, pos)
        if not m:
            ch = text[pos]
            if ch.isalpha():
                end = pos
                while end < n and (text[end].isalnum() or text[end] in "_‌"):
                    end += 1
                raise ExprError("non-ASCII name in expression", code="E_EXPR_NON_ASCII_NAME",
                                pos=pos, name=text[pos:end])
            raise ExprError(f"unexpected character {ch!r}", code="E_EXPR_TOKEN", pos=pos, char=ch)
        kind = m.lastgroup
        value = m.group()
        if kind != "WS":
            if kind == "POW":
                kind, value = "OP", "**"
            tokens.append(Token(kind, value, pos))
        pos = m.end()
    tokens.append(Token("END", "", n))
    return tokens


class _Parser:
    def __init__(self, tokens):
        self.toks = tokens
        self.i = 0
        self.nodes = 0
        self.depth = 0

    # -- helpers
    def peek(self):
        return self.toks[self.i]

    def next(self):
        t = self.toks[self.i]
        if t.type != "END":
            self.i += 1
        return t

    def _count(self, n=1):
        self.nodes += n
        if self.nodes > policy.MAX_EXPR_NODES:
            raise ExprError("expression is too complex", code="E_EXPR_TOO_COMPLEX", limit=policy.MAX_EXPR_NODES)

    def _enter(self):
        self.depth += 1
        if self.depth > policy.MAX_EXPR_DEPTH:
            raise ExprError("expression is nested too deeply", code="E_EXPR_TOO_COMPLEX",
                            limit=policy.MAX_EXPR_DEPTH)

    def _leave(self):
        self.depth -= 1

    def _is_op(self, t, *ops):
        return t.type == "OP" and t.value in ops

    # -- grammar
    def parse(self):
        if self.peek().type == "END":
            raise ExprError("empty expression", code="E_EXPR_EMPTY")
        node = self.expr()
        t = self.peek()
        if t.type != "END":
            if t.type == "RPAREN":
                raise ExprError("unmatched ')'", code="E_EXPR_PAREN_CLOSE", pos=t.pos)
            raise ExprError(f"unexpected {t.value!r}", code="E_EXPR_SYNTAX", pos=t.pos, found=t.value)
        return node

    def expr(self):
        self._enter()
        left = self.term()
        while self._is_op(self.peek(), "+", "-"):
            op = self.next().value
            right = self.term()
            self._count()
            left = ["bin", op, left, right]
        t = self.peek()
        if t.type in ("NUM", "NAME", "LPAREN"):
            raise ExprError("two values side by side - an operator is missing", code="E_EXPR_ADJACENT",
                            pos=t.pos, found=t.value)
        self._leave()
        return left

    def term(self):
        left = self.factor()
        while self._is_op(self.peek(), "*", "/"):
            op = self.next().value
            right = self.factor()
            self._count()
            left = ["bin", op, left, right]
        return left

    def factor(self):
        t = self.peek()
        if self._is_op(t, "+", "-"):
            self.next()
            self._enter()
            inner = self.factor()
            self._leave()
            if t.value == "-":
                self._count()
                return ["neg", inner]
            return inner
        return self.power()

    def power(self):
        base = self.atom()
        if self._is_op(self.peek(), "**"):
            self.next()
            self._enter()
            exponent = self.factor()
            self._leave()
            self._count()
            return ["bin", "**", base, exponent]
        return base

    def atom(self):
        t = self.next()
        if t.type == "NUM":
            try:
                value = float(t.value)
            except ValueError:
                raise ExprError("bad number", code="E_EXPR_NUMBER", pos=t.pos) from None
            if not math.isfinite(value) or abs(value) > policy.MAX_RESULT_ABS:
                raise ExprError("number too large", code="E_EXPR_NUMBER", pos=t.pos)
            self._count()
            return ["num", value]
        if t.type == "NAME":
            name = t.value.lower()
            if len(name) > _NAME_MAX:
                raise ExprError("name too long", code="E_EXPR_TOO_LONG", pos=t.pos, limit=_NAME_MAX)
            if self.peek().type == "LPAREN":
                if name not in FUNCTIONS:
                    raise ExprError(f"unknown function {name!r}", code="E_EXPR_UNKNOWN_FUNC", pos=t.pos, name=name)
                return self.call(name, t)
            if name in FUNCTIONS:
                raise ExprError(f"function name {name!r} used as a variable", code="E_EXPR_RESERVED_NAME",
                                pos=t.pos, name=name)
            self._count()
            if name in CONSTANTS:
                return ["const", name]
            return ["var", name]
        if t.type == "LPAREN":
            self._enter()
            inner = self.expr()
            self._leave()
            close = self.peek()
            if close.type == "RPAREN":
                self.next()
                return inner
            raise ExprError("missing ')'", code="E_EXPR_PAREN_OPEN", pos=close.pos)
        if t.type == "END":
            raise ExprError("expression ends unexpectedly", code="E_EXPR_SYNTAX_END", pos=t.pos)
        if t.type == "RPAREN":
            raise ExprError("unmatched ')'", code="E_EXPR_PAREN_CLOSE", pos=t.pos)
        raise ExprError(f"unexpected {t.value!r}", code="E_EXPR_SYNTAX", pos=t.pos, found=t.value)

    def call(self, name, name_tok):
        self.next()  # '('
        args = []
        lo, hi, _ = FUNCTIONS[name]
        if self.peek().type == "RPAREN":
            raise ExprError(f"{name}() needs arguments", code="E_EXPR_ARITY", pos=name_tok.pos, name=name)
        while True:
            args.append(self.expr())
            t = self.peek()
            if t.type == "COMMA":
                self.next()
                continue
            if t.type == "RPAREN":
                self.next()
                break
            if t.type == "END":
                raise ExprError("missing ')'", code="E_EXPR_PAREN_OPEN", pos=t.pos)
            raise ExprError(f"unexpected {t.value!r}", code="E_EXPR_SYNTAX", pos=t.pos, found=t.value)
        if not lo <= len(args) <= hi:
            raise ExprError(f"{name}() takes {lo}..{hi} arguments", code="E_EXPR_ARITY",
                            pos=name_tok.pos, name=name)
        self._count()
        return ["call", name, args]


def parse(text):
    """Strict parse; raises ExprError(code=E_EXPR_*)."""
    return _Parser(tokenize(text)).parse()


# -------------------------------------------------------------- analysis --

def variables(node):
    """Variable names in order of first appearance."""
    seen = []

    def walk(n):
        tag = n[0]
        if tag == "var":
            if n[1] not in seen:
                seen.append(n[1])
        elif tag == "neg":
            walk(n[1])
        elif tag == "bin":
            walk(n[2])
            walk(n[3])
        elif tag == "call":
            for a in n[2]:
                walk(a)

    walk(node)
    return seen


def functions_used(node):
    found = set()

    def walk(n):
        tag = n[0]
        if tag == "call":
            found.add(n[1])
            for a in n[2]:
                walk(a)
        elif tag == "neg":
            walk(n[1])
        elif tag == "bin":
            walk(n[2])
            walk(n[3])

    walk(node)
    return sorted(found)


def constants_used(node):
    found = set()

    def walk(n):
        tag = n[0]
        if tag == "const":
            found.add(n[1])
        elif tag == "neg":
            walk(n[1])
        elif tag == "bin":
            walk(n[2])
            walk(n[3])
        elif tag == "call":
            for a in n[2]:
                walk(a)

    walk(node)
    return sorted(found)


def count_nodes(node):
    tag = node[0]
    if tag in ("num", "const", "var"):
        return 1
    if tag == "neg":
        return 1 + count_nodes(node[1])
    if tag == "bin":
        return 1 + count_nodes(node[2]) + count_nodes(node[3])
    return 1 + sum(count_nodes(a) for a in node[2])


# -------------------------------------------------------- reference eval --

def evaluate(node, env):
    """Tree-walking reference evaluator. Raises mathcore.MathFailure on
    numeric failures. `env` maps variable name -> float."""
    tag = node[0]
    if tag == "num":
        return node[1]
    if tag == "const":
        return CONSTANTS[node[1]]
    if tag == "var":
        if node[1] not in env:
            raise mathcore.MathFailure("bad_input", f"missing input: {node[1]}")
        return mathcore._check(env[node[1]])
    if tag == "neg":
        return -evaluate(node[1], env)
    if tag == "bin":
        op = node[1]
        a = evaluate(node[2], env)
        b = evaluate(node[3], env)
        if op == "+":
            return a + b
        if op == "-":
            return a - b
        if op == "*":
            return a * b
        if op == "/":
            return mathcore.div(a, b)
        return mathcore.power(a, b)
    name = node[1]
    fn = getattr(mathcore, FUNCTIONS[name][2])
    return fn(*[evaluate(a, env) for a in node[2]])


def evaluate_final(node, env):
    return mathcore.finite(evaluate(node, env))


# --------------------------------------------------------- code generation --

PARAM_PREFIX = "x_"


def to_source(node):
    """Python source text of the expression using only literals, the
    parameter names `x_<var>`, the operators + - * and the pre-bound helper
    calls `_sb_*`. Every binary node is parenthesised, so precedence in the
    generated text can never differ from the tree."""
    tag = node[0]
    if tag == "num":
        return repr(float(node[1]))
    if tag == "const":
        return repr(float(CONSTANTS[node[1]]))
    if tag == "var":
        return PARAM_PREFIX + node[1]
    if tag == "neg":
        return "(-" + to_source(node[1]) + ")"
    if tag == "bin":
        op = node[1]
        left, right = to_source(node[2]), to_source(node[3])
        if op in ("+", "-", "*"):
            return f"({left} {op} {right})"
        if op == "/":
            return f"_sb_div({left}, {right})"
        return f"_sb_power({left}, {right})"
    helper = "_sb_" + FUNCTIONS[node[1]][2]
    return helper + "(" + ", ".join(to_source(a) for a in node[2]) + ")"


def helper_names_used(node):
    """The `_sb_*` helper names the generated source of `node` references."""
    names = set()

    def walk(n):
        tag = n[0]
        if tag == "bin":
            if n[1] == "/":
                names.add("_sb_div")
            elif n[1] == "**":
                names.add("_sb_power")
            walk(n[2])
            walk(n[3])
        elif tag == "neg":
            walk(n[1])
        elif tag == "call":
            names.add("_sb_" + FUNCTIONS[n[1]][2])
            for a in n[2]:
                walk(a)

    walk(node)
    return sorted(names)
