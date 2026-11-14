# Prompt 959 (stage A) - the optional cloud brain, the answers the app keeps, and «از مغزت بخواه»

Scope: give the app a way to understand free Persian sentences **without shipping any model and without any key of ours**: the user may
connect HIS OWN account of an AI service (his key, his cost), strictly opt-in, off by default, with explicit confirmations and a one-sentence
off switch. Three pieces:

1. **The cloud brain** (`brain_v2/`): a sentence nothing else in the app answered goes to the user's own service - only when he switched it on.
2. **The answers the app keeps** (`brain_v2/learned.py`): the answer to a general question is kept on the phone, so the same question later
   is answered offline, free and instantly. It only recognises a REPEATED question; it is not understanding.
3. **«از مغزت بخواه برایم X بسازد»** (the own-brain teacher): the same two-step safety as «از ChatGPT بخواه», but the request is sent by the
   app itself, in one tool-less request, to the user's own cloud brain. The answer is TEXT: a pack is reviewed (never run) and installed only
   after a second «بله».

A Persian user guide is in `docs/cloud_brain_guide_fa_prompt959.md`. Nothing here was run against a real provider or a real phone: the tests use a
scripted provider (see section 9).

## 1. The rule of every request

A request leaves the phone only when ALL of these hold **at that very moment** (they are re-checked on every call, fail closed):

| # | condition | how it is checked |
| --- | --- | --- |
| 1 | the user switched the cloud brain on and has not pressed the emergency stop | `settings.json`: mode `auto`, `halted` false |
| 2 | he said «بله» to sending his messages to THIS host | consent is bound to the host; changing the provider asks again |
| 3 | the app's internet permission is on | the hub's `network` permission (the master switch he already has) |
| 4 | a key is stored | `key.dat` exists (mode 0600) |
| 5 | the message passed the privacy filter and the hourly cap (120) is not used up | `privacy.check`, `BrainV2._take_call` |

The gate handed to the network layer (`net_tools.post_json`) re-evaluates 1-4 on every call. Audit lines (`brain.*`) record the host, the
outcome and character COUNTS - never a message, an answer or a key.

## 2. Modules

| Package | Modules | Role |
| --- | --- | --- |
| `brain_v2/` | `__init__.py`, `store.py`, `providers.py`, `settings.py`, `keyvault.py`, `privacy.py`, `persona.py`, `history.py`, `cloud.py`, `service.py`, `learned.py` | provider presets (Gemini, OpenAI, OpenRouter, Claude, any OpenAI-compatible host), settings, the key vault, the privacy filter, the system prompts, the short history, request building and failure reasons, the service (`BrainV2`), the kept answers |
| `net_tools/` | `post.py` (+ POST support in `transport.py`) | ONE narrow JSON POST for the cloud brain: HTTPS only, the consented host only, no redirects, bounded time and size, the key never in an error or a log |
| `persian_brain/` | `hub_brain.py`, `hub_brain_commands.py`, `hub_messages_brain.py` | the chat side: the setup conversation, the commands about the brain, the free-sentence reply, the Persian texts |
| `teacher/` | `assistants.py`, `request.py`, `service.py`, `store.py` | one pseudo-assistant `brain` (not in `ASSISTANTS`, so the manifest `<queries>` list is unchanged), the request text addressed to the own brain, the route `brain` |
| `persian_brain/` (existing) | `hub_intents.py`, `hub_teacher.py`, `hub_hooks.py`, `brain.py` | «از مغزت بخواه …» detection; the two branches of the teacher handlers; the hooks that call the new modules |

Files on disk (`<hub root>/brain_v2/`, written atomically, set aside and restarted empty if damaged): `settings.json`, `key.dat` (0600),
`history.json` (last 6 exchanges, 6 hours), `learned.json` (at most 200 answers). A brain that was never switched on leaves NO file.

## 3. The setup conversation (nothing is saved before the user's explicit words)

`«مغز ابری را فعال کن»` -> which service? -> the consent card (the exact host, what is sent, what never is, cost, VPN note) -> «بله» ->
paste the key (the chat-log row that held it is deleted; it never stays in the history) -> a tiny test request -> (if it works) «may personal
details go too?» (default no) -> done. The open question lives in its own key (`persian_brain.brain_pending.v1`); the dialogue module's closed set
of pending types is pinned by earlier tests and is not widened. A short question about the question itself («چرا؟», «یعنی چی؟», «از کجا بگیرم؟»,
«نمی‌فهمم») is answered with an explanation of THAT step and the same question stays open (`hub_brain_commands.is_clarify`); a bare «بله» to
«which service?» shows the list again; any other message that does not answer the question withdraws it (nothing was saved).

Commands (all deterministic, no model involved): switch off/on, status, test, change the model, change/forget the key, allow/forbid personal
details, clear the short history, and the four commands about the kept answers (on / off / clear / how many).

## 4. What never leaves the phone

`privacy.check` refuses, before any request: keys and tokens, private keys, card numbers, IBAN (شبا), passwords and security codes (including
short ones written with «رمز»/CVV/PIN), wallet recovery phrases. E-mail, phone, national-ID and wallet addresses go only if the user allowed it.
A refusal names the KIND found, never the value. The wish of an authoring request is checked twice: before the question («precheck») and again at
send time, on the text that is really sent.

## 5. The answers the app keeps

Only general, complete, non-timely questions (not personal, no secrets, no «today/price/news» words) are kept; matching ignores filler words only
(no fuzzy matching); 200 items, least-recently-used out. «این جواب غلط بود» removes the previous answer - claimed only when the previous reply was
a brain answer (otherwise the older feedback handling of the app answers it, unchanged). It can be switched off and wiped with one sentence each.

## 6. «از مغزت بخواه …» in detail

```
«از مغزت بخواه برایم X بسازد»           (also: «از مغز ابری‌ات بخواه …», «از مغز ابریم بخواه …», «از مغز خودت بخواه …»)
   |  hub_intents: TEACHER_ASK, assistant "brain"; the brain commands do not take it (an ask-verb «بخواه/بپرس» in a sentence that names the brain)
   v
 brain ready?  no -> the reason + the fix phrase, nothing is opened      secret in the wish? -> refused, nothing is opened
   v
 ONE question, naming exactly what leaves: the host, the model, the size of the text, that the chat history, the kept answers, files and
 passwords do not go, the cost, the wait (up to 3 minutes - the chat waits and a new message queues), and that a second «بله» is needed to install
   |  «بله»                      (any other message, or «نه», withdraws it; 30 minutes)
   v
 BrainV2.author(): ONE request, system prompt = persona.AUTHOR_FA, ONE user message (the app's own preface + the live pack format from
 brain_hub.pack_prompt + the wish); no history, nothing stored as history or as a kept answer; 6000 tokens at most; a cut-off answer is refused
   v
 the answer is TEXT: a pack (code.v1 / lang.v1) -> pack_system review (static scan, no execution) -> the user's SECOND «بله» installs it
                      anything else -> shown as text (clipped), nothing installed
```

A plain question («از مغزت بپرس X») is answered at once by the normal cloud path (history, kept answers, privacy) - it is the same as a free
sentence the cloud brain answers. A missing/off brain, the emergency stop, a lost internet permission, a used-up hourly cap, an HTTP error, a
network failure, a cut-off or a rejected pack each produce a plain Persian sentence that says what did NOT happen.

## 7. Honest limits

* Everything above is proven against a SCRIPTED provider and a fake phone. It was never run against a real provider or on a real phone.
* The chat is one request at a time: while the cloud brain writes a pack (usually tens of seconds, at most 3 minutes) the app's chat waits and
  a message typed meanwhile is queued by the page. The emergency word «ایست» is therefore handled after that request ends; a stop control that
  works independently of the chat is part of the next stage (the body of the app).
* There is no automatic repair: a pack the review rejects is shown with the reasons; the user may ask again.
* A model that writes a pack can be wrong; the review is a static scan plus the pack system's checks, not a proof of correctness. Nothing
  is installed without the user's second «بله».
* Some services do not work from Iran without a VPN; the consent card says so.
* A service may change its model names; «مدل مغز ابری را … کن» changes the model, and a failure message says why a request failed.

## 8. What was NOT changed

The seven files pinned by earlier prompts stay byte-identical (`android_entry.py`, `core/core.py`, `ael/interpreter.py`,
`runtime_integration/bridge.py`, `interface/server.py`, `runtime_integration/runtime_core.py`, `runtime_growth/runtime_growth_cycle.py`). The
hub's pinned pending types, the pinned `HUB_PERMISSIONS`, the manifest and the assistant list are unchanged; the frozen tests of earlier prompts
were not edited (the only test touched in the corrective release is this stage's own documentation test, see section 10).

## 9. Tests

`tests/test_net_tools_post_prompt959.py` (the POST layer), `tests/test_brain_v2_core_prompt959.py` (settings, key vault, privacy, history,
requests, failure reasons), `tests/test_brain_v2_chat_prompt959.py` (the whole setup and the commands through the real Persian brain),
`tests/test_brain_v2_learned_prompt959.py` and `tests/test_brain_v2_memory_chat_prompt959.py` (the kept answers), and
`tests/test_brain_v2_teacher_prompt959.py` (the own-brain teacher: nothing before the yes, one request, the second yes, every failure path), and
`tests/test_real_runtime_path_prompt959.py` (the corrective release: the real front door, section 10).

## 10. Corrective release - what the first real phone showed

The first test on a real phone failed on the very first sentence: «مغز ابری را فعال کن» answered «باشد، چیزی راه‌اندازی نشد…» every time.
**Cause:** the application builds its Persian brain as `PersianBrain(memory)` **without a clock** (only tests pass one) and the setup read that missing
clock; the failure was swallowed and looked like the user's own «no». All earlier tests of the cloud brain gave the brain a fake clock and called
`brain.respond` directly, so none of them could see it. **Fixes and rules:**

* `PersianBrain` always owns a clock (`clock or time.time`) and `hub_brain._now(clock)` accepts `None`. A failure to open the setup question now
  says so (`setup_failed`: «نتوانستم این سؤال را باز کنم …») and is never worded like the user's own «نه» (`setup_cancelled`).
* **Test rule:** a test of a chat feature must also go through the real front door - HTTP `POST /api/message` -> `RuntimeCore.process_input` -> `Core` ->
  skills -> Persian brain with NO injected clock - see `tests/test_real_runtime_path_prompt959.py` (41 tests; with the old defect put back - checked by hand, nothing
  committed - 38 checks of it fail).
* The classifier understands what people really type: possessive forms («مغز ابریت», «مغز ابری‌ات», «مغز ابریمو», «هوش مصنوعیِ ابری»), questions
  («چجوری … فعال کنم» = the guided setup, prefixed by one line), «می‌خوام / نمی‌خوام», «مغز ابری را خاموش نکن» (= status, not switch-off), questions
  about it («چیه؟», «امنه؟», «چطور کار می‌کنه؟»). Requests TO the brain («از مغز ابری‌ات می‌خوام یه بسته بنویسه») still go to the teacher. These are rules,
  not understanding: a sentence no rule covers is understood only when the cloud brain is on.
* More spoken names of the services are accepted («جمینی», «چت جی پی تی», «اپن ای آی», «کلاد», «اپن روتر»).
* **The pasted key:** after its chat-log row is deleted, `scrub_log` turns SQLite's `secure_delete` on for that one statement (a SQLite build without
  that default kept the key's bytes in `memory.db`; found by a test) and restores the setting. Where the key remains: its vault file `key.dat`
  (mode 0600, not yet encrypted by the Android Keystore) and, until the app is closed or the turn is pushed out, the in-memory `Core.context` ring of the
  last turns (RAM only; `core/core.py` is a pinned file and cannot be asked to forget it).
* The documentation test of this stage (`tests/test_docs_prompt959.py`) now also accepts the clarification phrases the guide tells the user to say.
* **The app's own «I do not know» replies** (what a user sees when no rule, no taught fact, no pack and no model answers):
  * a Persian sentence that is neither a question nor a request («من امروز خیلی خسته‌ام») used to fall through to the core's English line about AEL;
    `hub_hooks.unknown_reply` now also takes intents `STATEMENT` / `UNKNOWN` that hold at least one Persian letter (`_is_persian`; digits, symbols and
    English stay with the core) and answers in Persian - honestly: no free understanding, what it can do («چه کارهایی بلدی؟», «یاد بگیر که …»). Same
    first-long / then-short logic as the question reply (`hub_self.unknown(..., statement=True)`, one note per 15 quiet minutes).
  * the replies name the way to the cloud brain («مغز ابری را فعال کن») only while it is off: `hub_brain.is_on(brain)` (never raises) feeds
    `snap["cloud_on"]` of `hub_hooks._self_snapshot`; `grow_ways`, `upgrade`, `unknown_first/short` and the statement replies read it. Switched on
    (`mode == "auto"`), nothing points to it - a free sentence is already offered to it first (`hub_brain.reply`: any sentence with at least two letters
    that is not a bare yes/no, not a number or symbol, up to 2000 characters, with two or more words or a question mark).
  * the pinned core is untouched: this is only the Persian brain's own fallback; the English fallback stays for English input.
* **Frozen pins of Prompt 958 changed on purpose (found by the full run, not by the targeted tests).** Ten assertions in `test_pack_chat_prompt958`,
  `test_persian_llm_chat_prompt958` and `test_persian_teacher_chat_prompt958` used `assertIsNone(self.say(sentence))` as the signal «no pack, no model, no
  mission, no command answered this Persian sentence» (the core's English fallback then answered). The brain now answers such a sentence itself, so the
  signal is `tests/nobody_answered_prompt959.nobody_answered(reply)`: `None` or an EXACT match of the brain's two generic «I do not understand this sentence»
  texts - a real answer is still told apart from it. The positive checks («the pack DID answer») became `assertFalse(nobody_answered(...))`, otherwise they
  would pass vacuously now that an unanswered sentence also gets a reply. Every changed line carries a `# Prompt 959 (a conscious change of this pin …)` note; two
  tests of the new real-path module check the helper and that a fallback pack still outranks the generic reply.
* **«وضعیت مغز ابری» no longer says "ready ✅" after a failed connection.** Found by booting the app exactly like the phone (`android_entry.start`, real
  hub, real transport; only the sockets below the transport cut): the settings were complete, so the status said ready although the service had never been
  reached. `BrainV2._call` now remembers the outcome of the last REAL request (`_last = (reached, code, reason_fa)`, memory only - a restart forgets it;
  a service that answered, even with an empty text, counts as reached); `status()` carries `last_ok` / `last_reason`; the status text has the line
  «آخرین تلاش برای وصل‌شدن» (✅ / ❌ with the fixed Persian reason / not tried since the app was opened) and, when the last try failed, says
  «تنظیمات کامل است، ولی آخرین تلاش … ناموفق بود ❌» instead of «آماده است ✅». The provider's own error text is never shown there (it may echo the key).
