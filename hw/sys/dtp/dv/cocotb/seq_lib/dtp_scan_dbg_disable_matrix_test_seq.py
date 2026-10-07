# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Debug-disable matrix over the eight scan-side gate fields.

Deterministic one-hot rows, the all-clear and all-disabled boundary masks, and
seeded multi-hot masks. Every row drives the full disable vector, then proves each resource's
allowed/blocked outcome with temporal windows and chain readbacks, and only
then samples the functional-coverage cell.
"""

from __future__ import annotations

from env.dtp_dbg_disable import (
    IJTAG_SIB_DISABLE,
    STAP_DISABLE,
    full_dbg_disable,
)
from env.dtp_fcov import DtpDbgDisableFcov
from env.dtp_ijtag_sib_model import IJTAG_SIB_ORDER
from env.dtp_stap_3dcr_model import STAP_ORDER

from .dtp_jtag_base_test_seq import SCAN_LENGTH_CHECK_IDS
from .dtp_scan_base_test_seq import dtp_scan_base_test_seq

SCAN_FIELDS: tuple[str, ...] = (
    "stap_io",
    "stap_smc",
    "stap_sep",
    "stap_extra",
    "stap_host",
    "dft_secure",
    "dft_nonsecure",
    "dfd",
)

SELECTED_PAYLOAD = {"config_hold": 1, "stap_sel": 1, "tms_hold": 1}
CLEAR_PAYLOAD = {"config_hold": 0, "stap_sel": 0, "tms_hold": 0}


class dtp_scan_dbg_disable_matrix_test_seq(dtp_scan_base_test_seq):
    """Run the scan-side debug-disable matrix and emit the FCOV artifact."""

    def __init__(
        self,
        name: str = "dtp_scan_dbg_disable_matrix_test_seq",
        *,
        multi_hot_rows: int = 6,
        **kwargs,
    ) -> None:
        super().__init__(name, **kwargs)
        self.multi_hot_rows = multi_hot_rows
        self.fcov = DtpDbgDisableFcov("scan_matrix", SCAN_FIELDS)

    def build_rows(self) -> list[tuple[str, dict[str, int]]]:
        """Matrix rows: all clear, each field alone, seeded multi-hot masks, all disabled."""
        rows: list[tuple[str, dict[str, int]]] = [("all_clear", {})]
        rows += [(f"one_hot_{field}", {field: 1}) for field in SCAN_FIELDS]
        rng = self.rng("dbg_disable_scan_matrix")
        for idx in range(self.multi_hot_rows):
            while True:
                mask = {field: rng.randrange(2) for field in SCAN_FIELDS}
                if 2 <= sum(mask.values()) < len(SCAN_FIELDS):
                    break
            rows.append((f"multi_hot_{idx}", mask))
        rows.append(("all_disabled", {field: 1 for field in SCAN_FIELDS}))
        return rows

    def _family_failures(self) -> int:
        """Failed comparisons this pass's evidence checker has recorded."""
        return len(self.tap_checker.evidence.failures)

    async def check_ijtag_row(self, mask: dict[str, int], *, context: str) -> None:
        """Request all three SIBs open; each SIB's outcome follows its disable.
        The row's cells are sampled only when every check of the row passed."""
        failed_before = self._family_failures()
        state = await self.check_ijtag_pattern(0b111, dbg_disable=mask, context=f"{context}.ijtag")
        if self._family_failures() != failed_before:
            return
        full = full_dbg_disable(mask)
        for sib in IJTAG_SIB_ORDER:
            field = IJTAG_SIB_DISABLE[sib]
            value = full[field]
            self.fcov.sample_cell(
                field,
                value,
                mask=full,
                operation=f"ijtag_sib_{sib}_open_attempt",
                result=f"select={state.effective[sib]} gated={state.gated[sib]}",
            )

    async def check_stap_row(self, mask: dict[str, int], *, context: str) -> None:
        """Configure all four STAPs in one composed pass with every gate
        clear, then assert the row mask and observe under it: each port's
        outcome (forwarding, or quiet with tms parked at the stored
        tms_hold=1) follows its disable, the extended host scan interface
        follows stap_host, the chain readback matches the model, and a
        clearing 3DCR update under the mask is ignored by the gated ports and
        accepted by the ungated ones. The row's cells are sampled only when
        every check of the row passed; the row mask is back in force on
        return."""
        full = full_dbg_disable(mask)
        failed_before = self._family_failures()
        await self.enable_all_debug()
        await self.stap_chain_flush(context=f"{context}.flush")
        await self.stap_chain_write(
            ptap_select=1,
            ptap_config_hold=1,
            sib_en={name: 1 for name in STAP_ORDER},
            context=f"{context}.open_sibs",
        )
        await self.stap_chain_write(
            payloads={name: SELECTED_PAYLOAD for name in STAP_ORDER},
            context=f"{context}.write_3dcrs",
        )
        await self.set_dbg_disable_vector(mask)
        watch = [sig for name in STAP_ORDER for sig in self.stap_forwarding_watch(name)]
        watch += list(self.HOST_SCAN_CONTROLS)
        host_gated = full["stap_host"]
        window = self.start_scan_window(tuple(watch))
        captured = await self.stap_chain_maintain(dbg_disable=mask, context=f"{context}.observe")
        edges, counts = self.check_scan_window(
            window,
            quiet=self.HOST_SCAN_CONTROLS if host_gated else (),
            active=() if host_gated else self.HOST_SCAN_CONTROLS,
            context=f"{context}.window",
        )
        for name in STAP_ORDER:
            self.check_stap_forwarding(
                edges,
                counts,
                stap=name,
                forwarding=not full[STAP_DISABLE[name]],
                context=f"{context}.{name}",
            )
        self.check_stap_chain_readback(captured, dbg_disable=mask, context=f"{context}.readback")
        await self.stap_chain_write(
            payloads={name: CLEAR_PAYLOAD for name in STAP_ORDER},
            dbg_disable=mask,
            context=f"{context}.gated_clear_attempt",
        )
        captured = await self.stap_chain_maintain(
            dbg_disable=mask, context=f"{context}.gated_clear_readback"
        )
        self.check_stap_chain_readback(
            captured, dbg_disable=mask, context=f"{context}.gated_clear_readback"
        )

        if self._family_failures() == failed_before:
            for name in STAP_ORDER:
                field = STAP_DISABLE[name]
                value = full[field]
                self.fcov.sample_cell(
                    field,
                    value,
                    mask=full,
                    operation=f"stap_{name}_select_attempt",
                    result="no_forwarding+update_ignored" if value else "forwarding",
                )
            self.fcov.sample_cell(
                "stap_host",
                host_gated,
                mask=full,
                operation="ext_stap_scan_attempt",
                result="scan_controls_quiet" if host_gated else "scan_controls_active",
            )

        await self.enable_all_debug()
        await self.stap_chain_flush(context=f"{context}.cleanup")
        await self.set_dbg_disable_vector(mask)

    async def body(self) -> None:
        self.log_banner("Debug-disable scan matrix (8 fields)")
        await self.attach_family_checker(
            {"CHK-TAP-RESET-TLR", "CHK-SCAN-WIN", "CHK-SCAN-LEN", "CHK-SCAN-CHAIN"}
            | SCAN_LENGTH_CHECK_IDS
        )
        await self.enable_all_debug()
        await self.reset_to_tlr()
        rows = self.build_rows()
        for idx, (label, mask) in enumerate(rows):
            self.log_iteration(idx + 1, len(rows), "row=%s mask=%s", label, mask)
            full = full_dbg_disable(mask)
            self.fcov.sample_mask({field: full[field] for field in SCAN_FIELDS})
            await self.check_ijtag_row(mask, context=label)
            await self.check_stap_row(mask, context=label)
            hot = sum(full[field] for field in SCAN_FIELDS)
            if 0 < hot < len(SCAN_FIELDS):
                self.fcov.sample_aux("unrelated_isolation", context=label)

        # Delayed-replay proof (the check_stored_sib_across_gate pattern): a
        # SIB's update register retains a sanctioned open through a gate, so
        # close every SIB with a sanctioned write first, then attempt a fully
        # gated open of all three, release without reset, and prove no select
        # pulses (a gated open attempt that stuck would assert here).
        all_gated = {field: 1 for field in SCAN_FIELDS}
        failed_before = self._family_failures()
        await self.set_dbg_disable_vector({})
        await self.program_ijtag_sibs(0b000, context="release.close")
        await self.set_dbg_disable_vector(all_gated)
        await self.program_ijtag_sibs_quiet(
            0b111,
            dbg_disable=all_gated,
            quiet=self.ijtag_gated_controls(all_gated),
            context="release.gated_open_attempt",
        )
        await self.set_dbg_disable_vector({})
        await self.check_ijtag_all_closed(context="release.observe")
        if self._family_failures() == failed_before:
            self.fcov.sample_aux("release_no_replay", context="post_all_disabled_release")

        failed_before = self._family_failures()
        await self.check_ijtag_row({}, context="recovery")
        await self.check_stap_row({}, context="recovery")
        if self._family_failures() == failed_before:
            self.fcov.sample_aux("recovery", context="all_clear_after_all_disabled")

        await self.finalize_family_checker()
        self.fcov.require_cells()
        self.fcov.write_artifact(seed=self.scenario_seed)
        self.log_summary(
            "Debug-disable scan matrix",
            rows=len(rows),
            fields=SCAN_FIELDS,
            cells=len(self.fcov.hit_cells()),
        )
