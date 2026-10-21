"""
Prompt 957 - the chat road to a NEW capability: a user pastes an extension package into the Persian conversation, the
app proposes it (nothing changes), installs it only after an explicit «بله», proves the installation by re-reading it
from disk, and from then on answers plain sentences with it. Failures, restarts, updates and rollback are real flows on
a real MemorySystem + HubService (only the network, downloads and the Android bridge are scripted doubles).
"""
import json
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from persian_brain import hub_state
from self_builder import fa_text
from tests import brain_hub_fixtures_prompt957 as F
from tests.persian_hub_case_prompt957 import HubChatCase, fenced

fa = fa_text.fa_number
JALALI_QUESTION = "تاریخ شمسی ۲۰۲۴ ۳ ۲۰"
JALALI_V1 = "۲۰۲۴/۳/۲۰ میلادی = ۱۴۰۳/۱/۱ شمسی"
JALALI_V2 = "تاریخ شمسی: ۱۴۰۳-۱-۱"
FOOTER = "— افزونهٔ «تبدیل تاریخ میلادی به شمسی» · نسخهٔ %s"
CLAIMS = ("نصب و فعال شد", "نصب شد", "یاد گرفتم", "قابل استفاده است", "فعال شد")


def yes_pkg():
    """An extension whose triggers are the bare words «بله» and «نه»: it must never steal an answer to a question."""
    return {"schema": "ext.v1", "id": "yes_echo", "title": "پژواک بله", "description": "هر بار که کلمهٔ بله یا نه گفته شود عدد ثابتی برمی‌گرداند.",
            "inputs": [{"name": "unused", "type": "integer", "default": 0, "required": False}],
            "outputs": [{"name": "value", "type": "integer", "label": "مقدار"}],
            "source": "def run(unused):\n    return {'value': 42}\n", "triggers": ["بله", "نه"], "answer": "پژواک {value}",
            "tests": [{"inputs": {}, "expect": {"value": 42}}]}


class InstallFlow(HubChatCase):
    def test_a_package_is_only_proposed_until_the_user_says_yes(self):
        reply = self.paste(F.jalali_pkg())
        self.assertIn("هنوز چیزی نصب یا فعال نشده", reply)
        self.assertIn("(بله / نه)", reply)
        self.assertNotIn("نصب و فعال شد", reply)
        self.assertEqual(self.trace_kind(), ("HUB", "package"))
        self.assertEqual(self.pending()[0], "install")
        self.assertEqual(self.installed_ids(), [])
        self.assertEqual(len(self.hub.pending_proposals()), 1)
        # nothing can be called yet, neither through the hub nor through a sentence
        self.assertEqual(self.hub.invoke_extension("jalali_date", {"gy": 2024, "gm": 3, "gd": 20})["status"], "not_found")
        self.assertEqual(self.hub.match_extension(JALALI_QUESTION), {"status": "none"})

    def test_after_yes_the_extension_is_verified_and_answers_plain_chat(self):
        reply = self.install(F.jalali_pkg())
        self.assertIn("از دیسک دوباره بررسی شد", reply)
        self.assertIn("آزمون‌ها ۵ از ۵ موفق", reply)
        cap = self.hub.extension("jalali_date")
        self.assertEqual((cap["state"], cap["active_version"]), ("active", 1))
        self.assertIsNone(self.pending())
        answer = self.say(JALALI_QUESTION)
        self.assertIn(JALALI_V1, answer)
        self.assertIn(FOOTER % "۱", answer)
        self.assertEqual(self.trace_kind(), ("HUB", "extension"))

    def test_the_answer_is_computed_by_the_extension_and_not_looked_up(self):
        self.install(F.jalali_pkg())
        for gy, gm, gd, jy, jm, jd in F.JALALI_DATES:
            with self.subTest(date=(gy, gm, gd)):
                reply = self.say("تاریخ شمسی %d %d %d" % (gy, gm, gd))                    # plain ASCII digits
                self.assertIn("%s/%s/%s میلادی = %s/%s/%s شمسی" % tuple(fa(v) for v in (gy, gm, gd, jy, jm, jd)), reply)
        self.assertIn("۱۳۷۸/۱۰/۱۱ شمسی", self.say("۲۰۰۰ ۱ ۱ را به شمسی تبدیل کن"))     # the second trigger shape

    def test_inputs_that_do_not_fit_never_run_the_extension(self):
        self.install(F.jalali_pkg())
        reply = self.say("تاریخ شمسی ۲۰۲۴ ۱۳ ۲۰")
        self.assertIn("ورودی‌ها", reply)
        self.assertIn("چیزی اجرا نشد", reply)
        self.assertNotIn("شمسی =", reply)
        self.assertNotIn("میلادی =", reply)

    def test_no_installs_nothing_and_closes_the_proposal(self):
        self.paste(F.jalali_pkg())
        reply = self.say("نه")
        self.assertIn("چیزی نصب نشد", reply)
        self.assertIsNone(self.pending())
        self.assertEqual(self.installed_ids(), [])
        self.assertEqual(self.hub.pending_proposals(), [])
        self.assertNotIn("نصب و فعال شد", self.say("بله") or "")
        self.assertEqual(self.installed_ids(), [])

    def test_any_other_message_withdraws_and_declines_the_proposal(self):
        self.paste(F.jalali_pkg())
        self.say("سلام")
        self.assertIsNone(self.pending())
        self.assertEqual(self.hub.pending_proposals(), [])               # the review said it would be set aside: it was
        self.assertNotIn("نصب و فعال شد", self.say("بله") or "")
        self.assertEqual(self.installed_ids(), [])
        self.assertIn("رد شد", self.say("تاریخچهٔ افزونه‌ها"))

    def test_a_bare_yes_with_no_open_question_changes_nothing(self):
        for word in ("بله", "آره", "باشه"):
            with self.subTest(word=word):
                reply = self.say(word)
                self.assertNotIn("نصب و فعال شد", reply or "")
        self.assertEqual(self.installed_ids(), [])
        self.assertFalse(self.hub.has_extensions())                      # not even a store was created

    def test_the_question_expires_after_thirty_minutes_and_says_so(self):
        self.paste(F.jalali_pkg())
        self.clock.advance(hub_state.PENDING_TTL_SECONDS + 60)
        reply = self.say("بله")
        self.assertIn("منقضی شد", reply)
        self.assertIn("چیزی نصب یا تغییر نکرد", reply)
        self.assertEqual(self.installed_ids(), [])
        self.assertEqual(self.hub.pending_proposals(), [])
        self.assertIsNone(self.pending())
        self.assertNotIn("منقضی", self.say("بله") or "")                  # said once, not on every later «بله»

    def test_a_question_answered_within_thirty_minutes_still_installs(self):
        self.paste(F.jalali_pkg())
        self.clock.advance(hub_state.PENDING_TTL_SECONDS - 60)
        self.assertIn("نصب و فعال شد", self.say("بله"))

    def test_the_open_question_survives_a_restart(self):
        self.paste(F.jalali_pkg())
        self.open_app()
        self.assertEqual(self.pending()[0], "install")
        self.assertIn("نصب و فعال شد", self.say("بله"))
        self.assertEqual(self.installed_ids(), ["jalali_date"])

    def test_an_installed_extension_survives_restarts(self):
        self.install(F.jalali_pkg())
        for _ in range(2):
            self.open_app()
            self.assertIn(JALALI_V1, self.say(JALALI_QUESTION))
        self.assertEqual(self.active_version("jalali_date"), 1)
        self.assertIn("«تبدیل تاریخ میلادی به شمسی»", self.say("افزونه‌ها را لیست کن"))

    def test_packages_are_found_in_the_shapes_people_paste_them(self):
        body = F.dumps(F.jalali_pkg())
        shapes = {"bare json": body, "text around": "سلام! این بسته است " + body + " لطفاً نصبش کن.",
                  "plain fence": "```\n" + body + "\n```", "indented json": json.dumps(F.jalali_pkg(), ensure_ascii=False, indent=4),
                  "escaped unicode": json.dumps(F.jalali_pkg())}
        for name, text in shapes.items():
            with self.subTest(shape=name):
                reply = self.say(text)
                self.assertIn("هنوز چیزی نصب یا فعال نشده", reply)
                self.say("نه")                                                 # close the question for the next shape
                self.assertEqual(self.installed_ids(), [])
                self.assertEqual(self.hub.pending_proposals(), [])

    def test_an_incomplete_package_is_reported_never_guessed(self):
        cut = fenced(F.jalali_pkg())[:-70]
        reply = self.say(cut)
        self.assertIn("چیزی نصب نشد", reply)
        self.assertIsNone(self.pending())
        self.assertEqual(self.installed_ids(), [])
        self.assertEqual(self.hub.pending_proposals(), [])

    def test_talking_about_the_format_is_not_a_package(self):
        self.say("ext.v1 چیست؟")
        self.assertNotEqual(self.trace_kind()[0], "HUB")
        self.assertEqual(self.installed_ids(), [])

    def test_real_conversation_replies_are_counted_for_the_capability_map(self):
        before = self.hub.served_count("brain.conversation")
        self.assertIsNotNone(self.say("سلام"))
        self.assertEqual(self.hub.served_count("brain.conversation"), before + 1)
        self.install(F.jalali_pkg())
        self.assertGreater(self.hub.served_count("brain.conversation"), before + 1)


    def test_a_bare_yes_or_no_never_runs_an_extension_or_steals_the_dialogues_answer(self):
        self.install(yes_pkg())                                          # (installing it used the hub's own yes)
        self.assertIn("(بله / نه)", self.say("پایتون یک زبان برنامه‌نویسی است"))   # the dialogue asks whether to learn it
        reply = self.say("بله")
        self.assertIn("یاد گرفتم", reply)                                  # the dialogue got its answer ...
        self.assertNotIn("پژواک", reply)                                   # ... not the extension
        nothing = self.say("بله")
        self.assertNotIn("پژواک", nothing or "")


class Rejections(HubChatCase):
    def assertRejected(self, reply):
        self.assertIn("هیچ چیزی نصب یا فعال نشد", reply)
        for claim in CLAIMS:
            self.assertNotIn(claim, reply)
        self.assertIsNone(self.pending())
        self.assertEqual(self.installed_ids(), [])
        self.assertEqual(self.hub.pending_proposals(), [])

    def test_every_malicious_package_is_rejected_and_never_active(self):
        for kind in F.MALICIOUS:
            with self.subTest(kind=kind):
                self.assertRejected(self.paste(F.malicious_pkg(kind)))
                self.assertIsNone(self.hub.extension("evil_ext"))
                self.assertEqual(self.hub.invoke_extension("evil_ext", {"gy": 2024, "gm": 3, "gd": 20})["status"], "not_found")
                self.assertNotIn("نصب و فعال شد", self.say("بله") or "")           # a yes afterwards installs nothing
                self.assertEqual(self.installed_ids(), [])

    def test_the_rejection_names_the_stage_that_failed(self):
        self.assertIn("قواعد کد", self.paste(F.malicious_pkg("escape")))
        self.assertIn("آزمون‌های پذیرش", self.paste(F.malicious_pkg("endless")))
        wrong = self.paste(F.broken_tests_pkg())
        self.assertIn("آزمون‌های پذیرش", wrong)
        self.assertIn("expected 1400", wrong)                                      # the validator's own words, not invented
        self.assertRejected(wrong)

    def test_an_invalid_manifest_lists_the_problems_and_how_to_fix_them(self):
        reply = self.say('بسته: {"schema": "ext.v1", "id": "x"}')
        self.assertRejected(reply)
        self.assertIn("ساختار و فیلدهای بسته", reply)
        self.assertIn("• ", reply)
        self.assertIn("دوباره بفرستش", reply)

    def test_a_package_over_the_size_limit_is_refused(self):
        huge = F.jalali_pkg(source=F.JALALI_SOURCE + "# " + "x" * 210_000 + "\n")
        reply = self.paste(huge)
        self.assertRejected(reply)
        self.assertIn("200000", reply)

    def test_a_failed_update_leaves_the_working_version_active(self):
        self.install(F.jalali_pkg())
        for bad in (F.jalali_pkg(source=F.MALICIOUS["eval"]), F.broken_tests_pkg()):
            reply = self.paste(bad)
            self.assertIn("هیچ چیزی نصب یا فعال نشد", reply)
            self.assertIsNone(self.pending())
            self.assertEqual(self.active_version("jalali_date"), 1)
            self.assertIn(JALALI_V1, self.say(JALALI_QUESTION))
        self.assertEqual(self.hub.pending_proposals(), [])

    def test_rejection_replies_never_say_installed(self):
        for pkg in (F.malicious_pkg("open"), F.malicious_pkg("import"), F.broken_tests_pkg()):
            reply = self.paste(pkg)
            self.assertNotIn("نصب و فعال شد", reply)
            self.assertNotIn("هنوز چیزی نصب یا فعال نشده", reply)       # that sentence belongs to a valid proposal only


class UpdateAndRollback(HubChatCase):
    def update_to_v2(self):
        self.install(F.jalali_pkg())
        review = self.paste(F.jalali_pkg(answer="تاریخ شمسی: {jy}-{jm}-{jd}"))
        self.assertIn("به‌روزرسانی", review)
        self.assertIn("نسخهٔ ۲", review)
        self.assertEqual(self.active_version("jalali_date"), 1)           # nothing changed before the yes
        done = self.say("بله")
        self.assertIn("نصب و فعال شد (نسخهٔ ۲)", done)
        self.assertIn("نسخهٔ قبلی (۱) نگه داشته شد", done)
        return done

    def test_an_update_creates_version_two_and_keeps_version_one(self):
        self.update_to_v2()
        self.assertEqual(self.active_version("jalali_date"), 2)
        answer = self.say(JALALI_QUESTION)
        self.assertIn(JALALI_V2, answer)
        self.assertIn(FOOTER % "۲", answer)
        versions = {v["version"]: v["status"] for v in self.hub.extension_versions("jalali_date")}
        self.assertEqual(versions[2], "active")
        self.assertEqual(versions[1], "superseded")

    def test_rollback_is_asked_first_and_restores_the_previous_behaviour(self):
        self.update_to_v2()
        ask = self.say("افزونهٔ تبدیل تاریخ میلادی به شمسی را برگردان")
        self.assertIn("از نسخهٔ ۲ به نسخهٔ ۱ برگردانده شود؟", ask)
        self.assertEqual(self.active_version("jalali_date"), 2)           # not before the yes
        done = self.say("بله")
        self.assertIn("از نسخهٔ ۲ به نسخهٔ ۱ برگشت", done)
        self.assertEqual(self.active_version("jalali_date"), 1)
        self.assertIn(JALALI_V1, self.say(JALALI_QUESTION))              # the old behaviour is back
        history = self.say("تاریخچهٔ افزونه‌ها")
        self.assertIn("به نسخهٔ قبل برگشت", history)

    def test_rollback_goes_to_the_newest_older_version_and_an_explicit_version_works(self):
        self.update_to_v2()
        self.paste(F.jalali_pkg(answer="شمسی {jy}.{jm}.{jd}"))
        self.assertIn("نسخهٔ ۳", self.say("بله"))
        self.assertEqual(self.active_version("jalali_date"), 3)
        self.assertIn("از نسخهٔ ۳ به نسخهٔ ۲", self.say("افزونه را برگردان"))        # the newest OLDER one, not the oldest
        self.say("بله")
        self.assertIn(JALALI_V2, self.say(JALALI_QUESTION))
        self.assertIn("از نسخهٔ ۲ به نسخهٔ ۱", self.say("افزونه را برگردان"))
        self.say("بله")
        self.assertIn(JALALI_V1, self.say(JALALI_QUESTION))
        self.assertIn("از نسخهٔ ۱ به نسخهٔ ۳", self.say("افزونه را به نسخهٔ ۳ برگردان"))   # an explicit, healthy version
        self.say("بله")
        self.assertEqual(self.active_version("jalali_date"), 3)
        self.assertIn("شمسی ۱۴۰۳.۱.۱", self.say(JALALI_QUESTION))
        self.assertIn("آن نسخه وجود ندارد", self.say("افزونه را به نسخهٔ ۹ برگردان"))      # an unknown version is refused
        self.assertEqual(self.active_version("jalali_date"), 3)

    def test_the_history_names_every_event_and_never_shows_an_empty_name(self):
        self.update_to_v2()
        history = self.say("تاریخچهٔ افزونه‌ها")
        self.assertNotIn("«»", history)
        self.assertNotIn("None", history)
        self.assertNotIn("ext.", history)                                  # no raw event names
        self.assertIn("بررسی خودکار یکپارچگی حافظهٔ افزونه‌ها", history)   # an event of the whole store is named, not hidden
        for label in ("پیشنهاد شد", "تأیید شد", "فعال شد"):
            self.assertIn(label, history)

    def test_declining_the_rollback_keeps_the_current_version(self):
        self.update_to_v2()
        self.say("افزونه را برگردان")
        self.assertIn("چیزی تغییر نکرد", self.say("نه"))
        self.assertEqual(self.active_version("jalali_date"), 2)
        self.assertIn(JALALI_V2, self.say(JALALI_QUESTION))

    def test_rollback_survives_a_restart(self):
        self.update_to_v2()
        self.say("افزونه را برگردان")
        self.say("بله")
        self.open_app()
        self.assertEqual(self.active_version("jalali_date"), 1)
        self.assertIn(JALALI_V1, self.say(JALALI_QUESTION))

    def test_there_is_nothing_to_roll_back_without_an_older_version(self):
        self.install(F.jalali_pkg())
        reply = self.say("افزونه را برگردان")
        self.assertIn("نسخهٔ قبلیِ سالمی برای برگشتن ندارد", reply)
        self.assertIsNone(self.pending())
        self.assertEqual(self.active_version("jalali_date"), 1)

    def test_an_identical_package_changes_nothing(self):
        self.install(F.jalali_pkg())
        reply = self.paste(F.jalali_pkg())
        self.assertIn("دقیقاً یکی است", reply)
        self.assertIn("چیزی تغییر نکرد", reply)
        self.assertIsNone(self.pending())
        self.assertEqual(self.active_version("jalali_date"), 1)
        self.assertEqual(len(self.hub.extension_versions("jalali_date")), 1)

    def test_two_extensions_live_side_by_side(self):
        self.install(F.jalali_pkg())
        self.install(F.factors_pkg())
        self.assertEqual(self.installed_ids(), ["jalali_date", "prime_factors"])
        self.assertIn(JALALI_V1, self.say(JALALI_QUESTION))
        self.assertIn("۲، ۲، ۲، ۳، ۳، ۵", self.say("عوامل اول ۳۶۰"))
        asked = self.say("افزونه را غیرفعال کن")                          # two installed and none named: it asks which
        self.assertIn("کدام افزونه", asked)
        self.assertIsNone(self.pending())


if __name__ == "__main__":
    unittest.main()
