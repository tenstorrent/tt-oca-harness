# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP firmware-boot scoreboard.

Accumulates the console observables the boot test samples each cycle and, at
check_phase, asserts the positive evidence that the core booted and the firmware
ran:
  * the EL2 retired-instruction trace advanced across many distinct PCs (the core
    actually fetched and executed out of ICCM) -- sourced from the CPU trace
    monitor (env/sep_cpu_trace_monitor.py), which owns trace sampling;
  * the firmware console produced the expected banner; and
  * the firmware signaled PASS (not FAIL, and not "never finished").

o_cpu_run_ack is recorded for diagnosis but is not a hard
pass gate: with mpc_reset_run_req the core boots without the run handshake.
"""

from __future__ import annotations

from pyuvm import ConfigDB, uvm_component

_EXPECTED_LINE = "Hello from SEP OSS firmware!"
_MIN_DISTINCT_PCS = 16


class SepBootScoreboard(uvm_component):
    """Check PC advance, an optional banner, and PASS or no-PASS as configured."""

    def build_phase(self) -> None:
        self.cfg = ConfigDB().get(self, "", "cfg")
        # Trace evidence lives in the CPU trace monitor (built by sep_base_test
        # before any scoreboard, so the entry exists by the time this runs).
        # Fail loudly at check_phase if it is somehow absent: silently skipping
        # the PC-advance check would vacuously pass a core that never booted.
        try:
            self.trace_mon = ConfigDB().get(self, "", "cpu_trace_mon")
        except Exception:
            self.trace_mon = None
        self.run_ack_seen = False
        self.fw_done = False
        self.fw_pass = False
        self.console = bytearray()
        # Expected firmware console banner (positive evidence the right image
        # booted). A test that boots a different firmware sets this to its own
        # banner; "" skips the banner check (relying on PC-advance + fw_pass).
        self.expected_line = _EXPECTED_LINE
        # Whether this test expects the firmware to reach PASS. A negative boot
        # test -- one proving the ROM REFUSES a bad image -- sets this False,
        # which inverts the gate: a PASS becomes the failure. It does not merely
        # relax the check, because "no PASS magic" is also what a ROM that crashed
        # in its first instruction produces, and that must not pass a test
        # claiming the refusal was deliberate. The PC-advance check below stays in
        # force either way and is what separates the two.
        self.expect_fw_pass = True

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
        mon = self.trace_mon
        retired = mon.trace_count if mon is not None else 0
        distinct = len(mon.pcs) if mon is not None else 0
        self.logger.info(
            "boot: %d retired (%d distinct PCs), run_ack_seen=%s, fw_done=%s fw_pass=%s",
            retired,
            distinct,
            self.run_ack_seen,
            self.fw_done,
            self.fw_pass,
        )
        self.logger.info("firmware console: %r", console)

        errors: list[str] = []
        if mon is None:
            errors.append(
                "no CPU trace monitor attached (cpu_trace_mon missing from "
                "ConfigDB); PC-advance evidence unavailable"
            )
        elif distinct < _MIN_DISTINCT_PCS:
            errors.append(
                f"PC did not advance (only {distinct} distinct fetch PCs; "
                f"core likely never booted out of ICCM)"
            )
        if not self.expect_fw_pass:
            # The gate is on fw_pass, not on fw_done. A refused boot still
            # completes: rom_err_fail() writes the FAIL verdict to cold_scratch[0],
            # so fw_done asserts with fw_pass low. That is the ROM behaving
            # correctly, and requiring fw_done to stay low would fail a boot that
            # was refused exactly as intended. What must not happen is a PASS,
            # which only BL1 can produce and therefore only after the ROM handed
            # control to a payload it should have rejected.
            if self.fw_pass:
                errors.append(
                    "firmware signaled PASS on a boot that was required to be "
                    "refused: the ROM handed control to a payload it should have "
                    "rejected"
                )
        elif not self.fw_done:
            errors.append("firmware never signaled completion (no PASS/FAIL magic at 0x80000000)")
        elif not self.fw_pass:
            errors.append("firmware signaled FAIL (0xDEADBEEF)")
        if self.expected_line and self.expected_line not in console:
            errors.append(f"firmware console missing {self.expected_line!r}")

        assert not errors, "SEP boot scoreboard: " + "; ".join(errors)
        # Name only the checks that ran. expected_line is empty for tests that have
        # no banner (the ROM boot test clears it), and claiming "console banner seen"
        # there would report a comparison that never happened.
        done = ["core booted"]
        if self.expected_line:
            done.append("console banner seen")
        done.append("firmware PASS" if self.expect_fw_pass else "boot refused as required")
        self.logger.info("SEP boot PASS: %s", ", ".join(done))
