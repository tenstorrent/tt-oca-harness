# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence-level API over the slave driver with named checker evidence.

The slave side is reactive — the external host supplies all TCK/TMS/TDI
stimulus — so its sequence layer configures responses and judges what the
host wrote: backdoor register set/get, Update-DR inspection, and `CHK-*`
named evidence through the shared `OcahJtagChecker`. Tests drive the slave
VIP only through this class; missing operations get added here first.
"""

from __future__ import annotations

from .ocah_jtag_checker import OcahJtagChecker
from .ocah_jtag_slave_driver import OcahJtagSlaveDriver, OcahJtagSlaveUpdate
from .ocah_jtag_state import OcahJtagState, coerce_jtag_state

__all__ = ["OcahJtagSlaveSequence"]


class OcahJtagSlaveSequence:
    """Checked configuration/inspection operations over one slave driver."""

    def __init__(
        self,
        responder: OcahJtagSlaveDriver,
        checker: OcahJtagChecker | None = None,
    ) -> None:
        self.responder = responder
        self.checker = checker or OcahJtagChecker(
            name=f"{getattr(responder, 'name', 'OcahJtagSlave')}.seq_checker"
        )

    # ------------------------------------------------------------------
    # Response configuration.
    # ------------------------------------------------------------------

    def set_register(self, name: str, value: int) -> None:
        """Set the value a register presents on the next Capture-DR."""
        self.responder.set_register(name, value)

    def get_register(self, name: str) -> int:
        """Return a register's current stored value."""
        return self.responder.get_register(name)

    def device_state(self) -> OcahJtagState:
        """The device's current TAP controller state."""
        return self.responder.device_state()

    def active_instruction(self) -> int:
        """The instruction currently selecting the device's data register."""
        return self.responder.active_instruction()

    # ------------------------------------------------------------------
    # Device-state inspection (emit CHK-* named evidence).
    # ------------------------------------------------------------------

    def check_register(
        self,
        name: str,
        expected: int,
        *,
        check_id: str = "CHK-SLAVE-REG",
        context: str = "",
    ) -> bool:
        """Named check: a register currently holds the expected value.

        Independent of the Update-DR history: proves a value survived (or
        never changed) regardless of how many host scans ran meanwhile.
        """
        reg = self.responder.engine.device.reg(name)
        return self.checker.expect_equal(
            check_id,
            self.responder.get_register(name),
            int(expected) & ((1 << reg.width) - 1),
            context=f"reg={name} width={reg.width} {context}".strip(),
        )

    def check_state(
        self,
        expected_state,
        *,
        check_id: str = "CHK-SLAVE-STATE",
        context: str = "",
    ) -> bool:
        """Named check: the device's TAP controller is in the expected state."""
        expected = coerce_jtag_state(expected_state)
        observed = self.responder.device_state()
        return self.checker.expect_equal(
            check_id,
            int(observed),
            int(expected),
            context=f"state={observed.name} expected={expected.name} {context}".strip(),
        )

    # ------------------------------------------------------------------
    # Host-write inspection (emit CHK-* named evidence).
    # ------------------------------------------------------------------

    def updates(self) -> list[OcahJtagSlaveUpdate]:
        """All Update-DR latches recorded since the last clear."""
        return self.responder.get_updates()

    def clear_updates(self) -> None:
        self.responder.clear_updates()

    def check_last_update(
        self,
        reg_name: str,
        expected_value: int,
        *,
        check_id: str = "CHK-SLAVE-DR-UPDATE",
        context: str = "",
    ) -> bool:
        """Named check: the newest Update-DR latched the expected value."""
        updates = [u for u in self.updates() if u.reg_name == reg_name]
        if not updates:
            return self.checker.expect_true(
                check_id,
                False,
                context=f"reg={reg_name} no Update-DR observed {context}".strip(),
            )
        last = updates[-1]
        return self.checker.expect_equal(
            check_id,
            last.value,
            int(expected_value) & ((1 << last.width) - 1),
            context=f"reg={reg_name} width={last.width} {context}".strip(),
        )

    def check_update_count(
        self,
        expected: int,
        *,
        reg_name: str | None = None,
        check_id: str = "CHK-SLAVE-DR-UPDATE-COUNT",
        context: str = "",
    ) -> bool:
        """Named check: the host performed the expected number of writes."""
        updates = self.updates()
        if reg_name is not None:
            updates = [u for u in updates if u.reg_name == reg_name]
        return self.checker.expect_equal(
            check_id,
            len(updates),
            int(expected),
            context=f"reg={reg_name or 'any'} {context}".strip(),
        )

    def finalize(self) -> None:
        """Finalize retained findings and required named evidence."""
        self.checker.finalize()
