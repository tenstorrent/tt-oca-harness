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
    id that was framed, one valid bit per counter sent and the counter value
    itself reassembled, and ``CTRL.BUFFER_POP`` has to return it to empty.

S4  The ATB flush handshake. ``telemetry_receiver.sv`` drives
    ``afvalid_o = CTRL.TELEMETRY_TX_FLUSH`` and clears that field on
    ``afready_i && afvalid_o``, so with ``telemetry_afready_i`` held low the
    request must stay asserted, and only raising it may retire the request at
    both the pin and the register.

The frame this sequence builds is derived from the receiver's own packet and
block types and from its counter decode, not from a bench convention; the
constants below cite where each field comes from.

``telemetry_atid_i`` is driven because an ATB beat carries an ID, but no
register reflects it: ``telemetry_receiver.sv`` declares ``atid_i`` and never
reads it. Its capture is not claimed here.
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

# ATB frame layout, from hw/ip/telemetry_receiver/rtl/telemetry_receiver_pkg.sv
# and telemetry_receiver.sv. A packet is
# ``{last_packet, blocks[NUM_BLOCKS_PER_PACKET-1:0]}`` and a block is
# ``{vld, counter_val_partial[7:0]}``, so block k occupies bits 9k+8 .. 9k and
# ``last_packet`` is the packet's MSB. ``get_telemetry_probe_id`` reads
# ``telemetry_packets[0][60:56]``. The counter decode
# (telemetry_receiver.sv:187-213) starts at block index 1 and walks upward,
# MSB byte first, so counter 0 is blocks 1..4 of the first packet. The beats
# carry the packet a byte at a time, least significant byte first.
ATB_BEAT_BITS = 8
ATB_PACKET_BITS = 64
ATB_BEATS_PER_PACKET = ATB_PACKET_BITS // ATB_BEAT_BITS
ATB_BLOCK_BITS = ATB_BEAT_BITS + 1
ATB_FIRST_COUNTER_BLOCK = 1
ATB_BYTES_PER_COUNTER = 4
ATB_PROBE_ID_LSB = 56
ATB_LAST_PACKET_BIT = ATB_PACKET_BITS - 1

PROBE_ID = 0x0B
# One counter, so the whole message is a single packet: counter 1 would need
# the header block, which carries the probe id.
COUNTER_VALUE = 0x1122_3344
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

    def _frame_single_counter(self, probe_id: int, value: int) -> int:
        """One last-flagged packet carrying counter 0 in blocks 1..4."""
        packet = 1 << ATB_LAST_PACKET_BIT
        packet |= (probe_id & PROBE_ID_BM) << ATB_PROBE_ID_LSB
        for step in range(ATB_BYTES_PER_COUNTER):
            block = ATB_FIRST_COUNTER_BLOCK + step
            byte = (value >> ((ATB_BYTES_PER_COUNTER - 1 - step) * 8)) & 0xFF
            packet |= byte << (block * ATB_BLOCK_BITS)
            packet |= 1 << (block * ATB_BLOCK_BITS + ATB_BEAT_BITS)
        return packet

    async def _send_message(self) -> None:
        packet = self._frame_single_counter(PROBE_ID, COUNTER_VALUE)
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
            "one valid bit per counter sent",
            vlds,
            1,
            evidence="CHK-SMU-TEL-CAPTURE",
        )
        counter0 = await self._rd32(TEL_COUNTER0, "TELEMETRY_COUNTER[0]")
        self.sb.expect_eq(
            "counter 0 reassembles the four bytes that were framed",
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
