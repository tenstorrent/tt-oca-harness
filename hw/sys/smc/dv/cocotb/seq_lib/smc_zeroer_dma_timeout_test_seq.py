# SPDX-License-Identifier: Apache-2.0
"""Zeroer datapath payload check through the output-fabric responder."""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles

from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from ._one_shot import _OneShot
from .smc_csr_seq_utils import SmcCsrSeq

ZEROER_DEST_ADDR = 0xC003_8200
ZEROER_SIZE = 0xC003_8208
ZEROER_CTRL_STATUS = 0xC003_8210

INBOUND0_FILTER_CONFIG = 0xC001_5000
INBOUND0_START = 0xC001_5008
INBOUND0_END = 0xC001_5010
OUTBOUND0_FILTER_CONFIG = 0xC001_6000
OUTBOUND0_START = 0xC001_6008
OUTBOUND0_END = 0xC001_6010
PASS_ALL_CONFIG = 0x0100_3013

OUTPUT_FABRIC_ADDR = 0x0200_0000
OUTPUT_FABRIC_MODEL_REGION = "zeroer_output_fabric"
OUTPUT_FABRIC_MODEL_SIZE = 0x1000
ZEROER_POISON = bytes.fromhex("a0a1a2a3a4a5a6a7")
ZEROER_EXPECTED = bytes(len(ZEROER_POISON))
ZEROER_WAIT_CYCLES = 200


class smc_zeroer_dma_timeout_test_seq(SmcCsrSeq):
    """Program zeroer and verify that output-fabric bytes are actually cleared."""

    def __init__(self, name: str = "smc_zeroer_dma_timeout_test_seq") -> None:
        super().__init__(name)
        self.checked_bytes = 0
        self.model_checks = 0

    def _ensure_model_region(self) -> None:
        if OUTPUT_FABRIC_MODEL_REGION not in self.memory_model.regions:
            self.memory_model.add_region(
                OUTPUT_FABRIC_MODEL_REGION,
                OUTPUT_FABRIC_ADDR,
                OUTPUT_FABRIC_MODEL_SIZE,
            )

    async def _program_output_fabric_pass_all(self) -> None:
        await self.csr_write("INBOUND0_START_PASS_ALL", INBOUND0_START, 0x0, length=8)
        await self.csr_write("INBOUND0_END_PASS_ALL", INBOUND0_END,
                             0x00FF_FFFF_FFFF_FFFF, length=8)
        await self.csr_write("INBOUND0_FILTER_CONFIG_PASS_ALL", INBOUND0_FILTER_CONFIG,
                             PASS_ALL_CONFIG, length=8)
        await self.csr_write("OUTBOUND0_START_PASS_ALL", OUTBOUND0_START, 0x0, length=8)
        await self.csr_write("OUTBOUND0_END_PASS_ALL", OUTBOUND0_END,
                             0x00FF_FFFF_FFFF_FFFF, length=8)
        await self.csr_write("OUTBOUND0_FILTER_CONFIG_PASS_ALL", OUTBOUND0_FILTER_CONFIG,
                             PASS_ALL_CONFIG, length=8)

    async def _write_bytes(self, addr: int, data: bytes) -> None:
        assert self.env is not None, "sequence env is not initialized"
        item_name = f"jtag_output_preload_0x{addr:x}"
        item = SmcSysAxiItem(item_name)
        item.op = SmcSysAxiOp.WRITE
        item.addr = addr
        item.length = len(data)
        item.wdata = int.from_bytes(data, "little")
        await _OneShot(item, f"{item_name}_os").start(self.env.jtag_axi_agent.sequencer)

    async def _read_bytes(self, addr: int, length: int) -> bytes:
        assert self.env is not None, "sequence env is not initialized"
        item_name = f"jtag_output_readback_0x{addr:x}"
        item = SmcSysAxiItem(item_name)
        item.op = SmcSysAxiOp.READ
        item.addr = addr
        item.length = length
        await _OneShot(item, f"{item_name}_os").start(self.env.jtag_axi_agent.sequencer)
        return item.rdata.to_bytes(length, "little")

    async def _wait_for_zeroer_write(self, expected_count: int) -> None:
        for _ in range(ZEROER_WAIT_CYCLES):
            write_count = int(cocotb.top.tb_output_axi_write_count.value)
            if write_count >= expected_count:
                return
            await ClockCycles(cocotb.top.clk_smc_i, 1)
        raise AssertionError(
            f"zeroer write count did not reach {expected_count}, "
            f"got {int(cocotb.top.tb_output_axi_write_count.value)}"
        )

    async def body(self) -> None:
        self._ensure_model_region()
        await self._program_output_fabric_pass_all()

        start_writes = int(cocotb.top.tb_output_axi_write_count.value)
        self.memory_model.write(OUTPUT_FABRIC_ADDR, ZEROER_POISON,
                                region=OUTPUT_FABRIC_MODEL_REGION)
        await self._write_bytes(OUTPUT_FABRIC_ADDR, ZEROER_POISON)
        assert await self._read_bytes(OUTPUT_FABRIC_ADDR, len(ZEROER_POISON)) == ZEROER_POISON

        await self.csr_write("ZEROER_DEST_ADDR", ZEROER_DEST_ADDR, OUTPUT_FABRIC_ADDR, length=8)
        await self.csr_write("ZEROER_SIZE", ZEROER_SIZE, len(ZEROER_POISON), length=8)

        # The zeroer FSM starts on the INT_EN field write side effect.
        await self.csr_write("ZEROER_CTRL_STATUS_START", ZEROER_CTRL_STATUS, 0x1, length=8)
        await self._wait_for_zeroer_write(start_writes + 2)

        self.memory_model.write(OUTPUT_FABRIC_ADDR, ZEROER_EXPECTED,
                                region=OUTPUT_FABRIC_MODEL_REGION)
        actual = await self._read_bytes(OUTPUT_FABRIC_ADDR, len(ZEROER_EXPECTED))
        assert actual == ZEROER_EXPECTED, (
            f"zeroer did not clear payload: got {actual.hex()}, expected {ZEROER_EXPECTED.hex()}"
        )
        write_count = int(cocotb.top.tb_output_axi_write_count.value)
        assert write_count >= start_writes + 2, "zeroer write did not reach output responder"
        self.memory_model.expect(OUTPUT_FABRIC_ADDR, ZEROER_EXPECTED,
                                 region=OUTPUT_FABRIC_MODEL_REGION)
        self.checked_bytes = len(ZEROER_EXPECTED)
        self.model_checks = 1
