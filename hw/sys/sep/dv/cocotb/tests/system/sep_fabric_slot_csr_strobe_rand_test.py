# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Byte strobes, access sizes, back-pressure and locks on every fabric slot.

RANDOMIZED. Covers all 96 slots of the System-block fabric banks on the
CPU-LSU AXI master: 16 alias-remap regions, 16 AP and 16 STEE output-remap
regions, 32 outbound and 16 inbound filter entries. Each slot is its own
register block behind its own AXI-Lite port. The expected value of every
register comes from the generated IP-XACT field metadata (access, reset,
write-once-set); see ``seq_lib.sep_fabric_slot_csr_strobe_seq``.

Checkers:
  CHK-SLOT-RESET   every register reads its RDL reset value, as a 64-bit
                   access and as one 32-bit word.
  CHK-SLOT-STROBE  per register, one 64-bit write, one write per byte lane and
                   two 16/32-bit writes, in seeded order with seeded data and
                   seeded fill on every inactive lane. Each write lands on
                   exactly its enabled lanes of writable fields; read-only and
                   reserved bits keep their RDL value; a filter START/END pair
                   in one granule reads back widened to it. The fill is
                   counted on the s_axi pins and at the W port of each slot
                   register block (tb_top.sv fabric_slot_w_*): the two counts
                   match, and every slot's block saw fill.
  CHK-SLOT-PIPE    per slot, a write and a read issued together on s_axi: once
                   with BREADY and RREADY held, once with W ahead of AW. On the
                   s_axi pins, both are accepted and unanswered in one cycle;
                   the held B and R wait on READY; W leads AW. Both answer
                   OKAY, the read returns the half the write did not strobe,
                   and the write lands. Overlap at the slot's own port is not
                   claimed: the AXI-Lite demux in front of each slot holds one
                   transaction per direction and forwards W only after its AW.
  CHK-SLOT-LOCK    every filter entry is locked by a write that strobes
                   FILTER_CONFIG.locked; then seeded writes to FILTER_CONFIG,
                   START_ADDR and END_ADDR, each chosen to move the entry if it
                   were taken, and a write of 0 to the lock bit, leave the entry
                   unchanged. Each of those writes completes DECERR
                   (filter_ctrl.rdl locked).
  CHK-SLOT-FINAL   every register of every slot still holds its model value.

no_cpu / +skip_fuse_sense.
"""

from __future__ import annotations

import pyuvm
from sep_base_test import sep_base_test
from seq_lib.sep_fabric_slot_csr_strobe_seq import SepFabricSlotCsrStrobe


@pyuvm.test()
class sep_fabric_slot_csr_strobe_rand_test(sep_base_test):
    """Strobe, size, pipeline and lock sweep over every fabric remap/filter slot.

    RANDOMIZED (SepSeededRng): slot and register order, access offsets and
    sizes, write data, inactive-lane fill, response-channel hold lengths and
    the W-ahead-of-AW gap. The strobe, lock and pipeline contracts are fixed.
    """

    required_evidence = (
        "CHK-SLOT-RESET",
        "CHK-SLOT-STROBE",
        "CHK-SLOT-PIPE",
        "CHK-SLOT-LOCK",
        "CHK-SLOT-FINAL",
    )

    async def run_scenario(self) -> None:
        seed = self.random_seed()
        await self.bring_up_no_cpu()
        sweep = SepFabricSlotCsrStrobe(self, seed)
        n_regs = len(sweep.regs)
        self.logger.info(
            "slot sweep seed=%d: %d slots, %d registers",
            seed,
            len(sweep.slots),
            n_regs,
        )
        try:
            await self._run(sweep, n_regs)
        finally:
            sweep.restore_w_channel()

    def _slot_fill_verdict(self, sweep: SepFabricSlotCsrStrobe, st) -> None:
        """The fill seen on s_axi reaches the W port of every slot register block."""
        b_beats, b_fill, b_seen = sweep.slot_probe_before
        a_beats, a_fill, a_seen = sweep.slot_probe_after
        assert sweep.slot_probe_width == len(sweep.slots), (
            f"CHK-SLOT-STROBE FAIL: fabric_slot_w_fill_seen_o is {sweep.slot_probe_width} "
            f"bits, the register export has {len(sweep.slots)} slots"
        )
        assert b_seen == 0, (
            f"CHK-SLOT-STROBE FAIL: slot fill vector 0x{b_seen:x} before the sweep; "
            "the per-slot result would not be the sweep's own"
        )
        assert a_beats - b_beats == st["w_beats"], (
            f"CHK-SLOT-STROBE FAIL: {a_beats - b_beats} W beats at the slot ports, "
            f"{st['w_beats']} on s_axi"
        )
        assert a_fill - b_fill == st["w_beats_inactive_data"], (
            f"CHK-SLOT-STROBE FAIL: {a_fill - b_fill} W beats with inactive-lane data at "
            f"the slot ports, {st['w_beats_inactive_data']} on s_axi"
        )
        missing = sweep.slots_without_fill()
        assert not missing, (
            f"CHK-SLOT-STROBE FAIL: {len(missing)} slot register block(s) saw no "
            "inactive-lane data: " + ", ".join(missing[:8])
        )

    def _verdict(self, sweep: SepFabricSlotCsrStrobe, chk: str) -> None:
        bad = [m for m in sweep.mismatches if m.startswith(chk)]
        assert not bad, f"{chk} FAIL: {len(bad)} mismatch(es); first: " + "; ".join(bad[:4])

    async def _run(self, sweep: SepFabricSlotCsrStrobe, n_regs: int) -> None:
        st = sweep.stats

        await sweep.reset_walk()
        self._verdict(sweep, "CHK-SLOT-RESET")
        self.logger.info(
            "CHK-SLOT-RESET PASS: %d reads over %d registers returned their RDL reset",
            st["CHK-SLOT-RESET_reads"],
            n_regs,
        )

        await sweep.strobe_sweep()
        self._verdict(sweep, "CHK-SLOT-STROBE")
        assert st["strobe_writes"] == 11 * n_regs, (
            f"CHK-SLOT-STROBE FAIL: {st['strobe_writes']} writes, planned {11 * n_regs}"
        )
        assert st["strobe_writes_moved"] and st["inactive_fill_writes"], (
            "CHK-SLOT-STROBE FAIL: no write moved a register, or no inactive-lane fill "
            "differed from the register; the sweep proved nothing"
        )
        assert st["w_beats_inactive_data"], (
            f"CHK-SLOT-STROBE FAIL: none of {st['w_beats']} W beats on s_axi carried data "
            "on an inactive lane; the fill never reached the bus"
        )
        self._slot_fill_verdict(sweep, st)
        b_beats, b_fill, b_seen = sweep.slot_probe_before
        a_beats, a_fill, a_seen = sweep.slot_probe_after
        self.logger.info(
            "CHK-SLOT-STROBE PASS: %d strobed writes (%d moved the register, %d carried "
            "inactive-lane fill that differed from it); W beats with inactive-lane data: "
            "%d of %d on s_axi, %d of %d at the slot register-block ports; fill seen at "
            "%d of %d slot ports (vector 0x%024x, 0x%024x before); %d reads matched the "
            "RDL model",
            st["strobe_writes"],
            st["strobe_writes_moved"],
            st["inactive_fill_writes"],
            st["w_beats_inactive_data"],
            st["w_beats"],
            a_fill - b_fill,
            a_beats - b_beats,
            bin(a_seen).count("1"),
            len(sweep.slots),
            a_seen,
            b_seen,
            st["CHK-SLOT-STROBE_reads"],
        )

        await sweep.pipeline_sweep()
        self._verdict(sweep, "CHK-SLOT-PIPE")
        assert st["pairs"] == 2 * len(sweep.slots), (
            f"CHK-SLOT-PIPE FAIL: {st['pairs']} pairs, planned {2 * len(sweep.slots)}"
        )
        obs = sweep.pipe_obs
        hold = [o for o in obs if o["kind"] == "hold"]
        lead = [o for o in obs if o["kind"] == "w_first"]
        assert len(hold) == len(lead) == len(sweep.slots), (
            f"CHK-SLOT-PIPE FAIL: {len(hold)} hold and {len(lead)} W-first pairs, "
            f"planned {len(sweep.slots)} each"
        )

        def span(vals: list[int]) -> str:
            return f"{min(vals)}..{max(vals)}"

        self.logger.info(
            "CHK-SLOT-PIPE PASS: %d write/read pairs over %d slots answered OKAY with the "
            "model value; on s_axi both were accepted and unanswered for %s cycles; "
            "hold pairs: B waited %s and R waited %s cycles on READY; W-first pairs: "
            "WVALID led AWVALID by %s cycles",
            st["pairs"],
            len(sweep.slots),
            span([o["overlap"] for o in obs]),
            span([o["b_wait"] for o in hold]),
            span([o["r_wait"] for o in hold]),
            span([o["first_aw"] - o["first_w"] for o in lead]),
        )

        await sweep.lock_sweep()
        self._verdict(sweep, "CHK-SLOT-LOCK")
        n_filters = sum(1 for s in sweep.slots if s.is_filter)
        locked = sum(1 for s in sweep.slots if s.locked)
        assert locked == n_filters, f"CHK-SLOT-LOCK FAIL: {locked} of {n_filters} entries locked"
        codes = sweep.lock_codes()
        self.logger.info(
            "CHK-SLOT-LOCK locked-entry write responses (each graded DECERR): %s",
            ", ".join(f"{k}={v}" for k, v in sorted(codes.items())),
        )
        self.logger.info(
            "CHK-SLOT-LOCK PASS: %d filter entries locked; %d writes to locked entries, "
            "each one that would move the entry, left every entry unchanged",
            locked,
            st["locked_writes"],
        )

        await sweep.final_walk()
        self._verdict(sweep, "CHK-SLOT-FINAL")
        assert not sweep.mismatches, "unattributed mismatches: " + "; ".join(sweep.mismatches[:4])
        self.logger.info(
            "CHK-SLOT-FINAL PASS: %d registers across %d slots hold their model value",
            n_regs,
            len(sweep.slots),
        )
