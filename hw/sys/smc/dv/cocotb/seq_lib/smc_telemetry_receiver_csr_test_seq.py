# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""U4-6: TELEMETRY CSR + INTR_TEST IRQ + ATB message into receiver 0.

ATB framing mirrors hw/comp/telemetry_receiver/tb_vcs/test_telemetry_receiver.py
(8 beats/packet, last_packet bit63, probe_id in [60:56]).
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge

from .smc_addr_map import TELEMETRY_CG_EN, smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq

TELEMETRY_READS = [
    (
        "TELEMETRY_RECEIVER_0",
        smc_indexed_addr(
            "SMC_TOP_SMC_TELEMETRY_RECEIVER_WRAP_TELEMETRY_RECEIVER_CTRL_BASE_ADDR", 0
        ),
        0x0,
    ),
    (
        "TELEMETRY_RECEIVER_1",
        smc_indexed_addr(
            "SMC_TOP_SMC_TELEMETRY_RECEIVER_WRAP_TELEMETRY_RECEIVER_CTRL_BASE_ADDR", 1
        ),
        0x0,
    ),
    (
        "TELEMETRY_RECEIVER_2",
        smc_indexed_addr(
            "SMC_TOP_SMC_TELEMETRY_RECEIVER_WRAP_TELEMETRY_RECEIVER_CTRL_BASE_ADDR", 2
        ),
        0x0,
    ),
]

_TELEMETRY_0_CTRL = smc_indexed_addr(
    "SMC_TOP_SMC_TELEMETRY_RECEIVER_WRAP_TELEMETRY_RECEIVER_CTRL_BASE_ADDR", 0
)
_TELEMETRY_0_STATUS = smc_indexed_addr(
    "SMC_TOP_SMC_TELEMETRY_RECEIVER_WRAP_TELEMETRY_RECEIVER_STATUS_BASE_ADDR", 0
)
_TELEMETRY_0_INTR_STATUS = smc_indexed_addr(
    "SMC_TOP_SMC_TELEMETRY_RECEIVER_WRAP_TELEMETRY_RECEIVER_INTR_STATUS_BASE_ADDR", 0
)
_TELEMETRY_0_INTR_ENABLE = smc_indexed_addr(
    "SMC_TOP_SMC_TELEMETRY_RECEIVER_WRAP_TELEMETRY_RECEIVER_INTR_ENABLE_BASE_ADDR", 0
)
_TELEMETRY_0_INTR_TEST = smc_indexed_addr(
    "SMC_TOP_SMC_TELEMETRY_RECEIVER_WRAP_TELEMETRY_RECEIVER_INTR_TEST_BASE_ADDR", 0
)
_TELEMETRY_0_PROBE_ID = smc_indexed_addr(
    "SMC_TOP_SMC_TELEMETRY_RECEIVER_WRAP_TELEMETRY_RECEIVER_TELEMETRY_PROBE_ID_BASE_ADDR",
    0,
)
_STATUS_EMPTY = 0x1
_INTR_MISSING_LAST = 0x1
_CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")
_TELEMETRY_CG_EN = TELEMETRY_CG_EN
_NUM_BEATS_PER_PACKET = 8
_PROBE_ID = 0x05
_COUNTERS = [0x11223344, 0x55667788]


async def _atb_write_beat(dut, value: int) -> None:
    dut.tb_telemetry0_atdata.value = value & 0xFF
    dut.tb_telemetry0_atid.value = 0
    dut.tb_telemetry0_atvalid.value = 1
    await RisingEdge(dut.clk_smc_i)
    for _ in range(64):
        if int(dut.tb_telemetry0_atready.value):
            break
        await RisingEdge(dut.clk_smc_i)
    dut.tb_telemetry0_atvalid.value = 0


async def _send_telemetry_packet(dut, packet_data: int) -> None:
    for i in range(_NUM_BEATS_PER_PACKET):
        await _atb_write_beat(dut, (packet_data >> (i * 8)) & 0xFF)


async def _send_telemetry_message(dut, probe_id: int, counter_values: list[int]) -> None:
    """Send a complete last-flagged message (all counter bytes marked valid)."""
    counter_bytes: list[int] = []
    for counter_value in counter_values:
        for i in range(4):
            counter_bytes.append((counter_value >> ((3 - i) * 8)) & 0xFF)

    packet_data = 0
    packet_data |= (probe_id & 0x1F) << 56
    bit_index = 45

    for i, counter_byte in enumerate(counter_bytes):
        packet_data |= (counter_byte & 0xFF) << bit_index
        packet_data |= 1 << (bit_index + 8)  # valid bit
        if i == len(counter_bytes) - 1:
            packet_data |= 1 << 63  # last packet
            await _send_telemetry_packet(dut, packet_data)
        elif bit_index == 0:
            await _send_telemetry_packet(dut, packet_data)
            packet_data = 0
            bit_index = 54
        else:
            bit_index -= 9


class smc_telemetry_receiver_csr_test_seq(SmcCsrSeq):
    def __init__(self, name: str = "smc_telemetry_receiver_csr_test_seq") -> None:
        super().__init__(name)
        self.telemetry_irq_ok: bool = False
        self.telemetry_atb_ok: bool = False

    async def body(self) -> None:
        dut = cocotb.top
        for name, addr, expected in TELEMETRY_READS:
            await self.csr_read(name, addr, expected=expected)

        status = await self.csr_read("TELEMETRY_0_STATUS", _TELEMETRY_0_STATUS)
        assert status & _STATUS_EMPTY, (
            f"TELEMETRY_0 STATUS.EMPTY expected at reset, got 0x{status:08x}"
        )
        intr_st = await self.csr_read("TELEMETRY_0_INTR_STATUS", _TELEMETRY_0_INTR_STATUS)
        assert intr_st == 0, f"TELEMETRY_0 INTR_STATUS not quiet at reset: 0x{intr_st:08x}"

        cg = await self.csr_read("CLOCK_GATE_CONTROL", _CLOCK_GATE_CONTROL)
        await self.csr_write(
            "CLOCK_GATE_CONTROL_TELEMETRY_UNGATE",
            _CLOCK_GATE_CONTROL,
            cg & ~_TELEMETRY_CG_EN,
        )
        await ClockCycles(dut.clk_smc_i, 8)

        # --- U4-6a: INTR_TEST -> tb_telemetry_irq_any
        irq_before = int(dut.tb_telemetry_irq_any.value)
        await self.csr_write(
            "TELEMETRY_0_INTR_ENABLE", _TELEMETRY_0_INTR_ENABLE, _INTR_MISSING_LAST
        )
        await self.csr_write("TELEMETRY_0_INTR_TEST", _TELEMETRY_0_INTR_TEST, _INTR_MISSING_LAST)
        await ClockCycles(dut.clk_smc_i, 8)
        irq_after = int(dut.tb_telemetry_irq_any.value)
        intr_st = await self.csr_read("TELEMETRY_0_INTR_STATUS_POST", _TELEMETRY_0_INTR_STATUS)
        assert irq_after == 1, (
            f"tb_telemetry_irq_any not asserted after INTR_TEST "
            f"(before={irq_before} after={irq_after} INTR_STATUS=0x{intr_st:08x})"
        )
        await self.csr_write(
            "TELEMETRY_0_INTR_STATUS_W1C",
            _TELEMETRY_0_INTR_STATUS,
            _INTR_MISSING_LAST,
        )
        await self.csr_write("TELEMETRY_0_INTR_ENABLE_OFF", _TELEMETRY_0_INTR_ENABLE, 0)
        await ClockCycles(dut.clk_smc_i, 8)
        assert int(dut.tb_telemetry_irq_any.value) == 0, (
            "tb_telemetry_irq_any stuck high after clear"
        )
        self.telemetry_irq_ok = True

        # --- U4-6b: ATB message -> STATUS.~EMPTY + PROBE_ID
        assert hasattr(dut, "tb_telemetry0_atvalid"), (
            "tb_telemetry0_* ports missing; rebuild after ATB pad lift"
        )
        await _send_telemetry_message(dut, _PROBE_ID, _COUNTERS)
        await ClockCycles(dut.clk_smc_i, 16)
        status = 0
        for _ in range(200):
            status = await self.csr_read("TELEMETRY_0_STATUS_ATB", _TELEMETRY_0_STATUS)
            if not (status & _STATUS_EMPTY):
                break
            await ClockCycles(dut.clk_smc_i, 1)
        else:
            raise AssertionError(
                f"TELEMETRY_0 buffer stayed EMPTY after ATB message (STATUS=0x{status:08x})"
            )
        probe = await self.csr_read("TELEMETRY_0_PROBE_ID", _TELEMETRY_0_PROBE_ID)
        assert (probe & 0x1F) == _PROBE_ID, (
            f"PROBE_ID mismatch: got 0x{probe:x}, expected 0x{_PROBE_ID:x}"
        )
        # Pop the message so the buffer is clean for later tests.
        await self.csr_write("TELEMETRY_0_BUFFER_POP", _TELEMETRY_0_CTRL, 0x1)
        await ClockCycles(dut.clk_smc_i, 4)

        await self.csr_write("CLOCK_GATE_CONTROL_RESTORE", _CLOCK_GATE_CONTROL, cg)
        self.telemetry_atb_ok = True
        cocotb.log.info(
            "Telemetry U4-6 PASS: INTR_TEST IRQ + ATB msg probe_id=0x%02X (STATUS was non-empty)",
            _PROBE_ID,
        )
