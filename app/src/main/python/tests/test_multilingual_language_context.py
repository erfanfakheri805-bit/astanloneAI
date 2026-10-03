"""
Tests for Prompt 401 - Multilingual & Persian language readiness
(language_intelligence/language_context.py, the letter-only /
code-aware understanding/language_detection.py, the language fields on
LanguageUnderstandingResult / InferenceRequest / ModelInfo /
LocalModelConfig).

IMPORTANT - about the test doubles: `RecordingProvider` and
`ScriptedRuntime` below are TEST DOUBLES at the provider / runtime
boundary. Their output is whatever a test scripts into them; they are NOT
language models, perform NO inference, and nothing here downloads a model,
uses the network, or calls a cloud service. Every test is deterministic.

Run directly:
    python -m unittest tests.test_multilingual_language_context -v
(from app/src/main/python/)
"""

import json
import os
import re
import sys
import tempfile
import unicodedata
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import language_intelligence
from core.core import Core
from context.conversation_context import ConversationContext
from understanding.engine import UnderstandingEngine
from understanding.normalization import normalize
from understanding.language_detection import (
    detect_language, script_letter_counts, mask_non_prose,
    LANGUAGE_ENGLISH, LANGUAGE_PERSIAN, LANGUAGE_UNKNOWN,
)
from language_intelligence import language_context as language_context_module
from language_intelligence.language_context import (
    LanguageContext, build_language_context, resolve_response_language,
    detect_requested_language, conversation_language, canonical_language,
    CONFIDENCE_UNKNOWN, CONFIDENCE_LOW, CONFIDENCE_HIGH, DETECTION_METHOD_SCRIPT_HEURISTIC,
    SOURCE_EXPLICIT_REQUEST, SOURCE_CONVERSATION, SOURCE_DETECTED, SOURCE_DEFAULT, SOURCE_NONE,
)
from language_intelligence.deterministic_fallback_backend import DeterministicFallbackBackend
from language_intelligence.language_intelligence_core import LanguageIntelligenceCore
from language_intelligence.language_understanding_result import LanguageUnderstandingResult
from language_intelligence.backend import LanguageIntelligenceBackend
from language_intelligence.inference import (
    InferenceRequest, InferenceResult, ConversationMessage,
)
from language_intelligence.local_model_config import LocalModelConfig
from language_intelligence.local_model_mapping import build_inference_request
from language_intelligence.local_model_provider import (
    LocalModelProvider, RuntimeBackedProvider, ModelInfo,
)
from language_intelligence.local_model_backend import LocalLanguageModelBackend
from language_intelligence.local_model_runtime import (
    LocalModelRuntime, ModelAvailability, ModelLoadResult, RuntimeOutput,
    LOAD_OK, STATE_READY, STATE_UNLOADED,
)
from language_intelligence.response_generation import (
    STATUS_GENERATED, STATUS_MODEL_NOT_CONFIGURED,
)


# ----------------------------------------------------------------------
# Test doubles (NOT language models)
# ----------------------------------------------------------------------
class RecordingProvider(LocalModelProvider):
    """TEST PROVIDER: records every InferenceRequest it receives and
    returns a fixed scripted result."""

    def __init__(self):
        self.requests = []

    @property
    def provider_id(self):
        return "recording"

    def availability(self):
        return ModelAvailability(True, True, True, True, False, True, STATE_UNLOADED,
                                 model_id="scripted-model", runtime_name="scripted-engine")

    def model_info(self):
        return ModelInfo("recording", model_id="scripted-model")

    def load(self):
        return ModelLoadResult(LOAD_OK, "ok", None, "scripted-model", "scripted-engine")

    def generate(self, request, cancellation_token=None):
        self.requests.append(request)
        return InferenceResult.success("scripted-provider-output", model_id="scripted-model",
                                       runtime_name="scripted-engine")

    def resource_status(self):
        return {"state": STATE_READY, "loaded": True, "limits": None}


class ScriptedRuntime(LocalModelRuntime):
    """TEST DOUBLE runtime (scripted output only)."""

    @property
    def runtime_name(self):
        return "scripted-runtime"

    def _load_model(self, config):
        pass

    def _run_inference(self, request, params, config, control):
        return RuntimeOutput("scripted-runtime-output", "stop", 5, 2)


def _engine_backend(default_language=None):
    return DeterministicFallbackBackend(UnderstandingEngine(), default_language=default_language)


def _turns_context(*user_texts):
    context = ConversationContext(max_size=20)
    for text in user_texts:
        context.add_turn(text, "assistant reply")
    return context


# Samples used throughout ------------------------------------------------
FA_QUESTION = "سلام، پایتون چیست؟"
FA_LETTERS = "این یک متن پارسی با حروف پ چ ژ گ است"
FA_ARABIC_FORMS = "علي كتاب"                 # Arabic yeh (ي) and kaf (ك)
FA_PERSIAN_FORMS = "علی کتاب"                # Persian yeh (ی) and kaf (ک)
FA_ZWNJ = "پایتون یک زبان برنامه\u200cنویسی است."
FA_MIXED = "من از Python و Django استفاده می\u200cکنم"
CODE_BLOCK = "for item in items:\n    print(item)\n"
FA_WITH_CODE = "چرا این کد کار نمی\u200cکند؟\n```python\n" + CODE_BLOCK + "```\nممنون"


class TestPersianUnicodeInput(unittest.TestCase):
    """1. Persian Unicode input"""

    def test_persian_sentence_is_detected_as_persian(self):
        context = build_language_context(FA_QUESTION)
        self.assertEqual(context.detected_language, LANGUAGE_PERSIAN)
        self.assertEqual(context.scripts, ("arabic",))
        self.assertEqual(context.detection_confidence, CONFIDENCE_HIGH)
        self.assertFalse(context.mixed_script)

    def test_persian_specific_letters_are_supported(self):
        context = build_language_context(FA_LETTERS)
        self.assertEqual(context.detected_language, LANGUAGE_PERSIAN)
        self.assertEqual(context.original_text, FA_LETTERS)

    def test_zwnj_text_is_supported_and_untouched(self):
        context = build_language_context(FA_ZWNJ)
        self.assertEqual(context.detected_language, LANGUAGE_PERSIAN)
        self.assertIn("\u200c", context.original_text)
        self.assertEqual(context.original_text, FA_ZWNJ)

    def test_persian_is_not_forced_through_an_english_path(self):
        result = _engine_backend().understand(FA_QUESTION)
        self.assertEqual(result.detected_language, LANGUAGE_PERSIAN)
        self.assertEqual(result.language_context.response_language, LANGUAGE_PERSIAN)

    def test_arabic_and_persian_letter_forms_are_both_persian_script(self):
        for text in (FA_ARABIC_FORMS, FA_PERSIAN_FORMS):
            with self.subTest(text=text):
                context = build_language_context(text)
                self.assertEqual(context.detected_language, LANGUAGE_PERSIAN)
                self.assertEqual(context.scripts, ("arabic",))
                self.assertEqual(context.original_text, text)

    def test_arabic_and_persian_letters_are_not_unified(self):
        """Non-destructive: yeh/kaf variants stay exactly as typed."""
        self.assertNotEqual(FA_ARABIC_FORMS, FA_PERSIAN_FORMS)
        self.assertEqual(build_language_context(FA_ARABIC_FORMS).original_text, FA_ARABIC_FORMS)
        self.assertEqual(normalize(FA_ARABIC_FORMS).normalized_text, FA_ARABIC_FORMS)
        self.assertEqual(normalize(FA_PERSIAN_FORMS).normalized_text, FA_PERSIAN_FORMS)

    def test_context_is_json_serializable_with_persian_text(self):
        context = build_language_context(FA_QUESTION, normalized_text=FA_QUESTION)
        dumped = json.dumps(context.to_dict(), ensure_ascii=False)
        self.assertEqual(json.loads(dumped)["original_text"], FA_QUESTION)
        json.dumps(context.to_dict())   # also fine with ASCII escaping


class TestPersianPunctuation(unittest.TestCase):
    """2. Persian punctuation"""

    def test_persian_punctuation_alone_is_not_a_language(self):
        for text in ("؟", "،؛", "«»؟!", "؟؟؟ ،،،"):
            with self.subTest(text=text):
                self.assertEqual(detect_language(text), LANGUAGE_UNKNOWN)
                self.assertEqual(build_language_context(text).detected_language, LANGUAGE_UNKNOWN)

    def test_punctuation_is_preserved_in_original_and_normalized(self):
        text = "آیا این درست است؟ بله، درست؛ «سلام»"
        normalized = normalize(text).normalized_text
        for mark in ("؟", "،", "؛", "«", "»"):
            self.assertIn(mark, text)
            self.assertIn(mark, normalized)
        context = build_language_context(text, normalized_text=normalized)
        self.assertEqual(context.original_text, text)
        self.assertEqual(context.detected_language, LANGUAGE_PERSIAN)

    def test_arabic_question_mark_does_not_turn_english_into_persian(self):
        self.assertEqual(detect_language("Is this fine؟"), LANGUAGE_ENGLISH)


class TestPersianAndLatinDigits(unittest.TestCase):
    """3. Persian digits (and Latin digits)"""

    def test_digits_alone_carry_no_language(self):
        for text in ("۱۲۳۴۵", "12345", "٠١٢٣", "۱۲۳ 456 ٧٨٩", "۱۲.۵٪"):
            with self.subTest(text=text):
                self.assertEqual(detect_language(text), LANGUAGE_UNKNOWN)
                self.assertEqual(script_letter_counts(text), {})

    def test_persian_digits_do_not_outweigh_latin_letters(self):
        self.assertEqual(detect_language("ok ۱۲۳۴۵۶۷۸"), LANGUAGE_ENGLISH)

    def test_persian_sentence_with_persian_digits(self):
        text = "قیمت ۱۲۰۰ تومان و ۳ عدد است"
        context = build_language_context(text)
        self.assertEqual(context.detected_language, LANGUAGE_PERSIAN)
        self.assertEqual(context.original_text, text)
        for digit in ("۱", "۲", "۰", "۳"):
            self.assertIn(digit, text)

    def test_digits_are_never_converted(self):
        for text in ("عدد ۱۲۳ و 456 و ٧٨٩", "Room ۲۰۴ and 204"):
            with self.subTest(text=text):
                normalized = normalize(text).normalized_text
                self.assertEqual(normalized, text)
                self.assertEqual(build_language_context(text).original_text, text)

    def test_latin_digits_in_persian_text(self):
        context = build_language_context("نسخه 3.12 پایتون منتشر شد")
        self.assertEqual(context.detected_language, LANGUAGE_PERSIAN)
        self.assertEqual(context.scripts, ("arabic",))


class TestMixedPersianEnglish(unittest.TestCase):
    """4. Mixed Persian/English input (and 3. of the mixed-language spec)"""

    def test_persian_with_technical_english(self):
        context = build_language_context(FA_MIXED)
        self.assertEqual(context.detected_language, LANGUAGE_PERSIAN)
        self.assertEqual(set(context.scripts), {"arabic", "latin"})
        self.assertEqual(context.scripts[0], "arabic")
        self.assertTrue(context.mixed_script)
        self.assertEqual(context.detection_confidence, CONFIDENCE_LOW)
        self.assertEqual(context.original_text, FA_MIXED)
        self.assertEqual(context.response_language, LANGUAGE_PERSIAN)

    def test_english_with_persian_names(self):
        text = "Please introduce Ali to علی رضایی and مریم احمدی"
        context = build_language_context(text)
        self.assertEqual(context.detected_language, LANGUAGE_ENGLISH)
        self.assertTrue(context.mixed_script)
        self.assertEqual(set(context.scripts), {"arabic", "latin"})
        self.assertEqual(context.original_text, text)

    def test_dominant_language_is_not_presented_as_the_only_language(self):
        context = build_language_context(FA_MIXED).to_dict()
        self.assertTrue(context["mixed_script"])
        self.assertEqual(sorted(context["scripts"]), ["arabic", "latin"])

    def test_single_script_text_is_high_confidence_not_mixed(self):
        for text in (FA_QUESTION, "What is Python?"):
            with self.subTest(text=text):
                context = build_language_context(text)
                self.assertEqual(context.detection_confidence, CONFIDENCE_HIGH)
                self.assertFalse(context.mixed_script)

    def test_equal_mix_is_unknown_not_guessed(self):
        context = build_language_context("abc ابج")
        self.assertEqual(context.detected_language, LANGUAGE_UNKNOWN)
        self.assertEqual(context.detection_confidence, CONFIDENCE_UNKNOWN)
        self.assertTrue(context.mixed_script)

    def test_languages_can_alternate_across_one_conversation(self):
        engine = _engine_backend()
        results = [engine.understand(t) for t in ("What is Python?", FA_QUESTION, "Thanks!")]
        self.assertEqual([r.detected_language for r in results],
                         [LANGUAGE_ENGLISH, LANGUAGE_PERSIAN, LANGUAGE_ENGLISH])

    def test_other_scripts_are_reported_not_called_english(self):
        for text, script in (("Привет, как дела", "cyrillic"), ("你好，世界", "cjk"),
                             ("שלום עולם", "hebrew")):
            with self.subTest(script=script):
                context = build_language_context(text)
                self.assertEqual(context.detected_language, LANGUAGE_UNKNOWN)
                self.assertIn(script, context.scripts)
        self.assertEqual(detect_language("Привет hello"), LANGUAGE_UNKNOWN)


class TestPersianWithCodeAndNumbers(unittest.TestCase):
    """5. Persian + code / numbers / URLs"""

    def test_fenced_code_does_not_make_a_persian_question_english(self):
        # The code block has far more Latin letters than the sentence has Persian ones.
        self.assertGreater(sum(c.isascii() and c.isalpha() for c in FA_WITH_CODE),
                           sum(1 for c in FA_WITH_CODE if "\u0600" <= c <= "\u06ff"))
        context = build_language_context(FA_WITH_CODE)
        self.assertEqual(context.detected_language, LANGUAGE_PERSIAN)
        self.assertEqual(context.scripts, ("arabic",))
        self.assertEqual(context.response_language, LANGUAGE_PERSIAN)

    def test_inline_code_and_urls_are_ignored_for_detection(self):
        for text in ("چرا `print(len(items))` کار نمی\u200cکند؟",
                     "لینک https://example.com/very/long/path?query=value را باز کن",
                     "فایل `main.py` را در www.example.org/download ببین"):
            with self.subTest(text=text):
                self.assertEqual(build_language_context(text).detected_language, LANGUAGE_PERSIAN)

    def test_code_layout_and_symbols_survive_verbatim(self):
        text = FA_WITH_CODE + "\nx² + ۲ = ﬁle.txt"
        self.assertEqual(build_language_context(text).original_text, text)
        self.assertEqual(_engine_backend().understand(text).original_input, text)

    def test_unfenced_code_is_reported_as_mixed_rather_than_hidden(self):
        text = "چرا print(len(x)) کار نمی\u200cکند؟"
        context = build_language_context(text)
        self.assertTrue(context.mixed_script)
        self.assertEqual(context.original_text, text)

    def test_masking_only_affects_counting_not_the_text(self):
        text = "الف `code` ب https://x.y/z"
        masked = mask_non_prose(text)
        self.assertNotIn("code", masked)
        self.assertNotIn("https", masked)
        self.assertIn("الف", masked)
        self.assertEqual(build_language_context(text).original_text, text)
        self.assertEqual(_engine_backend().understand(text).original_input, text)

    def test_engine_and_context_agree_on_detection(self):
        samples = [
            "What is Python?", FA_QUESTION, FA_MIXED, FA_WITH_CODE, "۱۲۳", "", "   ",
            "Привет hello", "Please introduce Ali to علی رضایی and مریم احمدی",
            "چرا `print(x)`\nکار نمی\u200cکند؟", "x²  +  y", "؟؟؟",
            "text with `unfinished code", "Line one\nخط دوم\n\nLine three",
        ]
        backend = _engine_backend()
        for text in samples:
            with self.subTest(text=text):
                result = backend.understand(text)
                self.assertEqual(result.detected_language,
                                 result.language_context.detected_language)


class TestEnglishInput(unittest.TestCase):
    """6. English input"""

    def test_plain_english(self):
        context = build_language_context("What is Python?")
        self.assertEqual(context.detected_language, LANGUAGE_ENGLISH)
        self.assertEqual(context.scripts, ("latin",))
        self.assertEqual(context.detection_confidence, CONFIDENCE_HIGH)
        self.assertEqual(context.detection_method, DETECTION_METHOD_SCRIPT_HEURISTIC)
        self.assertEqual(context.response_language, LANGUAGE_ENGLISH)
        self.assertEqual(context.response_language_source, SOURCE_DETECTED)

    def test_english_with_digits_and_code(self):
        text = "Why does `x = 1` print ۲?"
        self.assertEqual(build_language_context(text).detected_language, LANGUAGE_ENGLISH)


class TestUnknownLanguage(unittest.TestCase):
    """7. Unknown language"""

    def test_no_letters_is_unknown(self):
        for text in ("", "   ", "12345 !!! ???", "😀😀", "...", None):
            with self.subTest(text=text):
                context = build_language_context(text)
                self.assertEqual(context.detected_language, LANGUAGE_UNKNOWN)
                self.assertEqual(context.detection_confidence, CONFIDENCE_UNKNOWN)
                self.assertEqual(context.scripts, ())
                self.assertIsNone(context.response_language)
                self.assertEqual(context.response_language_source, SOURCE_NONE)

    def test_unknown_uses_the_configured_default_and_says_so(self):
        context = build_language_context("12345", default_language="fa")
        self.assertEqual(context.response_language, LANGUAGE_PERSIAN)
        self.assertEqual(context.response_language_source, SOURCE_DEFAULT)
        self.assertEqual(context.detected_language, LANGUAGE_UNKNOWN)   # still unknown

    def test_non_string_input_never_raises(self):
        for value in (None, 12345, b"bytes".decode(), ["x"]):
            with self.subTest(value=value):
                self.assertIsInstance(build_language_context(value), LanguageContext)

    def test_empty_input_through_the_backend(self):
        result = _engine_backend().understand("")
        self.assertEqual(result.language_context.detected_language, LANGUAGE_UNKNOWN)
        self.assertEqual(result.original_input, "")


class TestExplicitResponseLanguage(unittest.TestCase):
    """8. Explicit response-language request"""

    def test_argument_wins_over_everything(self):
        context = build_language_context(
            FA_QUESTION, conversation=_turns_context("Hello", "How are you", "Fine"),
            requested_language="en", default_language="fa")
        self.assertEqual(context.requested_language, LANGUAGE_ENGLISH)
        self.assertEqual(context.response_language, LANGUAGE_ENGLISH)
        self.assertEqual(context.response_language_source, SOURCE_EXPLICIT_REQUEST)

    def test_argument_beats_a_request_in_the_text(self):
        context = build_language_context("Please answer in English.", requested_language="persian")
        self.assertEqual(context.response_language, LANGUAGE_PERSIAN)

    def test_codes_and_names_are_canonicalized(self):
        for value in ("fa", "FA", "fas", "Farsi", "persian", "fa-IR", " fa_IR "):
            with self.subTest(value=value):
                self.assertEqual(canonical_language(value), LANGUAGE_PERSIAN)
        for value in ("en", "eng", "English", "en-US", "en_GB"):
            with self.subTest(value=value):
                self.assertEqual(canonical_language(value), LANGUAGE_ENGLISH)
        self.assertEqual(canonical_language("FI"), "fi")           # unknown code: passthrough
        for value in (None, "", "  ", "unknown", "und", 5, ["fa"]):
            with self.subTest(value=value):
                self.assertIsNone(canonical_language(value))

    def test_invalid_argument_is_ignored(self):
        context = build_language_context(FA_QUESTION, requested_language=42)
        self.assertIsNone(context.requested_language)
        self.assertEqual(context.response_language, LANGUAGE_PERSIAN)

    def test_english_requests_in_the_text(self):
        cases = {
            "Please answer in Persian.": LANGUAGE_PERSIAN,
            "Could you reply to me in English?": LANGUAGE_ENGLISH,
            "Speak in Farsi": LANGUAGE_PERSIAN,
            "Thanks, respond in the English language": LANGUAGE_ENGLISH,
            "What is a list? Answer in Persian, please": LANGUAGE_PERSIAN,
            "Reply in French. Actually, reply in German.": "german",   # last request wins
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(detect_requested_language(text), expected)

    def test_persian_requests_in_the_text(self):
        cases = {
            "لطفا به انگلیسی جواب بده": LANGUAGE_ENGLISH,
            "فارسی جواب بده": LANGUAGE_PERSIAN,
            "به فارسی صحبت کن": LANGUAGE_PERSIAN,
            "جواب را به انگلیسی بده": LANGUAGE_ENGLISH,
            "با انگلیسي حرف بزن": LANGUAGE_ENGLISH,        # Arabic yeh spelling
            "پاسخ خودت را به زبان فارسی بده": LANGUAGE_PERSIAN,
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(detect_requested_language(text), expected)

    def test_non_requests_are_not_mistaken_for_requests(self):
        for text in (
            "How do you say hello in Persian?", "Do not answer in Persian",
            "Never respond in English", "I answer in English at work",
            "Explain the English language.", "Can you speak Persian?", "answer in detail",
            "Please answer `in English` hello", "What is Persian?", "Translate this to French",
            "زبان انگلیسی را توضیح بده", "به انگلیسی جواب نده", "سلام حالت چطوره؟", "", None,
        ):
            with self.subTest(text=text):
                self.assertIsNone(detect_requested_language(text))

    def test_request_in_text_becomes_the_response_language(self):
        context = build_language_context("What is a list? Please answer in Persian.")
        self.assertEqual(context.detected_language, LANGUAGE_ENGLISH)
        self.assertEqual(context.response_language, LANGUAGE_PERSIAN)
        self.assertEqual(context.response_language_source, SOURCE_EXPLICIT_REQUEST)

    def test_text_request_beats_conversation_language(self):
        context = build_language_context(
            "لطفا به انگلیسی جواب بده", conversation=_turns_context(FA_QUESTION, FA_ZWNJ))
        self.assertEqual(context.conversation_language, LANGUAGE_PERSIAN)
        self.assertEqual(context.response_language, LANGUAGE_ENGLISH)

    def test_explicit_request_reaches_the_backend_through_the_core(self):
        core = LanguageIntelligenceCore(_engine_backend())
        result = core.understand("What is Python?", requested_language="fa")
        self.assertEqual(result.language_context.response_language, LANGUAGE_PERSIAN)
        self.assertEqual(result.detected_language, LANGUAGE_ENGLISH)

    def test_requested_language_is_only_forwarded_when_given(self):
        """A backend written before Prompt 401 must keep working."""
        class OldBackend(LanguageIntelligenceBackend):
            @property
            def backend_kind(self):
                return "old"

            def understand(self, raw_text, context=None, relevant_context=None,
                           resolved_reference=None, active_topic=None):
                return raw_text

        self.assertEqual(LanguageIntelligenceCore(OldBackend()).understand("hi"), "hi")


class TestConversationLanguageContinuity(unittest.TestCase):
    """9. Conversation language continuity"""

    def test_persian_conversation_keeps_persian_for_an_english_message(self):
        context = build_language_context(
            "What is a decorator?", conversation=_turns_context(FA_QUESTION, FA_ZWNJ))
        self.assertEqual(context.detected_language, LANGUAGE_ENGLISH)
        self.assertEqual(context.conversation_language, LANGUAGE_PERSIAN)
        self.assertEqual(context.response_language, LANGUAGE_PERSIAN)
        self.assertEqual(context.response_language_source, SOURCE_CONVERSATION)

    def test_english_conversation_keeps_english_for_an_ambiguous_message(self):
        context = build_language_context(
            "12345", conversation=_turns_context("Hello there", "What is Python?"))
        self.assertEqual(context.response_language, LANGUAGE_ENGLISH)
        self.assertEqual(context.response_language_source, SOURCE_CONVERSATION)

    def test_one_off_language_does_not_switch_the_conversation(self):
        history = _turns_context(FA_QUESTION, FA_ZWNJ, "What is Python?")
        self.assertEqual(conversation_language(history), LANGUAGE_PERSIAN)

    def test_sustained_change_moves_the_conversation_language(self):
        history = _turns_context(FA_QUESTION, "What is Python?", "Explain lists please")
        self.assertEqual(conversation_language(history), LANGUAGE_ENGLISH)

    def test_tie_goes_to_the_most_recent_language(self):
        self.assertEqual(conversation_language(_turns_context(FA_QUESTION, "What is Python?"),
                                               window=2), LANGUAGE_ENGLISH)
        self.assertEqual(conversation_language(_turns_context("What is Python?", FA_QUESTION),
                                               window=2), LANGUAGE_PERSIAN)

    def test_only_the_recent_window_counts(self):
        history = _turns_context(*(["Hello there"] * 5 + [FA_QUESTION, FA_ZWNJ, FA_LETTERS]))
        self.assertEqual(conversation_language(history), LANGUAGE_PERSIAN)

    def test_unknown_turns_and_assistant_replies_are_ignored(self):
        history = ConversationContext()
        history.add_turn(FA_QUESTION, "This reply is in English and says nothing about the user.")
        history.add_turn("۱۲۳", "Another English reply.")
        history.add_turn("😀", "More English.")
        self.assertEqual(conversation_language(history), LANGUAGE_PERSIAN)

    def test_no_context_or_no_known_language_gives_none(self):
        self.assertIsNone(conversation_language(None))
        self.assertIsNone(conversation_language(ConversationContext()))
        self.assertIsNone(conversation_language(_turns_context("123", "!!!")))
        self.assertIsNone(conversation_language(object()))
        self.assertIsNone(conversation_language(_turns_context("Hi"), window=0))

    def test_language_does_not_flip_randomly_across_a_persian_conversation(self):
        history = _turns_context(FA_QUESTION, FA_ZWNJ)
        for message in ("What is Python?", "ok", "12345", FA_MIXED, "Thanks!", ""):
            with self.subTest(message=message):
                context = build_language_context(message, conversation=history)
                self.assertEqual(context.response_language, LANGUAGE_PERSIAN)

    def test_building_a_context_does_not_modify_the_conversation(self):
        history = _turns_context(FA_QUESTION, "What is Python?")
        before = history.get_recent_turns()
        for _ in range(3):
            build_language_context("Anything", conversation=history)
        self.assertEqual(history.get_recent_turns(), before)
        self.assertEqual(len(history), 0)

    def test_backend_reads_the_conversation_through_context(self):
        result = _engine_backend().understand(
            "What is Python?", context=_turns_context(FA_QUESTION, FA_ZWNJ))
        self.assertEqual(result.language_context.response_language, LANGUAGE_PERSIAN)
        self.assertEqual(result.detected_language, LANGUAGE_ENGLISH)   # message itself unchanged

    def test_priority_order_directly(self):
        cases = [
            (("fa", "en", "english", "en"), (LANGUAGE_PERSIAN, SOURCE_EXPLICIT_REQUEST)),
            ((None, "fa", "english", "en"), (LANGUAGE_PERSIAN, SOURCE_CONVERSATION)),
            ((None, None, "persian", "en"), (LANGUAGE_PERSIAN, SOURCE_DETECTED)),
            ((None, None, "unknown", "en"), (LANGUAGE_ENGLISH, SOURCE_DEFAULT)),
            ((None, None, "unknown", None), (None, SOURCE_NONE)),
            ((None, None, None, None), (None, SOURCE_NONE)),
        ]
        for args, expected in cases:
            with self.subTest(args=args):
                self.assertEqual(resolve_response_language(*args), expected)


class TestOriginalTextPreservation(unittest.TestCase):
    """10. Original text preservation"""

    TRICKY = [
        "  leading and trailing whitespace  ",
        FA_ZWNJ, FA_ARABIC_FORMS, FA_PERSIAN_FORMS,
        "عدد ۱۲۳ و 456 و ٧٨٩",
        "\u200fمتن با علامت راست‌به‌چپ\u200f",
        "x² + y³ = ﬁle_name.txt ｆｕｌｌｗｉｄｔｈ … ①",
        FA_WITH_CODE,
        "line1\n\n\tindented\n    spaces\r\nwindows",
        "see https://example.com/a_b?c=d#e and C:\\Users\\علی\\file (1).txt",
        "Hello  \t  world",
        "ﻣﺮﺣﺒﺎ ﺑﺎﻟﻌﺎﻟﻢ",   # Arabic presentation forms
    ]

    def test_context_original_text_is_verbatim(self):
        for text in self.TRICKY:
            with self.subTest(text=text):
                self.assertEqual(build_language_context(text).original_text, text)

    def test_understanding_result_original_is_verbatim(self):
        backend = _engine_backend()
        for text in self.TRICKY:
            with self.subTest(text=text):
                result = backend.understand(text)
                self.assertEqual(result.original_input, text)
                self.assertEqual(result.language_context.original_text, text)

    def test_model_request_user_input_is_the_original_not_the_normalized_text(self):
        backend = _engine_backend()
        for text in self.TRICKY:
            if not text.strip():
                continue
            with self.subTest(text=text):
                understanding = backend.understand(text)
                request = build_inference_request(understanding)
                self.assertEqual(request.user_input, text)
                self.assertEqual(request.language_context.original_text, text)

    def test_normalized_text_is_kept_separate_and_may_differ(self):
        text = "x²   +   ۲\n\n  ﬁle"
        result = _engine_backend().understand(text)
        self.assertEqual(result.original_input, text)
        self.assertNotEqual(result.normalized_input, text)
        self.assertEqual(result.language_context.normalized_text, result.normalized_input)
        self.assertEqual(result.language_context.original_text, text)

    def test_no_language_instruction_is_injected_into_the_text_or_prompt(self):
        understanding = _engine_backend().understand(FA_QUESTION)
        request = build_inference_request(understanding)
        self.assertEqual(request.user_input, FA_QUESTION)
        self.assertIsNone(request.system_prompt)
        self.assertEqual(request.conversation, [])


class TestNonDestructiveNormalization(unittest.TestCase):
    """11. Non-destructive normalization"""

    def test_persian_characters_survive_normalization(self):
        for text in (FA_ZWNJ, FA_LETTERS, FA_ARABIC_FORMS, FA_PERSIAN_FORMS,
                     "آیا «این» درست است؟ ۱۲۳"):
            with self.subTest(text=text):
                self.assertEqual(normalize(text).normalized_text, text)

    def test_zwnj_is_not_treated_as_whitespace(self):
        normalized = normalize("می\u200cخواهم   بروم").normalized_text
        self.assertEqual(normalized, "می\u200cخواهم بروم")

    def test_normalization_changes_layout_only_for_whitespace(self):
        text = "  سلام \n\n  دنیا  "
        self.assertEqual(normalize(text).normalized_text, "سلام دنیا")
        self.assertEqual(build_language_context(text).original_text, text)

    def test_detection_does_not_depend_on_normalization(self):
        for text in (FA_QUESTION, FA_MIXED, FA_WITH_CODE, "  What is Python?  \n"):
            with self.subTest(text=text):
                self.assertEqual(detect_language(text), detect_language(normalize(text).normalized_text))

    def test_normalized_text_is_analysis_only_not_used_for_detection(self):
        context = build_language_context(FA_QUESTION, normalized_text="English words here")
        self.assertEqual(context.normalized_text, "English words here")     # kept as given
        self.assertEqual(context.detected_language, LANGUAGE_PERSIAN)        # from the original
        self.assertEqual(context.original_text, FA_QUESTION)

    def test_normalization_stays_semantic_for_arabic_presentation_forms(self):
        text = "ﻣﺮﺣﺒﺎ"
        normalized = normalize(text).normalized_text
        self.assertEqual(normalized, unicodedata.normalize("NFKC", text))
        self.assertEqual(detect_language(text), LANGUAGE_PERSIAN)


class TestLanguageMetadataPropagation(unittest.TestCase):
    """12. Language metadata propagation into the model-provider request"""

    def _run(self, text, context=None, provider=None, **backend_kwargs):
        provider = provider or RecordingProvider()
        backend = LocalLanguageModelBackend(provider=provider, **backend_kwargs)
        understanding = _engine_backend().understand(text, context=context)
        response = backend.generate_response(understanding, context=context)
        return understanding, provider, response

    def test_language_context_reaches_the_provider_untouched(self):
        understanding, provider, response = self._run(FA_QUESTION)
        self.assertEqual(len(provider.requests), 1)
        request = provider.requests[0]
        self.assertIsInstance(request, InferenceRequest)
        self.assertIs(request.language_context, understanding.language_context)
        self.assertEqual(request.user_input, FA_QUESTION)
        self.assertEqual(request.language_context.detected_language, LANGUAGE_PERSIAN)
        self.assertEqual(request.language_context.response_language, LANGUAGE_PERSIAN)
        self.assertEqual(request.language_context.scripts, ("arabic",))
        self.assertEqual(response.status, STATUS_GENERATED)

    def test_mixed_input_reaches_the_provider_with_all_scripts(self):
        _, provider, _ = self._run(FA_MIXED)
        context = provider.requests[0].language_context
        self.assertEqual(provider.requests[0].user_input, FA_MIXED)
        self.assertTrue(context.mixed_script)
        self.assertEqual(set(context.scripts), {"arabic", "latin"})

    def test_conversation_and_request_language_propagate(self):
        history = _turns_context(FA_QUESTION, FA_ZWNJ)
        _, provider, _ = self._run("What is a decorator?", context=history, max_context_turns=2)
        request = provider.requests[0]
        self.assertEqual(request.language_context.conversation_language, LANGUAGE_PERSIAN)
        self.assertEqual(request.language_context.response_language, LANGUAGE_PERSIAN)
        self.assertEqual(request.user_input, "What is a decorator?")
        self.assertEqual([m.content for m in request.conversation][::2], [FA_QUESTION, FA_ZWNJ])

    def test_request_serializes_the_language_context(self):
        _, provider, _ = self._run(FA_QUESTION)
        as_dict = provider.requests[0].to_dict()
        self.assertEqual(as_dict["language_context"]["response_language"], LANGUAGE_PERSIAN)
        self.assertEqual(as_dict["language_context"]["original_text"], FA_QUESTION)
        self.assertEqual(as_dict["user_input"], FA_QUESTION)
        json.dumps(as_dict, ensure_ascii=False)

    def test_system_prompt_is_only_what_the_caller_configured(self):
        _, provider, _ = self._run(FA_QUESTION, system_prompt="Be brief.")
        self.assertEqual(provider.requests[0].system_prompt, "Be brief.")

    def test_language_context_is_separate_from_the_input_size(self):
        request = InferenceRequest("abc", language_context=build_language_context("abc"))
        self.assertEqual(request.input_char_count(), 3)

    def test_runtime_backed_provider_passes_it_to_the_runtime(self):
        seen = []

        class SpyRuntime(ScriptedRuntime):
            def _run_inference(self, request, params, config, control):
                seen.append(request)
                return super()._run_inference(request, params, config, control)

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "m.gguf")
            with open(path, "wb") as handle:
                handle.write(b"\0" * 16)
            runtime = SpyRuntime(LocalModelConfig(model_id="m", model_path=path,
                                                  context_length=512, max_output_tokens=64))
            backend = LocalLanguageModelBackend(runtime)
            understanding = _engine_backend().understand(FA_QUESTION)
            response = backend.generate_response(understanding)
        self.assertEqual(response.status, STATUS_GENERATED)
        self.assertEqual(response.response_text, "scripted-runtime-output")   # from the double
        self.assertIs(seen[0].language_context, understanding.language_context)
        self.assertEqual(seen[0].user_input, FA_QUESTION)

    def test_understanding_without_language_context_yields_a_request_without_one(self):
        legacy = LanguageUnderstandingResult(
            original_input="Hello", detected_language="english", normalized_input="Hello",
            intent="unknown", entities=[], referenced_items=[], active_topic=None,
            conversation_context=None, confidence=0.5, ambiguity=False,
            needs_clarification=False)
        self.assertIsNone(legacy.language_context)
        self.assertIsNone(legacy.to_dict()["language_context"])
        request = build_inference_request(legacy)
        self.assertIsNone(request.language_context)
        self.assertEqual(request.validate(), [])
        self.assertIsNone(request.to_dict()["language_context"])

    def test_invalid_language_context_is_reported_not_raised(self):
        request = InferenceRequest("hi", language_context="persian")
        self.assertTrue(any("language_context" in p for p in request.validate()))

    def test_unconfigured_backend_still_reports_no_model_and_no_text(self):
        understanding = _engine_backend().understand(FA_QUESTION)
        response = LocalLanguageModelBackend().generate_response(understanding)
        self.assertEqual(response.status, STATUS_MODEL_NOT_CONFIGURED)
        self.assertIsNone(response.response_text)

    def test_core_wires_language_context_into_the_understanding(self):
        with tempfile.TemporaryDirectory() as tmp:
            core = Core(memory_db_path=os.path.join(tmp, "m.sqlite3"),
                        skill_definitions_dir=os.path.join(tmp, "skills"))
            first = core.understand_language(FA_QUESTION)
            self.assertEqual(first.language_context.response_language, LANGUAGE_PERSIAN)
            core.process_input(FA_QUESTION)
            core.process_input(FA_ZWNJ)
            later = core.understand_language("What is a decorator?")
            self.assertEqual(later.language_context.conversation_language, LANGUAGE_PERSIAN)
            self.assertEqual(later.language_context.response_language, LANGUAGE_PERSIAN)
            self.assertEqual(later.original_input, "What is a decorator?")


class TestModelLanguageCapabilities(unittest.TestCase):
    """5. Multilingual model contract - declared, never assumed"""

    def _model_file(self, tmp):
        path = os.path.join(tmp, "m.gguf")
        with open(path, "wb") as handle:
            handle.write(b"\0" * 16)
        return path

    def test_nothing_declared_means_everything_unknown(self):
        info = ModelInfo("p", model_id="m")
        self.assertIsNone(info.supported_languages)
        self.assertIsNone(info.supported_scripts)
        self.assertIsNone(info.multilingual)
        self.assertIsNone(info.default_language)
        self.assertIsNone(info.supports_language("persian"))
        self.assertIsNone(info.supports_language("fa"))
        self.assertIsNone(info.supports_script("arabic"))

    def test_multilingual_flag_alone_does_not_claim_persian(self):
        info = ModelInfo("p", model_id="m", multilingual=True)
        self.assertTrue(info.multilingual)
        self.assertIsNone(info.supports_language("persian"))

    def test_declared_languages_are_matched_across_codes_and_names(self):
        info = ModelInfo("p", model_id="m", supported_languages=["en", "fa"],
                         supported_scripts=["Latin", "Arabic"], multilingual=True,
                         default_language="fa")
        self.assertTrue(info.supports_language("persian"))
        self.assertTrue(info.supports_language("FA"))
        self.assertTrue(info.supports_language("english"))
        self.assertFalse(info.supports_language("french"))
        self.assertTrue(info.supports_script("arabic"))
        self.assertFalse(info.supports_script("cyrillic"))
        self.assertIsNone(info.supports_language(None))
        self.assertIsNone(info.supports_language("unknown"))
        as_dict = info.to_dict()
        self.assertEqual(as_dict["supported_languages"], ["en", "fa"])
        self.assertEqual(as_dict["supported_scripts"], ["Latin", "Arabic"])
        self.assertTrue(as_dict["multilingual"])
        self.assertEqual(as_dict["default_language"], "fa")

    def test_declared_english_only_model_is_not_reported_as_persian_capable(self):
        self.assertFalse(ModelInfo("p", supported_languages=["en"]).supports_language("persian"))

    def test_model_info_is_backward_compatible(self):
        info = ModelInfo("p", "m", "gguf", ("en",), 512, 64, True, False, "rt")
        self.assertEqual(info.supported_languages, ("en",))
        self.assertEqual(info.runtime_name, "rt")
        self.assertIsNone(info.multilingual)

    def test_config_without_declaration_gives_unknown_model_info(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = LocalModelConfig(model_id="m", model_path=self._model_file(tmp))
            self.assertTrue(config.validate().valid)
            info = RuntimeBackedProvider(ScriptedRuntime(config)).model_info()
        self.assertIsNone(info.supported_languages)
        self.assertIsNone(info.multilingual)
        self.assertIsNone(info.supports_language("persian"))

    def test_config_declaration_reaches_model_info(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = LocalModelConfig(
                model_id="m", model_path=self._model_file(tmp),
                supported_languages=["en", "fa"], supported_scripts=["latin", "arabic"],
                multilingual=True, default_language="fa")
            self.assertTrue(config.validate().valid, config.validate().problems)
            info = LocalLanguageModelBackend(ScriptedRuntime(config)).model_info()
        self.assertTrue(info.supports_language("persian"))
        self.assertTrue(info.multilingual)
        self.assertEqual(info.default_language, "fa")
        self.assertEqual(info.supported_scripts, ("latin", "arabic"))

    def test_config_round_trips_through_a_dict(self):
        config = LocalModelConfig(model_id="m", model_path="/x/m.gguf",
                                  supported_languages=["en", "fa"], multilingual=True)
        rebuilt = LocalModelConfig.from_dict(json.loads(json.dumps(config.to_dict())))
        self.assertEqual(rebuilt.to_dict(), config.to_dict())
        self.assertEqual(rebuilt.validate().problems, [])

    def test_config_rejects_bad_declarations(self):
        bad = [
            dict(supported_languages="fa"),
            dict(supported_languages=[]),
            dict(supported_languages=["fa", ""]),
            dict(supported_languages=["fa", 3]),
            dict(supported_scripts="arabic"),
            dict(multilingual="yes"),
            dict(default_language=5),
            dict(default_language="unknown"),
            dict(supported_languages=["en"], default_language="fa"),
        ]
        for extra in bad:
            with self.subTest(extra=extra):
                config = LocalModelConfig(model_id="m", model_path="/x/m.gguf", **extra)
                key = list(extra)[-1]      # the field the problem is reported against
                self.assertTrue(any(p.startswith(key) for p in config.validate().problems),
                                config.validate().problems)

    def test_config_default_language_may_be_any_when_languages_undeclared(self):
        config = LocalModelConfig(model_id="m", model_path="/x/m.gguf", default_language="fa")
        self.assertEqual(config.validate().problems, [])


class TestEnglishBackwardCompatibility(unittest.TestCase):
    """13. Existing English behavior remains compatible"""

    def test_english_understanding_fields_are_unchanged(self):
        engine = UnderstandingEngine()
        reference = engine.understand("What is Python?")
        result = DeterministicFallbackBackend(engine).understand("What is Python?")
        self.assertEqual(result.original_input, "What is Python?")
        self.assertEqual(result.normalized_input, reference.normalized_text)
        self.assertEqual(result.detected_language, reference.language)
        self.assertEqual(result.detected_language, LANGUAGE_ENGLISH)
        self.assertEqual(result.entities, reference.entities)
        self.assertEqual(result.intent, "ask_question")
        self.assertAlmostEqual(result.confidence, reference.confidence)

    def test_existing_constructors_and_calls_still_work(self):
        self.assertIsNotNone(DeterministicFallbackBackend(UnderstandingEngine()))
        self.assertEqual(InferenceRequest("hi").validate(), [])
        self.assertEqual(InferenceRequest("hi").language_context, None)
        self.assertEqual(LocalModelConfig(model_id="m", model_path="/x/m.gguf").validate().problems,
                         [])
        result = LanguageIntelligenceCore(_engine_backend()).understand("Python uses indentation.")
        self.assertEqual(result.detected_language, LANGUAGE_ENGLISH)

    def test_simple_detector_behavior_is_unchanged(self):
        self.assertEqual(detect_language("Python is a programming language."), LANGUAGE_ENGLISH)
        self.assertEqual(detect_language("پایتون یک زبان برنامه‌نویسی است."), LANGUAGE_PERSIAN)
        self.assertEqual(detect_language(""), LANGUAGE_UNKNOWN)
        self.assertEqual(detect_language("123 !!! ???"), LANGUAGE_UNKNOWN)

    def test_english_message_in_an_english_conversation(self):
        history = _turns_context("Hello", "What is Python?")
        result = _engine_backend().understand("Python is a programming language.", context=history)
        self.assertEqual(result.language_context.response_language, LANGUAGE_ENGLISH)

    def test_to_dict_of_the_understanding_keeps_every_existing_field(self):
        as_dict = _engine_backend().understand("Python uses indentation.").to_dict()
        for field in ("original_input", "detected_language", "normalized_input", "intent",
                      "entities", "referenced_items", "active_topic", "conversation_context",
                      "confidence", "ambiguity", "needs_clarification", "warnings",
                      "source_backend", "language_context"):
            self.assertIn(field, as_dict)
        json.dumps(as_dict, ensure_ascii=False)


class TestNoFakeLanguageIntelligence(unittest.TestCase):
    """9./10. No fake AI, no cloud, small surface"""

    FORBIDDEN_IMPORTS = {
        "requests", "urllib", "urllib3", "http", "httpx", "socket", "ssl", "aiohttp",
        "openai", "anthropic", "google", "boto3", "ftplib", "smtplib", "websocket",
        "random", "subprocess", "os", "sys", "json",
    }

    @staticmethod
    def _source(name):
        base = os.path.dirname(language_intelligence.__file__)
        with open(os.path.join(base, name), encoding="utf-8") as handle:
            return handle.read()

    def test_language_context_module_is_pure_on_device_code(self):
        source = self._source("language_context.py")
        imported = {m.group(1) for m in re.finditer(
            r"^\s*(?:from|import)\s+([A-Za-z_]\w*)", source, re.M)}
        self.assertEqual(imported & self.FORBIDDEN_IMPORTS, set())
        lowered = source.lower()
        self.assertNotIn("api_key", lowered)
        self.assertNotIn("apikey", lowered)
        self.assertNotIn("http://", lowered)
        self.assertNotIn("open(", lowered)

    def test_language_context_module_exposes_no_text_generation(self):
        names = [n for n in dir(language_context_module)
                 if not n.startswith("_") and callable(getattr(language_context_module, n))]
        self.assertFalse([n for n in names if any(
            word in n.lower() for word in ("generate", "translate", "reply", "respond", "fake")
        )], names)

    def test_recognizers_return_identifiers_never_sentences(self):
        for text in ("Please answer in Persian.", "به انگلیسی جواب بده", FA_QUESTION):
            value = detect_requested_language(text)
            self.assertTrue(value is None or value in
                            {"english", "persian", "arabic", "french", "german", "spanish"})

    def test_deterministic_backend_still_generates_no_text(self):
        response = _engine_backend().generate_response(_engine_backend().understand(FA_QUESTION))
        self.assertIsNone(response.response_text)

    def test_context_building_is_deterministic(self):
        first = build_language_context(FA_MIXED, conversation=_turns_context(FA_QUESTION))
        second = build_language_context(FA_MIXED, conversation=_turns_context(FA_QUESTION))
        self.assertEqual(first.to_dict(), second.to_dict())

    def test_detection_source_is_labeled_a_heuristic(self):
        self.assertEqual(build_language_context(FA_QUESTION).detection_method,
                         "script_heuristic")


if __name__ == "__main__":
    unittest.main()
