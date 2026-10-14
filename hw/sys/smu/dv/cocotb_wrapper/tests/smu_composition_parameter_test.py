# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_composition_parameter_test - parameter and wire plumbing into the subsystems.

`doc/integrator/src/smu.adoc` states the SMU default parameters, the DTP
counts the SMC reservation adds to them, the fixed SEP OTP pipeline depths and
the extra-STAP port sizing; the SMC port table states the external interrupt
count; `hw/sys/sep/doc/security_disable.adoc` states the token width. Those
are the goldens the evidence tokens rest on, together with plumbing compares
of one parameter read at the wrapper and at the instance that consumes it.

`CFG` is compared only as a whole between the wrapper and `smu`; each
parameter is proven where an instance consumes it.

On the `--dut smu` production wrapper (compile_smu_chiplet, +expected_sep=1):
reads the 256-bit SEP_SEC_DISABLE_TOKEN at the SEP eFuse controller that
consumes it, the DTP's fixed SEP OTP pipeline
depths and each DTP and port parameter the build configuration sizes, at the
instance that consumes it, and records the security_disable net at the SEP
eFuse controller that drives it, the `smu` wire and the SMC input.

CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smu \\
    --items smu_composition_parameter_test \\
    --tool verilator
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_composition_parameter_seq import smu_composition_parameter_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_composition_parameter_test(smu_base_test):
    """Token, OTP depth, security_disable and CFG plumbing on the wrapper profile."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        await smu_composition_parameter_seq(self).run()
