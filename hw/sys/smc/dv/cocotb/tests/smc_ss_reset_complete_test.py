# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
# DV-TESTCASE-CONTRACT: SMC_COV_B1_004 ANCHOR: smc_ss_reset_complete_test
# DV-TESTCASE-CONTRACT-REVISION: 2 RECORD-SHA256: ab71b0b17cd83a861c0a487544151526d7cc50be78c669a9ce1604b358a1e053
# DV-TESTCASE-CONTRACT-SOURCE: hw/sys/smc/dv/ai/dv_vplan_gen/SMC_COV_B1_VPLAN_DETAIL.md @ artifact_revision 6 ENV: cocotb
"""ss_reset_complete_i CSR on every bit and SS0 warm_reset_n. No firmware."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_ss_reset_complete_test_seq import (
    FENCE_TERMS,
    PATTERN_VECTORS,
    RO_HOLD_VECTOR,
    SS_COMPLETE_ALL_ONE,
    SS_COMPLETE_DROP_0_31,
    SS_WARM_RESET_VALUE,
    WALK_BITS,
    smc_ss_reset_complete_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_ss_reset_complete_test(smc_base_test):
    """Pin→CSR complete on all 32 bits + SW warm SS0; not the FW handshake binary."""

    required_evidence = (
        "CHK-NONVAC",
        "CHK-SS-COMPLETE-DROP",
        "CHK-SS-COMPLETE-IDLE",
        "CHK-SS-COMPLETE-RESTORE",
        "CHK-SS-COMPLETE-SCRATCH-RW",
        "CHK-SS-WARM-SS0",
        "CHK-SSRC-ASSERT",
        "CHK-SSRC-PATTERNS",
        "CHK-SSRC-RELEASE",
        "CHK-SSRC-RO-WRITE",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 11

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_ss_reset_complete_test_seq("ss_reset_complete_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        # `idle_csr` / `drop_csr` / `restore_csr` come from `_await_csr` and
        # `warm_pins` from `_await_warm_pin`, both of which raise unless the value
        # equals the one waited for, so those two asserts guard only against the
        # helpers becoming non-raising. `warm_csr` comes from plain `csr_read`
        # with no `expected=` and the sequence asserts only bit 0 of the
        # asserted/released reads, so its full-word compare covers the other 31
        # bits.
        assert (seq.idle_csr, seq.drop_csr, seq.restore_csr) == (
            SS_COMPLETE_ALL_ONE,
            SS_COMPLETE_DROP_0_31,
            SS_COMPLETE_ALL_ONE,
        ), (
            f"ss_reset_complete_i -> CSR mirror wrong: idle=0x{seq.idle_csr:x} "
            f"drop=0x{seq.drop_csr:x} restore=0x{seq.restore_csr:x}, expected "
            f"0x{SS_COMPLETE_ALL_ONE:x}/0x{SS_COMPLETE_DROP_0_31:x}/0x{SS_COMPLETE_ALL_ONE:x}"
        )
        assert seq.warm_pins == (1, 0, 1), (
            f"ss_reset_ctrl[0].warm_reset_n did not follow the SW bit 1->0->1: {seq.warm_pins}"
        )
        assert seq.warm_csr == (
            SS_WARM_RESET_VALUE,
            SS_WARM_RESET_VALUE & ~0x1,
            SS_WARM_RESET_VALUE,
        ), (
            f"SS_WARM_RESET_N readbacks {seq.warm_csr} do not match the "
            f"programmed sequence around reset value 0x{SS_WARM_RESET_VALUE:x}"
        )
        assert tuple(t for t, _, _ in seq.fence) == FENCE_TERMS, (
            f"the vector legs completed fence terms {seq.fence}, want {FENCE_TERMS}"
        )
        assert (len(seq.assert_polls), len(seq.release_polls)) == (WALK_BITS, WALK_BITS), (
            f"walk covered {len(seq.assert_polls)} asserts / {len(seq.release_polls)} "
            f"releases, want {WALK_BITS} each"
        )
        assert seq.patterns_matched == len(PATTERN_VECTORS), (
            f"{seq.patterns_matched}/{len(PATTERN_VECTORS)} pattern vectors read back"
        )
        assert seq.ro_readbacks == [RO_HOLD_VECTOR, RO_HOLD_VECTOR], (
            f"SS_RESET_COMPLETE followed a write: readbacks {seq.ro_readbacks}, "
            f"want 0x{RO_HOLD_VECTOR:08x} twice"
        )
