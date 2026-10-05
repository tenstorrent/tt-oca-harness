# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""UART0 SCR R/W without LCR/MCR/ECR side-effects; idle LSR has no DR/OE/PE/FE/BI."""

from __future__ import annotations

from pathlib import Path

import cocotb
from cocotb.triggers import Timer

from .smc_addr_map import UART_CG_EN, _field_mask, smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq

_REPO = Path(__file__).resolve().parents[6]
_UART_H = _REPO / "hw" / "ip" / "uart" / "uart_16550" / "regs" / "gen" / "c" / "uart_16550_main.h"
_UART_WO_H = (
    _REPO / "hw" / "ip" / "uart" / "uart_16550" / "regs" / "gen" / "c" / "uart_16550_main_wo.h"
)
_UART_CTRL_H = (
    _REPO
    / "hw"
    / "ip"
    / "uart"
    / "uart_log_engine_wrap"
    / "regs"
    / "gen"
    / "c"
    / "uart_log_engine_ctrl.h"
)

UART_CTRL = smc_indexed_addr(
    "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LOG_ENGINE_CTRL_CTRL_BASE_ADDR",
    0,
)
UART_RBR = smc_indexed_addr("SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_RBR_BASE_ADDR", 0)
UART_IER = smc_indexed_addr("SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IER_BASE_ADDR", 0)
UART_IIR = smc_indexed_addr("SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IIR_BASE_ADDR", 0)
UART_LCR = smc_indexed_addr("SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LCR_BASE_ADDR", 0)
UART_MCR = smc_indexed_addr("SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_MCR_BASE_ADDR", 0)
UART_LSR = smc_indexed_addr("SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LSR_BASE_ADDR", 0)
UART_SCR = smc_indexed_addr("SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_SCR_BASE_ADDR", 0)
UART_ECR = smc_indexed_addr("SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ECR_BASE_ADDR", 0)
CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")

UART_EN = _field_mask(_UART_CTRL_H, "UART_LOG_ENGINE_CTRL__CTRL__UART_EN_bm")
FCR_FIFO_ENABLE = _field_mask(_UART_WO_H, "UART_16550_MAIN_WO__FCR__FIFO_ENABLE_bm")
IER_ERBFI = _field_mask(_UART_H, "UART_16550_MAIN__IER__ERBFI_bm")
IER_ETBEI = _field_mask(_UART_H, "UART_16550_MAIN__IER__ETBEI_bm")
IER_ELSI = _field_mask(_UART_H, "UART_16550_MAIN__IER__ELSI_bm")
IER_EDSSI = _field_mask(_UART_H, "UART_16550_MAIN__IER__EDSSI_bm")
LCR_DLAB = _field_mask(_UART_H, "UART_16550_MAIN__LCR__DLAB_bm")
LCR_WLS = _field_mask(_UART_H, "UART_16550_MAIN__LCR__WLS_bm")
MCR_LOOP = _field_mask(_UART_H, "UART_16550_MAIN__MCR__LOOP_bm")
MCR_RTS = _field_mask(_UART_H, "UART_16550_MAIN__MCR__RTS_bm")
LSR_DR = _field_mask(_UART_H, "UART_16550_MAIN__LSR__DR_bm")
LSR_OE = _field_mask(_UART_H, "UART_16550_MAIN__LSR__OE_bm")
LSR_PE = _field_mask(_UART_H, "UART_16550_MAIN__LSR__PE_bm")
LSR_FE = _field_mask(_UART_H, "UART_16550_MAIN__LSR__FE_bm")
LSR_BI = _field_mask(_UART_H, "UART_16550_MAIN__LSR__BI_bm")
SCR_SCR = _field_mask(_UART_H, "UART_16550_MAIN__SCR__SCR_bm")

_IER_BASIC = IER_ERBFI | IER_ETBEI | IER_ELSI | IER_EDSSI
_SCR_PATTERNS = (0x00, 0xFF, 0xA5, 0x5A, 0x01, 0x02, 0x04, 0x08)
# Only DR: `_positive_dr_then_idle` is the same-run control that shows DR going
# 1 then 0, so a stuck-at-0 DR fails. Nothing in this sequence can drive
# OE/PE/FE/BI to 1, so an idle check on them would be an unbacked negative that
# a tied-off bit passes; smc_uart_error_conditions_test drives each of them and
# back.
_LSR_IDLE_CHECKED = LSR_DR


class smc_uart_extremes_misc_test_seq(SmcCsrSeq):
    """UART0 SCR R/W + idle LSR quiet check."""

    def __init__(self, name: str = "smc_uart_extremes_misc_test_seq") -> None:
        super().__init__(name)
        self.scr_ok: bool = False
        self.idle_ok: bool = False

    async def _init_loopback(self) -> None:
        await self.csr_write("UART_EN", UART_CTRL, UART_EN)
        await self.csr_write("LCR_DLAB", UART_LCR, LCR_WLS | LCR_DLAB)
        await self.csr_write("DLL", UART_RBR, 1)
        await self.csr_write("DLH", UART_IER, 0)
        await self.csr_write("LCR_8N1", UART_LCR, LCR_WLS)
        await self.csr_write("MCR_LOOP", UART_MCR, MCR_LOOP | MCR_RTS)
        await self.csr_write("IER", UART_IER, _IER_BASIC)
        await self.csr_write("FCR", UART_IIR, FCR_FIFO_ENABLE)

    async def _test_scr(self) -> None:
        lcr_b = await self.csr_read("LCR_PRE", UART_LCR)
        mcr_b = await self.csr_read("MCR_PRE", UART_MCR)
        ecr_b = await self.csr_read("ECR_PRE", UART_ECR)
        for i, pat in enumerate(_SCR_PATTERNS):
            await self.csr_write(f"SCR_W_{i}", UART_SCR, pat & SCR_SCR)
            rd = await self.csr_read(f"SCR_R_{i}", UART_SCR)
            if (int(rd) & SCR_SCR) != pat:
                raise AssertionError(
                    f"SCR mismatch wrote 0x{pat:02x} read 0x{int(rd) & SCR_SCR:02x}"
                )
        lcr_a = await self.csr_read("LCR_POST", UART_LCR)
        mcr_a = await self.csr_read("MCR_POST", UART_MCR)
        ecr_a = await self.csr_read("ECR_POST", UART_ECR)
        if lcr_a != lcr_b:
            raise AssertionError(f"LCR changed after SCR 0x{lcr_b:08x}->0x{lcr_a:08x}")
        if mcr_a != mcr_b:
            raise AssertionError(f"MCR changed after SCR 0x{mcr_b:08x}->0x{mcr_a:08x}")
        if ecr_a != ecr_b:
            raise AssertionError(f"ECR changed after SCR 0x{ecr_b:08x}->0x{ecr_a:08x}")
        cocotb.log.info("CHK-UART-EXT-SCR: patterns=%d side-effect-free", len(_SCR_PATTERNS))

    async def _positive_dr_then_idle(self) -> None:
        # Positive control: loopback must set LSR.DR before the quiet claim.
        await self.csr_write("POS_THR", UART_RBR, 0x5A)
        lsr = 0
        for _ in range(512):
            lsr = await self.csr_read("POS_DR_WAIT", UART_LSR)
            if lsr & LSR_DR:
                break
            await Timer(100, unit="ns")
        else:
            raise AssertionError(f"positive-control LSR.DR never set LSR=0x{lsr:08x}")
        cocotb.log.info("CHK-UART-EXT-DR-POS: LSR.DR asserted after loopback TX")
        await self.csr_read("POS_RBR_POP", UART_RBR)
        for _ in range(64):
            lsr = await self.csr_read("POS_DRAIN", UART_LSR)
            if not (lsr & LSR_DR):
                break
            await self.csr_read("POS_DRAIN_RBR", UART_RBR)
            await Timer(100, unit="ns")
        else:
            raise AssertionError(f"LSR.DR sticky after RBR drain LSR=0x{lsr:08x}")

        await self.csr_write("SCR_MAGIC", UART_SCR, 0xA1)
        for i in range(256):
            lsr = await self.csr_read(f"IDLE_LSR_{i}", UART_LSR)
            if lsr & _LSR_IDLE_CHECKED:
                raise AssertionError(f"idle LSR.DR set LSR=0x{lsr:08x} iter={i}")
            await Timer(100, unit="ns")
        cocotb.log.info(
            "CHK-UART-EXT-IDLE: LSR.DR stayed 0 over the idle window after the "
            "DR+ drain; OE/PE/FE/BI are not claimed here (no control for them "
            "in this sequence)"
        )

    async def body(self) -> None:
        cg = await self.csr_read("UART_CG", CLOCK_GATE_CONTROL)
        await self.csr_write("UART_UNGATE", CLOCK_GATE_CONTROL, cg & ~UART_CG_EN)
        await self._init_loopback()
        await self._test_scr()
        self.scr_ok = True
        await self._positive_dr_then_idle()
        self.idle_ok = True
        cocotb.log.info("CHK-UART-EXT-BASIC: scr=%s idle=%s", self.scr_ok, self.idle_ok)
