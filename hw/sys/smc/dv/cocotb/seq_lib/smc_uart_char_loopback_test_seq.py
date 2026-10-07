# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A character through each UART's own loopback, and the registers it moves.

`smc_uart_log_engine_field_sweep_test` writes the UART's software-owned
registers, and the log-engine leaves read LSR and RBR while the engine feeds
the transmitter. This leaf drives the UART's own transmit holding register, the
write side of RBR, IIR, LSR and MSR, and the external-register handshake behind
RBR.

This leaf sends characters through each UART's system loopback from the CSR
port and checks the registers that move, on all four wrappers:

* **The write-only fields, read back where their effect shows.** FCR is
  write-only, so the only way to see that `FIFO_ENABLE` landed is `IIR`:
  `uart_16550_main.rdl` gives `IIR.FIFOS_ENABLED` the value `0x3` when the
  FIFOs are enabled and `0x0` when they are not, and the leaf drives FCR both
  ways and requires IIR to follow. `FCR.RCVR_FIFO_RESET` is `singlepulse`, and
  its effect shows as `LSR.DR` going away with a character still unread.
* **A character round trip.** A byte written into THR comes back through the
  receiver of the same UART, and the leaf compares what it read out of RBR
  against what it wrote. This is also the only access that reaches the
  external-register interface RBR sits behind.
* **Interrupt identification.** With `IER.ERBFI` set and a byte waiting, IIR
  has to report interrupt pending with the Received Data Ready id the RDL
  names (`0x2`), and once RBR is drained it has to report no interrupt pending
  again. `IIR.INTERRUPT_PENDING` is active low, which is why the pending case
  is the 0.
* **Modem status under loopback.** `doc/programmer/src/smc-programming.adoc`
  says that with `MCR.LOOP` set "`MSR` is fed from the `MCR` bits" (CTS from
  RTS, DSR from DTR, RI from OUT1, DCD from OUT2), so raising the four
  MCR outputs must raise exactly those four MSR levels, and dropping them must
  clear them. The sticky delta bits separate on the same two legs: DCTS, DDSR
  and DDCD set on either edge, while TERI sets only when RI goes from 1 to 0,
  so the rising leg must leave TERI clear and the falling leg must set it. The
  deltas are cleared by any read of MSR, so each observation is a single read.
* **Writes to the read-only registers.** LSR and MSR have no write side at
  all, so a write to either address must leave them reading what they read
  before. RBR and IIR share their addresses with THR and FCR, so a write there
  is the write-only register's write and is checked as such above.

The UART is put back to its reset configuration afterwards, and `MCR.LOOP`
keeps every character inside the UART, so no pad carries them.
"""

from __future__ import annotations

import cocotb

from .smc_addr_map import smc_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_log_engine_utils import (
    ARM_UART_ACCESSES,
    FCR_FIFO_ENABLE,
    FCR_RCVR_FIFO_RESET,
    IER_ERBFI,
    IIR_FIFOS_ENABLED,
    IIR_FIFOS_SHIFT,
    IIR_ID,
    IIR_ID_SHIFT,
    IIR_PENDING,
    LSR_DR,
    LSR_LINE_ERRORS,
    LSR_TEMT,
    LSR_THRE,
    MCR_DTR,
    MCR_LOOP,
    MCR_OUT1,
    MCR_OUT2,
    MCR_RTS,
    MSR_ANY_EDGE_DELTAS,
    MSR_LEVELS,
    MSR_TERI,
    RBR_DATA,
    RESTORE_UART_ACCESSES,
    THR_OFFSET,
    WRAP_NUM,
    arm_uart,
    restore_uart,
    uart_base,
    uart_reg,
)

# uart_16550_main.rdl, IIR.FIFOS_ENABLED: "0x0 - FIFOs are disabled,
# 0x3 - FIFOs are enabled".
_FIFOS_ON = 0x3
_FIFOS_OFF = 0x0
# uart_16550_main.rdl, IIR.INTERRUPT_ID: "0x2 - Received Data Ready Interrupt".
_IIR_ID_RX_READY = 0x2
# The four modem outputs the loopback feeds back into the four MSR levels.
_MCR_OUTPUTS = MCR_DTR | MCR_RTS | MCR_OUT1 | MCR_OUT2

# Characters sent through each UART. Distinct and spread across the byte so a
# stuck bit in the serialiser or the receiver shows up.
_PAYLOAD = (0x00, 0xFF, 0xA5, 0x5A, 0x01, 0x80)
# A byte sent only to be discarded by the receive-FIFO reset.
_FLUSH_BYTE = 0x3C
# A word written at the read-only registers. Every bit set, so a register that
# took any of it shows a change.
_WRITE_TO_READ_ONLY = 0xFFFF_FFFF

# Polls of LSR allowed per expected byte. The bound is a liveness ceiling:
# expiry is a FAILURE.
_RX_POLLS_PER_BYTE = 400
# Polls allowed for the receive FIFO to go empty after its reset.
_FLUSH_POLLS = 400

# SEP_IN accesses one wrapper needs: the UART setup and restore, the
# FIFO-enable leg, the round trip, the interrupt-identification leg, the modem
# leg, the receive-FIFO reset leg and the two read-only writes.
_MIN_ACCESSES_PER_WRAP = (
    ARM_UART_ACCESSES
    + RESTORE_UART_ACCESSES
    + 5  # FIFO-enable leg: IIR, FCR off, IIR, FCR on, IIR
    + 3 * len(_PAYLOAD)  # per byte: THR write, at least one LSR poll, RBR read
    + 2  # the idle LSR read before the round trip and the quiet one after
    + 7  # interrupt-identification leg
    + 7  # modem leg
    + 5  # receive-FIFO reset leg
    + 4  # the two writes at the read-only addresses and their readbacks
)


class smc_uart_char_loopback_test_seq(SmcCsrSeq):
    """Send characters through every UART's loopback and check what moves."""

    def __init__(self, name: str = "smc_uart_char_loopback_test_seq") -> None:
        super().__init__(name)
        self.bytes_checked = 0
        self.uarts = 0
        self.fifo_legs = 0
        self.intr_legs = 0
        self.modem_legs = 0

    # -- primitives ------------------------------------------------------

    async def _lsr(self, wrap: int, label: str) -> int:
        status = await self.csr_read(f"WRAP{wrap}_LSR_{label}", uart_reg(wrap, "LSR"))
        assert status & LSR_LINE_ERRORS == 0, (
            f"wrapper {wrap} [{label}]: LSR reports 0x{status & LSR_LINE_ERRORS:x} in its "
            f"overrun, parity, framing and break bits; the loopback did not carry the "
            f"character intact"
        )
        return status

    async def _send(self, wrap: int, byte: int) -> None:
        await self.csr_write(f"WRAP{wrap}_THR_{byte:02x}", uart_base(wrap) + THR_OFFSET, byte)

    async def _await_rx(self, wrap: int, label: str) -> None:
        for _ in range(_RX_POLLS_PER_BYTE):
            if await self._lsr(wrap, label) & LSR_DR:
                return
        raise AssertionError(
            f"wrapper {wrap} [{label}]: LSR never reported received data within "
            f"{_RX_POLLS_PER_BYTE} reads of a character written into THR, so the loopback "
            f"did not carry it"
        )

    async def _recv(self, wrap: int, label: str) -> int:
        byte = await self.csr_read(f"WRAP{wrap}_RBR_{label}", uart_reg(wrap, "RBR"))
        return byte & RBR_DATA

    async def _iir(self, wrap: int, label: str) -> int:
        return await self.csr_read(f"WRAP{wrap}_IIR_{label}", uart_reg(wrap, "IIR"))

    # -- legs ------------------------------------------------------------

    async def _fifo_enable_leg(self, wrap: int) -> None:
        """FCR is write-only; IIR is where its enable shows."""
        base = uart_base(wrap)
        armed = await self._iir(wrap, "FIFOS_ON")
        assert (armed & IIR_FIFOS_ENABLED) >> IIR_FIFOS_SHIFT == _FIFOS_ON, (
            f"wrapper {wrap}: IIR reports FIFOS_ENABLED="
            f"{(armed & IIR_FIFOS_ENABLED) >> IIR_FIFOS_SHIFT} after the setup enabled the "
            f"FIFOs; the RDL gives that field 0x{_FIFOS_ON:x} when they are on"
        )
        await self.csr_write(f"WRAP{wrap}_FCR_OFF", base + 0x8, 0)
        off = await self._iir(wrap, "FIFOS_OFF")
        assert (off & IIR_FIFOS_ENABLED) >> IIR_FIFOS_SHIFT == _FIFOS_OFF, (
            f"wrapper {wrap}: IIR reports FIFOS_ENABLED="
            f"{(off & IIR_FIFOS_ENABLED) >> IIR_FIFOS_SHIFT} after a write of 0 into the "
            f"write-only FCR; the RDL gives that field 0x{_FIFOS_OFF:x} when they are off"
        )
        await self.csr_write(f"WRAP{wrap}_FCR_ON", base + 0x8, FCR_FIFO_ENABLE)
        back = await self._iir(wrap, "FIFOS_BACK")
        assert (back & IIR_FIFOS_ENABLED) >> IIR_FIFOS_SHIFT == _FIFOS_ON, (
            f"wrapper {wrap}: IIR reports FIFOS_ENABLED="
            f"{(back & IIR_FIFOS_ENABLED) >> IIR_FIFOS_SHIFT} after the FIFOs were enabled "
            f"again"
        )
        self.fifo_legs += 1

    async def _round_trip(self, wrap: int) -> None:
        idle = await self._lsr(wrap, "IDLE")
        assert idle & LSR_DR == 0 and idle & LSR_THRE and idle & LSR_TEMT, (
            f"wrapper {wrap}: LSR reads 0x{idle:02x} before anything was sent; the "
            f"transmitter has to be empty and the receiver quiet for the round trip below "
            f"to mean anything"
        )
        for byte in _PAYLOAD:
            await self._send(wrap, byte)
            await self._await_rx(wrap, f"RX_{byte:02x}")
            got = await self._recv(wrap, f"{byte:02x}")
            assert got == byte, (
                f"wrapper {wrap}: a byte written into THR as 0x{byte:02x} came back out of "
                f"RBR as 0x{got:02x}"
            )
            self.bytes_checked += 1
        quiet = await self._lsr(wrap, "QUIET")
        assert quiet & LSR_DR == 0, (
            f"wrapper {wrap}: the receiver still reports data after every byte was read "
            f"out, so the loopback delivered more than was sent"
        )

    async def _interrupt_id_leg(self, wrap: int) -> None:
        await self.csr_write(f"WRAP{wrap}_IER_RX", uart_reg(wrap, "IER"), IER_ERBFI)
        await self._send(wrap, _PAYLOAD[0])
        await self._await_rx(wrap, "INTR")
        pending = await self._iir(wrap, "PENDING")
        assert pending & IIR_PENDING == 0, (
            f"wrapper {wrap}: IIR reads 0x{pending:02x} with a character waiting and the "
            f"received-data interrupt enabled; INTERRUPT_PENDING is active low, so it has "
            f"to read 0"
        )
        assert (pending & IIR_ID) >> IIR_ID_SHIFT == _IIR_ID_RX_READY, (
            f"wrapper {wrap}: IIR reports interrupt id "
            f"{(pending & IIR_ID) >> IIR_ID_SHIFT} with a character waiting; the RDL names "
            f"0x{_IIR_ID_RX_READY:x} for Received Data Ready"
        )
        got = await self._recv(wrap, "INTR")
        assert got == _PAYLOAD[0], (
            f"wrapper {wrap}: the byte behind the interrupt read back as 0x{got:02x}, not "
            f"0x{_PAYLOAD[0]:02x}"
        )
        drained = await self._iir(wrap, "DRAINED")
        assert drained & IIR_PENDING, (
            f"wrapper {wrap}: IIR still reports an interrupt pending (0x{drained:02x}) "
            f"after the only waiting character was read out of RBR"
        )
        await self.csr_write(f"WRAP{wrap}_IER_CLR", uart_reg(wrap, "IER"), 0)
        self.intr_legs += 1

    async def _modem_leg(self, wrap: int) -> None:
        """MCR drives MSR through the system loopback the programming guide fixes."""
        mcr = uart_reg(wrap, "MCR")
        msr = uart_reg(wrap, "MSR")
        # One read to clear the sticky deltas the loopback left behind, then a
        # second to establish the level the outputs rest at.
        await self.csr_read(f"WRAP{wrap}_MSR_CLR", msr)
        settled = await self.csr_read(f"WRAP{wrap}_MSR_IDLE", msr)
        assert settled & MSR_LEVELS == 0, (
            f"wrapper {wrap}: MSR reads 0x{settled:02x} with every MCR output deasserted; "
            f"under MCR.LOOP the four level bits are fed from those outputs, so they have "
            f"to read 0"
        )
        await self.csr_write(f"WRAP{wrap}_MCR_OUTPUTS", mcr, MCR_LOOP | _MCR_OUTPUTS)
        raised = await self.csr_read(f"WRAP{wrap}_MSR_RAISED", msr)
        assert raised & MSR_LEVELS == MSR_LEVELS, (
            f"wrapper {wrap}: MSR reads 0x{raised:02x} with all four MCR outputs asserted; "
            f"under MCR.LOOP CTS follows RTS, DSR follows DTR, RI follows OUT1 and DCD "
            f"follows OUT2, so all four level bits have to be set"
        )
        assert raised & MSR_ANY_EDGE_DELTAS == MSR_ANY_EDGE_DELTAS, (
            f"wrapper {wrap}: MSR reads 0x{raised:02x}; CTS, DSR and DCD all changed, so "
            f"DCTS, DDSR and DDCD have to be set in the read that reports it"
        )
        assert raised & MSR_TERI == 0, (
            f"wrapper {wrap}: MSR reads 0x{raised:02x} with TERI set after RI went from 0 "
            f"to 1; the RDL sets TERI only when RI changes from 1 to 0"
        )
        await self.csr_write(f"WRAP{wrap}_MCR_LOOP_ONLY", mcr, MCR_LOOP)
        dropped = await self.csr_read(f"WRAP{wrap}_MSR_DROPPED", msr)
        assert dropped & MSR_LEVELS == 0, (
            f"wrapper {wrap}: MSR reads 0x{dropped:02x} after the MCR outputs were "
            f"deasserted again; the four level bits have to follow them back down"
        )
        assert dropped & MSR_ANY_EDGE_DELTAS == MSR_ANY_EDGE_DELTAS, (
            f"wrapper {wrap}: MSR reads 0x{dropped:02x}; CTS, DSR and DCD changed again, "
            f"so DCTS, DDSR and DDCD have to be set again in this read"
        )
        assert dropped & MSR_TERI == MSR_TERI, (
            f"wrapper {wrap}: MSR reads 0x{dropped:02x} without TERI after RI went from 1 "
            f"to 0; that trailing edge is the one edge the RDL says sets it"
        )
        self.modem_legs += 1

    async def _fifo_reset_leg(self, wrap: int) -> None:
        """FCR.RCVR_FIFO_RESET is singlepulse; the receiver going empty is its effect."""
        await self._send(wrap, _FLUSH_BYTE)
        await self._await_rx(wrap, "FLUSH")
        await self.csr_write(
            f"WRAP{wrap}_FCR_RX_RESET",
            uart_base(wrap) + 0x8,
            FCR_FIFO_ENABLE | FCR_RCVR_FIFO_RESET,
        )
        for _ in range(_FLUSH_POLLS):
            if await self._lsr(wrap, "FLUSHED") & LSR_DR == 0:
                self.fifo_legs += 1
                return
        raise AssertionError(
            f"wrapper {wrap}: LSR still reports received data {_FLUSH_POLLS} reads after "
            f"FCR.RCVR_FIFO_RESET was written with a character waiting, so the receive "
            f"FIFO was not cleared"
        )

    async def _read_only_writes(self, wrap: int) -> None:
        """LSR and MSR have no write side; a write must leave them as they read."""
        for name in ("LSR", "MSR"):
            addr = uart_reg(wrap, name)
            before = await self.csr_read(f"WRAP{wrap}_{name}_BEFORE_WR", addr)
            await self.csr_write(f"WRAP{wrap}_{name}_WR", addr, _WRITE_TO_READ_ONLY)
            after = await self.csr_read(f"WRAP{wrap}_{name}_AFTER_WR", addr)
            assert after == before, (
                f"wrapper {wrap}: {name} read 0x{before:02x} before a write of "
                f"0x{_WRITE_TO_READ_ONLY:08x} and 0x{after:02x} after it; the RDL makes "
                f"every field of it `sw = r`, so the write has to take no effect"
            )

    # -- body ------------------------------------------------------------

    async def body(self) -> None:
        await self.wait_fuse_sense_done()
        wraps = smc_addr(WRAP_NUM)
        assert len(set(_PAYLOAD)) == len(_PAYLOAD), "the payload bytes are not distinct"

        for wrap in range(wraps):
            await arm_uart(self, wrap)
            await self._fifo_enable_leg(wrap)
            await self._round_trip(wrap)
            await self._interrupt_id_leg(wrap)
            await self._modem_leg(wrap)
            await self._fifo_reset_leg(wrap)
            await self._read_only_writes(wrap)
            await restore_uart(self, wrap)
            self.uarts += 1

        assert self.uarts == wraps, f"{self.uarts} of {wraps} UARTs exercised"
        assert self.bytes_checked == wraps * len(_PAYLOAD), (
            f"{self.bytes_checked} bytes compared, {wraps * len(_PAYLOAD)} were sent"
        )
        assert self.fifo_legs == 2 * wraps and self.intr_legs == wraps, (
            f"{self.fifo_legs} FIFO legs and {self.intr_legs} interrupt legs for {wraps} UARTs"
        )
        assert self.modem_legs == wraps, f"{self.modem_legs} modem legs for {wraps} UARTs"
        sb = getattr(getattr(self, "env", None), "scoreboard", None)
        assert sb is not None, (
            "no scoreboard on this sequence's env, so the CSR traffic cannot be "
            "corroborated independently of the sequence's own counter"
        )
        floor = wraps * _MIN_ACCESSES_PER_WRAP
        assert self.accesses >= floor, (
            f"the sequence issued {self.accesses} SEP_IN accesses; a run that sent "
            f"{wraps * len(_PAYLOAD)} characters through {wraps} UART(s) cannot have "
            f"issued fewer than {floor}"
        )
        assert sb.sys_axi_checks_seen >= self.accesses, (
            f"the scoreboard checked only {sb.sys_axi_checks_seen} SEP_IN AXI item(s) but "
            f"this sequence issued {self.accesses}, so the traffic never reached it"
        )

        cocotb.log.info(
            "CHK-UART-CHAR-LOOPBACK: %d bytes written into the transmit holding register "
            "of %d UART(s) came back out of the receiver of the same UART unchanged, with "
            "the transmitter reported empty before the first and the receiver quiet after "
            "the last, and no overrun, parity, framing or break error on any LSR read",
            self.bytes_checked,
            self.uarts,
        )
        cocotb.log.info(
            "CHK-UART-FCR-EFFECT: on %d UART(s) the write-only FCR was driven both ways "
            "and IIR reported FIFOS_ENABLED=0x%x and 0x%x to match, and a write of the "
            "singlepulse receive-FIFO reset with a character waiting made LSR stop "
            "reporting received data",
            self.uarts,
            _FIFOS_ON,
            _FIFOS_OFF,
        )
        cocotb.log.info(
            "CHK-UART-IIR-RX-READY: on %d UART(s) IIR reported an interrupt pending with "
            "the Received Data Ready id 0x%x while a character waited and the received-data "
            "interrupt was enabled, and reported none pending once RBR was drained",
            self.intr_legs,
            _IIR_ID_RX_READY,
        )
        cocotb.log.info(
            "CHK-UART-MSR-LOOPBACK: on %d UART(s) raising all four MCR outputs raised "
            "exactly the four MSR level bits the programming guide maps them to, with "
            "DCTS, DDSR and DDCD set and TERI clear because RI had risen; dropping them "
            "cleared the levels and set all four deltas including the TERI the falling "
            "edge of RI owns; and a write at the LSR and MSR addresses left both reading "
            "what they read before, which is their `sw = r` contract",
            self.modem_legs,
        )
