# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The log engine's shared write port, read-data FIFO depth and region clamp on wrapper 0.

Three sentences of the log-engine and wrapper documents that no other leaf grades:

* **The transmit holding register is shared.** `uart_log_engine_wrap.adoc` (transmit holding
  register sharing) and `hw/ip/uart/log_engine/doc/index.adoc`: the CPU's register path and the
  engine's write path reach THR through one 2:1 AXI-Lite arbiter that serialises them, with no
  hardware lock. A 64-byte log is started with the UART in `MCR.LOOP`, and while it runs the CPU
  writes eight bytes of its own into THR, one after each of the first eight log bytes received,
  with `LOG_CTRL[0]` read non-zero before each write. The 72 characters the receiver returns have
  to be exactly the 64 log bytes in their order and the eight CPU bytes in theirs, the last CPU
  byte before the last log byte (a lock that holds the CPU's writes until the log ends fails),
  with no overrun, parity, framing or break flag on any read.
* **The read-data FIFO holds four words.** `hw/sys/smc/doc/periphs.adoc` (the log engine at the
  IP default `FIFO_DEPTH` 4), `log_engine/doc/interface.adoc` and `uart_log_engine_wrap.adoc`
  (`LOG_ENGINE_FIFO_DEPTH` words buffered between fetch and write). The transmitter is disabled
  with two characters parked in its FIFO, so `uart_txrdy_o` is low and the engine's write side
  cannot advance; a 64-byte log from the output-fabric window is then submitted and the fetches on
  the SYS_OUT port are counted: exactly four words are fetched before the engine stalls, and once
  the transmitter is re-enabled the remaining four are fetched and all 66 characters arrive in
  order.
* **Oversized regions clamp to 512 KiB.** `log_engine/doc/architecture.adoc` and `log_engine.rdl`
  (`LOG_REGION_SIZE`: larger values clamp). With `LOG_REGION_SIZE` at its 20-bit maximum, slot 1
  starts 512 KiB / 16 = 0x8000 bytes into the region: its one fetch has to go to that address and
  the word placed there has to come back through the UART.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles

from .smc_addr_map import SPM_MEMORY_BASE, UART_CG_EN, log_engine_u32, smc_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_log_engine_transfer_test_seq import _OutputAxiCapture
from .smc_log_engine_utils import (
    CTRL_EN,
    DLL_OFFSET,
    DLM_OFFSET,
    INTR_STATUS_MASK,
    LCR_DLAB,
    LCR_WLS,
    LOG_CTRL_PATH,
    LOG_CTRL_PY,
    LOG_LEN,
    LSR_DR,
    LSR_LINE_ERRORS,
    NUM_LOG_ENTRIES,
    RBR_DATA,
    THR_OFFSET,
    WLS_8_BITS,
    WRAP_STRIDE_SYMBOL,
    arm_uart,
    engine_reg,
    restore_uart,
    uart_base,
    uart_reg,
)
from .smc_output_fabric_vip_utils import (
    OUTBOUND0_END,
    OUTBOUND0_FILTER_CONFIG,
    OUTBOUND0_START,
    OUTPUT_FABRIC_ADDR,
    OUTPUT_FABRIC_MODEL_SIZE,
    PASS_ALL_CONFIG,
)
from .smc_regblock_field_sweep_utils import array_reg_instances

WRAP = 0
CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")
WORD_BYTES = 8
# log_engine.rdl LOG_REGION_SIZE: at most 512 KiB, larger values clamp; the
# field itself is 20 bits wide.
MAX_REGION_SIZE = 0x80000
MAX_REGION_SIZE_FIELD = log_engine_u32("LOG_ENGINE__LOG_REGION_SIZE__LOG_REGION_SIZE_bm")
# uart_log_engine_wrap: LOG_ENGINE_FIFO_DEPTH 4 in the SMC.
FIFO_DEPTH = 4

# Arbiter leg: a 64-byte log in slot 0 of a 0x400-byte SPM region, bytes 0x80
# upward, and eight CPU bytes below 0x80, so each character names its source.
ARB_REGION = SPM_MEMORY_BASE + 0x42000
ARB_REGION_SIZE = 0x400
ARB_LOG = tuple(0x80 + i for i in range(64))
CPU_BYTES = tuple(range(1, 9))

# Depth leg: the same log shape in the output-fabric window, and the character
# parked in the disabled transmitter.
DEPTH_REGION = OUTPUT_FABRIC_ADDR + 0x5000
DEPTH_LOG = tuple(0x40 + i for i in range(64))
# Two characters parked in the disabled transmitter. The engine's write goes to
# UART offset 0, which LCR.DLAB remaps onto DLL, so the divisor is restored
# while the transmit FIFO still holds the second character and
# uart_txrdy_o stays low until DLAB is cleared again.
PARK_BYTES = (0xEE, 0xED)
# Cycles the fetch count has to hold at the FIFO depth while the writes stall.
STALL_WINDOW_CYCLES = 2000

# Clamp leg: slot 1 of a region at the window base with the size field at its
# maximum lies 512 KiB / 16 into the region, inside the responder's memory.
CLAMP_REGION = OUTPUT_FABRIC_ADDR
CLAMP_SLOT = 1
CLAMP_SLOT_OFFSET = (MAX_REGION_SIZE // NUM_LOG_ENTRIES) * CLAMP_SLOT
CLAMP_WORD = 0xC1C2_C3C4_C5C6_C7C8
assert CLAMP_SLOT_OFFSET + WORD_BYTES <= OUTPUT_FABRIC_MODEL_SIZE

POLL_LIMIT = 400
POLL_CYCLES = 50
RX_POLLS_PER_BYTE = 400


def _word(data: bytes) -> int:
    return int.from_bytes(data, "little")


class smc_log_engine_port_limits_test_seq(SmcCsrSeq):
    """Share THR with the CPU, stall the write side, and oversize the region."""

    def __init__(self, name: str = "smc_log_engine_port_limits_test_seq") -> None:
        super().__init__(name)
        self.merged: list[int] = []
        self.stalled_fetches = 0
        self.total_fetches = 0
        self.clamp_ar = 0
        self._slot0 = None
        self._slot1 = None

    # -- helpers -----------------------------------------------------------

    async def _lsr(self, label: str) -> int:
        status = await self.csr_read(f"{label}_LSR", uart_reg(WRAP, "LSR"))
        assert status & LSR_LINE_ERRORS == 0, (
            f"{label}: LSR 0x{status:02x} reports overrun, parity, framing or break"
        )
        return status

    async def _program(self, label: str, region: int, size: int) -> None:
        await self.csr_write(f"{label}_EN_OFF", engine_reg(WRAP, "CTRL"), 0)
        await self.csr_write(f"{label}_SIZE", engine_reg(WRAP, "LOG_REGION_SIZE"), size)
        addr = engine_reg(WRAP, "LOG_REGION_ADDR")
        await self.csr_write(f"{label}_ADDR_LO", addr, region & 0xFFFF_FFFF)
        await self.csr_write(f"{label}_ADDR_HI", addr + 4, region >> 32)
        await self.csr_write(
            f"{label}_WRITE_ADDR", engine_reg(WRAP, "LOG_WRITE_ADDR"), uart_base(WRAP) + THR_OFFSET
        )
        await self.csr_write(f"{label}_INTR_CLR", engine_reg(WRAP, "INTR_STATUS"), INTR_STATUS_MASK)
        await self.csr_write(f"{label}_EN", engine_reg(WRAP, "CTRL"), CTRL_EN)

    async def _await_clear(self, label: str, element) -> None:
        remaining = None
        for _ in range(POLL_LIMIT):
            remaining = (await self.csr_read(f"{label}_HWCLR", element.addr)) & LOG_LEN
            if remaining == 0:
                break
            await ClockCycles(cocotb.top.clk_smc_i, POLL_CYCLES)
        assert remaining == 0, f"{label}: LOG_CTRL still holds {remaining} byte(s)"
        status = await self.csr_read(f"{label}_INTR", engine_reg(WRAP, "INTR_STATUS"))
        assert status == 0, f"{label}: INTR_STATUS 0x{status:08x} after the log"
        await self.csr_write(f"{label}_EN_DONE", engine_reg(WRAP, "CTRL"), 0)

    async def _drain(self, label: str, expected: int, side=None) -> list[int]:
        """Read ``expected`` characters; ``side(received)`` runs after each one."""
        received: list[int] = []
        reads = 0
        status = 0
        while len(received) < expected:
            assert reads < expected * RX_POLLS_PER_BYTE, (
                f"{label}: {len(received)} of {expected} characters within "
                f"{expected * RX_POLLS_PER_BYTE} LSR reads; last LSR 0x{status:02x}"
            )
            status = await self._lsr(label)
            reads += 1
            if status & LSR_DR:
                received.append(
                    (await self.csr_read(f"{label}_RBR", uart_reg(WRAP, "RBR"))) & RBR_DATA
                )
                if side is not None:
                    await side(received)
        return received

    async def _set_divisor(self, label: str, divisor: int) -> None:
        base = uart_base(WRAP)
        # The word length stays at 8 bits while DLAB is set, so a character the
        # transmitter picks up during the divisor write keeps its format.
        await self.csr_write(
            f"{label}_LCR_DLAB", uart_reg(WRAP, "LCR"), (WLS_8_BITS & LCR_WLS) | LCR_DLAB
        )
        await self.csr_write(f"{label}_DLL", base + DLL_OFFSET, divisor)
        await self.csr_write(f"{label}_DLM", base + DLM_OFFSET, 0)
        await self.csr_write(f"{label}_LCR_8N1", uart_reg(WRAP, "LCR"), WLS_8_BITS & LCR_WLS)

    @staticmethod
    def _probe(name: str) -> int:
        value = getattr(cocotb.top, name).value
        assert value.is_resolvable, f"{name} is X/Z"
        return int(value)

    def _region_ars(self, capture: _OutputAxiCapture, region: int, size: int) -> list[int]:
        return [ar[0] for ar in capture.ars if region <= ar[0] < region + size]

    # -- legs --------------------------------------------------------------

    async def _arbiter_leg(self) -> None:
        label = "ARB"
        words = [_word(bytes(ARB_LOG[i : i + WORD_BYTES])) for i in range(0, len(ARB_LOG), 8)]
        for i, value in enumerate(words):
            await self.csr_write(f"{label}_LOAD{i}", ARB_REGION + i * WORD_BYTES, value, length=8)
        for i, value in enumerate(words):
            await self.csr_read(
                f"{label}_LOAD{i}_RB", ARB_REGION + i * WORD_BYTES, expected=value, length=8
            )
        await self._program(label, ARB_REGION, ARB_REGION_SIZE)
        await self.csr_write(f"{label}_GO", self._slot0.addr, len(ARB_LOG))
        thr = uart_base(WRAP) + THR_OFFSET
        written: list[int] = []
        pending_at_write: list[int] = []

        async def side(received: list[int]) -> None:
            if len(written) < len(CPU_BYTES):
                pending = (
                    await self.csr_read(f"{label}_LEN_{len(written)}", self._slot0.addr)
                ) & LOG_LEN
                pending_at_write.append(pending)
                byte = CPU_BYTES[len(written)]
                await self.csr_write(f"{label}_CPU_THR_{byte:02x}", thr, byte)
                written.append(byte)

        received = await self._drain(label, len(ARB_LOG) + len(CPU_BYTES), side)
        assert all(p == len(ARB_LOG) for p in pending_at_write), (
            f"{label}: LOG_CTRL[0] read {pending_at_write} before the CPU writes; every CPU byte "
            f"is written while the engine's log is still pending"
        )
        assert sorted(received) == sorted(ARB_LOG + CPU_BYTES), (
            f"{label}: the receiver returned {[hex(b) for b in received]}, not the 64 log bytes "
            f"and the 8 CPU bytes"
        )
        assert [b for b in received if b >= 0x80] == list(ARB_LOG), (
            f"{label}: the log bytes arrived out of order: "
            f"{[hex(b) for b in received if b >= 0x80]}"
        )
        assert [b for b in received if b < 0x80] == list(CPU_BYTES), (
            f"{label}: the CPU bytes arrived out of order: {[hex(b) for b in received if b < 0x80]}"
        )
        last_cpu = received.index(CPU_BYTES[-1])
        last_log = received.index(ARB_LOG[-1])
        assert last_cpu < last_log, (
            f"{label}: the last CPU byte arrived at position {last_cpu}, after the last log byte "
            f"at {last_log}; the arbiter serialises the two paths with no lock, so CPU bytes "
            f"written while the log runs are transmitted before it ends"
        )
        await self._await_clear(label, self._slot0)
        self.merged = received
        cocotb.log.info(
            "CHK-LE-THR-ARBITER-MERGE: wrapper 0 in MCR.LOOP, a 64-byte log (0x80..0xbf) and %d "
            "CPU THR writes (%s) issued while LOG_CTRL[0] read %d; the receiver returned all %d "
            "characters, the log bytes in order and the CPU bytes in order, the last CPU byte at "
            "position %d before the last log byte at %d, no OE/PE/FE/BI on any LSR read; merged "
            "order %s; LOG_CTRL[0] cleared, INTR_STATUS 0",
            len(CPU_BYTES),
            [hex(b) for b in CPU_BYTES],
            len(ARB_LOG),
            len(received),
            last_cpu,
            last_log,
            " ".join(f"{b:02x}" for b in received),
        )

    async def _depth_leg(self) -> None:
        label = "DEPTH"
        mem = self.cfg.sys_out_mem
        for i in range(0, len(DEPTH_LOG), WORD_BYTES):
            mem.write_int(DEPTH_REGION + i, _word(bytes(DEPTH_LOG[i : i + WORD_BYTES])), WORD_BYTES)
        # Characters parked in the disabled transmitter hold uart_txrdy_o low.
        await self._set_divisor(label, 0)
        for byte in PARK_BYTES:
            await self.csr_write(f"{label}_PARK_{byte:02x}", uart_base(WRAP) + THR_OFFSET, byte)
        for _ in range(POLL_LIMIT):
            if self._probe("tb_uart0_tx_ready") == 0:
                break
            await ClockCycles(cocotb.top.clk_smc_i, 1)
        assert self._probe("tb_uart0_tx_ready") == 0, (
            f"{label}: tb_uart0_tx_ready still 1 with a character parked in the disabled "
            f"transmitter"
        )
        capture = _OutputAxiCapture()
        task = cocotb.start_soon(capture.run())
        try:
            await self._program(label, DEPTH_REGION, ARB_REGION_SIZE)
            await self.csr_write(f"{label}_GO", self._slot0.addr, len(DEPTH_LOG))
            fetched = 0
            for _ in range(POLL_LIMIT):
                fetched = len(self._region_ars(capture, DEPTH_REGION, ARB_REGION_SIZE))
                if fetched >= FIFO_DEPTH:
                    break
                await ClockCycles(cocotb.top.clk_smc_i, POLL_CYCLES)
            assert fetched >= FIFO_DEPTH, (
                f"{label}: only {fetched} fetch(es) on the SYS_OUT port within "
                f"{POLL_LIMIT * POLL_CYCLES} cycles of the submission"
            )
            await ClockCycles(cocotb.top.clk_smc_i, STALL_WINDOW_CYCLES)
            self.stalled_fetches = len(self._region_ars(capture, DEPTH_REGION, ARB_REGION_SIZE))
            assert self.stalled_fetches == FIFO_DEPTH, (
                f"{label}: {self.stalled_fetches} words fetched with the write side stalled, "
                f"{STALL_WINDOW_CYCLES} cycles after the fourth; the read-data FIFO holds "
                f"{FIFO_DEPTH} words"
            )
            assert self._probe("tb_uart0_log_write_stalled") == 1, (
                f"{label}: the engine does not hold a fetched word against the low "
                f"tb_uart0_tx_ready"
            )
            await self._set_divisor(label, 1)
            received = await self._drain(label, len(PARK_BYTES) + len(DEPTH_LOG))
            assert received == [*PARK_BYTES, *DEPTH_LOG], (
                f"{label}: the receiver returned {[hex(b) for b in received]}, not the parked "
                f"{[hex(b) for b in PARK_BYTES]} followed by the 64 log bytes"
            )
            await self._await_clear(label, self._slot0)
        finally:
            task.kill()
        self.total_fetches = len(self._region_ars(capture, DEPTH_REGION, ARB_REGION_SIZE))
        assert self.total_fetches == len(DEPTH_LOG) // WORD_BYTES, (
            f"{label}: {self.total_fetches} fetches for a {len(DEPTH_LOG)}-byte log"
        )
        cocotb.log.info(
            "CHK-LOGENG-RDATA-FIFO-DEPTH-4: with the transmitter disabled (divisor 0) and "
            "%s parked so tb_uart0_tx_ready read 0, a 64-byte log from the output-fabric "
            "window fetched exactly %d words and then held (%d cycles, tb_uart0_log_write_stalled "
            "1); with the divisor restored the remaining words were fetched (%d in all) and the "
            "parked characters plus all 64 log bytes arrived in order",
            [hex(b) for b in PARK_BYTES],
            self.stalled_fetches,
            STALL_WINDOW_CYCLES,
            self.total_fetches,
        )

    async def _clamp_leg(self) -> None:
        label = "CLAMP"
        self.cfg.sys_out_mem.write_int(CLAMP_REGION + CLAMP_SLOT_OFFSET, CLAMP_WORD, WORD_BYTES)
        capture = _OutputAxiCapture()
        task = cocotb.start_soon(capture.run())
        try:
            await self._program(label, CLAMP_REGION, MAX_REGION_SIZE_FIELD)
            size = await self.csr_read(f"{label}_SIZE_RB", engine_reg(WRAP, "LOG_REGION_SIZE"))
            assert size == MAX_REGION_SIZE_FIELD, f"{label}: LOG_REGION_SIZE read 0x{size:x}"
            await self.csr_write(f"{label}_GO", self._slot1.addr, WORD_BYTES)
            received = await self._drain(label, WORD_BYTES)
            await self._await_clear(label, self._slot1)
        finally:
            task.kill()
        want = list(CLAMP_WORD.to_bytes(WORD_BYTES, "little"))
        assert received == want, (
            f"{label}: the receiver returned {[hex(b) for b in received]}, not the word at "
            f"0x{CLAMP_REGION + CLAMP_SLOT_OFFSET:x}"
        )
        ars = self._region_ars(capture, CLAMP_REGION, OUTPUT_FABRIC_MODEL_SIZE)
        assert ars == [CLAMP_REGION + CLAMP_SLOT_OFFSET], (
            f"{label}: fetches at {[hex(a) for a in ars]} for slot {CLAMP_SLOT} of a region "
            f"sized 0x{MAX_REGION_SIZE_FIELD:x}; the clamp to 0x{MAX_REGION_SIZE:x} puts the "
            f"slot at 0x{CLAMP_REGION + CLAMP_SLOT_OFFSET:x}"
        )
        self.clamp_ar = ars[0]
        cocotb.log.info(
            "CHK-LOGENG-REGION-CLAMP-512K: LOG_REGION_SIZE 0x%x (read back) with the region at "
            "0x%x: slot %d's one fetch went to 0x%x (= base + 0x%x / 16 x %d), and its word "
            "0x%016x came back through the UART; LOG_CTRL[%d] cleared, INTR_STATUS 0",
            MAX_REGION_SIZE_FIELD,
            CLAMP_REGION,
            CLAMP_SLOT,
            self.clamp_ar,
            MAX_REGION_SIZE,
            CLAMP_SLOT,
            CLAMP_WORD,
            CLAMP_SLOT,
        )

    # -- body --------------------------------------------------------------

    async def body(self) -> None:
        await self.wait_fuse_sense_done()
        assert self.cfg is not None and self.cfg.sys_out_mem is not None, (
            "the SYS_OUT responder is not bound, so the window legs cannot seed their logs"
        )
        elements = array_reg_instances(LOG_CTRL_PATH, LOG_CTRL_PY, WRAP_STRIDE_SYMBOL, WRAP)
        self._slot0, self._slot1 = elements[0], elements[CLAMP_SLOT]
        cg = await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        await self.csr_write("UART_UNGATE", CLOCK_GATE_CONTROL, cg & ~UART_CG_EN)
        await arm_uart(self, WRAP)

        await self._arbiter_leg()

        filters = (
            ("OUT0_START", OUTBOUND0_START, 0),
            ("OUT0_END", OUTBOUND0_END, 0x00FF_FFFF_FFFF_FFFF),
            ("OUT0_CFG", OUTBOUND0_FILTER_CONFIG, PASS_ALL_CONFIG),
        )
        saved = [await self.csr_read(f"{name}_SAVE", addr, length=8) for name, addr, _ in filters]
        for name, addr, value in filters:
            await self.csr_write(name, addr, value, length=8)
        try:
            await self._depth_leg()
            await self._clamp_leg()
        finally:
            for (name, addr, _), value in zip(filters, saved):
                await self.csr_write(f"{name}_RESTORE", addr, value, length=8)

        for name, reg in (
            ("SIZE", engine_reg(WRAP, "LOG_REGION_SIZE")),
            ("ADDR_LO", engine_reg(WRAP, "LOG_REGION_ADDR")),
            ("ADDR_HI", engine_reg(WRAP, "LOG_REGION_ADDR") + 4),
            ("WRITE_ADDR", engine_reg(WRAP, "LOG_WRITE_ADDR")),
        ):
            await self.csr_write(f"{name}_CLR", reg, 0)
        await restore_uart(self, WRAP)
        await self.csr_write("UART_REGATE", CLOCK_GATE_CONTROL, cg)

        sb = getattr(getattr(self, "env", None), "scoreboard", None)
        assert sb is not None, "no scoreboard on this sequence's env"
        assert sb.sys_axi_checks_seen >= self.accesses, (
            f"the scoreboard checked {sb.sys_axi_checks_seen} SEP_IN items, this sequence "
            f"issued {self.accesses}"
        )
