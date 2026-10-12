"""
Self-Builder - failure analysis and safe repair
===============================================
When a build attempt fails, the Self-Builder does not just give up and does
not guess freely: it classifies the failure by its stable code, looks up the
(small, fixed) list of repairs that are known to be safe for that class, applies
at most one, and re-runs the whole pipeline (validate -> test). Every attempt,
failure class and repair is recorded in the upgrade log.

Repair classes
--------------
Expression (formula archetype), triggered by the strict parser's error code:

  normalize_operators      × ÷ − ^ ٫ ، π √ ² ³ and full-width forms -> ASCII grammar        (safe)
  word_operators           "ضرب در" "تقسیم بر" "به توان" "منهای" "به علاوه" -> operators     (safe)
  map_identifiers          non-ASCII variable names -> v1, v2, ... (labels are kept)        (safe)
  implicit_multiplication  "2r", "2(x+1)", "(a)(b)", "r(x+1)" -> explicit "*"               (safe;
                           a longer unknown name before "(" such as log(x) is a function, not a product)
  balance_parentheses      append missing ")" at the end / drop extra trailing ")"          (guess)

Test-driven, after the sandbox suite failed:

  reorder_variables        a user example given positionally only passes with another
                           variable order -> re-order the formula's inputs                   (guess, verified by the example)

`safe` repairs change notation only. A `guess` repair is only accepted when a
user-supplied example verifies the result, otherwise the user is asked to
confirm the reading. Failures with no known safe repair (an example that
contradicts the formula, a generated-code fault, a policy violation) are NOT
repaired: nothing is applied and the failure is recorded.
"""

import itertools
import re

from . import expr as expr_mod
from . import fa_text, policy

# ----------------------------------------------------------------- helpers --

_FA_DIGIT_TABLE = {ord(c): str(i) for i, c in enumerate("۰۱۲۳۴۵۶۷۸۹")}
_AR_DIGIT_TABLE = {ord(c): str(i) for i, c in enumerate("٠١٢٣٤٥٦٧٨٩")}


def ascii_digits(text):
    """Persian/Arabic digits and separators -> ASCII, nothing else touched."""
    s = str(text).translate(_FA_DIGIT_TABLE).translate(_AR_DIGIT_TABLE)
    return s.replace("٫", ".").replace("٬", "")


_OP_MAP = {
    "×": "*", "✕": "*", "✖": "*", "⋅": "*", "·": "*", "∙": "*", "＊": "*", "✱": "*",
    "÷": "/", "∕": "/", "⁄": "/", "／": "/",
    "−": "-", "–": "-", "—": "-", "‒": "-", "➖": "-", "－": "-",
    "＋": "+", "➕": "+",
    "^": "**", "،": ",", "，": ",",
    "（": "(", "）": ")", "［": "(", "］": ")", "[": "(", "]": ")", "{": "(", "}": ")",
    "²": "**2", "³": "**3", "⁴": "**4",
    "π": "pi", "Π": "pi",
}
_SQRT_RE = re.compile(r"√\s*(\([^()]*\)|[A-Za-z_0-9.]+)")
_WORD_OPS = (
    (re.compile(r"(?<![\w])ضرب\s*در(?![\w])"), " * "),
    (re.compile(r"(?<![\w])ضربدر(?![\w])"), " * "),
    (re.compile(r"(?<![\w])تقسیم\s*بر(?![\w])"), " / "),
    (re.compile(r"(?<![\w])به\s*توان(?![\w])"), " ** "),
    (re.compile(r"(?<![\w])توان(?![\w])"), " ** "),
    (re.compile(r"(?<![\w])منهای(?![\w])"), " - "),
    (re.compile(r"(?<![\w])(?:به\s*علاوه|بعلاوه)(?![\w])"), " + "),
    (re.compile(r"(?<![\w])ضرب(?![\w])"), " * "),
    (re.compile(r"(?<![\w])تقسیم(?![\w])"), " / "),
)
_LENIENT_RE = re.compile(
    r"""
    (?P<WS>\s+)
  | (?P<NUM>(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?)
  | (?P<NAME>[^\W\d][\w‌]*)
  | (?P<POW>\*\*)
  | (?P<OP>[+\-*/])
  | (?P<LPAREN>\()
  | (?P<RPAREN>\))
  | (?P<COMMA>,)
  | (?P<OTHER>.)
    """,
    re.VERBOSE,
)


def _collapse(text):
    return " ".join(text.split())


class RepairOutcome:
    __slots__ = ("repair_id", "risk", "before", "after", "labels", "note_fa")

    def __init__(self, repair_id, risk, before, after, labels, note_fa):
        self.repair_id = repair_id
        self.risk = risk
        self.before = before
        self.after = after
        self.labels = labels
        self.note_fa = note_fa

    @property
    def changed(self):
        return self.before != self.after

    def to_dict(self):
        return {"repair": self.repair_id, "risk": self.risk, "before": self.before, "after": self.after,
                "note": self.note_fa}


# ----------------------------------------------------------- the repairs ---

def normalize_operators(text, labels):
    s = text
    s = _SQRT_RE.sub(lambda m: "sqrt(" + m.group(1).strip("()") + ")", s)
    s = "".join(_OP_MAP.get(ch, ch) for ch in s)
    s = ascii_digits(s)
    # Remaining compatibility characters (full-width digits/letters...) -> NFKC
    import unicodedata
    s = unicodedata.normalize("NFKC", s)
    s = _collapse(s.replace("‌", " "))
    return RepairOutcome("normalize_operators", "safe", text, s, labels,
                         "نمادهای ریاضی به شکل استاندارد تبدیل شد")


def word_operators(text, labels):
    s = text.replace("‌", " ")
    for pattern, replacement in _WORD_OPS:
        s = pattern.sub(replacement, s)
    s = _collapse(s)
    return RepairOutcome("word_operators", "safe", text, s, labels,
                         "عملگرهای نوشته‌شده با کلمه (مثل «ضرب در») به نماد تبدیل شد")


def _is_factor_name(name, labels):
    """`a(b + c)` is a product when `a` is a one-letter variable (or a mapped
    Persian variable name). A longer unknown name before "(" - log(x), tanh(x),
    pow(a, b) - is almost certainly a function the grammar does not have: it is
    NOT silently turned into a multiplication (the build fails with the stable
    unknown-function code instead)."""
    if name.lower() in expr_mod.FUNCTIONS:
        return False
    return len(name) == 1 or name in (labels or {})


def implicit_multiplication(text, labels):
    tokens = [(m.lastgroup, m.group()) for m in _LENIENT_RE.finditer(text) if m.lastgroup != "WS"]
    out = []
    prev = None
    inserted = False
    for kind, value in tokens:
        if prev is not None:
            pkind, pvalue = prev
            insert = False
            if pkind == "NUM" and kind in ("NAME", "LPAREN"):
                insert = True
            elif pkind == "RPAREN" and kind in ("NAME", "LPAREN", "NUM"):
                insert = True
            elif pkind == "NAME" and kind == "LPAREN" and _is_factor_name(pvalue, labels):
                insert = True
            if insert:
                out.append("*")
                inserted = True
        out.append(value)
        prev = (kind, value)
    s = " ".join(out) if inserted else text   # nothing to add: report "unchanged", never a fake repair
    return RepairOutcome("implicit_multiplication", "safe", text, s, labels,
                         "علامت ضرب که بین عبارت‌ها نوشته نشده بود اضافه شد")


def balance_parentheses(text, labels):
    depth = 0
    broken = False
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth < 0:
                broken = True
                break
    s = text
    if not broken and depth > 0:
        s = text.rstrip() + ")" * depth
    elif broken:
        stripped = text.rstrip()
        extra = 0
        probe = stripped
        while probe.endswith(")") and extra < 8:
            probe = probe[:-1].rstrip()
            extra += 1
            d = 0
            ok = True
            for ch in probe:
                d += (ch == "(") - (ch == ")")
                if d < 0:
                    ok = False
                    break
            if ok and d == 0:
                s = probe
                break
    return RepairOutcome("balance_parentheses", "guess", text, s, labels,
                         "پرانتزهای ناهماهنگ در انتهای فرمول اصلاح شد")


def map_identifiers(text, labels):
    labels = dict(labels or {})
    taken = {n for n in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", text)} | set(labels)
    mapping = {}
    counter = 0

    def repl(m):
        nonlocal counter
        word = m.group(0)
        if word.isascii():
            return word
        k = fa_text.key(word)
        if k not in mapping:
            counter += 1
            name = f"v{counter}"
            while name in taken:
                counter += 1
                name = f"v{counter}"
            taken.add(name)
            mapping[k] = (name, word.replace("‌", "‌"))
        return mapping[k][0]

    s = re.sub(r"[^\W\d][\w‌]*", repl, text)
    for name, original in mapping.values():
        labels[name] = original
    return RepairOutcome("map_identifiers", "safe", text, s, labels,
                         "نام‌های فارسی متغیرها به نام‌های داخلی (v1، v2، …) نگاشت شد؛ نام فارسی برای نمایش حفظ شد")


REPAIRS = {
    "normalize_operators": normalize_operators,
    "word_operators": word_operators,
    "implicit_multiplication": implicit_multiplication,
    "balance_parentheses": balance_parentheses,
    "map_identifiers": map_identifiers,
}

# failure code -> repairs worth trying, in order
EXPRESSION_REPAIR_PLAN = {
    "E_EXPR_TOKEN": ("normalize_operators", "word_operators"),
    "E_EXPR_NON_ASCII_NAME": ("normalize_operators", "word_operators", "map_identifiers"),
    "E_EXPR_ADJACENT": ("implicit_multiplication",),
    "E_EXPR_UNKNOWN_FUNC": ("implicit_multiplication",),
    "E_EXPR_PAREN_OPEN": ("balance_parentheses",),
    "E_EXPR_PAREN_CLOSE": ("balance_parentheses",),
    "E_EXPR_SYNTAX": ("normalize_operators", "word_operators"),
}


def plan_for_error(code):
    """Repair ids the analyzer considers for a strict-parse error code."""
    return list(EXPRESSION_REPAIR_PLAN.get(code, ()))


def next_expression_repair(error_code, text, labels, applied):
    """First not-yet-applied repair for `error_code` that actually changes
    `text`. Returns a RepairOutcome or None (-> the failure is not repairable)."""
    for repair_id in plan_for_error(error_code):
        if repair_id in applied:
            continue
        outcome = REPAIRS[repair_id](text, labels)
        if outcome.changed:
            return outcome
    return None


# ------------------------------------------------------- test-failure side --

def classify_test_failures(report):
    """Analysis of a failed sandbox suite: which class of failure is it?

    example_mismatch   only user-supplied examples failed (the formula/units
                       and the user's own numbers disagree)
    sandbox_fault      the generated module raised/timed out/returned garbage
    reference_mismatch an automatic differential case failed (a generation
                       bug - never repaired, never applied)
    """
    failed = report.get("failed", [])
    if not failed:
        return {"class": "none", "names": []}
    names = [f["name"] for f in failed]
    if any(f.get("actual", {}).get("error") in ("exception", "timeout", "bad_output") for f in failed):
        return {"class": "sandbox_fault", "names": names}
    if all(f.get("source") == "user" for f in failed):
        return {"class": "example_mismatch", "names": names}
    return {"class": "reference_mismatch", "names": names}


def reorder_candidates(count, limit=24):
    """Variable permutations (identity excluded) tried by reorder_variables."""
    perms = [p for p in itertools.permutations(range(count)) if list(p) != list(range(count))]
    return perms[:limit]


def repair_note_reorder(order_labels):
    return "ترتیب متغیرها طوری عوض شد که با مثال شما بخواند: " + "، ".join(order_labels)
