"""
Extension runtime - run-time guards
===================================
The instrumented extension code (instrument.py) never touches Python's own operators and builtins directly where
those could be abused: it calls the functions built here. One `Budget` per call carries the work counter and the
deadline; every guard charges it. `make_runtime(budget, ctx)` returns the exact namespace an extension module sees -
there is no `__import__`, no `open`, no `getattr`, no `type`: if a name is not in this namespace it does not exist.

Work units: one loop step / call = 1; an operation that builds a sequence of n items costs 1 + n/8. So the total
amount of memory an extension can build in one call is bounded by its fuel, not just by the size of one value.
"""

import math
import time
import types

from . import limits
from .errors import LimitExceeded

# ---------------------------------------------------------------------------------- allowed attribute (method) names
STR_METHODS = ("lower", "upper", "strip", "lstrip", "rstrip", "split", "rsplit", "join", "replace", "startswith",
               "endswith", "find", "rfind", "index", "rindex", "count", "isdigit", "isalpha", "isalnum", "isspace",
               "isnumeric", "isdecimal", "islower", "isupper", "istitle", "title", "capitalize", "swapcase",
               "casefold", "splitlines", "partition", "rpartition", "removeprefix", "removesuffix")
LIST_METHODS = ("append", "extend", "insert", "pop", "remove", "index", "count", "sort", "reverse", "copy", "clear")
TUPLE_METHODS = ("index", "count")
DICT_METHODS = ("get", "keys", "values", "items", "pop", "setdefault", "update", "copy", "clear", "popitem")
SET_METHODS = ("add", "discard", "remove", "pop", "union", "intersection", "difference", "symmetric_difference",
               "issubset", "issuperset", "isdisjoint", "update", "copy", "clear")
INT_METHODS = ("bit_length",)
FLOAT_METHODS = ("is_integer",)
ALL_METHOD_NAMES = frozenset(STR_METHODS + LIST_METHODS + TUPLE_METHODS + DICT_METHODS + SET_METHODS + INT_METHODS + FLOAT_METHODS)

MATH_CONSTANTS = ("pi", "e", "tau", "inf", "nan")
MATH_FUNCTIONS = ("sqrt", "cbrt", "sin", "cos", "tan", "asin", "acos", "atan", "atan2", "sinh", "cosh", "tanh",
                  "exp", "expm1", "log", "log10", "log2", "log1p", "floor", "ceil", "trunc", "fabs", "hypot",
                  "degrees", "radians", "gcd", "lcm", "isqrt", "isfinite", "isnan", "isinf", "copysign", "fmod",
                  "isclose", "fsum", "pow", "factorial", "comb", "perm")
MATH_NAMES = frozenset(MATH_CONSTANTS + MATH_FUNCTIONS)

_TABLES = {
    str: {n: vars(str)[n] for n in STR_METHODS},
    list: {n: vars(list)[n] for n in LIST_METHODS},
    tuple: {n: vars(tuple)[n] for n in TUPLE_METHODS},
    dict: {n: vars(dict)[n] for n in DICT_METHODS},
    set: {n: vars(set)[n] for n in SET_METHODS},
    int: {n: vars(int)[n] for n in INT_METHODS},
    float: {n: vars(float)[n] for n in FLOAT_METHODS},
}
_SEQ = (str, list, tuple)
_GROWERS = frozenset(("append", "extend", "insert", "add", "update", "setdefault"))
_SIZED = (str, list, tuple, dict, set, frozenset, range)


class Budget:
    __slots__ = ("fuel", "ticks", "deadline", "clock")

    def __init__(self, fuel=limits.MAX_FUEL, seconds=limits.MAX_SECONDS, clock=time.monotonic):
        self.fuel = int(fuel)
        self.ticks = 0
        self.clock = clock
        self.deadline = clock() + float(seconds)

    def tick(self, n=1):
        self.fuel -= n
        if self.fuel < 0:
            raise LimitExceeded("fuel", "work budget exhausted")
        self.ticks += 1
        if not (self.ticks & 15) and self.clock() > self.deadline:
            raise LimitExceeded("time", "time budget exhausted")


class _Ctor:
    """A type name as the extension sees it: callable (guarded) and usable with `isinstance`."""
    __slots__ = ("real", "name", "types", "budget", "charge")

    def __init__(self, real, name, types_, budget, charge):
        self.real, self.name, self.types, self.budget, self.charge = real, name, types_, budget, charge

    def __call__(self, *args, **kw):
        result = self.real(*args, **kw)
        if self.charge:
            _charge(self.budget, result)
        return result


def _charge(budget, value):
    if isinstance(value, _SIZED):
        n = len(value)
        if n > limits.MAX_SEQ:
            raise LimitExceeded("size", "a value grew beyond the size limit")
        budget.tick(1 + (n >> 3))
    return value


def _math_namespace(budget):
    ns = {n: getattr(math, n) for n in MATH_NAMES if n not in ("factorial", "comb", "perm", "fsum")}

    def factorial(n):
        if type(n) is int and n > limits.MAX_FACTORIAL:
            raise LimitExceeded("size", "factorial argument too large")
        budget.tick(1 + (n >> 4 if type(n) is int and n > 0 else 0))
        return math.factorial(n)

    def comb(n, k):
        if type(n) is int and n > limits.MAX_FACTORIAL:
            raise LimitExceeded("size", "comb argument too large")
        return math.comb(n, k)

    def perm(n, k=None):
        if type(n) is int and n > limits.MAX_FACTORIAL:
            raise LimitExceeded("size", "perm argument too large")
        return math.perm(n, k)

    def fsum(iterable):
        return math.fsum(_iter(budget, iterable))
    ns.update(factorial=factorial, comb=comb, perm=perm, fsum=fsum)
    return types.SimpleNamespace(**ns)


def _iter(budget, iterable):
    for item in iterable:
        budget.tick(1)
        yield item


def make_runtime(budget, ctx=None, granted=frozenset()):
    """The namespace of one extension call (instrumentation hooks first, then the names user code may use)."""
    tick = budget.tick
    cap = limits.MAX_SEQ

    def check_len(n):
        if n > cap:
            raise LimitExceeded("size", "a value grew beyond the size limit")

    # ---- instrumentation hooks (names start with an underscore: user code cannot write such names) ----
    def hook_t(n=1):
        tick(n)

    def hook_it(iterable):
        for item in iterable:
            tick(1)
            yield item

    def hook_w(cond):
        tick(1)
        return cond

    def hook_f(text):
        if len(text) > cap:
            raise LimitExceeded("size", "text grew beyond the size limit")
        tick(1 + (len(text) >> 3))
        return text

    def hook_add(a, b):
        if type(a) in _SEQ and type(b) is type(a):
            n = len(a) + len(b)
            check_len(n)
            tick(1 + (n >> 3))
        return a + b

    def hook_mul(a, b):
        ta, tb = type(a), type(b)
        if (ta in _SEQ and tb in (int, bool)) or (tb in _SEQ and ta in (int, bool)):
            seq, count = (a, b) if ta in _SEQ else (b, a)
            n = len(seq) * max(int(count), 0) if len(seq) else 0
            check_len(n)
            tick(1 + (n >> 3))
        elif ta is int and tb is int and a.bit_length() + b.bit_length() > limits.MAX_INT_BITS:
            raise LimitExceeded("size", "integer too large")
        return a * b

    def hook_pow(a, b):
        if type(a) is int and type(b) is int and b > 0 and a not in (0, 1, -1):
            if b > limits.MAX_INT_BITS or a.bit_length() * b > limits.MAX_INT_BITS:
                raise LimitExceeded("size", "integer too large")
        return a ** b

    def hook_shl(a, b):
        if type(a) is int and type(b) is int and a and a.bit_length() + b > limits.MAX_INT_BITS:
            raise LimitExceeded("size", "integer too large")
        return a << b

    def hook_mod(a, b):
        if isinstance(a, str):
            raise TypeError("string % formatting is not available: use an f-string")
        return a % b

    def hook_or(a, b):
        if isinstance(a, (set, dict, frozenset)) and isinstance(b, (set, dict, frozenset)):
            n = len(a) + len(b)
            check_len(n)
            tick(1 + (n >> 3))
        return a | b

    def hook_iadd(a, b):
        if type(a) is list:
            items = b if isinstance(b, _SIZED) else list(hook_it(b))
            check_len(len(a) + len(items))
            tick(1 + (len(items) >> 3))
            a.extend(items)
            return a
        return hook_add(a, b)

    def hook_imul(a, b):
        result = hook_mul(a, b)
        if type(a) is list:
            a[:] = result
            return a
        return result

    def hook_ior(a, b):
        if type(a) is set and isinstance(b, (set, frozenset)):
            check_len(len(a) + len(b))
            tick(1 + (len(b) >> 3))
            a |= b
            return a
        if type(a) is dict and isinstance(b, dict):
            check_len(len(a) + len(b))
            tick(1 + (len(b) >> 3))
            a.update(b)
            return a
        return hook_or(a, b)

    def hook_m(obj, name, *args, **kw):
        table = _TABLES.get(type(obj))
        fn = table.get(name) if table is not None else None
        if fn is None:
            raise TypeError(f"method {name!r} is not available on this value")
        kind = type(obj)
        if kind is str:
            if name == "replace" and len(args) >= 2 and isinstance(args[0], str) and isinstance(args[1], str):
                if len(args[1]) > len(args[0]):
                    grown = (len(obj) // max(len(args[0]), 1) + 1) * (len(args[1]) - len(args[0])) + len(obj)
                    check_len(grown)
            elif name == "join" and len(args) == 1:
                items = list(hook_it(args[0]))
                total = sum(len(x) for x in items if isinstance(x, str)) + len(obj) * max(len(items) - 1, 0)
                check_len(total)
                args = (items,)
        elif name == "extend" and args and not isinstance(args[0], _SIZED):
            args = (list(hook_it(args[0])),)
        elif name == "sort":
            tick(1 + (len(obj) >> 2))
        elif name in ("update", "union") and args and not all(isinstance(a, _SIZED) for a in args):
            args = tuple(list(hook_it(a)) if not isinstance(a, _SIZED) else a for a in args)
        tick(1)
        result = fn(obj, *args, **kw)
        if name in _GROWERS and isinstance(obj, _SIZED):
            check_len(len(obj))
        if isinstance(result, _SIZED):
            _charge(budget, result)
        return result

    # ---- builtins the extension may use ----
    def r_range(*a):
        try:
            r = range(*a)
            n = len(r)
        except OverflowError:
            raise LimitExceeded("size", "range too large") from None
        check_len(n)
        tick(1 + (n >> 3))
        return r

    def r_min(*a, **kw):
        return min(*((hook_it(a[0]),) if len(a) == 1 else a), **kw)

    def r_max(*a, **kw):
        return max(*((hook_it(a[0]),) if len(a) == 1 else a), **kw)

    def r_sum(iterable, start=0):
        if type(start) not in (int, float):
            raise TypeError("sum() start must be a number")
        return sum(hook_it(iterable), start)

    def r_sorted(iterable, key=None, reverse=False):
        items = list(hook_it(iterable))
        check_len(len(items))
        tick(1 + (len(items) >> 2))
        return sorted(items, key=key, reverse=bool(reverse))

    def r_any(iterable):
        return any(hook_it(iterable))

    def r_all(iterable):
        return all(hook_it(iterable))

    def r_round(x, ndigits=None):
        if ndigits is None:
            return round(x)
        if type(ndigits) is not int or not -30 <= ndigits <= 30:
            raise ValueError("round(): ndigits must be an integer between -30 and 30")
        return round(x, ndigits)

    def r_isinstance(value, spec):
        specs = spec if type(spec) is tuple else (spec,)
        real = []
        for s in specs:
            if not isinstance(s, _Ctor):
                raise TypeError("isinstance() needs int, float, str, bool, list, tuple, dict or set")
            real.extend(s.types)
        return isinstance(value, tuple(real))

    def r_chr(i):
        return chr(i)

    ns = {
        "len": len, "abs": abs, "divmod": divmod, "ord": ord, "chr": r_chr, "reversed": reversed,
        "enumerate": enumerate, "zip": zip, "map": map, "filter": filter,
        "range": r_range, "min": r_min, "max": r_max, "sum": r_sum, "sorted": r_sorted, "any": r_any, "all": r_all,
        "round": r_round, "isinstance": r_isinstance,
        "int": _Ctor(int, "int", (int,), budget, False), "float": _Ctor(float, "float", (float,), budget, False),
        "bool": _Ctor(bool, "bool", (bool,), budget, False), "str": _Ctor(str, "str", (str,), budget, True),
        "list": _Ctor(list, "list", (list,), budget, True), "tuple": _Ctor(tuple, "tuple", (tuple,), budget, True),
        "dict": _Ctor(dict, "dict", (dict,), budget, True), "set": _Ctor(set, "set", (set, frozenset), budget, True),
        "ValueError": ValueError, "TypeError": TypeError, "ZeroDivisionError": ZeroDivisionError,
        "KeyError": KeyError, "IndexError": IndexError, "Exception": Exception, "OverflowError": OverflowError,
        "math": _math_namespace(budget),
        "True": True, "False": False, "None": None,
    }

    def pad_left(text, width, fill=" "):
        _pad_check(text, width, fill)
        return str(text).rjust(width, fill)

    def pad_right(text, width, fill=" "):
        _pad_check(text, width, fill)
        return str(text).ljust(width, fill)

    def _pad_check(text, width, fill):
        if type(width) is not int or not 0 <= width <= 500 or not isinstance(fill, str) or len(fill) != 1:
            raise ValueError("pad_left/pad_right: width must be 0..500 and fill one character")
        tick(1 + (width >> 3))
    ns["pad_left"], ns["pad_right"] = pad_left, pad_right

    if ctx is not None:
        if limits.PERM_CLOCK in granted:
            ns["clock_now"] = lambda: float(ctx.clock())
        if limits.PERM_STORAGE in granted:
            ns["store_get"] = lambda key, default=None: ctx.store_get(key, default)
            ns["store_put"] = lambda key, value: ctx.store_put(key, value)
            ns["store_delete"] = lambda key: ctx.store_delete(key)
            ns["store_keys"] = lambda: list(ctx.store_keys())
        if limits.PERM_NETWORK in granted:
            ns["web_fetch_text"] = lambda url: _charge(budget, str(ctx.web_fetch_text(url)))
    hooks = {"_t": hook_t, "_it": hook_it, "_w": hook_w, "_f": hook_f, "_add": hook_add, "_mul": hook_mul,
             "_pow": hook_pow, "_shl": hook_shl, "_mod": hook_mod, "_or": hook_or, "_iadd": hook_iadd,
             "_imul": hook_imul, "_ior": hook_ior, "_m": hook_m}
    return hooks, ns
