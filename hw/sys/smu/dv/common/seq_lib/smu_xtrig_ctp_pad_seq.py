# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smu_xtrig_ctp_pad_test. SEP=0, no Force.

The DTP cross-trigger network is the pad controller on all four CTP groups of
the SMU boundary. Its registers sit in the SMC peripheral map at
``SMC_TOP_DTP_CTRL_REG``, and the CTN decodes that window onto the cross
trigger matrix (offset 0) and the sixteen cross trigger ports (offset 0x200,
0x10 apart) -- ``cross_trigger_network.sv:137-149``.

S1  Wire-OR defaults. ``CONFIG.MODE`` resets to 0, and
    ``cross_trigger_port_core.sv:151-169`` then drives ``req_out_din_en`` high
    on every lane and every other enable low. The five outputs
    ``cross_trigger_network.sv:247-252`` ties to ``1'b0`` -- req_in dout and
    dout_en, ack_in dout and dout_en, ack_out din_en -- are checked against
    that tie-off, on every lane.

S2  Point-to-point mode, one lane. Writing ``CONFIG.MODE = 1`` on lane 0 has
    to swap that lane's four enables (``req_out_din_en`` low; ``req_out_dout_en``,
    ``req_in_din_en``, ``ack_in_din_en`` and ``ack_out_dout_en`` high) and
    leave all fifteen other lanes at their wire-OR values.

S3  Point-to-point receiver. With lane 0 in P2P, a request on
    ``xtrig_ctp_req_in_din_i[0]`` has to raise ``xtrig_ctp_ack_out_dout_o[0]``
    and show in ``STATUS.REQ_IN``; releasing the request has to retire the
    acknowledge, which is the four-phase contract in ``ctp_handshake_ctrl.sv``.

S4  Matrix routing to a second port. With lane 1 also in P2P and
    ``CT_SRC[1].CT_DST_SELECT`` selecting lane 0's destination, the same
    request has to appear as ``xtrig_ctp_req_out_dout_o[1]``, and
    ``xtrig_ctp_ack_in_din_i[1]`` has to retire it.

S5  Matrix routing to the internal cross-trigger lanes. CTM port
    ``NUM_CTP + i`` is internal lane i and the SMU exposes DTP lanes 2..9 as
    ``xtrig_ctm_src_req_o[7:0]`` (``smu.sv:1314``), so selecting lane 0's
    destination into ``CT_SRC[18]`` has to make ``xtrig_ctm_src_req_o[0]``
    pulse on the same request.

S6  Wire-OR receive. Lane 2 is left in wire-OR, where the incoming trigger is
    an edge on ``xtrig_ctp_req_out_din_i``; routed into the same internal
    lane it has to produce the same pulse.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import cross_trigger_u32, smc_addr
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
# cross_trigger_network.sv:137-149: the CTM occupies the first CSR_ADDR_CTM_SIZE
# bytes of the CTN window and CTP i follows at CSR_ADDR_CTP_SIZE intervals.
CTN_CTP_BASE = 0x200
CTN_CTP_STRIDE = 0x10
# dtp_pkg.sv: DEFAULT_NUM_CTP / DEFAULT_NUM_INT_CT, and cross_trigger_network.sv
# numbers matrix port NUM_CTP + i as internal cross-trigger lane i.
NUM_CTP = 16
# smu.sv:1314: the SMU exposes DTP internal lanes 2..9, so its lane 0 is DTP 2.
SMU_INT_CT_FIRST = 2

CTP_CONFIG_OFF = cross_trigger_u32("CROSS_TRIGGER_PORT_CONFIG_BASE_ADDR")
CTP_STATUS_OFF = cross_trigger_u32("CROSS_TRIGGER_PORT_STATUS_BASE_ADDR")
CTM_SRC_STRIDE = cross_trigger_u32("CROSS_TRIGGER_MATRIX_CT_SRC_STRIDE")
CONFIG_MODE_BM = cross_trigger_u32("CROSS_TRIGGER_PORT__CONFIG__MODE_bm")
STATUS_REQ_IN_BM = cross_trigger_u32("CROSS_TRIGGER_PORT__STATUS__REQ_IN_bm")
STATUS_ACK_OUT_BM = cross_trigger_u32("CROSS_TRIGGER_PORT__STATUS__ACK_OUT_bm")
CT_DST_SELECT_BM = cross_trigger_u32("CROSS_TRIGGER_MATRIX__CT_SRC__CONFIG_0__CT_DST_SELECT_bm")

CTP_MASK = (1 << NUM_CTP) - 1
P2P_LANE = 0
SINK_LANE = 1
WIRE_OR_LANE = 2
SMU_CT_LANE = 0
# cross_trigger_port_core.sv flops every pad output, and a pad input crosses a
# two-flop synchronizer before the FSM sees it.
PAD_SETTLE = 8
PULSE_BOUND = 64

# The five pad outputs cross_trigger_network.sv:247-252 ties to 1'b0.
TIED_LOW_PINS = (
    "tb_xtrig_ctp_req_in_dout",
    "tb_xtrig_ctp_req_in_dout_en",
    "tb_xtrig_ctp_ack_in_dout",
    "tb_xtrig_ctp_ack_in_dout_en",
    "tb_xtrig_ctp_ack_out_din_en",
)


class smu_xtrig_ctp_pad_seq:
    """CTP pad direction and the point-to-point handshake at the SMU boundary."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.log = test.logger
        self.sb = test.env.scoreboard

    def _vec(self, name: str) -> int:
        pin = getattr(self.dut, name, None)
        if pin is None:
            raise AssertionError(f"{name} unobservable on this TB top")
        val = pin.value
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
        return DTP_CSR_BASE + CTN_CTP_BASE + lane * CTN_CTP_STRIDE + offset

    def _ctm_src_addr(self, port: int) -> int:
        return DTP_CSR_BASE + port * CTM_SRC_STRIDE

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
        if self._vec("tb_smc_jtag2axi_security_disable") & 1:
            raise AssertionError("SMC JTAG2AXI still gated; no CSR leg can run")

        await self._wire_or_defaults()
        await self._point_to_point_mode()
        await self._p2p_receiver()
        await self._matrix_route_to_port()
        await self._matrix_route_to_internal()
        await self._wire_or_receive()

    # ------------------------------------------------------------------
    # S1
    # ------------------------------------------------------------------
    async def _wire_or_defaults(self) -> None:
        config = await self._rd32(self._ctp_addr(P2P_LANE, CTP_CONFIG_OFF), "CTP0 CONFIG")
        self.sb.expect_eq(
            "CTP CONFIG.MODE resets to wire-OR",
            config & CONFIG_MODE_BM,
            0,
            evidence="CHK-SMU-CTP-DEFAULT",
        )
        self.sb.expect_eq(
            "wire-OR drives the request-out data input enable on every lane",
            self._vec("tb_xtrig_ctp_req_out_din_en"),
            CTP_MASK,
            evidence="CHK-SMU-CTP-DEFAULT",
        )
        for name in (
            "tb_xtrig_ctp_req_out_dout",
            "tb_xtrig_ctp_req_out_dout_en",
            "tb_xtrig_ctp_req_in_din_en",
            "tb_xtrig_ctp_ack_in_din_en",
            "tb_xtrig_ctp_ack_out_dout",
            "tb_xtrig_ctp_ack_out_dout_en",
        ):
            self.sb.expect_eq(
                f"{name} idle in wire-OR mode",
                self._vec(name),
                0,
                evidence="CHK-SMU-CTP-DEFAULT",
            )
        for name in TIED_LOW_PINS:
            self.sb.expect_eq(
                f"{name} is tied off in the cross-trigger network",
                self._vec(name),
                0,
                evidence="CHK-SMU-CTP-TIEOFF",
            )

    # ------------------------------------------------------------------
    # S2
    # ------------------------------------------------------------------
    async def _set_mode(self, lane: int, mode: int) -> None:
        addr = self._ctp_addr(lane, CTP_CONFIG_OFF)
        await self._wr32(addr, mode & CONFIG_MODE_BM, f"CTP{lane} CONFIG")
        readback = await self._rd32(addr, f"CTP{lane} CONFIG")
        self.sb.expect_eq(
            f"CTP{lane} CONFIG.MODE holds the written mode",
            readback & CONFIG_MODE_BM,
            mode & CONFIG_MODE_BM,
            evidence="CHK-SMU-CTP-P2P-MODE",
        )
        await ClockCycles(self.dut.clk_smu_i, PAD_SETTLE)

    async def _point_to_point_mode(self) -> None:
        lane = 1 << P2P_LANE
        await self._set_mode(P2P_LANE, CONFIG_MODE_BM)
        for name, expect in (
            ("tb_xtrig_ctp_req_out_dout_en", lane),
            ("tb_xtrig_ctp_req_in_din_en", lane),
            ("tb_xtrig_ctp_ack_in_din_en", lane),
            ("tb_xtrig_ctp_ack_out_dout_en", lane),
        ):
            self.sb.expect_eq(
                f"{name} follows CONFIG.MODE on the selected lane only",
                self._vec(name),
                expect,
                evidence="CHK-SMU-CTP-P2P-MODE",
            )
        self.sb.expect_eq(
            "the request-out data input enable drops on the point-to-point lane only",
            self._vec("tb_xtrig_ctp_req_out_din_en"),
            CTP_MASK & ~lane,
            evidence="CHK-SMU-CTP-P2P-MODE",
        )
        for name in TIED_LOW_PINS:
            self.sb.expect_eq(
                f"{name} stays tied off in point-to-point mode",
                self._vec(name),
                0,
                evidence="CHK-SMU-CTP-TIEOFF",
            )

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
        await self._set_mode(SINK_LANE, CONFIG_MODE_BM)
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
    async def _internal_src_port(self) -> int:
        return NUM_CTP + SMU_INT_CT_FIRST + SMU_CT_LANE

    async def _route_to_internal(self, dst_mask: int) -> None:
        port = await self._internal_src_port()
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
