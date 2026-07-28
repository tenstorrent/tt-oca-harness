# SPDX-License-Identifier: Apache-2.0
"""cocotb 1.9.2 / Python 3.13+ teardown-noise shim.

``GPITrigger`` declares ``__slots__ = ("cbhdl",)``. A ``Timer`` that is garbage
collected without a completed ``__init__`` can raise ``AttributeError`` inside
``Trigger.__del__`` -> ``unprime()`` and print a harmless
``Traceback (most recent call last):`` block at simulation shutdown. The DV log
parser treats that text as a hard-fail pattern, turning an otherwise PASSING
cocotb test into an ERROR.

Deallocators must never raise, so make ``Trigger.__del__`` exception-safe. This
only suppresses errors on the teardown path; it does not affect test behavior.
"""

from __future__ import annotations


def apply() -> None:
    try:
        import cocotb.triggers as _triggers
    except Exception:  # pragma: no cover - cocotb always present under the sim
        return

    trigger_cls = getattr(_triggers, "Trigger", None)
    trigger_del = getattr(trigger_cls, "__del__", None)
    if trigger_cls is None or trigger_del is None or getattr(trigger_del, "_dtp_safe", False):
        return

    def __del__(self):  # noqa: N807 - dunder override
        try:
            self.unprime()
        except Exception:
            pass

    __del__._dtp_safe = True
    trigger_cls.__del__ = __del__
