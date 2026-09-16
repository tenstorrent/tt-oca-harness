# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Debug-disable matrix over the three JTAG2AXI bridge gate fields.

Deterministic one-hot rows, the all-clear and all-disabled boundary masks,
and seeded multi-hot masks. Every row proves, per target: an allowed bridge
completes a write+readback with real bus activity; a blocked bridge produces
zero request activity from a counter snapshot taken before the gated TDR
write, inside a scoreboard blocked window held across the disable release,
and leaves a preloaded RAM sentinel untouched both while gated and after the
release (no delayed replay), and then recovers with a sanctioned operation.
Coverage cells are sampled only after the checks pass.
"""

from __future__ import annotations

from dataclasses import dataclass

from env.dtp_dbg_disable import full_dbg_disable
from env.dtp_fcov import ALLOWED, BLOCKED, DtpDbgDisableFcov
from env.dtp_types import DtpJtag2AxiOp

from .dtp_jtag2axi_base_test_seq import BLOCKED_CHECK_ID, dtp_jtag2axi_base_test_seq

MATRIX_TARGETS = ("smc_axi", "smc_otp", "sep_otp")
MATRIX_BASE_ADDR = 0x4800
# System-domain window observed after a gated attempt and after a release.
GATE_WINDOW_CYCLES = 8


@dataclass(frozen=True)
class _GatedAttempt:
    """One gated write: its slot, the sentinel preloaded there, and the counters before it."""

    addr: int
    sentinel: int
    before: dict[str, int]


class dtp_dbg_disable_jtag2axi_matrix_test_seq(dtp_jtag2axi_base_test_seq):
    """Run the JTAG2AXI debug-disable matrix and emit the FCOV artifact."""

    def __init__(
        self,
        name: str = "dtp_dbg_disable_jtag2axi_matrix_test_seq",
        *,
        multi_hot_rows: int = 2,
        **kwargs,
    ) -> None:
        super().__init__(name, **kwargs)
        self.multi_hot_rows = multi_hot_rows
        self.fcov = DtpDbgDisableFcov("jtag2axi_matrix")

    def build_rows(self) -> list[tuple[str, dict[str, int]]]:
        fields = tuple(self.target_cfg(t).dbg_disable_bit for t in MATRIX_TARGETS)
        rows: list[tuple[str, dict[str, int]]] = [("all_clear", {})]
        rows += [(f"one_hot_{field}", {field: 1}) for field in fields]
        rng = self.rng("dbg_disable_jtag2axi_matrix")
        for idx in range(self.multi_hot_rows):
            while True:
                mask = {field: rng.randrange(2) for field in fields}
                if sum(mask.values()) == 2:
                    break
            rows.append((f"multi_hot_{idx}", mask))
        rows.append(("all_disabled", {field: 1 for field in fields}))
        return rows

    def _row_addr(self, target: str, row_idx: int) -> int:
        cfg = self.target_cfg(target)
        return MATRIX_BASE_ADDR + row_idx * 8 * cfg.beat_bytes

    async def check_allowed(
        self, target: str, addr: int, data: int, *, mask: dict[str, int], context: str
    ) -> None:
        """Allowed bridge: write+readback complete with request activity on both."""
        cfg = self.target_cfg(target)
        before = await self.target_activity_counts(target)
        await self.write_target_single_and_check(target, addr, data, context=f"{context}.write")
        await self.expect_target_activity(
            target, before=before, read=False, context=f"{context}.write"
        )
        before = await self.target_activity_counts(target)
        await self.read_target_single_and_check(target, addr, data, context=f"{context}.read")
        await self.expect_target_activity(
            target, before=before, read=True, context=f"{context}.read"
        )
        self.fcov.sample_cell(
            cfg.dbg_disable_bit,
            0,
            ALLOWED,
            mask=mask,
            operation="single_write_read",
            result="activity+readback_ok",
        )

    async def check_blocked(
        self, target: str, addr: int, data: int, *, mask: dict[str, int], context: str
    ) -> _GatedAttempt:
        """Gated attempt: counters flat since before the TDR write, RAM sentinel untouched.

        The blocked window opened here stays open until ``check_released``
        closes it after the row's release, so a request the bridge queues while
        gated and replays afterwards fails as well.
        """
        cfg = self.target_cfg(target)
        size = cfg.default_size
        sentinel = (0x5EA1_0000 | (addr & 0xFFFF)) & self.data_mask(size)
        self.write_target_mem_int(target, addr, sentinel, size)
        before = await self.target_activity_counts(target)
        self.scoreboard_begin_blocked(target)
        await self.write_target_single_raw(
            target,
            DtpJtag2AxiOp.WRITE,
            addr,
            data=data,
            wstrb=self.target_full_wstrb(target, size),
            size=size,
            # Gated attempt: the write must never reach the bus, so no strobe
            # credit may be armed for it.
            arm_strobes=False,
        )
        await self.wait_sys_cycles(GATE_WINDOW_CYCLES)
        await self.scoreboard_expect_no_activity_since(
            target, before, context=f"{context}.no_activity"
        )
        self.assert_equal(
            f"{context}.sentinel",
            self.read_target_mem_int(target, addr, size),
            sentinel,
        )
        self.fcov.sample_cell(
            cfg.dbg_disable_bit,
            1,
            BLOCKED,
            mask=mask,
            operation="single_write_gated",
            result="no_activity+sentinel_intact",
        )
        return _GatedAttempt(addr=addr, sentinel=sentinel, before=before)

    async def check_released(self, target: str, attempt: _GatedAttempt, *, context: str) -> None:
        """After the release: counters equal the pre-attempt snapshot, window empty, sentinel intact."""
        cfg = self.target_cfg(target)
        await self.scoreboard_expect_no_activity_since(
            target, attempt.before, context=f"{context}.post_release"
        )
        self.scoreboard_end_blocked(
            target, context=f"{context}.blocked_window", check_id=BLOCKED_CHECK_ID
        )
        self.assert_equal(
            f"{context}.sentinel_post_release",
            self.read_target_mem_int(target, attempt.addr, cfg.default_size),
            attempt.sentinel,
        )

    async def _release_and_recover(
        self, label: str, row_idx: int, gated: dict[str, _GatedAttempt]
    ) -> None:
        """Release without reset: nothing queued may replay, then a sanctioned operation recovers."""
        await self.enable_all_debug()
        await self.wait_sys_cycles(GATE_WINDOW_CYCLES)
        for target, attempt in gated.items():
            await self.check_released(target, attempt, context=f"{label}.{target}")
        self.fcov.sample_aux("release_no_replay", context=label)
        for target, attempt in gated.items():
            cfg = self.target_cfg(target)
            recover_addr = attempt.addr + 4 * cfg.beat_bytes
            recover_data = (0xFEED_0000 | (row_idx << 4)) & self.data_mask(cfg.default_size)
            await self.check_allowed(
                target,
                recover_addr,
                recover_data,
                mask=full_dbg_disable({}),
                context=f"{label}.{target}.recovery",
            )
        self.fcov.sample_aux("recovery", context=label)

    async def body(self) -> None:
        self.log_banner("Debug-disable JTAG2AXI matrix (3 targets)")
        await self.enable_all_debug()
        await self.reset_tap()
        rows = self.build_rows()
        for row_idx, (label, mask) in enumerate(rows):
            self.log_iteration(row_idx + 1, len(rows), "row=%s mask=%s", label, mask)
            full = full_dbg_disable(mask)
            self.fcov.sample_mask(
                {
                    self.target_cfg(t).dbg_disable_bit: full[self.target_cfg(t).dbg_disable_bit]
                    for t in MATRIX_TARGETS
                }
            )
            await self.set_dbg_disable_vector(mask)

            gated: dict[str, _GatedAttempt] = {}
            allowed_any = False
            for target in MATRIX_TARGETS:
                cfg = self.target_cfg(target)
                addr = self._row_addr(target, row_idx)
                data = (0xC0DE_0000 | (row_idx << 8)) & self.data_mask(cfg.default_size)
                if full[cfg.dbg_disable_bit]:
                    gated[target] = await self.check_blocked(
                        target, addr, data, mask=full, context=f"{label}.{target}"
                    )
                else:
                    allowed_any = True
                    await self.check_allowed(
                        target, addr, data, mask=full, context=f"{label}.{target}"
                    )
            if gated and allowed_any:
                self.fcov.sample_aux("unrelated_isolation", context=label)
            if gated:
                await self._release_and_recover(label, row_idx, gated)

        self.fcov.require_cells(tuple(self.target_cfg(t).dbg_disable_bit for t in MATRIX_TARGETS))
        self.fcov.write_artifact(seed=self.scenario_seed)
        self.log_summary(
            "Debug-disable JTAG2AXI matrix",
            rows=len(rows),
            targets=MATRIX_TARGETS,
            cells=len(self.fcov.hit_cells()),
        )
