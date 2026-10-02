# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_dtp_scan_chain_boundary_test - iJTAG and secondary-TAP hosts at the pads.

The DFD, DFT and secure-DFT iJTAG SIB hosts and the I/O and extra secondary
TAPs leave smu_wrapper as scan_out/TDO and return as scan_in/TDI. With the
bench closing each loop the shift path runs through those boundary pins, so
this leaf can gate the hosts by instruction, measure the closed chain length,
round-trip the SIB enables, and prove the extra and I/O STAP selects at
their host pins.

CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smu \\
    --items smu_dtp_scan_chain_boundary_test --target compile_smu_chiplet_no_sep
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_dtp_scan_chain_boundary_seq import smu_dtp_scan_chain_boundary_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_dtp_scan_chain_boundary_test(smu_base_test):
    """iJTAG SIB chain and secondary-TAP select, closed through the pads."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        await smu_dtp_scan_chain_boundary_seq(self).run()
