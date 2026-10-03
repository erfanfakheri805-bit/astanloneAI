"""Prompt 719-C - test-support helper (not a test module).

Prompt 719-C adds exactly two things to `agent/agent_loop.py`: three import lines and ONE new method, `execute_routed_step`.
The older Section 6 guards (Prompts 712-718) pin the pre-719-C bytes of that file. Instead of weakening those pins, they read the
file through `baseline_bytes()` below, which removes exactly the sanctioned additions (nothing else) and so reproduces the frozen
pre-719-C bytes. If anything other than the sanctioned additions changed, the reconstructed bytes differ and the pins still fail.
"""
import os

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AGENT_LOOP_REL = "agent/agent_loop.py"
SANCTIONED_IMPORT_LINES = (
    "from planning.tool_step_dispatch import resolve_tool_step_dispatch\n",
    "from .tool_step_intent import build_tool_step_intent\n",
    "from .tool_step_runner import run_tool_step_intent\n",
)
METHOD_START = "    def execute_routed_step("
METHOD_END = "    def _finish(\n"


def current_text():
    with open(os.path.join(PY_ROOT, "agent", "agent_loop.py"), encoding="utf-8", newline="") as fh:
        return fh.read()


def split_additions(text):
    """Return (baseline_text, method_source) after removing the sanctioned imports and the one new method."""
    for line in SANCTIONED_IMPORT_LINES:
        if text.count(line) != 1:
            raise AssertionError("sanctioned import line missing or duplicated: " + line.strip())
        text = text.replace(line, "")
    if text.count(METHOD_START) != 1 or text.count(METHOD_END) != 1:
        raise AssertionError("execute_routed_step anchor missing or duplicated")
    start, end = text.index(METHOD_START), text.index(METHOD_END)
    if not start < end:
        raise AssertionError("execute_routed_step must sit directly before _finish")
    return text[:start] + text[end:], text[start:end]


def baseline_text():
    return split_additions(current_text())[0]


def baseline_bytes():
    return baseline_text().encode("utf-8")


def method_source():
    return split_additions(current_text())[1]


def file_bytes(rel):
    """Bytes of a production file; the Agent Loop is returned without the sanctioned 719-C additions."""
    if rel.replace(os.sep, "/") == AGENT_LOOP_REL:
        return baseline_bytes()
    with open(os.path.join(PY_ROOT, rel), "rb") as fh:
        return fh.read()


def read_text(path):
    """Text of a production file for the older source-scanning guards. Only `agent/agent_loop.py` is special-cased (returned without
    the sanctioned 719-C additions); every other path is read exactly as before."""
    absolute = path if os.path.isabs(path) else os.path.join(PY_ROOT, path)
    if os.path.relpath(absolute, PY_ROOT).replace(os.sep, "/") == AGENT_LOOP_REL:
        return baseline_text()
    with open(absolute, encoding="utf-8") as fh:
        return fh.read()
