# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Cross-bridge JTAG2AXI write traffic and system-reset recovery under CDC jitter.

The scenario's testlist entry passes ``+cdc_instrumentation_enabled=1``, so
every synchronizer of the bridges' clock crossings may hold a changing input
for one more destination cycle, and on VCS ``-xlrm hier_inst_seed``, which
gives each synchronizer its own draws. A write's AW and W beats then reach
the ACLK side in different cycles, and a system reset's isolate requests
reach the five TCK-side crossings in different TCK cycles.

The SV-UVM twin is ``uvm/seq_lib/dtp_jtag2axi_cdc_jitter_test_seq.svh``.
"""

from __future__ import annotations

import random

from env.dtp_types import (
    ABORT_ESCAPE_CHECK_ID,
    ABORT_FSM_CHECK_ID,
    ABORT_RECOVERY_CHECK_ID,
    CDC_CLEAR_CHECK_ID,
    DtpJtag2AxiOp,
    DtpJtag2AxiStatus,
    pack_series_data,
    unpack_series_data,
)
from ocah_jtag_vip import OcahJtagState

from .dtp_jtag2axi_base_test_seq import TAP_STATE_CHECK_ID
from .dtp_jtag2axi_robustness_test_seq import (
    ABORT_SETTLE_TCK,
    ROBUST_TARGETS,
    dtp_jtag2axi_robustness_test_seq,
)

# The reset leg's read: one 0x400 slot per bridge from the robustness base.
JITTER_READ_SLOT = 24
# TCK edges stepped after the issue scan's Update-DR before the system reset.
# The scan's request reaches the series request FIFO on the second edge after
# Update-DR and the state machine's address state on the third, and a reset
# with TCK idle reaches the TCK side of a crossing two or, with jitter, three
# edges after it. One edge therefore lands the first isolate request on the
# address state; zero edges land it on the queued request.
JITTER_RESET_EDGES = (0, 1)
# TCK edges after the system reset that are logged one by one, covering the
# state machine's path from Update-DR to the abort.
JITTER_TRACE_TCK = 6
# TCK edges in Run-Test/Idle within which the resumed read reaches the port.
JITTER_RESUME_TCK = 16


class dtp_jtag2axi_cdc_jitter_test_seq(dtp_jtag2axi_robustness_test_seq):
    """Run the CDC-jitter scenario on all three bridges.

    Step 1 runs the random-ops write traffic of the per-bridge random-ops
    tests on one bridge per pass, the bridges in turn: seeded SINGLE_OP
    writes into a byte image, then seeded series write programmings into the
    same image. CHK-AXI-WMEM and CHK-J2A-MEM-IMAGE judge every write against
    its stimulus: a write whose AW and W reach the ACLK side in different
    cycles lands once with its own data. Every bridge's evidence needs three
    passes.

    Step 2 runs one series-read reset abort per bridge and pass, judged by
    the PTAP system-reset recovery rules: after a clear with no traffic
    since, a pl_depth 0 SERIES_DATA_NO_INCR read is shifted in and a system
    reset lands a seeded number of TCK edges after its Update-DR. The
    discarded read reaches no port, SERIES_CTRL reads DECERR at its
    programmed address, and a second pl_depth 0 read shifted in without
    reprogramming SERIES_CTRL reaches the port and returns the word at that
    address.
    """

    def __init__(
        self,
        name: str = "dtp_jtag2axi_cdc_jitter_test_seq",
        *,
        scenario: str = "cdc_jitter_all_bridges",
        scenario_seed: int | None = None,
        random_count: int = 5,
    ) -> None:
        super().__init__(
            name, scenario=scenario, scenario_seed=scenario_seed, random_count=random_count
        )

    async def _random_write_traffic(self, target: str) -> None:
        """Seeded SINGLE_OP writes, then seeded series programmings, into one byte image.

        The AXI4 fabric bridge draws every size with a size-aligned lane
        offset; an AXI4-Lite OTP bridge writes at its bus width.
        """
        rng = self.rng(f"{target}.cdc_jitter_writes")
        cfg = self.target_cfg(target)
        subword = cfg.bus_type == 0
        image: dict[int, int] = {}
        for idx in range(1, self.random_count + 1):
            size = rng.choice(range(cfg.data_size + 1)) if subword else cfg.default_size
            offset = rng.randrange(cfg.beat_bytes >> size) << size if subword else 0
            addr = self.random_upper_addr(target, rng) | (
                self.random_target_aligned_addr(target, rng) + offset
            )
            data = rng.getrandbits(cfg.data_width) & self.data_mask(size)
            wstrb = rng.randint(1, self.target_full_wstrb(target, size))
            self.log_iteration(
                idx,
                self.random_count,
                "target=%s random write addr=0x%014x size=%d data=0x%x wstrb=0x%02x",
                target,
                addr,
                size,
                data,
                wstrb,
            )
            self.snapshot_target_word(target, image, addr, size)
            self.status, _ = await self.write_target_single_and_check(
                target, addr, data, size=size, wstrb=wstrb, context=f"jitter_write#{idx}"
            )
            self.image_write(target, image, addr, data, wstrb=wstrb, size=size)
            self.operation_count += 1
        self.check_memory_image(target, image, context="jitter_write")
        await self.run_random_series(target, image, self.rng(f"{target}.cdc_jitter_series"))

    async def _scan_series_read_to_update_dr(self, target: str, *, size: int) -> None:
        """Shift a SERIES_DATA_NO_INCR read in and hold the TAP in Update-DR with TCK idle."""
        cfg = self.target_cfg(target)
        value, width = pack_series_data(0, size, target=cfg)
        await self._scan_dr_to(
            target,
            cfg.series_data_no_incr_instr,
            value,
            width,
            stop=OcahJtagState.EXIT1_DR,
            context="series_data",
        )
        item = await self.tms_step(1)
        self.check_equal(
            self.target_evidence(target),
            TAP_STATE_CHECK_ID,
            item.result,
            int(OcahJtagState.UPDATE_DR),
            context=f"{target}.series_data held in Update-DR",
        )

    async def _trace_abort(self, target: str, *, context: str) -> str:
        """Step ``JITTER_TRACE_TCK`` edges in Run-Test/Idle after the reset, logging the
        state machine after each; returns the trace, one character per edge
        (I idle, R read path)."""
        tb_if = self.cfg.tb_if
        trace = ""
        for _ in range(JITTER_TRACE_TCK):
            await self.tms_step(0)
            trace += "R" if tb_if.bridge_fsm_on_path(target, read=True) else "I"
        self.log.info("%s state machine after the reset, per TCK edge: %s", context, trace)
        return trace

    async def _resume_series_read(
        self, target: str, *, addr: int, word: int, size: int, context: str
    ) -> None:
        """Shift a pl_depth 0 SERIES_DATA_NO_INCR read in without reprogramming
        SERIES_CTRL: the read reaches the port within ``JITTER_RESUME_TCK`` TCK edges
        and the next shift captures ``word``."""
        cfg = self.target_cfg(target)
        completed = self.port_history(target).count(read=True)
        before = await self.target_activity_counts(target)
        await self.series_data_no_incr(0, size=size, target=target, back_to_rti=True)
        issued = (await self.target_activity_counts(target))["ar"] > before["ar"]
        for _ in range(JITTER_RESUME_TCK):
            if issued:
                break
            await self.tms_step(0)
            issued = (await self.target_activity_counts(target))["ar"] > before["ar"]
        if not self._record_abort_check(
            target,
            ABORT_RECOVERY_CHECK_ID,
            f"{context}.resumed_read_issued",
            observed=int(issued),
            expected=1,
            context=f"AR at the port within {JITTER_RESUME_TCK} TCK edges of the shift",
        ):
            return
        await self.require_port_completion(
            target, read=True, above=completed, context=f"{context}.resumed_read"
        )
        raw = await self.series_data_no_incr(0, size=size, target=target, back_to_rti=True)
        payload, _ = unpack_series_data(raw, size, target=cfg)
        self.check_bridge_rdata(target, payload, word, context=f"{context}.resumed_read")

    async def _series_read_reset_abort(
        self, target: str, rng: random.Random, *, edges: int, context: str
    ) -> None:
        """System reset ``edges`` TCK edges after the Update-DR of a series read's issue scan.

        SERIES_CTRL is programmed and a system reset clears the idle bridge
        first, so the reset under test meets every crossing empty. With the
        status already OKAY, the discarded read makes SERIES_CTRL read DECERR
        (PTAP document, system reset recovery); no AR reaches the port, since
        the reset holds the ACLK side isolated from its assertion until the
        clear completes; and SERIES_CTRL keeps its address.
        """
        tb_if = self.cfg.tb_if
        size = self.target_cfg(target).default_size
        addr = self._target_addr(target, JITTER_READ_SLOT)
        word = self.random_distinct_word(rng, target)
        self.write_target_mem_int(target, addr, word, size)
        await self.jtag2axi_series_ctrl(DtpJtag2AxiOp.NOP, 0, reset=1, size=size, target=target)
        await self.jtag2axi_series_ctrl(DtpJtag2AxiOp.READ, addr, size=size, target=target)
        await self._clear_cdc_clear_seen()
        await self.pulse_system_reset(cycles=rng.randint(1, 3))
        for _ in range(ABORT_SETTLE_TCK):
            await self.tms_step(0)
        self._record_abort_check(
            target,
            CDC_CLEAR_CHECK_ID,
            f"{context}.idle_cdc_clear",
            observed=tb_if.cdc_clear_seen(target),
            expected=1,
            context="clear of the idle bridge before the read",
        )
        status = await self.check_series_addr(target, addr, size=size, context=f"{context}.idle")
        self._record_abort_check(
            target,
            ABORT_RECOVERY_CHECK_ID,
            f"{context}.idle_series_status",
            observed=status,
            expected=DtpJtag2AxiStatus.SUCCESS,
            context="no series operation in flight at the idle reset",
        )
        await self._scan_series_read_to_update_dr(target, size=size)
        for _ in range(edges):
            await self.tms_step(0)
        await self._clear_cdc_clear_seen()
        await self.pulse_system_reset(cycles=rng.randint(1, 3))
        # The reset clears the port's request counters: quiet means no request
        # counted since the pulse.
        activity_before = await self.target_activity_counts(target)
        await self._trace_abort(target, context=context)
        for _ in range(ABORT_SETTLE_TCK):
            await self.tms_step(0)
        self._record_abort_check(
            target,
            ABORT_FSM_CHECK_ID,
            f"{context}.fsm_idle",
            observed=tb_if.bridge_fsm_idle(target),
            expected=1,
            context="after the series-read reset",
        )
        self._record_abort_check(
            target,
            CDC_CLEAR_CHECK_ID,
            f"{context}.cdc_clear",
            observed=tb_if.cdc_clear_seen(target),
            expected=1,
        )
        activity_after = await self.target_activity_counts(target)
        self._record_abort_check(
            target,
            ABORT_ESCAPE_CHECK_ID,
            f"{context}.no_request",
            observed=activity_after["ar"] - activity_before["ar"],
            expected=0,
            context=f"AR requests at the port since the reset, edges={edges}",
        )
        status = await self.check_series_addr(target, addr, size=size, context=f"{context}.kept")
        recovered = self._record_abort_check(
            target,
            ABORT_RECOVERY_CHECK_ID,
            f"{context}.series_status",
            observed=status,
            expected=DtpJtag2AxiStatus.DECERR,
            context=f"SERIES_CTRL status={DtpJtag2AxiStatus(status).name} after the reset",
        )
        self.status = DtpJtag2AxiStatus(status)
        if recovered:
            await self._resume_series_read(target, addr=addr, word=word, size=size, context=context)
        self.operation_count += 1

    async def run_cdc_jitter_all_bridges(self) -> None:
        self.log_banner("JTAG2AXI traffic and system-reset recovery under CDC jitter")
        await self.reset_tap()
        writer = ROBUST_TARGETS[self.loop_index % len(ROBUST_TARGETS)]
        self.log_step(1, "Random-ops write traffic on %s / every write lands once", writer)
        await self._random_write_traffic(writer)
        self.log_step(
            2, "Series-read reset abort on every bridge / DECERR, no AR, the resumed read returns"
        )
        rng = self.rng("cdc_jitter_reset")
        for idx, target in enumerate(ROBUST_TARGETS, start=1):
            edges = JITTER_RESET_EDGES[(self.scenario_seed + idx) % len(JITTER_RESET_EDGES)]
            self.log_iteration(
                idx,
                len(ROBUST_TARGETS),
                "target=%s system reset %d TCK edges after the issue scan's Update-DR",
                target,
                edges,
            )
            await self._series_read_reset_abort(
                target, rng, edges=edges, context=f"jitter_reset.{target}"
            )

    async def body(self) -> None:
        await self.enable_all_debug()
        if self.scenario != "cdc_jitter_all_bridges":
            raise ValueError(f"unknown JTAG2AXI CDC-jitter scenario {self.scenario!r}")
        await self.run_cdc_jitter_all_bridges()
        await self.enable_all_debug()
        self.log_summary(
            "JTAG2AXI CDC-jitter scenario complete",
            scenario=self.scenario,
            operations=self.operation_count,
            status=DtpJtag2AxiStatus(self.status).name,
        )
