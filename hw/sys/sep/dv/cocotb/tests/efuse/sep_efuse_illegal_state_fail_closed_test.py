# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""eFuse read and program FSMs fail closed from an illegal state.

``efuse_read_interface`` and ``efuse_program_interface`` each hold a two-bit
state. ``hw/ip/efuse/doc/architecture.adoc`` names a two-state sequence
(idle, then waiting for a bank response). No document names the encodings.
The legal encodings, ``2'b01`` idle and ``2'b10`` wait, are the set the
state-inject record in ``tb/tb_top.sv`` accepts for this leaf.
The leaf injects the other two values for one cycle.
Those two codes have no frontdoor.

The recovery this leaf grades is DV-owned:

* an in-flight read command is withdrawn while the illegal encoding is held;
* on the next edge the read interface reports done and not busy with the error
  set, issues no command, and does not hand back the sensed fuse word;
* an idle program interface recovers to a legal encoding without issuing a
  bank command. Its pre-settled retirement status is not graded.

The leaf also grades the read-error lifecycle on the same interface:

* a successful read clears read_error_o, a read that outlives
  EFUSE_READ_REQ_TIMEOUT retires with the error set, and the next legal request
  clears it (CHK-READ-ERR-CLEAR-SUCCESS, -TIMEOUT, -CLEAR-REQUEST);
* with secure_tm latched, a read retires with the error set and zero data
  (CHK-READ-ERR-BLOCKED).

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

# hw/ip/efuse/doc/architecture.adoc names a two-state sequence (idle, waiting)
# and no encodings. The legal set below is the one the state-inject
# record in tb/tb_top.sv accepts. The injection walks its complement, and each
# recovery must return the state register to a member of it.
_ST_IDLE = 0b01
_ST_WAIT_RESP = 0b10
_ILLEGAL_STATES = tuple(v for v in range(4) if v not in (_ST_IDLE, _ST_WAIT_RESP))

_MAX_SENSE_CYCLES = 20_000

# The control read is a data spare, not LOCKS: an unlocked LOCKS word is 0,
# so a recovery that returns 0 would match it. A recovery must not hand the
# sensed spare back.
_CONTROL_FIELD = "SPARE0"

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


def _place(block, reg: str, field: str, value: int) -> int:
    """Put ``value`` into ``reg.field`` by its generated mask and LSB."""
    mask = block.field_mask(reg, field)
    lsb = block.field_lsb(reg, field)
    placed = value << lsb
    if placed & ~mask:
        raise ValueError(f"{reg}.{field}: {value:#x} does not fit mask {mask:#x}")
    return placed


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

# The bank takes about 30 cycles to retire a command. After an aborted operation,
# wait for the interface to go idle and then leave margin, so the next kick is
# not swallowed by a channel that is still busy.
_SETTLE_LIMIT = 400
_SETTLE_CYCLES = 64

# SPARE7 bits the program legs consume: two live controls and one per illegal
# encoding.
_PROGRAM_BITS_NEEDED = 2 + len(_ILLEGAL_STATES)


@pyuvm.test()
class sep_efuse_illegal_state_fail_closed_test(sep_base_test):
    """Illegal FSM encodings recover legally; an in-flight read fails closed."""

    required_evidence = (
        "CHK-READ-ALIVE",
        "CHK-PROGRAM-ALIVE",
        "CHK-READ-ERR-CLEAR-SUCCESS",
        "CHK-READ-ERR-TIMEOUT",
        "CHK-READ-ERR-CLEAR-REQUEST",
        "CHK-READ-ERR-BLOCKED",
        "CHK-READ-HELD",
        "CHK-READ-SUPPRESS",
        "CHK-READ-FAILCLOSED",
        "CHK-PROGRAM-FAILCLOSED",
    )
    min_evidence = 10

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
        await self.start_seq(sep_efuse_direct_read_seq(self._control_word))
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
        await self.start_seq(sep_efuse_direct_read_seq(self._control_word))
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
        await self._csr(
            SepAxiOp.WRITE,
            _READ_TIMEOUT,
            _place(
                EFUSE_INTERFACE_CTRL,
                "EFUSE_READ_REQ_TIMEOUT",
                "read_req_timeout_cycles",
                _TIMEOUT_CYCLES,
            )
            | _TIMEOUT_EN,
        )
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
        # Re-read the flag AFTER the cleanup writes and BEFORE the request. Both
        # of those writes could clear it, and sampling only after the request
        # would credit the request for a clear either of them may have done.
        _, _, err_before_req, _ = await self._read_probe()
        assert err_before_req == 1, (
            "CHK-READ-ERR-CLEAR-REQUEST FAIL: read_error_o was already clear before "
            f"the fresh request was issued (error={err_before_req}) -- dropping the "
            "timeout budget or the enable cleared it, so a clear observed after the "
            "request cannot be attributed to the request"
        )
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
        addr = _place(
            EFUSE_INTERFACE_CTRL, "EFUSE_READ_CTRL", "efuse_addr", self._control_word * 32
        )
        await self._csr(SepAxiOp.WRITE, _READ_CTRL, addr | _GO | _ENABLE)
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

        The request half of CHK-PROGRAM-FAILCLOSED asserts that this interface
        presents no command. A machine that never issues one -- because nothing
        ever asks it to -- satisfies that on any RTL, so a real program must be
        shown to move it first.
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
            addr = _place(EFUSE_INTERFACE_CTRL, "EFUSE_READ_CTRL", "efuse_addr", bit_addr)
            await self._csr(SepAxiOp.WRITE, _READ_CTRL, addr | _GO | _ENABLE)
        else:
            addr = _place(EFUSE_INTERFACE_CTRL, "EFUSE_PROGRAM_CTRL", "efuse_addr", bit_addr)
            await self._csr(SepAxiOp.WRITE, _PROGRAM_CTRL, addr | _PG_GO | _PG_ENABLE | _PG_DATA)

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
        # next fuse resense -- see the sep_efuse_illegal_state_fail_closed_test
        # section of hw/sys/sep/dv/docs/SEP_VPLAN.adoc.
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
        sequencer, and by the time it returns the whole bank operation (about 30 cycles)
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

        # error_o is cleared by the next request, not by a status write (the rule
        # CHK-READ-ERR-CLEAR-REQUEST grades), and _quiesce clears only the
        # interface-level efuse_req_error. On the first injection of an interface
        # the error term starts low and is asserted; on a later one the latch carries
        # over from the previous leg, so that leg rests on done and the data mismatch.
        await ReadOnly()
        err_before = int(getattr(dut, f"efuse_{which}_error_o").value)
        done_before = int(getattr(dut, f"efuse_{which}_done_o").value)

        if in_flight:
            # A command is mid-operation, so error and done are both low going in
            # and the 1/1/0 verdict below is a consequence of the injection.
            assert (err_before, done_before) == (0, 0), (
                f"{which} error_o={err_before} done_o={done_before} before an "
                "in-flight injection; the verdict terms must start low or they are "
                "not attributable to it"
            )
        else:
            # Idle-window injection. An idle interface has retired its last command
            # and reports it, so error_o and done_o are both 1 here, on the first
            # injection and on later ones.
            # busy/req are idle-low for the same reason, and the data term compares
            # the fixed refusal sentinel against an image word, which are never
            # equal. So every term of the 1/1/0 + data verdict is settled before
            # the injection and none of it grades suppression.
            #
            # What this leg does still grade is the state-report path: the injected
            # encoding must appear on *_state_o and the interface must recover to a
            # legal state afterwards. The asserts above and below check both.
            self.logger.info(
                "%s idle-window injection (%#04x): error_o=%d done_o=%d before the "
                "injection, so the 1/1/0 terms are pre-settled and grade nothing "
                "here -- this leg grades the state report and the recovery",
                which,
                state,
                err_before,
                done_before,
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
            f"{state:#04x} -- the force did not reach the register (inject "
            "confirmation, not fail-closed evidence)"
        )
        # Suppression is graded only on the in-flight leg: on an idle interface the
        # bank request is already low, so requiring it low holds whether or not the
        # design suppresses anything.
        req = int(getattr(dut, f"efuse_{which}_cmd_req_valid_o").value)
        if in_flight:
            assert req == 0, (
                f"CHK-{which.upper()}-SUPPRESS FAIL: the {which} interface still "
                f"presented its in-flight command to the fuse bank while "
                f"{which}_state_q held the illegal encoding {state:#04x}"
            )
            self.logger.info(
                "CHK-%s-SUPPRESS PASS: an accepted bank command was withdrawn within "
                "one cycle of %s_state_q = %#04x",
                which.upper(),
                which,
                state,
            )

        # Release, then grade the recovery on the following edge.
        await NextTimeStep()
        en.value = 0
        await RisingEdge(dut.clk_i)
        await ReadOnly()
        recovered = int(getattr(dut, f"efuse_{which}_state_o").value)
        assert recovered in (_ST_IDLE, _ST_WAIT_RESP), (
            f"CHK-{which.upper()}-FAILCLOSED FAIL: recovered {which} state "
            f"{recovered:#04x} is not a legal encoding "
            f"(idle={_ST_IDLE:#04x} wait={_ST_WAIT_RESP:#04x})"
        )
        assert int(getattr(dut, f"efuse_{which}_cmd_req_valid_o").value) == 0, (
            f"CHK-{which.upper()}-FAILCLOSED FAIL: the {which} interface issued a bank "
            f"command while recovering from {state:#04x}"
        )
        # Sample the shared status/data shape. These terms are graded only for
        # an in-flight read; an idle program interface has them pre-settled.
        data_probe = (
            dut.efuse_read_back_data_o if which == "read" else dut.efuse_program_read_back_data_o
        )
        err = int(getattr(dut, f"efuse_{which}_error_o").value)
        done = int(getattr(dut, f"efuse_{which}_done_o").value)
        busy = int(getattr(dut, f"efuse_{which}_busy_o").value)
        data = int(data_probe.value)
        sensed = self._sensed_control_word
        # The 1/1/0 status terms and the data mismatch are only attributable
        # when the injection landed mid-operation (they start 0/0). An idle
        # interface already reports a retired command, so those compares hold
        # whether or not the illegal encoding did anything. Idle grades the
        # recovered legal encoding above.
        if in_flight:
            assert (err, done, busy) == (1, 1, 0), (
                f"CHK-{which.upper()}-FAILCLOSED FAIL: recovering from {state:#04x} the "
                f"{which} interface reported error={err} done={done} busy={busy}, "
                "expected 1/1/0 -- a machine that recovers silently leaves the caller "
                "believing its operation is still in flight"
            )
            assert data != sensed, (
                f"CHK-{which.upper()}-FAILCLOSED FAIL: {which} read-back data = "
                f"{data:#010x} recovering from {state:#04x}, which is the sensed "
                f"control word -- a leaked fuse value the operation never "
                "legitimately fetched"
            )
            self.logger.info(
                "CHK-%s-FAILCLOSED PASS: recovered from %#04x mid-operation "
                "(state now %#04x), no bank command, error and done set, not busy, "
                "data 0x%08x is not the sensed control word 0x%08x",
                which.upper(),
                state,
                recovered,
                data,
                sensed,
            )
        else:
            self.logger.info(
                "CHK-%s-FAILCLOSED PASS: recovered from %#04x injected while idle "
                "(state now %#04x legal, no bank command); 1/1/0 and data are "
                "pre-settled on an idle interface and are not graded",
                which.upper(),
                state,
                recovered,
            )
        await self._quiesce(which)

    def _pick_pg_bits(self, img) -> list[int]:
        """SPARE7 bit indices to use as program stimulus, taken from the image.

        Every bit returned is ALREADY SET in the golden, so the array cannot
        change: the interface issues its bank command either way -- which is
        the only thing these legs grade -- and an operation aborted halfway
        cannot leave the OTP image disagreeing with the golden that the
        end-of-test resense compares against.

        The image is randomized per seed, so these cannot be constants: a bit
        set in one seed's image can be clear in another's, and programming it
        would move the array.
        """
        spare7 = img.field_int("SPARE7") & 0xFFFFFFFF
        bits = [b for b in range(32) if (spare7 >> b) & 1]
        assert len(bits) >= _PROGRAM_BITS_NEEDED, (
            f"test bug: SPARE7 word 0 of this seed's image is {spare7:#010x}, which has "
            f"only {len(bits)} bit(s) set, and the program legs need "
            f"{_PROGRAM_BITS_NEEDED} already-set bits to avoid changing the array"
        )
        return bits[:_PROGRAM_BITS_NEEDED]

    async def run_scenario(self) -> None:
        img = self.select_efuse_image(lc_raw=LC_PROD)
        pg_bits = self._pick_pg_bits(img)
        self._control_word = img.field(_CONTROL_FIELD).word
        if (img.words[self._control_word] & 0xFFFF_FFFF) == 0:
            img.words[self._control_word] = 0xA5A5_5A5A
        self._sensed_control_word = img.shadow_word(self._control_word)
        assert self._sensed_control_word != 0, (
            f"test bug: {_CONTROL_FIELD} word {self._control_word} is staged "
            "as 0, so a recovery that returns zero would not be "
            "distinguishable from a leaked fuse word"
        )
        self.write_efuse_image(img)
        await self.bring_up_and_wait_fuse_sense(max_cycles=_MAX_SENSE_CYCLES)

        # Control first: prove the read path is live before grading a refusal.
        await self._assert_read_alive("before")
        await self._assert_program_alive(pg_bits[0])

        # Establish the in-flight window before grading a withdrawal inside it.
        await self._assert_request_held("read", self._control_word * 32)

        for state, pg_bit in zip(_ILLEGAL_STATES, pg_bits[2:]):
            await self._inject("read", state, self._control_word * 32)
            # Idle window, not in flight. Aborting an ACCEPTED program parks the
            # example shim's write FSM (see the VPLAN section of this test), and
            # every later leg that resenses would then read a corrupted shadow
            # word. The read leg is the one that observes a withdrawal.
            await self._inject(
                "program", state, _CONTROL_PROGRAM_WORD * 32 + pg_bit, in_flight=False
            )

        # The block still works afterwards: recovery returned it to service
        # rather than wedging it.
        await self._assert_read_alive("after")
        # A fresh bit: OTP is write-once, so programming pg_bits[0] again would not
        # issue a command and the control would fail for the wrong reason.
        await self._assert_program_alive(pg_bits[1])

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
