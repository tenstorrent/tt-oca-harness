# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Directed eFuse and Zeroer state-corruption fault injection.

The testbench forces an unused encoding into a state flop for one cycle. The
forced value itself is never scored: the checks read the block's reaction on
signals the force does not touch -- the fuse request line during the corrupted
cycle, the fail-closed outputs and CSR status after the force is released, and
a legal operation succeeding afterwards.

Every Zeroer "a start write is ignored in ERROR" leg carries its own live control
immediately before its injection, and nothing resets the block between the two.
The control re-programs the pass-all output filters, which the cold reset ending
the previous encoding cleared -- rst_primary_smc_clk_ni is the filter CSRs' reset
(smc_internal_regs.sv: filter_ctrl_reg.arst_n), and a read-back after that reset
returns the reset word, not pass-all -- and then requires the identical
CTRL_STATUS write, issued from IDLE with DEST_ADDR/SIZE programmed, to start the
block and land exactly one write beat on the SYS_OUT responder.

That measurement, rather than an assumption about the filters, is what lets the
deny's "the responder write count did not move" mean the Zeroer refused the
start: the same write moved the same counter over the same filter configuration
cycles earlier, and the filters are not touched again until after the deny. The
port-level awvalid/wvalid asserts carry the deny at the Zeroer boundary; the
responder count carries it end to end.
"""

from __future__ import annotations

import os
import random

import cocotb
from cocotb.triggers import FallingEdge, NextTimeStep, ReadOnly, RisingEdge

from .smc_addr_map import (
    _REPO,
    INBOUND0_END,
    INBOUND0_FILTER_CONFIG,
    INBOUND0_START,
    OUTBOUND0_END,
    OUTBOUND0_FILTER_CONFIG,
    OUTBOUND0_START,
    ZEROER_CTRL_DEST_ADDR,
    ZEROER_CTRL_SIZE,
    ZEROER_CTRL_STATUS,
    efuse_ifc_u32,
    reg_field_encode,
    smc_addr,
)
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_output_fabric_vip_utils import (
    OUTPUT_FABRIC_ADDR,
    PASS_ALL_CONFIG,
    check_output_responder_delta,
    output_fabric_model,
    output_responder_counts,
)

PROGRAM_CTRL = smc_addr("SMC_TOP_EFUSE_INTERFACE_CTRL_EFUSE_PROGRAM_CTRL_BASE_ADDR")
READ_CTRL = smc_addr("SMC_TOP_EFUSE_INTERFACE_CTRL_EFUSE_READ_CTRL_BASE_ADDR")
STATUS = smc_addr("SMC_TOP_EFUSE_INTERFACE_CTRL_EFUSE_INTERFACE_CTRL_STATUS_BASE_ADDR")
PROG_DATA = efuse_ifc_u32("EFUSE_INTERFACE_CTRL__EFUSE_PROGRAM_CTRL__EFUSE_DATA_bm")
PROG_GO = efuse_ifc_u32("EFUSE_INTERFACE_CTRL__EFUSE_PROGRAM_CTRL__EFUSE_PROGRAM_GO_bm")
PROG_RB = efuse_ifc_u32("EFUSE_INTERFACE_CTRL__EFUSE_PROGRAM_CTRL__EFUSE_PROGRAM_READ_BACK_bm")
PROG_EN = efuse_ifc_u32("EFUSE_INTERFACE_CTRL__EFUSE_PROGRAM_CTRL__PROGRAM_ENABLE_bm")
PROG_BUSY = efuse_ifc_u32("EFUSE_INTERFACE_CTRL__EFUSE_PROGRAM_CTRL__PROGRAM_BUSY_bm")
PROG_DONE = efuse_ifc_u32("EFUSE_INTERFACE_CTRL__EFUSE_PROGRAM_CTRL__PROGRAM_DONE_bm")
PROG_STATUS = efuse_ifc_u32("EFUSE_INTERFACE_CTRL__EFUSE_PROGRAM_CTRL__PROGRAM_STATUS_bm")
READ_GO = efuse_ifc_u32("EFUSE_INTERFACE_CTRL__EFUSE_READ_CTRL__EFUSE_READ_GO_bm")
READ_EN = efuse_ifc_u32("EFUSE_INTERFACE_CTRL__EFUSE_READ_CTRL__READ_ENABLE_bm")
READ_BUSY = efuse_ifc_u32("EFUSE_INTERFACE_CTRL__EFUSE_READ_CTRL__READ_BUSY_bm")
READ_DONE = efuse_ifc_u32("EFUSE_INTERFACE_CTRL__EFUSE_READ_CTRL__READ_DONE_bm")
READ_STATUS = efuse_ifc_u32("EFUSE_INTERFACE_CTRL__EFUSE_READ_CTRL__READ_STATUS_bm")
REQ_ERR_CLR = efuse_ifc_u32(
    "EFUSE_INTERFACE_CTRL__EFUSE_INTERFACE_CTRL_STATUS__EFUSE_REQ_ERROR_CLEAR_bm"
)
# ZEROER_CTRL CTRL_STATUS is a 64-bit word: STATUS mirrors the Zeroer's busy
# output and INT_EN is the write side effect that starts the FSM. Both masks
# come from the generated field layout.
_ZEROER_CTRL_H = _REPO / "hw" / "ip" / "zeroer" / "regs" / "gen" / "c" / "zeroer_ctrl.h"
ZEROER_STATUS_BUSY = reg_field_encode(_ZEROER_CTRL_H, "ZEROER_CTRL", "CTRL_STATUS", status=1)
ZEROER_START = reg_field_encode(_ZEROER_CTRL_H, "ZEROER_CTRL", "CTRL_STATUS", int_en=1)
# The start control zeroes one 64-bit beat at the output fabric, so the
# operation is exactly one AXI write on the SYS_OUT responder.
ZEROER_CONTROL_SIZE = 8
ZEROER_CONTROL_WAIT_CYCLES = 200
FILTER_END_MAX = 0x00FF_FFFF_FFFF_FFFF

EFUSE_IDLE = 0b01
EFUSE_ERROR_DATA = 0xBADCAB1E
ZEROER_ERROR = 0b000
ZEROER_IDLE = 0b001
ZEROER_ILLEGAL_STATES = (0b011, 0b101, 0b110, 0b111)
EFUSE_UNUSED_STATES = (0b00, 0b11)
BLOCKS = ("program", "read", "zeroer")
RECOVERY_ORDERS = (("legal", "clear"), ("clear", "legal"))
_BOUND = 10_000


class smc_state_fault_inject_test_seq(SmcCsrSeq):
    """Prove same-cycle request suppression and fail-closed recovery.

    RAND-REP: the seed draws the block order, which unused encoding of each eFuse interface is
    injected with no request outstanding and which concurrently with a live operation, the
    injection cycle of the live one relative to the request (an offset inside the cycles the
    baseline operation held its request valid, so the corruption lands while the operation is
    live), the order in which the legal read and the read-error clear follow the two illegal-state
    injections and the physical read error, and the order of the four illegal Zeroer encodings.
    Every encoding is still walked in every run; the Zeroer injection stays from IDLE as the
    entry pins it.
    """

    def __init__(self, name: str = "smc_state_fault_inject_test_seq") -> None:
        super().__init__(name)
        self.seed = int(os.environ.get("RANDOM_SEED", "1"), 0)
        rng = random.Random(self.seed)
        self.block_order = rng.sample(BLOCKS, len(BLOCKS))
        # Per eFuse block: (encoding injected idle, encoding injected live, idle first?).
        self.efuse_cells: dict[str, tuple[int, int, bool]] = {}
        for kind in ("program", "read"):
            idle, live = rng.sample(EFUSE_UNUSED_STATES, 2)
            self.efuse_cells[kind] = (idle, live, rng.random() < 0.5)
        # The live injection offset is a fraction of the measured request window, resolved once
        # the baseline operation has been timed (see _live_offset).
        self.offset_fraction = {kind: rng.random() for kind in ("program", "read")}
        # The order is drawn for the two illegal-state injections and the physical error. The
        # guard error keeps the clear first: the bench forces the read interface's request-error
        # input and a released input holds the forced value until its driver next changes, which
        # the clear does. The secure-test refusal is followed by the clear alone: its forced input
        # is driven by a constant, so nothing re-drives it after the release.
        self.recovery = {
            label: rng.choice(RECOVERY_ORDERS)
            for label in ("ILLEGAL_IDLE", "ILLEGAL_LIVE", "PHYSICAL")
        }
        self.recovery["GUARD"] = ("clear", "legal")
        self.recovery["SECURE_TEST"] = ("clear",)
        self.zeroer_order = rng.sample(ZEROER_ILLEGAL_STATES, len(ZEROER_ILLEGAL_STATES))
        self.valid_cycles: dict[str, int] = {}
        self.offsets: dict[str, int] = {}
        cocotb.log.info(
            "RAND-SEED: %d; RAND-DRAW: block order %s; eFuse (idle, live, idle first) program=%s "
            "read=%s; live offset fractions program=%.3f read=%.3f; read recovery order %s; "
            "zeroer order %s",
            self.seed,
            self.block_order,
            self.efuse_cells["program"],
            self.efuse_cells["read"],
            self.offset_fraction["program"],
            self.offset_fraction["read"],
            {k: "->".join(v) for k, v in self.recovery.items()},
            [f"{e:03b}" for e in self.zeroer_order],
        )

    def _live_offset(self, kind: str) -> int:
        """Injection cycle of the live corruption: inside the measured request window."""
        window = self.valid_cycles[kind]
        offset = int(self.offset_fraction[kind] * max(0, window - 1))
        offset = min(offset, max(0, window - 2))
        self.offsets[kind] = offset
        cocotb.log.info(
            "RAND-DRAW: %s live injection offset %d cycles after the request rose (baseline "
            "request window %d cycles)",
            kind,
            offset,
            window,
        )
        return offset

    async def _watch_valid(self, kind: str, label: str) -> int:
        """Count the clk_smc_i rises at which the ``kind`` request valid reads 1 in one op."""
        signal = getattr(cocotb.top, f"tb_efuse_{kind}_req_valid")
        seen = 0
        for _ in range(_BOUND):
            await RisingEdge(cocotb.top.clk_smc_i)
            await ReadOnly()
            assert signal.value.is_resolvable, f"{label}: request valid sampled X/Z"
            if int(signal.value):
                seen += 1
            elif seen:
                return seen
        raise AssertionError(f"{label}: request valid never rose and fell within {_BOUND} cycles")

    async def _wait_signal(self, signal, value: int, label: str) -> None:
        for _ in range(_BOUND):
            await RisingEdge(cocotb.top.clk_smc_i)
            await ReadOnly()
            if signal.value.is_resolvable and int(signal.value) == value:
                return
        raise AssertionError(f"{label}: never reached {value}; last={signal.value}")

    async def _inject_efuse_state(
        self,
        *,
        kind: str,
        encoding: int,
        expect_prior_request: bool,
        offset: int = 0,
    ) -> None:
        dut = cocotb.top
        state = getattr(dut, f"tb_efuse_{kind}_state")
        request = getattr(dut, f"tb_efuse_{kind}_req_valid")
        error = getattr(dut, f"tb_efuse_{kind}_error")
        inject_value = getattr(dut, f"tb_efuse_{kind}_state_inject")
        inject_enable = getattr(dut, f"tb_efuse_{kind}_state_inject_en")

        if expect_prior_request:
            await self._wait_signal(request, 1, f"{kind} request before corruption")
            for n in range(offset):
                await RisingEdge(dut.clk_smc_i)
                await ReadOnly()
                assert int(request.value) == 1, (
                    f"{kind}: the operation completed {n + 1} cycles after its request rose, "
                    f"before the drawn injection cycle {offset}"
                )
        # The error flag is clear going in, so the flag the FSM raises on the
        # illegal encoding is a transition this injection caused.
        assert int(error.value) == 0, f"{kind}: error already set before corruption"

        await NextTimeStep()
        inject_value.value = encoding
        inject_enable.value = 1
        await RisingEdge(dut.clk_smc_i)
        await ReadOnly()
        assert int(request.value) == 0, (
            f"{kind}: request valid was not suppressed in the corruption cycle"
        )

        await NextTimeStep()
        inject_enable.value = 0
        await RisingEdge(dut.clk_smc_i)
        await ReadOnly()
        assert int(state.value) == EFUSE_IDLE, (
            f"{kind}: illegal state {encoding:02b} did not recover to IDLE; state={state.value}"
        )
        assert int(request.value) == 0, f"{kind}: recovery exposed request valid"
        assert int(getattr(dut, f"tb_efuse_{kind}_busy").value) == 0
        assert int(getattr(dut, f"tb_efuse_{kind}_done").value) == 1
        assert int(error.value) == 1, f"{kind}: illegal state {encoding:02b} did not raise error"
        readback_signal = (
            dut.tb_efuse_program_readback if kind == "program" else dut.tb_efuse_readback
        )
        readback = int(readback_signal.value)
        assert readback == EFUSE_ERROR_DATA, (
            f"{kind}: illegal-state recovery data 0x{readback:08x}, "
            f"expected 0x{EFUSE_ERROR_DATA:08x}"
        )
        await RisingEdge(dut.clk_smc_i)

    async def _check_efuse_fault_csr(self, kind: str, label: str) -> None:
        """The fail-closed completion is visible through the control register."""
        if kind == "program":
            addr, busy, done, status = PROGRAM_CTRL, PROG_BUSY, PROG_DONE, PROG_STATUS
        else:
            addr, busy, done, status = READ_CTRL, READ_BUSY, READ_DONE, READ_STATUS
        value = await self.csr_read(label, addr)
        assert value & done, f"{label}: CSR done not set after illegal state (0x{value:08x})"
        assert value & status, (
            f"{label}: CSR status not flagged after illegal state (0x{value:08x})"
        )
        assert not (value & busy), (
            f"{label}: CSR busy still set after illegal state (0x{value:08x})"
        )

    async def _wait_done(self, addr: int, mask: int, label: str) -> int:
        for _ in range(_BOUND):
            value = await self.csr_read(label, addr)
            if value & mask:
                return value
        raise AssertionError(f"{label}: completion did not assert")

    async def _program_legal(self, label: str) -> int:
        """Run a legal program command and return its completed CSR word."""
        await self.csr_write(f"{label}_GO", PROGRAM_CTRL, PROG_DATA | PROG_GO | PROG_RB | PROG_EN)
        value = await self._wait_done(PROGRAM_CTRL, PROG_DONE, f"{label}_DONE")
        await self.csr_write(f"{label}_IDLE", PROGRAM_CTRL, 0)
        return value

    async def _program_idle_injection(self, encoding: int) -> None:
        await self._inject_efuse_state(
            kind="program", encoding=encoding, expect_prior_request=False
        )
        await self._check_efuse_fault_csr("program", f"PROGRAM_ILLEGAL_{encoding:02b}_CSR")
        await self._program_recovered(f"PROGRAM_RECOVERED_{encoding:02b}")

    async def _program_live_injection(self, encoding: int) -> None:
        monitor = cocotb.start_soon(
            self._inject_efuse_state(
                kind="program",
                encoding=encoding,
                expect_prior_request=True,
                offset=self._live_offset("program"),
            )
        )
        await self.csr_write(
            "PROGRAM_CORRUPT_GO", PROGRAM_CTRL, PROG_DATA | PROG_GO | PROG_RB | PROG_EN
        )
        await monitor
        await self._check_efuse_fault_csr("program", f"PROGRAM_ILLEGAL_{encoding:02b}_CSR")
        await self.csr_write("PROGRAM_CORRUPT_IDLE", PROGRAM_CTRL, 0)
        await self._program_recovered(f"PROGRAM_RECOVERED_{encoding:02b}")

    async def _program_faults(self) -> None:
        dut = cocotb.top

        watch = cocotb.start_soon(self._watch_valid("program", "PROGRAM_BASELINE"))
        value = await self._program_legal("PROGRAM_BASELINE")
        self.valid_cycles["program"] = await watch
        assert not (value & PROG_STATUS), f"program baseline completed with error (0x{value:08x})"
        prior = int(dut.tb_efuse_program_readback.value)
        assert prior != EFUSE_ERROR_DATA, "program baseline already equals illegal-state sentinel"

        idle, live, idle_first = self.efuse_cells["program"]
        legs = [
            (self._program_idle_injection, idle),
            (self._program_live_injection, live),
        ]
        for leg, encoding in legs if idle_first else reversed(legs):
            await leg(encoding)

    async def _program_recovered(self, label: str) -> None:
        """The block is back in service after an illegal state.

        A legal program completes without error and its read-back is fuse data
        again rather than the sentinel, which also clears the fail-closed
        flags so the next injection's error and sentinel are its own.
        """
        value = await self._program_legal(label)
        assert not (value & PROG_STATUS), f"{label}: program errored (0x{value:08x})"
        recovered = int(cocotb.top.tb_efuse_program_readback.value)
        assert recovered != EFUSE_ERROR_DATA, f"{label}: read-back is still the sentinel"

    async def _read_once(self, label: str) -> None:
        dut = cocotb.top

        async def observe_completion() -> None:
            await self._wait_signal(dut.tb_efuse_read_done, 0, f"{label} accepted")
            assert int(dut.tb_efuse_read_error.value) == 0, (
                f"{label}: new legal request did not clear prior read error"
            )
            await self._wait_signal(dut.tb_efuse_read_done, 1, f"{label} completed")

        completion = cocotb.start_soon(observe_completion())
        await self.csr_write(f"{label}_GO", READ_CTRL, READ_GO | READ_EN)
        await completion
        await self.csr_write(f"{label}_IDLE", READ_CTRL, 0)

    async def _read_refused(self, label: str) -> None:
        """A start the interface refuses: no command issues and done stays set.

        The read interface answers a secure-test-mode start from IDLE in one
        cycle with read_error set, the return data cleared and read_done left
        at 1 (efuse_read_interface.sv, ST_READ_IDLE refused branch), so there
        is no done-low window to wait for.
        """
        dut = cocotb.top
        await self.csr_write(f"{label}_GO", READ_CTRL, READ_GO | READ_EN)
        await self._wait_signal(dut.tb_efuse_read_error, 1, f"{label} refused")
        assert int(dut.tb_efuse_read_done.value) == 1, (
            f"{label}: a refused start dropped read_done; the command was issued"
        )
        await self.csr_write(f"{label}_IDLE", READ_CTRL, 0)

    async def _read_recovery(self, key: str, label: str) -> None:
        """The legal read and the read-error clear that follow an injection, in the drawn order.

        The legal read must clear the prior read error (observed at its acceptance) and
        complete without one; the clear is the REQ_ERROR W1P write. Either order holds, as
        the clear does not touch the read interface's own error flag.
        """
        dut = cocotb.top
        for step in self.recovery[key]:
            if step == "legal":
                assert int(dut.tb_efuse_read_error.value) == 1, (
                    f"{label}: the read error is not set when the legal read starts"
                )
                await self._read_once(f"READ_{label}_LEGAL")
                assert int(dut.tb_efuse_read_error.value) == 0, (
                    f"{label}: the legal read after the injection left the read error set"
                )
            else:
                await self.csr_write(f"READ_{label}_REQ_ERR_CLEAR", STATUS, REQ_ERR_CLR)
                await self.csr_write(f"READ_{label}_REQ_ERR_CLEAR_IDLE", STATUS, 0)

    async def _read_idle_injection(self, encoding: int) -> None:
        await self._inject_efuse_state(kind="read", encoding=encoding, expect_prior_request=False)
        await self._check_efuse_fault_csr("read", f"READ_ILLEGAL_{encoding:02b}_CSR")
        await self._read_recovery("ILLEGAL_IDLE", f"ILLEGAL_{encoding:02b}")

    async def _read_live_injection(self, encoding: int) -> None:
        monitor = cocotb.start_soon(
            self._inject_efuse_state(
                kind="read",
                encoding=encoding,
                expect_prior_request=True,
                offset=self._live_offset("read"),
            )
        )
        await self.csr_write("READ_CORRUPT_GO", READ_CTRL, READ_GO | READ_EN)
        await monitor
        await self._check_efuse_fault_csr("read", f"READ_ILLEGAL_{encoding:02b}_CSR")
        await self.csr_write("READ_CORRUPT_IDLE", READ_CTRL, 0)
        await self._read_recovery("ILLEGAL_LIVE", f"CORRUPT_{encoding:02b}")

    async def _read_faults(self) -> None:
        dut = cocotb.top
        watch = cocotb.start_soon(self._watch_valid("read", "READ_BASELINE"))
        await self._read_once("READ_BASELINE")
        self.valid_cycles["read"] = await watch
        prior = int(dut.tb_efuse_readback.value)
        assert prior != EFUSE_ERROR_DATA, "read baseline already equals illegal-state sentinel"

        idle, live, idle_first = self.efuse_cells["read"]
        legs = [(self._read_idle_injection, idle), (self._read_live_injection, live)]
        for leg, encoding in legs if idle_first else reversed(legs):
            await leg(encoding)

        for selector, name in ((0b01, "PHYSICAL"), (0b10, "GUARD"), (0b11, "SECURE_TEST")):
            dut.tb_efuse_read_error_inject.value = selector
            if name == "SECURE_TEST":
                # Secure test mode is checked at the start: the read interface
                # refuses the start without issuing a command, so read_done
                # never drops and the error is reported from IDLE.
                await self._read_refused(f"READ_{name}_ERROR")
            else:
                await self._read_once(f"READ_{name}_ERROR")
            assert int(dut.tb_efuse_read_error.value) == 1, (
                f"{name}: read error output did not assert"
            )
            assert int(dut.tb_efuse_readback.value) == 0, (
                f"{name}: failed read did not clear return data"
            )
            dut.tb_efuse_read_error_inject.value = 0
            await RisingEdge(dut.clk_smc_i)
            await self._read_recovery(name, name)

    async def _zeroer_cold_reset(self, label: str) -> None:
        dut = cocotb.top
        await NextTimeStep()
        dut.rst_cold_ni.value = 0
        await FallingEdge(dut.rst_primary_smc_clk_no)
        await self._wait_signal(dut.tb_zeroer_state, ZEROER_IDLE, f"{label} reset escape")
        await NextTimeStep()
        dut.rst_cold_ni.value = 1
        await self.wait_fuse_sense_done()

    async def _program_output_fabric_pass_all(self, label: str) -> None:
        """Program filter entry 0 in both directions to pass all traffic.

        The filter CSRs are reset by rst_primary_smc_clk_ni
        (``smc_internal_regs.sv``: ``filter_ctrl_reg.arst_n``), which the cold
        reset between injections asserts and which a read-back after that reset
        confirms, so this runs once per control rather than once per test.
        """
        await self.csr_write(f"{label}_INBOUND0_START", INBOUND0_START, 0x0, length=8)
        await self.csr_write(f"{label}_INBOUND0_END", INBOUND0_END, FILTER_END_MAX, length=8)
        await self.csr_write(
            f"{label}_INBOUND0_FILTER_CONFIG", INBOUND0_FILTER_CONFIG, PASS_ALL_CONFIG, length=8
        )
        await self.csr_write(f"{label}_OUTBOUND0_START", OUTBOUND0_START, 0x0, length=8)
        await self.csr_write(f"{label}_OUTBOUND0_END", OUTBOUND0_END, FILTER_END_MAX, length=8)
        await self.csr_write(
            f"{label}_OUTBOUND0_FILTER_CONFIG", OUTBOUND0_FILTER_CONFIG, PASS_ALL_CONFIG, length=8
        )

    async def _zeroer_program_region(self, label: str) -> None:
        await self.csr_write(
            f"{label}_DEST_ADDR", ZEROER_CTRL_DEST_ADDR, OUTPUT_FABRIC_ADDR, length=8
        )
        await self.csr_write(f"{label}_SIZE", ZEROER_CTRL_SIZE, ZEROER_CONTROL_SIZE, length=8)

    async def _zeroer_idle_quiescent(self, label: str) -> None:
        dut = cocotb.top
        await self._wait_signal(dut.tb_zeroer_state, ZEROER_IDLE, f"{label} idle")
        assert int(dut.tb_zeroer_busy.value) == 0, f"{label}: busy while IDLE"
        status = await self.csr_read(f"{label}_IDLE_STATUS", ZEROER_CTRL_STATUS, length=8)
        assert not (status & ZEROER_STATUS_BUSY), f"{label}: CSR busy while IDLE (0x{status:016x})"

    async def _zeroer_start_control(self, label: str) -> None:
        """Positive control for one ERROR-state deny: the same start write, from IDLE, runs.

        Runs immediately before the injection it controls, and re-programs the
        pass-all output filters first, because the cold reset that ends the
        previous encoding is also the filter CSRs' reset. Requiring the write
        beat to land on the SYS_OUT responder here measures the path open under
        the same filter configuration the deny runs under, so the deny's
        unchanged responder write count is the Zeroer refusing the start rather
        than the path being shut.
        """
        dut = cocotb.top
        output_fabric_model(self)
        await self._program_output_fabric_pass_all(label)
        await self._zeroer_idle_quiescent(label)
        await self._zeroer_program_region(label)
        start_writes, start_reads = output_responder_counts()

        # A one-beat zeroing can raise and drop busy inside the CSR write's
        # completion latency, so the busy interval is sampled every cycle from
        # before the start write rather than waited for after it returns.
        seen: dict[str, int | set[int]] = {"busy_cycles": 0, "states": set()}

        async def observe_busy_interval() -> None:
            for _ in range(_BOUND):
                await RisingEdge(dut.clk_smc_i)
                await ReadOnly()
                busy = dut.tb_zeroer_busy.value
                assert busy.is_resolvable, f"{label}: tb_zeroer_busy sampled X/Z"
                if int(busy):
                    state = dut.tb_zeroer_state.value
                    assert state.is_resolvable, f"{label}: tb_zeroer_state sampled X/Z"
                    seen["busy_cycles"] += 1
                    seen["states"].add(int(state))
                elif seen["busy_cycles"]:
                    return
            raise AssertionError(
                f"{label}: busy interval did not complete within "
                f"{_BOUND} cycles (busy_cycles={seen['busy_cycles']})"
            )

        monitor = cocotb.start_soon(observe_busy_interval())
        await self.csr_write(f"{label}_START", ZEROER_CTRL_STATUS, ZEROER_START, length=8)
        await monitor
        assert seen["busy_cycles"], f"{label}: the start write never raised busy"
        # Busy asserts before the state register moves, so IDLE appears in the
        # first busy sample; what the control needs is that the FSM was also
        # seen somewhere else, i.e. the write actually advanced it.
        assert seen["states"] - {ZEROER_IDLE}, (
            f"{label}: busy for {seen['busy_cycles']} cycle(s) without leaving IDLE"
        )
        assert ZEROER_ERROR not in seen["states"], f"{label}: start entered ERROR"
        await check_output_responder_delta(
            start_writes=start_writes,
            start_reads=start_reads,
            write_delta=1,
            read_delta=0,
            last_addr=OUTPUT_FABRIC_ADDR,
            last_wdata=0,
            exact_writes=True,
            timeout_cycles=ZEROER_CONTROL_WAIT_CYCLES,
        )
        await self._wait_signal(dut.tb_zeroer_state, ZEROER_IDLE, f"{label} back to IDLE")
        assert int(dut.tb_zeroer_busy.value) == 0, f"{label}: busy after returning to IDLE"
        status = await self.csr_read(f"{label}_DONE_STATUS", ZEROER_CTRL_STATUS, length=8)
        assert not (status & ZEROER_STATUS_BUSY), (
            f"{label}: CSR still busy after the control zeroing (0x{status:016x})"
        )
        cocotb.log.info(
            f"CHK-ZEROER-START-CONTROL PASS [{label}]: with the pass-all inbound/outbound "
            "filters programmed and the Zeroer in IDLE with DEST_ADDR/SIZE set, the "
            f"CTRL_STATUS start write 0x{ZEROER_START:x} raised busy for "
            f"{seen['busy_cycles']} cycle(s) in states {sorted(seen['states'])}, produced "
            f"exactly one output-fabric write beat (0 at 0x{OUTPUT_FABRIC_ADDR:x}) and "
            "returned to IDLE with CSR busy clear, so the SYS_OUT write path is open "
            f"immediately before the deny that follows; drawn=seed {self.seed} zeroer order "
            f"{[f'{e:03b}' for e in self.zeroer_order]}"
        )

    async def _zeroer_faults(self) -> None:
        dut = cocotb.top
        for encoding in self.zeroer_order:
            # Each encoding gets its own control immediately before its
            # injection, so the deny below differs from the control in the FSM
            # state alone: the filters the control programs are still in place,
            # and the cold reset that clears them runs only after the deny. The
            # control moves the responder write count with the very write the
            # deny then requires not to move it.
            await self._zeroer_start_control(f"ZEROER_{encoding:03b}_CONTROL")
            # Each encoding starts from a quiescent IDLE Zeroer, so entering the
            # absorbing error state is this injection's doing, and DEST_ADDR/SIZE
            # are re-armed after the control consumed them.
            await self._zeroer_idle_quiescent(f"ZEROER_{encoding:03b}")
            await self._zeroer_program_region(f"ZEROER_{encoding:03b}")

            await NextTimeStep()
            dut.tb_zeroer_state_inject.value = encoding
            dut.tb_zeroer_state_inject_en.value = 1
            await RisingEdge(dut.clk_smc_i)
            await ReadOnly()
            assert int(dut.tb_zeroer_busy.value) == 1, f"{encoding:03b}: busy not raised"
            assert int(dut.tb_zeroer_intp.value) == 0, f"{encoding:03b}: intp raised"
            assert int(dut.tb_zeroer_awvalid.value) == 0, f"{encoding:03b}: awvalid raised"
            assert int(dut.tb_zeroer_wvalid.value) == 0, f"{encoding:03b}: wvalid raised"

            await NextTimeStep()
            dut.tb_zeroer_state_inject_en.value = 0
            await self._wait_signal(
                dut.tb_zeroer_state, ZEROER_ERROR, f"Zeroer {encoding:03b} error"
            )
            for _ in range(2):
                await RisingEdge(dut.clk_smc_i)
                await ReadOnly()
                assert int(dut.tb_zeroer_state.value) == ZEROER_ERROR
                assert int(dut.tb_zeroer_busy.value) == 1
                assert int(dut.tb_zeroer_intp.value) == 0
            # The absorbing state is what software sees: STATUS reports busy and
            # keeps reporting it, since nothing but a cold reset leaves ERROR.
            status = await self.csr_read(
                f"ZEROER_{encoding:03b}_ERROR_STATUS", ZEROER_CTRL_STATUS, length=8
            )
            assert status & ZEROER_STATUS_BUSY, (
                f"Zeroer CSR not busy in absorbing error after {encoding:03b} (0x{status:016x})"
            )
            assert int(dut.tb_zeroer_state.value) == ZEROER_ERROR, f"{encoding:03b}: left ERROR"

            # Writing CTRL_STATUS is the software start that this encoding's
            # control just ran from IDLE. In ERROR it must be ignored: the state,
            # busy and the AXI valids stay where they are, and the responder
            # write count stays put on a path the control showed to be open.
            writes_before, _reads_before = output_responder_counts()
            await self.csr_write(
                f"ZEROER_{encoding:03b}_ERROR_START", ZEROER_CTRL_STATUS, ZEROER_START, length=8
            )
            for _ in range(ZEROER_CONTROL_WAIT_CYCLES):
                await RisingEdge(dut.clk_smc_i)
                await ReadOnly()
                assert int(dut.tb_zeroer_state.value) == ZEROER_ERROR, (
                    f"{encoding:03b}: a CTRL_STATUS start write left ERROR"
                )
                assert int(dut.tb_zeroer_busy.value) == 1, f"{encoding:03b}: busy dropped on start"
                assert int(dut.tb_zeroer_intp.value) == 0, f"{encoding:03b}: intp raised on start"
                assert int(dut.tb_zeroer_awvalid.value) == 0, f"{encoding:03b}: awvalid on start"
                assert int(dut.tb_zeroer_wvalid.value) == 0, f"{encoding:03b}: wvalid on start"
            writes_after, _reads_after = output_responder_counts()
            assert writes_after == writes_before, (
                f"{encoding:03b}: the start write in ERROR produced an output-fabric beat "
                f"(tb_output_axi_write_count {writes_before}->{writes_after})"
            )

            await self._zeroer_cold_reset(f"Zeroer {encoding:03b}")

        status = await self.csr_read("ZEROER_RESET_STATUS", ZEROER_CTRL_STATUS, length=8)
        assert not (status & ZEROER_STATUS_BUSY), (
            f"Zeroer CSR still busy after cold reset (0x{status:016x})"
        )

    async def body(self) -> None:
        await self.wait_fuse_sense_done()
        blocks = {
            "program": self._program_faults,
            "read": self._read_faults,
            "zeroer": self._zeroer_faults,
        }
        for block in self.block_order:
            await blocks[block]()
        cells = "; ".join(
            f"{kind}: {idle:02b} idle, {live:02b} live at offset {self.offsets[kind]} of "
            f"{self.valid_cycles[kind]} request cycles, {'idle' if first else 'live'} first"
            for kind, (idle, live, first) in self.efuse_cells.items()
        )
        cocotb.log.info(
            "CHK-STATE-FAULT PASS: eFuse 00/11 suppressed the request, failed closed with "
            "done/status set in the CSR and the sentinel read-back, then completed a legal "
            "operation; read error sources set status; Zeroer 011/101/110/111 each entered the "
            "absorbing error state from IDLE, reported busy over the CSR, ignored the CTRL_STATUS "
            "start write that its own control had just used to zero a programmed region from "
            "IDLE over an open SYS_OUT path, and a cold reset returned it to IDLE; drawn=seed %d "
            "block order %s; %s; read recovery order %s; zeroer order %s",
            self.seed,
            self.block_order,
            cells,
            {k: "->".join(v) for k, v in self.recovery.items()},
            [f"{e:03b}" for e in self.zeroer_order],
        )
