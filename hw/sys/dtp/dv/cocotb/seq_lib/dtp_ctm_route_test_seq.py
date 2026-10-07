# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""CTM routing scenarios, dispatched on ``scenario``.

- ``ctm_wire_or_<class>``: a seeded route of the class and two sources
  merging onto one destination.
- ``ctm_p2p_<class>``: seeded point-to-point pairs of the class with full
  handshakes.
- ``ctm_reset_<mode>``: a system reset landing on live routes, then fresh
  routes.
- ``ctm_rand_<mix>``: seeded random route mixes constrained to the mix.

The SV-UVM twin is ``uvm/seq_lib/dtp_ctm_route_test_seq.svh``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from random import Random

import cocotb
from env.dtp_xtrig_types import (
    XTRIG_CTP_MODE_P2P,
    XTRIG_CTP_MODE_WIRE_OR,
    XTRIG_NUM_CTM_PORTS,
    XTRIG_NUM_CTP,
    XTRIG_NUM_INT_CT,
    ctp_mask,
    external_ctp_port,
    internal_ct_mask,
    internal_ct_port,
)

from .dtp_xtrig_base_test_seq import dtp_xtrig_base_test_seq

CTM_RAND_PULSE_MAX_CYCLES = 8
CTM_RAND_LEAD_MAX_CYCLES = 3


@dataclass
class DtpCtmRouteWalk:
    """The route walk of a random mix, which its test keeps across the passes.

    ``pending`` holds the routes, as (source, destination) in a seeded order,
    that no single-source window has driven yet: each iteration starts from
    the first one. ``driven`` holds the routes single-source windows drove.
    """

    pending: list[tuple[int, int]] = field(default_factory=list)
    driven: set[tuple[int, int]] = field(default_factory=set)


class dtp_ctm_route_test_seq(dtp_xtrig_base_test_seq):
    """CTM route-class, reset and random route-mix scenarios."""

    def __init__(
        self,
        name: str = "dtp_ctm_route_test_seq",
        *,
        route_walk: DtpCtmRouteWalk | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(name, **kwargs)
        self.route_walk = DtpCtmRouteWalk() if route_walk is None else route_walk

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
    # The random mixes whose last pass continues until every route of their
    # class has been driven alone.
    ROUTE_WALK_MIXES = ("cla_to_ctp", "ctp_to_cla")

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
        main = f"wire_or.{name}.main"
        await self.configure_ctp_modes_for_route_mask(
            1 << input_port, output_mask, XTRIG_CTP_MODE_WIRE_OR
        )
        await self.program_routes(1 << input_port, output_mask, label=main)
        # Every destination of the main route carries one pulse of the route
        # stretch width.
        widths = {
            port: cocotb.start_soon(self.xtrig.measure_mask_width(*self._request_bit(port)))
            for port in self.port_bits(output_mask)
        }
        await self.run_route_window(
            1 << input_port, output_mask, XTRIG_CTP_MODE_WIRE_OR, label=main
        )
        for port, task in widths.items():
            pulse = await task
            context = f"output={port} source={input_port}"
            self.check_evidence(
                self.CHK_STRETCH,
                f"{main}.port{port}.width",
                pulse.width,
                self.ROUTE_STRETCH_MULT + 1,
                context=context,
            )
            self.check_evidence(
                self.CHK_STRETCH, f"{main}.port{port}.pulses", pulse.pulses, 1, context=context
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
        width_task = cocotb.start_soon(
            self.xtrig.measure_mask_width(*self._request_bit(overlap_output))
        )
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

    def _request_bit(self, output_port: int) -> tuple[str, int]:
        """Observable and bit mask that carry a wire-OR request of ``output_port``."""
        if self.is_ctp_port(output_port):
            return "xtrig_ctp_req_out_dout_en", 1 << output_port
        return "xtrig_ctm_src_req", 1 << self.int_idx_from_port(output_port)

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
        pending = self.route_walk.pending
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
        self.route_walk.driven.add((in2, out2))
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
        driven = self.route_walk.driven
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
        pending = self.route_walk.pending
        if not pending:
            pending[:] = walk
            rng.shuffle(pending)
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
            self.route_walk.driven.update(retired)
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
