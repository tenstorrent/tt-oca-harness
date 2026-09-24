# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The log engine on UART wrapper 0 fetching from an address that refuses the read.

`log_engine.rdl` has an error interrupt, `LOG_FETCH_ERR`, for an error
response on the engine's fetch from the log region. The other log-engine
leaves give the engine a good region and raise the interrupt only through
`INTR_TEST`, so no fetch had ever come back with an error.

The address that refuses is the one `smc_deadspace_decode_test` holds the
decode to: inside the I2C0 instance's stride but past its `SIZE`, which the
I2C wrapper refuses with an error response rather than answering.
`LOG_REGION_ADDR` points there and one `LOG_CTRL` element asks for a log.
`INTR_STATUS.LOG_FETCH_ERR` must set and `LOG_WRITE_ERR` must not. With
`INTR_ENABLE.LOG_FETCH_ERR` set, the wrapper's interrupt line,
`tb_uart_irq_combined[0]`, must be low before the error and high after it --
the line also carries the 16550's own interrupt, so the UART is left with its
interrupts disabled -- and the status bit then clears on its written one and
the line drops.

The error does not stop the engine: the fetched word is still handed to the
write side and the log runs to its end, and only then does the engine clear the
element's `LOG_CTRL` length and retire its arbiter request. The engine is
disabled only after that clear. The vendored arbiter's `ReqStaysHighUntilGranted`
assumption forbids withdrawing an ungranted request, which disabling the
engine or zeroing the length mid-log would do.

The companion `LOG_WRITE_ERR` has no bus to come from: the engine's write port
reaches only its own wrapper's UART register blocks, which answer every
address without error. Its status is set instead through `INTR_TEST`
(`sw = w`, `singlepulse`), with only `INTR_ENABLE.LOG_WRITE_ERR` set: the
status must set alone, the interrupt line must rise, and the written one must
clear the status and drop the line.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles

from .smc_addr_map import UART_CG_EN, smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_log_engine_utils import (
    CTRL_EN,
    LOG_CTRL_PATH,
    LOG_CTRL_PY,
    LOG_LEN,
    LSR_DR,
    LSR_TEMT,
    THR_OFFSET,
    WRAP_STRIDE_SYMBOL,
    arm_uart,
    engine_reg,
    log_engine_u32,
    restore_uart,
    uart_base,
    uart_reg,
)
from .smc_regblock_field_sweep_utils import array_reg_instances

WRAP = 0
CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")
FETCH_ERR = log_engine_u32("LOG_ENGINE__INTR_STATUS__LOG_FETCH_ERR_bm")
WRITE_ERR = log_engine_u32("LOG_ENGINE__INTR_STATUS__LOG_WRITE_ERR_bm")
ENABLE_FETCH = log_engine_u32("LOG_ENGINE__INTR_ENABLE__LOG_FETCH_ERR_bm")
ENABLE_WRITE = log_engine_u32("LOG_ENGINE__INTR_ENABLE__LOG_WRITE_ERR_bm")
WRITE_ERR_TEST = log_engine_u32("LOG_ENGINE__INTR_TEST__LOG_WRITE_ERR_bm")
#: The I2C0 instance's stride runs past its SIZE; the wrapper refuses accesses
#: in between (the decode `smc_deadspace_decode_test` holds it to).
REFUSING_ADDR = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR", 0) + 0x100
REGION_SIZE = 0x100
LOG_BYTES = 8
POLL_LIMIT = 400
POLL_CYCLES = 50


class smc_log_engine_fetch_error_test_seq(SmcCsrSeq):
    """Point the log engine's fetch at an address that refuses it."""

    def __init__(self, name: str = "smc_log_engine_fetch_error_test_seq") -> None:
        super().__init__(name)
        self.written = 0

    def _irq(self) -> int:
        raw = cocotb.top.tb_uart_irq_combined.value
        assert raw.is_resolvable, "tb_uart_irq_combined is X/Z"
        return int(raw) & 1

    async def _await_status(self, label: str, bit: int) -> int:
        status = 0
        for _ in range(POLL_LIMIT):
            status = await self.csr_read(f"{label}_STATUS", engine_reg(WRAP, "INTR_STATUS"))
            if status & bit:
                return status
            await ClockCycles(cocotb.top.clk_smc_i, POLL_CYCLES)
        raise AssertionError(f"{label}: INTR_STATUS never showed 0x{bit:x} (0x{status:08x})")

    async def _await_irq(self, label: str, want: int) -> None:
        for _ in range(POLL_LIMIT):
            if self._irq() == want:
                return
            await ClockCycles(cocotb.top.clk_smc_i, 4)
        raise AssertionError(f"{label}: tb_uart_irq_combined[0] never reached {want}")

    async def _arm(self, label: str, region: int, write_addr: int, enable: int) -> None:
        await self.csr_write(f"{label}_OFF", engine_reg(WRAP, "CTRL"), 0)
        await self.csr_write(f"{label}_SIZE", engine_reg(WRAP, "LOG_REGION_SIZE"), REGION_SIZE)
        region_reg = engine_reg(WRAP, "LOG_REGION_ADDR")
        await self.csr_write(f"{label}_REGION_LO", region_reg, region & 0xFFFF_FFFF)
        await self.csr_write(f"{label}_REGION_HI", region_reg + 4, region >> 32)
        await self.csr_write(f"{label}_WRITE_ADDR", engine_reg(WRAP, "LOG_WRITE_ADDR"), write_addr)
        await self.csr_write(
            f"{label}_INTR_CLR", engine_reg(WRAP, "INTR_STATUS"), FETCH_ERR | WRITE_ERR
        )
        await self.csr_write(f"{label}_INTR_EN", engine_reg(WRAP, "INTR_ENABLE"), enable)
        status = await self.csr_read(f"{label}_INTR_IDLE", engine_reg(WRAP, "INTR_STATUS"))
        assert not status & (FETCH_ERR | WRITE_ERR), (
            f"{label}: INTR_STATUS=0x{status:08x} before the engine runs"
        )
        await ClockCycles(cocotb.top.clk_smc_i, 20)
        assert self._irq() == 0, f"{label}: tb_uart_irq_combined[0] is high before the error"
        await self.csr_write(f"{label}_ON", engine_reg(WRAP, "CTRL"), CTRL_EN)

    async def _drain_uart(self, label: str) -> int:
        """Read out whatever the engine wrote into the looped-back UART."""
        received = 0
        for _ in range(POLL_LIMIT):
            lsr = await self.csr_read(f"{label}_LSR", uart_reg(WRAP, "LSR"))
            if lsr & LSR_DR:
                await self.csr_read(f"{label}_RBR", uart_reg(WRAP, "RBR"))
                received += 1
                continue
            if lsr & LSR_TEMT:
                return received
            await ClockCycles(cocotb.top.clk_smc_i, POLL_CYCLES)
        raise AssertionError(f"{label}: the UART never went idle after the engine's write")

    async def _leg(
        self, label: str, region: int, write_addr: int, want: int, other: int, enable: int
    ) -> None:
        element = array_reg_instances(LOG_CTRL_PATH, LOG_CTRL_PY, WRAP_STRIDE_SYMBOL, WRAP)[0]
        await self._arm(label, region, write_addr, enable)
        await self.csr_write(f"{label}_GO", element.addr, LOG_BYTES)
        status = await self._await_status(label, want)
        assert not status & other, (
            f"{label}: INTR_STATUS=0x{status:08x}; only the one error this leg provokes may set"
        )
        await self._await_irq(f"{label}_RAISE", 1)
        # The engine carries an errored fetch through to its write and clears the
        # element's length when the log is done, which retires the arbiter request.
        # Disabling the engine or zeroing the length before that withdraws a request
        # the arbiter has not granted, so the leaf waits for the hardware clear.
        remaining = LOG_BYTES
        for _ in range(POLL_LIMIT):
            remaining = (await self.csr_read(f"{label}_HWCLR", element.addr)) & LOG_LEN
            if remaining == 0:
                break
            await ClockCycles(cocotb.top.clk_smc_i, POLL_CYCLES)
        assert remaining == 0, (
            f"{label}: LOG_CTRL[0] still holds {remaining} byte(s) after the errored fetch; "
            f"the engine has to finish the log and clear the length"
        )
        self.written = await self._drain_uart(label)
        await self.csr_write(f"{label}_STOP", engine_reg(WRAP, "CTRL"), 0)
        await self.csr_write(f"{label}_W1C", engine_reg(WRAP, "INTR_STATUS"), want)
        cleared = await self.csr_read(f"{label}_CLEARED", engine_reg(WRAP, "INTR_STATUS"))
        assert not cleared & want, f"{label}: the written one left 0x{cleared:08x}"
        await self._await_irq(f"{label}_DROP", 0)
        await self.csr_write(f"{label}_INTR_EN_OFF", engine_reg(WRAP, "INTR_ENABLE"), 0)

    async def _write_err_test_leg(self) -> None:
        """Set LOG_WRITE_ERR through INTR_TEST, with only its interrupt enabled."""
        label = "WRITE_TEST"
        status = await self.csr_read(f"{label}_ENTRY", engine_reg(WRAP, "INTR_STATUS"))
        assert not status & (FETCH_ERR | WRITE_ERR), (
            f"{label}: INTR_STATUS=0x{status:08x} before the forced event"
        )
        await self.csr_write(f"{label}_ENABLE", engine_reg(WRAP, "INTR_ENABLE"), ENABLE_WRITE)
        await ClockCycles(cocotb.top.clk_smc_i, 20)
        assert self._irq() == 0, f"{label}: tb_uart_irq_combined[0] is high before the event"
        await self.csr_write(f"{label}_TEST", engine_reg(WRAP, "INTR_TEST"), WRITE_ERR_TEST)
        status = await self.csr_read(f"{label}_SET", engine_reg(WRAP, "INTR_STATUS"))
        assert status & WRITE_ERR and not status & FETCH_ERR, (
            f"{label}: INTR_TEST.LOG_WRITE_ERR left INTR_STATUS=0x{status:08x}; the write "
            f"status sets alone"
        )
        await self._await_irq(f"{label}_RAISE", 1)
        await self.csr_write(f"{label}_W1C", engine_reg(WRAP, "INTR_STATUS"), WRITE_ERR)
        cleared = await self.csr_read(f"{label}_CLEARED", engine_reg(WRAP, "INTR_STATUS"))
        assert not cleared & WRITE_ERR, f"{label}: the written one left 0x{cleared:08x}"
        await self._await_irq(f"{label}_DROP", 0)
        await self.csr_write(f"{label}_ENABLE_OFF", engine_reg(WRAP, "INTR_ENABLE"), 0)
        cocotb.log.info(
            "CHK-LOG-ENGINE-WRITE-ERR-TEST: INTR_TEST.LOG_WRITE_ERR set INTR_STATUS.LOG_WRITE_ERR "
            "alone, which raised tb_uart_irq_combined[0] with only that interrupt enabled; "
            "its written one cleared it and the line dropped"
        )

    async def body(self) -> None:

        await self.wait_fuse_sense_done()
        cg = await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        await self.csr_write("UART_UNGATE", CLOCK_GATE_CONTROL, cg & ~UART_CG_EN)
        # The engine writes a byte only while the UART can take one, so the UART is set
        # up the way the transfer leaf sets it up, with its own interrupts left off.
        await arm_uart(self, WRAP)
        await ClockCycles(cocotb.top.clk_smc_i, 20)
        assert self._irq() == 0, "tb_uart_irq_combined[0] is high before either leg"

        await self._leg(
            "FETCH",
            REFUSING_ADDR,
            uart_base(WRAP) + THR_OFFSET,
            FETCH_ERR,
            WRITE_ERR,
            ENABLE_FETCH,
        )
        cocotb.log.info(
            "CHK-LOG-ENGINE-FETCH-ERR: a log region at 0x%08x, which refuses the access, set "
            "INTR_STATUS.LOG_FETCH_ERR alone and raised tb_uart_irq_combined[0] with the "
            "interrupt enabled; the engine still finished the log (%d byte(s) reached the "
            "UART) and cleared LOG_CTRL[0], and the status cleared on its written one with "
            "the line dropping",
            REFUSING_ADDR,
            self.written,
        )

        await self.csr_write("WRITE_ADDR_CLR", engine_reg(WRAP, "LOG_WRITE_ADDR"), 0)
        await self.csr_write("REGION_SIZE_CLR", engine_reg(WRAP, "LOG_REGION_SIZE"), 0)
        await self._write_err_test_leg()
        await restore_uart(self, WRAP)
        await self.csr_write("UART_REGATE", CLOCK_GATE_CONTROL, cg)
