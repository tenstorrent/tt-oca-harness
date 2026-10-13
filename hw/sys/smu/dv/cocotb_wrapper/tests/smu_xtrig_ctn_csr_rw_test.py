# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_xtrig_ctn_csr_rw_test - CTP CSR write and read-back, window independence, serialised access.

Contract: SMU_MISC_XTRIG_009, anchor smu_xtrig_ctn_csr_rw_test.
Spec: cross_trigger_port.rdl (CONFIG, STATUS, STRETCH_MULT), cross_trigger_network.rdl and
architecture.adoc (Address Map), cross_trigger_matrix.rdl (CT_SRC), smc.rdl (DTP CSR window base).
CONFIG and STRETCH_MULT of the CTP ports and CT_SRC registers are accessed through the SMC fabric
JTAG2AXI bridge.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_xtrig_ctn_csr_rw_test_seq import smu_xtrig_ctn_csr_rw_test_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_xtrig_ctn_csr_rw_test(smu_base_test):
    """CTP CSR storage, STATUS write ignore, port window independence and serialised accesses."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        await smu_xtrig_ctn_csr_rw_test_seq(self).run()
