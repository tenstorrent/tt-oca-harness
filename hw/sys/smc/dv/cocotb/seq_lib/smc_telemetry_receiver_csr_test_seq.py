# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""U4-6: TELEMETRY CSR + INTR_TEST IRQ + ATB message into receiver 0.

ATB FRAMING PROVENANCE. The IP lives at ``hw/ip/telemetry_receiver/``; there is
no ``hw/comp/`` tree in this repository, so nothing here may cite one
([INDEPENDENT-EXPECTED-MODEL]).

The framing constants come from the DUT RTL, and this is stated rather than
implied:

* 8-bit beats and the assembly into packets -- ``doc/interface.adoc:59,69``
  ("8-bit data beats", "Data Width: 8 bits per beat") and
  ``doc/architecture.adoc:56``; ``NUM_BEATS_PER_PACKET`` is the RTL parameter
  (``rtl/telemetry_receiver.sv:134``).
* ``probe_id`` at bits ``[60:56]`` -- ``rtl/telemetry_receiver.sv:77-80``,
  ``get_telemetry_probe_id`` returns ``telemetry_packets[0][60:56]``.
* ``last_packet`` at bit 63 -- the ``telemetry_packet_t`` field used at
  ``rtl/telemetry_receiver.sv:137``.

The prose in ``doc/architecture.adoc:43-45,56-60`` describes probe IDs and
last-packet boundaries but gives no bit positions, so no spec-level source for
them exists in the tree. The framing is therefore a STIMULUS FORMAT taken from
the design, not an independently derived expectation; what this testcase scores
is the CSR-visible consequence (STATUS.EMPTY clearing, PROBE_ID reading back the
value that was framed), not the framing itself.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge

from .smc_csr_seq_utils import SmcCsrSeq

from .smc_addr_map import TELEMETRY_CG_EN, smc_addr, smc_indexed_addr

# Reset sweep across ALL THREE receivers, not just receiver 0's CTRL.
#
# On the ATB stimulus side only receiver 0 is driven -- `tb_top.sv:518` says
# "receiver 0 driven; 1/2 quiet". Quiet is NOT tied off: `smc_peripherals.sv:774`
# instantiates `telemetry_receiver_wrap` with `NUM_TELEMETRY_RECEIVERS`, so all
# three receivers have real register blocks behind real addresses. A CSR RESET
# read does not need ATB input, and receivers 1/2 being unstimulated is exactly
# what guarantees their registers are still at reset when they are read.
#
# All seven single-indexed register types are swept. `TELEMETRY_COUNTER` is
# excluded: its generated macro is DOUBLY indexed
# (`..._TELEMETRY_COUNTER_BASE_ADDR(receiver_idx, counter_idx)`,
# smc_addr.h:820) and `smc_indexed_addr` resolves a single index only --
# computing the second stride here would be inventing an address the helper
# cannot source from the map ([ADDRESS-FROM-AUTHORITATIVE-MAP]).
#
# `STATUS` carries the discrimination: its generated reset is 0x1 (EMPTY set),
# the one non-zero value in the group, so a dead or unmapped receiver window
# reading 0 fails on it rather than satisfying six zero compares.
_TELEMETRY_REG_TYPES = (
    ("CTRL", 0x0),
    ("STATUS", 0x1),
    ("INTR_ENABLE", 0x0),
    ("INTR_STATUS", 0x0),
    ("INTR_TEST", 0x0),
    ("TELEMETRY_PROBE_ID", 0x0),
    ("TELEMETRY_COUNTER_VLDS", 0x0),
)
_TELEMETRY_RECEIVERS = 3

TELEMETRY_READS = [
    (
        f"TELEMETRY_RECEIVER_{_rx}_{_rt}",
        smc_indexed_addr(
            "SMC_TOP_SMC_TELEMETRY_RECEIVER_WRAP_TELEMETRY_RECEIVER_"
            f"{_rt}_BASE_ADDR",
            _rx,
        ),
        _reset,
    )
    for _rx in range(_TELEMETRY_RECEIVERS)
    for _rt, _reset in _TELEMETRY_REG_TYPES
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
_CLOCK_GATE_CONTROL = smc_addr(
    "SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR"
)
_TELEMETRY_CG_EN = TELEMETRY_CG_EN
_NUM_BEATS_PER_PACKET = 8
_PROBE_ID = 0x05
_COUNTERS = [0x11223344, 0x55667788]


_ATB_READY_BOUND = 64


async def _atb_write_beat(dut, value: int, *, beat: int = -1) -> None:
    """Drive one ATB beat and REQUIRE the handshake to complete.

    Expiry is a failure. A bounded wait that deasserts `atvalid` and returns
    regardless after 64 cycles without `atready` lets a dropped beat produce a
    PARTIAL frame, which can still clear STATUS.EMPTY and still match PROBE_ID,
    so the testcase would score a truncated message as a good one
    ([TIMEOUT-MUST-FAIL]).
    """
    dut.tb_telemetry0_atdata.value = value & 0xFF
    dut.tb_telemetry0_atid.value = 0
    dut.tb_telemetry0_atvalid.value = 1
    await RisingEdge(dut.clk_smc_i)
    accepted = False
    for _ in range(_ATB_READY_BOUND):
        if int(dut.tb_telemetry0_atready.value):
            accepted = True
            break
        await RisingEdge(dut.clk_smc_i)
    dut.tb_telemetry0_atvalid.value = 0
    if not accepted:
        raise AssertionError(
            f"ATB beat {beat} (data=0x{value & 0xFF:02x}) was never accepted: "
            f"tb_telemetry0_atready stayed low for {_ATB_READY_BOUND} "
            f"clk_smc_i cycles. Continuing would send a truncated frame, which "
            f"can still clear STATUS.EMPTY and still match PROBE_ID."
        )


async def _send_telemetry_packet(dut, packet_data: int) -> None:
    for i in range(_NUM_BEATS_PER_PACKET):
        await _atb_write_beat(dut, (packet_data >> (i * 8)) & 0xFF, beat=i)


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
        intr_st = await self.csr_read(
            "TELEMETRY_0_INTR_STATUS", _TELEMETRY_0_INTR_STATUS
        )
        assert intr_st == 0, (
            f"TELEMETRY_0 INTR_STATUS not quiet at reset: 0x{intr_st:08x}"
        )

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
        await self.csr_write(
            "TELEMETRY_0_INTR_TEST", _TELEMETRY_0_INTR_TEST, _INTR_MISSING_LAST
        )
        await ClockCycles(dut.clk_smc_i, 8)
        irq_after = int(dut.tb_telemetry_irq_any.value)
        intr_st = await self.csr_read(
            "TELEMETRY_0_INTR_STATUS_POST", _TELEMETRY_0_INTR_STATUS
        )
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
                f"TELEMETRY_0 buffer stayed EMPTY after ATB message "
                f"(STATUS=0x{status:08x})"
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
            "Telemetry U4-6 PASS: INTR_TEST IRQ + ATB msg probe_id=0x%02X "
            "(STATUS was non-empty)",
            _PROBE_ID,
        )
