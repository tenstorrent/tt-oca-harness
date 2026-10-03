# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared XTRIG helpers and full VPLAN scenario sequences."""

from __future__ import annotations

from random import Random
from typing import ClassVar

import cocotb
from cocotb.triggers import ClockCycles, NextTimeStep, ReadOnly
from env.dtp_dv_cfg import DTP_INT_CT_MODE
from env.dtp_types import RESET_COUNT_CHECK_ID
from env.dtp_xtrig_agent import DtpXtrigActivityWindow
from env.dtp_xtrig_types import (
    XTRIG_CT_DST_LATENCY,
    XTRIG_CTM_END,
    XTRIG_CTM_SELECT_DEFAULT,
    XTRIG_CTM_SELECT_MASK,
    XTRIG_CTP_BASE,
    XTRIG_CTP_CONFIG_DEFAULT,
    XTRIG_CTP_CONFIG_MASK,
    XTRIG_CTP_MODE_P2P,
    XTRIG_CTP_MODE_WIRE_OR,
    XTRIG_CTP_STATUS_ACK_IN,
    XTRIG_CTP_STATUS_ACK_OUT,
    XTRIG_CTP_STATUS_BUSY,
    XTRIG_CTP_STATUS_DEFAULT,
    XTRIG_CTP_STATUS_REQ_IN,
    XTRIG_CTP_STATUS_REQ_OUT,
    XTRIG_CTP_STRETCH_DEFAULT,
    XTRIG_CTP_STRETCH_MASK,
    XTRIG_NUM_CTM_PORTS,
    XTRIG_NUM_CTP,
    XTRIG_NUM_INT_CT,
    XTRIG_UNMAPPED_BASE,
    XTRIG_WIRE_OR_ASSERT,
    XTRIG_WIRE_OR_PULL,
    DtpCtmRefModel,
    apply_wstrb,
    ctm_config_addr,
    ctm_hole_addr,
    ctp_config_addr,
    ctp_hole_addr,
    ctp_mask,
    ctp_status_addr,
    ctp_stretch_addr,
    external_ctp_port,
    internal_ct_mask,
    internal_ct_port,
    pack_ctp_config,
    project_ctp_mask,
    project_internal_mask,
)
from ocah_checker import OcahChecker
from ocah_lib import OcahKnobs

from .dtp_base_test_seq import dtp_base_test_seq

FULL_WORD = 0xFFFF_FFFF
CTM_RAND_PULSE_MAX_CYCLES = 8
CTM_RAND_LEAD_MAX_CYCLES = 3
# STATUS carries five read-only bits (cross_trigger_port.rdl).
XTRIG_CTP_STATUS_MASK = (
    XTRIG_CTP_STATUS_BUSY
    | XTRIG_CTP_STATUS_REQ_OUT
    | XTRIG_CTP_STATUS_ACK_IN
    | XTRIG_CTP_STATUS_REQ_IN
    | XTRIG_CTP_STATUS_ACK_OUT
)
STATUS_BITS = {
    "busy": XTRIG_CTP_STATUS_BUSY,
    "req_out": XTRIG_CTP_STATUS_REQ_OUT,
    "ack_in": XTRIG_CTP_STATUS_ACK_IN,
    "req_in": XTRIG_CTP_STATUS_REQ_IN,
    "ack_out": XTRIG_CTP_STATUS_ACK_OUT,
}


class dtp_xtrig_base_test_seq(dtp_base_test_seq):
    """Helpers and scenario bodies for DTP XTRIG, CTP, and CTM tests.

    ``CT_SRC[k].CONFIG_0.CT_DST_SELECT`` (cross_trigger_matrix.rdl) selects the
    CT_Dst input ports whose pulses are OR'd onto CT_Src output ``k``: CT_Src
    ports are matrix outputs, CT_Dst ports are matrix inputs. The route helpers
    therefore program ``output_port <- input_port_mask`` and log both the VPLAN
    source/destination intent and the concrete CSR mapping.

    Pad polarity follows CONFIG.INVERT. Point-to-point request and
    acknowledge pads of an inverted CTP idle high and assert low, so every
    such pad the sequences drive goes through ``pad_level``. A wire-OR pad
    sits on the bench's open-drain shared wire: the wire rests at the pull of
    the board built for the CTP's sense (``XTRIG_WIRE_OR_PULL``, high for
    INVERT=0) and a chiplet driver pulls it to the asserted level, so the
    sequences never drive that pad's level; the port receives a trigger
    ``XTRIG_CT_DST_LATENCY`` cycles after the wire is pulled and nothing when
    it is released. The idle levels and the board pulls are re-applied
    whenever a CTP is programmed.
    """

    AXI_OKAY = 0
    AXI_DECERR = 3
    # Nonzero CONFIG words the CTP CSR sweep writes as byte-strobe bases,
    # neighbour words, and final words. MODE|INVERT is left out: the sweep
    # leaves the bench pads at their non-inverted idle levels, which an
    # inverted point-to-point receiver reads as a request.
    CTP_SWEEP_CONFIGS = (
        pack_ctp_config(mode=XTRIG_CTP_MODE_P2P),
        pack_ctp_config(invert=1),
        pack_ctp_config(reset=1),
        pack_ctp_config(mode=XTRIG_CTP_MODE_P2P, reset=1),
        pack_ctp_config(invert=1, reset=1),
    )
    # The internal-lane requests and the CTP request and acknowledge enables.
    # The internal lanes run in pulse mode, where their acknowledge is unused.
    QUIET_GROUPS = (
        "xtrig_ctm_src_req",
        "xtrig_ctp_req_out_dout_en",
        "xtrig_ctp_ack_out_dout_en",
    )
    # Observables a routed pulse can reach, plus the inputs the bench drives
    # (the wire pulls, the point-to-point request pads, and the internal
    # requests) and the receive pulses, which date each output against the
    # window's first input and each receive edge; the activity window ORs
    # them per cycle from before the input pulse until the drain tail ends.
    OUTPUT_SIGNALS = (
        "xtrig_ctm_src_req",
        "xtrig_ctp_req_out_dout",
        "xtrig_ctp_req_out_dout_en",
        "xtrig_ctp_wire_ext_assert",
        "xtrig_ctp_req_in_din",
        "xtrig_ctm_dst_req",
        "xtrig_ctp_ct_dst",
        "xtrig_int_ct_dst",
    )
    # Observables that must show no activity from the first held cycle of a
    # system reset until after its release: every request and acknowledge
    # output, the CTP busy flops, and every port's receive pulse.
    RESET_SIGNALS = (
        "xtrig_ctm_src_req",
        "xtrig_ctp_req_out_dout_en",
        "xtrig_ctp_ack_out_dout_en",
        "xtrig_ctp_req_out_dout",
        "xtrig_ctp_ack_out_dout",
        "xtrig_ctp_busy",
        "xtrig_ctp_ct_dst",
        "xtrig_int_ct_dst",
    )
    # The reset observables that move with every CTP in wire-OR mode, where
    # the acknowledge pads are static.
    RESET_SIGNALS_WIRE_OR = (
        "xtrig_ctm_src_req",
        "xtrig_ctp_req_out_dout_en",
        "xtrig_ctp_req_out_dout",
        "xtrig_ctp_busy",
        "xtrig_ctp_ct_dst",
        "xtrig_int_ct_dst",
    )
    # Observables that must show no activity while a CSR access is in flight:
    # the internal-lane requests, the CTP request and acknowledge enables,
    # and the CTP busy flops. The pad levels are left out because they follow
    # the polarity CSR the accesses write.
    IN_FLIGHT_SIGNALS = QUIET_GROUPS + ("xtrig_ctp_busy",)
    # The port observables that stay idle while CONFIG.RESET holds a
    # point-to-point port and across its release.
    CONFIG_RESET_SIGNALS = ("xtrig_ctp_req_out_dout", "xtrig_ctp_ack_out_dout", "xtrig_ctp_busy")
    # Crossbar demux state watched across a two-outstanding write.
    DEMUX_SIGNALS = ("xtrig_demux_aw_lock", "xtrig_demux_w_pending")
    # CSR port, spill-register and crossbar demux counters judged as deltas
    # across a two-outstanding write and a two-outstanding read.
    AW_PAIR_COUNTERS = (
        "xtrig_axil_aw_stall_count",
        "xtrig_axil_aw_open_stall_count",
        "xtrig_axil_aw_open_accept_count",
        "xtrig_axil_spill_err_count",
        "xtrig_axil_w_spill_full_count",
        "xtrig_demux_aw_open_stall_count",
        "xtrig_demux_aw_open_accept_count",
    )
    AR_PAIR_COUNTERS = (
        "xtrig_axil_ar_stall_count",
        "xtrig_axil_arvalid_count",
        "xtrig_axil_ar_open_stall_count",
        "xtrig_axil_ar_open_accept_count",
        "xtrig_axil_spill_err_count",
        "xtrig_axil_r_spill_full_count",
        "xtrig_demux_ar_open_stall_count",
        "xtrig_demux_ar_open_accept_count",
    )
    # Cycles the window stays open after the last expected output, so a late
    # or stretched pulse on any port is inside it.
    ISOLATION_TAIL_CYCLES = 6
    # Seeded range of the cycles BREADY waits after a skewed write's request
    # phase: longer than the write response takes to reach the CSR port, so
    # the port holds the response.
    SKEW_B_READY_DELAY = (5, 8)
    # Seeded range of the cycles the bench holds a point-to-point handshake
    # phase, one draw per phase: an acknowledge withheld from a request, an
    # acknowledge held after its request falls, and a request held after its
    # acknowledge rises.
    P2P_HOLD_MIN_CYCLES = 4
    P2P_HOLD_MAX_CYCLES = 16
    # Cycles within which a point-to-point pad or BUSY edge follows the peer
    # edge that causes it. The bound is below the span of the seeded holds,
    # so an edge timed from anything but the peer edge falls outside it on
    # some draw.
    P2P_PHASE_MAX_CYCLES = 8
    # Pending routes of a random mix, as (source, destination) in a seeded
    # order, kept across the passes of the test: each iteration starts from
    # the first pending route, and only a window whose one input is a
    # route's source retires that route.
    _route_pending: ClassVar[dict[str, list[tuple[int, int]]]] = {}
    # The routes of a random mix that a single-source window has driven in
    # the test.
    _route_driven: ClassVar[dict[str, set[tuple[int, int]]]] = {}
    # The random mixes whose last pass continues until every route of their
    # class has been driven alone.
    ROUTE_WALK_MIXES = ("cla_to_ctp", "ctp_to_cla")
    # STRETCH_MULT the route helpers program on every external CTP they use;
    # the internal CTPs carry the same multiplier (cross_trigger_network), so
    # every routed pulse is two cycles wide.
    ROUTE_STRETCH_MULT = 1
    # A STATUS read issued once the output enable has risen lands several
    # cycles later on the CSR path, so BUSY=1 is read back over the CSR only
    # for pulses at least this many cycles wide (STRETCH_MULT + 1); the busy
    # flop mirror covers every width cycle for cycle.
    BUSY_READ_MIN_STRETCH = 8
    # STRETCH_MULT of the pulse a system reset lands on: wide enough that the
    # output enable is active when the reset asserts.
    RESET_HOLD_STRETCH = 0xFFFF
    # The first iterations of the random CTP configuration test, as (MODE,
    # INVERT, lowest STRETCH_MULT, highest STRETCH_MULT): every pass runs a
    # point-to-point port at both pad polarities and an inverted wire-OR port
    # at the single-cycle width and a stretched one.
    RANDOM_HEAD = (
        (XTRIG_CTP_MODE_WIRE_OR, 1, 0, 0),
        (XTRIG_CTP_MODE_P2P, 0, 0, 7),
        (XTRIG_CTP_MODE_WIRE_OR, 1, 1, 7),
        (XTRIG_CTP_MODE_P2P, 1, 0, 7),
    )

    # Named-evidence IDs recorded by the shared helpers below. finalize() at
    # the end of body() rejects a zero-check run and any missing required ID,
    # so a scenario whose checks were silently skipped fails.
    CHK_CSR = "CHK-XTRIG-CSR"
    CHK_SIGNAL = "CHK-XTRIG-SIGNAL"
    CHK_ROUTE_MODEL = "CHK-XTRIG-ROUTE-MODEL"
    CHK_ISOLATION = "CHK-XTRIG-ISOLATION"
    CHK_QUIET = "CHK-XTRIG-QUIET"
    CHK_STRETCH = "CHK-XTRIG-STRETCH"
    CHK_AXIL = "CHK-XTRIG-AXIL"
    CHK_AW_LOCK = "CHK-XTRIG-AW-LOCK"
    CHK_AR_STALL = "CHK-XTRIG-AR-STALL"
    CHK_WIRE = "CHK-XTRIG-WIRE"
    CHK_RESET_COUNT = RESET_COUNT_CHECK_ID

    # DTP_XTRIG_NEGATIVE_CHECK=<n> is the per-check negative-validation hook:
    # every record of the evidence ID at index n is written with a corrupted
    # observed value, so that ID must fail wherever the scenario records it.
    NEGATIVE_CHECK_INDEX = {
        CHK_CSR: 1,
        CHK_SIGNAL: 2,
        CHK_ROUTE_MODEL: 3,
        CHK_ISOLATION: 4,
        CHK_QUIET: 5,
        CHK_STRETCH: 6,
        CHK_AXIL: 7,
        CHK_AW_LOCK: 8,
        CHK_AR_STALL: 9,
        CHK_WIRE: 10,
    }

    _ROUTE_IDS = (CHK_CSR, CHK_SIGNAL, CHK_ROUTE_MODEL, CHK_ISOLATION)
    _WIRE_OR_ROUTE_IDS = _ROUTE_IDS + (CHK_STRETCH, CHK_WIRE)
    SCENARIO_REQUIRED_IDS = {
        "reg_stall": (CHK_CSR, CHK_SIGNAL, CHK_QUIET, CHK_AXIL),
        "axi_channel_skew": (CHK_CSR, CHK_AXIL),
        "axi_channel_skew_demux_aw_lock_release": (CHK_AXIL, CHK_AW_LOCK),
        "axi_channel_skew_read_decode_backpressure": (CHK_AXIL, CHK_AR_STALL),
        "ctp_csr_sweep": _ROUTE_IDS + (CHK_STRETCH,),
        "ctm_csr_sweep": _ROUTE_IDS,
        "ctm_all_source_select": _ROUTE_IDS,
        "wire_or": (CHK_CSR, CHK_SIGNAL, CHK_STRETCH, CHK_ROUTE_MODEL, CHK_WIRE),
        "wire_or_bus": _ROUTE_IDS + (CHK_WIRE,),
        "p2p": (CHK_CSR, CHK_SIGNAL),
        "random": _ROUTE_IDS + (CHK_STRETCH,),
        "reset": _ROUTE_IDS + (CHK_QUIET, CHK_RESET_COUNT),
        "dst_port_sweep": _ROUTE_IDS,
        "ctm_wire_or_cla_to_ctp": _WIRE_OR_ROUTE_IDS,
        "ctm_wire_or_ctp_to_cla": _WIRE_OR_ROUTE_IDS,
        "ctm_wire_or_cla_to_cla": _WIRE_OR_ROUTE_IDS,
        "ctm_wire_or_ctp_to_ctp": _WIRE_OR_ROUTE_IDS,
        "ctm_p2p_cla_to_ctp": _ROUTE_IDS,
        "ctm_p2p_ctp_to_cla": _ROUTE_IDS,
        "ctm_p2p_cla_to_cla": _ROUTE_IDS,
        "ctm_p2p_ctp_to_ctp": _ROUTE_IDS,
        "ctm_reset_wire_or_mode": _ROUTE_IDS + (CHK_QUIET, CHK_WIRE, CHK_RESET_COUNT),
        "ctm_reset_p2p_mode": _ROUTE_IDS + (CHK_QUIET, CHK_RESET_COUNT),
        "ctm_reset_all_modes": _ROUTE_IDS + (CHK_QUIET, CHK_RESET_COUNT),
        "ctm_rand_all_scenarios": _ROUTE_IDS,
        "ctm_rand_wire_or_only": _ROUTE_IDS + (CHK_WIRE,),
        "ctm_rand_p2p_only": _ROUTE_IDS,
        "ctm_rand_cla_to_ctp": _ROUTE_IDS,
        "ctm_rand_ctp_to_cla": _ROUTE_IDS,
    }

    def __init__(
        self,
        name: str = "dtp_xtrig_base_test_seq",
        *,
        scenario: str = "reg_stall",
        total_passes: int = 0,
        **kwargs,
    ) -> None:
        super().__init__(name, **kwargs)
        self.scenario = scenario
        # Passes the test runs; the random mixes of ROUTE_WALK_MIXES need it
        # to find their last pass.
        self.total_passes = total_passes
        self._p2p_hold_rngs: dict[str, Random] = {}
        self.ctm_model = DtpCtmRefModel()
        # Named-evidence checker: every route observation, CSR readback, quiet
        # window, and stretch measurement lands one evidence record; body()
        # finalizes so a check-free pass cannot report PASS.
        self.checker = OcahChecker(
            name=f"dtp_xtrig_checker[{name}]",
            required_ids=self.SCENARIO_REQUIRED_IDS[scenario],
            logger=self.log,
        )

    @property
    def axil(self):
        assert self.cfg.xtrig_axil is not None, "XTRIG AXI-Lite BFM is not ready"
        return self.cfg.xtrig_axil

    @property
    def xtrig(self):
        assert self.cfg.xtrig_bfm is not None, "XTRIG GPIO BFM is not ready"
        return self.cfg.xtrig_bfm

    async def body(self) -> None:
        scenario_fn = getattr(self, f"run_{self.scenario}", None)
        if scenario_fn is None:
            raise ValueError(f"unknown XTRIG scenario {self.scenario}")
        await scenario_fn()
        # Every CSR port spill register has kept READY and VALID matched to the
        # beats it holds since the last system reset.
        sample = await self.xtrig.sample()
        self.check_evidence(
            self.CHK_AXIL, "spill_contract_all", sample["xtrig_axil_spill_err_count"], 0
        )
        # End-of-sequence enforcement: zero recorded checks or a missing
        # required evidence ID fails the pass — a silently skipped check net
        # cannot report PASS.
        self.checker.finalize()

    def check_evidence(
        self, check_id: str, name: str, observed: int, expected: int, *, context: str = ""
    ) -> None:
        """Record one named evidence comparison (raises on mismatch)."""
        negative = OcahKnobs.get_int("DTP_XTRIG_NEGATIVE_CHECK", 0)
        if negative != 0 and negative == self.NEGATIVE_CHECK_INDEX.get(check_id, 0):
            self.log.warning(
                "NEGATIVE VALIDATION: %s observed 0x%x recorded as 0x%x",
                check_id,
                observed,
                observed ^ 1,
            )
            observed ^= 1
        self.checker.expect_equal(check_id, observed, expected, context=f"{name} {context}".strip())

    def check_reset_counted(self, counter: str, before: int, after: int, context: str) -> None:
        """``CHK-RESET-COUNT`` under the cross-trigger checker."""
        self.checker.expect_equal(
            self.CHK_RESET_COUNT,
            after - before,
            1,
            context=f"{counter} before={before} after={after} {context}",
        )

    @staticmethod
    def require_pulse_mode_lanes(where: str) -> None:
        """The quiet and reset observable lists leave out the internal-lane acknowledge, which only a pulse-mode lane leaves unused."""
        if DTP_INT_CT_MODE != 0:
            raise ValueError(
                f"{where}: handshake-mode internal lanes (INT_CT_MODE=0x{DTP_INT_CT_MODE:x}) "
                "need their acknowledge watched"
            )

    # ------------------------------------------------------------------
    # CSR helpers
    # ------------------------------------------------------------------
    async def csr_write(self, addr: int, data: int, *, wstrb: int = 0xF, label: str = "") -> int:
        resp = await self.axil.write(addr, data, strb=wstrb)
        self.log.info(
            "XTRIG CSR WRITE %-34s addr=0x%03x data=0x%08x wstrb=0x%x resp=%d",
            label,
            addr,
            data & FULL_WORD,
            wstrb & 0xF,
            resp,
        )
        self.assert_equal(f"{label or hex(addr)}.bresp", resp, self.AXI_OKAY)
        return resp

    async def csr_read(self, addr: int, *, label: str = "") -> int:
        result = await self.axil.read_result(addr)
        data, resp = result.data, result.resp
        self.log.info(
            "XTRIG CSR READ  %-34s addr=0x%03x data=0x%08x resp=%d",
            label,
            addr,
            data,
            resp,
        )
        self.assert_equal(f"{label or hex(addr)}.rresp", resp, self.AXI_OKAY)
        return data

    async def write_read_check(
        self,
        addr: int,
        data: int,
        expected: int,
        *,
        wstrb: int = 0xF,
        mask: int = FULL_WORD,
        label: str = "",
    ) -> int:
        await self.csr_write(addr, data, wstrb=wstrb, label=label)
        observed = await self.csr_read(addr, label=label)
        self.check_evidence(
            self.CHK_CSR,
            label or f"csr_0x{addr:x}",
            observed & mask,
            expected & mask,
            context=f"addr=0x{addr:03x} wstrb=0x{wstrb:x}",
        )
        return observed

    async def check_status(self, ctp_idx: int, label: str, **expected_bits: int) -> int:
        """Read STATUS and record every named field (busy, req_out, ack_in, req_in, ack_out)."""
        status = await self.csr_read(ctp_status_addr(ctp_idx), label=f"{label}.status")
        self.log.info("%s decoded status %s", label, self.xtrig.decode_status(status))
        for name, expected in expected_bits.items():
            self.check_evidence(
                self.CHK_CSR,
                f"{label}.status.{name}",
                int(bool(status & STATUS_BITS[name])),
                expected,
                context=f"ctp={ctp_idx}",
            )
        return status

    async def program_ctp(
        self,
        ctp_idx: int,
        *,
        mode: int = XTRIG_CTP_MODE_WIRE_OR,
        invert: int = 0,
        reset: int = 0,
        stretch: int = 0,
    ) -> None:
        cfg = pack_ctp_config(mode=mode, invert=invert, reset=reset)
        self.cfg.xtrig_ctp_shadow.note(ctp_idx, mode=mode, invert=invert)
        self.log.info(
            "Configure CTP[%d]: mode=%s invert=%d reset=%d stretch=%d (wire rests at %d)",
            ctp_idx,
            "p2p" if mode else "wire_or",
            invert,
            reset,
            stretch,
            XTRIG_WIRE_OR_PULL[invert],
        )
        # The board comes first: the wire rests at the pull of the new sense
        # before software sets INVERT to match it.
        self.xtrig.set_ctp_wire_pull(self.cfg.xtrig_ctp_shadow.wire_pull_mask)
        await self.write_read_check(
            ctp_config_addr(ctp_idx),
            cfg,
            cfg,
            mask=XTRIG_CTP_CONFIG_MASK,
            label=f"ctp{ctp_idx}.config",
        )
        await self.write_read_check(
            ctp_stretch_addr(ctp_idx),
            stretch,
            stretch,
            mask=XTRIG_CTP_STRETCH_MASK,
            label=f"ctp{ctp_idx}.stretch",
        )
        self.apply_idle_levels()

    async def program_ctm_src(self, output_port: int, input_mask: int) -> None:
        input_mask &= XTRIG_CTM_SELECT_MASK
        model_mask = input_mask
        # DTP_XTRIG_CHECKER_NEGATIVE=1 is the documented negative-validation
        # hook: the reference model is programmed with an INVERTED select so
        # CHK-XTRIG-ROUTE-MODEL must fail, proving the model comparison gates
        # pass/fail end to end (route scenarios only).
        if OcahKnobs.is_set("DTP_XTRIG_CHECKER_NEGATIVE"):
            model_mask = (~input_mask) & XTRIG_CTM_SELECT_MASK
            self.log.warning(
                "NEGATIVE VALIDATION: CTM model select 0x%x instead of 0x%x",
                model_mask,
                input_mask,
            )
        self.ctm_model.program(output_port, model_mask)
        await self.write_read_check(
            ctm_config_addr(output_port),
            input_mask,
            input_mask,
            mask=XTRIG_CTM_SELECT_MASK,
            label=f"ctm.output{output_port}.select",
        )

    async def clear_ctm_routes(self) -> None:
        self.ctm_model = DtpCtmRefModel()
        for src_idx in range(XTRIG_NUM_CTM_PORTS):
            await self.csr_write(ctm_config_addr(src_idx), 0, label=f"clear.ctm{src_idx}")

    async def clear_xtrig(self) -> None:
        await self.xtrig.clear_inputs()
        self.cfg.xtrig_ctp_shadow.clear()
        for ctp_idx in range(XTRIG_NUM_CTP):
            await self.csr_write(ctp_config_addr(ctp_idx), 0, label=f"cleanup.ctp{ctp_idx}.cfg")
            await self.csr_write(
                ctp_stretch_addr(ctp_idx), 0, label=f"cleanup.ctp{ctp_idx}.stretch"
            )
        await self.clear_ctm_routes()

    async def reset_window(
        self,
        label: str,
        *,
        watched: tuple[str, ...],
        live: DtpXtrigActivityWindow,
        cycles: int = 3,
    ) -> None:
        """System reset watched from its first held cycle until after release.

        ``live`` is a window over ``watched`` that the scenario started before
        the traffic the reset lands on: every watched observable is active in
        it (CHK-XTRIG-SIGNAL), and none of them moves while the reset holds or
        for ``cycles + 2`` cycles after release (CHK-XTRIG-QUIET). The reset
        is counted (CHK-RESET-COUNT) and the CSR shadows reset with the DUT.
        """
        self.require_pulse_mode_lanes("reset_window")
        missing = set(watched) - set(live.names)
        if missing:
            raise ValueError(f"reset_window {label}: the live window does not sample {missing}")
        activity, _hold, _last = await live.stop()
        for name in watched:
            self.check_evidence(
                self.CHK_SIGNAL,
                f"reset_window.{label}.{name}.live_before",
                int(activity[name] != 0),
                1,
                context=f"cycles={live.cycles}",
            )
        before = self.cfg.tb_if.sample("sys_rst_assert_count")
        self.xtrig.init_signals()
        self.xtrig.set_sys_reset(active=True)
        await ClockCycles(self.xtrig.clk, 1)
        window = self.xtrig.activity_window(watched)
        window.start()
        await ClockCycles(self.xtrig.clk, cycles - 1)
        self.xtrig.set_sys_reset(active=False)
        self.ctm_model = DtpCtmRefModel()
        self.cfg.xtrig_ctp_shadow.clear()
        await ClockCycles(self.xtrig.clk, cycles + 2)
        activity, _hold, _last = await window.stop()
        self.check_reset_counted(
            "sys_rst_assert_count",
            before,
            self.cfg.tb_if.sample("sys_rst_assert_count"),
            f"reset_window.{label} cycles={cycles}",
        )
        for name in watched:
            self.check_evidence(
                self.CHK_QUIET,
                f"reset_window.{label}.{name}",
                activity.get(name, 0),
                0,
                context=f"cycles={window.cycles}",
            )

    async def check_ctp_defaults(self, label: str) -> None:
        """Every CTP CONFIG, STRETCH_MULT, and STATUS reads its reset value."""
        registers = (
            ("config", ctp_config_addr, XTRIG_CTP_CONFIG_MASK, XTRIG_CTP_CONFIG_DEFAULT),
            ("stretch", ctp_stretch_addr, XTRIG_CTP_STRETCH_MASK, XTRIG_CTP_STRETCH_DEFAULT),
            ("status", ctp_status_addr, XTRIG_CTP_STATUS_MASK, XTRIG_CTP_STATUS_DEFAULT),
        )
        for ctp_idx in range(XTRIG_NUM_CTP):
            for name, register_addr, mask, default in registers:
                addr = register_addr(ctp_idx)
                observed = await self.csr_read(addr, label=f"{label}.ctp{ctp_idx}.{name}")
                self.check_evidence(
                    self.CHK_CSR,
                    f"{label}.ctp{ctp_idx}.{name}.default",
                    observed & mask,
                    default & mask,
                    context=f"addr=0x{addr:03x}",
                )

    # ------------------------------------------------------------------
    # Protocol helpers
    # ------------------------------------------------------------------
    @staticmethod
    def is_ctp_port(port: int) -> bool:
        return 0 <= port < XTRIG_NUM_CTP

    @staticmethod
    def int_idx_from_port(port: int) -> int:
        return port - XTRIG_NUM_CTP

    @staticmethod
    def port_bits(mask: int) -> list[int]:
        return [port for port in range(XTRIG_NUM_CTM_PORTS) if (mask >> port) & 1]

    def _ctp_p2p_mask(self) -> int:
        return self.cfg.xtrig_ctp_shadow.p2p_mask

    def _ctp_invert_mask(self) -> int:
        return self.cfg.xtrig_ctp_shadow.invert_mask

    def pad_level(self, ctp_mask_: int, *, asserted: bool) -> int:
        """Point-to-point pad levels of ``ctp_mask_``: asserted high and idle low, inverted CTPs the reverse."""
        inverted = self._ctp_invert_mask()
        return (ctp_mask_ & ~inverted) if asserted else (ctp_mask_ & inverted)

    def apply_idle_levels(self) -> None:
        """Rest every point-to-point pad at its idle level and every wire at its board's pull."""
        inverted = self._ctp_invert_mask()
        self.xtrig.set_ctp_req_in_din(inverted)
        self.xtrig.set_ctp_ack_in_din(inverted)
        self.xtrig.set_ctp_wire_pull(self.cfg.xtrig_ctp_shadow.wire_pull_mask)

    async def idle_inputs(self) -> None:
        """Return every driven cross-trigger input to its idle level.

        The idle levels are written in the same time step as the quiesce, so
        an inverted point-to-point pad never passes through its asserted low
        level.
        """
        self.xtrig.init_signals()
        self.apply_idle_levels()
        await ClockCycles(self.xtrig.clk, 1)

    async def drive_p2p_req_in(self, ctp_idx: int, *, asserted: bool) -> None:
        level = self.pad_level(1 << ctp_idx, asserted=asserted) >> ctp_idx
        await self.xtrig.drive_ctp_p2p_req_in(ctp_idx, level)

    async def drive_p2p_ack_in(self, ctp_idx: int, *, asserted: bool) -> None:
        level = self.pad_level(1 << ctp_idx, asserted=asserted) >> ctp_idx
        await self.xtrig.drive_ctp_p2p_ack_in(ctp_idx, level)

    async def sample_xtrig(self, label: str) -> dict[str, int]:
        sample = await self.xtrig.sample()
        self.log.info(
            "XTRIG SAMPLE %-28s ctm_src_req=0x%03x req_out_en=0x%04x req_out=0x%04x ack_out=0x%04x",
            label,
            sample.get("xtrig_ctm_src_req", 0),
            sample.get("xtrig_ctp_req_out_dout_en", 0),
            sample.get("xtrig_ctp_req_out_dout", 0),
            sample.get("xtrig_ctp_ack_out_dout", 0),
        )
        return sample

    async def wait_signal_mask(
        self,
        name: str,
        mask: int,
        expected: int,
        *,
        cycles: int = 60,
        label: str = "",
    ) -> int:
        observed = 0
        for _ in range(cycles):
            await ReadOnly()
            observed = self.xtrig.sample_signal(name) & mask
            await ClockCycles(self.xtrig.clk, 1)
            if observed == (expected & mask):
                self.log.info("Observed %s mask=0x%x expected=0x%x %s", name, mask, expected, label)
                break
        else:
            await ReadOnly()
            observed = self.xtrig.sample_signal(name) & mask
        self.check_evidence(
            self.CHK_SIGNAL, f"{name}.mask", observed, expected & mask, context=label
        )
        return observed

    async def check_quiet(self, label: str, *, cycles: int = 4) -> None:
        activity = await self.xtrig.assert_quiet(self.QUIET_GROUPS, cycles=cycles)
        for name, value in activity.items():
            self.check_evidence(
                self.CHK_QUIET, f"quiet.{label}.{name}", value, 0, context=f"cycles={cycles}"
            )

    async def configure_ctp_mode_for_port(
        self, port: int, mode: int, *, stretch: int = ROUTE_STRETCH_MULT
    ) -> None:
        """Program an external CTP port for a route; internal ports have no CONFIG."""
        if not self.is_ctp_port(port):
            return
        if mode == XTRIG_CTP_MODE_P2P:
            # The handshake sender latches every delivered trigger whatever the
            # mode, and only an acknowledge or CONFIG.RESET releases it, so a
            # port entering P2P mode would otherwise present a request left
            # pending from wire-OR routing. RESET is a level: assert, then program.
            await self.csr_write(
                ctp_config_addr(port),
                pack_ctp_config(mode=mode, reset=1),
                label=f"ctp{port}.handshake_reset",
            )
        await self.program_ctp(port, mode=mode, stretch=stretch)

    async def configure_ctp_modes_for_route(
        self, input_port: int, output_mask: int, mode: int
    ) -> None:
        await self.configure_ctp_modes_for_route_mask(1 << input_port, output_mask, mode)

    async def configure_ctp_modes_for_route_mask(
        self, input_mask: int, output_mask: int, mode: int
    ) -> None:
        for port in self.port_bits(input_mask | output_mask):
            await self.configure_ctp_mode_for_port(port, mode)

    async def program_route(self, input_port: int, output_mask: int, *, label: str) -> None:
        await self.program_routes(1 << input_port, output_mask, label=label)

    async def program_routes(self, input_mask: int, output_mask: int, *, label: str) -> None:
        """Select ``input_mask`` on every output of ``output_mask`` (multi-bit = wire-OR merge)."""
        self.log.info(
            "Program CTM route %-20s input_mask=0x%08x output_mask=0x%08x (CSR output selects inputs)",
            label,
            input_mask,
            output_mask,
        )
        await self.clear_ctm_routes()
        for output_port in self.port_bits(output_mask):
            await self.program_ctm_src(output_port, input_mask)

    async def drive_input_port(self, input_port: int, mode: int, *, cycles: int = 2) -> None:
        await self.drive_input_mask(1 << input_port, mode, cycles=cycles)

    async def drive_input_mask(
        self, input_mask: int, mode: int, *, cycles: int = 2, label: str = ""
    ) -> None:
        """Pulse every input of ``input_mask`` in the same cycles; a P2P CTP source raises its request pad.

        A wire-OR CTP source has its shared wire pulled by the chiplet on it;
        internal sources request through a pulse in every mode. The bench is
        the four-phase sender of a P2P CTP source: CT_Ack_out is idle before
        the request and asserts within ``P2P_PHASE_MAX_CYCLES`` of it, the
        request stays up for ``cycles`` and for a seeded
        ``p2p_hold_cycles()`` after CT_Ack_out asserts, and CT_Ack_out stays
        asserted until the release and drops within ``P2P_PHASE_MAX_CYCLES``
        of it.
        """
        ctp_bits = project_ctp_mask(input_mask)
        if mode == XTRIG_CTP_MODE_P2P and ctp_bits:
            ports = self.port_bits(ctp_bits)
            assert len(ports) == 1 and input_mask == ctp_bits, "a P2P request is one CTP source"
            invert = self._ctp_invert_mask()
            await ReadOnly()
            ack_before = self.xtrig.sample_signal("xtrig_ctp_ack_out_dout") & ctp_bits
            await NextTimeStep()
            self.check_evidence(
                self.CHK_SIGNAL,
                f"{label}.src_ack_idle_before",
                ack_before,
                self.pad_level(ctp_bits, asserted=False),
            )
            await self.drive_p2p_req_in(ports[0], asserted=True)
            ack, rose_at = await self.wait_p2p_phase(
                "xtrig_ctp_ack_out_dout", ctp_bits, ctp_bits, invert=invert
            )
            self.check_evidence(
                self.CHK_SIGNAL,
                f"{label}.src_ack",
                ack,
                ctp_bits,
                context=f"CT_Ack_out asserted {rose_at} cycles after CT_Req_in",
            )
            hold = max(self.p2p_hold_cycles("req_hold"), cycles - rose_at)
            held = ack
            for _ in range(hold):
                await ClockCycles(self.xtrig.clk, 1)
                await ReadOnly()
                held &= self.xtrig.sample_signal("xtrig_ctp_ack_out_dout") ^ invert
            await NextTimeStep()
            self.check_evidence(
                self.CHK_SIGNAL,
                f"{label}.src_ack_held",
                held,
                ctp_bits,
                context=f"CT_Req_in held {hold} cycles after CT_Ack_out asserted",
            )
            await self.drive_p2p_req_in(ports[0], asserted=False)
            ack, fell_at = await self.wait_p2p_phase(
                "xtrig_ctp_ack_out_dout", ctp_bits, 0, invert=invert
            )
            self.check_evidence(
                self.CHK_SIGNAL,
                f"{label}.src_ack_idle",
                ack,
                0,
                context=f"CT_Ack_out fell {fell_at} cycles after CT_Req_in released",
            )
            return
        await self.xtrig.pulse_input_mask(
            project_ctp_mask(input_mask), project_internal_mask(input_mask), cycles=cycles
        )

    def check_receive_edges(
        self,
        window: DtpXtrigActivityWindow,
        *,
        ctp_sources: int,
        int_sources: int,
        label: str,
    ) -> None:
        """Every wire-OR source received its own assertion once, at the receive latency.

        A CTP source's wire is pulled by its chiplet, an internal source's
        CLA request rises; the port's ct_dst rises ``XTRIG_CT_DST_LATENCY``
        cycles later and never again in the window (CHK-XTRIG-WIRE).
        """
        for ctp_idx in self.port_bits(ctp_sources):
            self._check_receive_edge(
                window,
                assert_name="xtrig_ctp_wire_ext_assert",
                receive_name="xtrig_ctp_ct_dst",
                bit=ctp_idx,
                label=f"{label}.ctp{ctp_idx}",
            )
        for int_idx in self.port_bits(int_sources):
            self._check_receive_edge(
                window,
                assert_name="xtrig_ctm_dst_req",
                receive_name="xtrig_int_ct_dst",
                bit=int_idx,
                label=f"{label}.int{int_idx}",
            )

    def _check_receive_edge(
        self,
        window: DtpXtrigActivityWindow,
        *,
        assert_name: str,
        receive_name: str,
        bit: int,
        label: str,
        asserted_at: int | None = None,
    ) -> None:
        if asserted_at is None:
            asserted_at = window.first_seen[assert_name].get(bit)
        received_at = window.first_seen[receive_name].get(bit)
        latency = -1 if asserted_at is None or received_at is None else received_at - asserted_at
        self.check_evidence(
            self.CHK_WIRE,
            f"{label}.ct_dst_latency",
            latency,
            XTRIG_CT_DST_LATENCY,
            context=f"asserted@{asserted_at} ct_dst@{received_at}",
        )
        self.check_evidence(
            self.CHK_WIRE,
            f"{label}.ct_dst_pulses",
            window.rises[receive_name].get(bit, 0),
            1,
            context="one receive per wire assertion",
        )

    def fired_vector(self, activity: dict[str, int], hold: dict[str, int]) -> int:
        """CTM-port vector of every output that requested at some cycle of the window.

        A wire-OR CTP requests through its output enable; a P2P CTP through its
        request level, which idles low (or high when inverted). Internal ports
        request through ``xtrig_ctm_src_req``.
        """
        all_ctp = (1 << XTRIG_NUM_CTP) - 1
        p2p = self._ctp_p2p_mask()
        inverted = self._ctp_invert_mask()
        dout_any = activity.get("xtrig_ctp_req_out_dout", 0)
        dout_all = hold.get("xtrig_ctp_req_out_dout", 0)
        p2p_fired = ((dout_any & ~inverted) | (~dout_all & inverted)) & p2p
        wire_or_fired = activity.get("xtrig_ctp_req_out_dout_en", 0) & ~p2p
        int_fired = activity.get("xtrig_ctm_src_req", 0) & ((1 << XTRIG_NUM_INT_CT) - 1)
        return ((p2p_fired | wire_or_fired) & all_ctp) | (int_fired << XTRIG_NUM_CTP)

    def level_vector(self, sample: dict[str, int]) -> int:
        """CTM-port vector of every output requesting in one sample."""
        all_ctp = (1 << XTRIG_NUM_CTP) - 1
        p2p = self._ctp_p2p_mask()
        inverted = self._ctp_invert_mask()
        p2p_level = (sample.get("xtrig_ctp_req_out_dout", 0) ^ inverted) & p2p
        wire_or_level = sample.get("xtrig_ctp_req_out_dout_en", 0) & ~p2p
        int_level = sample.get("xtrig_ctm_src_req", 0) & ((1 << XTRIG_NUM_INT_CT) - 1)
        return ((p2p_level | wire_or_level) & all_ctp) | (int_level << XTRIG_NUM_CTP)

    def input_vector(self, sample: dict[str, int]) -> int:
        """CTM-port vector of every input the bench asserts in one sample.

        A wire-OR CTP input is its chiplet's pull of the wire, a P2P CTP input
        its request pad at the port's polarity, and an internal input its CLA
        request.
        """
        all_ctp = (1 << XTRIG_NUM_CTP) - 1
        p2p = self._ctp_p2p_mask()
        inverted = self._ctp_invert_mask()
        wire_or_input = sample.get("xtrig_ctp_wire_ext_assert", 0) & ~p2p
        p2p_input = (sample.get("xtrig_ctp_req_in_din", 0) ^ inverted) & p2p
        int_input = sample.get("xtrig_ctm_dst_req", 0) & ((1 << XTRIG_NUM_INT_CT) - 1)
        return ((wire_or_input | p2p_input) & all_ctp) | (int_input << XTRIG_NUM_CTP)

    async def wait_window_fired(
        self,
        name: str,
        mask: int,
        window: DtpXtrigActivityWindow | None,
        *,
        cycles: int = 60,
        label: str = "",
    ) -> int:
        """Wait until every bit of ``mask`` on ``name`` has fired: seen by ``window``, or high now.

        A selected output whose pulse ended while its trigger was still held
        counts as fired.
        """
        observed = 0
        for _ in range(cycles):
            await ReadOnly()
            observed = self.xtrig.sample_signal(name)
            if window is not None:
                observed |= window.activity.get(name, 0)
            observed &= mask
            await ClockCycles(self.xtrig.clk, 1)
            if observed == mask:
                break
        self.check_evidence(self.CHK_SIGNAL, f"{name}.mask", observed, mask, context=label)
        return observed

    def p2p_hold_cycles(self, phase: str) -> int:
        """Seeded cycles the bench holds one point-to-point handshake phase, from that phase's stream."""
        rng = self._p2p_hold_rngs.get(phase)
        if rng is None:
            rng = self._p2p_hold_rngs[phase] = self.rng(f"p2p_{phase}")
        return rng.randint(self.P2P_HOLD_MIN_CYCLES, self.P2P_HOLD_MAX_CYCLES)

    async def wait_p2p_phase(
        self, name: str, mask: int, expected: int, *, invert: int = 0
    ) -> tuple[int, int]:
        """Sample ``name`` from the current clock on until its ``mask`` bits, XOR ``invert``, read ``expected``.

        One sample per clock for up to ``P2P_PHASE_MAX_CYCLES`` clocks.
        Returns the last such sample and the clock it matched at: 1 for the
        current clock, -1 for none.
        """
        level = 0
        for cycle in range(1, self.P2P_PHASE_MAX_CYCLES + 1):
            await ReadOnly()
            level = (self.xtrig.sample_signal(name) ^ invert) & mask
            if level == expected:
                await NextTimeStep()
                return level, cycle
            await ClockCycles(self.xtrig.clk, 1)
        return level, -1

    async def await_selected_outputs(
        self,
        output_mask: int,
        mode: int,
        *,
        label: str,
        window: DtpXtrigActivityWindow | None = None,
    ) -> None:
        """Wait for every selected output to request; acknowledge P2P CTP outputs and see them idle.

        The bench is the four-phase responder of a P2P CTP output. The
        request holds while CT_Ack_in is withheld for a seeded
        ``p2p_hold_cycles()`` and drops within ``P2P_PHASE_MAX_CYCLES`` of
        CT_Ack_in. CT_Ack_in stays asserted for a further seeded hold, through
        which BUSY stays set and the request stays released, and BUSY clears
        within ``P2P_PHASE_MAX_CYCLES`` of the CT_Ack_in release.
        """
        ctp_outputs = project_ctp_mask(output_mask)
        int_outputs = project_internal_mask(output_mask)
        if ctp_outputs and mode == XTRIG_CTP_MODE_P2P:
            active = self.pad_level(ctp_outputs, asserted=True)
            await self.wait_signal_mask(
                "xtrig_ctp_req_out_dout", ctp_outputs, active, label=f"{label}.ctp"
            )
            all_idle = self._ctp_invert_mask()
            held = ctp_outputs
            holdoff = self.p2p_hold_cycles("ack_holdoff")
            for _ in range(holdoff):
                await ClockCycles(self.xtrig.clk, 1)
                await ReadOnly()
                held &= self.xtrig.sample_signal("xtrig_ctp_req_out_dout") ^ all_idle
            await NextTimeStep()
            self.check_evidence(
                self.CHK_SIGNAL,
                f"{label}.ctp_held",
                held,
                ctp_outputs,
                context=f"acknowledge withheld {holdoff} cycles",
            )
            self.xtrig.set_ctp_ack_in_din((all_idle & ~ctp_outputs) | active)
            await ClockCycles(self.xtrig.clk, 1)
            requested, fell_at = await self.wait_p2p_phase(
                "xtrig_ctp_req_out_dout", ctp_outputs, 0, invert=all_idle
            )
            self.check_evidence(
                self.CHK_SIGNAL,
                f"{label}.ctp_released_on_ack",
                ctp_outputs & ~requested,
                ctp_outputs,
                context=f"fell {fell_at} cycles after CT_Ack_in",
            )
            ack_hold = self.p2p_hold_cycles("ack_hold")
            busy = ctp_outputs
            for _ in range(ack_hold):
                await ClockCycles(self.xtrig.clk, 1)
                await ReadOnly()
                busy &= self.xtrig.sample_signal("xtrig_ctp_busy")
                level = self.xtrig.sample_signal("xtrig_ctp_req_out_dout") ^ all_idle
                requested |= level & ctp_outputs
            await NextTimeStep()
            self.check_evidence(
                self.CHK_SIGNAL,
                f"{label}.ctp_busy_under_ack",
                busy & ~requested,
                ctp_outputs,
                context=f"CT_Ack_in held {ack_hold} cycles after the fall busy=0x{busy:x} "
                f"requested=0x{requested:x}",
            )
            self.xtrig.set_ctp_ack_in_din(all_idle)
            await ClockCycles(self.xtrig.clk, 1)
            busy, cleared_at = await self.wait_p2p_phase("xtrig_ctp_busy", ctp_outputs, 0)
            self.check_evidence(
                self.CHK_SIGNAL,
                f"{label}.ctp_done",
                busy,
                0,
                context=f"BUSY cleared {cleared_at} cycles after CT_Ack_in released",
            )
        elif ctp_outputs:
            await self.wait_window_fired(
                "xtrig_ctp_req_out_dout_en", ctp_outputs, window, label=f"{label}.ctp"
            )
        if int_outputs:
            await self.wait_window_fired(
                "xtrig_ctm_src_req", int_outputs, window, label=f"{label}.internal"
            )

    async def check_output_mask(
        self,
        output_mask: int,
        mode: int,
        *,
        predicted: int,
        window: DtpXtrigActivityWindow,
        label: str,
        drain_cycles: int = ISOLATION_TAIL_CYCLES,
        input_mask: int = 0,
        await_outputs: bool = True,
    ) -> None:
        """Judge one route: selected outputs fire, the window matches the model, nothing else moves.

        Every predicted output starts requesting once, after the window's
        first input, and no other output requests. The wire-OR sources of
        ``input_mask`` (every internal source, and the CTP sources unless
        ``mode`` is point-to-point) also receive their own assertion once, at
        the receive latency. With ``await_outputs`` false the selected outputs
        have already fired inside the window and only the drain tail is
        waited for.
        """
        if await_outputs:
            await self.await_selected_outputs(output_mask, mode, label=label, window=window)
        await ClockCycles(self.xtrig.clk, drain_cycles)
        activity, hold, last = await window.stop()
        fired = self.fired_vector(activity, hold)
        ctp_sources = 0 if mode == XTRIG_CTP_MODE_P2P else project_ctp_mask(input_mask)
        self.check_receive_edges(
            window,
            ctp_sources=ctp_sources & ~self._ctp_p2p_mask(),
            int_sources=project_internal_mask(input_mask),
            label=label,
        )
        intent = output_mask & XTRIG_CTM_SELECT_MASK
        self.log.info(
            "XTRIG WINDOW %-28s fired=0x%07x predicted=0x%07x intent=0x%07x p2p_ctps=0x%04x "
            "cycles=%d rose=%s",
            label,
            fired,
            predicted & XTRIG_CTM_SELECT_MASK,
            intent,
            self._ctp_p2p_mask(),
            window.cycles,
            window.first_seen_text(),
        )
        # Reference model against the DUT: the outputs that fired anywhere in
        # the window, and only those, are the model's prediction.
        self.check_evidence(
            self.CHK_ROUTE_MODEL,
            f"{label}.model_route",
            fired,
            predicted & XTRIG_CTM_SELECT_MASK,
            context=f"mode={mode}",
        )
        # One group of inputs pulsed in the same cycles reaches each output a
        # window predicts, so the output asserts once, and only after the
        # window's first input.
        input_at = min(window.first_seen["ctm_port_input"].values(), default=-1)
        for port in self.port_bits((predicted | fired) & XTRIG_CTM_SELECT_MASK):
            self.check_evidence(
                self.CHK_ROUTE_MODEL,
                f"{label}.port{port}.asserts",
                window.rises["ctm_port_request"].get(port, 0),
                (predicted >> port) & 1,
                context=f"mode={mode}",
            )
            if (fired >> port) & 1:
                request_at = window.first_seen["ctm_port_request"].get(port, -1)
                self.check_evidence(
                    self.CHK_ROUTE_MODEL,
                    f"{label}.port{port}.after_input",
                    int(0 <= input_at < request_at),
                    1,
                    context=f"input@{input_at} request@{request_at}",
                )
        # Isolation: no unselected output fired anywhere in the window, and the
        # selected outputs are idle again at its end.
        self.check_evidence(
            self.CHK_ISOLATION,
            f"{label}.unselected_quiet",
            fired & ~intent,
            0,
            context=f"mode={mode}",
        )
        self.check_evidence(
            self.CHK_ISOLATION,
            f"{label}.selected_deasserted",
            self.level_vector(last) & intent,
            0,
            context=f"mode={mode}",
        )

    async def run_route_window(
        self,
        input_mask: int,
        intent_mask: int,
        mode: int,
        *,
        label: str,
        drain_cycles: int = ISOLATION_TAIL_CYCLES,
        pulse_cycles: int = 2,
        lead_cycles: int = 0,
    ) -> DtpXtrigActivityWindow:
        """Pulse ``input_mask`` through the programmed routes and judge the output window.

        The model programmed alongside the CSRs predicts the DUT output vector
        of this pulse; under the negative-validation knob the model is
        corrupted, so the comparison against the DUT must fail. Returns the
        stopped window.
        """
        predicted = self.ctm_model.route(input_mask)
        window = await self._open_route_window()
        if lead_cycles:
            await ClockCycles(self.xtrig.clk, lead_cycles)
        await self.drive_input_mask(input_mask, mode, cycles=pulse_cycles, label=label)
        await self.check_output_mask(
            intent_mask,
            mode,
            predicted=predicted,
            window=window,
            label=label,
            drain_cycles=drain_cycles,
            input_mask=input_mask,
        )
        return window

    async def verify_route(
        self, input_port: int, output_mask: int, mode: int, *, label: str
    ) -> None:
        """Program one route, pulse its input, and judge the output window."""
        await self.verify_route_mask(1 << input_port, output_mask, mode, label=label)

    async def verify_route_mask(
        self,
        input_mask: int,
        output_mask: int,
        mode: int,
        *,
        label: str,
        pulse_cycles: int = 2,
        lead_cycles: int = 0,
    ) -> None:
        """Program every output of ``output_mask`` with ``input_mask``, pulse the inputs together, judge."""
        await self.configure_ctp_modes_for_route_mask(input_mask, output_mask, mode)
        await self.program_routes(input_mask, output_mask, label=label)
        await self.run_route_window(
            input_mask,
            output_mask,
            mode,
            label=label,
            pulse_cycles=pulse_cycles,
            lead_cycles=lead_cycles,
        )

    async def verify_route_cases(
        self, cases: list[tuple[int, int]], mode: int, *, label: str
    ) -> None:
        for idx, (input_port, output_mask) in enumerate(cases, start=1):
            self.log_iteration(
                idx, len(cases), "%s input=%d output_mask=0x%x", label, input_port, output_mask
            )
            await self.verify_route(input_port, output_mask, mode, label=f"{label}.{idx}")

    async def verify_wire_or_pulse(
        self, ctp_idx: int, int_idx: int, *, stretch: int, invert: int = 0, label: str
    ) -> None:
        """Route one internal CT to a wire-OR CTP: window, model, isolation, one pulse of width stretch+1.

        The data pad holds the level the port pulls its wire to (INVERT) at
        every cycle of the window, the enable pulse included.
        """
        await self.program_ctp(ctp_idx, mode=XTRIG_CTP_MODE_WIRE_OR, invert=invert, stretch=stretch)
        await self.program_route(
            internal_ct_port(int_idx), 1 << external_ctp_port(ctp_idx), label=label
        )
        width_task = cocotb.start_soon(
            self.xtrig.measure_mask_width(
                "xtrig_ctp_req_out_dout_en", 1 << ctp_idx, timeout_cycles=stretch + 60
            )
        )
        window = await self.run_route_window(
            1 << internal_ct_port(int_idx),
            1 << external_ctp_port(ctp_idx),
            XTRIG_CTP_MODE_WIRE_OR,
            label=label,
            drain_cycles=self.ISOLATION_TAIL_CYCLES + stretch,
        )
        pulse = await width_task
        self.check_evidence(
            self.CHK_STRETCH, f"{label}.width", pulse.width, stretch + 1, context=f"ctp={ctp_idx}"
        )
        self.check_evidence(
            self.CHK_STRETCH, f"{label}.pulses", pulse.pulses, 1, context=f"ctp={ctp_idx}"
        )
        for tag, levels in (("any", window.activity), ("all", window.hold)):
            self.check_evidence(
                self.CHK_SIGNAL,
                f"{label}.wire_polarity_{tag}",
                (levels["xtrig_ctp_req_out_dout"] >> ctp_idx) & 1,
                XTRIG_WIRE_OR_ASSERT[invert],
                context=f"ctp={ctp_idx} invert={invert}",
            )

    async def check_all_ctm_cleared(self, label: str) -> None:
        """Every CT_SRC select reads its reset value."""
        for src_idx in range(XTRIG_NUM_CTM_PORTS):
            addr = ctm_config_addr(src_idx)
            observed = await self.csr_read(addr, label=f"{label}.ctm{src_idx}")
            self.check_evidence(
                self.CHK_CSR,
                f"{label}.ctm{src_idx}.default",
                observed & XTRIG_CTM_SELECT_MASK,
                XTRIG_CTM_SELECT_DEFAULT & XTRIG_CTM_SELECT_MASK,
                context=f"addr=0x{addr:03x}",
            )

    # ------------------------------------------------------------------
    # CTP scenarios
    # ------------------------------------------------------------------
    async def run_wire_or(self) -> None:
        self.log_banner("DTP XTRIG CTP wire-OR pulse stretching and sync")
        # Seeded per-pass port pair and an extra random stretch: per spec every
        # CTP behaves identically, so each loop proves the same properties on a
        # different CTP/internal pair and stretch width.
        rng = self.rng("xtrig_wire_or")
        ctp_idx = rng.randrange(XTRIG_NUM_CTP)
        int_idx = rng.randrange(XTRIG_NUM_INT_CT)
        int_port = internal_ct_port(int_idx)
        ctp_port = external_ctp_port(ctp_idx)

        for stretch in (15, 0, rng.randint(1, 14)):
            self.log_step(
                "setup", "Configure wire-OR stretch=%d and route internal CT to CTP", stretch
            )
            await self.program_ctp(ctp_idx, mode=XTRIG_CTP_MODE_WIRE_OR, stretch=stretch)
            await self.program_route(int_port, 1 << ctp_port, label=f"wire_or.stretch{stretch}")
            await self.run_wire_or_pulse(ctp_idx, int_idx, stretch=stretch)

        for invert in (0, 1):
            self.log_step(
                "sync",
                "A chiplet pulls the CTP's shared wire (INVERT=%d) and the internal CT delivers",
                invert,
            )
            await self.program_ctp(ctp_idx, mode=XTRIG_CTP_MODE_WIRE_OR, invert=invert, stretch=0)
            await self.program_route(
                ctp_port, 1 << int_port, label=f"wire_or.external_to_internal.inv{invert}"
            )
            await self.run_route_window(
                1 << ctp_port,
                1 << int_port,
                XTRIG_CTP_MODE_WIRE_OR,
                label=f"wire_or.external_sync.inv{invert}",
            )
        await self.program_ctp(ctp_idx, mode=XTRIG_CTP_MODE_WIRE_OR, stretch=0)
        self.log_summary("wire_or", ctp=ctp_idx, internal=int_idx, checked_stretches="15,0,random")

    async def run_wire_or_pulse(self, ctp_idx: int, int_idx: int, *, stretch: int) -> None:
        """One stretched pulse after the internal request: enable and busy widths, aligned rise, BUSY over the CSR, then clear."""
        label = f"wire_or.stretch{stretch}"
        mask = 1 << ctp_idx
        await self.idle_inputs()
        window = self.xtrig.activity_window(
            ("xtrig_ctp_req_out_dout_en", "xtrig_ctp_busy", "xtrig_ctm_dst_req")
        )
        window.start()
        width_task = cocotb.start_soon(
            self.xtrig.measure_mask_width("xtrig_ctp_req_out_dout_en", mask)
        )
        busy_task = cocotb.start_soon(self.xtrig.measure_mask_width("xtrig_ctp_busy", mask))
        await self.xtrig.pulse_ctm_dst_req(1 << int_idx, cycles=1)
        await self.wait_signal_mask(
            "xtrig_ctp_req_out_dout_en", mask, mask, label=f"{label}.active"
        )
        if stretch >= self.BUSY_READ_MIN_STRETCH:
            await self.check_status(ctp_idx, f"{label}.active", busy=1)
        pulse = await width_task
        busy = await busy_task
        await window.stop()
        self.check_evidence(self.CHK_STRETCH, f"{label}.width", pulse.width, stretch + 1)
        self.check_evidence(self.CHK_STRETCH, f"{label}.pulses", pulse.pulses, 1)
        self.check_evidence(self.CHK_STRETCH, f"{label}.busy_width", busy.width, stretch + 1)
        self.check_evidence(self.CHK_STRETCH, f"{label}.busy_pulses", busy.pulses, 1)
        requested_at = window.first_seen["xtrig_ctm_dst_req"].get(int_idx, -1)
        enabled_at = window.first_seen["xtrig_ctp_req_out_dout_en"].get(ctp_idx, -1)
        self.check_evidence(
            self.CHK_SIGNAL,
            f"{label}.after_input",
            int(0 <= requested_at < enabled_at),
            1,
            context=f"request@{requested_at} enable@{enabled_at}",
        )
        self.check_evidence(
            self.CHK_SIGNAL,
            f"{label}.enable_seen",
            int(ctp_idx in window.first_seen["xtrig_ctp_req_out_dout_en"]),
            1,
        )
        self.check_evidence(
            self.CHK_SIGNAL,
            f"{label}.busy_rise",
            window.first_seen["xtrig_ctp_busy"].get(ctp_idx, -1),
            enabled_at,
            context="busy rises with the output enable",
        )
        await self.check_status(ctp_idx, f"{label}.cleared", busy=0)
        self.check_evidence(
            self.CHK_SIGNAL,
            f"{label}.busy_flop_cleared",
            self.xtrig.sample_signal("xtrig_ctp_busy") & mask,
            0,
        )

    async def run_wire_or_bus(self) -> None:
        """Several CTPs on one shared wire: the transmitter's, a chiplet's, and a merged pull each reach every member once."""
        self.log_banner("DTP XTRIG CTPs on one shared wire-OR wire")
        # Seeded per pass: the members of the wire, their stretch, the
        # transmitter, the internal source that triggers it, and one internal
        # output per member. The passes alternate the sense of the wire.
        rng = self.rng("xtrig_wire_or_bus")
        members = rng.sample(range(XTRIG_NUM_CTP), rng.randrange(2, 5))
        invert = self.loop_index % 2
        stretch = rng.randrange(0, 8)
        int_src, *int_outs = rng.sample(range(XTRIG_NUM_INT_CT), len(members) + 1)
        tx = members[0]
        member_ports = sum(1 << external_ctp_port(m) for m in members)
        listener_outputs = sum(1 << internal_ct_port(k) for k in int_outs)
        self.log.info(
            "shared wire: CTPs %s (INVERT=%d, STRETCH_MULT=%d), transmitter CTP[%d] from "
            "internal CT[%d], listeners to internal CTs %s",
            members,
            invert,
            stretch,
            tx,
            int_src,
            int_outs,
        )
        for member in members:
            await self.program_ctp(
                member, mode=XTRIG_CTP_MODE_WIRE_OR, invert=invert, stretch=stretch
            )
        self.xtrig.set_ctp_wire_group(member_ports, pull=XTRIG_WIRE_OR_PULL[invert])
        await self.clear_ctm_routes()
        await self.program_ctm_src(external_ctp_port(tx), 1 << internal_ct_port(int_src))
        for member, int_out in zip(members, int_outs, strict=True):
            await self.program_ctm_src(internal_ct_port(int_out), 1 << external_ctp_port(member))
        transmit_predicted = self.ctm_model.route(1 << internal_ct_port(int_src)) | (
            self.ctm_model.route(member_ports)
        )
        transmit_intent = (1 << external_ctp_port(tx)) | listener_outputs

        self.log_step(
            1, "The transmitter pulls the wire: every member, itself included, receives once"
        )
        window = await self._open_route_window()
        await self.xtrig.pulse_ctm_dst_req(1 << int_src, cycles=1)
        await self.check_output_mask(
            transmit_intent,
            XTRIG_CTP_MODE_WIRE_OR,
            predicted=transmit_predicted,
            window=window,
            label="wire_or_bus.transmit",
            drain_cycles=self.ISOLATION_TAIL_CYCLES + stretch,
            input_mask=1 << internal_ct_port(int_src),
        )
        self._check_shared_wire_receive(
            window,
            members,
            pulled_at_name="xtrig_ctp_req_out_dout_en",
            pulled_by=tx,
            label="wire_or_bus.transmit",
        )

        self.log_step(2, "A chiplet pulls the wire: every member receives once")
        puller = members[-1]
        window = await self._open_route_window()
        await self.xtrig.pull_ctp_wire(puller, cycles=rng.randrange(1, 6))
        await self.check_output_mask(
            listener_outputs,
            XTRIG_CTP_MODE_WIRE_OR,
            predicted=self.ctm_model.route(member_ports),
            window=window,
            label="wire_or_bus.chiplet",
        )
        self._check_shared_wire_receive(
            window,
            members,
            pulled_at_name="xtrig_ctp_wire_ext_assert",
            pulled_by=puller,
            label="wire_or_bus.chiplet",
        )

        self.log_step(
            3, "The transmitter pulls while a chiplet holds the wire: one merged assertion"
        )
        window = await self._open_route_window()
        self.xtrig.set_ctp_wire_ext_assert(1 << puller)
        await ClockCycles(self.xtrig.clk, rng.randrange(1, 4))
        await self.xtrig.pulse_ctm_dst_req(1 << int_src, cycles=1)
        # The chiplet keeps the wire asserted until the transmitter has released it.
        await self.wait_signal_mask(
            "xtrig_ctp_req_out_dout_en", 1 << tx, 1 << tx, label="wire_or_bus.merged.tx_pulls"
        )
        await self.wait_signal_mask(
            "xtrig_ctp_req_out_dout_en", 1 << tx, 0, label="wire_or_bus.merged.tx_releases"
        )
        await ClockCycles(self.xtrig.clk, 2)
        self.xtrig.set_ctp_wire_ext_assert(0)
        await self.check_output_mask(
            transmit_intent,
            XTRIG_CTP_MODE_WIRE_OR,
            predicted=transmit_predicted,
            window=window,
            label="wire_or_bus.merged",
            drain_cycles=self.ISOLATION_TAIL_CYCLES + stretch,
            await_outputs=False,
        )
        self._check_shared_wire_receive(
            window,
            members,
            pulled_at_name="xtrig_ctp_wire_ext_assert",
            pulled_by=puller,
            label="wire_or_bus.merged",
        )

        self.xtrig.set_ctp_wire_group(0, pull=XTRIG_WIRE_OR_PULL[0])
        await self.clear_ctm_routes()
        self.log_summary("wire_or_bus", members=members, invert=invert, stretch=stretch)

    async def _open_route_window(self) -> DtpXtrigActivityWindow:
        """Idle the inputs and start an activity window over the route observables.

        The window also tracks the per-port request levels (``ctm_port_request``)
        and the inputs the bench asserts (``ctm_port_input``).
        """
        await self.idle_inputs()
        await ClockCycles(self.xtrig.clk, 2)
        window = self.xtrig.activity_window(
            self.OUTPUT_SIGNALS,
            derived={"ctm_port_request": self.level_vector, "ctm_port_input": self.input_vector},
        )
        window.start()
        return window

    def _check_shared_wire_receive(
        self,
        window: DtpXtrigActivityWindow,
        members: list[int],
        *,
        pulled_at_name: str,
        pulled_by: int,
        label: str,
    ) -> None:
        """Every member of the shared wire received the one assertion ``pulled_by`` made."""
        pulled_at = window.first_seen[pulled_at_name].get(pulled_by)
        for member in members:
            self._check_receive_edge(
                window,
                assert_name=pulled_at_name,
                receive_name="xtrig_ctp_ct_dst",
                bit=member,
                label=f"{label}.ctp{member}",
                asserted_at=pulled_at,
            )

    async def run_p2p(self) -> None:
        self.log_banner("DTP XTRIG CTP point-to-point handshakes")
        # Seeded per-pass port pair: each loop proves the P2P handshakes on a
        # different CTP/internal combination.
        rng = self.rng("xtrig_p2p")
        ctp_idx = rng.randrange(XTRIG_NUM_CTP)
        int_idx = rng.randrange(XTRIG_NUM_INT_CT)
        ctp_port = external_ctp_port(ctp_idx)
        int_port = internal_ct_port(int_idx)
        mask = 1 << ctp_idx
        await self.configure_ctp_mode_for_port(ctp_port, XTRIG_CTP_MODE_P2P, stretch=0)

        self.log_step(1, "Internal trigger asserts CT_Req_out and BUSY until CT_Ack_in")
        await self.program_route(int_port, 1 << ctp_port, label="p2p.internal_to_ctp")
        await self.idle_inputs()
        before = await self.sample_xtrig("p2p.before_request")
        self.check_evidence(
            self.CHK_SIGNAL,
            "p2p.req_out_idle_before",
            before["xtrig_ctp_req_out_dout"] & mask,
            self.pad_level(mask, asserted=False),
        )
        await self.xtrig.pulse_ctm_dst_req(1 << int_idx, cycles=2)
        await self.wait_signal_mask(
            "xtrig_ctp_req_out_dout", mask, self.pad_level(mask, asserted=True), label="p2p.req_out"
        )
        await self.check_status(
            ctp_idx, "p2p.request", busy=1, req_out=1, ack_in=0, req_in=0, ack_out=0
        )
        await self.drive_p2p_ack_in(ctp_idx, asserted=True)
        await self.wait_signal_mask(
            "xtrig_ctp_req_out_dout",
            mask,
            self.pad_level(mask, asserted=False),
            cycles=self.P2P_PHASE_MAX_CYCLES,
            label="p2p.req_out_clear",
        )
        await self.check_status(
            ctp_idx, "p2p.acknowledged", busy=1, req_out=0, ack_in=1, req_in=0, ack_out=0
        )
        # CT_Req_out stays idle from the acknowledge release until STATUS reads the port idle.
        released = self.xtrig.activity_window(("xtrig_ctp_req_out_dout",))
        released.start()
        await self.drive_p2p_ack_in(ctp_idx, asserted=False)
        await self.wait_signal_mask("xtrig_ctp_busy", mask, 0, label="p2p.request_done")
        await self.wait_signal_mask(
            "xtrig_ctp_req_out_dout",
            mask,
            self.pad_level(mask, asserted=False),
            label="p2p.req_out_idle",
        )
        await self.check_status(
            ctp_idx, "p2p.request_done", busy=0, req_out=0, ack_in=0, req_in=0, ack_out=0
        )
        activity, hold, _last = await released.stop()
        inverted = self._ctp_invert_mask()
        self.check_evidence(
            self.CHK_SIGNAL,
            "p2p.request_done.req_out_idle",
            (
                (activity["xtrig_ctp_req_out_dout"] & ~inverted)
                | (~hold["xtrig_ctp_req_out_dout"] & inverted)
            )
            & mask,
            0,
            context=f"cycles={released.cycles}",
        )

        self.log_step(2, "External CT_Req_in asserts CT_Ack_out, delivers the trigger, then idles")
        await self.program_route(ctp_port, 1 << int_port, label="p2p.ctp_to_internal")
        before = await self.sample_xtrig("p2p.before_response")
        self.check_evidence(
            self.CHK_SIGNAL,
            "p2p.internal_idle_before",
            before["xtrig_ctm_src_req"] & (1 << int_idx),
            0,
        )
        self.check_evidence(
            self.CHK_SIGNAL,
            "p2p.ack_out_idle_before",
            before["xtrig_ctp_ack_out_dout"] & mask,
            self.pad_level(mask, asserted=False),
        )
        delivery = self.xtrig.activity_window(("xtrig_ctm_src_req",))
        delivery.start()
        await self.drive_p2p_req_in(ctp_idx, asserted=True)
        await self.wait_signal_mask(
            "xtrig_ctp_ack_out_dout", mask, self.pad_level(mask, asserted=True), label="p2p.ack_out"
        )
        await self.wait_signal_mask(
            "xtrig_ctm_src_req", 1 << int_idx, 1 << int_idx, label="p2p.internal_delivery"
        )
        await self.wait_signal_mask(
            "xtrig_ctm_src_req", 1 << int_idx, 0, label="p2p.internal_released"
        )
        await self.check_status(
            ctp_idx, "p2p.response", busy=1, req_out=0, ack_in=0, req_in=1, ack_out=1
        )
        await self.drive_p2p_req_in(ctp_idx, asserted=False)
        await self.wait_signal_mask(
            "xtrig_ctp_ack_out_dout",
            mask,
            self.pad_level(mask, asserted=False),
            cycles=self.P2P_PHASE_MAX_CYCLES,
            label="p2p.ack_out_clear",
        )
        await self.wait_signal_mask("xtrig_ctp_busy", mask, 0, label="p2p.response_done")
        await self.check_status(
            ctp_idx, "p2p.response_done", busy=0, req_out=0, ack_in=0, req_in=0, ack_out=0
        )
        # One CT_Req_in assertion delivers one pulse, to the routed destination only.
        activity, _hold, _last = await delivery.stop()
        self.check_evidence(
            self.CHK_SIGNAL,
            "p2p.internal_delivery.pulses",
            delivery.rises["xtrig_ctm_src_req"].get(int_idx, 0),
            1,
            context=f"cycles={delivery.cycles}",
        )
        self.check_evidence(
            self.CHK_SIGNAL,
            "p2p.internal_delivery.isolated",
            activity["xtrig_ctm_src_req"] & ~(1 << int_idx),
            0,
            context=f"cycles={delivery.cycles}",
        )
        self.log_summary("p2p", ctp=ctp_idx)

    async def run_reset(self) -> None:
        self.log_banner("DTP XTRIG CTP reset recovery")
        # Seeded per-pass ports: each loop deadlocks and recovers a different
        # CTP, and system-resets a different second CTP.
        rng = self.rng("xtrig_reset")
        ctp_idx = rng.randrange(XTRIG_NUM_CTP)
        int_idx = rng.randrange(XTRIG_NUM_INT_CT)
        ctp_b = rng.choice([c for c in range(XTRIG_NUM_CTP) if c != ctp_idx])
        int_b = rng.choice([i for i in range(XTRIG_NUM_INT_CT) if i != int_idx])
        int_c = rng.choice([i for i in range(XTRIG_NUM_INT_CT) if i not in (int_idx, int_b)])
        ctp_port = external_ctp_port(ctp_idx)
        int_port = internal_ct_port(int_idx)
        mask = 1 << ctp_idx

        self.log_step(
            1, "Stall the acknowledge of a P2P handshake and recover through CONFIG.RESET"
        )
        await self.configure_ctp_mode_for_port(ctp_port, XTRIG_CTP_MODE_P2P, stretch=0)
        await self.program_route(int_port, 1 << ctp_port, label="reset.deadlock_setup")
        await self.idle_inputs()
        await self.xtrig.pulse_ctm_dst_req(1 << int_idx, cycles=2)
        await self.wait_signal_mask(
            "xtrig_ctp_req_out_dout",
            mask,
            self.pad_level(mask, asserted=True),
            label="reset.stuck_req",
        )
        await self.check_status(ctp_idx, "reset.before_config_reset", busy=1, req_out=1)
        # CONFIG.RESET resets the sender alone: a request the port receives
        # keeps CT_Ack_out asserted through the reset until CT_Req_in drops.
        await self.drive_p2p_req_in(ctp_idx, asserted=True)
        await self.wait_signal_mask(
            "xtrig_ctp_ack_out_dout",
            mask,
            self.pad_level(mask, asserted=True),
            label="reset.rx_held",
        )
        rx_window = self.xtrig.activity_window(("xtrig_ctp_ack_out_dout",))
        rx_window.start()
        await self.csr_write(
            ctp_config_addr(ctp_idx),
            pack_ctp_config(mode=XTRIG_CTP_MODE_P2P, reset=1),
            label=f"ctp{ctp_idx}.config_reset",
        )
        await self.wait_signal_mask(
            "xtrig_ctp_req_out_dout",
            mask,
            self.pad_level(mask, asserted=False),
            label="reset.config_reset_clear",
        )
        await self.check_status(
            ctp_idx, "reset.config_reset_rx_held", busy=1, req_out=0, req_in=1, ack_out=1
        )
        activity, hold, _last = await rx_window.stop()
        inverted = self._ctp_invert_mask()
        self.check_evidence(
            self.CHK_SIGNAL,
            "reset.config_reset.rx_kept",
            (
                (hold["xtrig_ctp_ack_out_dout"] & ~inverted)
                | (~activity["xtrig_ctp_ack_out_dout"] & inverted)
            )
            & mask,
            mask,
            context=f"cycles={rx_window.cycles}",
        )
        await self.drive_p2p_req_in(ctp_idx, asserted=False)
        await self.wait_signal_mask(
            "xtrig_ctp_ack_out_dout",
            mask,
            self.pad_level(mask, asserted=False),
            cycles=self.P2P_PHASE_MAX_CYCLES,
            label="reset.rx_released",
        )
        await self.program_ctp(ctp_idx, mode=XTRIG_CTP_MODE_P2P, reset=1)
        await self.check_status(ctp_idx, "reset.config_reset", busy=0, req_out=0)
        # The window opens once STATUS has read BUSY=0, because the registered
        # busy flop clears a cycle after RESET forces the sender idle.
        held = self.xtrig.activity_window(self.CONFIG_RESET_SIGNALS)
        held.start()
        await self.program_ctp(ctp_idx, mode=XTRIG_CTP_MODE_P2P, reset=0)
        await ClockCycles(self.xtrig.clk, self.ISOLATION_TAIL_CYCLES)
        activity, _hold, _last = await held.stop()
        for name in self.CONFIG_RESET_SIGNALS:
            self.check_evidence(
                self.CHK_QUIET,
                f"reset.config_reset.{name}",
                (activity[name] >> ctp_idx) & 1,
                0,
                context=f"cycles={held.cycles}",
            )
        await self.verify_route(
            int_port, 1 << ctp_port, XTRIG_CTP_MODE_P2P, label="reset.post_config_reset"
        )

        self.log_step(
            2,
            "System reset while an inverted wire-OR pulse and a P2P receive are active on "
            "two CTPs and an internal CT has pulsed",
        )
        live = self.xtrig.activity_window(self.RESET_SIGNALS)
        live.start()
        await self.program_ctp(
            ctp_b, mode=XTRIG_CTP_MODE_WIRE_OR, invert=1, stretch=self.RESET_HOLD_STRETCH
        )
        await self.program_ctm_src(ctp_b, 1 << internal_ct_port(int_b))
        await self.program_ctm_src(internal_ct_port(int_c), 1 << internal_ct_port(int_b))
        await self.idle_inputs()
        await self.xtrig.pulse_ctm_dst_req(1 << int_b, cycles=1)
        await self.wait_signal_mask(
            "xtrig_ctp_req_out_dout_en", 1 << ctp_b, 1 << ctp_b, label="reset.active_before"
        )
        await self.wait_window_fired(
            "xtrig_ctm_src_req", 1 << int_c, live, label="reset.internal_active"
        )
        await self.drive_p2p_req_in(ctp_idx, asserted=True)
        await self.wait_signal_mask(
            "xtrig_ctp_ack_out_dout",
            mask,
            self.pad_level(mask, asserted=True),
            label="reset.rx_ack_held",
        )
        await self.reset_window("xtrig_reset", watched=self.RESET_SIGNALS, live=live)
        await self.check_ctp_defaults("reset.system")
        await self.check_all_ctm_cleared("reset.system")
        await self.verify_route(
            internal_ct_port(int_b),
            1 << external_ctp_port(ctp_b),
            XTRIG_CTP_MODE_WIRE_OR,
            label="reset.post_system_reset",
        )
        self.log_summary("reset", ctp=ctp_idx, reset_ctp=ctp_b)

    async def run_random(self) -> None:
        self.log_banner("DTP XTRIG seeded random CTP configuration")
        rng = self.rng("xtrig_random")
        for idx in range(self.random_count):
            ctp_idx = rng.randrange(XTRIG_NUM_CTP)
            mode = rng.randrange(2)
            invert = rng.randrange(2)
            stretch = rng.randrange(0, 8)
            if idx < len(self.RANDOM_HEAD):
                mode, invert, lowest, highest = self.RANDOM_HEAD[idx]
                stretch = rng.randint(lowest, highest)
            int_idx = rng.randrange(XTRIG_NUM_INT_CT)
            self.log_iteration(
                idx + 1,
                self.random_count,
                "ctp=%d mode=%d invert=%d stretch=%d internal=%d",
                ctp_idx,
                mode,
                invert,
                stretch,
                int_idx,
            )
            label = f"random.{idx}"
            if mode == XTRIG_CTP_MODE_WIRE_OR:
                await self.verify_wire_or_pulse(
                    ctp_idx, int_idx, stretch=stretch, invert=invert, label=label
                )
                continue
            await self.csr_write(
                ctp_config_addr(ctp_idx),
                pack_ctp_config(mode=mode, invert=invert, reset=1),
                label=f"ctp{ctp_idx}.handshake_reset",
            )
            await self.program_ctp(ctp_idx, mode=mode, invert=invert, stretch=stretch)
            await self.program_route(
                internal_ct_port(int_idx), 1 << external_ctp_port(ctp_idx), label=label
            )
            await self.run_route_window(
                1 << internal_ct_port(int_idx),
                1 << external_ctp_port(ctp_idx),
                XTRIG_CTP_MODE_P2P,
                label=label,
            )
            # The same port receives: CT_Req_in at the port's polarity reaches
            # the internal CT through the reverse route.
            await self.program_route(
                external_ctp_port(ctp_idx), 1 << internal_ct_port(int_idx), label=f"{label}.rx"
            )
            await self.run_route_window(
                1 << external_ctp_port(ctp_idx),
                1 << internal_ct_port(int_idx),
                XTRIG_CTP_MODE_P2P,
                label=f"{label}.rx",
            )
        self.log_summary("random", iterations=self.random_count)

    async def run_ctp_csr_sweep(self) -> None:
        self.log_banner("DTP XTRIG CTP deterministic CSR and byte-strobe sweep")
        # Seeded per-pass order and an extra random stretch value: the sweep
        # stays exhaustive while each loop exercises different write orders.
        rng = self.rng("ctp_csr_sweep")
        base = [
            pack_ctp_config(mode=XTRIG_CTP_MODE_WIRE_OR),
            pack_ctp_config(mode=XTRIG_CTP_MODE_WIRE_OR, invert=1),
            pack_ctp_config(mode=XTRIG_CTP_MODE_P2P),
            pack_ctp_config(mode=XTRIG_CTP_MODE_P2P, invert=1, reset=1),
        ]
        rng.shuffle(base)
        # Reserved bits are driven to 1 by the all-ones and inverted patterns
        # and must read back 0 (full-word compare).
        config_patterns = base + [FULL_WORD] + [(~word) & FULL_WORD for word in base]
        stretch_patterns = [
            0,
            1,
            0x55AA,
            0xFFFF,
            rng.getrandbits(16),
            FULL_WORD,
            ~0x55AA & FULL_WORD,
        ]
        for ctp_idx in range(XTRIG_NUM_CTP):
            self.log_iteration(ctp_idx + 1, XTRIG_NUM_CTP, "CTP[%d] CSR sweep", ctp_idx)
            # The neighbour holds seeded nonzero words the sweep does not end
            # on, so a write that also lands in the neighbour leaves another
            # value there.
            neighbor = (ctp_idx + 1) % XTRIG_NUM_CTP
            nbr_config = self.sweep_config_word(rng)
            nbr_stretch = rng.randrange(1, 1 << 16)
            await self.write_read_check(
                ctp_config_addr(neighbor),
                nbr_config,
                nbr_config,
                mask=XTRIG_CTP_CONFIG_MASK,
                label=f"ctp{ctp_idx}.neighbor_preload.config",
            )
            await self.write_read_check(
                ctp_stretch_addr(neighbor),
                nbr_stretch,
                nbr_stretch,
                mask=XTRIG_CTP_STRETCH_MASK,
                label=f"ctp{ctp_idx}.neighbor_preload.stretch",
            )
            await self.sweep_ctp_words(
                ctp_idx,
                config_patterns,
                stretch_patterns,
                rng,
                final_config=self.sweep_config_word(rng, exclude=nbr_config),
                final_stretch=nbr_stretch ^ rng.randrange(1, 1 << 16),
            )
            for name, addr, mask, expected in (
                ("config", ctp_config_addr(neighbor), XTRIG_CTP_CONFIG_MASK, nbr_config),
                ("stretch", ctp_stretch_addr(neighbor), XTRIG_CTP_STRETCH_MASK, nbr_stretch),
            ):
                observed = await self.csr_read(addr, label=f"ctp{ctp_idx}.neighbor_after.{name}")
                self.check_evidence(
                    self.CHK_CSR,
                    f"ctp{ctp_idx}.neighbor_no_alias.{name}",
                    observed & mask,
                    expected,
                    context=f"ctp={neighbor}",
                )
        self.log_step("route", "One programmed CTP routes a stretched pulse after the sweep")
        await self.clear_xtrig()
        stretch = rng.randint(1, 14)
        await self.verify_wire_or_pulse(
            rng.randrange(XTRIG_NUM_CTP),
            rng.randrange(XTRIG_NUM_INT_CT),
            stretch=stretch,
            label="ctp_csr_sweep.route",
        )
        await self.clear_xtrig()
        self.log_summary("ctp_csr_sweep", ctp_count=XTRIG_NUM_CTP)

    def sweep_config_word(self, rng: Random, *, exclude: int | None = None) -> int:
        """One seeded word of ``CTP_SWEEP_CONFIGS`` other than ``exclude``."""
        return rng.choice([word for word in self.CTP_SWEEP_CONFIGS if word != exclude])

    async def sweep_ctp_words(
        self,
        ctp_idx: int,
        config_patterns: list[int],
        stretch_patterns: list[int],
        rng: Random,
        *,
        final_config: int,
        final_stretch: int,
    ) -> None:
        """Patterns, byte strobes, a STATUS write, the final words, then a hole write, on one CTP."""
        config = ctp_config_addr(ctp_idx)
        stretch = ctp_stretch_addr(ctp_idx)
        for pat_idx, word in enumerate(config_patterns):
            await self.write_read_check(
                config, word, word & XTRIG_CTP_CONFIG_MASK, label=f"ctp{ctp_idx}.cfg{pat_idx}"
            )
        for pat_idx, word in enumerate(stretch_patterns):
            await self.write_read_check(
                stretch, word, word & XTRIG_CTP_STRETCH_MASK, label=f"ctp{ctp_idx}.stretch{pat_idx}"
            )
        # Byte strobes over a nonzero base: only the strobed lanes change, and
        # a strobed reserved lane changes nothing.
        for wstrb in (0x1, 0x2, 0x4, 0x8):
            old_cfg = self.sweep_config_word(rng)
            new_cfg = rng.getrandbits(32)
            await self.csr_write(config, old_cfg, label=f"ctp{ctp_idx}.byte_base")
            await self.write_read_check(
                config,
                new_cfg,
                apply_wstrb(old_cfg, new_cfg, wstrb) & XTRIG_CTP_CONFIG_MASK,
                wstrb=wstrb,
                label=f"ctp{ctp_idx}.cfg_wstrb{wstrb:x}",
            )
            old_stretch = rng.randrange(1, 1 << 16)
            new_stretch = rng.getrandbits(32)
            await self.csr_write(stretch, old_stretch, label=f"ctp{ctp_idx}.stretch_base")
            await self.write_read_check(
                stretch,
                new_stretch,
                apply_wstrb(old_stretch, new_stretch, wstrb) & XTRIG_CTP_STRETCH_MASK,
                wstrb=wstrb,
                label=f"ctp{ctp_idx}.stretch_wstrb{wstrb:x}",
            )
        status_before = await self.csr_read(ctp_status_addr(ctp_idx), label=f"ctp{ctp_idx}.status")
        await self.write_read_check(
            ctp_status_addr(ctp_idx), FULL_WORD, status_before, label=f"ctp{ctp_idx}.status_ro"
        )
        await self.write_read_check(
            config,
            final_config,
            final_config,
            mask=XTRIG_CTP_CONFIG_MASK,
            label=f"ctp{ctp_idx}.cfg_final",
        )
        await self.write_read_check(
            stretch,
            final_stretch,
            final_stretch,
            mask=XTRIG_CTP_STRETCH_MASK,
            label=f"ctp{ctp_idx}.stretch_final",
        )
        # The word past STRETCH_MULT is a hole: it reads 0 after an all-ones
        # write, and the write leaves the window's registers on the final words.
        await self.write_read_check(
            ctp_hole_addr(ctp_idx), FULL_WORD, 0, label=f"ctp{ctp_idx}.hole"
        )
        for name, addr, mask, expected in (
            ("config", config, XTRIG_CTP_CONFIG_MASK, final_config),
            ("stretch", stretch, XTRIG_CTP_STRETCH_MASK, final_stretch),
        ):
            observed = await self.csr_read(addr, label=f"ctp{ctp_idx}.hole_after.{name}")
            self.check_evidence(
                self.CHK_CSR,
                f"ctp{ctp_idx}.hole_no_alias.{name}",
                observed & mask,
                expected & mask,
                context=f"ctp={ctp_idx}",
            )

    async def run_dst_port_sweep(self) -> None:
        self.log_banner("DTP XTRIG deterministic destination-port sweep")
        # Seeded per-pass source: the output sweep stays exhaustive while each
        # loop drives it from a different internal CT.
        input_port = internal_ct_port(self.rng("dst_port_sweep").randrange(XTRIG_NUM_INT_CT))
        for output_port in range(XTRIG_NUM_CTM_PORTS):
            self.log_iteration(
                output_port + 1,
                XTRIG_NUM_CTM_PORTS,
                "input port %d -> output port %d",
                input_port,
                output_port,
            )
            await self.verify_route(
                input_port,
                1 << output_port,
                XTRIG_CTP_MODE_WIRE_OR,
                label=f"dst_sweep.port{output_port}",
            )
            if not self.is_ctp_port(output_port):
                ack_mask = 1 << self.int_idx_from_port(output_port)
                self.xtrig.set_ctm_src_ack(ack_mask)
                await ClockCycles(self.xtrig.clk, 1)
                self.xtrig.set_ctm_src_ack(0)
        self.log_summary("dst_port_sweep", outputs=XTRIG_NUM_CTM_PORTS)

    # ------------------------------------------------------------------
    # AXI-Lite skew/default path scenarios
    # ------------------------------------------------------------------
    async def run_reg_stall(self) -> None:
        """Accepted-path CSR accesses under an activity window.

        No internal-lane request, CTP request or acknowledge enable, or CTP
        busy flop moves while an access is in flight, the crossbar demux's AW
        and AR stall counters do not advance while the port's AWVALID and
        ARVALID counters do, and two routes afterwards, one wire-OR and one
        point-to-point, are the positive control that moves each of those
        observables.
        """
        self.require_pulse_mode_lanes("run_reg_stall")
        self.log_banner("DTP XTRIG accepted-path CSR access and stall rationale")
        # Seeded per-pass CSR payloads and control ports: each loop writes
        # different values down the accepted path.
        rng = self.rng("reg_stall")
        stretch = rng.getrandbits(16)
        select = rng.randint(1, XTRIG_CTM_SELECT_MASK)
        int_idx, int_out, int_p2p = rng.sample(range(XTRIG_NUM_INT_CT), 3)
        ctp_idx, ctp_p2p = rng.sample(range(XTRIG_NUM_CTP), 2)
        before = await self.sample_xtrig("accepted_path.before")
        await self.idle_inputs()
        window = self.xtrig.activity_window(self.IN_FLIGHT_SIGNALS)
        window.start()
        await self.write_read_check(
            ctp_config_addr(0),
            pack_ctp_config(invert=1),
            pack_ctp_config(invert=1),
            mask=XTRIG_CTP_CONFIG_MASK,
            label="regstall.ctp0.config",
        )
        await self.write_read_check(
            ctp_stretch_addr(0),
            stretch,
            stretch,
            mask=XTRIG_CTP_STRETCH_MASK,
            label="regstall.ctp0.stretch",
        )
        await self.write_read_check(
            ctm_config_addr(0), select, select, mask=XTRIG_CTM_SELECT_MASK, label="regstall.ctm0"
        )
        await ClockCycles(self.xtrig.clk, 2)
        activity, _hold, _last = await window.stop()
        for name in self.IN_FLIGHT_SIGNALS:
            self.check_evidence(
                self.CHK_QUIET,
                f"regstall.in_flight.{name}",
                activity.get(name, 0),
                0,
                context=f"cycles={window.cycles}",
            )
        await self.check_quiet("reg_stall_accepted")
        sample = await self.sample_xtrig("accepted_path")
        # A single access never fills a spill register, so the port keeps its
        # READY high and a regblock stall shows only at the demux behind it.
        for channel in ("aw", "ar"):
            self.check_evidence(
                self.CHK_AXIL,
                f"regstall.{channel}_stall_count_delta",
                sample[f"xtrig_demux_{channel}_stall_count"]
                - before[f"xtrig_demux_{channel}_stall_count"],
                0,
            )
            self.check_evidence(
                self.CHK_AXIL,
                f"regstall.{channel}valid_count_advanced",
                int(
                    sample[f"xtrig_axil_{channel}valid_count"]
                    - before[f"xtrig_axil_{channel}valid_count"]
                    > 0
                ),
                1,
            )
        # Positive control: a wire-OR route to a CTP and an internal CT and a
        # point-to-point route to a second CTP move every observable the
        # quiet records judged.
        await self.clear_xtrig()
        control = self.xtrig.activity_window(self.IN_FLIGHT_SIGNALS)
        control.start()
        await self.verify_route_mask(
            1 << internal_ct_port(int_idx),
            (1 << external_ctp_port(ctp_idx)) | (1 << internal_ct_port(int_out)),
            XTRIG_CTP_MODE_WIRE_OR,
            label="regstall.control.wire_or",
        )
        await self.verify_route(
            internal_ct_port(int_p2p),
            1 << external_ctp_port(ctp_p2p),
            XTRIG_CTP_MODE_P2P,
            label="regstall.control.p2p",
        )
        activity, _hold, _last = await control.stop()
        for name in self.IN_FLIGHT_SIGNALS:
            self.check_evidence(
                self.CHK_SIGNAL,
                f"regstall.control.{name}.live",
                int(activity[name] != 0),
                1,
                context=f"cycles={control.cycles}",
            )
        await self.clear_xtrig()
        self.log_summary(
            "reg_stall",
            rationale="local regblock stall path documented as structurally unreachable",
        )

    async def run_axi_channel_skew(self) -> None:
        self.log_banner("DTP XTRIG manual AXI-Lite AW/W and RREADY skew")
        # Seeded per-pass payloads and skew timing: each loop exercises the
        # channel-skew paths with different data, gaps, and READY delays.
        rng = self.rng("axi_channel_skew")
        addr = ctp_stretch_addr(rng.randrange(XTRIG_NUM_CTP))
        # Each write replaces a different value, so a dropped write reads back
        # the one before it.
        prior = await self.csr_read(addr, label="axi_skew.prior") & XTRIG_CTP_STRETCH_MASK
        d1 = prior ^ rng.randrange(1, 1 << 16)
        d2 = d1 ^ rng.randrange(1, 1 << 16)
        d3 = d2 ^ rng.randrange(1, 1 << 16)
        result = await self.axil.write_skewed_result(
            addr,
            d1,
            w_valid_delay=rng.randint(3, 7),
            b_ready_delay=rng.randint(*self.SKEW_B_READY_DELAY),
        )
        self.check_evidence(self.CHK_AXIL, "axi_skew.aw_before_w.bresp", result.resp, self.AXI_OKAY)
        observed = await self.csr_read(addr, label="axi_skew.aw_before_w.readback")
        self.check_evidence(
            self.CHK_AXIL, "axi_skew.aw_before_w.stretch", observed & XTRIG_CTP_STRETCH_MASK, d1
        )
        await self.write_read_check(
            addr, d2, d2, mask=XTRIG_CTP_STRETCH_MASK, label="axi_skew.normal_after_aw"
        )
        before = await self.sample_xtrig("axi_skew.w_before_aw.before")
        aw_delay = rng.randint(3, 7)
        result = await self.axil.write_skewed_result(
            addr,
            d3,
            aw_valid_delay=aw_delay,
            b_ready_delay=rng.randint(*self.SKEW_B_READY_DELAY),
        )
        after = await self.sample_xtrig("axi_skew.w_before_aw.after")
        delta = {
            name: after[name] - before[name]
            for name in (
                "xtrig_axil_w_stall_count",
                "xtrig_demux_w_stall_count",
                "xtrig_axil_spill_err_count",
            )
        }
        self.check_evidence(self.CHK_AXIL, "axi_skew.w_before_aw.bresp", result.resp, self.AXI_OKAY)
        # The CSR port's W spill register takes the early W beat with WREADY
        # high. The demux behind it passes a W beat from the cycle after its AW
        # enters the demux's W-select queue, so the beat stalls there for at
        # least the AW delay plus one cycle.
        self.check_evidence(
            self.CHK_AXIL,
            "axi_skew.w_before_aw.port_w_unstalled",
            delta["xtrig_axil_w_stall_count"],
            0,
        )
        self.check_evidence(
            self.CHK_AXIL,
            "axi_skew.w_before_aw.w_ready_low_seen",
            int(delta["xtrig_demux_w_stall_count"] >= aw_delay + 1),
            1,
            context=f"demux_w_stall_cycles={delta['xtrig_demux_w_stall_count']} aw_delay={aw_delay}",
        )
        self.check_evidence(
            self.CHK_AXIL,
            "axi_skew.w_before_aw.spill_contract",
            delta["xtrig_axil_spill_err_count"],
            0,
        )
        observed = await self.csr_read(addr, label="axi_skew.final_read")
        self.check_evidence(
            self.CHK_AXIL, "axi_skew.final_stretch", observed & XTRIG_CTP_STRETCH_MASK, d3
        )
        held = await self.axil.read_hold_result(addr, rng.randint(3, 7))
        self.check_evidence(self.CHK_AXIL, "axi_skew.rresp", held.resp, self.AXI_OKAY)
        self.check_evidence(self.CHK_AXIL, "axi_skew.rstable", int(held.hold_stable), 1)
        self.check_evidence(self.CHK_AXIL, "axi_skew.rdata", held.data & XTRIG_CTP_STRETCH_MASK, d3)
        self.log_summary("axi_channel_skew", final=f"0x{held.data:08x}")

    async def run_axi_channel_skew_demux_aw_lock_release(self) -> None:
        self.log_banner("DTP XTRIG AXI-Lite demux AW-lock release")
        # Seeded per-pass targets, payloads, and skew timing.
        rng = self.rng("demux_aw_lock")
        ctp_a, ctp_b = rng.sample(range(XTRIG_NUM_CTP), 2)
        data_a = pack_ctp_config(mode=rng.randrange(2), invert=rng.randrange(2))
        data_b = pack_ctp_config(mode=rng.randrange(2), invert=rng.randrange(2))
        self.log_step(1, "AW-first pair to two CTP ports: the second AW waits behind the pending W")
        await self.run_write_pair(
            ctp_config_addr(ctp_a),
            data_a,
            ctp_config_addr(ctp_b),
            data_b,
            w_valid_delay=rng.randint(4, 8),
            b_ready_delay=rng.randint(1, 4),
            label="demux_aw_lock.ctp_pair",
        )
        for addr, data, tag in (
            (ctp_config_addr(ctp_a), data_a, "ctp_a"),
            (ctp_config_addr(ctp_b), data_b, "ctp_b"),
        ):
            observed = await self.csr_read(addr, label=f"demux_aw_lock.{tag}.readback")
            self.check_evidence(
                self.CHK_AXIL,
                f"demux_aw_lock.{tag}.readback",
                observed & XTRIG_CTP_CONFIG_MASK,
                data & XTRIG_CTP_CONFIG_MASK,
            )
        self.log_step(2, "W-first pair to a CTM register and an unmapped word: responses in order")
        select_port = rng.randrange(XTRIG_NUM_CTM_PORTS)
        select = rng.randint(1, XTRIG_CTM_SELECT_MASK)
        unmapped = XTRIG_UNMAPPED_BASE + rng.randrange(0, 0x40) * 4
        result = await self.run_write_pair(
            ctm_config_addr(select_port),
            select,
            unmapped,
            rng.getrandbits(32),
            aw_valid_delay=rng.randint(4, 8),
            b_ready_delay=rng.randint(1, 4),
            label="demux_aw_lock.order",
            check_response=False,
        )
        self.check_evidence(
            self.CHK_AXIL, "demux_aw_lock.order.first_bresp", result.first.resp, self.AXI_OKAY
        )
        self.check_evidence(
            self.CHK_AXIL, "demux_aw_lock.order.second_bresp", result.second.resp, self.AXI_DECERR
        )
        observed = await self.csr_read(ctm_config_addr(select_port), label="demux_aw_lock.order")
        self.check_evidence(
            self.CHK_AXIL,
            "demux_aw_lock.order.readback",
            observed & XTRIG_CTM_SELECT_MASK,
            select,
        )
        self.log_summary("axi_channel_skew_demux_aw_lock_release", pairs=2)

    async def run_write_pair(
        self,
        addr_a: int,
        data_a: int,
        addr_b: int,
        data_b: int,
        *,
        aw_valid_delay: int = 0,
        w_valid_delay: int = 0,
        b_ready_delay: int = 0,
        label: str,
        check_response: bool = True,
    ):
        """Two outstanding skewed writes judged against the demux state mirrors.

        The CSR port's spill registers accept both AWs and both W beats with
        READY high. Behind them the demux queues the first AW's port selection
        until its W passes (``xtrig_demux_w_pending``) and holds the second AW
        meanwhile: the demux open-write counters see the second AW wait, and
        no AW admitted, while the first is owed its W. The AW lock flag, which
        needs a subordinate that refuses a presented AW, stays clear. Both
        responses must complete, every spill register's READY and VALID must
        match the beats it holds, and the port stall counter must agree with
        the VIP's AW observation.
        """
        before = await self.sample_xtrig(f"{label}.before")
        window = self.xtrig.activity_window(self.DEMUX_SIGNALS)
        window.start()
        result = await self.axil.write_pair_skewed_result(
            addr_a,
            data_a,
            addr_b,
            data_b,
            aw_valid_delay=aw_valid_delay,
            w_valid_delay=w_valid_delay,
            b_ready_delay=b_ready_delay,
            check_response=check_response,
        )
        activity, _hold, last = await window.stop()
        after = await self.sample_xtrig(f"{label}.after")
        delta = {name: after[name] - before[name] for name in self.AW_PAIR_COUNTERS}
        self.log.info(
            "%s aw_stall=%d aw_stable=%s w_pending_seen=%d aw_lock_seen=%d resp=%d/%d "
            "port_open_accept=%d w_spill_full=%d spill_err=%d demux_open_stall=%d "
            "demux_open_accept=%d",
            label,
            result.aw_stall_cycles,
            result.aw_stable,
            activity["xtrig_demux_w_pending"],
            activity["xtrig_demux_aw_lock"],
            result.first.resp,
            result.second.resp,
            delta["xtrig_axil_aw_open_accept_count"],
            delta["xtrig_axil_w_spill_full_count"],
            delta["xtrig_axil_spill_err_count"],
            delta["xtrig_demux_aw_open_stall_count"],
            delta["xtrig_demux_aw_open_accept_count"],
        )
        if check_response:
            self.check_evidence(
                self.CHK_AXIL, f"{label}.first_bresp", result.first.resp, self.AXI_OKAY
            )
            self.check_evidence(
                self.CHK_AXIL, f"{label}.second_bresp", result.second.resp, self.AXI_OKAY
            )
        self.check_evidence(
            self.CHK_AXIL, f"{label}.spill_contract", delta["xtrig_axil_spill_err_count"], 0
        )
        # A W-first pair fills the W spill register with both W beats. In an
        # AW-first pair the port accepts the second AW one cycle after the
        # first, which counts as an acceptance while the first is open only
        # when the first W beat trails its AW by two or more cycles.
        if aw_valid_delay > 0:
            self.check_evidence(
                self.CHK_AXIL,
                f"{label}.w_spill_holds_pair",
                int(delta["xtrig_axil_w_spill_full_count"] > 0),
                1,
                context=f"w_full_cycles={delta['xtrig_axil_w_spill_full_count']}",
            )
        elif w_valid_delay >= 2:
            self.check_evidence(
                self.CHK_AXIL,
                f"{label}.port_second_aw_accepted",
                delta["xtrig_axil_aw_open_accept_count"],
                1,
                context=f"port_open_stall_cycles={delta['xtrig_axil_aw_open_stall_count']}",
            )
        self.check_evidence(
            self.CHK_AW_LOCK, f"{label}.w_pending_engaged", activity["xtrig_demux_w_pending"], 1
        )
        self.check_evidence(
            self.CHK_AW_LOCK, f"{label}.w_pending_released", last["xtrig_demux_w_pending"], 0
        )
        self.check_evidence(
            self.CHK_AW_LOCK, f"{label}.aw_lock_clear", activity["xtrig_demux_aw_lock"], 0
        )
        self.check_evidence(
            self.CHK_AW_LOCK,
            f"{label}.second_aw_held_while_w_open",
            int(delta["xtrig_demux_aw_open_stall_count"] > 0),
            1,
            context=f"demux_open_stall_cycles={delta['xtrig_demux_aw_open_stall_count']}",
        )
        self.check_evidence(
            self.CHK_AW_LOCK,
            f"{label}.no_aw_accept_while_w_open",
            delta["xtrig_demux_aw_open_accept_count"],
            0,
        )
        self.check_evidence(
            self.CHK_AW_LOCK,
            f"{label}.aw_stall_count",
            delta["xtrig_axil_aw_stall_count"],
            result.aw_stall_cycles,
        )
        return result

    async def run_axi_channel_skew_read_decode_backpressure(self) -> None:
        self.log_banner("DTP XTRIG AXI-Lite read decode backpressure")
        # Seeded per-pass CTP, STRETCH_MULT value, unmapped offset and RREADY
        # hold width. The two reads target different subordinates: a CTP
        # register, then an unmapped word.
        rng = self.rng("read_decode_backpressure")
        addr_a = ctp_stretch_addr(rng.randrange(XTRIG_NUM_CTP))
        addr_b = XTRIG_UNMAPPED_BASE + rng.randrange(0, 0x40) * 4
        stretch = rng.randrange(1, 1 << 16)
        hold = rng.randint(4, 8)
        await self.csr_write(addr_a, stretch, label="read_decode.first.write")
        before = await self.sample_xtrig("read_decode.before")
        result = await self.axil.read_pair_hold_result(addr_a, addr_b, hold, check_response=False)
        after = await self.sample_xtrig("read_decode.after")
        delta = {name: after[name] - before[name] for name in self.AR_PAIR_COUNTERS}
        self.log.info(
            "read pair a=0x%x b=0x%x hold=%d resp=%d/%d data=0x%08x/0x%08x ar_stall=%d "
            "ar_stable=%s hold_stable=%s port_open_accept=%d r_spill_full=%d spill_err=%d "
            "demux_open_stall=%d demux_open_accept=%d",
            addr_a,
            addr_b,
            hold,
            result.first.resp,
            result.second.resp,
            result.first.data,
            result.second.data,
            result.ar_stall_cycles,
            result.ar_stable,
            result.first.hold_stable,
            delta["xtrig_axil_ar_open_accept_count"],
            delta["xtrig_axil_r_spill_full_count"],
            delta["xtrig_axil_spill_err_count"],
            delta["xtrig_demux_ar_open_stall_count"],
            delta["xtrig_demux_ar_open_accept_count"],
        )
        # The first read returns the STRETCH_MULT word written before the pair.
        # No subordinate decodes the unmapped second address: AXI answers DECERR.
        self.check_evidence(
            self.CHK_AXIL, "read_decode.first.resp", result.first.resp, self.AXI_OKAY
        )
        self.check_evidence(
            self.CHK_AXIL,
            "read_decode.first.data",
            result.first.data & XTRIG_CTP_STRETCH_MASK,
            stretch,
        )
        self.check_evidence(
            self.CHK_AXIL, "read_decode.second.resp", result.second.resp, self.AXI_DECERR
        )
        self.check_evidence(
            self.CHK_AXIL, "read_decode.first.hold_stable", int(result.first.hold_stable), 1
        )
        stall_delta = delta["xtrig_axil_ar_stall_count"]
        self.check_evidence(
            self.CHK_AXIL, "read_decode.spill_contract", delta["xtrig_axil_spill_err_count"], 0
        )
        self.check_evidence(
            self.CHK_AXIL,
            "read_decode.port_second_ar_accepted",
            delta["xtrig_axil_ar_open_accept_count"],
            1,
            context=f"port_open_stall_cycles={delta['xtrig_axil_ar_open_stall_count']}",
        )
        self.check_evidence(
            self.CHK_AXIL,
            "read_decode.r_spill_holds_pair",
            int(delta["xtrig_axil_r_spill_full_count"] > 0),
            1,
            context=f"r_full_cycles={delta['xtrig_axil_r_spill_full_count']}",
        )
        # The demux admits one read in flight. The two reads go to different
        # subordinates, so the demux alone holds the second AR, and admits
        # none, while the first read is owed its R beat.
        self.check_evidence(
            self.CHK_AR_STALL,
            "read_decode.second_ar_held_while_read_open",
            int(delta["xtrig_demux_ar_open_stall_count"] > 0),
            1,
            context=f"demux_open_stall_cycles={delta['xtrig_demux_ar_open_stall_count']}",
        )
        self.check_evidence(
            self.CHK_AR_STALL,
            "read_decode.no_ar_accept_while_read_open",
            delta["xtrig_demux_ar_open_accept_count"],
            0,
        )
        self.check_evidence(
            self.CHK_AR_STALL, "read_decode.ar_stall_count", stall_delta, result.ar_stall_cycles
        )
        self.check_evidence(
            self.CHK_AR_STALL,
            "read_decode.ar_accepted",
            delta["xtrig_axil_arvalid_count"] - stall_delta,
            2,
        )
        self.log_summary(
            "axi_channel_skew_read_decode_backpressure", unmapped_base=f"0x{XTRIG_UNMAPPED_BASE:x}"
        )

    # ------------------------------------------------------------------
    # CTM route scenarios
    # ------------------------------------------------------------------
    # Seeded per-pass port picks: every source/destination CTP and internal CT
    # is interchangeable per spec, so each loop proves the route class on a
    # different port set. Inputs are kept out of the output masks so the
    # isolation check stays meaningful.
    async def run_ctm_wire_or_cla_to_ctp(self) -> None:
        rng = self.rng("ctm_wire_or_cla_to_ctp")
        int_in, int_ovl = rng.sample(range(XTRIG_NUM_INT_CT), 2)
        outs = rng.sample(range(XTRIG_NUM_CTP), 3)
        await self.run_ctm_wire_or_route_class(
            "cla_to_ctp",
            internal_ct_port(int_in),
            ctp_mask(*outs),
            overlap_input=internal_ct_port(int_ovl),
            overlap_output=external_ctp_port(rng.choice(outs)),
        )

    async def run_ctm_wire_or_ctp_to_cla(self) -> None:
        rng = self.rng("ctm_wire_or_ctp_to_cla")
        ctp_in, ctp_ovl = rng.sample(range(XTRIG_NUM_CTP), 2)
        outs = rng.sample(range(XTRIG_NUM_INT_CT), 3)
        await self.run_ctm_wire_or_route_class(
            "ctp_to_cla",
            external_ctp_port(ctp_in),
            internal_ct_mask(*outs),
            overlap_input=external_ctp_port(ctp_ovl),
            overlap_output=internal_ct_port(rng.choice(outs)),
        )

    async def run_ctm_wire_or_cla_to_cla(self) -> None:
        rng = self.rng("ctm_wire_or_cla_to_cla")
        picks = rng.sample(range(XTRIG_NUM_INT_CT), 5)
        int_in, int_ovl, outs = picks[0], picks[1], picks[2:5]
        await self.run_ctm_wire_or_route_class(
            "cla_to_cla",
            internal_ct_port(int_in),
            internal_ct_mask(*outs),
            overlap_input=internal_ct_port(int_ovl),
            overlap_output=internal_ct_port(rng.choice(outs)),
        )

    async def run_ctm_wire_or_ctp_to_ctp(self) -> None:
        rng = self.rng("ctm_wire_or_ctp_to_ctp")
        picks = rng.sample(range(XTRIG_NUM_CTP), 5)
        ctp_in, ctp_ovl, outs = picks[0], picks[1], picks[2:5]
        await self.run_ctm_wire_or_route_class(
            "ctp_to_ctp",
            external_ctp_port(ctp_in),
            ctp_mask(*outs),
            overlap_input=external_ctp_port(ctp_ovl),
            overlap_output=external_ctp_port(rng.choice(outs)),
        )

    async def run_ctm_wire_or_route_class(
        self,
        name: str,
        input_port: int,
        output_mask: int,
        *,
        overlap_input: int,
        overlap_output: int,
    ) -> None:
        self.log_banner(f"DTP CTM wire-OR routing {name}")
        await self.verify_route(
            input_port, output_mask, XTRIG_CTP_MODE_WIRE_OR, label=f"wire_or.{name}.main"
        )
        # Two sources selected into one destination: each source alone reaches
        # it, and both pulsed in the same cycle merge into one pulse of the
        # single-source width.
        both = (1 << input_port) | (1 << overlap_input)
        await self.clear_ctm_routes()
        await self.configure_ctp_modes_for_route_mask(
            both, 1 << overlap_output, XTRIG_CTP_MODE_WIRE_OR
        )
        await self.program_ctm_src(overlap_output, both)
        for tag, pulsed in (
            ("overlap_second", 1 << overlap_input),
            ("overlap_first", 1 << input_port),
        ):
            await self.run_route_window(
                pulsed, 1 << overlap_output, XTRIG_CTP_MODE_WIRE_OR, label=f"wire_or.{name}.{tag}"
            )
        signal, bit = self.request_observable(overlap_output)
        width_task = cocotb.start_soon(self.xtrig.measure_mask_width(signal, 1 << bit))
        await self.run_route_window(
            both,
            1 << overlap_output,
            XTRIG_CTP_MODE_WIRE_OR,
            label=f"wire_or.{name}.overlap_merged",
        )
        pulse = await width_task
        self.check_evidence(
            self.CHK_STRETCH,
            f"wire_or.{name}.merged_width",
            pulse.width,
            self.ROUTE_STRETCH_MULT + 1,
            context=f"output={overlap_output} sources=0x{both:x}",
        )
        self.check_evidence(
            self.CHK_STRETCH,
            f"wire_or.{name}.merged_pulses",
            pulse.pulses,
            1,
            context=f"output={overlap_output} sources=0x{both:x}",
        )
        self.log_summary(f"ctm_wire_or_{name}", input=input_port, outputs=f"0x{output_mask:x}")

    def request_observable(self, output_port: int) -> tuple[str, int]:
        """Observable and bit that carry a wire-OR request of ``output_port``."""
        if self.is_ctp_port(output_port):
            return "xtrig_ctp_req_out_dout_en", output_port
        return "xtrig_ctm_src_req", self.int_idx_from_port(output_port)

    # Seeded per-pass pairs: each loop proves the P2P route class on three
    # different source/destination combinations (source != destination).
    async def run_ctm_p2p_cla_to_ctp(self) -> None:
        rng = self.rng("ctm_p2p_cla_to_ctp")
        pairs = [
            (internal_ct_port(i), external_ctp_port(c))
            for i, c in zip(
                rng.sample(range(XTRIG_NUM_INT_CT), 3), rng.sample(range(XTRIG_NUM_CTP), 3)
            )
        ]
        await self.run_ctm_p2p_route_class("cla_to_ctp", pairs)

    async def run_ctm_p2p_ctp_to_cla(self) -> None:
        rng = self.rng("ctm_p2p_ctp_to_cla")
        pairs = [
            (external_ctp_port(c), internal_ct_port(i))
            for c, i in zip(
                rng.sample(range(XTRIG_NUM_CTP), 3), rng.sample(range(XTRIG_NUM_INT_CT), 3)
            )
        ]
        await self.run_ctm_p2p_route_class("ctp_to_cla", pairs)

    async def run_ctm_p2p_cla_to_cla(self) -> None:
        rng = self.rng("ctm_p2p_cla_to_cla")
        picks = rng.sample(range(XTRIG_NUM_INT_CT), 6)
        pairs = [(internal_ct_port(picks[k]), internal_ct_port(picks[k + 3])) for k in range(3)]
        await self.run_ctm_p2p_route_class("cla_to_cla", pairs)

    async def run_ctm_p2p_ctp_to_ctp(self) -> None:
        rng = self.rng("ctm_p2p_ctp_to_ctp")
        picks = rng.sample(range(XTRIG_NUM_CTP), 6)
        pairs = [(external_ctp_port(picks[k]), external_ctp_port(picks[k + 3])) for k in range(3)]
        await self.run_ctm_p2p_route_class("ctp_to_ctp", pairs)

    async def run_ctm_p2p_route_class(self, name: str, pairs: list[tuple[int, int]]) -> None:
        self.log_banner(f"DTP CTM point-to-point routing {name}")
        for idx, (input_port, output_port) in enumerate(pairs, start=1):
            self.log_iteration(
                idx, len(pairs), "%s input=%d output=%d", name, input_port, output_port
            )
            await self.verify_route(
                input_port, 1 << output_port, XTRIG_CTP_MODE_P2P, label=f"p2p.{name}.{idx}"
            )
        self.log_summary(f"ctm_p2p_{name}", pairs=len(pairs))

    # ------------------------------------------------------------------
    # CTM reset and random scenarios
    # ------------------------------------------------------------------
    async def run_ctm_reset_wire_or_mode(self) -> None:
        self.log_banner("DTP CTM reset in wire-OR mode")
        # Seeded per-pass ports: each loop resets and recovers different routes.
        rng = self.rng("ctm_reset_wire_or")
        int_a, int_b, int_c = rng.sample(range(XTRIG_NUM_INT_CT), 3)
        ctps = rng.sample(range(XTRIG_NUM_CTP), 5)
        inverted = rng.randrange(2)
        active = ctp_mask(ctps[0], ctps[1])
        self.log_step(
            1,
            "Two outputs, CTP[%d] inverted, hold a long stretched pulse when the reset lands",
            ctps[inverted],
        )
        for k, ctp_idx in enumerate(ctps[:2]):
            await self.program_ctp(
                ctp_idx,
                mode=XTRIG_CTP_MODE_WIRE_OR,
                invert=int(k == inverted),
                stretch=self.RESET_HOLD_STRETCH,
            )
        await self.program_routes(
            1 << internal_ct_port(int_a),
            active | (1 << internal_ct_port(int_c)),
            label="reset_wire_or.pre",
        )
        live = self.xtrig.activity_window(self.RESET_SIGNALS_WIRE_OR)
        live.start()
        await self.idle_inputs()
        await self.xtrig.pulse_ctm_dst_req(1 << int_a, cycles=1)
        await self.wait_signal_mask(
            "xtrig_ctp_req_out_dout_en", active, active, label="reset_wire_or.active_before"
        )
        await self.wait_window_fired(
            "xtrig_ctm_src_req", 1 << int_c, live, label="reset_wire_or.internal_active"
        )
        # Each output drives its own wire, so each receives its own pull.
        await self.wait_window_fired(
            "xtrig_ctp_ct_dst", active, live, label="reset_wire_or.self_receive"
        )
        await self.check_status(ctps[0], "reset_wire_or.active_before", busy=1)
        await self.reset_window("ctm_reset_wire_or", watched=self.RESET_SIGNALS_WIRE_OR, live=live)
        self.log_step(2, "Routing and CTP state read their defaults, then fresh routes recover")
        await self.check_all_ctm_cleared("reset_wire_or")
        await self.check_ctp_defaults("reset_wire_or")
        await self.verify_route(
            internal_ct_port(int_b),
            ctp_mask(*ctps[2 : 2 + rng.randint(2, 3)]),
            XTRIG_CTP_MODE_WIRE_OR,
            label="reset_wire_or.post",
        )
        self.log_summary("ctm_reset_wire_or")

    async def run_ctm_reset_p2p_mode(self) -> None:
        self.log_banner("DTP CTM reset in P2P mode")
        # Seeded per-pass ports: each loop resets and recovers different routes.
        rng = self.rng("ctm_reset_p2p")
        int_a, int_b, int_c = rng.sample(range(XTRIG_NUM_INT_CT), 3)
        ctps = rng.sample(range(XTRIG_NUM_CTP), 3)
        mask = 1 << ctps[0]
        rx = 1 << ctps[1]
        self.log_step(
            1,
            "A P2P request stays pending without its acknowledge, and a second P2P port holds "
            "a received request, when the reset lands",
        )
        await self.configure_ctp_mode_for_port(ctps[0], XTRIG_CTP_MODE_P2P)
        await self.program_route(internal_ct_port(int_a), mask, label="reset_p2p.pre")
        await self.configure_ctp_mode_for_port(ctps[1], XTRIG_CTP_MODE_P2P)
        await self.program_ctm_src(internal_ct_port(int_c), rx)
        live = self.xtrig.activity_window(self.RESET_SIGNALS)
        live.start()
        await self.idle_inputs()
        await self.xtrig.pulse_ctm_dst_req(1 << int_a, cycles=2)
        await self.wait_signal_mask(
            "xtrig_ctp_req_out_dout",
            mask,
            self.pad_level(mask, asserted=True),
            label="reset_p2p.stuck_req",
        )
        await self.check_status(ctps[0], "reset_p2p.before", busy=1, req_out=1)
        await self.drive_p2p_req_in(ctps[1], asserted=True)
        await self.wait_signal_mask(
            "xtrig_ctp_ack_out_dout",
            rx,
            self.pad_level(rx, asserted=True),
            label="reset_p2p.rx_ack_held",
        )
        await self.wait_window_fired(
            "xtrig_ctm_src_req", 1 << int_c, live, label="reset_p2p.rx_delivered"
        )
        await self.reset_window("ctm_reset_p2p", watched=self.RESET_SIGNALS, live=live)
        self.log_step(
            2,
            "The handshake, routing, and CTP state read their defaults, then a fresh route completes",
        )
        await self.check_status(ctps[0], "reset_p2p.after", busy=0, req_out=0)
        await self.check_all_ctm_cleared("reset_p2p")
        await self.check_ctp_defaults("reset_p2p")
        await self.verify_route(
            internal_ct_port(int_b),
            1 << external_ctp_port(ctps[2]),
            XTRIG_CTP_MODE_P2P,
            label="reset_p2p.post",
        )
        self.log_summary("ctm_reset_p2p")

    async def run_ctm_reset_all_modes(self) -> None:
        self.log_banner("DTP CTM reset across wire-OR and P2P modes")
        # Seeded per-pass ports: each loop resets and recovers different routes.
        rng = self.rng("ctm_reset_all_modes")
        int_a, int_b, int_c = rng.sample(range(XTRIG_NUM_INT_CT), 3)
        ctps = rng.sample(range(XTRIG_NUM_CTP), 5)
        # Both classes programmed together and each pulsed, so the reset lands
        # on live routing state of both kinds: one wire-OR source to two CTPs
        # and one internal CT (so the internal request outputs are a live
        # observable of this test), one P2P source to a third CTP, and a fifth
        # CTP in P2P mode that receives a request.
        wire_in = 1 << internal_ct_port(int_a)
        wire_outputs = (
            external_ctp_port(ctps[0]),
            external_ctp_port(ctps[1]),
            internal_ct_port(int_c),
        )
        wire_mask = sum(1 << port for port in wire_outputs)
        p2p_in = 1 << internal_ct_port(int_b)
        p2p_mask = 1 << external_ctp_port(ctps[2])
        rx = 1 << external_ctp_port(ctps[4])
        await self.configure_ctp_modes_for_route_mask(wire_in, wire_mask, XTRIG_CTP_MODE_WIRE_OR)
        await self.configure_ctp_modes_for_route_mask(p2p_in, p2p_mask, XTRIG_CTP_MODE_P2P)
        await self.configure_ctp_mode_for_port(external_ctp_port(ctps[4]), XTRIG_CTP_MODE_P2P)
        await self.clear_ctm_routes()
        for port in wire_outputs:
            await self.program_ctm_src(port, wire_in)
        await self.program_ctm_src(external_ctp_port(ctps[2]), p2p_in)
        live = self.xtrig.activity_window(self.RESET_SIGNALS)
        live.start()
        await self.run_route_window(
            wire_in, wire_mask, XTRIG_CTP_MODE_WIRE_OR, label="reset_all.pre_wire"
        )
        await self.run_route_window(p2p_in, p2p_mask, XTRIG_CTP_MODE_P2P, label="reset_all.pre_p2p")
        self.log_step(
            2,
            "A P2P request stays pending without its acknowledge, and a second P2P port holds "
            "a received request, when the reset lands",
        )
        await self.idle_inputs()
        await self.drive_input_mask(p2p_in, XTRIG_CTP_MODE_P2P)
        await self.wait_signal_mask(
            "xtrig_ctp_req_out_dout",
            p2p_mask,
            self.pad_level(p2p_mask, asserted=True),
            label="reset_all.stuck_req",
        )
        await self.check_status(ctps[2], "reset_all.before", busy=1, req_out=1)
        await self.drive_p2p_req_in(ctps[4], asserted=True)
        await self.wait_signal_mask(
            "xtrig_ctp_ack_out_dout",
            rx,
            self.pad_level(rx, asserted=True),
            label="reset_all.rx_ack_held",
        )
        await self.reset_window("ctm_reset_all", watched=self.RESET_SIGNALS, live=live)
        await self.check_status(ctps[2], "reset_all.after", busy=0, req_out=0)
        await self.check_all_ctm_cleared("reset_all")
        await self.check_ctp_defaults("reset_all")
        await self.verify_route(
            internal_ct_port(int_a),
            1 << external_ctp_port(ctps[0]),
            XTRIG_CTP_MODE_WIRE_OR,
            label="reset_all.post_wire",
        )
        await self.verify_route(
            internal_ct_port(int_b),
            1 << external_ctp_port(ctps[3]),
            XTRIG_CTP_MODE_P2P,
            label="reset_all.post_p2p",
        )
        self.log_summary("ctm_reset_all_modes")

    async def run_ctm_rand_all_scenarios(self) -> None:
        await self.run_ctm_random(
            "all_scenarios", source_class="all", dest_class="all", multicast=True, p2p=True
        )

    async def run_ctm_rand_wire_or_only(self) -> None:
        await self.run_ctm_random(
            "wire_or_only", source_class="all", dest_class="all", multicast=True, p2p=False
        )

    async def run_ctm_rand_p2p_only(self) -> None:
        await self.run_ctm_random(
            "p2p_only", source_class="all", dest_class="all", multicast=False, p2p=True
        )

    async def run_ctm_rand_cla_to_ctp(self) -> None:
        await self.run_ctm_random(
            "cla_to_ctp", source_class="internal", dest_class="ctp", multicast=True, p2p=True
        )

    async def run_ctm_rand_ctp_to_cla(self) -> None:
        await self.run_ctm_random(
            "ctp_to_cla", source_class="ctp", dest_class="internal", multicast=True, p2p=True
        )

    async def run_p2p_pair_isolation(
        self,
        rng: Random,
        name: str,
        input_mask: int,
        output_mask: int,
        *,
        source_pool: list[int],
        dest_pool: list[int],
        label: str,
    ) -> None:
        """A second point-to-point route alongside ``input_mask -> output_mask``.

        Programmed without clearing the first and each pulsed alone: a request
        on either route reaches only its own destination while the other stays
        live. A pending route of the mix on free ports is preferred.
        """
        used = input_mask | output_mask
        free_src = [port for port in source_pool if not (used >> port) & 1]
        free_dst = [port for port in dest_pool if not (used >> port) & 1]
        pending = self._route_pending.get(name, [])
        candidates = [
            (src, dst)
            for (src, dst) in pending
            if src in free_src and dst in free_dst and src != dst
        ]
        if candidates:
            in2, out2 = rng.choice(candidates)
        else:
            if not free_src:
                return
            in2 = rng.choice(free_src)
            free_dst = [port for port in free_dst if port != in2]
            if not free_dst:
                return
            out2 = rng.choice(free_dst)
        if (in2, out2) in pending:
            pending.remove((in2, out2))
        self._route_driven.setdefault(name, set()).add((in2, out2))
        self.log.info("%s: second P2P route input=%d output=%d alongside", label, in2, out2)
        await self.configure_ctp_modes_for_route_mask(1 << in2, 1 << out2, XTRIG_CTP_MODE_P2P)
        await self.program_ctm_src(out2, 1 << in2)
        await self.run_route_window(
            1 << in2, 1 << out2, XTRIG_CTP_MODE_P2P, label=f"{label}.pair_second"
        )
        await self.run_route_window(
            input_mask, output_mask, XTRIG_CTP_MODE_P2P, label=f"{label}.pair_first"
        )

    async def run_ctm_random(
        self, name: str, *, source_class: str, dest_class: str, multicast: bool, p2p: bool
    ) -> None:
        """Seeded route mixes.

        A wire-OR iteration selects one or two sources on two to four outputs;
        a point-to-point iteration adds a second, disjoint route alongside its
        own and pulses each alone. Each iteration starts from the first pending
        route of the mix, adds a second source that shares its destination and
        further outputs of its source that are still pending, and draws its
        trigger timing: the pulse width and the idle lead before it. A
        point-to-point CTP source holds its request for the drawn width and
        until its acknowledge. The last pass of a ``ROUTE_WALK_MIXES`` mix
        continues with single-source iterations until every route of the mix
        has been driven alone, and counts those routes.
        """
        self.log_banner(f"DTP CTM seeded random routing {name}")
        rng = self.rng(f"ctm_random_{name}")
        source_pool = self.port_pool(source_class)
        dest_pool = self.port_pool(dest_class)
        walk = [(s, d) for s in source_pool for d in dest_pool if s != d]
        closes_walk = name in self.ROUTE_WALK_MIXES
        if closes_walk and self.total_passes == 0:
            raise ValueError(
                f"ctm_rand_{name} needs total_passes to find the pass that closes its walk"
            )
        for idx in range(self.random_count):
            await self._ctm_random_iteration(
                rng,
                name,
                idx,
                self.random_count,
                walk=walk,
                source_pool=source_pool,
                dest_pool=dest_pool,
                multicast=multicast,
                p2p=p2p,
            )
        iterations = self.random_count
        driven = self._route_driven.setdefault(name, set())
        if closes_walk and self.loop_index == self.total_passes - 1:
            # Every single-source iteration retires at least its head route,
            # so the walk closes within this many iterations.
            bound = iterations + len(walk) - len(driven)
            while len(driven) < len(walk) and iterations < bound:
                await self._ctm_random_iteration(
                    rng,
                    name,
                    iterations,
                    bound,
                    walk=walk,
                    source_pool=source_pool,
                    dest_pool=dest_pool,
                    multicast=multicast,
                    p2p=p2p,
                    single_source=True,
                )
                iterations += 1
            self.check_evidence(
                self.CHK_ROUTE_MODEL,
                f"rand.{name}.routes_driven",
                len(driven),
                len(walk),
                context=f"iterations={iterations}",
            )
        self.log_summary(f"ctm_rand_{name}", iterations=iterations)

    async def _ctm_random_iteration(
        self,
        rng: Random,
        name: str,
        idx: int,
        total: int,
        *,
        walk: list[tuple[int, int]],
        source_pool: list[int],
        dest_pool: list[int],
        multicast: bool,
        p2p: bool,
        single_source: bool = False,
    ) -> None:
        """One route-mix iteration from the head of the walk; a single-source window retires the routes it drives."""
        mode = (
            XTRIG_CTP_MODE_P2P
            if (p2p and (not multicast or rng.randrange(2)))
            else XTRIG_CTP_MODE_WIRE_OR
        )
        n_inputs = (
            2 if not single_source and mode == XTRIG_CTP_MODE_WIRE_OR and rng.randrange(2) else 1
        )
        pulse_cycles = rng.randint(2, CTM_RAND_PULSE_MAX_CYCLES)
        lead_cycles = rng.randint(0, CTM_RAND_LEAD_MAX_CYCLES)
        pending = self._route_pending.get(name)
        if not pending:
            pending = list(walk)
            rng.shuffle(pending)
            self._route_pending[name] = pending
        head_src, head_dst = pending[0]
        inputs = [head_src]
        if n_inputs == 2:
            others = [s for s in source_pool if s not in (head_src, head_dst)]
            partners = [s for s in others if (s, head_dst) in pending]
            if partners or others:
                inputs.append(rng.choice(partners or others))
        input_mask = sum(1 << port for port in inputs)
        selected = [head_dst]
        if mode == XTRIG_CTP_MODE_WIRE_OR:
            rest = [d for d in dest_pool if d != head_dst and d not in inputs]
            pending_dst = [d for d in rest if (head_src, d) in pending]
            other_dst = [d for d in rest if (head_src, d) not in pending]
            rng.shuffle(pending_dst)
            rng.shuffle(other_dst)
            extra = pending_dst + other_dst
            k = min(4, len(extra) + 1)
            selected += extra[: rng.randint(min(2, k), k) - 1]
        output_mask = sum(1 << port for port in selected)
        # With two sources selected on every output a missing select bit of
        # either source goes unseen, so only a single-source window retires
        # the routes it drives.
        if len(inputs) == 1:
            retired = {(head_src, d) for d in selected}
            pending[:] = [route for route in pending if route not in retired]
            self._route_driven.setdefault(name, set()).update(retired)
        self.log_iteration(
            idx + 1,
            total,
            "inputs=0x%x mode=%d outputs=0x%x pulse=%d lead=%d",
            input_mask,
            mode,
            output_mask,
            pulse_cycles,
            lead_cycles,
        )
        await self.verify_route_mask(
            input_mask,
            output_mask,
            mode,
            label=f"rand.{name}.{idx}",
            pulse_cycles=pulse_cycles,
            lead_cycles=lead_cycles,
        )
        if mode == XTRIG_CTP_MODE_P2P:
            await self.run_p2p_pair_isolation(
                rng,
                name,
                input_mask,
                output_mask,
                source_pool=source_pool,
                dest_pool=dest_pool,
                label=f"rand.{name}.{idx}",
            )

    @staticmethod
    def port_pool(port_class: str) -> list[int]:
        if port_class == "ctp":
            return list(range(XTRIG_NUM_CTP))
        if port_class == "internal":
            return [internal_ct_port(idx) for idx in range(XTRIG_NUM_INT_CT)]
        return list(range(XTRIG_NUM_CTM_PORTS))

    async def run_ctm_csr_sweep(self) -> None:
        self.log_banner("DTP CTM deterministic CSR byte-strobe and mask sweep")
        # Seeded per-pass extra pattern and byte-strobe payloads on top of the
        # deterministic sweep. Reserved bits [31:26] are driven to 1 by the
        # all-ones and inverted patterns and must read back 0.
        rng = self.rng("ctm_csr_sweep")
        random_mask = rng.randint(1, XTRIG_CTM_SELECT_MASK)
        patterns = [
            0,
            1,
            1 << external_ctp_port(0),
            1 << internal_ct_port(0),
            XTRIG_CTM_SELECT_MASK,
            0x0155_AA55 & XTRIG_CTM_SELECT_MASK,
            random_mask,
            FULL_WORD,
            (~0x0155_AA55) & FULL_WORD,
            (~random_mask) & FULL_WORD,
        ]
        for src_idx in range(XTRIG_NUM_CTM_PORTS):
            self.log_iteration(src_idx + 1, XTRIG_NUM_CTM_PORTS, "CT_SRC[%d] CSR sweep", src_idx)
            for pat_idx, word in enumerate(patterns):
                await self.write_read_check(
                    ctm_config_addr(src_idx),
                    word,
                    word & XTRIG_CTM_SELECT_MASK,
                    label=f"ctm{src_idx}.pat{pat_idx}",
                )
            for wstrb in (0x1, 0x2, 0x4, 0x8):
                old_mask = rng.getrandbits(32) & XTRIG_CTM_SELECT_MASK
                new_mask = rng.getrandbits(32)
                held = apply_wstrb(old_mask, new_mask, wstrb) & XTRIG_CTM_SELECT_MASK
                await self.program_ctm_src(src_idx, old_mask)
                await self.write_read_check(
                    ctm_config_addr(src_idx),
                    new_mask,
                    held,
                    wstrb=wstrb,
                    label=f"ctm{src_idx}.wstrb{wstrb:x}",
                )
            # The word past CT_SRC[src_idx] in its slot is a hole: it reads 0
            # after an all-ones write, and the write leaves the register on its
            # last word.
            await self.write_read_check(
                ctm_hole_addr(src_idx), FULL_WORD, 0, label=f"ctm{src_idx}.hole"
            )
            observed = await self.csr_read(
                ctm_config_addr(src_idx), label=f"ctm{src_idx}.hole_after"
            )
            self.check_evidence(
                self.CHK_CSR,
                f"ctm{src_idx}.hole_no_alias",
                observed,
                held,
                context=f"src={src_idx}",
            )
        # The matrix aperture past its register extent and every word past the
        # last CTP window decode to no register: a write and a read of a seeded
        # word of each complete with DECERR.
        for name, addr in (
            (
                "ctm_unmapped",
                XTRIG_CTM_END + rng.randrange((XTRIG_CTP_BASE - XTRIG_CTM_END) // 4) * 4,
            ),
            ("unmapped", XTRIG_UNMAPPED_BASE + rng.randrange(0, 0x40) * 4),
        ):
            resp = await self.axil.write(addr, FULL_WORD)
            self.check_evidence(
                self.CHK_CSR, f"{name}.bresp", resp, self.AXI_DECERR, context=f"addr=0x{addr:03x}"
            )
            result = await self.axil.read_result(addr)
            self.check_evidence(
                self.CHK_CSR,
                f"{name}.rresp",
                result.resp,
                self.AXI_DECERR,
                context=f"addr=0x{addr:03x}",
            )
        self.log_step(
            "route",
            "Two swept output registers route a selected input and ignore an unselected one",
        )
        for k, output_port in enumerate(rng.sample(range(XTRIG_NUM_CTM_PORTS), 2)):
            await self.verify_swept_select(
                output_port, random_mask, rng, label=f"ctm_csr_sweep.route{k}"
            )
        await self.clear_ctm_routes()
        self.log_summary("ctm_csr_sweep", sources=XTRIG_NUM_CTM_PORTS)

    async def verify_swept_select(
        self, output_port: int, select: int, rng: Random, *, label: str
    ) -> None:
        """One output holding a multi-bit select fires for a selected input and stays quiet for an unselected one."""
        select &= XTRIG_CTM_SELECT_MASK & ~(1 << output_port)
        selected = [p for p in self.port_bits(select)]
        unselected = [
            p for p in range(XTRIG_NUM_CTM_PORTS) if p != output_port and not (select >> p) & 1
        ]
        input_in = rng.choice(selected)
        await self.configure_ctp_modes_for_route_mask(
            1 << input_in, 1 << output_port, XTRIG_CTP_MODE_WIRE_OR
        )
        await self.clear_ctm_routes()
        await self.program_ctm_src(output_port, select)
        await self.run_route_window(
            1 << input_in, 1 << output_port, XTRIG_CTP_MODE_WIRE_OR, label=f"{label}.selected"
        )
        if unselected:
            input_out = rng.choice(unselected)
            await self.configure_ctp_modes_for_route_mask(1 << input_out, 0, XTRIG_CTP_MODE_WIRE_OR)
            await self.run_route_window(
                1 << input_out, 0, XTRIG_CTP_MODE_WIRE_OR, label=f"{label}.unselected"
            )

    async def run_ctm_all_source_select(self) -> None:
        self.log_banner("DTP CTM all-source select coverage")
        # Seeded per-pass extra mask on top of the deterministic per-source set.
        rng = self.rng("ctm_all_source_select")
        for src_idx in range(XTRIG_NUM_CTM_PORTS):
            masks = [
                1 << (src_idx % XTRIG_NUM_CTM_PORTS),
                (1 << src_idx) | (1 << ((src_idx + 1) % XTRIG_NUM_CTM_PORTS)),
                (~(1 << src_idx)) & XTRIG_CTM_SELECT_MASK,
                rng.randint(1, XTRIG_CTM_SELECT_MASK),
            ]
            neighbor = ctm_config_addr((src_idx + 1) % XTRIG_NUM_CTM_PORTS)
            before_neighbor = await self.csr_read(
                neighbor, label=f"allsrc{src_idx}.neighbor_before"
            )
            for mask_idx, dst_mask in enumerate(masks):
                await self.write_read_check(
                    ctm_config_addr(src_idx),
                    dst_mask,
                    dst_mask,
                    mask=XTRIG_CTM_SELECT_MASK,
                    label=f"allsrc{src_idx}.mask{mask_idx}",
                )
            after_neighbor = await self.csr_read(neighbor, label=f"allsrc{src_idx}.neighbor_after")
            self.check_evidence(
                self.CHK_CSR,
                f"allsrc{src_idx}.neighbor_no_alias",
                after_neighbor & XTRIG_CTM_SELECT_MASK,
                before_neighbor & XTRIG_CTM_SELECT_MASK,
                context=f"ct_src={(src_idx + 1) % XTRIG_NUM_CTM_PORTS}",
            )
            # One routed pulse per source: its select decodes into the matrix.
            await self.verify_route(
                src_idx,
                1 << ((src_idx + 1) % XTRIG_NUM_CTM_PORTS),
                XTRIG_CTP_MODE_WIRE_OR,
                label=f"allsrc{src_idx}.route",
            )
        self.log_summary("ctm_all_source_select", sources=XTRIG_NUM_CTM_PORTS)
