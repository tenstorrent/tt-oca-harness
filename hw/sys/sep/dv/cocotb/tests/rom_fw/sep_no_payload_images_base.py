# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared stimulus and evidence for the three "manifest declares no payload images" rows.

THE STIMULUS. A manifest whose payload carries an EMPTY image list. In the
reference regression that is written as ``payload_images: []`` in the manifest
generator's YAML; here the packed artefact is mutated directly, so the equivalent
is ``toc->image_count = 0`` -- the field the ROM reads to decide how many images
the payload describes.

WHY THAT IS THE RIGHT TARGET ON THIS DESIGN, and not the reference's own token.
``validate_manifest_payload`` (``bootrom/prod/src/manifest_load.c``) refuses
``n == 0u || n > 256u`` with ``MANIFEST_ERR_TOC_COUNT`` (0x00030010). An empty
image list is the ``n == 0`` half, and that half has no row anywhere in this
repository: all four existing ``*_invalid_payload_image_count_test`` cells plant
257, and ``sep_toc_defect.BAD_IMAGE_COUNT`` states in writing that the zero half
"needs its own row". These three rows are it.

The reference reports ``INVALID_PAYLOAD_LENGTH`` for the same stimulus because it
has a rule this design does not: its header validation refuses
``payload_length <= sizeof(toc_header) + sizeof(toc_entry)``, i.e. "must include
the TOC and at least one image", and its empty-list artefact packs a payload short
enough to land there. This ROM has no such rule: its only MINIMUM-size rule on
``payload_length`` is ``p_len == 0``, which a payload holding a TOC header
satisfies, so the empty list is refused one stage later by the count bound
instead. (Several other arms return ``MANIFEST_ERR_BAD_LENGTH``, but none of them
requires the payload to hold a TOC plus one entry.) Requiring the reference's
token here would therefore aim at a truncated-payload rule rather than at the
empty image list.

The planted shape is the reference's too, just reached from its other config: the
reference generator defines BOTH ``zero_payload_images`` (an empty list) and
``payload_image_count_zero`` (a full payload whose TOC declares zero), and this
port plants the latter. On this ROM the two are indistinguishable -- the count arm
returns before ``payload_length``, ``toc_bytes`` or any entry is read -- so no
coverage of ``validate_manifest_payload`` is lost by mutating the packed artefact
instead of re-running a generator this workspace does not have.

WHAT ``n == 0`` ACTUALLY REACHES, which is what the row pins. The per-image loop
does not execute at all, so no image type, bound, ordering or digest is examined
and ``bl1_found`` stays false. That alone would NOT let the payload through: the
``if (!bl1_found)`` arm after the loop refuses it with
``MANIFEST_ERR_NO_BL1_IMAGE`` regardless. So the count arm is not the only thing
standing between an empty list and a boot -- what this row establishes is WHICH arm
refuses it and HOW EARLY, and both neighbours are forbidden: ``TOC_REGION_OOB=``
with 0x00030007 immediately after the count, and ``NO_BL1_IMAGE`` with 0x00030008
at the end of the loop. A run that reached either would mean the count bound did
not fire.

THE ARM IS SILENT. It returns without printing a token of its own, so three
things carry the attribution instead and every member asserts all three:

  * THE ERROR CODE, 0x00030010, positioned inside the attempt of the slot that
    planted it. Every neighbouring structural code is forbidden, so a rejection by
    a different check cannot satisfy a row here;
  * THE PLACE IN THE CHAIN. The arm sits downstream of ``manifest_crypto_validate``
    (``manifest_load.c`` fixes the order: security version -> signature -> payload
    hash -> decrypt -> TOC), so the planting slot's own ``RSA_VERIFY_START``,
    ``SIG_VALID``, ``PLD_HASH_OK`` and ``CRYPTO_VALIDATE_OK`` must have been printed
    before its rejection. An upstream refusal wearing the right code cannot
    reproduce that order;
  * THE BYTES THE DEVICE SERVED. The flash BFM must be shown to have returned eight
    zero bytes at the exact flash address of that slot's ``image_count``. That is
    the half the ROM cannot fake, and it is what separates these rows from the
    257-valued cells whose console evidence is otherwise identical.

THE PAYLOAD IS PLAINTEXT. All three rows load ``secure_boot.bin``, whose slots both
carry ``encrypted_payload = 0``, and each base asserts that flag on the loaded
image. ``DECRYPT_START`` is forbidden outright, which is positive evidence the
plaintext arm ran: the ROM calls ``decrypt_payload`` only for a slot whose flag is
set. The encrypted counterpart of this stimulus is not covered by these rows.

THE THREE ROWS AND WHAT SEPARATES THEM:

  * PRIMARY -- the primary plants the empty list, is refused, and the untouched
    backup completes a boot. The rejection returns into ``rom_manifest_boot``'s
    retry loop, so recovery is the required outcome;
  * BACKUP -- the backup plants it and the run is terminal. Reaching the backup at
    all needs the primary refused first, and the trigger is the REFERENCE's own:
    an invalid primary TOC ``major_version``, which gives a distinct error code
    (0x00030006) downstream of the same crypto chain;
  * PRIMARY_AND_BACKUP -- both slots plant it, both are refused with the SAME code,
    and the run is terminal.

WHY THE TERMINAL PAIR NEEDS A ``_check`` OF ITS OWN rather than
``sep_backup_payload_fail_base``. That base grades exactly the right stage, but two
of its rules are incompatible with these rows and neither could be relaxed without
weakening its existing dependants. It REFUSES equal primary and backup error codes,
which is precisely the PRIMARY_AND_BACKUP scenario; and it requires each crypto
marker EXACTLY ONCE, on the stated grounds that its own members' primaries die
before the verifier. Here both slots reach it, so the count is two. The replacement
below is stricter, not looser: it pins each crypto marker to two occurrences, one
inside each slot's own attempt, and when the two codes coincide it requires the
code twice and brackets each occurrence by the slot that produced it.
"""

from __future__ import annotations

import pyuvm  # noqa: F401  (members register themselves with @pyuvm.test)

from env import sep_manifest_mutate as mm
from env import sep_payload_mutate as pm
from rom_fw import sep_manifest_field_defect as fd
from rom_fw import sep_toc_defect as td
from rom_fw.sep_backup_manifest_fail_base import sep_backup_manifest_fail_base
from rom_fw.sep_primary_fail_backup_boot_base import sep_primary_fail_backup_boot_base

# The stimulus: an empty image list.
EMPTY_IMAGE_COUNT = 0
# manifest.h, the arm that refuses it.
ERR_TOC_COUNT = td.ERR_TOC_COUNT

# The failover trigger the BACKUP row plants in its primary, taken from the
# reference scenario rather than from this repository's usual BAD_MAGIC: the
# reference sets the primary's TOC major_version to 99 and expects a version
# verdict ahead of the backup's. 99 is not TOC_MAJOR_VERSION, so
# validate_manifest_payload returns MANIFEST_ERR_BAD_TOC_VERSION -- a code
# distinct from the arm under test, reached through the same crypto chain.
TRIGGER_TOC_VERSION = 99
ERR_BAD_TOC_VERSION = td.ERR_BAD_TOC_VERSION

# Payload-relative location and width of the mutated field, manifest.h.
IMAGE_COUNT_FIELD = (pm.TOC_OFF_IMAGE_COUNT, 8)
TOC_VERSION_FIELD = (pm.TOC_OFF_MAJOR_VERSION, 2)

# manifest_crypto.c, in emission order. Both slots run the whole chain in every
# member here, so each marker must appear twice and each slot's four must sit
# inside its own attempt.
CRYPTO_CHAIN = ("RSA_VERIFY_START", "SIG_VALID", "PLD_HASH_OK",
                "CRYPTO_VALIDATE_OK")
MANIFEST_HASH_OK = "MANIFEST_HASH_OK"
ALL_FAILED = "MANIFEST_ALL_FAILED"
MANIFEST_OK = "MANIFEST_OK"
CRYPTO_FAIL = "CRYPTO_FAIL="
SBOOT_OFF = "SBOOT_OFF"
BOOT_PROGRESS = ("PRE_JUMP", "BL1_COPIED", "BL1_JUMP=")

# Every structural code the ROM could return, so a member can forbid all of them
# except the ones its own two slots produce.
_ALL_STRUCTURAL_ERRORS = (
    td.ERR_BAD_MAGIC, td.ERR_BAD_VERSION, td.ERR_BAD_LENGTH, td.ERR_BAD_TOC_ID,
    td.ERR_BAD_TOC_VERSION, td.ERR_PAYLOAD_TOO_LARGE, td.ERR_NO_BL1_IMAGE,
    td.ERR_TOC_COUNT,
)


def forbidden_errors(*produced: int) -> list[str]:
    """``MANIFEST_ERR=`` codes that would mean a check this row does not plant fired.

    ``produced`` names the codes the row's own slots legitimately emit. Everything
    else is forbidden, which is the swap test: a row whose mutation were replaced
    by a neighbouring family's would be refused here rather than accepted as a
    generic manifest failure.
    """
    return [f"MANIFEST_ERR=0x{c:08x}" for c in _ALL_STRUCTURAL_ERRORS
            if c not in produced]


def plant_empty_image_list(logger, buf: bytearray, slot: str) -> bytes:
    """Declare an empty image list in ``slot``'s TOC and return the stored bytes.

    The surrounding checks are asserted satisfiable first, because a slot refused
    by ``validate_manifest_header`` never reaches the TOC at all and would report a
    different verdict through the same failover.

    The return value is what the flash DEVICE must later be shown to have served.
    """
    major, minor = mm.manifest_version(buf, slot)
    assert (major, minor) == (mm.MANIFEST_MAJOR_VERSION, 0), (
        f"{slot} manifest version is {major}.{minor}: the slot would be refused by "
        f"validate_manifest_header before the TOC is ever parsed"
    )
    assert mm.manifest_length(buf, slot) == mm.MANIFEST_SIZE, (
        f"{slot} manifest_length is {mm.manifest_length(buf, slot)}, expected "
        f"{mm.MANIFEST_SIZE}: BAD_LENGTH would pre-empt the TOC arm"
    )
    off, size = IMAGE_COUNT_FIELD
    was = pm.set_toc_image_count(buf, slot, EMPTY_IMAGE_COUNT)
    assert was > 0, (
        f"{slot} TOC already declared {was} images before the mutation, so this row "
        f"would not have changed the count the ROM reads"
    )
    p = pm.payload_base(buf, slot)
    stored = bytes(buf[p + off:p + off + size])
    # The value is pinned to literal ZERO, not merely to whatever this module
    # declares. Both halves of `n == 0 || n > 256` return the same code, so an
    # over-large count would satisfy every other assertion in these rows and turn
    # them into copies of the existing 257-valued cells -- silently, because the
    # device-side check only compares against what was planted.
    assert EMPTY_IMAGE_COUNT == 0 and stored == bytes(size), (
        f"{slot} TOC image_count was planted as {EMPTY_IMAGE_COUNT} and stored as "
        f"{stored.hex()}; these rows are the ZERO half of the count bound, and the "
        f"over-large half already has four cells of its own "
        f"(sep_toc_defect.BAD_IMAGE_COUNT). Anything but zero here makes this row a "
        f"duplicate of those while still passing every other check"
    )
    now = int.from_bytes(bytes(pm.toc_plaintext(buf, slot)[off:off + size]), "little")
    assert now == EMPTY_IMAGE_COUNT, (
        f"{slot} TOC image_count reads {now} after the write, expected "
        f"{EMPTY_IMAGE_COUNT}; the mutation did not land"
    )
    logger.info(
        "CHK-STIMULUS-NO-PAYLOAD-IMAGES: %s TOC image_count %d -> %d. The field "
        "sits at flash 0x%06x and the device must serve %s there. Every other "
        "payload rule is left SATISFIED -- identifier PTOC, major_version %d, "
        "payload_length agreeing with the manifest, payload_hash and the signature "
        "recomputed over the edit -- so the empty image list is the only rule "
        "validate_manifest_payload can refuse this slot on, and it is refused "
        "BEFORE the TOC_REGION_OOB bound that follows it",
        slot, was, now, p + off, stored.hex(), pm.TOC_MAJOR_VERSION,
    )
    return stored


def assert_crypto_chain_twice(logger, console: list[str], i_psrc: int,
                              i_bsrc: int, i_end: int) -> tuple[list[int], list[int]]:
    """Both slots ran the whole crypto chain, each inside its own attempt.

    This is the positive evidence that places a TOC rejection downstream of a
    VERIFIED signature rather than in place of one. Presence alone would be
    satisfied by four markers belonging to one slot, so each is pinned to exactly
    two occurrences and each slot's four are required in emission order between
    that slot's read and the end of its attempt.
    """
    primary: list[int] = []
    backup: list[int] = []
    for markers, lo, hi, who in ((primary, i_psrc, i_bsrc, "primary"),
                                 (backup, i_bsrc, i_end, "backup")):
        previous = lo
        for marker in CRYPTO_CHAIN:
            n = fd.count(console, marker)
            assert n == 2, (
                f"{marker} appeared {n} times, expected exactly 2 (one per slot): "
                f"every member here plants a defect downstream of the crypto chain, "
                f"so both slots must reach it. Console: {console}"
            )
            i = fd.first_index(console, marker, after=previous)
            assert previous < i < hi, (
                f"the {who}'s {marker}@{i} does not sit between the previous "
                f"stage@{previous} and the end of its attempt@{hi}: its crypto chain "
                f"is out of order or outside its own attempt. Console: {console}"
            )
            markers.append(i)
            previous = i
    logger.info(
        "CHK-CRYPTO-BOTH-SLOTS: primary %s; backup %s -- each slot's signature "
        "verified inside its own attempt before its payload was graded",
        ", ".join(f"{m}@{p}" for m, p in zip(CRYPTO_CHAIN, primary)),
        ", ".join(f"{m}@{p}" for m, p in zip(CRYPTO_CHAIN, backup)),
    )
    return primary, backup


class sep_no_payload_images_primary_base(sep_primary_fail_backup_boot_base):
    """The PRIMARY declares an empty image list; the backup boots."""

    flash_image = td.PLAINTEXT_IMAGE
    efuse_preload = td.PLAINTEXT_EFUSE
    primary_expected_error = ERR_TOC_COUNT
    # The arm returns without printing, so the base's marker machinery is told so
    # explicitly rather than being handed an empty string by accident. It is also
    # coupled to a required CRYPTO_FAIL= line, which this arm never produces.
    primary_defect_marker = ""
    # The primary's signature verifies and only its TOC is refused, so it drives
    # the verifier and reaches a verified signature of its own.
    primary_expected_rsa_starts = 1
    primary_expected_sig_valids = 1

    extra_required = (MANIFEST_HASH_OK, "PLD_HASH_OK", "BL1_COPIED", "BL1_JUMP=")
    extra_forbidden = tuple(
        forbidden_errors(ERR_TOC_COUNT)
        + [CRYPTO_FAIL, ALL_FAILED, td.DECRYPT_START]
        + list(td.OTHER_PAYLOAD_TOKENS)
        + list(td.DECRYPT_FAILURE_TOKENS)
    )

    def mutate_flash_image(self, buf: bytearray) -> bytearray:
        # Which image was loaded is a property of the artefact, not of a class
        # attribute. Assert it, so a row pointed at the encrypted image fails here
        # instead of quietly running a scenario this module does not describe.
        for slot in ("primary", "backup"):
            assert not pm.is_encrypted(buf, slot), (
                f"{slot} payload carries encrypted_payload = 1; these rows are the "
                f"PLAINTEXT stimulus and the loaded image ({self.flash_image}) is "
                f"not the one they are about"
            )
        self._payload_offset = pm.payload_base(buf, "primary") - mm.slot_base("primary")
        return super().mutate_flash_image(buf)

    def corrupt_primary(self, buf: bytearray) -> None:
        self._served = plant_empty_image_list(self.logger, buf, "primary")

    def check_efuse(self, image) -> None:
        fd.assert_clean_key_fuses(image)

    def check_transport(self, console: list[str], flash) -> None:
        super().check_transport(console, flash)

        slot_err = f"MANIFEST_ERR=0x{ERR_TOC_COUNT:08x}"
        i_psrc = fd.first_index(console, fd.PRIMARY_SRC)
        i_bsrc = fd.first_index(console, fd.BACKUP_SRC)

        # CHK-COUNT-ATTRIBUTION: the arm's code is the primary's and only the
        # primary's. The arm is silent, so this code is the whole ROM-side statement
        # about which check refused the slot, which is why every neighbouring code
        # and token is forbidden above.
        i_err = fd.assert_slot_attributed(console, slot_err, after=i_psrc,
                                          before=i_bsrc)

        # CHK-STIMULUS-SERVED: the device really returned eight zero bytes at the
        # primary's image_count. The 257-valued cells' consoles are otherwise
        # identical to this one; this is what separates them.
        off, _size = IMAGE_COUNT_FIELD
        fd.assert_served_field(self.logger, flash, "primary",
                               self._payload_offset + off, self._served,
                               "primary TOC image_count")

        self.logger.info(
            "CHK-NO-PAYLOAD-IMAGES: primary@%d declared an empty image list and was "
            "refused %s@%d inside its own attempt, after its signature verified; the "
            "untouched backup was read@%d and booted",
            i_psrc, slot_err, i_err, i_bsrc,
        )


class sep_no_payload_images_terminal_base(sep_backup_manifest_fail_base):
    """Both slots are refused and the ROM halts; the BACKUP plants the empty list.

    The primary's defect is declared by the member: an invalid TOC major_version
    for the BACKUP row, and the same empty image list for the PRIMARY_AND_BACKUP
    row. Both sit downstream of the crypto chain, so the grading below is shared.
    """

    flash_image = td.PLAINTEXT_IMAGE
    efuse_preload = td.PLAINTEXT_EFUSE
    expected_error = ERR_TOC_COUNT
    # The arm returns without printing; the error code, the chain position and the
    # device's bytes carry the attribution instead.
    backup_defect_marker = ""
    requires_defect_marker = False
    # (payload-relative offset, width) and expected bytes of the PRIMARY's own
    # planted field, for the device-side check. Set by the member.
    primary_field: tuple[int, int] = IMAGE_COUNT_FIELD

    def mutate_flash_image(self, buf: bytearray) -> bytearray:
        for slot in ("primary", "backup"):
            assert not pm.is_encrypted(buf, slot), (
                f"{slot} payload carries encrypted_payload = 1; these rows are the "
                f"PLAINTEXT stimulus and the loaded image ({self.flash_image}) is "
                f"not the one they are about"
            )
        self._primary_payload_offset = (pm.payload_base(buf, "primary")
                                        - mm.slot_base("primary"))
        self._backup_payload_offset = (pm.payload_base(buf, "backup")
                                       - mm.slot_base("backup"))
        return super().mutate_flash_image(buf)

    def corrupt_backup(self, buf: bytearray) -> None:
        self._backup_served = plant_empty_image_list(self.logger, buf, "backup")

    def check_efuse(self, image) -> None:
        fd.assert_clean_key_fuses(image)

    def _check(self, console, status_seq, fw_done, fw_pass, retired) -> None:
        log = self.logger
        status_hex = [hex(v) for v in status_seq]
        log.info("cold_scratch[1] sequence: %s", status_hex)
        log.info("ROM console: %s", console)

        # Guard the guards: a dark console makes every marker check vacuous.
        assert retired, "core retired no instructions; the ROM never ran"
        assert console, (
            "ROM console is empty, so no marker check below means anything (the "
            "virt console is DEBUG-build only -- check the ROM build)"
        )

        primary_err = f"MANIFEST_ERR=0x{self.primary_expected_error:08x}"
        backup_err = f"MANIFEST_ERR=0x{self.expected_error:08x}"
        i_psrc = fd.first_index(console, fd.PRIMARY_SRC)
        i_bsrc = fd.first_index(console, fd.BACKUP_SRC)
        i_all = fd.first_index(console, ALL_FAILED)

        # CHK-FAILOVER: both slots were read, in order, and the loop then gave up.
        assert i_psrc >= 0, (
            f"ROM never read the primary slot ({fd.PRIMARY_SRC}). Console: {console}"
        )
        assert i_psrc < i_bsrc, (
            f"backup slot ({fd.BACKUP_SRC}@{i_bsrc}) was not read after the "
            f"primary@{i_psrc}: this is not a failover. Console: {console}"
        )
        assert i_bsrc < i_all, (
            f"{ALL_FAILED}@{i_all} did not follow the backup read@{i_bsrc}: the ROM "
            f"gave up before evaluating the backup. Console: {console}"
        )

        # CHK-BOTH-SLOTS-CRYPTO: both signatures verified inside their own attempts.
        primary_chain, backup_chain = assert_crypto_chain_twice(
            log, console, i_psrc, i_bsrc, i_all)
        n_hash = fd.count(console, MANIFEST_HASH_OK)
        assert n_hash == 2, (
            f"{MANIFEST_HASH_OK} appeared {n_hash} times, expected exactly 2 (one "
            f"per slot): every defect here sits downstream of "
            f"manifest_check_integrity, so both slots must pass it and neither is "
            f"refused for a stale hash. Console: {console}"
        )
        for lo, hi, who in ((i_psrc, primary_chain[0], "primary"),
                            (i_bsrc, backup_chain[0], "backup")):
            i = fd.first_index(console, MANIFEST_HASH_OK, after=lo)
            assert lo < i < hi, (
                f"the {who}'s {MANIFEST_HASH_OK}@{i} does not sit between its "
                f"read@{lo} and its {CRYPTO_CHAIN[0]}@{hi}: its integrity check is "
                f"not part of its own attempt. Console: {console}"
            )

        # CHK-SLOT-ERRORS: each slot was refused inside its own attempt, and the
        # total number of slot errors is exactly two. When the two codes COINCIDE --
        # the PRIMARY_AND_BACKUP row -- the code itself cannot separate the slots, so
        # the count and the two brackets are what attribute one occurrence to each.
        n_err = fd.count(console, "MANIFEST_ERR=")
        assert n_err == 2, (
            f"MANIFEST_ERR= appeared {n_err} times, expected exactly 2 (one per "
            f"slot). Console: {console}"
        )
        if primary_err == backup_err:
            assert fd.count(console, primary_err) == 2, (
                f"{primary_err} appeared {fd.count(console, primary_err)} times; "
                f"this row plants the same defect in both slots, so the code must "
                f"appear once per slot. Console: {console}"
            )
            i_perr = fd.first_index(console, primary_err)
            i_berr = fd.first_index(console, backup_err, after=i_bsrc)
            assert i_psrc < i_perr < i_bsrc < i_berr < i_all, (
                f"the two rejections are not one per slot: primary read@{i_psrc}, "
                f"error@{i_perr}, backup read@{i_bsrc}, error@{i_berr}, "
                f"{ALL_FAILED}@{i_all}. Console: {console}"
            )
        else:
            i_perr = fd.assert_slot_attributed(console, primary_err, after=i_psrc,
                                               before=i_bsrc)
            i_berr = fd.assert_slot_attributed(console, backup_err, after=i_bsrc,
                                               before=i_all)
        assert primary_chain[-1] < i_perr, (
            f"{primary_err}@{i_perr} precedes the primary's "
            f"{CRYPTO_CHAIN[-1]}@{primary_chain[-1]}: its rejection is not "
            f"downstream of its own crypto chain. Console: {console}"
        )
        assert backup_chain[-1] < i_berr, (
            f"{backup_err}@{i_berr} precedes the backup's "
            f"{CRYPTO_CHAIN[-1]}@{backup_chain[-1]}: its rejection is not "
            f"downstream of its own crypto chain. Console: {console}"
        )
        log.info(
            "CHK-SLOT-ERRORS: primary@%d -> %s@%d -> backup@%d -> %s@%d -> %s@%d, "
            "and MANIFEST_ERR= appeared exactly twice",
            i_psrc, primary_err, i_perr, i_bsrc, backup_err, i_berr, ALL_FAILED,
            i_all,
        )

        # CHK-NOT-A-CRYPTO-FAILURE: the run must not be confused with the family
        # whose slots die inside manifest_crypto_validate. CRYPTO_FAIL= is printed on
        # exactly that arm, so its absence says the payload check ended this run.
        # MANIFEST_OK is emitted only after a slot passes in full, and the payload
        # check is the last thing before it.
        for marker in (CRYPTO_FAIL, MANIFEST_OK, SBOOT_OFF):
            assert not any(marker in line for line in console), (
                f"ROM printed {marker}, so the payload rejection under test is not "
                f"what ended this run. Console: {console}"
            )
        log.info("CHK-NOT-A-CRYPTO-FAILURE: neither %s, %s nor %s appeared",
                 CRYPTO_FAIL, MANIFEST_OK, SBOOT_OFF)

        # CHK-TERMINAL: the ROM converged on the BACKUP's code. The status word is
        # the independent half -- the console says which check complained, the
        # encoded status says what rom_err_fail() was handed (rom_main.c).
        expected_status = 0x0F01_0000 | (self.expected_error & 0xFFFF)
        assert expected_status in status_seq, (
            f"cold_scratch[1] never held 0x{expected_status:08x} "
            f"(STATUS_ENCODE(ERROR, 0x{self.expected_error & 0xFFFF:04x})); "
            f"observed {status_hex}"
        )
        assert fw_done, (
            f"ROM never signalled completion; two rejected slots must converge on a "
            f"FAIL verdict. cold_scratch[1]: {status_hex}"
        )
        assert not fw_pass, (
            "ROM signalled PASS: it booted an image it was supposed to reject"
        )
        log.info("CHK-TERMINAL: %s, %s, cold_scratch[1]=0x%08x, verdict FAIL",
                 backup_err, ALL_FAILED, expected_status)

        # CHK-NO-BOOT: nothing downstream of the rejection ran.
        for marker in BOOT_PROGRESS + tuple(self.extra_forbidden):
            assert not any(marker in line for line in console), (
                f"ROM printed {marker}, which sits past the rejection: it continued "
                f"booting a manifest it had already failed. Console: {console}"
            )
        log.info("CHK-NO-BOOT: none of %s reached",
                 ", ".join(BOOT_PROGRESS + tuple(self.extra_forbidden)))

        # CHK-STIMULUS-SERVED: the device really returned each row's planted bytes at
        # each slot's own field address. `self._flash` is published by
        # sep_backup_manifest_fail_base for exactly this kind of device-side check.
        off, _size = IMAGE_COUNT_FIELD
        fd.assert_served_field(log, self._flash, "backup",
                               self._backup_payload_offset + off,
                               self._backup_served, "backup TOC image_count")
        p_off, _p_size = self.primary_field
        fd.assert_served_field(log, self._flash, "primary",
                               self._primary_payload_offset + p_off,
                               self._primary_served,
                               "primary's failover-trigger field")
