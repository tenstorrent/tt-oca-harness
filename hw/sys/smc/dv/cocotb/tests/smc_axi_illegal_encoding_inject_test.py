# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Illegal AXI encodings on SEP_IN and SYS_IN, the checkers' view masked by the inject hook.

Per port, a write and a read with AxBURST WRAP and AxLEN 0, with the reserved
AxBURST 2'b11, and as an INCR of full-width beats from the misc_wrap
scratch_cold island across one 4 KiB boundary. Each request must be answered
(one B, or AxLEN+1 R beats with RLAST last), registers outside its footprint
must keep their values, and the port must answer a fresh legal read afterwards.
The response codes are observations.

Requires +smc_axi_wrap_len1_inject (the SEP_IN and SYS_IN checkers and the
checkers of the two fabric links the requests are forwarded on see each
request at a legal encoding; the DUT sees the real one) and
+axi_sva_need_sep_in +axi_sva_need_sys_in. Without the inject plusarg the run
fails on the six masked rules (CTRL-G11-NO-INJECT).

Run:
    python3 tools/dv/run_dv.py --dut smc --items smc_axi_illegal_encoding_inject_test \\
        --tool vcs --seed 1
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_axi_illegal_encoding_inject_test_seq import (
    smc_axi_illegal_encoding_inject_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_axi_illegal_encoding_inject_test(smc_base_test):
    """WRAP AxLEN 0, reserved-burst and 4 KiB-crossing requests answered on SEP_IN and SYS_IN."""

    required_evidence = (
        "CHK-G11-4KB-ANSWERED",
        "CHK-G11-FOOTPRINT",
        "CHK-G11-INJECT-MASK",
        "CHK-G11-LIVENESS",
        "CHK-G11-RSVD-BURST-ANSWERED",
        "CHK-G11-SPLIT-BRESP",
        "CHK-G11-WRAP-LEN0-ANSWERED",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 9

    async def run_scenario(self) -> None:
        seq = smc_axi_illegal_encoding_inject_test_seq("axi_illegal_encoding_inject_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.expired == 0 and seq.waits > 0, (
            f"bounded waits {seq.waits}, expired {seq.expired}"
        )
        assert len(seq.reqs) == 12 and all(req.answered for req in seq.reqs), (
            f"illegal requests answered: {[(r.label, r.answered) for r in seq.reqs]}"
        )
