# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared iJTAG/STAP scan helpers for DTP scan scenarios."""

from __future__ import annotations

from env.dtp_scan_ref_model import (
    IJTAG_INSTRUMENT_WIDTHS,
    IJTAG_OBSERVE_SCAN_WIDTH,
    IJTAG_SIB_ORDER,
    PTAP_3DCR_WIDTH,
    SCAN_MARKER_WIDTH,
    STAP_HOST_SEGMENT_WIDTH,
    STAP_ORDER,
    DtpIjtagSibModel,
    DtpStap3dcrModel,
    IjtagSibState,
    Stap3dcrState,
)
from env.dtp_scan_window_monitor import DtpScanControlWindowMonitor
from env.dtp_types import DtpJtagInstr
from ocah_jtag_vip import OcahJtagSlaveSequence, OcahJtagState

from .dtp_jtag_base_test_seq import dtp_jtag_base_test_seq


class dtp_scan_base_test_seq(dtp_jtag_base_test_seq):
    """Helpers for IEEE 1687 SIB and IEEE 1838 STAP/3DCR checks.

    Scenario checks land named family evidence when a family checker is
    attached (``CHK-SCAN-WIN`` for the temporal windows, ``CHK-SCAN-LEN``
    for the measured iJTAG chain latency, ``CHK-SCAN-CHAIN`` for chain
    readbacks, ``CHK-SCAN-OBS`` for register readbacks over the PTAP TDR
    return path, ``CHK-DS-*`` for downstream TAP readbacks) and fall back to
    plain asserts otherwise, so ``DTP_JTAG_FAMILY_CHECKER_NEGATIVE`` gates
    the scan evidence end to end.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.ijtag_model = DtpIjtagSibModel()
        self.stap_model = DtpStap3dcrModel()

    async def reset_to_tlr(self) -> None:
        """TAP reset with family evidence; Test-Logic-Reset clears the SIB chain state."""
        await super().reset_to_tlr()
        self.ijtag_model.reset()

    # --- temporal scan-control windows ----------------------------------------
    def check_scan_window(
        self,
        monitor: DtpScanControlWindowMonitor,
        *,
        quiet: tuple[str, ...] = (),
        active: tuple[str, ...] = (),
        context: str,
    ) -> tuple[int, dict[str, int]]:
        """Close a window the DUT shifted through; quiet signals never pulsed, active ones did."""
        edges, counts = monitor.stop()
        self.log.info(
            "%s scan window edges=%d dut_shift_cycles=%d counts=%s",
            context,
            edges,
            monitor.dut_shift_cycles,
            counts,
        )
        self.check_window_shifted("CHK-SCAN-WIN", monitor, context=f"{context} edges={edges}")
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

    # --- iJTAG ---------------------------------------------------------------
    IJTAG_SIGNAL_PREFIX = {
        "dft_secure": "jtag_dft_secure",
        "dft": "jtag_dft",
        "dfd": "jtag_dfd",
    }

    async def ijtag_scan(
        self,
        *,
        pattern: int | None = None,
        inst_values: dict[str, int] | None = None,
        dbg_disable: dict[str, int] | None = None,
        marker: int = 0,
        width: int | None = None,
        context: str,
    ) -> int:
        """One SELECT_IJTAG data scan composed over the current chain.

        The chain image (SIB bits, open instruments) occupies the last
        ``chain_len`` bits shifted in; ``marker`` rides in the leading bits
        and passes straight through to TDO. The captured bits are checked
        against the model (``CHK-SCAN-CHAIN``): a SIB captures its effective
        state, an open instrument its stored register.
        """
        chain_len = self.ijtag_model.chain_len(dbg_disable)
        width = chain_len if width is None else width
        value = self.ijtag_model.compose_scan(
            chain_len, pattern=pattern, inst_values=inst_values, dbg_disable=dbg_disable
        )
        value = (value << (width - chain_len)) | marker
        expected, _ = self.ijtag_model.expected_capture(dbg_disable)
        self.log.info(
            "%s SELECT_IJTAG scan value=0x%0*x width=%d chain_len=%d inst_values=%s",
            context,
            (width + 3) // 4,
            value,
            width,
            chain_len,
            inst_values,
        )
        await self.load_ir(DtpJtagInstr.SELECT_IJTAG)
        item = await self.shift_dr(value, width)
        self.ijtag_model.apply_scan(
            pattern=pattern, inst_values=inst_values, dbg_disable=dbg_disable
        )
        self.family_check(
            "CHK-SCAN-CHAIN",
            "ijtag_chain_readback",
            item.result & self.bit_mask(chain_len),
            expected,
            context=f"{context} len={chain_len}",
        )
        return item.result

    async def program_ijtag_sibs(
        self,
        pattern: int,
        *,
        dbg_disable: dict[str, int] | None = None,
        inst_values: dict[str, int] | None = None,
        context: str,
    ) -> IjtagSibState:
        """Write the three SIB bits (MSB = TDI-nearest SIB) and, through
        every SIB already open and ungated, its instrument value."""
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
        await self.ijtag_scan(
            pattern=pattern, inst_values=inst_values, dbg_disable=dbg_disable, context=context
        )
        return state

    def ijtag_gated_controls(self, dbg_disable: dict[str, int] | None) -> tuple[str, ...]:
        """The select, shift, capture, and update controls of every SIB
        ``dbg_disable`` gates."""
        return tuple(
            f"{self.IJTAG_SIGNAL_PREFIX[name]}_{suffix}"
            for name, gated in self.ijtag_model.gates(dbg_disable).items()
            if gated
            for suffix in ("select", "shift_en", "capture_en", "update_en")
        )

    async def program_ijtag_sibs_quiet(
        self,
        pattern: int,
        *,
        dbg_disable: dict[str, int] | None,
        quiet: tuple[str, ...],
        inst_values: dict[str, int] | None = None,
        context: str,
    ) -> IjtagSibState:
        """``program_ijtag_sibs`` inside a temporal window: every control in
        ``quiet`` stays low across the whole program scan (``CHK-SCAN-WIN``)."""
        window = self.start_scan_window(quiet)
        state = await self.program_ijtag_sibs(
            pattern, dbg_disable=dbg_disable, inst_values=inst_values, context=context
        )
        self.check_scan_window(window, quiet=quiet, context=f"{context}.program_window")
        return state

    def check_ijtag_chain_latency(
        self, observed: int, marker: int, chain_len: int, *, context: str
    ) -> None:
        """The marker's set MSB fixes where the stream leaves the chain: the
        highest observed bit measures the chain latency (``CHK-SCAN-LEN``)
        and the marker itself must arrive intact behind the capture."""
        latency = observed.bit_length() - SCAN_MARKER_WIDTH
        self.family_check(
            "CHK-SCAN-LEN",
            "ijtag_chain_latency",
            latency,
            chain_len,
            context=f"{context} observed=0x{observed:x} marker=0x{marker:x}",
        )
        self.family_check(
            "CHK-SCAN-CHAIN",
            "ijtag_marker_passthrough",
            (observed >> chain_len) & self.bit_mask(SCAN_MARKER_WIDTH),
            marker,
            context=f"{context} len={chain_len}",
        )

    def ijtag_window_signals(self, state: IjtagSibState) -> tuple[list[str], list[str]]:
        """(quiet, active) observables for a scan under ``state``: a
        requested-but-gated SIB's controls never pulse, an effective SIB's
        select is seen high and its capture, shift, and update strobes pulse,
        a closed SIB's select stays quiet."""
        quiet: list[str] = []
        active: list[str] = []
        for name in IJTAG_SIB_ORDER:
            prefix = self.IJTAG_SIGNAL_PREFIX[name]
            if state.effective[name]:
                active.extend(
                    f"{prefix}_{suffix}"
                    for suffix in ("select", "shift_en", "capture_en", "update_en")
                )
            elif state.requested[name] and state.gated[name]:
                quiet.extend(
                    f"{prefix}_{suffix}"
                    for suffix in ("select", "shift_en", "capture_en", "update_en")
                )
            else:
                quiet.append(f"{prefix}_select")
        return quiet, active

    async def check_ijtag_pattern(
        self, pattern: int, *, dbg_disable: dict[str, int] | None = None, context: str
    ) -> IjtagSibState:
        """Program a SIB pattern under a disable mask and prove the outcome.

        Drives the full disable vector, programs the SIBs with seeded
        instrument values (inside a window over every gated SIB's controls
        when the mask gates one), then observes a marker scan under a
        temporal window: the control windows, the measured chain latency,
        and the captured SIB states and instrument registers must all match
        the model. Returns the model state."""
        dbg = dict(dbg_disable or {})
        rng = self.rng(f"ijtag.{context}")
        inst_values = {
            name: rng.getrandbits(IJTAG_INSTRUMENT_WIDTHS[name]) for name in IJTAG_SIB_ORDER
        }
        marker = rng.getrandbits(SCAN_MARKER_WIDTH) | (1 << (SCAN_MARKER_WIDTH - 1))
        await self.set_dbg_disable_vector(dbg)
        gated_controls = self.ijtag_gated_controls(dbg)
        if gated_controls:
            state = await self.program_ijtag_sibs_quiet(
                pattern,
                dbg_disable=dbg,
                quiet=gated_controls,
                inst_values=inst_values,
                context=f"{context}.program",
            )
        else:
            state = await self.program_ijtag_sibs(
                pattern, dbg_disable=dbg, inst_values=inst_values, context=f"{context}.program"
            )
        quiet, active = self.ijtag_window_signals(state)
        window = self.start_scan_window(quiet + active)
        observed = await self.ijtag_scan(
            dbg_disable=dbg,
            marker=marker,
            width=IJTAG_OBSERVE_SCAN_WIDTH,
            context=f"{context}.observe",
        )
        self.check_scan_window(
            window, quiet=tuple(quiet), active=tuple(active), context=f"{context}.window"
        )
        self.check_ijtag_chain_latency(
            observed, marker, state.chain_len, context=f"{context}.latency"
        )
        return state

    async def check_ijtag_all_closed(
        self, *, dbg_disable: dict[str, int] | None = None, context: str
    ) -> None:
        """A close-everything scan under a window with every SIB already
        closed or gated before it: no SIB select pulses (a stored open bit
        re-arming on gate release would pulse here)."""
        quiet = tuple(f"{self.IJTAG_SIGNAL_PREFIX[name]}_select" for name in IJTAG_SIB_ORDER)
        window = self.start_scan_window(quiet)
        await self.program_ijtag_sibs(0, dbg_disable=dbg_disable, context=context)
        self.check_scan_window(window, quiet=quiet, context=f"{context}.window")

    def check_host_scan_out_reset(self, *, context: str) -> None:
        """Before any scan captures into them, every iJTAG SIB and the extended
        STAP chain drive a resolved 0 on their host scan output
        (``CHK-SCAN-RESET``)."""
        names = [f"{self.IJTAG_SIGNAL_PREFIX[name]}_host_scan_out" for name in IJTAG_SIB_ORDER]
        names.append("jtag_stap_host_scan_out")
        for name in names:
            sampled = self.cfg.tb_if.handle(name).value
            try:
                observed = int(sampled)
            except ValueError:
                observed = -1
            self.family_check(
                "CHK-SCAN-RESET", name, observed, 0, context=f"{context} sampled={sampled}"
            )

    # --- STAP / 3DCR ---------------------------------------------------------
    # The extended STAP host scan controls on dtp_scan_if.
    HOST_SCAN_CONTROLS = dtp_jtag_base_test_seq.scan_ctrl_signals("jtag_stap_host")

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

    # --- composed TAP_3DCR chain scans (IEEE 1838 serial configuration) -------
    # With the PTAP 3DCR select set, the TAP_3DCR data register is the 2-bit
    # PTAP 3DCR followed serially by the STAP configuration chain, and the
    # chain shifts on every scan, so each scan drives the full chain state.
    # With the select clear the chain holds and a scan reaches only the PTAP
    # 3DCR. Scans are over-length: leading zeros pass through and the
    # trailing bits land in the chain. 64 bits
    # holds the worst case (PTAP 3DCR + a 32-bit downstream IDCODE + the
    # I/O STAP splice + four open SIBs with their 3DCRs + the host segment).
    STAP_CHAIN_SCAN_WIDTH = 64
    # The PTAP instruction of each composed data-scan kind.
    CHAIN_SCAN_NAMES = {"dr": "TAP_3DCR", "zlb": "ZERO_LENGTH_BYPASS", "bypass": "BYPASS"}

    # --- downstream STAP TAPs ------------------------------------------------
    def attach_downstream_taps(self) -> None:
        """Seed the chain model with every attached downstream TAP and the
        host segment, and route the downstream slave-sequence evidence into
        this pass's family checker.

        Call once per pass after ``attach_family_checker``; a scenario on a
        bench with no attached ports is unaffected.
        """
        if self.cfg.stap_host_segment:
            self.stap_model.attach_host_segment()
            self.log.info(
                "host segment behind the extended STAP host scan: width=%d",
                STAP_HOST_SEGMENT_WIDTH,
            )
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
        """Reset the scan network and load TAP_3DCR over a zeroed chain.

        TRST clears the PTAP 3DCR and every STAP SIB and 3DCR (a held
        config_hold included) and parks the downstream TAPs on IDCODE. With
        the PTAP select clear the chain holds through the TAP_3DCR load and
        the over-length zero scan, which leaves the PTAP 3DCR cleared.
        """
        self.log.info("%s reset and flush the TAP_3DCR configuration chain", context)
        await self.apply_trst()
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
        host_segment: int | None = None,
        marker: int = 0,
        context: str,
        scan_kind: str = "dr",
    ) -> int:
        """One composed data scan driving the full chain state.

        The loaded PTAP instruction must match ``scan_kind``: TAP_3DCR
        (stap_chain_flush) for ``"dr"``, ZERO_LENGTH_BYPASS for ``"zlb"``,
        or BYPASS for ``"bypass"``, the last two with the PTAP 3DCR select
        set and no PTAP 3DCR field in the scan. Unspecified fields keep
        their stored values, so a bare call is a maintain scan whose
        captured bits read back the pre-scan chain state; ``ds_values``
        writes a spliced downstream TAP's selected (writable) register and
        ``host_segment`` the host segment while it is in the chain.
        ``marker`` rides in the leading bits that pass through the chain.
        The chain moves only while the PTAP select is already set, so a call
        that sets the select and writes chain fields first sets the select
        in a scan of its own.
        """
        assert scan_kind == "dr" or (ptap_select is None and ptap_config_hold is None), (
            f"a {scan_kind} scan does not reach the PTAP 3DCR"
        )
        if (
            ptap_select
            and not self.stap_model.ptap_select
            and (sib_en or payloads or ds_values or host_segment is not None)
        ):
            await self.stap_chain_write(
                ptap_select=ptap_select,
                ptap_config_hold=ptap_config_hold,
                dbg_disable=dbg_disable,
                context=f"{context}.ptap_select",
            )
            ptap_select = ptap_config_hold = None
        kwargs = {
            "ptap_select": ptap_select,
            "ptap_config_hold": ptap_config_hold,
            "sib_en": sib_en,
            "payloads": self._payload_states(payloads),
            "ds_values": ds_values,
            "dbg_disable": dbg_disable,
            "host_segment": host_segment,
        }
        value = self.stap_model.compose_scan(
            self.STAP_CHAIN_SCAN_WIDTH, scan_kind=scan_kind, **kwargs
        )
        chain_len = len(self.stap_model.chain_layout(dbg_disable, scan_kind))
        assert marker < 1 << (self.STAP_CHAIN_SCAN_WIDTH - chain_len), "marker overlaps the chain"
        value |= marker
        self.log.info(
            "%s %s chain scan value=0x%016x chain_len=%d sib_en=%s payloads=%s ds=%s "
            "host_segment=%s",
            context,
            self.CHAIN_SCAN_NAMES[scan_kind],
            value,
            chain_len,
            sib_en,
            payloads,
            ds_values,
            host_segment,
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
        (``ds_ir`` names new instructions; others keep the active one). With
        the select clear the scan carries the PTAP instruction alone.
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
        self,
        *,
        dbg_disable: dict[str, int] | None = None,
        marker: int = 0,
        context: str,
        scan_kind: str = "dr",
    ) -> int:
        """State-preserving chain scan; the capture reads back stored state."""
        return await self.stap_chain_write(
            dbg_disable=dbg_disable, marker=marker, context=context, scan_kind=scan_kind
        )

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

    def check_stap_chain_marker(
        self,
        captured: int,
        marker: int,
        *,
        dbg_disable: dict[str, int] | None = None,
        context: str,
    ) -> None:
        """The marker a maintain scan shifts ahead of the chain image leaves
        TDO right behind the captured chain, so where it arrives is the
        length of the chain the scan returned through (``CHK-SCAN-CHAIN``).

        Valid while the PTAP 3DCR select was already 1 before the scan.
        """
        chain_len = len(self.stap_model.chain_layout(dbg_disable))
        self.family_check(
            "CHK-SCAN-CHAIN",
            "stap_chain_marker_passthrough",
            (captured >> chain_len) & self.bit_mask(SCAN_MARKER_WIDTH),
            marker,
            context=f"{context} len={chain_len} captured=0x{captured:x}",
        )

    async def read_ptap_3dcr_deselected(self, *, marker: int, context: str) -> int:
        """PTAP 3DCR readback while its select is clear.

        With the select clear, TDO carries the 2-bit PTAP 3DCR register
        itself (config_hold at bit 0, then select) and the marker arrives two
        bits later; the chain return would place it ``chain_len`` bits later,
        so the marker position proves which path answered (``CHK-SCAN-OBS``).
        """
        model = self.stap_model
        assert model.ptap_select == 0, "the model must hold the PTAP select clear"
        expected = model.ptap_3dcr_value(config_hold=model.ptap_config_hold, select=0)
        captured = await self.stap_chain_maintain(marker=marker, context=context)
        self.family_check(
            "CHK-SCAN-OBS",
            "ptap_3dcr_readback",
            captured & self.bit_mask(PTAP_3DCR_WIDTH),
            expected,
            context=f"{context} captured=0x{captured:x}",
        )
        self.family_check(
            "CHK-SCAN-OBS",
            "ptap_3dcr_tdr_path_marker",
            (captured >> PTAP_3DCR_WIDTH) & self.bit_mask(SCAN_MARKER_WIDTH),
            marker,
            context=context,
        )
        return captured

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

    def stap_forwarding_watch(self, stap: str) -> tuple[str, ...]:
        """The host-port observables ``check_stap_forwarding`` judges."""
        prefix = self.stap_signal_prefix(stap)
        return (f"{prefix}_tdo_oen", f"{prefix}_tms", f"{prefix}_tms_mismatch")

    def check_stap_forwarding(
        self,
        edges: int,
        counts: dict[str, int],
        *,
        stap: str,
        forwarding: bool,
        context: str,
    ) -> None:
        """A selected STAP forwards: tdo_oen pulses during shifts and the
        host tms follows the live TMS, equal to the primary TMS at every
        rising TCK edge of a window where it toggles. A deselected or gated
        STAP never drives tdo_oen and parks its tms at the stored tms_hold,
        high or low for the whole window."""
        prefix = self.stap_signal_prefix(stap)
        tdo_oen = counts[f"{prefix}_tdo_oen"]
        tms = counts[f"{prefix}_tms"]
        mismatches = counts[f"{prefix}_tms_mismatch"]
        if forwarding:
            self.family_check(
                "CHK-SCAN-WIN",
                f"{prefix}_tdo_oen forwarding",
                int(tdo_oen > 0),
                1,
                context=f"{context} count={tdo_oen}/{edges}",
            )
            self.family_check(
                "CHK-SCAN-WIN",
                f"{prefix}_tms equals the primary TMS",
                mismatches,
                0,
                context=f"{context} mismatches={mismatches}/{edges}",
            )
            self.family_check(
                "CHK-SCAN-WIN",
                f"{prefix}_tms follows live TMS",
                int(0 < tms < edges),
                1,
                context=f"{context} count={tms}/{edges}",
            )
        else:
            tms_hold = self.stap_model.staps[stap].tms_hold
            self.family_check(
                "CHK-SCAN-WIN", f"{prefix}_tdo_oen quiet", tdo_oen, 0, context=context
            )
            self.family_check(
                "CHK-SCAN-WIN",
                f"{prefix}_tms parked at tms_hold={tms_hold}",
                tms,
                edges * tms_hold,
                context=f"{context} edges={edges}",
            )

    async def apply_tlr(self) -> None:
        """Five TMS=1 cycles into Test-Logic-Reset, then Run-Test/Idle.

        An attached checker records the walk as ``CHK-TAP-TLR-TMS5``.
        """
        for _ in range(5):
            item = await self.tms_step(1)
        if self.tap_checker is not None:
            self.tap_checker.check_tms_ones_to_tlr(5, item.result)
        self.record_tap_state(item.result, OcahJtagState.TEST_LOGIC_RESET)
        item = await self.tms_step(0)
        self.record_tap_state(item.result, OcahJtagState.RUN_TEST_IDLE)
        self.stap_model.tlr()
        self.ijtag_model.reset()

    async def apply_trst(self) -> None:
        """Pulse the active-low TRST pin, then step into Run-Test/Idle."""
        await self.assert_trst(cycles=5)
        await self.deassert_trst(cycles=2)
        item = await self.tms_step(0)
        self.record_tap_state(item.result, OcahJtagState.RUN_TEST_IDLE)
        self.stap_model.trst()
        self.ijtag_model.reset()
