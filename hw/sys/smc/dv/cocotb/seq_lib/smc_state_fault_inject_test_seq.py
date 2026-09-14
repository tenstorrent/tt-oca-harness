# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Directed eFuse and Zeroer state-corruption fault injection.

The testbench forces an unused encoding into a state flop for one cycle. The
forced value itself is never scored: the checks read the block's reaction on
signals the force does not touch -- the fuse request line during the corrupted
cycle, the fail-closed outputs and CSR status after the force is released, and
a legal operation succeeding afterwards.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import FallingEdge, NextTimeStep, ReadOnly, RisingEdge

from .smc_addr_map import ZEROER_CTRL_STATUS, efuse_ifc_u32, smc_addr
from .smc_csr_seq_utils import SmcCsrSeq

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
# ZEROER_CTRL CTRL_STATUS.STATUS mirrors the Zeroer's busy output and sits
# above bit 31, so the register is read as a 64-bit word.
ZEROER_STATUS_BUSY = 1 << 32

EFUSE_IDLE = 0b01
EFUSE_ERROR_DATA = 0xBADCAB1E
ZEROER_ERROR = 0b000
ZEROER_IDLE = 0b001
ZEROER_ILLEGAL_STATES = (0b011, 0b101, 0b110, 0b111)
_BOUND = 10_000


class smc_state_fault_inject_test_seq(SmcCsrSeq):
    """Prove same-cycle request suppression and fail-closed recovery."""

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
    ) -> None:
        dut = cocotb.top
        state = getattr(dut, f"tb_efuse_{kind}_state")
        request = getattr(dut, f"tb_efuse_{kind}_req_valid")
        error = getattr(dut, f"tb_efuse_{kind}_error")
        inject_value = getattr(dut, f"tb_efuse_{kind}_state_inject")
        inject_enable = getattr(dut, f"tb_efuse_{kind}_state_inject_en")

        if expect_prior_request:
            await self._wait_signal(request, 1, f"{kind} request before corruption")
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

    async def _program_faults(self) -> None:
        dut = cocotb.top

        value = await self._program_legal("PROGRAM_BASELINE")
        assert not (value & PROG_STATUS), f"program baseline completed with error (0x{value:08x})"
        prior = int(dut.tb_efuse_program_readback.value)
        assert prior != EFUSE_ERROR_DATA, "program baseline already equals illegal-state sentinel"

        await self._inject_efuse_state(kind="program", encoding=0b00, expect_prior_request=False)
        await self._check_efuse_fault_csr("program", "PROGRAM_ILLEGAL_00_CSR")
        await self._program_recovered("PROGRAM_RECOVERED_00")

        monitor = cocotb.start_soon(
            self._inject_efuse_state(kind="program", encoding=0b11, expect_prior_request=True)
        )
        await self.csr_write(
            "PROGRAM_CORRUPT_GO", PROGRAM_CTRL, PROG_DATA | PROG_GO | PROG_RB | PROG_EN
        )
        await monitor
        await self._check_efuse_fault_csr("program", "PROGRAM_ILLEGAL_11_CSR")
        await self.csr_write("PROGRAM_CORRUPT_IDLE", PROGRAM_CTRL, 0)
        await self._program_recovered("PROGRAM_RECOVERED_11")

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

    async def _read_faults(self) -> None:
        dut = cocotb.top
        await self._read_once("READ_BASELINE")
        prior = int(dut.tb_efuse_readback.value)
        assert prior != EFUSE_ERROR_DATA, "read baseline already equals illegal-state sentinel"

        await self._inject_efuse_state(kind="read", encoding=0b00, expect_prior_request=False)
        await self._check_efuse_fault_csr("read", "READ_ILLEGAL_00_CSR")
        await self._read_once("READ_SUCCESS_AFTER_ILLEGAL")
        assert int(dut.tb_efuse_read_error.value) == 0, (
            "successful read did not clear the illegal-state error"
        )

        monitor = cocotb.start_soon(
            self._inject_efuse_state(kind="read", encoding=0b11, expect_prior_request=True)
        )
        await self.csr_write("READ_CORRUPT_GO", READ_CTRL, READ_GO | READ_EN)
        await monitor
        await self._check_efuse_fault_csr("read", "READ_ILLEGAL_11_CSR")
        await self.csr_write("READ_CORRUPT_IDLE", READ_CTRL, 0)
        await self._read_once("READ_SUCCESS_AFTER_CORRUPT")
        assert int(dut.tb_efuse_read_error.value) == 0, (
            "successful read did not clear the in-flight illegal-state error"
        )

        for selector, name in ((0b01, "PHYSICAL"), (0b10, "GUARD"), (0b11, "SECURE_TEST")):
            dut.tb_efuse_read_error_inject.value = selector
            await self._read_once(f"READ_{name}_ERROR")
            assert int(dut.tb_efuse_read_error.value) == 1, (
                f"{name}: read error output did not assert"
            )
            assert int(dut.tb_efuse_readback.value) == 0, (
                f"{name}: failed read did not clear return data"
            )
            dut.tb_efuse_read_error_inject.value = 0
            await RisingEdge(dut.clk_smc_i)
            await self.csr_write(f"READ_{name}_REQ_ERR_CLEAR", STATUS, REQ_ERR_CLR)
            await self.csr_write(f"READ_{name}_REQ_ERR_CLEAR_IDLE", STATUS, 0)

    async def _zeroer_cold_reset(self, label: str) -> None:
        dut = cocotb.top
        await NextTimeStep()
        dut.rst_cold_ni.value = 0
        await FallingEdge(dut.rst_primary_smc_clk_no)
        await self._wait_signal(dut.tb_zeroer_state, ZEROER_IDLE, f"{label} reset escape")
        await NextTimeStep()
        dut.rst_cold_ni.value = 1
        await self.wait_fuse_sense_done()

    async def _zeroer_faults(self) -> None:
        dut = cocotb.top
        for encoding in ZEROER_ILLEGAL_STATES:
            # Each encoding starts from a quiescent IDLE Zeroer, so entering the
            # absorbing error state is this injection's doing.
            await self._wait_signal(dut.tb_zeroer_state, ZEROER_IDLE, f"Zeroer {encoding:03b} idle")
            assert int(dut.tb_zeroer_busy.value) == 0, f"Zeroer busy before {encoding:03b}"
            status = await self.csr_read(
                f"ZEROER_{encoding:03b}_IDLE_STATUS", ZEROER_CTRL_STATUS, length=8
            )
            assert not (status & ZEROER_STATUS_BUSY), (
                f"Zeroer CSR busy before {encoding:03b} (0x{status:016x})"
            )

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

            await self._zeroer_cold_reset(f"Zeroer {encoding:03b}")

        status = await self.csr_read("ZEROER_RESET_STATUS", ZEROER_CTRL_STATUS, length=8)
        assert not (status & ZEROER_STATUS_BUSY), (
            f"Zeroer CSR still busy after cold reset (0x{status:016x})"
        )

    async def body(self) -> None:
        await self.wait_fuse_sense_done()
        await self._program_faults()
        await self._read_faults()
        await self._zeroer_faults()
        cocotb.log.info(
            "CHK-STATE-FAULT PASS: eFuse 00/11 suppressed the request, failed closed with "
            "done/status set in the CSR and the sentinel read-back, then completed a legal "
            "operation; read error sources set status; Zeroer 011/101/110/111 each entered the "
            "absorbing error state from IDLE, reported busy over the CSR, and only a cold reset "
            "returned it to IDLE"
        )
