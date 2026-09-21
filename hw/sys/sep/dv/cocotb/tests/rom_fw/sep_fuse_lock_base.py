# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared scenario for the four fuse-lock rows: a 2x2 of lifecycle x device control.

THE FEATURE. ``lock_fuse_secrets()`` writes six read-lock bits into the SET_ONLY
``SEP_EFUSE_MAP_LOCKS`` register and ``check_fuse_secrets_locked()`` reads them
back, printing ``FUSE_SECRETS_LOCKED`` or halting the boot
(``bootrom/prod/src/fuse_lock.c``, called from ``rom_main.c`` between the
demotion decision and the BL1 handoff). The locked fields are ``class_key``, the
two RMA token digests, and the three UIDs. What these four rows establish is that
the lock happens on EVERY boot the ROM completes, whatever lifecycle it is in and
whichever way the secure-boot decision went -- the window in which those fuses
are readable must close before anything else runs.

THE REFERENCE'S CHECK, AND WHY THIS PORT IS STRONGER. The reference test reads
the shadow LOCKS register in ``final_phase`` and raises on four read-lock bits:
CLASS_KEY (15), CHIPLET_UID (23), its SOP_UID (27) and SYS_UID (31). This design
places the same four fields at the same four bit positions, so the port asserts
the reference's four AND the two the reference does not check -- the RMA token
digests at 11 and 13 -- i.e. the ROM's whole ``FUSE_SECRET_READ_LOCK_MASK``. The
reference's *cocotb* half only logs: a missing ``SECURE_BOOT_ENABLED`` pattern
produces ``log.warning`` and the run still passes. Every marker here raises.

THE 2x2, AND WHY EACH CELL IS INDEPENDENTLY WITNESSED. The reference drives both
axes as real fuses (``efuse_lc_state``, ``efuse_sboot_dis``), so this port does
too, through committed OTP preloads rather than a randomised item:

    row                  LC_STATE   SBOOT_DIS   secure_boot_enabled()
    secure_test_dev      TEST_DEV       0       ON  -- the manifest flag decides
    secure_prod          PROD           0       ON  -- the lifecycle enforces
    non_secure_test_dev  TEST_DEV       1       OFF -- device control
    non_secure_prod      PROD           1       OFF -- device control beats PROD

Four tests over one flow is exactly where all four can pass on one arm, so no row
is graded on the shared outcome alone. Values the ROM ITSELF echoes separate
them, and each row forbids every other row's value of each:

  * ``LC_STATE=0x0000000n`` -- ``lifecycle.c`` printing the RAW nibble the sense
    FSM produced, before it decodes it. This is the strongest of the three: it is
    the fuse value, not a name;
  * ``LC=TEST_DEV`` / ``LC=PROD`` -- the decode of that same nibble, required in
    addition and asserted to FOLLOW it. Every other decode this ROM can print,
    PROD_END and the two RMA states included, is forbidden, which is what turns a
    preload that failed to stage into a failure rather than a pass;
  * ``FUSE: SBOOT_DIS: 0`` / ``: 1`` -- ``rom_main.c`` echoing the fuse it read.
    The opposite value is forbidden.

The secure-boot verdict is then the CONSEQUENCE of that pair, and it is graded on
both sides: a secure row requires ``RSA_VERIFY_START``, ``SIG_VALID`` and
``CRYPTO_VALIDATE_OK`` and forbids ``SBOOT_OFF``; a non-secure row requires
``SBOOT_OFF`` and forbids all three crypto markers. ``SBOOT_OFF`` alone would say
only that the ROM REPORTED the decision; forbidding the crypto chain says it
acted on it.

THE LOCK IS THE ROM'S WORK, NOT THE PRELOAD'S. The reference constrains
``efuse_locks == 0``, and so does every row here: :meth:`check_efuse` asserts the
staged image leaves LOCKS and LOCKS_SPARE clear, and the shadow compare that
``sep_base_test`` runs at fuse-sense-done confirms the DUT sensed that same zero.
The post-boot read of the same probe then shows the six bits set. Without the
"before" half the "after" would be satisfied by a preload that arrived locked.

WHY THE LOCK IS GRADED THREE TIMES. ``FUSE_SECRETS_LOCKED`` is already a
read-back -- ``check_fuse_secrets_locked()`` reads the register before printing
it -- but that read and the print are the same statement by the same agent, and
``rom_main.c`` halts when it fails, so on a completed boot the marker is close to
entailed. Two independent observers are required alongside it:

  * BL1, a DIFFERENT agent running after the handoff, reads the same register and
    prints the whole word. ``LOCKS=0x8880A800`` is required literally, which pins
    all six bits -- BL1's own comparison covers only three of them -- and
    ``LOCK_RD_OK`` then says a locked field really reads back 0xBADCAB1E instead
    of raising SLVERR, i.e. the lock is functionally effective and not just a set
    bit;
  * the testbench reads ``efuse_shadow_probe_o``, the shadow register file's own
    output and the same probe the sense-time golden compare uses. It is a READ,
    so it adds no stimulus the silicon would not see.

THE MANIFEST IS NOT MUTATED. The shipped signed image already carries everything
these rows need: ``selector_bits[16]`` set so the lifecycle usage constraint
RUNS, ``life_cycle_states`` permitting TEST_DEV, PROD and PROD_END (0x7) so it
PASSES in either lifecycle, the ``secure_boot`` flag set, and ``SKIP_SHA256``
clear. :meth:`assert_manifest_preconditions` asserts each of those on the loaded
bytes rather than assuming them.

The reference narrows ``life_cycle_states`` to each cell's single bit, because it
regenerates and re-signs the manifest per run. That is REPRODUCIBLE here --
``sep_payload_mutate.reseal`` re-signs a mutated slot with the dev0 key -- and it
is deliberately not done, for two reasons. It would replace the shipped
signature with a test-generated one on all four rows, and the property it would
buy is redundant: a manifest permitting only PROD would be a SECOND witness that
the part is in PROD, and the ROM already prints the first one directly, as the
raw sensed nibble. So the shipped 0x7 stands, the lifecycle usage constraint is
graded NEGATIVELY by forbidding ``LC_USAGE_CONSTRAINT_FAIL`` and its echoes, and
the positive half -- that the check ran at all -- rests on the asserted selector
bit. The consequence to state plainly is that ``life_cycle_states`` contributes
nothing to telling the four cells apart; the two fuse echoes carry all of it.

TWO SCOPE LIMITS, both relative to the reference's own configuration. It sets
``encrypted_payload = 1`` on its two SECURE cells; these rows load the plaintext
signed image and :meth:`assert_manifest_preconditions` asserts that, so the
decryption KDF is not on any of these four paths. The encrypted arm is covered by
this repository's ``*_encrypted_*`` families instead. And the reference's
``selector_bits`` value carries only bit 16 here, so the chiplet_id and
package_id arms of the same usage-constraint block are not reached either.
"""

from __future__ import annotations

import os
from pathlib import Path

import cocotb

from env import sep_manifest_mutate as mm
from env import sep_payload_mutate as pm
from rom_fw import sep_manifest_field_defect as fd
from rom_fw.sep_rom_ot_dma_boot_test import SECURE_FLASH_IMAGE, sep_rom_ot_dma_boot_test

EFUSE_DIR = (Path(__file__).resolve().parents[3] / "tb" / "efuse_preloads"
             / "efuse_configurations")

# lifecycle.h raw codes, and lifecycle.c's decode of each.
LC_RAW_TEST_DEV = 0x0
LC_RAW_PROD = 0x1
LC_MARKERS = {
    LC_RAW_TEST_DEV: "LC=TEST_DEV",
    LC_RAW_PROD: "LC=PROD",
}
# Every decode this ROM can print. A row requires its own and forbids the rest,
# which is what stops a preload that failed to stage from looking like a pass.
ALL_LC_MARKERS = ("LC=TEST_DEV", "LC=PROD", "LC=PROD_END", "LC=RMA_SIP",
                  "LC=RMA_CHIPLET")


def lc_raw_echo(raw: int) -> str:
    """``lifecycle.c`` echoes the RAW sensed LC_STATE before it decodes it.

    Stronger than the decode string, and the reason both are required: the decode
    collapses each RMA range to one name, while this is the nibble the sense FSM
    actually produced. A row requires its own value and forbids the other cell's.
    """
    return f"LC_STATE=0x{raw:08x}"


# lifecycle.c: the arm that refuses an LC_STATE outside the legal set. Not to be
# confused with SEP_MSG_LIFECYCLE_INVALID, which is a status code and never
# reaches the console.
LC_STATE_INVALID = "LC_STATE_INVALID="

# rom_main.c echoes the fuse it sensed, in decimal.
SBOOT_DIS_MARKERS = {0: "FUSE: SBOOT_DIS: 0", 1: "FUSE: SBOOT_DIS: 1"}

# manifest_crypto.c / rsa_verify.c, emitted only on the authenticated path.
CRYPTO_MARKERS = ("RSA_VERIFY_START", "SIG_VALID", "CRYPTO_VALIDATE_OK")
# manifest_load.c, printed when secure_boot_enabled() returned false.
SBOOT_OFF = "SBOOT_OFF"
# manifest_load.c: the hash gate's opt-out. Forbidden on every row, because the
# rows assert SKIP_SHA256 is clear in the loaded image.
SHA_DISABLED = "SHA256_CHECKS_DISABLED"
MANIFEST_HASH_OK = "MANIFEST_HASH_OK"
# manifest_crypto.c verify_payload_hash(): called from BOTH arms of the
# secure-boot branch, so all four cells reach it. Required rather than assumed --
# the function returns silently when payload_hashed_length is 0, so its absence
# would mean the shipped image stopped binding its payload to a digest.
PLD_HASH_OK = "PLD_HASH_OK"
MANIFEST_OK = "MANIFEST_OK"

# fuse_lock.c.
FUSE_SECRETS_LOCKED = "FUSE_SECRETS_LOCKED"
FUSE_SECRETS_NOT_LOCKED = "FUSE_SECRETS_NOT_LOCKED"
# rom_handoff.c: the handoff the lock must precede.
BL1_COPIED = "BL1_COPIED"
BL1_JUMP = "BL1_JUMP="
# Printed by BL1 and by nothing in the ROM, so it is the transfer of control.
BL1_MARKER = "FUSE_CHK"
# BL1's own verification of the ROM's work (dv/fw/tests/bl1_pass_test):
# bl1_verify_fuse_locks() reads the LOCKS register and PRINTS the whole word,
# then bl1_test_locked_field_reads() proves a locked field reads back
# 0xBADCAB1E rather than raising SLVERR. Its own comparison mask is only
# 0x0000A800 -- CLASS_KEY and the two RMA tokens, not the three UIDs -- so
# requiring the printed WORD is what pins all six bits the ROM sets, and it is a
# second agent's read of the same register.
BL1_FUSE_OK = "FUSE_OK"
BL1_LOCK_RD_OK = "LOCK_RD_OK"
BL1_LOCK_FAILURES = ("FAIL:LOCKS", "FUSE_LOCK_VERIFY_FAIL", "LOCK_RD_FAIL",
                     "FAIL:CLASS_KEY=", "BL0S_VERIFY_FAIL")

# Anything that would mean this boot did not complete for the ordinary reason.
BOOT_FAILURE_TOKENS = (
    "MANIFEST_ERR=", "MANIFEST_ALL_FAILED", "MANIFEST_BOOT_FAIL=", "CRYPTO_FAIL=",
    "LC_USAGE_CONSTRAINT_FAIL", "LC_ALLOWED=", "LC_BIT=", "CHIPLET_ID_MISMATCH",
    "PACKAGE_ID_MISMATCH", "MANIFEST_HASH_MISMATCH", "PLD_HASH_FAIL=",
    LC_STATE_INVALID, "VERSION_ROLLBACK",
)

# sep_efuse_map.h read-lock bit positions, which are also the reference
# checker's: CLASS_KEY 15, CHIPLET_UID 23, SIP_UID 27 (its SOP_UID), SYS_UID 31.
REFERENCE_LOCK_BITS = {
    "CLASS_KEY": 15,
    "CHIPLET_UID": 23,
    "SIP_UID": 27,
    "SYS_UID": 31,
}
# The two this ROM also locks and the reference does not check.
EXTRA_LOCK_BITS = {
    "RMA_SIP_TOKEN_DIGEST": 11,
    "RMA_CHIPLET_TOKEN_DIGEST": 13,
}
ALL_LOCK_BITS = {**REFERENCE_LOCK_BITS, **EXTRA_LOCK_BITS}
# fuse_lock.c FUSE_SECRET_READ_LOCK_MASK, re-derived from the bit table above so
# the two cannot drift apart silently.
FUSE_SECRET_READ_LOCK_MASK = 0
for _bit in ALL_LOCK_BITS.values():
    FUSE_SECRET_READ_LOCK_MASK |= 1 << _bit

# LOCKS occupies OTP words 0 and 1; efuse_shadow_probe_o places word i at bits
# 32*i, so the low half of LOCKS is word 0.
_LOCKS_WORD = 0


def bl1_locks_echo() -> str:
    """The LOCKS word BL1 must print, pinned to the ROM's full mask."""
    return f"LOCKS=0x{FUSE_SECRET_READ_LOCK_MASK:08X}"


class sep_fuse_lock_base(sep_rom_ot_dma_boot_test):
    """Boot the signed SPI image under one lifecycle/device-control cell."""

    flash_image = SECURE_FLASH_IMAGE

    # --- subclass contract -------------------------------------------------
    # Committed OTP preload for this cell. Required, including for the TEST_DEV
    # cell an unprogrammed OTP would already sense: without the plusarg
    # dv_sim_prestage.stage() is a no-op, and the image the DUT sensed would rest
    # on the RTL array default rather than on a file the testlist names.
    efuse_preload: Path | None = None
    # Raw LC_STATE this cell must sense, and the SBOOT_DIS value.
    expected_lc_raw: int = LC_RAW_TEST_DEV
    expected_sboot_dis: int = 0

    # --- derived marker sets ------------------------------------------------
    @classmethod
    def _secure_expected(cls) -> bool:
        """``secure_boot_enabled()`` for this cell, with the shipped manifest flag set.

        The fuse wins outright; otherwise the manifest asks for secure boot and
        gets it in every lifecycle. Re-derived here rather than declared per row,
        so a row cannot state an outcome its own fuse values contradict.
        """
        return cls.expected_sboot_dis == 0

    @property
    def required_markers(self) -> tuple[str, ...]:  # type: ignore[override]
        lc = LC_MARKERS[self.expected_lc_raw]
        raw = lc_raw_echo(self.expected_lc_raw)
        sboot = SBOOT_DIS_MARKERS[self.expected_sboot_dis]
        outcome = CRYPTO_MARKERS if self._secure_expected() else (SBOOT_OFF,)
        return (
            sep_rom_ot_dma_boot_test.required_markers
            + (raw, lc, sboot, MANIFEST_HASH_OK, PLD_HASH_OK)
            + outcome
            + (MANIFEST_OK, FUSE_SECRETS_LOCKED, BL1_COPIED, BL1_JUMP, BL1_MARKER,
               bl1_locks_echo(), BL1_FUSE_OK, BL1_LOCK_RD_OK)
        )

    @property
    def forbidden_markers(self) -> tuple[str, ...]:  # type: ignore[override]
        lc = LC_MARKERS[self.expected_lc_raw]
        other_lc = tuple(m for m in ALL_LC_MARKERS if m != lc)
        other_raw = tuple(
            lc_raw_echo(r) for r in (LC_RAW_TEST_DEV, LC_RAW_PROD)
            if r != self.expected_lc_raw
        )
        other_sboot = (SBOOT_DIS_MARKERS[1 - self.expected_sboot_dis],)
        outcome = (SBOOT_OFF,) if self._secure_expected() else CRYPTO_MARKERS
        return (
            sep_rom_ot_dma_boot_test.forbidden_markers
            + other_lc + other_raw + other_sboot + outcome
            + (FUSE_SECRETS_NOT_LOCKED, SHA_DISABLED) + BL1_LOCK_FAILURES
            + BOOT_FAILURE_TOKENS
        )

    # --- stimulus guards ----------------------------------------------------
    def build_efuse_image(self):
        assert self.efuse_preload is not None and os.path.isfile(self.efuse_preload), (
            f"eFuse preload missing: {self.efuse_preload}. Every cell names one, so "
            f"the t=0 staged image and this test's golden come from one file"
        )
        image = self.select_efuse_image(default_preload=self.efuse_preload)
        self.check_efuse(image)
        return image

    def check_efuse(self, image) -> None:
        """Both axes of the cell, read off the image the DUT will sense.

        ``select_efuse_image()`` falls back to a seeded random image when the
        plusarg is absent, and a random image would land on a lifecycle this row
        does not grade. Asserting both values here is what makes the testlist's
        ``+sep_efuse_preload`` load-bearing rather than decorative.
        """
        lc = image.lc_raw()
        sboot_dis = image.field_int("SBOOT_DIS") & 0x1
        assert lc == self.expected_lc_raw, (
            f"LC_STATE raw is 0x{lc:x}, expected 0x{self.expected_lc_raw:x}: this "
            f"cell's whole identity is its lifecycle, and the testlist must pass "
            f"+sep_efuse_preload={self.efuse_preload}"
        )
        assert sboot_dis == self.expected_sboot_dis, (
            f"SBOOT_DIS is {sboot_dis}, expected {self.expected_sboot_dis}: the "
            f"device-control axis of this cell did not stage"
        )
        # The reference constrains efuse_locks == 0, and so must this: a preload
        # that already carried the read locks would satisfy the post-boot read
        # without the ROM having done anything.
        for field in ("LOCKS", "LOCKS_SPARE"):
            got = image.field_int(field)
            assert got == 0, (
                f"{field} is 0x{got:x} in the staged image, expected 0: the "
                f"post-boot lock check would pass on a preload that arrived "
                f"locked, proving nothing about lock_fuse_secrets()"
            )
        # Version floors and revocations would refuse the signed image for a
        # reason that has nothing to do with this cell.
        fd.assert_clean_key_fuses(image)
        self.logger.info(
            "CHK-FUSE-LOCK-STIMULUS: LC raw=0x%x (%s), SBOOT_DIS=%d, LOCKS=0 and "
            "LOCKS_SPARE=0, so secure_boot_enabled() must return %s",
            lc, LC_MARKERS[self.expected_lc_raw], sboot_dis,
            self._secure_expected(),
        )

    def mutate_flash_image(self, buf: bytearray) -> bytearray:
        self.assert_manifest_preconditions(buf)
        return buf

    def assert_manifest_preconditions(self, buf: bytearray) -> None:
        """Every manifest property these rows rely on, asserted on the loaded bytes.

        Nothing is changed. The point is that the cell's outcome is attributable
        to the two fuses and to nothing in the image: if the shipped manifest ever
        stops asking for secure boot, or stops permitting one of the two
        lifecycles, the affected rows must fail here rather than quietly become
        a different experiment.
        """
        for slot in ("primary", "backup"):
            mm.verify_layout(buf, slot)
            mm.verify_usage_constraints_layout(buf, slot)
            sel = mm.selector_bits(buf, slot)
            assert sel & (1 << mm.SELECTOR_BIT_LIFE_CYCLE_STATES), (
                f"{slot} selector_bits is 0x{sel:x} and leaves bit "
                f"{mm.SELECTOR_BIT_LIFE_CYCLE_STATES} clear, so the ROM skips the "
                f"lifecycle usage constraint entirely and forbidding "
                f"LC_USAGE_CONSTRAINT_FAIL says nothing"
            )
            allowed = mm.life_cycle_states(buf, slot)
            # lifecycle.c lc_state_to_manifest_bit(): TEST_DEV -> 0, PROD -> 1.
            live_bit = 0 if self.expected_lc_raw == LC_RAW_TEST_DEV else 1
            assert allowed & (1 << live_bit), (
                f"{slot} life_cycle_states is 0x{allowed:x} and does not permit "
                f"bit {live_bit} (the lifecycle this cell senses), so the slot "
                f"would be refused by the usage constraint instead of booting"
            )
            flags = mm.get_flag_args(buf, slot)
            assert (flags >> mm.FLAG_ARGS_BIT_SECURE_BOOT) & 1, (
                f"{slot} flag_args is 0x{flags:08x} and asks for NON-secure boot; "
                f"the two secure cells would then be indistinguishable from the "
                f"non-secure ones in TEST_DEV"
            )
            assert not (flags >> mm.FLAG_ARGS_BIT_SKIP_SHA256) & 1, (
                f"{slot} flag_args is 0x{flags:08x} and sets SKIP_SHA256; "
                f"MANIFEST_HASH_OK would be absent in TEST_DEV and "
                f"{SHA_DISABLED} is forbidden"
            )
            assert not pm.is_encrypted(buf, slot), (
                f"{slot} payload carries encrypted_payload = 1; manifest_load.c "
                f"refuses an encrypted payload outright when secure boot is off, "
                f"so the two non-secure cells could not boot"
            )
            self.logger.info(
                "CHK-MANIFEST-PRECONDITION: %s selector_bits=0x%x "
                "life_cycle_states=0x%x flag_args=0x%08x, plaintext payload, "
                "unmutated -- %s",
                slot, sel, allowed, flags, mm.describe(buf, slot),
            )

    # --- outcome ------------------------------------------------------------
    def check_transport(self, console: list[str], flash) -> None:
        super().check_transport(console, flash)
        self._check_decision_order(console)
        self._check_locks_register()

    def _check_decision_order(self, console: list[str]) -> None:
        """The two echoes precede the decision, and the lock sits between accept and handoff."""
        def index_of(marker: str) -> int:
            for i, line in enumerate(console):
                if marker in line:
                    return i
            return -1

        lc = LC_MARKERS[self.expected_lc_raw]
        raw = lc_raw_echo(self.expected_lc_raw)
        sboot = SBOOT_DIS_MARKERS[self.expected_sboot_dis]
        i_raw = index_of(raw)
        i_lc = index_of(lc)
        i_sboot = index_of(sboot)
        decision = CRYPTO_MARKERS[0] if self._secure_expected() else SBOOT_OFF
        i_decision = index_of(decision)
        i_ok = index_of(MANIFEST_OK)
        i_lock = index_of(FUSE_SECRETS_LOCKED)
        i_jump = index_of(BL1_JUMP)
        i_bl1 = index_of(BL1_MARKER)

        # CHK-DECISION-ORDER: both sensed values were echoed BEFORE the
        # secure-boot verdict they determine. Presence in any order would also be
        # satisfied by a ROM that decided first and reported the fuses afterwards,
        # which would make the cell's identity unfalsifiable.
        assert 0 <= i_raw < i_lc, (
            f"{raw}@{i_raw} does not precede {lc}@{i_lc}: lifecycle.c echoes the "
            f"raw sensed nibble before it decodes it, so this pair being out of "
            f"order means one of them did not come from that decode. "
            f"Console: {console}"
        )
        assert 0 <= i_lc < i_decision and 0 <= i_sboot < i_decision, (
            f"{lc}@{i_lc} and {sboot}@{i_sboot} do not both precede "
            f"{decision}@{i_decision}: the secure-boot verdict is not downstream "
            f"of the fuses this cell stages. Console: {console}"
        )
        # CHK-LOCK-ORDER: rom_main.c locks the secrets after the manifest is
        # accepted and before the handoff, and the boot then really reaches BL1.
        # A lock observed after the jump would not have closed the window.
        assert 0 <= i_ok < i_lock < i_jump < i_bl1, (
            f"lock sequence is out of order: {MANIFEST_OK}@{i_ok} -> "
            f"{FUSE_SECRETS_LOCKED}@{i_lock} -> {BL1_JUMP}@{i_jump} -> "
            f"{BL1_MARKER}@{i_bl1}. Console: {console}"
        )
        self.logger.info(
            "CHK-DECISION-ORDER: %s@%d -> %s@%d, and %s@%d -> %s@%d; %s@%d -> "
            "%s@%d -> %s@%d -> %s@%d",
            raw, i_raw, lc, i_lc, sboot, i_sboot, decision, i_decision,
            MANIFEST_OK, i_ok, FUSE_SECRETS_LOCKED, i_lock, BL1_JUMP, i_jump,
            BL1_MARKER, i_bl1,
        )

    def _check_locks_register(self) -> None:
        """Read the shadow LOCKS word off the DUT and require every secret read-lock set.

        The reference's ``final_phase`` equivalent, on the same probe the
        sense-time golden compare reads. Read-only.
        """
        probe = self.rd(cocotb.top.efuse_shadow_probe_o)
        locks_lo = (probe >> (32 * _LOCKS_WORD)) & 0xFFFF_FFFF
        missing = sorted(name for name, bit in ALL_LOCK_BITS.items()
                         if not (locks_lo & (1 << bit)))
        assert not missing, (
            f"LOCKS[31:0] read back 0x{locks_lo:08x} from the shadow register "
            f"file; the read-lock bits for {', '.join(missing)} are CLEAR, so "
            f"lock_fuse_secrets() did not close the window on those secrets "
            f"(expected mask 0x{FUSE_SECRET_READ_LOCK_MASK:08x})"
        )
        assert locks_lo & FUSE_SECRET_READ_LOCK_MASK == FUSE_SECRET_READ_LOCK_MASK, (
            f"LOCKS[31:0] = 0x{locks_lo:08x} does not cover the ROM's whole "
            f"FUSE_SECRET_READ_LOCK_MASK 0x{FUSE_SECRET_READ_LOCK_MASK:08x}"
        )
        self.logger.info(
            "CHK-FUSE-LOCK-REGISTER: LOCKS[31:0]=0x%08x, read locks set for %s "
            "(the reference's four plus %s)",
            locks_lo, ", ".join(sorted(ALL_LOCK_BITS)),
            ", ".join(sorted(EXTRA_LOCK_BITS)),
        )
