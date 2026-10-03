# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""KM key/policy vault: slot extent, SRAM write-lock, and the KPV seal.

no_cpu / +skip_fuse_sense / +km_rom_hex=km_rom_vault.parhex. RANDCFG.
Not ``rom_main``: KPV CTRL and SRAM_LOCK are on the KM CPU bus. The seal
lives here rather than on the mailbox command set because no command
seals a slot -- over the mailbox an erase always frees, so the retire
path has no vehicle there. The host posts a seed-selected slot, SRAM
region and seal/free slot pair through the mailbox; the ROM walks slot
0, that slot, and slot 63, rejects a store past ``KM_KPV_SIZE``, locks
the selected SRAM region and W1C-clears the violation / IRQ, then runs
the seal contrast: the same erase retires a sealed slot and frees an
unsealed one.
Result flags in KM SRAM word0 (the ``km_sram_word0_o`` probe).
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import RisingEdge
from sep_base_test import sep_base_test
from seq_lib.sep_km_vault_seq import (
    FLAG_DROP,
    FLAG_ERASEDATA,
    FLAG_EXTENT,
    FLAG_FREE,
    FLAG_IRQ,
    FLAG_IRQSET,
    FLAG_LOCKUSE,
    FLAG_LOCKWR,
    FLAG_RETIRE,
    FLAG_RETSTICK,
    FLAG_SEAL,
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
            # The word can be unknown before the ROM's first store; the poll
            # tolerates that, and the graded word is re-read as fully known.
            word = self.rd(dut.km_sram_word0_o, allow_unknown=True)
            if (word >> 24) == RESULT_MAGIC:
                word = self.rd(dut.km_sram_word0_o)
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
            "CHK-SLOT PASS: CTRL lock_write stuck on endpoints 0 and 63 plus seed slot"
        )
        _bit(FLAG_LOCKWR, "CHK-LOCKWR")
        self.logger.info(
            "CHK-LOCKWR PASS: key-data write to write-locked slot %d raised AXI SLVERR",
            cfg.slot,
        )
        _bit(FLAG_LOCKUSE, "CHK-LOCKUSE")
        self.logger.info(
            "CHK-LOCKUSE PASS: slot %d with lock_write only read back 0xA11CE000 with "
            "AXI_SLVERR clear (control); after lock_use the same read raised SLVERR "
            "and returned zero",
            cfg.slot,
        )
        _bit(FLAG_EXTENT, "CHK-EXTENT")
        self.logger.info(
            "CHK-EXTENT PASS: store 0x13108 set AXI_SLVERR with AXI_DECERR clear "
            "(key_manager.rdl: unmapped offset inside a window answers SLVERR)"
        )
        _bit(FLAG_DROP, "CHK-DROP")
        self.logger.info("CHK-DROP PASS: locked SRAM write dropped (readback unchanged)")
        _bit(FLAG_VIOL, "CHK-VIOL")
        self.logger.info("CHK-VIOL PASS: SRAM_WRITE_LOCK_VIOLATION matching bit set")
        _bit(FLAG_IRQ, "CHK-IRQ")
        self.logger.info("CHK-IRQ PASS: IRQ_STATUS.SRAM_WRITE_LOCK_ERR set")
        _bit(FLAG_W1C, "CHK-W1C")
        self.logger.info("CHK-W1C PASS: violation and IRQ read back 0 after W1C")
        _bit(FLAG_SEAL, "CHK-SEAL")
        self.logger.info(
            "CHK-SEAL PASS: one CTRL write on slot %d reads back exactly seal|lock_write "
            "(lock_use and erase clear before the erase)",
            cfg.seal_slot,
        )
        _bit(FLAG_RETIRE, "CHK-RETIRE")
        self.logger.info(
            "CHK-RETIRE PASS: erasing sealed slot %d left it retired "
            "(lock_write held, lock_use gained)",
            cfg.seal_slot,
        )
        _bit(FLAG_RETSTICK, "CHK-RETSTICK")
        self.logger.info(
            "CHK-RETSTICK PASS: a second erase left slot %d retired, not released",
            cfg.seal_slot,
        )
        _bit(FLAG_FREE, "CHK-FREE")
        self.logger.info(
            "CHK-FREE PASS: erasing unsealed slot %d cleared CTRL entirely (reusable)",
            cfg.free_slot,
        )
        _bit(FLAG_ERASEDATA, "CHK-ERASEDATA")
        self.logger.info(
            "CHK-ERASEDATA PASS: the erase overwrote both preloaded key words in slot "
            "%d with differing values, so the fill ran and advanced",
            cfg.free_slot,
        )
        _bit(FLAG_IRQSET, "CHK-IRQSET")
        self.logger.info(
            "CHK-IRQSET PASS: IRQ_SET.DRBG_ERR_SET raised IRQ_STATUS.DRBG_ERR and W1C "
            "cleared it (interrupt plumbing only, not the DRBG fault source)"
        )
        assert word == cfg.expect, f"CHK-RANDCFG FAIL: word0=0x{word:08x} != 0x{cfg.expect:08x}"
        self.logger.info(
            "CHK-RANDCFG PASS: the ROM echoed a fold of the whole config word "
            "(slot=%d region=%d seal_slot=%d free_slot=%d, seed %d) word0=0x%08x",
            cfg.slot,
            cfg.region,
            cfg.seal_slot,
            cfg.free_slot,
            cfg.seed,
            word,
        )
