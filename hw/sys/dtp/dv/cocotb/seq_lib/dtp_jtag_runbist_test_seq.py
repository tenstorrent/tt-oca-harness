# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for dtp_jtag_runbist_test."""

from __future__ import annotations

from env.dtp_types import DtpJtagInstr

from .dtp_jtag_base_test_seq import dtp_jtag_base_test_seq


class dtp_jtag_runbist_test_seq(dtp_jtag_base_test_seq):
    """Run RUNBIST instruction decode and iJTAG loopback checks."""

    async def body(self) -> None:
        await self.reset_tap()
        await self.load_ir(DtpJtagInstr.RUNBIST)
        await self.expect_decoded_instruction(DtpJtagInstr.RUNBIST)

        rng = self.rng("runbist")
        patterns = [0x00, 0xFF, 0x5A, 0xA5]
        patterns.extend(self.random_pattern(8, rng) for _ in range(self.random_count))

        results = []
        for pattern in patterns:
            item = await self.shift_dr(pattern, 8)
            results.append(item.result & 0xFF)

        assert len(set(results)) > 1, (
            "RUNBIST/iJTAG scan path did not respond to changed stimulus: "
            f"patterns={patterns} results={results}"
        )
        assert any(result != 0 for result in results), "RUNBIST/iJTAG scan path was all zero"
