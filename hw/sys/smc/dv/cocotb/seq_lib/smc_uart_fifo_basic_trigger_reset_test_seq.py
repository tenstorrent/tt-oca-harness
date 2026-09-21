# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""UART0 MCR.LOOP: RCVR trigger then RX/TX FIFO reset clears LSR.DR / THRE."""

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
UART_ECR = smc_indexed_addr("SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ECR_BASE_ADDR", 0)
CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")

UART_EN = _field_mask(_UART_CTRL_H, "UART_LOG_ENGINE_CTRL__CTRL__UART_EN_bm")
FCR_FIFO_ENABLE = _field_mask(_UART_WO_H, "UART_16550_MAIN_WO__FCR__FIFO_ENABLE_bm")
FCR_RCVR_FIFO_RESET = _field_mask(_UART_WO_H, "UART_16550_MAIN_WO__FCR__RCVR_FIFO_RESET_bm")
FCR_XMIT_FIFO_RESET = _field_mask(_UART_WO_H, "UART_16550_MAIN_WO__FCR__XMIT_FIFO_RESET_bm")
FCR_RCVR_TRIGGER_BP = _field_mask(_UART_WO_H, "UART_16550_MAIN_WO__FCR__RCVR_TRIGGER_bp")
ECR_RCVR_TRIGGER_MS2B_BP = _field_mask(_UART_H, "UART_16550_MAIN__ECR__RCVR_TRIGGER_MS2B_bp")
IIR_INTERRUPT_PENDING = _field_mask(_UART_H, "UART_16550_MAIN__IIR__INTERRUPT_PENDING_bm")
IIR_INTERRUPT_ID = _field_mask(_UART_H, "UART_16550_MAIN__IIR__INTERRUPT_ID_bm")
IIR_INTERRUPT_ID_BP = _field_mask(_UART_H, "UART_16550_MAIN__IIR__INTERRUPT_ID_bp")
IER_ERBFI = _field_mask(_UART_H, "UART_16550_MAIN__IER__ERBFI_bm")
LCR_DLAB = _field_mask(_UART_H, "UART_16550_MAIN__LCR__DLAB_bm")
LCR_WLS = _field_mask(_UART_H, "UART_16550_MAIN__LCR__WLS_bm")
MCR_LOOP = _field_mask(_UART_H, "UART_16550_MAIN__MCR__LOOP_bm")
MCR_RTS = _field_mask(_UART_H, "UART_16550_MAIN__MCR__RTS_bm")
LSR_DR = _field_mask(_UART_H, "UART_16550_MAIN__LSR__DR_bm")
LSR_THRE = _field_mask(_UART_H, "UART_16550_MAIN__LSR__THRE_bm")
LSR_TEMT = _field_mask(_UART_H, "UART_16550_MAIN__LSR__TEMT_bm")

# 16550 IntrID encodings, from uart_16550_main.rdl IIR.INTERRUPT_ID (the RDL
# lists every encoding with its priority; RTL is not the source here).
#   0x2 - Received Data Ready Interrupt   (priority 3)
#   0x6 - Reception Timeout Interrupt     (priority 2)
_INTR_ID_RDR = 0x2
_INTR_ID_CHAR_TIMEOUT = 0x6
# FCR.RCVR_TRIGGER encodings, from uart_16550_main_wo.rdl FCR.RCVR_TRIGGER:
#   0x0 - 1 character, 0x1 - 4 characters, 0x2 - 8, 0x3 - 14.
_TRIG_1B = 0
_TRIG_4B = 1
_TRIG_32B = 4
_TRIG_LEVEL_CHARS = {_TRIG_1B: 1, _TRIG_4B: 4, _TRIG_32B: 32}
_ABOVE_FIFO_DEPTH_TRIGGERS = {
    5: 64,
    6: 128,
    7: 256,
    8: 512,
    9: 1024,
    10: 2048,
    11: 4096,
}

# Baud divisor used by the TX-FIFO-reset leg to hold data in the transmitter
# long enough for LSR.THRE to be sampled at 0. Derivation:
# uart_16550/doc/interface.adoc ("Serial Interface Timing") states the serial
# rate comes from the divisor latches with **16x oversampling**, so one 8N1
# character (start + 8 data + 1 stop = 10 bit times) occupies
# 16 * 10 * DLL uart clocks. The fill loop below issues one THR write plus one
# LSR read per iteration over the SEP_IN AXI CSR path, which costs on the order
# of 10^2 clocks; a divisor of 32 makes a character 5120 clocks, i.e. an order
# of magnitude longer than one sample, so the transmitter is guaranteed to still
# be busy when LSR is read. The loop remains event-based (it polls LSR.THRE) and
# bounded, so expiry FAILS rather than being masked by a longer delay.
_UART_OVERSAMPLE = 16
_CHAR_BITS_8N1 = 10
_DLL_SLOW = 32
_SLOW_CHAR_CLOCKS = _UART_OVERSAMPLE * _CHAR_BITS_8N1 * _DLL_SLOW
# Samples of IIR required to show NO RCVR-data-available while the RX FIFO sits
# below the programmed trigger level.
_PRE_HOLD_SAMPLES = 4


def _iir_id(iir: int) -> int:
    return (int(iir) & IIR_INTERRUPT_ID) >> IIR_INTERRUPT_ID_BP


def _iir_pending(iir: int) -> bool:
    # Active-low: 0 means an interrupt is pending.
    return (int(iir) & IIR_INTERRUPT_PENDING) == 0


class smc_uart_fifo_basic_trigger_reset_test_seq(SmcCsrSeq):
    """UART0 loopback FIFO trigger + reset proof."""

    def __init__(self, name: str = "smc_uart_fifo_basic_trigger_reset_test_seq") -> None:
        super().__init__(name)
        self.trigger_1b_ok: bool = False
        self.trigger_4b_ok: bool = False
        self.trigger_32b_ok: bool = False
        self.above_depth_ok: bool = False
        self.reset_ok: bool = False
        # label -> (pre-threshold IIR id, at-threshold IIR id, below-level IIR
        # id). Measured values the test module gates on, so a cell that ran but
        # observed the wrong interrupt fails the testcase, not just the token.
        self.trigger_ids: dict[str, tuple[int, int, int]] = {}

    async def _write_fcr(self, value: int) -> None:
        # FCR is the write-only alias of the IIR address in the 16550 map, so the
        # label names BOTH the register written and the symbol addressed; a log
        # line reading only "FCR" would trace to no symbol in this file.
        await self.csr_write("FCR_via_UART_IIR", UART_IIR, value)

    async def _fifo_set_trigger(self, trigger_cfg: int) -> None:
        await self.csr_write(
            "ECR_RCVR_TRIGGER_MS2B",
            UART_ECR,
            ((trigger_cfg >> 2) & 0x3) << ECR_RCVR_TRIGGER_MS2B_BP,
        )
        fcr = FCR_FIFO_ENABLE | ((trigger_cfg & 0x3) << FCR_RCVR_TRIGGER_BP)
        await self._write_fcr(fcr)

    async def _fifo_reset(self, *, rx: bool, tx: bool) -> None:
        fcr = FCR_FIFO_ENABLE
        if rx:
            fcr |= FCR_RCVR_FIFO_RESET
        if tx:
            fcr |= FCR_XMIT_FIFO_RESET
        await self._write_fcr(fcr)

    async def _init_loopback(self) -> None:
        await self.csr_write("UART_EN", UART_CTRL, UART_EN)
        # Divisor=1 (fast loopback), 8N1, LOOP+RTS, ERBFI.
        await self.csr_write("LCR_DLAB", UART_LCR, LCR_WLS | LCR_DLAB)
        # DLL/DLH are the DLAB=1 aliases of the RBR/IER addresses; the labels
        # name both so every register name in the kept log resolves to the
        # symbol that addressed it.
        await self.csr_write("DLL_via_UART_RBR", UART_RBR, 1)
        await self.csr_write("DLH_via_UART_IER", UART_IER, 0)
        await self.csr_write("LCR_8N1", UART_LCR, LCR_WLS)
        await self.csr_write("MCR_LOOP", UART_MCR, MCR_LOOP | MCR_RTS)
        await self.csr_write("IER_ERBFI", UART_IER, IER_ERBFI)

    async def _wait_iir_id(self, label: str, expect_id: int, iters: int = 256) -> int:
        iir = 0
        for _ in range(iters):
            iir = await self.csr_read(f"{label}_IIR", UART_IIR)
            if _iir_pending(iir) and _iir_id(iir) == expect_id:
                return iir
            await Timer(1, unit="us")
        raise AssertionError(
            f"{label}: IIR id=0x{expect_id:x} not seen last=0x{iir:08x} "
            f"pending={_iir_pending(iir)} id=0x{_iir_id(iir):x}"
        )

    async def _wait_lsr_bit(self, label: str, mask: int, want_set: bool, iters: int = 512) -> int:
        lsr = 0
        for _ in range(iters):
            lsr = await self.csr_read(f"{label}_LSR", UART_LSR)
            if bool(lsr & mask) == want_set:
                return lsr
            await Timer(1, unit="us")
        raise AssertionError(
            f"{label}: LSR bit 0x{mask:02x} never reached {int(want_set)} (last LSR=0x{lsr:08x})"
        )

    async def _wait_iir_not_id(self, label: str, forbidden_id: int, iters: int = 256) -> int:
        iir = 0
        for _ in range(iters):
            iir = await self.csr_read(f"{label}_IIR", UART_IIR)
            if not (_iir_pending(iir) and _iir_id(iir) == forbidden_id):
                return iir
            await Timer(1, unit="us")
        raise AssertionError(
            f"{label}: IIR id=0x{forbidden_id:x} still pending after "
            f"{iters} samples (last=0x{iir:08x})"
        )

    async def _test_rx_trigger(self, label: str, trig_cfg: int) -> None:
        """Prove the programmed FCR.RCVR_TRIGGER level, not a character timeout.

        The level is only observable at its boundary, so all three legs are run
        against the SAME programmed encoding:

        * ``depth - 1`` characters in the RX FIFO must NOT raise
          RECEIVED_DATA_READY (IIR id 0x2), held over several samples;
        * the ``depth``-th character must raise it within a bounded wait -- a
          newly received character also clears any pending Reception Timeout, so
          the higher-priority 0x6 cannot mask this;
        * popping one character back below the level must clear it again.

        With ``FCR.RCVR_TRIGGER`` tied off, or programmed to the other encoding,
        one of the three legs fails: the 1-character cell would not see 0x2 after
        its single character, and the 4-character cell would see 0x2 while only
        3 characters are queued.
        """
        depth = _TRIG_LEVEL_CHARS[trig_cfg]
        await self._fifo_reset(rx=True, tx=True)
        await self._fifo_set_trigger(trig_cfg)
        await self.csr_read(f"{label}_LSR_CLR", UART_LSR)
        await self.csr_read(f"{label}_IIR_CLR", UART_IIR)

        # Pre-threshold fill. LSR.TEMT means the transmit holding register AND
        # the shift register are empty, so under MCR.LOOP every character written
        # here has already been received: the RX FIFO holds exactly depth-1.
        for i in range(1, depth):
            await self.csr_write(f"{label}_THR_PRE_{i}", UART_RBR, 0x30 + i)
        await self._wait_lsr_bit(f"{label}_PRE_TEMT", LSR_TEMT, True)
        pre_iir = await self.csr_read(f"{label}_IIR_PRE", UART_IIR)
        for sample in range(_PRE_HOLD_SAMPLES):
            held = await self.csr_read(f"{label}_IIR_PRE_HOLD{sample}", UART_IIR)
            if _iir_pending(held) and _iir_id(held) == _INTR_ID_RDR:
                raise AssertionError(
                    f"{label}: RECEIVED_DATA_READY (id 0x2) pending with only "
                    f"{depth - 1} character(s) in the RX FIFO and "
                    f"FCR.RCVR_TRIGGER programmed to {depth} "
                    f"(sample {sample}, IIR=0x{held:08x})"
                )
            await Timer(1, unit="us")

        # Threshold character.
        await self.csr_write(f"{label}_THR_TRIG", UART_RBR, 0x30 + depth)
        trig_iir = await self._wait_iir_id(f"{label}_RDR", _INTR_ID_RDR)

        # Back below the level.
        await self.csr_read(f"{label}_RBR_POP", UART_RBR)
        below_iir = await self._wait_iir_not_id(f"{label}_BELOW", _INTR_ID_RDR)
        self.trigger_ids[label] = (_iir_id(pre_iir), _iir_id(trig_iir), _iir_id(below_iir))
        cocotb.log.info(
            "CHK-UART-FIFO-TRIG-%s: FCR.RCVR_TRIGGER=0x%x (%d character(s) per "
            "uart_16550_main_wo.rdl) -- with %d character(s) queued IIR read "
            "0x%08x (id=0x%x, no RECEIVED_DATA_READY over %d samples); the %dth "
            "character raised IIR=0x%08x id=0x%x; popping one back below the "
            "level left IIR=0x%08x id=0x%x",
            label,
            trig_cfg,
            depth,
            depth - 1,
            pre_iir,
            _iir_id(pre_iir),
            _PRE_HOLD_SAMPLES,
            depth,
            trig_iir,
            _iir_id(trig_iir),
            below_iir,
            _iir_id(below_iir),
        )

    async def _test_fifo_reset(self) -> None:
        await self._fifo_reset(rx=True, tx=True)
        await self._fifo_set_trigger(_TRIG_1B)
        for i in range(4):
            await self.csr_write(f"RST_THR_{i}", UART_RBR, 0x40 + i)

        lsr = 0
        for _ in range(512):
            lsr = await self.csr_read("RST_TEMT_WAIT", UART_LSR)
            if lsr & LSR_TEMT:
                break
            await Timer(1, unit="us")
        else:
            raise AssertionError(f"TEMT not set before RX reset LSR=0x{lsr:08x}")

        lsr = 0
        for _ in range(512):
            lsr = await self.csr_read("RST_DR_WAIT", UART_LSR)
            if lsr & LSR_DR:
                break
            await Timer(1, unit="us")
        else:
            raise AssertionError(f"LSR.DR=0 before RX reset LSR=0x{lsr:08x}")
        lsr = await self.csr_read("RST_DR_PRE", UART_LSR)
        if not (lsr & LSR_DR):
            raise AssertionError(f"LSR.DR cleared before RX reset LSR=0x{lsr:08x}")
        await self._fifo_reset(rx=True, tx=False)
        lsr = await self.csr_read("RST_DR_POST", UART_LSR)
        if lsr & LSR_DR:
            raise AssertionError(f"LSR.DR still set after RX reset LSR=0x{lsr:08x}")
        iir = await self.csr_read("RST_IIR_POST", UART_IIR)
        if _iir_pending(iir) and _iir_id(iir) == _INTR_ID_RDR:
            raise AssertionError(f"RDR still pending after RX reset IIR=0x{iir:08x}")
        cocotb.log.info("CHK-UART-FIFO-RST-RX: DR cleared after RCVR_FIFO_RESET")

        # Slow the baud divisor so a character occupies _SLOW_CHAR_CLOCKS uart
        # clocks (see the constant's comment: 16x oversampling x 10 bit times x
        # DLL, per uart_16550/doc/interface.adoc). The THRE==0 precondition below
        # is still established from a DUT-reported event -- the fill loop polls
        # LSR.THRE and raises if it never reads 0 -- the divisor only widens the
        # transmit window so a bounded poll can land inside it.
        await self.csr_write("LCR_DLAB_SLOW", UART_LCR, LCR_WLS | LCR_DLAB)
        await self.csr_write("DLL_SLOW_via_UART_RBR", UART_RBR, _DLL_SLOW)
        await self.csr_write("DLH_SLOW_via_UART_IER", UART_IER, 0)
        await self.csr_write("LCR_8N1_SLOW", UART_LCR, LCR_WLS)
        await self.csr_write("IER_ERBFI_SLOW", UART_IER, IER_ERBFI)

        saw_thre0 = False
        for i in range(16):
            await self.csr_write(f"TX_FILL_{i}", UART_RBR, 0x50 + i)
            lsr = await self.csr_read(f"TX_LSR_{i}", UART_LSR)
            if not (lsr & LSR_THRE):
                saw_thre0 = True
                break
        if not saw_thre0:
            raise AssertionError(
                f"THRE never 0 before TX reset LSR=0x{lsr:08x} (with "
                f"DLL={_DLL_SLOW}, one character is {_SLOW_CHAR_CLOCKS} uart "
                f"clocks, so the transmitter should still be busy at the sample)"
            )
        lsr = await self.csr_read("TX_THRE_PRE", UART_LSR)
        if lsr & LSR_THRE:
            raise AssertionError(f"THRE set before TX reset LSR=0x{lsr:08x}")
        await self._fifo_reset(rx=False, tx=True)
        lsr = await self.csr_read("TX_THRE_POST", UART_LSR)
        if not (lsr & LSR_THRE):
            raise AssertionError(f"THRE not set after TX reset LSR=0x{lsr:08x}")
        for _ in range(4096):
            lsr = await self.csr_read("TX_TEMT_POST", UART_LSR)
            if lsr & LSR_TEMT:
                break
            await Timer(1, unit="us")
        else:
            raise AssertionError(f"TEMT not set after TX reset LSR=0x{lsr:08x}")
        cocotb.log.info("CHK-UART-FIFO-RST-TX: THRE+TEMT after XMIT_FIFO_RESET")

    async def _test_above_depth_triggers(self) -> None:
        """An empty 32-entry FIFO never reaches unsupported thresholds 64 through 4096."""
        await self._fifo_reset(rx=True, tx=True)
        for trigger_cfg, threshold in _ABOVE_FIFO_DEPTH_TRIGGERS.items():
            await self._fifo_set_trigger(trigger_cfg)
            samples = []
            for sample in range(_PRE_HOLD_SAMPLES):
                iir = await self.csr_read(f"ABOVE_DEPTH_{threshold}_{sample}_IIR", UART_IIR)
                samples.append(iir)
                if _iir_pending(iir) and _iir_id(iir) == _INTR_ID_RDR:
                    raise AssertionError(
                        f"RCVR trigger {trigger_cfg:#x} ({threshold} characters) "
                        f"raised RECEIVED_DATA_READY for an empty 32-entry FIFO: "
                        f"IIR=0x{iir:08x}"
                    )
            cocotb.log.info(
                "CHK-UART-FIFO-TRIG-ABOVE-DEPTH: encoding=0x%x threshold=%d "
                "characters stayed below RECEIVED_DATA_READY across IIR samples %s",
                trigger_cfg,
                threshold,
                [f"0x{value:08x}" for value in samples],
            )

    async def body(self) -> None:
        cg = await self.csr_read("UART_CG", CLOCK_GATE_CONTROL)
        await self.csr_write("UART_UNGATE", CLOCK_GATE_CONTROL, cg & ~UART_CG_EN)
        await self._init_loopback()

        await self._test_rx_trigger("1B", _TRIG_1B)
        self.trigger_1b_ok = True
        await self._test_rx_trigger("4B", _TRIG_4B)
        self.trigger_4b_ok = True
        await self._test_rx_trigger("32B", _TRIG_32B)
        self.trigger_32b_ok = True
        await self._test_above_depth_triggers()
        self.above_depth_ok = True
        await self._test_fifo_reset()
        self.reset_ok = True
