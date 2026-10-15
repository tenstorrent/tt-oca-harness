# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Cross-trigger CTP protocol scenarios, dispatched on ``scenario``.

- ``wire_or``: wire-OR pulse stretching, BUSY over the CSR for wide pulses,
  and synchronization of an external pulse onto an internal lane.
- ``wire_or_bus``: CTPs sharing one open-drain wire.
- ``p2p``: point-to-point request and acknowledge handshakes in both
  directions, with STATUS read at every phase.
- ``reset``: per-CTP CONFIG.RESET recovery from a stalled handshake, then a
  system reset landing on live traffic, CSR defaults, and a fresh route.
- ``random``: seeded CTP configurations (mode, polarity, stretch).
- ``dst_port_sweep``: one internal source swept across every CTM destination,
  then every CTP routed to itself in point-to-point mode.

The SV-UVM twin is ``uvm/seq_lib/dtp_xtrig_route_test_seq.svh``.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles
from env.dtp_xtrig_agent import DtpXtrigActivityWindow
from env.dtp_xtrig_types import (
    XTRIG_CTP_MODE_P2P,
    XTRIG_CTP_MODE_WIRE_OR,
    XTRIG_NUM_CTM_PORTS,
    XTRIG_NUM_CTP,
    XTRIG_NUM_INT_CT,
    XTRIG_WIRE_OR_PULL,
    ctp_config_addr,
    external_ctp_port,
    internal_ct_port,
    pack_ctp_config,
)

from .dtp_xtrig_base_test_seq import dtp_xtrig_base_test_seq


class dtp_xtrig_route_test_seq(dtp_xtrig_base_test_seq):
    """CTP wire-OR, point-to-point, reset, random and destination-sweep scenarios."""

    # The port observables that stay idle while CONFIG.RESET holds a
    # point-to-point port and across its release.
    CONFIG_RESET_SIGNALS = ("xtrig_ctp_req_out_dout", "xtrig_ctp_ack_out_dout", "xtrig_ctp_busy")
    # A STATUS read issued once the output enable has risen lands several
    # cycles later on the CSR path, so BUSY=1 is read back over the CSR only
    # for pulses at least this many cycles wide (STRETCH_MULT + 1); the busy
    # flop mirror covers every width cycle for cycle.
    BUSY_READ_MIN_STRETCH = 8
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
        # Every CTP routed to itself: in point-to-point mode its request and
        # acknowledge pads differ on each side, so the trigger it receives
        # leaves on its own CT_Req_out once, without feeding back.
        for ctp_idx in range(XTRIG_NUM_CTP):
            port = external_ctp_port(ctp_idx)
            self.log_iteration(ctp_idx + 1, XTRIG_NUM_CTP, "CTP %d -> itself", ctp_idx)
            await self.verify_route(
                port, 1 << port, XTRIG_CTP_MODE_P2P, label=f"dst_sweep.self{ctp_idx}"
            )
        self.log_summary("dst_port_sweep", outputs=XTRIG_NUM_CTM_PORTS, self_routes=XTRIG_NUM_CTP)
