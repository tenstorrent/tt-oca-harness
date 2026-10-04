# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Load declarative SEP boot-ROM testlists."""

import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import AbstractSet

from sepvp.config import SMC_SRAM_SIZE_BYTES
from sepvp.judges import SpiReadSpan

_CLASSIFICATIONS = {
    "vp-equivalent",
    "harness-blocked",
    "model-blocked",
    "rtl-only",
    "partial",
    "retired",
}
RUNNABLE_BLOCKED = frozenset({"harness-blocked", "model-blocked", "rtl-only"})
FAMILY_ORDER = (
    "warm_reset",
    "spi_boot",
    "secure_boot_policy",
    "golden",
    "encryption",
    "manifest",
    "rom_key",
    "pubkey_revocation",
    "signature",
    "chiplet_pubkey",
    "security_version",
    "bl1_image",
    "manifest_toc",
    "payload_metadata",
    "demotion",
    "boot_source",
    "platform_gating",
    "payload_location",
    "payload_size",
    "sram_selection",
    "fuse_lock",
    "secondary_chiplet",
    "payload_limits",
    "mixed_failure",
    "measurement",
)
_RETIRED_FIELDS = {"name", "family", "tp_id", "classification", "reason", "markers"}
_XFAIL_REASON_RE = re.compile(r"\bB\d+\b")
# Cold scratch past the verdict word, SMC scratch and SMC DFX_CTRL_STATUS; the model drops ROM
# and ICCM writes, and a pre-boot write to cold scratch 0 would forge the run's verdict.
_INIT_WRITE_WINDOWS = (
    (0x10802004, 0x10802040),
    (0x40039080, 0x40039100),
    (0x4000B800, 0x4000B804),
)
_SLOTS = ("primary", "backup")
_BASE_INIS = {"secure", "insecure"}
_VERDICTS = {"PASSED", "FAILED", "none"}
_FAILED_VERDICT_TOKEN = "[VP] SIMULATION OF THE TEST FAILED"
_TESTCASE_FIELDS = {
    "name",
    "family",
    "tp_id",
    "classification",
    "image",
    "base_ini",
    "efuse",
    "observation",
    "boot",
    "rotate_update",
    "recovery",
    "timeout",
    "markers",
    "pytest_markers",
    "expect",
    "forbid",
    "expect_counts",
    "terminal_token",
    "expect_silence",
    "expect_status",
    "forbid_status",
    "expect_verdict",
    "preloaded_test_programs",
    "init_writes",
    "spi_reads",
    "spi_read_order",
    "image_asserts",
    "smc_sram_image",
    "smc_sram_source",
    "smc_sram_offset",
    "smc_sram_manifest_at",
    "measurement_golden",
    "reason",
    "xfail_reason",
    "xfail_match",
}
# Placeholder for the measurement digest, which is computed from the generated image.
MEASUREMENT_DIGEST_TOKEN = "{measurement_golden}"
_MEASUREMENT_TOKENS = (MEASUREMENT_DIGEST_TOKEN,)
_MEASUREMENT_FIELDS = {
    "slot",
    "lc_state",
    "demotion_decision",
    "secure_boot",
    "sboot_dis",
}
# Field widths of the measured scalars; a wider value would not be the value hashed.
_MEASUREMENT_LIMITS = {
    "lc_state": 0xF,
    "demotion_decision": 0x7,
    "secure_boot": 0x1,
    "sboot_dis": 0x1,
}
_SMC_SRAM_FIELDS = (
    "smc_sram_image",
    "smc_sram_source",
    "smc_sram_offset",
    "smc_sram_manifest_at",
)
_SPI_SPAN_FIELDS = {"name", "range", "exact", "min", "max"}
_IMAGE_ASSERT_FIELDS = {"range", "all", "same_as", "differs_from", "xor", "field", "toc_field"}
_IMAGE_ASSERT_MODES = ("all", "same_as", "differs_from", "field", "toc_field")
_FIELD_ASSERT_KEYS = {"name", "slot", "size", "value"}
_TOC_FIELD_ASSERT_KEYS = {"name", "slot", "entry", "size", "value"}
_STATUS_ASSERTION_RE = re.compile(r"^\S+ 0x[0-9a-fA-F]{4}$")


@dataclass(frozen=True)
class InitWrite:
    address: int
    value: int


@dataclass(frozen=True)
class FieldAssert:
    """A manifest field, named by its ``OFF_`` symbol, that must hold ``value`` in ``slot``."""

    name: str
    slot: str
    size: int
    value: int


@dataclass(frozen=True)
class TocFieldAssert:
    """A cleartext TOC entry field, named by its ``OFF_TOC_ENTRY_`` symbol, holding ``value``."""

    name: str
    slot: str
    entry: int
    size: int
    value: int


@dataclass(frozen=True)
class ImageAssert:
    """A pre-run check on the generated image; ``high=None`` means its last byte.

    ``differs_from`` is the negative control of ``same_as``; ``same_as`` with ``xor``
    requires every byte to be the reference byte XOR that mask. A ``field`` or
    ``toc_field`` check ignores ``low`` and ``high``.
    """

    low: int
    high: int | None
    all_byte: int | None
    same_as: str | None
    differs_from: str | None
    field: FieldAssert | None = None
    xor: int | None = None
    toc_field: TocFieldAssert | None = None


@dataclass(frozen=True)
class MeasurementGolden:
    """The boot state whose measurement digest a testcase asserts.

    The four scalars are the inputs BL0 hashes alongside the manifest hash of ``slot``.
    """

    slot: str
    lc_state: int
    demotion_decision: int
    secure_boot: int
    sboot_dis: int


@dataclass(frozen=True)
class RomTestCase:
    name: str
    family: str
    classification: str
    image: str | None
    base_ini: str | None
    efuse: Mapping[str, object]
    observation: str
    boot: str
    rotate_update: bool
    recovery: bool
    timeout: int
    tp_id: str | None
    markers: tuple[str, ...]
    pytest_markers: tuple[str, ...]
    expect: tuple[str, ...]
    forbid: tuple[str, ...]
    expect_counts: Mapping[str, int]
    terminal_token: str | None
    expect_silence: bool
    expect_status: tuple[str, ...]
    forbid_status: tuple[str, ...]
    expect_verdict: str | None
    preloaded_test_programs: tuple[str, ...]
    init_writes: tuple[InitWrite, ...]
    spi_reads: tuple[SpiReadSpan, ...]
    spi_read_order: tuple[str, ...]
    image_asserts: tuple[ImageAssert, ...]
    smc_sram_image: str | None
    smc_sram_source: tuple[int, int] | None
    smc_sram_offset: int | None
    smc_sram_manifest_at: int | None
    measurement_golden: MeasurementGolden | None
    reason: str | None = None
    xfail_reason: str | None = None
    xfail_match: str | None = None


def _required_string(entry: dict, field: str, name: str) -> str:
    value = entry.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"testcase {name!r} {field} must be a non-empty string")
    return value


def _string_tuple(entry: dict, field: str, name: str) -> tuple[str, ...]:
    values = entry.get(field, [])
    if not isinstance(values, list) or any(
        not isinstance(value, str) or not value.strip() for value in values
    ):
        raise ValueError(f"testcase {name!r} {field} must be an array of non-empty strings")
    return tuple(values)


def _init_writes(entry: dict, name: str) -> tuple[InitWrite, ...]:
    values = entry.get("init_writes", [])
    if not isinstance(values, list):
        raise ValueError(f"testcase {name!r} init_writes must be an array")

    writes = []
    for index, value in enumerate(values):
        if not isinstance(value, dict) or set(value) != {"address", "value"}:
            raise ValueError(
                f"testcase {name!r} init_writes[{index}] must contain address and value"
            )
        address = value["address"]
        word = value["value"]
        if type(address) is not int or not 0 <= address <= 0xFFFFFFFF:
            raise ValueError(f"testcase {name!r} init_writes[{index}] address must fit in 32 bits")
        if address % 4:
            raise ValueError(
                f"testcase {name!r} init_writes[{index}] address must be 4-byte aligned"
            )
        if type(word) is not int or not 0 <= word <= 0xFFFFFFFF:
            raise ValueError(f"testcase {name!r} init_writes[{index}] value must fit in 32 bits")
        if not any(low <= address < high for low, high in _INIT_WRITE_WINDOWS):
            raise ValueError(
                f"testcase {name!r} init_writes[{index}] address 0x{address:x} is outside the "
                "cold scratch 1-15, SMC scratch and SMC DFX status windows; cold scratch 0 "
                "holds the verdict, and ICCM contents go through preloaded_test_programs"
            )
        writes.append(InitWrite(address, word))
    return tuple(writes)


def _spi_reads(entry: dict, name: str) -> tuple[SpiReadSpan, ...]:
    values = entry.get("spi_reads", [])
    if not isinstance(values, list):
        raise ValueError(f"testcase {name!r} spi_reads must be an array")

    spans = []
    for index, value in enumerate(values):
        if not isinstance(value, dict):
            raise ValueError(f"testcase {name!r} spi_reads[{index}] must be a table")
        unknown = set(value) - _SPI_SPAN_FIELDS
        if unknown:
            raise ValueError(
                f"testcase {name!r} spi_reads[{index}] has unknown field {sorted(unknown)[0]!r}"
            )
        span = value.get("name")
        if not isinstance(span, str) or not span.strip():
            raise ValueError(
                f"testcase {name!r} spi_reads[{index}] name must be a non-empty string"
            )
        bounds = value.get("range")
        if (
            not isinstance(bounds, list)
            or len(bounds) != 2
            or any(type(edge) is not int or not 0 <= edge <= 0xFFFFFFFF for edge in bounds)
        ):
            raise ValueError(
                f"testcase {name!r} spi_reads[{span!r}] range must be two 32-bit addresses"
            )
        low, high = bounds
        if low >= high:
            raise ValueError(f"testcase {name!r} spi_reads[{span!r}] range is empty")
        counts = {key: value[key] for key in ("exact", "min", "max") if key in value}
        if not counts:
            raise ValueError(
                f"testcase {name!r} spi_reads[{span!r}] declares no exact/min/max "
                "read count, so it asserts nothing"
            )
        for key, count in counts.items():
            if type(count) is not int or count < 0:
                raise ValueError(
                    f"testcase {name!r} spi_reads[{span!r}] {key} must be a non-negative integer"
                )
        spans.append(
            SpiReadSpan(
                name=span,
                low=low,
                high=high,
                exact=counts.get("exact"),
                minimum=counts.get("min"),
                maximum=counts.get("max"),
            )
        )

    # Reads are bucketed by span name; a repeated name would merge two spans.
    names = [span.name for span in spans]
    duplicate = next((span for span in names if names.count(span) > 1), None)
    if duplicate is not None:
        raise ValueError(
            f"testcase {name!r} spi_reads has two spans named {duplicate!r}; "
            "their counts would merge"
        )
    for index, first in enumerate(spans):
        for second in spans[index + 1 :]:
            if first.low < second.high and second.low < first.high:
                raise ValueError(
                    f"testcase {name!r} spi_reads spans {first.name!r} and "
                    f"{second.name!r} overlap; a read's bucket would depend on order"
                )
    return tuple(spans)


def _field_assert(value: object, name: str, index: int) -> FieldAssert:
    where = f"testcase {name!r} image_asserts[{index}] field"
    if not isinstance(value, dict) or set(value) != _FIELD_ASSERT_KEYS:
        raise ValueError(f"{where} must contain exactly name, slot, size and value")
    symbol = value["name"]
    if (
        not isinstance(symbol, str)
        or not symbol.startswith("OFF_")
        or symbol.startswith("OFF_TOC_")
    ):
        raise ValueError(f"{where} name must be an OFF_ manifest field symbol, not OFF_TOC_")
    if value["slot"] not in _SLOTS:
        raise ValueError(f"{where} slot must be one of {list(_SLOTS)}")
    if type(value["size"]) is not int or value["size"] not in (1, 2, 4, 8):
        raise ValueError(f"{where} size must be 1, 2, 4 or 8")
    expected = value["value"]
    if type(expected) is not int or not 0 <= expected < 1 << (8 * value["size"]):
        raise ValueError(f"{where} value must fit in {value['size']} byte(s)")
    return FieldAssert(symbol, value["slot"], value["size"], expected)


def _toc_field_assert(value: object, name: str, index: int) -> TocFieldAssert:
    where = f"testcase {name!r} image_asserts[{index}] toc_field"
    if not isinstance(value, dict) or set(value) != _TOC_FIELD_ASSERT_KEYS:
        raise ValueError(f"{where} must contain exactly name, slot, entry, size and value")
    symbol = value["name"]
    if not isinstance(symbol, str) or not symbol.startswith("OFF_TOC_ENTRY_"):
        raise ValueError(f"{where} name must be an OFF_TOC_ENTRY_ field symbol")
    if value["slot"] not in _SLOTS:
        raise ValueError(f"{where} slot must be one of {list(_SLOTS)}")
    entry = value["entry"]
    if type(entry) is not int or entry < 0:
        raise ValueError(f"{where} entry must be a non-negative TOC entry index")
    if type(value["size"]) is not int or value["size"] not in (1, 2, 4, 8):
        raise ValueError(f"{where} size must be 1, 2, 4 or 8")
    expected = value["value"]
    if type(expected) is not int or not 0 <= expected < 1 << (8 * value["size"]):
        raise ValueError(f"{where} value must fit in {value['size']} byte(s)")
    return TocFieldAssert(symbol, value["slot"], entry, value["size"], expected)


def _image_asserts(entry: dict, name: str) -> tuple[ImageAssert, ...]:
    values = entry.get("image_asserts", [])
    if not isinstance(values, list):
        raise ValueError(f"testcase {name!r} image_asserts must be an array")

    checks = []
    for index, value in enumerate(values):
        if not isinstance(value, dict):
            raise ValueError(f"testcase {name!r} image_asserts[{index}] must be a table")
        unknown = set(value) - _IMAGE_ASSERT_FIELDS
        if unknown:
            raise ValueError(
                f"testcase {name!r} image_asserts[{index}] has unknown field {sorted(unknown)[0]!r}"
            )
        modes = [mode for mode in _IMAGE_ASSERT_MODES if mode in value]
        if len(modes) != 1:
            raise ValueError(
                f"testcase {name!r} image_asserts[{index}] must name exactly one of "
                "all, same_as, differs_from, field or toc_field"
            )
        if "xor" in value and modes != ["same_as"]:
            raise ValueError(f"testcase {name!r} image_asserts[{index}] xor needs same_as")
        if modes in (["field"], ["toc_field"]):
            if "range" in value:
                raise ValueError(
                    f"testcase {name!r} image_asserts[{index}] {modes[0]} check cannot "
                    "carry a range"
                )
            field = toc_field = None
            if modes == ["field"]:
                field = _field_assert(value["field"], name, index)
            else:
                toc_field = _toc_field_assert(value["toc_field"], name, index)
            checks.append(
                ImageAssert(
                    low=0,
                    high=None,
                    all_byte=None,
                    same_as=None,
                    differs_from=None,
                    field=field,
                    toc_field=toc_field,
                )
            )
            continue
        bounds = value.get("range")
        if not isinstance(bounds, list) or len(bounds) != 2:
            raise ValueError(f"testcase {name!r} image_asserts[{index}] range must be [low, high]")
        low, high = bounds
        if type(low) is not int or low < 0:
            raise ValueError(
                f"testcase {name!r} image_asserts[{index}] low bound must be a non-negative integer"
            )
        if high != "end" and type(high) is not int:
            raise ValueError(
                f"testcase {name!r} image_asserts[{index}] high bound must be an integer or 'end'"
            )
        if high != "end" and low >= high:
            raise ValueError(f"testcase {name!r} image_asserts[{index}] range is empty")

        all_byte = value.get("all")
        if all_byte is not None and (type(all_byte) is not int or not 0 <= all_byte <= 0xFF):
            raise ValueError(f"testcase {name!r} image_asserts[{index}] all must be a byte")
        xor = value.get("xor")
        # A zero mask would make the check a plain same_as under another name.
        if xor is not None and (type(xor) is not int or not 0 < xor <= 0xFF):
            raise ValueError(
                f"testcase {name!r} image_asserts[{index}] xor must be a non-zero byte"
            )
        references = {}
        for mode in ("same_as", "differs_from"):
            reference = value.get(mode)
            if reference is not None and (not isinstance(reference, str) or not reference.strip()):
                raise ValueError(
                    f"testcase {name!r} image_asserts[{index}] {mode} must name an image"
                )
            references[mode] = reference
        checks.append(
            ImageAssert(
                low=low,
                high=None if high == "end" else high,
                all_byte=all_byte,
                same_as=references["same_as"],
                differs_from=references["differs_from"],
                xor=xor,
            )
        )
    return tuple(checks)


def _smc_sram(
    entry: dict,
    name: str,
    known_images: AbstractSet[str],
    boot: str,
    recovery: bool,
    observation: str,
) -> tuple[str | None, tuple[int, int] | None, int | None, int | None]:
    """Bytes the emulated SMC leaves in its SRAM window, and where; the fields move together."""
    present = [field for field in _SMC_SRAM_FIELDS if field in entry]
    if not present:
        return None, None, None, None
    missing = [field for field in _SMC_SRAM_FIELDS if field not in entry]
    if missing:
        raise ValueError(
            f"testcase {name!r} declares {present[0]} but not {missing[0]}; the staged "
            "bytes, the range they come from and the address they are published at are "
            "one statement"
        )
    if boot != "secondary" and not recovery:
        raise ValueError(
            f'testcase {name!r} smc_sram_image needs boot = "secondary" or recovery = true; '
            "a primary chiplet outside recovery boots from SPI flash and never reads the SMC window"
        )
    if observation != "complete":
        raise ValueError(
            f'testcase {name!r} smc_sram_image needs observation = "complete"; the '
            "check that the platform actually staged the window is a complete-run judge, "
            "and without it a run whose staging silently did nothing reads an erased "
            "window and still satisfies the contract"
        )

    image = entry["smc_sram_image"]
    if not isinstance(image, str) or not image.strip():
        raise ValueError(f"testcase {name!r} smc_sram_image must be a non-empty string")
    if image not in known_images:
        raise ValueError(f"testcase {name!r} names unknown boot image {image!r}")

    bounds = entry["smc_sram_source"]
    if (
        not isinstance(bounds, list)
        or len(bounds) != 2
        or any(type(edge) is not int or edge < 0 for edge in bounds)
    ):
        raise ValueError(
            f"testcase {name!r} smc_sram_source must be two non-negative offsets into {image!r}"
        )
    low, high = bounds
    if low >= high:
        raise ValueError(f"testcase {name!r} smc_sram_source range is empty")

    offset = entry["smc_sram_offset"]
    if type(offset) is not int or not 0 <= offset < SMC_SRAM_SIZE_BYTES:
        raise ValueError(
            f"testcase {name!r} smc_sram_offset must lie inside the 1 MiB SMC SRAM window"
        )
    if offset % 4:
        raise ValueError(
            f"testcase {name!r} smc_sram_offset must be 4-byte aligned; the ROM DMAs the "
            "manifest from it"
        )
    if offset + (high - low) > SMC_SRAM_SIZE_BYTES:
        raise ValueError(
            f"testcase {name!r} smc_sram_source does not fit at smc_sram_offset "
            f"0x{offset:x}; the platform would refuse the image and the ROM would read "
            "an erased window"
        )

    manifest_at = entry["smc_sram_manifest_at"]
    if type(manifest_at) is not int or manifest_at < 0:
        raise ValueError(
            f"testcase {name!r} smc_sram_manifest_at must be a non-negative offset "
            "into the staged bytes"
        )
    if manifest_at % 4:
        raise ValueError(f"testcase {name!r} smc_sram_manifest_at must be 4-byte aligned")
    if manifest_at + 4 > high - low:
        raise ValueError(
            f"testcase {name!r} smc_sram_manifest_at 0x{manifest_at:x} lies past the "
            f"0x{high - low:x} staged bytes"
        )
    return image, (low, high), offset, manifest_at


def _measurement_golden(
    entry: dict,
    name: str,
    image: str | None,
    observation: str,
    expect: tuple[str, ...],
) -> MeasurementGolden | None:
    """The declared boot state behind a computed measurement golden.

    The spec and the placeholder token are required together: either alone asserts nothing
    real.
    """
    spec = entry.get("measurement_golden")
    placed = [token for token in _MEASUREMENT_TOKENS if token in expect]
    if spec is None:
        if placed:
            raise ValueError(
                f"testcase {name!r} expects {placed[0]} but declares no "
                "measurement_golden, so nothing computes that value"
            )
        return None
    if not isinstance(spec, dict):
        raise ValueError(f"testcase {name!r} measurement_golden must be a table")
    unknown = set(spec) - _MEASUREMENT_FIELDS
    if unknown:
        raise ValueError(
            f"testcase {name!r} measurement_golden has unknown field {sorted(unknown)[0]!r}"
        )
    missing = sorted(_MEASUREMENT_FIELDS - set(spec))
    if missing:
        raise ValueError(
            f"testcase {name!r} measurement_golden is missing {missing[0]!r}; the "
            "digest is over all four inputs plus the named slot's manifest hash"
        )
    slot = spec["slot"]
    if slot not in _SLOTS:
        raise ValueError(f"testcase {name!r} measurement_golden slot must be one of {list(_SLOTS)}")
    for field, limit in _MEASUREMENT_LIMITS.items():
        value = spec[field]
        if type(value) is not int or not 0 <= value <= limit:
            raise ValueError(
                f"testcase {name!r} measurement_golden {field} must be an integer "
                f"in 0..0x{limit:x}; measurement.h masks it to that width, so a "
                "wider value would not be the value hashed"
            )
    if image is None:
        raise ValueError(
            f"testcase {name!r} measurement_golden needs an image; the digest is "
            "taken over that image's manifest hash"
        )
    if observation != "complete":
        raise ValueError(
            f'testcase {name!r} measurement_golden needs observation = "complete"; '
            "the digest reaches the log from BL1, after every ROM token"
        )
    unplaced = [token for token in _MEASUREMENT_TOKENS if token not in expect]
    if unplaced:
        raise ValueError(
            f"testcase {name!r} declares measurement_golden but does not expect "
            f"{unplaced[0]}, so the computed digest would assert nothing"
        )
    return MeasurementGolden(
        slot=slot,
        lc_state=spec["lc_state"],
        demotion_decision=spec["demotion_decision"],
        secure_boot=spec["secure_boot"],
        sboot_dis=spec["sboot_dis"],
    )


def _spi_read_order(entry: dict, name: str, spans: tuple[SpiReadSpan, ...]) -> tuple[str, ...]:
    order = _string_tuple(entry, "spi_read_order", name)
    if order and not spans:
        raise ValueError(
            f"testcase {name!r} spi_read_order needs spi_reads; it orders spans by name"
        )
    known = {span.name for span in spans}
    unknown = next((span for span in order if span not in known), None)
    if unknown is not None:
        raise ValueError(f"testcase {name!r} spi_read_order names unknown span {unknown!r}")
    return order


def _efuse(entry: dict, name: str) -> Mapping[str, object]:
    """Fuse-map field overrides on the base profile, named as the VP fuse-map names them.

    ``lc_state`` drives both the eFuse model and the lifecycle controller.
    """
    overrides = entry.get("efuse", {})
    if not isinstance(overrides, dict):
        raise ValueError(f"testcase {name!r} efuse must be a table")

    parsed = {}
    for field, value in overrides.items():
        if not isinstance(field, str) or not field.strip():
            raise ValueError(f"testcase {name!r} efuse field names must be non-empty")
        if isinstance(value, list):
            if any(type(word) is not int for word in value):
                raise ValueError(f"testcase {name!r} efuse {field} array must hold integers")
            parsed[field] = tuple(value)
        elif type(value) is int or isinstance(value, str):
            parsed[field] = value
        else:
            raise ValueError(
                f"testcase {name!r} efuse {field} must be an integer, a symbolic "
                "name, or an array of integers"
            )
    return MappingProxyType(parsed)


def _expect_counts(entry: dict, name: str) -> Mapping[str, int]:
    counts = entry.get("expect_counts", {})
    if not isinstance(counts, dict):
        raise ValueError(f"testcase {name!r} expect_counts must be a table")
    for token, count in counts.items():
        if not isinstance(token, str) or not token.strip():
            raise ValueError(f"testcase {name!r} expect_counts keys must be non-empty strings")
        if type(count) is not int or count < 0:
            raise ValueError(
                f"testcase {name!r} expect_counts values must be non-negative integers"
            )
    return MappingProxyType(dict(counts))


def _status_tuple(entry: dict, field: str, name: str) -> tuple[str, ...]:
    statuses = _string_tuple(entry, field, name)
    if any(_STATUS_ASSERTION_RE.fullmatch(status) is None for status in statuses):
        raise ValueError(f"testcase {name!r} {field} entries must use 'SEVERITY 0xCODE'")
    return tuple(f"{severity} {code.lower()}" for severity, code in map(str.split, statuses))


def _parse_testcase(
    entry: object,
    known_programs: AbstractSet[str],
    known_images: AbstractSet[str],
) -> RomTestCase:
    if not isinstance(entry, dict):
        raise ValueError("each testcase must be a TOML table")

    unknown = set(entry) - _TESTCASE_FIELDS
    if unknown:
        raise ValueError(f"unknown field in testcase: {sorted(unknown)[0]}")

    if entry.get("classification") == "retired":
        return _retired_case(entry)

    name = _required_string(entry, "name", "<unnamed>")
    family = _required_string(entry, "family", name)
    classification = _required_string(entry, "classification", name)
    if classification not in _CLASSIFICATIONS:
        raise ValueError(
            f"testcase {name!r} classification must be one of {sorted(_CLASSIFICATIONS)}"
        )

    image = entry.get("image")
    if image is not None and (not isinstance(image, str) or not image.strip()):
        raise ValueError(f"testcase {name!r} image must be a non-empty string")
    if image is not None and image not in known_images:
        raise ValueError(f"testcase {name!r} names unknown boot image {image!r}")

    base_ini = entry.get("base_ini")
    if base_ini is not None and (not isinstance(base_ini, str) or base_ini not in _BASE_INIS):
        raise ValueError(f"testcase {name!r} base_ini must be one of {sorted(_BASE_INIS)}")

    observation = entry.get("observation", "complete")
    if observation not in ("complete", "streaming"):
        raise ValueError(f"testcase {name!r} observation must be complete or streaming")

    boot = entry.get("boot", "secondary")
    if boot not in ("primary", "secondary"):
        raise ValueError(f"testcase {name!r} boot must be primary or secondary")

    rotate_update = entry.get("rotate_update", False)
    if type(rotate_update) is not bool:
        raise ValueError(f"testcase {name!r} rotate_update must be a boolean")
    if rotate_update and boot != "primary":
        raise ValueError(
            f'testcase {name!r} rotate_update needs boot = "primary"; it reorders the '
            "SPI slot attempt, which only a primary-chiplet boot makes"
        )

    recovery = entry.get("recovery", False)
    if type(recovery) is not bool:
        raise ValueError(f"testcase {name!r} recovery must be a boolean")
    if recovery and boot != "primary":
        raise ValueError(
            f'testcase {name!r} recovery needs boot = "primary"; it makes a primary chiplet '
            "wait for the SMC manifest instead of reading SPI flash"
        )
    if recovery and rotate_update:
        raise ValueError(
            f"testcase {name!r} recovery cannot combine with rotate_update; a recovery boot "
            "never reads the SPI slots rotate_update reorders"
        )

    timeout = entry.get("timeout", 120)
    if type(timeout) is not int or timeout <= 0:
        raise ValueError(f"testcase {name!r} timeout must be a positive integer")

    tp_id = entry.get("tp_id")
    if tp_id is not None and (not isinstance(tp_id, str) or not tp_id):
        raise ValueError(f"testcase {name!r} tp_id must be a non-empty string")

    efuse = _efuse(entry, name)
    if efuse and base_ini is None:
        raise ValueError(f"testcase {name!r} efuse needs a base_ini to layer its overrides on")

    if "reason" in entry:
        raise ValueError(f"testcase {name!r} reason is only for retired entries")
    xfail_reason = entry.get("xfail_reason")
    xfail_match = entry.get("xfail_match")
    if xfail_reason is None and xfail_match is not None:
        raise ValueError(f"testcase {name!r} xfail_match needs xfail_reason")
    if xfail_reason is not None:
        if not isinstance(xfail_reason, str) or not xfail_reason.strip():
            raise ValueError(f"testcase {name!r} xfail_reason must be a non-empty string")
        if _XFAIL_REASON_RE.search(xfail_reason) is None:
            raise ValueError(f"testcase {name!r} xfail_reason must cite a DV B-number such as 'B7'")
        if not isinstance(xfail_match, str) or not xfail_match:
            raise ValueError(
                f"testcase {name!r} xfail_match must be a non-empty regex string; a sentinel "
                "must name the failure it expects"
            )
        try:
            pattern = re.compile(xfail_match)
        except re.error as error:
            raise ValueError(f"testcase {name!r} xfail_match is not a valid regex: {error}")
        if pattern.search("") is not None:
            raise ValueError(
                f"testcase {name!r} xfail_match matches an empty message, so it would "
                "accept any judge failure"
            )
        if classification in RUNNABLE_BLOCKED:
            raise ValueError(
                f"testcase {name!r} xfail_reason cannot combine with a blocked classification"
            )

    markers = _string_tuple(entry, "markers", name)
    if classification in RUNNABLE_BLOCKED and not any(
        marker.startswith("Blocked:") and marker.removeprefix("Blocked:").strip()
        for marker in markers
    ):
        raise ValueError(
            f"testcase {name!r} classification {classification!r} "
            "requires a non-empty 'Blocked:' marker"
        )

    programs = _string_tuple(entry, "preloaded_test_programs", name)
    init_writes = _init_writes(entry, name)
    unresolved = set(programs) - known_programs
    if unresolved:
        raise ValueError(
            f"testcase {name!r} names unknown preloaded test program {sorted(unresolved)[0]!r}"
        )

    expect = _string_tuple(entry, "expect", name)
    forbid = _string_tuple(entry, "forbid", name)
    overlap = set(expect) & set(forbid)
    if overlap:
        raise ValueError(
            f"testcase {name!r} token {sorted(overlap)[0]!r} appears in both expect and forbid"
        )

    expect_silence = entry.get("expect_silence", False)
    if type(expect_silence) is not bool:
        raise ValueError(f"testcase {name!r} expect_silence must be a boolean")
    if expect_silence and expect:
        raise ValueError(f"testcase {name!r} expect_silence and expect are contradictory")
    if expect_silence and not forbid:
        raise ValueError(f"testcase {name!r} expect_silence requires forbid")
    if expect_silence and not (programs or init_writes):
        raise ValueError(
            f"testcase {name!r} expect_silence requires an init-write liveness stimulus"
        )

    terminal_token = entry.get("terminal_token")
    if terminal_token is not None and (
        not isinstance(terminal_token, str) or not terminal_token.strip()
    ):
        raise ValueError(f"testcase {name!r} terminal_token must be a non-empty string")

    expect_verdict = entry.get("expect_verdict")
    if expect_verdict is not None and expect_verdict not in _VERDICTS:
        raise ValueError(f"testcase {name!r} expect_verdict must be one of {sorted(_VERDICTS)}")
    # The FAILED verdict line is also a console token; the typed verdict must agree with it.
    if _FAILED_VERDICT_TOKEN in expect and expect_verdict != "FAILED":
        raise ValueError(
            f"testcase {name!r} expects the FAILED verdict token, so it must also "
            'declare expect_verdict = "FAILED"'
        )

    expect_status = _status_tuple(entry, "expect_status", name)
    forbid_status = _status_tuple(entry, "forbid_status", name)
    expect_counts = _expect_counts(entry, name)
    spi_reads = _spi_reads(entry, name)
    spi_read_order = _spi_read_order(entry, name, spi_reads)
    image_asserts = _image_asserts(entry, name)
    if image_asserts and image is None:
        raise ValueError(f"testcase {name!r} image_asserts needs an image to check")
    smc_sram_image, smc_sram_source, smc_sram_offset, smc_sram_manifest_at = _smc_sram(
        entry, name, known_images, boot, recovery, observation
    )
    measurement_golden = _measurement_golden(entry, name, image, observation, expect)
    status_overlap = set(expect_status) & set(forbid_status)
    if status_overlap:
        raise ValueError(
            f"testcase {name!r} status {sorted(status_overlap)[0]!r} appears in both "
            "expect_status and forbid_status"
        )
    if observation == "streaming" and (
        expect_counts
        or terminal_token is not None
        or expect_silence
        or expect_status
        or forbid_status
        or spi_reads
        or expect_verdict is not None
    ):
        raise ValueError(
            f"testcase {name!r} streaming observation cannot use complete-run assertions"
        )
    if observation == "complete" and expect_verdict is None:
        raise ValueError(
            f"testcase {name!r} must declare expect_verdict; a complete run without it "
            "passes whatever verdict the firmware reports"
        )

    return RomTestCase(
        name=name,
        family=family,
        classification=classification,
        image=image,
        base_ini=base_ini,
        efuse=efuse,
        observation=observation,
        boot=boot,
        rotate_update=rotate_update,
        recovery=recovery,
        timeout=timeout,
        tp_id=tp_id,
        markers=markers,
        pytest_markers=_string_tuple(entry, "pytest_markers", name),
        expect=expect,
        forbid=forbid,
        expect_counts=expect_counts,
        terminal_token=terminal_token,
        expect_silence=expect_silence,
        expect_status=expect_status,
        forbid_status=forbid_status,
        expect_verdict=expect_verdict,
        preloaded_test_programs=programs,
        init_writes=init_writes,
        spi_reads=spi_reads,
        spi_read_order=spi_read_order,
        image_asserts=image_asserts,
        smc_sram_image=smc_sram_image,
        smc_sram_source=smc_sram_source,
        smc_sram_offset=smc_sram_offset,
        smc_sram_manifest_at=smc_sram_manifest_at,
        measurement_golden=measurement_golden,
        xfail_reason=xfail_reason,
        xfail_match=xfail_match,
    )


def _retired_case(entry: dict) -> RomTestCase:
    name = _required_string(entry, "name", "<unnamed>")
    extra = set(entry) - _RETIRED_FIELDS
    if extra:
        raise ValueError(f"testcase {name!r} is retired; it cannot declare {sorted(extra)[0]!r}")
    tp_id = entry.get("tp_id")
    if tp_id is not None and (not isinstance(tp_id, str) or not tp_id):
        raise ValueError(f"testcase {name!r} tp_id must be a non-empty string")
    return RomTestCase(
        name=name,
        family=_required_string(entry, "family", name),
        classification="retired",
        image=None,
        base_ini=None,
        efuse=MappingProxyType({}),
        observation="complete",
        boot="secondary",
        rotate_update=False,
        recovery=False,
        timeout=1,
        tp_id=tp_id,
        markers=_string_tuple(entry, "markers", name),
        pytest_markers=(),
        expect=(),
        forbid=(),
        expect_counts=MappingProxyType({}),
        terminal_token=None,
        expect_silence=False,
        expect_status=(),
        forbid_status=(),
        expect_verdict=None,
        preloaded_test_programs=(),
        init_writes=(),
        spi_reads=(),
        spi_read_order=(),
        image_asserts=(),
        smc_sram_image=None,
        smc_sram_source=None,
        smc_sram_offset=None,
        smc_sram_manifest_at=None,
        measurement_golden=None,
        reason=_required_string(entry, "reason", name),
    )


def load_testlist(
    path: str | Path,
    *,
    known_programs: AbstractSet[str] = frozenset(),
    known_images: AbstractSet[str] = frozenset(),
) -> tuple[RomTestCase, ...]:
    """Load and validate one SEP ROM testcase TOML testlist."""
    with Path(path).open("rb") as testlist_file:
        data = tomllib.load(testlist_file)

    unknown_root = set(data) - {"testcase"}
    if unknown_root:
        raise ValueError(f"unknown testlist field: {sorted(unknown_root)[0]}")

    entries = data.get("testcase")
    if not isinstance(entries, list) or not entries:
        raise ValueError("testlist must contain at least one [[testcase]]")

    testcases = tuple(_parse_testcase(entry, known_programs, known_images) for entry in entries)
    names = [testcase.name for testcase in testcases]
    duplicate = next((name for name in names if names.count(name) > 1), None)
    if duplicate is not None:
        raise ValueError(f"duplicate testcase name {duplicate!r}")
    return testcases


def load_testlist_dir(
    directory: str | Path,
    *,
    known_programs: AbstractSet[str] = frozenset(),
    known_images: AbstractSet[str] = frozenset(),
) -> tuple[RomTestCase, ...]:
    """Load every family file under *directory* in FAMILY_ORDER."""
    directory = Path(directory)
    unknown = sorted({path.stem for path in directory.glob("*.toml")} - set(FAMILY_ORDER))
    if unknown:
        raise ValueError(f"{unknown[0]}.toml is not a testlist family; add it to FAMILY_ORDER")
    testcases = []
    owner: dict[str, str] = {}
    for family in FAMILY_ORDER:
        path = directory / f"{family}.toml"
        if not path.is_file():
            raise ValueError(f"{path.name} is missing; every FAMILY_ORDER family needs its file")
        for case in load_testlist(path, known_programs=known_programs, known_images=known_images):
            if case.family != family:
                raise ValueError(
                    f"{path.name}: testcase {case.name!r} declares family {case.family!r}"
                )
            if case.name in owner:
                raise ValueError(
                    f"duplicate testcase name {case.name!r} in {owner[case.name]} and {path.name}"
                )
            owner[case.name] = path.name
            testcases.append(case)
    return tuple(testcases)
