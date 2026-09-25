# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Outbound words through the M-mode and hypervisor remap windows, over JTAG ingress.

Programs M-mode remap entries 0 and 1 and hypervisor entry 0. It then writes
and reads a word through each window's LOCAL_BASE and GLOBAL_BASE copy, and one
address past the hypervisor window. Each word must land in SYS_OUT memory where
`output_remap.rdl` puts it, and read back through the same window. Outbound
filter entries that match the M-mode source ID must allow the M-mode words and
must not catch the hypervisor words. The entries are restored.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_output_remap_window_test_seq import _LEGS, smc_output_remap_window_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_output_remap_window_test(smc_base_test):
    """Outbound traffic through both copies of both remap windows lands where the entry says."""

    required_evidence = ("CHK-OUTPUT-REMAP-WINDOWS",)
    min_evidence = 1

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_output_remap_window_test_seq("smc_output_remap_window_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.legs_checked == len(_LEGS), (
            f"{seq.legs_checked} of {len(_LEGS)} remap legs checked"
        )
