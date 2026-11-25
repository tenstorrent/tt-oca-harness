# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""eFuse read and program FSMs after an injected illegal state.

``efuse_read_interface`` and ``efuse_program_interface`` each hold a two-bit
state. ``hw/ip/efuse/doc/architecture.adoc`` names a two-state sequence
(idle, then waiting for a bank response). No document names the encodings.
The leaf forces each state register, for one cycle, to the two codes outside
the set the state-inject record in ``tb/tb_top.sv`` accepts. Those codes have
no frontdoor. They are stimulus only: no graded term uses an encoding.

Graded after each injection:

* the interface reports an error (OCAH-HSR-SEP-011,
  ``doc/trm/meta/ocah_hsr_table.adoc:38``): ``efuse_<read|program>_error_o``
  is 1, and so is the field software reads it through,
  ``EFUSE_READ_CTRL.read_status`` / ``EFUSE_PROGRAM_CTRL.program_status``
  (``efuse_interface_ctrl.rdl:133``, ``:102``: "1: Error")
  (CHK-READ-FAILCLOSED-ERR, CHK-PROGRAM-FAILCLOSED);
* the idle program interface issues no bank command: with no program go and
  no enable there is no program request (``efuse_interface_ctrl.rdl:76``,
  ``:112``; CHK-PROGRAM-FAILCLOSED);
* the read interface serves a new request after both injections, and the
  program interface after each one (CHK-READ-ALIVE and CHK-PROGRAM-ALIVE
  after; OCAH-HSR-SEP-010).

Each injection enters with the error output at 0, and on the program interface
with ``program_status`` at 0 (CTRL-<READ|PROGRAM>-FAILCLOSED-CLEAN). The second
program leg follows a cold reset, which returns ``program_status`` to its reset
value 0 (``efuse_interface_ctrl.rdl:97``).

Logged, not graded: no authored text states the FSM encodings or the outputs
of an interface after an illegal state. The withdrawal of the in-flight read
command, the recovered state, the bank request after the release, and the
done, busy and read-back data values are OBS lines (OBS-READ-SUPPRESS,
OBS-READ-FAILCLOSED, OBS-PROGRAM-FAILCLOSED-STATUS), and so is the clock at
which a new go clears the read error (OBS-READ-ERR-CLEAR-EDGE). The idle
program injection has no go pending, so its no-command term fails only if the
illegal state itself issues a request; the error term carries that check.

The leaf also grades the read-error lifecycle on the same interface:

* a successful read clears read_error_o, a read with the timeout enabled at
  its reset count completes without error and returns the sensed word, a read
  that outlives a short EFUSE_READ_REQ_TIMEOUT retires with the error set, and
  the next legal read, of a different spare word staged with a different
  value, completes with no error and that word's sensed value, not the
  timed-out word (CHK-READ-ERR-CLEAR-SUCCESS, -TIMEOUT-ARMED, -TIMEOUT,
  -CLEAR-REQUEST);
* with secure_tm latched, a read retires with the error set and zero data
  (CHK-READ-ERR-BLOCKED).

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
# and no encodings. The set below is the one the state-inject record in
# tb/tb_top.sv accepts. The injection walks its complement. These constants
# choose stimulus only; no graded term compares against them.
_ST_IDLE = 0b01
_ST_WAIT_RESP = 0b10
_ILLEGAL_STATES = tuple(v for v in range(4) if v not in (_ST_IDLE, _ST_WAIT_RESP))

_MAX_SENSE_CYCLES = 20_000

# The control read is a data spare, not LOCKS: an unlocked LOCKS word is 0,
# so a recovery that returns 0 would match it. A recovery must not hand the
# sensed spare back.
_CONTROL_FIELD = "SPARE0"

# The read after the timed-out one targets a different spare word whose staged
# value differs from the control word, so data carried over from the timed-out
# read cannot pass as the recovery read's data. Not SPARE7, which the program
# legs use.
_RECOVERY_FIELD = "SPARE1"

# A SPARE word: programming one bit of it disturbs no graded field, and OTP is
# write-once so the control must pick a fresh bit each time it runs.
_CONTROL_PROGRAM_WORD = sym("SEP_EFUSE_WRAP_SEP_EFUSE_MAP_SPARE7_REG_OFFSET") // 4

_READ_CTRL = EFUSE_INTERFACE_CTRL.addr("EFUSE_READ_CTRL")
_READ_ADDR = EFUSE_INTERFACE_CTRL.addr("EFUSE_READ_ADDR")
_READ_TIMEOUT = EFUSE_INTERFACE_CTRL.addr("EFUSE_READ_REQ_TIMEOUT")
_GO = EFUSE_INTERFACE_CTRL.field_mask("EFUSE_READ_CTRL", "efuse_read_go")
_ENABLE = EFUSE_INTERFACE_CTRL.field_mask("EFUSE_READ_CTRL", "read_enable")
# `read_req_timout_enable` -- the field name carries a typo in
# efuse_interface_ctrl.rdl; the generated symbol reproduces it.
_TIMEOUT_EN = EFUSE_INTERFACE_CTRL.field_mask("EFUSE_READ_REQ_TIMEOUT", "read_req_timout_enable")
# Short enough that the SHIM cannot answer inside it, so the timeout fires
# rather than the read completing first.
_TIMEOUT_CYCLES = 4
# The RDL reset count. The bank answers a read long before it, so a read with
# the timeout enabled at this count completes without error.
_TIMEOUT_RESET_CYCLES = EFUSE_INTERFACE_CTRL.field_reset(
    "EFUSE_READ_REQ_TIMEOUT", "read_req_timeout_cycles"
)
_READ_DATA = EFUSE_INTERFACE_CTRL.addr("EFUSE_READ_INTERFACE_READ_DATA")
_RD_BUSY = EFUSE_INTERFACE_CTRL.field_mask("EFUSE_READ_CTRL", "read_busy")
_RD_DONE = EFUSE_INTERFACE_CTRL.field_mask("EFUSE_READ_CTRL", "read_done")
_RD_STATUS = EFUSE_INTERFACE_CTRL.field_mask("EFUSE_READ_CTRL", "read_status")
_PG_STATUS = EFUSE_INTERFACE_CTRL.field_mask("EFUSE_PROGRAM_CTRL", "program_status")


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
_PROGRAM_ADDR = EFUSE_INTERFACE_CTRL.addr("EFUSE_PROGRAM_ADDR")
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

# SPARE7 bits the program legs consume: the live control before the
# injections, and per illegal encoding one injection and one live control.
_PROGRAM_BITS_NEEDED = 1 + 2 * len(_ILLEGAL_STATES)


@pyuvm.test()
class sep_efuse_illegal_state_fail_closed_test(sep_base_test):
    """An injected illegal state sets the interface error; both FSMs stay in service."""

    required_evidence = (
        "CHK-READ-ALIVE",
        "CHK-PROGRAM-ALIVE",
        "CHK-READ-ERR-CLEAR-SUCCESS",
        "CHK-READ-ERR-TIMEOUT-ARMED",
        "CHK-READ-ERR-TIMEOUT",
        "CHK-READ-ERR-CLEAR-REQUEST",
        "CHK-READ-ERR-BLOCKED",
        "CHK-READ-FAILCLOSED-ERR",
        "CHK-PROGRAM-FAILCLOSED",
    )
    min_evidence = 9

    async def _assert_read_alive(self, tag: str) -> None:
        """Positive control: a frontdoor OTP read presents a bank command.

        Read on the same signal the OBS request terms log. Fuse sense does not
        drive this interface -- it serves the EFUSE_READ_CTRL frontdoor -- so
        only a real direct read is a control. After the injections it shows the
        read FSM still serves a new request.
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
            "the fuse bank"
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
        """read_error_o is set by a timed-out read; the next legal read completes cleanly."""
        # 1. A successful read leaves the error flag clear. It reads the recovery
        #    word, so the read data it leaves differs from the control word that
        #    the armed read in step 2 must return.
        await self.start_seq(sep_efuse_direct_read_seq(self._recovery_word))
        done, busy, err, _ = await self._read_probe()
        assert (done, busy, err) == (1, 0, 0), (
            f"CHK-READ-ERR-CLEAR-SUCCESS FAIL: a successful read reported done={done} "
            f"busy={busy} error={err}, expected 1/0/0"
        )
        self.logger.info(
            "CHK-READ-ERR-CLEAR-SUCCESS PASS: a completed read reports done, not busy, no error"
        )

        # 2. With the timeout enabled at its reset count, a read completes
        #    without error and returns the sensed word.
        await self._read_with_reset_timeout()

        # 3. A read that outlives its timeout budget retires with the error set
        #    (efuse_interface_ctrl.rdl:133; smc-programming.adoc:1690-1692). The
        #    budget is short enough that the SHIM cannot answer inside it, and
        #    the read must present its bank command, so the timeout decides the
        #    outcome.
        timeout = (
            _place(
                EFUSE_INTERFACE_CTRL,
                "EFUSE_READ_REQ_TIMEOUT",
                "read_req_timeout_cycles",
                _TIMEOUT_CYCLES,
            )
            | _TIMEOUT_EN
        )
        await self._csr(SepAxiOp.WRITE, _READ_TIMEOUT, timeout)
        timeout_rb = await self._csr(SepAxiOp.READ, _READ_TIMEOUT)
        assert timeout_rb == timeout, (
            f"test bug: EFUSE_READ_REQ_TIMEOUT reads {timeout_rb:#010x} after writing "
            f"{timeout:#010x}, so the short timeout is not armed"
        )
        held = await self._kick_and_catch("read", self._control_word * 32)
        assert held, (
            "CHK-READ-ERR-TIMEOUT FAIL: the read interface presented no bank command, "
            "so the read was not accepted and an error could not come from the timeout"
        )
        done, busy, err, data = await self._await_read_done()
        ctrl = await self._csr(SepAxiOp.READ, _READ_CTRL)
        rd_data = await self._csr(SepAxiOp.READ, _READ_DATA)
        rd_done = int(bool(ctrl & _RD_DONE))
        rd_busy = int(bool(ctrl & _RD_BUSY))
        rd_status = int(bool(ctrl & _RD_STATUS))
        fields = (
            f"t_cycles={_TIMEOUT_CYCLES:#x} t_reg={timeout_rb:#010x} done={done} busy={busy} "
            f"err={err} read_done={rd_done} read_busy={rd_busy} read_status={rd_status} "
            f"data={data:#010x} read_data={rd_data:#010x}"
        )
        ok = (done, busy, err) == (1, 0, 1) and (rd_done, rd_busy, rd_status) == (1, 0, 1)
        assert ok, (
            "CHK-READ-ERR-TIMEOUT FAIL: a read that outlived its timeout budget did not "
            f"retire with done and the error set: {fields}"
        )
        self.logger.info("CHK-READ-ERR-TIMEOUT PASS: %s", fields)

        # 4. The next legal read after the timed-out one completes with no
        #    error and the sensed word of its own address
        #    (architecture.adoc:102-107; efuse_interface_ctrl.rdl:127, :133;
        #    smc-programming.adoc:1725-1729). It reads the recovery word, not
        #    the timed-out control word, so the two expected words differ. The
        #    error from leg 3 is the precondition. When the flag clears is not
        #    stated; it is logged.
        await self._csr(SepAxiOp.WRITE, _READ_TIMEOUT, 0)
        await self._csr(SepAxiOp.WRITE, _READ_CTRL, 0)
        _, _, err_after_cleanup, _ = await self._read_probe()
        held = await self._kick_and_catch("read", self._recovery_word * 32)
        assert held, (
            "CHK-READ-ERR-CLEAR-REQUEST FAIL: the read interface presented no bank "
            "command for the read after the timed-out one"
        )
        _, _, err_after_go, _ = await self._read_probe()
        done, busy, err, data = await self._await_read_done()
        ctrl = await self._csr(SepAxiOp.READ, _READ_CTRL)
        rd_data = await self._csr(SepAxiOp.READ, _READ_DATA)
        await self._csr(SepAxiOp.WRITE, _READ_CTRL, 0)
        self.logger.info(
            "OBS-READ-ERR-CLEAR-EDGE err_after_cleanup=%d err_after_go=%d graded=0",
            err_after_cleanup,
            err_after_go,
        )
        sensed = self._sensed_recovery_word
        rd_done = int(bool(ctrl & _RD_DONE))
        rd_busy = int(bool(ctrl & _RD_BUSY))
        rd_status = int(bool(ctrl & _RD_STATUS))
        fields = (
            f"timed_out_addr={self._control_word * 32:#x} "
            f"timed_out_word={self._sensed_control_word:#010x} "
            f"addr={self._recovery_word * 32:#x} done={done} busy={busy} err={err} "
            f"read_done={rd_done} read_busy={rd_busy} read_status={rd_status} "
            f"data={data:#010x} read_data={rd_data:#010x} exp={sensed:#010x}"
        )
        ok = (done, busy, err) == (1, 0, 0) and (rd_done, rd_busy, rd_status) == (1, 0, 0)
        assert ok and data == sensed and rd_data == sensed, (
            "CHK-READ-ERR-CLEAR-REQUEST FAIL: the read after a timed-out read did not "
            f"complete with no error and the sensed word: {fields}"
        )
        self.logger.info("CHK-READ-ERR-CLEAR-REQUEST PASS: %s", fields)

    async def _read_with_reset_timeout(self) -> None:
        """A read with the timeout armed at its reset count completes cleanly.

        The error term carries the grade. The leg before leaves read_error_o at
        0, and this read is accepted (its bank command is caught), so an error
        here can only come from the armed timeout firing before the bank
        answers. The data terms compare the sensed control word, which a
        timed-out read replaces with zero.
        """
        timeout = (
            _place(
                EFUSE_INTERFACE_CTRL,
                "EFUSE_READ_REQ_TIMEOUT",
                "read_req_timeout_cycles",
                _TIMEOUT_RESET_CYCLES,
            )
            | _TIMEOUT_EN
        )
        await self._csr(SepAxiOp.WRITE, _READ_TIMEOUT, timeout)
        timeout_rb = await self._csr(SepAxiOp.READ, _READ_TIMEOUT)
        assert timeout_rb == timeout, (
            f"test bug: EFUSE_READ_REQ_TIMEOUT reads {timeout_rb:#010x} after writing "
            f"{timeout:#010x}, so the timeout is not armed at the reset count"
        )
        _, _, err_before, _ = await self._read_probe()
        assert err_before == 0, (
            f"test bug: read_error_o={err_before} before the armed read, so an error "
            "after it could not be attributed to the timeout"
        )
        held = await self._kick_and_catch("read", self._control_word * 32)
        assert held, (
            "CHK-READ-ERR-TIMEOUT-ARMED FAIL: the read interface presented no bank "
            "command, so the read was not accepted and the timeout never ran"
        )
        done, busy, err, data = await self._await_read_done()
        ctrl = await self._csr(SepAxiOp.READ, _READ_CTRL)
        rd_data = await self._csr(SepAxiOp.READ, _READ_DATA)
        await self._csr(SepAxiOp.WRITE, _READ_CTRL, 0)
        sensed = self._sensed_control_word
        rd_done = int(bool(ctrl & _RD_DONE))
        rd_busy = int(bool(ctrl & _RD_BUSY))
        rd_status = int(bool(ctrl & _RD_STATUS))
        fields = (
            f"t_cycles={_TIMEOUT_RESET_CYCLES:#x} t_reg={timeout_rb:#010x} done={done} busy={busy} err={err} "
            f"read_done={rd_done} read_busy={rd_busy} read_status={rd_status} "
            f"data={data:#010x} read_data={rd_data:#010x} exp={sensed:#010x}"
        )
        ok = (done, busy, err) == (1, 0, 0) and (rd_done, rd_busy, rd_status) == (1, 0, 0)
        assert ok and data == sensed and rd_data == sensed, (
            "CHK-READ-ERR-TIMEOUT-ARMED FAIL: a read with the timeout enabled at its "
            f"reset count did not complete cleanly with the sensed word: {fields}"
        )
        self.logger.info("CHK-READ-ERR-TIMEOUT-ARMED PASS: %s", fields)

    async def _read_blocked_by_secure_tm(self) -> None:
        """A read refused by the guard retires as an error with zero data."""
        cocotb.top.test_en_strap_i.value = 1
        await self.resense(max_cycles=_MAX_SENSE_CYCLES)
        assert int(cocotb.top.secure_tm_o.value) & 1 == 1, (
            "test bug: TEST_EN raised and resensed but secure_tm_o is still 0, so the "
            "guard is not blocking and the refusal below would not be under test"
        )
        addr = _place(
            EFUSE_INTERFACE_CTRL, "EFUSE_READ_ADDR", "efuse_addr", self._control_word * 32
        )
        await self._csr(SepAxiOp.WRITE, _READ_ADDR, addr)
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
            "the fuse bank, so the no-command term of CHK-PROGRAM-FAILCLOSED would "
            "hold on an interface that never issues one"
        )
        self.logger.info(
            "CHK-PROGRAM-ALIVE PASS: a frontdoor OTP program drove a bank command (SPARE7 bit %d)",
            bit_offset,
        )

    async def _kick(self, which: str, bit_addr: int) -> None:
        """Start one frontdoor operation and return without retiring it."""
        if which == "read":
            addr = _place(EFUSE_INTERFACE_CTRL, "EFUSE_READ_ADDR", "efuse_addr", bit_addr)
            await self._csr(SepAxiOp.WRITE, _READ_ADDR, addr)
            await self._csr(SepAxiOp.WRITE, _READ_CTRL, _GO | _ENABLE)
        else:
            addr = _place(EFUSE_INTERFACE_CTRL, "EFUSE_PROGRAM_ADDR", "efuse_addr", bit_addr)
            await self._csr(SepAxiOp.WRITE, _PROGRAM_ADDR, addr)
            await self._csr(SepAxiOp.WRITE, _PROGRAM_CTRL, _PG_GO | _PG_ENABLE | _PG_DATA)

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

    async def _count_cmd_req(self, which: str, stop: Event) -> int:
        """Count the clocks on which the interface's bank request is high until ``stop``."""
        dut = cocotb.top
        req = getattr(dut, f"efuse_{which}_cmd_req_valid_o")
        cycles = 0
        while not stop.is_set():
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            cycles += int(req.value)
        return cycles

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

        OBS-READ-SUPPRESS logs whether the request drops while the illegal code
        is held. That value means something only if a machine left alone keeps
        the request high across the same edge, so measure the hold first, on
        unforced outputs, and require it to outlast the one cycle the injection
        costs.
        """
        held = await self._kick_and_catch(which, bit_addr)
        assert held, (
            f"CTRL-{which.upper()}-HELD FAIL: the {which} interface never presented a "
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
            f"CTRL-{which.upper()}-HELD FAIL: the bank request was asserted for only "
            f"{cycles} cycle, so it would fall on its own across the injection edge"
        )
        self.logger.info("CTRL-%s-HELD cycles=%d", which.upper(), cycles)
        return cycles

    async def _inject(
        self, which: str, state: int, bit_addr: int, *, in_flight: bool = True, leg: int = 0
    ) -> None:
        """Force an illegal code for one cycle and grade the error it reports.

        The read leg injects while a real read is in flight with its request
        asserted. The program leg injects into an idle interface: aborting an
        accepted program parks the example shim's write FSM (see the VPLAN
        section of this test).
        """
        dut = cocotb.top
        en = getattr(dut, f"efuse_{which}_state_inject_en_i")
        val = getattr(dut, f"efuse_{which}_state_inject_i")
        tag = which.upper()

        if not in_flight and which != "program":
            raise ValueError("test bug: the idle-window injection is a program-interface leg")
        if in_flight:
            held = await self._kick_and_catch(which, bit_addr)
            assert held, (
                f"test bug: the {which} interface presented no command, so the injection "
                "would land in an idle window"
            )

        # An error after the injection is attributable to it only where the
        # error output, and on the idle program interface program_status, enter
        # low. _quiesce clears only the interface-level efuse_req_error, so an
        # idle interface keeps the error of its last retirement.
        status_before = 0
        if not in_flight:
            status_before = int(bool(await self._csr(SepAxiOp.READ, _PROGRAM_CTRL) & _PG_STATUS))
        await ReadOnly()
        err_before = int(getattr(dut, f"efuse_{which}_error_o").value)
        done_before = int(getattr(dut, f"efuse_{which}_done_o").value)
        busy_before = int(getattr(dut, f"efuse_{which}_busy_o").value)
        before = f"error_o={err_before}"
        if not in_flight:
            before += f" program_status={status_before}"
        assert err_before == 0 and status_before == 0, (
            f"CTRL-{tag}-FAILCLOSED-CLEAN FAIL: {before} before the leg {leg} injection, "
            "so an error after it could be a stale one"
        )
        assert not in_flight or (busy_before == 1 and done_before == 0), (
            f"CTRL-{tag}-FAILCLOSED-CLEAN FAIL: busy_o={busy_before} done_o={done_before} "
            f"before the leg {leg} injection, so the read is not in flight"
        )
        self.logger.info(
            "CTRL-%s-FAILCLOSED-CLEAN state=%#04x leg=%d %s done_o=%d busy_o=%d "
            "before the injection",
            tag,
            state,
            leg,
            before,
            done_before,
            busy_before,
        )

        req_stop = Event()
        req_count = None
        if not in_flight:
            req_count = cocotb.start_soon(self._count_cmd_req(which, req_stop))
        await NextTimeStep()
        val.value = state
        en.value = 1
        await RisingEdge(dut.clk_i)

        await ReadOnly()
        observed = int(getattr(dut, f"efuse_{which}_state_o").value)
        if observed != state:
            raise AssertionError(
                f"CTRL-{tag}-INJECT FAIL: {which} state reads {observed:#04x}, expected "
                f"the injected {state:#04x}, so the force did not reach the register"
            )
        req_held = int(getattr(dut, f"efuse_{which}_cmd_req_valid_o").value)
        self.logger.info(
            "CTRL-%s-INJECT state=%#04x observed=%#04x leg=%d", tag, state, observed, leg
        )
        if in_flight:
            self.logger.info(
                "OBS-READ-SUPPRESS state=%#04x leg=%d req=%d graded=0", state, leg, req_held
            )

        # Release, then sample the interface on the following edge.
        await NextTimeStep()
        en.value = 0
        await RisingEdge(dut.clk_i)
        await ReadOnly()
        recovered = int(getattr(dut, f"efuse_{which}_state_o").value)
        req = int(getattr(dut, f"efuse_{which}_cmd_req_valid_o").value)
        data_probe = (
            dut.efuse_read_back_data_o if which == "read" else dut.efuse_program_read_back_data_o
        )
        err = int(getattr(dut, f"efuse_{which}_error_o").value)
        done = int(getattr(dut, f"efuse_{which}_done_o").value)
        busy = int(getattr(dut, f"efuse_{which}_busy_o").value)
        data = int(data_probe.value)
        ctrl = await self._csr(SepAxiOp.READ, _READ_CTRL if in_flight else _PROGRAM_CTRL)
        status = int(bool(ctrl & (_RD_STATUS if in_flight else _PG_STATUS)))

        if in_flight:
            self.logger.info(
                "OBS-READ-FAILCLOSED state=%#04x leg=%d recovered=%#04x req=%d err=%d "
                "done=%d busy=%d data=%#010x sensed=%#010x rd_ctrl=%#010x graded=0",
                state,
                leg,
                recovered,
                req,
                err,
                done,
                busy,
                data,
                self._sensed_control_word,
                ctrl,
            )
            fields = f"state={state:#04x} leg={leg} err={err} read_status={status}"
            assert (err, status) == (1, 1), (
                f"CHK-READ-FAILCLOSED-ERR FAIL: an illegal read state reported no error: {fields}"
            )
            self.logger.info("CHK-READ-FAILCLOSED-ERR PASS: %s", fields)
        else:
            self.logger.info(
                "OBS-PROGRAM-FAILCLOSED-STATUS state=%#04x leg=%d recovered=%#04x "
                "err_before=%d done_before=%d busy_before=%d err=%d done=%d busy=%d "
                "data=%#010x pg_ctrl=%#010x graded=0",
                state,
                leg,
                recovered,
                err_before,
                done_before,
                busy_before,
                err,
                done,
                busy,
                data,
                ctrl,
            )
            # The request is counted on every clock from the force edge until
            # the interface settles, not only on the release edge.
            await self._quiesce(which)
            req_stop.set()
            req_cycles = await req_count
            fields = (
                f"state={state:#04x} leg={leg} req_cycles={req_cycles} "
                f"err_before={err_before} err={err} program_status={status}"
            )
            assert req_cycles == 0 and (err, status) == (1, 1), (
                "CHK-PROGRAM-FAILCLOSED FAIL: an illegal state on the idle program "
                f"interface issued a bank command or reported no error: {fields}"
            )
            self.logger.info("CHK-PROGRAM-FAILCLOSED PASS: %s", fields)
            return
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
        self._recovery_word = img.field(_RECOVERY_FIELD).word
        staged = img.words[self._recovery_word] & 0xFFFF_FFFF
        if staged in (0, self._sensed_control_word):
            inverted = (~self._sensed_control_word) & 0xFFFF_FFFF
            img.words[self._recovery_word] = inverted or 0x5A5A_A5A5
        self._sensed_recovery_word = img.shadow_word(self._recovery_word)
        assert self._sensed_recovery_word not in (0, self._sensed_control_word), (
            f"test bug: {_RECOVERY_FIELD} word {self._recovery_word} is staged as "
            f"{self._sensed_recovery_word:#010x}, so the recovery read could not tell "
            "its own word from zero or from the timed-out read's word"
        )
        self.write_efuse_image(img)
        await self.bring_up_and_wait_fuse_sense(max_cycles=_MAX_SENSE_CYCLES)

        # Controls first: both interfaces issue a bank command when asked.
        await self._assert_read_alive("before")
        await self._assert_program_alive(pg_bits[0])

        # Establish the in-flight window before logging a withdrawal inside it.
        await self._assert_request_held("read", self._control_word * 32)

        for leg, state in enumerate(_ILLEGAL_STATES, start=1):
            await self._inject("read", state, self._control_word * 32, leg=leg)
        # The read FSM serves a new request after the injections (OCAH-HSR-SEP-010).
        await self._assert_read_alive("after")

        # Each program leg uses two fresh bits: OTP is write-once, so programming
        # a bit again would not issue a command and a control would fail for the
        # wrong reason.
        pg_leg_bits = zip(pg_bits[1::2], pg_bits[2::2])
        for leg, (state, (inject_bit, alive_bit)) in enumerate(
            zip(_ILLEGAL_STATES, pg_leg_bits), start=1
        ):
            if leg > 1:
                # The leg before left program_status at 1. A cold reset returns
                # it to its reset value 0 (efuse_interface_ctrl.rdl:97), so this
                # leg's error is set by its own injection. The alive check ends
                # in ReadOnly; leave it before the reset drives rst_ni.
                await RisingEdge(cocotb.top.clk_i)
                await self.resense(max_cycles=_MAX_SENSE_CYCLES)
            # Idle window, not in flight. Aborting an ACCEPTED program parks the
            # example shim's write FSM (see the VPLAN section of this test), and
            # every later leg that resenses would then read a corrupted shadow
            # word. The read leg is the one that logs a withdrawal.
            await self._inject(
                "program",
                state,
                _CONTROL_PROGRAM_WORD * 32 + inject_bit,
                in_flight=False,
                leg=leg,
            )
            # The program FSM serves a new request after this injection, before
            # any reset (OCAH-HSR-SEP-010).
            await self._assert_program_alive(alive_bit)

        # Error lifecycle on the same interface: set by a timed-out read, and
        # the next legal read completes cleanly.
        await self._read_error_lifecycle()

        # Last, because it latches secure_tm and a resense does not undo that
        # for the legs above.
        await self._read_blocked_by_secure_tm()
        self.logger.info(
            "illegal-state ALL CHECKS PASS: both FSMs, both injected codes, both "
            "interfaces live before and after the injections"
        )
