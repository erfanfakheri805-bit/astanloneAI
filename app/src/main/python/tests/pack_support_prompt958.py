"""
Shared, DETERMINISTIC helpers for the Prompt-958 pack-system tests (not a test module itself).

Builds pack packages in the *text form* chat assistants write, cleans the process-wide state a pack leaves behind
(import hook, registry, imported pack modules) and gives a fake clock. Nothing here touches the network or the phone.
"""

import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

GREETER_SOURCE = '''VERSION = %(version)d


def register(api):
    def match(ctx):
        return "سلام دمو" in ctx.text

    def handle(ctx):
        return "سلام از بستهٔ دمو، نسخهٔ %%d" %% VERSION

    api.register_chat("greet", match, handle, stage="fallback")
%(extra)s
'''


class FakeClock:
    def __init__(self, start=1_700_000_000.0):
        self.now = float(start)

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += float(seconds)


def text_pack(pid="demo_greeter", version=1, source=None, title="سلام‌کنندهٔ آزمایشی", permissions="", replaces="",
              extra_files=None, entry=None, description="یک بستهٔ آزمایشی"):
    """The `=== PACK code.v1 ===` text form."""
    if source is None:
        source = GREETER_SOURCE % {"version": version, "extra": ""}
    lines = ["=== PACK code.v1 ===", "id: %s" % pid, "version: %d" % version, "title: %s" % title,
             "description: %s" % description]
    if permissions:
        lines.append("permissions: %s" % permissions)
    if replaces:
        lines.append("replaces: %s" % replaces)
    if entry:
        lines.append("entry: %s" % entry)
    lines += ["=== FILE %s/__init__.py ===" % pid, "", "=== FILE %s/main.py ===" % pid, source.rstrip("\n")]
    for path, body in (extra_files or {}).items():
        lines += ["=== FILE %s ===" % path, body.rstrip("\n")]
    lines.append("=== END PACK ===")
    return "\n".join(lines) + "\n"


def lang_pack(pid="fa_demo", version=1, qa=None, title="داده‌های آزمایشی"):
    qa = qa if qa is not None else [("پایتخت ایران کجاست | پایتخت ایران چیست", "تهران"),
                                    ("سلام | درود | سلام علیکم", "سلام! خوش آمدی.")]
    lines = ["=== PACK lang.v1 ===", "id: %s" % pid, "version: %d" % version, "title: %s" % title, "=== QA ==="]
    for questions, answer in qa:
        lines += ["q: %s" % questions, "a: %s" % answer]
    lines.append("=== END PACK ===")
    return "\n".join(lines) + "\n"


def ctx_for(api_or_none, text, brain=None):
    from pack_system.api import ChatContext
    return ChatContext(text, text, text.split(), api_or_none, brain)


def reset_process_state(*pack_ids):
    """Remove everything a test pack leaves in the process: import hook, registry, imported modules."""
    from pack_system import overlay
    from pack_system.registry import REGISTRY
    overlay.uninstall()
    REGISTRY.clear()
    REGISTRY.on_failure = None
    REGISTRY.bind(None)
    for pid in pack_ids:
        for name in [n for n in list(sys.modules) if n == pid or n.startswith(pid + ".")]:
            sys.modules.pop(name, None)
