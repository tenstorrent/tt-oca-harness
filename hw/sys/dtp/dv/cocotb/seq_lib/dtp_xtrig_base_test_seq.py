# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Helper base of the cross-trigger scenario sequences.

CSR accessors, the CTM reference model and CTP shadow, the pin drivers and
samplers, route windows, and per-pass ``CHK-XTRIG-*`` evidence. The scenario
bodies live in ``dtp_xtrig_route_test_seq``, ``dtp_xtrig_csr_test_seq`` and
``dtp_ctm_route_test_seq``. The SV-UVM twin is
``uvm/seq_lib/dtp_xtrig_base_test_seq.svh``.
"""

from __future__ import annotations

from random import Random

import cocotb
from cocotb.triggers import ClockCycles, NextTimeStep, ReadOnly
from env.dtp_dv_cfg import DTP_INT_CT_MODE
from env.dtp_types import RESET_COUNT_CHECK_ID
from env.dtp_xtrig_agent import DtpXtrigActivityWindow
from env.dtp_xtrig_types import (
    XTRIG_CT_DST_LATENCY,
    XTRIG_CTM_SELECT_DEFAULT,
    XTRIG_CTM_SELECT_MASK,
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
    XTRIG_WIRE_OR_ASSERT,
    XTRIG_WIRE_OR_PULL,
    DtpCtmRefModel,
    ctm_config_addr,
    ctp_config_addr,
    ctp_status_addr,
    ctp_stretch_addr,
    external_ctp_port,
    internal_ct_port,
    pack_ctp_config,
    project_ctp_mask,
    project_internal_mask,
)
from ocah_checker import OcahChecker
from ocah_lib import OcahKnobs

from .dtp_base_test_seq import dtp_base_test_seq

FULL_WORD = 0xFFFF_FFFF
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
    # Cycles the window stays open after the last expected output, so a late
    # or stretched pulse on any port is inside it.
    ISOLATION_TAIL_CYCLES = 6
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
    # STRETCH_MULT the route helpers program on every external CTP they use;
    # the internal CTPs carry the same multiplier (cross_trigger_network), so
    # every routed pulse is two cycles wide.
    ROUTE_STRETCH_MULT = 1
    # STRETCH_MULT of the pulse a system reset lands on: wide enough that the
    # output enable is active when the reset asserts.
    RESET_HOLD_STRETCH = 0xFFFF
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
        "axi_outstanding": (CHK_AXIL, CHK_AW_LOCK, CHK_AR_STALL),
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
