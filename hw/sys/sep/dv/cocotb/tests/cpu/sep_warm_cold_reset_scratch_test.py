# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP warm/cold reset scratch-bank retention (PyUVM).

OSS port of reference suite ``sep_clock_uvm_warm_reset_vs_cold_reset_test``.
Proves the SEP System-block dual scratch banks honor their reset domains:

  * SCRATCH_WARM (base 0x1080_2080) is in the WARM domain -- its register block is
    reset by ``rst_ni && rst_warm_ni`` (sep_system_csr.sv u_sep_scratch_reg_warm),
    where ``rst_warm_ni = sep_cpu_reset_n = sep_reset_n & wdt_rst_ni`` (sep.sv:816,
    sep_reset_ctrl.sv:59). A warm reset (wdt_rst_ni low) clears it.
  * SCRATCH_COLD (base 0x1080_2000) is in the COLD domain -- reset by ``rst_ni``
    only (u_sep_scratch_reg_cold). A warm reset does NOT clear it; only a cold
    reset (rst_ni) does.

Stronger than the reference ref: it adds the COLD-reset re-init half (reference suite only
warm-resets) and cross-checks the cold bank both FRONTDOOR (the CPU-LSU AXI
readback) and BACKDOOR (the ``scratch_cold_probe_o`` XMR tap), proving they agree.

Checks (each asserts an exact value, so a stuck/X register fails):
  CHK-NONVAC     : pre-reset AXI writes to SCRATCH_WARM[0]/SCRATCH_COLD[0] read
                   back the written patterns (the writes land + banks AXI-live).
                   Cold bank cross-checked via scratch_cold_probe_o.
  CHK-WARM-RST   : a wdt_rst_ni_i low pulse drives sep_cpu_reset_n 1->0->1.
                   Cold-domain isolation is CHK-WARM-CLEAR / CHK-WARM-RETAIN
                   (warm bank clears, cold bank retains) -- dbg_sep_reset_n_o has
                   no fan-out from wdt_rst_ni_i, so asserting it stays 1 cannot fail.
  CHK-WARM-CLEAR : after the warm reset, SCRATCH_WARM[0] == reset default 0x0.
  CHK-WARM-RETAIN: after the warm reset, SCRATCH_COLD[0] == its written pattern
                   (survives). Probe cross-check.
  CHK-WARM-RECOVER: SCRATCH_WARM[0] is writable again post-warm-reset.
  CHK-COLD-REINIT: after a cold reset (rst_ni resense), BOTH banks == reset
                   default (stronger than the reference suite). Probe cross-check on the cold bank.

no_cpu / +skip_fuse_sense (the scratch banks are reached over the CPU-LSU AXI
splice; the reset stimulus is the wdt_rst_ni_i / rst_ni primary inputs -- no OTP
data is read).
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from sep_base_test import sep_base_test
from seq_lib.sep_scratch_reset_seq import (
    COLD_PATTERN,
    SCRATCH_COLD_0,
    SCRATCH_RESET_DEFAULT,
    SCRATCH_WARM_0,
    WARM_PATTERN,
    WARM_PATTERN2,
    SepScratchReset,
)

# Cycles to let the async reset settle after a wdt_rst_ni / rst_ni edge.
_SETTLE = 20


@pyuvm.test()
class sep_warm_cold_reset_scratch_test(sep_base_test):
    """Warm reset clears the warm scratch bank; the cold bank survives until a
    cold reset clears both."""

    def _scratch_cold_probe(self, idx: int) -> int:
        """Slice cold-bank word ``idx`` (32b) out of the 256b scratch_cold_probe_o."""
        probe = self.rd(cocotb.top.scratch_cold_probe_o)
        return (probe >> (32 * idx)) & 0xFFFF_FFFF

    async def _check_reset_obs(self, sig, name: str, expected: int) -> None:
        """Assert a reset observable equals an exact value (X resolves to 0)."""
        val = self.rd(sig)
        if val != expected:
            raise AssertionError(f"{name}: expected {expected}, got {val}")
        self.logger.info("PASS: %s == %d", name, expected)

    async def run_scenario(self) -> None:
        dut = cocotb.top
        await self.bring_up_no_cpu()
        self.scr = SepScratchReset(self)

        # --- CHK-NONVAC: writes land + banks AXI-live ---
        await self.scr.write(SCRATCH_WARM_0, WARM_PATTERN)
        await self.scr.write(SCRATCH_COLD_0, COLD_PATTERN)
        warm_rb = await self.scr.read(SCRATCH_WARM_0)
        cold_rb = await self.scr.read(SCRATCH_COLD_0)
        assert warm_rb == WARM_PATTERN, (
            f"CHK-NONVAC warm write/readback 0x{warm_rb:08x} != 0x{WARM_PATTERN:08x}"
        )
        assert cold_rb == COLD_PATTERN, (
            f"CHK-NONVAC cold write/readback 0x{cold_rb:08x} != 0x{COLD_PATTERN:08x}"
        )
        probe0 = self._scratch_cold_probe(0)
        assert probe0 == COLD_PATTERN, (
            f"CHK-NONVAC cold probe 0x{probe0:08x} != 0x{COLD_PATTERN:08x}"
        )
        self.logger.info(
            "CHK-NONVAC PASS: SCRATCH_WARM[0]=0x%08x SCRATCH_COLD[0]=0x%08x (probe agrees)",
            warm_rb,
            cold_rb,
        )

        # --- CHK-WARM-RST: wdt_rst_ni pulse drives sep_cpu_reset_n 1->0->1 ---
        await self._check_reset_obs(
            dut.sep_cpu_reset_n_o, "CHK-WARM-RST baseline sep_cpu_reset_n", 1
        )
        dut.wdt_rst_ni_i.value = 0
        await ClockCycles(dut.clk_i, _SETTLE)
        await self._check_reset_obs(
            dut.sep_cpu_reset_n_o, "CHK-WARM-RST asserted sep_cpu_reset_n", 0
        )
        dut.wdt_rst_ni_i.value = 1
        await ClockCycles(dut.clk_i, _SETTLE)
        await self._check_reset_obs(
            dut.sep_cpu_reset_n_o, "CHK-WARM-RST released sep_cpu_reset_n", 1
        )
        self.logger.info("CHK-WARM-RST PASS: warm reset asserted and released sep_cpu_reset_n")

        # --- CHK-WARM-CLEAR: warm bank cleared by the warm reset ---
        warm_post = await self.scr.read(SCRATCH_WARM_0)
        assert warm_post == SCRATCH_RESET_DEFAULT, (
            f"CHK-WARM-CLEAR SCRATCH_WARM[0]=0x{warm_post:08x} != reset default "
            f"0x{SCRATCH_RESET_DEFAULT:08x}"
        )
        self.logger.info("CHK-WARM-CLEAR PASS: SCRATCH_WARM[0] cleared to 0x%08x", warm_post)

        # --- CHK-WARM-RETAIN: cold bank survives the warm reset ---
        cold_post = await self.scr.read(SCRATCH_COLD_0)
        assert cold_post == COLD_PATTERN, (
            f"CHK-WARM-RETAIN SCRATCH_COLD[0]=0x{cold_post:08x} != 0x{COLD_PATTERN:08x}"
        )
        probe_post = self._scratch_cold_probe(0)
        assert probe_post == COLD_PATTERN, (
            f"CHK-WARM-RETAIN cold probe 0x{probe_post:08x} != 0x{COLD_PATTERN:08x}"
        )
        self.logger.info(
            "CHK-WARM-RETAIN PASS: SCRATCH_COLD[0] retained 0x%08x (probe agrees)", cold_post
        )

        # --- CHK-WARM-RECOVER: warm bank writable again post-warm-reset ---
        await self.scr.write(SCRATCH_WARM_0, WARM_PATTERN2)
        warm_rec = await self.scr.read(SCRATCH_WARM_0)
        assert warm_rec == WARM_PATTERN2, (
            f"CHK-WARM-RECOVER SCRATCH_WARM[0]=0x{warm_rec:08x} != 0x{WARM_PATTERN2:08x}"
        )
        self.logger.info("CHK-WARM-RECOVER PASS: SCRATCH_WARM[0] re-written 0x%08x", warm_rec)

        # --- CHK-COLD-REINIT: a cold reset clears BOTH banks (stronger than the reference suite) ---
        # State going in: SCRATCH_COLD[0]=COLD_PATTERN, SCRATCH_WARM[0]=WARM_PATTERN2.
        # resense() pulses rst_ni low->high and re-gates fuse-sense; the clocks keep
        # running and the cocotb-driven idle defaults persist across the pulse. Both
        # banks' arst_n deasserts on rst_ni (cold: rst_ni; warm: rst_ni && rst_warm_ni),
        # so both must return to the reset default.
        await self.resense()
        cold_cold = await self.scr.read(SCRATCH_COLD_0)
        warm_cold = await self.scr.read(SCRATCH_WARM_0)
        assert cold_cold == SCRATCH_RESET_DEFAULT, (
            f"CHK-COLD-REINIT SCRATCH_COLD[0]=0x{cold_cold:08x} != reset default"
        )
        assert warm_cold == SCRATCH_RESET_DEFAULT, (
            f"CHK-COLD-REINIT SCRATCH_WARM[0]=0x{warm_cold:08x} != reset default"
        )
        probe_cold = self._scratch_cold_probe(0)
        assert probe_cold == SCRATCH_RESET_DEFAULT, (
            f"CHK-COLD-REINIT cold probe 0x{probe_cold:08x} != reset default"
        )
        self.logger.info(
            "CHK-COLD-REINIT PASS: both scratch banks reset to 0x%08x", SCRATCH_RESET_DEFAULT
        )

        self.logger.info(
            "warm/cold reset scratch PASS: warm/cold reset scratch-bank domain partition verified "
            "(nonvac / warm-rst / warm-clear / warm-retain / warm-recover / cold-reinit)"
        )
