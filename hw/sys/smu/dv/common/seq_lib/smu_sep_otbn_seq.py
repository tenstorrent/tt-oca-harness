# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Real SEP DV OTBN CSR firmware under the OSS SMU wrapper.

Boots hw/sys/sep/dv/fw/tests/sep_smu_otbn, which writes five OTBN CSRs
(INTR_ENABLE, INTR_STATE, ERR_BITS, INSN_CNT, LOAD_CHECKSUM) and parks.

WHAT THIS PROVES, precisely. Reaching the pass loop means those five writes
completed without taking a store access fault: the SEP outbound fabric is
BlockByDefault=1, so a write that missed every filter window would be isolated
and answered with an error, the EL2 would trap, and the image would spin in its
trap handler instead of parking. That is a real reachability claim about the
OTBN register aperture through the SEP fabric.

WHAT IT DOES NOT PROVE. The firmware's own pass/fail branch is vacuous: it keys
off `g_otbn_status`, a file-scope `volatile int` that nothing ever assigns, so
it is zero and the fail branch is unreachable. The fail-loop symbol is watched
here anyway -- it costs nothing and stops being dead the day the firmware sets
that variable -- but a PASS from this test carries no OTBN functional content.
There is no IMEM/DMEM load and no EXECUTE; the firmware header says as much.

This image needs no entropy: it does not touch AES masking or the Key Manager.
The earlier note pairing it with sep_smu_aes as "blocked on entropy bring-up"
was wrong about this half.
"""

from __future__ import annotations

from seq_lib.sep_terminal_loop_seq import SepTerminalLoopSeq


class SmuSepOtbnSeq(SepTerminalLoopSeq):
    NAME = "sep_otbn"
    PASS_SYM = "smu_sep_otbn_pass_loop"
    FAIL_SYMS = {"otbn": "smu_sep_otbn_fail_loop"}
    SYM_DEFAULT = "sep_smu_otbn.tcm.sym"
    EVIDENCE = ("SEP_REAL_FW_OTBN_CSR_REACHABLE",)
