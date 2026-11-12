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
of pending types is pinned by earlier tests and is not widened. Any message that does not answer the question withdraws it.

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
hub's pinned pending types, the pinned `HUB_PERMISSIONS`, the manifest and the assistant list are unchanged; frozen tests were not edited.

## 9. Tests

`tests/test_net_tools_post_prompt959.py` (the POST layer), `tests/test_brain_v2_core_prompt959.py` (settings, key vault, privacy, history,
requests, failure reasons), `tests/test_brain_v2_chat_prompt959.py` (the whole setup and the commands through the real Persian brain),
`tests/test_brain_v2_learned_prompt959.py` and `tests/test_brain_v2_memory_chat_prompt959.py` (the kept answers), and
`tests/test_brain_v2_teacher_prompt959.py` (the own-brain teacher: nothing before the yes, one request, the second yes, every failure path).
