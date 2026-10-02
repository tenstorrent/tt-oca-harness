# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The UART mode selectors no leaf drives: FIFOs off, DMA mode 1, line loopback.

Every UART leaf in the package configures the UART the same way -- the FIFOs
enabled, DMA mode 0, the receive trigger at one character and `MCR.LOOP` for the
loopback -- so three of the core's mode selectors have never been moved off
their reset or their setup value on any wrapper:

* **The receive path with the FIFOs disabled.** `FCR.FIFO_ENABLE` resets clear,
  and `hw/ip/uart/uart_16550/doc/architecture.adoc` describes the two receive
  paths the 16550 has: software reads "from RBR or FIFO". Every leaf enables the
  FIFOs, so the receiver buffer register itself -- the path a character takes
  when they are off -- has never held a character.
* **DMA mode 1.** `programming.adoc` lists "Select DMA mode if using DMA
  transfers" as a step of FIFO configuration and `uart_16550_main_wo.rdl` gives
  FCR a `DMA_MODE_SELECT` bit, but no leaf writes it, so the receive and
  transmit ready handshakes it selects have never run.
* **Line loopback.** `MCR.LINE_LOOPBACK` is the second of the two loopback modes
  `programming.adoc` documents, and no leaf sets it.

The leaf drives all three and checks what each one is specified to do.

**The receive path with the FIFOs disabled.** A character is left unread in the
receive FIFO and `FCR.FIFO_ENABLE` is then written clear. `IIR.FIFOS_ENABLED`
has to report the FIFOs off -- `uart_16550_main.rdl` gives that field `0x0` --
and `LSR.DR` has to read clear, because the character parked in the FIFO is no
longer on the path software reads. Two further characters are then sent one at a
time and compared against what comes back, which is the only traffic in the
package that goes through the receiver buffer register rather than the FIFO.

**DMA mode 1 and the reception timeout.** With the FIFOs on, DMA mode 1
selected and `FCR.RCVR_TRIGGER` programmed to four characters, one character is
sent and left unread. Its trigger level is not reached, so the only interrupt
that can arise is the reception timeout `architecture.adoc` fixes at four
character times, and `uart_16550_main.rdl` names id `0x6` for it. IIR has to
report exactly that, and no interrupt pending once the character is read out.
Four characters are then sent and read back in order, which is the same mode
with the trigger level reached instead of timed out.

**Line loopback.** `programming.adoc`: "With `MCR.LINE_LOOPBACK` set, the modem
inputs are routed straight back out to the modem outputs and all four MSR level
bits read `0`." The leaf sets it and requires those four bits to read 0. In this
mode the receiver input is held idle, so a character written into THR must be
transmitted without ever being received: the leaf polls until `LSR.TEMT` reports
the transmitter drained and requires `LSR.DR` clear on every read up to that
point.

**The transmit FIFO under DMA mode 1.** Still in line loopback, the divisor is
slowed and a burst longer than `smc_config_pkg::UartTxFifoDepth` is written
into THR without polling, so the transmit FIFO reaches its full condition while
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

from .smc_addr_map import smc_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_log_engine_utils import (
    ARM_UART_ACCESSES,
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
    LSR_TEMT,
    LSR_THRE,
    MCR_LINE_LOOPBACK,
    MCR_LOOP,
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
# uart_16550_main.rdl, IIR.INTERRUPT_ID: "0x6 - Reception Timeout Interrupt".
_IIR_ID_TIMEOUT = 0x6
# uart_16550_main_wo.rdl, FCR.RCVR_TRIGGER: "0x1 - 4 characters". One character
# is below it, so the watermark cannot be what raises the interrupt below.
_TRIGGER_4_CHARS = 0x1
_TRIGGER_4_CHARS_DEPTH = 4

# Characters for the receiver-buffer leg, the DMA-mode leg and the character
# that is parked in the receive FIFO before the FIFOs are turned off. All
# distinct and spread across the byte, so a stuck bit shows up and no leg can
# pass on a character another leg left behind.
_RBR_PAYLOAD = (0xC3, 0x3C)
_DMA_TIMEOUT_BYTE = 0x96
_DMA_TRIGGER_PAYLOAD = (0x11, 0x22, 0x44, 0x88)
_PARKED_BYTE = 0x69
_LINE_LOOPBACK_BYTE = 0x5A

# smc_config_pkg.sv gives the SMC UARTs UART_TX_FIFO_DEPTH = 32. The burst is
# comfortably longer so the transmit FIFO reaches its full condition even if
# the CSR port delivers a write every few cycles.
_TX_FIFO_DEPTH = 32
_TX_BURST = tuple(range(64))
# uart_16550_dl.rdl: "baud_rate = system_clock_frequency / (16 * (divisor +
# 1))". `arm_uart` uses the fastest divisor the RDL allows; the burst leg wants
# the transmitter slow relative to the CSR port so the FIFO fills, and this
# divisor makes a character five times longer than that.
_BURST_DIVISOR = 4

# Polls of LSR or IIR allowed per expected event. Each bound is a liveness
# ceiling on an event that has to happen: expiry is a FAILURE, never a pass.
_RX_POLLS_PER_BYTE = 400
_TIMEOUT_POLLS = 600
_DRAIN_POLLS = 4000

# SEP_IN accesses one wrapper needs: the UART setup and restore, the
# receiver-buffer leg and the DMA-mode leg.
_MIN_ACCESSES_PER_WRAP = ARM_UART_ACCESSES + RESTORE_UART_ACCESSES + 15 + 22
# SEP_IN accesses the line-loopback leg adds on wrapper 0: the divisor change,
# MCR, FCR, the two MSR reads, the quiet character and its drain poll, the
# burst and the two LSR reads around it, and the MCR restore.
_LINE_LOOPBACK_ACCESSES = 13 + len(_TX_BURST)


class smc_uart_core_mode_select_test_seq(SmcCsrSeq):
    """Drive the UART mode selectors no other leaf moves, and check each one."""

    def __init__(self, name: str = "smc_uart_core_mode_select_test_seq") -> None:
        super().__init__(name)
        self.uarts = 0
        self.rbr_bytes = 0
        self.dma_bytes = 0
        self.timeout_legs = 0
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
        # receiver is then given until it raises an interrupt -- the trigger
        # level reached, or the timeout on a level that never fills -- before
        # any of them is read back.
        for index, byte in enumerate(_DMA_TRIGGER_PAYLOAD):
            label = f"DMA_TRIG{index}"
            await self._send(wrap, byte, label)
            await self._await_tx_drained(wrap, label)
        for _ in range(_TIMEOUT_POLLS):
            iir = await self.csr_read(f"WRAP{wrap}_IIR_TRIGGER", uart_reg(wrap, "IIR"))
            if iir & IIR_PENDING == 0:
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

        await self.csr_write(f"WRAP{wrap}_IER_CLR", uart_reg(wrap, "IER"), 0)
        await self._fcr(wrap, "DMA_MODE_0", FCR_FIFO_ENABLE | FCR_RCVR_FIFO_RESET)

    async def _line_loopback_leg(self, wrap: int) -> None:
        """Line loopback deasserts the MSR levels and holds the receiver idle."""
        base = uart_base(wrap)
        await self.csr_write(f"WRAP{wrap}_LCR_DLAB_SLOW", uart_reg(wrap, "LCR"), LCR_DLAB)
        await self.csr_write(f"WRAP{wrap}_DLL_SLOW", base + DLL_OFFSET, _BURST_DIVISOR)
        await self.csr_write(f"WRAP{wrap}_DLM_SLOW", base + DLM_OFFSET, 0)
        await self.csr_write(
            f"WRAP{wrap}_LCR_8N1_SLOW", uart_reg(wrap, "LCR"), WLS_8_BITS & LCR_WLS
        )
        await self.csr_write(f"WRAP{wrap}_MCR_LINE", uart_reg(wrap, "MCR"), MCR_LINE_LOOPBACK)
        await self._fcr(
            wrap,
            "BURST",
            FCR_FIFO_ENABLE | FCR_DMA_MODE_SELECT | FCR_XMIT_FIFO_RESET | FCR_RCVR_FIFO_RESET,
        )

        msr_addr = uart_reg(wrap, "MSR")
        await self.csr_read(f"WRAP{wrap}_MSR_CLR", msr_addr)
        levels = await self.csr_read(f"WRAP{wrap}_MSR_LINE", msr_addr)
        assert levels & MSR_LEVELS == 0, (
            f"wrapper {wrap}: MSR reads 0x{levels:02x} with MCR.LINE_LOOPBACK set; the "
            f"programming guide says all four level bits read 0 in that mode"
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
        sent = set(_RBR_PAYLOAD) | set(_DMA_TRIGGER_PAYLOAD)
        sent |= {_DMA_TIMEOUT_BYTE, _PARKED_BYTE, _LINE_LOOPBACK_BYTE}
        assert len(sent) == len(_RBR_PAYLOAD) + len(_DMA_TRIGGER_PAYLOAD) + 3, (
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
            "CHK-UART-DMA-MODE-1: on %d UART(s) FCR selected DMA mode 1 with the receive "
            "trigger at %d characters, and %d character(s) sent in that mode came back in "
            "order, both below the trigger level and with it reached",
            self.uarts,
            _TRIGGER_4_CHARS_DEPTH,
            self.dma_bytes,
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
            "CHK-UART-LINE-LOOPBACK: with MCR.LINE_LOOPBACK set on wrapper 0 all four MSR "
            "level bits read 0 as the programming guide requires, a character written into "
            "THR was transmitted to completion without the receiver ever reporting data, "
            "and a %d-character burst into the %d-deep transmit FIFO left LSR reporting the "
            "holding register non-empty and then drained to both TEMT and THRE set",
            self.burst_bytes,
            _TX_FIFO_DEPTH,
        )
