# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Real SEP DV OTBN CSR firmware under the OSS SMU wrapper.

Boots hw/sys/sep/dv/fw/tests/sep_smu_otbn, which writes five OTBN CSRs
(INTR_ENABLE, INTR_STATE, ERR_BITS, INSN_CNT, LOAD_CHECKSUM), reads INTR_ENABLE
back, and parks in its pass loop only if the readback matches what it wrote.

WHAT THIS PROVES, precisely. OTBN sits at 0x1090_0000, inside the SEP's own
peripheral region, so these five accesses travel the SEP-internal fabric; the
outbound filter, whose only open window is the STDOUT mailbox, never sees them.
Reaching the pass loop means two things about that internal path: no access
took a store fault (crt0 installs a trap handler that parks elsewhere), and the
INTR_ENABLE write both arrived and stuck, since the image compares the value it
read back against the value it wrote and branches to its fail loop on a
mismatch. A write silently absorbed by a default slave is therefore caught
rather than assumed.

WHAT IT DOES NOT PROVE. Nothing about OTBN functionality, and nothing about the
SEP outbound fabric: there is no IMEM/DMEM load and no EXECUTE, the other four
writes are observed only through the absence of a fault, and no transaction is
counted at the OTBN aperture itself.

This image needs no entropy: it does not touch AES masking or the Key Manager.
"""

from __future__ import annotations

from seq_lib.sep_terminal_loop_seq import SepTerminalLoopSeq


class SmuSepOtbnSeq(SepTerminalLoopSeq):
    NAME = "sep_otbn"
    PASS_SYM = "smu_sep_otbn_pass_loop"
    FAIL_SYMS = {"otbn": "smu_sep_otbn_fail_loop"}
    SYM_DEFAULT = "sep_smu_otbn.tcm.sym"
    EVIDENCE = ("SEP_REAL_FW_OTBN_CSR_REACHABLE",)
