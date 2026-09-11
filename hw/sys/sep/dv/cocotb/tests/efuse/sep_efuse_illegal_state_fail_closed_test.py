# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""eFuse read and program FSMs fail closed from an illegal state.

``efuse_read_interface`` and ``efuse_program_interface`` each hold a two-bit
state whose only legal encodings are ``2'b01`` (idle) and ``2'b10`` (waiting for
the bank response). ``2'b00`` and ``2'b11`` are unreachable by design, so the
recovery the RTL specifies for them cannot be provoked by any frontdoor
stimulus. This leaf injects one, for one cycle, and grades the recovery.

The contract, from the design's own assertions:

* while the state is illegal, no command reaches the bank
  (``IllegalReadStateSuppressesRequest_A`` / ``IllegalProgramState…``);
* on the next edge the FSM is back in idle, not busy, reporting done with the
  error flag set, still issuing no command, and returning the error sentinel
  (``IllegalReadStateFailsClosed_A`` / ``IllegalProgramState…``).

Failing closed is the point: an FSM that resumed a read from a corrupted state
could return fuse data it never legitimately fetched.

Every check is on a DUT output. The injections are bracketed by a frontdoor OTP
read that must move the machine: fuse sense does not use this FSM, so only a
real EFUSE_READ_CTRL read is a control. Without it the recovery checks hold on a
block that never moves, which reports "no command issued, error set" whatever
the state was.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, Event, NextTimeStep, ReadOnly, RisingEdge
from env.sep_axi_agent import SepAxiOp
from env.sep_lcc_golden import LC_PROD
from sep_base_test import sep_base_test
from sep_reg_meta import EFUSE_INTERFACE_CTRL, sym
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_efuse_direct_read_seq import sep_efuse_direct_read_seq
from seq_lib.sep_efuse_otp_program_seq import sep_efuse_otp_program_seq

# efuse_read_interface.sv / efuse_program_interface.sv. These encodings are read
# off the RTL enums, and no document states them, so they are used only to
# CONSTRUCT stimulus -- which values are unreachable, and so worth injecting.
# They are deliberately not used as expected values: the recovery below is
# graded on the interface's documented outputs (not busy, done, no bank command,
# error sentinel), never on the state register reading a particular number. An
# expected value taken from the design it checks proves only that the design
# agrees with itself.
_ST_IDLE = 0b01
_ST_WAIT_RESP = 0b10
# Derived, so the legal set is stated once: everything a two-bit register can
# hold that is not legal. Both survivors are walked -- 2'b00 and 2'b11 fail the
# legal-set test for different reasons, and a recovery written as a comparison
# against one of them would recover from that one only.
_ILLEGAL_STATES = tuple(v for v in range(4) if v not in (_ST_IDLE, _ST_WAIT_RESP))

# The error sentinel both interfaces return. hw/ip/efuse/doc/architecture.adoc
# states it for blocked accesses; EFUSE_ERROR_DATA and
# EFUSE_PROGRAM_ERROR_DATA are the same value.
_ERROR_DATA = 0xBADCAB1E

_MAX_SENSE_CYCLES = 20_000

# Any always-readable OTP word; the control grades FSM motion, not the value.
_CONTROL_WORD = 0

# A SPARE word: programming one bit of it disturbs no graded field, and OTP is
# write-once so the control must pick a fresh bit each time it runs.
_CONTROL_PROGRAM_WORD = sym("SEP_EFUSE_MAP_SPARE7_REG_OFFSET") // 4

_READ_CTRL = EFUSE_INTERFACE_CTRL.addr("EFUSE_READ_CTRL")
_READ_TIMEOUT = EFUSE_INTERFACE_CTRL.addr("EFUSE_READ_REQ_TIMEOUT")
_GO = EFUSE_INTERFACE_CTRL.field_mask("EFUSE_READ_CTRL", "efuse_read_go")
_ENABLE = EFUSE_INTERFACE_CTRL.field_mask("EFUSE_READ_CTRL", "read_enable")
# `read_req_timout_enable` -- the field name carries a typo in
# efuse_interface_ctrl.rdl; the generated symbol reproduces it.
_TIMEOUT_EN = EFUSE_INTERFACE_CTRL.field_mask("EFUSE_READ_REQ_TIMEOUT", "read_req_timout_enable")
# Short enough that the SHIM cannot answer inside it, so the timeout fires
# rather than the read completing first.
_TIMEOUT_CYCLES = 4

# The program interface is driven register-directly, not through
# sep_efuse_otp_program_seq: the injection aborts the operation in flight, and
# that sequence raises on the resulting PROGRAM_ERR rather than returning.
_PROGRAM_CTRL = EFUSE_INTERFACE_CTRL.addr("EFUSE_PROGRAM_CTRL")
_PG_GO = EFUSE_INTERFACE_CTRL.field_mask("EFUSE_PROGRAM_CTRL", "efuse_program_go")
_PG_ENABLE = EFUSE_INTERFACE_CTRL.field_mask("EFUSE_PROGRAM_CTRL", "program_enable")
_PG_DATA = EFUSE_INTERFACE_CTRL.field_mask("EFUSE_PROGRAM_CTRL", "efuse_data")
_IFACE_STATUS = EFUSE_INTERFACE_CTRL.addr("EFUSE_INTERFACE_CTRL_STATUS")
_REQ_ERROR_CLEAR = EFUSE_INTERFACE_CTRL.field_mask(
    "EFUSE_INTERFACE_CTRL_STATUS", "efuse_req_error_clear"
)

# SPARE7 bits used as program stimulus. Every one of them is ALREADY set in the
# golden image, which is what makes them safe to use: the interface issues its
# bank command either way -- that is the only thing these legs grade -- but the
# array cannot change, so an operation aborted halfway cannot leave the OTP
# image disagreeing with the golden the end-of-test resense compares against.
# The bank takes ~29 cycles to retire a command. After an aborted operation,
# wait for the interface to go idle and then leave margin, so the next kick is
# not swallowed by a channel that is still busy.
_SETTLE_LIMIT = 400
_SETTLE_CYCLES = 64

_PROGRAM_HELD_BIT = 4
_PROGRAM_INJECT_BITS = (6, 11)
assert len(_PROGRAM_INJECT_BITS) == len(_ILLEGAL_STATES), (
    "one SPARE7 bit per program injection, so a run that adds an illegal encoding "
    "cannot silently reuse a bit and leave two injections sharing one address"
)


@pyuvm.test()
class sep_efuse_illegal_state_fail_closed_test(sep_base_test):
    """An illegal FSM encoding recovers to idle, reports error, issues nothing."""

    required_evidence = (
        "CHK-READ-ALIVE",
        "CHK-PROGRAM-ALIVE",
        "CHK-READ-ERR-CLEAR-SUCCESS",
        "CHK-READ-ERR-TIMEOUT",
        "CHK-READ-ERR-CLEAR-REQUEST",
        "CHK-READ-ERR-BLOCKED",
        "CHK-READ-HELD",
        "CHK-PROGRAM-HELD",
        "CHK-READ-SUPPRESS",
        "CHK-READ-FAILCLOSED",
        "CHK-PROGRAM-SUPPRESS",
        "CHK-PROGRAM-FAILCLOSED",
    )
    min_evidence = 12

    async def _assert_read_alive(self, tag: str) -> None:
        """Positive control: a frontdoor OTP read presents a bank command.

        Graded on the same signal the suppression checks use, so the control
        and the check cannot disagree about what "a command" means. Fuse sense
        does not drive this interface -- it serves the EFUSE_READ_CTRL
        frontdoor -- so only a real direct read is a control. Without it,
        "no command issued" holds on an interface that never issues one.
        """
        seen_active = False
        stop = Event()

        async def _watch() -> None:
            nonlocal seen_active
            while not stop.is_set():
                await RisingEdge(cocotb.top.clk_i)
                await ReadOnly()
                if int(cocotb.top.efuse_read_cmd_req_valid_o.value):
                    seen_active = True

        task = cocotb.start_soon(_watch())
        await self.start_seq(sep_efuse_direct_read_seq(_CONTROL_WORD))
        stop.set()
        await task

        assert seen_active, (
            f"CHK-READ-ALIVE FAIL ({tag}): a frontdoor OTP read presented no command to "
            "the fuse bank, so the suppression checks would hold on an interface that "
            "never issues one"
        )
        self.logger.info("CHK-READ-ALIVE PASS (%s): a frontdoor OTP read drove a bank command", tag)

    async def _csr(self, op: SepAxiOp, addr: int, data: int = 0) -> int:
        seq = SepAxiAccessSeq(
            f"efuse_{op.value}_0x{addr:08x}", op=op, addr=addr, wdata=data, size=2
        )
        await self.start_seq(seq)
        return seq.rdata & 0xFFFF_FFFF

    async def _read_probe(self) -> tuple[int, int, int, int]:
        await ReadOnly()
        dut = cocotb.top
        return (
            int(dut.efuse_read_done_o.value),
            int(dut.efuse_read_busy_o.value),
            int(dut.efuse_read_error_o.value),
            int(dut.efuse_read_back_data_o.value),
        )

    async def _await_read_done(self, limit: int = 400) -> tuple[int, int, int, int]:
        """Wait on the DUT's own done, not on a CSR poll.

        The error legs below are graded on the interface outputs, so the wait
        has to observe the same signals; polling the CSR would let a read that
        never retires look like one that did.
        """
        for _ in range(limit):
            await RisingEdge(cocotb.top.clk_i)
            probe = await self._read_probe()
            if probe[0]:
                return probe
        raise AssertionError(f"the read interface never asserted read_done within {limit} cycles")

    async def _read_error_lifecycle(self) -> None:
        """read_error_o is set by a failure and cleared by the next request."""
        # 1. A successful read leaves the error flag clear (ReadSuccessClearsError).
        await self.start_seq(sep_efuse_direct_read_seq(_CONTROL_WORD))
        done, busy, err, _ = await self._read_probe()
        assert (done, busy, err) == (1, 0, 0), (
            f"CHK-READ-ERR-CLEAR-SUCCESS FAIL: a successful read reported done={done} "
            f"busy={busy} error={err}, expected 1/0/0"
        )
        self.logger.info(
            "CHK-READ-ERR-CLEAR-SUCCESS PASS: a completed read reports done, not busy, no error"
        )

        # 2. A read that outlives its timeout budget sets the error
        #    (ReadTimeoutSetsError). The budget is short enough that the SHIM
        #    cannot answer inside it, so the timeout decides the outcome.
        await self._csr(SepAxiOp.WRITE, _READ_TIMEOUT, _TIMEOUT_CYCLES | _TIMEOUT_EN)
        await self._csr(SepAxiOp.WRITE, _READ_CTRL, _GO | _ENABLE)
        done, busy, err, _ = await self._await_read_done()
        assert (done, busy, err) == (1, 0, 1), (
            f"CHK-READ-ERR-TIMEOUT FAIL: a timed-out read reported done={done} "
            f"busy={busy} error={err}, expected 1/0/1 -- a read that never got a "
            "response must retire as an error, not hang or report success"
        )
        self.logger.info(
            "CHK-READ-ERR-TIMEOUT PASS: a read outliving %d cycles retires with error set",
            _TIMEOUT_CYCLES,
        )

        # 3. Issuing a fresh legal request clears it (ReadRequestClearsError).
        #    The error from leg 2 is the precondition: without it this holds
        #    trivially, so the assert above is also this leg's control.
        await self._csr(SepAxiOp.WRITE, _READ_TIMEOUT, 0)
        await self._csr(SepAxiOp.WRITE, _READ_CTRL, 0)
        await self._csr(SepAxiOp.WRITE, _READ_CTRL, _GO | _ENABLE)
        await RisingEdge(cocotb.top.clk_i)
        _, _, err_after_req, _ = await self._read_probe()
        assert err_after_req == 0, (
            "CHK-READ-ERR-CLEAR-REQUEST FAIL: read_error_o stayed set after a fresh "
            "legal request; a stale error would mislabel the next read"
        )
        await self._await_read_done()
        await self._csr(SepAxiOp.WRITE, _READ_CTRL, 0)
        self.logger.info(
            "CHK-READ-ERR-CLEAR-REQUEST PASS: a new legal request cleared the error "
            "left by the timeout"
        )

    async def _read_blocked_by_secure_tm(self) -> None:
        """A read refused by the guard retires as an error with zero data."""
        cocotb.top.test_en_strap_i.value = 1
        await self.resense(max_cycles=_MAX_SENSE_CYCLES)
        assert int(cocotb.top.secure_tm_o.value) & 1 == 1, (
            "test bug: TEST_EN raised and resensed but secure_tm_o is still 0, so the "
            "guard is not blocking and the refusal below would not be under test"
        )
        await self._csr(SepAxiOp.WRITE, _READ_CTRL, _GO | _ENABLE)
        done, busy, err, data = await self._await_read_done()
        assert (done, busy, err) == (1, 0, 1), (
            f"CHK-READ-ERR-BLOCKED FAIL: a guard-blocked read reported done={done} "
            f"busy={busy} error={err}, expected 1/0/1"
        )
        assert data == 0, (
            f"CHK-READ-ERR-BLOCKED FAIL: a blocked read returned {data:#010x}, expected "
            "zero -- a refused read must not hand back fuse content"
        )
        await self._csr(SepAxiOp.WRITE, _READ_CTRL, 0)
        self.logger.info(
            "CHK-READ-ERR-BLOCKED PASS: a read refused while secure_tm is latched "
            "retires with error set and zero data"
        )

    async def _assert_program_alive(self, bit_offset: int) -> None:
        """Positive control for the program machine.

        CHK-PROGRAM-SUPPRESS and the request half of CHK-PROGRAM-FAILCLOSED both
        assert that this interface presents no command. A machine that never
        issues one -- because nothing ever asks it to -- satisfies them on any
        RTL, so a real program must be shown to move it first.
        """
        seen_active = False
        stop = Event()

        async def _watch() -> None:
            nonlocal seen_active
            while not stop.is_set():
                await RisingEdge(cocotb.top.clk_i)
                await ReadOnly()
                if int(cocotb.top.efuse_program_cmd_req_valid_o.value):
                    seen_active = True

        task = cocotb.start_soon(_watch())
        await self.start_seq(sep_efuse_otp_program_seq(_CONTROL_PROGRAM_WORD * 32 + bit_offset))
        stop.set()
        await task

        assert seen_active, (
            "CHK-PROGRAM-ALIVE FAIL: a frontdoor OTP program presented no command to "
            "the fuse bank, so the suppression checks below would hold on an "
            "interface that never issues one"
        )
        self.logger.info(
            "CHK-PROGRAM-ALIVE PASS: a frontdoor OTP program drove a bank command (SPARE7 bit %d)",
            bit_offset,
        )

    async def _kick(self, which: str, bit_addr: int) -> None:
        """Start one frontdoor operation and return without retiring it."""
        if which == "read":
            await self._csr(SepAxiOp.WRITE, _READ_CTRL, (bit_addr & 0xFFFF) | _GO | _ENABLE)
        else:
            await self._csr(
                SepAxiOp.WRITE,
                _PROGRAM_CTRL,
                (bit_addr & 0xFFFF) | _PG_GO | _PG_ENABLE | _PG_DATA,
            )

    async def _quiesce(self, which: str) -> None:
        """Drop the enable and clear the sticky request error.

        An aborted operation leaves its enable asserted, which starves the
        shared command channel, and may leave efuse_req_error latched. Neither
        is graded here, but either would make the next leg fail for a reason
        that has nothing to do with the state machine.
        """
        await self._csr(SepAxiOp.WRITE, _READ_CTRL if which == "read" else _PROGRAM_CTRL, 0)
        await self._csr(SepAxiOp.WRITE, _IFACE_STATUS, _REQ_ERROR_CLEAR)

        # Wait for the interface to retire and then leave margin.
        #
        # NOTE: the shared channel is NOT idle at this point. An interface that
        # withdraws a command the shim has already accepted leaves the shim's
        # write FSM parked in its APB wait state, and it stays there until the
        # next fuse resense -- see the observation recorded in the plan entry.
        # This leaf waits on the interface outputs it grades, and the legs that
        # follow each resense before they need the channel.
        dut = cocotb.top
        for _ in range(_SETTLE_LIMIT):
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            if not int(getattr(dut, f"efuse_{which}_busy_o").value) and not int(
                getattr(dut, f"efuse_{which}_cmd_req_valid_o").value
            ):
                break
        await ClockCycles(dut.clk_i, _SETTLE_CYCLES)

    async def _kick_and_catch(self, which: str, bit_addr: int, limit: int = 400) -> bool:
        """Start an operation and return on the cycle its bank request is up.

        The watcher runs CONCURRENTLY with the register write. Kicking first and
        watching afterwards misses the window: the write retires through the AXI
        sequencer, and by the time it returns the whole 29-cycle bank operation
        can already be over, leaving nothing in flight to inject into.
        """
        dut = cocotb.top
        kick = cocotb.start_soon(self._kick(which, bit_addr))
        try:
            for _ in range(limit):
                await RisingEdge(dut.clk_i)
                await ReadOnly()
                if int(getattr(dut, f"efuse_{which}_cmd_req_valid_o").value):
                    return True
            return False
        finally:
            await kick

    async def _assert_request_held(self, which: str, bit_addr: int) -> int:
        """Control: measure how many cycles the bank request stays asserted.

        The suppression check injects while that request is high and requires it
        to drop. That is only evidence if a machine left alone would have KEPT
        it high across the same edge -- otherwise the request falls on its own,
        for reasons the injection had nothing to do with, and "no command" holds
        on any RTL. So measure the hold first, on unforced outputs, and require
        it to outlast the one cycle the injection costs.
        """
        held = await self._kick_and_catch(which, bit_addr)
        assert held, (
            f"CHK-{which.upper()}-HELD FAIL: the {which} interface never presented a "
            "command to the fuse bank, so there is no in-flight window to inject into"
        )
        cycles = 1
        dut = cocotb.top
        while cycles < 400:
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            if not int(getattr(dut, f"efuse_{which}_cmd_req_valid_o").value):
                break
            cycles += 1
        await self._quiesce(which)
        assert cycles >= 2, (
            f"CHK-{which.upper()}-HELD FAIL: the bank request was asserted for only "
            f"{cycles} cycle -- it would fall on its own across the injection edge, so "
            "the suppression check below could not tell a suppressing design from one "
            "that does nothing"
        )
        self.logger.info(
            "CHK-%s-HELD PASS: the %s interface holds its bank request for %d cycles, "
            "so an injection lands inside a window where a legal machine keeps it high",
            which.upper(),
            which,
            cycles,
        )
        return cycles

    async def _inject(
        self, which: str, state: int, bit_addr: int, *, in_flight: bool = True
    ) -> None:
        """Force an illegal encoding while a real command is in flight.

        Injecting into an idle block would grade a request that is already low,
        which holds whether or not the design suppresses anything. Here the
        interface is mid-operation with its request asserted, so the drop to
        zero is a consequence of the injection and a design that carried the
        command through a corrupted state fails.
        """
        dut = cocotb.top
        en = getattr(dut, f"efuse_{which}_state_inject_en_i")
        val = getattr(dut, f"efuse_{which}_state_inject_i")

        if in_flight:
            held = await self._kick_and_catch(which, bit_addr)
            assert held, (
                f"test bug: the {which} interface presented no command, so the injection "
                "would land in an idle window and grade nothing"
            )

        await NextTimeStep()
        val.value = state
        en.value = 1
        await RisingEdge(dut.clk_i)

        # While the state is illegal, the in-flight command must be withdrawn.
        await ReadOnly()
        observed = int(getattr(dut, f"efuse_{which}_state_o").value)
        assert observed == state, (
            f"test bug: {which} state reads {observed:#04x}, expected the injected "
            f"{state:#04x} -- the force did not reach the register"
        )
        req = int(getattr(dut, f"efuse_{which}_cmd_req_valid_o").value)
        assert req == 0, (
            f"CHK-{which.upper()}-SUPPRESS FAIL: the {which} interface presented a "
            f"command to the fuse bank while {which}_state_q held the illegal "
            f"encoding {state:#04x}"
        )
        self.logger.info(
            "CHK-%s-SUPPRESS PASS: no bank command while %s_state_q = %#04x (%s)",
            which.upper(),
            which,
            state,
            "an accepted command was withdrawn" if in_flight else "injected while idle",
        )

        # Release, then grade the recovery on the following edge.
        await NextTimeStep()
        en.value = 0
        await RisingEdge(dut.clk_i)
        await ReadOnly()
        recovered = int(getattr(dut, f"efuse_{which}_state_o").value)
        assert int(getattr(dut, f"efuse_{which}_cmd_req_valid_o").value) == 0, (
            f"CHK-{which.upper()}-FAILCLOSED FAIL: the {which} interface issued a bank "
            f"command while recovering from {state:#04x}"
        )
        # Both interfaces retire the same way, so both are graded the same way:
        # the machine reports done and not busy with the error set, and hands
        # back the sentinel rather than any fuse content.
        data_probe = (
            dut.efuse_read_back_data_o if which == "read" else dut.efuse_program_read_back_data_o
        )
        err = int(getattr(dut, f"efuse_{which}_error_o").value)
        done = int(getattr(dut, f"efuse_{which}_done_o").value)
        busy = int(getattr(dut, f"efuse_{which}_busy_o").value)
        data = int(data_probe.value)
        assert (err, done, busy) == (1, 1, 0), (
            f"CHK-{which.upper()}-FAILCLOSED FAIL: recovering from {state:#04x} the "
            f"{which} interface reported error={err} done={done} busy={busy}, "
            "expected 1/1/0 -- a machine that recovers silently leaves the caller "
            "believing its operation is still in flight"
        )
        assert data == _ERROR_DATA, (
            f"CHK-{which.upper()}-FAILCLOSED FAIL: {which} read-back data = "
            f"{data:#010x} recovering from {state:#04x}, expected the sentinel "
            f"{_ERROR_DATA:#010x} -- anything else risks handing back fuse content "
            "the operation never legitimately fetched"
        )
        self.logger.info(
            "CHK-%s-FAILCLOSED PASS: recovered from %#04x mid-operation (state now "
            "%#04x, reported not asserted), no bank command, error and done set, not "
            "busy, data = 0xbadcab1e",
            which.upper(),
            state,
            recovered,
        )
        await self._quiesce(which)

    async def run_scenario(self) -> None:
        img = self.select_efuse_image(lc_raw=LC_PROD)
        self.write_efuse_image(img)
        await self.bring_up_and_wait_fuse_sense(max_cycles=_MAX_SENSE_CYCLES)

        # Control first: prove the read path is live before grading a refusal.
        await self._assert_read_alive("before")
        await self._assert_program_alive(0)

        # Establish the in-flight window before grading a withdrawal inside it.
        await self._assert_request_held("read", _CONTROL_WORD * 32)
        await self._assert_request_held("program", _CONTROL_PROGRAM_WORD * 32 + _PROGRAM_HELD_BIT)

        for state, pg_bit in zip(_ILLEGAL_STATES, _PROGRAM_INJECT_BITS):
            await self._inject("read", state, _CONTROL_WORD * 32)
            # Idle window, not in flight. Aborting an ACCEPTED program parks the
            # example shim's write FSM (see the plan entry's observation), and
            # every later leg that resenses would then read a corrupted shadow
            # word. The read leg is the one that observes a withdrawal.
            await self._inject(
                "program", state, _CONTROL_PROGRAM_WORD * 32 + pg_bit, in_flight=False
            )

        # The block still works afterwards: recovery returned it to service
        # rather than wedging it.
        await self._assert_read_alive("after")
        # A fresh bit: OTP is write-once, so re-programming bit 0 would not
        # issue a command and the control would fail for the wrong reason.
        await self._assert_program_alive(1)

        # Error lifecycle on the same interface: set by a failure, cleared by
        # the next legal request.
        await self._read_error_lifecycle()

        # Last, because it latches secure_tm and a resense does not undo that
        # for the legs above.
        await self._read_blocked_by_secure_tm()
        self.logger.info(
            "illegal-state fail-closed ALL CHECKS PASS: both FSMs, both illegal "
            "encodings, read path live before and after"
        )
