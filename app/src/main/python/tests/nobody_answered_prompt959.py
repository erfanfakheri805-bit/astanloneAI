"""Prompt 959 (corrective release) - what «nothing answered this sentence» means in the frozen chat tests of Prompt 958.

Those tests used `assertIsNone(self.say(sentence))` as the signal that no pack, no language model, no mission and no command answered a
Persian sentence, because then the brain left the sentence to the core, whose fallback is an ENGLISH line about AEL. On the phone that
line made the app look as if it understood nothing: a Persian sentence such as «من امروز خیلی خسته‌ام» got an English sentence about
teaching it AEL. The brain now answers such a sentence itself, honestly and in Persian (`hub_hooks.unknown_reply`, intents STATEMENT and
UNKNOWN; `hub_messages_self.unknown_statement_first` / `unknown_statement_short`).

So the signal changed from «the brain returned None» to «the brain returned None OR its own generic «I do not understand this sentence»
reply». `nobody_answered` is exactly that - an exact match against the two generic texts, so a real answer (a pack's, a model's, a
command's) is still told apart from it. The positive checks («the pack DID answer») use `assertFalse(nobody_answered(...))`, otherwise
they would pass vacuously now that an unanswered sentence also gets a reply.
"""
from persian_brain import hub_messages_self as HS

__all__ = ["nobody_answered"]

_VARIANTS = (False, True, None)       # `cloud_on` of the self-knowledge snapshot decides whether the generic text names the cloud brain


def nobody_answered(reply):
    """True for `None` and for the brain's two generic «I do not understand this sentence» texts; False for any real answer."""
    if reply is None:
        return True
    for cloud_on in _VARIANTS:
        snap = {"cloud_on": cloud_on}
        if reply in (HS.unknown_statement_first(snap), HS.unknown_statement_short(snap)):
            return True
    return False
