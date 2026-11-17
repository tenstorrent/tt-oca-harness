# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_axi_ext_in_illegal_encoding_test - illegal encodings and legal bursts on ext_in.

DV-TESTCASE-CONTRACT: TC_G11 ANCHOR: smu_axi_ext_in_illegal_encoding_test
DV-TESTCASE-CONTRACT-REVISION: 3 RECORD-SHA256: 5fa0ba9d86d17fb3a0c786960f0ac12a30bcb5ed9895024c390827bbf027255d
DV-TESTCASE-CONTRACT-SOURCE: hw/sys/smu/dv/ai/dv_vplan_gen/SMU_AXI_GAPS_VPLAN_DETAIL.md @ artifact_revision 10 ENV: cocotb

A raw-channel driver on the ext_in pins presents legal INCR, FIXED and WRAP
bursts and narrow writes into the SEP SRAM and the SMC scratchpad, then a WRAP
burst with AxLEN 0, the reserved burst encoding and a 4 KiB-crossing INCR
toward the SEP aperture, the SMC aperture and neither aperture, each followed
by a fresh legal access. The SMU forwards each illegal request unchanged to
the link its start address selects and the target answers it as the boundary
contract states; +smu_axi_illegal_inject presents those three encodings to
the checkers on that path as legal, and the leaf grades the forwarded fields
on the target links itself. VCS only; the bench checkers print their CHK-AXI-SVA and
CHK-AXI-STALL lines at final.

CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smu \\
    --items smu_axi_ext_in_illegal_encoding_test --target compile_smu_chiplet --tool vcs
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_axi_ext_in_illegal_encoding_test_seq import (
    smu_axi_ext_in_illegal_encoding_test_seq,
)
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_axi_ext_in_illegal_encoding_test(smu_base_test):
    """ext_in illegal encodings under the bench hook and legal burst shapes; no Force."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info("DUT_TAG=WRAPPER smu_axi_ext_in_illegal_encoding_test AXI-ILLEGAL")
        seq = smu_axi_ext_in_illegal_encoding_test_seq(self)
        await seq.run()
        assert seq.done, "ext_in illegal-encoding scenario did not reach its checkers"
