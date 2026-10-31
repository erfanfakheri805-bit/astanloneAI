# Self-knowledge, the honest "I do not know", and the growth platform's chat surface (Prompt 958)

This note is for the engineer (or the assistant) who changes the Persian brain after Prompt 958. It explains **what was added to the
conversation, why it is built the way it is, and which older tests were changed on purpose**. Everything about on-device behaviour is
UNVERIFIED: the Java side was compiled and exercised only against hand-written stand-ins, and no real phone has run this build yet.

## 1. What the user sees

| The user says | The app answers from | Module |
| --- | --- | --- |
| «چه کارهایی بلدی؟», «توانایی‌هات چیه؟», «تو کی هستی؟», «اسمت چیه؟» | one unified reply: what it can do + what it really has on this phone + what it cannot do yet | `hub_hooks.about_reply` → `hub_messages_self.about` |
| «مغز فارسی داری؟», «چطور باهوش‌ترت کنم؟» | the two layers of the Persian brain and the ways to grow | `hub_self` BRAIN |
| «خودت را ارتقا بده», «کد خودت را تغییر بده» | the safe ways (packs, a model file, a GitHub build); nothing is changed silently | `hub_self` UPGRADE |
| «صدایم را می‌شنوی؟», «می‌تونی حرف بزنی؟» | dictation button yes/no, and what is not there (always-on listening, "Jarvis" wake word, speaking aloud) | `hub_self` VOICE |
| «می‌تونی از ChatGPT کمک بگیری؟», «می‌تونی بری توی گوگل؟» | the real doors and their conditions (internet read, the teacher, the accessibility service) | `hub_self` OUTSIDE |
| any question or request nothing can answer | «این را نمی‌دانم …» + the real ways to grow; the sentence is kept for «از ChatGPT بخواه» | `hub_self.unknown` |
| «راهنما» | the older help list + `help_more()` (the growth ways) | `hub_hooks.help_reply` |

## 2. Where it sits in `PersianBrain._respond` (scope FULL only)

`hub_hooks.early` (pack/extension paste) → routing → `hub_hooks.command` (the closed-vocabulary `HI.classify` cascade) → `I.classify` →
`_dispatch`. For QUESTION / STATEMENT / UNKNOWN / other REQUEST the tail is:

`_general` → `hub_hooks.gap_reply` (pack `fallback` handlers → **`self_reply`** → gap catalogue) → `hub_hooks.llm_reply` (a usable local model) →
**`hub_hooks.unknown_reply`** → otherwise `None` and the Core's own fallback speaks.

The self layer is deliberately **before** the language model: a small model asked "who are you?" says "I am Gemma"; the right answer is
"your personal assistant (not ChatGPT, not Claude)" built from the live state. Outside `SCOPE_FULL` (a plain desktop Core, scope
"capabilities") nothing new is claimed: the old capability list/help is used and unknown questions still return `None`.

## 3. Classification (`persian_brain/hub_self.py`)

* `classify(norm, toks)` → one of ABOUT / BRAIN / UPGRADE / VOICE / OUTSIDE or `None`. Priority: UPGRADE, VOICE, OUTSIDE, BRAIN, ABOUT.
* Closed word lists only (no similarity guessing). Limits: `MAX_CHARS = 240`, at most 24 tokens - a long message is not a question about the assistant.
* Attached possessives («توانایی‌هات», «اسمت», «تونی») are split before matching; the user's own name sentences («اسم من عرفان است») and sentences that name
  another assistant in a "with me" or "use X" shape are never taken as questions about the app.
* «مدل زبانی داری؟» belongs to the HUB models list (not to BRAIN); «چه کاری از دستت برمیاد؟» goes through the COMMAND/list route so that there is ONE reply.

## 4. The snapshot (the only source of truth for the replies)

`hub_hooks._self_snapshot` builds a plain dict - nothing in `hub_messages_self` may state a fact that is not in it:

```
{"model": {"state": "none|imported|usable", "title": str, "reason": str},
 "packs": {"active": int, "installed": int, "safe": bool},
 "assistants": [{"id": str, "title": str, "installed": bool}],
 "native": frozenset({"file_chooser", "voice_input", ...}),
 "internet": bool, "wish": str}
```

Consequences that tests pin: the dictation button is mentioned only when `voice_input` is in `native`; an installed assistant app is named only when it
was really seen; a model is "usable" only after the model manager's real pipeline passed; the accessibility door is described as "needs your own switch".

## 4a. The unknown reply (`hub_self.unknown`, `hub_hooks.unknown_reply`)

* Fires for QUESTION / REQUEST with at least 2 tokens and at most `MAX_LLM_CHARS`, only in scope FULL, only after the model step had nothing.
* The long text is shown first; within 15 minutes (`UNKNOWN_QUIET_SECONDS = 900`, key `UNKNOWN_KEY`) only the short text. The timestamp is written **only when the long
  text was actually shown**.
* It saves the sentence as the user's "wish" (24 h TTL, `hub_state.load_wish` returns `""` when there is none) so that a bare «از ChatGPT بخواه» can take it on.
* It keeps the real intent (QUESTION/general); self replies set `Intent("HUB", "self_<kind>", 0.9, ["self_knowledge"])`.

## 5. Older tests that were changed ON PURPOSE (and why)

The rule "do not edit a test to make it pass" was kept: each of these tests encoded behaviour that this prompt deliberately replaced, and each carries an
"Updated in Prompt 958 on purpose" comment with the reason. None was loosened to hide a regression.

| Test | Old expectation | New expectation and reason |
| --- | --- | --- |
| `test_persian_brain_final_exit001.TestKnowledgeAndTeaching.test_a_plain_statement_is_only_remembered_after_the_user_agrees` | an unanswerable question → `None` | honest «نمی‌دانم» reply; nothing is stored |
| `…TestKnowledgeAndTeaching.test_declining_a_statement_stores_nothing` | `None` | same reply; still no stored fact |
| `…TestKnowledgeAndTeaching.test_unknown_knowledge_questions_are_left_to_the_existing_pipeline` | `None` | the pipeline still invents nothing; the honest reply replaces `None` |
| `…TestOpenQuestionVersusNewRequest.test_a_question_mark_marks_a_new_topic_but_the_word_what_does_not` | «اسم تو چیست؟» got no reply | it is a question about the assistant and is now answered by the self layer |
| `…TestNoResponseTable.test_unknown_messages_get_no_invented_answer` | `None` | in scope FULL the brain says plainly it does not know; outside FULL it is still `None` |
| `test_baby_ai_acceptance_prompt957.A07Unsupported.test_an_unknown_question_is_not_dressed_up_as_knowledge` | silent | honest «نمی‌دانم» + real ways to grow; still no fabricated fact |
| `test_brain_hub_invoker_prompt957.GraphOverview.test_a_fresh_install_lists_everything_and_creates_nothing` | 957 node counts | the growth platform adds nodes (packs, teacher, local model, native doors) |
| `…GraphOverview.test_a_builder_that_fails_adds_a_broken_node_and_hides_nothing` | counts | the separate platform builder's four native-door nodes stay when another builder fails |
| `test_pack_chat_prompt958.PasteAndApproveTests.test_pasting_a_lang_pack_proposes_then_the_yes_installs_it` | blank Core fallback for "nothing answers" | the honest reply |
| `test_persian_teacher_chat_prompt958.AnswerTests.test_an_arrival_with_no_open_mission_is_just_an_ordinary_sentence` | `None` | still not a command (nothing starts, nothing is asked), but the unknown reply may speak |

## 6. Tests and how they were checked

* `tests/test_self_knowledge_prompt958.py` covers classification (positive and negative sentences), every reply against its snapshot (no claim without evidence),
  the unknown reply (cooldown, wish, scope), the unified list route, the help text, and the in-app advice audit: every command the app itself recommends must be understood.
* During development the layer was mutation-checked (each guard removed in turn must make a test fail); the final run had no survivors. The mutation script is not part of the repo.
* The documents are tied to the code by `DocsStayTrue` in the same test file: the numbers and examples of `chatgpt_briefing_prompt958.md` must equal the live pack
  limits and examples, and every command in the tables of `baby_ai_guide_fa_prompt958.md` must be understood by the real brain.

## 7. Known limits

* The classifiers are closed word lists; a phrasing nobody listed falls through to the language model (if any) or the honest unknown reply - never to a guess.
* The unknown reply is Persian-only by design.
* `hub_hooks.gap_reply` still ends some gap texts with «پرامپت افزونه» (the `ext.v1` route); it works and is understood, but new advice should prefer «پرامپت بسته برای …».
* With no pending request, «جواب آمد» is not a command (`None` → the Core's own fallback).
