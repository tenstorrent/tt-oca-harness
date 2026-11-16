# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Three UART mode selectors: FIFOs off, DMA mode 1, line loopback.

* **The receive path with the FIFOs disabled.** `FCR.FIFO_ENABLE` resets clear,
  and `hw/ip/uart/uart_16550/doc/architecture.adoc` describes the two receive
  paths the 16550 has: software reads "from RBR or FIFO". With the FIFOs off a
  character goes through the receiver buffer register itself.
* **DMA mode 1.** The Programmer's Guide UART FIFO section says "Set
  `FCR.DMA_MODE_SELECT` only to use mode-1 DMA service indications" and
  `uart_16550_main_wo.rdl` gives FCR a `DMA_MODE_SELECT` bit, which selects the
  receive and transmit ready handshakes.
* **Line loopback.** `MCR.LINE_LOOPBACK` is the second of the two loopback modes
  the Programmer's Guide documents.

The leaf drives all three and checks what each one is specified to do.

**The receive path with the FIFOs disabled.** A character is left unread in the
receive FIFO and `FCR.FIFO_ENABLE` is then written clear. `IIR.FIFOS_ENABLED`
has to report the FIFOs off -- `uart_16550_main.rdl` gives that field `0x0` --
and `LSR.DR` has to read clear, because the character parked in the FIFO is no
longer on the path software reads. Two further characters are then sent one at a
time and compared against what comes back; with the FIFOs off that traffic
goes through the receiver buffer register rather than the FIFO. Two more are
then sent back to back and neither is read until both have arrived:
`architecture.adoc` ("an unread character can be overwritten in RBR") and
`uart_16550_main.rdl` (`LSR.OE` is "set only in FIFO mode") have the second
replace the first with `OE` clear, so `RBR` has to return the second character
and `LSR.OE` has to stay clear on every read.

**The reception timeout, timed.** `architecture.adoc` puts the timeout at
"roughly four character times" of unchanged occupancy and says it is "not
gated by IER", and `uart_16550_main.rdl` lists no `IER` enable for it. With the
FIFOs on, `IER` written 0 and the trigger above one character, one character is
sent in loopback and the wrapper's raw interrupt line (`tb_uart_irq_raw`) is
watched: it has to rise four character times after the character arrived (the
THR write plus one frame, within two and a half bit times), IER has to still
read 0 and IIR has to report the timeout id at that moment, and the RBR read
has to drop the line.

**DMA mode 1 and the reception timeout.** With the FIFOs on, DMA mode 1
selected and `FCR.RCVR_TRIGGER` programmed to four characters, one character is
sent and left unread. Its trigger level is not reached, so the only interrupt
that can arise is the reception timeout `architecture.adoc` fixes at four
character times, and `uart_16550_main.rdl` names id `0x6` for it. IIR has to
report exactly that, and no interrupt pending once the character is read out.
Four characters are then sent and read back in order, which is the same mode
with the trigger level reached instead of timed out.

**Line loopback.** The Programmer's Guide: "With `MCR.LINE_LOOPBACK` set, the modem
inputs are routed straight back out to the modem outputs and all four MSR level
bits read `0`." The leaf sets it and requires those four bits to read 0. In this
mode the receiver input is held idle, so a character written into THR must be
transmitted without ever being received: the leaf polls until `LSR.TEMT` reports
the transmitter drained and requires `LSR.DR` clear on every read up to that
point.

**The transmit FIFO under DMA mode 1.** Still in line loopback, the divisor is
slowed and a burst longer than the SMC UARTs' 32-entry transmit FIFO
(`hw/sys/smc/doc/periphs.adoc`, peripheral parameter table: `UartTxFifoDepth`
SMC value 32; `hw/ip/uart/uart_16550/doc/index.adoc`: "32-entry TX and RX
FIFOs") is written into THR without polling, so the FIFO reaches its full
condition while
the transmitter is still draining the first characters. What the leaf checks is
what the register map exposes: `LSR.THRE` clear straight after the burst, so the
FIFO is holding characters, and `LSR.TEMT` and `LSR.THRE` both set once it has
drained, so the UART carried the burst instead of wedging. The full flag itself
is not a register field and is not claimed.

Line loopback is driven on wrapper 0 only. In that mode the transmit pin carries
the receive pin, and `hw/sys/smc/dv/tb/tb_top.sv` drives only UART0's receive
pad -- idle high -- unless `+smc_uart_cross_3to0` shorts the pairs, so wrapper 0
is the only one where the substituted pin has a defined value. The other two
modes use `MCR.LOOP`, which keeps every character inside the UART, and run on
all four wrappers.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge, Timer
from cocotb.utils import get_sim_time

from .smc_addr_map import smc_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_log_engine_utils import (
    ARM_UART_ACCESSES,
    DIVISOR,
    DLL_OFFSET,
    DLM_OFFSET,
    FCR_DMA_MODE_SELECT,
    FCR_FIFO_ENABLE,
    FCR_OFFSET,
    FCR_RCVR_FIFO_RESET,
    FCR_RCVR_TRIGGER_SHIFT,
    FCR_XMIT_FIFO_RESET,
    IER_ERBFI,
    IIR_FIFOS_ENABLED,
    IIR_FIFOS_SHIFT,
    IIR_ID,
    IIR_ID_SHIFT,
    IIR_PENDING,
    LCR_DLAB,
    LCR_WLS,
    LSR_DR,
    LSR_LINE_ERRORS,
    LSR_OE,
    LSR_TEMT,
    LSR_THRE,
    MCR_DTR,
    MCR_LINE_LOOPBACK,
    MCR_LOOP,
    MCR_OUT1,
    MCR_OUT2,
    MCR_RTS,
    MSR_LEVELS,
    RBR_DATA,
    RESTORE_UART_ACCESSES,
    THR_OFFSET,
    WLS_8_BITS,
    WRAP_NUM,
    arm_uart,
    restore_uart,
    uart_base,
    uart_reg,
)

# uart_16550_main.rdl, IIR.FIFOS_ENABLED: "0x0 - FIFOs are disabled, 0x3 -
# FIFOs are enabled".
_FIFOS_ON = 0x3
_FIFOS_OFF = 0x0
# uart_16550_main.rdl, IIR.INTERRUPT_ID: "0x6 - Reception Timeout Interrupt",
# "0x2 - Received Data Ready Interrupt".
_IIR_ID_TIMEOUT = 0x6
_IIR_ID_RDR = 0x2
# uart_16550_main_wo.rdl, FCR.RCVR_TRIGGER: "0x1 - 4 characters". One character
# is below it, so the watermark cannot be what raises the interrupt below.
_TRIGGER_4_CHARS = 0x1
_TRIGGER_4_CHARS_DEPTH = 4

# Characters for the receiver-buffer leg, the DMA-mode leg and the character
# that is parked in the receive FIFO before the FIFOs are turned off. All
# distinct and spread across the byte, so a stuck bit shows up and no leg can
# pass on a character another leg left behind.
_RBR_PAYLOAD = (0xC3, 0x3C)
_RBR_OVERWRITE_PAIR = (0xB7, 0x4E)
_TIMED_BYTE = 0x6D
_DMA_TIMEOUT_BYTE = 0x96
_DMA_TRIGGER_PAYLOAD = (0x11, 0x22, 0x44, 0x88)
# Two characters queued back to back for the transmit-ready observation.
_TXRDY_PAIR = (0x33, 0x66)
_PARKED_BYTE = 0x69
_LINE_LOOPBACK_BYTE = 0x5A
# The four MCR outputs that MCR.LOOP routes onto the four MSR levels.
_MCR_OUTPUTS = MCR_DTR | MCR_RTS | MCR_OUT1 | MCR_OUT2

# hw/sys/smc/doc/periphs.adoc (peripheral parameter table) and
# hw/ip/uart/uart_16550/doc/index.adoc give the SMC UARTs a 32-entry transmit
# FIFO. The burst is comfortably longer so the FIFO reaches its full condition
# even if the CSR port delivers a write every few cycles.
_TX_FIFO_DEPTH = 32
_TX_BURST = tuple(range(64))
# uart_16550_dl.rdl: "baud_rate = system_clock_frequency / (16 * (divisor +
# 1))". `arm_uart` uses the fastest divisor the RDL allows; the burst leg wants
# the transmitter slow relative to the CSR port so the FIFO fills, and this
# divisor makes a character five times longer than that.
_BURST_DIVISOR = 4
# Divisor of the timed reception-timeout leg: a bit is 16 x (15 + 1) = 256
# peripheral clocks, so the CSR write that queues the character and the LSR
# polls are a small fraction of a bit time and the timing compare below has
# the resolution it needs.
_TIMEOUT_DIVISOR = 15
# uart_16550: 16 baud ticks per bit; 8N1 is 10 bits per character.
_TICKS_PER_BIT = 16
_CHAR_BITS_8N1 = 10
# architecture.adoc: the timeout is "roughly four character times" of the
# programmed format.
_TIMEOUT_CHARS = 4
# Tolerance of the timing compare in bit times: the transmitter starts within
# one bit of the THR write (its baud tick is free running), the receiver's tick
# is realigned at the start bit, and the CSR write completes a fraction of a
# bit after the register took the character.
_TIMEOUT_TOLERANCE_BITS = 2.5
# Bound on waiting for the line, in character times after the THR write.
_TIMEOUT_BOUND_CHARS = 8

# Polls of LSR or IIR allowed per expected event. Each bound is a liveness
# ceiling on an event that has to happen: expiry is a FAILURE, never a pass.
_RX_POLLS_PER_BYTE = 400
_TIMEOUT_POLLS = 600
_DRAIN_POLLS = 4000

# SEP_IN accesses one wrapper needs: the UART setup and restore, the
# receiver-buffer leg and the DMA-mode leg.
# ... plus the overwrite pair (two writes, a drain poll, two LSR reads and an
# RBR read) and the timed leg (nine programming accesses, the character, its
# poll, IER, IIR, RBR and the drained IIR).
_MIN_ACCESSES_PER_WRAP = ARM_UART_ACCESSES + RESTORE_UART_ACCESSES + 15 + 22 + 6 + 15
# SEP_IN accesses the line-loopback leg adds on wrapper 0: the divisor change,
# the two MCR writes with their two MSR reads of the control, FCR, the two MSR
# reads, the quiet character and its drain poll, the burst and the two LSR
# reads around it, and the MCR restore.
_LINE_LOOPBACK_ACCESSES = 16 + len(_TX_BURST)


class smc_uart_core_mode_select_test_seq(SmcCsrSeq):
    """Drive the FIFOs-off receive path, DMA mode 1 and line loopback, and check each one."""

    def __init__(self, name: str = "smc_uart_core_mode_select_test_seq") -> None:
        super().__init__(name)
        self.uarts = 0
        self.rbr_bytes = 0
        self.dma_bytes = 0
        self.timeout_legs = 0
        self.overwrite_legs = 0
        self.timed_legs = 0
        self.timed_chars: dict[int, float] = {}
        self.trigger_ids: dict[int, int] = {}
        self.txrdy_samples: dict[str, list[int]] = {}
        self.line_loopback_legs = 0
        self.burst_bytes = 0

    # -- primitives ------------------------------------------------------

    async def _lsr(self, wrap: int, label: str) -> int:
        status = await self.csr_read(f"WRAP{wrap}_LSR_{label}", uart_reg(wrap, "LSR"))
        assert status & LSR_LINE_ERRORS == 0, (
            f"wrapper {wrap} [{label}]: LSR reports 0x{status & LSR_LINE_ERRORS:x} in its "
            f"overrun, parity, framing and break bits; the character did not arrive intact"
        )
        return status

    async def _send(self, wrap: int, byte: int, label: str) -> None:
        await self.csr_write(f"WRAP{wrap}_THR_{label}", uart_base(wrap) + THR_OFFSET, byte)

    async def _await_rx(self, wrap: int, label: str) -> None:
        for _ in range(_RX_POLLS_PER_BYTE):
            if await self._lsr(wrap, label) & LSR_DR:
                return
        raise AssertionError(
            f"wrapper {wrap} [{label}]: LSR never reported received data within "
            f"{_RX_POLLS_PER_BYTE} reads of a character written into THR"
        )

    async def _await_tx_drained(self, wrap: int, label: str) -> None:
        """Wait until the transmitter reports itself empty, which the DUT times."""
        for _ in range(_DRAIN_POLLS):
            if await self._lsr(wrap, label) & LSR_TEMT:
                return
        raise AssertionError(
            f"wrapper {wrap} [{label}]: the transmitter never reported itself empty within "
            f"{_DRAIN_POLLS} reads of a character written into THR"
        )

    async def _recv(self, wrap: int, label: str, expect: int) -> None:
        got = await self.csr_read(f"WRAP{wrap}_RBR_{label}", uart_reg(wrap, "RBR")) & RBR_DATA
        assert got == expect, (
            f"wrapper {wrap} [{label}]: a byte written into THR as 0x{expect:02x} came back "
            f"out of the receiver as 0x{got:02x}"
        )

    async def _fifos_enabled(self, wrap: int, label: str, expect: int) -> None:
        iir = await self.csr_read(f"WRAP{wrap}_IIR_{label}", uart_reg(wrap, "IIR"))
        reported = (iir & IIR_FIFOS_ENABLED) >> IIR_FIFOS_SHIFT
        assert reported == expect, (
            f"wrapper {wrap} [{label}]: IIR reports FIFOS_ENABLED={reported}; the RDL gives "
            f"that field 0x{expect:x} for the state FCR was just written to"
        )

    async def _fcr(self, wrap: int, label: str, value: int) -> None:
        await self.csr_write(f"WRAP{wrap}_FCR_{label}", uart_base(wrap) + FCR_OFFSET, value)

    def _frame_ns(self, divisor: int) -> int:
        """One 8N1 frame at ``divisor`` in ns (uart_16550_dl.rdl: 16 x (divisor + 1) per bit)."""
        return _CHAR_BITS_8N1 * _TICKS_PER_BIT * (divisor + 1) * self.cfg.periph_clk_period_ns

    async def _watch_irq_rise(self, wrap: int, bound_ns: int) -> int | None:
        """Simulation time in ns of the first rise of ``tb_uart_irq_raw[wrap]``, or None."""
        dut = cocotb.top
        start = get_sim_time("ns")
        while get_sim_time("ns") - start < bound_ns:
            await RisingEdge(dut.clk_smc_i)
            raw = dut.tb_uart_irq_raw.value
            assert raw.is_resolvable, "tb_uart_irq_raw is X/Z"
            if (int(raw) >> wrap) & 1:
                return int(get_sim_time("ns"))
        return None

    # -- legs ------------------------------------------------------------

    async def _receiver_buffer_leg(self, wrap: int) -> None:
        """With the FIFOs off a character takes the receiver buffer register."""
        await self._send(wrap, _PARKED_BYTE, "PARKED")
        await self._await_rx(wrap, "PARKED")

        await self._fcr(wrap, "FIFOS_OFF", 0)
        await self._fifos_enabled(wrap, "FIFOS_OFF", _FIFOS_OFF)
        quiet = await self._lsr(wrap, "AFTER_FIFOS_OFF")
        assert quiet & LSR_DR == 0, (
            f"wrapper {wrap}: LSR still reports received data after the FIFOs were turned "
            f"off with a character unread in the receive FIFO; with them off the receiver "
            f"buffer register is the path software reads, and it holds nothing yet"
        )

        for index, byte in enumerate(_RBR_PAYLOAD):
            label = f"RBR{index}"
            await self._send(wrap, byte, label)
            await self._await_rx(wrap, label)
            await self._recv(wrap, label, byte)
            self.rbr_bytes += 1

        drained = await self._lsr(wrap, "RBR_DRAINED")
        assert drained & LSR_DR == 0, (
            f"wrapper {wrap}: the receiver still reports data after every character sent "
            f"with the FIFOs off was read out"
        )

        # Two characters, the first seen in the receiver (LSR.DR) and left unread
        # before the second is sent. `_lsr` fails the run on OE at every read of
        # the wait, and the looped second character lands within one frame of
        # the transmitter idling.
        first, second = _RBR_OVERWRITE_PAIR
        await self._send(wrap, first, "OVERWRITE0")
        await self._await_rx(wrap, "OVERWRITE0")
        await self._send(wrap, second, "OVERWRITE1")
        await self._await_tx_drained(wrap, "OVERWRITE_TEMT")
        await Timer(self._frame_ns(DIVISOR), unit="ns")
        status = await self.csr_read(f"WRAP{wrap}_LSR_OVERWRITE", uart_reg(wrap, "LSR"))
        assert status & LSR_DR, (
            f"wrapper {wrap}: LSR 0x{status:02x} reports no data after two characters were "
            f"sent with the FIFOs off"
        )
        assert status & LSR_OE == 0, (
            f"wrapper {wrap}: LSR 0x{status:02x} reports an overrun after a second character "
            f"reached the unread receiver buffer register; OE is set only in FIFO mode"
        )
        await self._recv(wrap, "OVERWRITE", second)
        after = await self._lsr(wrap, "OVERWRITE_EMPTY")
        assert after & LSR_DR == 0, (
            f"wrapper {wrap}: LSR 0x{after:02x} still reports data after the overwriting "
            f"character was read; the overwritten first character is gone"
        )
        self.overwrite_legs += 1

        await self._fcr(wrap, "FIFOS_BACK", FCR_FIFO_ENABLE | FCR_RCVR_FIFO_RESET)
        await self._fifos_enabled(wrap, "FIFOS_BACK", _FIFOS_ON)
        flushed = await self._lsr(wrap, "FIFOS_BACK")
        assert flushed & LSR_DR == 0, (
            f"wrapper {wrap}: LSR reports received data after the FIFOs were enabled again "
            f"with the singlepulse receive-FIFO reset, which had to discard the character "
            f"parked before they were turned off"
        )

    async def _dma_mode_leg(self, wrap: int) -> None:
        """DMA mode 1 with the trigger above one character: timeout, then watermark."""
        dma_fcr = (
            FCR_FIFO_ENABLE | FCR_DMA_MODE_SELECT | (_TRIGGER_4_CHARS << FCR_RCVR_TRIGGER_SHIFT)
        )
        await self._fcr(wrap, "DMA_MODE_1", dma_fcr)
        await self.csr_write(f"WRAP{wrap}_IER_RX", uart_reg(wrap, "IER"), IER_ERBFI)

        await self._send(wrap, _DMA_TIMEOUT_BYTE, "DMA_TIMEOUT")
        await self._await_rx(wrap, "DMA_TIMEOUT")
        for _ in range(_TIMEOUT_POLLS):
            iir = await self.csr_read(f"WRAP{wrap}_IIR_TIMEOUT", uart_reg(wrap, "IIR"))
            if iir & IIR_PENDING == 0:
                reported = (iir & IIR_ID) >> IIR_ID_SHIFT
                assert reported == _IIR_ID_TIMEOUT, (
                    f"wrapper {wrap}: IIR reports interrupt id {reported} with one "
                    f"character waiting and FCR.RCVR_TRIGGER programmed to "
                    f"{_TRIGGER_4_CHARS_DEPTH} characters; the trigger level is not "
                    f"reached, so the only source that can be pending is the reception "
                    f"timeout the RDL gives id 0x{_IIR_ID_TIMEOUT:x}"
                )
                break
        else:
            raise AssertionError(
                f"wrapper {wrap}: IIR never reported an interrupt pending within "
                f"{_TIMEOUT_POLLS} reads of a character left unread below the trigger "
                f"level; the reception timeout has to raise one after four character times"
            )
        self.timeout_legs += 1

        await self._recv(wrap, "DMA_TIMEOUT", _DMA_TIMEOUT_BYTE)
        self.dma_bytes += 1
        cleared = await self.csr_read(f"WRAP{wrap}_IIR_DRAINED", uart_reg(wrap, "IIR"))
        assert cleared & IIR_PENDING, (
            f"wrapper {wrap}: IIR still reports an interrupt pending (0x{cleared:02x}) "
            f"after the character that timed out was read out of the receiver"
        )

        # LSR.DR reports the receiver non-empty, so it is set by the first of
        # these characters and says nothing about the rest. Each one is sent
        # only once the transmitter reports the previous one gone, and the
        # receiver is then given until it raises an interrupt, which has to be
        # the trigger level reached, before any of them is read back.
        for index, byte in enumerate(_DMA_TRIGGER_PAYLOAD):
            label = f"DMA_TRIG{index}"
            await self._send(wrap, byte, label)
            await self._await_tx_drained(wrap, label)
        for _ in range(_TIMEOUT_POLLS):
            iir = await self.csr_read(f"WRAP{wrap}_IIR_TRIGGER", uart_reg(wrap, "IIR"))
            if iir & IIR_PENDING == 0:
                reported = (iir & IIR_ID) >> IIR_ID_SHIFT
                assert reported == _IIR_ID_RDR, (
                    f"wrapper {wrap}: IIR reports interrupt id {reported} with "
                    f"{len(_DMA_TRIGGER_PAYLOAD)} characters waiting at a trigger level of "
                    f"{_TRIGGER_4_CHARS_DEPTH}; the level reached is the Received Data Ready "
                    f"id 0x{_IIR_ID_RDR:x}, not the timeout"
                )
                self.trigger_ids[wrap] = reported
                break
        else:
            raise AssertionError(
                f"wrapper {wrap}: IIR never reported an interrupt pending within "
                f"{_TIMEOUT_POLLS} reads of {len(_DMA_TRIGGER_PAYLOAD)} characters sent "
                f"into a receiver with the trigger level at "
                f"{_TRIGGER_4_CHARS_DEPTH} characters"
            )
        for index, byte in enumerate(_DMA_TRIGGER_PAYLOAD):
            await self._recv(wrap, f"DMA_TRIG{index}", byte)
            self.dma_bytes += 1

        if wrap == 0:
            await self._txrdy_leg(wrap, "DMA1")
        await self.csr_write(f"WRAP{wrap}_IER_CLR", uart_reg(wrap, "IER"), 0)
        await self._fcr(wrap, "DMA_MODE_0", FCR_FIFO_ENABLE | FCR_RCVR_FIFO_RESET)
        if wrap == 0:
            await self._txrdy_leg(wrap, "DMA0")
            assert set(self.txrdy_samples["DMA1"]) != set(self.txrdy_samples["DMA0"]), (
                f"tb_uart0_tx_ready read {self.txrdy_samples['DMA1']} in DMA mode 1 and "
                f"{self.txrdy_samples['DMA0']} in mode 0 with two characters queued; "
                f"interface.adoc has the ready behaviour change with the FIFO control mode"
            )

    async def _txrdy_leg(self, wrap: int, label: str) -> None:
        """Two characters queued: sample uart_txrdy_o while the FIFO holds them.

        uart_16550/doc/interface.adoc (DMA Interface): `txrdy_o` indicates when
        DMA can proceed "with behavior configurable through FIFO control
        modes". `tb_uart0_tx_ready` is sampled on every LSR read that sees
        THRE clear; the level has to be one value throughout the queue, and
        the caller requires the two modes to read different values.
        """
        dut = cocotb.top
        for byte in _TXRDY_PAIR:
            await self._send(wrap, byte, f"{label}_TXRDY_{byte:02x}")
        seen: list[int] = []
        for _ in range(_RX_POLLS_PER_BYTE):
            status = await self._lsr(wrap, f"{label}_TXRDY")
            ready = dut.tb_uart0_tx_ready.value
            assert ready.is_resolvable, "tb_uart0_tx_ready is X/Z"
            if status & LSR_THRE == 0:
                seen.append(int(ready))
            if status & LSR_TEMT:
                break
        else:
            raise AssertionError(
                f"wrapper {wrap} [{label}]: the transmitter never drained the two characters "
                f"within {_RX_POLLS_PER_BYTE} LSR reads"
            )
        assert seen and len(set(seen)) == 1, (
            f"wrapper {wrap} [{label}]: tb_uart0_tx_ready read {seen} on the LSR reads with "
            f"THRE clear; one level is expected throughout the queued pair"
        )
        for byte in _TXRDY_PAIR:
            await self._await_rx(wrap, f"{label}_TXRDY_RX")
            await self._recv(wrap, f"{label}_TXRDY_{byte:02x}", byte)
        self.txrdy_samples[label] = seen

    async def _timed_timeout_leg(self, wrap: int) -> None:
        """The timeout fires four character times after the character, with IER clear."""
        dut = cocotb.top
        base = uart_base(wrap)
        await self.csr_write(f"WRAP{wrap}_LCR_DLAB_TIMED", uart_reg(wrap, "LCR"), LCR_DLAB)
        await self.csr_write(f"WRAP{wrap}_DLL_TIMED", base + DLL_OFFSET, _TIMEOUT_DIVISOR)
        await self.csr_write(f"WRAP{wrap}_DLM_TIMED", base + DLM_OFFSET, 0)
        await self.csr_write(
            f"WRAP{wrap}_LCR_8N1_TIMED", uart_reg(wrap, "LCR"), WLS_8_BITS & LCR_WLS
        )
        await self._fcr(
            wrap,
            "TIMED",
            FCR_FIFO_ENABLE
            | FCR_RCVR_FIFO_RESET
            | FCR_XMIT_FIFO_RESET
            | (_TRIGGER_4_CHARS << FCR_RCVR_TRIGGER_SHIFT),
        )
        await self.csr_write(f"WRAP{wrap}_IER_TIMED_OFF", uart_reg(wrap, "IER"), 0)
        await self.csr_read(f"WRAP{wrap}_IIR_TIMED_CLR", uart_reg(wrap, "IIR"))
        await self._lsr(wrap, "TIMED_IDLE")
        raw = dut.tb_uart_irq_raw.value
        assert raw.is_resolvable and (int(raw) >> wrap) & 1 == 0, (
            f"wrapper {wrap}: tb_uart_irq_raw reads {raw} before the timed character; the raw "
            f"line is low with IER clear and nothing pending"
        )
        frame_ns = self._frame_ns(_TIMEOUT_DIVISOR)
        bit_ns = frame_ns / _CHAR_BITS_8N1
        watcher = cocotb.start_soon(self._watch_irq_rise(wrap, _TIMEOUT_BOUND_CHARS * frame_ns))
        t_write = int(get_sim_time("ns"))
        await self._send(wrap, _TIMED_BYTE, "TIMED")
        await self._await_rx(wrap, "TIMED")
        t_seen = int(get_sim_time("ns"))
        t_irq = await watcher
        assert t_irq is not None, (
            f"wrapper {wrap}: tb_uart_irq_raw[{wrap}] never rose within {_TIMEOUT_BOUND_CHARS} "
            f"character times of a character left unread below the trigger level, with IER 0"
        )
        assert t_irq > t_seen, (
            f"wrapper {wrap}: the raw line rose at {t_irq} ns, before LSR reported the character "
            f"at {t_seen} ns"
        )
        # Arrival = the THR write plus one frame; the timeout counts from there.
        measured_chars = (t_irq - t_write) / frame_ns - 1.0
        tolerance_chars = _TIMEOUT_TOLERANCE_BITS / _CHAR_BITS_8N1
        assert abs(measured_chars - _TIMEOUT_CHARS) <= tolerance_chars, (
            f"wrapper {wrap}: the reception timeout raised the raw line {measured_chars:.2f} "
            f"character times after the character arrived (THR write at {t_write} ns plus one "
            f"{frame_ns} ns frame, line at {t_irq} ns); architecture.adoc puts it at "
            f"{_TIMEOUT_CHARS} character times, tolerance {_TIMEOUT_TOLERANCE_BITS} bit times"
        )
        ier = await self.csr_read(f"WRAP{wrap}_IER_TIMED_RB", uart_reg(wrap, "IER"))
        assert ier == 0, f"wrapper {wrap}: IER reads 0x{ier:08x} while the timeout is pending"
        iir = await self.csr_read(f"WRAP{wrap}_IIR_TIMED", uart_reg(wrap, "IIR"))
        reported = (iir & IIR_ID) >> IIR_ID_SHIFT
        assert iir & IIR_PENDING == 0 and reported == _IIR_ID_TIMEOUT, (
            f"wrapper {wrap}: IIR reads 0x{iir:02x} with IER 0 and the raw line high; the "
            f"timeout is reported pending with id 0x{_IIR_ID_TIMEOUT:x} without an IER enable"
        )
        combined = dut.tb_uart_irq_combined.value
        assert combined.is_resolvable, "tb_uart_irq_combined is X/Z"
        combined_bit = (int(combined) >> wrap) & 1
        await self._recv(wrap, "TIMED", _TIMED_BYTE)
        for _ in range(_TIMEOUT_POLLS):
            raw = dut.tb_uart_irq_raw.value
            assert raw.is_resolvable, "tb_uart_irq_raw is X/Z"
            if (int(raw) >> wrap) & 1 == 0:
                break
            await RisingEdge(dut.clk_smc_i)
        else:
            raise AssertionError(
                f"wrapper {wrap}: tb_uart_irq_raw[{wrap}] stayed high {_TIMEOUT_POLLS} cycles "
                f"after the timed-out character was read out"
            )
        cleared = await self.csr_read(f"WRAP{wrap}_IIR_TIMED_DRAINED", uart_reg(wrap, "IIR"))
        assert cleared & IIR_PENDING, (
            f"wrapper {wrap}: IIR still reports an interrupt pending (0x{cleared:02x}) after "
            f"the timed-out character was read out"
        )
        self.timed_chars[wrap] = measured_chars
        self.timed_legs += 1
        cocotb.log.info(
            "wrapper %d timed timeout: THR write at %d ns, LSR.DR seen at %d ns, raw line at "
            "%d ns; frame %d ns (%.0f ns/bit); %.2f character times after arrival; IER 0x%x, "
            "IIR 0x%02x, combined line bit %d",
            wrap,
            t_write,
            t_seen,
            t_irq,
            frame_ns,
            bit_ns,
            measured_chars,
            ier,
            iir,
            combined_bit,
        )

    async def _line_loopback_leg(self, wrap: int) -> None:
        """Line loopback deasserts the MSR levels and holds the receiver idle."""
        base = uart_base(wrap)
        await self.csr_write(f"WRAP{wrap}_LCR_DLAB_SLOW", uart_reg(wrap, "LCR"), LCR_DLAB)
        await self.csr_write(f"WRAP{wrap}_DLL_SLOW", base + DLL_OFFSET, _BURST_DIVISOR)
        await self.csr_write(f"WRAP{wrap}_DLM_SLOW", base + DLM_OFFSET, 0)
        await self.csr_write(
            f"WRAP{wrap}_LCR_8N1_SLOW", uart_reg(wrap, "LCR"), WLS_8_BITS & LCR_WLS
        )
        # Control: under MCR.LOOP the four MCR outputs feed the four MSR levels,
        # so with all four set the levels read 1 before line loopback drops them.
        msr_addr = uart_reg(wrap, "MSR")
        await self.csr_write(
            f"WRAP{wrap}_MCR_LOOP_ALL", uart_reg(wrap, "MCR"), MCR_LOOP | _MCR_OUTPUTS
        )
        await self.csr_read(f"WRAP{wrap}_MSR_LOOP_CLR", msr_addr)
        live = await self.csr_read(f"WRAP{wrap}_MSR_LOOP_ALL", msr_addr)
        assert live & MSR_LEVELS == MSR_LEVELS, (
            f"wrapper {wrap}: MSR reads 0x{live:02x} with MCR.LOOP and DTR, RTS, OUT1, OUT2 set; "
            f"all four level bits read 1 in that mode, so a level bit can be shown to read 1"
        )
        await self.csr_write(
            f"WRAP{wrap}_MCR_LINE", uart_reg(wrap, "MCR"), MCR_LINE_LOOPBACK | _MCR_OUTPUTS
        )
        await self._fcr(
            wrap,
            "BURST",
            FCR_FIFO_ENABLE | FCR_DMA_MODE_SELECT | FCR_XMIT_FIFO_RESET | FCR_RCVR_FIFO_RESET,
        )

        await self.csr_read(f"WRAP{wrap}_MSR_CLR", msr_addr)
        levels = await self.csr_read(f"WRAP{wrap}_MSR_LINE", msr_addr)
        assert levels & MSR_LEVELS == 0, (
            f"wrapper {wrap}: MSR reads 0x{levels:02x} with MCR.LINE_LOOPBACK set and the same "
            f"four MCR outputs; the programming guide says all four level bits read 0 in that mode"
        )

        await self._send(wrap, _LINE_LOOPBACK_BYTE, "LINE_QUIET")
        for _ in range(_DRAIN_POLLS):
            status = await self._lsr(wrap, "LINE_QUIET")
            assert status & LSR_DR == 0, (
                f"wrapper {wrap}: LSR reports received data while MCR.LINE_LOOPBACK is "
                f"set; in that mode the receiver input is held idle and the character "
                f"written into THR goes out of the transmit pin, not back into the receiver"
            )
            if status & LSR_TEMT:
                break
        else:
            raise AssertionError(
                f"wrapper {wrap}: the transmitter never reported itself empty within "
                f"{_DRAIN_POLLS} reads of a single character written into THR"
            )

        for byte in _TX_BURST:
            await self._send(wrap, byte, f"BURST{byte:02x}")
            self.burst_bytes += 1
        filled = await self._lsr(wrap, "BURST_FILLED")
        assert filled & LSR_THRE == 0, (
            f"wrapper {wrap}: LSR reports the transmitter empty (0x{filled:02x}) straight "
            f"after {len(_TX_BURST)} characters were written back to back into a "
            f"{_TX_FIFO_DEPTH}-deep transmit FIFO; it has to still be holding characters"
        )
        for _ in range(_DRAIN_POLLS):
            status = await self._lsr(wrap, "BURST_DRAIN")
            if status & LSR_TEMT:
                assert status & LSR_THRE, (
                    f"wrapper {wrap}: LSR reports the transmitter idle without reporting "
                    f"the holding register empty (0x{status:02x}) after the burst drained"
                )
                assert status & LSR_DR == 0, (
                    f"wrapper {wrap}: LSR reports received data after a burst sent with "
                    f"MCR.LINE_LOOPBACK set, which holds the receiver input idle"
                )
                break
        else:
            raise AssertionError(
                f"wrapper {wrap}: the transmit FIFO never drained within {_DRAIN_POLLS} "
                f"reads of a {len(_TX_BURST)}-character burst"
            )

        await self.csr_write(f"WRAP{wrap}_MCR_LOOP_BACK", uart_reg(wrap, "MCR"), MCR_LOOP)
        self.line_loopback_legs += 1

    # -- body ------------------------------------------------------------

    async def body(self) -> None:
        await self.wait_fuse_sense_done()
        wraps = smc_addr(WRAP_NUM)
        sent = set(_RBR_PAYLOAD) | set(_DMA_TRIGGER_PAYLOAD) | set(_RBR_OVERWRITE_PAIR)
        sent |= set(_TXRDY_PAIR)
        sent |= {_DMA_TIMEOUT_BYTE, _PARKED_BYTE, _LINE_LOOPBACK_BYTE, _TIMED_BYTE}
        assert len(sent) == len(_RBR_PAYLOAD) + len(_DMA_TRIGGER_PAYLOAD) + 8, (
            "the characters the legs send are not all distinct, so a character left behind "
            "by one leg could be mistaken for the character another leg sent"
        )
        assert len(_TX_BURST) > _TX_FIFO_DEPTH, (
            f"the burst is {len(_TX_BURST)} characters and the transmit FIFO is "
            f"{_TX_FIFO_DEPTH} deep, so the burst cannot fill it"
        )

        for wrap in range(wraps):
            await arm_uart(self, wrap)
            await self._receiver_buffer_leg(wrap)
            await self._dma_mode_leg(wrap)
            await self._timed_timeout_leg(wrap)
            if wrap == 0:
                await self._line_loopback_leg(wrap)
            await restore_uart(self, wrap)
            self.uarts += 1

        assert self.uarts == wraps, f"{self.uarts} of {wraps} UARTs exercised"
        assert self.rbr_bytes == wraps * len(_RBR_PAYLOAD), (
            f"{self.rbr_bytes} characters compared through the receiver buffer register, "
            f"{wraps * len(_RBR_PAYLOAD)} were sent with the FIFOs off"
        )
        expected_dma = wraps * (1 + len(_DMA_TRIGGER_PAYLOAD))
        assert self.dma_bytes == expected_dma, (
            f"{self.dma_bytes} characters compared in DMA mode 1, {expected_dma} were sent"
        )
        assert self.timeout_legs == wraps, (
            f"{self.timeout_legs} reception-timeout legs for {wraps} UARTs"
        )
        assert len(self.trigger_ids) == wraps and set(self.trigger_ids.values()) == {_IIR_ID_RDR}
        assert set(self.txrdy_samples) == {"DMA1", "DMA0"}, (
            f"transmit-ready observed in {sorted(self.txrdy_samples)}; both modes run on wrapper 0"
        )
        assert self.overwrite_legs == wraps, (
            f"{self.overwrite_legs} receiver-buffer overwrite legs for {wraps} UARTs"
        )
        assert self.timed_legs == wraps and len(self.timed_chars) == wraps, (
            f"{self.timed_legs} timed reception-timeout legs for {wraps} UARTs"
        )
        assert self.line_loopback_legs == 1, (
            f"{self.line_loopback_legs} line-loopback legs; the mode substitutes the "
            f"receive pin onto the transmit pin and only wrapper 0 has its receive pad "
            f"driven, so it runs there exactly once"
        )
        assert self.burst_bytes == len(_TX_BURST), (
            f"{self.burst_bytes} characters burst into the transmit FIFO, "
            f"{len(_TX_BURST)} were meant to be"
        )

        sb = getattr(getattr(self, "env", None), "scoreboard", None)
        assert sb is not None, (
            "no scoreboard on this sequence's env, so the CSR traffic cannot be "
            "corroborated independently of the sequence's own counter"
        )
        floor = wraps * _MIN_ACCESSES_PER_WRAP + _LINE_LOOPBACK_ACCESSES
        assert self.accesses >= floor, (
            f"the sequence issued {self.accesses} SEP_IN accesses; a run that drove three "
            f"mode selectors on {wraps} UART(s) cannot have issued fewer than {floor}"
        )
        assert sb.sys_axi_checks_seen >= self.accesses, (
            f"the scoreboard checked only {sb.sys_axi_checks_seen} SEP_IN AXI item(s) but "
            f"this sequence issued {self.accesses}, so the traffic never reached it"
        )

        cocotb.log.info(
            "CHK-UART-RBR-PATH: on %d UART(s) FCR.FIFO_ENABLE was written clear with a "
            "character unread in the receive FIFO, IIR reported FIFOS_ENABLED=0x%x and LSR "
            "stopped reporting received data, and %d further character(s) sent with the "
            "FIFOs off came back out of the receiver buffer register unchanged before the "
            "FIFOs were enabled again and IIR reported 0x%x",
            self.uarts,
            _FIFOS_OFF,
            self.rbr_bytes,
            _FIFOS_ON,
        )
        cocotb.log.info(
            "CHK-UART-RBR-OVERWRITE-NO-OE: on %d UART(s) with the FIFOs off 0x%02x was sent "
            "and seen in the receiver (LSR.DR) but left unread, then 0x%02x was sent; LSR "
            "reported data with OE clear on every read, RBR returned 0x%02x (the second) and "
            "LSR reported no data afterwards",
            self.overwrite_legs,
            _RBR_OVERWRITE_PAIR[0],
            _RBR_OVERWRITE_PAIR[1],
            _RBR_OVERWRITE_PAIR[1],
        )
        cocotb.log.info(
            "CHK-UART-RX-TIMEOUT-4CHAR: on %d UART(s) with IER 0 the raw interrupt line rose "
            "%s character times after one character arrived below the trigger level (THR write "
            "plus one frame at divisor %d), within %.1f bit times of the four character times "
            "architecture.adoc states",
            self.timed_legs,
            ", ".join(f"w{w}={c:.2f}" for w, c in sorted(self.timed_chars.items())),
            _TIMEOUT_DIVISOR,
            _TIMEOUT_TOLERANCE_BITS,
        )
        cocotb.log.info(
            "CHK-UART-RX-TIMEOUT-IER-INDEPENDENT: on %d UART(s) the raw line was high and IIR "
            "reported the Reception Timeout id 0x%x pending while IER read 0, and the RBR read "
            "dropped the line and left IIR with none pending",
            self.timed_legs,
            _IIR_ID_TIMEOUT,
        )
        cocotb.log.info(
            "CHK-UART-DMA-MODE-1: on %d UART(s) FCR selected DMA mode 1 with the receive "
            "trigger at %d characters, and %d character(s) sent in that mode came back in "
            "order, both below the trigger level (timeout id 0x%x) and with it reached (IIR id "
            "0x%x on every wrapper); on wrapper 0 tb_uart0_tx_ready read %s with two characters "
            "queued in mode 1 and %s in mode 0",
            self.uarts,
            _TRIGGER_4_CHARS_DEPTH,
            self.dma_bytes,
            _IIR_ID_TIMEOUT,
            _IIR_ID_RDR,
            self.txrdy_samples["DMA1"],
            self.txrdy_samples["DMA0"],
        )
        cocotb.log.info(
            "CHK-UART-RX-TIMEOUT: on %d UART(s) a single character left unread below the "
            "trigger level made IIR report an interrupt pending with the Reception Timeout "
            "id 0x%x, which is the only source that can be pending below the trigger, and "
            "IIR reported none pending once that character was read out",
            self.timeout_legs,
            _IIR_ID_TIMEOUT,
        )
        cocotb.log.info(
            "CHK-UART-LINE-LOOPBACK: on wrapper 0 all four MSR level bits read 1 under "
            "MCR.LOOP with DTR, RTS, OUT1 and OUT2 set, then with MCR.LINE_LOOPBACK set and "
            "the same outputs all four read 0 as the programming guide requires, a character "
            "written into "
            "THR was transmitted to completion without the receiver ever reporting data, "
            "and a %d-character burst into the %d-deep transmit FIFO left LSR reporting the "
            "holding register non-empty and then drained to both TEMT and THRE set",
            self.burst_bytes,
            _TX_FIFO_DEPTH,
        )
