"""
AEL Parser
===========
Converts a token stream (from tokenizer.py) into a structured
Instruction representation the interpreter can execute.

This is deliberately a small, explicit recursive-descent parser over a
tiny grammar - not a general-purpose language parser. Extending AEL with
new instruction types later means adding one more `_parse_x` method and
one more branch here, without touching the rest of the system.
"""

from .tokenizer import tokenize, Token


class Instruction:
    """Structured representation of a single parsed AEL instruction."""

    def __init__(self, kind, args):
        self.kind = kind        # e.g. "TEACH", "RELATE", "SKILL"
        self.args = args        # dict of parsed arguments

    def __repr__(self):
        return f"Instruction({self.kind}, {self.args})"

    def to_dict(self):
        return {"kind": self.kind, "args": self.args}


class AELSyntaxError(Exception):
    pass


def parse_line(line):
    """Parse a single line of AEL source into an Instruction, or None
    if the line is blank/not AEL at all."""
    tokens = tokenize(line)
    if not tokens:
        return None
    return _parse_tokens(tokens)


def _expect(tokens, idx, type_):
    if idx >= len(tokens) or tokens[idx].type != type_:
        got = tokens[idx].type if idx < len(tokens) else "EOF"
        raise AELSyntaxError(f"Expected {type_}, got {got}")
    return tokens[idx]


def _parse_tokens(tokens):
    head = tokens[0]

    if head.type == "TEACH":
        # TEACH <name> IS <text>
        name_tok = _expect(tokens, 1, "IDENT")
        _expect(tokens, 2, "IS")
        text_tok = _expect(tokens, 3, "TEXT")
        return Instruction("TEACH", {"name": name_tok.value, "description": text_tok.value})

    if head.type == "RELATE":
        # RELATE <a> TO <b> AS <relation>
        a_tok = _expect(tokens, 1, "IDENT")
        _expect(tokens, 2, "TO")
        b_tok = _expect(tokens, 3, "IDENT")
        _expect(tokens, 4, "AS")
        rel_tok = _expect(tokens, 5, "IDENT")
        return Instruction("RELATE", {
            "from": a_tok.value, "to": b_tok.value, "relation": rel_tok.value,
        })

    if head.type == "SKILL":
        # SKILL <name> RESPONDS TO <kw1,kw2> WITH <text>
        name_tok = _expect(tokens, 1, "IDENT")
        _expect(tokens, 2, "RESPONDS")
        _expect(tokens, 3, "TO")
        kw_tok = _expect(tokens, 4, "IDENT")
        _expect(tokens, 5, "WITH")
        text_tok = _expect(tokens, 6, "TEXT")
        keywords = [k.strip() for k in kw_tok.value.split(",") if k.strip()]
        return Instruction("SKILL", {
            "name": name_tok.value, "keywords": keywords, "response": text_tok.value,
        })

    if head.type == "ASK":
        # ASK <name>
        name_tok = _expect(tokens, 1, "IDENT")
        return Instruction("ASK", {"name": name_tok.value})

    if head.type == "UPGRADE":
        # UPGRADE <name> IS <text>
        name_tok = _expect(tokens, 1, "IDENT")
        _expect(tokens, 2, "IS")
        text_tok = _expect(tokens, 3, "TEXT")
        return Instruction("UPGRADE", {"name": name_tok.value, "description": text_tok.value})

    if head.type == "ROLLBACK":
        # ROLLBACK <version_id>
        id_tok = _expect(tokens, 1, "IDENT")
        return Instruction("ROLLBACK", {"version_id": id_tok.value})

    if head.type == "RULE":
        return _parse_rule(tokens)

    raise AELSyntaxError(f"Unknown AEL instruction starting with {head.type}")


def _parse_triple(tokens, idx):
    """Parse one (var_from, relation_type, var_to) IDENT-IDENT-IDENT
    triple starting at `idx`. Returns (triple, next_idx)."""
    var_from = _expect(tokens, idx, "IDENT").value
    relation = _expect(tokens, idx + 1, "IDENT").value
    var_to = _expect(tokens, idx + 2, "IDENT").value
    return (var_from, relation, var_to), idx + 3


def _parse_rule(tokens):
    # RULE <name> IF <triple> (AND <triple>)* THEN <triple>
    name_tok = _expect(tokens, 1, "IDENT")
    _expect(tokens, 2, "IF")

    conditions = []
    triple, idx = _parse_triple(tokens, 3)
    conditions.append(triple)

    while idx < len(tokens) and tokens[idx].type == "AND":
        triple, idx = _parse_triple(tokens, idx + 1)
        conditions.append(triple)

    _expect(tokens, idx, "THEN")
    conclusion, idx = _parse_triple(tokens, idx + 1)

    if idx != len(tokens):
        raise AELSyntaxError(f"Unexpected extra tokens after RULE conclusion: {tokens[idx:]}")

    return Instruction("RULE", {
        "name": name_tok.value, "conditions": conditions, "conclusion": conclusion,
    })


def parse_program(source):
    """Parse a multi-line AEL program into a list of Instructions,
    skipping blank lines and '#' comments."""
    instructions = []
    for raw_line in source.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        instructions.append(parse_line(line))
    return [i for i in instructions if i is not None]
