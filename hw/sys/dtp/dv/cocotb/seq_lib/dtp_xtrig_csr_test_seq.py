# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Cross-trigger CSR and AXI-Lite channel scenarios, dispatched on ``scenario``.

- ``reg_stall``: accepted-path CSR accesses with the cross-trigger pins quiet,
  then two routes that move every quiet observable.
- ``ctp_csr_sweep`` and ``ctm_csr_sweep``: full-word patterns, byte strobes,
  holes and unmapped words of the CTP and CTM registers.
- ``ctm_all_source_select``: per-source select masks with no aliasing.
- ``axi_channel_skew``, ``axi_channel_skew_demux_aw_lock_release`` and
  ``axi_channel_skew_read_decode_backpressure``: skewed and held channels at
  the CSR port and the crossbar demux.
- ``axi_outstanding``: several reads, then several writes, in flight with
  their responses held.

The SV-UVM twin is ``uvm/seq_lib/dtp_xtrig_csr_test_seq.svh``.
"""

from __future__ import annotations

from random import Random

from cocotb.triggers import ClockCycles
from env.dtp_xtrig_types import (
    XTRIG_CTM_END,
    XTRIG_CTM_SELECT_MASK,
    XTRIG_CTP_BASE,
    XTRIG_CTP_CONFIG_MASK,
    XTRIG_CTP_MODE_P2P,
    XTRIG_CTP_MODE_WIRE_OR,
    XTRIG_CTP_STRETCH_MASK,
    XTRIG_NUM_CTM_PORTS,
    XTRIG_NUM_CTP,
    XTRIG_NUM_INT_CT,
    XTRIG_UNMAPPED_BASE,
    DtpXtrigCsrKind,
    apply_wstrb,
    ctm_config_addr,
    ctm_hole_addr,
    ctp_config_addr,
    ctp_hole_addr,
    ctp_status_addr,
    ctp_stretch_addr,
    external_ctp_port,
    internal_ct_port,
    pack_ctp_config,
    xtrig_csr_decode,
)
from ocah_axi_vip import OcahAxiPipelineOp

from .dtp_xtrig_base_test_seq import FULL_WORD, dtp_xtrig_base_test_seq


class dtp_xtrig_csr_test_seq(dtp_xtrig_base_test_seq):
    """CSR map and AXI-Lite channel scenarios."""

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
    # Observables that must show no activity while a CSR access is in flight:
    # the internal-lane requests, the CTP request and acknowledge enables,
    # and the CTP busy flops. The pad levels are left out because they follow
    # the polarity CSR the accesses write.
    IN_FLIGHT_SIGNALS = dtp_xtrig_base_test_seq.QUIET_GROUPS + ("xtrig_ctp_busy",)
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
    # Seeded range of the cycles BREADY waits after a skewed write's request
    # phase: longer than the write response takes to reach the CSR port, so
    # the port holds the response.
    SKEW_B_READY_DELAY = (5, 8)
    # Accesses in each outstanding read or write burst. The CSR port holds
    # two requests in its address spill register, the crossbar one, and the
    # response spill register two responses, so with the responses held the
    # sixth and seventh requests find READY low.
    OUTSTANDING_BURST = 7
    # Seeded range of the cycles BREADY or RREADY stays low after a burst's
    # first response: long enough for the burst to back up to the port.
    OUTSTANDING_HOLD = (12, 16)
    # Crossbar subordinates a burst's third access visits in turn: the
    # matrix, the sixteen CTPs, and the decode-error subordinate.
    OUTSTANDING_TARGETS = XTRIG_NUM_CTP + 2
    # An unmapped word with every address bit above the CSR map set.
    XTRIG_HIGH_UNMAPPED = 0xFFFF_FC00
    # Cycles a write waits behind two held reads and a third read to its
    # register block: the sweep lands it while that read's response is stuck
    # in the block.
    OUTSTANDING_IN_FLIGHT_DELAYS = (6, 8, 10, 12, 14)

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

    def outstanding_word(self, target: int, rng: Random, *, write: bool) -> int:
        """A word of crossbar subordinate ``target``: 0 the matrix, 1 to 16 a CTP, 17 none.

        Writes land on a CT_SRC select or a STRETCH_MULT, which change no
        pad while no trigger is pulsed; reads may also land on CONFIG and
        STATUS.
        """
        if target == 0:
            return ctm_config_addr(rng.randrange(XTRIG_NUM_CTM_PORTS))
        if target <= XTRIG_NUM_CTP:
            ctp = target - 1
            if write:
                return ctp_stretch_addr(ctp)
            return rng.choice((ctp_config_addr(ctp), ctp_stretch_addr(ctp), ctp_status_addr(ctp)))
        return XTRIG_UNMAPPED_BASE + rng.randrange(0, 0x40) * 4

    def outstanding_write(self, addr: int, rng: Random, **kwargs) -> OcahAxiPipelineOp:
        """A write of a drawn word."""
        return OcahAxiPipelineOp.write(addr, rng.getrandbits(32), **kwargs)

    async def run_outstanding_pipeline(
        self,
        ops: list[OcahAxiPipelineOp],
        *,
        label: str,
        b_hold: int = 0,
        r_hold: int = 0,
    ) -> tuple[object, dict[str, int]]:
        """Issue ``ops`` through the VIP pipeline and judge responses, spill contract and stalls.

        Every access answers DECERR exactly when no subordinate decodes its
        word, every CSR port spill register keeps READY and VALID matched to
        the beats it holds, and the port's stall counters agree with the
        stall cycles the VIP saw on each request channel.
        """
        before = await self.sample_xtrig(f"{label}.before")
        result = await self.axil.pipeline_result(
            ops, b_hold_cycles=b_hold, r_hold_cycles=r_hold, check_response=False
        )
        after = await self.sample_xtrig(f"{label}.after")
        delta = {name: after[name] - before[name] for name in after}
        self.log.info(
            "%s %d accesses b_hold=%d r_hold=%d resp=%s aw/w/ar stall=%d/%d/%d",
            label,
            len(ops),
            b_hold,
            r_hold,
            [res.resp for res in result.results],
            result.aw_stall_cycles,
            result.w_stall_cycles,
            result.ar_stall_cycles,
        )
        for index, (op, res) in enumerate(zip(ops, result.results)):
            kind, _ = xtrig_csr_decode(op.address)
            expected = self.AXI_DECERR if kind is DtpXtrigCsrKind.UNMAPPED else self.AXI_OKAY
            self.check_evidence(
                self.CHK_AXIL,
                f"{label}.{op.direction}{index}.resp",
                res.resp,
                expected,
                context=f"addr=0x{op.address:08x}",
            )
        self.check_evidence(
            self.CHK_AXIL, f"{label}.spill_contract", delta["xtrig_axil_spill_err_count"], 0
        )
        for channel, vip_stall in (
            ("aw", result.aw_stall_cycles),
            ("w", result.w_stall_cycles),
            ("ar", result.ar_stall_cycles),
        ):
            self.check_evidence(
                self.CHK_AXIL,
                f"{label}.{channel}_stall_count",
                delta[f"xtrig_axil_{channel}_stall_count"],
                vip_stall,
            )
        return result, delta

    async def run_axi_outstanding(self) -> None:
        """Several CSR accesses in flight, with the responses held.

        Read and write bursts deep enough to back up to the port visit every
        crossbar subordinate as their third access, a sweep of a write, a
        read and a second write to one register block engages the demux AW
        lock, a read parked behind two held reads meets a write to its own
        block, accesses carry every AxPROT value and the address bits outside
        the map, reads address every subordinate at an unaligned byte, and
        the matrix and the decode-error subordinate take a late W and
        back-to-back ARs. Every CT_SRC select holds a drawn mask meanwhile,
        so the held read data carries the upper select bits; no trigger is
        pulsed, and the selects are cleared on exit.
        """
        self.log_banner("DTP XTRIG AXI-Lite outstanding accesses")
        rng = self.rng("axi_outstanding")
        targets = list(range(self.OUTSTANDING_TARGETS))
        await self.run_outstanding_pipeline(
            [
                self.outstanding_write(ctm_config_addr(port), rng)
                for port in range(XTRIG_NUM_CTM_PORTS)
            ],
            label="outstanding.ct_src_masks",
        )

        rng.shuffle(targets)
        for target in targets:
            label = f"outstanding.read{target}"
            ops = [
                OcahAxiPipelineOp.read(
                    self.outstanding_word(
                        target if index == 2 else rng.randrange(self.OUTSTANDING_TARGETS),
                        rng,
                        write=False,
                    ),
                    prot=rng.randrange(8),
                )
                for index in range(self.OUTSTANDING_BURST)
            ]
            _, delta = await self.run_outstanding_pipeline(
                ops, label=label, r_hold=rng.randint(*self.OUTSTANDING_HOLD)
            )
            self.check_evidence(
                self.CHK_AR_STALL,
                f"{label}.port_ar_stalled",
                int(delta["xtrig_axil_ar_stall_count"] > 0),
                1,
                context=f"ar_stall_cycles={delta['xtrig_axil_ar_stall_count']}",
            )

        # The fifth write of each burst waits in the port's AW spill register
        # at an unaligned address: its strobe covers the lanes from that byte
        # up.
        rng.shuffle(targets)
        for target in targets:
            label = f"outstanding.write{target}"
            ops = []
            for index in range(self.OUTSTANDING_BURST):
                addr = self.outstanding_word(
                    target if index == 2 else rng.randrange(self.OUTSTANDING_TARGETS),
                    rng,
                    write=True,
                )
                strb = (0xF << rng.randint(1, 3)) & 0xF if index == 4 else None
                ops.append(self.outstanding_write(addr, rng, strb=strb, prot=rng.randrange(8)))
            _, delta = await self.run_outstanding_pipeline(
                ops, label=label, b_hold=rng.randint(*self.OUTSTANDING_HOLD)
            )
            for channel in ("aw", "w"):
                self.check_evidence(
                    self.CHK_AXIL,
                    f"{label}.port_{channel}_stalled",
                    int(delta[f"xtrig_axil_{channel}_stall_count"] > 0),
                    1,
                    context=f"{channel}_stall_cycles={delta[f'xtrig_axil_{channel}_stall_count']}",
                )

        # A register block takes a read and a write together, on a seeded CTP
        # and on the matrix. Its AW lock needs the demux to present a write
        # the block refuses, which a read and a second write landing a cycle
        # after the first write produce.
        ctp = rng.randrange(XTRIG_NUM_CTP)
        stretch, config = ctp_stretch_addr(ctp), ctp_config_addr(ctp)
        select_w, select_r = rng.sample(range(XTRIG_NUM_CTM_PORTS), 2)
        blocks = (
            (1 + ctp, stretch, config),
            (0, ctm_config_addr(select_w), ctm_config_addr(select_r)),
        )
        window = self.xtrig.activity_window(self.DEMUX_SIGNALS)
        window.start()
        for target, write_word, read_word in blocks:
            for ar_delay in range(3):
                for aw_delay in range(3):
                    for w_lag in (0, 2):
                        await self.run_outstanding_pipeline(
                            [
                                self.outstanding_write(write_word, rng),
                                OcahAxiPipelineOp.read(read_word, ar_valid_delay=ar_delay),
                                self.outstanding_write(
                                    write_word,
                                    rng,
                                    aw_valid_delay=aw_delay,
                                    w_valid_delay=aw_delay + w_lag,
                                ),
                            ],
                            label=f"outstanding.lock{target}.ar{ar_delay}.aw{aw_delay}.w{w_lag}",
                        )
                    await self.run_outstanding_pipeline(
                        [
                            OcahAxiPipelineOp.read(read_word),
                            self.outstanding_write(
                                write_word, rng, aw_valid_delay=ar_delay, w_valid_delay=ar_delay
                            ),
                            OcahAxiPipelineOp.read(read_word, ar_valid_delay=aw_delay),
                        ],
                        label=f"outstanding.mixed{target}.aw{ar_delay}.ar{aw_delay}",
                    )
        activity, _hold, _last = await window.stop()
        self.check_evidence(
            self.CHK_AW_LOCK, "outstanding.aw_lock_engaged", activity["xtrig_demux_aw_lock"], 1
        )

        # Two reads parked behind the RREADY hold, a third read stuck at a
        # register block, and a write to the same block, swept so it lands
        # while that read's response waits: the block holds two accesses.
        for target, write_word, read_word in blocks:
            others = [other for other in range(self.OUTSTANDING_TARGETS) if other != target]
            for delay in self.OUTSTANDING_IN_FLIGHT_DELAYS:
                parked = [
                    OcahAxiPipelineOp.read(self.outstanding_word(other, rng, write=False))
                    for other in rng.sample(others, 2)
                ]
                await self.run_outstanding_pipeline(
                    [
                        *parked,
                        OcahAxiPipelineOp.read(read_word),
                        self.outstanding_write(
                            write_word, rng, aw_valid_delay=delay, w_valid_delay=delay
                        ),
                    ],
                    label=f"outstanding.in_flight{target}.d{delay}",
                    r_hold=rng.randint(*self.OUTSTANDING_HOLD),
                )

        # Every AxPROT bit set and cleared, and an unmapped word with every
        # address bit above the map set, behind a mapped access on each
        # channel; then a read of every subordinate at an unaligned byte.
        await self.run_outstanding_pipeline(
            [
                OcahAxiPipelineOp.read(config, prot=0),
                OcahAxiPipelineOp.read(self.XTRIG_HIGH_UNMAPPED, prot=7),
                self.outstanding_write(stretch, rng, prot=0),
                self.outstanding_write(self.XTRIG_HIGH_UNMAPPED, rng, prot=7),
                OcahAxiPipelineOp.read(config, prot=0),
                self.outstanding_write(stretch, rng, prot=0),
            ],
            label="outstanding.address_shape",
        )
        await self.run_outstanding_pipeline(
            [
                OcahAxiPipelineOp.read(
                    self.outstanding_word(target, rng, write=False) + rng.randint(1, 3),
                    prot=rng.randrange(8),
                )
                for target in range(self.OUTSTANDING_TARGETS - 1)
            ],
            label="outstanding.unaligned",
        )

        # The matrix and the decode-error subordinate each take a write whose
        # W trails its AW, and the matrix a second AR on the cycle after the
        # first.
        for target in (0, self.OUTSTANDING_TARGETS - 1):
            await self.run_outstanding_pipeline(
                [
                    self.outstanding_write(
                        self.outstanding_word(target, rng, write=True), rng, w_valid_delay=3
                    )
                ],
                label=f"outstanding.late_w{target}",
            )
        await self.run_outstanding_pipeline(
            [
                OcahAxiPipelineOp.read(self.outstanding_word(0, rng, write=False)),
                OcahAxiPipelineOp.read(
                    self.outstanding_word(0, rng, write=False), ar_valid_delay=1
                ),
            ],
            label="outstanding.ctm_ar_pair",
        )
        await self.run_outstanding_pipeline(
            [
                OcahAxiPipelineOp.write(ctm_config_addr(port), 0)
                for port in range(XTRIG_NUM_CTM_PORTS)
            ],
            label="outstanding.ct_src_clear",
        )
        self.log_summary("axi_outstanding", targets=self.OUTSTANDING_TARGETS)

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
