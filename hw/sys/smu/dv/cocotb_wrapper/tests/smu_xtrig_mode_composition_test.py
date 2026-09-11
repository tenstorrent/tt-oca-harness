# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_xtrig_mode_composition_test - per-internal-CT mode vector into DTP.

Closes SMU-XTRIG-MODE.S1 and SMU-XTRIG-MODE.S2 against SMU_SPEC.md
"Configuration Parameters", on the `--dut smu` production wrapper built with
compile_smu_chiplet_no_sep: the DTP's XTRIG_INT_CT_MODE parameter is read as
{Cfg.XTRIG_INT_CT_MODE, 2'b00} with the upper byte equal to the elaborated Cfg
field and to the +xtrig_int_ct_mode contract, and each external CTM lane is
then requested in turn so that only the lanes whose mode bit is set
acknowledge.

CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smu \\
    --items smu_xtrig_mode_composition_test --tool verilator
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_xtrig_mode_composition_seq import smu_xtrig_mode_composition_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_xtrig_mode_composition_test(smu_base_test):
    """Mode vector concatenation {Cfg.XTRIG_INT_CT_MODE, 2'b00} at the DTP."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        await smu_xtrig_mode_composition_seq(self).run()
