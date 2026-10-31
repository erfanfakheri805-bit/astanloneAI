"""
pack_system.scan - the static safety scan of a code pack's Python source
========================================================================
It reads the syntax tree and NEVER runs the code. It is a safety net against accidents and the obvious tricks, not a
sandbox: a pack runs inside the app with the app's own rights, which is why the user must approve it and why safe mode
and rollback exist. What it blocks:

* syntax errors; hidden characters (NUL, bidirectional controls) and non-ASCII identifiers (look-alike names);
* process, native-code and raw-network modules (`subprocess`, `ctypes`, `socket`, `urllib.request` ...): a pack reaches
  the web only through `api.net_fetch` (the hub's gate, limits and audit) and the phone only through `api.android`;
* file-system modules and the bare `open()`: a pack reads and writes only through `api` (its own data folder, the
  user's inbox);
* `eval`, `exec`, `compile`, `__import__`, `globals`, ... and the object-graph escape attributes (`__globals__`,
  `__subclasses__`, `f_back` ...), also when they appear as string constants (for `getattr`);
* Java access (`java`, `jclass` ...) unless the pack declares `unsafe_native` (then the user is asked twice);
* `_private` attributes reached through `api` (`api._store`, `api.android._jvm`): only the documented public methods.
"""

import ast

from . import limits

BLOCKED_MODULES = frozenset({
    "subprocess", "ctypes", "_ctypes", "pty", "fcntl", "multiprocessing", "signal", "pickle", "cPickle", "marshal", "shelve",
    "runpy", "imp", "importlib", "builtins", "__builtin__", "code", "codeop", "pdb", "gc", "inspect", "sys", "socket", "ssl",
    "select", "selectors", "asyncio", "http", "ftplib", "smtplib", "poplib", "imaplib", "nntplib", "telnetlib", "xmlrpc",
    "socketserver", "webbrowser", "shutil", "pathlib", "glob", "tempfile", "sqlite3", "mmap", "fileinput", "tarfile",
    "zipimport", "pkgutil", "site", "sysconfig", "ensurepip", "venv", "distutils", "setuptools", "pip", "readline",
    "rlcompleter", "curses", "tkinter", "turtle", "idlelib", "trace", "tracemalloc", "faulthandler", "atexit", "posix",
    "nt", "_thread", "urllib.request", "urllib.robotparser", "pty", "resource", "syslog", "crypt", "grp", "pwd", "termios"})
NATIVE_MODULES = frozenset({"java", "android", "com", "chaquopy"})
NATIVE_NAMES = frozenset({"jclass", "jarray", "jvoid", "jboolean", "jint", "jlong", "jfloat", "jdouble", "dynamic_proxy",
                          "JavaClass", "JavaObject"})
OS_ALLOWED_ATTRS = frozenset({"path", "sep", "linesep", "name", "curdir", "pardir", "extsep", "urandom", "cpu_count"})
BLOCKED_CALLS = frozenset({"eval", "exec", "compile", "__import__", "open", "input", "breakpoint", "exit", "quit", "globals",
                           "locals", "execfile", "reload"})
BLOCKED_ATTRS = frozenset({
    "__subclasses__", "__globals__", "__code__", "__closure__", "__builtins__", "__loader__", "__bases__", "__mro__",
    "__getattribute__", "__reduce__", "__reduce_ex__", "__import__", "gi_frame", "gi_code", "cr_frame", "cr_code", "ag_frame",
    "f_globals", "f_locals", "f_back", "f_builtins", "f_code", "tb_frame", "co_code", "func_globals"})
BLOCKED_NAMES = frozenset({"__builtins__", "__loader__", "__import__"})
DYNAMIC_ATTR_CALLS = frozenset({"getattr", "setattr", "delattr", "hasattr"})
_BIDI = set(range(0x202A, 0x202F)) | set(range(0x2066, 0x206A)) | {0x200E, 0x200F}
MAX_NODES = 300_000


class Finding:
    __slots__ = ("severity", "code", "file", "line", "message_fa")

    def __init__(self, severity, code, file, line, message_fa):
        self.severity, self.code, self.file, self.line, self.message_fa = severity, code, file, int(line or 0), message_fa

    def to_dict(self):
        return {"severity": self.severity, "code": self.code, "file": self.file, "line": self.line, "message_fa": self.message_fa}


class ScanReport:
    def __init__(self):
        self.findings = []
        self.imports = set()
        self.uses = set()
        self.nodes = 0

    @property
    def blocks(self):
        return [f for f in self.findings if f.severity == "block"]

    @property
    def warnings(self):
        return [f for f in self.findings if f.severity == "warn"]

    @property
    def ok(self):
        return not self.blocks

    def add(self, severity, code, file, node_or_line, message_fa):
        if len(self.findings) >= 60:
            return
        line = node_or_line if isinstance(node_or_line, int) else getattr(node_or_line, "lineno", 0)
        self.findings.append(Finding(severity, code, file, line, message_fa))

    def to_dict(self):
        return {"ok": self.ok, "blocks": [f.to_dict() for f in self.blocks], "warnings": [f.to_dict() for f in self.warnings],
                "imports": sorted(self.imports), "uses": sorted(self.uses), "nodes": self.nodes}


def _ascii_ident(text):
    return isinstance(text, str) and text.isascii()


def _private_behind_api(node):
    """True for `api._x`, `api.android._jvm`, `ctx.api._store` ...: a `_private` attribute reached through the pack's `api`."""
    if not node.attr.startswith("_"):
        return False
    names, cur = [], node.value
    while isinstance(cur, ast.Attribute):
        names.append(cur.attr)
        cur = cur.value
    names.reverse()
    return isinstance(cur, ast.Name) and (cur.id == "api" or "api" in names)


class _Visitor(ast.NodeVisitor):
    def __init__(self, report, file, unsafe_native):
        self.rep, self.file, self.native_ok = report, file, unsafe_native
        self.os_names = set()

    def block(self, code, node, fa):
        self.rep.add("block", code, self.file, node, fa)

    def warn(self, code, node, fa):
        self.rep.add("warn", code, self.file, node, fa)

    def generic_visit(self, node):
        self.rep.nodes += 1
        super().generic_visit(node)

    # ---- imports ------------------------------------------------------------------------------
    def _module_check(self, name, node):
        top = name.split(".")[0]
        self.rep.imports.add(top)
        if name in BLOCKED_MODULES or top in BLOCKED_MODULES:
            self.block("E_SCAN_IMPORT", node, "وارد کردن ماژول «%s» مجاز نیست (فرایند، کد بومی، شبکهٔ خام یا فایل). از امکانات «api» استفاده کن." % name)
        elif top in NATIVE_MODULES:
            if self.native_ok:
                self.warn("W_SCAN_NATIVE", node, "دسترسی مستقیم به Java/اندروید (%s)؛ این بسته «unsafe_native» دارد و تأیید دوباره می‌خواهد." % name)
            else:
                self.block("E_SCAN_NATIVE", node, "دسترسی مستقیم به Java/اندروید «%s» فقط با مجوز «unsafe_native» در بسته ممکن است؛ بهتر است از api.android استفاده کنی." % name)

    def visit_Import(self, node):
        for alias in node.names:
            self._module_check(alias.name, node)
            if alias.name == "os":
                self.os_names.add(alias.asname or "os")
            elif alias.name.startswith("os.") and alias.name != "os.path":
                self.block("E_SCAN_OS", node, "«%s» مجاز نیست؛ فقط os.path." % alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        if node.level:
            self.block("E_SCAN_IMPORT", node, "وارد کردن نسبی (from . import) مجاز نیست؛ نام کامل ماژول را بنویس.")
        mod = node.module or ""
        if mod:
            self._module_check(mod, node)
        if mod == "os":
            for alias in node.names:
                if alias.name not in OS_ALLOWED_ATTRS:
                    self.block("E_SCAN_OS", node, "«from os import %s» مجاز نیست؛ فقط path و چند ثابت." % alias.name)
        elif mod == "":
            pass
        for alias in node.names:
            if alias.name in NATIVE_NAMES and not self.native_ok:
                self.block("E_SCAN_NATIVE", node, "«%s» فقط با مجوز «unsafe_native» مجاز است." % alias.name)
        self.generic_visit(node)

    # ---- names, attributes, calls ----------------------------------------------------------------
    def visit_Name(self, node):
        if not _ascii_ident(node.id):
            self.block("E_SCAN_IDENT", node, "نام «%s» نویسهٔ غیر ASCII دارد (ممکن است شبیه نام دیگری باشد)." % node.id[:30])
        if node.id in BLOCKED_NAMES:
            self.block("E_SCAN_NAME", node, "استفاده از «%s» مجاز نیست." % node.id)
        if node.id in NATIVE_NAMES and not self.native_ok:
            self.block("E_SCAN_NATIVE", node, "«%s» فقط با مجوز «unsafe_native» مجاز است." % node.id)
        self.generic_visit(node)

    def visit_Attribute(self, node):
        if not _ascii_ident(node.attr):
            self.block("E_SCAN_IDENT", node, "نام ویژگی «%s» نویسهٔ غیر ASCII دارد." % node.attr[:30])
        if node.attr in BLOCKED_ATTRS:
            self.block("E_SCAN_ATTR", node, "دسترسی به «%s» (درون‌نگری پایتون) مجاز نیست." % node.attr)
        if _private_behind_api(node):
            self.block("E_SCAN_PRIVATE", node, "دسترسی به ویژگی خصوصیِ «%s» از طریق api مجاز نیست؛ فقط روش‌های عمومی api." % node.attr[:30])
        base = node.value
        if isinstance(base, ast.Name) and base.id in self.os_names and node.attr not in OS_ALLOWED_ATTRS:
            self.block("E_SCAN_OS", node, "«os.%s» مجاز نیست (فرایند/فایل)؛ از api استفاده کن." % node.attr)
        if isinstance(base, ast.Name) and base.id == "api":
            if node.attr in ("android", "net_fetch", "ask_model", "teacher", "ui"):
                self.rep.uses.add(node.attr)
        if isinstance(base, ast.Attribute) and isinstance(base.value, ast.Name) and base.value.id == "api" and base.attr == "android":
            if node.attr in ("clipboard", "screen"):
                self.rep.uses.add(node.attr)
        self.generic_visit(node)

    def visit_Call(self, node):
        func = node.func
        if isinstance(func, ast.Name):
            if func.id in BLOCKED_CALLS:
                self.block("E_SCAN_CALL", node, "فراخوانی «%s()» مجاز نیست." % func.id)
            elif func.id in DYNAMIC_ATTR_CALLS:
                if len(node.args) >= 2 and not isinstance(node.args[1], ast.Constant):
                    self.warn("W_SCAN_DYNAMIC", node, "«%s» با نام ویژگیِ پویا؛ بررسی دستی لازم است." % func.id)
        self.generic_visit(node)

    def visit_Constant(self, node):
        value = node.value
        if isinstance(value, str):
            if value in BLOCKED_ATTRS or value in BLOCKED_NAMES:
                self.block("E_SCAN_ATTR", node, "رشتهٔ «%s» (برای getattr و مانند آن) مجاز نیست." % value)
            if any(ord(ch) in _BIDI for ch in value):
                self.block("E_SCAN_HIDDEN", node, "رشته نویسهٔ جهت‌دهندهٔ پنهان (Unicode bidi) دارد.")
        self.generic_visit(node)

    # ---- definitions with identifiers ---------------------------------------------------------------
    def _def_name(self, node):
        if not _ascii_ident(node.name):
            self.block("E_SCAN_IDENT", node, "نام «%s» نویسهٔ غیر ASCII دارد." % node.name[:30])

    def visit_FunctionDef(self, node):
        self._def_name(node)
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node):
        self._def_name(node)
        self.generic_visit(node)

    def visit_arg(self, node):
        if not _ascii_ident(node.arg):
            self.block("E_SCAN_IDENT", node, "نام پارامتر «%s» نویسهٔ غیر ASCII دارد." % node.arg[:30])
        self.generic_visit(node)

    def visit_Global(self, node):
        self.warn("W_SCAN_GLOBAL", node, "استفاده از global؛ ممکن است وضعیت مشترک ناخواسته بسازد.")


def scan_source(path, source, report=None, unsafe_native=False):
    """Scan one `.py` text; findings are added to (and returned in) `report`."""
    report = report or ScanReport()
    if any(ord(ch) in _BIDI for ch in source) or "\x00" in source:
        report.add("block", "E_SCAN_HIDDEN", path, 0, "متن کد نویسهٔ پنهان (NUL یا جهت‌دهندهٔ Unicode) دارد.")
        return report
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as exc:
        report.add("block", "E_SCAN_SYNTAX", path, exc.lineno or 0, "خطای نحوی (Syntax): %s" % str(exc.msg)[:80])
        return report
    except (ValueError, RecursionError, MemoryError):
        report.add("block", "E_SCAN_SYNTAX", path, 0, "فایل پایتون قابل تحلیل نیست.")
        return report
    _Visitor(report, path, unsafe_native).visit(tree)
    if report.nodes > MAX_NODES:
        report.add("block", "E_SCAN_SIZE", path, 0, "کد بیش از حد بزرگ است.")
    return report


def _defines_register(source):
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return True                                            # a syntax error is reported on its own
    return any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "register" for n in tree.body)


def scan_pack(manifest):
    """The `ScanReport` of every `.py` file of a normalized code manifest (cross-checks the declared permissions)."""
    report = ScanReport()
    perms = set(manifest.get("permissions") or ())
    native_ok = "unsafe_native" in perms
    for path in sorted(manifest.get("files") or ()):
        if path.endswith(".py"):
            scan_source(path, manifest["files"][path], report, native_ok)
    entry = manifest.get("entry") or ""
    if entry:
        rel = entry.replace(".", "/")
        text = (manifest.get("files") or {}).get(rel + ".py")
        if text is None:
            text = (manifest.get("files") or {}).get(rel + "/__init__.py")
        if text is not None and not _defines_register(text):
            report.add("block", "E_SCAN_NO_REGISTER", entry.replace(".", "/") + ".py", 0,
                       "ماژول ورودی «%s» تابع register(api) ندارد؛ بدون آن بسته هیچ کاری ثبت نمی‌کند." % entry)
    advisory = {"android": "android", "net_fetch": "network", "ask_model": "model", "teacher": "teacher", "ui": "ui",
                "clipboard": "clipboard", "screen": "screen"}
    for used, perm in advisory.items():
        if used in report.uses and perm not in perms:
            report.add("warn", "W_SCAN_PERMISSION", "", 0, "کد از api.%s استفاده می‌کند ولی مجوز «%s» در بسته اعلام نشده؛ در اجرا رد می‌شود." % (used, perm))
    return report


__all__ = ["scan_source", "scan_pack", "ScanReport", "Finding"]
