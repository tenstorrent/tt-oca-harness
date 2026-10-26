# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""UART line errors, loopback, modem control, THRE and FIFO access. Requires +smc_uart_cross_3to0.

The UART0 legs prove parity mismatch, RX overrun and break/framing. The UART1-3 legs follow
them on the cross-wired pairs (UART1<->UART2, UART3<->UART0): receive break, parity and
framing errors with IER.ELSI on and off, LSR read-to-clear, MCR.LOOP, IIR with THRE pending,
THRE forced through ITR, FCR.XMIT_FIFO_RESET, and the THR overflow / RBR underflow
observation.

Spec sources: hw/ip/uart/uart_16550/regs/gen/adoc/uart_16550_main.adoc (IER, IIR, LCR, MCR,
LSR, ITR), uart_16550_main_wo.adoc (FCR), hw/ip/uart/uart_16550/doc/architecture.adoc.
"""

from __future__ import annotations

from pathlib import Path

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge, Timer
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import UART_CG_EN, _field_mask, smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_log_engine_utils import (
    DLL_OFFSET,
    DLM_OFFSET,
    FCR_OFFSET,
    THR_OFFSET,
    uart_base,
    uart_reg,
)

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

CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")

UART_EN = _field_mask(_UART_CTRL_H, "UART_LOG_ENGINE_CTRL__CTRL__UART_EN_bm")
FCR_FIFO_ENABLE = _field_mask(_UART_WO_H, "UART_16550_MAIN_WO__FCR__FIFO_ENABLE_bm")
IER_ERBFI = _field_mask(_UART_H, "UART_16550_MAIN__IER__ERBFI_bm")
IER_ETBEI = _field_mask(_UART_H, "UART_16550_MAIN__IER__ETBEI_bm")
IER_ELSI = _field_mask(_UART_H, "UART_16550_MAIN__IER__ELSI_bm")
IER_EDSSI = _field_mask(_UART_H, "UART_16550_MAIN__IER__EDSSI_bm")
IIR_INTERRUPT_PENDING = _field_mask(_UART_H, "UART_16550_MAIN__IIR__INTERRUPT_PENDING_bm")
IIR_INTERRUPT_ID = _field_mask(_UART_H, "UART_16550_MAIN__IIR__INTERRUPT_ID_bm")
IIR_INTERRUPT_ID_BP = _field_mask(_UART_H, "UART_16550_MAIN__IIR__INTERRUPT_ID_bp")
LCR_DLAB = _field_mask(_UART_H, "UART_16550_MAIN__LCR__DLAB_bm")
LCR_WLS = _field_mask(_UART_H, "UART_16550_MAIN__LCR__WLS_bm")
LCR_PEN = _field_mask(_UART_H, "UART_16550_MAIN__LCR__PEN_bm")
LCR_EPS = _field_mask(_UART_H, "UART_16550_MAIN__LCR__EPS_bm")
LCR_SET_BREAK = _field_mask(_UART_H, "UART_16550_MAIN__LCR__SET_BREAK_bm")
MCR_LOOP = _field_mask(_UART_H, "UART_16550_MAIN__MCR__LOOP_bm")
MCR_RTS = _field_mask(_UART_H, "UART_16550_MAIN__MCR__RTS_bm")
LSR_DR = _field_mask(_UART_H, "UART_16550_MAIN__LSR__DR_bm")
LSR_OE = _field_mask(_UART_H, "UART_16550_MAIN__LSR__OE_bm")
LSR_PE = _field_mask(_UART_H, "UART_16550_MAIN__LSR__PE_bm")
LSR_FE = _field_mask(_UART_H, "UART_16550_MAIN__LSR__FE_bm")
LSR_BI = _field_mask(_UART_H, "UART_16550_MAIN__LSR__BI_bm")

_INTR_RDR = 0x2
_INTR_LSR = 0x3
_FIFO_DEPTH = 32
_IER_BASIC = IER_ERBFI | IER_ETBEI | IER_ELSI | IER_EDSSI

FCR_RCVR_FIFO_RESET = _field_mask(_UART_WO_H, "UART_16550_MAIN_WO__FCR__RCVR_FIFO_RESET_bm")
FCR_XMIT_FIFO_RESET = _field_mask(_UART_WO_H, "UART_16550_MAIN_WO__FCR__XMIT_FIFO_RESET_bm")
IIR_FIFOS_ENABLED = _field_mask(_UART_H, "UART_16550_MAIN__IIR__FIFOS_ENABLED_bm")
ITR_TTBEI = _field_mask(_UART_H, "UART_16550_MAIN__ITR__TTBEI_bm")
MCR_DTR = _field_mask(_UART_H, "UART_16550_MAIN__MCR__DTR_bm")
MCR_OUT1 = _field_mask(_UART_H, "UART_16550_MAIN__MCR__OUT1_bm")
MCR_OUT2 = _field_mask(_UART_H, "UART_16550_MAIN__MCR__OUT2_bm")
LSR_THRE = _field_mask(_UART_H, "UART_16550_MAIN__LSR__THRE_bm")
LSR_TEMT = _field_mask(_UART_H, "UART_16550_MAIN__LSR__TEMT_bm")
LSR_ERROR_IN_RCVR_FIFO = _field_mask(_UART_H, "UART_16550_MAIN__LSR__ERROR_IN_RCVR_FIFO_bm")
RBR_DATA = _field_mask(_UART_H, "UART_16550_MAIN__RBR__DATA_bm")

_INTR_THRE = 0x1
# Contract S1-S4 formats: 8N1, 8 bits even parity, 8 bits odd parity, 5 bits 1 stop.
LCR_8N1 = LCR_WLS
LCR_8E1 = LCR_WLS | LCR_PEN | LCR_EPS
LCR_8O1 = LCR_WLS | LCR_PEN
LCR_5N1 = 0
MCR_MODEM_OUT = MCR_DTR | MCR_OUT1 | MCR_OUT2
LSR_RX_ERRORS = LSR_BI | LSR_FE | LSR_PE
LSR_LINE_STATUS = LSR_RX_ERRORS | LSR_OE
LSR_IDLE = LSR_TEMT | LSR_THRE
IIR_NONE = IIR_FIFOS_ENABLED | IIR_INTERRUPT_PENDING
IIR_LSR = IIR_FIFOS_ENABLED | (_INTR_LSR << IIR_INTERRUPT_ID_BP)
IIR_THRE = IIR_FIFOS_ENABLED | (_INTR_THRE << IIR_INTERRUPT_ID_BP)
IIR_RDR = IIR_FIFOS_ENABLED | (_INTR_RDR << IIR_INTERRUPT_ID_BP)

# Receiver -> the cross-wired instance whose TX drives its RX under +smc_uart_cross_3to0.
PEER = {1: 2, 2: 1, 3: 0}
RECEIVERS = (1, 2, 3)
DIVISOR = 1
# S10 needs 33 THR writes inside one frame time: at this divisor a frame is longer than the
# writes take over SEP_IN, at DIVISOR it is not.
FIFO_ACCESS_DIVISOR = 4
FRAME_BITS = 10
OVERSAMPLE = 16


def _frame_clocks(divisor: int) -> int:
    """uart_16550_dl: baud = clk / (16 * (divisor + 1)); one 8N1 frame is 10 bits."""
    return FRAME_BITS * OVERSAMPLE * (divisor + 1)


FRAME_CLOCKS = _frame_clocks(DIVISOR)
FIFO_ACCESS_FRAME_CLOCKS = _frame_clocks(FIFO_ACCESS_DIVISOR)
BREAK_CLOCKS = 2 * FRAME_CLOCKS
XMIT_WINDOW_CLOCKS = 12 * FRAME_CLOCKS
POLL_LIMIT = 160
DRAIN_LIMIT = 40
COLLECT_LIMIT = 4000

PARITY_CHAR = 0x55
FRAMING_CHAR = 0xC1
LOOP_CHAR = 0xA5
UNLOOP_CHAR = 0x5A
THRE_CHAR = 0x33
THRE_ARM_CHAR = 0x3C
ITR_CHARS = (0x61, 0x62, 0x63, 0x64)
XMIT_HELD_CHAR = 0x6E
XMIT_CHARS = tuple(range(0x40, 0x48))
FIFO_ACCESS_CHARS = tuple(range(0x80, 0xA1))
FIFO_ACCESS_GROUPS = ((1, 3), (2,))

UART0_WAITS = (
    "PE_LSR/PE_IIR per byte: 512 LSR+IIR reads 100 ns apart, expiry raises 'parity PE not "
    "seen' or 'parity LSR IRQ not seen' with the byte",
    "OK_RDR per byte: 64 IIR reads 100 ns apart, expiry raises 'matched parity missing RDR' "
    "with the byte",
    "OE_NEG_RDR: 512 IIR reads 100 ns apart, expiry raises 'single byte produced no RDR interrupt'",
    "OE_RDR per write: 512 IIR reads 100 ns apart, expiry raises 'overrun path missing RDR "
    "after write' with the write index",
    "OE_POLL: 1024 LSR reads 100 ns apart, expiry raises 'LSR.OE never set after FIFO overflow'",
    "OE_LSR: 32 IIR reads 100 ns apart, expiry raises 'overrun missing LSR interrupt'",
    "OE_DRAIN: at most 64 LSR+RBR read pairs, no expiry of its own; the OE_POST LSR compare "
    "that follows raises with that LSR value",
    "BRK_POLL: 128 LSR reads 1 us apart, expiry raises 'LSR.BI never set under SET_BREAK loopback'",
    "BRK_LSR: 32 IIR reads 100 ns apart, expiry raises 'break missing LSR interrupt'",
    "BRK_CLR: 256 LSR+RBR+IIR read rounds 100 ns apart, expiry raises 'FE/BI sticky after "
    "break clear' with the last LSR value",
)

STEPS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9", "S10", "S11")
CHECKERS = (
    ("CHK-UART13-BREAK", "S2"),
    ("CHK-UART13-PARITY", "S3"),
    ("CHK-UART13-FRAMING", "S4"),
    ("CHK-UART13-LSR-RC", "S4"),
    ("CHK-UART13-MCR-LOOP", "S5"),
    ("CHK-UART13-OUT2-IIR", "S6"),
    ("CHK-UART13-IIR-THRE", "S7"),
    ("CHK-UART13-ITR-THRE", "S8"),
    ("CHK-UART13-XMIT-RESET", "S9"),
    ("CHK-UART13-FIFO-ACCESS-OBS", "S10"),
)
FENCE_TERMS = (
    "BRINGUP",
    "UART13_BREAK",
    "UART13_PARITY",
    "UART13_FRAMING",
    "UART13_MCR_LOOP",
    "UART13_OUT2_IIR",
    "UART13_IIR_THRE",
    "UART13_ITR_THRE",
    "UART13_XMIT_RESET",
    "UART13_FIFO_ACCESS",
)


def _uart_regs(idx: int) -> dict[str, int]:
    return {
        "ctrl": smc_indexed_addr(
            "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LOG_ENGINE_CTRL_CTRL_BASE_ADDR",
            idx,
        ),
        "rbr": smc_indexed_addr(
            "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_RBR_BASE_ADDR", idx
        ),
        "ier": smc_indexed_addr(
            "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IER_BASE_ADDR", idx
        ),
        "iir": smc_indexed_addr(
            "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IIR_BASE_ADDR", idx
        ),
        "lcr": smc_indexed_addr(
            "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LCR_BASE_ADDR", idx
        ),
        "mcr": smc_indexed_addr(
            "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_MCR_BASE_ADDR", idx
        ),
        "lsr": smc_indexed_addr(
            "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LSR_BASE_ADDR", idx
        ),
    }


def _uart13_regs(idx: int) -> dict[str, int]:
    base = uart_base(idx)
    regs = {
        name.lower(): uart_reg(idx, name) for name in ("IER", "IIR", "LCR", "MCR", "LSR", "ITR")
    }
    regs.update(
        ctrl=smc_indexed_addr(
            "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LOG_ENGINE_CTRL_CTRL_BASE_ADDR", idx
        ),
        rbr=uart_reg(idx, "RBR"),
        thr=base + THR_OFFSET,
        fcr=base + FCR_OFFSET,
        dll=base + DLL_OFFSET,
        dlm=base + DLM_OFFSET,
    )
    return regs


def _iir_id(iir: int) -> int:
    return (int(iir) & IIR_INTERRUPT_ID) >> IIR_INTERRUPT_ID_BP


def _iir_pending(iir: int) -> bool:
    return (int(iir) & IIR_INTERRUPT_PENDING) == 0


class smc_uart_error_conditions_test_seq(SmcCsrSeq):
    """UART0/3 parity, UART0 overrun, UART0 break/framing."""

    def __init__(self, name: str = "smc_uart_error_conditions_test_seq") -> None:
        super().__init__(name)
        self.parity_ok: bool = False
        self.overrun_ok: bool = False
        self.break_ok: bool = False
        self.dut = cocotb.top
        self.u = {idx: _uart13_regs(idx) for idx in range(4)}
        self.stamps: list[tuple[str, int]] = []
        self.chk_marks: list[tuple[str, int]] = []
        self.waits: dict[str, list[str]] = {}
        self.last_lsr: dict[int, int] = {}
        self.last_iir: dict[int, int] = {}
        self.rc_rows: list[str] = []
        self.windows: dict[str, str] = {}

    async def _enable(self, idx: int) -> None:
        r = _uart_regs(idx)
        await self.csr_write(f"UART{idx}_EN", r["ctrl"], UART_EN)

    async def _clear_status(self, r: dict[str, int], tag: str) -> None:
        await self.csr_read(f"{tag}_LSR", r["lsr"])
        await self.csr_read(f"{tag}_IIR", r["iir"])
        await self.csr_read(f"{tag}_RBR", r["rbr"])

    async def _program_format(
        self,
        r: dict[str, int],
        tag: str,
        *,
        divisor: int = 1,
        pen: bool = False,
        eps: bool = False,
        loop: bool = False,
    ) -> None:
        await self.csr_write(f"{tag}_MCR", r["mcr"], MCR_RTS | (MCR_LOOP if loop else 0))
        await self.csr_write(f"{tag}_LCR_DLAB", r["lcr"], LCR_WLS | LCR_DLAB)
        await self.csr_write(f"{tag}_DLL", r["rbr"], divisor & 0xFF)
        await self.csr_write(f"{tag}_DLH", r["ier"], (divisor >> 8) & 0xFF)
        lcr = LCR_WLS
        if pen:
            lcr |= LCR_PEN
        if eps:
            lcr |= LCR_EPS
        await self.csr_write(f"{tag}_LCR", r["lcr"], lcr)
        await self.csr_write(f"{tag}_IER", r["ier"], _IER_BASIC)
        await self.csr_write(f"{tag}_FCR", r["iir"], FCR_FIFO_ENABLE)

    async def _wait_iir_id(
        self, r: dict[str, int], tag: str, expect: int, iters: int = 512
    ) -> bool:
        for _ in range(iters):
            iir = await self.csr_read(f"{tag}_IIR", r["iir"])
            if _iir_pending(iir) and _iir_id(iir) == expect:
                return True
            await Timer(100, unit="ns")
        return False

    async def _test_parity(self) -> None:
        if "smc_uart_cross_3to0" not in cocotb.plusargs:
            raise AssertionError(
                "smc_uart_error_conditions_test parity requires +smc_uart_cross_3to0"
            )
        ctrl = _uart_regs(3)
        tgt = _uart_regs(0)
        await self._enable(3)
        await self._enable(0)
        # UART3 odd, UART0 even → PE on UART0.
        await self._program_format(ctrl, "C3", pen=True, eps=False)
        await self._program_format(tgt, "T0", pen=True, eps=True)
        await self._clear_status(ctrl, "C3")
        await self._clear_status(tgt, "T0")

        for i, tx in enumerate((0x00, 0xFF, 0x55, 0xAA)):
            await self.csr_write(f"PE_TX_{i}", ctrl["rbr"], tx)
            saw_pe = False
            saw_lsr_irq = False
            for _ in range(512):
                lsr = await self.csr_read(f"PE_LSR_{i}", tgt["lsr"])
                if lsr & LSR_PE:
                    saw_pe = True
                iir = await self.csr_read(f"PE_IIR_{i}", tgt["iir"])
                if _iir_pending(iir) and _iir_id(iir) == _INTR_LSR:
                    saw_lsr_irq = True
                if saw_pe and saw_lsr_irq:
                    break
                await Timer(100, unit="ns")
            if not saw_pe:
                raise AssertionError(f"parity PE not seen for byte 0x{tx:02x}")
            if not saw_lsr_irq:
                raise AssertionError(f"parity LSR IRQ not seen for byte 0x{tx:02x}")
            await self.csr_read(f"PE_POP_{i}", tgt["rbr"])
        cocotb.log.info("CHK-UART-ERR-PE: mismatch PE + LSR IRQ on UART0")

        # Matching even parity: no PE/FE/BI.
        await self._program_format(ctrl, "C3E", pen=True, eps=True)
        await self._program_format(tgt, "T0E", pen=True, eps=True)
        await self._clear_status(ctrl, "C3E")
        await self._clear_status(tgt, "T0E")
        for i, tx in enumerate((0x00, 0xFF, 0x55, 0xAA)):
            await self.csr_write(f"OK_TX_{i}", ctrl["rbr"], tx)
            if not await self._wait_iir_id(tgt, f"OK_RDR_{i}", _INTR_RDR, 64):
                raise AssertionError(f"matched parity missing RDR for 0x{tx:02x}")
            lsr = await self.csr_read(f"OK_LSR_{i}", tgt["lsr"])
            if lsr & (LSR_PE | LSR_FE | LSR_BI):
                raise AssertionError(f"matched parity unexpected err LSR=0x{lsr:08x}")
            await self.csr_read(f"OK_POP_{i}", tgt["rbr"])
        cocotb.log.info("CHK-UART-ERR-PE-NEG: matched even parity clean")

    async def _test_overrun(self) -> None:
        r = _uart_regs(0)
        await self._enable(0)
        await self._program_format(r, "OE", loop=True)
        await self._clear_status(r, "OE")

        # Below-threshold control for the OE claim below: one byte cannot
        # overflow a FIFO of _FIFO_DEPTH, so DR must set and OE must stay clear.
        # It puts OE=0 in the run alongside the OE=1 the overflow leg produces,
        # which a bit stuck at 1 or a constant LSR read cannot do.
        await self.csr_write("OE_NEG_THR", r["rbr"], 0x5A)
        if not await self._wait_iir_id(r, "OE_NEG_RDR", _INTR_RDR, 512):
            raise AssertionError("single byte produced no RDR interrupt")
        lsr = await self.csr_read("OE_NEG_LSR", r["lsr"])
        if not lsr & LSR_DR:
            raise AssertionError(f"single byte left LSR.DR clear LSR=0x{lsr:08x}")
        if lsr & LSR_OE:
            raise AssertionError(f"single byte set LSR.OE LSR=0x{lsr:08x}")
        cocotb.log.info("CHK-UART-ERR-OE-NEG: one byte -> LSR.DR=1 LSR.OE=0 (LSR=0x%08x)", lsr)
        await self._clear_status(r, "OE")

        total = _FIFO_DEPTH + 4
        for i in range(total):
            await self.csr_write(f"OE_THR_{i}", r["rbr"], 0x20 + (i & 0x3F))
            if not await self._wait_iir_id(r, f"OE_RDR_{i}", _INTR_RDR, 512):
                raise AssertionError(f"overrun path missing RDR after write {i}")
        saw_oe = False
        for _ in range(1024):
            lsr = await self.csr_read("OE_POLL", r["lsr"])
            if lsr & LSR_OE:
                saw_oe = True
                break
            await Timer(100, unit="ns")
        if not saw_oe:
            raise AssertionError("LSR.OE never set after FIFO overflow")
        if not await self._wait_iir_id(r, "OE_LSR", _INTR_LSR, 32):
            raise AssertionError("overrun missing LSR interrupt")
        for _ in range(64):
            lsr = await self.csr_read("OE_DRAIN_LSR", r["lsr"])
            if not (lsr & LSR_DR):
                break
            await self.csr_read("OE_DRAIN_RBR", r["rbr"])
        lsr = await self.csr_read("OE_POST", r["lsr"])
        if lsr & LSR_OE:
            raise AssertionError(f"LSR.OE sticky after drain LSR=0x{lsr:08x}")
        cocotb.log.info("CHK-UART-ERR-OE: overrun OE + LSR IRQ then clear")

    async def _test_break(self) -> None:
        r = _uart_regs(0)
        await self._enable(0)
        await self._program_format(r, "BRK", loop=True)
        await self._clear_status(r, "BRK")
        lsr = await self.csr_read("BRK_PRE", r["lsr"])
        if lsr & (LSR_FE | LSR_BI):
            raise AssertionError(f"FE/BI set before break LSR=0x{lsr:08x}")
        await self.csr_write("BRK_SET", r["lcr"], LCR_WLS | LCR_SET_BREAK)
        saw_bi = False
        for _ in range(128):
            lsr = await self.csr_read("BRK_POLL", r["lsr"])
            if lsr & LSR_BI:
                saw_bi = True
                break
            await Timer(1, unit="us")
        if not saw_bi:
            raise AssertionError("LSR.BI never set under SET_BREAK loopback")
        if not await self._wait_iir_id(r, "BRK_LSR", _INTR_LSR, 32):
            raise AssertionError("break missing LSR interrupt")
        await self.csr_write("BRK_CLR", r["lcr"], LCR_WLS)
        lsr = 0
        for _ in range(256):
            lsr = await self.csr_read("BRK_CLR_LSR", r["lsr"])
            await self.csr_read("BRK_CLR_RBR", r["rbr"])
            await self.csr_read("BRK_CLR_IIR", r["iir"])
            if not (lsr & (LSR_FE | LSR_BI)):
                break
            await Timer(100, unit="ns")
        else:
            raise AssertionError(f"FE/BI sticky after break clear LSR=0x{lsr:08x}")
        lsr = await self.csr_read("BRK_POST", r["lsr"])
        if lsr & (LSR_FE | LSR_BI):
            raise AssertionError(f"FE/BI reappeared after clear LSR=0x{lsr:08x}")
        cocotb.log.info("CHK-UART-ERR-BI: SET_BREAK BI + LSR IRQ then clear")

    # ---- UART1-3 legs (contract SMC_UART_ERROR_CONDITIONS S1-S11) ----

    def _step(self, step_id: str) -> None:
        self.stamps.append((step_id, int(get_sim_time("ps"))))

    def _chk(self, chk_id: str, step_id: str, text: str, *args) -> None:
        assert self.stamps and self.stamps[-1][0] == step_id, (
            f"{chk_id} printed before its step {step_id} completed; stamps {self.stamps}"
        )
        self.chk_marks.append((chk_id, len(self.stamps)))
        cocotb.log.info("%s: " + text, chk_id, *args)

    def _wait(self, name: str, bound: str) -> None:
        self.waits.setdefault(name, [bound, "not reached"])

    def _end(self, name: str, state: str) -> None:
        self.waits[name][1] = state

    def _line(self, idx: int) -> int:
        value = self.dut.tb_uart_irq_combined.value
        assert value.is_resolvable, f"tb_uart_irq_combined is X/Z ({value})"
        return (int(value) >> idx) & 1

    def _state(self, idx: int) -> str:
        lsr = self.last_lsr.get(idx, -1)
        iir = self.last_iir.get(idx, -1)
        return f"UART{idx} last LSR=0x{lsr:x} last IIR=0x{iir:x} line={self._line(idx)}"

    async def _wr(self, idx: int, reg: str, label: str, data: int) -> None:
        await self.csr_write(f"U{idx}_{label}", self.u[idx][reg], data)

    async def _lsr(self, idx: int, label: str) -> int:
        self.last_lsr[idx] = await self.csr_read(f"U{idx}_{label}_LSR", self.u[idx]["lsr"])
        return self.last_lsr[idx]

    async def _iir(self, idx: int, label: str) -> int:
        self.last_iir[idx] = await self.csr_read(f"U{idx}_{label}_IIR", self.u[idx]["iir"])
        return self.last_iir[idx]

    async def _rbr(self, idx: int, label: str) -> int:
        return (await self.csr_read(f"U{idx}_{label}_RBR", self.u[idx]["rbr"])) & RBR_DATA

    async def _poll_lsr(self, idx: int, label: str, mask: int, *, every: bool = False) -> int:
        """Read LSR until any (or, with ``every``, all) of ``mask`` reads 1."""
        name = f"{label}:LSR_{'all' if every else 'any'}_0x{mask:x}"
        self._wait(name, f"{POLL_LIMIT} LSR reads")
        for n in range(POLL_LIMIT):
            lsr = await self._lsr(idx, f"{label}_POLL")
            if (lsr & mask == mask) if every else (lsr & mask):
                self._end(name, f"UART{idx} LSR=0x{lsr:x} after {n + 1} reads")
                return lsr
        raise AssertionError(
            f"{label}: UART{idx} LSR mask 0x{mask:x} never set in {POLL_LIMIT} reads; "
            f"{self._state(idx)}"
        )

    async def _poll_iir_pending(self, idx: int, label: str) -> int:
        name = f"{label}:IIR_pending"
        self._wait(name, f"{POLL_LIMIT} IIR reads")
        for n in range(POLL_LIMIT):
            iir = await self._iir(idx, f"{label}_POLL")
            if _iir_pending(iir):
                self._end(name, f"UART{idx} IIR=0x{iir:x} after {n + 1} reads")
                return iir
        raise AssertionError(
            f"{label}: UART{idx} reported no interrupt in {POLL_LIMIT} reads; {self._state(idx)}"
        )

    async def _drain(self, idx: int, label: str) -> list[int]:
        name = f"{label}:RBR_drain"
        self._wait(name, f"{DRAIN_LIMIT} LSR+RBR read pairs")
        chars: list[int] = []
        for _ in range(DRAIN_LIMIT):
            lsr = await self._lsr(idx, f"{label}_DRAIN")
            if not lsr & LSR_DR:
                self._end(name, f"UART{idx} LSR=0x{lsr:x} after {len(chars)} RBR reads")
                return chars
            chars.append(await self._rbr(idx, f"{label}_DRAIN"))
        raise AssertionError(f"{label}: UART{idx} RBR never emptied; {self._state(idx)}")

    async def _collect(
        self,
        receivers: tuple[int, ...],
        label: str,
        window_clocks: int,
        senders: tuple[int, ...] = (),
    ) -> dict[int, list[int]]:
        """Read every character the receivers take until each sender reads LSR.TEMT=1, then
        for a further ``window_clocks`` clk_periph cycles, then until their FIFOs are empty."""
        got: dict[int, list[int]] = {r: [] for r in receivers}

        async def take() -> None:
            for r in receivers:
                lsr = await self._lsr(r, f"{label}_RX")
                if lsr & LSR_DR:
                    got[r].append(await self._rbr(r, f"{label}_RX"))

        name = f"{label}:sender_TEMT"
        if senders:
            self._wait(name, f"{COLLECT_LIMIT} receive rounds")
        pending = set(senders)
        rounds = 0
        while pending:
            rounds += 1
            assert rounds <= COLLECT_LIMIT, (
                f"{label}: senders {sorted(pending)} never read LSR.TEMT=1 in {COLLECT_LIMIT} "
                f"rounds; received {got}; " + "; ".join(self._state(s) for s in sorted(pending))
            )
            await take()
            for s in sorted(pending):
                if (await self._lsr(s, f"{label}_TX")) & LSR_TEMT:
                    pending.discard(s)
        if senders:
            self._end(name, f"senders {list(senders)} TEMT after {rounds} rounds")

        done: list[int] = []

        async def window() -> None:
            await ClockCycles(self.dut.clk_periph, window_clocks)
            done.append(1)

        timer = cocotb.start_soon(window())
        while not done:
            await take()
        await timer
        self.windows[f"{label}:receive_window"] = (
            f"{window_clocks} clk_periph cycles, last received {got}"
        )
        for r in receivers:
            got[r].extend(await self._drain(r, f"{label}_COLLECT"))
        return got

    async def _set_divisor(self, idx: int, label: str, divisor: int) -> None:
        await self._wr(idx, "lcr", f"{label}_LCR_DLAB", LCR_DLAB | LCR_8N1)
        await self._wr(idx, "dll", f"{label}_DLL", divisor & 0xFF)
        await self._wr(idx, "dlm", f"{label}_DLM", (divisor >> 8) & 0xFF)
        await self._wr(idx, "lcr", f"{label}_LCR", LCR_8N1)

    async def _quiet(self, idx: int, label: str) -> None:
        """Drain the receiver and read LSR until no line-status error remains."""
        name = f"{label}:line_status_quiet"
        self._wait(name, f"{DRAIN_LIMIT} LSR reads")
        for n in range(DRAIN_LIMIT):
            lsr = await self._lsr(idx, f"{label}_QUIET")
            if not lsr & (LSR_DR | LSR_LINE_STATUS):
                self._end(name, f"UART{idx} LSR=0x{lsr:x} after {n + 1} reads")
                return
            if lsr & LSR_DR:
                await self._rbr(idx, f"{label}_QUIET")
        raise AssertionError(f"{label}: UART{idx} line status never quiet; {self._state(idx)}")

    async def _s1(self) -> None:
        if "smc_uart_cross_3to0" not in cocotb.plusargs:
            raise AssertionError("the UART1-3 legs require +smc_uart_cross_3to0")
        assert hasattr(self.dut, "tb_uart_irq_combined"), "tb_top has no tb_uart_irq_combined"
        assert hasattr(self.dut, "clk_periph"), "tb_top has no clk_periph net"
        fcr = FCR_FIFO_ENABLE | FCR_RCVR_FIFO_RESET | FCR_XMIT_FIFO_RESET
        for idx in range(4):
            await self._wr(idx, "ctrl", "S1_EN", UART_EN)
            await self._wr(idx, "ier", "S1_IER", 0)
            await self._wr(idx, "itr", "S1_ITR", 0)
            await self._wr(idx, "mcr", "S1_MCR", 0)
            await self._set_divisor(idx, "S1", DIVISOR)
            await self._wr(idx, "fcr", "S1_FCR", fcr)
        for idx in range(4):
            await self._quiet(idx, "S1")
        for idx in RECEIVERS:
            iir = await self._iir(idx, "S1")
            lsr = await self._lsr(idx, "S1")
            assert iir == IIR_NONE and lsr == LSR_IDLE, (
                f"S1: UART{idx} IIR=0x{iir:x} LSR=0x{lsr:x} after setup; "
                f"IIR=0x{IIR_NONE:x} and LSR=0x{LSR_IDLE:x} were required"
            )
        self._step("S1")

    async def _line_error_leg(
        self, kind: str, rx: int, elsi: bool, err: int, send, absent: int = 0
    ) -> str:
        """One receive-error leg on ``rx``; ``send`` starts the faulty frame from the peer."""
        tx = PEER[rx]
        tag = f"{kind}_{'ELSI' if elsi else 'NOELSI'}"
        await self._wr(rx, "ier", f"{tag}_IER", IER_ELSI if elsi else IER_ERBFI)
        await send(tx, tag)
        name = f"{tag}_SENDER:LSR_any_0x{LSR_TEMT:x}"
        self._wait(name, f"{POLL_LIMIT} LSR reads")
        for k in range(POLL_LIMIT):
            lsr_tx = await self._lsr(tx, f"{tag}_SENDER_POLL")
            assert not lsr_tx & LSR_LINE_STATUS, (
                f"{tag}: UART{tx} (sending, not receiving) LSR=0x{lsr_tx:x} has line-status "
                f"bits 4:1 set"
            )
            if lsr_tx & LSR_TEMT:
                self._end(name, f"UART{tx} LSR=0x{lsr_tx:x} after {k + 1} reads")
                break
        else:
            raise AssertionError(
                f"{tag}: UART{tx} LSR.TEMT never set in {POLL_LIMIT} reads; {self._state(tx)}"
            )
        iir = await self._poll_iir_pending(rx, tag)
        lsr1 = await self._lsr(rx, f"{tag}_FIRST")
        others = {o: await self._lsr(o, f"{tag}_OTHER") for o in RECEIVERS if o != rx}
        line = self._line(rx)
        lsr2 = await self._lsr(rx, f"{tag}_SECOND")
        if elsi:
            assert iir == IIR_LSR, (
                f"{tag}: UART{rx} IIR=0x{iir:x} with the error pending and ELSI=1; "
                f"0x{IIR_LSR:x} was required"
            )
        else:
            assert iir == IIR_RDR, (
                f"{tag}: UART{rx} IIR=0x{iir:x} with IER=ERBFI only and the erroring character "
                f"received; 0x{IIR_RDR:x} (ID 0x2, no ID 0x3 with ELSI=0) was required"
            )
        assert lsr1 & err == err, (
            f"{tag}: UART{rx} first LSR=0x{lsr1:x} lacks the error bits 0x{err:x}"
        )
        assert not lsr1 & absent, f"{tag}: UART{rx} first LSR=0x{lsr1:x} has bits 0x{absent:x}"
        for o, lsr in others.items():
            assert not lsr & LSR_LINE_STATUS, (
                f"{tag}: UART{o} (not receiving) LSR=0x{lsr:x} has line-status bits 4:1 set"
            )
        got = await self._collect((rx,), tag, FRAME_CLOCKS, (tx,))
        lsr3 = await self._lsr(rx, f"{tag}_DRAINED")
        assert not lsr3 & LSR_RX_ERRORS, (
            f"{tag}: UART{rx} LSR=0x{lsr3:x} still has error bits 4:2 after the RBR drain"
        )
        await self._wr(rx, "ier", f"{tag}_IER_OFF", 0)
        self.rc_rows.append(f"U{rx}:{tag}:first=0x{lsr1:x},second=0x{lsr2:x},drained=0x{lsr3:x}")
        return (
            f"U{rx}(from U{tx}) ELSI={int(elsi)} IIR=0x{iir:x} LSR first=0x{lsr1:x} "
            f"second(measured, SF-041)=0x{lsr2:x} after drain=0x{lsr3:x} "
            f"others={','.join(f'U{o}=0x{v:x}' for o, v in others.items())} line={line} "
            f"chars={[f'0x{c:02x}' for c in got[rx]]}"
        )

    async def _send_break(self, tx: int, tag: str) -> None:
        await self._wr(tx, "lcr", f"{tag}_BREAK_ON", LCR_8N1 | LCR_SET_BREAK)
        await ClockCycles(self.dut.clk_periph, BREAK_CLOCKS)
        await self._wr(tx, "lcr", f"{tag}_BREAK_OFF", LCR_8N1)

    async def _send_parity(self, tx: int, tag: str) -> None:
        await self._wr(tx, "thr", f"{tag}_THR", PARITY_CHAR)

    async def _send_framing(self, tx: int, tag: str) -> None:
        await self._wr(tx, "thr", f"{tag}_THR", FRAMING_CHAR)

    async def _s2(self) -> None:
        rows = []
        for rx in RECEIVERS:
            for elsi in (True, False):
                rows.append(
                    await self._line_error_leg(
                        "S2_BI",
                        rx,
                        elsi,
                        LSR_BI | (LSR_ERROR_IN_RCVR_FIFO if elsi else 0),
                        self._send_break,
                    )
                )
        self._step("S2")
        self._chk(
            "CHK-UART13-BREAK",
            "S2",
            "a %d-clk_periph break from each peer gave BI=1 (ERROR_IN_RCVR_FIFO=1 and "
            "IIR=0x%x with ELSI=1, no ID 0x3 with ELSI=0) and LSR bits 4:2 = 0 after the RBR "
            "drain; the other receivers read LSR bits 4:1 = 0; line, break character count and "
            "the second LSR read before the drain measured (LINKED-ISSUE SF-001, SF-021, "
            "SF-041): %s",
            BREAK_CLOCKS,
            IIR_LSR,
            " | ".join(rows),
        )

    async def _s3(self) -> None:
        rows = []
        for rx in RECEIVERS:
            tx = PEER[rx]
            await self._wr(rx, "lcr", "S3_LCR_RX", LCR_8E1)
            await self._wr(tx, "lcr", "S3_LCR_TX", LCR_8O1)
            for elsi in (True, False):
                rows.append(
                    await self._line_error_leg("S3_PE", rx, elsi, LSR_PE, self._send_parity)
                )
            await self._wr(rx, "lcr", "S3_LCR_RX_8N1", LCR_8N1)
            await self._wr(tx, "lcr", "S3_LCR_TX_8N1", LCR_8N1)
        self._step("S3")
        self._chk(
            "CHK-UART13-PARITY",
            "S3",
            "0x%02x sent odd parity into an even-parity receiver gave PE=1 (IIR=0x%x with "
            "ELSI=1, no ID 0x3 with ELSI=0) and LSR bits 4:2 = 0 after the RBR drain; the other "
            "receivers read PE=0; line and the second LSR read before the drain measured "
            "(LINKED-ISSUE SF-001, SF-041): %s",
            PARITY_CHAR,
            IIR_LSR,
            " | ".join(rows),
        )

    async def _s4(self) -> None:
        rows = []
        for rx in RECEIVERS:
            tx = PEER[rx]
            await self._wr(rx, "lcr", "S4_LCR_RX", LCR_5N1)
            await self._wr(tx, "lcr", "S4_LCR_TX", LCR_8N1)
            for elsi in (True, False):
                rows.append(
                    await self._line_error_leg(
                        "S4_FE", rx, elsi, LSR_FE, self._send_framing, absent=LSR_BI
                    )
                )
            await self._wr(rx, "lcr", "S4_LCR_RX_8N1", LCR_8N1)
        self._step("S4")
        self._chk(
            "CHK-UART13-FRAMING",
            "S4",
            "8N1 0x%02x into a 5-bit receiver put 0 at its stop position: FE=1 with BI=0 "
            "(IIR=0x%x with ELSI=1, no ID 0x3 with ELSI=0) and LSR bits 4:2 = 0 after the RBR "
            "drain; line and the second LSR read before the drain measured (LINKED-ISSUE "
            "SF-001, SF-041): %s",
            FRAMING_CHAR,
            IIR_LSR,
            " | ".join(rows),
        )
        self._chk(
            "CHK-UART13-LSR-RC",
            "S4",
            "%d legs (BI, PE, FE x ELSI on/off x UART1-3): the first LSR read carried the error "
            "and the LSR read after the RBR drain returned bits 4:2 = 0; the second LSR read "
            "before the drain measured (LINKED-ISSUE gate T_impl_uart_err-s2-dut / SF-041): %s",
            len(self.rc_rows),
            ", ".join(self.rc_rows),
        )

    async def _s5(self) -> None:
        rows = []
        for n in RECEIVERS:
            p = PEER[n]
            await self._wr(n, "mcr", "S5_LOOP_ON", MCR_LOOP)
            await self._wr(n, "thr", "S5_THR_LOOP", LOOP_CHAR)
            lsr_n = await self._poll_lsr(n, "S5_LOOP", LSR_DR | LSR_TEMT, every=True)
            got_n = await self._rbr(n, "S5_LOOP")
            lsr_p = await self._lsr(p, "S5_LOOP_PEER")
            assert got_n == LOOP_CHAR, (
                f"S5: UART{n} looped RBR=0x{got_n:02x}, not 0x{LOOP_CHAR:02x}"
            )
            assert not lsr_p & LSR_DR, (
                f"S5: the looped byte reached UART{p}: LSR=0x{lsr_p:x} reads DR=1"
            )
            await self._wr(n, "mcr", "S5_LOOP_OFF", 0)
            await self._wr(n, "thr", "S5_THR_LINE", UNLOOP_CHAR)
            lsr_p2 = await self._poll_lsr(p, "S5_LINE_PEER", LSR_DR)
            got_p = await self._rbr(p, "S5_LINE_PEER")
            lsr_n2 = await self._lsr(n, "S5_LINE_OWN")
            assert got_p == UNLOOP_CHAR, (
                f"S5: UART{p} RBR=0x{got_p:02x} with LOOP=0, not 0x{UNLOOP_CHAR:02x}"
            )
            assert not lsr_n2 & LSR_DR, (
                f"S5: the unlooped byte appeared in UART{n}: LSR=0x{lsr_n2:x} reads DR=1"
            )
            await self._collect((n, p), "S5", FRAME_CLOCKS, (n,))
            rows.append(
                f"U{n}: LOOP=1 LSR=0x{lsr_n:x} RBR=0x{got_n:02x} peer U{p} LSR=0x{lsr_p:x}; "
                f"LOOP=0 peer LSR=0x{lsr_p2:x} RBR=0x{got_p:02x} own LSR=0x{lsr_n2:x}"
            )
        self._step("S5")
        self._chk(
            "CHK-UART13-MCR-LOOP",
            "S5",
            "with LOOP=1 each instance read back 0x%02x with DR=1 while its peer read DR=0; "
            "with LOOP=0 the peer read 0x%02x while the instance read DR=0: %s",
            LOOP_CHAR,
            UNLOOP_CHAR,
            " | ".join(rows),
        )

    async def _s6(self) -> None:
        rows = []
        for n in RECEIVERS:
            await self._wr(n, "mcr", "S6_MCR_MODEM", MCR_MODEM_OUT)
            await self._wr(n, "mcr", "S6_MCR_CLR", 0)
            await self._wr(n, "ier", "S6_IER", IER_ETBEI)
            await self._wr(n, "itr", "S6_ITR", ITR_TTBEI)
            await self._wr(n, "mcr", "S6_OUT2_ON", MCR_OUT2)
            iir_on = await self._iir(n, "S6_OUT2_ON")
            line_on = self._line(n)
            await self._wr(n, "mcr", "S6_OUT2_OFF", 0)
            iir_off = await self._iir(n, "S6_OUT2_OFF")
            line_off = self._line(n)
            await self._wr(n, "itr", "S6_ITR_OFF", 0)
            await self._wr(n, "ier", "S6_IER_OFF", 0)
            assert iir_on == IIR_THRE and iir_off == IIR_THRE, (
                f"S6: UART{n} IIR=0x{iir_on:x} after OUT2=1 and 0x{iir_off:x} after OUT2=0 "
                f"with ITR.TTBEI forcing; 0x{IIR_THRE:x} was required after each"
            )
            rows.append(
                f"U{n}: IIR OUT2=1 0x{iir_on:x} line={line_on} OUT2=0 0x{iir_off:x} line={line_off}"
            )
        self._step("S6")
        self._chk(
            "CHK-UART13-OUT2-IIR",
            "S6",
            "after MCR=0x%02x then 0x00 (stimulus only, SF-042), with ITR.TTBEI forcing IIR "
            "read 0x%x after each MCR.OUT2 write; line measured (LINKED-ISSUE SF-001): %s",
            MCR_MODEM_OUT,
            IIR_THRE,
            " | ".join(rows),
        )

    async def _s7(self) -> None:
        rows = []
        for n in RECEIVERS:
            p = PEER[n]
            await self._wr(n, "ier", "S7_IER", IER_ETBEI)
            await self._wr(n, "thr", "S7_THR_ARM", THRE_ARM_CHAR)
            await self._poll_lsr(n, "S7_ARM", LSR_TEMT)
            first = await self._iir(n, "S7_FIRST")
            second = await self._iir(n, "S7_SECOND")
            lsr = await self._lsr(n, "S7_EMPTY")
            assert first == IIR_THRE and second == IIR_NONE and lsr & LSR_THRE, (
                f"S7: UART{n} IIR 0x{first:x} then 0x{second:x}, LSR=0x{lsr:x} with the TX "
                f"FIFO empty; 0x{IIR_THRE:x}, 0x{IIR_NONE:x} and LSR.THRE=1 were required"
            )
            await self._wr(n, "thr", "S7_THR", THRE_CHAR)
            await self._poll_lsr(n, "S7_DRAIN", LSR_TEMT)
            drained = await self._iir(n, "S7_DRAINED")
            assert drained == IIR_THRE, (
                f"S7: UART{n} IIR=0x{drained:x} after 0x{THRE_CHAR:02x} drained; "
                f"0x{IIR_THRE:x} was required"
            )
            await self._collect((p,), "S7_TX", FRAME_CLOCKS)
            await self._wr(n, "ier", "S7_IER_LSR", IER_ETBEI | IER_ELSI)
            await self._wr(n, "lcr", "S7_LCR_RX", LCR_8E1)
            await self._wr(p, "lcr", "S7_LCR_TX", LCR_8O1)
            await self._wr(p, "thr", "S7_THR_PE", PARITY_CHAR)
            raised = await self._poll_iir_pending(n, "S7_PE")
            await self._wr(n, "thr", "S7_THR_REARM", THRE_ARM_CHAR)
            both = await self._iir(n, "S7_BOTH")
            lsr_pe = await self._lsr(n, "S7_PE")
            after = await self._iir(n, "S7_AFTER")
            assert raised == IIR_LSR and both == IIR_LSR, (
                f"S7: UART{n} IIR 0x{raised:x} / 0x{both:x} with a parity error pending; "
                f"0x{IIR_LSR:x} was required"
            )
            assert lsr_pe & LSR_PE, f"S7: UART{n} LSR=0x{lsr_pe:x} lacks PE"
            rx = await self._drain(n, "S7_PE")
            lsr_drained = await self._lsr(n, "S7_DRAINED")
            serviced = await self._iir(n, "S7_SERVICED")
            assert serviced == IIR_THRE, (
                f"S7: UART{n} IIR=0x{serviced:x} after the RBR drain and LSR read "
                f"(LSR=0x{lsr_drained:x}) with THRE pending; 0x{IIR_THRE:x} was required"
            )
            await self._wr(n, "ier", "S7_IER_OFF", 0)
            got = await self._collect((n, p), "S7_PE", FRAME_CLOCKS, (n, p))
            await self._wr(n, "lcr", "S7_LCR_RX_8N1", LCR_8N1)
            await self._wr(p, "lcr", "S7_LCR_TX_8N1", LCR_8N1)
            await self._quiet(p, "S7")
            rows.append(
                f"U{n}: empty IIR 0x{first:x},0x{second:x} LSR=0x{lsr:x}; drained IIR "
                f"0x{drained:x}; PE IIR 0x{raised:x},0x{both:x} LSR=0x{lsr_pe:x} IIR after the "
                f"LSR read (measured, SF-041) 0x{after:x}; drained "
                f"{[f'0x{c:02x}' for c in rx + got[n]]} LSR=0x{lsr_drained:x} IIR 0x{serviced:x}"
            )
        self._step("S7")
        self._chk(
            "CHK-UART13-IIR-THRE",
            "S7",
            "with ETBEI=1 and the TX FIFO empty IIR read 0x%x then 0x%x with LSR.THRE=1, "
            "0x%x again after a character drained, and with a parity error also pending "
            "0x%x, then 0x%x after the RBR drain and an LSR read; the IIR read right after "
            "the first LSR read measured (LINKED-ISSUE gate T_impl_uart_err-s2-dut / "
            "SF-041): %s",
            IIR_THRE,
            IIR_NONE,
            IIR_THRE,
            IIR_LSR,
            IIR_THRE,
            " | ".join(rows),
        )

    async def _s8(self) -> None:
        rows = []
        for n in RECEIVERS:
            p = PEER[n]
            await self._wr(n, "ier", "S8_IER", IER_ETBEI)
            for i, char in enumerate(ITR_CHARS):
                await self._wr(n, "thr", f"S8_THR_{i}", char)
            lsr = await self._lsr(n, "S8_BUSY")
            assert not lsr & LSR_THRE, (
                f"S8: UART{n} LSR=0x{lsr:x} reads THRE=1 with {len(ITR_CHARS)} characters "
                f"queued; the TX FIFO was required non-empty for the ITR reads"
            )
            await self._wr(n, "itr", "S8_ITR_ON", ITR_TTBEI)
            forced = await self._iir(n, "S8_FORCED")
            line_forced = self._line(n)
            await self._wr(n, "itr", "S8_ITR_OFF", 0)
            released = await self._iir(n, "S8_RELEASED")
            line_released = self._line(n)
            assert forced == IIR_THRE and released == IIR_NONE, (
                f"S8: UART{n} IIR 0x{forced:x} with ITR.TTBEI=1 and 0x{released:x} after "
                f"ITR=0; 0x{IIR_THRE:x} and 0x{IIR_NONE:x} were required"
            )
            await self._wr(n, "ier", "S8_IER_OFF", 0)
            got = await self._collect((p,), "S8", FRAME_CLOCKS, (n,))
            rows.append(
                f"U{n}: IIR forced 0x{forced:x} line={line_forced} released 0x{released:x} "
                f"line={line_released} LSR=0x{lsr:x} peer rx {[f'0x{c:02x}' for c in got[p]]}"
            )
        self._step("S8")
        self._chk(
            "CHK-UART13-ITR-THRE",
            "S8",
            "with %d characters queued (LSR.THRE=0) ITR.TTBEI=1 made IIR read 0x%x and ITR=0 "
            "made it read 0x%x; line measured (LINKED-ISSUE SF-001): %s",
            len(ITR_CHARS),
            IIR_THRE,
            IIR_NONE,
            " | ".join(rows),
        )

    async def _s9(self) -> None:
        rows = []
        for n in RECEIVERS:
            p = PEER[n]
            await self._wr(p, "thr", "S9_THR_HELD", XMIT_HELD_CHAR)
            await self._poll_lsr(n, "S9_HELD", LSR_DR)
            for i, char in enumerate(XMIT_CHARS):
                await self._wr(n, "thr", f"S9_THR_{i}", char)
            await self._wr(n, "fcr", "S9_FCR_XMIT_RESET", FCR_FIFO_ENABLE | FCR_XMIT_FIFO_RESET)
            lsr = await self._lsr(n, "S9_RESET")
            got = await self._collect((p,), "S9", XMIT_WINDOW_CLOCKS)
            lsr_rx = await self._lsr(n, "S9_HELD_AFTER")
            held = await self._rbr(n, "S9_HELD")
            assert lsr & LSR_THRE, f"S9: UART{n} LSR=0x{lsr:x} reads THRE=0 after the TX reset"
            assert len(got[p]) <= 1 and all(c == XMIT_CHARS[0] for c in got[p]), (
                f"S9: UART{p} received {[hex(c) for c in got[p]]} after the TX reset; at most "
                f"one character, 0x{XMIT_CHARS[0]:02x}, was allowed"
            )
            assert lsr_rx & LSR_DR and held == XMIT_HELD_CHAR, (
                f"S9: UART{n} LSR=0x{lsr_rx:x} RBR=0x{held:02x} after the TX reset; DR=1 and "
                f"0x{XMIT_HELD_CHAR:02x} were required"
            )
            await self._poll_lsr(n, "S9_IDLE", LSR_TEMT)
            rows.append(
                f"U{n}: LSR=0x{lsr:x} peer U{p} rx {[f'0x{c:02x}' for c in got[p]]} "
                f"own LSR=0x{lsr_rx:x} RBR=0x{held:02x}"
            )
        self._step("S9")
        self._chk(
            "CHK-UART13-XMIT-RESET",
            "S9",
            "after %d THR writes and FCR.XMIT_FIFO_RESET LSR.THRE read 1, each peer received "
            "at most 0x%02x in %d clk_periph cycles, and the held byte 0x%02x stayed: %s",
            len(XMIT_CHARS),
            XMIT_CHARS[0],
            XMIT_WINDOW_CLOCKS,
            XMIT_HELD_CHAR,
            " | ".join(rows),
        )

    async def _access(self, idx: int, label: str, reg: str, op: SmcSysAxiOp, data: int = 0):
        item = SmcSysAxiItem(f"U{idx}_{label}")
        item.op = op
        item.addr = self.u[idx][reg]
        item.length = 4
        item.wdata = data
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        return item

    async def _s10(self) -> None:
        rows = []
        for idx in range(4):
            await self._set_divisor(idx, "S10", FIFO_ACCESS_DIVISOR)
        for group in FIFO_ACCESS_GROUPS:
            obs: dict[int, str] = {}
            for n in group:
                edges: list[int] = [0]
                stop: list[int] = []

                async def count() -> None:
                    while not stop:
                        await RisingEdge(self.dut.clk_periph)
                        edges[0] += 1

                counter = cocotb.start_soon(count())
                resps = []
                for i, char in enumerate(FIFO_ACCESS_CHARS):
                    item = await self._access(n, f"S10_THR_{i}", "thr", SmcSysAxiOp.WRITE, char)
                    resps.append(item.resp_code)
                stop.append(1)
                await counter
                iir = await self._iir(n, "S10_FULL")
                lsr = await self._lsr(n, "S10_FULL")
                line = self._line(n)
                assert all(r is not None for r in resps), f"S10: UART{n} THR resp {resps}"
                assert edges[0] < FIFO_ACCESS_FRAME_CLOCKS, (
                    f"S10: {len(FIFO_ACCESS_CHARS)} THR writes took {edges[0]} clk_periph "
                    f"cycles, not inside one {FIFO_ACCESS_FRAME_CLOCKS}-cycle frame"
                )
                obs[n] = (
                    f"U{n}: {len(resps)} THR writes in {edges[0]} cycles resp "
                    f"{sorted(set(resps))} last={resps[-1]} IIR=0x{iir:x} LSR=0x{lsr:x} line={line}"
                )
            got = await self._collect(
                tuple(PEER[n] for n in group), "S10", FIFO_ACCESS_FRAME_CLOCKS, group
            )
            for n in group:
                p = PEER[n]
                pre = await self._lsr(n, "S10_EMPTY")
                assert not pre & LSR_DR, f"S10: UART{n} RX FIFO not empty, LSR=0x{pre:x}"
                item = await self._access(n, "S10_RBR_EMPTY", "rbr", SmcSysAxiOp.READ)
                lsr = await self._lsr(n, "S10_UNDERFLOW")
                iir = await self._iir(n, "S10_UNDERFLOW")
                line = self._line(n)
                assert not lsr & LSR_DR, (
                    f"S10: UART{n} LSR=0x{lsr:x} reads DR=1 after the empty RBR read"
                )
                chars = got[p]
                rows.append(
                    f"{obs[n]}; peer U{p} received {len(chars)} chars first=0x{chars[0]:02x} "
                    f"last=0x{chars[-1]:02x} missing="
                    f"{[f'0x{c:02x}' for c in FIFO_ACCESS_CHARS if c not in chars]}; "
                    f"empty RBR resp={item.resp_code} data=0x{item.rdata:x} LSR=0x{lsr:x} "
                    f"IIR=0x{iir:x} line={line}"
                    if chars
                    else f"{obs[n]}; peer U{p} received nothing; empty RBR resp={item.resp_code} "
                    f"data=0x{item.rdata:x} LSR=0x{lsr:x} IIR=0x{iir:x} line={line}"
                )
        self._step("S10")
        self._chk(
            "CHK-UART13-FIFO-ACCESS-OBS",
            "S10",
            "LSR.DR read 0 after each empty RBR read; THR overflow and RBR underflow "
            "indications measured at divisor %d (LINKED-ISSUE SF-018): %s",
            FIFO_ACCESS_DIVISOR,
            " | ".join(rows),
        )

    async def _s11(self) -> None:
        for idx in range(4):
            await self._wr(idx, "ier", "S11_IER", 0)
            await self._set_divisor(idx, "S11", DIVISOR)
        self._step("S11")
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: %d bounded waits of the UART1-3 legs, each with its bound and "
            "the last state it observed (an expiry raises AssertionError naming the UART and "
            "its last LSR, IIR and combined line, the sender_TEMT waits also the characters "
            "received): %s; %d collection windows (fixed clk_periph windows that keep reading "
            "the receiver, no expiry): %s; %d pre-existing UART0-leg waits: %s",
            len(self.waits),
            " ; ".join(f"{n} bound={b} last={s}" for n, (b, s) in self.waits.items()),
            len(self.windows),
            " ; ".join(f"{n} {w}" for n, w in self.windows.items()),
            len(UART0_WAITS),
            " ; ".join(UART0_WAITS),
        )

    async def _uart13(self) -> None:
        for step in (
            self._s1,
            self._s2,
            self._s3,
            self._s4,
            self._s5,
            self._s6,
            self._s7,
            self._s8,
            self._s9,
            self._s10,
            self._s11,
        ):
            await step()
        ids = [s for s, _ in self.stamps]
        assert ids == list(STEPS), f"step order {ids}, expected {list(STEPS)}"
        times = [t for _, t in self.stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"stamps not increasing: {times}"
        marks = [c for c, _ in self.chk_marks]
        assert marks == [c for c, _ in CHECKERS], f"checker order {marks}"
        for (chk, step), (_, n) in zip(CHECKERS, self.chk_marks):
            assert self.stamps[n - 1][0] == step, f"{chk} printed after {self.stamps[n - 1][0]}"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s after the UART0 legs; checker lines %s; stamps %s",
            " < ".join(FENCE_TERMS),
            ",".join(marks),
            ",".join(f"{s}={t}" for s, t in self.stamps),
        )

    async def body(self) -> None:
        cg = await self.csr_read("UART_CG", CLOCK_GATE_CONTROL)
        await self.csr_write("UART_UNGATE", CLOCK_GATE_CONTROL, cg & ~UART_CG_EN)

        await self._test_parity()
        self.parity_ok = True
        await self._test_overrun()
        self.overrun_ok = True
        await self._test_break()
        self.break_ok = True
        cocotb.log.info(
            "CHK-UART-ERR-BASIC: pe=%s oe=%s bi=%s",
            self.parity_ok,
            self.overrun_ok,
            self.break_ok,
        )
        await self._uart13()
