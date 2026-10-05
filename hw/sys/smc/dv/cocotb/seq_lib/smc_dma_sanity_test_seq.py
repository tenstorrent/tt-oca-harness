# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DMA source-to-destination payload check through the output-fabric responder.

The SYS_OUT responder is shared. The outbound filter this sequence programs
passes every address, so the SMC CPU cluster's instruction fetches at address
0 leave through the same port and complete on the same responder. The tb_top
``tb_output_axi_*_count`` registers count every transaction that completes
there, whatever issued it, so they cannot say that *this* sequence's traffic
arrived. Which of those fetches land inside a sampled window is decided by the
seeded clock periods, not by the DMA.

The counts below therefore come from ``_OutputFabricWatch``, which attributes
each SYS_OUT transaction to the address of its own address-channel handshake
and counts per address. That is exact in both directions -- a read the DMA
sent to the wrong address, or a second read of the same address, still fails --
and it does not depend on what else is on the bus.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from ._one_shot import _OneShot
from .smc_addr_map import smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq

DMA_CTRL_CONFIG = 0xC003_8000
DMA_CTRL_STATUS_0 = 0xC003_8004
DMA_CTRL_NEXT_ID_0 = 0xC003_8048
DMA_CTRL_DONE_0 = 0xC003_80C8
DMA_CTRL_DST_ADDRESS_LO = 0xC003_8108
DMA_CTRL_DST_ADDRESS_HI = 0xC003_810C
DMA_CTRL_SRC_ADDRESS_LO = 0xC003_8110
DMA_CTRL_SRC_ADDRESS_HI = 0xC003_8114
DMA_CTRL_LENGTH_LO = 0xC003_8118
DMA_CTRL_LENGTH_HI = 0xC003_811C
DMA_CTRL_DST_STRIDE_LO = 0xC003_8120
DMA_CTRL_DST_STRIDE_HI = 0xC003_8124
DMA_CTRL_SRC_STRIDE_LO = 0xC003_8128
DMA_CTRL_SRC_STRIDE_HI = 0xC003_812C
DMA_CTRL_NUM_REPETITIONS_LO = 0xC003_8130
DMA_CTRL_NUM_REPETITIONS_HI = 0xC003_8134
DMA_CONFIG_ENABLED_ND = 1 << 10

INBOUND0_FILTER_CONFIG = smc_indexed_addr(
    "SMC_TOP_SMC_INBOUND_FILTER_CTRL_FILTER_CONFIG_BASE_ADDR", 0
)
INBOUND0_START = smc_indexed_addr("SMC_TOP_SMC_INBOUND_FILTER_CTRL_START_ADDR_BASE_ADDR", 0)
INBOUND0_END = smc_indexed_addr("SMC_TOP_SMC_INBOUND_FILTER_CTRL_END_ADDR_BASE_ADDR", 0)
OUTBOUND0_FILTER_CONFIG = smc_indexed_addr(
    "SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_FILTER_CONFIG_BASE_ADDR", 0
)
OUTBOUND0_START = smc_indexed_addr("SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_START_ADDR_BASE_ADDR", 0)
OUTBOUND0_END = smc_indexed_addr("SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_END_ADDR_BASE_ADDR", 0)
PASS_ALL_CONFIG = 0x0100_3013

DMA_SRC_ADDR = 0x0200_0000
DMA_DST_ADDR = 0x0200_0008
DMA_MODEL_REGION = "dma_output_fabric"
DMA_MODEL_SIZE = 0x1000
DMA_PAYLOAD = bytes.fromhex("1020304050607080")
DMA_DST_POISON = bytes(0x5A for _ in range(len(DMA_PAYLOAD)))

# Single-byte descriptor. Both words are 8-byte aligned and disjoint from the
# eight-byte copy above, so the two legs cannot mask each other. The source
# word's first byte is the only byte the transfer may move; the destination
# word's remaining seven bytes carry a distinct poison, so a transfer that
# moved a whole 64-bit beat instead of one byte is visible in the readback.
ONE_BYTE_SRC_ADDR = 0x0200_0020
ONE_BYTE_DST_ADDR = 0x0200_0040
ONE_BYTE_SRC_WORD = bytes.fromhex("c3a5960f1e2d3c4b")
ONE_BYTE_DST_POISON = bytes(0xEE for _ in range(8))
ONE_BYTE_DST_EXPECTED = ONE_BYTE_SRC_WORD[:1] + ONE_BYTE_DST_POISON[1:]
# Thirty-two bytes, four full-width beats in one burst. Every source byte is
# distinct and every destination poison byte differs from the source byte in
# the same lane, so a beat that lands in the wrong place is visible.
BLOCK_SRC_ADDR = 0x0200_0100
BLOCK_DST_ADDR = 0x0200_0200
BLOCK_SRC_DATA = bytes(0x40 + i for i in range(32))
BLOCK_DST_POISON = bytes(0xA0 + (i % 8) for i in range(32))


class _OutputFabricWatch:
    """Per-address tally of the transactions issued to the SYS_OUT responder.

    A read transaction starts at its AR handshake and a write at its AW
    handshake, and the address is on the channel in that cycle, so counting
    there attributes every transaction to the address it names without needing
    to pair a response back to a request while several are outstanding.
    """

    def __init__(self, dut) -> None:
        self.dut = dut
        self.stop = False
        self.reads: dict[int, int] = {}
        self.writes: dict[int, int] = {}

    def _read(self, name: str) -> int | None:
        value = getattr(self.dut, name).value
        return int(value) if value.is_resolvable else None

    def _accepted(self, channel: str) -> int | None:
        valid = self._read(f"tb_output_axi_{channel}valid")
        ready = self._read(f"tb_output_axi_{channel}ready")
        if valid != 1 or ready != 1:
            return None
        return self._read(f"tb_output_axi_{channel}addr")

    async def run(self) -> None:
        while not self.stop:
            await RisingEdge(self.dut.clk_smc_i)
            await ReadOnly()
            addr = self._accepted("ar")
            if addr is not None:
                self.reads[addr] = self.reads.get(addr, 0) + 1
            addr = self._accepted("aw")
            if addr is not None:
                self.writes[addr] = self.writes.get(addr, 0) + 1

    def snapshot(self) -> tuple[dict[int, int], dict[int, int]]:
        return dict(self.reads), dict(self.writes)

    def foreign_reads(self, owned: tuple[int, ...]) -> int:
        """Transactions from other masters, reported so the bus stays visible."""
        return sum(count for addr, count in self.reads.items() if addr not in owned)


def _delta(now: dict[int, int], before: dict[int, int], addr: int) -> int:
    return now.get(addr, 0) - before.get(addr, 0)


class smc_dma_sanity_test_seq(SmcCsrSeq):
    """Program DMA and verify that output-fabric destination bytes match source."""

    def __init__(self, name: str = "smc_dma_sanity_test_seq") -> None:
        super().__init__(name)
        self.checked_bytes = 0
        self.model_checks = 0
        self.start_id = 0
        self.done_id = 0
        self.one_byte_dst = -1
        self.watch: _OutputFabricWatch | None = None
        self.watcher = None

    def _ensure_model_region(self) -> None:
        if DMA_MODEL_REGION not in self.memory_model.regions:
            self.memory_model.add_region(DMA_MODEL_REGION, DMA_SRC_ADDR, DMA_MODEL_SIZE)

    async def _program_output_fabric_pass_all(self) -> None:
        await self.csr_write("INBOUND0_START_PASS_ALL", INBOUND0_START, 0x0, length=8)
        await self.csr_write("INBOUND0_END_PASS_ALL", INBOUND0_END, 0x00FF_FFFF_FFFF_FFFF, length=8)
        await self.csr_write(
            "INBOUND0_FILTER_CONFIG_PASS_ALL", INBOUND0_FILTER_CONFIG, PASS_ALL_CONFIG, length=8
        )
        await self.csr_write("OUTBOUND0_START_PASS_ALL", OUTBOUND0_START, 0x0, length=8)
        await self.csr_write(
            "OUTBOUND0_END_PASS_ALL", OUTBOUND0_END, 0x00FF_FFFF_FFFF_FFFF, length=8
        )
        await self.csr_write(
            "OUTBOUND0_FILTER_CONFIG_PASS_ALL", OUTBOUND0_FILTER_CONFIG, PASS_ALL_CONFIG, length=8
        )

    async def _write_bytes(self, addr: int, data: bytes, *, update_golden: bool = False) -> None:
        assert self.env is not None, "sequence env is not initialized"
        item_name = f"jtag_dma_preload_0x{addr:x}"
        item = SmcSysAxiItem(item_name)
        item.op = SmcSysAxiOp.WRITE
        item.addr = addr
        item.length = min(len(data), 8)
        item.beats = max(1, len(data) // 8)
        item.wdata = int.from_bytes(data, "little")
        item.update_golden = update_golden
        item.memory_region = DMA_MODEL_REGION
        await _OneShot(item, f"{item_name}_os").start(self.env.jtag_axi_agent.sequencer)

    async def _read_bytes(self, addr: int, length: int, *, check_golden: bool = False) -> bytes:
        assert self.env is not None, "sequence env is not initialized"
        item_name = f"jtag_dma_read_0x{addr:x}"
        item = SmcSysAxiItem(item_name)
        item.op = SmcSysAxiOp.READ
        item.addr = addr
        item.length = min(length, 8)
        item.beats = max(1, length // 8)
        item.check_golden = check_golden
        item.memory_region = DMA_MODEL_REGION
        await _OneShot(item, f"{item_name}_os").start(self.env.jtag_axi_agent.sequencer)
        return item.rdata.to_bytes(length, "little")

    async def _program_dma(
        self,
        *,
        tag: str = "",
        src: int = DMA_SRC_ADDR,
        dst: int = DMA_DST_ADDR,
        length: int = len(DMA_PAYLOAD),
    ) -> None:
        await self.csr_write(f"DMA_CONFIG{tag}", DMA_CTRL_CONFIG, DMA_CONFIG_ENABLED_ND)
        await self.csr_write(f"DMA_DST_ADDRESS_LO{tag}", DMA_CTRL_DST_ADDRESS_LO, dst & 0xFFFF_FFFF)
        await self.csr_write(f"DMA_DST_ADDRESS_HI{tag}", DMA_CTRL_DST_ADDRESS_HI, dst >> 32)
        await self.csr_write(f"DMA_SRC_ADDRESS_LO{tag}", DMA_CTRL_SRC_ADDRESS_LO, src & 0xFFFF_FFFF)
        await self.csr_write(f"DMA_SRC_ADDRESS_HI{tag}", DMA_CTRL_SRC_ADDRESS_HI, src >> 32)
        await self.csr_write(f"DMA_LENGTH_LO{tag}", DMA_CTRL_LENGTH_LO, length)
        await self.csr_write(f"DMA_LENGTH_HI{tag}", DMA_CTRL_LENGTH_HI, 0)
        await self.csr_write(f"DMA_DST_STRIDE_LO{tag}", DMA_CTRL_DST_STRIDE_LO, 0)
        await self.csr_write(f"DMA_DST_STRIDE_HI{tag}", DMA_CTRL_DST_STRIDE_HI, 0)
        await self.csr_write(f"DMA_SRC_STRIDE_LO{tag}", DMA_CTRL_SRC_STRIDE_LO, 0)
        await self.csr_write(f"DMA_SRC_STRIDE_HI{tag}", DMA_CTRL_SRC_STRIDE_HI, 0)
        await self.csr_write(f"DMA_NUM_REPETITIONS_LO{tag}", DMA_CTRL_NUM_REPETITIONS_LO, 1)
        await self.csr_write(f"DMA_NUM_REPETITIONS_HI{tag}", DMA_CTRL_NUM_REPETITIONS_HI, 0)

    async def _wait_done(self, baseline_done: int) -> int:
        for _ in range(50):
            done = await self.csr_read("DMA_DONE_0_POLL", DMA_CTRL_DONE_0)
            if done > baseline_done:
                return done
            await ClockCycles(cocotb.top.clk_smc_i, 20)
        status = await self.csr_read("DMA_STATUS_0_TIMEOUT", DMA_CTRL_STATUS_0)
        raise AssertionError(
            f"DMA did not complete: baseline_done={baseline_done} status=0x{status:x}"
        )

    async def body(self) -> None:
        self._ensure_model_region()
        self.watch = _OutputFabricWatch(cocotb.top)
        self.watcher = cocotb.start_soon(self.watch.run())
        await self._program_output_fabric_pass_all()

        # Preload DUT + golden via scoreboard update_golden (U1-3).
        await self._write_bytes(DMA_DST_ADDR, DMA_DST_POISON, update_golden=True)
        await self._write_bytes(DMA_SRC_ADDR, DMA_PAYLOAD, update_golden=True)
        assert (
            await self._read_bytes(DMA_SRC_ADDR, len(DMA_PAYLOAD), check_golden=True) == DMA_PAYLOAD
        )
        assert (
            await self._read_bytes(DMA_DST_ADDR, len(DMA_DST_POISON), check_golden=True)
            == DMA_DST_POISON
        )

        # Baselined here, after every preload and golden-verify access, so the
        # deltas below are the DMA's own traffic plus the one post-copy read
        # this sequence issues.
        base_reads, base_writes = self.watch.snapshot()

        baseline_done = await self.csr_read("DMA_DONE_0_BASELINE", DMA_CTRL_DONE_0)
        await self._program_dma()
        # This read IS the launch, not an observation: idma_generated.sv gates
        # the register response on the arbiter (`read_happens && arb_ready`) and
        # submits the programmed descriptor. Nothing else may read NEXT_ID here
        # -- a second read would start a second, unprogrammed transfer.
        self.start_id = await self.csr_read("DMA_NEXT_ID_0_START", DMA_CTRL_NEXT_ID_0)
        self.done_id = await self._wait_done(baseline_done)
        # The id that completed is the id this launch was given. A test that the
        # id is merely non-zero would hold on any run: `next_id_i` is a
        # free-running allocation counter.
        assert self.done_id == self.start_id, (
            f"DMA completed id {self.done_id}, but this sequence launched id "
            f"{self.start_id}; DONE advanced for some other transfer"
        )
        # Predict DMA outcome in golden *before* the post-copy read so the
        # scoreboard check is DUT vs prediction (not golden==golden).
        self.memory_model.write(DMA_DST_ADDR, DMA_PAYLOAD, region=DMA_MODEL_REGION)
        actual = await self._read_bytes(DMA_DST_ADDR, len(DMA_PAYLOAD), check_golden=True)
        assert actual == DMA_PAYLOAD, (
            f"DMA copy mismatch: got {actual.hex()}, expected {DMA_PAYLOAD.hex()}"
        )
        reads, writes = self.watch.snapshot()
        # Exact per address, because every access this sequence made after the
        # baseline above is accounted for: the DMA reads the source word once
        # and writes the destination word once, and this sequence reads the
        # destination word once to verify it.
        src_reads = _delta(reads, base_reads, DMA_SRC_ADDR)
        dst_reads = _delta(reads, base_reads, DMA_DST_ADDR)
        dst_writes = _delta(writes, base_writes, DMA_DST_ADDR)
        assert dst_writes == 1, (
            f"DMA write did not reach the output responder: {dst_writes} write "
            f"transaction(s) addressed {DMA_DST_ADDR:#x} there, expected exactly one"
        )
        assert src_reads == 1, (
            f"DMA read did not reach the output responder: {src_reads} read "
            f"transaction(s) addressed the source {DMA_SRC_ADDR:#x} there, "
            f"expected exactly one"
        )
        assert dst_reads == 1, (
            f"the post-copy verification read did not reach the output responder: "
            f"{dst_reads} read transaction(s) addressed the destination "
            f"{DMA_DST_ADDR:#x} there, expected exactly one"
        )
        # Self-check on this sequence's own golden verification, NOT evidence
        # about the DMA: all three checks are raised by `check_golden=True` reads
        # issued here. The DMA proof is `actual == DMA_PAYLOAD` above.
        assert self.env.scoreboard.memory_model_checks_seen == 3, (
            f"sequence issued {self.env.scoreboard.memory_model_checks_seen} golden "
            f"checks, expected its own 3"
        )
        self.checked_bytes = len(DMA_PAYLOAD)
        self.model_checks = self.env.scoreboard.memory_model_checks_seen
        await self._copy_block()
        await self._copy_one_byte()

    async def _copy_block(self) -> None:
        """Descriptor with LENGTH = 32: one four-beat burst per direction.

        The eight-byte and one-byte legs each move a single beat, so neither
        shows the engine forming a burst. Thirty-two bytes is four full-width
        beats, small enough to stay one burst, and the destination is poisoned
        beat by beat so a burst that repeats, drops or misplaces a beat fails
        on the bytes rather than on the completion count.
        """
        await self._write_bytes(BLOCK_SRC_ADDR, BLOCK_SRC_DATA)
        await self._write_bytes(BLOCK_DST_ADDR, BLOCK_DST_POISON)
        assert await self._read_bytes(BLOCK_SRC_ADDR, len(BLOCK_SRC_DATA)) == BLOCK_SRC_DATA, (
            "block source preload did not stick"
        )
        assert await self._read_bytes(BLOCK_DST_ADDR, len(BLOCK_DST_POISON)) == BLOCK_DST_POISON, (
            "block destination poison did not stick"
        )

        base_reads, base_writes = self.watch.snapshot()
        baseline_done = await self.csr_read("DMA_DONE_0_BASELINE_BLOCK", DMA_CTRL_DONE_0)
        await self._program_dma(
            tag="_BLOCK", src=BLOCK_SRC_ADDR, dst=BLOCK_DST_ADDR, length=len(BLOCK_SRC_DATA)
        )
        start_id = await self.csr_read("DMA_NEXT_ID_0_START_BLOCK", DMA_CTRL_NEXT_ID_0)
        done_id = await self._wait_done(baseline_done)
        assert done_id == start_id, (
            f"block transfer completed id {done_id}, but this leg launched id {start_id}"
        )

        actual = await self._read_bytes(BLOCK_DST_ADDR, len(BLOCK_SRC_DATA))
        assert actual == BLOCK_SRC_DATA, (
            f"LENGTH={len(BLOCK_SRC_DATA)} transfer wrote {actual.hex()}, expected "
            f"{BLOCK_SRC_DATA.hex()}"
        )
        reads, writes = self.watch.snapshot()
        src_reads = _delta(reads, base_reads, BLOCK_SRC_ADDR)
        dst_reads = _delta(reads, base_reads, BLOCK_DST_ADDR)
        dst_writes = _delta(writes, base_writes, BLOCK_DST_ADDR)
        assert dst_writes == 1, (
            f"the LENGTH={len(BLOCK_SRC_DATA)} transfer addressed {BLOCK_DST_ADDR:#x} with "
            f"{dst_writes} write transaction(s) on the output responder, expected one burst"
        )
        assert src_reads == 1, (
            f"the LENGTH={len(BLOCK_SRC_DATA)} transfer addressed its source "
            f"{BLOCK_SRC_ADDR:#x} with {src_reads} read transaction(s) on the output "
            f"responder, expected one burst"
        )
        assert dst_reads == 1, (
            f"the LENGTH={len(BLOCK_SRC_DATA)} verification read addressed "
            f"{BLOCK_DST_ADDR:#x} with {dst_reads} read transaction(s) on the output "
            f"responder, expected exactly one"
        )
        self.block_dst = actual

    async def _copy_one_byte(self) -> None:
        """Second descriptor with LENGTH = 1: exactly one byte moves.

        The eight-byte leg above cannot separate "the programmed length was
        honoured" from "a whole 64-bit beat was copied", because there the two
        outcomes are the same bytes. A one-byte descriptor does separate them:
        the destination word's upper seven bytes must still read the poison
        this leg wrote, so a DUT that emitted a full-width strobe for
        LENGTH = 1 fails on those seven bytes rather than on the one it copied.
        """
        await self._write_bytes(ONE_BYTE_SRC_ADDR, ONE_BYTE_SRC_WORD)
        await self._write_bytes(ONE_BYTE_DST_ADDR, ONE_BYTE_DST_POISON)
        src_before = await self._read_bytes(ONE_BYTE_SRC_ADDR, len(ONE_BYTE_SRC_WORD))
        dst_before = await self._read_bytes(ONE_BYTE_DST_ADDR, len(ONE_BYTE_DST_POISON))
        assert src_before == ONE_BYTE_SRC_WORD, (
            f"one-byte source preload did not stick: got {src_before.hex()}, "
            f"expected {ONE_BYTE_SRC_WORD.hex()}"
        )
        assert dst_before == ONE_BYTE_DST_POISON, (
            f"one-byte destination poison did not stick: got {dst_before.hex()}, "
            f"expected {ONE_BYTE_DST_POISON.hex()}"
        )
        # The poison differs from the source byte in every lane, so the
        # post-copy compare below cannot be satisfied by an unchanged word.
        assert ONE_BYTE_DST_POISON[0] != ONE_BYTE_SRC_WORD[0], (
            "one-byte poison equals the source byte; the copy would be invisible"
        )

        base_reads, base_writes = self.watch.snapshot()
        baseline_done = await self.csr_read("DMA_DONE_0_BASELINE_ONE_BYTE", DMA_CTRL_DONE_0)
        await self._program_dma(
            tag="_ONE_BYTE", src=ONE_BYTE_SRC_ADDR, dst=ONE_BYTE_DST_ADDR, length=1
        )
        start_id = await self.csr_read("DMA_NEXT_ID_0_START_ONE_BYTE", DMA_CTRL_NEXT_ID_0)
        done_id = await self._wait_done(baseline_done)
        assert done_id == start_id, (
            f"one-byte transfer completed id {done_id}, but this leg launched id {start_id}"
        )

        actual = await self._read_bytes(ONE_BYTE_DST_ADDR, len(ONE_BYTE_DST_EXPECTED))
        assert actual == ONE_BYTE_DST_EXPECTED, (
            f"LENGTH=1 transfer wrote {actual.hex()}, expected "
            f"{ONE_BYTE_DST_EXPECTED.hex()}: byte 0 must carry the source byte "
            f"{ONE_BYTE_SRC_WORD[0]:#04x} and bytes 1-7 must still carry the "
            f"poison {ONE_BYTE_DST_POISON[1]:#04x}"
        )
        reads, writes = self.watch.snapshot()
        src_reads = _delta(reads, base_reads, ONE_BYTE_SRC_ADDR)
        dst_reads = _delta(reads, base_reads, ONE_BYTE_DST_ADDR)
        dst_writes = _delta(writes, base_writes, ONE_BYTE_DST_ADDR)
        assert dst_writes == 1, (
            f"the LENGTH=1 transfer addressed {ONE_BYTE_DST_ADDR:#x} with "
            f"{dst_writes} write transaction(s) on the output responder, "
            f"expected exactly one"
        )
        assert src_reads == 1, (
            f"the LENGTH=1 transfer addressed its source {ONE_BYTE_SRC_ADDR:#x} "
            f"with {src_reads} read transaction(s) on the output responder, "
            f"expected exactly one"
        )
        assert dst_reads == 1, (
            f"the LENGTH=1 verification read addressed {ONE_BYTE_DST_ADDR:#x} "
            f"with {dst_reads} read transaction(s) on the output responder, "
            f"expected exactly one"
        )
        self.one_byte_dst = int.from_bytes(actual, "little")
        self.watch.stop = True
        await RisingEdge(cocotb.top.clk_smc_i)
        await self.watcher
        cocotb.log.info(
            "CHK-DMA-OUTPUT-FABRIC-TRAFFIC: all three transfers addressed the SYS_OUT responder "
            "exactly once per leg and direction (%#x read, %#x written and read back; %#x read "
            "and %#x written as one 4-beat burst each and read back; %#x read, "
            "%#x written and read back) while %d unrelated read transaction(s) from other "
            "masters completed on the same responder",
            DMA_SRC_ADDR,
            DMA_DST_ADDR,
            BLOCK_SRC_ADDR,
            BLOCK_DST_ADDR,
            ONE_BYTE_SRC_ADDR,
            ONE_BYTE_DST_ADDR,
            self.watch.foreign_reads(
                (
                    DMA_SRC_ADDR,
                    DMA_DST_ADDR,
                    BLOCK_SRC_ADDR,
                    BLOCK_DST_ADDR,
                    ONE_BYTE_SRC_ADDR,
                    ONE_BYTE_DST_ADDR,
                )
            ),
        )
