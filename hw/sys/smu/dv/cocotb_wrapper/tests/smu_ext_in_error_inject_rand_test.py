# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_ext_in_error_inject_rand_test - responder error codes returned to the outbound initiators.

CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smu \\
    --items smu_ext_in_error_inject_rand_test --target compile_smu_chiplet
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_ext_in_error_inject_rand_test_seq import smu_ext_in_error_inject_rand_test_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_ext_in_error_inject_rand_test(smu_base_test):
    """A responder SLVERR or DECERR on a drawn beat is the response at the initiator."""

    use_shared_env = True
    required_evidence = (
        "CHK-EXTERR-BEAT",
        "CHK-EXTERR-INBOUND",
        "CHK-EXTERR-NOXBAR",
        "CHK-EXTERR-RECOVER",
        "CHK-EXTERR-RESP",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )

    async def run_scenario(self) -> None:
        self.logger.info("DUT_TAG=WRAPPER smu_ext_in_error_inject_rand_test SEP=1 J2A IDMA SBA")
        seq = smu_ext_in_error_inject_rand_test_seq(self)
        await seq.run()
        assert seq.done, "outbound error-injection scenario incomplete"
