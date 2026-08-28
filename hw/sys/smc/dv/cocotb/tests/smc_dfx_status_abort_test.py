# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DFX STATUS_SMU abort pins. Not DEBUG_CTRL reset reads."""

from __future__ import annotations

import pyuvm
from smc_base_test import smc_base_test
from seq_lib.smc_dfx_status_abort_test_seq import smc_dfx_status_abort_test_seq


@pyuvm.test()
class smc_dfx_status_abort_test(smc_base_test):
    """mem_repair_abort / mbist_abort → STATUS_SMU sticky bits."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_dfx_status_abort_test_seq("dfx_status_abort_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        # WHERE THE TEETH ARE. `idle_ok` / `repair_ok` / `mbist_ok` are set
        # unconditionally after their legs, and every leg either raises
        # (`_await_status` has a fail-on-expiry `raise`) or compares with
        # `expected=`. So all three are literal True at this line and the old
        # `assert idle_ok and repair_ok and mbist_ok` could not fail on
        # anything the DUT did ([NO-ALWAYS-PASS-CHECKER]).
        #
        # The fail-capable, DUT-sensitive content is in the sequence: driving
        # `mem_repair_abort_i` / `mbist_abort_i` must make the corresponding
        # DFX_STATUS_SMU bit appear, and the bit must PERSIST after the pin
        # returns to 0 -- both enforced by `csr_read(..., expected=...)` through
        # the scoreboard, and by `_await_status` raising if the word never
        # arrives.
        #
        # Retained here, with an honest split of what each half can do:
        #
        #   * `len(prog) == 3` is NOT implied by anything upstream. It fails if a
        #     stage never ran -- e.g. a refactor that made `_await_status`
        #     non-raising, which is exactly how the old boolean gate could have
        #     gone quiet.
        #   * the superset loop IS implied. The sequence already pins all three
        #     words with exact `expected=` compares (IDLE, IDLE|REPAIR,
        #     IDLE|REPAIR|MBIST), so given those, "each stage is a strict
        #     superset of the previous" is arithmetic, not an observation. It is
        #     kept as a guard against those exact compares being loosened later,
        #     and it is NOT this testcase's proof. Saying otherwise would be the
        #     same mistake as the boolean gate it replaced.
        prog = seq.status_progression
        assert len(prog) == 3, (
            f"DFX abort observed {len(prog)} of 3 STATUS_SMU stages: "
            f"{[hex(v) for v in prog]}"
        )
        for earlier, later in zip(prog, prog[1:]):
            assert later & earlier == earlier and later != earlier, (
                f"DFX_STATUS_SMU did not accumulate: 0x{earlier:x} -> "
                f"0x{later:x}. The abort bits are specified sticky, so each "
                f"stage must be a strict superset of the one before it."
            )
