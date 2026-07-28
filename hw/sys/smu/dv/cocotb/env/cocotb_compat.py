# SPDX-License-Identifier: Apache-2.0
"""cocotb 1.9.2 teardown-noise shim (same contract as DTP OSS).

``GPITrigger`` declares ``__slots__ = ("cbhdl",)``. A ``Timer`` GC'd without a
completed ``__init__`` can raise ``AttributeError`` inside ``Trigger.__del__``
and print a ``Traceback`` at shutdown. The DV log parser treats that as a
hard-fail, turning an otherwise PASSING test into ERROR.

Deallocators must never raise - make ``Trigger.__del__`` exception-safe.
"""

from __future__ import annotations


def apply() -> None:
    try:
        import cocotb.triggers as _triggers
    except Exception:  # pragma: no cover
        return

    trigger_cls = getattr(_triggers, "Trigger", None)
    trigger_del = getattr(trigger_cls, "__del__", None)
    if trigger_cls is None or trigger_del is None or getattr(trigger_del, "_smu_safe", False):
        return

    def __del__(self):  # noqa: N807
        try:
            self.unprime()
        except Exception:
            pass

    __del__._smu_safe = True
    trigger_cls.__del__ = __del__
