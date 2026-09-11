# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_composition_parameter_test - parameter and wire plumbing into the subsystems.

Closes SMU-SEC-TOKEN.S1, SMU-SEC-TOKEN.S2, SMU-OTPAXI-SEP.S3, SMU-LC-SECDIS.S1
and SMU-NOSEP.S4 against SMU_SPEC.md "Configuration Parameters" and "Security
Considerations", on the `--dut smu` production wrapper. The SEP=1 entry
(compile_smu_chiplet_sep_rtl, +expected_sep=1) reads the 256-bit
SEP_SEC_DISABLE_TOKEN at the wrapper, at `smu` and at the SEP eFuse controller
that consumes it, the DTP's forced SEP OTP pipeline depths, and the one
security_disable net from the SEP consumer through the `smu` wire into the SMC
input; both entries decode the elaborated `Cfg` struct field by field against
the spec default table, so the SEP=0 entry (compile_smu_chiplet_no_sep,
+expected_sep=0) shows NoSepCfg field-identical to DefaultCfg.

CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smu \\
    --items smu_composition_parameter_sep_rtl_test smu_composition_parameter_no_sep_test \\
    --tool verilator
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_composition_parameter_seq import smu_composition_parameter_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_composition_parameter_test(smu_base_test):
    """Token, OTP depth, security_disable and Cfg plumbing, both build profiles."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        await smu_composition_parameter_seq(self).run()
