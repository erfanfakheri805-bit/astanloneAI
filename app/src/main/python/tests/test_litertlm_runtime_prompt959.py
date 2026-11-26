"""
Prompt 959 (stage B, «مغز خودکار») - `model_runtime.litertlm_runtime.LiteRtLmRuntime`, the Python side of the phone's own language model,
against a FAKE bridge that answers with the same "OK\\n..." / "ERR\\n..." strings as the Java class `LiteRtLmBridge`.

What is pinned: the exact words of availability («which part is missing»), the crash guard (a marker written BEFORE the engine is loaded and
lifted only after a real answer, so an app killed while loading is never loaded into again by itself), the mapping of every error to a stable
code, the cleaning of what is sent to the engine, and that nothing here can raise out of `cancel` / `unload` / `diagnostics`.
Nothing here says how the real engine behaves: the Java side is covered separately against a stand-in engine.
"""
import hashlib
import os
import sys
import tempfile
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from model_runtime import litertlm_runtime as LR
from model_runtime.card import parse_card
from model_runtime.runtimes import LoadedModel, RuntimeGenerateError, RuntimeLoadError
from tests.ownbrain_support_prompt959 import FakeBridge, FakeJvm, engine_runtime

SHA = hashlib.sha256(b"x").hexdigest()
CARD = parse_card(dict(model_id="own-test", title="Test", version="1", format="litertlm", source_url="https://huggingface.co/a/b/resolve/main/m.litertlm",
                       sha256=SHA, size_bytes=10, license="apache-2.0"))


class ParseTests(unittest.TestCase):
    def test_a_good_answer_and_an_empty_one(self):
        self.assertEqual(LR.parse_result("OK\nسلام دنیا"), ("OK", "سلام دنیا", ""))
        self.assertEqual(LR.parse_result("OK"), ("OK", "", ""))
        self.assertEqual(LR.parse_result("OK\n"), ("OK", "", ""))
        self.assertEqual(LR.parse_result("OK\nline one\nline two"), ("OK", "line one\nline two", ""), "the text keeps its own line breaks")

    def test_an_error_has_a_code_and_a_detail(self):
        self.assertEqual(LR.parse_result("ERR\noom\nout of memory at 12"), ("ERR", "oom", "out of memory at 12"))
        self.assertEqual(LR.parse_result("ERR\noom"), ("ERR", "oom", ""))
        self.assertEqual(LR.parse_result("ERR\n"), ("ERR", "engine_error", ""))
        self.assertEqual(LR.parse_result("ERR\n\nonly detail"), ("ERR", "engine_error", "only detail"))

    def test_code_and_detail_are_cut_to_a_safe_length(self):
        kind, code, detail = LR.parse_result("ERR\n" + "c" * 100 + "\n" + "d" * 500)
        self.assertEqual((kind, len(code), len(detail)), ("ERR", 40, 160))

    def test_anything_else_is_a_bad_bridge_answer_never_an_exception(self):
        for raw in (None, "", "garbage", "ok\nlower case", b"OK\nbytes", 7, ["OK"], "OKAY\nx", " OK\nx"):
            self.assertEqual(LR.parse_result(raw)[:2], ("ERR", "bad_bridge_answer"), repr(raw))


class HistoryTests(unittest.TestCase):
    def test_only_the_last_turns_are_sent_and_empty_ones_are_dropped(self):
        turns = [("u%d" % i, "a%d" % i) for i in range(10)]
        records = LR.encode_history(turns).split(LR.TURN_SEP)
        self.assertEqual(len(records), LR.MAX_HISTORY_TURNS)
        self.assertEqual(records[0], "u4" + LR.FIELD_SEP + "a4")
        self.assertEqual(records[-1], "u9" + LR.FIELD_SEP + "a9")
        self.assertEqual(LR.encode_history([("", "x"), ("y", ""), ("  ", "  ")]), "")
        self.assertEqual(LR.encode_history(None), "")
        self.assertEqual(LR.encode_history([]), "")

    def test_control_characters_and_the_two_separators_cannot_break_the_record_format(self):
        hostile = "a" + LR.FIELD_SEP + "b" + LR.TURN_SEP + "c\x00d\x1be"
        encoded = LR.encode_history([(hostile, hostile)])
        self.assertEqual(encoded.count(LR.FIELD_SEP), 1, "exactly one field separator per turn")
        self.assertNotIn(LR.TURN_SEP, encoded)
        self.assertNotIn("\x00", encoded)
        self.assertNotIn("\x1b", encoded)
        self.assertEqual(LR.encode_history([("سلام\r\nخوبی؟", "بله")]), "سلام\nخوبی؟" + LR.FIELD_SEP + "بله", "carriage returns go, line breaks stay")

    def test_a_malformed_turn_is_skipped_not_raised(self):
        turns = [("fine", "ok"), 5, ("only one",), None, ("also", "fine")]
        encoded = LR.encode_history(turns)
        self.assertEqual(encoded, "fine" + LR.FIELD_SEP + "ok" + LR.TURN_SEP + "also" + LR.FIELD_SEP + "fine")

    def test_every_field_is_cut_to_its_limit(self):
        encoded = LR.encode_history([("u" * 9000, "a" * 9000)])
        user, answer = encoded.split(LR.FIELD_SEP)
        self.assertEqual((len(user), len(answer)), (LR.MAX_FIELD_CHARS, LR.MAX_FIELD_CHARS))


class AvailabilityTests(unittest.TestCase):
    def runtime(self, bridge=None, *, available=True, provider=None):
        return LR.LiteRtLmRuntime(jvm_provider=provider or (lambda: FakeJvm(bridge or FakeBridge(), available)))

    def test_off_the_phone_it_says_so(self):
        for runtime in (self.runtime(available=False), self.runtime(provider=lambda: None)):
            report = runtime.availability()
            self.assertEqual((report.available, report.code), (False, "unavailable_platform"))
            self.assertIn("اندروید", report.reason_fa)
            self.assertEqual(report.requires, LR.REQUIRES)

    def test_a_build_without_the_bridge_class_says_which_piece_is_missing(self):
        class Missing(Exception):
            code = "class_missing"

        class Jvm(FakeJvm):
            def jclass(self, name):
                raise Missing(name)

        report = self.runtime(provider=lambda: Jvm(FakeBridge())).availability()
        self.assertEqual((report.available, report.code), (False, "dependency_missing"))
        self.assertIn("پلِ موتور مغز", report.reason_fa)

    def test_a_build_with_the_bridge_but_without_the_engine_says_so(self):
        report = self.runtime(FakeBridge(present=False)).availability()
        self.assertEqual((report.available, report.code), (False, "dependency_missing"))
        self.assertIn("با موتور مغز (LiteRT-LM) ساخته نشده", report.reason_fa)

    def test_any_other_failure_is_an_engine_error_not_an_exception(self):
        class Jvm(FakeJvm):
            def jclass(self, name):
                raise RuntimeError("boom")

        report = self.runtime(provider=lambda: Jvm(FakeBridge())).availability()
        self.assertEqual((report.available, report.code), (False, "engine_error"))

    def test_with_the_engine_in_the_build_it_is_available(self):
        report = self.runtime(FakeBridge()).availability()
        self.assertEqual((report.available, report.code), (True, "ok"))

    def test_an_engine_in_the_apk_that_is_not_shaped_as_expected_is_refused_before_any_download(self):
        bridge = FakeBridge(probe_result="ERR\napi_mismatch\nEngineConfig(String, Backend)")
        report = self.runtime(bridge).availability()
        self.assertEqual((report.available, report.code), (False, "api_mismatch"))
        self.assertIn("EngineConfig(String, Backend)", report.reason_fa)
        self.assertIn("EngineConfig(String, Backend)", report.reason_en)
        self.assertIn("دانلودِ مغز بی‌فایده است", report.reason_fa)
        self.assertEqual(report.requires, LR.REQUIRES)
        self.assertEqual(bridge.probes, 1)

    def test_a_probe_that_cannot_be_asked_or_says_something_else_never_blocks(self):
        class Raising(FakeBridge):
            def probe(self):
                raise RuntimeError("no")

        class NoProbe:                                  # an older bridge without the method
            def isPresent(self):
                return True

        for bridge in (Raising(), NoProbe(), FakeBridge(probe_result="OK\nready"), FakeBridge(probe_result="garbage"),
                       FakeBridge(probe_result="ERR\nnative_missing\nx"), FakeBridge(probe_result="ERR\ndependency_missing\nengine")):
            report = self.runtime(bridge).availability()
            self.assertEqual((report.available, report.code), (True, "ok"), type(bridge).__name__)

    def test_a_missing_piece_without_a_name_is_still_reported(self):
        report = self.runtime(FakeBridge(probe_result="ERR\napi_mismatch\n")).availability()
        self.assertEqual((report.available, report.code), (False, "api_mismatch"))
        self.assertIn("نامشخص", report.reason_fa)

    def test_the_probe_is_not_asked_when_the_engine_is_absent_or_off_the_phone(self):
        bridge = FakeBridge(present=False, probe_result="ERR\napi_mismatch\nx")
        self.assertEqual(self.runtime(bridge).availability().code, "dependency_missing")
        self.assertEqual(bridge.probes, 0)

    def test_the_real_api_listing_is_passed_on_cut_and_never_raises(self):
        self.assertEqual(self.runtime(FakeBridge(api_text="Engine: initialize();")).api_listing(), "Engine: initialize();")

        class Raising(FakeBridge):
            def api(self):
                raise RuntimeError("no")

        self.assertEqual(len(self.runtime(FakeBridge(api_text="x" * 9000)).api_listing()), 6000)
        self.assertEqual(self.runtime(Raising()).api_listing(), "")
        self.assertEqual(self.runtime(available=False).api_listing(), "")

    def test_the_bridges_own_report_is_passed_on_and_cut_and_never_raises(self):
        self.assertIn("fake bridge present=True", self.runtime(FakeBridge()).diagnostics())

        class Long(FakeBridge):
            def describe(self):
                return "x" * 1000

        class Broken(FakeBridge):
            def describe(self):
                raise RuntimeError("no")

        self.assertEqual(len(self.runtime(Long()).diagnostics()), 300)
        self.assertEqual(self.runtime(Broken()).diagnostics(), "")
        self.assertEqual(self.runtime(available=False).diagnostics(), "")


class RuntimeCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = os.path.join(self._tmp.name, "model.litertlm")
        with open(self.path, "wb") as handle:
            handle.write(b"not a real model")
        self.bridge = FakeBridge()
        self.runtime = engine_runtime(self.bridge)

    def marker(self):
        return LR.crash_guard_active(self.path)

    def loaded(self):
        return self.runtime.load(self.path, CARD)


class LoadTests(RuntimeCase):
    def test_a_good_load_leaves_the_marker_until_the_first_real_answer(self):
        loaded = self.loaded()
        self.assertEqual((loaded.model_id, loaded.runtime, loaded.path), ("own-test", "litertlm", self.path))
        self.assertEqual(self.bridge.loads, [(self.path, LR.ENGINE_CONTEXT_TOKENS)])
        self.assertTrue(self.marker(), "the load has not been proven yet: a death now must be remembered")
        report = self.runtime.smoke_test(loaded)
        self.assertTrue(report.ok, report)
        self.assertFalse(self.marker(), "the first real answer lifts the guard")

    def test_the_marker_is_written_before_the_engine_is_asked(self):
        seen = []

        class Watching(FakeBridge):
            def load(inner, path, tokens):
                seen.append(os.path.exists(path + LR.MARKER_SUFFIX))
                return super().load(path, tokens)

        engine_runtime(Watching()).load(self.path, CARD)
        self.assertEqual(seen, [True])

    def test_an_app_that_died_while_loading_is_not_loaded_into_again_by_itself(self):
        self.loaded()                                           # ... and the process dies here, before any answer
        revived = engine_runtime(FakeBridge())                  # the next start
        with self.assertRaises(RuntimeLoadError) as caught:
            revived.load(self.path, CARD)
        self.assertEqual(caught.exception.code, "crashed_before")
        self.assertEqual(revived._bridge().loads, [], "the engine was not touched")
        self.assertTrue(LR.reset_crash_guard(self.path), "the user's own «try again»")
        self.assertTrue(revived.load(self.path, CARD))

    def test_an_error_string_from_the_engine_lifts_the_guard_because_the_process_survived(self):
        self.bridge.load_result = "ERR\nengine_load_failed\nout of memory"
        with self.assertRaises(RuntimeLoadError) as caught:
            self.loaded()
        self.assertEqual((caught.exception.code, caught.exception.detail), ("engine_load_failed", "out of memory"))
        self.assertFalse(self.marker())

    def test_a_bare_error_string_becomes_a_load_failure_code(self):
        self.bridge.load_result = "ERR\n"
        with self.assertRaises(RuntimeLoadError) as caught:
            self.loaded()
        self.assertEqual(caught.exception.code, "engine_load_failed")
        self.bridge.load_result = "nonsense"
        with self.assertRaises(RuntimeLoadError) as caught:
            self.loaded()
        self.assertEqual(caught.exception.code, "bad_bridge_answer")
        self.assertFalse(self.marker())

    def test_a_python_level_exception_lifts_the_guard_and_names_only_its_type(self):
        self.bridge.raise_on_load = ValueError("secret path /data/x")
        with self.assertRaises(RuntimeLoadError) as caught:
            self.loaded()
        self.assertEqual((caught.exception.code, caught.exception.detail), ("engine_load_failed", "ValueError"))
        self.assertNotIn("secret", str(caught.exception))
        self.assertFalse(self.marker())

    def test_without_the_engine_nothing_is_loaded_and_no_marker_is_left(self):
        runtime = engine_runtime(FakeBridge(present=False))
        with self.assertRaises(RuntimeLoadError) as caught:
            runtime.load(self.path, CARD)
        self.assertEqual(caught.exception.code, "dependency_missing")
        self.assertFalse(self.marker())

    def test_a_missing_file_or_a_link_is_refused(self):
        with self.assertRaises(RuntimeLoadError) as caught:
            self.runtime.load(os.path.join(self._tmp.name, "absent.litertlm"), CARD)
        self.assertEqual(caught.exception.code, "model_file_invalid")
        link = os.path.join(self._tmp.name, "link.litertlm")
        os.symlink(self.path, link)
        with self.assertRaises(RuntimeLoadError) as caught:
            self.runtime.load(link, CARD)
        self.assertEqual(caught.exception.code, "model_file_invalid")
        self.assertEqual(self.bridge.loads, [])

    def test_the_guard_helpers_are_safe_on_paths_that_do_not_exist(self):
        absent = os.path.join(self._tmp.name, "nothing", "model.litertlm")
        self.assertFalse(LR.crash_guard_active(absent))
        self.assertTrue(LR.reset_crash_guard(absent))


class ChatTests(RuntimeCase):
    def test_the_engine_gets_the_parts_separately_and_cleaned(self):
        loaded = self.loaded()
        text = self.runtime.chat(loaded, "تو یک دستیار\x00 هستی", [("سلام", "درود")], "  چطوری؟\r\n ", max_tokens=40)
        self.assertEqual(text, "سلام! من مغزِ آزمایشی هستم.")
        call = self.bridge.chats[-1]
        self.assertEqual(call["system"], "تو یک دستیار هستی")
        self.assertEqual(call["history"], "سلام" + LR.FIELD_SEP + "درود")
        self.assertEqual(call["user"], "چطوری؟")
        self.assertEqual(call["max_tokens"], 40)

    def test_a_bare_prompt_is_one_user_message(self):
        loaded = self.loaded()
        self.runtime.generate(loaded, "یک جمله بگو", max_tokens=16, seed=0)
        call = self.bridge.chats[-1]
        self.assertEqual((call["system"], call["history"], call["user"], call["max_tokens"]), ("", "", "یک جمله بگو", 16))

    def test_an_answer_is_cut_to_the_token_budget(self):
        self.bridge.answers = ["کلمه " * 100]
        loaded = self.loaded()
        text = self.runtime.chat(loaded, "", (), "بگو", max_tokens=4)
        self.assertLessEqual(len(text), 4 * 5)
        self.assertTrue(text)

    def test_what_cannot_be_asked_is_refused_before_the_engine(self):
        loaded = self.loaded()
        calls = len(self.bridge.chats)
        for question in ("", "   ", "\x00\x01"):
            with self.assertRaises(RuntimeGenerateError) as caught:
                self.runtime.chat(loaded, "s", (), question, max_tokens=8)
            self.assertEqual((caught.exception.code, caught.exception.detail), ("bad_arguments", "empty_question"))
        with self.assertRaises(RuntimeGenerateError) as caught:
            self.runtime.chat(LoadedModel("x", "litertlm", object(), self.path), "", (), "سلام", max_tokens=8)
        self.assertEqual(caught.exception.code, "not_loaded")
        with self.assertRaises(RuntimeGenerateError) as caught:
            self.runtime.chat(LoadedModel("x", "litertlm", None, self.path), "", (), "سلام", max_tokens=8)
        self.assertEqual(caught.exception.code, "not_loaded")
        self.assertEqual(len(self.bridge.chats), calls)

    def test_every_way_the_engine_can_fail_has_a_stable_code(self):
        loaded = self.loaded()
        self.bridge.chat_error = "cancelled\nuser asked"
        with self.assertRaises(RuntimeGenerateError) as caught:
            self.runtime.chat(loaded, "", (), "سلام", max_tokens=8)
        self.assertEqual((caught.exception.code, caught.exception.detail), ("cancelled", "user asked"))
        self.bridge.chat_error = None
        self.bridge.answers = ["   "]
        with self.assertRaises(RuntimeGenerateError) as caught:
            self.runtime.chat(loaded, "", (), "سلام", max_tokens=8)
        self.assertEqual((caught.exception.code, caught.exception.detail), ("engine_bad_output", "empty"))

        class Raising(FakeBridge):
            def chat(inner, system, history, user, max_tokens):
                raise OSError("secret /data/user")

        runtime = engine_runtime(Raising())
        with self.assertRaises(RuntimeGenerateError) as caught:
            runtime.chat(LoadedModel("x", "litertlm", LR._Handle(Raising(), self.path), self.path), "", (), "سلام", max_tokens=8)
        self.assertEqual((caught.exception.code, caught.exception.detail), ("engine_generate_failed", "OSError"))
        self.assertNotIn("secret", str(caught.exception))


class SmokeTests(RuntimeCase):
    def test_a_real_answer_passes_and_lifts_the_guard(self):
        loaded = self.loaded()
        report = self.runtime.smoke_test(loaded)
        self.assertEqual((report.ok, report.details), (True, "non_empty_completion"))
        self.assertTrue(report.output_excerpt.startswith("سلام"))
        self.assertFalse(self.marker())

    def test_an_error_answer_fails_with_its_code_but_lifts_the_guard_the_process_lived(self):
        loaded = self.loaded()
        self.bridge.chat_error = "engine_error\nstate 7"
        report = self.runtime.smoke_test(loaded)
        self.assertEqual((report.ok, report.details), (False, "engine_error:state 7"))
        self.assertFalse(self.marker())

    def test_an_empty_answer_fails(self):
        loaded = self.loaded()
        self.bridge.answers = [""]
        report = self.runtime.smoke_test(loaded)
        self.assertFalse(report.ok)
        self.assertIn("engine_bad_output", report.details)


class CancelAndUnloadTests(RuntimeCase):
    def test_cancel_reaches_the_engine_and_never_raises(self):
        self.runtime.cancel()
        self.assertEqual(self.bridge.cancels, 1)
        engine_runtime(FakeBridge(), available=False).cancel()

        class Broken(FakeBridge):
            def cancel(inner):
                raise RuntimeError("no")

        engine_runtime(Broken()).cancel()

    def test_unload_frees_the_engine_forgets_the_handle_and_never_raises(self):
        loaded = self.loaded()
        self.runtime.unload(loaded)
        self.assertEqual(self.bridge.unloads, 1)
        self.assertIsNone(loaded.handle)
        self.runtime.unload(loaded)                                       # twice: nothing more to free
        self.assertEqual(self.bridge.unloads, 1)

        class Broken(FakeBridge):
            def unload(inner):
                raise RuntimeError("no")

        broken = engine_runtime(Broken())
        broken.unload(LoadedModel("x", "litertlm", LR._Handle(Broken(), self.path), self.path))


class DescriptionTests(unittest.TestCase):
    def test_it_announces_what_it_runs_and_that_it_never_executes_the_output(self):
        runtime = LR.LiteRtLmRuntime(jvm_provider=lambda: None)
        self.assertEqual((runtime.name, runtime.formats, runtime.supports_chat), ("litertlm", ("litertlm",), True))
        self.assertIn("هرگز اجرا نمی‌شود", runtime.description_fa)
        self.assertIn("never executed", runtime.description_en)


if __name__ == "__main__":
    unittest.main()
