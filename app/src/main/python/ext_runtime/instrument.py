"""
Extension runtime - instrumentation
===================================
Rewrites a VALIDATED extension syntax tree so that every loop step, call and growth-capable operation goes through
the guards in guards.py (work/time budget, size limits). The rewrite keeps line numbers, so errors point at the
author's own lines. Imports are dropped here (the `math` namespace is injected by the runner instead) and type
annotations are stripped (they are never evaluated).

    for x in xs:            ->  for x in _it(xs):
    while cond:             ->  while _w(cond):
    a + b, a * b, a ** b    ->  _add(a, b), _mul(a, b), _pow(a, b)       (also <<, %, |)
    s.split(",")            ->  _m(s, "split", ",")                       (the only way to call a method)
    d[k] += v               ->  _a1 = d; _a2 = k; _a1[_a2] = _iadd(_a1[_a2], v)
    def f(...): body        ->  def f(...): _t(1); body
    f"..."                  ->  _f(f"...")
"""

import ast

_BINOP_HOOKS = {ast.Add: "_add", ast.Mult: "_mul", ast.Pow: "_pow", ast.LShift: "_shl", ast.Mod: "_mod", ast.BitOr: "_or"}
_AUG_HOOKS = {ast.Add: "_iadd", ast.Mult: "_imul", ast.Pow: "_pow", ast.LShift: "_shl", ast.Mod: "_mod", ast.BitOr: "_ior"}


def _name(ident, ctx=None):
    return ast.Name(id=ident, ctx=ctx or ast.Load())


def _call(hook, *args):
    return ast.Call(func=_name(hook), args=list(args), keywords=[])


def _is_math(node):
    return isinstance(node, ast.Name) and node.id == "math"


class Instrumenter(ast.NodeTransformer):
    def __init__(self):
        self.temp = 0

    def fresh(self):
        self.temp += 1
        return f"_a{self.temp}"

    # imports are replaced by the namespace the runner injects
    def visit_Import(self, node):
        return None

    visit_ImportFrom = visit_Import

    def visit_arg(self, node):
        node.annotation = None
        return node

    def visit_FunctionDef(self, node):
        self.generic_visit(node)
        node.returns = None
        node.body.insert(0, ast.copy_location(ast.Expr(value=_call("_t", ast.Constant(value=1))), node))
        return node

    def visit_Lambda(self, node):
        self.generic_visit(node)
        ticked = ast.Tuple(elts=[_call("_t", ast.Constant(value=1)), node.body], ctx=ast.Load())
        node.body = ast.Subscript(value=ticked, slice=ast.Constant(value=1), ctx=ast.Load())
        return node

    def visit_While(self, node):
        self.generic_visit(node)
        node.test = ast.copy_location(_call("_w", node.test), node.test)
        return node

    def visit_For(self, node):
        self.generic_visit(node)
        node.iter = ast.copy_location(_call("_it", node.iter), node.iter)
        return node

    def visit_comprehension(self, node):
        self.generic_visit(node)
        node.iter = ast.copy_location(_call("_it", node.iter), node.iter)
        return node

    def visit_BinOp(self, node):
        self.generic_visit(node)
        hook = _BINOP_HOOKS.get(type(node.op))
        if hook is None:
            return node
        return ast.copy_location(_call(hook, node.left, node.right), node)

    def visit_AnnAssign(self, node):
        self.generic_visit(node)
        return ast.copy_location(ast.Assign(targets=[node.target], value=node.value), node)

    def visit_AugAssign(self, node):
        self.generic_visit(node)
        hook = _AUG_HOOKS.get(type(node.op))
        if hook is None:
            return node
        t = node.target
        if isinstance(t, ast.Name):
            new = ast.Assign(targets=[_name(t.id, ast.Store())], value=_call(hook, _name(t.id), node.value))
            return ast.copy_location(new, node)
        obj, idx = self.fresh(), self.fresh()
        stmts = [
            ast.Assign(targets=[_name(obj, ast.Store())], value=t.value),
            ast.Assign(targets=[_name(idx, ast.Store())], value=t.slice),
            ast.Assign(targets=[ast.Subscript(value=_name(obj), slice=_name(idx), ctx=ast.Store())],
                       value=_call(hook, ast.Subscript(value=_name(obj), slice=_name(idx), ctx=ast.Load()), node.value)),
        ]
        return [ast.copy_location(s, node) for s in stmts]

    def visit_Call(self, node):
        self.generic_visit(node)
        f = node.func
        if isinstance(f, ast.Attribute) and not _is_math(f.value):
            return ast.copy_location(ast.Call(func=_name("_m"), args=[f.value, ast.Constant(value=f.attr)] + list(node.args),
                                              keywords=list(node.keywords)), node)
        return node

    def visit_FormattedValue(self, node):
        node.value = self.visit(node.value)          # the format spec is a constant: leave it alone
        return node

    def visit_JoinedStr(self, node):
        self.generic_visit(node)
        return ast.copy_location(_call("_f", node), node)


def instrument(tree):
    """Return a NEW instrumented tree (the validated tree is left untouched)."""
    import copy
    new = Instrumenter().visit(copy.deepcopy(tree))
    return ast.fix_missing_locations(new)
