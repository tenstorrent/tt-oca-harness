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
from env.dtp_fcov import ALLOWED, BLOCKED, DtpDbgDisableFcov
from env.dtp_scan_ref_model import IJTAG_SIB_ORDER, STAP_ORDER

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

HOST_SCAN_CONTROLS = (
    "jtag_stap_host_select",
    "jtag_stap_host_shift_en",
    "jtag_stap_host_capture_en",
    "jtag_stap_host_update_en",
)

SELECTED_PAYLOAD = {"config_hold": 1, "stap_sel": 1, "tms_hold": 1}


class dtp_dbg_disable_scan_matrix_test_seq(dtp_scan_base_test_seq):
    """Run the scan-side debug-disable matrix and emit the FCOV artifact."""

    def __init__(
        self,
        name: str = "dtp_dbg_disable_scan_matrix_test_seq",
        *,
        multi_hot_rows: int = 4,
        **kwargs,
    ) -> None:
        super().__init__(name, **kwargs)
        self.multi_hot_rows = multi_hot_rows
        self.fcov = DtpDbgDisableFcov("scan_matrix")

    def build_rows(self) -> list[tuple[str, dict[str, int]]]:
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

    async def check_ijtag_row(self, mask: dict[str, int], *, context: str) -> None:
        """Request all three SIBs open; each SIB's outcome follows its disable."""
        state = await self.check_ijtag_pattern(0b111, dbg_disable=mask, context=f"{context}.ijtag")
        full = full_dbg_disable(mask)
        for sib in IJTAG_SIB_ORDER:
            field = IJTAG_SIB_DISABLE[sib]
            value = full[field]
            self.fcov.sample_cell(
                field,
                value,
                BLOCKED if value else ALLOWED,
                mask=full,
                operation=f"ijtag_sib_{sib}_open_attempt",
                result=f"select={state.effective[sib]} gated={state.gated[sib]}",
            )

    async def check_stap_row(self, mask: dict[str, int], *, context: str) -> None:
        """Configure all four STAPs in one composed pass; each port's outcome
        (forwarding vs quiet+parked-low) follows its disable, the extended
        host scan interface follows stap_host, and the chain readback matches
        the model's gated-update semantics."""
        full = full_dbg_disable(mask)
        await self.stap_chain_flush(context=f"{context}.flush")
        await self.stap_chain_write(
            ptap_select=1,
            ptap_config_hold=1,
            sib_en={name: 1 for name in STAP_ORDER},
            dbg_disable=mask,
            context=f"{context}.open_sibs",
        )
        await self.stap_chain_write(
            payloads={name: SELECTED_PAYLOAD for name in STAP_ORDER},
            dbg_disable=mask,
            context=f"{context}.write_3dcrs",
        )
        watch = [
            f"{self.stap_signal_prefix(name)}_{sig}"
            for name in STAP_ORDER
            for sig in ("tdo_oen", "tms")
        ]
        watch += list(HOST_SCAN_CONTROLS)
        window = self.start_scan_window(tuple(watch))
        captured = await self.stap_chain_maintain(dbg_disable=mask, context=f"{context}.observe")
        edges, counts = self.check_scan_window(window, context=f"{context}.window")

        for name in STAP_ORDER:
            field = STAP_DISABLE[name]
            value = full[field]
            prefix = self.stap_signal_prefix(name)
            tdo_oen = counts[f"{prefix}_tdo_oen"]
            tms = counts[f"{prefix}_tms"]
            if value:
                # Gated: the 3DCR write was ignored, so the port never
                # forwards and tms parks at the reset tms_hold=0.
                assert tdo_oen == 0, f"{context}.{name}: tdo_oen pulsed {tdo_oen}x while gated"
                assert tms == 0, f"{context}.{name}: tms not parked low while gated ({tms}/{edges})"
                result = "no_forwarding+update_ignored"
            else:
                assert tdo_oen > 0, f"{context}.{name}: tdo_oen never pulsed while enabled"
                assert 0 < tms < edges, (
                    f"{context}.{name}: tms must follow live TMS ({tms}/{edges})"
                )
                result = "forwarding"
            self.fcov.sample_cell(
                field,
                value,
                BLOCKED if value else ALLOWED,
                mask=full,
                operation=f"stap_{name}_select_attempt",
                result=result,
            )

        host_value = full["stap_host"]
        select = counts["jtag_stap_host_select"]
        shift_en = counts["jtag_stap_host_shift_en"]
        if host_value:
            for sig in HOST_SCAN_CONTROLS:
                assert counts[sig] == 0, f"{context}.stap_host: {sig} pulsed while gated"
            host_result = "scan_controls_quiet"
        else:
            assert select > 0 and shift_en > 0, (
                f"{context}.stap_host: scan controls never pulsed while enabled "
                f"(select={select} shift_en={shift_en})"
            )
            host_result = "scan_controls_active"
        self.fcov.sample_cell(
            "stap_host",
            host_value,
            BLOCKED if host_value else ALLOWED,
            mask=full,
            operation="ext_stap_scan_attempt",
            result=host_result,
        )

        self.check_stap_chain_readback(captured, dbg_disable=mask, context=f"{context}.readback")
        await self.stap_chain_flush(context=f"{context}.cleanup")

    async def body(self) -> None:
        self.log_banner("Debug-disable scan matrix (8 fields)")
        await self.enable_all_debug()
        await self.reset_tap()
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
        await self.set_dbg_disable_vector({})
        await self.program_ijtag_sibs(0b000, context="release.close")
        await self.set_dbg_disable_vector(all_gated)
        await self.program_ijtag_sibs(
            0b111, dbg_disable=all_gated, context="release.gated_open_attempt"
        )
        await self.set_dbg_disable_vector({})
        await self.check_ijtag_all_closed(context="release.observe")
        self.fcov.sample_aux("release_no_replay", context="post_all_disabled_release")

        await self.check_ijtag_row({}, context="recovery")
        await self.check_stap_row({}, context="recovery")
        self.fcov.sample_aux("recovery", context="all_clear_after_all_disabled")

        self.fcov.require_cells(SCAN_FIELDS)
        self.fcov.write_artifact(seed=self.scenario_seed)
        self.log_summary(
            "Debug-disable scan matrix",
            rows=len(rows),
            fields=SCAN_FIELDS,
            cells=len(self.fcov.hit_cells()),
        )
