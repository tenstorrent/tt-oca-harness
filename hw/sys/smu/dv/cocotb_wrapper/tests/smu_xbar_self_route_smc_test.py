# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_xbar_self_route_smc_test - an SMC access into its own global aperture stays local.

The crossbar routing table of hw/sys/smu/doc/index.adoc ("AXI Crossbar")
gives the smc_out row's SMC-aperture cell DECERR; the SMC input fabric
(hw/sys/smc/doc/fabric.adoc) sends an internal initiator's global-window
address to the local fabric, so the SMC never issues that request. The
JTAG2AXI bridge, the SMC master the bench drives, writes and reads
GLOBAL_BASE plus the VERSION_LO offset with the aperture at its reset values:
both answer SUCCESS, the read returns the VERSION_LO reset value, and the
crossbar's smc_out port and the smc_in, sep_in and ext_out taps do not move.
A local-alias VERSION_LO read and an egress round trip outside both apertures
are the controls.

CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smu \\
    --items smu_xbar_self_route_smc_test --tool verilator
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_xbar_self_route_smc_test_seq import smu_xbar_self_route_smc_test_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_xbar_self_route_smc_test(smu_base_test):
    """The SMC's global window served locally, with the egress and local-alias controls."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info("DUT_TAG=WRAPPER smu_xbar_self_route_smc_test SEP=1 JTAG2AXI")
        seq = smu_xbar_self_route_smc_test_seq(self)
        await seq.run()
        assert seq.done, "SMC global-window scenario incomplete"
