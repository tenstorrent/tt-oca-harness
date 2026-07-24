# SPDX-License-Identifier: Apache-2.0
"""P1 coverage-gap Round 5: SMC_PVT_WRAP_DROOP sweep (TC_SMC_P1CG_22).

RTL exposes a dedicated droop-monitor sub-block at 0xC000_7400, distinct
from the PVT combined sensor (0xC000_7000) and temperature sensor
(0xC000_7900) that `smc_pvt_analog_sensor_test` already covers. Round 1-4
never reached the droop sub-block. This test reads a representative set of
registers spanning the block (control, sampling, config, and readback
surfaces) via bounded reads — the analog droop monitor may be power/clock
gated in the current OSS bring-up.
"""

from __future__ import annotations

from .smc_csr_seq_utils import SmcCsrSeq

# Representative registers spanning the DROOP block (base 0xC000_7400).
PVT_DROOP_READS = [
    ("DROOP_ENABLES",             0xC000_7400),
    ("DROOP_SAMPLE_STROBE",       0xC000_7404),
    ("DROOP_TARGET_MONITOR_CODE", 0xC000_7408),
    ("DROOP_CONFIG",              0xC000_740C),
    ("DROOP_MEAS_DURATION0",      0xC000_7410),
    ("DROOP_LONG_TERM_MAX_CODE",  0xC000_7418),
    ("DROOP_FORCE",               0xC000_7438),
    ("DROOP_SAMPLED_DROOP",       0xC000_7440),
    ("DROOP_CONFIG_SETTING_0_LW", 0xC000_744C),
    ("DROOP_PERCENT_DELAY_TH0",   0xC000_74EC),
]


class smc_pvt_droop_test_seq(SmcCsrSeq):
    async def body(self) -> None:
        # The PVT/DROOP window is an externalised macro port terminated by the
        # OSS bench DECERR boundary responder (0xBADCAB1E). Assert that signature
        # deterministically rather than tolerating any response.
        for name, addr in PVT_DROOP_READS:
            await self.csr_read_err_signature(name, addr)
