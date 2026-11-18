# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP_LOCAL_BASE_ADDR reads its reset value, and four SEP_CPU_CTRL registers read back.

The CPU-LSU master reads SEP_LOCAL_BASE_ADDR and writes and reads back four
SEP_CPU_CTRL registers. Each read must return the expected value (CHK-DECODE,
CHK-WR-RB, in seq_lib/sep_axi_smoke_seq.py), and the scoreboard judges every read
value and rejects no access (CHK-NONVAC). No document states the response of these
accesses, so OBS-RESP logs each response code, not graded. Run mode: no_cpu with
+skip_fuse_sense.
"""

from __future__ import annotations

import pyuvm
from env.sep_fabric_common import RESP_NAME
from sep_base_test import sep_base_test
from seq_lib.sep_axi_smoke_seq import WRITE_READBACK, sep_axi_smoke_seq


@pyuvm.test()
class sep_axi_smoke_test(sep_base_test):
    """SEP_LOCAL_BASE_ADDR equals its reset value, and four SEP_CPU_CTRL registers
    return the written pattern over the CPU LSU bus."""

    required_evidence = ("CHK-DECODE", "CHK-WR-RB", "CHK-NONVAC")

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        seq = sep_axi_smoke_seq("smoke_seq")
        mark = self.sb_mark()
        await self.start_seq(seq)

        self.logger.info(
            "OBS-RESP LOG accesses=%d %s",
            len(seq.responses),
            " ".join(f"{op}@0x{addr:08x}={RESP_NAME.get(c, c)}" for op, addr, c in seq.responses),
        )
        rejected = self.env.scoreboard.errors[mark[0] :]
        # One reset read plus one readback per write/readback register.
        reads = 1 + len(WRITE_READBACK)
        judged = self.env.scoreboard.value_checks - mark[1]
        assert judged == reads and not rejected, (
            f"CHK-NONVAC FAIL: scoreboard judged {judged} of {reads} reads; rejections {rejected}"
        )
        self.logger.info(
            "CHK-NONVAC PASS: scoreboard judged %d/%d read values, 0 rejections", judged, reads
        )
