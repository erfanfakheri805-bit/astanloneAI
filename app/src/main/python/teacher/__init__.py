"""
teacher - asking other assistants (ChatGPT, Claude, Gemini ...) for what this app cannot do itself
==================================================================================================
    assistants   the known assistants: Android packages, websites, Persian names
    request      the text the assistant receives (built from the live pack validator)
    store        missions and the user's per-app allowances (atomic, bounded, validated)
    recipes      how to drive an assistant's app, as data from a closed vocabulary
    capture      recognising the answer (screen / shared into the inbox / clipboard)
    service      TeacherService: draft, deliver, capture, the optional typing run
    facade       `api.teacher` for code packs

Everything the assistant returns is text. A pack found in it goes through the pack system's review and the user's own yes.
"""

__all__ = ["assistants", "request", "store", "recipes", "capture", "service", "facade"]
