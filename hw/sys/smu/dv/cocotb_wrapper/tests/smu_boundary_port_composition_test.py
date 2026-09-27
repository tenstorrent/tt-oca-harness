# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_boundary_port_composition_test - SEP=1 boundary port widths and presence.

Every port read here has a row in `hw/sys/smu/doc/port_table.adoc`: presence,
direction, type, width expression and, for the CTP channels, the "Tie to '0
if unused" note the inertness legs rest on. Every width compare that carries
an evidence token takes its expected value from a specification: the port
table's literal widths, the parameter defaults in
`doc/integrator/src/smu.adoc` "SMU Default Parameters", the SMC port table's
external interrupt count and system AXI input ID width, and the generated
`reset_unit` register header for `SS_CONFIG`. seq_lib/smu_compose_helpers.py
names the source of each constant. The SMN struct widths and the
crossbar-side and SEP-side ID widths have no specification in this tree and
are checked as untokened drift. The `SMU-<feature>.S<n>` ids the CHK-SMU-*
evidence tokens are named after are the ids the coverage policies' deferral
rationales use; no document in this tree defines them.

On the `--dut smu` production wrapper built with compile_smu_chiplet:
every named port is read on the elaborated `smu` instance for its specified
width, the SMC-side ID-width converter presents the 6-bit subsystem ID, the
CTP channels whose data inputs the wrapper ties to zero stay static at zero at
the DTP consumer and at the SMU boundary, `ss_config_o` presents the SS_CONFIG
reset value and `skip_mem_repair_o` is clear with no isolation request
pending.

CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smu \\
    --items smu_boundary_port_composition_test --tool verilator
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_boundary_port_composition_seq import smu_boundary_port_composition_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_boundary_port_composition_test(smu_base_test):
    """Specified widths, idle values and tie-off inertness at the SEP=1 SMU boundary."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        await smu_boundary_port_composition_seq(self).run()
