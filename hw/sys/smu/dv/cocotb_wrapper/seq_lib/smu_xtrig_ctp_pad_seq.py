# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smu_xtrig_ctp_pad_test. SEP=1 (sep_rtl), no Force.

The DTP cross-trigger network is the pad controller on all four CTP groups of
the SMU boundary. Its registers sit in the SMC peripheral map at
``SMC_TOP_DTP_CTRL_REG``; inside that window the cross trigger matrix and the
cross trigger ports are placed by the generated CTN address header
(``cross_trigger_network_addr.h``), which also carries the CTP count and the
matrix port count.

Golden sources, in the order the policy allows them:

* Register offsets, bitmasks, the CONFIG.MODE reset value, the CTP count and
  the per-index addresses come from the generated cross-trigger headers.
* The pad-control level per mode (``CTP_PAD_LEVELS``) is a DV-owned table
  transcribed from the CTP signal interface table in
  ``hw/ip/cross_trigger/cross_trigger_port/doc/interface.adoc``.
* The pad-ring controls the CTP defines no driver for
  (``UNDRIVEN_PAD_CONTROLS``) are the DTP port-table rows
  (``hw/sys/dtp/doc/port_table.adoc``) with no counterpart in that signal
  interface table; the CTN architecture names CT_Req_in and CT_Ack_in as
  input pads and CT_Ack_out as an output pad. Reading them as 0 is a DV rule.
* The matrix port of an internal lane follows the CTM port-indexing table
  (external CTPs first, internal lanes after) and the SMU integrator note that
  the low DTP internal-CT lanes are reserved for the SMC and the SMU exposes
  the lanes above them (``doc/integrator/src/smu.adoc``,
  ``hw/sys/smu/doc/port_table.adoc``).

S1  Wire-OR defaults. CONFIG.MODE reads its RDL reset value, which the CTP
    spec pins to wire-OR, and every CTP pad control sits at its wire-OR level
    on every lane. The undriven pad-ring controls read 0.

S2  Point-to-point mode, one lane. Writing CONFIG.MODE = 1 on lane 0 moves
    that lane's pad controls to their point-to-point levels and leaves the
    other lanes at their wire-OR levels. The undriven controls still read 0.

S3  Point-to-point receiver. With lane 0 in P2P, a request on
    ``xtrig_ctp_req_in_din_i[0]`` raises ``xtrig_ctp_ack_out_dout_o[0]`` and
    shows in ``STATUS.REQ_IN``; releasing the request retires the
    acknowledge, the four-phase sequence of the CTP receiver state machine.

S4  Matrix routing to a second port. With lane 1 also in P2P and
    ``CT_SRC[1].CT_DST_SELECT`` selecting lane 0's destination, the same
    request appears as ``xtrig_ctp_req_out_dout_o[1]``, and
    ``xtrig_ctp_ack_in_din_i[1]`` retires it.

S5  Matrix routing to the internal cross-trigger lanes. Selecting lane 0's
    destination into the CT_SRC port of the first SMU-exposed internal lane
    makes ``xtrig_ctm_src_req_o[0]`` pulse on the same request.

S6  Wire-OR receive. Lane 2 is left in wire-OR, where the incoming trigger is
    an edge on ``xtrig_ctp_req_out_din_i``; routed into the same internal
    lane it produces the same pulse.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import smc_addr
from seq_lib.smu_boundary_regs import (
    cross_trigger_network_indexed_addr,
    cross_trigger_network_u32,
    cross_trigger_u32,
)
from seq_lib.smu_compose_helpers import bit_width
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

DTP_CSR_BASE = smc_addr("SMC_TOP_DTP_CTRL_REG_BASE_ADDR")

NUM_CTP = cross_trigger_network_u32("CROSS_TRIGGER_NETWORK_CTP_NUM")
NUM_CT_SRC = cross_trigger_network_u32("CROSS_TRIGGER_NETWORK_CTM_CT_SRC_NUM")
CTP_CONFIG_OFF = cross_trigger_u32("CROSS_TRIGGER_PORT_CONFIG_BASE_ADDR")
CTP_STATUS_OFF = cross_trigger_u32("CROSS_TRIGGER_PORT_STATUS_BASE_ADDR")
CONFIG_MODE_BM = cross_trigger_u32("CROSS_TRIGGER_PORT__CONFIG__MODE_bm")
CONFIG_MODE_BP = cross_trigger_u32("CROSS_TRIGGER_PORT__CONFIG__MODE_bp")
CONFIG_MODE_RESET = cross_trigger_u32("CROSS_TRIGGER_PORT__CONFIG__MODE_reset")
STATUS_REQ_IN_BM = cross_trigger_u32("CROSS_TRIGGER_PORT__STATUS__REQ_IN_bm")
STATUS_ACK_OUT_BM = cross_trigger_u32("CROSS_TRIGGER_PORT__STATUS__ACK_OUT_bm")
CT_DST_SELECT_BM = cross_trigger_u32("CROSS_TRIGGER_MATRIX__CT_SRC__CONFIG_0__CT_DST_SELECT_bm")

# CTP signal interface table: MODE 0 is wire-OR, 1 is point-to-point.
WIRE_OR = 0
P2P = 1

# Integrator DTP configuration table, SMU default for XTRIG_NUM_INT_CT: the
# SMU exposes 8 of the DTP's internal cross-trigger lanes, the ones above the
# SMC reservation.
SMU_INT_CT_EXPOSED = 8

CTP_MASK = (1 << NUM_CTP) - 1
P2P_LANE = 0
SINK_LANE = 1
WIRE_OR_LANE = 2
SMU_CT_LANE = 0
# Pad inputs cross the CTP's two-flop synchronizer and the CTM registers its
# outputs, so a mode write or a pad release reaches the pads a few clocks later.
PAD_SETTLE = 8
PULSE_BOUND = 64

# CTP pad-control level per mode with no trigger in flight, transcribed from
# the CTP signal interface table: an enable the table calls "enabled" is 1,
# one it calls "disabled" or "enabled by a cross trigger pulse" is 0, and a
# data output it calls "static-low", or that carries no request or
# acknowledge, is 0. Index by mode: (wire-OR, point-to-point).
CTP_PAD_LEVELS: dict[str, tuple[int, int]] = {
    "tb_xtrig_ctp_req_out_dout_en": (0, 1),
    "tb_xtrig_ctp_req_out_din_en": (1, 0),
    "tb_xtrig_ctp_req_out_dout": (0, 0),
    "tb_xtrig_ctp_req_in_din_en": (0, 1),
    "tb_xtrig_ctp_ack_in_din_en": (0, 1),
    "tb_xtrig_ctp_ack_out_dout_en": (0, 1),
    "tb_xtrig_ctp_ack_out_dout": (0, 0),
}

# DTP pad-ring outputs with no counterpart in the CTP signal interface table:
# CT_Req_in and CT_Ack_in are input pads with no output data or output enable,
# and CT_Ack_out is an output pad with no input-buffer enable. DV rule: a pad
# control with no driver reads 0 in every mode.
UNDRIVEN_PAD_CONTROLS = (
    "tb_xtrig_ctp_req_in_dout",
    "tb_xtrig_ctp_req_in_dout_en",
    "tb_xtrig_ctp_ack_in_dout",
    "tb_xtrig_ctp_ack_in_dout_en",
    "tb_xtrig_ctp_ack_out_din_en",
)


def expected_pad_vectors(modes: dict[int, int]) -> dict[str, int]:
    """Per-pin expected vector from ``CTP_PAD_LEVELS``; lanes not in ``modes`` are wire-OR."""
    out: dict[str, int] = {}
    for name, levels in CTP_PAD_LEVELS.items():
        vec = 0
        for lane in range(NUM_CTP):
            vec |= levels[modes.get(lane, WIRE_OR)] << lane
        out[name] = vec
    return out


class smu_xtrig_ctp_pad_seq:
    """CTP pad direction and the point-to-point handshake at the SMU boundary."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.log = test.logger
        self.sb = test.env.scoreboard

    def _pin(self, name: str):
        pin = getattr(self.dut, name, None)
        if pin is None:
            raise AssertionError(f"{name} unobservable on this TB top")
        return pin

    def _vec(self, name: str) -> int:
        val = self._pin(name).value
        if not val.is_resolvable:
            raise AssertionError(f"X/Z on {name}: {val}")
        return int(val)

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

    def _ctp_addr(self, lane: int, offset: int) -> int:
        if not 0 <= lane < NUM_CTP:
            raise AssertionError(f"CTP lane {lane} outside CROSS_TRIGGER_NETWORK_CTP_NUM={NUM_CTP}")
        return (
            DTP_CSR_BASE
            + cross_trigger_network_indexed_addr("CROSS_TRIGGER_NETWORK_CTP_BASE_ADDR", lane)
            + offset
        )

    def _ctm_src_addr(self, port: int) -> int:
        if not 0 <= port < NUM_CT_SRC:
            raise AssertionError(
                f"CTM port {port} outside CROSS_TRIGGER_NETWORK_CTM_CT_SRC_NUM={NUM_CT_SRC}"
            )
        return DTP_CSR_BASE + cross_trigger_network_indexed_addr(
            "CROSS_TRIGGER_NETWORK_CTM_CT_SRC_BASE_ADDR", port
        )

    async def run(self) -> None:
        dut = self.dut
        await self.cfg.reset_done.wait()
        if CONFIG_MODE_RESET != WIRE_OR:
            raise AssertionError(
                f"CONFIG.MODE reset {CONFIG_MODE_RESET} in the RDL header is not the wire-OR "
                "value the CTP spec requires at reset"
            )
        for name in (*CTP_PAD_LEVELS, *UNDRIVEN_PAD_CONTROLS):
            width = bit_width(self._pin(name), name)
            if width != NUM_CTP:
                raise AssertionError(
                    f"{name} is {width} wide; CROSS_TRIGGER_NETWORK_CTP_NUM is {NUM_CTP}"
                )
        self.jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await self.jtag.reset_tap()
        await self.jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await self.jtag.step_tms(0)
        idcode = await self.jtag.read_idcode()
        if idcode != DTP_DEFAULT_IDCODE:
            raise AssertionError(f"IDCODE want 0x{DTP_DEFAULT_IDCODE:x} got 0x{idcode:08x}")
        if self._vec("tb_smc_jtag2axi_security_disable") & 1:
            raise AssertionError("SMC JTAG2AXI still gated; no CSR leg can run")

        await self._wire_or_defaults()
        await self._point_to_point_mode()
        await self._p2p_receiver()
        await self._matrix_route_to_port()
        await self._matrix_route_to_internal()
        await self._wire_or_receive()

    def _check_pads(self, modes: dict[int, int], label: str, evidence: str) -> None:
        for name, want in expected_pad_vectors(modes).items():
            self.sb.expect_eq(
                f"{name} sits at the CTP-table level for every lane ({label})",
                self._vec(name),
                want,
                evidence=evidence,
            )
        for name in UNDRIVEN_PAD_CONTROLS:
            self.sb.expect_eq(
                f"{name} has no CTP driver and reads 0 ({label})",
                self._vec(name),
                0,
                evidence="CHK-SMU-CTP-TIEOFF",
            )

    # ------------------------------------------------------------------
    # S1
    # ------------------------------------------------------------------
    async def _wire_or_defaults(self) -> None:
        config = await self._rd32(self._ctp_addr(P2P_LANE, CTP_CONFIG_OFF), "CTP0 CONFIG")
        self.sb.expect_eq(
            "CTP CONFIG.MODE reads its RDL reset value (wire-OR)",
            (config & CONFIG_MODE_BM) >> CONFIG_MODE_BP,
            CONFIG_MODE_RESET,
            evidence="CHK-SMU-CTP-DEFAULT",
        )
        self._check_pads({}, "all lanes wire-OR", "CHK-SMU-CTP-DEFAULT")

    # ------------------------------------------------------------------
    # S2
    # ------------------------------------------------------------------
    async def _set_mode(self, lane: int, mode: int) -> None:
        addr = self._ctp_addr(lane, CTP_CONFIG_OFF)
        await self._wr32(addr, (mode << CONFIG_MODE_BP) & CONFIG_MODE_BM, f"CTP{lane} CONFIG")
        readback = await self._rd32(addr, f"CTP{lane} CONFIG")
        self.sb.expect_eq(
            f"CTP{lane} CONFIG.MODE holds the written mode",
            (readback & CONFIG_MODE_BM) >> CONFIG_MODE_BP,
            mode,
            evidence="CHK-SMU-CTP-P2P-MODE",
        )
        await ClockCycles(self.dut.clk_smu_i, PAD_SETTLE)

    async def _point_to_point_mode(self) -> None:
        await self._set_mode(P2P_LANE, P2P)
        self._check_pads({P2P_LANE: P2P}, f"lane {P2P_LANE} point-to-point", "CHK-SMU-CTP-P2P-MODE")

    # ------------------------------------------------------------------
    # S3
    # ------------------------------------------------------------------
    async def _wait_vec_bit(self, name: str, bit: int, want: int, what: str) -> int:
        for cycle in range(PULSE_BOUND):
            if ((self._vec(name) >> bit) & 1) == want:
                return cycle
            await ClockCycles(self.dut.clk_smu_i, 1)
        raise AssertionError(
            f"TIMEOUT {what}: {name}[{bit}] stayed {1 - want} for {PULSE_BOUND} clk_smu cycles"
        )

    async def _p2p_receiver(self) -> None:
        dut = self.dut
        dut.tb_xtrig_ctp_req_in_din.value = 1 << P2P_LANE
        cycles = await self._wait_vec_bit(
            "tb_xtrig_ctp_ack_out_dout", P2P_LANE, 1, "P2P receiver acknowledge"
        )
        self.log.info("ack_out_dout rose %d clk_smu after the request", cycles)
        self.sb.expect_eq(
            "a point-to-point request in raises the acknowledge out",
            (self._vec("tb_xtrig_ctp_ack_out_dout") >> P2P_LANE) & 1,
            1,
            evidence="CHK-SMU-CTP-P2P-RX",
        )
        status = await self._rd32(self._ctp_addr(P2P_LANE, CTP_STATUS_OFF), "CTP0 STATUS")
        self.sb.expect_eq(
            "STATUS reports the request in and the acknowledge out together",
            status & (STATUS_REQ_IN_BM | STATUS_ACK_OUT_BM),
            STATUS_REQ_IN_BM | STATUS_ACK_OUT_BM,
            evidence="CHK-SMU-CTP-P2P-RX",
        )
        dut.tb_xtrig_ctp_req_in_din.value = 0
        await self._wait_vec_bit(
            "tb_xtrig_ctp_ack_out_dout", P2P_LANE, 0, "P2P receiver acknowledge release"
        )
        self.sb.expect_eq(
            "releasing the request retires the acknowledge (four-phase)",
            (self._vec("tb_xtrig_ctp_ack_out_dout") >> P2P_LANE) & 1,
            0,
            evidence="CHK-SMU-CTP-P2P-RX",
        )

    # ------------------------------------------------------------------
    # S4
    # ------------------------------------------------------------------
    async def _matrix_route_to_port(self) -> None:
        dut = self.dut
        await self._set_mode(SINK_LANE, P2P)
        select = (1 << P2P_LANE) & CT_DST_SELECT_BM
        await self._wr32(self._ctm_src_addr(SINK_LANE), select, "CTM CT_SRC[1]")
        readback = await self._rd32(self._ctm_src_addr(SINK_LANE), "CTM CT_SRC[1]")
        self.sb.expect_eq(
            "the matrix holds the destination select for the sink port",
            readback & CT_DST_SELECT_BM,
            select,
            evidence="CHK-SMU-CTP-ROUTE",
        )
        self.sb.expect_eq(
            "no request is presented on the sink lane before the trigger",
            (self._vec("tb_xtrig_ctp_req_out_dout") >> SINK_LANE) & 1,
            0,
            evidence="CHK-SMU-CTP-ROUTE",
        )
        dut.tb_xtrig_ctp_req_in_din.value = 1 << P2P_LANE
        cycles = await self._wait_vec_bit(
            "tb_xtrig_ctp_req_out_dout", SINK_LANE, 1, "routed request out"
        )
        self.log.info("req_out_dout[%d] rose %d clk_smu after the trigger", SINK_LANE, cycles)
        self.sb.expect_eq(
            "the matrix routes the trigger to the sink port's request out",
            (self._vec("tb_xtrig_ctp_req_out_dout") >> SINK_LANE) & 1,
            1,
            evidence="CHK-SMU-CTP-ROUTE",
        )
        dut.tb_xtrig_ctp_ack_in_din.value = 1 << SINK_LANE
        await self._wait_vec_bit(
            "tb_xtrig_ctp_req_out_dout", SINK_LANE, 0, "routed request release"
        )
        self.sb.expect_eq(
            "the acknowledge in retires the sink port's request out",
            (self._vec("tb_xtrig_ctp_req_out_dout") >> SINK_LANE) & 1,
            0,
            evidence="CHK-SMU-CTP-ROUTE",
        )
        dut.tb_xtrig_ctp_ack_in_din.value = 0
        dut.tb_xtrig_ctp_req_in_din.value = 0
        await ClockCycles(dut.clk_smu_i, PAD_SETTLE)
        await self._wr32(self._ctm_src_addr(SINK_LANE), 0, "CTM CT_SRC[1]")

    # ------------------------------------------------------------------
    # S5 / S6
    # ------------------------------------------------------------------
    def _internal_src_port(self) -> int:
        """CTM port of SMU-exposed internal lane ``SMU_CT_LANE``.

        CTM ports 0..NUM_CTP-1 are the external CTPs and the DTP internal lanes
        follow; the SMU exposes the DTP lanes above the SMC reservation, so the
        reservation is the DTP internal-lane count less the exposed count.
        """
        dtp_int_ct = NUM_CT_SRC - NUM_CTP
        exposed = bit_width(self._pin("xtrig_ctm_src_req"), "xtrig_ctm_src_req")
        if exposed != SMU_INT_CT_EXPOSED:
            raise AssertionError(
                f"xtrig_ctm_src_req is {exposed} wide; the SMU default exposes "
                f"{SMU_INT_CT_EXPOSED} internal lanes"
            )
        if not 0 <= SMU_CT_LANE < SMU_INT_CT_EXPOSED <= dtp_int_ct:
            raise AssertionError(
                f"exposed lane {SMU_CT_LANE} of {SMU_INT_CT_EXPOSED} does not fit the "
                f"{dtp_int_ct} DTP internal lanes"
            )
        return NUM_CTP + (dtp_int_ct - SMU_INT_CT_EXPOSED) + SMU_CT_LANE

    async def _route_to_internal(self, dst_mask: int) -> None:
        port = self._internal_src_port()
        select = dst_mask & CT_DST_SELECT_BM
        await self._wr32(self._ctm_src_addr(port), select, f"CTM CT_SRC[{port}]")
        readback = await self._rd32(self._ctm_src_addr(port), f"CTM CT_SRC[{port}]")
        self.sb.expect_eq(
            f"the matrix holds the destination select for internal lane {SMU_CT_LANE}",
            readback & CT_DST_SELECT_BM,
            select,
            evidence="CHK-SMU-CTM-SRC",
        )

    async def _matrix_route_to_internal(self) -> None:
        dut = self.dut
        await self._route_to_internal(1 << P2P_LANE)
        self.sb.expect_eq(
            "no internal cross-trigger request before the trigger",
            (self._vec("xtrig_ctm_src_req") >> SMU_CT_LANE) & 1,
            0,
            evidence="CHK-SMU-CTM-SRC",
        )
        dut.tb_xtrig_ctp_req_in_din.value = 1 << P2P_LANE
        cycles = await self._wait_vec_bit(
            "xtrig_ctm_src_req", SMU_CT_LANE, 1, "internal cross-trigger request"
        )
        self.log.info("xtrig_ctm_src_req_o[%d] rose after %d clk_smu", SMU_CT_LANE, cycles)
        self.sb.expect_eq(
            "a point-to-point trigger reaches the internal cross-trigger lane",
            (self._vec("xtrig_ctm_src_req") >> SMU_CT_LANE) & 1,
            1,
            evidence="CHK-SMU-CTM-SRC",
        )
        dut.tb_xtrig_ctp_req_in_din.value = 0
        await ClockCycles(dut.clk_smu_i, PULSE_BOUND)

    async def _wire_or_receive(self) -> None:
        dut = self.dut
        # Lane 2 keeps the wire-OR default, where the trigger is an edge on the
        # request-out data input rather than a level on the request-in pin.
        await self._route_to_internal(1 << WIRE_OR_LANE)
        await self._wait_vec_bit(
            "xtrig_ctm_src_req", SMU_CT_LANE, 0, "internal request idle before wire-OR trigger"
        )
        dut.tb_xtrig_ctp_req_out_din.value = 1 << WIRE_OR_LANE
        cycles = await self._wait_vec_bit("xtrig_ctm_src_req", SMU_CT_LANE, 1, "wire-OR trigger")
        self.log.info("wire-OR trigger reached the internal lane after %d clk_smu", cycles)
        self.sb.expect_eq(
            "a wire-OR edge on the request-out data input reaches the internal lane",
            (self._vec("xtrig_ctm_src_req") >> SMU_CT_LANE) & 1,
            1,
            evidence="CHK-SMU-CTM-SRC",
        )
        dut.tb_xtrig_ctp_req_out_din.value = 0
        await ClockCycles(dut.clk_smu_i, PAD_SETTLE)
