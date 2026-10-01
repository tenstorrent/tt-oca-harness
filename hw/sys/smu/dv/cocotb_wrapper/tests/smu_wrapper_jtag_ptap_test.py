# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Drive the primary TAP on the production wrapper with the SEP running."""

from __future__ import annotations

import pyuvm
from seq_lib.smu_wrapper_jtag_ptap_seq import SmuWrapperJtagPtapSeq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_wrapper_jtag_ptap_test(smu_base_test):
    """Require the TAP to answer, and the SEP to keep running while it does."""

    async def run_scenario(self) -> None:
        await SmuWrapperJtagPtapSeq(self).run()
