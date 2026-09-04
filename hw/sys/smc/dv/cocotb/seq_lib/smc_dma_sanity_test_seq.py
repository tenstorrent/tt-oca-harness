# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DMA source-to-destination payload check through the output-fabric responder."""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles
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


class smc_dma_sanity_test_seq(SmcCsrSeq):
    """Program DMA and verify that output-fabric destination bytes match source."""

    def __init__(self, name: str = "smc_dma_sanity_test_seq") -> None:
        super().__init__(name)
        self.checked_bytes = 0
        self.model_checks = 0
        self.start_id = 0
        self.done_id = 0

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
        item.length = len(data)
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
        item.length = length
        item.check_golden = check_golden
        item.memory_region = DMA_MODEL_REGION
        await _OneShot(item, f"{item_name}_os").start(self.env.jtag_axi_agent.sequencer)
        return item.rdata.to_bytes(length, "little")

    async def _program_dma(self) -> None:
        await self.csr_write("DMA_CONFIG", DMA_CTRL_CONFIG, DMA_CONFIG_ENABLED_ND)
        await self.csr_write(
            "DMA_DST_ADDRESS_LO", DMA_CTRL_DST_ADDRESS_LO, DMA_DST_ADDR & 0xFFFF_FFFF
        )
        await self.csr_write("DMA_DST_ADDRESS_HI", DMA_CTRL_DST_ADDRESS_HI, DMA_DST_ADDR >> 32)
        await self.csr_write(
            "DMA_SRC_ADDRESS_LO", DMA_CTRL_SRC_ADDRESS_LO, DMA_SRC_ADDR & 0xFFFF_FFFF
        )
        await self.csr_write("DMA_SRC_ADDRESS_HI", DMA_CTRL_SRC_ADDRESS_HI, DMA_SRC_ADDR >> 32)
        await self.csr_write("DMA_LENGTH_LO", DMA_CTRL_LENGTH_LO, len(DMA_PAYLOAD))
        await self.csr_write("DMA_LENGTH_HI", DMA_CTRL_LENGTH_HI, 0)
        await self.csr_write("DMA_DST_STRIDE_LO", DMA_CTRL_DST_STRIDE_LO, 0)
        await self.csr_write("DMA_DST_STRIDE_HI", DMA_CTRL_DST_STRIDE_HI, 0)
        await self.csr_write("DMA_SRC_STRIDE_LO", DMA_CTRL_SRC_STRIDE_LO, 0)
        await self.csr_write("DMA_SRC_STRIDE_HI", DMA_CTRL_SRC_STRIDE_HI, 0)
        await self.csr_write("DMA_NUM_REPETITIONS_LO", DMA_CTRL_NUM_REPETITIONS_LO, 1)
        await self.csr_write("DMA_NUM_REPETITIONS_HI", DMA_CTRL_NUM_REPETITIONS_HI, 0)

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
        start_writes = int(cocotb.top.tb_output_axi_write_count.value)
        start_reads = int(cocotb.top.tb_output_axi_read_count.value)

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
        write_count = int(cocotb.top.tb_output_axi_write_count.value)
        read_count = int(cocotb.top.tb_output_axi_read_count.value)
        # Exact, because every access after the baseline above is accounted for:
        # the DMA contributes one destination write and one source read, and this
        # sequence contributes the single post-copy verification read.
        assert write_count == start_writes + 1, (
            f"DMA write did not reach the output responder: B responses went "
            f"{start_writes} -> {write_count}, expected exactly one more"
        )
        assert read_count == start_reads + 2, (
            f"DMA read did not reach the output responder: R beats went "
            f"{start_reads} -> {read_count}, expected exactly two more (DMA source "
            f"read + this sequence's post-copy read)"
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
