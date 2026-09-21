# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Both slots declare payload fields at the 32-bit limits; the ROM halts.

The procedure drives ``payload_offset`` and ``payload_length`` to values that risk
a 32-bit wrap in BL0's bounds arithmetic and requires BL0 to reject each one
WITHOUT arithmetic wrap, the primary as a slot error and the backup terminally.

THE PROCEDURE CALLS BOTH FIELDS ``uint32``; IN THIS DESIGN THEY ARE 64-BIT.
``manifest.h`` declares ``boot_arguments.payload_offset`` as ``int64_t`` and
``payload_length`` as ``uint64_t``, so a 32-bit sum cannot wrap inside the fields
themselves. The concern the procedure names is nonetheless real and lands one
level down: ``validate_manifest_header`` narrows BOTH to 32 bits, and this is an
RV32 target where ``size_t`` is 32 bits too. The ROM says so itself -- "every
consumer below truncates them to 32 bits ... or a value above 4 GiB silently
becomes a small in-range one and every later bound is computed against the wrong
number" (``bootrom/prod/src/manifest_load.c``). So the four boundary
combinations the procedure lists are exactly the right stimuli; what they prove
is that the ROM's explicit range and wrap guards exist and fire, rather than that
a field overflowed.

THE FOUR COMBINATIONS COLLAPSE ONTO TWO ARMS, which is what this row is built
around. Written as the ROM evaluates them:

  (a) ``payload_offset = 0xFFFFF000, payload_length = 0x2000``  ]
  (b) ``payload_offset = 0xFFFFFFFF, payload_length = 1``       ]-> PAYLOAD_OFF_RANGE
  (c) ``payload_offset = 0x80000000, payload_length = 0x80000000``]
  (d) ``payload_length = 0xFFFFFFFF``                            -> wrap arm

(a), (b) and (c) all exceed ``+0x7FFFFFFF`` and are claimed by the offset-range
arm before the length is ever looked at -- in (c) the length never gets read at
all. Only (d) reaches the arithmetic: ``0xFFFFFFFF`` is the largest value the
length-range arm ACCEPTS, so the slot survives to
``total = (uint32_t)p_off + p_len`` and is caught by ``total < p_off``.

So the two arms go one per slot, rather than the procedure's "second copy of the
boundary manifest" in both. ``sep_backup_manifest_structural_fail_base`` refuses
to run when the two slots declare the same error code, so a second copy cannot be
graded by that base at all. Splitting the arms also covers two boundary classes
per run instead of one.

WHAT THAT COSTS, stated rather than glossed: combination (d) is proved RETRYABLE
here, not terminal, because the terminal code is the backup's. Proving (d)
terminal needs a row that swaps the two arms between slots, which does not exist.

WHAT PROVES THE WRAP ARM FIRED, given that it prints NOTHING. Three of the four
arms of ``validate_manifest_header`` return ``MANIFEST_ERR_PAYLOAD_TOO_LARGE``
and two of those are silent, so the code alone says very little. This row
excludes the other two by construction and asserts the exclusion:

  * the LENGTH-RANGE arm is excluded and its boundary proved at the same time.
    ``0xFFFFFFFF`` is not ``> 0xFFFFFFFF``, so ``PAYLOAD_LEN_RANGE`` must be
    ABSENT while the slot is still refused. An off-by-one there -- ``>=`` instead
    of ``>`` -- would print the token, so its absence is the accept-side evidence
    for that arm and not merely a forbidden neighbour.
  * the CAPACITY arm is excluded arithmetically: the wrapped sum is
    ``0x1000 + 0xFFFFFFFF = 0xFFF`` in 32 bits, three orders of magnitude inside
    the 256 KiB SRAM, so ``total > SRAM_SIZE`` is false and cannot be the arm that
    refused the slot. ``declare_wrapping_payload_length`` asserts that against the
    real field values before the run, and the geometry is logged.
  * a ROM MISSING the wrap test would compute the same small ``total``, find it
    in range, and ACCEPT the slot -- so the refusal is not a weak outcome here,
    it is the entire result. ``MANIFEST_HASH_OK`` must never appear, which is the
    positive evidence that neither slot got past ``validate_manifest_header``.

THE OFFSET VALUE IS DRAWN from the procedure's own three, and the draw's CLASS is
asserted rather than assumed: the stored ``int64`` must exceed ``+0x7FFFFFFF``.
That matters more than it looks. Sign-extending ``0xFFFFFFFF`` into the signed
field would store ``-1``, which is INSIDE the permitted negative range and is
then refused by the ``p_off <= 0`` arm -- the same ``MANIFEST_ERR_BAD_LENGTH``,
a different arm, and no token at all. The seed is the runner's, so a failing draw
replays with the run's own ``--seed``.

NO RE-SEAL ON THE BACKUP, BY LAYOUT. ``boot_arguments`` sits outside the TBS and
outside the bytes ``manifest_hash`` covers (``manifest.h``), so the backup stays
genuinely signed and the declared offset is its only defect. The primary's
``payload_length`` DOES sit inside the TBS, so that slot is re-signed and the
declared length is likewise its only defect. Neither payload is moved: both
refusals precede the fetch.

SCOPE. The length-range arm's REJECT side (``payload_length > 0xFFFFFFFF``) is
not among the procedure's four combinations and is not claimed here. The
capacity arm's accept and reject sides belong to the payload-size group
(``sep_payload_size_base``), which bounds its declared length below the wrap arm
on purpose so the silent arms stay separable; this row is the other side of that
split.

No ``+sep_crypto_edn_force``: both slots are refused upstream of the crypto
chain, so no RSA modexp runs and OTBN never needs an entropy grant.
"""

from __future__ import annotations

import pyuvm

from env import sep_manifest_mutate as mm
from env import sep_payload_mutate as pm
from env.sep_seeded_rng import SepSeededRng
from rom_fw import sep_manifest_field_defect as fd
from rom_fw.sep_backup_manifest_structural_fail_base import (
    sep_backup_manifest_structural_fail_base,
)
from rom_fw.sep_usage_constraint_base import EFUSE_PRELOAD

# manifest.h. The wrap arm's code, shared with the length-range and capacity arms
# -- see the module docstring for how the other two are excluded.
ERR_PAYLOAD_TOO_LARGE = 0x0003_0007
# manifest.h. The offset-range arm's code, shared with every other length verdict
# in the same function, each of which is forbidden below by its own token.
ERR_BAD_LENGTH = 0x0003_0004

_OFF_RANGE_TOKEN = "PAYLOAD_OFF_RANGE"
_LEN_RANGE_TOKEN = "PAYLOAD_LEN_RANGE"


@pyuvm.test()
class sep_manifest_payload_limits_test(sep_backup_manifest_structural_fail_base):
    """Primary wraps its payload bound, backup over-ranges its offset, ROM halts."""

    efuse_preload = EFUSE_PRELOAD
    primary_expected_error = ERR_PAYLOAD_TOO_LARGE
    expected_error = ERR_BAD_LENGTH
    backup_defect_marker = _OFF_RANGE_TOKEN

    # The sibling arms that return one of this row's two codes, plus everything
    # downstream of a decision neither slot reaches. PAYLOAD_LEN_RANGE carries the
    # most weight: it is the arm whose accept-side boundary the primary sits on.
    extra_forbidden = (
        _LEN_RANGE_TOKEN, "PAYLOAD_OFF_ALIGN", "PAYLOAD_HASHED_LEN_BAD=",
        "ENC_HASHED_LEN_PARTIAL", "PAYLOAD_OVERLAPS_MANIFEST",
        "TOC_REGION_OOB=", "TOC_PLEN_MISMATCH=", "PAYLOAD_NO_ROOM=",
        "PAYLOAD_LOC_OVERFLOW", "PAYLOAD_LOC_OT_OOB", "PAYLOAD_DST=",
        "USING_SEP_SRAM", "USING_SMC_SRAM", "EXT_SRAM_INIT_WAIT",
        "MANIFEST_HASH_MISMATCH", "MANIFEST_HASH_OK", "CRYPTO_FAIL=",
        fd.LC_MARKER, fd.CHIPLET_MARKER, fd.PACKAGE_MARKER,
    )

    def corrupt_primary(self, buf: bytearray) -> None:
        geom = pm.declare_wrapping_payload_length(buf, "primary")
        self._wrap = geom
        self._primary_served = geom["payload_length"].to_bytes(8, "little")
        stored = bytes(buf[mm.slot_base("primary") + pm.OFF_PAYLOAD_LENGTH:
                           mm.slot_base("primary") + pm.OFF_PAYLOAD_LENGTH + 8])
        assert stored == self._primary_served, (
            f"primary payload_length reads {stored.hex()} after the write, expected "
            f"{self._primary_served.hex()}; the mutation did not land"
        )
        # The payload SOURCE the ROM would have fetched, for the negative device
        # check. The refusal precedes the fetch, so no read may begin here.
        self._primary_src = mm.slot_base("primary") + geom["payload_offset"]
        self.logger.info(
            "CHK-STIMULUS-WRAP: primary payload_length 0x%x -> 0x%x at "
            "payload_offset 0x%x. (0x%x + 0x%x) & 0xFFFFFFFF = 0x%x, which is BELOW "
            "the offset (so `total < p_off` fires) and below the 0x%x SRAM (so the "
            "capacity arm cannot fire). 0x%x is the largest value the length-range "
            "arm accepts, so %s must be ABSENT. Re-signed: the declared length is "
            "the slot's only defect",
            geom["payload_length_before"], geom["payload_length"],
            geom["payload_offset"], geom["payload_offset"], geom["payload_length"],
            geom["wrapped_sum"], geom["sram_size"], geom["len_range_limit"],
            _LEN_RANGE_TOKEN,
        )

    def corrupt_backup(self, buf: bytearray) -> None:
        seed = self.random_seed()
        value = SepSeededRng(seed).choice(pm.OFF_RANGE_VALUES)
        was = pm.set_out_of_range_payload_offset(buf, "backup", value)
        self._off_value = value
        self._backup_served = value.to_bytes(8, "little")
        stored = int.from_bytes(
            bytes(buf[mm.slot_base("backup") + pm.OFF_BOOT_PAYLOAD_OFFSET:
                      mm.slot_base("backup") + pm.OFF_BOOT_PAYLOAD_OFFSET + 8]),
            "little", signed=True,
        )
        # CHK-DRAW-CLASS: the drawn value really is in the class this row names.
        # A sign-extended write would land on the `p_off <= 0` arm instead, with
        # the same error code and no token, and the run would look the same.
        assert stored > pm.PAYLOAD_OFF_RANGE_LIMIT, (
            f"backup payload_offset reads {stored} as int64 for draw 0x{value:x}; "
            f"the offset-range arm needs a value above "
            f"+0x{pm.PAYLOAD_OFF_RANGE_LIMIT:x}, and a smaller or negative one is "
            f"claimed by a different arm that returns the same code silently"
        )
        self.logger.info(
            "CHK-STIMULUS-OFF-RANGE: seed %d drew payload_offset 0x%x from the "
            "procedure's %s; the backup's field goes %d -> %d as int64, above "
            "+0x%x, so validate_manifest_header must refuse it as %s before the "
            "cast to int32. NOT re-signed -- boot_arguments sits outside the TBS -- "
            "and the payload is not moved, because the refusal precedes the fetch",
            seed, value, [hex(v) for v in pm.OFF_RANGE_VALUES], was, stored,
            pm.PAYLOAD_OFF_RANGE_LIMIT, _OFF_RANGE_TOKEN,
        )

    def check_efuse(self, image) -> None:
        fd.assert_clean_key_fuses(image)

    def _check(self, console, status_seq, fw_done, fw_pass, retired) -> None:
        super()._check(console, status_seq, fw_done, fw_pass, retired)

        i_psrc = fd.first_index(console, fd.PRIMARY_SRC)
        i_bsrc = fd.first_index(console, fd.BACKUP_SRC)

        # CHK-WRAP-SILENT: the primary's arm printed no token of its own, which is
        # what says the rejection came from the wrap test rather than from either
        # of its two announcing siblings. The parent already pinned the primary's
        # error code to one occurrence inside the primary's own attempt; this adds
        # that no announcing arm claimed that window.
        for token in (_OFF_RANGE_TOKEN, _LEN_RANGE_TOKEN):
            n_before_backup = sum(
                1 for i, line in enumerate(console)
                if i_psrc < i < i_bsrc and token in line
            )
            assert n_before_backup == 0, (
                f"{token} appeared inside the primary's attempt (lines "
                f"{i_psrc}..{i_bsrc}): the primary declared an in-range, aligned "
                f"payload_offset and a length the range arm accepts, so an "
                f"announcing arm must not be what refused it. Console: {console}"
            )

        # CHK-OFF-RANGE-ATTRIBUTION: the announcing token is the BACKUP's, exactly
        # once, inside its own attempt. The parent checks the token is present and
        # positioned; the count is what rules out both slots producing it.
        n_off = fd.count(console, _OFF_RANGE_TOKEN)
        assert n_off == 1, (
            f"{_OFF_RANGE_TOKEN} appeared {n_off} times, expected exactly 1 (the "
            f"backup's): only the backup declares an out-of-range offset, and a "
            f"second occurrence would mean the two slots carry one defect and "
            f"nothing attributes the terminal verdict. Console: {console}"
        )
        self.logger.info(
            "CHK-ARM-SPLIT: primary@%d refused silently with "
            "MANIFEST_ERR=0x%08x (the wrap arm), backup@%d refused with %s and "
            "MANIFEST_ERR=0x%08x (the offset-range arm) -- two different arms, two "
            "different codes, one terminal verdict",
            i_psrc, ERR_PAYLOAD_TOO_LARGE, i_bsrc, _OFF_RANGE_TOKEN,
            ERR_BAD_LENGTH,
        )

        # CHK-NO-READ: the ROM never fetched the primary's payload. The refusal is
        # the first payload decision it makes, so the absence of this read is a
        # claim about that decision rather than about the transport.
        fd.assert_no_read_starting_at(
            self.logger, self._flash, self._primary_src,
            f"the primary declared payload_length 0x{self._wrap['payload_length']:x}, "
            f"whose 32-bit sum with payload_offset wraps, so "
            f"validate_manifest_header must refuse the slot before the payload "
            f"fetch is issued",
        )

        # CHK-STIMULUS-SERVED: the device really returned both mutated fields, so
        # the DUT was given this row's stimulus and not the shipped one.
        fd.assert_served_field(self.logger, self._flash, "primary",
                               pm.OFF_PAYLOAD_LENGTH, self._primary_served,
                               "primary payload_length")
        fd.assert_served_field(self.logger, self._flash, "backup",
                               pm.OFF_BOOT_PAYLOAD_OFFSET, self._backup_served,
                               "backup boot_arguments.payload_offset")
