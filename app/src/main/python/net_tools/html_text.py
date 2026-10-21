"""
net_tools.html_text - readable text from an HTML page
=====================================================
`html_to_text(html, max_chars) -> (title, text)` uses the stdlib
`html.parser.HTMLParser` (character references are converted). It drops
script/style/noscript/template/svg content and the `<head>` (except the page
title), turns block-level tags into line breaks, collapses whitespace, never
raises for broken markup and never returns more than `max_chars` characters.
Persian text, including the zero-width non-joiner, is kept as it is: only
whitespace runs and control characters are changed.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import List, Tuple

__all__ = ["html_to_text", "collapse_text"]

_MAX_INPUT_CHARS = 1_000_000
_MAX_TITLE = 300
_DROPPED = frozenset({"script", "style", "noscript", "template", "svg"})
_BLOCKS = frozenset({
    "p", "div", "br", "li", "ul", "ol", "tr", "table", "h1", "h2", "h3", "h4", "h5", "h6", "section",
    "article", "header", "footer", "nav", "aside", "blockquote", "pre", "hr", "form", "fieldset",
    "figure", "figcaption", "main", "dl", "dt", "dd", "address", "details", "summary", "caption",
})
_CELLS = frozenset({"td", "th"})
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_SPACE_RE = re.compile(r"[^\S\n]+")
_BLANKS_RE = re.compile(r"\n{3,}")
_TAG_RE = re.compile(r"<[^>]*>")


def collapse_text(text: str) -> str:
    """Collapse runs of blanks, trim every line and keep at most one empty line in a row."""
    text = _CONTROL_RE.sub("", text.replace("\r\n", "\n").replace("\r", "\n"))
    text = _SPACE_RE.sub(" ", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    return _BLANKS_RE.sub("\n\n", text).strip()


class _Extractor(HTMLParser):
    def __init__(self, max_chars: int) -> None:
        super().__init__(convert_charrefs=True)
        self._budget = max_chars * 2 + 64  # collapse shrinks text, so collect a little more than needed
        self._used = 0
        self._parts: List[str] = []
        self._title: List[str] = []
        self._dropped = 0
        self._in_head = False
        self._in_title = False
        self._title_done = False

    def _add(self, text: str) -> None:
        if self._used < self._budget:
            self._parts.append(text)
            self._used += len(text)

    def handle_starttag(self, tag, attrs):
        if tag in _DROPPED:
            self._dropped += 1
            return
        if tag == "head":
            self._in_head = True
        elif tag == "body":
            self._in_head = False
        elif tag == "title" and not self._dropped and not self._title_done:
            self._in_title = True
        elif tag in _BLOCKS:
            self._add("\n")
        elif tag in _CELLS:
            self._add(" ")

    def handle_startendtag(self, tag, attrs):
        if tag in _DROPPED:
            return  # self-closing: nothing to drop
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag in _DROPPED:
            if self._dropped:
                self._dropped -= 1
            return
        if tag == "head":
            self._in_head = False
        elif tag == "title":
            if self._in_title:
                self._in_title = False
                self._title_done = True
        elif tag in _BLOCKS:
            self._add("\n")
        elif tag in _CELLS:
            self._add(" ")

    def handle_data(self, data):
        if self._dropped:
            return
        if self._in_title:
            self._title.append(data)
            return
        if self._in_head:
            return
        self._add(data)

    def result(self, max_chars: int) -> Tuple[str, str]:
        title = collapse_text(" ".join(self._title).replace("\n", " "))[:_MAX_TITLE]
        return title, collapse_text("".join(self._parts))[:max_chars]


def html_to_text(html: str, max_chars: int) -> Tuple[str, str]:
    """(title, text) of an HTML string; bounded by `max_chars`; never raises."""
    if not isinstance(html, str):
        raise TypeError("html must be a string")
    if not isinstance(max_chars, int) or isinstance(max_chars, bool) or max_chars < 1:
        raise ValueError("max_chars must be a positive integer")
    html = html[:_MAX_INPUT_CHARS]
    parser = _Extractor(max_chars)
    try:
        parser.feed(html)
        parser.close()
        return parser.result(max_chars)
    except Exception:  # truly broken input: fall back to a plain tag stripper
        plain = collapse_text(_TAG_RE.sub(" ", html))
        return "", plain[:max_chars]
