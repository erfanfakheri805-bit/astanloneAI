"""Prompt 959 (stage A) - «از مغزت بخواه برایم X بسازد»: the user's OWN cloud brain as a teacher.

The real Persian brain (FULL scope) on a real memory, a real hub and a real pack system, with a scripted provider instead of the network.
What these tests protect, in the user's terms:

* the request only OPENS a question; nothing leaves the phone before his «بله», and the question says exactly what would leave;
* a secret in the wish is refused before he is asked anything; the emergency stop, a lost internet permission or a used-up hourly cap
  stop the request even after he said «بله»;
* ONE request is sent: the wish and the app's own format instructions - no chat history, nothing stored as history or as a remembered answer;
* what comes back is TEXT: a pack is reviewed (never run) and installed only after a SECOND «بله»; a broken, rejected, cut-off or
  non-pack answer installs nothing and says so;
* the words about the brain («مغز ابری را فعال کن») and the older teacher («از ChatGPT بخواه») keep working exactly as before.
"""
import json
import os
import re
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from brain_hub import pack_prompt
from brain_v2 import cloud, persona, providers
from brain_v2.service import MAX_CALLS_PER_HOUR
from net_tools import TransportError
from pack_system import boot
from persian_brain import hub_brain_commands as BC
from persian_brain import hub_intents as HI
from persian_brain import hub_messages_brain as BM
from persian_brain import hub_state
from persian_brain import normalization as nz
from self_builder import fa_text
from teacher import assistants
from teacher import request as teacher_request
from teacher import service as teacher_service
from tests import pack_support_prompt958 as S
from tests import test_brain_v2_core_prompt959 as core
from tests.test_brain_v2_chat_prompt959 import CloudChatCase
from tests.test_brain_v2_core_prompt959 import JSON, KEY, openai_answer

PACK_IDS = ("brain_demo", "brain_bad", "fa_brain_cook")
CODE_WISH = "از مغزت بخواه یک قابلیت جواب‌دادن به قیمت دلار برایم بسازد"
LANG_WISH = "از مغزت بخواه یک بستهٔ زبان دربارهٔ آشپزی ایرانی بنویسد"
MARKER = "RAW_BODY_MARKER_7431"

DEMO_SOURCE = '''# %s
VERSION = 1


def register(api):
    def match(ctx):
        return "قیمت دلار" in ctx.norm

    def handle(ctx):
        return "این جواب را بستهٔ مغز ابری نوشت"

    api.register_chat("brain_demo", match, handle, stage="fallback")
''' % MARKER


def code_pack(source=DEMO_SOURCE, pid="brain_demo"):
    return S.text_pack(pid=pid, version=1, source=source, title="جواب قیمت دلار")


def lang_pack():
    return S.lang_pack(pid="fa_brain_cook", qa=[("قورمه سبزی چیست | قورمه سبزی چه غذایی است", "خورشتی ایرانی با سبزی و لوبیا و گوشت")])


def reply_with(text, finish="stop"):
    return [(200, openai_answer(text, finish=finish), JSON)]


class OwnBrainCase(CloudChatCase):
    def setUp(self):
        S.reset_process_state(*PACK_IDS)
        boot.reset_for_tests()
        teacher_service.reset_for_tests()
        self.addCleanup(self._clean_process)
        super().setUp()

    def _clean_process(self):
        S.reset_process_state(*PACK_IDS)
        boot.reset_for_tests()
        teacher_service.reset_for_tests()

    # ------------------------------------------------------------------ helpers
    def pm(self):
        return boot.manager_for(self.memory)

    def teacher(self):
        return teacher_service.get_service(self.hub)

    def latest(self):
        return self.teacher().store.latest(only_open=False)

    def ready(self, **kw):
        """The brain is on and the key is stored (the whole setup conversation)."""
        self.connect(**kw)
        self.assertTrue(self.svc.ready()[0])

    def script(self, text, finish="stop"):
        self.cloud.script = reply_with(text, finish)

    def ask(self, sentence=CODE_WISH):
        before = len(self.cloud.calls)
        reply = self.say(sentence)
        self.assertEqual(len(self.cloud.calls), before, "asking must not send anything")
        return reply

    def ask_and_confirm(self, sentence=CODE_WISH):
        question = self.ask(sentence)
        self.assertEqual(self.pending()[0], "teacher_send", question)
        return question, self.say("بله")


# ====================================================================== which sentences are requests TO the brain
class RoutingTests(unittest.TestCase):
    @staticmethod
    def classify(text):
        norm = nz.normalize(text)
        toks = fa_text.words(norm)
        return HI.classify(text, norm, toks), BC.classify(text, norm, toks)

    def test_requests_to_the_brain_are_teacher_asks_and_never_brain_commands(self):
        for sentence in ("از مغزت بخواه یک ماشین‌حساب ساده برایم بسازد", "از مغز ابری‌ات بخواه یک بستهٔ زبان دربارهٔ تاریخ ایران بنویسد",
                         "از مغز ابری بخواه برایم قابلیت یادآوری بساز", "از مغز ابریم بخواه یه قابلیت بنویسه",
                         "برو از مغزتون بخواه یه بسته زبان بنویسه", "از مغز ابری‌ات بخواه برایم یک افزونهٔ یادداشت بسازد",
                         "از مغز خودت بخواه برایم یک قابلیت جدید بسازه"):
            hub, brain = self.classify(sentence)
            self.assertIsNotNone(hub, sentence)
            self.assertEqual((hub.kind, hub.slots["assistant"]), (HI.TEACHER_ASK, "brain"), sentence)
            self.assertIsNone(brain, sentence)

    def test_the_kind_of_answer_follows_the_words(self):
        self.assertEqual(self.classify("از مغزت بخواه یک بستهٔ زبان دربارهٔ آشپزی بنویسد")[0].slots["kind"], "lang")
        self.assertEqual(self.classify("از مغزت بخواه یک ماشین‌حساب برایم بسازد")[0].slots["kind"], "code")
        self.assertEqual(self.classify("از مغزت بپرس تفاوت HTTP و HTTPS چیست؟")[0].slots["kind"], "ask")

    def test_a_question_about_the_app_is_not_a_request_and_the_brain_commands_are_unchanged(self):
        self.assertEqual(self.classify("می‌تونی از مغزت کمک بگیری؟"), (None, None))
        self.assertEqual(self.classify("هوا ابری است و مغز من خسته است"), (None, None))
        self.assertEqual(self.classify("مغز ابری را فعال کن")[1].kind, BC.SETUP)
        self.assertEqual(self.classify("مغز ابری را خاموش کن")[1].kind, BC.OFF)
        self.assertEqual(self.classify("وضعیت مغز ابری")[1].kind, BC.STATUS)

    def test_the_outside_assistants_are_untouched(self):
        hub, _ = self.classify("از ChatGPT بخواه یک ماشین‌حساب بسازد")
        self.assertEqual((hub.kind, hub.slots["assistant"]), (HI.TEACHER_ASK, "chatgpt"))
        self.assertNotIn("brain", [a.assistant_id for a in assistants.ASSISTANTS])
        self.assertEqual(len(assistants.ASSISTANTS), 7)
        self.assertIsNone(assistants.find_in_tokens(["از", "مغزت", "بخواه"]))
        self.assertIs(assistants.get("brain"), assistants.BRAIN)

    def test_the_request_text_for_the_own_brain_names_no_other_assistant_and_carries_the_live_format(self):
        text, kind = teacher_request.build("یک بستهٔ کوچک", "code", assistants.BRAIN.title, own_brain=True)
        outside, _ = teacher_request.build("یک بستهٔ کوچک", "code", "ChatGPT")
        self.assertEqual(kind, "code")
        self.assertIn("مغز ابری", text.splitlines()[0])
        self.assertNotIn("سلام", text.splitlines()[0])
        self.assertIn("code.v1", text)
        self.assertTrue(text.endswith(outside[outside.index(pack_prompt.build_prompt("یک بستهٔ کوچک", "code")[:200]):]),
                        "the format instructions must be the very same live text the outside route uses")


# ====================================================================== the first «بله»
class AskingTests(OwnBrainCase):
    def test_asking_opens_one_question_and_sends_nothing(self):
        self.ready()
        reply = self.ask()
        self.assertIn("بفرستم؟ (بله / نه)", reply)
        self.assertIn("generativelanguage.googleapis.com", reply)
        self.assertIn("قیمت دلار", reply)
        self.assertIn("فقط به", reply)
        self.assertIn("بدون «بله»ی دومِ تو هیچ چیزی نصب یا فعال نمی‌شود", reply)
        self.assertIn("حداکثر ۳ دقیقه", reply)
        self.assertNotIn(KEY, reply)
        self.assertEqual(self.pending(), ("teacher_send", {"mission_id": self.latest()["id"], "assistant": "brain", "kind": "code"}))
        mission = self.latest()
        self.assertEqual((mission["state"], mission["assistant"], mission["route"]), ("drafted", "brain", ""))

    def test_a_no_declines_and_nothing_is_sent(self):
        self.ready()
        self.ask()
        self.assertIn("کنار گذاشتم", self.say("نه"))
        self.assertEqual(self.latest()["state"], "cancelled")
        self.assertIsNone(self.pending())
        self.assertEqual(len(self.cloud.calls), 1, "only the setup probe was ever sent")

    def test_any_other_message_withdraws_the_draft_and_a_later_yes_sends_nothing(self):
        self.ready()
        self.ask()
        self.say("سلام")
        self.assertEqual(self.latest()["state"], "cancelled")
        self.say("بله")
        self.assertEqual(len(self.cloud.calls), 1)

    def test_an_expired_question_is_not_answered(self):
        self.ready()
        self.ask()
        self.clock.advance(31 * 60)
        self.assertIn("منقضی", self.say("بله"))
        self.assertEqual(len(self.cloud.calls), 1)

    def test_a_stray_yes_never_sends(self):
        self.ready()
        self.say("بله")
        self.assertEqual(len(self.cloud.calls), 1)

    def test_without_a_wish_the_app_says_what_to_write_and_opens_nothing(self):
        self.ready()
        reply = self.ask("از مغزت بخواه")
        self.assertIn("چه چیزی را از مغز ابری‌ات بخواهم", reply)
        self.assertIsNone(self.pending())
        self.assertIsNone(self.latest())

    def test_the_wish_the_app_could_not_fulfil_is_remembered_for_a_bare_request(self):
        self.ready()
        hub_state.save_wish(self.memory, "یک ماشین‌حساب ساده", self.clock)
        reply = self.ask("از مغزت بخواه")
        self.assertIn("درخواست قبلی‌ات را برمی‌دارم", reply)
        self.assertIn("یک ماشین‌حساب ساده", reply)
        self.assertEqual(self.pending()[0], "teacher_send")

    def test_an_open_mission_with_another_assistant_is_replaced_only_after_the_yes(self):
        self.ready()
        store = self.teacher().store
        old = store.create("code", "چیزی از چت‌جی‌پی‌تی", "chatgpt")
        store.update(old["id"], state="sent", route="share")
        reply = self.ask()
        self.assertIn("ماموریت بازِ قبلی با «بله» کنار گذاشته می‌شود", reply)
        self.assertEqual(store.get(old["id"])["state"], "sent", "nothing is replaced before the yes")
        self.script(lang_pack())
        self.say("بله")
        self.assertEqual(store.get(old["id"])["state"], "cancelled")

    def test_the_words_of_the_older_teacher_still_open_the_older_question(self):
        self.ready()
        reply = self.say("از ChatGPT بخواه یه قابلیت ساخت عکس برام بسازه")
        self.assertIn("ChatGPT", reply)
        self.assertEqual(self.pending()[1]["assistant"], "chatgpt")
        self.assertEqual(len(self.cloud.calls), 1)


# ====================================================================== what is checked before the user is asked
class RefusalBeforeAskingTests(OwnBrainCase):
    def test_a_secret_in_the_wish_is_refused_before_any_question(self):
        self.ready()
        reply = self.ask("از مغزت بخواه قابلیتی بسازد که این کلید را نگه دارد sk-abcdefghijklmnopqrstuvwxyz0123456789ABCD")
        self.assertIn("به مغز ابری نفرستادمش", reply)
        self.assertNotIn("sk-abcdefghijklmnop", reply)
        self.assertIsNone(self.pending())
        self.assertIsNone(self.latest(), "no mission is made for a refused wish")

    def test_a_brain_that_is_not_ready_says_why_and_opens_nothing(self):
        reply = self.ask()
        self.assertIn("باید روشن و آماده باشد", reply)
        self.assertIn("هنوز راه‌اندازی نشده", reply)
        self.assertIn("مغز ابری را فعال کن", reply)
        self.assertIsNone(self.pending())
        self.assertIsNone(self.latest())
        self.assertEqual(self.cloud.calls, [])

    def test_the_emergency_stop_and_the_internet_switch_are_named(self):
        self.ready()
        self.say("ایست")
        self.assertIn("ایست", self.ask())
        self.assertIsNone(self.pending())
        self.say("ادامه")
        self.hub.permissions.revoke("network")
        self.assertIn("اینترنت برنامه خاموش است", self.ask())
        self.assertIsNone(self.pending())


# ====================================================================== the second step: what really leaves, what comes back
class SendingTests(OwnBrainCase):
    def test_the_yes_sends_exactly_one_request_with_the_wish_and_the_format_and_no_history(self):
        self.ready()
        self.say(QUESTION_TO_BRAIN)                                      # so that a history exists
        self.assertEqual(self.svc.history.count(), 1)
        self.script(code_pack())
        self.ask()
        before = len(self.cloud.calls)
        self.say("بله")
        self.assertEqual(len(self.cloud.calls), before + 1, "exactly one request")
        sent = self.cloud.calls[-1]
        self.assertEqual((sent.method, sent.host), ("POST", "generativelanguage.googleapis.com"))
        self.assertEqual(sent.headers["Authorization"], "Bearer " + KEY)
        body = json.loads(sent.body.decode("utf-8"))
        self.assertEqual([m["role"] for m in body["messages"]], ["system", "user"])
        self.assertEqual(body["messages"][0]["content"], persona.AUTHOR_FA)
        self.assertEqual(body[providers.get("gemini").tokens_field], cloud.MAX_TOKENS_AUTHOR)
        asked = body["messages"][1]["content"]
        self.assertIn("قیمت دلار", asked)
        self.assertIn("code.v1", asked)
        self.assertNotIn("پایتخت", json.dumps(body, ensure_ascii=False), "the earlier chat must not travel with an authoring request")
        self.assertNotIn(KEY, sent.body.decode("utf-8"), "the key travels in the header only")
        self.assertEqual(asked, self.teacher().request_text(self.latest()), "what was announced is what was sent")

    def test_a_good_code_pack_is_only_reviewed_then_installed_by_the_second_yes(self):
        self.ready()
        self.script("حتماً! این هم بسته:\n\n```text\n" + code_pack() + "```\n")
        _, reviewed = self.ask_and_confirm()
        self.assertIn("از مغز ابریِ خودت گرفتم و فقط بررسی کردم", reviewed)
        self.assertIn("هنوز چیزی نصب یا فعال نشده", reviewed)
        self.assertEqual(self.pending()[0], "pack_install")
        self.assertEqual(self.pm().list(), [], "nothing is installed before the second yes")
        self.assertEqual(self.latest()["state"], "proposed")
        self.assertEqual(self.latest()["route"], "brain")

    def test_any_other_message_after_the_review_installs_nothing(self):
        self.ready()
        self.script(code_pack())
        self.ask_and_confirm()
        self.say("سلام")                                                 # any other message withdraws the install question
        self.assertIsNone(self.pending())
        self.say("بله")
        self.assertEqual(self.pm().list(), [])
        self.assertEqual(self.pm().pending(), [])

    def test_the_second_yes_installs_the_code_pack_and_it_answers_by_itself(self):
        self.ready()
        self.script(code_pack())
        self.ask_and_confirm()
        done = self.say("بله")
        self.assertIn("نصب و فعال شد", done)
        calls = len(self.cloud.calls)
        self.assertEqual(self.say("قیمت دلار چنده؟"), "این جواب را بستهٔ مغز ابری نوشت")
        self.assertEqual(len(self.cloud.calls), calls, "the installed pack answers without the cloud")

    def test_a_lang_pack_from_the_brain_installs_the_same_way(self):
        self.ready()
        self.script(lang_pack())
        _, reviewed = self.ask_and_confirm(LANG_WISH)
        self.assertEqual(self.latest()["kind"], "lang")
        self.assertIn("بستهٔ زبان", reviewed)
        self.assertEqual(self.pm().list(), [])
        self.assertIn("نصب و فعال شد", self.say("بله"))
        calls = len(self.cloud.calls)
        self.assertIn("خورشتی ایرانی", self.say("قورمه سبزی چیست"))
        self.assertEqual(len(self.cloud.calls), calls)

    def test_a_no_to_the_second_question_installs_nothing(self):
        self.ready()
        self.script(lang_pack())
        self.ask_and_confirm(LANG_WISH)
        self.assertIn("کنار گذاشتم", self.say("نه"))
        self.assertEqual(self.pm().list(), [])
        self.assertEqual(self.pm().pending(), [])

    def test_the_answer_is_not_kept_as_history_as_a_remembered_answer_or_in_the_chat_log(self):
        self.ready(memory=True)
        history, kept = self.svc.history.count(), self.svc.learned.count()
        self.script(code_pack())
        self.ask_and_confirm()
        self.assertEqual((self.svc.history.count(), self.svc.learned.count()), (history, kept))
        for name, text in self.every_file_text().items():
            self.assertNotIn(MARKER, text, name + " must not hold the authored pack")
        self.assertNotIn(MARKER, self.logged())
        self.assertNotIn(KEY, self.logged())

    def every_file_text(self):
        out = {}
        for folder, _, names in os.walk(self.brain_dir()):
            for name in names:
                with open(os.path.join(folder, name), "rb") as handle:
                    out[name] = handle.read().decode("utf-8", "replace")
        return out

    def test_the_pack_text_is_not_changed_on_the_way(self):
        """Code needs its indentation, backticks and underscores: the authoring path must not 'clean' them like a chat answer."""
        self.ready()
        source = DEMO_SOURCE.replace("VERSION = 1", "VERSION = 1\nNOTE = 'a_b__c `x` **y**'")
        self.script(code_pack(source))
        self.ask_and_confirm()
        self.assertIn("نصب و فعال شد", self.say("بله"))
        with open(os.path.join(self.pm().store.files_dir("brain_demo", 1), "brain_demo", "main.py"), encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn("NOTE = 'a_b__c `x` **y**'", text)
        self.assertIn("\n    def match(ctx):\n        return", text)


QUESTION_TO_BRAIN = "پایتخت فرانسه کجاست؟"


# ====================================================================== answers that must install nothing
class BadAnswerTests(OwnBrainCase):
    def test_a_reply_that_is_not_a_pack_is_shown_as_text_and_nothing_is_proposed(self):
        self.ready()
        self.script("متأسفم، من این کار را نمی‌توانم انجام دهم.")
        _, reply = self.ask_and_confirm()
        self.assertIn("«بستهٔ» کامل", reply)
        self.assertIn("نمی‌توانم انجام دهم", reply)
        self.assertIn("چیزی نصب یا عوض نشد", reply)
        self.assertIsNone(self.pending())
        self.assertEqual(self.latest()["state"], "failed")
        self.assertEqual(self.pm().list(), [])

    def test_a_pack_the_review_rejects_is_not_installed_and_the_reason_is_shown(self):
        self.ready()
        self.script(code_pack("import subprocess\n\n\ndef register(api):\n    pass\n", pid="brain_bad"))
        _, reply = self.ask_and_confirm()
        self.assertIn("subprocess", reply)
        self.assertIn("بسته را نپذیرفتم", reply)
        self.assertIsNone(self.pending())
        self.assertEqual(self.latest()["state"], "failed")
        self.assertEqual(self.pm().list(), [])
        self.assertEqual(self.pm().pending(), [])

    def test_a_pack_of_another_format_version_is_explained_and_not_installed(self):
        self.ready()
        self.script("=== PACK code.v9 ===\nid: brain_demo\nversion: 1\n=== END PACK ===\n")
        _, reply = self.ask_and_confirm()
        self.assertIsNone(self.pending())
        self.assertEqual(self.pm().list(), [])
        self.assertIn("code.v9", reply)

    def test_an_answer_cut_off_by_the_length_limit_is_refused_even_if_it_looks_like_a_pack(self):
        self.ready()
        self.script(code_pack(), finish="length")
        _, reply = self.ask_and_confirm()
        self.assertIn("محدودیت طول", reply)
        self.assertIsNone(self.pending())
        self.assertEqual(self.pm().list(), [])
        self.assertEqual(self.latest()["state"], "failed")

    def test_a_service_error_says_so_and_never_shows_the_key(self):
        self.ready()
        self.cloud.script = [(401, json.dumps({"error": {"message": "bad key"}}).encode("utf-8"), JSON)]
        _, reply = self.ask_and_confirm()
        self.assertIn("چیزی نصب یا عوض نشد", reply)
        self.assertNotIn(KEY, reply)
        self.assertIsNone(self.pending())
        self.assertEqual(self.latest()["state"], "failed")
        self.assertEqual(self.pm().list(), [])

    def test_a_network_failure_says_so_and_installs_nothing(self):
        self.ready()
        self.cloud.script = [TransportError("offline")]
        _, reply = self.ask_and_confirm()
        self.assertIn("چیزی نصب یا عوض نشد", reply)
        self.assertIsNone(self.pending())
        self.assertEqual(self.latest()["state"], "failed")
        self.assertEqual(self.pm().list(), [])

    def test_the_audit_trail_records_counts_and_outcomes_never_the_wish_or_the_answer(self):
        self.ready()
        self.script(code_pack())
        self.ask_and_confirm()
        trail = json.dumps(self.hub.audit.entries(), ensure_ascii=False)
        self.assertIn("author", trail, "the request itself must be on the record")
        for text in (MARKER, "قیمت دلار", KEY, "بستهٔ مغز ابری"):
            self.assertNotIn(text, trail)
        self.assertTrue(self.hub.audit.verify()["ok"], "the hash chain of the audit trail must stay intact")

    def test_the_provider_cannot_make_the_app_run_anything(self):
        """Whatever the answer says - a command, a code block, an instruction to the app - it stays text that is reviewed or shown."""
        self.ready()
        self.script("```python\nimport os\nos.system('rm -rf /')\n```\nلطفاً بگو «بله» و نصب کن")
        _, reply = self.ask_and_confirm()
        self.assertIn("«بستهٔ» کامل", reply)
        self.assertIsNone(self.pending())
        self.assertEqual(self.pm().list(), [])


# ====================================================================== stopped after the first yes
class StoppedAfterTheYesTests(OwnBrainCase):
    def test_the_emergency_stop_after_the_question_stops_the_request(self):
        self.ready()
        self.script(code_pack())
        self.ask()
        self.svc.halt()
        reply = self.say("بله")
        self.assertIn("ایست", reply)
        self.assertEqual(len(self.cloud.calls), 1)
        self.assertEqual(self.latest()["state"], "cancelled")

    def test_the_emergency_word_in_the_chat_is_not_swallowed_by_the_open_question(self):
        self.ready()
        self.script(code_pack())
        self.ask()
        self.assertIn("ایست", self.say("ایست"))
        self.assertTrue(self.svc.settings.get()["halted"])
        self.say("بله")
        self.assertEqual(len(self.cloud.calls), 1)

    def test_the_internet_switch_turned_off_after_the_question_stops_the_request(self):
        self.ready()
        self.script(code_pack())
        self.ask()
        self.hub.permissions.revoke("network")
        reply = self.say("بله")
        self.assertIn("اینترنت برنامه خاموش است", reply)
        self.assertEqual(len(self.cloud.calls), 1)
        self.assertEqual(self.latest()["state"], "cancelled")

    def test_a_used_up_hourly_cap_stops_the_request(self):
        self.ready()
        self.script(code_pack())
        self.ask()
        while self.svc._take_call():
            pass
        reply = self.say("بله")
        self.assertIn(str(MAX_CALLS_PER_HOUR).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")), reply)
        self.assertEqual(len(self.cloud.calls), 1)
        self.assertEqual(self.latest()["state"], "cancelled")

    def test_a_secret_that_got_into_the_stored_wish_is_still_caught_at_send_time(self):
        self.ready()
        self.script(code_pack())
        self.ask()
        # the stored wish is the thing that would be sent: a tampered store must not be able to smuggle a secret out
        path = self.teacher().store.path
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        data["missions"][-1]["wish"] = "کلید من sk-abcdefghijklmnopqrstuvwxyz0123456789ABCD است"
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False)
        reply = self.say("بله")
        self.assertIn("به مغز ابری نفرستادمش", reply)
        self.assertEqual(len(self.cloud.calls), 1)
        self.assertEqual(self.pm().list(), [])


# ====================================================================== a plain question to the brain, and the status words
class QuestionAndStatusTests(OwnBrainCase):
    def test_a_question_to_the_brain_is_answered_at_once_by_the_normal_cloud_path(self):
        self.ready()
        self.script("پایتخت فرانسه پاریس است.")
        reply = self.say("از مغزت بپرس پایتخت فرانسه کجاست؟")
        self.assertTrue(reply.startswith("پایتخت فرانسه پاریس است."))
        self.assertIsNone(self.pending())
        self.assertEqual(len(self.cloud.calls), 2)
        body = json.loads(self.cloud.calls[-1].body.decode("utf-8"))
        self.assertTrue(body["messages"][0]["content"].startswith(persona.BASE_FA), "a question uses the chat persona, not the authoring one")
        self.assertEqual(body["messages"][-1], {"role": "user", "content": "پایتخت فرانسه کجاست"})
        self.assertEqual(body[providers.get("gemini").tokens_field], cloud.MAX_TOKENS_CHAT)

    def test_a_question_to_a_brain_that_is_off_is_still_answered_from_the_kept_answers(self):
        self.ready(memory=True)
        self.script("پایتخت فرانسه پاریس است.")
        self.say("پایتخت فرانسه کجاست؟")                                 # kept for next time
        self.say("مغز ابری را خاموش کن")
        calls = len(self.cloud.calls)
        reply = self.say("از مغزت بپرس پایتخت فرانسه کجاست؟")
        self.assertTrue(reply.startswith("پایتخت فرانسه پاریس است."))
        self.assertIn("بدون اینترنت از حافظهٔ خودم دادم", reply)
        self.assertEqual(len(self.cloud.calls), calls)

    def test_a_question_to_a_brain_that_is_off_says_why(self):
        reply = self.say("از مغزت بپرس پایتخت فرانسه کجاست؟")
        self.assertIn("باید روشن و آماده باشد", reply)
        self.assertEqual(self.cloud.calls, [])

    def test_a_question_with_a_secret_is_not_sent(self):
        self.ready()
        reply = self.say("از مغزت بپرس این کلید برای چیست؟ sk-abcdefghijklmnopqrstuvwxyz0123456789ABCD")
        self.assertIn("به مغز ابری نفرستادمش", reply)
        self.assertEqual(len(self.cloud.calls), 1)

    def test_the_status_words_know_the_brain_route(self):
        self.ready()
        self.script(lang_pack())
        self.ask_and_confirm(LANG_WISH)
        status = self.say("وضعیت ماموریت")
        self.assertIn("مغز ابری", status)
        self.assertIn("درخواست مستقیم به مغز ابریِ خودت", status)
        self.assertIn("بررسی شد", status)


class SuggestedPhrasesTests(unittest.TestCase):
    """The app tells the user which words to say; each phrase it suggests must really be understood (a hint that does not work is a bug)."""

    def test_every_example_the_app_gives_is_a_request_to_the_brain(self):
        phrases = re.findall(r"«([^»]+)»", BM.teacher_need_wish())
        self.assertEqual(len(phrases), 3)
        for phrase in phrases:
            with self.subTest(phrase=phrase):
                norm = nz.normalize(phrase)
                toks = fa_text.words(norm)
                command = HI.classify(phrase, norm, toks)
                self.assertIsNotNone(command)
                self.assertEqual((command.kind, command.slots["assistant"]), (HI.TEACHER_ASK, "brain"))
                self.assertTrue(command.slots["wish"])
                self.assertIsNone(BC.classify(phrase, norm, toks))

    def test_the_hint_for_a_brain_that_is_off_is_a_real_command(self):
        self.assertIn("«مغز ابری را فعال کن»", BM.teacher_not_ready("off"))
        norm = nz.normalize("مغز ابری را فعال کن")
        self.assertEqual(BC.classify("مغز ابری را فعال کن", norm, fa_text.words(norm)).kind, BC.SETUP)

    def test_the_help_text_mentions_the_route_and_its_two_yeses(self):
        text = BM.help_text({"mode": "off", "provider": ""})
        self.assertIn("از مغزت بخواه", text)
        self.assertIn("«بله»ی دومِ تو", text)


class PrecheckTests(core.BrainCase):
    def test_a_clean_wish_passes_and_a_secret_is_named_without_its_value(self):
        brain = self.ready_brain()
        self.assertIsNone(brain.precheck("یک بستهٔ زبان دربارهٔ آشپزی"))
        refused = brain.precheck("کلید من sk-abcdefghijklmnopqrstuvwxyz0123456789ABCD است")
        self.assertEqual((refused.kind, refused.secret), ("blocked", True))
        self.assertNotIn("sk-abcdefgh", json.dumps(self.audit.lines, ensure_ascii=False))
        self.assertEqual(self.fake.calls, [])

    def test_personal_details_follow_the_users_own_switch(self):
        brain = self.ready_brain()
        wish = "پیام را به ali@example.com بفرست"
        self.assertEqual(brain.precheck(wish).code, "email")
        brain.set_share_private(True)
        self.assertIsNone(brain.precheck(wish))

    def test_author_needs_a_ready_brain_and_never_touches_history_or_memory(self):
        brain = self.make()
        self.assertEqual(brain.author("متن", wish="").kind, "not_ready")
        self.assertEqual(self.fake.calls, [])
        brain = self.ready_brain((200, openai_answer("```py\nx_y = 1\n```"), JSON))
        before = (brain.history.count(), brain.learned.count())
        reply = brain.author("یک درخواست", wish="یک درخواست")
        self.assertEqual((reply.kind, reply.text), ("answer", "```py\nx_y = 1\n```"))
        self.assertEqual((brain.history.count(), brain.learned.count()), before)


if __name__ == "__main__":
    unittest.main()
