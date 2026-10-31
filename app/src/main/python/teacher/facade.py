"""
teacher.facade - `api.teacher`: what a code pack with the "teacher" permission may do
====================================================================================
    api.teacher.assistants()                       the assistants and which are installed
    api.teacher.build_request(wish, kind)          the request text (no delivery)
    api.teacher.recipes_for(assistant_id)          the recipes currently available
    api.teacher.validate_recipe(recipe)            True / a Persian reason

A pack cannot deliver a request by itself (that is what the chat command, the user's question and the share sheet are for), and it
cannot start the typing recipe: the most it can do is ADD a recipe (`api.register_recipe`), which the user still has to allow app by app.
"""

from . import assistants as A
from . import recipes as RC
from . import request as R

__all__ = ["TeacherAPI", "for_pack"]


class TeacherAPI:
    def __init__(self, pack_id, registry=None):
        self.pack_id = pack_id
        self._registry = registry

    def assistants(self):
        return [{"id": a.assistant_id, "title": a.title, "packages": list(a.packages), "site": a.site} for a in A.ASSISTANTS]

    def build_request(self, wish, kind="code", assistant_id="chatgpt"):
        assistant = A.get(assistant_id) or A.get("chatgpt")
        return R.build(wish, kind, assistant.title)[0]

    def recipes_for(self, assistant_id):
        try:
            registered = self._registry.recipes() if self._registry is not None else {}
        except Exception:
            registered = {}
        return [dict(r) for r in registered.values() if isinstance(r, dict) and r.get("assistant") == assistant_id]

    def validate_recipe(self, recipe):
        try:
            RC.validate(recipe)
            return True
        except ValueError as exc:
            return str(exc)


def for_pack(pack_id, permissions, registry=None):
    return TeacherAPI(pack_id, registry)
