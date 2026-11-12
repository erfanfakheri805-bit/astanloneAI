"""
pack_system.limits - the numbers, names and vocabularies of the pack system (one place)
=======================================================================================
A *pack* is the unit by which the app grows from the inside, without a new APK:

    code.v1   Python modules (new features, or replacements of non-protected modules). Runs inside the app with the
              app's own rights - so it is only ever installed after the user's explicit yes, after a static scan,
              versioned, verifiable by hash, revertible, and switched off automatically by "safe mode" if it breaks
              the start of the app.
    lang.v1   Persian language data (question -> answer entries, many phrasings per answer). Pure data.

The extension format `ext.v1` (restricted pure functions) stays as it is; it is the lightest way to add a feature.
"""

import re

PLATFORM_LEVEL = 958                         # what the packs may ask for in `min_platform`
CODE_SCHEMA = "code.v1"
LANG_SCHEMA = "lang.v1"
SCHEMAS = (CODE_SCHEMA, LANG_SCHEMA)

ID_RE = re.compile(r"^[a-z][a-z0-9_]{2,39}$")
PROPOSAL_RE = re.compile(r"^q[0-9a-f]{8,24}$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
MODULE_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*){0,5}$")
_SEGMENT = r"[a-z_][a-z0-9_]{0,39}"
FILE_PATH_RE = re.compile(r"^(?:%s/){0,5}%s\.(?:py|json|txt|md)$" % (_SEGMENT, _SEGMENT))

MAX_TEXT_BYTES = 1_600_000                   # one pasted package / one package file
MAX_FILES = 60
MAX_FILE_BYTES = 300_000
MAX_TOTAL_BYTES = 1_200_000
MAX_TITLE = 80
MAX_DESC = 600
MAX_NOTES = 1200
MAX_VERSION = 999_999
KEEP_VERSIONS = 6                            # versions kept on disk per pack (the active and last-good ones are never removed)
MAX_PENDING_PROPOSALS = 6
PROPOSAL_TTL_SECONDS = 24 * 3600
MAX_PACKS = 60

# lang.v1 data limits
MAX_QA = 4000
MAX_QUESTIONS_PER_ENTRY = 16
MAX_QUESTION_CHARS = 200
MAX_ANSWER_CHARS = 1500
MAX_LANG_BYTES = 1_200_000

# what a code pack may declare it uses (shown to the user before the yes)
PERMISSIONS = ("network", "android", "clipboard", "screen", "model", "teacher", "ui", "replace_core", "unsafe_native")
# these need a second, explicit confirmation word: they change the app itself, reach any Android class, or read and operate other apps
RISKY_PERMISSIONS = frozenset({"replace_core", "unsafe_native", "screen"})

# modules a pack may never replace (the approval gates, the audit/permission stores, the network policy, the extension
# sandbox, the pack system itself, the data store, the optional cloud brain - it holds the user's key and the privacy filter -
# and the seven files pinned by the project's frozen tests)
PINNED_MODULES = frozenset({
    "android_entry", "core.core", "ael.interpreter", "runtime_integration.bridge", "interface.server",
    "runtime_integration.runtime_core", "runtime_growth.runtime_growth_cycle"})
PROTECTED_PREFIXES = ("pack_system", "platform_boot", "net_tools", "ext_runtime", "brain_hub", "android_adapters",
                      "persian_brain.hub_", "memory", "platform_layer", "brain_v2")

# bootstrapping / safe mode
BOOT_GOOD_AFTER_SECONDS = 30.0               # a start that is still alive after this long is a good start
SAFE_MODE_AFTER_FAILED_STARTS = 2
MAX_PACK_FAILURES = 3                        # runtime errors of one pack's handlers before it is switched off
SELFTEST_SECONDS = 20.0
HANDLER_SECONDS = 45.0                       # one chat handler of a pack (a local model answer can take a while)


def is_protected(module):
    """True for a dotted module name no pack may replace."""
    if module in PINNED_MODULES:
        return True
    for prefix in PROTECTED_PREFIXES:
        if prefix.endswith("_"):
            if module.startswith(prefix):
                return True
        elif module == prefix or module.startswith(prefix + "."):
            return True
    return False
