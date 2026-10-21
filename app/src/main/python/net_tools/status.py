"""
net_tools.status - what we truthfully know about the network
============================================================
`network_status(probe)` never guesses. The Android layer may pass a `probe`
(a zero-argument callable returning True, False or None). Without a probe, with
a probe that answers None, or with a probe that raises, the state is
"unknown" - never "online" and never "offline" without evidence. Note that even
"online" only says the device reports a connection; a request can still fail.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Callable, Optional

__all__ = ["NetworkStatus", "network_status"]

_TEXT = {
    "online": ("دستگاه گزارش می‌دهد به اینترنت وصل است (این به معنای موفق‌شدن هر درخواست نیست).",
               "The device reports a network connection (this does not guarantee that any request succeeds)."),
    "offline": ("دستگاه گزارش می‌دهد به اینترنت وصل نیست.", "The device reports that it is not connected to a network."),
    "unknown": ("وضعیت اینترنت مشخص نیست؛ فقط با انجام درخواست واقعی می‌توان فهمید.",
                "The network state is unknown; only a real request can tell."),
}


@dataclass(frozen=True)
class NetworkStatus:
    state: str  # "online" | "offline" | "unknown"
    source: str  # "probe" | "none" | "probe_error" | "probe_unknown"
    detail: str
    message_fa: str
    message_en: str
    checked_at: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


def network_status(probe: Optional[Callable[[], Optional[bool]]] = None,
                   clock: Callable[[], float] = time.time) -> NetworkStatus:
    """Truthful network state. See the module docstring for what 'unknown' means."""
    now = float(clock())
    if probe is None:
        state, source, detail = "unknown", "none", "no_probe"
    else:
        try:
            answer = probe()
        except Exception as exc:
            state, source, detail = "unknown", "probe_error", type(exc).__name__
        else:
            if answer is True:
                state, source, detail = "online", "probe", "reported_connected"
            elif answer is False:
                state, source, detail = "offline", "probe", "reported_disconnected"
            else:
                state, source, detail = "unknown", "probe_unknown", "probe_returned_none"
    fa, en = _TEXT[state]
    return NetworkStatus(state, source, detail, fa, en, now)
