# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared iJTAG/STAP scan helpers for DTP scan scenarios."""

from __future__ import annotations

from env.dtp_scan_ref_model import (
    IJTAG_SIB_COUNT,
    IJTAG_SIB_ORDER,
    STAP_ORDER,
    DtpIjtagSibModel,
    DtpStap3dcrModel,
    Stap3dcrState,
)
from env.dtp_scan_window_monitor import DtpScanControlWindowMonitor
from env.dtp_types import DtpJtagInstr
from ocah_jtag_vip import OcahJtagSlaveSequence

from .dtp_jtag_base_test_seq import dtp_jtag_base_test_seq


class dtp_scan_base_test_seq(dtp_jtag_base_test_seq):
    """Helpers for IEEE 1687 SIB and IEEE 1838 STAP/3DCR checks.

    Scenario checks land named family evidence when a family checker is
    attached (``CHK-SCAN-WIN`` for the temporal windows, ``CHK-SCAN-CHAIN``
    for chain readbacks, ``CHK-DS-*`` for downstream TAP readbacks) and fall
    back to plain asserts otherwise, so ``DTP_JTAG_FAMILY_CHECKER_NEGATIVE``
    gates the scan evidence end to end.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.ijtag_model = DtpIjtagSibModel()
        self.stap_model = DtpStap3dcrModel()

    # --- temporal scan-control windows ----------------------------------------
    def check_scan_window(
        self,
        monitor: DtpScanControlWindowMonitor,
        *,
        quiet: tuple[str, ...] = (),
        active: tuple[str, ...] = (),
        context: str,
    ) -> tuple[int, dict[str, int]]:
        """Close a window and prove quiet signals never pulsed and active ones did."""
        edges, counts = monitor.stop()
        self.log.info("%s scan window edges=%d counts=%s", context, edges, counts)
        self.family_check(
            "CHK-SCAN-WIN", "window edges nonvacuous", int(edges > 0), 1, context=context
        )
        for name in quiet:
            self.family_check(
                "CHK-SCAN-WIN", f"{name} quiet", counts[name], 0, context=f"{context} edges={edges}"
            )
        for name in active:
            self.family_check(
                "CHK-SCAN-WIN",
                f"{name} active",
                int(counts[name] > 0),
                1,
                context=f"{context} count={counts[name]}/{edges}",
            )
        return edges, counts

    # --- generic observable checks ------------------------------------------
    async def sample_signals(self) -> dict[str, int]:
        return (await self.sample_observables()).signals

    def check_observable(
        self, signals: dict[str, int], name: str, expected: int, *, context: str
    ) -> None:
        assert name in signals, f"{name} is not exposed by the DTP JTAG driver"
        self.assert_equal(name, signals[name], expected, context)

    async def finish_dr_update(self) -> None:
        """Leave Shift-DR by pulsing Update-DR and returning to RTI."""
        await self.tms_step(1)
        await self.tms_step(1)
        await self.tms_step(0)

    async def shift_dr_observe(
        self, value: int, width: int, *, context: str
    ) -> tuple[int, dict[str, int]]:
        """Shift DR while staying in Shift-DR long enough to sample controls."""
        item = await self.shift_dr(value, width, back_to_rti=False)
        signals = await self.sample_signals()
        self.log.info(
            "%s observed TDO=0x%x width=%d signals=%s", context, item.result, width, signals
        )
        await self.finish_dr_update()
        return item.result, signals

    # --- iJTAG ---------------------------------------------------------------
    async def program_ijtag_sibs(
        self,
        pattern: int,
        *,
        context: str,
        dbg_disable: dict[str, int] | None = None,
    ):
        """Update the three iJTAG SIB bits in LSB-first RTL order."""
        state = self.ijtag_model.state(pattern, dbg_disable)
        self.log.info(
            "%s SIB pattern=0x%x requested=%s gated=%s effective=%s chain_len=%d",
            context,
            pattern,
            state.requested,
            state.gated,
            state.effective,
            state.chain_len,
        )
        await self.load_ir(DtpJtagInstr.SELECT_IJTAG)
        await self.shift_dr(pattern, IJTAG_SIB_COUNT)
        return state

    async def observe_ijtag_controls(
        self, pattern: int, *, context: str
    ) -> tuple[int, dict[str, int]]:
        await self.load_ir(DtpJtagInstr.SELECT_IJTAG)
        return await self.shift_dr_observe(pattern, IJTAG_SIB_COUNT, context=context)

    IJTAG_SIGNAL_PREFIX = {
        "dft_secure": "jtag_dft_secure",
        "dft": "jtag_dft",
        "dfd": "jtag_dfd",
    }

    def check_ijtag_controls(self, state, signals: dict[str, int], *, context: str) -> None:
        for name in IJTAG_SIB_ORDER:
            prefix = self.IJTAG_SIGNAL_PREFIX[name]
            expected_select = state.effective[name]
            self.check_observable(
                signals, f"{prefix}_select", expected_select, context=f"{context}.{name}"
            )

    async def check_ijtag_pattern(
        self, pattern: int, *, dbg_disable: dict[str, int] | None = None, context: str
    ):
        """Program a SIB pattern under a disable mask and prove the outcome.

        Drives the full disable vector, programs the SIBs, then observes with
        a temporal window: a requested-but-gated SIB's scan controls must
        never pulse, an effective SIB's select must be seen high, and any
        closed SIB's select stays quiet. Returns the model state."""
        dbg = dict(dbg_disable or {})
        await self.set_dbg_disable_vector(dbg)
        state = await self.program_ijtag_sibs(
            pattern, context=f"{context}.program", dbg_disable=dbg
        )

        quiet: list[str] = []
        active: list[str] = []
        for name in IJTAG_SIB_ORDER:
            prefix = self.IJTAG_SIGNAL_PREFIX[name]
            if state.effective[name]:
                active.append(f"{prefix}_select")
            elif state.requested[name] and state.gated[name]:
                quiet.extend(
                    f"{prefix}_{suffix}"
                    for suffix in ("select", "shift_en", "capture_en", "update_en")
                )
            else:
                quiet.append(f"{prefix}_select")
        window = self.start_scan_window(quiet + active)
        _, signals = await self.observe_ijtag_controls(pattern, context=f"{context}.observe")
        self.check_scan_window(
            window, quiet=tuple(quiet), active=tuple(active), context=f"{context}.window"
        )
        self.check_ijtag_controls(state, signals, context=context)
        self.assert_equal(f"{context}.chain_len", state.chain_len, 3)
        return state

    # --- STAP / 3DCR ---------------------------------------------------------
    @staticmethod
    def stap_index(name: str) -> int:
        return STAP_ORDER.index(name)

    @staticmethod
    def stap_signal_prefix(name: str) -> str:
        return {
            "io": "jtag_stap_io",
            "smc": "jtag_stap_smc",
            "sep": "jtag_stap_sep",
            "extra0": "jtag_stap_extra0",
        }[name]

    async def write_ptap_3dcr(self, *, config_hold: int, select: int, context: str) -> None:
        value = self.stap_model.ptap_3dcr_value(config_hold=config_hold, select=select)
        self.log.info(
            "%s PTAP_3DCR config_hold=%d select=%d raw=0x%x", context, config_hold, select, value
        )
        self.stap_model.update_ptap(value)
        await self.write_tdr("TAP_3DCR", value)
        await self.tms_step(0)
        await self.tms_step(0)

    async def read_ptap_3dcr(self, *, shift_value: int = 0) -> int:
        return await self.read_tdr("TAP_3DCR", shift_value=shift_value)

    def stap_sib_pattern(self, name: str, enabled: int) -> int:
        return (enabled & 0x1) << (len(STAP_ORDER) - 1 - self.stap_index(name))

    async def shift_stap_sibs(self, pattern: int, *, context: str) -> None:
        self.log.info("%s STAP SIB pattern=0x%x order=%s", context, pattern, STAP_ORDER)
        await self.load_ir(DtpJtagInstr.TAP_3DCR)
        await self.shift_dr(pattern, len(STAP_ORDER))

    async def observe_stap_controls(self, name: str, *, context: str) -> tuple[int, dict[str, int]]:
        await self.load_ir(DtpJtagInstr.TAP_3DCR)
        return await self.shift_dr_observe(0, len(STAP_ORDER), context=context)

    # --- composed TAP_3DCR chain scans (IEEE 1838 serial configuration) -------
    # The TAP_3DCR data register is the 2-bit PTAP 3DCR followed serially by
    # the STAP configuration chain, and the chain shifts on every scan, so
    # each scan drives the full chain state. Scans are over-length: leading
    # zeros pass through and the trailing bits land in the chain. 64 bits
    # holds the worst case (PTAP 3DCR + a 32-bit downstream IDCODE + the
    # I/O STAP splice + four open SIBs with their 3DCRs).
    STAP_CHAIN_SCAN_WIDTH = 64

    # --- downstream STAP TAPs ------------------------------------------------
    def attach_downstream_taps(self) -> None:
        """Seed the chain model with every attached downstream TAP and route
        their slave-sequence evidence into this pass's family checker.

        Call once per pass after ``attach_family_checker``; a scenario on a
        bench with no attached ports is unaffected.
        """
        for stap in STAP_ORDER:
            if stap not in self.cfg.stap_ds_attach:
                continue
            ds = self.stap_model.attach(stap, self.cfg.stap_ds_device[stap])
            if self.tap_checker is not None:
                self.stap_ds_seq(stap).checker = self.tap_checker
            self.log.info(
                "downstream TAP behind STAP %s: idcode=0x%08x ir_width=%d regs=%s",
                stap,
                ds.idcode,
                ds.ir_width,
                {r.name: r.width for r in ds.regs.values()},
            )

    def ds_attached(self, stap: str) -> bool:
        """True when a downstream TAP is attached behind STAP ``stap``."""
        return self.stap_model.attached(stap)

    def stap_ds_seq(self, stap: str) -> OcahJtagSlaveSequence:
        """The slave sequence (the only test-facing surface) of a downstream TAP."""
        return self.cfg.stap_ds_seq[stap]

    async def settle_stap_release(self) -> None:
        """Re-establish lockstep after a STAP's disable clears.

        While gated, the port parks its host TMS at the stored tms_hold, so a
        downstream TAP behind it sits in Test-Logic-Reset. The disable
        clears through the DUT's 2-stage TCK synchronizer and the downstream
        then needs one live TMS=0 cycle to re-enter Run-Test/Idle alongside
        the PTAP; ``wait_dbg_disable_sync`` leaves a one-cycle margin, so add
        two idle TCK cycles before the next composed scan.
        """
        for _ in range(2):
            await self.tms_step(0)

    async def stap_chain_flush(
        self, *, context: str, dbg_disable: dict[str, int] | None = None
    ) -> None:
        """Load TAP_3DCR and zero the whole PTAP+STAP configuration chain.

        With a selected STAP splicing an attached downstream TAP, a plain
        6-bit IR load would shift garbage through the network at Update-IR
        (into the SIB/3DCR flops and the downstream IR) and leave the
        downstream instruction untracked, so the load is a composed IR scan
        that parks every spliced downstream TAP on BYPASS first.
        """
        spliced = self.stap_model.spliced_downstream(dbg_disable)
        if spliced:
            self.log.info(
                "%s flush TAP_3DCR chain (composed IR load, downstream %s)", context, spliced
            )
            await self.stap_chain_ir_write(
                ds_ir={name: self.stap_model.downstream[name].bypass_opcode for name in spliced},
                dbg_disable=dbg_disable,
                context=f"{context}.ir",
            )
        else:
            self.log.info("%s flush TAP_3DCR configuration chain", context)
            await self.load_ir(DtpJtagInstr.TAP_3DCR)
        await self.shift_dr(0, self.STAP_CHAIN_SCAN_WIDTH)
        self.stap_model.flush_scan(dbg_disable)

    @staticmethod
    def _payload_states(payloads: dict[str, dict[str, int]] | None) -> dict[str, Stap3dcrState]:
        return {
            name: Stap3dcrState(
                config_hold=p.get("config_hold", 0),
                stap_sel=p.get("stap_sel", 0),
                tms_hold=p.get("tms_hold", 0),
            )
            for name, p in (payloads or {}).items()
        }

    async def stap_chain_write(
        self,
        *,
        ptap_select: int | None = None,
        ptap_config_hold: int | None = None,
        sib_en: dict[str, int] | None = None,
        payloads: dict[str, dict[str, int]] | None = None,
        ds_values: dict[str, int] | None = None,
        dbg_disable: dict[str, int] | None = None,
        context: str,
    ) -> int:
        """One composed TAP_3DCR scan driving the full chain state.

        TAP_3DCR must already be loaded (stap_chain_flush). Unspecified
        fields keep their stored values, so a bare call is a maintain scan
        whose captured bits read back the pre-scan chain state; ``ds_values``
        writes a spliced downstream TAP's selected (writable) register.
        """
        kwargs = {
            "ptap_select": ptap_select,
            "ptap_config_hold": ptap_config_hold,
            "sib_en": sib_en,
            "payloads": self._payload_states(payloads),
            "ds_values": ds_values,
            "dbg_disable": dbg_disable,
        }
        value = self.stap_model.compose_scan(self.STAP_CHAIN_SCAN_WIDTH, **kwargs)
        chain_len = len(self.stap_model.chain_layout(dbg_disable))
        self.log.info(
            "%s TAP_3DCR chain scan value=0x%016x chain_len=%d sib_en=%s payloads=%s ds=%s",
            context,
            value,
            chain_len,
            sib_en,
            payloads,
            ds_values,
        )
        item = await self.shift_dr(value, self.STAP_CHAIN_SCAN_WIDTH)
        self.stap_model.apply_scan(**kwargs)
        return item.result

    async def stap_chain_ir_write(
        self,
        *,
        ptap_instr: DtpJtagInstr | int = DtpJtagInstr.TAP_3DCR,
        ds_ir: dict[str, int] | None = None,
        sib_en: dict[str, int] | None = None,
        payloads: dict[str, dict[str, int]] | None = None,
        dbg_disable: dict[str, int] | None = None,
        context: str,
    ) -> int:
        """One composed instruction scan over the full network.

        With the PTAP 3DCR select set the IR shift-out feeds the STAP chain,
        so the scan carries the PTAP instruction, every SIB/3DCR field
        (maintained unless given), and each spliced downstream TAP's IR
        (``ds_ir`` names new instructions; others keep the active one).
        """
        kwargs = {
            "ds_ir": ds_ir,
            "sib_en": sib_en,
            "payloads": self._payload_states(payloads),
            "dbg_disable": dbg_disable,
        }
        value = self.stap_model.compose_ir_scan(
            self.STAP_CHAIN_SCAN_WIDTH, int(ptap_instr), **kwargs
        )
        chain_len = len(self.stap_model.chain_layout(dbg_disable, "ir"))
        self.log.info(
            "%s composed IR scan value=0x%016x chain_len=%d ptap_instr=0x%02x ds_ir=%s",
            context,
            value,
            chain_len,
            int(ptap_instr),
            ds_ir,
        )
        item = await self.shift_ir(value, self.STAP_CHAIN_SCAN_WIDTH)
        self.stap_model.apply_ir_scan(int(ptap_instr), **kwargs)
        return item.result

    async def stap_chain_maintain(
        self, *, dbg_disable: dict[str, int] | None = None, context: str
    ) -> int:
        """State-preserving chain scan; the capture reads back stored state."""
        return await self.stap_chain_write(dbg_disable=dbg_disable, context=context)

    def check_stap_chain_readback(
        self,
        captured: int,
        *,
        dbg_disable: dict[str, int] | None = None,
        context: str,
        scan_kind: str = "dr",
    ) -> None:
        """Compare a maintain scan's captured bits against the model state.

        Valid only while the PTAP 3DCR select was already 1 before the scan
        (otherwise TDO carries the PTAP TDR path, not the chain return).
        """
        expected, care, chain_len = self.stap_model.expected_capture(dbg_disable, scan_kind)
        self.log.info(
            "%s chain readback captured=0x%016x expected=0x%0*x care=0x%0*x len=%d",
            context,
            captured,
            (chain_len + 3) // 4,
            expected,
            (chain_len + 3) // 4,
            care,
            chain_len,
        )
        self.family_check(
            "CHK-SCAN-CHAIN",
            "stap_chain_readback",
            captured & care,
            expected & care,
            context=f"{context} len={chain_len} care=0x{care:x}",
        )

    # --- downstream TAP access through the selected STAP ------------------------
    async def stap_ds_load_ir(
        self,
        stap: str,
        reg_name: str,
        *,
        dbg_disable: dict[str, int] | None = None,
        context: str,
    ) -> None:
        """Select ``reg_name`` in the downstream TAP behind a selected STAP
        (composed IR scan; the PTAP keeps TAP_3DCR)."""
        opcode = self.stap_model.downstream[stap].opcode_of(reg_name)
        self.log.info("%s downstream %s: load IR %s (0x%02x)", context, stap, reg_name, opcode)
        await self.stap_chain_ir_write(
            ds_ir={stap: opcode}, dbg_disable=dbg_disable, context=context
        )

    async def stap_ds_write_tdr(
        self,
        stap: str,
        value: int,
        *,
        dbg_disable: dict[str, int] | None = None,
        context: str,
    ) -> int:
        """Write the downstream TAP's selected register through the chain."""
        ds = self.stap_model.downstream[stap]
        reg = ds.selected()
        assert reg is not None and reg.writable, (
            f"{stap}: selected downstream register is not writable"
        )
        value &= (1 << reg.width) - 1
        self.log.info("%s downstream %s: write %s=0x%x", context, stap, reg.name, value)
        return await self.stap_chain_write(
            ds_values={stap: value}, dbg_disable=dbg_disable, context=context
        )

    async def stap_ds_readback(
        self,
        stap: str,
        *,
        check_id: str,
        dbg_disable: dict[str, int] | None = None,
        context: str,
    ) -> int:
        """Maintain scan; extract the downstream segment and record it as
        ``check_id`` evidence against the model's predicted capture (the full
        chain readback is checked as well)."""
        ds = self.stap_model.downstream[stap]
        reg = ds.selected()
        name = reg.name if reg is not None else "BYPASS"
        # Layout and prediction as they exist during the scan (pre-update).
        lsb, width = self.stap_model.ds_capture_slice(stap, dbg_disable)
        expected = ds.capture("dr")
        captured = await self.stap_chain_maintain(dbg_disable=dbg_disable, context=context)
        observed = (captured >> lsb) & ((1 << width) - 1)
        self.family_check(
            check_id,
            f"{stap} downstream {name} readback",
            observed,
            expected,
            context=f"{context} width={width} lsb={lsb}",
        )
        self.check_stap_chain_readback(captured, dbg_disable=dbg_disable, context=context)
        return observed

    async def stap_ds_read_tdr(
        self,
        stap: str,
        *,
        check_id: str = "CHK-DS-TDR-READBACK",
        dbg_disable: dict[str, int] | None = None,
        context: str,
    ) -> int:
        """Read back the downstream TAP's selected data register."""
        return await self.stap_ds_readback(
            stap, check_id=check_id, dbg_disable=dbg_disable, context=context
        )

    async def check_ds_idcode(
        self,
        stap: str,
        *,
        dbg_disable: dict[str, int] | None = None,
        context: str,
    ) -> int:
        """Read the downstream TAP's IDCODE through the selected STAP (the
        device must have IDCODE selected: after reset, or parked in
        Test-Logic-Reset while its port was deselected or gated)."""
        ds = self.stap_model.downstream[stap]
        assert ds.active_ir == ds.idcode_opcode, (
            f"{stap}: downstream IR is 0x{ds.active_ir:02x}, not IDCODE"
        )
        return await self.stap_ds_readback(
            stap, check_id="CHK-DS-IDCODE", dbg_disable=dbg_disable, context=context
        )

    async def apply_tlr(self) -> None:
        for _ in range(5):
            await self.tms_step(1)
        await self.tms_step(0)
        self.stap_model.tlr()

    async def apply_trst(self) -> None:
        await self.assert_trst(cycles=5)
        await self.deassert_trst(cycles=2)
        self.stap_model.trst()
