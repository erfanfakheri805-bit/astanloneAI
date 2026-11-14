"""
Prompt 959 (corrective release) - the cloud brain through the REAL front door, exactly as the phone runs it.

Why this file exists: on a real phone «مغز ابری را فعال کن» answered «باشد، چیزی راه‌اندازی نشد…» every single time. The cause was a
difference between the tests and the phone that no test had covered: the application builds its Persian brain as `PersianBrain(memory)`
WITHOUT a clock (only tests inject one), and the setup called that missing clock. Every earlier test of the cloud brain gave the brain a
fake clock and called `brain.respond` directly, so they all passed.

Everything here goes the way a message really goes: HTTP `POST /api/message` -> `RuntimeCore.process_input` -> `Core` -> skills ->
Persian brain (built with NO injected clock, like production) -> cloud brain. Only the outside world (the cloud provider) is scripted.
It also pins the colloquial sentences people really type («مغز ابریت رو فعال کنم», «چجوری … فعال کنم», «چرا؟») and the rule that a
pasted key leaves no trace in the app's database file even on a SQLite that does not zero deleted rows.
"""
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from unittest import mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import android_entry
from brain_hub.service import HubService, default_root, set_hub
from net_tools import TransportError
from brain_v2 import providers
from interface.server import make_handler
from memory.memory_system import MemorySystem
from persian_brain import hub_brain
from persian_brain import hub_brain_commands as BC
from persian_brain import hub_hooks
from persian_brain import hub_messages_brain as BM
from persian_brain import hub_messages_self as HS
from persian_brain import hub_intents as HI
from persian_brain import normalization as nz
from persian_brain.brain import PersianBrain
from platform_layer import set_platform
from runtime_integration.runtime_core import RuntimeCore
from self_builder import fa_text
from tests import brain_hub_fixtures_prompt957 as F
from tests.persian_app_case_prompt957 import AppCase
from tests.test_pack_chat_prompt958 import PackChatCase
from tests.nobody_answered_prompt959 import nobody_answered
from tests.test_brain_v2_core_prompt959 import JSON, KEY, Fake, openai_answer

ANSWER = "پایتخت فرانسه پاریس است."


class RealPathCase(AppCase):
    """The installed app with a scripted cloud provider. The hub gets a fake clock (as in every acceptance test) but the BRAIN gets none:
    `get_brain(memory)` builds it the way `Core` does on the phone."""

    def setUp(self):
        self.cloud = Fake((200, openai_answer(ANSWER), JSON))
        super().setUp()

    def start_app(self):
        self.stop_app()
        set_platform(android_entry.AndroidFilesDirAdapter(self.files))
        self.core = RuntimeCore()
        memory = self.core.memory
        memory._conn.execute("PRAGMA secure_delete = OFF")      # the worst case: a SQLite that leaves deleted rows in the file
        self.hub = HubService(default_root(memory), memory=memory, clock=self.clock, transport=self.cloud,
                              download_transport=self.stream, free_space_fn=F.PLENTY, bridge=F.HubFakeBridge())
        set_hub(memory, self.hub)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.core))
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    # ------------------------------------------------------------------ helpers
    def open_question(self):
        """The type of the cloud brain's open question («provider», «consent», «key» ...) or None."""
        raw = self.memory.get_state(hub_brain.PENDING_KEY, None)
        return raw["type"] if isinstance(raw, dict) else None

    def connect(self):
        """The whole setup conversation as the README of the stage describes it. Returns the replies."""
        replies = [self.ask("مغز ابری را فعال کن"), self.ask("۱"), self.ask("بله"), self.ask(KEY), self.ask("نه")]
        self.assertEqual(self.open_question(), None)
        return replies

    def files_holding(self, secret):
        """Relative paths of every file under the app's files folder that contains `secret` as plain bytes."""
        needle, found = secret.encode("utf-8"), []
        for folder, _dirs, names in os.walk(self.files):
            for name in names:
                path = os.path.join(folder, name)
                with open(path, "rb") as handle:
                    if needle in handle.read():
                        found.append(os.path.relpath(path, self.files).replace(os.sep, "/"))
        return found


class TheClockTests(RealPathCase):
    def test_the_brain_of_the_real_app_has_a_working_clock_without_being_given_one(self):
        brain = self.brain
        self.assertTrue(callable(brain._clock))
        self.assertIsInstance(float(brain._clock()), float)
        self.assertTrue(callable(PersianBrain(self.memory)._clock), "a brain built without a clock must still own one")

    def test_a_question_can_be_opened_and_read_back_with_no_injected_clock(self):
        brain = PersianBrain(self.memory)                        # exactly how Core builds it
        self.assertTrue(hub_brain._arm(brain, "provider", {}))
        self.assertEqual(hub_brain._load(self.memory, brain._clock), ("provider", {}))
        self.assertEqual(hub_brain._load(self.memory, None), ("provider", {}), "a missing clock means «now»")

    def test_a_question_that_could_not_be_opened_is_not_worded_as_the_users_own_no(self):
        real = self.memory.set_state

        def broken(key, value, *args, **kwargs):
            if key == hub_brain.PENDING_KEY:
                raise RuntimeError("disk full")
            return real(key, value, *args, **kwargs)

        with mock.patch.object(self.memory, "set_state", side_effect=broken):
            reply = self.ask("مغز ابری را فعال کن")
        self.assertEqual(reply, BM.setup_failed())
        self.assertNotEqual(reply, BM.setup_cancelled(), "a failure must never look like the user's own «no» (that wording hid the real bug)")
        self.assertFalse(reply.startswith("باشد"))
        self.assertIsNone(self.open_question())


class ThePhoneConversationTests(RealPathCase):
    """The conversation of the user's screenshots, sentence by sentence."""

    def test_the_sentence_that_failed_on_the_phone_now_asks_which_service(self):
        reply = self.ask("مغز ابری را فعال کن")
        self.assertIn("کدام سرویس", reply)
        self.assertNotEqual(reply, BM.setup_cancelled())
        self.assertEqual(reply, BM.setup_intro())
        self.assertEqual(self.open_question(), "provider")
        self.assertEqual(self.cloud.calls, [], "nothing leaves the phone before the user's own yes")

    def test_a_fresh_app_explains_itself_instead_of_pretending(self):
        self.assertIn("هنوز راه‌اندازی نشده", self.ask("وضعیت مغز ابری"))
        wish = self.ask("از مغزت بخواه یک بستهٔ زبان دربارهٔ آشپزی ایرانی بنویسد")
        self.assertIn("هنوز راه‌اندازی نشده", wish)
        self.assertIn("چیزی فرستاده نشد", wish)
        self.assertEqual(self.cloud.calls, [])

    def test_the_whole_setup_and_the_first_answer(self):
        replies = self.connect()
        self.assertIn("کدام سرویس", replies[0])
        self.assertIn("generativelanguage.googleapis.com", replies[1])
        self.assertIn("کلید API", replies[2])
        self.assertIn("وصل شد", replies[3])
        self.assertIn("تمام شد", replies[4])
        self.svc_memory_off()
        self.assertIn("پاریس", self.ask("پایتخت فرانسه کجاست؟"))
        self.assertEqual(len(self.cloud.calls), 2, "the key check and the one real question")

    def svc_memory_off(self):
        from brain_v2 import get_brain
        get_brain(self.hub).set_memory(False)

    def test_the_cloud_brain_can_be_switched_off_and_on_with_possessive_words(self):
        from brain_v2 import get_brain
        self.connect()
        svc = get_brain(self.hub)
        self.assertEqual(svc.status()["mode"], "auto")
        self.assertEqual(self.ask("مغز ابریت رو خاموش کن"), BM.turned_off())
        self.assertEqual(svc.status()["mode"], "local")
        self.assertIn("موقتاً خاموش", self.ask("وضعیت مغز ابری"))
        self.assertIn("روشن شد", self.ask("مغز ابریمو روشن کن"))
        self.assertEqual(svc.status()["mode"], "auto")
        self.assertIn("وضعیت مغز ابری:", self.ask("مغز ابری را خاموش نکن"))      # the opposite of a switch-off: nothing changes
        self.assertEqual(svc.status()["mode"], "auto")
        self.assertEqual(self.ask("نمی‌خوام مغز ابری رو"), BM.turned_off())
        self.assertEqual(svc.status()["mode"], "local")


class ColloquialSentenceTests(RealPathCase):
    """What people really type. Each of these failed (or fell to the generic «I cannot answer») before this release."""

    OPENS_THE_SETUP = ("مغز ابری را فعال کن", "مغز ابری رو فعال کن", "مغز ابریت رو فعال کن", "مغز ابری‌ات را روشن کن", "مغزِ ابریتو روشن کن",
                       "چجوری مغز ابریت رو فعال کنم", "چطوری مغز ابری رو روشن کنم؟", "چطور به مغز ابری وصل بشم؟", "چیکار کنم مغز ابری فعال بشه",
                       "می‌خوام مغز ابری داشته باشی", "میخوام مغز ابری رو راه بندازم", "مغز ابری میخوام", "بیا مغز ابری رو راه بندازیم",
                       "هوش مصنوعی ابری رو فعال کن", "هوش مصنوعی آنلاین رو وصل کن", "از مغز ابری استفاده کن", "میخوام کلید api بدم")
    NOT_FOR_THE_CLOUD_BRAIN = ("هوا ابری است", "امروز هوا ابریه", "مغزم درد می‌کنه", "مغز انسان چطور کار می‌کند؟", "هوش مصنوعی چیست؟",
                               "من ابری رو دوست دارم", "ساعت چنده", "پایتخت فرانسه کجاست؟")

    def test_each_form_opens_the_service_question_and_the_users_no_closes_it(self):
        for text in self.OPENS_THE_SETUP:
            with self.subTest(text):
                reply = self.ask(text)
                self.assertTrue(reply.endswith(BM.provider_question()), reply)
                self.assertEqual(self.open_question(), "provider")
                self.assertEqual(self.ask("نه"), BM.setup_cancelled())
                self.assertIsNone(self.open_question())
        self.assertEqual(self.cloud.calls, [])

    def test_a_how_question_is_answered_by_walking_through_the_setup(self):
        for text in ("چجوری مغز ابریت رو فعال کنم", "چطور مغز ابری رو روشن کنم", "برای فعال کردن مغز ابری چیکار کنم"):
            with self.subTest(text):
                reply = self.ask(text)
                self.assertEqual(reply, BM.setup_how_lead() + BM.setup_intro())
                self.ask("نه")

    def test_questions_about_the_cloud_brain_get_the_explanation(self):
        for text in ("مغز ابری چیه؟", "مغز ابری چطور کار می‌کنه؟", "مغز ابری امنه؟", "چرا مغز ابری؟", "فایدهٔ مغز ابری چیه"):
            with self.subTest(text):
                self.assertIn("مغز ابری چیست؟", self.ask(text))
                self.assertIsNone(self.open_question(), "an explanation opens no question")

    def test_sentences_that_only_share_a_word_are_left_alone(self):
        for text in self.NOT_FOR_THE_CLOUD_BRAIN:
            with self.subTest(text):
                norm = nz.normalize(text)
                self.assertIsNone(BC.classify(text, norm, fa_text.words(norm)))
                self.ask(text)
                self.assertIsNone(self.open_question())

    def test_a_request_to_the_users_own_brain_stays_with_the_teacher(self):
        for text in ("از مغزت بخواه یک بستهٔ زبان دربارهٔ آشپزی ایرانی بنویسد", "از مغز ابری‌ات می‌خوام یه بسته برام بنویسه",
                     "از مغز ابریت بخواه یه قابلیت بسازه"):
            with self.subTest(text):
                norm = nz.normalize(text)
                toks = fa_text.words(norm)
                self.assertIsNone(BC.classify(text, norm, toks))
                self.assertEqual(HI.classify(text, norm, toks).kind, HI.TEACHER_ASK)

    def test_spoken_names_of_the_services(self):
        for spoken, provider_id in (("جمینی", "gemini"), ("گوگل جمینای", "gemini"), ("چت جی پی تی", "openai"), ("چت جی بی تی", "openai"),
                                    ("اپن ای آی", "openai"), ("کلاد", "anthropic"), ("کلود", "anthropic"), ("اپن روتر", "openrouter"),
                                    ("دلخواه", "custom"), ("۱", "gemini"), ("۴", "anthropic")):
            with self.subTest(spoken):
                self.assertEqual(providers.parse_provider_word(spoken), provider_id)
        self.assertIsNone(providers.parse_provider_word("بله"))
        self.assertIsNone(providers.parse_provider_word("چرا"))


class OpenQuestionHelpTests(RealPathCase):
    """«چرا؟» / «یعنی چی؟» / «از کجا بگیرم؟» in the middle of the setup: the step is explained and the SAME question stays open."""

    def test_every_step_can_be_asked_about_without_losing_the_question(self):
        self.ask("مغز ابری را فعال کن")
        self.assertEqual(self.ask("چرا"), BM.clarify_provider())
        self.assertEqual(self.ask("یعنی چی؟"), BM.clarify_provider())
        self.assertEqual(self.open_question(), "provider")
        self.assertIn("generativelanguage.googleapis.com", self.ask("جمینی"))
        self.assertEqual(self.open_question(), "consent")
        self.assertIn("تا «بله» نگویی", self.ask("چرا باید اجازه بدم؟"))
        self.assertEqual(self.open_question(), "consent")
        self.assertEqual(self.cloud.calls, [], "asking why sends nothing")
        self.assertIn("aistudio.google.com/apikey", self.ask("بله"))
        self.assertEqual(self.open_question(), "key")
        reply = self.ask("کلید از کجا بگیرم؟")
        self.assertIn("مثل یک رمزِ اختصاصی", reply)
        self.assertIn("aistudio.google.com/apikey", reply)
        self.assertEqual(self.open_question(), "key")
        self.assertIn("وصل شد", self.ask(KEY))
        self.assertEqual(self.open_question(), "private")
        self.assertEqual(self.ask("یعنی چی؟"), BM.clarify_private())
        self.assertEqual(self.open_question(), "private")
        self.assertIn("تمام شد", self.ask("نه"))
        self.assertIsNone(self.open_question())

    def test_a_bare_yes_to_the_service_question_does_not_cancel_it(self):
        self.ask("مغز ابری را فعال کن")
        self.assertEqual(self.ask("بله"), BM.provider_again())
        self.assertEqual(self.open_question(), "provider")

    def test_an_unrelated_question_withdraws_the_open_question(self):
        self.ask("مغز ابری را فعال کن")
        self.ask("چرا آسمان آبی است؟")
        self.assertIsNone(self.open_question())

    def test_the_forget_question_can_be_asked_about_too(self):
        self.connect()
        self.assertEqual(self.ask("کلید را فراموش کن"), BM.ask_forget())
        self.assertEqual(self.ask("یعنی چی؟"), BM.ask_forget())
        self.assertEqual(self.open_question(), "forget")
        self.assertEqual(self.ask("نه"), BM.forget_cancelled())


class KeyLeavesNoTraceTests(RealPathCase):
    VAULT = "data/brain_hub/brain_v2/key.dat"

    def test_after_the_setup_the_key_is_only_in_its_vault_file(self):
        self.connect()
        self.assertEqual(self.files_holding(KEY), [self.VAULT])
        self.assertNotIn(KEY, json.dumps(self.memory.recent_messages(500), ensure_ascii=False))

    def test_a_key_pasted_with_no_question_open_is_scrubbed_and_never_stored(self):
        self.assertEqual(self.ask(KEY), BM.stray_key())
        self.assertEqual(self.files_holding(KEY), [])

    def test_deleted_rows_are_overwritten_even_where_sqlite_does_not_zero_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "memory.db")
            memory = MemorySystem(path)
            try:
                memory._conn.execute("PRAGMA secure_delete = OFF")
                for i in range(3):
                    memory.log_message("user", "سلام %d" % i)
                memory.log_message("user", "کلید من " + KEY)
                memory.log_message("assistant", "ذخیره شد")
                self.assertEqual(hub_brain.scrub_log(memory, KEY), 1)
                self.assertEqual(memory._conn.execute("PRAGMA secure_delete").fetchone()[0], 0, "the connection's own setting is put back")
            finally:
                memory._conn.close()
            with open(path, "rb") as handle:
                self.assertNotIn(KEY.encode("utf-8"), handle.read())


class RealWorldKeyShapeTests(RealPathCase):
    """Real keys are long and full of «-» and «_» (made-up ones of the same shape here). They must survive the whole chat path byte for byte,
    reach the provider in the right header, and leave no trace outside their vault file."""

    VAULT = "data/brain_hub/brain_v2/key.dat"
    SHAPES = (("۱", "gemini", "AIzaSyA-1b2C3d4_E5f6G7h8-I9j0K1l2M3n4O5"),
              ("۲", "openai", "sk-proj-" + ("Ab3_dE-6gH9jK2mN5pQ8" * 8)[:150]),
              ("۳", "openrouter", "sk-or-v1-" + "0123456789abcdef" * 4),
              ("۴", "anthropic", "sk-ant-api03-" + ("Zy9_xW-8vU7tS6rQ5pO4nM3lK2jI1hG" * 3)[:93] + "AA"))

    def test_a_key_of_each_service_survives_the_chat_path_unchanged(self):
        anthropic = json.dumps({"content": [{"type": "text", "text": "درود"}], "stop_reason": "end_turn"}).encode("utf-8")
        for number, provider_id, key in self.SHAPES:
            with self.subTest(provider_id):
                self.cloud.calls.clear()
                self.cloud.script = [(200, anthropic if provider_id == "anthropic" else openai_answer("درود"), JSON)]
                self.assertTrue(self.ask("مغز ابری را فعال کن").endswith(BM.provider_question()))
                self.assertIn(providers.host_of(providers.endpoint(provider_id)), self.ask(number), "the consent card names the exact host")
                self.ask("بله")
                self.assertIn("وصل شد", self.ask(key))
                self.assertIn("تمام شد", self.ask("نه"))
                header = self.cloud.calls[0].headers
                if provider_id == "anthropic":
                    self.assertEqual(header["x-api-key"], key)
                else:
                    self.assertEqual(header["Authorization"], "Bearer " + key)
                self.assertEqual(self.files_holding(key), [self.VAULT])
                self.assertNotIn(key, json.dumps(self.memory.recent_messages(500), ensure_ascii=False))
                self.ask("کلید را فراموش کن")
                self.assertIn("کلید پاک شد", self.ask("بله"))
                self.assertEqual(self.files_holding(key), [], "forgetting the key removes the last copy")


class RealPathAnswerTests(RealPathCase):
    """What the cloud brain does once it is on - again only through the real front door."""

    def test_the_same_question_twice_is_answered_offline_the_second_time(self):
        self.connect()
        calls = len(self.cloud.calls)
        self.assertIn("پاریس", self.ask("پایتخت فرانسه کجاست؟"))
        self.assertEqual(len(self.cloud.calls), calls + 1)
        second = self.ask("پایتخت فرانسه کجاست؟")
        self.assertIn("پاریس", second)
        self.assertIn("بدون اینترنت از حافظهٔ خودم", second)
        self.assertEqual(len(self.cloud.calls), calls + 1, "the second answer came from the phone")
        self.assertIn("از حافظه‌ام پاک کردم", self.ask("این جواب غلط بود"))

    def test_a_message_with_a_secret_never_leaves_the_phone(self):
        self.connect()
        calls = len(self.cloud.calls)
        reply = self.ask("رمز عبور من ۱۲۳۴۵۶ است، آیا امن است؟")
        self.assertIn("به مغز ابری نفرستادمش", reply)
        self.assertEqual(len(self.cloud.calls), calls)

    def test_the_emergency_word_stops_the_cloud_brain_and_resume_brings_it_back(self):
        self.connect()
        self.assertEqual(self.ask("ایست"), BM.halt_done())
        calls = len(self.cloud.calls)
        self.assertEqual(self.ask("پایتخت ایتالیا کجاست؟"), BM.halted())
        self.assertEqual(len(self.cloud.calls), calls)
        self.assertEqual(self.ask("ادامه"), BM.resume_done())
        self.assertIn("پاریس", self.ask("پایتخت ایتالیا کجاست؟"))

    def test_with_the_internet_switch_off_nothing_is_sent(self):
        self.connect()
        self.assertIn("خاموش", self.ask("اینترنت را خاموش کن"))
        calls = len(self.cloud.calls)
        reply = self.ask("پایتخت اسپانیا کجاست؟")
        self.assertNotIn("پاریس", reply)
        self.assertEqual(len(self.cloud.calls), calls)


class RealPathTeacherTests(RealPathCase):
    """«از مغزت بخواه …» through the real front door: nothing before the first yes, one request, a review, a second yes."""

    PACK_ID = "fa_brain_cook"
    WISH = "از مغزت بخواه یک بستهٔ زبان دربارهٔ آشپزی ایرانی بنویسد"

    def setUp(self):
        from pack_system import boot
        from teacher import service as teacher_service
        from tests import pack_support_prompt958 as S
        self.S, self.boot, self.teacher_service = S, boot, teacher_service
        for reset in (lambda: S.reset_process_state(self.PACK_ID), boot.reset_for_tests, teacher_service.reset_for_tests):
            reset()
            self.addCleanup(reset)
        super().setUp()

    def test_a_language_pack_is_authored_reviewed_and_installed(self):
        self.connect()
        pack = self.S.lang_pack(pid=self.PACK_ID, qa=[("قورمه سبزی چیست | قورمه سبزی چه غذایی است", "خورشتی ایرانی با سبزی و لوبیا و گوشت")])
        self.cloud.script = [(200, openai_answer(pack), JSON)]
        calls = len(self.cloud.calls)
        question = self.ask(self.WISH)
        self.assertEqual(len(self.cloud.calls), calls, "asking sends nothing")
        self.assertIn("از مغز ابری‌ات بخواهم", question)
        self.assertEqual(self.boot.manager_for(self.memory).list(), [])
        reviewed = self.ask("بله")
        self.assertEqual(len(self.cloud.calls), calls + 1, "exactly one request")
        self.assertIn("بستهٔ زبان", reviewed)
        self.assertEqual(self.boot.manager_for(self.memory).list(), [], "reviewed, not installed")
        self.assertIn("نصب و فعال شد", self.ask("بله"))
        self.assertIn("خورشتی ایرانی", self.ask("قورمه سبزی چیست"))
        self.assertEqual(len(self.cloud.calls), calls + 1, "the installed pack answers without the cloud")

    def test_a_no_to_the_first_question_sends_nothing(self):
        self.connect()
        calls = len(self.cloud.calls)
        self.ask(self.WISH)
        self.assertIn("چیزی فرستاده نشد", self.ask("نه"))
        self.assertEqual(len(self.cloud.calls), calls)
        self.assertEqual(self.boot.manager_for(self.memory).list(), [])


class TheAppsOwnIDontKnowRepliesTests(RealPathCase):
    """What the app says when it understands nothing - the other half of «why doesn't it understand anything I say».

    On the phone a Persian sentence that was no question («من امروز خیلی خسته‌ام») fell through to the core's English line about AEL, and the
    honest «I do not know» replies never named the cloud brain. Both are fixed; the cloud brain is named only while it is still off."""

    STATEMENT = "من امروز خیلی خسته‌ام"
    OTHER = "یه چیزی بهت میگم"

    def snap(self):
        return hub_hooks._self_snapshot(self.brain)

    def test_a_persian_sentence_that_is_no_question_gets_a_persian_answer_not_the_english_core_line(self):
        reply = self.ask(self.STATEMENT)
        for english in ("I don't have enough information", "AEL", "TEACH", "ASK sun"):
            self.assertNotIn(english, reply)
        self.assertEqual(reply, HS.unknown_statement_first(self.snap()))
        self.assertIn("نمی‌فهمم", reply)
        self.assertIn("«چه کارهایی بلدی؟»", reply)
        self.assertIn("«یاد بگیر که …»", reply)
        self.assertIn("«مغز ابری را فعال کن»", reply)
        self.assertEqual(self.cloud.calls, [], "nothing leaves the phone")
        self.assertIsNone(self.open_question(), "it only informs; it opens no question")

    def test_the_long_text_comes_once_and_the_short_one_after_it_until_a_quiet_period_has_passed(self):
        now = [time.time()]
        self.brain._clock = lambda: now[0]
        first = self.ask(self.STATEMENT)
        now[0] += 10
        second = self.ask(self.OTHER)
        self.assertEqual(second, HS.unknown_statement_short(self.snap()))
        self.assertLess(len(second), len(first) // 2)
        self.assertIn("«مغز ابری را فعال کن»", second)
        now[0] += 16 * 60
        self.assertEqual(self.ask(self.OTHER), first, "after the quiet period the full explanation returns")

    def test_the_way_to_the_cloud_brain_is_named_only_while_it_is_off(self):
        self.assertFalse(hub_brain.is_on(self.brain))
        self.assertIn(HS.CLOUD_WAY, HS.grow_ways(self.snap()))
        self.assertIn("«مغز ابری را فعال کن»", self.ask("چطور باهوش‌ترت کنم؟"))
        self.assertIn("«مغز ابری را فعال کن»", self.ask("پایتخت فرانسه کجاست؟"), "an unanswerable question names the way too")
        self.connect()
        self.assertTrue(hub_brain.is_on(self.brain))
        self.assertNotIn(HS.CLOUD_WAY, HS.grow_ways(self.snap()))
        self.assertNotIn("«مغز ابری را فعال کن»", self.ask("چطور باهوش‌ترت کنم؟"), "no pointer to something that is already on")
        self.ask("مغز ابری را خاموش کن")
        self.assertFalse(hub_brain.is_on(self.brain))
        self.assertIn(HS.CLOUD_WAY, HS.grow_ways(self.snap()), "switched off again, so it is offered again")

    def test_once_the_cloud_brain_is_on_a_free_sentence_is_answered_not_declared_unknown(self):
        self.connect()
        calls = len(self.cloud.calls)
        reply = self.ask(self.STATEMENT)
        self.assertEqual(len(self.cloud.calls), calls + 1, "the sentence went to the cloud brain, after the privacy check")
        self.assertIn("پاریس", reply)
        self.assertNotIn("نمی‌فهمم", reply)

    def test_what_the_app_already_understands_is_not_taken_by_the_new_reply(self):
        for text, expected in (("سلام", "سلام"), ("ممنون", "خواهش"), ("چه کارهایی بلدی؟", "بلدم")):
            reply = self.ask(text)
            self.assertIn(expected, reply, text)
            self.assertNotEqual(reply, HS.unknown_statement_first(self.snap()), text)
            self.assertNotIn("نمی‌فهمم", reply, text)
        self.ask("من عرفان هستم")
        self.assertIn("عرفان", self.ask("اسم من چیه؟"))

    def test_sentences_with_no_persian_letter_stay_with_the_core(self):
        for text in ("hello", "!!! ???", "۱۲۳ ۴۵۶"):
            reply = self.ask(text)
            self.assertNotIn("نمی‌فهمم", reply, text)
            self.assertNotIn("نفهمیدم", reply, text)
        self.assertFalse(hub_hooks._is_persian("۱۲۳ ۴۵۶ !?"), "digits and symbols alone are not a Persian sentence")
        self.assertTrue(hub_hooks._is_persian("من 3 تا سیب دارم"))

    def test_is_on_never_raises(self):
        self.assertFalse(hub_brain.is_on(None))
        with mock.patch.object(hub_brain, "service", side_effect=RuntimeError("broken")):
            self.assertFalse(hub_brain.is_on(self.brain))
        self.assertFalse(hub_brain.is_on(object()))


class TheStatusTellsTheTruthTests(RealPathCase):
    """«وضعیت مغز ابری» must not say "ready ✅" as if everything worked while every request to the service fails (found by booting the app the way
    the phone does, with the network cut below the transport: the settings were complete, so the status said ready although the service was never reached)."""

    def test_after_a_working_setup_the_status_says_the_service_answered(self):
        self.connect()
        status = self.ask("وضعیت مغز ابری")
        self.assertIn("آخرین تلاش برای وصل‌شدن: ✅ سرویس جواب داد", status)
        self.assertIn("نتیجه: آماده است ✅", status)
        self.assertNotIn(KEY, status)

    def test_when_the_service_cannot_be_reached_the_status_says_so_instead_of_ready_and_recovers_after_a_retry(self):
        self.cloud.script = [TransportError("offline")]
        replies = [self.ask("مغز ابری را فعال کن"), self.ask("۱"), self.ask("بله"), self.ask(KEY)]
        self.assertIn("به مغز ابری نرسیدم", replies[-1])
        self.assertIn("کلید ذخیره ماند", replies[-1])
        status = self.ask("وضعیت مغز ابری")
        self.assertIn("آخرین تلاش برای وصل‌شدن: ❌ به مغز ابری نرسیدم", status)
        self.assertIn("تنظیمات کامل است، ولی آخرین تلاش برای وصل‌شدن ناموفق بود ❌", status)
        self.assertNotIn("آماده است ✅", status, "a status that says ready while every request fails is a lie")
        self.assertNotIn(KEY, status)
        # a question now fails honestly too - and the status keeps saying the truth
        self.assertIn("به مغز ابری نرسیدم", self.ask("پایتخت فرانسه کجاست؟"))
        self.assertIn("❌", self.ask("وضعیت مغز ابری"))
        # the problem goes away: the retry command works and the status follows it
        self.cloud.script = [(200, openai_answer(ANSWER), JSON)]
        self.assertIn("مغز ابری جواب داد", self.ask("مغز ابری را امتحان کن"))
        status = self.ask("وضعیت مغز ابری")
        self.assertIn("آخرین تلاش برای وصل‌شدن: ✅ سرویس جواب داد", status)
        self.assertIn("نتیجه: آماده است ✅", status)
        self.assertNotIn("ناموفق بود", status)

    def test_after_a_restart_it_says_nothing_was_tried_yet_instead_of_inventing_an_outcome(self):
        self.connect()
        self.start_app()                      # the app is closed and opened again: the outcome of the last request is not kept
        status = self.ask("وضعیت مغز ابری")
        self.assertIn("از وقتی برنامه باز شده هنوز تلاشی نشده", status)
        self.assertNotIn("سرویس جواب داد", status)
        self.assertNotIn("ناموفق", status)
        self.assertIn("نتیجه: آماده است ✅", status, "the settings are complete; only the connection is untested")

    def test_a_refused_key_is_reported_with_the_fixed_reason_and_never_with_the_key(self):
        refusal = ('{"error": {"message": "API key not valid: %s"}}' % KEY).encode("utf-8")
        self.cloud.script = [(401, refusal, JSON)]
        for text in ("مغز ابری را فعال کن", "۱", "بله", KEY):
            reply = self.ask(text)
        self.assertNotIn(KEY, reply, "the provider's own message may echo the key; it must never be shown")
        status = self.ask("وضعیت مغز ابری")
        self.assertNotIn(KEY, status)
        self.assertIn("آخرین تلاش برای وصل‌شدن: ❌", status)
        self.assertNotIn("آماده است ✅", status)

    def test_the_new_status_fields_are_plain_data_and_cost_no_request(self):
        self.connect()
        calls = len(self.cloud.calls)
        for _ in range(3):
            self.ask("وضعیت مغز ابری")
        self.assertEqual(len(self.cloud.calls), calls, "asking for the status never contacts the service")
        info = hub_brain.service(self.brain).status()
        self.assertIs(info["last_ok"], True)
        self.assertEqual(info["last_reason"], "")


class NobodyAnsweredHelperTests(unittest.TestCase):
    """The helper that keeps the old meaning of «nothing answered» in the frozen chat tests of Prompt 958 must not swallow a real answer."""

    def test_it_accepts_only_none_and_the_two_generic_texts(self):
        self.assertTrue(nobody_answered(None))
        for cloud_on in (False, True, None):
            snap = {"cloud_on": cloud_on}
            self.assertTrue(nobody_answered(HS.unknown_statement_first(snap)))
            self.assertTrue(nobody_answered(HS.unknown_statement_short(snap)))
        for real in ("", "نسخهٔ 1 جواب داد", "سلام!", HS.unknown_first({"cloud_on": False}), HS.unknown_short({"cloud_on": False})):
            self.assertFalse(nobody_answered(real), real)


class APackAnswerBeatsTheGenericReplyTests(PackChatCase):
    def test_the_same_sentence_is_unanswered_then_answered_by_a_fallback_pack(self):
        # unanswered -> the generic Persian reply (not the core's English line); after a fallback pack is installed it answers (priority unchanged)
        sentence = "قیمت دلار چنده"
        first = self.say(sentence)
        self.assertTrue(nobody_answered(first), first)
        self.assertIn("نمی‌فهمم", first)
        self.install_pack(self.code(1))
        answered = self.say(sentence)
        self.assertFalse(nobody_answered(answered), answered)
        self.assertIn("نسخهٔ 1 جواب داد", answered)


if __name__ == "__main__":
    unittest.main()
