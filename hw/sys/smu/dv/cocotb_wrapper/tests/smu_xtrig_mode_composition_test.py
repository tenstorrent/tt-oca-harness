# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_xtrig_mode_composition_test - per-internal-CT mode vector into DTP.

`Cfg.XTRIG_INT_CT_MODE` and the SMU concatenation that places SMC-reserved
pulse-sync bits in the low lanes exist only in `hw/sys/smu/rtl/smu_pkg.sv` and
`hw/sys/smu/rtl/smu.sv`; this tree carries no SMU specification of either. The
parameter reads below are therefore drift checks and carry no evidence token.
What the tokens rest on is the live leg: `hw/sys/smu/doc/port_table.adoc` states
that the CTM ack ports are "Unused in pulse-sync mode (mode bit = 0)", and each
external CTM lane is requested in turn so that a lane whose mode bit is set
acknowledges and a pulse-sync lane does not.

On the `--dut smu` production wrapper built with compile_smu_chiplet.

CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smu \\
    --items smu_xtrig_mode_composition_test --tool verilator
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_xtrig_mode_composition_seq import smu_xtrig_mode_composition_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_xtrig_mode_composition_test(smu_base_test):
    """Mode vector concatenation into DTP, with SMC-reserved lanes pulse-sync."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        await smu_xtrig_mode_composition_seq(self).run()
