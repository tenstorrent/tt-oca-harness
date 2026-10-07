# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The SMC CPU reads and writes the CSR window of I3C instance 5.

Firmware test: `fw/tests/i3c5_csr_access` reads HCI_VERSION and HC_CONTROL in
the window at `SMC_TOP_OCA_I3C_WRAP_I3C_CSR_BASE_ADDR(5)`, sets and restores
HC_CONTROL.BUS_ENABLE, and publishes every value it read in CPU_CTRL
SCRATCH_4..7. `smc_i3c_to_fabric_test` covers the same registers on instance 0
from SEP_IN; this leaf covers the CPU's path to the sixth instance.

Bench observation: before release, one SEP_IN read of HCI_VERSION per instance
must advance exactly that instance's read counter; then the published values
against the vendor RDL, the accesses
completed at each I3C core's CSR port between release and PASS (four reads
and two writes on instance 5, none elsewhere), and HC_CONTROL read over SEP_IN
after PASS.

Tokens: CHK-FW-I3C5-CSR-COUNTER-PROBE, CHK-FW-I3C5-CSR-BOOT, CHK-FW-I3C5-CSR-ACCESS-COUNT,
CHK-FW-I3C5-HCI-VERSION, CHK-FW-I3C5-HC-CONTROL-BUS-ENABLE.

Requires the staged image and a held boot:
  +smc_scratch_ram_hex=i3c5_csr_access.ecc.hex   (bare basename; staged by c_compile)
  +smc_hold_cpu_boot
Must NOT use +skip_fuse_sense -- see dv_policy 1.6.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_fw_i3c5_csr_access_test_seq import smc_fw_i3c5_csr_access_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_fw_i3c5_csr_access_test(smc_base_test):
    """CPU loads and stores in the I3C5 CSR window, counted at the core's port."""

    auto_protocol_vip = False
    required_evidence = (
        "CHK-FW-I3C5-CSR-ACCESS-COUNT",
        "CHK-FW-I3C5-CSR-BOOT",
        "CHK-FW-I3C5-CSR-COUNTER-PROBE",
        "CHK-FW-I3C5-HC-CONTROL-BUS-ENABLE",
        "CHK-FW-I3C5-HCI-VERSION",
    )
    min_evidence = 5

    async def run_scenario(self) -> None:
        seq = smc_fw_i3c5_csr_access_test_seq("fw_i3c5_csr_access_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.boot.get("boot_checked") is True, f"firmware boot was not checked: {seq.boot}"
        assert seq.access_ok, "the I3C CSR access counts were not checked after PASS"
        assert seq.values_ok, "the published I3C5 values were not checked after PASS"
