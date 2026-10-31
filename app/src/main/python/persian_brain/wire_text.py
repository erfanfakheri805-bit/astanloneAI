"""
persian_brain.wire_text - multi-line text that has to cross the chat route intact
================================================================================
Every message the page sends is folded by the core (`InputSystem.normalize`) before any skill or the Persian brain sees
it: ALL white space - newlines, tabs, runs of spaces - becomes ONE space. That is right for a sentence and fatal for a
pack in its text form (`=== PACK code.v1 ===`): its structure is line based and the Python inside it depends on its
indentation. (The core is one of the files this project keeps byte-identical, so the fix lives at both ends of the road.)

So the page (interface/static/i18n.js, `protectPackage`) sends a message that holds such a pack as ONE line that has no
white space left to fold:

    === ESCAPED TEXT v1 === <body>

The body is the original text with

    \\            ->  \\\\             (so the escapes below are never ambiguous)
    newline       ->  \\n      tab ->  \\t      carriage return ->  \\r
    any other white-space character (U+00A0, U+2028 ...)  ->  \\uXXXX      (four lower-case hex digits)
    a space that touches another space, or either end of the text  ->  \\s

What stays literal is a single space between two other characters, and folding does not change that. `decode` undoes
the whole thing and `PersianBrain.respond` calls it first, so everything below the brain (the pack reader, the
teacher, the language model) sees exactly the text the user pasted. A text that does not start with the mark is
returned as it is.

`encode` is the reference implementation of the page's encoder: tests/test_wire_text_prompt958.py runs the page's
JavaScript and this function over the same texts and demands identical output, and runs the core's own folding
over the result to prove that nothing is lost.
"""

import re

MARK = "=== ESCAPED TEXT v1 ==="

# Every character `str.split()` treats as white space, except the plain space (a run of spaces has its own rule below).
# A test checks this class against all of Unicode, so a character that would be folded can never slip through.
_WHITE = re.compile("[\t\n\x0b\x0c\r\x1c-\x1f\x85\xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]")
_SPACES = re.compile(" +")
_ESCAPE = re.compile(r"\\(u[0-9a-fA-F]{4}|[\\ntrs])")

_SHORT = {"\n": "\\n", "\t": "\\t", "\r": "\\r"}
_LONG = {"n": "\n", "t": "\t", "r": "\r", "s": " ", "\\": "\\"}


def _white(match):
    ch = match.group(0)
    return _SHORT.get(ch) or "\\u%04x" % ord(ch)


def _spaces(match):
    run = match.group(0)
    if len(run) == 1 and 0 < match.start() and match.end() < len(match.string):
        return run                                         # one space between two other characters: nothing can fold it
    return "\\s" * len(run)


def encode(text):
    """The one-line form of `text` that the core's whitespace folding leaves exactly as it is."""
    body = text.replace("\\", "\\\\")
    body = _WHITE.sub(_white, body)
    body = _SPACES.sub(_spaces, body)
    return MARK + " " + body if body else MARK


def _unescape(match):
    code = match.group(1)
    if code[0] == "u" and len(code) == 5:
        return chr(int(code[1:], 16))
    return _LONG[code]


def is_encoded(text):
    """True when `text` starts with the mark as a word of its own."""
    if not isinstance(text, str):
        return False
    head = text.lstrip()
    return head.startswith(MARK) and (len(head) == len(MARK) or head[len(MARK)].isspace())


def decode(text):
    """The original text of an `encode` result (folded or not); any other text is returned unchanged."""
    if not is_encoded(text):
        return text
    body = text.lstrip()[len(MARK):]
    if body.startswith(" "):
        body = body[1:]
    return _ESCAPE.sub(_unescape, body.rstrip(" \t\r\n"))
