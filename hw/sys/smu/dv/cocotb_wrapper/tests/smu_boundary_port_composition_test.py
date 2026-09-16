# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_boundary_port_composition_test - SEP=1 boundary port widths and presence.

Every port read here has a row in `hw/sys/smu/doc/port_table.adoc`, the only
SMU specification this tree carries: the row gives the port's presence,
direction, type, width expression and, for the CTP channels, the "Tie to '0 if
unused" note the inertness legs rest on. The numeric widths those expressions
elaborate to, and the SMN struct field layout, come from the implementation
(`hw/sys/smu/rtl/smu_pkg.sv`, `smu_axi_xbar_pkg.sv`), so a width compare
against one of them is a drift check -- seq_lib/smu_compose_helpers.py states
which constant comes from where. The `SMU-<feature>.S<n>` ids the CHK-SMU-*
evidence tokens are named after are the ids the coverage policies' deferral
rationales use; no document in this tree defines them.

On the `--dut smu` production wrapper built with compile_smu_chiplet:
every named port is read on the elaborated `smu` instance for its declared
width, the SMN request/response struct widths decode to the 8-bit inbound and
10-bit outbound IDs, the ID-width converters carry 10 to 6 bits, and the CTP
channels whose data inputs the wrapper ties to zero stay static at zero at the
DTP consumer and at the SMU boundary.

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
