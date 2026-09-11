# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Directed eFuse and Zeroer state-corruption fault injection."""

from __future__ import annotations

import cocotb
from cocotb.triggers import FallingEdge, NextTimeStep, ReadOnly, RisingEdge

from .smc_addr_map import efuse_ifc_u32, smc_addr
from .smc_csr_seq_utils import SmcCsrSeq

PROGRAM_CTRL = smc_addr("SMC_TOP_EFUSE_INTERFACE_CTRL_EFUSE_PROGRAM_CTRL_BASE_ADDR")
READ_CTRL = smc_addr("SMC_TOP_EFUSE_INTERFACE_CTRL_EFUSE_READ_CTRL_BASE_ADDR")
STATUS = smc_addr("SMC_TOP_EFUSE_INTERFACE_CTRL_EFUSE_INTERFACE_CTRL_STATUS_BASE_ADDR")
PROG_DATA = efuse_ifc_u32("EFUSE_INTERFACE_CTRL__EFUSE_PROGRAM_CTRL__EFUSE_DATA_bm")
PROG_GO = efuse_ifc_u32("EFUSE_INTERFACE_CTRL__EFUSE_PROGRAM_CTRL__EFUSE_PROGRAM_GO_bm")
PROG_RB = efuse_ifc_u32("EFUSE_INTERFACE_CTRL__EFUSE_PROGRAM_CTRL__EFUSE_PROGRAM_READ_BACK_bm")
PROG_EN = efuse_ifc_u32("EFUSE_INTERFACE_CTRL__EFUSE_PROGRAM_CTRL__PROGRAM_ENABLE_bm")
PROG_DONE = efuse_ifc_u32("EFUSE_INTERFACE_CTRL__EFUSE_PROGRAM_CTRL__PROGRAM_DONE_bm")
READ_GO = efuse_ifc_u32("EFUSE_INTERFACE_CTRL__EFUSE_READ_CTRL__EFUSE_READ_GO_bm")
READ_EN = efuse_ifc_u32("EFUSE_INTERFACE_CTRL__EFUSE_READ_CTRL__READ_ENABLE_bm")
READ_DONE = efuse_ifc_u32("EFUSE_INTERFACE_CTRL__EFUSE_READ_CTRL__READ_DONE_bm")
REQ_ERR_CLR = efuse_ifc_u32(
    "EFUSE_INTERFACE_CTRL__EFUSE_INTERFACE_CTRL_STATUS__EFUSE_REQ_ERROR_CLEAR_bm"
)

EFUSE_IDLE = 0b01
EFUSE_WAIT = 0b10
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
        inject_value = getattr(dut, f"tb_efuse_{kind}_state_inject")
        inject_enable = getattr(dut, f"tb_efuse_{kind}_state_inject_en")

        if expect_prior_request:
            await self._wait_signal(request, 1, f"{kind} request before corruption")

        await NextTimeStep()
        inject_value.value = encoding
        inject_enable.value = 1
        await RisingEdge(dut.clk_smc_i)
        await ReadOnly()
        assert int(state.value) == encoding, (
            f"{kind}: fault encoding {encoding:02b} did not reach state flop"
        )
        assert int(request.value) == 0, (
            f"{kind}: request valid was not suppressed in the corruption cycle"
        )

        await NextTimeStep()
        inject_enable.value = 0
        await RisingEdge(dut.clk_smc_i)
        await ReadOnly()
        assert int(state.value) == EFUSE_IDLE, f"{kind}: illegal state did not recover to IDLE"
        assert int(request.value) == 0, f"{kind}: recovery exposed request valid"
        assert int(getattr(dut, f"tb_efuse_{kind}_busy").value) == 0
        assert int(getattr(dut, f"tb_efuse_{kind}_done").value) == 1
        assert int(getattr(dut, f"tb_efuse_{kind}_error").value) == 1
        readback_signal = (
            dut.tb_efuse_program_readback if kind == "program" else dut.tb_efuse_readback
        )
        readback = int(readback_signal.value)
        assert readback == EFUSE_ERROR_DATA, (
            f"{kind}: illegal-state recovery data 0x{readback:08x}, "
            f"expected 0x{EFUSE_ERROR_DATA:08x}"
        )
        await RisingEdge(dut.clk_smc_i)

    async def _wait_done(self, addr: int, mask: int, label: str) -> int:
        for _ in range(_BOUND):
            value = await self.csr_read(label, addr)
            if value & mask:
                return value
        raise AssertionError(f"{label}: completion did not assert")

    async def _program_faults(self) -> None:
        dut = cocotb.top
        command = PROG_DATA | PROG_GO | PROG_RB | PROG_EN

        await self.csr_write("PROGRAM_BASELINE_GO", PROGRAM_CTRL, command)
        await self._wait_done(PROGRAM_CTRL, PROG_DONE, "PROGRAM_BASELINE_DONE")
        prior = int(dut.tb_efuse_program_readback.value)
        assert prior != EFUSE_ERROR_DATA, "program baseline already equals illegal-state sentinel"
        await self.csr_write("PROGRAM_BASELINE_IDLE", PROGRAM_CTRL, 0)

        await self._inject_efuse_state(kind="program", encoding=0b00, expect_prior_request=False)
        assert int(dut.tb_efuse_program_readback.value) == EFUSE_ERROR_DATA

        monitor = cocotb.start_soon(
            self._inject_efuse_state(kind="program", encoding=0b11, expect_prior_request=True)
        )
        await self.csr_write("PROGRAM_CORRUPT_GO", PROGRAM_CTRL, command)
        await monitor
        await self.csr_write("PROGRAM_CORRUPT_IDLE", PROGRAM_CTRL, 0)

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
        await self._read_once("READ_SUCCESS_AFTER_ILLEGAL")
        assert int(dut.tb_efuse_read_error.value) == 0, (
            "successful read did not clear the illegal-state error"
        )

        monitor = cocotb.start_soon(
            self._inject_efuse_state(kind="read", encoding=0b11, expect_prior_request=True)
        )
        await self.csr_write("READ_CORRUPT_GO", READ_CTRL, READ_GO | READ_EN)
        await monitor
        await self.csr_write("READ_CORRUPT_IDLE", READ_CTRL, 0)

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

    async def _zeroer_faults(self) -> None:
        dut = cocotb.top
        for encoding in ZEROER_ILLEGAL_STATES:
            await NextTimeStep()
            dut.tb_zeroer_state_inject.value = encoding
            dut.tb_zeroer_state_inject_en.value = 1
            await RisingEdge(dut.clk_smc_i)
            await ReadOnly()
            assert int(dut.tb_zeroer_state.value) == encoding
            assert int(dut.tb_zeroer_busy.value) == 1
            assert int(dut.tb_zeroer_intp.value) == 0
            assert int(dut.tb_zeroer_awvalid.value) == 0
            assert int(dut.tb_zeroer_wvalid.value) == 0

            await NextTimeStep()
            dut.tb_zeroer_state_inject_en.value = 0
            await self._wait_signal(dut.tb_zeroer_state, ZEROER_ERROR, "Zeroer error state")
            for _ in range(2):
                await RisingEdge(dut.clk_smc_i)
                await ReadOnly()
                assert int(dut.tb_zeroer_state.value) == ZEROER_ERROR
                assert int(dut.tb_zeroer_busy.value) == 1
                assert int(dut.tb_zeroer_intp.value) == 0

        await NextTimeStep()
        dut.rst_cold_ni.value = 0
        await FallingEdge(dut.rst_primary_smc_clk_no)
        await self._wait_signal(dut.tb_zeroer_state, ZEROER_IDLE, "Zeroer reset escape")
        await NextTimeStep()
        dut.rst_cold_ni.value = 1

    async def body(self) -> None:
        await self.wait_fuse_sense_done()
        await self._program_faults()
        await self._read_faults()
        await self._zeroer_faults()
        cocotb.log.info(
            "CHK-STATE-FAULT PASS: eFuse 00/11 fail closed; read error sources set status; "
            "Zeroer 011/101/110/111 entered absorbing error and reset escaped"
        )
