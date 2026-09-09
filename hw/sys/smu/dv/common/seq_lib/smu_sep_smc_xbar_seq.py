# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP-driven SMC bring-up and SEP<->SMC crossbar handshake.

Two firmwares again, but unlike smu_sep_bidirect the SEP is the primary and the
SMC does not boot on its own: the SMC image is placed in SMC SRAM by the
testbench (`+smc_scratch_ram_hex`, the 72-bit .ecc.hex that
hw/sys/smc/dv/models/smc_cpu_mem_dv.sv backdoors into the scratch banks), and
the SEP firmware then

  * programs its SMU aperture and inbound window so SMC->SEP writes are routable,
  * opens its outbound egress window over the SEP->SMC region,
  * waits for SMC fuse-sense-done, then for the image cookie in SMC SRAM,
  * re-vectors all four SMC cores to the image entry and pulses their reset,
  * and only then trades scratch tokens with the now-running SMC.

The cookie and entry are contract values shared by both halves
(smc_sep_xbar_protocol.h) and are checked here against the built SMC image, so a
relink that moves the entry fails loudly instead of hanging in bring-up.
"""

from __future__ import annotations

import os
import re

import cocotb

from seq_lib.sep_fw_common import load_syms
from seq_lib.sep_terminal_loop_seq import SepTerminalLoopSeq

# From hw/sys/sep/dv/fw/tests/common/smc_sep_xbar_protocol.h.
XBAR_SMC_ENTRY = 0xC006_01B2
XBAR_SMC_IMAGE_FIRST_WORD = 0x4101_4081

SMC_ENTRY_SYM = "smc_sep_xbar_entry"


class SmuSepSmcXbarSeq(SepTerminalLoopSeq):
    NAME = "sep_smc_xbar"
    PASS_SYM = "smc_sep_xbar_pass_loop"
    FAIL_SYMS = {"xbar": "smc_sep_xbar_fail_loop"}
    SYM_DEFAULT = "sep_smc_xbar.tcm.sym"
    EVIDENCE = ("SEP_REAL_FW_SMC_XBAR_OK", "SEP_DRIVEN_SMC_BRINGUP_OK")

    def _check_smc_image_contract(self) -> None:
        """Reconcile the SMC half against the constants the SEP half compiles in.

        Bring-up polls SRAM[0] for the cookie and then re-vectors the cores to a
        fixed entry. If either drifts, the SEP simply never gets past its poll,
        which is indistinguishable from a dead SMC -- so check it up front.
        """
        sym_path = str(cocotb.plusargs.get("smc_sym", "smc_sep_xbar.sram.sym"))
        syms = load_syms(sym_path)
        if not syms:
            self.log.warning("no SMC symbol table at %s -- entry reconciliation skipped", sym_path)
            return
        entry = next((a for a, n in syms if n == SMC_ENTRY_SYM), None)
        assert entry is not None, f"{SMC_ENTRY_SYM} not in the SMC image symbol table {sym_path}"
        assert entry == XBAR_SMC_ENTRY, (
            f"SMC image entry 0x{entry:08x} != the protocol's XBAR_SMC_ENTRY "
            f"0x{XBAR_SMC_ENTRY:08x}; SEP bring-up would re-vector the cores to "
            "the wrong address"
        )

        preload = str(cocotb.plusargs.get("smc_scratch_ram_hex", ""))
        if preload and os.path.exists(preload):
            with open(preload, "r", encoding="ascii", errors="replace") as stream:
                first = next(
                    (ln.strip() for ln in stream if ln.strip() and not ln.strip().startswith("@")),
                    "",
                )
            m = re.fullmatch(r"[0-9a-fA-F]+", first)
            assert m, f"unreadable first word in {preload!r}: {first!r}"
            # 72-bit ECC word; the cookie is the low 32 data bits.
            got = int(first, 16) & 0xFFFF_FFFF
            assert got == XBAR_SMC_IMAGE_FIRST_WORD, (
                f"SMC SRAM preload first word 0x{got:08x} != cookie "
                f"0x{XBAR_SMC_IMAGE_FIRST_WORD:08x}; SEP bring-up would poll forever"
            )
            self.log.info("SMC image contract OK: entry=0x%08x cookie=0x%08x", entry, got)

    async def run(self) -> None:
        self._check_smc_image_contract()
        await super().run()
