"""
Self-Builder - sandbox helpers
==============================
The ONLY names a generated module can call other than its own functions.
The sandbox binds this dictionary into the module namespace before the module
body runs; the AST validator (validator.py) rejects any generated source that
calls something that is not in `HELPER_NAMES` or defined by the module itself.

Nothing here gives generated code access to files, the network, processes,
imports, the clock or randomness: every helper is a pure function over
numbers or text (see mathcore.py and textops.py).
"""

from . import mathcore, textops

HELPERS = {
    "_sb_div": mathcore.div,
    "_sb_power": mathcore.power,
    "_sb_sqrt": mathcore.sqrt,
    "_sb_absolute": mathcore.absolute,
    "_sb_minimum": mathcore.minimum,
    "_sb_maximum": mathcore.maximum,
    "_sb_floor": mathcore.floor,
    "_sb_ceil": mathcore.ceil,
    "_sb_round_to": mathcore.round_to,
    "_sb_ln": mathcore.ln,
    "_sb_log10": mathcore.log10,
    "_sb_exp": mathcore.exp,
    "_sb_sin": mathcore.sin,
    "_sb_cos": mathcore.cos,
    "_sb_tan": mathcore.tan,
    "_sb_finite": mathcore.finite,
    "_sb_number_input": mathcore.number_input,
    "_sb_text_input": textops.text_input,
}
for _op_id, _row in textops.OPS.items():
    HELPERS[textops.HELPER_PREFIX + _op_id] = _row[0]

HELPER_NAMES = frozenset(HELPERS)
