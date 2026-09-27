# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DV-owned apertures, PIC IDs, and mailbox constants.

``WINDOWS``, ``PIC``, mailbox sentinels, and ``OUTPUT_REMAP_REGIONS`` are
the expectation. ABR offsets come from ``abr_reg.rdl``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

_REPO = Path(__file__).resolve().parents[6]
_ABR_RDL = (
    _REPO
    / "vendor"
    / "chipsalliance"
    / "adams-bridge"
    / "upstream"
    / "src"
    / "abr_top"
    / "rtl"
    / "abr_reg.rdl"
)

# Key-Vault control register types instantiated by abr_reg.rdl.
_KV_RDL = _ABR_RDL.with_name("kv_def.rdl")

_ABR_CLOSE = re.compile(
    r"^    \} ([A-Za-z0-9_]+)(?:\[(\d+)\])?(?:\s*@(0x[0-9A-Fa-f]+))?;",
    re.M,
)
_ABR_NAMED = re.compile(
    r"^    (\w+)\s+(\w+)(?:\s*@(0x[0-9A-Fa-f]+))?;",
    re.M,
)
# Sequential `type_t name_r;` instances in `regfile intr_block_t`.
_ABR_INTR_INST = re.compile(r"^\s+\w+_t\s+(\w+_r)\s*;", re.M)


@dataclass(frozen=True)
class MapWindow:
    """One aperture. Inclusive ``end`` except SEP Local Alias (exclusive)."""

    unit: str
    base: int
    end: int
    size: int


# From hw/sys/sep/doc/memory_map.adoc.
WINDOWS = {
    "SEP Local Alias": MapWindow("SEP Local Alias", 0xD000_0000, 0x1_0000_0000, 0x3000_0000),
    "ABR": MapWindow("ABR", 0x1094_0000, 0x1094_FFFF, 0x1_0000),
    "EPOOL": MapWindow("EPOOL", 0x1095_0000, 0x1095_FFFF, 0x1_0000),
    "AP Remap Region": MapWindow("AP Remap Region", 0x1100_0000, 0x117F_FFFF, 0x80_0000),
    "STEE Remap Region": MapWindow("STEE Remap Region", 0x1180_0000, 0x11FF_FFFF, 0x80_0000),
}

# From hw/sys/sep/doc/interrupts.adoc. 1-based PIC source.
PIC = {
    "Mailbox interrupt 0": 1,
    "Mailbox interrupt 1": 2,
    "Mailbox interrupt 2": 3,
    "Mailbox interrupt 3": 4,
    "Mailbox interrupt 4": 5,
    "Mailbox interrupt 5": 6,
    "Mailbox interrupt 6": 7,
    "Mailbox interrupt 7": 8,
    "DMA transfer done": 9,
    "DMA chunk done": 10,
    "DMA error": 11,
    "SPI IRQ": 14,
    "KM mailbox IRQ": 15,
    "HMAC done": 18,
    "HMAC error": 20,
    "KMAC done": 21,
    "KMAC error": 23,
    "CSRNG command request done": 24,
    "CSRNG entropy request": 25,
    "CSRNG HW instance exception": 26,
    "CSRNG fatal error": 27,
    "EDN command request done": 28,
    "EDN fatal error": 29,
    "OTBN done": 30,
    "KM unrecoverable error": 31,
    "KM recoverable error": 32,
    "Locked field access": 34,
    "Token match fault": 40,
    "Adams Bridge error": 35,
    "Adams Bridge notification": 36,
    "Entropy pool low": 37,
    "Entropy pool fill stall": 38,
    "DMA register-path bus error": 41,
    "DMA host-path integrity/bus fault": 42,
    "Peripheral register-bridge fault": 43,
}

# From hw/ip/axi_lite_mailbox_unit/doc/{architecture,interface}.adoc.
MAILBOX_DEPTH = 8
MAILBOX_EMPTY_SENTINEL = 0xFEEDDEAD
MAILBOX_WRITE_DATA_RD_SENTINEL = 0xFEEDC0DE

# From hw/sys/sep/doc/fabric.adoc ("Sixteen remap regions").
OUTPUT_REMAP_REGIONS = 16

# DV-owned concurrency depth for the crypto CSR apertures. This is how hard
# the wide-access leaf pushes a converted aperture, NOT a hardware parameter
# and NOT a scored contract: the claim graded against it is that concurrent
# reads each return their own data, which holds at any depth. Deliberately not
# read from the converter's AxiMaxReads -- scoring "every read slot was
# occupied" against the RTL's own slot count is the DUT agreeing with itself.
# Eight is chosen because it is the most a single SEP master holds outstanding
# on this path today; raising it only strengthens the stimulus.
CRYPTO_CONCURRENT_READS = 8

# DV-owned BIW lane packing: out[i] = (b[i] * b[i+4]) + b[i+8]; out[0] is MSB.
BIW_TRIPLES = ((0, 4, 8), (1, 5, 9), (2, 6, 10), (3, 7, 11))
BIW_OUT_SHIFTS = (24, 16, 8, 0)

# KMAC / SHA-3 walk set. SHA-3 strengths and digest sizes are FIPS 202.
# SHAKE / cSHAKE accept 128 and 256 only (kmac.adoc / kmac.rdl kstrength).
# Keyed KMAC is cSHAKE plus kmac_en (kmac.adoc). KEY_LEN is a 3-bit choice
# with no RDL enum; the five widths below are the DV-owned walk.
KMAC_SHA3_STRENGTHS = (224, 256, 384, 512)
KMAC_SHA3_DIGEST_BYTES = {224: 28, 256: 32, 384: 48, 512: 64}
KMAC_XOF_STRENGTHS = (128, 256)
KMAC_KEY_LENGTHS = (128, 192, 256, 384, 512)


def window(unit: str) -> MapWindow:
    try:
        return WINDOWS[unit]
    except KeyError as exc:
        raise KeyError(f"{unit!r} missing from the DV-owned memory-map table") from exc


def pic(source: str) -> int:
    try:
        return PIC[source]
    except KeyError as exc:
        raise KeyError(f"{source!r} missing from the DV-owned PIC table") from exc


def agg_from_pic(source: str) -> int:
    """Aggregator bit = documented 1-based PIC source minus 1."""
    return pic(source) - 1


def mailbox_depth() -> int:
    return MAILBOX_DEPTH


def mailbox_empty_sentinel() -> int:
    return MAILBOX_EMPTY_SENTINEL


def mailbox_write_data_rd_sentinel() -> int:
    return MAILBOX_WRITE_DATA_RD_SENTINEL


def fabric_output_remap_regions() -> int:
    return OUTPUT_REMAP_REGIONS


@lru_cache(maxsize=1)
def abr_offsets() -> dict[str, int]:
    """CSR offsets from ``abr_reg.rdl``."""
    text = _ABR_RDL.read_text(encoding="utf-8")
    off = 0
    out: dict[str, int] = {}
    for m in _ABR_CLOSE.finditer(text):
        name, count, at = m.group(1), m.group(2), m.group(3)
        n = int(count) if count else 1
        prefix = text[: m.start()]
        last_mem = prefix.rfind("external mem")
        last_reg = max(prefix.rfind("    reg {"), prefix.rfind("    external reg"))
        is_mem = last_mem > last_reg
        mem_body = prefix[last_mem:] if is_mem else ""
        if at:
            addr = int(at, 16)
        elif is_mem:
            entries = int(re.search(r"mementries\s*=\s*(\d+)", mem_body).group(1))
            width = int(re.search(r"memwidth\s*=\s*(\d+)", mem_body).group(1))
            size = entries * (width // 8)
            align = 1 << (size - 1).bit_length()
            addr = (off + align - 1) & ~(align - 1)
        else:
            addr = off
        out[name] = addr
        if is_mem:
            entries = int(re.search(r"mementries\s*=\s*(\d+)", mem_body).group(1))
            width = int(re.search(r"memwidth\s*=\s*(\d+)", mem_body).group(1))
            off = addr + entries * (width // 8)
        else:
            off = addr + n * 4
    # `type name @addr;` instances. An instance without @addr is packed 4 bytes
    # after the previous one only when nothing but blank or comment lines lies
    # between them (a run such as the KV control block at @0xC000).
    prev_addr: int | None = None
    prev_end = 0
    for m in _ABR_NAMED.finditer(text):
        _kind, name, at = m.group(1), m.group(2), m.group(3)
        gap = re.sub(r"//[^\n]*", "", text[prev_end : m.start()]).strip()
        if at:
            prev_addr = int(at, 16)
        elif prev_addr is not None and not gap:
            prev_addr += 4
        else:
            prev_addr = None
        prev_end = m.end()
        if at:
            out[name] = prev_addr
        elif prev_addr is not None:
            out.setdefault(name, prev_addr)
    if "intr_block_rf" not in out:
        raise RuntimeError("intr_block_rf missing from abr_reg.rdl")
    # First nine packed 32-bit instances in `regfile intr_block_t`, relative
    # to `intr_block_rf`. Later counters carry explicit @ offsets.
    rf_start = text.find("regfile intr_block_t")
    rf_end = text.find("intr_block_t intr_block_rf", rf_start)
    if rf_start < 0 or rf_end < 0:
        raise RuntimeError("abr_reg.rdl is missing the interrupt register file")
    insts = _ABR_INTR_INST.findall(text[rf_start:rf_end])[:9]
    if len(insts) < 9:
        raise RuntimeError(f"abr_reg.rdl intr_block_t packed {len(insts)} instances, need 9")
    for i, name in enumerate(insts):
        out.setdefault(name, i * 4)
    return out


def abr_off(name: str) -> int:
    try:
        return abr_offsets()[name]
    except KeyError as exc:
        raise KeyError(f"{name!r} missing from abr_reg.rdl") from exc


# Implicit-packed `reg { ... } NAME;` blocks in abr_reg.rdl. Field [N] is a
# width; field [hi:lo] is an explicit range; a bare field is one bit.
_ABR_REG = re.compile(
    r"    reg \{\n(?P<body>.*?)\n    \} (?P<name>[A-Za-z0-9_]+)(?:\[\d+\])?;",
    re.S,
)
_ABR_FIELD = re.compile(
    r"field\s*\{(?P<body>[^{}]*)\}\s*(?P<name>[A-Za-z_]\w*)"
    r"(?:\s*\[(?P<hi>\d+)(?::(?P<lo>\d+))?\])?\s*=",
    re.S,
)
_ABR_CMD = re.compile(r"\[br\]\s*([01]{3})\s+for\s+([A-Za-z+]+)")
_ABR_TYPED_REG = re.compile(
    r"reg (\w+_t) \{\n(?P<body>.*?)\n        \};",
    re.S,
)
# Interrupt-block type -> the instance this package reads.
_ABR_TYPE_TO_INST = {
    "global_intr_en_t": "global_intr_en_r",
    "error_intr_en_t": "error_intr_en_r",
    "notif_intr_en_t": "notif_intr_en_r",
    "error_intr_t": "error_internal_intr_r",
    "notif_intr_t": "notif_internal_intr_r",
    "error_intr_trig_t": "error_intr_trig_r",
    "notif_intr_trig_t": "notif_intr_trig_r",
}

# Packed crypto-EDN probe word order. Consuming tests bind each name with a
# single-client beat delta before any concurrent fork.
CRYPTO_EDN_SINKS = ("aes", "kmac", "otbn_rnd", "otbn_urnd")


@lru_cache(maxsize=1)
def abr_reg_fields() -> dict[str, dict[str, tuple[int, int]]]:
    """``reg -> field -> (lsb, width)`` from ``abr_reg.rdl`` packing."""
    text = _ABR_RDL.read_text(encoding="utf-8")
    out: dict[str, dict[str, tuple[int, int]]] = {}
    for m in _ABR_REG.finditer(text):
        lsb = 0
        fields: dict[str, tuple[int, int]] = {}
        for f in _ABR_FIELD.finditer(m.group("body")):
            if f.group("hi") and f.group("lo"):
                hi, lo = int(f.group("hi")), int(f.group("lo"))
                width = hi - lo + 1
                flsb = lo
            elif f.group("hi"):
                width = int(f.group("hi"))
                flsb = lsb
            else:
                width = 1
                flsb = lsb
            fields[f.group("name")] = (flsb, width)
            lsb = flsb + width
        out[m.group("name")] = fields
    for m in _ABR_TYPED_REG.finditer(text):
        lsb = 0
        fields = {}
        for f in _ABR_FIELD.finditer(m.group("body")):
            if f.group("hi") and f.group("lo"):
                hi, lo = int(f.group("hi")), int(f.group("lo"))
                width = hi - lo + 1
                flsb = lo
            elif f.group("hi"):
                width = int(f.group("hi"))
                flsb = lsb
            else:
                width = 1
                flsb = lsb
            fields[f.group("name")] = (flsb, width)
            lsb = flsb + width
        if fields:
            out[m.group(1)] = fields
            inst = _ABR_TYPE_TO_INST.get(m.group(1))
            if inst:
                out[inst] = fields
    return out


def abr_field_lsb(reg: str, field: str) -> int:
    try:
        return abr_reg_fields()[reg][field][0]
    except KeyError as exc:
        raise KeyError(f"{reg}.{field} missing from abr_reg.rdl") from exc


_KV_REG = re.compile(r"reg (\w+)\s*(?:#\([^)]*\))?\s*\{\n(?P<body>.*?)\n    \};", re.S)


@lru_cache(maxsize=1)
def kv_reg_fields() -> dict[str, dict[str, tuple[int, int]]]:
    """``reg type -> field -> (lsb, width)`` for the flat types in ``kv_def.rdl``.

    Fields pack from bit 0 in declaration order; ``name[N]`` is N bits wide.
    A width given by a parameter takes the parameter default from the type
    header. A type whose fields carry nested braces (an enum) is skipped.
    """
    text = _KV_RDL.read_text(encoding="utf-8")
    out: dict[str, dict[str, tuple[int, int]]] = {}
    for m in _KV_REG.finditer(text):
        header = text[m.start() : m.start("body")]
        params = dict(re.findall(r"(\w+)\s*=\s*(\d+)", header))
        body = m.group("body")
        lsb = 0
        fields: dict[str, tuple[int, int]] = {}
        for f in re.finditer(
            r"field\s*\{[^{}]*\}\s*(?P<name>\w+)(?:\[(?P<w>\w+)\])?\s*=", body, re.S
        ):
            w = f.group("w")
            width = 1 if w is None else int(params[w]) if w in params else int(w)
            fields[f.group("name")] = (lsb, width)
            lsb += width
        if fields and lsb == 32:
            out[m.group(1)] = fields
    return out


def kv_field_mask(reg_type: str, field: str) -> int:
    try:
        lsb, width = kv_reg_fields()[reg_type][field]
    except KeyError as exc:
        raise KeyError(f"{reg_type}.{field} missing from kv_def.rdl") from exc
    return ((1 << width) - 1) << lsb


def abr_field_mask(reg: str, field: str) -> int:
    try:
        lsb, width = abr_reg_fields()[reg][field]
    except KeyError as exc:
        raise KeyError(f"{reg}.{field} missing from abr_reg.rdl") from exc
    return ((1 << width) - 1) << lsb


@lru_cache(maxsize=None)
def abr_ctrl_cmds(reg: str) -> dict[str, int]:
    """CTRL encodings from the ``CTRL`` field description of ``reg``."""
    fields = abr_reg_fields().get(reg)
    if not fields or "CTRL" not in fields:
        raise KeyError(f"{reg}.CTRL missing from abr_reg.rdl")
    text = _ABR_RDL.read_text(encoding="utf-8")
    block = next((m for m in _ABR_REG.finditer(text) if m.group("name") == reg), None)
    if block is None:
        raise KeyError(f"{reg} missing from abr_reg.rdl")
    ctrl = next(
        (f for f in _ABR_FIELD.finditer(block.group("body")) if f.group("name") == "CTRL"), None
    )
    if ctrl is None:
        raise KeyError(f"{reg}.CTRL field body missing from abr_reg.rdl")
    alias = {"SIGNING": "SIGN", "VERIFYING": "VERIFY"}
    cmds: dict[str, int] = {}
    for enc, label in _ABR_CMD.findall(ctrl.group("body")):
        key = alias.get(label.upper(), label.replace("+", "_").upper())
        cmds[key] = int(enc, 2)
    if not cmds:
        raise RuntimeError(f"{reg}.CTRL description has no encodings")
    return cmds


def abr_ctrl_cmd(reg: str, name: str) -> int:
    try:
        return abr_ctrl_cmds(reg)[name]
    except KeyError as exc:
        raise KeyError(f"{reg}.CTRL {name!r} missing from abr_reg.rdl") from exc


_ESRC_RDL = _REPO / "hw" / "ip" / "entropy_source" / "regs" / "entropy_source.rdl"
_KPV_RDL = _REPO / "hw" / "ip" / "key_manager" / "regs" / "km_kpv.rdl"


@lru_cache(maxsize=1)
def kpv_scrambler_ctrl_fields() -> dict[str, tuple[int, int]]:
    """``ENABLE`` / ``LOCK`` ``(lsb, width)`` from ``km_kpv.rdl``."""
    text = _KPV_RDL.read_text(encoding="utf-8")
    block = re.search(r"reg kpv_scrambler_ctrl_reg \{(.*?)\n    \};", text, re.S)
    if block is None:
        raise RuntimeError("kpv_scrambler_ctrl_reg missing from km_kpv.rdl")
    out: dict[str, tuple[int, int]] = {}
    for name, hi, lo in re.findall(r"\} (enable|lock)\[(\d+):(\d+)\]", block.group(1), re.I):
        out[name.upper()] = (int(lo), int(hi) - int(lo) + 1)
    if "ENABLE" not in out or "LOCK" not in out:
        raise RuntimeError(f"KPV_SCRAMBLER_CTRL fields incomplete: {out}")
    return out


def kpv_scrambler_ctrl_mask(name: str) -> int:
    try:
        lsb, width = kpv_scrambler_ctrl_fields()[name]
    except KeyError as exc:
        raise KeyError(f"KPV_SCRAMBLER_CTRL.{name} missing from km_kpv.rdl") from exc
    return ((1 << width) - 1) << lsb


_RDL_REG = re.compile(r"^\s*reg\s+([A-Za-z_]\w*)\s*\{", re.M)
_RDL_FIELD = re.compile(r"field\s*\{(?P<body>[^{}]*)\}\s*(?P<name>[A-Za-z_]\w*)\s*\[", re.S)


@lru_cache(maxsize=1)
def esrc_fips_locked_fields() -> dict[str, frozenset[str]]:
    """Fields FIPS_LOCK.LOCK freezes, keyed by register, from ``entropy_source.rdl``.

    The certified-configuration inventory is the set of fields the RDL marks
    ``swwel``; FIPS_LOCK's own block documents it in those terms. The generated
    Python and C exports drop ``swwel``, so the property is read from the RDL
    source, as ``abr_offsets`` reads ``abr_reg.rdl``.

    This is the DV-side expectation of what must freeze. It is deliberately not
    taken from ``entropy_source.sv``: the RTL is hand-written and maintained
    separately from this file, so a lock the RTL adds or drops on its own shows
    up here as a disagreement instead of being copied into the expectation.
    """
    text = _ESRC_RDL.read_text(encoding="utf-8")
    bounds = [(m.group(1), m.start()) for m in _RDL_REG.finditer(text)]
    out: dict[str, frozenset[str]] = {}
    for i, (reg, start) in enumerate(bounds):
        end = bounds[i + 1][1] if i + 1 < len(bounds) else len(text)
        locked = {
            f.group("name")
            for f in _RDL_FIELD.finditer(text[start:end])
            if "swwel" in f.group("body")
        }
        if locked:
            out[reg] = frozenset(locked)
    if not out:
        raise RuntimeError(
            f"no swwel fields parsed from {_ESRC_RDL}; the walked lock set would "
            "be empty and every post-lock check would pass without poking anything"
        )
    return out


def esrc_fips_locked(reg: str) -> frozenset[str]:
    """The FIPS-locked fields of one register. Raises if the register locks none."""
    try:
        return esrc_fips_locked_fields()[reg]
    except KeyError as exc:
        raise KeyError(
            f"{reg!r} has no swwel field in entropy_source.rdl; it is not part of "
            "the certified-configuration inventory FIPS_LOCK freezes"
        ) from exc


_AON_TIMER_HJSON = (
    _REPO
    / "vendor"
    / "lowRISC"
    / "opentitan"
    / "upstream"
    / "hw"
    / "ip"
    / "aon_timer"
    / "data"
    / "aon_timer.hjson"
)

_HJSON_REG = re.compile(r'\{\s*name:\s*"([A-Z0-9_]+)"', re.S)
_HJSON_REGWEN = re.compile(r'regwen:\s*"([A-Z0-9_]+)"')


@lru_cache(maxsize=1)
def aon_timer_regwen_map() -> dict[str, frozenset[str]]:
    """Registers each aon_timer regwen gates, from ``aon_timer.hjson``.

    The OpenTitan register specification is the authority for this lock map, and
    ``aon_timer_reg_top.sv`` is generated from it. Reading the description keeps
    the expectation off the generated RTL, so a hand-edit to ``src_regwen_i``
    shows up as a disagreement instead of being adopted as the golden.
    """
    text = _AON_TIMER_HJSON.read_text(encoding="utf-8")
    bounds = [(m.group(1), m.start()) for m in _HJSON_REG.finditer(text)]
    out: dict[str, set[str]] = {}
    for i, (reg, start) in enumerate(bounds):
        end = bounds[i + 1][1] if i + 1 < len(bounds) else len(text)
        gate = _HJSON_REGWEN.search(text[start:end])
        if gate:
            out.setdefault(gate.group(1), set()).add(reg)
    if not out:
        raise RuntimeError(
            f"no regwen linkage parsed from {_AON_TIMER_HJSON}; a REGWEN scope "
            "check built on an empty map would assert nothing"
        )
    return {k: frozenset(v) for k, v in out.items()}


def aon_timer_regwen_gates(regwen: str) -> frozenset[str]:
    """The registers one aon_timer regwen gates. Raises if it gates none."""
    try:
        return aon_timer_regwen_map()[regwen]
    except KeyError as exc:
        raise KeyError(f"{regwen!r} gates no register in aon_timer.hjson") from exc


# AON timer wakeup prescaler. OpenTitan "AON Timer Technical Specification",
# Wakeup timer section: "The number of cycles per tick is one more than the
# 12-bit WKUP_CTRL.prescaler field."
#
# DV-owned transcription. The rate is stated in neither aon_timer.rdl nor
# aon_timer.hjson -- both describe the field only as "Pre-scaler value for
# wakeup timer count" -- so it is carried here rather than read back from
# aon_timer_core.sv, which is the datapath under test.
AON_TIMER_PRESCALE_OFFSET = 1


def aon_timer_wkup_ticks_per_count(prescaler: int) -> int:
    """clk_aon ticks per wakeup-counter increment at this prescaler value."""
    if prescaler < 0:
        raise ValueError(f"prescaler must be non-negative, got {prescaler}")
    return prescaler + AON_TIMER_PRESCALE_OFFSET


# AMBA AXI byte-lane mapping (IHI 0022, "Data read and write structure" /
# narrow transfers): on a data bus of W bytes, a transfer is carried on the byte
# lanes selected by the low bits of the address, and WSTRB bit n asserts byte
# lane n. A 32-bit access on a 64-bit bus therefore uses lanes 0-3 when
# address[2] is 0 and lanes 4-7 when it is 1. Alignment is the protocol's, not
# any one adapter's: address[1:0] must be 0 for a 32-bit transfer.
#
# DV-owned, so a lane adapter that disagreed with AMBA is driven with a
# protocol-legal access and answers for itself, rather than defining what legal
# means.
AXI_BUS_BYTES = 8

# Read data of a JTAG access the eFuse lifecycle demux blocks:
# hw/ip/efuse/doc/architecture.adoc "the error slave returns an error response
# with data value 0xbadcab1e". Only the eFuse error slave has a specified read
# payload. The axi_filter spec (hw/ip/axi_filter/doc/index.adoc, Blocked
# Transactions) names DECERR and no data, so an inbound-filter deny is graded
# on the response and on not returning the protected value.
EFUSE_ERR_SLV_RDATA = 0xBADC_AB1E


def axi_lane_strobe(addr: int, access_bytes: int = 4, bus_bytes: int = AXI_BUS_BYTES) -> int:
    """WSTRB for an aligned ``access_bytes`` transfer at ``addr`` on the bus."""
    if access_bytes <= 0 or bus_bytes % access_bytes:
        raise ValueError(f"{access_bytes}-byte access does not divide a {bus_bytes}-byte bus")
    if addr % access_bytes:
        raise ValueError(f"0x{addr:x} is not aligned for a {access_bytes}-byte AXI transfer")
    lane = addr % bus_bytes
    return ((1 << access_bytes) - 1) << lane


def _selftest() -> None:
    assert window("ABR").base == 0x1094_0000
    assert window("EPOOL").base == 0x1095_0000
    assert pic("CSRNG command request done") == 24
    assert pic("KM mailbox IRQ") == 15
    assert agg_from_pic("KM mailbox IRQ") == 14
    assert agg_from_pic("Adams Bridge notification") == 35
    assert MAILBOX_DEPTH == 8
    assert BIW_TRIPLES[0] == (0, 4, 8)
    assert BIW_OUT_SHIFTS[0] == 24
    assert KMAC_SHA3_STRENGTHS == (224, 256, 384, 512)
    assert KMAC_XOF_STRENGTHS == (128, 256)
    assert abr_off("MLDSA_CTRL") == 0x10
    assert abr_off("MLDSA_PUBKEY") == 0x1000
    assert abr_off("kv_mldsa_seed_rd_ctrl") == 0x8000
    assert abr_off("global_intr_en_r") == 0x0
    assert abr_off("error_intr_trig_r") == 0x1C
    assert abr_field_mask("global_intr_en_r", "error_en") == 1
    assert abr_field_mask("global_intr_en_r", "notif_en") == 2
    assert abr_field_mask("error_intr_en_r", "error_internal_en") == 1
    assert abr_field_lsb("MLDSA_CTRL", "CTRL") == 0
    assert abr_field_mask("MLDSA_CTRL", "ZEROIZE") == 1 << 3
    assert abr_field_mask("MLDSA_CTRL", "EXTERNAL_MU") == 1 << 5
    assert abr_field_mask("MLDSA_STATUS", "READY") == 1 << 0
    assert abr_field_mask("MLDSA_STATUS", "VALID") == 1 << 1
    assert abr_field_mask("MLDSA_STATUS", "ERROR") == 1 << 3
    assert abr_ctrl_cmd("MLDSA_CTRL", "KEYGEN") == 1
    assert abr_ctrl_cmd("MLDSA_CTRL", "SIGN") == 2
    assert abr_ctrl_cmd("MLDSA_CTRL", "VERIFY") == 3
    assert abr_ctrl_cmd("MLKEM_CTRL", "KEYGEN") == 1
    assert abr_ctrl_cmd("MLKEM_CTRL", "ENCAPS") == 2
    assert abr_field_mask("MLKEM_CTRL", "ZEROIZE") == 1 << 3
    assert abr_field_mask("MLKEM_STATUS", "ERROR") == 1 << 2
    assert pic("Token match fault") == 40
    assert agg_from_pic("Token match fault") == 39
    assert CRYPTO_EDN_SINKS == ("aes", "kmac", "otbn_rnd", "otbn_urnd")
    assert kpv_scrambler_ctrl_mask("ENABLE") == 1
    assert kpv_scrambler_ctrl_mask("LOCK") == 2
    locked = esrc_fips_locked_fields()
    # A parse that silently matched nothing would empty the post-lock walk.
    assert len(locked) >= 10, locked
    assert sum(len(v) for v in locked.values()) >= 30
    assert esrc_fips_locked("CTRL") >= {"MODULE_ENABLE", "SHA256_WHITENING_ENABLE"}
    assert esrc_fips_locked("HEALTH_TEST_CTRL") >= {"ENABLE", "REPETITION_LIMIT"}
    assert "LOCK" not in locked.get("FIPS_LOCK", frozenset())
    assert aon_timer_regwen_gates("WDOG_REGWEN") == frozenset(
        {"WDOG_CTRL", "WDOG_BARK_THOLD", "WDOG_BITE_THOLD"}
    )
    assert "WDOG_COUNT" not in aon_timer_regwen_gates("WDOG_REGWEN")
    assert "WKUP_THOLD_LO" not in aon_timer_regwen_gates("WDOG_REGWEN")
    assert aon_timer_wkup_ticks_per_count(0) == 1
    assert aon_timer_wkup_ticks_per_count(24) == 25
    assert axi_lane_strobe(0x0) == 0x0F
    assert axi_lane_strobe(0x4) == 0xF0
    assert axi_lane_strobe(0x8) == 0x0F
    assert axi_lane_strobe(0xC) == 0xF0


_selftest()
