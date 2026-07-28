# SPDX-License-Identifier: Apache-2.0
"""PyUVM entry point for the production SMU wrapper elaboration smoke."""

from __future__ import annotations

import pyuvm

from smu_base_test import smu_base_test
from seq_lib.smu_wrapper_elaboration_seq import SmuWrapperElaborationSeq


@pyuvm.test()
class smu_wrapper_elaboration_test(smu_base_test):
    """Verify the selected production-wrapper profile and reset propagation."""

    async def run_scenario(self) -> None:
        await SmuWrapperElaborationSeq(self).run()
