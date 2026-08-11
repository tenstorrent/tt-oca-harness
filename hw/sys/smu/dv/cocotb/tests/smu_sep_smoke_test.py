# SPDX-License-Identifier: Apache-2.0
"""smu_sep_smoke_test — SMU_ALL_007 RST-PRIMARY + CTM.S2/S3 (SEP=0 bare).

DV-CARD:          SMU_ALL_007   ANCHOR: smu_sep_smoke_test
DV-CARD-REVISION: 11   RECORD-SHA256: 01ce931b85a69a79d77782cf37f77dbe6361b59123bff20c856825e861ab6b71
DV-CARD-SOURCE:   hw/sys/smu/dv/tb/SMU_ALL_VPLAN_DETAIL.md @ artifact_revision 11   ENV: cocotb

Card OWNS (narrowed Option B):
  SMC-RST-PRIMARY-EXPORT.S1/S2, DTP-XTRIG-CTM.S2/S3
SEP sysif/LC/SEC_DIS/mem/fuse/WDT/alias, CTM.S1, CTP, DTP CSR are out of scope
(re-homed to 008). Bare tb_top SEP=0 only — not cocotb_wrapper SEP=1.
"""

from __future__ import annotations

import pyuvm

from seq_lib.smu_sep_smoke_test_seq import smu_sep_smoke_test_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_sep_smoke_test(smu_base_test):
    """SMU_ALL_007: SMC primary-reset export + DTP CTM pulse-sync / [1:0]."""

    async def run_scenario(self) -> None:
        self.logger.info(
            "DUT_TAG=BARE smu_sep_smoke_test SMU_ALL_007 under "
            "--dut smu SEP=0 (RST-PRIMARY.S1/S2 + CTM.S2/S3 only)"
        )
        seq = smu_sep_smoke_test_seq(self)
        await seq.run()
