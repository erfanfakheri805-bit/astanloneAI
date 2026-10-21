"""
Extension runtime - fixed limits and closed allowlists
======================================================
Everything an extension may be, may ask for or may use is declared here, in
one place. The numbers are deliberately small: an extension is a tiny pure
function, not a program.
"""

EXT_SCHEMA = "ext.v1"
EXT_KIND = "extension"

# ---- manifest / package -----------------------------------------------------
MAX_PACKAGE_BYTES = 200_000        # a whole pasted extension package (JSON text)
MAX_SOURCE_BYTES = 64_000          # the extension's Python source
MAX_TITLE_CHARS = 80
MAX_DESCRIPTION_CHARS = 400
MAX_LABEL_CHARS = 60
MAX_INPUTS = 10
MAX_OUTPUTS = 10
MAX_TESTS = 24
MAX_TRIGGERS = 12
MAX_TRIGGER_CHARS = 200
MAX_PROVENANCE_CHARS = 300
MAX_TEXT_INPUT_CHARS = 20_000      # one text input handed to an extension
MAX_LIST_INPUT_ITEMS = 500

# ---- static validation --------------------------------------------------------
MAX_AST_NODES = 12_000
MAX_AST_DEPTH = 60
MAX_STRING_CONSTANT = 20_000
MAX_INT_CONSTANT_BITS = 4_000

# ---- run-time budget (per call) -------------------------------------------------
MAX_FUEL = 250_000                 # loop iterations / calls / helper uses
MAX_SECONDS = 2.0                  # wall clock per call
MAX_CALL_DEPTH = 120               # nested extension-defined calls
MAX_SEQ = 200_000                  # items of any list/str/tuple/dict/set an operation may create
MAX_INT_BITS = 50_000              # size of an integer an operation may create
MAX_FACTORIAL = 2_500
MAX_OUTPUT_BYTES = 40_000          # serialised result
MAX_OUTPUT_TEXT = 20_000
MAX_OUTPUT_LIST = 1_000
MAX_OUTPUT_DEPTH = 5
MAX_ERROR_DETAIL = 200

# ---- permissions ------------------------------------------------------------------
PERM_COMPUTE = "compute"           # implicit: pure computation
PERM_CLOCK = "clock"               # clock_now()
PERM_STORAGE = "storage"           # store_get / store_put / store_delete / store_keys
PERM_NETWORK = "network"           # web_fetch_text(url)
OPTIONAL_PERMISSIONS = (PERM_CLOCK, PERM_STORAGE, PERM_NETWORK)
ALL_PERMISSIONS = (PERM_COMPUTE,) + OPTIONAL_PERMISSIONS
PERMISSION_HELPERS = {
    PERM_CLOCK: ("clock_now",),
    PERM_STORAGE: ("store_get", "store_put", "store_delete", "store_keys"),
    PERM_NETWORK: ("web_fetch_text",),
}
HELPER_TO_PERMISSION = {h: p for p, hs in PERMISSION_HELPERS.items() for h in hs}

# ---- dependencies (helper namespaces an extension may import) --------------------------
ALLOWED_DEPENDENCIES = ("math",)

# ---- storage / network helper limits ----------------------------------------------------
MAX_KV_KEYS = 200
MAX_KV_KEY_CHARS = 64
MAX_KV_VALUE_BYTES = 8_000
MAX_FETCH_TEXT = 20_000

# ---- input / output field types ----------------------------------------------------------
TYPE_NUMBER = "number"
TYPE_INTEGER = "integer"
TYPE_TEXT = "text"
TYPE_BOOLEAN = "boolean"
TYPE_LIST_NUMBER = "list_number"
TYPE_LIST_TEXT = "list_text"
INPUT_TYPES = (TYPE_NUMBER, TYPE_INTEGER, TYPE_TEXT, TYPE_BOOLEAN, TYPE_LIST_NUMBER, TYPE_LIST_TEXT)
OUTPUT_TYPES = (TYPE_NUMBER, TYPE_INTEGER, TYPE_TEXT, TYPE_BOOLEAN, "list", "json")
