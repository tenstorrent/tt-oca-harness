# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""KPV scrambler: the stored word and the address mapping are both transformed.

no_cpu / +skip_fuse_sense / +km_rom_hex=km_rom_kpv_scrambler.parhex. RANDCFG.

The key/policy vault hangs off the Key Manager's own crossbar, whose single
slave port is wired to the KM CPU, so no host master can reach it and a
dedicated ROM drives it. It cannot be ``rom_main`` either: that image
programs the scrambler key, enables it and takes the sticky lock during boot,
so the enable toggle this test needs is already gone before the host can act.

No hierarchical peek is needed. The ROM writes plaintext with scrambling on,
disables it, and reads the stored words back through the disabled path, a
legitimate frontdoor. That the disabled path addresses the register file
logically and passes data through unmodified is the observation aperture this
test relies on, not a contract it grades: no non-zero word is written while
disabled, so a self-consistent non-identity disabled mapping also passes.

Checkers:
  CHK-COUNT  after three writes through the enabled scrambler, EXACTLY three
             words in the whole 1024-word file differ from the zeroed setup
  CHK-DATA   each stored word differs from the plaintext that produced it
  CHK-ADDR   the stored words do not all sit at their own logical index: the
             address mapping is tweaked, not identity
  CHK-KEYED  the same plaintext at the same logical index under a DIFFERENT key
             stores a different word, so the transform is keyed rather than a
             fixed obfuscation
  CHK-RT     with the scrambler re-enabled, the logical index reads back the
             exact plaintext
  CHK-KEYRD  before the lock, the key register reads back the key that was
             written
  CHK-LOCKRT the round-trip still recovers the plaintext after the lock, so the
             hardware kept the key it was using
  CHK-SWWEL  control first: before the lock, with ENABLE=1, a write of a third
             key (~key B) changes the round-trip away from the plaintext.
             Then, after the lock, a write of that same third key leaves the
             key the hardware uses unchanged (the round-trip still returns
             the plaintext), and a write clearing ENABLE is refused (ENABLE
             still reads 1)

Anti-vacuity. "Exactly three" is the load-bearing quantifier, not "at least
one": a write that never landed gives zero differences and fails, a read path
stuck at zero gives zero and fails, and a register file left dirty gives more
than three and fails. A bare "the stored word differs from the plaintext" check
would pass in the first two cases, and under a simulator that defaults
uninitialised memory to zero it would also pass on a file that was never
written. The round-trip is a required conjunct, so a scrambler that destroys
data cannot pass by looking scrambled.

CHK-ADDR asserts "not all of them" rather than "each of them". The
address transform is a bijection on the 1024 indices and a bijection may have
fixed points, so a single index mapping to itself is legal; an identity mapping
across three seeded indices is not.

The architecture document requires only that a locked key cannot be modified.
CHK-SWWEL grades that on the key the datapath uses. Every other key write in
the test is made while ENABLE=0, so without the unlocked control an unchanged
post-lock round-trip would also come from hardware that takes its key copy only
while disabled, with no lock at all. The control writes the same key with
ENABLE=1 before the lock and requires the round-trip to change, so the
post-lock result is evidence of the lock. The write lock on the
KPV_SCRAMBLER_KEY register itself is not claimed: the hardware keeps its own
copy of the key it uses, and km_kpv.rdl does not specify what the locked
register reads, so no frontdoor observation separates a refused register write
from a landed one. For the same reason the ROM does not read the key register
after the lock. CHK-LOCKRT shows the hardware kept the key it was using.
"""

from __future__ import annotations

import pyuvm
from env.sep_spec_tables import kpv_scrambler_ctrl_mask
from sep_base_test import sep_base_test
from seq_lib.sep_km_kpv_scrambler_seq import (
    KPV_N_WORDS,
    N_TEST_INDICES,
    SepKpvScrambler,
    SepKpvScramblerCfg,
    plaintext_for,
)
from seq_lib.sep_km_mem_smoke_seq import sep_km_release_seq


@pyuvm.test()
class sep_km_kpv_scrambler_test(sep_base_test):
    """The KPV scrambler transforms data and address, depends on its key, and locks the key."""

    async def run_scenario(self) -> None:
        cfg = SepKpvScramblerCfg(self.random_seed())
        self.logger.info("kpv scrambler: %s", cfg.summary())

        await self.bring_up_no_cpu()
        await self.start_seq(sep_km_release_seq("km_kpv_scrambler_release"))

        kpv = SepKpvScrambler(self)
        await kpv.post_cfg(cfg)
        rep = await kpv.collect()

        # --- CHK-COUNT --------------------------------------------------------
        # The collector raises on a wrong count before it drains the pair list a
        # wrong count would flood; this assertion carries the CHK-COUNT tag.
        assert rep.count == N_TEST_INDICES, (
            f"CHK-COUNT FAIL: {rep.count} of the 1024 key-entry words differ from the "
            f"zeroed setup, expected exactly {N_TEST_INDICES}. Fewer means a write "
            "never landed or the read path is stuck; more means the file was left "
            f"dirty. Stored: {[(hex(i), hex(v)) for i, v in rep.pairs]}"
        )
        self.logger.info(
            "CHK-COUNT PASS: exactly %d words changed across the whole key-entry file",
            rep.count,
        )

        # --- CHK-DATA ---------------------------------------------------------
        # Each stored word must differ from every plaintext written this pass,
        # not merely from the one at its own logical index: the address tweak
        # means the physical index does not say which plaintext landed there.
        plaintexts = {plaintext_for(idx) for idx in cfg.indices}
        for index, value in rep.pairs:
            assert value not in plaintexts, (
                f"CHK-DATA FAIL: physical index {index} holds 0x{value:08x}, which is "
                "one of the plaintexts written -- the data was stored unmodified"
            )
        self.logger.info(
            "CHK-DATA PASS: no stored word equals any plaintext written (%s)",
            [hex(p) for p in sorted(plaintexts)],
        )

        # --- CHK-ADDR ---------------------------------------------------------
        stored_indices = sorted(index for index, _ in rep.pairs)
        logical = sorted(cfg.indices)
        assert stored_indices != logical, (
            "CHK-ADDR FAIL: the set of physical indices written is identical to the "
            f"set of logical indices asked for ({logical}), so the address tweak "
            "moved nothing. Note this compares the two as SETS: a tweak that merely "
            "permuted these three indices among themselves would also land here"
        )
        self.logger.info("CHK-ADDR PASS: logical %s stored at physical %s", logical, stored_indices)

        # --- CHK-KEYED --------------------------------------------------------
        key_b_index, key_b_value = rep.key_b_pair
        # The ROM's "nothing stored" sentinel is -1, written with a 32-bit store,
        # so it arrives here as 0xFFFFFFFF. Range-check it: a signed >= 0 test
        # would never fire and would let a second-key pass whose write never
        # landed be reported as evidence that the transform is keyed.
        assert key_b_index < KPV_N_WORDS, (
            "CHK-KEYED FAIL: the second-key pass stored nothing anywhere in the file "
            f"(index sentinel 0x{key_b_index:08x})"
        )
        assert key_b_value != 0, (
            f"CHK-KEYED FAIL: the second-key pass reported physical index {key_b_index} "
            "holding zero, which is the value the setup fill left everywhere"
        )
        first_logical = cfg.indices[0]
        first_words = {v for _, v in rep.pairs}
        assert key_b_value not in first_words, (
            f"CHK-KEYED FAIL: the same plaintext at logical index {first_logical} "
            f"stored word 0x{key_b_value:08x} under BOTH keys "
            f"(0x{cfg.key_a:08x} and 0x{cfg.key_b:08x}) -- the data path ignores the key"
        )
        self.logger.info(
            "CHK-KEYED PASS: logical %d key-B word 0x%08x (physical %d) "
            "is not among the %d first-key stored words",
            first_logical,
            key_b_value,
            key_b_index,
            len(first_words),
        )

        # --- CHK-RT -----------------------------------------------------------
        expected_pt = plaintext_for(first_logical)
        assert rep.round_trip == expected_pt, (
            f"CHK-RT FAIL: logical index {first_logical} read back 0x{rep.round_trip:08x} "
            f"through the enabled scrambler, expected the plaintext 0x{expected_pt:08x}"
        )
        self.logger.info(
            "CHK-RT PASS: logical %d round-trips to 0x%08x", first_logical, expected_pt
        )

        # --- CHK-KEYRD / CHK-LOCKRT -------------------------------------------
        assert rep.key_unlocked == cfg.key_b, (
            f"CHK-KEYRD FAIL: before the lock, KPV_SCRAMBLER_KEY read back "
            f"0x{rep.key_unlocked:08x}, expected the written key 0x{cfg.key_b:08x}. "
            "Without this a write-only register would make CHK-SWWEL look locked"
        )
        self.logger.info(
            "CHK-KEYRD PASS: the key register reads back 0x%08x while unlocked", cfg.key_b
        )

        assert rep.post_lock_round_trip == expected_pt, (
            f"CHK-LOCKRT FAIL: after the lock, logical index {first_logical} read back "
            f"0x{rep.post_lock_round_trip:08x}, expected 0x{expected_pt:08x} -- the "
            "hardware did not keep the key it was using"
        )
        self.logger.info(
            "CHK-LOCKRT PASS: the round-trip still recovers the plaintext after the lock"
        )

        # --- CHK-SWWEL --------------------------------------------------------
        # Control: before the lock, with ENABLE=1, the ROM writes ~key B and
        # reads the first logical index. That word must not be the plaintext,
        # so a key write made while enabled is shown to reach the datapath.
        # Without it the post-lock compare below cannot fail on hardware that
        # copies the key only while ENABLE=0.
        rekey = (~cfg.key_b) & 0xFFFF_FFFF
        assert rep.rekey_round_trip != expected_pt, (
            f"CHK-SWWEL FAIL: control: before the lock, with ENABLE=1, writing key "
            f"0x{rekey:08x} left logical index {first_logical} reading the plaintext "
            f"0x{expected_pt:08x} -- a key write made while enabled does not reach the "
            "datapath, so the post-lock key compare could not fail"
        )
        # After the lock, a later key write must not change the key the datapath
        # uses, and an ENABLE-clear must be refused. A lock that froze the key
        # but let ENABLE clear would leave the vault passing plaintext through.
        assert rep.refused_round_trip == expected_pt, (
            f"CHK-SWWEL FAIL: after writing a different key and clearing ENABLE on the "
            f"locked scrambler, logical index {first_logical} read back "
            f"0x{rep.refused_round_trip:08x}, expected 0x{expected_pt:08x} -- one of "
            "the two writes reached the datapath"
        )
        assert rep.ctrl_after_refused & kpv_scrambler_ctrl_mask("ENABLE"), (
            f"CHK-SWWEL FAIL: KPV_SCRAMBLER_CTRL reads 0x{rep.ctrl_after_refused:08x} "
            "after a write clearing ENABLE on the locked scrambler; ENABLE should still "
            "be set"
        )
        self.logger.info(
            "CHK-SWWEL PASS: unlocked control: key 0x%08x written with ENABLE=1 moved "
            "the round-trip to 0x%08x (plaintext 0x%08x); after the lock, the same key "
            "write left the datapath key unchanged (round-trip 0x%08x) and an ENABLE "
            "clear is refused (CTRL=0x%08x); the KEY register lock itself is not "
            "observable frontdoor",
            rekey,
            rep.rekey_round_trip,
            expected_pt,
            rep.refused_round_trip,
            rep.ctrl_after_refused,
        )
