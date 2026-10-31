"""
pack_system.errors - one exception type with a stable code and a Persian message
================================================================================
Every refusal of the pack system carries a short stable `code` (for tests and logs) and a `message_fa` the chat can
show as it is. Nothing here is raised for a user-level problem outside this package: the manager turns it into a
plain-data result.
"""

__all__ = ["PackError"]


class PackError(Exception):
    def __init__(self, code, message_fa, detail=""):
        super().__init__("%s: %s" % (code, detail or message_fa))
        self.code = str(code)
        self.message_fa = str(message_fa)
        self.detail = str(detail)[:200]

    def to_dict(self):
        return {"status": "rejected", "code": self.code, "message_fa": self.message_fa, "detail": self.detail}
