# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""KM key/policy vault: slot extent and SRAM write-lock.

no_cpu / +skip_fuse_sense / +km_rom_hex=km_rom_vault.parhex. RANDCFG.
Not ``rom_main``: KPV CTRL and SRAM_LOCK are on the KM CPU bus, and
seal stays on the parked command-set vehicle. The host posts a seed-
selected slot and SRAM region through the mailbox; the ROM walks slot
0, that slot, and slot 63, rejects a store past ``KM_KPV_SIZE``, then
locks the selected SRAM region and W1C-clears the violation / IRQ.
Result flags in KM SRAM word0 (the signed-off ``km_sram_word0_o`` probe).
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge
import pyuvm

from sep_base_test import sep_base_test
from seq_lib.sep_km_vault_seq import (
    FLAG_DROP,
    FLAG_EXTENT,
    FLAG_IRQ,
    FLAG_SLOT,
    FLAG_VIOL,
    FLAG_W1C,
    RESULT_MAGIC,
    SepKmVault,
    SepKmVaultCfg,
    km_vault_release,
)

_MAX_KM_CYCLES = 40_000


@pyuvm.test()
class sep_km_key_policy_vault_test(sep_base_test):
    """Legal KPV slot, out-of-window reject, SRAM write-lock W1C."""

    async def run_scenario(self) -> None:
        cfg = SepKmVaultCfg(self.random_seed())
        self.logger.info("km vault: %s", cfg.summary())
        await self.bring_up_no_cpu()
        await km_vault_release(self)
        vault = SepKmVault(self)
        await vault.post_cfg(cfg)

        dut = cocotb.top
        word = 0
        polled = 0
        for polled in range(1, _MAX_KM_CYCLES + 1):
            await RisingEdge(dut.clk_i)
            word = self.rd(dut.km_sram_word0_o)
            if (word & 0xFFFF_0000) == RESULT_MAGIC:
                break
        else:
            raise AssertionError(
                f"CHK-LIVE FAIL: KM SRAM word0=0x{word:08x} after {polled} "
                "cycles (no vault result magic)"
            )

        def _bit(flag: int, name: str) -> None:
            assert word & flag, (
                f"{name} FAIL: word0=0x{word:08x} missing 0x{flag:02x} "
                f"(slot={cfg.slot} region={cfg.region})"
            )

        _bit(FLAG_SLOT, "CHK-SLOT")
        self.logger.info(
            "CHK-SLOT PASS: CTRL lock_write stuck on slots 0, %d, 63", cfg.slot)
        _bit(FLAG_EXTENT, "CHK-EXTENT")
        self.logger.info(
            "CHK-EXTENT PASS: store 0x13108 set AXI_SLVERR or AXI_DECERR")
        _bit(FLAG_DROP, "CHK-DROP")
        self.logger.info(
            "CHK-DROP PASS: write to locked SRAM region %d dropped", cfg.region)
        _bit(FLAG_VIOL, "CHK-VIOL")
        self.logger.info(
            "CHK-VIOL PASS: SRAM_WRITE_LOCK_VIOLATION bit %d set", cfg.region)
        _bit(FLAG_IRQ, "CHK-IRQ")
        self.logger.info(
            "CHK-IRQ PASS: IRQ_STATUS.SRAM_WRITE_LOCK_ERR set")
        _bit(FLAG_W1C, "CHK-W1C")
        self.logger.info(
            "CHK-W1C PASS: violation and IRQ read back 0 after W1C")
        assert word == cfg.expect, (
            f"CHK-RANDCFG FAIL: word0=0x{word:08x} != 0x{cfg.expect:08x}"
        )
        self.logger.info(
            "CHK-RANDCFG PASS: slot=%d region=%d from seed %d word0=0x%08x",
            cfg.slot, cfg.region, cfg.seed, word)
