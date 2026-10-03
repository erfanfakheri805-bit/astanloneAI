"""
Parser
=======
Decides what *kind* of input this is, before anything acts on it:

  - AEL source (starts with a recognized AEL keyword: TEACH / RELATE /
    SKILL / ASK / UPGRADE / ROLLBACK / RULE)
  - plain conversational text (everything else)

This keeps routing logic out of the Core: Core just asks the Parser what
it's looking at, then dispatches accordingly.
"""

AEL_KEYWORDS = ("TEACH ", "RELATE ", "SKILL ", "ASK ", "UPGRADE ", "ROLLBACK ", "RULE ")


class ParsedInput:
    def __init__(self, kind, text):
        self.kind = kind    # "ael" | "conversation"
        self.text = text


class Parser:
    def parse(self, text):
        upper = text.upper()
        if any(upper.startswith(kw) for kw in AEL_KEYWORDS):
            return ParsedInput("ael", text)
        return ParsedInput("conversation", text)
