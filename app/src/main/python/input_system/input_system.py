"""
Input System
=============
The single entry point for anything the user types into the interface.
Its job is narrow on purpose: clean and normalize raw text before it is
handed to the Parser. Keeping this separate from parsing means future
input sources (file uploads, images, voice-to-text) can plug in here
without the Parser or Core needing to change.
"""


class InputSystem:
    def normalize(self, raw_text):
        if raw_text is None:
            return ""
        text = str(raw_text).strip()
        # Collapse internal whitespace
        text = " ".join(text.split())
        return text
