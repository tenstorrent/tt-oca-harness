# SPDX-License-Identifier: Apache-2.0
"""P1 coverage-gap: PVT analog + GPIO POC/PBIAS (TC_SMC_P1CG_13/14/15).

Bundles three previously-unreached analog / mixed-signal CSR surfaces:

* SMC_PVT_WRAP_COMBINED_PVT (0xC000_7000) — combined PVT sensor wrap.
* SMC_PVT_WRAP_TEMP_SENSOR  (0xC000_7900) — temperature sensor wrap.
* GPIO_POC_PBIAS_CTRL       (0xC000_4DE0) — POC / PBIAS control.

The PVT/TEMP windows are externalised macro ports terminated by the OSS bench
DECERR boundary responder (0xBADCAB1E). POC/PBIAS is a real register in the GPIO
block (U5 RW-stub, returns OKAY), at 0xC000_4DE0/0xC000_4DE8 — NOT 0xC000_6000,
which is an unmapped periph-xbar hole (GPIO ends at 0xC000_5000, PVT starts at
0xC000_7000).
"""

from __future__ import annotations

from .smc_csr_seq_utils import SmcCsrSeq

# Externalised PVT/TEMP macro windows -> DECERR boundary responder + 0xBADCAB1E.
PVT_ERR_READS = [
    ("PVT_COMBINED_CTRL_0", 0xC000_7000, None),
    ("PVT_COMBINED_CTRL_1", 0xC000_7004, None),
    ("PVT_COMBINED_STATUS", 0xC000_7008, None),
    ("TEMP_SENSOR_CTRL_0",  0xC000_7900, None),
    ("TEMP_SENSOR_CTRL_1",  0xC000_7904, None),
    ("TEMP_SENSOR_STATUS",  0xC000_7908, None),
]

# POC/PBIAS control lives in the GPIO block (RW-stubbed -> OKAY), not a macro
# window. GPIO_POC_PBIAS_CTRL_CONTROL=0xC000_4DE0, ACCESS_FILTER=0xC000_4DE8.
POC_PBIAS_OKAY_READS = [
    ("GPIO_POC_PBIAS_CTRL", 0xC000_4DE0),
    ("GPIO_POC_PBIAS_ACCESS_FILTER", 0xC000_4DE8),
]


class smc_pvt_analog_sensor_test_seq(SmcCsrSeq):
    async def body(self) -> None:
        # PVT/TEMP macro windows deterministically return the error signature.
        for name, addr, _expected in PVT_ERR_READS:
            await self.csr_read_err_signature(name, addr)
        # POC/PBIAS is a real GPIO-block register: it must decode and return OKAY.
        for name, addr in POC_PBIAS_OKAY_READS:
            await self.csr_read(name, addr)
