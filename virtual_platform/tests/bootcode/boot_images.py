# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Produce the boot images a ROM testcase names, and check them before the run."""

from collections.abc import Mapping
from pathlib import Path

import boot_image_mutations
import boot_measurement_golden
import oca_image_ops
import oca_layout as L
import oca_repack
from sepvp import paths
from testlist_loader import MEASUREMENT_DIGEST_TOKEN, RomTestCase

_SLOTS = {"primary": L.PRIMARY_OFFSET, "backup": L.BACKUP_OFFSET}


def _validate(mutations: Mapping[str, boot_image_mutations.BootImageMutation]) -> None:
    """Refuse a spec that names an image or op this layer cannot produce."""
    shadowed = sorted(set(mutations) & set(paths.OCA_IMAGE_PATHS))
    if shadowed:
        raise ValueError(
            f"boot image mutation {shadowed[0]!r} shadows a prebuilt image; a testcase "
            "naming it could not say which bytes it meant"
        )
    for name, mutation in sorted(mutations.items()):
        if mutation.base is not None and mutation.base not in paths.OCA_IMAGE_PATHS:
            raise ValueError(
                f"boot image mutation {name!r} names unknown base image {mutation.base!r}; "
                f"known: {sorted(paths.OCA_IMAGE_PATHS)}"
            )
        for op in mutation.ops:
            if op.op not in oca_image_ops.OPS:
                raise ValueError(
                    f"boot image mutation {name!r} op {op.op!r} is not a whitelisted OCA op"
                )


MUTATIONS = boot_image_mutations.load_mutations()
_validate(MUTATIONS)


def known_images() -> frozenset[str]:
    return frozenset(paths.OCA_IMAGE_PATHS) | frozenset(MUTATIONS)


def _mutation(image: str):
    mutation = MUTATIONS.get(image)
    if mutation is None and image not in paths.OCA_IMAGE_PATHS:
        raise ValueError(f"unknown boot image {image!r}")
    return mutation


def missing_prebuilt(testcase: RomTestCase, oca_images: Mapping[str, Path]) -> list[str]:
    """The prebuilt images the case's run or image checks read that are not on disk."""
    names = {ref for check in testcase.image_asserts for ref in (check.same_as, check.differs_from)}
    for image in (testcase.image, testcase.smc_sram_image):
        mutation = None if image is None else _mutation(image)
        if mutation is None:
            names.add(image)
            continue
        names.add(mutation.base)
        names |= {op.args["image"] for op in mutation.ops if op.op == "graft_slot_from"}
    names.discard(None)
    return sorted(name for name in names if not Path(oca_images[name]).is_file())


def materialize_boot_image(
    image: str | None, oca_images: Mapping[str, Path], output_dir: Path
) -> Path:
    """Return the raw SPI image sep-vp boots for *image*, generating it if it is a spec."""
    if image is None:
        raise ValueError("testcase does not name a boot image")
    mutation = _mutation(image)
    if mutation is None:
        return Path(oca_images[image])

    output_dir.mkdir(parents=True, exist_ok=True)
    if mutation.pack_config is not None:
        packed = oca_repack.repack(
            image, mutation.pack_config, mutation.set, mutation.pin, output_dir
        )
        if not mutation.patch:
            return packed
        # A separate file keeps the packer's output intact for comparison.
        output = output_dir / f"{image}.patched.bin"
        data = boot_image_mutations.apply_patches(packed.read_bytes(), mutation.patch)
        output.write_bytes(data)
        return output

    data = Path(oca_images[mutation.base]).read_bytes()
    if mutation.ops:
        data = oca_image_ops.apply_ops(data, mutation.ops, images=oca_images)
    if mutation.patch:
        data = boot_image_mutations.apply_patches(data, mutation.patch)
    output = output_dir / f"{image}.bin"
    output.write_bytes(data)
    return output


def _check_field(testcase: RomTestCase, index: int, data: bytes) -> None:
    check = testcase.image_asserts[index].field
    where = f"{testcase.name} image_asserts[{index}] field {check.name} ({check.slot})"
    offset = getattr(L.C, check.name, None)
    if type(offset) is not int:
        raise AssertionError(f"{where}: no OCA manifest field of that name")
    at = _SLOTS[check.slot] + offset
    if at + check.size > len(data):
        raise AssertionError(f"{where} at 0x{at:x} runs past the 0x{len(data):x}-byte image")
    held = int.from_bytes(data[at : at + check.size], "little")
    if held != check.value:
        raise AssertionError(
            f"{where} at 0x{at:x} holds 0x{held:x}, expected 0x{check.value:x}; the "
            "image does not carry the intended stimulus"
        )


def _toc_entry_field_at(testcase: RomTestCase, index: int, data: bytes) -> int:
    """Image offset of a TOC entry field, from the slot's own payload_offset and TOC layout."""
    check = testcase.image_asserts[index].toc_field
    where = (
        f"{testcase.name} image_asserts[{index}] toc_field {check.name} entry {check.entry} "
        f"({check.slot})"
    )
    field = getattr(L.C, check.name, None)
    if type(field) is not int:
        raise AssertionError(f"{where}: no OCA TOC entry field of that name")
    if field + check.size > L.TOC_ENTRY_SIZE:
        raise AssertionError(f"{where}: {check.size} bytes at {field} run past the TOC entry")
    base = _SLOTS[check.slot]
    control = base + L.C.OFF_PAYLOAD_ENCRYPTION_CONTROL
    if int.from_bytes(data[control : control + 2], "little") != 0:
        raise AssertionError(
            f"{where}: the slot payload is encrypted, so its TOC is not in the image; "
            "assert on the ciphertext span instead"
        )
    at = base + L.OFF_PAYLOAD_OFFSET
    payload = base + int.from_bytes(data[at : at + 8], "little")
    if data[payload : payload + len(L.C.PTOC_MAGIC)] != L.C.PTOC_MAGIC:
        raise AssertionError(f"{where}: the payload at 0x{payload:x} does not start with a TOC")
    count_at = payload + L.C.OFF_TOC_IMAGE_COUNT
    count = int.from_bytes(data[count_at : count_at + 8], "little")
    if check.entry >= count:
        raise AssertionError(f"{where}: the TOC declares only {count} entries")
    return payload + L.TOC_HEADER_SIZE + check.entry * L.TOC_ENTRY_SIZE + field


def _check_toc_field(testcase: RomTestCase, index: int, data: bytes) -> None:
    check = testcase.image_asserts[index].toc_field
    at = _toc_entry_field_at(testcase, index, data)
    where = (
        f"{testcase.name} image_asserts[{index}] toc_field {check.name} entry {check.entry} "
        f"({check.slot}) at 0x{at:x}"
    )
    if at + check.size > len(data):
        raise AssertionError(f"{where} runs past the 0x{len(data):x}-byte image")
    held = int.from_bytes(data[at : at + check.size], "little")
    if held != check.value:
        raise AssertionError(
            f"{where} holds 0x{held:x}, expected 0x{check.value:x}; the image does not "
            "carry the intended stimulus"
        )


def check_image_asserts(testcase: RomTestCase, image: Path, oca_images: Mapping[str, Path]) -> None:
    """Prove the generated bytes carry the intended stimulus, before the run.

    A byte patch or op is compared only against the image it edited; a repack shares
    no bytes with anything by construction, so it may name any prebuilt image.
    """
    if not testcase.image_asserts:
        return
    data = Path(image).read_bytes()
    mutation = _mutation(testcase.image)
    if mutation is None:
        comparable = {testcase.image}
    elif mutation.pack_config is not None:
        comparable = set(paths.OCA_IMAGE_PATHS)
    else:
        comparable = {mutation.base}
    resolved: dict[str, bytes] = {}
    for index, check in enumerate(testcase.image_asserts):
        if check.field is not None:
            _check_field(testcase, index, data)
            continue
        if check.toc_field is not None:
            _check_toc_field(testcase, index, data)
            continue
        high = len(data) if check.high is None else check.high
        if not 0 <= check.low < high <= len(data):
            raise AssertionError(
                f"{testcase.name} image_asserts[{index}] range "
                f"[0x{check.low:x},0x{high:x}) is out of bounds for a "
                f"0x{len(data):x}-byte image"
            )
        span = data[check.low : high]
        if check.all_byte is not None:
            wrong = next(
                (check.low + i for i, byte in enumerate(span) if byte != check.all_byte), None
            )
            if wrong is not None:
                raise AssertionError(
                    f"{testcase.name} image_asserts[{index}] expected "
                    f"[0x{check.low:x},0x{high:x}) to be all 0x{check.all_byte:02x} "
                    f"but 0x{wrong:x} is 0x{data[wrong]:02x}; the mutation did not "
                    "produce the intended stimulus"
                )
            continue

        mode = "same_as" if check.same_as is not None else "differs_from"
        reference = check.same_as if check.same_as is not None else check.differs_from
        if reference not in comparable:
            raise AssertionError(
                f"{testcase.name} image_asserts[{index}] {mode} names {reference!r}, "
                f"which is not a base image {testcase.image!r} can be compared against "
                f"({sorted(comparable)})"
            )
        if reference not in resolved:
            resolved[reference] = Path(oca_images[reference]).read_bytes()
        base = resolved[reference]
        if check.xor is not None:
            expected = bytes(byte ^ check.xor for byte in base[check.low : high])
            if high > len(base) or span != expected:
                raise AssertionError(
                    f"{testcase.name} image_asserts[{index}] same_as {reference!r} xor "
                    f"0x{check.xor:02x} [0x{check.low:x},0x{high:x}) does not hold the "
                    "reference bytes under that mask; the mutation did not produce the "
                    "intended stimulus"
                )
            continue
        matches = high <= len(base) and base[check.low : high] == span
        if mode == "same_as" and not matches:
            raise AssertionError(
                f"{testcase.name} image_asserts[{index}] same_as "
                f"[0x{check.low:x},0x{high:x}) differs from {reference!r}; the "
                "mutation touched a region that was supposed to survive"
            )
        if mode == "differs_from" and matches:
            raise AssertionError(
                f"{testcase.name} image_asserts[{index}] differs_from "
                f"[0x{check.low:x},0x{high:x}) is identical to {reference!r}; the "
                "mutation left a region it was supposed to change"
            )


def materialize_smc_sram_image(
    testcase: RomTestCase, oca_images: Mapping[str, Path], output_dir: Path
) -> Path | None:
    """Cut the bytes the emulated SMC leaves in its SRAM window, or None if unused.

    The VP models no SMC, so a testcase names a prebuilt image and the byte range to
    take from it; the platform publishes the destination offset as MANIFEST_ADDR.
    """
    if testcase.smc_sram_image is None:
        return None
    if testcase.smc_sram_image not in paths.OCA_IMAGE_PATHS:
        raise ValueError(
            f"testcase {testcase.name!r} smc_sram_image {testcase.smc_sram_image!r} is not "
            f"a prebuilt base image ({sorted(paths.OCA_IMAGE_PATHS)}); staging a "
            "generated variant into the SMC window is not supported"
        )
    low, high = testcase.smc_sram_source
    data = Path(oca_images[testcase.smc_sram_image]).read_bytes()
    if high > len(data):
        raise ValueError(
            f"testcase {testcase.name!r} smc_sram_source [0x{low:x},0x{high:x}) runs "
            f"past {testcase.smc_sram_image!r}, which is 0x{len(data):x} bytes"
        )
    staged = data[low:high]
    _check_smc_sram_manifest(testcase, staged)
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"{testcase.name}.smc_sram.bin"
    output.write_bytes(staged)
    return output


def _check_smc_sram_manifest(testcase: RomTestCase, staged: bytes) -> None:
    """Separate a mispointed MANIFEST_ADDR from an empty window; both read as BAD_MAGIC."""
    at = testcase.smc_sram_manifest_at
    found = staged[at : at + len(L.OCAC_MAGIC)]
    if found != L.OCAC_MAGIC:
        raise AssertionError(
            f"{testcase.name} smc_sram_manifest_at 0x{at:x} holds {found!r}, not "
            f"{L.OCAC_MAGIC!r}; the staged window does not carry the manifest this "
            "testcase says it does"
        )
    if at != 0 and staged[: len(L.OCAC_MAGIC)] == L.OCAC_MAGIC:
        raise AssertionError(
            f"{testcase.name} says the ROM is pointed 0x{at:x} short of the manifest, "
            "but offset 0 of the staged window is a manifest too, so the published "
            "address is valid and the testcase proves the opposite of its name"
        )


def measurement_tokens(testcase: RomTestCase, image: Path) -> dict[str, str]:
    """The console token the declared boot state must produce, keyed by placeholder.

    Computed from the image the run is given and the declared scalars, never from a run.
    """
    spec = testcase.measurement_golden
    if spec is None:
        raise ValueError(f"testcase {testcase.name!r} declares no measurement_golden")
    pcr = boot_measurement_golden.boot_pcr(
        boot_measurement_golden.manifest_hash(Path(image).read_bytes(), spec.slot),
        lc_state=spec.lc_state,
        demotion_decision=spec.demotion_decision,
        secure_boot=spec.secure_boot,
        sboot_dis=spec.sboot_dis,
    )
    return {MEASUREMENT_DIGEST_TOKEN: boot_measurement_golden.pcr_token(pcr)}
