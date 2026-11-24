# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Boot ROM gate ledger on a normal boot: four stamps, then the self-check in its [S29] place.

rom.adoc, Pre-Hand-off Self-Check (Gate Ledger) and Release and Jump ([S29]):

* "Every manifest slot attempt ([S23]) starts the ledger again ... MANIFEST, CRYPTO and HASH
  are stamped inside the attempt; FUSELOCK is stamped after the slot loop, when [S26] has
  confirmed the locks."
* SEP-ROM-HOFF-040: "At [S29], after the BL1 copy and before the `EXEC_IMAGE` and
  `STARTING_BL1` reports and the PMP release, the ROM shall require
  `gate_ok == BOOT_GATE_EXPECT` *and* `gate_inv == ~BOOT_GATE_EXPECT` (`0xFFFF_FFF0`)."
* SEP-ROM-HOFF-050: "The checks run in this order: the ledger pair of SEP-ROM-HOFF-040, the
  manifest locus twice, the lock state twice — five checks."
* Item 2 of Release and Jump: "Only when it passes does the ROM report `EXEC_IMAGE` and then
  `STARTING_BL1` with the entry address".
* SEP-ROM-HOFF-060: "Only after the self-check passes shall the ROM release the PMP execution
  fence for the region BL1 was loaded into".

The boot takes the SMC-SRAM manifest path with no fault injected. Times are retirement times
from the trace: the return from the BL1 DMA copy, the first and last self-check retirement,
the EXEC_IMAGE and STARTING_BL1 status stores (located in rom_handoff_bl1 of the loaded image)
and the first PMP CSR write after the cold rule set.

Checks: CHK-STAMP-<GATE> (both stores of each gate retired after the attempt's reset),
CHK-LEDGER-READBACK (gate_ok and gate_inv hold 0xF and 0xFFFF_FFF0 in DCCM when the
self-check starts; BL1 reuses that memory later),
CHK-SELFCHECK-RAN (each of the five checks, both tally compares and the return retired, in
table order), CHK-SELFCHECK-ORDER (copy return < self-check < EXEC_IMAGE < STARTING_BL1 <
release), CHK-REACHED-BL1 (PASS verdict and the first post-mret retirement outside the ROM).
"""

from __future__ import annotations

import pyuvm
from env.sep_rv32_trace_decode import CSR_PMPCFG0, OP_JALR, OP_STORE, opcode
from rom_fw.sep_rom_gate_ledger_base import (
    BOOT_GATE_EXPECT,
    CHECKS,
    GATES,
    ROM_HI,
    SCRATCH_STATUS,
    STATUS_EXEC_IMAGE,
    STATUS_PRESTART_DONE,
    STATUS_STARTING_BL1,
    selfcheck_map,
    sep_rom_gate_ledger_base,
)
from rom_fw.sep_rom_observe_base import ROM_BASE


@pyuvm.test()
class sep_rom_gate_ledger_pass_test(sep_rom_gate_ledger_base):
    def copy_return(self) -> int:
        lo, hi = self.img.func("rom_handoff_bl1")
        sites = [p for p in self.img.calls("sep_dma_copy") if lo <= p < hi]
        assert len(sites) == 1, f"rom_handoff_bl1 calls sep_dma_copy at {sites}"
        return sites[0] + 4

    def status_stores(self, word: int) -> list[int]:
        """PCs in rom_handoff_bl1 that store word to the status scratch register."""
        return [
            i.pc
            for i in self.img.scan("rom_handoff_bl1")
            if opcode(i.word) == OP_STORE and i.mem == SCRATCH_STATUS and i.value == word
        ]

    def extra_watch(self) -> set[int]:
        stores = self.status_stores(STATUS_EXEC_IMAGE) + self.status_stores(STATUS_STARTING_BL1)
        return {self.copy_return(), *stores}

    async def inject(self, obs) -> None:
        # BL1 reuses the DCCM, so the ledger is read when the self-check starts.
        await self.wait_hit(obs, self.img.syms["rom_handoff_selfcheck"])
        self.ledger_at_check = self.ledger_readback()

    def grade(self, obs, chk) -> None:
        img = self.img
        reset_t = self.last_reset_t(obs)
        chk.ctrl("RESET-RETIRED", reset_t >= 0, reset_ps=reset_t)
        for gate in GATES:
            ok, inv = self.stamp_stores(gate)
            chk.ok(
                f"STAMP-{gate.upper()}",
                self.stamps_retired(obs, gate, reset_t),
                gate_ok_store=f"0x{ok:08x}",
                gate_inv_store=f"0x{inv:08x}",
                hits=len(obs.at(ok)) + len(obs.at(inv)),
            )
        ledger = getattr(self, "ledger_at_check", None)
        gate_ok, gate_inv = ledger if ledger is not None else (None, None)
        chk.ok(
            "LEDGER-READBACK",
            gate_ok == BOOT_GATE_EXPECT and gate_inv == (~BOOT_GATE_EXPECT) & 0xFFFF_FFFF,
            gate_ok=f"0x{gate_ok:08x}" if ledger else "unread",
            gate_inv=f"0x{gate_inv:08x}" if ledger else "unread",
        )

        m = selfcheck_map(img)
        sc_lo, sc_hi = img.func("rom_handoff_selfcheck")
        sc = [r for r in obs.hits if sc_lo <= r.pc < sc_hi]
        entries = [img.syms[n] for n in CHECKS]
        order = [r.pc for r in obs.hits if r.pc in entries]
        ret = [r for r in sc if opcode(r.insn) == OP_JALR and r.insn == 0x0000_8067]
        tally = all(obs.at(p) for p in m.tally_branches)
        chk.ok(
            "SELFCHECK-RAN",
            order == entries and tally and bool(ret),
            checks=[img.owner(p) for p in order],
            tally_retired=tally,
            returned=bool(ret),
        )

        copy_t = next((r.t_ps for r in obs.at(self.copy_return())), None)
        first = sc[0].t_ps if sc else None
        last = ret[-1].t_ps if ret else None

        def status_store(word: int) -> int | None:
            hits = [r.t_ps for pc in self.status_stores(word) for r in obs.at(pc)]
            return min(hits) if len(hits) == 1 else None

        exec_t = status_store(STATUS_EXEC_IMAGE)
        start_t = status_store(STATUS_STARTING_BL1)
        prestart = obs.status_t(STATUS_PRESTART_DONE)
        rel = [
            r
            for r in obs.csr_writes(CSR_PMPCFG0, CSR_PMPCFG0 + 0x4F)
            if prestart is not None and r.t_ps > prestart
        ]
        rel_t = rel[0].t_ps if rel else None
        seq = [copy_t, first, last, exec_t, start_t, rel_t]
        chk.ok(
            "SELFCHECK-ORDER",
            None not in seq and seq == sorted(seq) and len(set(seq)) == len(seq),
            copy_return_ps=copy_t,
            selfcheck_first_ps=first,
            selfcheck_return_ps=last,
            exec_image_store_ps=exec_t,
            starting_bl1_store_ps=start_t,
            release_ps=rel_t,
        )
        post = obs.post_mret
        chk.ok(
            "REACHED-BL1",
            obs.verdict_pass() is True and post is not None and not ROM_BASE <= post.pc < ROM_HI,
            verdict_pass=obs.verdict_pass(),
            post_mret_pc=f"0x{post.pc:08x}" if post else "none",
        )
