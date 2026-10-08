# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for dtp_jtag_runbist_test.

RUNBIST (IR 0x02) selects the iJTAG network as its data register. With every
SIB closed that register is the three-SIB chain; an open SIB splices its
instrument stub in, so a DR scan returns the chain's capture bits followed by
the pattern one TCK per chain flop behind TDI. The RUNBIST
strobe reaches the non-secure DFT host whatever the SIB state and the
``dft_nonsecure`` disable; that disable holds the DFT SIB closed and silences
its host scan controls without touching the instruction decode, and the gated
SIB ignores the Update-DR of a scan that shifts 0 into it, so the stored open
state is effective again once the disable clears.
"""

from __future__ import annotations

import random

from env.dtp_ijtag_sib_model import IJTAG_INSTRUMENT_WIDTHS, DtpIjtagSibModel
from env.dtp_types import DtpJtagInstr, DtpScanCtrlExpect

from .dtp_jtag_base_test_seq import DFT_SCAN_CTRL, SCAN_CTRL_CHECK_IDS, dtp_jtag_base_test_seq

# Wider than the SIB chain, so the retimed pattern is visible above the captures.
RUNBIST_SCAN_WIDTH = 8
# Stored SIB bits that open the non-secure DFT SIB alone, and that close
# every SIB.
DFT_SIB_OPEN = {"dft_secure": 0, "dft": 1, "dfd": 0}
SIBS_CLOSED = {"dft_secure": 0, "dft": 0, "dfd": 0}
RUNBIST_STROBE_CHECK_ID = "CHK-DFT-RUNBIST"
RUNBIST_DR_CHECK_ID = "CHK-RUNBIST-DR-LEN"


class dtp_jtag_runbist_test_seq(dtp_jtag_base_test_seq):
    """Run RUNBIST decode, SIB-chain response, DFT strobe, and DFT SIB gating checks."""

    def __init__(self, name: str = "dtp_jtag_runbist_test_seq", **kwargs) -> None:
        super().__init__(name, **kwargs)
        self.sib_model = DtpIjtagSibModel()
        self.dbg_disable: dict[str, int] = {}

    async def load_runbist(self, context: str) -> None:
        """Load RUNBIST; check its decode and the DFT host's runbist strobe."""
        await self.load_ir(DtpJtagInstr.RUNBIST)
        await self.expect_decoded_instruction(DtpJtagInstr.RUNBIST)
        await self.check_scan_observable(
            RUNBIST_STROBE_CHECK_ID, "jtag_dft_runbist", 1, context=context
        )

    def judge_runbist_tdo(self, pattern: int, observed: int, *, context: str) -> None:
        """Compare one RUNBIST DR scan with the chain prediction, then commit its update."""
        expected = self.sib_model.expected_scan_tdo(pattern, RUNBIST_SCAN_WIDTH, self.dbg_disable)
        self.family_check(
            RUNBIST_DR_CHECK_ID,
            "RUNBIST TDO is the iJTAG chain: capture bits, then TDI behind the chain",
            observed,
            expected,
            context=(
                f"pattern=0x{pattern:02x} chain_len={self.sib_model.chain_len(self.dbg_disable)}"
                f" sibs={self.sib_model.effective(self.dbg_disable)} {context}"
            ),
        )
        self.sib_model.apply_raw_scan(pattern, RUNBIST_SCAN_WIDTH, self.dbg_disable)

    async def runbist_scan(self, pattern: int, *, context: str) -> int:
        """One RUNBIST DR scan judged against the SIB-chain prediction."""
        item = await self.shift_dr(pattern, RUNBIST_SCAN_WIDTH)
        observed = item.result & self.bit_mask(RUNBIST_SCAN_WIDTH)
        self.judge_runbist_tdo(pattern, observed, context=context)
        return observed

    async def runbist_scan_windowed(
        self, pattern: int, *, mode: DtpScanCtrlExpect, context: str
    ) -> None:
        """RUNBIST DR scan under a window on the non-secure DFT host scan controls."""
        item, edges, counts = await self.shift_dr_windowed(
            pattern, RUNBIST_SCAN_WIDTH, self.scan_ctrl_signals(DFT_SCAN_CTRL)
        )
        self.judge_runbist_tdo(
            pattern, item.result & self.bit_mask(RUNBIST_SCAN_WIDTH), context=context
        )
        self.check_scan_ctrl_counts(
            DFT_SCAN_CTRL,
            counts,
            width=RUNBIST_SCAN_WIDTH,
            mode=mode,
            context=f"{context} edges={edges}",
        )

    def dft_open_pattern(self, rng: random.Random) -> int:
        """RUNBIST scan value that keeps only the DFT SIB open and randomizes the rest."""
        value = self.sib_model.compose_scan(
            RUNBIST_SCAN_WIDTH,
            pattern=self.sib_model.pattern_value(DFT_SIB_OPEN),
            inst_values={"dft": rng.getrandbits(IJTAG_INSTRUMENT_WIDTHS["dft"])},
            dbg_disable=self.dbg_disable,
        )
        free = RUNBIST_SCAN_WIDTH - self.sib_model.chain_len(self.dbg_disable)
        return value | self.random_pattern(free, rng)

    def dft_gated_pattern(self, rng: random.Random) -> int:
        """RUNBIST scan value that shifts 0 into every SIB flop and randomizes the rest."""
        value = self.sib_model.compose_scan(
            RUNBIST_SCAN_WIDTH,
            pattern=self.sib_model.pattern_value(SIBS_CLOSED),
            dbg_disable=self.dbg_disable,
        )
        free = RUNBIST_SCAN_WIDTH - self.sib_model.chain_len(self.dbg_disable)
        return value | self.random_pattern(free, rng)

    async def open_dft_sib(self) -> None:
        """Program the SIB chain through SELECT_IJTAG so only the DFT SIB is open."""
        width = self.sib_model.chain_len(self.dbg_disable)
        value = self.sib_model.compose_scan(
            width, pattern=self.sib_model.pattern_value(DFT_SIB_OPEN), dbg_disable=self.dbg_disable
        )
        await self.load_ir(DtpJtagInstr.SELECT_IJTAG)
        await self.shift_dr(value, width)
        self.sib_model.apply_raw_scan(value, width, self.dbg_disable)

    async def check_runbist_response(self, rng: random.Random) -> None:
        """Directed and seeded RUNBIST scans: chain response, distinct and nonzero."""
        patterns = [0x00, 0xFF, 0x5A, 0xA5]
        patterns.extend(
            self.random_pattern(RUNBIST_SCAN_WIDTH, rng) for _ in range(self.random_count)
        )
        results = []
        for idx, pattern in enumerate(patterns, start=1):
            results.append(await self.runbist_scan(pattern, context=f"sweep#{idx}"))
        self.family_check(
            "CHK-RUNBIST-RESPONSE",
            "distinct RUNBIST scan responses",
            int(len(set(results)) > 1),
            1,
            context=f"patterns={patterns} results={results}",
        )
        self.family_check(
            "CHK-RUNBIST-RESPONSE",
            "nonzero RUNBIST scan response",
            int(any(result != 0 for result in results)),
            1,
            context=f"results={results}",
        )

    async def body(self) -> None:
        await self.attach_family_checker(
            {
                "CHK-TAP-RESET-TLR",
                "CHK-IR-DECODE",
                "CHK-RUNBIST-RESPONSE",
                RUNBIST_DR_CHECK_ID,
                RUNBIST_STROBE_CHECK_ID,
                *SCAN_CTRL_CHECK_IDS[DFT_SCAN_CTRL],
                "CHK-SCAN-COUNT",
                "CHK-SCAN-IR-LEN",
                "CHK-SCAN-DR-LEN",
                "CHK-NONVAC",
            },
        )
        rng = self.rng("runbist")
        self.log_banner("RUNBIST: decode, SIB-chain response, DFT strobe, DFT SIB gating")
        self.log_step(1, "Reset TAP; RUNBIST raises the DFT runbist strobe, BYPASS drops it")
        await self.reset_to_tlr()
        self.sib_model.reset()
        self.dbg_disable = {}
        await self.load_runbist("RUNBIST loaded")
        await self.load_ir(DtpJtagInstr.BYPASS_3F)
        await self.check_scan_observable(
            RUNBIST_STROBE_CHECK_ID, "jtag_dft_runbist", 0, context="BYPASS loaded"
        )
        await self.load_runbist("RUNBIST reloaded")

        self.log_step(2, "RUNBIST DR scans return the chain capture, then the pattern behind it")
        await self.check_runbist_response(rng)

        self.log_step(3, "Open the DFT SIB: the RUNBIST scan drives the DFT host scan controls")
        await self.open_dft_sib()
        await self.load_runbist("RUNBIST with the DFT SIB open")
        await self.runbist_scan_windowed(
            self.dft_open_pattern(rng), mode=DtpScanCtrlExpect.SELECTED, context="dft enabled"
        )

        self.log_step(4, "dft_nonsecure disable gates the DFT SIB, not the RUNBIST instruction")
        await self.set_dbg_disable(dft_nonsecure=1)
        self.dbg_disable = {"dft_nonsecure": 1}
        await self.load_runbist("RUNBIST under the dft_nonsecure disable")
        await self.runbist_scan_windowed(
            self.dft_gated_pattern(rng), mode=DtpScanCtrlExpect.GATED, context="dft disabled"
        )

        self.log_step(5, "Clearing the disable restores the stored DFT SIB open state")
        await self.set_dbg_disable(dft_nonsecure=0)
        self.dbg_disable = {}
        await self.runbist_scan_windowed(
            self.dft_open_pattern(rng), mode=DtpScanCtrlExpect.SELECTED, context="dft restored"
        )
        await self.finalize_family_checker()
