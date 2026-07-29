# SPDX-License-Identifier: Apache-2.0
"""PyUVM entry point for the OSS smc_wrapper elaboration smoke."""

from __future__ import annotations

import pyuvm

from smc_wrapper_base_test import smc_wrapper_base_test
from seq_lib.smc_wrapper_elaboration_seq import SmcWrapperElaborationSeq


@pyuvm.test()
class smc_wrapper_elaboration_test(smc_wrapper_base_test):
    """Verify pad-level powergood / cold-reset propagation on smc_wrapper."""

    async def run_scenario(self) -> None:
        await SmcWrapperElaborationSeq(self).run()
