# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smu_telemetry_atb_capture_test. SEP=0, no Force.

The ATB telemetry source interface at the SMU boundary, driven on receiver 0
and read back through the telemetry receiver's own registers over JTAG2AXI.

S1  Reset state. ``STATUS.BUFFER_EMPTY`` reads 1 while ``TELEMETRY_PROBE_ID``
    and ``TELEMETRY_COUNTER_VLDS`` read 0, so the window is discriminating:
    a dead read returning zeros fails the STATUS compare.

S2  The telemetry clock gate. ``SMC_BASE_CONFIG.CLOCK_GATE_CONTROL``'s
    ``TELEMETRY_CG_EN`` is read, cleared and read back before any beat, so a
    captured message cannot be credited to an accidentally gated receiver.

S3  One complete last-flagged ATB message. Every beat must be accepted --
    ``telemetry_atready_o`` high on a ``clk_telemetry_i`` edge while
    ``telemetry_atvalid_i`` is high -- because a dropped beat leaves a partial
    frame that can still clear ``STATUS.BUFFER_EMPTY`` and still match the
    probe id. The receiver then has to report the buffer non-empty, the probe
    id that was framed, one valid bit for the one counter's worth of valid
    blocks sent, that counter reassembled from the byte every valid block
    carried, and ``CTRL.BUFFER_POP`` has to return it to empty.

S4  The ATB flush handshake. ``CTRL.TELEMETRY_TX_FLUSH`` requests the
    upstream flush over the ATB AF interface and clears itself when the flush
    completes (``regs/telemetry_receiver.rdl``; ``doc/programming.adoc``,
    "Transmitter Flush"); ``afvalid_o`` is the flush request and ``afready_i``
    its acknowledgment (``doc/interface.adoc``). With ``telemetry_afready_i``
    held low the request must stay asserted at the pin and in the field, and
    raising it retires both.

The frame this sequence drives is a DV-owned table transcribed from the
telemetry receiver specification under ``hw/ip/telemetry_receiver/``; the
constants below cite each entry and name the positions the specification
leaves open.

``telemetry_atid_i`` is driven because an ATB beat carries a 7-bit source ID
(``doc/interface.adoc``), but no register in ``regs/telemetry_receiver.rdl``
reflects it, so its capture is not claimed here.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import smc_addr, smc_indexed_addr
from seq_lib.smu_boundary_regs import (
    smc_base_config_u32,
    smc_indexed2_addr,
    telemetry_receiver_u32,
)
from seq_lib.smu_jtag_helpers import (
    DTP_DEFAULT_IDCODE,
    J2A_STATUS_SUCCESS,
    SMC_DBG_AXSIZE_4B,
    axi64_pack32,
    axi64_unpack32,
    jtag2axi_single_read,
    jtag2axi_single_write,
    make_smu_jtag_tap,
    require_jtag_tdo_resolved,
)

TEL_CTRL = smc_indexed_addr(
    "SMC_TOP_SMC_TELEMETRY_RECEIVER_WRAP_TELEMETRY_RECEIVER_CTRL_BASE_ADDR", 0
)
TEL_STATUS = smc_indexed_addr(
    "SMC_TOP_SMC_TELEMETRY_RECEIVER_WRAP_TELEMETRY_RECEIVER_STATUS_BASE_ADDR", 0
)
TEL_PROBE_ID = smc_indexed_addr(
    "SMC_TOP_SMC_TELEMETRY_RECEIVER_WRAP_TELEMETRY_RECEIVER_TELEMETRY_PROBE_ID_BASE_ADDR", 0
)
TEL_COUNTER_VLDS = smc_indexed_addr(
    "SMC_TOP_SMC_TELEMETRY_RECEIVER_WRAP_TELEMETRY_RECEIVER_TELEMETRY_COUNTER_VLDS_BASE_ADDR", 0
)
TEL_COUNTER0 = smc_indexed2_addr(
    "SMC_TOP_SMC_TELEMETRY_RECEIVER_WRAP_TELEMETRY_RECEIVER_TELEMETRY_COUNTER_BASE_ADDR", 0, 0
)
CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")
TELEMETRY_CG_EN_BM = smc_base_config_u32("SMC_BASE_CONFIG__CLOCK_GATE_CONTROL__TELEMETRY_CG_EN_bm")

STATUS_EMPTY_BM = telemetry_receiver_u32("TELEMETRY_RECEIVER__STATUS__BUFFER_EMPTY_bm")
PROBE_ID_BM = telemetry_receiver_u32("TELEMETRY_RECEIVER__TELEMETRY_PROBE_ID__PROBE_ID_bm")
BUFFER_POP_BM = telemetry_receiver_u32("TELEMETRY_RECEIVER__CTRL__BUFFER_POP_bm")
TX_FLUSH_BM = telemetry_receiver_u32("TELEMETRY_RECEIVER__CTRL__TELEMETRY_TX_FLUSH_bm")

# ATB message format, transcribed from the telemetry receiver specification:
# hw/ip/telemetry_receiver/doc/index.adoc "Message Format" (eight little-endian
# beats form a 64-bit packet; a message ends at the packet with ``last_packet``
# set; ``last_packet`` is bit 63 of each packet; ``probe_id`` is bits [60:56]
# of the first packet; a block is 9 bits, one valid bit and one data byte,
# seven per packet; a counter is four consecutive blocks, most-significant
# byte first, valid only when all four blocks are valid), doc/interface.adoc
# (ATB_DATA_WIDTH 8, PACKET_WIDTH 64, ``atid_i`` 7 bits) and the generated
# regs/gen/c/telemetry_receiver.h (PROBE_ID width; COUNTER_VLDS bit i is
# counter i).
ATB_BEAT_BITS = 8
ATB_PACKET_BITS = 64
ATB_BEATS_PER_PACKET = ATB_PACKET_BITS // ATB_BEAT_BITS
ATB_LAST_PACKET_BIT = 63
ATB_PROBE_ID_MSB = 60
ATB_PROBE_ID_LSB = 56
ATB_PROBE_ID_BITS = telemetry_receiver_u32("TELEMETRY_RECEIVER__TELEMETRY_PROBE_ID__PROBE_ID_bw")
ATB_PROBE_ID_MASK = (1 << ATB_PROBE_ID_BITS) - 1
ATB_BLOCK_BITS = ATB_BEAT_BITS + 1
ATB_BLOCKS_PER_PACKET = 7
ATB_BLOCKS_PER_COUNTER = 4
assert ATB_PROBE_ID_MSB - ATB_PROBE_ID_LSB + 1 == ATB_PROBE_ID_BITS
assert ATB_BLOCKS_PER_PACKET * ATB_BLOCK_BITS + 1 == ATB_PACKET_BITS

# Seven 9-bit blocks fill bits 62:0 below ``last_packet``, so block boundaries
# sit at multiples of 9 and ``probe_id`` lies inside the top block, bits 62:54.
# The specification does not say which of the seven positions is block 0,
# whether a block's valid bit is its top or its bottom bit, or which block
# begins counter 0. The frame below is DV-owned and independent of all three:
# the header block is left invalid under either orientation, and every other
# block is all ones, the only 9-bit pattern that reads valid with the same data
# byte whichever bit is the valid bit. Any four consecutive valid blocks then
# reassemble COUNTER_VALUE in either byte order, and the six valid blocks hold
# exactly one counter's worth, so byte order and block placement are not
# discriminated here.
ATB_HEADER_BLOCK_LSB = ATB_LAST_PACKET_BIT - ATB_BLOCK_BITS
ATB_BLOCK_FILL = (1 << ATB_BLOCK_BITS) - 1
COUNTER_FILL_BYTE = ATB_BLOCK_FILL & ((1 << ATB_BEAT_BITS) - 1)
COUNTERS_SENT = (ATB_BLOCKS_PER_PACKET - 1) // ATB_BLOCKS_PER_COUNTER
COUNTER_VALUE = int.from_bytes(bytes([COUNTER_FILL_BYTE]) * ATB_BLOCKS_PER_COUNTER, "big")
EXPECTED_COUNTER_VLDS = (1 << COUNTERS_SENT) - 1
assert ATB_HEADER_BLOCK_LSB <= ATB_PROBE_ID_LSB and ATB_PROBE_ID_MSB < ATB_LAST_PACKET_BIT
assert COUNTERS_SENT == 1

PROBE_ID = 0x0B
assert PROBE_ID <= ATB_PROBE_ID_MASK
ATB_ID = 0x2A
ATB_READY_BOUND = 64
STATUS_POLL_BOUND = 200
AF_SETTLE_CYCLES = 16


class smu_telemetry_atb_capture_seq:
    """An ATB message driven at the SMU boundary and read back from the receiver."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.log = test.logger
        self.sb = test.env.scoreboard

    def _bit(self, name: str) -> int:
        pin = getattr(self.dut, name, None)
        if pin is None:
            raise AssertionError(f"{name} unobservable on this TB top")
        val = pin.value
        if not val.is_resolvable:
            raise AssertionError(f"X/Z on {name}: {val}")
        return int(val) & 1

    async def _rd32(self, addr: int, what: str) -> int:
        status, rdata = await jtag2axi_single_read(
            self.jtag, addr, size=SMC_DBG_AXSIZE_4B, require_complete=True
        )
        require_jtag_tdo_resolved(f"{what} RD @0x{addr:08x}")
        if status != J2A_STATUS_SUCCESS:
            raise AssertionError(f"{what} read @0x{addr:08x} status={status}")
        return axi64_unpack32(addr, rdata)

    async def _wr32(self, addr: int, data: int, what: str) -> None:
        wstrb, beat = axi64_pack32(addr, data)
        status, _ = await jtag2axi_single_write(
            self.jtag, addr, beat, wstrb=wstrb, size=SMC_DBG_AXSIZE_4B, require_complete=True
        )
        require_jtag_tdo_resolved(f"{what} WR @0x{addr:08x}")
        if status != J2A_STATUS_SUCCESS:
            raise AssertionError(f"{what} write @0x{addr:08x} status={status}")

    async def run(self) -> None:
        dut = self.dut
        await self.cfg.reset_done.wait()
        self.jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await self.jtag.reset_tap()
        await self.jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await self.jtag.step_tms(0)
        idcode = await self.jtag.read_idcode()
        if idcode != DTP_DEFAULT_IDCODE:
            raise AssertionError(f"IDCODE want 0x{DTP_DEFAULT_IDCODE:x} got 0x{idcode:08x}")
        if self._bit("tb_smc_jtag2axi_security_disable"):
            raise AssertionError("SMC JTAG2AXI still gated; no CSR leg can run")

        await self._reset_state()
        await self._ungate()
        await self._send_message()
        await self._flush_handshake()

    # ------------------------------------------------------------------
    # S1 / S2
    # ------------------------------------------------------------------
    async def _reset_state(self) -> None:
        status = await self._rd32(TEL_STATUS, "TELEMETRY STATUS")
        self.sb.expect_eq(
            "receiver 0 reports its message buffer empty out of reset",
            status & STATUS_EMPTY_BM,
            STATUS_EMPTY_BM,
            evidence="CHK-SMU-TEL-RESET",
        )
        probe = await self._rd32(TEL_PROBE_ID, "TELEMETRY_PROBE_ID")
        self.sb.expect_eq(
            "no probe id captured before any beat",
            probe & PROBE_ID_BM,
            0,
            evidence="CHK-SMU-TEL-RESET",
        )
        vlds = await self._rd32(TEL_COUNTER_VLDS, "TELEMETRY_COUNTER_VLDS")
        self.sb.expect_eq(
            "no counter reported valid before any beat",
            vlds,
            0,
            evidence="CHK-SMU-TEL-RESET",
        )
        counter0 = await self._rd32(TEL_COUNTER0, "TELEMETRY_COUNTER[0]")
        self.sb.expect_eq(
            "counter 0 reads its reset value before any beat",
            counter0,
            0,
            evidence="CHK-SMU-TEL-RESET",
        )

    async def _ungate(self) -> None:
        cg_mask = TELEMETRY_CG_EN_BM
        before = await self._rd32(CLOCK_GATE_CONTROL, "CLOCK_GATE_CONTROL")
        await self._wr32(CLOCK_GATE_CONTROL, before & ~cg_mask, "CLOCK_GATE_CONTROL")
        after = await self._rd32(CLOCK_GATE_CONTROL, "CLOCK_GATE_CONTROL")
        self.sb.expect_eq(
            "the telemetry clock gate is open before any beat is driven",
            after & cg_mask,
            0,
            evidence="CHK-SMU-TEL-CAPTURE",
        )

    # ------------------------------------------------------------------
    # S3
    # ------------------------------------------------------------------
    async def _drive_beat(self, value: int, index: int) -> None:
        """Drive one ATB beat and require the handshake to complete.

        Expiry is a failure, not a skip: a dropped beat leaves a partial frame
        that can still clear STATUS.BUFFER_EMPTY and still match the probe id.
        """
        dut = self.dut
        dut.tb_telemetry_atdata.value = value & 0xFF
        dut.tb_telemetry_atid.value = ATB_ID
        dut.tb_telemetry_atvalid.value = 1
        await RisingEdge(dut.clk_ref_i)
        accepted = False
        for _ in range(ATB_READY_BOUND):
            if self._bit("tb_telemetry_atready"):
                accepted = True
                break
            await RisingEdge(dut.clk_ref_i)
        dut.tb_telemetry_atvalid.value = 0
        if not accepted:
            raise AssertionError(
                f"ATB beat {index} (data=0x{value & 0xFF:02x}) was never accepted: "
                f"telemetry_atready_o stayed low for {ATB_READY_BOUND} clk_telemetry_i "
                f"cycles, and continuing would send a truncated frame"
            )

    async def _send_packet(self, packet: int) -> None:
        mask = (1 << ATB_BEAT_BITS) - 1
        for i in range(ATB_BEATS_PER_PACKET):
            await self._drive_beat((packet >> (i * ATB_BEAT_BITS)) & mask, i)

    def _frame_single_counter(self, probe_id: int) -> int:
        """One last-flagged packet: ``probe_id`` in the header block, every other block valid."""
        packet = 1 << ATB_LAST_PACKET_BIT
        packet |= (probe_id & ATB_PROBE_ID_MASK) << ATB_PROBE_ID_LSB
        for block_lsb in range(0, ATB_HEADER_BLOCK_LSB, ATB_BLOCK_BITS):
            packet |= ATB_BLOCK_FILL << block_lsb
        return packet

    async def _send_message(self) -> None:
        packet = self._frame_single_counter(PROBE_ID)
        self.log.info("ATB packet framed as 0x%016x", packet)
        await self._send_packet(packet)

        polls = 0
        for polls in range(1, STATUS_POLL_BOUND + 1):
            status = await self._rd32(TEL_STATUS, "TELEMETRY STATUS")
            if not status & STATUS_EMPTY_BM:
                break
        else:
            raise AssertionError(
                f"STATUS.BUFFER_EMPTY never cleared after a complete last-flagged "
                f"message: {STATUS_POLL_BOUND} polls"
            )
        self.log.info("telemetry receiver 0 reported a message after %d status polls", polls)
        self.sb.expect_eq(
            "a complete last-flagged ATB message leaves the buffer non-empty",
            status & STATUS_EMPTY_BM,
            0,
            evidence="CHK-SMU-TEL-CAPTURE",
        )
        probe = await self._rd32(TEL_PROBE_ID, "TELEMETRY_PROBE_ID")
        self.sb.expect_eq(
            "the receiver reports the probe id that was framed on the ATB beats",
            probe & PROBE_ID_BM,
            PROBE_ID,
            evidence="CHK-SMU-TEL-CAPTURE",
        )
        vlds = await self._rd32(TEL_COUNTER_VLDS, "TELEMETRY_COUNTER_VLDS")
        self.sb.expect_eq(
            "one valid bit for the one counter's worth of valid blocks sent",
            vlds,
            EXPECTED_COUNTER_VLDS,
            evidence="CHK-SMU-TEL-CAPTURE",
        )
        counter0 = await self._rd32(TEL_COUNTER0, "TELEMETRY_COUNTER[0]")
        self.sb.expect_eq(
            "counter 0 reassembles the byte that filled every valid block",
            counter0,
            COUNTER_VALUE,
            evidence="CHK-SMU-TEL-CAPTURE",
        )
        await self._wr32(TEL_CTRL, BUFFER_POP_BM, "TELEMETRY CTRL")
        await ClockCycles(self.dut.clk_smu_i, AF_SETTLE_CYCLES)
        status = await self._rd32(TEL_STATUS, "TELEMETRY STATUS")
        self.sb.expect_eq(
            "popping the only message returns the buffer to empty",
            status & STATUS_EMPTY_BM,
            STATUS_EMPTY_BM,
            evidence="CHK-SMU-TEL-CAPTURE",
        )

    # ------------------------------------------------------------------
    # S4
    # ------------------------------------------------------------------
    async def _flush_handshake(self) -> None:
        dut = self.dut
        dut.tb_telemetry_afready.value = 0
        await ClockCycles(dut.clk_ref_i, AF_SETTLE_CYCLES)
        self.sb.expect_eq(
            "no ATB flush is requested before software asks for one",
            self._bit("tb_telemetry_afvalid"),
            0,
            evidence="CHK-SMU-TEL-FLUSH",
        )
        await self._wr32(TEL_CTRL, TX_FLUSH_BM, "TELEMETRY CTRL")
        await ClockCycles(dut.clk_ref_i, AF_SETTLE_CYCLES)
        self.sb.expect_eq(
            "CTRL.TELEMETRY_TX_FLUSH raises telemetry_afvalid_o",
            self._bit("tb_telemetry_afvalid"),
            1,
            evidence="CHK-SMU-TEL-FLUSH",
        )
        held = await self._rd32(TEL_CTRL, "TELEMETRY CTRL")
        self.sb.expect_eq(
            "the flush request stays asserted while telemetry_afready_i is low",
            held & TX_FLUSH_BM,
            TX_FLUSH_BM,
            evidence="CHK-SMU-TEL-FLUSH",
        )
        dut.tb_telemetry_afready.value = 1
        await ClockCycles(dut.clk_ref_i, AF_SETTLE_CYCLES)
        self.sb.expect_eq(
            "telemetry_afready_i retires the request at the pin",
            self._bit("tb_telemetry_afvalid"),
            0,
            evidence="CHK-SMU-TEL-FLUSH",
        )
        cleared = await self._rd32(TEL_CTRL, "TELEMETRY CTRL")
        self.sb.expect_eq(
            "the acknowledged flush clears CTRL.TELEMETRY_TX_FLUSH",
            cleared & TX_FLUSH_BM,
            0,
            evidence="CHK-SMU-TEL-FLUSH",
        )
        dut.tb_telemetry_afready.value = 0
