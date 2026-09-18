# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_composition_parameter_test - parameter and wire plumbing into the subsystems.

This tree carries no SMU specification of the build configuration: the
`smu_cfg_t` struct and its `DefaultCfg` / `NoSepCfg` presets exist only in
`hw/sys/smu/rtl/smu_pkg.sv`. The per-field `Cfg` compares below are therefore
drift checks on the elaborated parameters against a table that mirrors that
package, and they carry no evidence token. What the tokens rest on is plumbing
the design can get wrong: a parameter reaching the instance that consumes it.

On the `--dut smu` production wrapper (compile_smu_chiplet, +expected_sep=1):
reads the 256-bit SEP_SEC_DISABLE_TOKEN at the wrapper, at `smu` and at the
SEP eFuse controller that consumes it, the DTP's forced SEP OTP pipeline
depths, and the one security_disable net from the SEP consumer through the
`smu` wire into the SMC input. It also decodes the elaborated `Cfg` struct
field by field and checks each decoded field against the port width or
sub-block parameter that follows it.

CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smu \\
    --items smu_composition_parameter_sep_rtl_test \\
    --tool verilator
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_composition_parameter_seq import smu_composition_parameter_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_composition_parameter_test(smu_base_test):
    """Token, OTP depth, security_disable and Cfg plumbing on the wrapper profile."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        await smu_composition_parameter_seq(self).run()
