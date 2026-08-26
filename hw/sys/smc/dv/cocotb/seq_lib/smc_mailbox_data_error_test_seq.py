# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Mailbox data path and error-response depth test over real SEP_IN AXI."""

from __future__ import annotations

from .smc_addr_map import smc_addr
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_base_test_seq import smc_base_test_seq

AXI_RESP_OKAY = 0
AXI_RESP_SLVERR = 2

CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")  # base_config offset 0x18 (was 0x30 before HANG_DET_* added)
MAILBOX_CG_EN = 1 << 1

OUTBOUND_WRITE_DATA = smc_addr("SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_BASE_ADDR")
OUTBOUND_READ_DATA = smc_addr("SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_BASE_ADDR") + 0x8
OUTBOUND_STATUS = smc_addr("SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_BASE_ADDR") + 0x10
OUTBOUND_ERROR_FLAGS = smc_addr("SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_BASE_ADDR") + 0x18

INBOUND_WRITE_DATA = smc_addr("SMC_TOP_SMC_MAILBOX_INBOUND_MAILBOX_0_BASE_ADDR")
INBOUND_READ_DATA = smc_addr("SMC_TOP_SMC_MAILBOX_INBOUND_MAILBOX_0_BASE_ADDR") + 0x8
INBOUND_STATUS = smc_addr("SMC_TOP_SMC_MAILBOX_INBOUND_MAILBOX_0_BASE_ADDR") + 0x10
INBOUND_ERROR_FLAGS = smc_addr("SMC_TOP_SMC_MAILBOX_INBOUND_MAILBOX_0_BASE_ADDR") + 0x18

MAILBOX_OUTBOUND_MODEL_REGION = "mailbox_outbound_to_inbound"
MAILBOX_INBOUND_MODEL_REGION = "mailbox_inbound_to_outbound"
MAILBOX_OUTBOUND_MODEL_BASE = 0x1000_0000
MAILBOX_INBOUND_MODEL_BASE = 0x1000_1000
MAILBOX_MODEL_SIZE = 0x100


class smc_mailbox_data_error_test_seq(smc_base_test_seq):
    """Exercise mailbox write/read data flow and illegal access responses."""

    def __init__(self, name: str = "smc_mailbox_data_error_test_seq") -> None:
        super().__init__(name)
        self.accesses = 0
        self.clock_gate_value: int = 0

    def _ensure_model_regions(self) -> None:
        for name, base in (
            (MAILBOX_OUTBOUND_MODEL_REGION, MAILBOX_OUTBOUND_MODEL_BASE),
            (MAILBOX_INBOUND_MODEL_REGION, MAILBOX_INBOUND_MODEL_BASE),
        ):
            if name not in self.memory_model.regions:
                self.memory_model.add_region(name, base, MAILBOX_MODEL_SIZE)

    def _model_write(self, region: str, base: int, slot: int, data: int) -> None:
        self.memory_model.write_int(base + slot * 8, data, length=8, region=region)

    def _model_expect(self, region: str, base: int, slot: int, expected: int) -> None:
        self.memory_model.expect_int(base + slot * 8, expected, length=8, region=region)

    async def _read(self, name: str, addr: int, expected: int | None = None,
                    expected_resp: int = AXI_RESP_OKAY,
                    allow_error: bool = False) -> int:
        item = SmcSysAxiItem(f"rd_{name}")
        item.op = SmcSysAxiOp.READ
        item.addr = addr
        item.length = 8
        item.expected = expected
        item.expected_resp = expected_resp
        item.allow_error = allow_error
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        return item.rdata

    async def _write(self, name: str, addr: int, data: int,
                     expected_resp: int = AXI_RESP_OKAY,
                     allow_error: bool = False) -> None:
        item = SmcSysAxiItem(f"wr_{name}")
        item.op = SmcSysAxiOp.WRITE
        item.addr = addr
        item.length = 8
        item.wdata = data
        item.expected_resp = expected_resp
        item.allow_error = allow_error
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1

    async def _enable_mailbox_clock(self) -> None:
        self.clock_gate_value = await self._read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        enabled = self.clock_gate_value | MAILBOX_CG_EN
        await self._write("CLOCK_GATE_CONTROL_ENABLE_MAILBOX", CLOCK_GATE_CONTROL, enabled)
        await self._read("CLOCK_GATE_CONTROL_ENABLED", CLOCK_GATE_CONTROL, expected=enabled)

    async def _restore_mailbox_clock(self) -> None:
        await self._write("CLOCK_GATE_CONTROL_RESTORE", CLOCK_GATE_CONTROL,
                          self.clock_gate_value)
        await self._read("CLOCK_GATE_CONTROL_RESTORED", CLOCK_GATE_CONTROL,
                         expected=self.clock_gate_value)

    async def body(self) -> None:
        self._ensure_model_regions()
        await self._enable_mailbox_clock()

        await self._read("OUTBOUND_STATUS_BASE", OUTBOUND_STATUS)
        await self._read("INBOUND_STATUS_BASE", INBOUND_STATUS)
        await self._read("OUTBOUND_ERROR_FLAGS_BASE", OUTBOUND_ERROR_FLAGS)
        await self._read("INBOUND_ERROR_FLAGS_BASE", INBOUND_ERROR_FLAGS)

        # Writes to READ_DATA are illegal valid-address operations.
        await self._write("OUTBOUND_READ_DATA_ILLEGAL", OUTBOUND_READ_DATA, 0xBAD0_BAD0_0000_0001,
                          expected_resp=AXI_RESP_SLVERR, allow_error=True)
        await self._write("INBOUND_READ_DATA_ILLEGAL", INBOUND_READ_DATA, 0xBAD0_BAD0_0000_0002,
                          expected_resp=AXI_RESP_SLVERR, allow_error=True)

        # Outbound write-data is consumed from the paired inbound read-data port.
        await self._write("OUTBOUND_WRITE_DATA_0", OUTBOUND_WRITE_DATA, 0x1111_2222_3333_4444)
        self._model_write(
            MAILBOX_OUTBOUND_MODEL_REGION,
            MAILBOX_OUTBOUND_MODEL_BASE,
            0,
            0x1111_2222_3333_4444,
        )
        await self._write("OUTBOUND_WRITE_DATA_1", OUTBOUND_WRITE_DATA, 0x5555_6666_7777_8888)
        self._model_write(
            MAILBOX_OUTBOUND_MODEL_REGION,
            MAILBOX_OUTBOUND_MODEL_BASE,
            1,
            0x5555_6666_7777_8888,
        )
        await self._write("OUTBOUND_WRITE_DATA_FULL", OUTBOUND_WRITE_DATA, 0x9999_AAAA_BBBB_CCCC,
                          expected_resp=AXI_RESP_SLVERR, allow_error=True)
        await self._read("INBOUND_READ_DATA_0", INBOUND_READ_DATA, expected=0x1111_2222_3333_4444)
        self._model_expect(
            MAILBOX_OUTBOUND_MODEL_REGION,
            MAILBOX_OUTBOUND_MODEL_BASE,
            0,
            0x1111_2222_3333_4444,
        )
        await self._read("INBOUND_READ_DATA_1", INBOUND_READ_DATA, expected=0x5555_6666_7777_8888)
        self._model_expect(
            MAILBOX_OUTBOUND_MODEL_REGION,
            MAILBOX_OUTBOUND_MODEL_BASE,
            1,
            0x5555_6666_7777_8888,
        )
        await self._read("INBOUND_READ_DATA_EMPTY", INBOUND_READ_DATA,
                         expected_resp=AXI_RESP_SLVERR, allow_error=True)

        # Inbound write-data is consumed from the paired outbound read-data port.
        await self._write("INBOUND_WRITE_DATA_0", INBOUND_WRITE_DATA, 0xAAAA_BBBB_CCCC_DDDD)
        self._model_write(
            MAILBOX_INBOUND_MODEL_REGION,
            MAILBOX_INBOUND_MODEL_BASE,
            0,
            0xAAAA_BBBB_CCCC_DDDD,
        )
        await self._read("OUTBOUND_READ_DATA_0", OUTBOUND_READ_DATA, expected=0xAAAA_BBBB_CCCC_DDDD)
        self._model_expect(
            MAILBOX_INBOUND_MODEL_REGION,
            MAILBOX_INBOUND_MODEL_BASE,
            0,
            0xAAAA_BBBB_CCCC_DDDD,
        )
        await self._read("OUTBOUND_READ_DATA_EMPTY", OUTBOUND_READ_DATA,
                         expected_resp=AXI_RESP_SLVERR, allow_error=True)

        await self._read("OUTBOUND_STATUS_FINAL", OUTBOUND_STATUS)
        await self._read("INBOUND_STATUS_FINAL", INBOUND_STATUS)

        await self._restore_mailbox_clock()
        assert self.accesses == 22, "expected mailbox data/error access sequence"
