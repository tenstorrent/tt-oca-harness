# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The log engine on UART wrapper 0 fetching from an address that refuses the read.

`log_engine.rdl` has an error interrupt, `LOG_FETCH_ERR`, for an error
response on the engine's fetch from the log region; this leaf provokes that
response.

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

A third leg starves the write side of its next word. The engine fetches one
word at a time into a FIFO that runs ahead of the UART, so from local memory
the next word is always waiting when a word's last byte leaves. Here the log
sits in the output-fabric window, and the responder's R channel is held once
the first fetch has returned: the engine writes that word's eight bytes and
then waits for a word the FIFO does not have. Once all eight bytes have come
back through the loopback, with exactly one fetch returned, the hold is
released, and all sixteen bytes must arrive in order with no error status.

The companion `LOG_WRITE_ERR` has no bus to come from: the engine's write port
reaches only its own wrapper's UART register blocks, which answer every
address without error. Its status is set instead through `INTR_TEST`
(`sw = w`, `singlepulse`), with only `INTR_ENABLE.LOG_WRITE_ERR` set: the
status must set alone, the interrupt line must rise, and the written one must
clear the status and drop the line.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, FallingEdge, ReadOnly, RisingEdge
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from ._one_shot import _OneShot
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
from .smc_output_fabric_vip_utils import (
    OUTBOUND0_END,
    OUTBOUND0_FILTER_CONFIG,
    OUTBOUND0_START,
    OUTPUT_FABRIC_ADDR,
    OUTPUT_FABRIC_MODEL_BASE,
    OUTPUT_FABRIC_MODEL_REGION,
    OUTPUT_FABRIC_MODEL_SIZE,
    PASS_ALL_CONFIG,
    output_responder_counts,
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
#: A two-word log in the output-fabric window for the starved-fetch leg.
STARVED_REGION = OUTPUT_FABRIC_ADDR + 0x3000
STARVED_WORDS = (0x4847_4645_4443_4241, 0x5057_5655_5453_5251)
WORD_BYTES = 8


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

    async def _drain_uart(self, label: str, expected: int) -> int:
        """Read the ``expected`` bytes the engine wrote into the looped-back UART.

        `LSR.TEMT` reports the transmitter empty before the looped-back
        receiver has flagged the last byte, so the drain runs on the byte
        count and only then requires the transmitter idle. A byte beyond the
        count that lands before that fails here; the next leg's byte compare
        catches one that lands later.
        """
        received = 0
        lsr = 0
        for _ in range(POLL_LIMIT):
            lsr = await self.csr_read(f"{label}_LSR", uart_reg(WRAP, "LSR"))
            if lsr & LSR_DR:
                await self.csr_read(f"{label}_RBR", uart_reg(WRAP, "RBR"))
                received += 1
                assert received <= expected, (
                    f"{label}: the looped-back UART received {received} bytes for a "
                    f"{expected}-byte log"
                )
                continue
            if received == expected and lsr & LSR_TEMT:
                return received
            await ClockCycles(cocotb.top.clk_smc_i, POLL_CYCLES)
        raise AssertionError(
            f"{label}: {received} of {expected} log bytes reached the looped-back UART "
            f"before the transmitter went idle (LSR 0x{lsr:02x})"
        )

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
        self.written = await self._drain_uart(label, LOG_BYTES)
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

    async def _fabric_write(self, addr: int, value: int) -> None:
        item = SmcSysAxiItem(f"fabric_preload_0x{addr:x}")
        item.op = SmcSysAxiOp.WRITE
        item.addr = addr
        item.length = WORD_BYTES
        item.wdata = value
        await _OneShot(item, f"fabric_preload_0x{addr:x}_os").start(
            self.env.jtag_axi_agent.sequencer
        )
        assert item.resp_code == 0, f"preload of 0x{addr:08x} answered {item.resp_code}"

    async def _read_byte(self, label: str) -> int:
        for _ in range(POLL_LIMIT):
            lsr = await self.csr_read(f"{label}_LSR", uart_reg(WRAP, "LSR"))
            if lsr & LSR_DR:
                return (await self.csr_read(f"{label}_RBR", uart_reg(WRAP, "RBR"))) & 0xFF
            await ClockCycles(cocotb.top.clk_smc_i, POLL_CYCLES)
        raise AssertionError(f"{label}: no byte reached the looped-back receiver")

    async def _hold_after_first_fetch(self, base_reads: int) -> None:
        """Hold the output responder's R channel once the first fetch has returned.

        The counter moves on the edge that completes the first read; the hold is
        applied at the falling edge after it, before the engine can have issued
        and been answered on its second fetch.
        """
        dut = cocotb.top
        while True:
            await RisingEdge(dut.clk_smc_i)
            await ReadOnly()
            if output_responder_counts(dut)[1] > base_reads:
                break
        await FallingEdge(dut.clk_smc_i)
        dut.tb_output_axi_resp_hold.value = 1

    async def _starved_leg(self) -> tuple[list[int], int]:
        """A two-word log whose second fetch is held until the first word is out."""
        label = "STARVED"
        dut = cocotb.top
        if OUTPUT_FABRIC_MODEL_REGION not in self.memory_model.regions:
            self.memory_model.add_region(
                OUTPUT_FABRIC_MODEL_REGION, OUTPUT_FABRIC_MODEL_BASE, OUTPUT_FABRIC_MODEL_SIZE
            )
        await self.csr_write(f"{label}_OUT_START", OUTBOUND0_START, 0x0, length=8)
        await self.csr_write(f"{label}_OUT_END", OUTBOUND0_END, 0x00FF_FFFF_FFFF_FFFF, length=8)
        await self.csr_write(f"{label}_OUT_CFG", OUTBOUND0_FILTER_CONFIG, PASS_ALL_CONFIG, length=8)
        for i, word in enumerate(STARVED_WORDS):
            await self._fabric_write(STARVED_REGION + i * WORD_BYTES, word)
        want = [(w >> (8 * lane)) & 0xFF for w in STARVED_WORDS for lane in range(WORD_BYTES)]
        dut.tb_output_axi_resp_hold.value = 0
        element = array_reg_instances(LOG_CTRL_PATH, LOG_CTRL_PY, WRAP_STRIDE_SYMBOL, WRAP)[0]
        await self._arm(label, STARVED_REGION, uart_base(WRAP) + THR_OFFSET, 0)
        _, base_reads = output_responder_counts(dut)
        watcher = cocotb.start_soon(self._hold_after_first_fetch(base_reads))
        got: list[int] = []
        try:
            await self.csr_write(f"{label}_GO", element.addr, len(want))
            for i in range(WORD_BYTES):
                got.append(await self._read_byte(f"{label}_B{i}"))
            _, held_reads = output_responder_counts(dut)
            assert held_reads == base_reads + 1, (
                f"{label}: {held_reads - base_reads} fetches returned while the second was to "
                f"be held; the first word's bytes were to leave with the next word missing"
            )
        finally:
            watcher.kill()
            dut.tb_output_axi_resp_hold.value = 0
        for i in range(WORD_BYTES, len(want)):
            got.append(await self._read_byte(f"{label}_B{i}"))
        remaining = len(want)
        for _ in range(POLL_LIMIT):
            remaining = (await self.csr_read(f"{label}_HWCLR", element.addr)) & LOG_LEN
            if remaining == 0:
                break
            await ClockCycles(dut.clk_smc_i, POLL_CYCLES)
        assert remaining == 0, f"{label}: LOG_CTRL[0] still holds {remaining} byte(s)"
        status = await self.csr_read(f"{label}_INTR", engine_reg(WRAP, "INTR_STATUS"))
        assert not status & (FETCH_ERR | WRITE_ERR), (
            f"{label}: INTR_STATUS=0x{status:08x} after a log with no error"
        )
        assert got == want, (
            f"{label}: the UART received {[hex(b) for b in got]}, not the log "
            f"{[hex(b) for b in want]}"
        )
        await self.csr_write(f"{label}_STOP", engine_reg(WRAP, "CTRL"), 0)
        _, end_reads = output_responder_counts(dut)
        return got, end_reads - base_reads

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
            "interrupt enabled; the engine still finished the log (all %d bytes of the errored "
            "word reached the UART) and cleared LOG_CTRL[0], and the status cleared on its "
            "written one with the line dropping",
            REFUSING_ADDR,
            self.written,
        )

        got, fetches = await self._starved_leg()
        cocotb.log.info(
            "CHK-LOG-ENGINE-STARVED-FETCH: a %d-byte log in the output-fabric window, with the "
            "responder holding the second fetch until the first word's %d bytes had reached "
            "the UART, delivered every byte in order once the hold was released (%d fetches, "
            "no error status)",
            len(got),
            WORD_BYTES,
            fetches,
        )

        await self.csr_write("WRITE_ADDR_CLR", engine_reg(WRAP, "LOG_WRITE_ADDR"), 0)
        await self.csr_write("REGION_SIZE_CLR", engine_reg(WRAP, "LOG_REGION_SIZE"), 0)
        await self._write_err_test_leg()
        await restore_uart(self, WRAP)
        await self.csr_write("UART_REGATE", CLOCK_GATE_CONTROL, cg)
