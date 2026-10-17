# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_sep_wdt_bite_to_smc_reset_test - SEP watchdog bite into the SMC reset unit and its release.

CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smu \\
    --items smu_sep_wdt_bite_to_smc_reset_test --target compile_smu_chiplet
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_sep_wdt_bite_to_smc_reset_test_seq import smu_sep_wdt_bite_to_smc_reset_test_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_sep_wdt_bite_to_smc_reset_test(smu_base_test):
    """SEP watchdog bite drops the SMC watchdog-term and warm resets; the cool pin releases them."""

    use_shared_env = True
    required_evidence = (
        "CHK-NONVAC",
        "CHK-SEP-WDT-SMC-ASSERT",
        "CHK-SEP-WDT-SMC-CONVERGE",
        "CHK-SEP-WDT-SMC-HOLD",
        "CHK-SEP-WDT-SMC-ORDER",
        "CHK-SEP-WDT-SMC-PRIMARY-COLD",
        "CHK-SEP-WDT-SMC-RELEASE",
        "CHK-SEP-WDT-SMC-REQ",
        "CHK-SEP-WDT-SMC-TERM-WARM",
        "CHK-TIMEOUT-PATHS",
    )

    async def run_scenario(self) -> None:
        self.logger.info("DUT_TAG=WRAPPER smu_sep_wdt_bite_to_smc_reset_test SEP=1 JTAG")
        seq = smu_sep_wdt_bite_to_smc_reset_test_seq(self)
        await seq.run()
        assert seq.done, "SEP watchdog bite to SMC reset scenario incomplete"
