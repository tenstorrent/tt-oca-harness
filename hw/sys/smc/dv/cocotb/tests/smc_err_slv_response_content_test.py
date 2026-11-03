# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
# DV-TESTCASE-CONTRACT: TC_M9 ANCHOR: smc_err_slv_response_content_test
# DV-TESTCASE-CONTRACT-REVISION: 4 RECORD-SHA256: 2bc401fa5d3517a441624e3c0ed66257a973bdb98bac081e4bb6b9d47bc2a149
# DV-TESTCASE-CONTRACT-SOURCE: hw/sys/smc/dv/ai/dv_vplan_gen/SMC_AXI_FAB_VPLAN_DETAIL.md @ artifact_revision 3 ENV: cocotb
"""Response content of every SMC error subordinate seen from SEP_IN, SYS_IN and JTAG_IN.

Drives single, paired 32-bit, written, INCR burst and narrow accesses to every error
location of nine families (outside both apertures, units past REGION_SIZE, reserved gaps,
the Debug Module window, past-extent words of the 64-bit and 32-bit islands, misc-wrapper
holes, GPIO past slots, clock-gated peripheral windows), then the REGION_SIZE straddling
unit, the clock-gate redirect and the split 8-byte slots. Response code per beat, beat
count, RLAST, IDs, one B per write burst, the stated 0xBADCAB1E word, bystander registers,
SYS_OUT responder counts and a LOCAL_BASE liveness read are graded from a passive
per-port handshake sampler; values the specification leaves open are OBS lines.

Run (VCS: the X-hygiene and data-known rules of the AXI checkers grade on VCS only):
    python3 tools/dv/run_dv.py --dut smc --items smc_err_slv_response_content_test --tool vcs
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_err_slv_response_content_test_seq import smc_err_slv_response_content_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_err_slv_response_content_test(smc_base_test):
    """Grade the error answers of the inbound ports at every error location."""

    required_evidence = (
        "CHK-ERRC-CLKGATE",
        "CHK-ERRC-DEBUGWIN",
        "CHK-ERRC-GAP",
        "CHK-ERRC-GPIOPAST",
        "CHK-ERRC-MISCHOLE",
        "CHK-ERRC-OUTSIDE",
        "CHK-ERRC-PASTEXT32",
        "CHK-ERRC-PASTEXT64",
        "CHK-ERRC-REGIONSIZE",
        "CHK-ERRC-SPLITSLOT",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 12

    async def run_scenario(self) -> None:
        seq = smc_err_slv_response_content_test_seq("err_slv_response_content_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        seq.log_timeout_paths()
        seq.nonvac_fence()
        seq.raise_findings()
