# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_xbar_connectivity_matrix_test - ext_in has no route to ext_out.

The routing the check below requires -- an unmatched `ext_in` access returns
a decode error and does not reach `ext_out` -- is the integrator guide's rule
(`doc/integrator/src/smu.adoc`, "SMU AXI Crossbar Address Map"). The DECERR
and the silence at the SMN egress boundary are measured on the DUT.

On the `--dut smu` production wrapper built with compile_smu_chiplet:
the external master issues a read and a write to an address outside both live
apertures, the crossbar itself answers DECERR with the issued IDs, and the SMN
egress boundary counters do not move. SMU-XBAR-CONN.S5 and S6 (sep_out and
smc_out self-routes) need SEP or SMC firmware that targets its own aperture and
are not claimed here.

CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smu \\
    --items smu_xbar_connectivity_matrix_test --tool verilator
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_xbar_connectivity_matrix_seq import smu_xbar_connectivity_matrix_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_xbar_connectivity_matrix_test(smu_base_test):
    """Unmatched ext_in access decode-errors instead of reaching ext_out."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        await smu_xbar_connectivity_matrix_seq(self).run()
