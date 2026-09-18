# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared XTRIG helpers and full VPLAN scenario sequences."""

from __future__ import annotations

from random import Random

import cocotb
from cocotb.triggers import ClockCycles, ReadOnly
from env.dtp_xtrig_agent import DtpXtrigActivityWindow
from env.dtp_xtrig_types import (
    XTRIG_CTM_SELECT_MASK,
    XTRIG_CTP_CONFIG_MASK,
    XTRIG_CTP_MODE_P2P,
    XTRIG_CTP_MODE_WIRE_OR,
    XTRIG_CTP_STATUS_ACK_IN,
    XTRIG_CTP_STATUS_ACK_OUT,
    XTRIG_CTP_STATUS_BUSY,
    XTRIG_CTP_STATUS_REQ_IN,
    XTRIG_CTP_STATUS_REQ_OUT,
    XTRIG_CTP_STRETCH_MASK,
    XTRIG_DECERR_DATA,
    XTRIG_NUM_CTM_PORTS,
    XTRIG_NUM_CTP,
    XTRIG_NUM_INT_CT,
    XTRIG_UNMAPPED_BASE,
    DtpCtmRefModel,
    apply_wstrb,
    ctm_config_addr,
    ctp_config_addr,
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

    Pad polarity follows CONFIG.INVERT: an inverted CTP's request and
    acknowledge pads idle high and assert low, so every pad the sequences
    drive goes through ``pad_level`` and the idle levels are re-applied
    whenever a CTP is programmed.
    """

    AXI_OKAY = 0
    AXI_DECERR = 3
    QUIET_GROUPS = (
        "xtrig_ctm_src_req",
        "xtrig_ctm_dst_ack",
        "xtrig_ctp_req_out_dout_en",
        "xtrig_ctp_ack_out_dout_en",
    )
    # Observables a routed pulse can reach; the activity window ORs them per
    # cycle from before the input pulse until the drain tail ends.
    OUTPUT_SIGNALS = (
        "xtrig_ctm_src_req",
        "xtrig_ctp_req_out_dout",
        "xtrig_ctp_req_out_dout_en",
    )
    # Observables that must show no activity from the first held cycle of a
    # system reset until after its release: every request and acknowledge
    # output plus the CTP busy flops.
    RESET_SIGNALS = QUIET_GROUPS + (
        "xtrig_ctp_req_out_dout",
        "xtrig_ctp_ack_out_dout",
        "xtrig_ctp_busy",
    )
    # Observables that must show no activity while a CSR access is in flight:
    # the request and acknowledge enables and the CTP busy flops. The pad
    # levels are left out because they follow the polarity CSR the accesses
    # write.
    IN_FLIGHT_SIGNALS = QUIET_GROUPS + ("xtrig_ctp_busy",)
    # Crossbar demux state watched across a two-outstanding write.
    DEMUX_SIGNALS = ("xtrig_demux_aw_lock", "xtrig_demux_w_pending")
    # Cycles the window stays open after the last expected output, so a late
    # or stretched pulse on any port is inside it.
    ISOLATION_TAIL_CYCLES = 6
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
    }

    _ROUTE_IDS = (CHK_CSR, CHK_SIGNAL, CHK_ROUTE_MODEL, CHK_ISOLATION)
    SCENARIO_REQUIRED_IDS = {
        "reg_stall": (CHK_CSR, CHK_QUIET, CHK_AXIL),
        "axi_channel_skew": (CHK_CSR, CHK_AXIL),
        "axi_channel_skew_demux_aw_lock_release": (CHK_AXIL, CHK_AW_LOCK),
        "axi_channel_skew_read_decode_backpressure": (CHK_AXIL, CHK_AR_STALL),
        "ctp_csr_sweep": _ROUTE_IDS + (CHK_STRETCH,),
        "ctm_csr_sweep": _ROUTE_IDS,
        "ctm_all_source_select": (CHK_CSR,),
        "wire_or": (CHK_CSR, CHK_SIGNAL, CHK_STRETCH),
        "p2p": (CHK_CSR, CHK_SIGNAL),
        "random": _ROUTE_IDS + (CHK_STRETCH,),
        "reset": _ROUTE_IDS + (CHK_QUIET,),
        "dst_port_sweep": _ROUTE_IDS,
        "ctm_wire_or_cla_to_ctp": _ROUTE_IDS + (CHK_STRETCH,),
        "ctm_wire_or_ctp_to_cla": _ROUTE_IDS + (CHK_STRETCH,),
        "ctm_wire_or_cla_to_cla": _ROUTE_IDS + (CHK_STRETCH,),
        "ctm_wire_or_ctp_to_ctp": _ROUTE_IDS + (CHK_STRETCH,),
        "ctm_p2p_cla_to_ctp": _ROUTE_IDS,
        "ctm_p2p_ctp_to_cla": _ROUTE_IDS,
        "ctm_p2p_cla_to_cla": _ROUTE_IDS,
        "ctm_p2p_ctp_to_ctp": _ROUTE_IDS,
        "ctm_reset_wire_or_mode": _ROUTE_IDS + (CHK_QUIET,),
        "ctm_reset_p2p_mode": _ROUTE_IDS + (CHK_QUIET,),
        "ctm_reset_all_modes": _ROUTE_IDS + (CHK_QUIET,),
        "ctm_rand_all_scenarios": _ROUTE_IDS,
        "ctm_rand_wire_or_only": _ROUTE_IDS,
        "ctm_rand_p2p_only": _ROUTE_IDS,
        "ctm_rand_cla_to_ctp": _ROUTE_IDS,
        "ctm_rand_ctp_to_cla": _ROUTE_IDS,
    }

    def __init__(
        self,
        name: str = "dtp_xtrig_base_test_seq",
        *,
        scenario: str = "reg_stall",
        **kwargs,
    ) -> None:
        super().__init__(name, **kwargs)
        self.scenario = scenario
        self.ctm_model = DtpCtmRefModel()
        # Named-evidence checker: every route observation, CSR readback, quiet
        # window, and stretch measurement lands one evidence record; body()
        # finalizes so a check-free pass cannot report PASS.
        self.checker = OcahChecker(
            name=f"dtp_xtrig_checker[{name}]",
            required_ids=self.SCENARIO_REQUIRED_IDS.get(scenario, (self.CHK_CSR,)),
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
        # End-of-sequence enforcement: zero recorded checks or a missing
        # required evidence ID fails the pass — a silently skipped check net
        # cannot report PASS.
        self.checker.finalize()

    def check_evidence(
        self, check_id: str, name: str, observed: int, expected: int, *, context: str = ""
    ) -> None:
        """Record one named evidence comparison (raises on mismatch)."""
        if OcahKnobs.get_int("DTP_XTRIG_NEGATIVE_CHECK", 0) == self.NEGATIVE_CHECK_INDEX[check_id]:
            self.log.warning(
                "NEGATIVE VALIDATION: %s observed 0x%x recorded as 0x%x",
                check_id,
                observed,
                observed ^ 1,
            )
            observed ^= 1
        self.checker.expect_equal(check_id, observed, expected, context=f"{name} {context}".strip())

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
            "Configure CTP[%d]: mode=%s invert=%d reset=%d stretch=%d",
            ctp_idx,
            "p2p" if mode else "wire_or",
            invert,
            reset,
            stretch,
        )
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

    async def pulse_reset(self, cycles: int = 3) -> None:
        """System reset with idle inputs; every XTRIG CSR returns to its reset value."""
        await self.xtrig.pulse_reset(cycles=cycles)
        self.ctm_model = DtpCtmRefModel()
        self.cfg.xtrig_ctp_shadow.clear()

    async def reset_window(self, label: str, *, cycles: int = 3) -> None:
        """System reset watched from its first held cycle until after release.

        Every request and acknowledge output and every CTP busy flop must
        show zero activity while the reset holds and for ``cycles + 2`` cycles
        after release (CHK-XTRIG-QUIET); the CSR shadows reset with the DUT.
        """
        self.xtrig.init_signals()
        self.xtrig.set_sys_reset(active=True)
        await ClockCycles(self.xtrig.clk, 1)
        window = self.xtrig.activity_window(self.RESET_SIGNALS)
        window.start()
        await ClockCycles(self.xtrig.clk, cycles - 1)
        self.xtrig.set_sys_reset(active=False)
        self.ctm_model = DtpCtmRefModel()
        self.cfg.xtrig_ctp_shadow.clear()
        await ClockCycles(self.xtrig.clk, cycles + 2)
        activity, _hold, _last = await window.stop()
        for name in self.RESET_SIGNALS:
            self.check_evidence(
                self.CHK_QUIET,
                f"reset_window.{label}.{name}",
                activity.get(name, 0),
                0,
                context=f"cycles={window.cycles}",
            )

    async def check_ctp_defaults(self, label: str) -> None:
        """Every CTP CONFIG, STRETCH_MULT, and STATUS reads its reset value."""
        for ctp_idx in range(XTRIG_NUM_CTP):
            for name, addr, mask in (
                ("config", ctp_config_addr(ctp_idx), XTRIG_CTP_CONFIG_MASK),
                ("stretch", ctp_stretch_addr(ctp_idx), XTRIG_CTP_STRETCH_MASK),
                ("status", ctp_status_addr(ctp_idx), XTRIG_CTP_STATUS_MASK),
            ):
                observed = await self.csr_read(addr, label=f"{label}.ctp{ctp_idx}.{name}")
                self.check_evidence(
                    self.CHK_CSR,
                    f"{label}.ctp{ctp_idx}.{name}.default",
                    observed & mask,
                    0,
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
        """Pad levels of ``ctp_mask_``: an asserted pad is high, an idle pad low, inverted CTPs the reverse."""
        inverted = self._ctp_invert_mask()
        return (ctp_mask_ & ~inverted) if asserted else (ctp_mask_ & inverted)

    def apply_idle_levels(self) -> None:
        """Drive every CTP request and acknowledge pad to its idle level."""
        inverted = self._ctp_invert_mask()
        self.xtrig.set_ctp_req_out_din(inverted)
        self.xtrig.set_ctp_req_in_din(inverted)
        self.xtrig.set_ctp_ack_in_din(inverted)

    async def idle_inputs(self) -> None:
        """Return every driven cross-trigger input to its idle level."""
        await self.xtrig.clear_inputs()
        self.apply_idle_levels()

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

    async def drive_input_mask(self, input_mask: int, mode: int, *, cycles: int = 2) -> None:
        """Pulse every input of ``input_mask`` in the same cycles; a P2P CTP source raises its request pad.

        Internal sources request through a pulse in every mode.
        """
        ctp_bits = project_ctp_mask(input_mask)
        if mode == XTRIG_CTP_MODE_P2P and ctp_bits:
            ports = self.port_bits(ctp_bits)
            assert len(ports) == 1 and input_mask == ctp_bits, "a P2P request is one CTP source"
            await self.drive_p2p_req_in(ports[0], asserted=True)
            await ClockCycles(self.xtrig.clk, cycles)
            await self.drive_p2p_req_in(ports[0], asserted=False)
            return
        await self.xtrig.pulse_input_mask(
            project_ctp_mask(input_mask),
            project_internal_mask(input_mask),
            ctp_invert=self._ctp_invert_mask(),
            cycles=cycles,
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

    async def await_selected_outputs(self, output_mask: int, mode: int, *, label: str) -> None:
        """Wait for every selected output to request; acknowledge P2P CTP outputs and see them idle."""
        ctp_outputs = project_ctp_mask(output_mask)
        int_outputs = project_internal_mask(output_mask)
        if ctp_outputs and mode == XTRIG_CTP_MODE_P2P:
            active = self.pad_level(ctp_outputs, asserted=True)
            idle = self.pad_level(ctp_outputs, asserted=False)
            await self.wait_signal_mask(
                "xtrig_ctp_req_out_dout", ctp_outputs, active, label=f"{label}.ctp"
            )
            all_idle = self._ctp_invert_mask()
            self.xtrig.set_ctp_ack_in_din((all_idle & ~ctp_outputs) | active)
            await ClockCycles(self.xtrig.clk, 3)
            self.xtrig.set_ctp_ack_in_din(all_idle)
            await self.wait_signal_mask(
                "xtrig_ctp_req_out_dout", ctp_outputs, idle, label=f"{label}.ctp_idle"
            )
        elif ctp_outputs:
            await self.wait_signal_mask(
                "xtrig_ctp_req_out_dout_en", ctp_outputs, ctp_outputs, label=f"{label}.ctp"
            )
        if int_outputs:
            await self.wait_signal_mask(
                "xtrig_ctm_src_req", int_outputs, int_outputs, label=f"{label}.internal"
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
    ) -> None:
        """Judge one route: selected outputs fire, the window matches the model, nothing else moves."""
        await self.await_selected_outputs(output_mask, mode, label=label)
        await ClockCycles(self.xtrig.clk, drain_cycles)
        activity, hold, last = await window.stop()
        fired = self.fired_vector(activity, hold)
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
    ) -> None:
        """Pulse ``input_mask`` through the programmed routes and judge the output window.

        The model programmed alongside the CSRs predicts the DUT output vector
        of this pulse; under the negative-validation knob the model is
        corrupted, so the comparison against the DUT must fail.
        """
        predicted = self.ctm_model.route(input_mask)
        await self.idle_inputs()
        await ClockCycles(self.xtrig.clk, 2)
        window = self.xtrig.activity_window(self.OUTPUT_SIGNALS)
        window.start()
        await self.drive_input_mask(input_mask, mode)
        await self.check_output_mask(
            intent_mask,
            mode,
            predicted=predicted,
            window=window,
            label=label,
            drain_cycles=drain_cycles,
        )

    async def verify_route(
        self, input_port: int, output_mask: int, mode: int, *, label: str
    ) -> None:
        """Program one route, pulse its input, and judge the output window."""
        await self.verify_route_mask(1 << input_port, output_mask, mode, label=label)

    async def verify_route_mask(
        self, input_mask: int, output_mask: int, mode: int, *, label: str
    ) -> None:
        """Program every output of ``output_mask`` with ``input_mask``, pulse the inputs together, judge."""
        await self.configure_ctp_modes_for_route_mask(input_mask, output_mask, mode)
        await self.program_routes(input_mask, output_mask, label=label)
        await self.run_route_window(input_mask, output_mask, mode, label=label)

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
        """Route one internal CT to a wire-OR CTP: window, model, isolation, and width stretch+1."""
        await self.program_ctp(ctp_idx, mode=XTRIG_CTP_MODE_WIRE_OR, invert=invert, stretch=stretch)
        await self.program_route(
            internal_ct_port(int_idx), 1 << external_ctp_port(ctp_idx), label=label
        )
        width_task = cocotb.start_soon(
            self.xtrig.measure_mask_width(
                "xtrig_ctp_req_out_dout_en", 1 << ctp_idx, timeout_cycles=stretch + 60
            )
        )
        await self.run_route_window(
            1 << internal_ct_port(int_idx),
            1 << external_ctp_port(ctp_idx),
            XTRIG_CTP_MODE_WIRE_OR,
            label=label,
            drain_cycles=self.ISOLATION_TAIL_CYCLES + stretch,
        )
        width = await width_task
        self.check_evidence(
            self.CHK_STRETCH, f"{label}.width", width, stretch + 1, context=f"ctp={ctp_idx}"
        )

    async def check_all_ctm_cleared(self, label: str) -> None:
        for src_idx in range(XTRIG_NUM_CTM_PORTS):
            observed = await self.csr_read(ctm_config_addr(src_idx), label=f"{label}.ctm{src_idx}")
            self.assert_equal(f"{label}.ctm{src_idx}.default", observed & XTRIG_CTM_SELECT_MASK, 0)

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

        self.log_step("sync", "Drive external CT_Req_out input and expect internal CT delivery")
        await self.program_ctp(ctp_idx, mode=XTRIG_CTP_MODE_WIRE_OR, stretch=0)
        await self.program_route(ctp_port, 1 << int_port, label="wire_or.external_to_internal")
        await self.drive_input_port(ctp_port, XTRIG_CTP_MODE_WIRE_OR)
        await self.wait_signal_mask(
            "xtrig_ctm_src_req", 1 << int_idx, 1 << int_idx, label="wire_or.external_sync"
        )
        self.log_summary("wire_or", ctp=ctp_idx, internal=int_idx, checked_stretches="15,0,random")

    async def run_wire_or_pulse(self, ctp_idx: int, int_idx: int, *, stretch: int) -> None:
        """One stretched pulse: enable and busy widths, aligned rise, BUSY over the CSR, then clear."""
        label = f"wire_or.stretch{stretch}"
        mask = 1 << ctp_idx
        await self.idle_inputs()
        window = self.xtrig.activity_window(("xtrig_ctp_req_out_dout_en", "xtrig_ctp_busy"))
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
        width = await width_task
        busy_width = await busy_task
        await window.stop()
        self.check_evidence(self.CHK_STRETCH, f"{label}.width", width, stretch + 1)
        self.check_evidence(self.CHK_STRETCH, f"{label}.busy_width", busy_width, stretch + 1)
        self.check_evidence(
            self.CHK_SIGNAL,
            f"{label}.busy_rise",
            window.first_seen["xtrig_ctp_busy"].get(ctp_idx, -1),
            window.first_seen["xtrig_ctp_req_out_dout_en"].get(ctp_idx, -1),
            context="busy rises with the output enable",
        )
        await self.check_status(ctp_idx, f"{label}.cleared", busy=0)
        self.check_evidence(
            self.CHK_SIGNAL,
            f"{label}.busy_flop_cleared",
            self.xtrig.sample_signal("xtrig_ctp_busy") & mask,
            0,
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
        await self.xtrig.pulse_ctm_dst_req(1 << int_idx, cycles=2)
        await self.wait_signal_mask(
            "xtrig_ctp_req_out_dout", mask, self.pad_level(mask, asserted=True), label="p2p.req_out"
        )
        await self.check_status(ctp_idx, "p2p.request", busy=1, req_out=1)
        await self.drive_p2p_ack_in(ctp_idx, asserted=True)
        await self.wait_signal_mask(
            "xtrig_ctp_req_out_dout",
            mask,
            self.pad_level(mask, asserted=False),
            label="p2p.req_out_clear",
        )
        await self.check_status(ctp_idx, "p2p.acknowledged", ack_in=1, req_out=0, busy=1)
        await self.drive_p2p_ack_in(ctp_idx, asserted=False)
        await self.wait_signal_mask("xtrig_ctp_busy", mask, 0, label="p2p.request_done")
        await self.check_status(ctp_idx, "p2p.request_done", busy=0, ack_in=0)

        self.log_step(2, "External CT_Req_in asserts CT_Ack_out, delivers the trigger, then idles")
        await self.program_route(ctp_port, 1 << int_port, label="p2p.ctp_to_internal")
        await self.drive_p2p_req_in(ctp_idx, asserted=True)
        await self.wait_signal_mask(
            "xtrig_ctp_ack_out_dout", mask, self.pad_level(mask, asserted=True), label="p2p.ack_out"
        )
        await self.wait_signal_mask(
            "xtrig_ctm_src_req", 1 << int_idx, 1 << int_idx, label="p2p.internal_delivery"
        )
        await self.check_status(ctp_idx, "p2p.response", req_in=1, ack_out=1, busy=1)
        await self.drive_p2p_req_in(ctp_idx, asserted=False)
        await self.wait_signal_mask(
            "xtrig_ctp_ack_out_dout",
            mask,
            self.pad_level(mask, asserted=False),
            label="p2p.ack_out_clear",
        )
        await self.wait_signal_mask("xtrig_ctp_busy", mask, 0, label="p2p.response_done")
        await self.check_status(ctp_idx, "p2p.response_done", busy=0, req_in=0, ack_out=0)
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
        await self.program_ctp(ctp_idx, mode=XTRIG_CTP_MODE_P2P, reset=1)
        await self.wait_signal_mask(
            "xtrig_ctp_req_out_dout",
            mask,
            self.pad_level(mask, asserted=False),
            label="reset.config_reset_clear",
        )
        await self.check_status(ctp_idx, "reset.config_reset", busy=0, req_out=0)
        await self.program_ctp(ctp_idx, mode=XTRIG_CTP_MODE_P2P, reset=0)
        await self.verify_route(
            int_port, 1 << ctp_port, XTRIG_CTP_MODE_P2P, label="reset.post_config_reset"
        )

        self.log_step(2, "System reset while an inverted wire-OR pulse is active on a second CTP")
        await self.program_ctp(
            ctp_b, mode=XTRIG_CTP_MODE_WIRE_OR, invert=1, stretch=self.RESET_HOLD_STRETCH
        )
        await self.program_ctm_src(ctp_b, 1 << internal_ct_port(int_b))
        await self.idle_inputs()
        await self.xtrig.pulse_ctm_dst_req(1 << int_b, cycles=1)
        await self.wait_signal_mask(
            "xtrig_ctp_req_out_dout_en", 1 << ctp_b, 1 << ctp_b, label="reset.active_before"
        )
        await self.reset_window("xtrig_reset")
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
        # The first two iterations take one mode each, so every pass records a
        # stretch width and a P2P handshake; the rest draw the mode at random.
        directed_modes = (XTRIG_CTP_MODE_WIRE_OR, XTRIG_CTP_MODE_P2P)
        for idx in range(self.random_count):
            ctp_idx = rng.randrange(XTRIG_NUM_CTP)
            mode = directed_modes[idx] if idx < len(directed_modes) else rng.randrange(2)
            invert = rng.randrange(2)
            stretch = rng.randrange(0, 8)
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
                # The pad data of a wire-OR port is the static level INVERT
                # selects while its enable pulses.
                await self.wait_signal_mask(
                    "xtrig_ctp_req_out_dout",
                    1 << ctp_idx,
                    (1 << ctp_idx) if invert else 0,
                    label=f"{label}.wire_polarity",
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
            neighbor = (ctp_idx + 1) % XTRIG_NUM_CTP
            before = await self.read_ctp_words(neighbor, f"ctp{ctp_idx}.neighbor_before")
            await self.sweep_ctp_words(ctp_idx, config_patterns, stretch_patterns, rng)
            after = await self.read_ctp_words(neighbor, f"ctp{ctp_idx}.neighbor_after")
            self.check_evidence(
                self.CHK_CSR,
                f"ctp{ctp_idx}.neighbor_no_alias",
                after,
                before,
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

    async def read_ctp_words(self, ctp_idx: int, label: str) -> int:
        """CONFIG and STRETCH_MULT of one CTP packed as ``stretch << 32 | config``."""
        config = await self.csr_read(ctp_config_addr(ctp_idx), label=f"{label}.config")
        stretch = await self.csr_read(ctp_stretch_addr(ctp_idx), label=f"{label}.stretch")
        return ((stretch & XTRIG_CTP_STRETCH_MASK) << 32) | (config & XTRIG_CTP_CONFIG_MASK)

    async def sweep_ctp_words(
        self, ctp_idx: int, config_patterns: list[int], stretch_patterns: list[int], rng: Random
    ) -> None:
        """Full-word patterns, every byte strobe, and a STATUS write on one CTP."""
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
        # Byte strobes: only the strobed lanes change, and a strobed reserved
        # lane changes nothing.
        for wstrb in (0x1, 0x2, 0x4, 0x8):
            old_cfg = pack_ctp_config(mode=XTRIG_CTP_MODE_WIRE_OR)
            new_cfg = rng.getrandbits(32)
            await self.csr_write(config, old_cfg, label=f"ctp{ctp_idx}.byte_base")
            await self.write_read_check(
                config,
                new_cfg,
                apply_wstrb(old_cfg, new_cfg, wstrb) & XTRIG_CTP_CONFIG_MASK,
                wstrb=wstrb,
                label=f"ctp{ctp_idx}.cfg_wstrb{wstrb:x}",
            )
            old_stretch = rng.getrandbits(16)
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
            mode = (
                XTRIG_CTP_MODE_WIRE_OR if self.is_ctp_port(output_port) else XTRIG_CTP_MODE_WIRE_OR
            )
            await self.verify_route(
                input_port, 1 << output_port, mode, label=f"dst_sweep.port{output_port}"
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

        No request or acknowledge enable or CTP busy flop moves while an
        access is in flight, the crossbar's READY-low stall counters do not
        advance, and a routed pulse afterwards is the positive control of the
        same observables.
        """
        self.log_banner("DTP XTRIG accepted-path CSR access and stall rationale")
        # Seeded per-pass CSR payloads: each loop writes different values down
        # the accepted path.
        rng = self.rng("reg_stall")
        stretch = rng.getrandbits(16)
        select = rng.randint(1, XTRIG_CTM_SELECT_MASK)
        int_idx = rng.randrange(XTRIG_NUM_INT_CT)
        ctp_idx = rng.randrange(XTRIG_NUM_CTP)
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
        for channel in ("aw", "ar"):
            self.check_evidence(
                self.CHK_AXIL,
                f"regstall.{channel}_stall_count_delta",
                sample[f"xtrig_axil_{channel}_stall_count"]
                - before[f"xtrig_axil_{channel}_stall_count"],
                0,
            )
        self.check_evidence(
            self.CHK_AXIL,
            "regstall.awvalid_count_nonzero",
            int(sample["xtrig_axil_awvalid_count"] > 0),
            1,
        )
        self.check_evidence(
            self.CHK_AXIL,
            "regstall.arvalid_count_nonzero",
            int(sample["xtrig_axil_arvalid_count"] > 0),
            1,
        )
        # Positive control: the observables the quiet records judged move for
        # a routed pulse in the same pass.
        await self.clear_xtrig()
        await self.verify_route(
            internal_ct_port(int_idx),
            1 << external_ctp_port(ctp_idx),
            XTRIG_CTP_MODE_WIRE_OR,
            label="regstall.control",
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
        d1, d2, d3 = (rng.getrandbits(16) for _ in range(3))
        addr = ctp_stretch_addr(rng.randrange(XTRIG_NUM_CTP))
        result = await self.axil.write_skewed_result(
            addr, d1, w_valid_delay=rng.randint(3, 7), b_ready_delay=rng.randint(1, 4)
        )
        self.check_evidence(self.CHK_AXIL, "axi_skew.aw_before_w.bresp", result.resp, self.AXI_OKAY)
        await self.write_read_check(
            addr, d2, d2, mask=XTRIG_CTP_STRETCH_MASK, label="axi_skew.normal_after_aw"
        )
        result = await self.axil.write_skewed_result(
            addr,
            d3,
            aw_valid_delay=rng.randint(3, 7),
            b_ready_delay=rng.randint(1, 4),
        )
        self.check_evidence(self.CHK_AXIL, "axi_skew.w_before_aw.bresp", result.resp, self.AXI_OKAY)
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

        The demux queues the first AW's port selection until its W passes
        (``xtrig_demux_w_pending``) and holds the second AW with AWREADY low
        meanwhile; the AW lock flag, which needs a master port that refuses a
        fresh AW, stays clear. Both responses must complete and the bench stall
        counter must agree with the VIP's AW observation.
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
        self.log.info(
            "%s aw_stall=%d aw_stable=%s w_pending_seen=%d aw_lock_seen=%d resp=%d/%d",
            label,
            result.aw_stall_cycles,
            result.aw_stable,
            activity["xtrig_demux_w_pending"],
            activity["xtrig_demux_aw_lock"],
            result.first.resp,
            result.second.resp,
        )
        if check_response:
            self.check_evidence(
                self.CHK_AXIL, f"{label}.first_bresp", result.first.resp, self.AXI_OKAY
            )
            self.check_evidence(
                self.CHK_AXIL, f"{label}.second_bresp", result.second.resp, self.AXI_OKAY
            )
        stall_delta = after["xtrig_axil_aw_stall_count"] - before["xtrig_axil_aw_stall_count"]
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
            self.CHK_AW_LOCK, f"{label}.second_aw_held", int(result.aw_stall_cycles > 0), 1
        )
        self.check_evidence(self.CHK_AW_LOCK, f"{label}.aw_stable", int(result.aw_stable), 1)
        self.check_evidence(
            self.CHK_AW_LOCK, f"{label}.aw_stall_count", stall_delta, result.aw_stall_cycles
        )
        return result

    async def run_axi_channel_skew_read_decode_backpressure(self) -> None:
        self.log_banner("DTP XTRIG AXI-Lite read decode backpressure")
        # Seeded per-pass unmapped offsets and RREADY hold width.
        rng = self.rng("read_decode_backpressure")
        offsets = sorted(rng.sample(range(0, 0x40), 2))
        addr_a, addr_b = (XTRIG_UNMAPPED_BASE + offset * 4 for offset in offsets)
        hold = rng.randint(4, 8)
        before = await self.sample_xtrig("read_decode.before")
        result = await self.axil.read_pair_hold_result(addr_a, addr_b, hold, check_response=False)
        after = await self.sample_xtrig("read_decode.after")
        self.log.info(
            "unmapped pair a=0x%x b=0x%x hold=%d resp=%d/%d data=0x%08x/0x%08x ar_stall=%d "
            "ar_stable=%s hold_stable=%s",
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
        )
        for tag, read in (("first", result.first), ("second", result.second)):
            self.check_evidence(
                self.CHK_AXIL, f"read_decode.{tag}.resp", read.resp, self.AXI_DECERR
            )
            # The crossbar's error subordinate, not a register block, answers
            # an unmapped read: its data word says so.
            self.check_evidence(
                self.CHK_AXIL, f"read_decode.{tag}.err_slv_data", read.data, XTRIG_DECERR_DATA
            )
        self.check_evidence(
            self.CHK_AXIL, "read_decode.first.hold_stable", int(result.first.hold_stable), 1
        )
        stall_delta = after["xtrig_axil_ar_stall_count"] - before["xtrig_axil_ar_stall_count"]
        arvalid_delta = after["xtrig_axil_arvalid_count"] - before["xtrig_axil_arvalid_count"]
        self.check_evidence(
            self.CHK_AR_STALL, "read_decode.second_ar_held", int(result.ar_stall_cycles > 0), 1
        )
        self.check_evidence(self.CHK_AR_STALL, "read_decode.ar_stable", int(result.ar_stable), 1)
        self.check_evidence(
            self.CHK_AR_STALL, "read_decode.ar_stall_count", stall_delta, result.ar_stall_cycles
        )
        self.check_evidence(
            self.CHK_AR_STALL, "read_decode.ar_accepted", arvalid_delta - stall_delta, 2
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
        width = await width_task
        self.check_evidence(
            self.CHK_STRETCH,
            f"wire_or.{name}.merged_width",
            width,
            self.ROUTE_STRETCH_MULT + 1,
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
        int_a, int_b = rng.sample(range(XTRIG_NUM_INT_CT), 2)
        ctps = rng.sample(range(XTRIG_NUM_CTP), 5)
        active = ctp_mask(ctps[0], ctps[1])
        self.log_step(1, "Two outputs hold a long stretched pulse when the reset lands")
        for ctp_idx in ctps[:2]:
            await self.program_ctp(
                ctp_idx, mode=XTRIG_CTP_MODE_WIRE_OR, stretch=self.RESET_HOLD_STRETCH
            )
        await self.program_routes(1 << internal_ct_port(int_a), active, label="reset_wire_or.pre")
        await self.idle_inputs()
        await self.xtrig.pulse_ctm_dst_req(1 << int_a, cycles=1)
        await self.wait_signal_mask(
            "xtrig_ctp_req_out_dout_en", active, active, label="reset_wire_or.active_before"
        )
        await self.check_status(ctps[0], "reset_wire_or.active_before", busy=1)
        await self.reset_window("ctm_reset_wire_or")
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
        int_a, int_b = rng.sample(range(XTRIG_NUM_INT_CT), 2)
        ctps = rng.sample(range(XTRIG_NUM_CTP), 3)
        mask = 1 << ctps[0]
        self.log_step(1, "A P2P request stays pending without its acknowledge when the reset lands")
        await self.configure_ctp_mode_for_port(ctps[0], XTRIG_CTP_MODE_P2P)
        await self.program_route(internal_ct_port(int_a), mask, label="reset_p2p.pre")
        await self.idle_inputs()
        await self.xtrig.pulse_ctm_dst_req(1 << int_a, cycles=2)
        await self.wait_signal_mask(
            "xtrig_ctp_req_out_dout",
            mask,
            self.pad_level(mask, asserted=True),
            label="reset_p2p.stuck_req",
        )
        await self.check_status(ctps[0], "reset_p2p.before", busy=1, req_out=1)
        await self.reset_window("ctm_reset_p2p")
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
        ctps = rng.sample(range(XTRIG_NUM_CTP), 4)
        # Both classes programmed together and each pulsed, so the reset lands
        # on live routing state of both kinds: one wire-OR source to two CTPs
        # and one internal CT (so the internal request outputs are a live
        # observable of this test), and one P2P source to a third CTP.
        wire_in = 1 << internal_ct_port(int_a)
        wire_outputs = (
            external_ctp_port(ctps[0]),
            external_ctp_port(ctps[1]),
            internal_ct_port(int_c),
        )
        wire_mask = sum(1 << port for port in wire_outputs)
        p2p_in = 1 << internal_ct_port(int_b)
        p2p_mask = 1 << external_ctp_port(ctps[2])
        await self.configure_ctp_modes_for_route_mask(wire_in, wire_mask, XTRIG_CTP_MODE_WIRE_OR)
        await self.configure_ctp_modes_for_route_mask(p2p_in, p2p_mask, XTRIG_CTP_MODE_P2P)
        await self.clear_ctm_routes()
        for port in wire_outputs:
            await self.program_ctm_src(port, wire_in)
        await self.program_ctm_src(external_ctp_port(ctps[2]), p2p_in)
        await self.run_route_window(
            wire_in, wire_mask, XTRIG_CTP_MODE_WIRE_OR, label="reset_all.pre_wire"
        )
        await self.run_route_window(p2p_in, p2p_mask, XTRIG_CTP_MODE_P2P, label="reset_all.pre_p2p")
        self.log_step(2, "A P2P request stays pending without its acknowledge when the reset lands")
        await self.idle_inputs()
        await self.drive_input_mask(p2p_in, XTRIG_CTP_MODE_P2P)
        await self.wait_signal_mask(
            "xtrig_ctp_req_out_dout",
            p2p_mask,
            self.pad_level(p2p_mask, asserted=True),
            label="reset_all.stuck_req",
        )
        await self.check_status(ctps[2], "reset_all.before", busy=1, req_out=1)
        await self.reset_window("ctm_reset_all")
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
        live.
        """
        used = input_mask | output_mask
        free_src = [port for port in source_pool if not (used >> port) & 1]
        if not free_src:
            return
        in2 = rng.choice(free_src)
        used |= 1 << in2
        free_dst = [port for port in dest_pool if not (used >> port) & 1]
        if not free_dst:
            return
        out2 = rng.choice(free_dst)
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

        A wire-OR iteration selects one or two sources on every output; a
        point-to-point iteration adds a second, disjoint route alongside its
        own and pulses each alone.
        """
        self.log_banner(f"DTP CTM seeded random routing {name}")
        rng = self.rng(f"ctm_random_{name}")
        source_pool = self.port_pool(source_class)
        dest_pool = self.port_pool(dest_class)
        for idx in range(self.random_count):
            mode = (
                XTRIG_CTP_MODE_P2P
                if (p2p and (not multicast or rng.randrange(2)))
                else XTRIG_CTP_MODE_WIRE_OR
            )
            n_inputs = 2 if mode == XTRIG_CTP_MODE_WIRE_OR and rng.randrange(2) else 1
            inputs = rng.sample(source_pool, min(n_inputs, len(source_pool)))
            input_mask = sum(1 << port for port in inputs)
            choices = [d for d in dest_pool if d not in inputs] or dest_pool
            if mode == XTRIG_CTP_MODE_P2P:
                selected = [rng.choice(choices)]
            else:
                rng.shuffle(choices)
                selected = choices[: max(2, min(4, len(choices)))]
            output_mask = sum(1 << port for port in selected)
            self.log_iteration(
                idx + 1,
                self.random_count,
                "inputs=0x%x mode=%d outputs=0x%x",
                input_mask,
                mode,
                output_mask,
            )
            await self.verify_route_mask(input_mask, output_mask, mode, label=f"rand.{name}.{idx}")
            if mode == XTRIG_CTP_MODE_P2P:
                await self.run_p2p_pair_isolation(
                    rng,
                    input_mask,
                    output_mask,
                    source_pool=source_pool,
                    dest_pool=dest_pool,
                    label=f"rand.{name}.{idx}",
                )
        self.log_summary(f"ctm_rand_{name}", iterations=self.random_count)

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
                await self.program_ctm_src(src_idx, old_mask)
                await self.write_read_check(
                    ctm_config_addr(src_idx),
                    new_mask,
                    apply_wstrb(old_mask, new_mask, wstrb) & XTRIG_CTM_SELECT_MASK,
                    wstrb=wstrb,
                    label=f"ctm{src_idx}.wstrb{wstrb:x}",
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
            if ((src_idx + 1) % XTRIG_NUM_CTM_PORTS) != src_idx:
                self.assert_equal(
                    f"allsrc{src_idx}.neighbor_no_alias",
                    after_neighbor & XTRIG_CTM_SELECT_MASK,
                    before_neighbor & XTRIG_CTM_SELECT_MASK,
                )
        self.log_summary("ctm_all_source_select", sources=XTRIG_NUM_CTM_PORTS)
