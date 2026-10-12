"""
Self-Builder - math primitives
==============================
The few numeric operations that generated capability modules and the
reference expression evaluator share. They are plain, total functions over
floats: every one either returns a finite float or raises `MathFailure` with
a stable `code`. Generated code never imports anything - the sandbox hands
these (and only these) in as pre-bound helper names (see helpers.py).

`+`, `-` and `*` are left to Python's own float operators; a result that
overflowed to inf/nan is caught by `finite()` at the end of every capability
call (and by every primitive below, which refuses non-finite arguments).
"""

import math

from . import policy

MAX_POW_EXPONENT = 64.0


class MathFailure(ArithmeticError):
    """A numeric failure with a stable code:
    division_by_zero | domain | overflow | bad_power | bad_input"""

    def __init__(self, code, detail=""):
        super().__init__(detail or code)
        self.code = code
        self.detail = detail or code


def _check(x):
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        raise MathFailure("bad_input", "number expected")
    f = float(x)
    if not math.isfinite(f):
        raise MathFailure("overflow", "non-finite intermediate value")
    return f


def finite(x):
    """The final result of a capability call: finite and not absurdly large."""
    f = float(x)
    if not math.isfinite(f) or abs(f) > policy.MAX_RESULT_ABS:
        raise MathFailure("overflow", "result is not a finite number")
    return f


def div(a, b):
    a, b = _check(a), _check(b)
    if b == 0.0:
        raise MathFailure("division_by_zero", "division by zero")
    return a / b


def power(a, b):
    a, b = _check(a), _check(b)
    if abs(b) > MAX_POW_EXPONENT:
        raise MathFailure("bad_power", "exponent magnitude above limit")
    if a == 0.0 and b < 0.0:
        raise MathFailure("division_by_zero", "zero raised to a negative power")
    if a < 0.0 and b != math.floor(b):
        raise MathFailure("domain", "negative base with a fractional exponent")
    try:
        return finite(a ** b)
    except OverflowError:
        raise MathFailure("overflow", "power overflow") from None


def sqrt(x):
    x = _check(x)
    if x < 0.0:
        raise MathFailure("domain", "square root of a negative number")
    return math.sqrt(x)


def absolute(x):
    return abs(_check(x))


def minimum(*xs):
    return min(_check(x) for x in xs)


def maximum(*xs):
    return max(_check(x) for x in xs)


def floor(x):
    return float(math.floor(_check(x)))


def ceil(x):
    return float(math.ceil(_check(x)))


def round_to(x, digits=0.0):
    x = _check(x)
    d = _check(digits)
    if d != math.floor(d) or abs(d) > 12:
        raise MathFailure("domain", "digits must be a whole number up to 12")
    return float(round(x, int(d)))


def ln(x):
    x = _check(x)
    if x <= 0.0:
        raise MathFailure("domain", "logarithm of a non-positive number")
    return math.log(x)


def log10(x):
    x = _check(x)
    if x <= 0.0:
        raise MathFailure("domain", "logarithm of a non-positive number")
    return math.log10(x)


def exp(x):
    x = _check(x)
    if x > 700.0:
        raise MathFailure("overflow", "exp overflow")
    return math.exp(x)


def sin(x):
    return math.sin(_check(x))


def cos(x):
    return math.cos(_check(x))


def tan(x):
    r = math.tan(_check(x))
    if not math.isfinite(r) or abs(r) > 1e15:
        raise MathFailure("domain", "tangent is undefined here")
    return r


def number_input(inputs, name):
    """A named numeric input of a capability call (bool and non-numbers refused)."""
    if not isinstance(inputs, dict) or name not in inputs:
        raise MathFailure("bad_input", f"missing input: {name}")
    return _check(inputs[name])
