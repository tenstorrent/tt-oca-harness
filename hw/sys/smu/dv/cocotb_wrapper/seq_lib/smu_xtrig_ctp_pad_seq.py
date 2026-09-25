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

S6  Wire-OR receive. Every CT_Req_out pad sits on an ``ocah_open_drain_bus``
    shared wire (private per pad, or the group wire the pads in
    ``tb_xtrig_ctp_wire_group`` share) resting at the board pull of the
    port's INVERT sense; the DUT never sees the pad driven directly. With
    every wire resting, no port's ``ct_dst`` rises through reset
    (``CHK-SMU-CTP-WIRE-IDLE``). Lane 2 stays wire-OR: a chiplet pull of its
    private wire raises ``tb_xtrig_ctp_ct_dst[2]`` exactly
    ``CT_DST_LATENCY`` clocks after the wire is first seen asserted, once for
    the pull and never again at the release (``CHK-SMU-CTP-WIRE-RX``), and
    the same pull reaches the routed internal lane
    (``xtrig_ctm_src_req_o[0]``, ``CHK-SMU-CTM-SRC`` restated).

S7  Wire-OR shared wire. Three wire-OR lanes join one group wire
    (``tb_xtrig_ctp_wire_group``). One chiplet pull on one member reaches
    every member's ``ct_dst`` once, at the same latency, and leaves every
    non-member lane quiet -- the P2P lanes, the private-wire receiver, and
    every lane above the group; two members pulled in overlapping windows
    still reach every member exactly once and leave every non-member lane
    quiet (``CHK-SMU-CTP-WIRE-SHARED``).
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, NextTimeStep, ReadOnly
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
# Ties the board smu_base_test.drive_idle_inputs drives (every wire's pull
# held at the literal 1) to the sense that literal assumes: INVERT=0 is a
# pull-up. A header whose INVERT reset disagrees invalidates that board.
CONFIG_INVERT_RESET = cross_trigger_u32("CROSS_TRIGGER_PORT__CONFIG__INVERT_reset")
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
# Wire-OR lanes joined on the S7 group wire: not P2P_LANE/SINK_LANE, which S2/S4
# moved to point-to-point, and not WIRE_OR_LANE, S6's private-wire receiver.
WIRE_OR_SHARED_LANES = (3, 4, 5)

# Not a DUT pin: a per-lane pseudo-vector the window samples like any other,
# computed as the resolved wire tb_xtrig_ctp_req_out_din XOR its own pull, so
# a bit reads 1 exactly when that lane's wire sits away from its rest level
# ("the wire is first seen asserted"), whichever polarity INVERT selects.
WIRE_ASSERTED_PSEUDO_NAME = "tb_xtrig_ctp_wire_asserted"

# Clock edges from the wire's assertion edge to a wire-OR port's registered
# ct_dst: the CTP synchronizer's one 2-FF synchronizer, i.e. two flop stages
# (ctp_synchronizer row, hw/ip/cross_trigger/cross_trigger_port/doc/
# architecture.adoc) plus the registered ct_dst output; the same constant as
# DTP_CT_DST_LATENCY (hw/sys/dtp/dv/cocotb/env/dtp_dv_cfg.py).
CT_DST_LATENCY = 3

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


class _WireOrWindow:
    """Per-clk_smu-cycle first-seen cycle and rise count of named vectors.

    Mirrors ``DtpXtrigActivityWindow``: each window cycle samples in
    ``ReadOnly`` the instant the window is at, then advances exactly one
    clk_smu period (``NextTimeStep`` then ``ClockCycles(clk_smu_i, 1)``) before
    sampling again, so cycle 0 is whatever instant ``start()`` was called at
    rather than the next edge. ``first_seen`` holds the window cycle at which
    each bit of each name first went high; ``rises`` counts how many times
    each bit rose. A caller that both starts a window and changes a driven
    vector must land on the same clk_smu edge first (e.g.
    ``await ClockCycles(clk_smu_i, n)``) and make the change right after that
    edge, in the same timestep as ``start()``, never inside ``ReadOnly``: a
    write at an arbitrary phase makes cycle 0 no longer the edge the DUT's
    synchronizer samples, which desyncs the measured latency from
    CT_DST_LATENCY by the fraction of a cycle the write drifted.
    """

    def __init__(self, seq: "smu_xtrig_ctp_pad_seq") -> None:
        self._seq = seq
        self._task: cocotb.Task | None = None
        self.names: tuple[str, ...] = ()
        self.cycles = 0
        self.activity: dict[str, int] = {}
        self.last: dict[str, int] = {}
        self.first_seen: dict[str, dict[int, int]] = {}
        self.rises: dict[str, dict[int, int]] = {}

    def start(self, names: tuple[str, ...]) -> None:
        self.names = names
        self.cycles = 0
        self.activity = {name: 0 for name in names}
        self.last = {name: 0 for name in names}
        self.first_seen = {name: {} for name in names}
        self.rises = {name: {} for name in names}
        self._task = cocotb.start_soon(self._run())

    async def _run(self) -> None:
        clk = self._seq.dut.clk_smu_i
        while True:
            await ReadOnly()
            self._record()
            await NextTimeStep()
            await ClockCycles(clk, 1)

    def _record(self) -> None:
        for name in self.names:
            value = self._seq._vec(name)
            new_bits = value & ~self.activity[name]
            while new_bits:
                bit = (new_bits & -new_bits).bit_length() - 1
                self.first_seen[name][bit] = self.cycles
                new_bits &= new_bits - 1
            rose = value & ~self.last[name]
            while rose:
                bit = (rose & -rose).bit_length() - 1
                self.rises[name][bit] = self.rises[name].get(bit, 0) + 1
                rose &= rose - 1
            self.activity[name] |= value
            self.last[name] = value
        self.cycles += 1

    def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None


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
        if name == WIRE_ASSERTED_PSEUDO_NAME:
            wire = self._vec("tb_xtrig_ctp_req_out_din")
            pull = self._vec("tb_xtrig_ctp_wire_pull")
            return (wire ^ pull) & CTP_MASK
        val = self._pin(name).value
        if not val.is_resolvable:
            raise AssertionError(f"X/Z on {name}: {val}")
        return int(val)

    @staticmethod
    def _rises_in_mask(window: "_WireOrWindow", name: str, mask: int) -> int:
        """Total rises of ``name`` across every bit set in ``mask``."""
        return sum(count for bit, count in window.rises[name].items() if (mask >> bit) & 1)

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
        if CONFIG_INVERT_RESET != 0:
            raise AssertionError(
                f"CONFIG.INVERT reset {CONFIG_INVERT_RESET} in the RDL header disagrees with "
                "the wire-OR pull-up board smu_base_test.drive_idle_inputs drives for every "
                "wire (that board assumes INVERT's reset value is 0)"
            )
        # As early as the sequence can observe: reset_done fires once the
        # bench-side wire-OR board (drive_idle_inputs) is already resting
        # every wire at its pull, so this is the earliest point wire idleness
        # is provable.
        await self._wire_or_idle()
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
        await self._wire_or_shared()

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

    async def _wire_or_idle(self) -> None:
        """CHK-SMU-CTP-WIRE-IDLE: every wire rests at its pull through reset.

        Observed as early as the sequence can run, right after
        ``cfg.reset_done``: no wire-OR port's ct_dst rises and the bench's
        pull-mismatch flag stays clear for a window long enough to cover the
        receive latency twice over plus a pad settle.
        """
        dut = self.dut
        window = _WireOrWindow(self)
        idle_cycles = 2 * CT_DST_LATENCY + PAD_SETTLE
        window.start(("tb_xtrig_ctp_ct_dst", "tb_xtrig_ctp_wire_mismatch"))
        await ClockCycles(dut.clk_smu_i, idle_cycles)
        window.stop()
        rises = sum(window.rises["tb_xtrig_ctp_ct_dst"].values())
        # activity is the OR of every sample the window took, so this is the
        # mismatch flag never having read 1 at any point in the window, not
        # merely at the one instant a single end-of-window sample would catch.
        mismatch_activity = window.activity["tb_xtrig_ctp_wire_mismatch"]
        self.sb.expect_eq(
            "CHK-SMU-CTP-WIRE-IDLE",
            (rises, mismatch_activity),
            (0, 0),
            evidence="CHK-SMU-CTP-WIRE-IDLE",
        )

    async def _wire_or_receive(self) -> None:
        """CHK-SMU-CTP-WIRE-RX: lane 2 stays wire-OR, on its private wire.

        A chiplet pull of that wire (held >= PULSE_BOUND clk_smu) must raise
        tb_xtrig_ctp_ct_dst[2] exactly CT_DST_LATENCY clocks after the wire is
        first seen asserted, once for the pull, and the release must raise
        nothing in a further PULSE_BOUND-clock window. The same pull must
        also route through to xtrig_ctm_src_req_o[0] (CHK-SMU-CTM-SRC
        restated): the pulse follows the pull, not the release.
        """
        dut = self.dut
        # Lane 2 keeps the wire-OR default, where the trigger is an edge on
        # its shared wire rather than a level on the request-in pin.
        await self._route_to_internal(1 << WIRE_OR_LANE)
        await self._wait_vec_bit(
            "xtrig_ctm_src_req", SMU_CT_LANE, 0, "internal request idle before wire-OR trigger"
        )
        # Land on a clean clk_smu edge first: window.start() and the pull that
        # follows must share the exact timestep the window's cycle 0 samples,
        # or cycle 0 stops lining up with the edge the DUT's synchronizer
        # samples and the measured latency drifts off CT_DST_LATENCY.
        await ClockCycles(dut.clk_smu_i, PAD_SETTLE)
        window = _WireOrWindow(self)
        window.start(
            (
                WIRE_ASSERTED_PSEUDO_NAME,
                "tb_xtrig_ctp_ct_dst",
                "xtrig_ctm_src_req",
                "tb_xtrig_ctp_wire_mismatch",
            )
        )
        dut.tb_xtrig_ctp_wire_ext_assert.value = 1 << WIRE_OR_LANE
        await ClockCycles(dut.clk_smu_i, PULSE_BOUND)
        dut.tb_xtrig_ctp_wire_ext_assert.value = 0
        await ClockCycles(dut.clk_smu_i, PULSE_BOUND)
        window.stop()

        # The reference is the resolved wire (via WIRE_ASSERTED_PSEUDO_NAME),
        # not the chiplet control tb_xtrig_ctp_wire_ext_assert: the two only
        # coincide because ocah_open_drain_bus is combinational.
        asserted_at = window.first_seen[WIRE_ASSERTED_PSEUDO_NAME].get(WIRE_OR_LANE)
        # The release lands exactly PULSE_BOUND window cycles after the pull:
        # one window sample is one clk_smu period, the same unit ClockCycles
        # advanced by while the wire was held.
        release_at = None if asserted_at is None else asserted_at + PULSE_BOUND
        received_at = window.first_seen["tb_xtrig_ctp_ct_dst"].get(WIRE_OR_LANE)
        latency = -1 if asserted_at is None or received_at is None else received_at - asserted_at
        rises = window.rises["tb_xtrig_ctp_ct_dst"].get(WIRE_OR_LANE, 0)
        mismatch_activity = window.activity["tb_xtrig_ctp_wire_mismatch"]
        self.log.info(
            "wire-OR lane %d: asserted@%s ct_dst@%s latency=%s rises=%d",
            WIRE_OR_LANE,
            asserted_at,
            received_at,
            latency,
            rises,
        )
        self.sb.expect_eq(
            "CHK-SMU-CTP-WIRE-RX",
            (latency, rises, mismatch_activity),
            (CT_DST_LATENCY, 1, 0),
            evidence="CHK-SMU-CTP-WIRE-RX",
        )
        ctm_first_seen = window.first_seen["xtrig_ctm_src_req"].get(SMU_CT_LANE)
        ctm_rises = window.rises["xtrig_ctm_src_req"].get(SMU_CT_LANE, 0)
        follows_pull = (
            ctm_rises == 1
            and asserted_at is not None
            and ctm_first_seen is not None
            and asserted_at <= ctm_first_seen < release_at
        )
        self.sb.expect_eq(
            "the routed request follows the wire-OR pull, not the release "
            "(CHK-SMU-CTM-SRC restated)",
            follows_pull,
            True,
            evidence="CHK-SMU-CTM-SRC",
        )
        await ClockCycles(dut.clk_smu_i, PAD_SETTLE)

    async def _wire_or_shared(self) -> None:
        """CHK-SMU-CTP-WIRE-SHARED: three wire-OR lanes share one group wire.

        (a) One chiplet pull on one member: every member's ct_dst rises
        exactly once, each CT_DST_LATENCY clocks after the wire is first seen
        asserted; every non-member lane (the P2P lanes, the private-wire
        receiver, and every lane above the group) shows no rise.
        (b) Two members pulled in overlapping windows: exactly one ct_dst per
        member, and every non-member lane still shows no rise.
        Both windows also require the mismatch flag never reads 1.
        """
        dut = self.dut
        members = WIRE_OR_SHARED_LANES
        member_mask = sum(1 << lane for lane in members)
        non_member_mask = CTP_MASK & ~member_mask
        dut.tb_xtrig_ctp_wire_group.value = member_mask
        dut.tb_xtrig_ctp_wire_group_pull.value = 1
        await ClockCycles(dut.clk_smu_i, PAD_SETTLE)

        window = _WireOrWindow(self)
        window.start(
            (WIRE_ASSERTED_PSEUDO_NAME, "tb_xtrig_ctp_ct_dst", "tb_xtrig_ctp_wire_mismatch")
        )
        dut.tb_xtrig_ctp_wire_ext_assert.value = 1 << members[0]
        await ClockCycles(dut.clk_smu_i, PULSE_BOUND)
        dut.tb_xtrig_ctp_wire_ext_assert.value = 0
        await ClockCycles(dut.clk_smu_i, PULSE_BOUND)
        window.stop()
        # The reference is the resolved wire (via WIRE_ASSERTED_PSEUDO_NAME),
        # not the chiplet control tb_xtrig_ctp_wire_ext_assert.
        asserted_at = window.first_seen[WIRE_ASSERTED_PSEUDO_NAME].get(members[0])
        for member in members:
            received_at = window.first_seen["tb_xtrig_ctp_ct_dst"].get(member)
            latency = (
                -1 if asserted_at is None or received_at is None else received_at - asserted_at
            )
            rises = window.rises["tb_xtrig_ctp_ct_dst"].get(member, 0)
            self.sb.expect_eq(
                "CHK-SMU-CTP-WIRE-SHARED",
                (latency, rises),
                (CT_DST_LATENCY, 1),
                evidence="CHK-SMU-CTP-WIRE-SHARED",
            )
        non_member_rises = self._rises_in_mask(window, "tb_xtrig_ctp_ct_dst", non_member_mask)
        self.sb.expect_eq(
            "CHK-SMU-CTP-WIRE-SHARED",
            (non_member_rises, window.activity["tb_xtrig_ctp_wire_mismatch"]),
            (0, 0),
            evidence="CHK-SMU-CTP-WIRE-SHARED",
        )

        await ClockCycles(dut.clk_smu_i, PAD_SETTLE)
        window = _WireOrWindow(self)
        window.start(("tb_xtrig_ctp_ct_dst", "tb_xtrig_ctp_wire_mismatch"))
        dut.tb_xtrig_ctp_wire_ext_assert.value = 1 << members[1]
        await ClockCycles(dut.clk_smu_i, PULSE_BOUND // 2)
        dut.tb_xtrig_ctp_wire_ext_assert.value = (1 << members[1]) | (1 << members[2])
        await ClockCycles(dut.clk_smu_i, PULSE_BOUND // 2)
        dut.tb_xtrig_ctp_wire_ext_assert.value = 1 << members[2]
        await ClockCycles(dut.clk_smu_i, PULSE_BOUND // 2)
        dut.tb_xtrig_ctp_wire_ext_assert.value = 0
        await ClockCycles(dut.clk_smu_i, PULSE_BOUND)
        window.stop()
        for member in members:
            self.sb.expect_eq(
                "CHK-SMU-CTP-WIRE-SHARED",
                window.rises["tb_xtrig_ctp_ct_dst"].get(member, 0),
                1,
                evidence="CHK-SMU-CTP-WIRE-SHARED",
            )
        non_member_rises = self._rises_in_mask(window, "tb_xtrig_ctp_ct_dst", non_member_mask)
        self.sb.expect_eq(
            "CHK-SMU-CTP-WIRE-SHARED",
            (non_member_rises, window.activity["tb_xtrig_ctp_wire_mismatch"]),
            (0, 0),
            evidence="CHK-SMU-CTP-WIRE-SHARED",
        )

        dut.tb_xtrig_ctp_wire_group.value = 0
        dut.tb_xtrig_ctp_wire_group_pull.value = 1
        await ClockCycles(dut.clk_smu_i, PAD_SETTLE)
