# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_dtp_bsr_extest_loopback_test - P4 EXTEST BSR scan loopback.

Loads IR=EXTEST, shifts compact 8-bit patterns through the TB scan_in<-scan_out
loopback, and checks TDO returns the pattern retimed by one TCK
(`(pattern << 1) & mask`): the zero-length chain feeds TDI through the DUT's
IEEE 1149.1 falling-edge TDO retimer, so observed bit i is pattern bit i-1 and
observed bit 0 is the retimer's scan-entry content (0, TDI held low during TAP
navigation). Also checks one-hot EXTEST decode.

STUB:DECLARED
  name: BSR_TB_SCAN_LOOPBACK
  site: tb_top jtag_bsr_host_scan_in_i <- jtag_bsr_host_scan_out_o
  length: DTP_BSR_MODEL_LEN (compact 8-bit model)
  scope: TB EXTEST DR path only — NOT LIVE pad BSR / SEP STAP proof
  real-path: needs a pad-BSR / STAP model

Patterns whose retimed expectation is all-zero are forbidden: the JTAG driver's
_logic_int maps X/Z TDO to 0, which would make an all-zero expect can't-fail.
Nonzero expectations remain sensitive to stuck-0 / unresolved TDO.

All TAP driving goes through the VIP sequence API (OcahJtagMasterSequence); the raw
driver built by make_smu_jtag_tap is wrapped, never called directly here.
"""

from __future__ import annotations

import random

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from ocah_jtag_vip import OcahJtagMasterSequence
from seq_lib.smu_jtag_helpers import (
    DTP_BSR_MODEL_LEN,
    DTP_EXTEST_DECODED_BIT,
    DTP_IR_EXTEST,
    make_smu_jtag_tap,
)
from smu_base_test import smu_base_test

# Nonzero-only: VIP X/Z->0 would false-pass an all-zero expect.
_PATTERNS = (0xFF, 0xA5, 0x5A, 0xC3, 0x3C, 0x01)


def _sample(signal, name: str) -> int:
    val = signal.value
    if isinstance(val, int):
        # An enum-typed handle (jtag_ptap_inst_decoded) reads back as a plain int on VCS.
        return val
    if not val.is_resolvable:
        raise AssertionError(f"X/Z sample on {name}: {val}")
    return int(val)


@pyuvm.test()
class smu_dtp_bsr_extest_loopback_test(smu_base_test):
    """EXTEST DR loopback + instruction decode."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        dut = cocotb.top
        sb = self.env.scoreboard

        seq = OcahJtagMasterSequence(make_smu_jtag_tap(dut, self.cfg.jtag_period_ns))
        await self.cfg.reset_done.wait()
        await seq.reset_to_tlr()
        await ClockCycles(dut.clk_smu_i, 8)

        self.logger.info(
            "STUB:DECLARED BSR_TB_SCAN_LOOPBACK "
            "site=tb_top.scan_in<-scan_out len=%d "
            "scope=TB_EXTEST_DR_only (not LIVE pad BSR)",
            DTP_BSR_MODEL_LEN,
        )

        await seq.shift_ir(DTP_IR_EXTEST)
        await ClockCycles(dut.clk_smu_i, 4)

        decoded = _sample(dut.jtag_ptap_inst_decoded, "jtag_ptap_inst_decoded")
        expect_onehot = 1 << DTP_EXTEST_DECODED_BIT
        sb.expect_eq(
            "EXTEST decode one-hot",
            decoded,
            expect_onehot,
            evidence="BSR_EXTEST_DECODE",
        )

        mask = (1 << DTP_BSR_MODEL_LEN) - 1
        # Seeded random patterns on top of the directed set. Salted so the
        # draws stay decoupled from the base test's timing randomization.
        seed = self.random_seed()
        rng = random.Random(seed ^ 0x0B52)
        randoms: list[int] = []
        while len(randoms) < 4:
            pattern = rng.getrandbits(DTP_BSR_MODEL_LEN) & mask
            if (pattern << 1) & mask and pattern not in randoms:
                randoms.append(pattern)
        self.logger.info(
            "BSR_EXTEST patterns: directed=%s random=%s (RANDOM_SEED=%d)",
            [hex(p) for p in _PATTERNS],
            [hex(p) for p in randoms],
            seed,
        )
        for pattern in (*_PATTERNS, *randoms):
            expected = (pattern << 1) & mask  # one-TCK TDO retiming delay
            if expected == 0:
                raise AssertionError("all-zero expectation forbidden (X/Z->0 can't-fail)")
            captured = await seq.shift_dr(
                pattern & mask,
                DTP_BSR_MODEL_LEN,
                back_to_rti=True,
            )
            # Fail-closed observation of TDO pin after VIP capture.
            _sample(dut.jtag_tdo, "jtag_tdo")
            sb.expect_eq(
                f"BSR_EXTEST_TDO_MATCH pat=0x{pattern:02x}",
                int(captured) & mask,
                expected,
                evidence="BSR_EXTEST_TDO_MATCH",
            )

        self.logger.info(
            "smu_dtp_bsr_extest_loopback_test: BSR_EXTEST_TDO_MATCH %d patterns",
            len(_PATTERNS),
        )
