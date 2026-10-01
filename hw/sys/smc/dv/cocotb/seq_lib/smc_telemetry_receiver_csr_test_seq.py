# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""U4-6: TELEMETRY CSR + INTR_TEST IRQ + a framed ATB message per receiver.

ATB FRAMING PROVENANCE. The IP lives at ``hw/ip/telemetry_receiver/``; the
framing this sequence drives is a DV-owned table (the ``_ATB_*`` constants
below) and each entry names its source:

* 8-bit beats assembled LSB-first into 64-bit packets -- ``doc/interface.adoc``
  (``ATB_DATA_WIDTH`` 8, ``PACKET_WIDTH`` 64, "8-bit data beats") and
  ``doc/architecture.adoc`` ("assembles streams of 8-bit ATB data into 64-bit
  packets ... little-endian (LSB-first) byte alignment"). Beats per packet is
  the quotient of the two documented widths.
* 9-bit blocks, each an 8-bit counter byte plus its valid flag --
  ``doc/architecture.adoc`` ("validates each 9-bit packet block"; "broken into
  9-bit blocks, counters are extracted and checked, and validity flags
  assigned").
* a 5-bit probe-ID header and a last-packet flag --
  ``regs/telemetry_receiver.rdl`` (``TELEMETRY_PROBE_ID.PROBE_ID[4:0]``, "the
  Probe ID field of the telemetry message"; ``INTR_STATUS.MISSING_LAST``, "has
  not received a Last Packet flag") and ``doc/architecture.adoc`` ("parsed for
  headers (probe ID)", "detects last-packet boundaries").
* the bit positions of the probe-ID header, of the last-packet flag and of the
  first block in each packet -- no document in the tree fixes them, so their
  values are not derived from any document: they are the layout this bench
  drives and the receiver under test accepts (``_ATB_PROBE_ID_LSB``,
  ``_ATB_LAST_PACKET_BIT``, ``_ATB_FIRST_BLOCK_LSB``, ``_ATB_NEXT_BLOCK_LSB``),
  recorded as DV-owned assumptions until a document states the packet layout.

What this testcase scores is the CSR-visible consequence of a message framed
per that table (STATUS.EMPTY clearing, PROBE_ID reading back the value that was
framed), not that the table is the specified telemetry format: a receiver that
decoded a differently laid-out message would fail here without being wrong.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge

from .smc_addr_map import TELEMETRY_CG_EN, smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq

# Reset sweep across all three receivers.
#
# The reset reads run before any ATB stimulus, which is what guarantees every
# receiver's registers are still at reset when they are read. The generated
# address map carries indexed TELEMETRY_RECEIVER symbols for all three
# receivers, and the INTR_ENABLE write/readback leg below proves each register
# block is live.
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
# A reset sweep alone would leave receivers 1 and 2 at "mapped, and at reset",
# so each also takes a write/readback/restore on INTR_ENABLE before its own
# framed ATB message below. INTR_ENABLE's two writable fields are
# `MISSING_LAST[0]` and `BUFFER_THRESHOLD[4]` (telemetry_receiver.rdl:127-141),
# giving the pattern below. A window that decodes but does not store, or one
# that returns a bus default, fails the readback
# ([NEGATIVE-NEEDS-POSITIVE-CONTROL]).
_INTR_ENABLE_WRITABLE = 0x11
_QUIET_RECEIVERS = (1, 2)

TELEMETRY_READS = [
    (
        f"TELEMETRY_RECEIVER_{_rx}_{_rt}",
        smc_indexed_addr(
            f"SMC_TOP_SMC_TELEMETRY_RECEIVER_WRAP_TELEMETRY_RECEIVER_{_rt}_BASE_ADDR",
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
_CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")
_TELEMETRY_CG_EN = TELEMETRY_CG_EN
# DV-owned ATB framing table; the provenance of every entry is in the module
# docstring.
_ATB_BEAT_BITS = 8  # interface.adoc ATB_DATA_WIDTH
_ATB_PACKET_BITS = 64  # interface.adoc PACKET_WIDTH
_NUM_BEATS_PER_PACKET = _ATB_PACKET_BITS // _ATB_BEAT_BITS
_ATB_BLOCK_DATA_BITS = 8  # one counter byte per block (architecture.adoc)
_ATB_BLOCK_BITS = _ATB_BLOCK_DATA_BITS + 1  # plus its valid flag: "9-bit block"
_ATB_PROBE_ID_BITS = 5  # telemetry_receiver.rdl PROBE_ID[4:0]
# Positions no document fixes (DV-owned assumptions, see the module docstring).
_ATB_PROBE_ID_LSB = 56
_ATB_LAST_PACKET_BIT = 63
_ATB_FIRST_BLOCK_LSB = 45  # first block of the packet that carries the header
_ATB_NEXT_BLOCK_LSB = 54  # first block of every following packet
_PROBE_ID = 0x05
assert _PROBE_ID < (1 << _ATB_PROBE_ID_BITS)
_COUNTERS = [0x11223344, 0x55667788]

# Per-receiver ATB legs. Each receiver is framed with a probe ID of its own, so
# the PROBE_ID readback below cannot be satisfied by another receiver's message
# leaking into the wrong buffer, and with an ATB ID of its own, which is the
# only stimulus that distinguishes the three ATB sources at the pins.
_RX_ATB_LEGS = {
    0: {"probe_id": _PROBE_ID, "atid": 0x00, "counters": _COUNTERS},
    1: {"probe_id": 0x0A, "atid": 0x11, "counters": [0x9A8B7C6D, 0x0F1E2D3C]},
    2: {"probe_id": 0x13, "atid": 0x22, "counters": [0xDEADBEEF, 0xFEEDFACE]},
}
for _leg in _RX_ATB_LEGS.values():
    assert _leg["probe_id"] < (1 << _ATB_PROBE_ID_BITS)
assert len({_leg["atid"] for _leg in _RX_ATB_LEGS.values()}) == len(_RX_ATB_LEGS)
assert len({_leg["probe_id"] for _leg in _RX_ATB_LEGS.values()}) == len(_RX_ATB_LEGS)
# Bound on the assembled message reaching the message buffer.
_BUFFER_POLL_BOUND = 200


_ATB_READY_BOUND = 64
# Bound for the INTR_TEST-to-IRQ and IRQ-clear observations. No stated
# INTR_TEST-to-`telemetry_irq_any` latency exists in the IP documentation, so
# this is a generous ceiling on a bounded poll, not a settling delay: the poll
# returns on the level it is waiting for and raises with the last observed level
# on expiry, and the cycles it actually consumed are carried in the evidence
# token ([NO-BLIND-DELAY-SYNC]).
_IRQ_POLL_BOUND = 64


async def _await_irq_level(dut, want: int, label: str) -> int:
    """Poll tb_telemetry_irq_any for `want`; raise on expiry. Returns cycles."""
    last = int(dut.tb_telemetry_irq_any.value)
    if last == want:
        return 0
    for cyc in range(1, _IRQ_POLL_BOUND + 1):
        await RisingEdge(dut.clk_smc_i)
        last = int(dut.tb_telemetry_irq_any.value)
        if last == want:
            return cyc
    raise AssertionError(
        f"{label}: tb_telemetry_irq_any stayed {last} for {_IRQ_POLL_BOUND} "
        f"clk_smc_i cycles, want {want}"
    )


async def _atb_write_beat(dut, value: int, *, beat: int = -1, rx: int = 0, atid: int = 0) -> None:
    """Drive one ATB beat into receiver `rx` and REQUIRE the handshake.

    Expiry is a failure: a dropped beat produces a PARTIAL frame, which can
    still clear STATUS.EMPTY and still match PROBE_ID, so a truncated message
    would score as a good one ([TIMEOUT-MUST-FAIL]).
    """
    atdata = getattr(dut, f"tb_telemetry{rx}_atdata")
    atid_pin = getattr(dut, f"tb_telemetry{rx}_atid")
    atvalid = getattr(dut, f"tb_telemetry{rx}_atvalid")
    atready = getattr(dut, f"tb_telemetry{rx}_atready")
    atdata.value = value & 0xFF
    atid_pin.value = atid & 0x7F
    atvalid.value = 1
    await RisingEdge(dut.clk_smc_i)
    accepted = False
    for _ in range(_ATB_READY_BOUND):
        raw = atready.value
        if not raw.is_resolvable:
            raise AssertionError(f"tb_telemetry{rx}_atready is X/Z: {raw}")
        if int(raw):
            accepted = True
            break
        await RisingEdge(dut.clk_smc_i)
    atvalid.value = 0
    if not accepted:
        raise AssertionError(
            f"ATB beat {beat} (data=0x{value & 0xFF:02x}) into receiver {rx} was "
            f"never accepted: tb_telemetry{rx}_atready stayed low for "
            f"{_ATB_READY_BOUND} clk_smc_i cycles. Continuing would send a "
            f"truncated frame, which can still clear STATUS.EMPTY and still "
            f"match PROBE_ID."
        )


async def _send_telemetry_packet(dut, packet_data: int, *, rx: int = 0, atid: int = 0) -> None:
    beat_mask = (1 << _ATB_BEAT_BITS) - 1
    for i in range(_NUM_BEATS_PER_PACKET):
        await _atb_write_beat(
            dut, (packet_data >> (i * _ATB_BEAT_BITS)) & beat_mask, beat=i, rx=rx, atid=atid
        )


async def _send_telemetry_message(
    dut, probe_id: int, counter_values: list[int], *, rx: int = 0, atid: int = 0
) -> None:
    """Send a complete last-flagged message (all counter bytes marked valid)."""
    counter_bytes: list[int] = []
    for counter_value in counter_values:
        for i in range(4):
            counter_bytes.append((counter_value >> ((3 - i) * 8)) & 0xFF)

    packet_data = 0
    packet_data |= (probe_id & ((1 << _ATB_PROBE_ID_BITS) - 1)) << _ATB_PROBE_ID_LSB
    bit_index = _ATB_FIRST_BLOCK_LSB

    for i, counter_byte in enumerate(counter_bytes):
        packet_data |= (counter_byte & 0xFF) << bit_index
        packet_data |= 1 << (bit_index + _ATB_BLOCK_DATA_BITS)  # valid flag
        if i == len(counter_bytes) - 1:
            packet_data |= 1 << _ATB_LAST_PACKET_BIT
            await _send_telemetry_packet(dut, packet_data, rx=rx, atid=atid)
        elif bit_index == 0:
            await _send_telemetry_packet(dut, packet_data, rx=rx, atid=atid)
            packet_data = 0
            bit_index = _ATB_NEXT_BLOCK_LSB
        else:
            bit_index -= _ATB_BLOCK_BITS


class smc_telemetry_receiver_csr_test_seq(SmcCsrSeq):
    def __init__(self, name: str = "smc_telemetry_receiver_csr_test_seq") -> None:
        super().__init__(name)
        # Values the run measured, published for the testcase module's record.
        self.probe_id_readback: int | None = None
        self.status_non_empty: int | None = None
        self.irq_rise_cycles: int | None = None
        self.irq_fall_cycles: int | None = None
        self.quiet_receivers_proved: list[int] = []
        #: PROBE_ID read back per receiver after its own ATB message.
        self.rx_atb_probe_ids: dict[int, int] = {}
        #: STATUS word sampled per receiver while its buffer was non-empty.
        self.rx_atb_status: dict[int, int] = {}

    async def _atb_message_leg(self, dut, rx: int) -> None:
        """Frame one message into receiver `rx` and score its CSR consequence.

        Each receiver gets the same framing the receiver-0 leg drives, with a
        probe ID and an ATB ID of its own, so the claim for receivers 1 and 2
        is the same as for receiver 0 rather than stopping at "mapped, at
        reset, and stores INTR_ENABLE". The leg scores two CSR consequences: EMPTY clearing on THIS receiver
        and THIS receiver's PROBE_ID reading back the value framed into it. A
        wrap that routed the beats to the wrong receiver fails on the empty
        sample of the receiver it was told to fill, and a receiver that latched
        the neighbour's header fails on PROBE_ID.
        """
        leg = _RX_ATB_LEGS[rx]
        status_addr = smc_indexed_addr(
            "SMC_TOP_SMC_TELEMETRY_RECEIVER_WRAP_TELEMETRY_RECEIVER_STATUS_BASE_ADDR", rx
        )
        probe_addr = smc_indexed_addr(
            "SMC_TOP_SMC_TELEMETRY_RECEIVER_WRAP_TELEMETRY_RECEIVER_TELEMETRY_PROBE_ID_BASE_ADDR",
            rx,
        )
        ctrl_addr = smc_indexed_addr(
            "SMC_TOP_SMC_TELEMETRY_RECEIVER_WRAP_TELEMETRY_RECEIVER_CTRL_BASE_ADDR", rx
        )
        before = await self.csr_read(f"TELEMETRY_{rx}_STATUS_PRE_ATB", status_addr)
        assert before & _STATUS_EMPTY, (
            f"TELEMETRY_{rx} STATUS.EMPTY expected before its ATB message, got "
            f"0x{before:08x}; a later non-empty sample would not be "
            f"attributable to this leg"
        )
        await _send_telemetry_message(
            dut, leg["probe_id"], leg["counters"], rx=rx, atid=leg["atid"]
        )
        await ClockCycles(dut.clk_smc_i, 16)
        status = 0
        for _ in range(_BUFFER_POLL_BOUND):
            status = await self.csr_read(f"TELEMETRY_{rx}_STATUS_ATB", status_addr)
            if not (status & _STATUS_EMPTY):
                break
            await ClockCycles(dut.clk_smc_i, 1)
        else:
            raise AssertionError(
                f"TELEMETRY_{rx} buffer stayed EMPTY after its ATB message "
                f"(STATUS=0x{status:08x}) over {_BUFFER_POLL_BOUND} polls"
            )
        probe = await self.csr_read(f"TELEMETRY_{rx}_PROBE_ID_ATB", probe_addr)
        assert (probe & 0x1F) == leg["probe_id"], (
            f"TELEMETRY_{rx} PROBE_ID mismatch: got 0x{probe:x}, expected "
            f"0x{leg['probe_id']:x} (the value framed into receiver {rx})"
        )
        await self.csr_write(f"TELEMETRY_{rx}_BUFFER_POP", ctrl_addr, 0x1)
        await ClockCycles(dut.clk_smc_i, 4)
        self.rx_atb_probe_ids[rx] = probe & 0x1F
        self.rx_atb_status[rx] = status
        cocotb.log.info(
            "CHK-TELEMETRY-RECEIVER-%d-ATB: STATUS went 0x%08x (EMPTY set) -> "
            "0x%08x (EMPTY clear) and TELEMETRY_PROBE_ID read back 0x%02X for "
            "the message framed into receiver %d with ATB ID 0x%02X",
            rx,
            before,
            status,
            self.rx_atb_probe_ids[rx],
            rx,
            leg["atid"],
        )

    async def body(self) -> None:
        dut = cocotb.top
        for name, addr, expected in TELEMETRY_READS:
            await self.csr_read(name, addr, expected=expected)

        # Receivers 1/2: one behavioural leg each, so the claim for them is not
        # limited to "the window decodes and reads its reset values".
        for rx in _QUIET_RECEIVERS:
            addr = smc_indexed_addr(
                "SMC_TOP_SMC_TELEMETRY_RECEIVER_WRAP_TELEMETRY_RECEIVER_INTR_ENABLE_BASE_ADDR",
                rx,
            )
            await self.csr_write(f"TELEMETRY_{rx}_INTR_ENABLE_WR", addr, _INTR_ENABLE_WRITABLE)
            await self.csr_read(
                f"TELEMETRY_{rx}_INTR_ENABLE_RB",
                addr,
                expected=_INTR_ENABLE_WRITABLE,
            )
            await self.csr_write(f"TELEMETRY_{rx}_INTR_ENABLE_RESTORE", addr, 0)
            await self.csr_read(f"TELEMETRY_{rx}_INTR_ENABLE_RESTORE_RB", addr, expected=0)
            self.quiet_receivers_proved.append(rx)

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
        # The readback is the completion handshake for the ungate: it is a real
        # AXI round trip with an exact expectation, so nothing here stands in
        # for a fixed settling delay ([NO-BLIND-DELAY-SYNC]).
        await self.csr_read(
            "CLOCK_GATE_CONTROL_TELEMETRY_UNGATE_RB",
            _CLOCK_GATE_CONTROL,
            expected=cg & ~_TELEMETRY_CG_EN,
        )

        # --- U4-6a: INTR_TEST -> tb_telemetry_irq_any
        irq_before = int(dut.tb_telemetry_irq_any.value)
        assert irq_before == 0, (
            f"tb_telemetry_irq_any is already {irq_before} before INTR_TEST is "
            f"written; the rise observed below could not be attributed to it"
        )
        await self.csr_write(
            "TELEMETRY_0_INTR_ENABLE", _TELEMETRY_0_INTR_ENABLE, _INTR_MISSING_LAST
        )
        await self.csr_write("TELEMETRY_0_INTR_TEST", _TELEMETRY_0_INTR_TEST, _INTR_MISSING_LAST)
        self.irq_rise_cycles = await _await_irq_level(dut, 1, "INTR_TEST rise")
        intr_st = await self.csr_read("TELEMETRY_0_INTR_STATUS_POST", _TELEMETRY_0_INTR_STATUS)
        assert intr_st & _INTR_MISSING_LAST, (
            f"tb_telemetry_irq_any rose but TELEMETRY_0 INTR_STATUS does not "
            f"carry MISSING_LAST: 0x{intr_st:08x}"
        )
        await self.csr_write(
            "TELEMETRY_0_INTR_STATUS_W1C",
            _TELEMETRY_0_INTR_STATUS,
            _INTR_MISSING_LAST,
        )
        await self.csr_write("TELEMETRY_0_INTR_ENABLE_OFF", _TELEMETRY_0_INTR_ENABLE, 0)
        self.irq_fall_cycles = await _await_irq_level(dut, 0, "INTR_STATUS clear")

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
        self.probe_id_readback = probe & 0x1F
        self.status_non_empty = status
        # Pop the message so the buffer is clean for later tests.
        await self.csr_write("TELEMETRY_0_BUFFER_POP", _TELEMETRY_0_CTRL, 0x1)
        await ClockCycles(dut.clk_smc_i, 4)

        # --- U4-6c: the same framed message into receivers 1 and 2
        for rx in _QUIET_RECEIVERS:
            await self._atb_message_leg(dut, rx)

        await self.csr_write("CLOCK_GATE_CONTROL_RESTORE", _CLOCK_GATE_CONTROL, cg)
        # Every field below is a value this run read back or counted
        # ([EVIDENCE-TOKEN-CONDITIONAL]).
        cocotb.log.info(
            "CHK-TELEMETRY-RECEIVER-CSR: receiver 0 framed probe_id read back "
            "0x%02X from TELEMETRY_PROBE_ID and STATUS read 0x%08x (EMPTY "
            "clear) after the ATB message; INTR_TEST raised "
            "tb_telemetry_irq_any %d clk_smc_i cycle(s) after the write and "
            "the W1C cleared it %d cycle(s) after; receivers %s each stored and "
            "restored INTR_ENABLE=0x%02x; each of receivers %s also assembled "
            "its own framed ATB message, reading back PROBE_ID %s against the "
            "framed values %s",
            self.probe_id_readback,
            self.status_non_empty,
            self.irq_rise_cycles,
            self.irq_fall_cycles,
            ",".join(str(r) for r in self.quiet_receivers_proved),
            _INTR_ENABLE_WRITABLE,
            ",".join(str(r) for r in sorted(self.rx_atb_probe_ids)),
            ",".join(f"0x{self.rx_atb_probe_ids[r]:02X}" for r in sorted(self.rx_atb_probe_ids)),
            ",".join(f"0x{_RX_ATB_LEGS[r]['probe_id']:02X}" for r in sorted(self.rx_atb_probe_ids)),
        )
