# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP lifecycle flow: real eFuse sense, then firmware-driven demotes, traced to SMC and DTP."""

from __future__ import annotations

import pyuvm
from seq_lib.smu_sep_lcc_flow_seq import SepSenseMonitor, SmuSepLccFlowSeq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_sep_lcc_flow_test(smu_base_test):
    """Require the sensed posture and the demote posture to reach every LCC consumer."""

    async def bring_up(self) -> None:
        # The SEP sense delivers the LC word early in the sense, so the pre-sense
        # posture has to be sampled at cold-reset release, inside bring-up.
        self.sense_mon = SepSenseMonitor(self)
        self.sense_mon.start()
        await super().bring_up()

    async def run_scenario(self) -> None:
        await SmuSepLccFlowSeq(self, self.sense_mon).run()
