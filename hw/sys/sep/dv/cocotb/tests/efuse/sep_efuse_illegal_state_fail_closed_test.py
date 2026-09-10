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
from cocotb.triggers import Event, NextTimeStep, ReadOnly, RisingEdge
from env.sep_lcc_golden import LC_PROD
from sep_base_test import sep_base_test
from seq_lib.sep_efuse_direct_read_seq import sep_efuse_direct_read_seq

# efuse_read_interface.sv / efuse_program_interface.sv: the legal encodings.
_ST_IDLE = 0b01
_ST_WAIT_RESP = 0b10
# The two the design says cannot occur. Both are walked: 2'b00 and 2'b11 fail
# `inside {IDLE, WAIT_RESP}` for different reasons, and a decoder written as a
# comparison against one of them would recover from that one only.
_ILLEGAL_STATES = (0b00, 0b11)

# efuse_read_interface.sv EFUSE_READ_ERROR_DATA
_READ_ERROR_DATA = 0xBADCAB1E

_MAX_SENSE_CYCLES = 20_000

# Any always-readable OTP word; the control grades FSM motion, not the value.
_CONTROL_WORD = 0


@pyuvm.test()
class sep_efuse_illegal_state_fail_closed_test(sep_base_test):
    """An illegal FSM encoding recovers to idle, reports error, issues nothing."""

    required_evidence = (
        "CHK-READ-ALIVE",
        "CHK-READ-SUPPRESS",
        "CHK-READ-FAILCLOSED",
        "CHK-PROGRAM-SUPPRESS",
        "CHK-PROGRAM-FAILCLOSED",
    )
    min_evidence = 5

    async def _assert_read_alive(self, tag: str) -> None:
        """Positive control: a frontdoor OTP read moves the read FSM.

        Fuse sense does not use this FSM -- it serves the EFUSE_READ_CTRL
        frontdoor -- so the control has to be a real direct read. Without it
        the recovery checks below hold on a block that never moves:
        permanently idle, permanently issuing nothing, which is
        indistinguishable from a machine that failed closed correctly.
        """
        seen_active = False
        stop = Event()

        async def _watch() -> None:
            nonlocal seen_active
            while not stop.is_set():
                await RisingEdge(cocotb.top.clk_i)
                await ReadOnly()
                if int(cocotb.top.efuse_read_state_o.value) != _ST_IDLE:
                    seen_active = True

        task = cocotb.start_soon(_watch())
        await self.start_seq(sep_efuse_direct_read_seq(_CONTROL_WORD))
        stop.set()
        await task

        assert seen_active, (
            f"CHK-READ-ALIVE FAIL ({tag}): a frontdoor OTP read left the read FSM in "
            "idle throughout, so the fail-closed checks would hold on a block that "
            "does nothing"
        )
        self.logger.info(
            "CHK-READ-ALIVE PASS (%s): a frontdoor OTP read drove the read FSM out of idle",
            tag,
        )

    async def _inject(self, which: str, state: int) -> None:
        dut = cocotb.top
        en = getattr(dut, f"efuse_{which}_state_inject_en_i")
        val = getattr(dut, f"efuse_{which}_state_inject_i")
        await NextTimeStep()
        val.value = state
        en.value = 1
        await RisingEdge(dut.clk_i)

        # While the state is illegal, nothing may be presented to the bank.
        await ReadOnly()
        observed = int(getattr(dut, f"efuse_{which}_state_o").value)
        assert observed == state, (
            f"test bug: {which} state reads {observed:#04x}, expected the injected "
            f"{state:#04x} -- the force did not reach the register"
        )
        assert int(dut.efuse_cmd_req_valid_o.value) == 0, (
            f"CHK-{which.upper()}-SUPPRESS FAIL: a command was presented to the fuse "
            f"bank while {which}_state_q held the illegal encoding {state:#04x}"
        )
        self.logger.info(
            "CHK-%s-SUPPRESS PASS: no bank command while %s_state_q = %#04x",
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
        assert recovered == _ST_IDLE, (
            f"CHK-{which.upper()}-FAILCLOSED FAIL: {which}_state_q recovered to "
            f"{recovered:#04x} from the illegal {state:#04x}, expected idle {_ST_IDLE:#04x}"
        )
        assert int(dut.efuse_cmd_req_valid_o.value) == 0, (
            f"CHK-{which.upper()}-FAILCLOSED FAIL: a bank command was issued while "
            f"recovering from {state:#04x}"
        )
        if which == "read":
            err = int(dut.efuse_read_error_o.value)
            done = int(dut.efuse_read_done_o.value)
            busy = int(dut.efuse_read_busy_o.value)
            data = int(dut.efuse_read_back_data_o.value)
            assert (err, done, busy) == (1, 1, 0), (
                f"CHK-READ-FAILCLOSED FAIL: recovering from {state:#04x} reported "
                f"error={err} done={done} busy={busy}, expected 1/1/0"
            )
            assert data == _READ_ERROR_DATA, (
                f"CHK-READ-FAILCLOSED FAIL: read_back_data = {data:#010x} recovering "
                f"from {state:#04x}, expected the error sentinel {_READ_ERROR_DATA:#010x} "
                "-- returning anything else risks handing back unfetched fuse data"
            )
        self.logger.info(
            "CHK-%s-FAILCLOSED PASS: %#04x -> idle, no bank command%s",
            which.upper(),
            state,
            ", error+done set, data = 0xbadcab1e" if which == "read" else "",
        )

    async def run_scenario(self) -> None:
        img = self.select_efuse_image(lc_raw=LC_PROD)
        self.write_efuse_image(img)
        await self.bring_up_and_wait_fuse_sense(max_cycles=_MAX_SENSE_CYCLES)

        # Control first: prove the read path is live before grading a refusal.
        await self._assert_read_alive("before")

        for state in _ILLEGAL_STATES:
            await self._inject("read", state)
            await self._inject("program", state)

        # The block still works afterwards: recovery returned it to service
        # rather than wedging it.
        await self._assert_read_alive("after")
        self.logger.info(
            "illegal-state fail-closed ALL CHECKS PASS: both FSMs, both illegal "
            "encodings, read path live before and after"
        )
