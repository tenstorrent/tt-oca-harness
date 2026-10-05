# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Produce the boot images a ROM testcase names, and check them before the run."""

import dataclasses
from collections.abc import Mapping
from pathlib import Path

import boot_image_mutations
import boot_measurement_golden
import dv_env
import oca_image_ops
import oca_layout as L
import oca_repack
from sepvp import paths
from testlist_loader import (
    MEASUREMENT_DIGEST_TOKEN,
    RomTestCase,
    check_smc_sram_source,
    check_spi_spans,
    evaluate,
    image_placeholders,
)

_SLOTS = {"primary": L.PRIMARY_OFFSET, "backup": L.BACKUP_OFFSET}
_PM = dv_env.load("sep_payload_mutate")


class ImageFacts:
    """The testlist IMAGE_FACTS of one SPI image, read with the DV payload helpers."""

    def __init__(self, data: bytes):
        self._data = data

    def __getitem__(self, name: str) -> int:
        if name == "image_end":
            return len(self._data)
        slot, fact = name.split(".")
        start = _PM.payload_base(self._data, slot)
        if fact == "payload_start":
            return start
        if fact == "payload_end":
            return start + _PM.manifest_payload_length(self._data, slot)
        if _PM.is_encrypted(self._data, slot):
            raise AssertionError(
                f"{name}: the {slot} payload is encrypted, so its BL1 TOC entry is not in the image"
            )
        length = _PM.bl1_field(self._data, slot, _PM.E_LENGTH)
        if fact == "bl1_start":
            return start + _PM.bl1_field(self._data, slot, _PM.E_OFFSET)
        if fact == "bl1_len":
            return length
        if fact == "bl1_copy_len":
            # The ROM copies whole words.
            return (length + 3) & ~3
        if fact == "bl1_copy_src":
            return _PM.bl1_sram_source(self._data, slot)
        raise KeyError(name)


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
    names |= {
        field.value_from.image
        for check in testcase.image_asserts
        for field in (check.field, check.toc_field)
        if field is not None and field.value_from is not None
    }
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


def _held(data: bytes, at: int, size: int, where: str) -> int:
    if at + size > len(data):
        raise AssertionError(f"{where} at 0x{at:x} runs past the 0x{len(data):x}-byte image")
    return int.from_bytes(data[at : at + size], "little")


def _check_value(check, where: str, held: int, facts: ImageFacts, reference) -> None:
    """Compare a field with its literal, its image-fact expression, or the reference image."""
    if check.value_from is None:
        expected = evaluate(check.value, facts)
        source = "" if type(check.value) is int else f" ({check.value})"
    else:
        expected = reference(check.value_from)
        source = f" (as in {check.value_from.image!r})"
    if held != expected:
        raise AssertionError(
            f"{where} holds 0x{held:x}, expected 0x{expected:x}{source}; the image does not "
            "carry the intended stimulus"
        )


def _check_field(testcase: RomTestCase, index: int, data: bytes, facts, reference) -> None:
    check = testcase.image_asserts[index].field
    where = f"{testcase.name} image_asserts[{index}] field {check.name} ({check.slot})"
    offset = getattr(L.C, check.name, None)
    if type(offset) is not int:
        raise AssertionError(f"{where}: no OCA manifest field of that name")
    at = _SLOTS[check.slot] + offset
    held = _held(data, at, check.size, where)
    _check_value(
        check,
        f"{where} at 0x{at:x}",
        held,
        facts,
        lambda source: _held(reference(source.image, where), at, check.size, where),
    )


def _toc_entry_field_at(testcase: RomTestCase, index: int, data: bytes, entry: int) -> int:
    """Image offset of a TOC entry field, from the slot's own payload_offset and TOC layout."""
    check = testcase.image_asserts[index].toc_field
    where = (
        f"{testcase.name} image_asserts[{index}] toc_field {check.name} entry {entry} "
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
    if entry >= count:
        raise AssertionError(f"{where}: the TOC declares only {count} entries")
    return payload + L.TOC_HEADER_SIZE + entry * L.TOC_ENTRY_SIZE + field


def _check_toc_field(testcase: RomTestCase, index: int, data: bytes, facts, reference) -> None:
    check = testcase.image_asserts[index].toc_field
    at = _toc_entry_field_at(testcase, index, data, check.entry)
    where = (
        f"{testcase.name} image_asserts[{index}] toc_field {check.name} entry {check.entry} "
        f"({check.slot})"
    )

    def from_reference(source) -> int:
        other = reference(source.image, where)
        other_at = _toc_entry_field_at(testcase, index, other, source.entry)
        return _held(other, other_at, check.size, f"{where} in {source.image!r}")

    held = _held(data, at, check.size, where)
    _check_value(check, f"{where} at 0x{at:x}", held, facts, from_reference)


def _check_decrypt_pad(testcase: RomTestCase, index: int, data: bytes) -> None:
    """Require the slot payload's PKCS#7 pad, decrypted as the ROM would, to match ``valid``."""
    check = testcase.image_asserts[index].decrypt_pad
    valid, _plain = _PM.rom_view_decrypt(data, check.slot)
    if valid != check.valid:
        found = "a valid" if valid else "an invalid"
        raise AssertionError(
            f"{testcase.name} image_asserts[{index}] decrypt_pad ({check.slot}): the payload "
            f"decrypts to {found} PKCS#7 pad, so the ROM refuses it at a different check; "
            "the image does not carry the intended stimulus"
        )


def _range(
    testcase: RomTestCase, index: int, check, data: bytes, facts, reference
) -> tuple[int, int]:
    """Resolve a range; a fact-named bound must sit at the same offset in the reference."""
    low = evaluate(check.low, facts)
    high = len(data) if check.high is None else evaluate(check.high, facts)
    named = [bound for bound in (check.low, check.high) if type(bound) is str]
    if named and (check.same_as or check.differs_from):
        name = check.same_as or check.differs_from
        other = ImageFacts(reference(name, f"{testcase.name} image_asserts[{index}]"))
        for bound in named:
            here, there = evaluate(bound, facts), evaluate(bound, other)
            if here != there:
                raise AssertionError(
                    f"{testcase.name} image_asserts[{index}] bound {bound!r} is 0x{here:x} "
                    f"here but 0x{there:x} in {name!r}; the mutation moved the region it "
                    "compares, so the bytes are not the same region"
                )
    if not 0 <= low < high <= len(data):
        raise AssertionError(
            f"{testcase.name} image_asserts[{index}] range "
            f"[0x{low:x},0x{high:x}) is out of bounds for a "
            f"0x{len(data):x}-byte image"
        )
    return low, high


def check_image_asserts(testcase: RomTestCase, image: Path, oca_images: Mapping[str, Path]) -> None:
    """Prove the generated bytes carry the intended stimulus, before the run.

    A byte patch or op is compared only against the image it edited; a repack shares
    no bytes with anything by construction, so it may name any prebuilt image.
    """
    if not testcase.image_asserts:
        return
    data = Path(image).read_bytes()
    facts = ImageFacts(data)
    mutation = _mutation(testcase.image)
    if mutation is None:
        comparable = {testcase.image}
    elif mutation.pack_config is not None:
        comparable = set(paths.OCA_IMAGE_PATHS)
    else:
        comparable = {mutation.base}
    resolved: dict[str, bytes] = {}

    def reference(name: str, where: str) -> bytes:
        if name not in comparable:
            raise AssertionError(
                f"{where} names {name!r}, which is not a base image {testcase.image!r} can "
                f"be compared against ({sorted(comparable)})"
            )
        if name not in resolved:
            resolved[name] = Path(oca_images[name]).read_bytes()
        return resolved[name]

    for index, check in enumerate(testcase.image_asserts):
        if check.field is not None:
            _check_field(testcase, index, data, facts, reference)
            continue
        if check.toc_field is not None:
            _check_toc_field(testcase, index, data, facts, reference)
            continue
        if check.decrypt_pad is not None:
            _check_decrypt_pad(testcase, index, data)
            continue
        low, high = _range(testcase, index, check, data, facts, reference)
        span = data[low:high]
        if check.all_byte is not None:
            wrong = next((low + i for i, byte in enumerate(span) if byte != check.all_byte), None)
            if wrong is not None:
                raise AssertionError(
                    f"{testcase.name} image_asserts[{index}] expected "
                    f"[0x{low:x},0x{high:x}) to be all 0x{check.all_byte:02x} "
                    f"but 0x{wrong:x} is 0x{data[wrong]:02x}; the mutation did not "
                    "produce the intended stimulus"
                )
            continue

        mode = "same_as" if check.same_as is not None else "differs_from"
        name = check.same_as if check.same_as is not None else check.differs_from
        base = reference(name, f"{testcase.name} image_asserts[{index}] {mode}")
        if check.xor is not None:
            expected = bytes(byte ^ check.xor for byte in base[low:high])
            if high > len(base) or span != expected:
                raise AssertionError(
                    f"{testcase.name} image_asserts[{index}] same_as {name!r} xor "
                    f"0x{check.xor:02x} [0x{low:x},0x{high:x}) does not hold the "
                    "reference bytes under that mask; the mutation did not produce the "
                    "intended stimulus"
                )
            continue
        matches = high <= len(base) and base[low:high] == span
        if mode == "same_as" and not matches:
            raise AssertionError(
                f"{testcase.name} image_asserts[{index}] same_as "
                f"[0x{low:x},0x{high:x}) differs from {name!r}; the "
                "mutation touched a region that was supposed to survive"
            )
        if mode == "differs_from" and matches:
            raise AssertionError(
                f"{testcase.name} image_asserts[{index}] differs_from "
                f"[0x{low:x},0x{high:x}) is identical to {name!r}; the "
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
    data = Path(oca_images[testcase.smc_sram_image]).read_bytes()
    low, high = testcase.smc_sram_source
    if type(low) is not int or type(high) is not int:
        raise ValueError(
            f"testcase {testcase.name!r} smc_sram_source is unresolved; call resolve_case"
        )
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


def _fill_image_facts(token: str, facts: ImageFacts) -> str:
    for name in image_placeholders(token):
        token = token.replace(f"{{{name}}}", f"0x{facts[name]:08x}")
    return token


def resolve_case(
    testcase: RomTestCase, image: Path | None, oca_images: Mapping[str, Path]
) -> RomTestCase:
    """The testcase with every image fact and computed token replaced by its value.

    Facts come from the image the run boots; smc_sram_source reads the SMC SRAM image.
    """
    facts = None if image is None else ImageFacts(Path(image).read_bytes())
    measured = {} if testcase.measurement_golden is None else measurement_tokens(testcase, image)

    def token(text: str) -> str:
        return _fill_image_facts(measured.get(text, text), facts)

    spans = tuple(
        dataclasses.replace(span, low=evaluate(span.low, facts), high=evaluate(span.high, facts))
        for span in testcase.spi_reads
    )
    if spans != testcase.spi_reads:
        check_spi_spans(testcase.name, spans)

    source = testcase.smc_sram_source
    if source is not None and any(type(edge) is str for edge in source):
        staged = ImageFacts(Path(oca_images[testcase.smc_sram_image]).read_bytes())
        source = tuple(evaluate(edge, staged) for edge in source)
        check_smc_sram_source(
            testcase.name, *source, testcase.smc_sram_offset, testcase.smc_sram_manifest_at
        )

    return dataclasses.replace(
        testcase,
        expect=tuple(map(token, testcase.expect)),
        forbid=tuple(map(token, testcase.forbid)),
        expect_counts={token(text): count for text, count in testcase.expect_counts.items()},
        spi_reads=spans,
        smc_sram_source=source,
    )
