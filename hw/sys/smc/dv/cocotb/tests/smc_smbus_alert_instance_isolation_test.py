# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
# DV-TESTCASE-CONTRACT: SMC_COV_R5_003 ANCHOR: smc_smbus_alert_instance_isolation_test
# DV-TESTCASE-CONTRACT-REVISION: 1 RECORD-SHA256: 890c309bea536ec51786567fbbd950887e9fdf997098b896590d0c6b680db254
# DV-TESTCASE-CONTRACT-SOURCE: hw/sys/smc/dv/ai/dv_vplan_gen/SMC_COV_R5_VPLAN_DETAIL.md @ artifact_revision 1 ENV: cocotb
"""Per-instance SMBUS_EN isolation of the SMBALERT gate across the three I2C instances.

Also SMBUS_EN and CTRL.LLPBK masking of the alert on instances 1, 2 and 0-2,
reserved-bit, partial-strobe and per-entry I2C_CTRL writes, the I2C wrapper
window past its decoded extent and the alert pad direction.

Run:
    python3 tools/dv/run_dv.py --dut smc --items smc_smbus_alert_instance_isolation_test --tool vcs
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_smbus_alert_instance_isolation_test_seq import (
    smc_smbus_alert_instance_isolation_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_smbus_alert_instance_isolation_test(smc_base_test):
    """Clearing one instance's SMBUS_EN leaves the other two instances' SMBALERT status at 1."""

    required_evidence = (
        "CHK-GATE-ALL-SEE-ALERT",
        "CHK-GATE-OTHERS-UNMASKED",
        "CHK-I2C-ALERT-PAD-DIR",
        "CHK-I2C-CTRL-ENTRY-ISOLATE",
        "CHK-I2C-CTRL-PARTIAL-WRITE",
        "CHK-I2C-CTRL-RSVD-WRITE",
        "CHK-I2C-WRAP-PAST-EXTENT",
        "CHK-LLPBK-ALERT-MASK",
        "CHK-NONVAC",
        "CHK-SMBUS-EN-ISOLATE",
        "CHK-SMBUS-EN-MASK-I2C12",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 12

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_smbus_alert_instance_isolation_test_seq("smbus_alert_instance_isolation_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
