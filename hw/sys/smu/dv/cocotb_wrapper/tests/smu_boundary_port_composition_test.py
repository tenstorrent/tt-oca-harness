# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_boundary_port_composition_test - SEP=1 boundary port widths and presence.

Closes SMU-EXT-SMN.S4, SMU-INT-AGG.S1, SMU-XTRIG-CTP.S1, SMU-XTRIG-CTP.S6,
SMU-LC-STATE.S1, SMU-LC-DEMOTE.S1, SMU-EFUSE-SHIM-SMC.S3, SMU-FUSE-SENSE.S4,
SMU-SSRESET.S2 and SMU-SSRESET.S4 against SMU_SPEC.md "Specifications" and
port_table.adoc, on the `--dut smu` production wrapper built with
compile_smu_chiplet_sep_rtl: every named port is read on the elaborated `smu`
instance for its declared width, the SMN request/response struct widths decode
to the 8-bit inbound and 10-bit outbound IDs, the ID-width converters carry 10
to 6 bits, and the CTP channels whose data inputs the wrapper ties to zero stay
static at zero at the DTP consumer and at the SMU boundary.

CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smu \\
    --items smu_boundary_port_composition_test --tool verilator
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_boundary_port_composition_seq import smu_boundary_port_composition_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_boundary_port_composition_test(smu_base_test):
    """Static widths, presence and tie-off inertness at the SEP=1 SMU boundary."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        await smu_boundary_port_composition_seq(self).run()
