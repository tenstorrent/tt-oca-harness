# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP firmware-boot scoreboard.

Accumulates the boot observables the boot test samples each cycle and, at
check_phase, asserts the positive evidence that the core booted and the firmware
ran:
  * the EL2 retired-instruction trace advanced across many distinct PCs (the core
    actually fetched and executed out of ICCM);
  * the firmware console produced the expected banner; and
  * the firmware signaled PASS (not FAIL, and not "never finished").

o_cpu_run_ack is recorded for diagnosis (the known watch-item) but is not a hard
pass gate: with mpc_reset_run_req the core boots without the run handshake.
"""

from __future__ import annotations

from pyuvm import ConfigDB, uvm_component

_EXPECTED_LINE = "Hello from SEP OSS firmware!"
_MIN_DISTINCT_PCS = 16


class SepBootScoreboard(uvm_component):
    def build_phase(self) -> None:
        self.cfg = ConfigDB().get(self, "", "cfg")
        self.trace_count = 0
        self.pcs: set[int] = set()
        self.last_pc = 0
        self.run_ack_seen = False
        self.fw_done = False
        self.fw_pass = False
        self.console = bytearray()
        # Expected firmware console banner (positive evidence the right image
        # booted). A test that boots a different firmware sets this to its own
        # banner; "" skips the banner check (relying on PC-advance + fw_pass).
        self.expected_line = _EXPECTED_LINE

    def note_trace(self, valid: int, addr: int) -> None:
        if valid:
            self.last_pc = addr & 0xFFFF_FFFF
            self.trace_count += 1
            self.pcs.add(self.last_pc)

    def note_run_ack(self, val: int) -> None:
        if val:
            self.run_ack_seen = True

    def note_char(self, byte: int) -> None:
        self.console.append(byte & 0xFF)

    def note_fw(self, done: bool, passed: int) -> None:
        if done:
            self.fw_done = True
            self.fw_pass = bool(passed)

    def console_text(self) -> str:
        return bytes(self.console).decode("ascii", "replace")

    def check_phase(self) -> None:
        console = self.console_text()
        self.logger.info(
            "boot: %d retired (%d distinct PCs), run_ack_seen=%s, fw_done=%s fw_pass=%s",
            self.trace_count,
            len(self.pcs),
            self.run_ack_seen,
            self.fw_done,
            self.fw_pass,
        )
        self.logger.info("firmware console: %r", console)

        errors: list[str] = []
        if len(self.pcs) < _MIN_DISTINCT_PCS:
            errors.append(
                f"PC did not advance (only {len(self.pcs)} distinct fetch PCs; "
                f"core likely never booted out of ICCM)"
            )
        if not self.fw_done:
            errors.append(
                "firmware never signaled completion (no PASS/FAIL magic at 0x80000000)"
            )
        elif not self.fw_pass:
            errors.append("firmware signaled FAIL (0xDEADBEEF)")
        if self.expected_line and self.expected_line not in console:
            errors.append(f"firmware console missing {self.expected_line!r}")

        assert not errors, "SEP boot scoreboard: " + "; ".join(errors)
        # Name only the checks that actually ran. expected_line is empty for tests
        # that have no banner (the ROM boot test clears it), and claiming "console
        # banner seen" there told an auditor a comparison had happened when none
        # had -- on a run whose console was in fact empty.
        done = ["core booted"]
        if self.expected_line:
            done.append("console banner seen")
        done.append("firmware PASS")
        self.logger.info("SEP boot PASS: %s", ", ".join(done))
