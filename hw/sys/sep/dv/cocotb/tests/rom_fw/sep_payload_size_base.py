# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared stimulus and assertions for the payload image size testcases.

The requirement is the ROM's decision about how big a payload may be, and it is
decided in three places (``manifest_load.c``):

  * ``validate_manifest_header``: ``payload_offset + payload_length`` must fit
    SEP EXT SRAM, else ``MANIFEST_ERR_PAYLOAD_TOO_LARGE``. Upstream of the
    transfer, so an over-declared payload is refused before a byte moves.
  * the staging block: ``payload_length`` must fit the chosen destination's
    capacity, ``SRAM_BASE + SRAM_SIZE - payload_dest`` for EXT SRAM or the
    SMC-published ``scratch[14]`` window length for SMC SRAM, else
    ``PAYLOAD_NO_ROOM=`` and ``MANIFEST_ERR_PAYLOAD_NO_ROOM``.
  * ``boot_flash_bounds_ok`` (``boot_flash.h``): the flash read must stay inside
    one boot slot, whose span is also the SEP SRAM size.

On the EXT path all three land on the same number, because the shipped
``payload_offset`` is the same for the flash slot and the SRAM destination:
``SEP SRAM size - payload_offset``, i.e. 252 KiB. :func:`ext_payload_capacity`
derives it instead of restating it, and :func:`assert_rom_sram_bounds` proves the
SRAM size this module uses is the one the ROM was compiled with -- a testcase that
picks a size relative to a stale copy of that number measures nothing, and does so
silently.

WHAT A MEMBER HAS TO ESTABLISH. "The run booted" is not it: the shipped payload
already boots, so a member that only repacked the length would pass against a ROM
that ignored the field. Each accepted member therefore requires

  * ``PAYLOAD=`` echoing its own ``payload_length`` -- the ROM prints the value it
    accepted, so this is the decision itself rather than a proxy;
  * the destination marker of the branch it selected, exactly once, with the other
    branch's forbidden, and ``PAYLOAD_DST=`` at that destination's address;
  * a flash read that actually served every byte of the declared payload, taken
    from the device's transaction record, so the size is a property of the
    transfer and not only of the manifest;

and forbids every refusal token the size decision could have produced, so an
accepted member cannot pass by being refused and recovering.

WHAT THE STAGED COPY IS AND IS NOT CHECKED AGAINST. The evidence above is the
declared length, the destination, and the bytes the DEVICE served. Of the bytes
that arrive at the destination, only the TOC region and the BL1 body are bound by
a digest the ROM verifies (``payload_hashed_length`` is the packer's 248, and each
image body has its own entry digest), so a transfer that silently delivered fewer
bytes than the device served would not be caught here. That gap is the price of
keeping the fill zeros; closing it needs a non-zero fill and a read-back of the
staged region, which is a different stimulus from the size decision.

The refused member is the mirror image: the ROM must refuse the PRIMARY with
``MANIFEST_ERR=0x00030007`` before any staging, fall over to the backup, and boot
it. The primary's payload read must be absent from the device record -- that is
what separates "refused the declared size" from "read it and then complained".

SCOPE LIMIT for the SMC members, in two parts.

``u_smc_mem`` is a flat ``axi_sim_mem`` and the window comes from
``+sep_smc_scratch13/14``, so a pass says the ROM honoured the window it was given
at the size under test. It says nothing about SMC firmware publishing that window;
see ``sep_use_ext_sram_base`` for the same caveat.

And none of these members reaches the window's own capacity check. The window the
testlist publishes is 256 KiB, larger than the 252 KiB
``validate_manifest_header`` allows any payload in the first place, so
``PAYLOAD_NO_ROOM=`` / ``MANIFEST_ERR_PAYLOAD_NO_ROOM`` cannot fire for any size
this group can declare -- that arm is only reachable with a window smaller than
the payload, which is the SMC over-capacity stimulus and belongs to a different
testcase. Do not book any row here as covering it.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from env import sep_manifest_mutate as mm
from env import sep_payload_mutate as pm
from env import sep_spi_slot_evidence as ev
from rom_fw import sep_manifest_field_defect as fd
from rom_fw import sep_use_ext_sram_base as ues
from rom_fw.sep_rom_ot_dma_boot_test import SECURE_FLASH_IMAGE
from rom_fw.sep_rom_ot_secure_boot_test import sep_rom_ot_secure_boot_test
from sep_reg_meta import sym

# PROD lifecycle, so secure_boot_enabled() enforces the crypto chain regardless of
# the manifest flag and every member re-signs into a genuinely verified image.
EFUSE_PRELOAD = (
    Path(__file__).resolve().parents[3] / "tb" / "efuse_preloads"
    / "efuse_configurations" / "sep_efuse_lc_prod.toml"
)

# The generated SEP map. manifest_load.c takes SRAM_BASE/SRAM_SIZE from the C half
# of the same generator, which assert_rom_sram_bounds() cross-checks.
SEP_SRAM_BASE = sym("SEP_SRAM_MEM_BASE_ADDR")
SEP_SRAM_SIZE = sym("SEP_SRAM_MEM_SIZE")

_SEP_ADDR_H = (
    Path(__file__).resolve().parents[4] / "regs" / "gen" / "c" / "sep_addr.h"
)

# SMC staging window for the SMC members, published through
# +sep_smc_scratch13/14 in the testlist. The offset is the one
# sep_use_ext_sram_base already argues for -- it clears the status ring buffer at
# the SMC SRAM base and is 8-byte aligned, so neither window check is what these
# members exercise. The length is 256 KiB, above the 252 KiB
# validate_manifest_header allows any payload, which puts the window's own
# capacity check out of reach on purpose: see the scope limit in the module
# docstring. It must stay consistent with the +sep_smc_scratch13/14 values on
# every SMC member's testlist entry.
SMC_WINDOW_OFFSET = 0x0002_0000
SMC_WINDOW_SIZE = 0x0004_0000
SMC_PAYLOAD_DST = ues.SMC_SRAM_BASE + SMC_WINDOW_OFFSET

# manifest.h. Returned by three arms of validate_manifest_header: the 4 GiB range
# test, which prints PAYLOAD_LEN_RANGE; the payload_offset + payload_length
# overflow test, which prints nothing at all; and the capacity test this group is
# about. PayloadSizeRefusedTest keeps the code attributable by forbidding the
# first arm's token and by bounding its own declared length below the overflow
# arm, so the silent one cannot be the arm that fired.
ERR_PAYLOAD_TOO_LARGE = 0x0003_0007

# Tokens the other arms print before returning the same code, or that a different
# length defect would produce. Forbidding them is what makes the code attributable
# to the capacity decision.
_OTHER_LENGTH_REFUSALS = (
    "PAYLOAD_LEN_RANGE", "PAYLOAD_OFF_RANGE", "PAYLOAD_OFF_ALIGN",
    "PAYLOAD_HASHED_LEN_BAD=", "ENC_HASHED_LEN_PARTIAL", "TOC_REGION_OOB=",
    "TOC_PLEN_MISMATCH=", "PAYLOAD_OVERLAPS_MANIFEST",
)
# Refusals downstream of the size decision. None may appear in any member: an
# accepted payload must be accepted, and the refused member's backup must boot.
_STRUCTURAL_REFUSALS = (
    "IMAGE_OFF_ALIGN idx=", "IMAGE_END_OVERFLOW idx=", "IMAGE_OOB_BOUND idx=",
    "IMAGE_ORDER_BAD idx=", "IMAGE_LEN_ZERO idx=", "IMAGE_LEN_ALIGN idx=",
    "IMAGE_HASH_MISMATCH idx=", "IMAGE_HASH_TIMEOUT", "NO_BL1_IMAGE",
    "BL1_ADDR_RANGE", "BL1_ENTRY_RANGE", "PLD_HASH_FAIL=", "CRYPTO_FAIL=",
    "MANIFEST_ALL_FAILED",
)
_PRIMARY_SRC = fd.PRIMARY_SRC
_BACKUP_SRC = fd.BACKUP_SRC


def assert_rom_sram_bounds() -> tuple[int, int]:
    """Cross-check the SEP SRAM base/size against the header the ROM compiles with.

    ``manifest_load.c`` computes both capacity bounds from
    ``OCH_SEP_TOP_SEP_SRAM_BASE_ADDR`` / ``OCH_SEP_TOP_SEP_SRAM_SIZE`` in the
    generated C header, while this module reads the generated Python map. They come
    from one generator, so they agree today; the point is what happens when the
    SRAM is resized. A size chosen to sit ABOVE the capacity silently becomes a
    legal size, and the refused member keeps passing while measuring a boot that
    was supposed to fail. Read the C defines back and require agreement.

    Returns the ``(base, size)`` parsed from the header.
    """
    text = _SEP_ADDR_H.read_text()
    found = {}
    for name in ("OCH_SEP_TOP_SEP_SRAM_BASE_ADDR", "OCH_SEP_TOP_SEP_SRAM_SIZE"):
        hit = re.search(rf"^#define\s+{name}\s+(0x[0-9a-fA-F]+)\s*$", text, re.MULTILINE)
        assert hit, (
            f"{name} is not defined in {_SEP_ADDR_H}; every payload size bound in "
            f"this module is then an unverified number"
        )
        found[name] = int(hit.group(1), 16)
    base = found["OCH_SEP_TOP_SEP_SRAM_BASE_ADDR"]
    size = found["OCH_SEP_TOP_SEP_SRAM_SIZE"]
    assert (base, size) == (SEP_SRAM_BASE, SEP_SRAM_SIZE), (
        f"{_SEP_ADDR_H} gives SEP SRAM base 0x{base:08x} size 0x{size:08x}, but the "
        f"generated Python map gives 0x{SEP_SRAM_BASE:08x}/0x{SEP_SRAM_SIZE:08x}. "
        f"The ROM is compiled against the C values, so the capacity this testcase "
        f"reasons about is not the one the DUT enforces"
    )
    return base, size


def shipped_payload_bytes(slot: str) -> int:
    """``payload_length`` the packer wrote for ``slot`` in the signed image.

    The refused members boot the untouched backup, so the length the ROM echoes on
    that path is the packer's. Reading it out of the artefact keeps the expected
    ``PAYLOAD=`` in step with a repack of the image, where a literal would turn a
    packer change into a marker that no longer describes any slot.
    """
    with open(SECURE_FLASH_IMAGE, "rb") as fh:
        return pm.manifest_payload_length(bytearray(fh.read()), slot)


def shipped_payload_offset(slot: str) -> int:
    """``boot_arguments.payload_offset`` the packer wrote for ``slot``.

    The EXT capacity is measured from this offset, so a member that hardcoded it
    would be choosing its stimulus relative to a number the image no longer uses.
    """
    with open(SECURE_FLASH_IMAGE, "rb") as fh:
        buf = bytearray(fh.read())
    return pm.payload_base(buf, slot) - mm.slot_base(slot)


def ext_payload_capacity(payload_offset: int) -> int:
    """Largest ``payload_length`` the EXT SRAM path accepts for this offset.

    All three of the ROM's bounds collapse to this one number for the shipped
    layout: ``validate_manifest_header``'s ``payload_offset + payload_length <=
    SRAM_SIZE``, the staging block's ``SRAM_BASE + SRAM_SIZE - payload_dest`` with
    ``payload_dest = SRAM_BASE + payload_offset``, and ``boot_flash_bounds_ok``'s
    slot span, which is the same SRAM size measured from the slot base.
    """
    assert_rom_sram_bounds()
    return SEP_SRAM_SIZE - payload_offset


def _destination_markers(smc: bool) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Required/forbidden destination tokens for the branch a member selects."""
    if smc:
        return (
            (ues.WAIT_MARKER, ues.USING_SMC,
             f"SMC_WIN_OFF=0x{SMC_WINDOW_OFFSET:08x}",
             f"SMC_WIN_LEN=0x{SMC_WINDOW_SIZE:08x}",
             f"PAYLOAD_DST=0x{SMC_PAYLOAD_DST:08x}"),
            (ues.USING_SEP,) + ues.SMC_REFUSALS,
        )
    return (
        (ues.USING_SEP, f"PAYLOAD_DST=0x{ues.SEP_PAYLOAD_DST:08x}"),
        (ues.USING_SMC, ues.WAIT_MARKER) + ues.SMC_REFUSALS,
    )


def accepted_markers(payload_bytes: int, *,
                     smc: bool) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Markers for a member whose payload size the ROM must accept and boot."""
    required, forbidden = _destination_markers(smc)
    return (
        required + (
            "MANIFEST_PRIMARY", _PRIMARY_SRC, "MANIFEST_OK",
            "IMAGES=0x00000001", f"PAYLOAD=0x{payload_bytes:08x}",
            "BL1_COPIED", "BL1_JUMP=",
        ),
        forbidden + _OTHER_LENGTH_REFUSALS + _STRUCTURAL_REFUSALS + (
            "MANIFEST_BACKUP", _BACKUP_SRC, "MANIFEST_ERR=",
            "PAYLOAD_LOC_OT_OOB", "PAYLOAD_LOC_SMC_OOB", "PAYLOAD_LOC_OVERFLOW",
        ),
    )


def refused_markers(backup_payload_bytes: int) -> tuple[tuple[str, ...],
                                                        tuple[str, ...]]:
    """Markers for a member whose primary payload size the ROM must refuse.

    The backup is untouched, so it stages in EXT SRAM and its accepted length is
    the packer's. Both slots' tokens are required, which is what makes the console
    say "the primary was refused for its size AND the backup booted" rather than
    only one of the two.
    """
    required, forbidden = _destination_markers(False)
    return (
        required + (
            "MANIFEST_PRIMARY", _PRIMARY_SRC,
            f"MANIFEST_ERR=0x{ERR_PAYLOAD_TOO_LARGE:08x}",
            "MANIFEST_BACKUP", _BACKUP_SRC, "MANIFEST_OK",
            "IMAGES=0x00000001", f"PAYLOAD=0x{backup_payload_bytes:08x}",
            "BL1_COPIED", "BL1_JUMP=",
        ),
        forbidden + _OTHER_LENGTH_REFUSALS + _STRUCTURAL_REFUSALS + (
            "PAYLOAD_NO_ROOM=", "PAYLOAD_LOC_OT_OOB", "PAYLOAD_LOC_SMC_OOB",
            "PAYLOAD_LOC_OVERFLOW", "STAGED_WIPE=", "FLASH_REINIT_FAIL=",
        ),
    )


def _served_intervals(flash) -> list[tuple[int, int]]:
    """Flash ranges the device actually streamed back, merged and deflated by one.

    ``ocah_spi_flash`` streams until CS deasserts, so every recorded span ends one
    byte past the request (``sep_manifest_field_defect.reads_starting_at`` says the
    same). Dropping that byte makes a coverage claim under-count rather than
    over-count, so "every byte was served" cannot be satisfied by the artefact of
    the model.
    """
    spans = []
    for txn in ev.reads(flash.get_transactions()):
        start, end = ev.read_span(txn)
        if end - 1 > start:
            spans.append((start, end - 1))
    spans.sort()
    merged: list[tuple[int, int]] = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def assert_payload_served(logger, flash, payload_src: int, payload_bytes: int,
                          what: str) -> None:
    """Require the device to have served every byte of the declared payload.

    The console proves what the ROM decided; this proves the transfer that decision
    caused really moved the declared number of bytes. Without it a member could
    pass with a manifest that claims a size the transport never carried, which is
    precisely the difference between producing a payload size and declaring one.
    """
    merged = _served_intervals(flash)
    want_end = payload_src + payload_bytes
    covering = [(s, e) for s, e in merged if s <= payload_src and e >= want_end]
    assert covering, (
        f"the device did not serve all of {what} at flash "
        f"0x{payload_src:x}..0x{want_end:x} ({payload_bytes} bytes). Served ranges: "
        f"{[f'0x{s:x}..0x{e:x}' for s, e in merged]}"
    )
    logger.info(
        "CHK-PAYLOAD-SERVED: the flash served 0x%06x..0x%06x (%d bytes) for %s, so "
        "the payload size under test is a property of the transfer. Served ranges: %s",
        payload_src, want_end, payload_bytes, what,
        [f"0x{s:x}..0x{e:x}" for s, e in merged],
    )


class _PayloadSizeTest(sep_rom_ot_secure_boot_test):
    """Common configuration for every payload-size member."""

    efuse_preload = EFUSE_PRELOAD
    # Bytes the primary manifest declares. Set by each member; a member that left
    # it unset would silently test the shipped size.
    payload_bytes: int = 0
    # False: the manifest keeps use_ext_sram=1 and stages in SEP EXT SRAM.
    # True: the bit is cleared and the ROM stages in the SMC-published window.
    stage_in_smc = False

    def build_efuse_image(self):
        assert self.efuse_preload and os.path.isfile(self.efuse_preload), (
            f"eFuse preload missing: {self.efuse_preload}"
        )
        image = self.select_efuse_image(default_preload=self.efuse_preload)
        lc = image.lc_raw()
        assert lc == 0x1, f"LC_STATE raw is 0x{lc:x}, expected 0x1 (PROD)"
        assert (image.field_int("SBOOT_DIS") & 0x1) == 0, (
            "SBOOT_DIS is set: the crypto chain would be skipped"
        )
        fd.assert_clean_key_fuses(image)
        return image

    def _payload_src(self, buf) -> int:
        """Flash byte offset the ROM will read the primary payload from."""
        return pm.payload_base(buf, "primary")

    def _select_destination(self, buf: bytearray) -> None:
        """Point the primary at the destination this member is named for.

        ``flag_args`` bit 29 sits outside the signed TBS, so clearing it leaves the
        hash and the signature valid: the SMC members' slots are still genuinely
        signed images, and the branch is the only thing that changed.
        """
        mm.set_flag_args_bit(buf, "primary", mm.FLAG_ARGS_BIT_USE_EXT_SRAM,
                             not self.stage_in_smc)
        ues.assert_stimulus(self.logger, buf, "primary",
                            want_set=not self.stage_in_smc)

    def log_transport(self, flash) -> None:
        self.logger.info(
            "SPI reads served: %s",
            [f"0x{s:x}..0x{e:x}" for s, e in _served_intervals(flash)],
        )


class PayloadSizeAcceptedTest(_PayloadSizeTest):
    """A legal payload size: the primary is repacked to it and must boot."""

    def mutate_flash_image(self, buf: bytearray) -> bytearray:
        assert self.payload_bytes, "payload_bytes is unset"
        geometry = pm.repack_payload(buf, "primary", self.payload_bytes)
        self._select_destination(buf)
        # The stimulus has to be legal for the reason this member claims, not by
        # accident. Both the destination capacity and the staged total are checked
        # against the ROM's own numbers.
        payload_offset = geometry["payload_flash_offset"] - mm.slot_base("primary")
        capacity = ext_payload_capacity(payload_offset)
        assert self.payload_bytes <= capacity, (
            f"{self.payload_bytes} bytes at payload_offset 0x{payload_offset:x} "
            f"exceeds the {capacity}-byte EXT SRAM capacity, so this member would "
            f"be refused rather than accepted"
        )
        if self.stage_in_smc:
            assert self.payload_bytes <= SMC_WINDOW_SIZE, (
                f"{self.payload_bytes} bytes exceeds the {SMC_WINDOW_SIZE}-byte SMC "
                f"window the testlist publishes, so the ROM would refuse this with "
                f"PAYLOAD_NO_ROOM= instead of staging it"
            )
        mm.verify_public_key(buf, "primary")
        self._src = self._payload_src(buf)
        self.logger.info(
            "CHK-STIMULUS-PAYLOAD-SIZE: primary repacked to payload_length=%d "
            "(0x%x), %s, BL1 %d bytes at payload offset %d; EXT capacity %d, "
            "destination %s",
            self.payload_bytes, self.payload_bytes, geometry,
            geometry["bl1_length"], geometry["bl1_offset"], capacity,
            "SMC window" if self.stage_in_smc else "SEP EXT SRAM",
        )
        return buf

    def check_transport(self, console: list[str], flash) -> None:
        ues.assert_destination(self.logger, console, expect_smc=self.stage_in_smc)
        accepted = fd.hex_value(console, "PAYLOAD=")
        assert accepted == self.payload_bytes, (
            f"the ROM accepted PAYLOAD=0x{accepted:08x} but this member repacked "
            f"0x{self.payload_bytes:08x}; the size the DUT acted on is not the one "
            f"under test. Console: {console}"
        )
        assert fd.count(console, "MANIFEST_PRIMARY") == 1, (
            f"MANIFEST_PRIMARY appeared "
            f"{fd.count(console, 'MANIFEST_PRIMARY')} times, expected 1. "
            f"Console: {console}"
        )
        self.logger.info(
            "CHK-SIZE-ACCEPTED: the ROM echoed PAYLOAD=0x%08x and reached BL1, so "
            "%d bytes is inside the bound it enforces", accepted, self.payload_bytes,
        )
        assert_payload_served(self.logger, flash, self._src, self.payload_bytes,
                              "the primary payload")


class PayloadSizeRefusedTest(_PayloadSizeTest):
    """An over-capacity payload size: the primary is refused, the backup boots."""

    def mutate_flash_image(self, buf: bytearray) -> bytearray:
        assert self.payload_bytes, "payload_bytes is unset"
        payload_offset = pm.payload_base(buf, "primary") - mm.slot_base("primary")
        capacity = ext_payload_capacity(payload_offset)
        assert self.payload_bytes > capacity, (
            f"{self.payload_bytes} bytes fits the {capacity}-byte EXT SRAM "
            f"capacity at payload_offset 0x{payload_offset:x}, so the ROM would "
            f"ACCEPT it and this member would prove the opposite of its name"
        )
        # validate_manifest_header returns the same code from an overflow arm that
        # prints nothing at all (manifest_load.c), so a declared length near the
        # 32-bit top would be indistinguishable on the console from the capacity
        # refusal this member claims. Keeping the sum inside 32 bits is what makes
        # the code attributable, rather than leaving it to be inferred.
        assert self.payload_bytes <= 0xFFFF_FFFF - payload_offset, (
            f"payload_offset 0x{payload_offset:x} + {self.payload_bytes} bytes "
            f"overflows 32 bits, which validate_manifest_header refuses through a "
            f"silent arm returning the same error code as the capacity check; the "
            f"refusal would no longer be attributable to the size decision"
        )
        was = pm.declare_payload_length(buf, "primary", self.payload_bytes)
        self._select_destination(buf)
        mm.verify_public_key(buf, "primary")
        self._backup_payload_bytes = pm.manifest_payload_length(buf, "backup")
        self._src = self._payload_src(buf)
        self.logger.info(
            "CHK-STIMULUS-PAYLOAD-SIZE: primary payload_length %d -> %d (0x%x), "
            "which is %d bytes past the %d-byte EXT SRAM capacity at "
            "payload_offset 0x%x; the backup keeps %d",
            was, self.payload_bytes, self.payload_bytes,
            self.payload_bytes - capacity, capacity, payload_offset,
            self._backup_payload_bytes,
        )
        return buf

    def check_transport(self, console: list[str], flash) -> None:
        err = f"MANIFEST_ERR=0x{ERR_PAYLOAD_TOO_LARGE:08x}"
        i_primary = fd.first_index(console, "MANIFEST_PRIMARY")
        i_err = fd.first_index(console, err)
        i_backup = fd.first_index(console, "MANIFEST_BACKUP")
        i_ok = fd.first_index(console, "MANIFEST_OK")
        assert 0 <= i_primary < i_err < i_backup < i_ok, (
            f"the refusal is not attributable to the primary: MANIFEST_PRIMARY@"
            f"{i_primary}, {err}@{i_err}, MANIFEST_BACKUP@{i_backup}, "
            f"MANIFEST_OK@{i_ok}. Console: {console}"
        )
        assert fd.count(console, "MANIFEST_ERR=") == 1, (
            f"MANIFEST_ERR= appeared {fd.count(console, 'MANIFEST_ERR=')} times; "
            f"only the primary may fail here, so a second slot error means the "
            f"backup was refused for a reason this member does not model. "
            f"Console: {console}"
        )
        # The ROM prints the accepted length after MANIFEST_OK, which on this path
        # is the backup's. Requiring the packer's value rules out the primary's
        # over-declaration having been accepted anywhere.
        accepted = fd.hex_value(console, "PAYLOAD=")
        assert accepted == self._backup_payload_bytes, (
            f"the ROM accepted PAYLOAD=0x{accepted:08x}, not the backup's "
            f"0x{self._backup_payload_bytes:08x}. Console: {console}"
        )
        # The primary never chose a destination, so the single staging event is the
        # backup's -- and it must sit after the backup attempt started.
        ues.assert_destination(self.logger, console, expect_smc=False)
        i_stage = fd.first_index(console, ues.USING_SEP)
        assert i_backup < i_stage, (
            f"{ues.USING_SEP}@{i_stage} precedes MANIFEST_BACKUP@{i_backup}: the "
            f"primary staged its payload, so the refusal did not happen upstream "
            f"of the transfer. Console: {console}"
        )
        self.logger.info(
            "CHK-SIZE-REFUSED: MANIFEST_PRIMARY@%d -> %s@%d -> MANIFEST_BACKUP@%d "
            "-> %s@%d -> MANIFEST_OK@%d -- the over-capacity primary was refused "
            "before staging and the backup booted",
            i_primary, err, i_err, i_backup, ues.USING_SEP, i_stage, i_ok,
        )
        fd.assert_no_read_starting_at(
            self.logger, flash, self._src,
            "the primary declared a payload larger than SEP SRAM, so "
            "validate_manifest_header must refuse the slot before the payload "
            "fetch is ever issued",
        )
