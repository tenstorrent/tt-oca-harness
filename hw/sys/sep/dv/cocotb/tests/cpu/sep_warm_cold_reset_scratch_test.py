# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A warm reset clears only SCRATCH_WARM, and a cold reset clears both scratch banks.

OCAH provenance: ``sep_clock_uvm_warm_reset_vs_cold_reset_test`` checks the
warm- and cold-reset scratch-bank partition.

The test proves the SEP System-block dual scratch banks honor their reset domains:

  * SCRATCH_WARM (0x1080_2080) is in the WARM domain: a warm reset (``wdt_rst_ni_i`` low)
    clears it.
  * SCRATCH_COLD (0x1080_2000) is in the COLD domain: only a cold reset (``rst_ni``) clears it.

Both the warm reset and the cold-reset re-init are covered, and the cold bank is read both over
the CPU-LSU AXI path and through the ``scratch_cold_probe_o`` tap.

Checks (exact values, so a stuck or X register fails):
  CHK-NONVAC      : pre-reset writes to SCRATCH_WARM[0]/SCRATCH_COLD[0] read back (probe too).
  CHK-WARM-RST    : a wdt_rst_ni_i low pulse drives sep_cpu_reset_n 1->0->1.
  CHK-BANK-ALIAS  : a distinct pattern in every register of both banks reads back at its own
                    index, so no index or bank aliases (probe word-by-word).
  CHK-WARM-CLEAR  : after the warm reset, SCRATCH_WARM[0] == reset default.
  CHK-WARM-RETAIN : after the warm reset, SCRATCH_COLD[0] keeps its pattern (probe too).
  CHK-WARM-BANK   : the warm reset clears every warm register and keeps every cold one.
  CHK-WARM-RECOVER: both banks accept a new pattern after the warm reset.
  CHK-COLD-ARM    : both banks hold distinct patterns just before the cold reset, so
                    CHK-COLD-BANK cannot pass on state the warm reset left.
  CHK-COLD-REINIT : after a cold reset (rst_ni resense), both banks == reset default (probe too).
  CHK-COLD-BANK   : the cold reset clears every register of both banks.

Cold-domain isolation is shown by CHK-WARM-CLEAR / CHK-WARM-RETAIN: dbg_sep_reset_n_o has no
fan-out from wdt_rst_ni_i, so a check that it stays 1 could not fail.

no_cpu / +skip_fuse_sense: the banks are reached over the CPU-LSU AXI splice and the reset
stimulus is the wdt_rst_ni_i / rst_ni primary inputs; no OTP data is read.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from sep_base_test import sep_base_test
from seq_lib.sep_scratch_reset_seq import (
    COLD_PATTERN,
    COLD_PATTERN2,
    COLD_PATTERNS,
    SCRATCH_COLD_0,
    SCRATCH_COLD_ADDRS,
    SCRATCH_N,
    SCRATCH_RESET_DEFAULT,
    SCRATCH_WARM_0,
    SCRATCH_WARM_ADDRS,
    WARM_PATTERN,
    WARM_PATTERN2,
    WARM_PATTERNS,
    SepScratchReset,
)

# Cycles to let the async reset settle after a wdt_rst_ni / rst_ni edge.
_SETTLE = 20


@pyuvm.test()
class sep_warm_cold_reset_scratch_test(sep_base_test):
    """Warm reset clears the warm scratch bank; the cold bank survives until a
    cold reset clears both."""

    def _scratch_cold_probe(self, idx: int) -> int:
        """Slice cold-bank word ``idx`` (32b) out of the 256b scratch_cold_probe_o.

        Only the slice being read is required to be known: CHK-COLD-REINIT and
        CHK-COLD-BANK expect zero there, so an X in it must raise. The other
        seven words may legitimately be X and are not demanded.
        """
        probe = self.rd_known(cocotb.top.scratch_cold_probe_o, 0xFFFF_FFFF << (32 * idx))
        return (probe >> (32 * idx)) & 0xFFFF_FFFF

    async def _check_reset_obs(self, sig, name: str, expected: int) -> None:
        """Assert a reset observable equals an exact value.

        ``rd`` raises on an X/Z bit, so neither ``== 0`` nor ``== 1`` can hold
        for an observable nothing drives.
        """
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

        # --- CHK-BANK-ALIAS: every index of both banks stores independently ---
        # One index cannot prove the address decode: a bank whose registers alias, or
        # whose warm and cold instances share storage, still passes an index-0 check.
        await self.scr.write_bank(SCRATCH_WARM_ADDRS, WARM_PATTERNS)
        await self.scr.write_bank(SCRATCH_COLD_ADDRS, COLD_PATTERNS)
        warm_bank = await self.scr.read_bank(SCRATCH_WARM_ADDRS)
        cold_bank = await self.scr.read_bank(SCRATCH_COLD_ADDRS)
        for idx in range(SCRATCH_N):
            assert warm_bank[idx] == WARM_PATTERNS[idx], (
                f"CHK-BANK-ALIAS SCRATCH_WARM[{idx}]=0x{warm_bank[idx]:08x} != "
                f"0x{WARM_PATTERNS[idx]:08x}"
            )
            assert cold_bank[idx] == COLD_PATTERNS[idx], (
                f"CHK-BANK-ALIAS SCRATCH_COLD[{idx}]=0x{cold_bank[idx]:08x} != "
                f"0x{COLD_PATTERNS[idx]:08x}"
            )
            probe_i = self._scratch_cold_probe(idx)
            assert probe_i == COLD_PATTERNS[idx], (
                f"CHK-BANK-ALIAS cold probe[{idx}]=0x{probe_i:08x} != 0x{COLD_PATTERNS[idx]:08x}"
            )
        self.logger.info(
            "CHK-BANK-ALIAS PASS: all %d warm and %d cold scratch registers hold their own "
            "pattern (probe agrees word-by-word) -- no index or bank aliasing",
            SCRATCH_N,
            SCRATCH_N,
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

        # --- CHK-WARM-BANK: the domain split holds for every index, not just 0 ---
        warm_bank_post = await self.scr.read_bank(SCRATCH_WARM_ADDRS)
        cold_bank_post = await self.scr.read_bank(SCRATCH_COLD_ADDRS)
        for idx in range(SCRATCH_N):
            assert warm_bank_post[idx] == SCRATCH_RESET_DEFAULT, (
                f"CHK-WARM-BANK SCRATCH_WARM[{idx}]=0x{warm_bank_post[idx]:08x} not cleared "
                f"by the warm reset"
            )
            assert cold_bank_post[idx] == COLD_PATTERNS[idx], (
                f"CHK-WARM-BANK SCRATCH_COLD[{idx}]=0x{cold_bank_post[idx]:08x} != "
                f"0x{COLD_PATTERNS[idx]:08x} (cold register lost its value to a warm reset)"
            )
            probe_i = self._scratch_cold_probe(idx)
            assert probe_i == COLD_PATTERNS[idx], (
                f"CHK-WARM-BANK cold probe[{idx}]=0x{probe_i:08x} != 0x{COLD_PATTERNS[idx]:08x}"
            )
        self.logger.info(
            "CHK-WARM-BANK PASS: the warm reset cleared all %d warm registers and left all "
            "%d cold registers at their patterns (probe agrees)",
            SCRATCH_N,
            SCRATCH_N,
        )

        # --- CHK-WARM-RECOVER: both banks writable again post-warm-reset ---
        await self.scr.write(SCRATCH_WARM_0, WARM_PATTERN2)
        await self.scr.write(SCRATCH_COLD_0, COLD_PATTERN2)
        warm_rec = await self.scr.read(SCRATCH_WARM_0)
        cold_rec = await self.scr.read(SCRATCH_COLD_0)
        assert warm_rec == WARM_PATTERN2, (
            f"CHK-WARM-RECOVER SCRATCH_WARM[0]=0x{warm_rec:08x} != 0x{WARM_PATTERN2:08x}"
        )
        assert cold_rec == COLD_PATTERN2, (
            f"CHK-WARM-RECOVER SCRATCH_COLD[0]=0x{cold_rec:08x} != 0x{COLD_PATTERN2:08x}"
        )
        self.logger.info(
            "CHK-WARM-RECOVER PASS: warm SCRATCH_WARM[0] re-written 0x%08x, cold "
            "SCRATCH_COLD[0] re-written 0x%08x after the warm reset",
            warm_rec,
            cold_rec,
        )

        # --- CHK-COLD-REINIT: a cold reset clears BOTH banks ---
        # State going in: SCRATCH_COLD[0]=COLD_PATTERN2, SCRATCH_WARM[0]=WARM_PATTERN2.
        # resense() pulses rst_ni low->high and re-gates fuse-sense; the clocks keep
        # running and the cocotb-driven idle defaults persist across the pulse. Both
        # banks' arst_n asserts on cold reset (cold: rst_ni; warm: rst_warm_ni,
        # which already includes rst_ni), so both must return to the reset default.
        # Re-arm BOTH banks first. The warm reset above cleared warm[1..7] and only
        # warm[0] was rewritten, so without this the cold-reset assertion on those
        # seven is satisfied by state the warm reset already produced and cannot
        # detect a cold reset that misses the warm bank.
        await self.scr.write_bank(SCRATCH_WARM_ADDRS, WARM_PATTERNS)
        await self.scr.write_bank(SCRATCH_COLD_ADDRS, COLD_PATTERNS)
        rearm_warm = await self.scr.read_bank(SCRATCH_WARM_ADDRS)
        rearm_cold = await self.scr.read_bank(SCRATCH_COLD_ADDRS)
        assert rearm_warm == list(WARM_PATTERNS) and rearm_cold == list(COLD_PATTERNS), (
            "CHK-COLD-BANK: both banks must hold their patterns before the cold "
            f"reset, got warm={[hex(v) for v in rearm_warm]} "
            f"cold={[hex(v) for v in rearm_cold]}"
        )
        self.logger.info(
            "CHK-COLD-ARM PASS: %d warm + %d cold registers armed before the cold "
            "reset, warm[0]=0x%08x warm[%d]=0x%08x cold[0]=0x%08x cold[%d]=0x%08x",
            SCRATCH_N,
            SCRATCH_N,
            rearm_warm[0],
            SCRATCH_N - 1,
            rearm_warm[SCRATCH_N - 1],
            rearm_cold[0],
            SCRATCH_N - 1,
            rearm_cold[SCRATCH_N - 1],
        )
        await self.scr.write(SCRATCH_WARM_0, WARM_PATTERN2)

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

        # --- CHK-COLD-BANK: the cold reset clears every register of both banks ---
        warm_bank_cold = await self.scr.read_bank(SCRATCH_WARM_ADDRS)
        cold_bank_cold = await self.scr.read_bank(SCRATCH_COLD_ADDRS)
        for idx in range(SCRATCH_N):
            assert cold_bank_cold[idx] == SCRATCH_RESET_DEFAULT, (
                f"CHK-COLD-BANK SCRATCH_COLD[{idx}]=0x{cold_bank_cold[idx]:08x} not cleared "
                f"by the cold reset"
            )
            assert warm_bank_cold[idx] == SCRATCH_RESET_DEFAULT, (
                f"CHK-COLD-BANK SCRATCH_WARM[{idx}]=0x{warm_bank_cold[idx]:08x} not cleared "
                f"by the cold reset"
            )
            probe_i = self._scratch_cold_probe(idx)
            assert probe_i == SCRATCH_RESET_DEFAULT, (
                f"CHK-COLD-BANK cold probe[{idx}]=0x{probe_i:08x} != reset default"
            )
        self.logger.info(
            "CHK-COLD-BANK PASS: the cold reset cleared all %d registers of both banks "
            "(probe agrees)",
            2 * SCRATCH_N,
        )

        self.logger.info(
            "warm/cold reset scratch PASS: warm/cold reset scratch-bank domain partition verified "
            "(nonvac / bank-alias / warm-rst / warm-clear / warm-retain / warm-bank / "
            "warm-recover / cold-reinit / cold-bank)"
        )
