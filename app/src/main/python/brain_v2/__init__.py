"""
brain_v2 - the optional CLOUD brain (the user's own key) and the answers the app keeps for offline
==================================================================================================
Off by default, never on without the user's explicit words. See `service.BrainV2` for the five conditions under which a request
may leave the phone, `privacy` for what can never leave, `keyvault` for where the key lives, and `providers` for the services.

The modules do not import the chat layer or the hub (the hub builds a `BrainV2` through `service.get_brain`), so every rule here
is testable with a fake transport and a temporary folder.
"""

from .service import BrainReply, BrainV2, get_brain, reset_brain

__all__ = ["BrainV2", "BrainReply", "get_brain", "reset_brain"]
