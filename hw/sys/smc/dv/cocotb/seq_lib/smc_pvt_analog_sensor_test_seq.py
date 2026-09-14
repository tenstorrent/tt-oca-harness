# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""PVT analog + GPIO POC/PBIAS (TC_SMC_P1CG_13/14/15).

* SMC_PVT_WRAP_COMBINED_PVT / TEMP — ``pvt_wrap`` OKAY + 0.
* GPIO_POC_PBIAS_CTRL (0xC000_4DE0) — on the gpio_ctrl port
  (``u_gpio_ctrl_err_slv``): DECERR + 0.
"""

from __future__ import annotations

from .smc_csr_seq_utils import SmcCsrSeq

PVT_OKAY_READS = [
    ("PVT_COMBINED_CTRL_0", 0xC000_7000, 0),
    ("PVT_COMBINED_CTRL_1", 0xC000_7004, 0),
    ("PVT_COMBINED_STATUS", 0xC000_7008, 0),
    ("TEMP_SENSOR_CTRL_0", 0xC000_7900, 0),
    ("TEMP_SENSOR_CTRL_1", 0xC000_7904, 0),
    ("TEMP_SENSOR_STATUS", 0xC000_7908, 0),
]

POC_PBIAS_DECERR_READS = [
    ("GPIO_POC_PBIAS_CTRL", 0xC000_4DE0, None),
    ("GPIO_POC_PBIAS_ACCESS_FILTER", 0xC000_4DE8, None),
]


class smc_pvt_analog_sensor_test_seq(SmcCsrSeq):
    async def body(self) -> None:
        await self.csr_read_many(PVT_OKAY_READS)
        await self.csr_read_many_decerr_zero(POC_PBIAS_DECERR_READS)
