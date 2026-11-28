# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A fault that jumps over the whole payload-hash acceptance block halts from the self-check.

rom.adoc, Pre-Hand-off Self-Check (Gate Ledger):

* "The accept-then-hand-off decision is hardened against single-glitch fault injection with
  a lockstep gate ledger."
* `BOOT_GATE_HASH` (bit 2, `0x4`: payload hashes verified); "HASH: the
  `oca_check_payload_at()` result is `OCA_OK`."
* SEP-ROM-HOFF-040: "A skipped gate leaves both words wrong".
* SEP-ROM-HOFF-050: "Any shortfall or disagreement is fatal
  (`ROM_ERR_HANDOFF_SELFCHECK_FAILED`, `0xF004`)."

Once DMA_INIT_OK ([S20], after the [S17] self-hash) is on the console, the instruction after
the START_PAYLOAD_VALIDATION status store in rom_manifest_boot becomes a jump to the
instruction after the PAYLOAD_OK print: the payload check, its HASH stamp, the
PAYLOAD_VALIDATED status and the PAYLOAD_OK line are all skipped. The site is found the same
way in any build, so the same fault runs on a ROM without the gate ledger, where the boot
reaches BL1 and this leaf fails; INFO-BOOT-OUTCOME records where the boot went.

Checks: CHK-HASH-BLOCK-SKIPPED (the jump retired after the START_PAYLOAD_VALIDATION status and
the next watched retirement is its target; neither PAYLOAD_VALIDATED nor PAYLOAD_OK appears,
while later console lines and status words do), CHK-HASH-UNSTAMPED (DCCM read-back: HASH
missing from both ledger words), and the halt contract with the halt at the ledger evaluation.
"""

from __future__ import annotations

import pyuvm
from rom_fw.sep_rom_gate_ledger_base import (
    AFTER_S17_LINE,
    GATE_BIT,
    STATUS_PAYLOAD_VALIDATED,
    STATUS_START_PAYLOAD_VALIDATION,
    hash_bypass,
    jump,
    sep_rom_gate_ledger_base,
)


@pyuvm.test()
class sep_rom_gate_hash_bypass_test(sep_rom_gate_ledger_base):
    def extra_watch(self) -> set[int]:
        return set(hash_bypass(self.img))

    async def inject(self, obs) -> None:
        await self.wait_line(obs, AFTER_S17_LINE)
        src, dst = hash_bypass(self.img)
        await self.patch({src: jump(src, dst)})

    def grade(self, obs, chk) -> None:
        src, dst = hash_bypass(self.img)
        jumped = self.retired_as(obs, src, jump(src, dst))
        nxt = [r.pc for r in obs.hits if jumped and r.t_ps > jumped[0].t_ps][:1]
        start_t = obs.status_t(STATUS_START_PAYLOAD_VALIDATION)
        later = [line for t, line in obs.console if jumped and t > jumped[0].t_ps]
        chk.ok(
            "HASH-BLOCK-SKIPPED",
            bool(jumped)
            and start_t is not None
            and nxt == [dst]
            and STATUS_PAYLOAD_VALIDATED not in obs.statuses()
            and obs.line_t("PAYLOAD_OK") is None
            and bool(later),
            source=f"0x{src:08x}",
            target=f"0x{dst:08x}",
            jump_retired=len(jumped),
            next_watched=[f"0x{p:08x}" for p in nxt],
            start_payload_validation_ps=start_t if start_t is not None else -1,
            console_after_jump=len(later),
        )
        post = obs.post_mret
        self.chk.info(
            "BOOT-OUTCOME",
            verdict_pass=obs.verdict_pass(),
            post_mret_pc=f"0x{post.pc:08x}" if post else "none",
            gate_ledger_in_rom=self.img.has("rom_handoff_selfcheck"),
        )
        if self.img.has("g_gate_ok"):
            gate_ok, gate_inv = self.ledger_readback()
            bit = GATE_BIT["hash"]
            chk.ok(
                "HASH-UNSTAMPED",
                not gate_ok & bit and bool(gate_inv & bit),
                gate_ok=f"0x{gate_ok:08x}",
                gate_inv=f"0x{gate_inv:08x}",
            )
        else:
            chk.ok("HASH-UNSTAMPED", False, reason="this ROM has no gate ledger")
        self.grade_halt(obs, chk, kind="eval", check="check_ledger")
