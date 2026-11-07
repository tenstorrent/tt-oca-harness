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
FCR_RCVR_TRIGGER_BM = _field_mask(_UART_WO_H, "UART_16550_MAIN_WO__FCR__RCVR_TRIGGER_bm")
FCR_RCVR_TRIGGER_BW = _field_mask(_UART_WO_H, "UART_16550_MAIN_WO__FCR__RCVR_TRIGGER_bw")
ECR_RCVR_TRIGGER_MS2B_BP = _field_mask(_UART_H, "UART_16550_MAIN__ECR__RCVR_TRIGGER_MS2B_bp")
ECR_RCVR_TRIGGER_MS2B_BM = _field_mask(_UART_H, "UART_16550_MAIN__ECR__RCVR_TRIGGER_MS2B_bm")
IIR_INTERRUPT_PENDING = _field_mask(_UART_H, "UART_16550_MAIN__IIR__INTERRUPT_PENDING_bm")
IIR_INTERRUPT_ID = _field_mask(_UART_H, "UART_16550_MAIN__IIR__INTERRUPT_ID_bm")
IIR_INTERRUPT_ID_BP = _field_mask(_UART_H, "UART_16550_MAIN__IIR__INTERRUPT_ID_bp")
IIR_FIFOS_ENABLED = _field_mask(_UART_H, "UART_16550_MAIN__IIR__FIFOS_ENABLED_bm")
IIR_FIFOS_ENABLED_BP = _field_mask(_UART_H, "UART_16550_MAIN__IIR__FIFOS_ENABLED_bp")
IER_ERBFI = _field_mask(_UART_H, "UART_16550_MAIN__IER__ERBFI_bm")
LCR_DLAB = _field_mask(_UART_H, "UART_16550_MAIN__LCR__DLAB_bm")
LCR_WLS = _field_mask(_UART_H, "UART_16550_MAIN__LCR__WLS_bm")
MCR_LOOP = _field_mask(_UART_H, "UART_16550_MAIN__MCR__LOOP_bm")
MCR_RTS = _field_mask(_UART_H, "UART_16550_MAIN__MCR__RTS_bm")
LSR_DR = _field_mask(_UART_H, "UART_16550_MAIN__LSR__DR_bm")
LSR_OE = _field_mask(_UART_H, "UART_16550_MAIN__LSR__OE_bm")
LSR_THRE = _field_mask(_UART_H, "UART_16550_MAIN__LSR__THRE_bm")
LSR_TEMT = _field_mask(_UART_H, "UART_16550_MAIN__LSR__TEMT_bm")
# Every LSR field, for a whole-register compare.
LSR_FIELDS = (
    LSR_DR
    | LSR_OE
    | _field_mask(_UART_H, "UART_16550_MAIN__LSR__PE_bm")
    | _field_mask(_UART_H, "UART_16550_MAIN__LSR__FE_bm")
    | _field_mask(_UART_H, "UART_16550_MAIN__LSR__BI_bm")
    | LSR_THRE
    | LSR_TEMT
    | _field_mask(_UART_H, "UART_16550_MAIN__LSR__ERROR_IN_RCVR_FIFO_bm")
)

# 16550 IntrID encodings, from uart_16550_main.rdl IIR.INTERRUPT_ID (the RDL
# lists every encoding with its priority).
#   0x2 - Received Data Ready Interrupt   (priority 3)
#   0x6 - Reception Timeout Interrupt     (priority 2)
_INTR_ID_RDR = 0x2
_INTR_ID_CHAR_TIMEOUT = 0x6
# IIR samples after the pop below the level, a quarter character apart: the
# Reception Timeout outranks RECEIVED_DATA_READY in IIR and fires four
# character times after the last FIFO change, so the samples stay inside one
# character time of the pop and a level that did not clear cannot be hidden
# behind the timeout id.
_BELOW_SAMPLES = 2
# FCR.RCVR_TRIGGER encodings, from uart_16550_main_wo.rdl FCR.RCVR_TRIGGER:
#   0x0 - 1 character, 0x1 - 4 characters, 0x2 - 8, 0x3 - 14; the ECR extension
#   (uart_16550_main.rdl RCVR_TRIGGER_MS2B) adds 0x4 - 32.
_TRIG_1B = 0
_TRIG_4B = 1
_TRIG_8B = 2
_TRIG_14B = 3
_TRIG_32B = 4
_TRIG_LEVEL_CHARS = {_TRIG_1B: 1, _TRIG_4B: 4, _TRIG_8B: 8, _TRIG_14B: 14, _TRIG_32B: 32}
# The trigger cells in the order they run; the test module gates on every one.
TRIGGER_CELLS = (
    ("1B", _TRIG_1B),
    ("4B", _TRIG_4B),
    ("8B", _TRIG_8B),
    ("14B", _TRIG_14B),
    ("32B", _TRIG_32B),
)
# IIR.FIFOS_ENABLED (uart_16550_main.rdl): 0x3 with the FIFOs on, 0x0 off.
_FIFOS_ON = 0x3
_FIFOS_OFF = 0x0
# LSR with the transmitter idle and nothing received: THRE and TEMT only.
_LSR_IDLE = LSR_THRE | LSR_TEMT
# The receiver FIFO depth: the largest trigger level the RDL lists that a
# 32-entry FIFO can reach, and the number of characters the above-depth leg
# queues so the unsupported encodings are sampled on a full FIFO.
_RX_FIFO_DEPTH = _TRIG_LEVEL_CHARS[_TRIG_32B]
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
# be busy when LSR is read.
_UART_OVERSAMPLE = 16
_CHAR_BITS_8N1 = 10
_DLL_SLOW = 32
_SLOW_CHAR_CLOCKS = _UART_OVERSAMPLE * _CHAR_BITS_8N1 * _DLL_SLOW
# Samples of IIR required to show NO RCVR-data-available while the RX FIFO sits
# below the programmed trigger level.
_PRE_HOLD_SAMPLES = 4
# Divisor of the loopback legs; the hold samples above are spread over one
# character time at it, so the receiver's four-character-time reception
# timeout (IIR id 0x6) cannot fire on the queued characters while they wait.
_DLL_FAST = 1


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
        self.fcr_under_dlab_ok: bool = False
        # label -> (pre-threshold IIR id, at-threshold IIR id, below-level IIR
        # id). Measured values the test module gates on, so a cell that ran but
        # observed the wrong interrupt fails the testcase, not just the token.
        self.trigger_ids: dict[str, tuple[int, int, int]] = {}

    async def _write_fcr(self, value: int) -> None:
        # FCR is the write-only alias of the IIR address in the 16550 map; the
        # label names both the register written and the symbol addressed.
        await self.csr_write("FCR_via_UART_IIR", UART_IIR, value)

    async def _fifo_set_trigger(self, trigger_cfg: int) -> None:
        # The 4-bit encoding splits into FCR.RCVR_TRIGGER (low bits) and
        # ECR.RCVR_TRIGGER_MS2B (high bits); ECR is readable and read back.
        ecr = (
            (trigger_cfg >> FCR_RCVR_TRIGGER_BW) << ECR_RCVR_TRIGGER_MS2B_BP
        ) & ECR_RCVR_TRIGGER_MS2B_BM
        await self.csr_write("ECR_RCVR_TRIGGER_MS2B", UART_ECR, ecr)
        got = await self.csr_read("ECR_RCVR_TRIGGER_MS2B_RB", UART_ECR)
        assert got & ECR_RCVR_TRIGGER_MS2B_BM == ecr, (
            f"ECR read 0x{got:08x} after writing 0x{ecr:08x}; RCVR_TRIGGER_MS2B did not land"
        )
        fcr = FCR_FIFO_ENABLE | ((trigger_cfg << FCR_RCVR_TRIGGER_BP) & FCR_RCVR_TRIGGER_BM)
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
        # name both.
        await self.csr_write("DLL_via_UART_RBR", UART_RBR, _DLL_FAST)
        await self.csr_write("DLH_via_UART_IER", UART_IER, 0)
        await self.csr_write("LCR_8N1", UART_LCR, LCR_WLS)
        await self.csr_write("MCR_LOOP", UART_MCR, MCR_LOOP | MCR_RTS)
        await self.csr_write("IER_ERBFI", UART_IER, IER_ERBFI)

    def _hold_step_ns(self) -> int:
        """A quarter of the character time at the fast divisor, in ns."""
        char_ns = _UART_OVERSAMPLE * _CHAR_BITS_8N1 * _DLL_FAST * self.cfg.periph_clk_period_ns
        return max(1, int(char_ns / 4))

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
            await Timer(self._hold_step_ns(), unit="ns")
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
        * popping one character back below the level must clear it again
          within one character time, before the Reception Timeout, which
          outranks it in IIR, could stand in for a level that did not clear.

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
        fifos = (pre_iir & IIR_FIFOS_ENABLED) >> IIR_FIFOS_ENABLED_BP
        assert fifos == _FIFOS_ON, (
            f"{label}: IIR=0x{pre_iir:08x} reports FIFOS_ENABLED=0x{fifos:x}; the trigger level "
            f"is a FIFO-mode compare and needs the FIFOs on (0x{_FIFOS_ON:x})"
        )
        for sample in range(_PRE_HOLD_SAMPLES):
            held = await self.csr_read(f"{label}_IIR_PRE_HOLD{sample}", UART_IIR)
            if _iir_pending(held) and _iir_id(held) == _INTR_ID_RDR:
                raise AssertionError(
                    f"{label}: RECEIVED_DATA_READY (id 0x2) pending with only "
                    f"{depth - 1} character(s) in the RX FIFO and "
                    f"FCR.RCVR_TRIGGER programmed to {depth} "
                    f"(sample {sample}, IIR=0x{held:08x})"
                )
            await Timer(self._hold_step_ns(), unit="ns")

        # Threshold character.
        await self.csr_write(f"{label}_THR_TRIG", UART_RBR, 0x30 + depth)
        trig_iir = await self._wait_iir_id(f"{label}_RDR", _INTR_ID_RDR)

        # Back below the level.
        await self.csr_read(f"{label}_RBR_POP", UART_RBR)
        below_iir = await self._wait_iir_not_id(f"{label}_BELOW", _INTR_ID_RDR, _BELOW_SAMPLES)
        assert not (_iir_pending(below_iir) and _iir_id(below_iir) == _INTR_ID_CHAR_TIMEOUT), (
            f"{label}: IIR=0x{below_iir:08x} reports the Reception Timeout within one character "
            f"time of the pop; the level below the trigger is not shown cleared"
        )
        self.trigger_ids[label] = (_iir_id(pre_iir), _iir_id(trig_iir), _iir_id(below_iir))
        cocotb.log.info(
            "CHK-UART-FIFO-TRIG-%s: FCR.RCVR_TRIGGER=0x%x (%d character(s) per "
            "uart_16550_main_wo.rdl) -- with %d character(s) queued IIR read "
            "0x%08x (FIFOS_ENABLED=0x%x, id=0x%x, no RECEIVED_DATA_READY over %d samples); "
            "the %dth character raised IIR=0x%08x id=0x%x; popping one back below the "
            "level left IIR=0x%08x id=0x%x within %d quarter-character samples (not the "
            "timeout id 0x%x)",
            label,
            trig_cfg,
            depth,
            depth - 1,
            pre_iir,
            fifos,
            _iir_id(pre_iir),
            _PRE_HOLD_SAMPLES,
            depth,
            trig_iir,
            _iir_id(trig_iir),
            below_iir,
            _iir_id(below_iir),
            _BELOW_SAMPLES,
            _INTR_ID_CHAR_TIMEOUT,
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
        # DLL, per uart_16550/doc/interface.adoc); the fill loop below polls
        # LSR.THRE inside that window.
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

    async def _refill_to_depth(self, label: str) -> int:
        """Pop one character and loop one back, so the FIFO returns to its depth.

        The arrival re-evaluates the trigger level against the encoding that is
        programmed at that moment and clears any Reception Timeout, so the IIR
        sampled right after it reports the level compare and not a timeout
        left over from the previous encoding.
        """
        await self.csr_read(f"{label}_POP", UART_RBR)
        await self.csr_write(f"{label}_REFILL_THR", UART_RBR, 0x7E)
        await self._wait_lsr_bit(f"{label}_REFILL_TEMT", LSR_TEMT, True)
        return await self._wait_lsr_bit(f"{label}_REFILL_DR", LSR_DR, True)

    async def _test_above_depth_triggers(self) -> None:
        """Unsupported thresholds 64 through 4096 never fire on a FULL 32-entry FIFO.

        The FIFO is filled to its depth through loopback, and for every
        encoding the level is re-evaluated by popping one character and
        looping one back, so the 32nd arrival is compared against that
        encoding. The same refill raises RECEIVED_DATA_READY at the
        32-character encoding immediately before each encoding and after the
        sweep, so a level that could not fire at all is told apart from one
        that does not fire above the depth.
        """
        await self._fifo_reset(rx=True, tx=True)
        await self._fifo_set_trigger(_TRIG_32B)
        await self.csr_read("ABOVE_DEPTH_IIR_CLR", UART_IIR)
        for i in range(_RX_FIFO_DEPTH):
            await self.csr_write(f"ABOVE_DEPTH_FILL_{i}", UART_RBR, 0x60 + i)
        # TEMT under MCR.LOOP: every character written has been received.
        await self._wait_lsr_bit("ABOVE_DEPTH_FILL_TEMT", LSR_TEMT, True)
        lsr = await self._wait_lsr_bit("ABOVE_DEPTH_FULL", LSR_DR, True)
        assert not (lsr & LSR_OE), (
            f"LSR=0x{lsr:08x} reports an overrun after {_RX_FIFO_DEPTH} looped-back "
            f"characters: the RX FIFO is shallower than the 32-character trigger level"
        )
        await self._wait_iir_id("ABOVE_DEPTH_ARMED", _INTR_ID_RDR)
        for trigger_cfg, threshold in _ABOVE_FIFO_DEPTH_TRIGGERS.items():
            # Each encoding starts from the 32-character encoding re-armed and
            # raising RECEIVED_DATA_READY, so an FCR write that did not land
            # leaves a level that fires, not the previous unsupported one.
            await self._fifo_set_trigger(_TRIG_32B)
            await self._refill_to_depth(f"ABOVE_DEPTH_{threshold}_REARM")
            armed = await self._wait_iir_id(f"ABOVE_DEPTH_{threshold}_ARMED", _INTR_ID_RDR)
            await self._fifo_set_trigger(trigger_cfg)
            lsr = await self._refill_to_depth(f"ABOVE_DEPTH_{threshold}")
            assert not (lsr & LSR_OE), f"overrun while refilling to depth: LSR=0x{lsr:08x}"
            samples = []
            for sample in range(_PRE_HOLD_SAMPLES):
                iir = await self.csr_read(f"ABOVE_DEPTH_{threshold}_{sample}_IIR", UART_IIR)
                samples.append(iir)
                if _iir_pending(iir) and _iir_id(iir) == _INTR_ID_RDR:
                    raise AssertionError(
                        f"RCVR trigger {trigger_cfg:#x} ({threshold} characters) "
                        f"raised RECEIVED_DATA_READY with {_RX_FIFO_DEPTH} characters "
                        f"queued in the 32-entry FIFO: IIR=0x{iir:08x}"
                    )
            cocotb.log.info(
                "CHK-UART-FIFO-TRIG-ABOVE-DEPTH: encoding=0x%x threshold=%d characters: the "
                "32nd character arrived with this encoding programmed (LSR=0x%08x, DR set, no "
                "overrun; the same refill raised IIR=0x%08x at the 32-character encoding re-armed "
                "just before, ECR read back) and RECEIVED_DATA_READY stayed absent across IIR "
                "samples %s",
                trigger_cfg,
                threshold,
                lsr,
                armed,
                [f"0x{value:08x}" for value in samples],
            )
        # Same depth, supported encoding again: the level compare is live.
        await self._fifo_set_trigger(_TRIG_32B)
        await self._refill_to_depth("ABOVE_DEPTH_REARM")
        rearmed = await self._wait_iir_id("ABOVE_DEPTH_REARMED", _INTR_ID_RDR)
        cocotb.log.info(
            "above-depth positive control: the 32-character encoding raised IIR=0x%08x again on "
            "the %d queued characters after the sweep",
            rearmed,
            _RX_FIFO_DEPTH,
        )
        await self._fifo_reset(rx=True, tx=True)

    async def _test_fcr_under_dlab(self) -> None:
        """FCR, IIR and LSR stay reachable with LCR.DLAB set.

        uart_16550_main.rdl (LCR.DLAB) and memmap.adoc: only offsets 0x00 and
        0x04 change meaning with DLAB; FCR at 0x08 is writable, and IIR and
        LSR readable, for either DLAB value. With DLAB set, FCR is written
        with the FIFOs off and then on, and IIR.FIFOS_ENABLED has to follow
        each write; LSR has to read the idle transmitter. The DLAB=0 write
        afterwards is the control that the same FCR path answers both ways.

        The reset leg before this one leaves the transmitter idle; under
        MCR.LOOP its last character lands in the receiver within one character
        time of that, so one character time at the slow divisor passes before
        the FIFOs are turned off, and the LSR compare sees no late arrival.
        """
        await self._wait_lsr_bit("DLAB_PRE_TEMT", LSR_TEMT, True)
        await Timer(_SLOW_CHAR_CLOCKS * self.cfg.periph_clk_period_ns, unit="ns")
        await self.csr_write("DLAB_SET", UART_LCR, LCR_WLS | LCR_DLAB)
        lcr_set = await self.csr_read("DLAB_SET_RB", UART_LCR)
        assert lcr_set & LCR_DLAB, f"LCR read 0x{lcr_set:08x} after the DLAB write; DLAB is clear"
        await self._write_fcr(0)
        iir_off = await self.csr_read("DLAB_IIR_FIFOS_OFF", UART_IIR)
        fifos_off = (iir_off & IIR_FIFOS_ENABLED) >> IIR_FIFOS_ENABLED_BP
        assert fifos_off == _FIFOS_OFF, (
            f"with LCR.DLAB set an FCR write of 0 left IIR=0x{iir_off:08x} "
            f"(FIFOS_ENABLED=0x{fifos_off:x}); FCR at 0x08 is writable for either DLAB value"
        )
        await self._write_fcr(FCR_FIFO_ENABLE | FCR_RCVR_FIFO_RESET | FCR_XMIT_FIFO_RESET)
        iir_on = await self.csr_read("DLAB_IIR_FIFOS_ON", UART_IIR)
        fifos_on = (iir_on & IIR_FIFOS_ENABLED) >> IIR_FIFOS_ENABLED_BP
        assert fifos_on == _FIFOS_ON, (
            f"with LCR.DLAB set an FCR write of FIFO_ENABLE left IIR=0x{iir_on:08x} "
            f"(FIFOS_ENABLED=0x{fifos_on:x}); FCR at 0x08 is writable for either DLAB value"
        )
        lsr = await self.csr_read("DLAB_LSR", UART_LSR)
        assert lsr & LSR_FIELDS == _LSR_IDLE, (
            f"with LCR.DLAB set LSR read 0x{lsr:08x}; the idle transmitter reads THRE and TEMT "
            f"(0x{_LSR_IDLE:02x}) for either DLAB value"
        )
        await self.csr_write("DLAB_CLR", UART_LCR, LCR_WLS)
        lcr_clr = await self.csr_read("DLAB_CLR_RB", UART_LCR)
        assert not lcr_clr & LCR_DLAB, f"LCR read 0x{lcr_clr:08x} after the DLAB clear; DLAB is set"
        iir_dlab0 = await self.csr_read("DLAB0_IIR_FIFOS_ON", UART_IIR)
        assert (iir_dlab0 & IIR_FIFOS_ENABLED) >> IIR_FIFOS_ENABLED_BP == _FIFOS_ON, (
            f"IIR=0x{iir_dlab0:08x} after LCR.DLAB was cleared; the FIFOs enabled under DLAB=1 "
            f"stay enabled"
        )
        self.fcr_under_dlab_ok = True
        cocotb.log.info(
            "CHK-UART-FCR-UNDER-DLAB: with LCR read back 0x%08x (DLAB=1) FCR written 0 then "
            "FIFO_ENABLE: IIR read 0x%08x (FIFOS_ENABLED=0x%x) then 0x%08x (FIFOS_ENABLED=0x%x), "
            "LSR read 0x%08x (THRE+TEMT); with LCR read back 0x%08x (DLAB=0) IIR read 0x%08x",
            lcr_set,
            iir_off,
            fifos_off,
            iir_on,
            fifos_on,
            lsr,
            lcr_clr,
            iir_dlab0,
        )

    async def body(self) -> None:
        cg = await self.csr_read("UART_CG", CLOCK_GATE_CONTROL)
        await self.csr_write("UART_UNGATE", CLOCK_GATE_CONTROL, cg & ~UART_CG_EN)
        await self._init_loopback()

        for label, trig_cfg in TRIGGER_CELLS:
            await self._test_rx_trigger(label, trig_cfg)
        self.trigger_1b_ok = "1B" in self.trigger_ids
        self.trigger_4b_ok = "4B" in self.trigger_ids
        self.trigger_32b_ok = "32B" in self.trigger_ids
        await self._test_above_depth_triggers()
        self.above_depth_ok = True
        await self._test_fifo_reset()
        self.reset_ok = True
        await self._test_fcr_under_dlab()
