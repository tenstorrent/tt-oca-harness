# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""GPIO ACCESS_FILTER AxPROT."""

from __future__ import annotations

import pyuvm
from smc_base_test import smc_base_test
from seq_lib.smc_gpio_filter_access_sep_test_seq import (
    smc_gpio_filter_access_sep_test_seq,
)


@pyuvm.test()
class smc_gpio_filter_access_sep_test(smc_base_test):
    """GPIO0/1 ACCESS_FILTER: AxPROT=1 allow, AxPROT=0 error-slave."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_gpio_filter_access_sep_test_seq("gpio_filter_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        # WHERE THE TEETH ARE. The `*_ok` flags are set unconditionally after
        # their legs, and every leg either raises or compares with `expected=`,
        # so all of them are literal True at this line: the assert they used to
        # feed could not fail on anything the DUT did
        # ([NO-ALWAYS-PASS-CHECKER]).
        #
        # The fail-capable content is in the sequence: the filter's allow leg must
        # return OKAY with the programmed value and the deny leg must return a
        # non-OKAY response on the SAME address, both scoreboard-enforced.
        #
        # What is kept is the one thing not implied upstream: that every leg
        # actually ran. A refactor that made a bounded wait non-raising, or a
        # leg quietly skipped, fails here.
        legs = {"pre": seq.pre_ok, "priv": seq.priv_ok,
                "unpriv": seq.unpriv_ok, "gpio1": seq.gpio1_ok}
        missing = [k for k, v in legs.items() if not v]
        assert not missing, f"gpio filter legs that did not run: {missing}"
