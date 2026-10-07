# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""UART0 divisor x WLS/STB/parity sweep, proven at the pads rather than in loopback.

Under ``MCR.LOOP`` the transmitter and receiver share one ``LCR``/``DLL``
setting, so any divisor, stop-bit or parity configuration frames and deframes
the same byte: a DUT that ignored ``DLL``, ``LCR.STB``, ``LCR.PEN`` or
``LCR.EPS`` would pass every combination. This sequence therefore observes
each axis where it is visible:

* **TX pad timing and content.** Three bytes are queued and the frames on
  ``tb_uart0_tx_from_dut`` are decoded at simulation-time resolution: the
  start bit, every data bit, the parity bit and the stop bit are sampled at
  their bit centres, and the interval between consecutive start bits is
  compared with ``(1 + data + parity + stop) x 16 x (DLL + 1)`` peripheral
  clocks (``clk_rst.adoc``: the UART runs on the peripheral clock;
  ``uart_16550_main.rdl``: ``STB`` selects 1, 2 or 1.5 stop bits, ``EPS``
  selects even parity). The divisor, the stop-bit count and the parity
  polarity each change that measurement, so each is falsifiable.
* **RX pad content.** One frame in the same format is driven onto
  ``tb_uart0_rx_ext_drive`` and the byte is read back through ``RBR`` with
  ``LSR`` free of PE/FE/BI.
* **Error detectors can assert.** Once per divisor a frame with the wrong
  parity raises ``LSR.PE`` and a frame with a low stop bit raises ``LSR.FE``,
  so the "no error" compares above rest on detectors shown to fire.
"""

from __future__ import annotations

from pathlib import Path

import cocotb
from cocotb.triggers import FallingEdge, SimTimeoutError, Timer, with_timeout
from cocotb.utils import get_sim_time

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
CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")
UART_EN = _field_mask(_UART_CTRL_H, "UART_LOG_ENGINE_CTRL__CTRL__UART_EN_bm")
FCR_FIFO_ENABLE = _field_mask(_UART_WO_H, "UART_16550_MAIN_WO__FCR__FIFO_ENABLE_bm")
FCR_RCVR_FIFO_RESET = _field_mask(_UART_WO_H, "UART_16550_MAIN_WO__FCR__RCVR_FIFO_RESET_bm")
FCR_XMIT_FIFO_RESET = _field_mask(_UART_WO_H, "UART_16550_MAIN_WO__FCR__XMIT_FIFO_RESET_bm")
LCR_DLAB = _field_mask(_UART_H, "UART_16550_MAIN__LCR__DLAB_bm")
LCR_WLS_BM = _field_mask(_UART_H, "UART_16550_MAIN__LCR__WLS_bm")
LCR_WLS_BP = _field_mask(_UART_H, "UART_16550_MAIN__LCR__WLS_bp")
LCR_STB = _field_mask(_UART_H, "UART_16550_MAIN__LCR__STB_bm")
LCR_PEN = _field_mask(_UART_H, "UART_16550_MAIN__LCR__PEN_bm")
LCR_EPS = _field_mask(_UART_H, "UART_16550_MAIN__LCR__EPS_bm")
MCR_RTS = _field_mask(_UART_H, "UART_16550_MAIN__MCR__RTS_bm")
LSR_DR = _field_mask(_UART_H, "UART_16550_MAIN__LSR__DR_bm")
LSR_OE = _field_mask(_UART_H, "UART_16550_MAIN__LSR__OE_bm")
LSR_PE = _field_mask(_UART_H, "UART_16550_MAIN__LSR__PE_bm")
LSR_FE = _field_mask(_UART_H, "UART_16550_MAIN__LSR__FE_bm")
LSR_BI = _field_mask(_UART_H, "UART_16550_MAIN__LSR__BI_bm")
LSR_TEMT = _field_mask(_UART_H, "UART_16550_MAIN__LSR__TEMT_bm")
LSR_ERRORS = LSR_OE | LSR_PE | LSR_FE | LSR_BI

# uart_16550: 16 baud-generator ticks per bit, the generator divides the
# peripheral clock by DLL + 1 (the same relation smc_clock_domain_connectivity
# measures against clk_periph_i).
TICKS_PER_BIT = 16
_DIVISORS = (1, 8)
# (wls, stb, pen, eps); stick parity excluded.
_FRAME_CFGS = (
    (0, 0, 0, 0),
    (0, 1, 0, 0),
    (0, 0, 1, 0),
    (0, 1, 1, 1),
    (1, 0, 0, 0),
    (1, 1, 0, 0),
    (1, 0, 1, 0),
    (1, 1, 1, 1),
    (2, 0, 0, 0),
    (2, 1, 0, 0),
    (2, 0, 1, 0),
    (2, 1, 1, 1),
    (3, 0, 0, 0),
    (3, 1, 0, 0),
    (3, 0, 1, 0),
    (3, 0, 1, 1),
)
# Three queued bytes, so the intervals between consecutive start bits measure
# the frame length twice while the FIFO is primed; the third frame closes the
# second interval. The RX byte is driven from the bench.
_TX_BYTES = (0x5A, 0xA5, 0x3C)
_RX_BYTE = 0x96
# Frames start and stop on baud ticks, each one peripheral clock wide, so an
# interval may differ from the ideal by a tick either side plus the pad path.
_TOLERANCE_TICKS = 2
# Bounds on waiting for a start bit: the transmitter may hold THR data for up
# to one bit time before the start bit, plus the AXI write that queued it.
_START_BOUND_BITS = 6
_LSR_POLLS = 4096
# LSR reads allowed for an error flag to clear once its character was popped:
# the flag belongs to the character at the top of the FIFO and is cleared by
# the LSR read that follows the pop, so a stuck flag is caught within a few.
_ERROR_CLEAR_READS = 4


def _data_bits(wls: int) -> int:
    return 5 + wls


def _stop_bits(wls: int, stb: int) -> float:
    # uart_16550_main.rdl LCR.STB: 0 -> 1 stop bit; 1 -> 2 stop bits, or 1.5
    # when the word length is 5 bits.
    if not stb:
        return 1.0
    return 1.5 if wls == 0 else 2.0


def _stop_bits_admitted(wls: int, stb: int) -> tuple[float, ...]:
    """Stop-bit counts the frame-length compare admits for a format.

    Every format is held to the RDL count, except the 5-bit word with STB=1:
    the RDL says 1.5 stop bits and the transmitter emits 2. The plan's Known
    Limitations records that difference, and the compare admits both counts
    for that one format so a transmitter emitting one stop bit still fails.
    """
    if stb and wls == 0:
        return (1.5, 2.0)
    return (_stop_bits(wls, stb),)


def _parity_bit(data: int, eps: int) -> int:
    ones = bin(data).count("1") & 1
    # EPS=1 even parity: the parity bit makes the total number of ones even.
    return ones if eps else ones ^ 1


class smc_uart_baud_word_parity_format_test_seq(SmcCsrSeq):
    """UART0 pad-level baud/word/parity format sweep with error-detector controls."""

    def __init__(self, name: str = "smc_uart_baud_word_parity_format_test_seq") -> None:
        super().__init__(name)
        self.combos_ok: int = 0
        self.frame_lengths_ps: dict[str, tuple[int, int]] = {}
        #: label -> measured stop-bit count where it differs from the RDL count.
        self.stop_bit_discrepancies: dict[str, float] = {}
        self.pe_asserted: bool = False
        self.fe_asserted: bool = False
        self._periph_ps: int = 0

    # ------------------------------------------------------------------ setup
    def _bit_ps(self, divisor: int) -> int:
        return TICKS_PER_BIT * (divisor + 1) * self._periph_ps

    async def _program(self, divisor: int, wls: int, stb: int, pen: int, eps: int) -> None:
        # No MCR.LOOP: the frames go out on pad 12 and come in on pad 11.
        await self.csr_write("MCR_PADS", UART_MCR, MCR_RTS)
        await self.csr_write("LCR_DLAB", UART_LCR, LCR_DLAB)
        await self.csr_write("DLL", UART_RBR, divisor & 0xFF)
        await self.csr_write("DLH", UART_IER, (divisor >> 8) & 0xFF)
        lcr = ((wls & 0x3) << LCR_WLS_BP) & LCR_WLS_BM
        if stb:
            lcr |= LCR_STB
        if pen:
            lcr |= LCR_PEN
        if eps:
            lcr |= LCR_EPS
        await self.csr_write("LCR_FMT", UART_LCR, lcr)
        await self.csr_write("IER_OFF", UART_IER, 0)
        await self.csr_write(
            "FCR_via_UART_IIR",
            UART_IIR,
            FCR_FIFO_ENABLE | FCR_RCVR_FIFO_RESET | FCR_XMIT_FIFO_RESET,
        )

    # -------------------------------------------------------------- TX decode
    async def _capture_tx_frames(
        self, label: str, divisor: int, wls: int, stb: int, pen: int, eps: int
    ) -> tuple[list[int], list[int]]:
        """Decode the three queued frames on the TX pad; return (bytes, start-bit intervals)."""
        dut = cocotb.top
        tx = dut.tb_uart0_tx_from_dut
        bit_ps = self._bit_ps(divisor)
        nbits = _data_bits(wls)
        assert int(tx.value) == 1, f"{label}: UART0 TX pad is not idle-high before THR"
        decoded: list[int] = []
        starts: list[int] = []
        for frame in range(len(_TX_BYTES)):
            bound_ns = (_START_BOUND_BITS * bit_ps) // 1000 + 2000
            try:
                await with_timeout(FallingEdge(tx), bound_ns, "ns")
            except SimTimeoutError as exc:
                raise AssertionError(
                    f"{label}: frame {frame} start bit never appeared on the TX pad within "
                    f"{bound_ns} ns"
                ) from exc
            t0 = int(round(get_sim_time("ps")))
            starts.append(t0)
            # Bit centres: start at t0 + 0.5 bit, data bit n at t0 + (n + 1.5) bit.
            await Timer(bit_ps // 2, "ps")
            assert int(tx.value) == 0, f"{label}: frame {frame} start bit not low at its centre"
            data = 0
            for n in range(nbits):
                await Timer(bit_ps, "ps")
                data |= int(tx.value) << n
            if pen:
                await Timer(bit_ps, "ps")
                parity = int(tx.value)
                assert parity == _parity_bit(data, eps), (
                    f"{label}: frame {frame} parity bit {parity} for data 0x{data:02x} with "
                    f"EPS={eps}, expected {_parity_bit(data, eps)}"
                )
            await Timer(bit_ps, "ps")
            assert int(tx.value) == 1, f"{label}: frame {frame} stop bit not high at its centre"
            decoded.append(data)
        intervals = [b - a for a, b in zip(starts, starts[1:])]
        return decoded, intervals

    async def _tx_leg(
        self, label: str, divisor: int, wls: int, stb: int, pen: int, eps: int
    ) -> None:
        bit_ps = self._bit_ps(divisor)
        nbits = _data_bits(wls)
        mask = (1 << nbits) - 1
        capture = cocotb.start_soon(self._capture_tx_frames(label, divisor, wls, stb, pen, eps))
        for i, byte in enumerate(_TX_BYTES):
            await self.csr_write(f"{label}_THR_{i}", UART_RBR, byte)
        decoded, intervals = await capture
        expected = [b & mask for b in _TX_BYTES]
        assert decoded == expected, (
            f"{label}: TX pad frames decoded {[hex(d) for d in decoded]}, expected "
            f"{[hex(e) for e in expected]} (WLS={wls} -> {nbits} data bits)"
        )
        tolerance_ps = _TOLERANCE_TICKS * (bit_ps // TICKS_PER_BIT) + 2 * self._periph_ps
        admitted = {
            stop: int(round((1 + nbits + pen + stop) * bit_ps))
            for stop in _stop_bits_admitted(wls, stb)
        }
        # The FIFO is primed for at least one of the two intervals (three bytes
        # are queued within one frame), so the shorter interval is a frame; no
        # interval may be shorter than a frame.
        shortest = min(intervals)
        matched = [stop for stop, ps in admitted.items() if abs(shortest - ps) <= tolerance_ps]
        assert matched, (
            f"{label}: start-to-start interval {shortest} ps is not one frame of "
            f"(1 + {nbits} + {pen} + {'/'.join(str(x) for x in admitted)}) bits x {bit_ps} ps = "
            f"{'/'.join(str(v) for v in admitted.values())} ps (tolerance {tolerance_ps} ps; "
            f"intervals {intervals})"
        )
        frame_ps = admitted[matched[0]]
        assert all(iv >= frame_ps - tolerance_ps for iv in intervals), (
            f"{label}: an interval between start bits {intervals} is shorter than one frame "
            f"{frame_ps} ps"
        )
        if matched[0] != _stop_bits(wls, stb):
            self.stop_bit_discrepancies[label] = matched[0]
            cocotb.log.warning(
                "%s: the transmitter emitted %s stop bits where uart_16550_main.rdl LCR.STB "
                "says %s for a 5-bit word; recorded under Known Limitations (#2121)",
                label,
                matched[0],
                _stop_bits(wls, stb),
            )
        self.frame_lengths_ps[label] = (shortest, frame_ps)
        # Drain the loopback-free transmitter before the RX leg.
        for _ in range(_LSR_POLLS):
            lsr = await self.csr_read(f"{label}_TX_TEMT", UART_LSR)
            if lsr & LSR_TEMT:
                break
            await Timer(bit_ps, "ps")
        else:
            raise AssertionError(f"{label}: TEMT never set after the three TX frames")

    # -------------------------------------------------------------- RX drive
    async def _drive_rx_frame(
        self,
        divisor: int,
        wls: int,
        stb: int,
        pen: int,
        eps: int,
        data: int,
        *,
        parity_error: bool = False,
        framing_error: bool = False,
    ) -> None:
        dut = cocotb.top
        rx = dut.tb_uart0_rx_ext_drive
        bit_ps = self._bit_ps(divisor)
        nbits = _data_bits(wls)
        rx.value = 0
        await Timer(bit_ps, "ps")
        for n in range(nbits):
            rx.value = (data >> n) & 1
            await Timer(bit_ps, "ps")
        if pen:
            rx.value = _parity_bit(data, eps) ^ int(parity_error)
            await Timer(bit_ps, "ps")
        # Stop bit(s): a low stop bit is the framing error the receiver reports.
        rx.value = 0 if framing_error else 1
        await Timer(int(round(_stop_bits(wls, stb) * bit_ps)), "ps")
        rx.value = 1
        # Idle for a full frame so a following frame is unambiguous.
        await Timer(bit_ps * 4, "ps")

    async def _wait_dr(self, label: str, divisor: int) -> int:
        lsr = 0
        for _ in range(_LSR_POLLS):
            lsr = await self.csr_read(f"{label}_LSR", UART_LSR)
            if lsr & LSR_DR:
                return lsr
            await Timer(self._bit_ps(divisor), "ps")
        raise AssertionError(f"{label}: LSR.DR never set (last LSR=0x{lsr:08x})")

    async def _rx_leg(
        self, label: str, divisor: int, wls: int, stb: int, pen: int, eps: int
    ) -> int:
        nbits = _data_bits(wls)
        expected = _RX_BYTE & ((1 << nbits) - 1)
        await self._drive_rx_frame(divisor, wls, stb, pen, eps, expected)
        lsr = await self._wait_dr(f"{label}_RX", divisor)
        assert not (lsr & LSR_ERRORS), (
            f"{label}: LSR=0x{lsr:08x} reports an error on a well-formed frame "
            f"(div={divisor} wls={wls} stb={stb} pen={pen} eps={eps})"
        )
        rx = await self.csr_read(f"{label}_RBR", UART_RBR, expected=expected)
        return int(rx) & 0xFF

    async def _pop_and_clear(self, label: str, flag: int, name: str) -> int:
        """Pop the erroneous character, then require ``flag`` to clear within a few LSR reads."""
        await self.csr_read(f"{label}_RBR_POP", UART_RBR)
        lsr = 0
        for i in range(_ERROR_CLEAR_READS):
            lsr = await self.csr_read(f"{label}_LSR_CLEARED_{i}", UART_LSR)
            if not (lsr & flag):
                return lsr
        raise AssertionError(
            f"{label}: LSR.{name} still set {_ERROR_CLEAR_READS} LSR reads after the erroneous "
            f"character was popped (LSR=0x{lsr:08x})"
        )

    # ------------------------------------------------------- error controls
    async def _error_controls(self, divisor: int) -> None:
        """Prove LSR.PE and LSR.FE can assert at this divisor, then clear again."""
        label = f"D{divisor}_PE"
        wls, stb, pen, eps = 3, 0, 1, 1
        await self._program(divisor, wls, stb, pen, eps)
        await self._drive_rx_frame(divisor, wls, stb, pen, eps, 0x55, parity_error=True)
        lsr = await self._wait_dr(label, divisor)
        assert lsr & LSR_PE, (
            f"{label}: a frame with the wrong parity bit did not raise LSR.PE (LSR=0x{lsr:08x})"
        )
        lsr_after = await self._pop_and_clear(label, LSR_PE, "PE")
        self.pe_asserted = True
        cocotb.log.info(
            "CHK-UART-FMT-PE-ASSERTS: div=%d 8E1 frame driven on the RX pad with the parity "
            "bit inverted -> LSR=0x%08x (PE set, DR set); after the RBR pop LSR read 0x%08x "
            "(PE clear), so the parity detector the sweep's no-error compares rely on can fire",
            divisor,
            lsr,
            lsr_after,
        )

        label = f"D{divisor}_FE"
        wls, stb, pen, eps = 3, 0, 0, 0
        await self._program(divisor, wls, stb, pen, eps)
        await self._drive_rx_frame(divisor, wls, stb, pen, eps, 0x55, framing_error=True)
        lsr = await self._wait_dr(label, divisor)
        assert lsr & LSR_FE, (
            f"{label}: a frame with a low stop bit did not raise LSR.FE (LSR=0x{lsr:08x})"
        )
        lsr_after = await self._pop_and_clear(label, LSR_FE, "FE")
        self.fe_asserted = True
        cocotb.log.info(
            "CHK-UART-FMT-FE-ASSERTS: div=%d 8N1 frame driven on the RX pad with a low stop bit "
            "-> LSR=0x%08x (FE set, DR set); after the RBR pop LSR read 0x%08x (FE clear), so "
            "the framing detector the sweep's no-error compares rely on can fire",
            divisor,
            lsr,
            lsr_after,
        )

    # ---------------------------------------------------------------- body
    async def _exchange(
        self, label: str, divisor: int, wls: int, stb: int, pen: int, eps: int
    ) -> None:
        await self._program(divisor, wls, stb, pen, eps)
        await self._tx_leg(label, divisor, wls, stb, pen, eps)
        rx_b = await self._rx_leg(label, divisor, wls, stb, pen, eps)
        shortest, frame_ps = self.frame_lengths_ps[label]
        measured_stop = self.stop_bit_discrepancies.get(label, _stop_bits(wls, stb))
        cocotb.log.info(
            "CHK-UART-BAUD-FMT: div=%d wls=%d stb=%d pen=%d eps=%d: TX pad frames decoded "
            "%s at %d ps/bit with parity per EPS and start-to-start interval %d ps == %d ps "
            "(1+%d+%d+%s bits); RX pad frame read back 0x%02x through RBR with LSR clear of "
            "OE/PE/FE/BI",
            divisor,
            wls,
            stb,
            pen,
            eps,
            [f"0x{b & ((1 << _data_bits(wls)) - 1):02x}" for b in _TX_BYTES],
            self._bit_ps(divisor),
            shortest,
            frame_ps,
            _data_bits(wls),
            pen,
            measured_stop,
            rx_b,
        )

    async def body(self) -> None:
        self._periph_ps = int(round(self.cfg.periph_clk_period_ns * 1000))
        assert self._periph_ps > 0, "periph_clk_period_ns must be positive"
        assert int(cocotb.top.tb_uart0_rx_ext_drive.value) == 1, "RX pad must idle high"
        cg = await self.csr_read("UART_CG", CLOCK_GATE_CONTROL)
        await self.csr_write("UART_UNGATE", CLOCK_GATE_CONTROL, cg & ~UART_CG_EN)
        await self.csr_write("UART_EN", UART_CTRL, UART_EN)

        for divisor in _DIVISORS:
            for wls, stb, pen, eps in _FRAME_CFGS:
                label = f"D{divisor}_W{wls}_S{stb}_P{pen}{eps}"
                await self._exchange(label, divisor, wls, stb, pen, eps)
                self.combos_ok += 1
            await self._error_controls(divisor)

        expect = len(_DIVISORS) * len(_FRAME_CFGS)
        if self.combos_ok != expect:
            raise AssertionError(f"combo count {self.combos_ok} != {expect}")
        assert self.pe_asserted and self.fe_asserted, "error-detector controls did not run"
        cocotb.log.info(
            "CHK-UART-BAUD-BASIC: combos=%d (div x frame), each decoded on the TX pad and read "
            "back from the RX pad; PE and FE proven able to assert at every divisor",
            self.combos_ok,
        )
