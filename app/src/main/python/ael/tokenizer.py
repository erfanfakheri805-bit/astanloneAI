"""
AEL Tokenizer
==============
AEL (Adaptive Evolution Language) is the small internal instruction
language that will eventually be used to teach and upgrade the AI from
inside the application. This is the foundation stage: a simple line-based
grammar, tokenized with a basic scanner.

Foundation grammar (kept intentionally small):

    TEACH <name> IS <free text description>
    RELATE <name> TO <name> AS <relation_type>
    SKILL <name> RESPONDS TO <kw1,kw2,...> WITH <free text response>
    ASK <name>
    UPGRADE <name> IS <free text description>
    ROLLBACK <version_id>

Stage 6 adds one more statement, RULE, for structured-rule teaching (see
reasoning/rule_registry.py). It stays a single line, like every other AEL
statement - the whole tokenizer/parser is line-based (parse_program below
splits on newlines before anything else touches a line), so a multi-line
`RULE ... IF ... THEN ...` block would need a different parsing strategy
entirely. AND-joined conditions on one line give the same expressive
power (multiple premises) without that:

    RULE <name> IF <var> <relation> <var> (AND <var> <relation> <var>)* THEN <var> <relation> <var>

    e.g. RULE is_a_used_for IF X IS_A B AND B USED_FOR C THEN X USED_FOR C

Tokens are simple (type, value) pairs. Free-text segments (after IS / WITH)
are captured as a single TEXT token rather than being split further -
this keeps the tokenizer simple while still giving the parser clean,
unambiguous input. RULE/IF/THEN/AND never trigger free-text capture -
every field in a RULE statement is a structured identifier (a variable
name or a relation type), never prose.
"""

import re

KEYWORDS = {
    "TEACH", "IS", "RELATE", "TO", "AS", "SKILL", "RESPONDS", "WITH",
    "ASK", "UPGRADE", "ROLLBACK", "RULE", "IF", "THEN", "AND",
}

_token_pattern = re.compile(r"""
    (?P<KEYWORD>\bTEACH\b|\bIS\b|\bRELATE\b|\bTO\b|\bAS\b|\bSKILL\b|\bRESPONDS\b|\bWITH\b
               |\bASK\b|\bUPGRADE\b|\bROLLBACK\b|\bRULE\b|\bIF\b|\bTHEN\b|\bAND\b)
    | (?P<IDENT>[A-Za-z0-9_\-]+(?:,[A-Za-z0-9_\-]+)*)
    | (?P<WS>\s+)
""", re.VERBOSE)


class Token:
    def __init__(self, type_, value):
        self.type = type_
        self.value = value

    def __repr__(self):
        return f"Token({self.type}, {self.value!r})"


def tokenize(line):
    """Tokenize a single AEL statement.

    Splits the line into KEYWORD / IDENT tokens up until the first
    'free text' marker (IS / WITH), after which the remainder of the
    line is captured verbatim as a single TEXT token. This matches the
    grammar's design: structure first, free-form content last.
    """
    line = line.strip()
    if not line:
        return []

    tokens = []
    pos = 0
    free_text_markers = {"IS", "WITH"}

    while pos < len(line):
        match = _token_pattern.match(line, pos)
        if not match:
            raise ValueError(f"AEL tokenizer error near: {line[pos:pos + 20]!r}")
        pos = match.end()
        if match.lastgroup == "WS":
            continue
        value = match.group()
        if match.lastgroup == "KEYWORD":
            tokens.append(Token(value.upper(), value.upper()))
            if value.upper() in free_text_markers:
                remainder = line[pos:].strip()
                if remainder:
                    tokens.append(Token("TEXT", remainder))
                pos = len(line)
        else:
            tokens.append(Token("IDENT", value))

    return tokens
