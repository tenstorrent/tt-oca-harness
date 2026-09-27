# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP UVM scoreboard.

Subscribes to the AXI agent's completed-transaction stream and checks:
  * every access reports an OKAY AXI response (no SLVERR/DECERR);
  * reads carrying an ``expected`` value return it exactly (value-specific
    positive evidence, not a "no-X" cross-check);
  * a negative-path probe (``item.expect_error``) is the inverse: it must return a
    real error response (the access is meant to be blocked/undecoded) -- NOT OKAY
    and NOT a timeout/wedge. The sequence/test asserts the exact error code
    (DECERR); the scoreboard guards against a probe silently succeeding (OKAY) or
    passing vacuously on a wedge (timed_out).
"""

from __future__ import annotations

from pyuvm import ConfigDB, uvm_subscriber

from .sep_axi_agent import SepAxiItem, SepAxiOp


class SepScoreboard(uvm_subscriber):
    def build_phase(self) -> None:
        self.cfg = ConfigDB().get(self, "", "cfg")
        self.errors: list[str] = []
        self.checks = 0  # transactions observed
        self.value_checks = 0  # reads whose expected value was verified
        self.expected_reads = 0  # reads that carried an expected value
        self.error_checks = 0  # negative-path probes that returned a non-OKAY (as expected)

    def _fail(self, msg: str) -> None:
        self.errors.append(msg)
        self.logger.error("SCOREBOARD FAIL: %s", msg)

    def write(self, item: SepAxiItem) -> None:
        self.checks += 1
        if item.expect_error:
            # Negative-path probe: a real non-OKAY response (e.g. DECERR) is the
            # expected outcome. Two ways it can pass vacuously, both rejected here:
            #   * OKAY  -> the access was NOT blocked/undecoded (a real fault);
            #   * timed_out -> the access WEDGED with no response. A blocked access
            #     must return an error response, not hang; a timeout is not evidence
            #     of enforcement, so the check holds even when expect_error is paired
            #     with allow_timeout.
            # The sequence/test asserts the exact error code separately.
            if item.timed_out:
                self._fail(
                    f"{item.op.value} @ 0x{item.addr:08x} marked expect_error but "
                    f"TIMED OUT (no response) -- a blocked access must return an error "
                    f"(e.g. DECERR), not wedge"
                )
            elif item.resp_ok:
                self._fail(
                    f"{item.op.value} @ 0x{item.addr:08x} marked expect_error but "
                    f"returned OKAY (access was not blocked)"
                )
            else:
                self.error_checks += 1
                self.logger.info(
                    "expected-error %s @ 0x%08x returned resp=%d (as expected)",
                    item.op.value,
                    item.addr,
                    item.resp_code,
                )
            return
        if not item.resp_ok:
            if item.op is SepAxiOp.WRITE and item.allow_unverified_write_resp:
                self.logger.info(
                    "write @ 0x%08x response not classified OKAY; sequence verifies by readback",
                    item.addr,
                )
                return
            self._fail(
                f"{item.op.value} @ 0x{item.addr:08x} returned a non-OKAY or "
                f"unverifiable AXI response"
            )
            return
        if item.op is SepAxiOp.READ and item.expected is not None:
            self.expected_reads += 1
            mask = (1 << (item.length * 8)) - 1
            got = item.rdata & mask
            exp = item.expected & mask
            width = item.length * 2
            if got != exp:
                self._fail(
                    f"read 0x{item.addr:08x} = 0x{got:0{width}x} != expected 0x{exp:0{width}x}"
                )
            else:
                self.value_checks += 1
                self.logger.info("read check OK @ 0x%08x = 0x%0*x", item.addr, width, got)

    def check_phase(self) -> None:
        assert not self.errors, f"SEP scoreboard found {len(self.errors)} error(s): " + "; ".join(
            self.errors
        )
        # Positive evidence: a clean run must have actually observed
        # transactions, not passed vacuously on zero activity.
        assert self.checks > 0, "SEP scoreboard saw no AXI transactions (no positive evidence)"
        if self.expected_reads:
            assert self.value_checks > 0, (
                "SEP scoreboard saw reads that carried an expected value but verified none"
            )
        self.logger.info(
            "SEP scoreboard: %d checks (%d value-verified, %d expected-error), 0 errors",
            self.checks,
            self.value_checks,
            self.error_checks,
        )
