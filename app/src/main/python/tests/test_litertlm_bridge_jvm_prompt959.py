"""Prompt 959 (stage B, «مغز خودکار") - the Java side of the on-device brain: `LiteRtLmBridge.java` compiled and RUN against a stand-in engine.

The real engine (`com.google.ai.edge.litertlm`) is a Kotlin library that is not available here, so the bridge is exercised against hand-written
Java classes shaped like its compiled API (`tests/jvm_stub_litertlm/`): `EngineConfig` with its ONE seven-parameter constructor (and Kotlin's synthetic
default-values constructor beside it), the constructors `@JvmOverloads` yields for `ConversationConfig`, `Backend.CPU()` with a public no-argument
constructor, the NON-`@JvmStatic` companions of `Contents` / `Message`, `Engine.initialize/close`, `Conversation.sendMessage/cancelProcess`.
What this proves: the file compiles for Java 8, never throws, builds the engine and conversations in the documented way, passes the history in
order, falls back to simpler configurations, cancels, reports every failure as a code, and is harmless in an APK that has no engine at all.
What it can NOT prove: that the REAL engine accepts this call sequence (only a phone running the real engine can). The test is skipped, and says so,
when no JDK is installed.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PYTHON_ROOT = os.path.dirname(HERE)
STUB = os.path.join(HERE, "jvm_stub_litertlm")
# The two stub folders are FLAT on purpose (files directly inside `ok/` and `drift/`; javac takes the files by name, the `package` line decides
# where the classes land): a deep `com/google/ai/...` tree was once lost in a GitHub web upload, and every other test then failed with an
# opaque javac error. `StubFilesPresentTests` below names the missing file instead.
STUB_FILES = {"": ("AbsentMain.java", "OkMain.java"), "drift": ("EngineConfig.java",),
              "ok": ("Backend.java", "Content.java", "Contents.java", "Conversation.java", "ConversationConfig.java", "Engine.java",
                     "EngineConfig.java", "Message.java", "Placeholders.java", "SamplerConfig.java", "StubControl.java", "ThinkingConfig.java")}
BRIDGE = os.path.normpath(os.path.join(PYTHON_ROOT, "..", "java", "com", "erfan", "standaloneai", "LiteRtLmBridge.java"))
HAVE_JDK = bool(shutil.which("javac") and shutil.which("java"))


def java_files(folder, skip=()):
    out = []
    for base, _dirs, names in os.walk(folder):
        out.extend(os.path.join(base, n) for n in sorted(names) if n.endswith(".java") and n not in skip)
    return sorted(out)


def compile_into(case, sources, out):
    built = subprocess.run(["javac", "-encoding", "UTF-8", "--release", "8", "-proc:none", "-nowarn", "-Xlint:-options", "-d", out] + sources,
                           capture_output=True, text=True, timeout=240)
    case.assertEqual(built.returncode, 0, "javac failed:\n" + built.stdout + built.stderr)


def run_main(out, main, *args):
    ran = subprocess.run(["java", "-cp", out, main] + list(args), capture_output=True, text=True, timeout=120, encoding="utf-8")
    return ran.returncode, ran.stdout, ran.stderr


def compile_and_run(case, sources, main, *args):
    with tempfile.TemporaryDirectory() as out:
        compile_into(case, sources, out)
        return run_main(out, main, *args)


def hide(file, text):
    """(file, text, the same text without its first `public `): the member stays visible to the other stand-ins but no longer to reflection -
    what Kotlin's `internal` does. The edit is made on a temporary copy by the test, so no extra stand-in file is ever needed."""
    assert "public " in text, text
    return (file, text, text.replace("public ", "", 1))


H_INIT = hide("Engine.java", "    public void initialize() {")
H_CREATE = hide("Engine.java", "    public Conversation createConversation(ConversationConfig conversationConfig) {")
H_ENGINE = hide("Engine.java", "    public Engine(EngineConfig engineConfig) {")
# The stand-in EngineConfig is shaped like the real Kotlin class: ONE public constructor with all seven parameters (no @JvmOverloads), and Kotlin's
# synthetic "default values" constructor (an int and a marker at the end), which must never be chosen. These texts are its first lines.
CFG_FULL_HEADER = ("    public EngineConfig(String modelPath, Backend backend, Backend visionBackend, Backend audioBackend, Integer maxNumTokens, Integer maxNumImages,\n"
                   "                        String cacheDir) {")
H_CFG_FULL = hide("EngineConfig.java", CFG_FULL_HEADER)
CFG_SHORT_TWO = ("EngineConfig.java", CFG_FULL_HEADER,
                 "    public EngineConfig(String modelPath, Backend backend) {\n        this(modelPath, backend, null, null, null, null, null);\n    }\n\n"
                 "    EngineConfig(String modelPath, Backend backend, Backend visionBackend, Backend audioBackend, Integer maxNumTokens, Integer maxNumImages,\n"
                 "                 String cacheDir) {")
CFG_SHORT_FIVE = ("EngineConfig.java", CFG_FULL_HEADER,
                  "    public EngineConfig(String modelPath, Backend backend, Backend visionBackend, Backend audioBackend, Integer maxNumTokens) {\n"
                  "        this(modelPath, backend, visionBackend, audioBackend, maxNumTokens, null, null);\n    }\n\n"
                  "    EngineConfig(String modelPath, Backend backend, Backend visionBackend, Backend audioBackend, Integer maxNumTokens, Integer maxNumImages,\n"
                  "                 String cacheDir) {")


def cfg_with_only(extra):
    """The EngineConfig stand-in whose full constructor is hidden and which has this public one instead (its body only throws: it is never called)."""
    return ("EngineConfig.java", CFG_FULL_HEADER,
            "    public EngineConfig(" + extra + ") {\n        throw new UnsupportedOperationException(\"stand-in\");\n    }\n\n"
            "    EngineConfig(String modelPath, Backend backend, Backend visionBackend, Backend audioBackend, Integer maxNumTokens, Integer maxNumImages,\n"
            "                 String cacheDir) {")


def cfg_with_extra(extra):
    """The EngineConfig stand-in with one more PUBLIC constructor next to the full one (its body only throws: choosing it would show)."""
    return ("EngineConfig.java", CFG_FULL_HEADER,
            "    public EngineConfig(" + extra + ") {\n        throw new UnsupportedOperationException(\"stand-in: a narrower form must not be chosen\");\n    }\n\n"
            + CFG_FULL_HEADER)


CFG_REJECTS_NULL_TAIL = ("EngineConfig.java", "        if (maxNumTokens != null && maxNumTokens <= 0) {",
                         "        if (cacheDir == null) {\n            throw new IllegalArgumentException(\"cacheDir must not be null\");\n        }\n"
                         "        if (maxNumTokens != null && maxNumTokens <= 0) {")
H_CPU0 = hide("Backend.java", "        public CPU() {")
H_CPU2 = hide("Backend.java", "        public CPU(Integer threadCount, Integer numOfThreads) {")
H_CC1 = hide("ConversationConfig.java", "    public ConversationConfig(Contents systemInstruction) {")
H_CC4 = hide("ConversationConfig.java", "    public ConversationConfig(Contents systemInstruction, List<Message> initialMessages, List<ToolProvider> tools, SamplerConfig samplerConfig) {")
H_CC11 = hide("ConversationConfig.java", "    public ConversationConfig(Contents systemInstruction, List<Message> initialMessages, List<ToolProvider> tools, SamplerConfig samplerConfig,\n"
                                         "                              boolean automaticToolCalling")
H_CONTENTS_COMPANION = hide("Contents.java", "    public static final Companion Companion = new Companion();")
H_CONTENTS_OF = hide("Contents.java", "        public Contents of(String text) {")
H_MESSAGE_COMPANION = hide("Message.java", "    public static final Companion Companion = new Companion();")
H_USER = hide("Message.java", "        public Message user(String text) {")
H_MODEL = hide("Message.java", "        public Message model(String text) {")
H_SEND1 = hide("Conversation.java", "    public Message sendMessage(String text) {")
H_SEND6 = hide("Conversation.java", "    public Message sendMessage(String text, Map<String, Object> extraContext, RepetitionPenaltyConfig a, NoRepeatNgramConfig b,\n"
                                    "                               SuppressTokensConfig c, Integer maxOutputToken) {")
# four hundred public methods more on the Engine: a listing far longer than the 6000 characters the self-test report may carry
PADDING = ("Engine.java", "    @Override\n    public void close() {",
           "".join("    public void padding%04d(int a, String b) {\n    }\n" % i for i in range(400)) + "    @Override\n    public void close() {")


class StubFilesPresentTests(unittest.TestCase):
    """Runs even without a JDK: a partly uploaded repository must say WHICH stand-in file is missing (and where it belongs)."""

    def test_every_stand_in_file_is_there_and_nothing_else(self):
        missing, extra = [], []
        for folder, names in STUB_FILES.items():
            where = os.path.join(STUB, folder) if folder else STUB
            have = sorted(n for n in os.listdir(where) if n.endswith(".java")) if os.path.isdir(where) else []
            missing += ["tests/jvm_stub_litertlm/" + (folder + "/" if folder else "") + n for n in names if n not in have]
            extra += ["tests/jvm_stub_litertlm/" + (folder + "/" if folder else "") + n for n in have if n not in names]
        self.assertEqual(missing, [], "stand-in files missing - upload them to the repository at exactly these paths (the CI cannot compile the bridge without them): "
                         + ", ".join(missing))
        self.assertEqual(extra, [], "unexpected stand-in files (list them in STUB_FILES on purpose): " + ", ".join(extra))

    def test_the_folders_hold_their_files_directly(self):
        for folder in ("ok", "drift"):
            where = os.path.join(STUB, folder)
            self.assertTrue(os.path.isdir(where), where)
            self.assertEqual([n for n in os.listdir(where) if os.path.isdir(os.path.join(where, n))], [], folder + " must stay flat")

    def test_every_stand_in_declares_the_engine_package(self):
        for folder, names in STUB_FILES.items():
            if not folder:
                continue
            for name in names:
                with open(os.path.join(STUB, folder, name), encoding="utf-8") as fh:
                    self.assertTrue(fh.read().lstrip().startswith("package com.google.ai.edge.litertlm;"), folder + "/" + name)


class BridgeSourceTests(unittest.TestCase):
    def test_the_bridge_uses_no_android_or_third_party_class(self):
        with open(BRIDGE, encoding="utf-8") as fh:
            text = fh.read()
        self.assertTrue(text.startswith("package com.erfan.standaloneai;"))
        imports = re.findall(r"^import ([\w.]+);", text, re.M)
        self.assertTrue(imports and all(i.startswith("java.") for i in imports), imports)
        self.assertNotIn("android.", text.replace("android.jar", ""))   # not even named in code: reflection only
        self.assertNotIn("import com.google", text)                     # the engine is reached by reflection only
        for forbidden in ("Runtime.getRuntime", "ProcessBuilder", "exec(", "System.load", "loadLibrary", "HttpURLConnection", "Socket"):
            self.assertNotIn(forbidden, text, forbidden)

    def test_every_public_method_is_static_and_never_declares_a_throw(self):
        with open(BRIDGE, encoding="utf-8") as fh:
            text = fh.read()
        public = re.findall(r"^    public (static )?[\w<>\[\], ]+ \w+\([^)]*\)( throws [\w, ]+)?\s*\{", text, re.M)
        self.assertGreaterEqual(len(public), 7)
        for static, throws in public:
            self.assertEqual(static, "static ")
            self.assertEqual(throws, "")


@unittest.skipUnless(HAVE_JDK, "no JDK (javac/java) on this machine: the bridge could not be compiled here")
class BridgeAgainstStandInTests(unittest.TestCase):
    def check(self, code, out, err, expected_passes):
        fails = [line for line in out.splitlines() if line.startswith("FAIL")]
        self.assertEqual((code, fails), (0, []), out + err)
        self.assertIn("DONE failures=0", out)
        passes = [line for line in out.splitlines() if line.startswith("PASS")]
        self.assertGreaterEqual(len(passes), expected_passes, out)

    def test_with_an_engine_shaped_as_expected(self):
        code, out, err = compile_and_run(self, [BRIDGE] + java_files(os.path.join(STUB, "ok")) + [os.path.join(STUB, "OkMain.java")], "OkMain", "ok")
        self.check(code, out, err, 36)

    def test_with_an_engine_whose_api_drifted_the_app_survives_and_says_api_mismatch(self):
        sources = [BRIDGE] + java_files(os.path.join(STUB, "ok"), skip=("EngineConfig.java",)) + java_files(os.path.join(STUB, "drift")) \
            + [os.path.join(STUB, "OkMain.java")]
        code, out, err = compile_and_run(self, sources, "OkMain", "drift")
        self.check(code, out, err, 4)

    # ---- the pre-download probe, tried on engines with ONE thing hidden ---------------------------------------------------------------------
    # (what is hidden, the edits to the "ok" stand-ins, the probe's verdict, the piece it must name). A verdict of "ok" is checked for TRUTH too:
    # the engine must then really load and really answer (one wrong "api_mismatch" would stop the user from fetching a brain that works, one
    # wrong "ok" would let him fetch gigabytes for nothing). Every check inside the probe has a variant that only that check can tell apart.
    VARIANTS = (
        ("Engine.initialize() hidden", (H_INIT,), "api_mismatch", "Engine.initialize()"),
        ("Engine.createConversation hidden", (H_CREATE,), "api_mismatch", "Engine.createConversation(ConversationConfig)"),
        ("Engine constructor hidden", (H_ENGINE,), "api_mismatch", "Engine(EngineConfig)"),
        ("the full EngineConfig constructor hidden (only Kotlin's synthetic one is public)", (H_CFG_FULL,), "api_mismatch", "EngineConfig(String, Backend)"),
        ("an EngineConfig with only a five-parameter form", (CFG_SHORT_FIVE,), "ok", ""),
        ("an EngineConfig with only a two-parameter form", (CFG_SHORT_TWO,), "ok", ""),
        ("an EngineConfig that refuses null for its optional tail", (CFG_REJECTS_NULL_TAIL,), "api_mismatch",
         "EngineConfig(String, Backend): IllegalArgumentException"),
        ("an EngineConfig with a narrower public form beside the full one (the widest is used)",
         (cfg_with_extra("String modelPath, Backend backend, Backend visionBackend, Backend audioBackend, Integer maxNumTokens"),), "ok", ""),
        ("an EngineConfig whose second parameter is not a Backend", (cfg_with_only("String modelPath, Integer notABackend"),), "api_mismatch",
         "EngineConfig(String, Backend)"),
        ("an EngineConfig whose first parameter is not a String", (cfg_with_only("Integer notAPath, Backend backend"),), "api_mismatch",
         "EngineConfig(String, Backend)"),
        ("an EngineConfig with only a one-parameter form", (cfg_with_only("String modelPath"),), "api_mismatch", "EngineConfig(String, Backend)"),
        ("both Backend.CPU constructors hidden", (H_CPU0, H_CPU2), "api_mismatch", "Backend.CPU()"),
        ("only the no-argument Backend.CPU constructor left", (H_CPU2,), "ok", ""),
        ("only the two-argument Backend.CPU constructor left", (H_CPU0,), "ok", ""),
        ("every ConversationConfig constructor the bridge can use hidden", (H_CC1, H_CC4, H_CC11), "api_mismatch", "ConversationConfig(...)"),
        ("only the long ConversationConfig constructor left", (H_CC1, H_CC4), "ok", ""),
        ("only the middle ConversationConfig constructor left", (H_CC1, H_CC11), "ok", ""),
        ("only the short ConversationConfig constructor left", (H_CC4, H_CC11), "ok", ""),
        ("Contents companion hidden", (H_CONTENTS_COMPANION,), "api_mismatch", "Contents.of(String)"),
        ("Contents.of(String) hidden", (H_CONTENTS_OF,), "api_mismatch", "Contents.of(String)"),
        ("Message companion hidden", (H_MESSAGE_COMPANION,), "api_mismatch", "Message.user/model(String)"),
        ("Message.user(String) hidden", (H_USER,), "api_mismatch", "Message.user/model(String)"),
        ("Message.model(String) hidden", (H_MODEL,), "api_mismatch", "Message.user/model(String)"),
        ("both sendMessage shapes hidden", (H_SEND1, H_SEND6), "api_mismatch", "Conversation.sendMessage(String)"),
        ("only the long sendMessage left", (H_SEND1,), "ok", ""),
        ("only the short sendMessage left", (H_SEND6,), "ok", ""),
    )

    def stand_ins_with(self, work, edits=()):
        for name in os.listdir(os.path.join(STUB, "ok")):
            shutil.copy(os.path.join(STUB, "ok", name), os.path.join(work, name))
        for file, old, new in edits:
            path = os.path.join(work, file)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            self.assertEqual(text.count(old), 1, "the stand-in no longer has exactly this text - update the variant together with it: " + old)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text.replace(old, new, 1))

    def run_probe_variant(self, edits, verdict, piece, *more):
        with tempfile.TemporaryDirectory() as work:
            self.stand_ins_with(work, edits)
            code, out, err = compile_and_run(self, [BRIDGE] + java_files(work) + [os.path.join(STUB, "OkMain.java")], "OkMain", "probe", verdict, piece, *more)
        self.check(code, out, err, 5 if verdict == "ok" else 3)

    def test_the_probe_judges_each_piece_of_the_engine_api_before_any_model_is_fetched(self):
        for label, edits, verdict, piece in self.VARIANTS:
            with self.subTest(variant=label):
                self.run_probe_variant(edits, verdict, piece)

    def test_a_very_long_api_listing_is_cut_at_six_thousand_characters(self):
        self.run_probe_variant((PADDING,), "ok", "", "huge")

    def test_the_probe_when_a_whole_class_is_gone(self):
        # compiled once; each variant deletes the class file(s) of one class. The engine counts as present only with Engine, EngineConfig and
        # Conversation (their absence is "no engine in this APK"); a missing class beside them is an engine of another shape.
        gone = (("Engine", ("Engine.class",), "dependency_missing", "engine"),
                ("EngineConfig", ("EngineConfig.class",), "dependency_missing", "engine"),
                ("Conversation", ("Conversation.class",), "dependency_missing", "engine"),
                ("Backend", ("Backend.class", "Backend$CPU.class", "Backend$GPU.class"), "api_mismatch", "Backend"),
                ("Backend$CPU", ("Backend$CPU.class",), "api_mismatch", "Backend$CPU"),
                ("ConversationConfig", ("ConversationConfig.class",), "api_mismatch", "ConversationConfig"),
                ("Contents", ("Contents.class", "Contents$Companion.class"), "api_mismatch", "Contents"),
                ("Message", ("Message.class", "Message$Companion.class"), "api_mismatch", "Message"))
        with tempfile.TemporaryDirectory() as work, tempfile.TemporaryDirectory() as built:
            self.stand_ins_with(work)
            compile_into(self, [BRIDGE] + java_files(work) + [os.path.join(STUB, "OkMain.java")], built)
            for label, files, verdict, piece in gone:
                with self.subTest(class_gone=label), tempfile.TemporaryDirectory() as copy:
                    shutil.rmtree(copy)
                    shutil.copytree(built, copy)
                    for name in files:
                        target = os.path.join(copy, "com", "google", "ai", "edge", "litertlm", name)
                        self.assertTrue(os.path.isfile(target), target)
                        os.remove(target)
                    code, out, err = run_main(copy, "OkMain", "probe", verdict, piece)
                    self.check(code, out, err, 3)

    def test_in_an_apk_without_the_engine_nothing_throws(self):
        code, out, err = compile_and_run(self, [BRIDGE, os.path.join(STUB, "AbsentMain.java")], "AbsentMain")
        self.check(code, out, err, 6)


if __name__ == "__main__":
    unittest.main()
