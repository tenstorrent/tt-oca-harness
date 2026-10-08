# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_ndm_reset_handshake_test - NDM reset request mirror and process output.

SMU_RESET_026 (smu_ndm_reset_handshake_test), steps S1-S8, checkers CHK-NDM-REQUEST-S1..S4 and CHK-NDM-PROCESS-S1..S3.
Spec: hw/sys/smc/regs/blocks/ndm_reset/ndm_reset.rdl, doc/integrator/src/smu-smc.adoc (External CPU cluster NDM reset), hw/sys/smu/doc/port_table.adoc.

CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smu \\
    --items smu_ndm_reset_handshake_test --target compile_smu_chiplet
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_ndm_reset_handshake_test_seq import smu_ndm_reset_handshake_test_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_ndm_reset_handshake_test(smu_base_test):
    """NDMRESET_REQUEST mirrors the request pins and NDMRESET_PROCESS drives the process pins."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        await smu_ndm_reset_handshake_test_seq(self).run()
