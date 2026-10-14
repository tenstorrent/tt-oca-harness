# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_xtrig_ctm_select_walk_test - walking-one storage of CT_DST_SELECT in CT_SRC registers.

Spec: cross_trigger_matrix.rdl (CT_SRC[n].CT_DST_SELECT), cross_trigger_matrix/doc/architecture.adoc
(port indexing), cross_trigger_network.rdl (CTN window), smc.rdl (DTP CSR window base).
Bit n of CT_DST_SELECT is written in a CT_SRC register of each index kind and read back.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_xtrig_ctm_select_walk_test_seq import smu_xtrig_ctm_select_walk_test_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_xtrig_ctm_select_walk_test(smu_base_test):
    """CT_DST_SELECT[25:0] walking-one storage across CTP, reserved-lane and exposed-lane
    indexes."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        await smu_xtrig_ctm_select_walk_test_seq(self).run()
