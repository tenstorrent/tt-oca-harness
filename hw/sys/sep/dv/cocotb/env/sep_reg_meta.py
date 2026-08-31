# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Register metadata accessor over the generated SystemRDL Python header.

Tests and sequences must NOT keep their own copies of register offsets, reset
values, or field masks. House rule: prefer source-derived expected values over
hardcoded literals). ``hw/sys/sep/regs/gen/py/sep_reg.py`` is the authoritative
machine-readable export of ``hw/sys/sep/regs/**/*.rdl``, so this module wraps it
and hands out three things per register:

* ``offset`` / ``addr`` — from ``<BLOCK>_<REG>_REG_OFFSET`` / ``_REG_ADDR``
* ``reset``  — from ``<BLOCK>_<REG>_REG_DEFAULT``
* ``mask``   — the union of the register's implemented field bits, probed from
  the generated ctypes bitfield struct. Probing (rather than summing widths)
  keeps the mask correct for registers whose fields are not bit-0-contiguous.

The mask matters because a write/readback check must compare against
``pattern & mask``: RDL placeholder registers (``TIMEOUT_COUNT``,
``TIMEOUT_ENABLE``, ``CLOCK_GATE_CTRL``, …) carry a single bit today, so a
32-bit pattern reads back as just that bit.

Two masks, deliberately distinct:
  ``mask()``     — software-usable fields only; RDL ``reserved`` fields excluded.
  ``mask_all()`` — every field bit, reserved included: the STORAGE mask.
They differ wherever a placeholder field is declared ``sw=rw`` yet named
``reserved`` (``TIMEOUT_COUNT``/``TIMEOUT_ENABLE``, sep_cpu_ctrl.rdl:76-80): real
read/write storage that software must not treat as an implemented field. Use
``mask()`` to ask "what may software use", ``mask_all()`` to ask "did the write
reach storage" — a write/readback check wants the latter.

Usage:
    from sep_reg_meta import SEP_CPU_CTRL as CPU_CTRL
    CPU_CTRL.addr("EXT_TRNG_SRC_SEL")   # 0x10A3_0190
    CPU_CTRL.reset("EXT_TRNG_SRC_SEL")  # 0x7
    CPU_CTRL.mask("EXT_TRNG_SRC_SEL")   # 0x7
"""

from __future__ import annotations

import importlib.util
import re
import sys
from dataclasses import dataclass
from pathlib import Path

# The generated header is not a package and is not on `python_paths`, so resolve it
# repo-relatively. This keeps the module self-contained: it works both inside a sim
# (where `cocotb/env` is on the path) and standalone, e.g. for the self-test below
# via `python3 cocotb/env/sep_reg_meta.py`.
_GEN_PY = Path(__file__).resolve().parents[3] / "regs" / "gen" / "py"
if _GEN_PY.is_dir() and str(_GEN_PY) not in sys.path:
    sys.path.insert(0, str(_GEN_PY))

import sep_reg  # noqa: E402  (path bootstrap must precede the import)

# RDL reserved-field names as emitted by the generator: `rsvd`, `rsvd_<n>`,
# `reserved`, `reserved_<n>`. Anchored so real fields that merely contain the
# word (`test_reserved`, `spi_control_field_en_rsvd`) are NOT excluded.
_RESERVED_FIELD_RE = re.compile(r"^(?:rsvd|reserved)(?:_\d+)?$")

# Registers whose OFFSET is emitted per instance but whose DEFAULT/struct is
# emitted once per RDL *type* (the generator does not duplicate a reused `reg`
# definition). Mapped explicitly rather than by prefix-trimming so a lookup can
# never silently resolve to a different register's reset value.
_TYPE_ALIAS = {
    "TIMEOUT_COUNT_DMA": "TIMEOUT_COUNT",
    "TIMEOUT_COUNT_SYS_IN": "TIMEOUT_COUNT",
    "TIMEOUT_COUNT_MAILBOX_INBOUND": "TIMEOUT_COUNT",
    "TIMEOUT_COUNT_MAILBOX_OUTBOUND": "TIMEOUT_COUNT",
    "TIMEOUT_COUNT_ENTROPY_WRITE": "TIMEOUT_COUNT",
    "TIMEOUT_COUNT_ENTROPY_READ": "TIMEOUT_COUNT",
    "TIMEOUT_COUNT_FILTER_OUT": "TIMEOUT_COUNT",
    "TIMEOUT_COUNT_ALIAS_REMAP": "TIMEOUT_COUNT",
}


def _default_type_keys() -> list[str]:
    """Type prefixes that have a generated ``_REG_DEFAULT`` (cached)."""
    keys = getattr(_default_type_keys, "_cache", None)
    if keys is None:
        keys = [
            n[: -len("_REG_DEFAULT")]
            for n in vars(sep_reg)
            if n.endswith("_REG_DEFAULT")
        ]
        _default_type_keys._cache = keys
    return keys


def _normalize_inst_name(name: str) -> str:
    """Drop trailing instance indices: ``SCRATCH_0_`` → ``SCRATCH``."""
    body = name.rstrip("_")
    body = re.sub(r"(?:_\d+)+$", "", body)
    return body


class RegBlock:
    """Metadata view of one generated register block (e.g. ``SEP_CPU_CTRL``)."""

    def __init__(self, block: str) -> None:
        self.block = block

    def _type_key(self, name: str) -> str | None:
        """Prefix for DEFAULT / field-struct when the instance reuses a type.

        PeakRDL emits OFFSET/ADDR per instance and DEFAULT/struct once per
        RDL type. ``WDT_TIMER.WKUP_CTRL`` therefore lives at
        ``AON_TIMER_WKUP_CTRL_*``, and ``SEP_SCRATCH_COLD.SCRATCH_0_`` at
        ``SEP_SCRATCH_SCRATCH_*``.
        """
        exact = f"{self.block}_{name}"
        if hasattr(sep_reg, f"{exact}_REG_DEFAULT"):
            return exact
        if name in _TYPE_ALIAS:
            alias = f"{self.block}_{_TYPE_ALIAS[name]}"
            if hasattr(sep_reg, f"{alias}_REG_DEFAULT"):
                return alias
        norm = _normalize_inst_name(name)
        hits = [
            key for key in _default_type_keys()
            if key.endswith("_" + norm) or key == norm
        ]
        if len(hits) == 1:
            return hits[0]
        if len(hits) > 1:
            tokens = [t for t in self.block.split("_") if t and not t.isdigit()]
            scored = [h for h in hits if any(tok in h for tok in tokens)]
            if len(scored) == 1:
                return scored[0]
        return None

    def _sym(self, name: str, suffix: str, *, alias_ok: bool):
        key = f"{self.block}_{name}_{suffix}"
        value = getattr(sep_reg, key, None)
        if value is not None:
            return value
        if alias_ok:
            type_key = self._type_key(name)
            if type_key is not None:
                value = getattr(sep_reg, f"{type_key}_{suffix}", None)
                if value is not None:
                    return value
            if name in _TYPE_ALIAS:
                alias = _TYPE_ALIAS[name]
                value = getattr(sep_reg, f"{self.block}_{alias}_{suffix}", None)
                if value is not None:
                    return value
        raise KeyError(
            f"{key} not found in the generated register header; regenerate "
            f"hw/sys/sep/regs/gen/py/sep_reg.py or add a _TYPE_ALIAS entry"
        )

    def offset(self, name: str) -> int:
        # Offsets are always emitted per instance, so no type alias applies.
        return int(self._sym(name, "REG_OFFSET", alias_ok=False))

    def addr(self, name: str) -> int:
        return int(self._sym(name, "REG_ADDR", alias_ok=False))

    def reset(self, name: str) -> int:
        return int(self._sym(name, "REG_DEFAULT", alias_ok=True))

    def mask(self, name: str) -> int:
        """Union of the register's IMPLEMENTED field bits.

        Each non-reserved bitfield is set to all-ones on a fresh union and the raw value is
        OR-ed in, so the result reflects the fields' real bit positions.

        RDL reserved fields are excluded. They appear in the generated struct
        like any other field, so OR-ing them in claims bits software cannot use.
        SEP_NMI_VEC is the worked example: its bit 0 is `rsvd`, so the
        implemented mask is 0xFFFF_FFFE, not 0xFFFF_FFFF. A register that is
        reserved end to end (TIMEOUT_COUNT -- a lone 1-bit `reserved`) then
        correctly masks to 0, which callers must treat as "nothing to prove"
        rather than as a passing check.

        Matched by exact name, not substring: `test_reserved` and
        `spi_control_field_en_rsvd` are real, software-visible fields.
        """
        struct = self._sym(name, "reg_t", alias_ok=True)
        union = getattr(sep_reg, struct.__name__.replace("_reg_t", "_reg_u"))
        bits = 0
        for field_name, _ctype, width in struct._fields_:
            if _RESERVED_FIELD_RE.match(field_name):
                continue
            view = union()
            view.val = 0
            setattr(view.f, field_name, (1 << width) - 1)
            bits |= int(view.val)
        return bits

    def mask_all(self, name: str) -> int:
        """Union of EVERY field bit, reserved included -- the storage mask.

        Distinct from mask(), which reports only software-usable fields. Use this
        when the question is "did the write reach storage", not "what may software
        use". TIMEOUT_COUNT is the case that forces the distinction: its lone
        field is declared `sw=rw; hw=r` yet named `reserved`
        (sep_cpu_ctrl.rdl:76-80), so it is real read/write storage that mask()
        must not count as implemented but a storage proof still can.
        """
        struct = self._sym(name, "reg_t", alias_ok=True)
        union = getattr(sep_reg, struct.__name__.replace("_reg_t", "_reg_u"))
        bits = 0
        for field_name, _ctype, width in struct._fields_:
            view = union()
            view.val = 0
            setattr(view.f, field_name, (1 << width) - 1)
            bits |= int(view.val)
        return bits

    def mask32_all(self, name: str) -> int:
        """Storage mask truncated to the low 32 bits (the DV access width)."""
        return self.mask_all(name) & 0xFFFF_FFFF

    def reset32(self, name: str) -> int:
        """Reset value truncated to the low 32 bits (the DV access width)."""
        return self.reset(name) & 0xFFFF_FFFF

    def mask32(self, name: str) -> int:
        """Implemented-field mask truncated to the low 32 bits."""
        return self.mask(name) & 0xFFFF_FFFF


class CHeaderRegBlock:
    """Field metadata for a block whose generated Python export omits field structs.

    Some IP blocks (entropy_source is one) emit per-field metadata only into the
    generated C header, as
    ``<BLOCK>__<REG>__<FIELD>_{bm,bp,bw,reset}`` defines. Parse those so field
    masks and reset values stay source-derived instead of being
    re-encoded as magic numbers in a sequence.

    The important primitive is :meth:`value`: build a register value from named
    fields, defaulting every unnamed field to ITS RESET. That is what keeps a
    control write from silently clearing a field the writer forgot about — e.g.
    ``entropy_source.CTRL.MODULE_ENABLE`` resets to 1, so a hand-built
    "just set the whitening bit" literal disables the whole entropy source.
    """

    _SUFFIXES = ("bm", "bp", "bw", "reset")

    def __init__(self, block: str, header: Path) -> None:
        self.block = block
        self.header = header
        self._fields: dict[str, dict[str, dict[str, int]]] = {}
        self._parse()

    def _parse(self) -> None:
        prefix = f"{self.block}__"
        for line in self.header.read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) < 3 or parts[0] != "#define" or not parts[1].startswith(prefix):
                continue
            name, raw = parts[1], parts[2]
            body = name[len(prefix):]
            for suffix in self._SUFFIXES:
                if not body.endswith("_" + suffix):
                    continue
                key = body[: -(len(suffix) + 1)]
                reg, _, field = key.partition("__")
                if not field:
                    break
                try:
                    value = int(raw, 0)
                except ValueError:
                    break
                self._fields.setdefault(reg, {}).setdefault(field, {})[suffix] = value
                break

    def fields(self, reg: str) -> dict[str, dict[str, int]]:
        try:
            return self._fields[reg]
        except KeyError as exc:
            raise KeyError(
                f"{self.block}__{reg}__* not found in {self.header}; regenerate the "
                f"register headers or check the register name"
            ) from exc

    def mask(self, reg: str) -> int:
        """Union of the register's implemented field bits."""
        return sum(meta.get("bm", 0) for meta in self.fields(reg).values())

    def reset(self, reg: str) -> int:
        """Register reset value assembled from its per-field resets."""
        total = 0
        for meta in self.fields(reg).values():
            total |= (meta.get("reset", 0) << meta.get("bp", 0)) & meta.get("bm", 0)
        return total

    def value(self, reg: str, **overrides: int) -> int:
        """Build a register value: named fields as given, the rest at their reset."""
        known = self.fields(reg)
        unknown = set(overrides) - set(known)
        if unknown:
            raise KeyError(
                f"unknown field(s) {sorted(unknown)} for {self.block}.{reg}; "
                f"known: {sorted(known)}"
            )
        total = 0
        for name, meta in known.items():
            raw = overrides.get(name, meta.get("reset", 0))
            total |= (raw << meta.get("bp", 0)) & meta.get("bm", 0)
        return total


def sym(name: str) -> int:
    """Absolute address of a symbol in the generated top-level SEP register map.

    For call sites that want a block base or a single register address by its
    generated name, e.g. ``sym("AES_REG_MAP_BASE_ADDR")``. Raises rather than
    returning a wrong value if the register flow renames or drops the symbol, so a
    map change surfaces as an import-time error instead of a silently stale
    constant.

    NOT every hex literal in the DV is an address -- SHA round constants, KAT key
    vectors and CSR bitmasks must stay literal. Only use this where the value is
    genuinely an address in the SEP memory map.
    """
    try:
        return int(getattr(sep_reg, name))
    except AttributeError as exc:
        raise KeyError(
            f"{name} not found in the generated register header "
            f"({_GEN_PY}/sep_reg.py); regenerate it or check the symbol name"
        ) from exc


def ip_c_header(ip: str) -> Path:
    """Path to hw/ip/<ip>/regs/gen/c/<ip>.h (the generated C register header)."""
    return _HW_ROOT / "ip" / ip / "regs" / "gen" / "c" / f"{ip}.h"


_HW_ROOT = Path(__file__).resolve().parents[5]
_REPO_ROOT = Path(__file__).resolve().parents[6]


@dataclass(frozen=True)
class RegInfo:
    """One generated register: address plus the two masks and the reset value."""

    block: str
    name: str
    addr: int
    reset: int
    mask: int
    mask_all: int

    @property
    def reserved(self) -> int:
        """Bits inside storage but outside the software-usable field mask."""
        return (self.mask_all & ~self.mask) & 0xFFFF_FFFF


def block_names() -> list[str]:
    """Every ``<BLOCK>_REG_MAP_BASE_ADDR`` in the generated SEP header.

    Longest name first so a later prefix match cannot steal a nested block
    (``AXIL_MAILBOX`` vs ``AXIL_MAILBOX_OUTBOUND_MAILBOX_0``).
    """
    names = [
        n[: -len("_REG_MAP_BASE_ADDR")]
        for n in vars(sep_reg)
        if n.endswith("_REG_MAP_BASE_ADDR")
    ]
    names.sort(key=len, reverse=True)
    return names


def block_size(block: str) -> int:
    """Allocated byte size of ``block`` from ``<BLOCK>_REG_MAP_SIZE``."""
    key = f"{block}_REG_MAP_SIZE"
    try:
        return int(getattr(sep_reg, key))
    except AttributeError as exc:
        raise KeyError(
            f"{key} not found in the generated register header "
            f"({_GEN_PY}/sep_reg.py); regenerate it or check the block name"
        ) from exc


def _load_py_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise FileNotFoundError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def ot_reg_map_size(ip: str) -> int:
    """Allocated byte size of an OpenTitan / IP block not in the SEP header."""
    if ip == "entropy_source":
        path = _HW_ROOT / "ip" / "entropy_source" / "regs" / "gen" / "py" / "entropy_source_reg.py"
    else:
        path = (
            _REPO_ROOT / "vendor" / "lowRISC" / "opentitan" / "overlay" / "regs"
            / ip / "regs" / "gen" / "py" / f"{ip}_reg.py"
        )
    module = _load_py_module(path, f"{ip}_reg")
    key = f"{ip.upper()}_REG_MAP_SIZE"
    try:
        return int(getattr(module, key))
    except AttributeError as exc:
        raise KeyError(f"{key} not found in {path}") from exc


def ot_reg_offsets(ip: str) -> list[tuple[str, int]]:
    """``(name, offset)`` for every ``_REG_OFFSET`` in an OT / IP header."""
    if ip == "entropy_source":
        path = _HW_ROOT / "ip" / "entropy_source" / "regs" / "gen" / "py" / "entropy_source_reg.py"
    else:
        path = (
            _REPO_ROOT / "vendor" / "lowRISC" / "opentitan" / "overlay" / "regs"
            / ip / "regs" / "gen" / "py" / f"{ip}_reg.py"
        )
    module = _load_py_module(path, f"{ip}_reg_off")
    out: list[tuple[str, int]] = []
    for name, val in vars(module).items():
        if name.endswith("_REG_OFFSET"):
            out.append((name[: -len("_REG_OFFSET")], int(val)))
    out.sort(key=lambda item: item[1])
    return out


def iter_registers() -> list[RegInfo]:
    """Every generated SEP register that has an offset, address, and reset.

    A register without ``_REG_DEFAULT`` (after ``_TYPE_ALIAS``) is skipped:
    there is no source-derived reset to check. The sweep uses this list as
    the single inventory — tests do not keep their own copies.
    """
    names = block_names()
    found: list[RegInfo] = []
    seen: set[tuple[str, str]] = set()
    for sym_name, val in vars(sep_reg).items():
        if not sym_name.endswith("_REG_OFFSET"):
            continue
        stem = sym_name[: -len("_REG_OFFSET")]
        block = None
        reg = None
        for candidate in names:
            prefix = candidate + "_"
            if stem.startswith(prefix):
                block = candidate
                reg = stem[len(prefix):]
                break
        if block is None or (block, reg) in seen:
            continue
        seen.add((block, reg))
        view = RegBlock(block)
        try:
            addr = view.addr(reg)
            reset = view.reset32(reg)
            mask = view.mask32(reg)
            mask_all = view.mask32_all(reg)
        except KeyError:
            continue
        found.append(RegInfo(block, reg, addr, reset, mask, mask_all))
    found.sort(key=lambda info: (info.addr, info.block, info.name))
    return found


def iter_addrs() -> list[tuple[str, str, int]]:
    """Every generated ``(block, name, addr)`` — DEFAULT is not required.

    Used when a watch list needs the allocated addresses (dead-space
    no-alias) even if the type default/struct is missing.
    """
    names = block_names()
    found: list[tuple[str, str, int]] = []
    seen: set[tuple[str, str]] = set()
    for sym_name in vars(sep_reg):
        if not sym_name.endswith("_REG_ADDR"):
            continue
        if sym_name.endswith("_REG_MAP_BASE_ADDR"):
            continue
        stem = sym_name[: -len("_REG_ADDR")]
        block = None
        reg = None
        for candidate in names:
            prefix = candidate + "_"
            if stem.startswith(prefix):
                block = candidate
                reg = stem[len(prefix):]
                break
        if block is None or (block, reg) in seen:
            continue
        seen.add((block, reg))
        found.append((block, reg, int(getattr(sep_reg, sym_name))))
    found.sort(key=lambda item: (item[2], item[0], item[1]))
    return found

SEP_CPU_CTRL = RegBlock("SEP_CPU_CTRL")
ENTROPY_SOURCE = CHeaderRegBlock("ENTROPY_SOURCE", ip_c_header("entropy_source"))
# Blocks the fabric walk value-checks. Others (CSRNG/EDN/AES/entropy/mailbox/…)
# are not exported by this header and stay explicit in the sequence.
SEP_RESET_CTRL = RegBlock("SEP_RESET_CTRL")
OTBN = RegBlock("OTBN")
HMAC = RegBlock("HMAC")
KMAC = RegBlock("KMAC")


def _selftest() -> int:
    """Assert the accessor against values read directly out of sep_cpu_ctrl.rdl.

    These are not a second copy of the register map — they are a handful of
    tripwires that fail loudly if the generated header stops matching the RDL
    (or if the generator changes its naming), which would otherwise silently
    weaken every source-derived checker built on this module.
    """
    cpu = SEP_CPU_CTRL
    checks = [
        # (register, offset, reset, mask)
        ("CLOCK_GATE_CTRL", 0x008, 0x0, 0x1),          # pka_cg_enable[0:0], placeholder
        ("PKA_CTRL", 0x020, 0x0, 0x7),                 # 3 x 1-bit placeholder fields
        # reserved[0:0] placeholder: real sw=rw storage, but NOT a software-usable
        # field, so the implemented mask is 0. Storage is pinned separately below.
        ("TIMEOUT_ENABLE", 0x068, 0x0, 0x0),
        ("SEP_LOCAL_BASE_ADDR", 0x0C8, 0xD000_0000, 0xFFFF_FFFF),
        ("SEP_REGION_SIZE", 0x0D0, 0x0100_0000, 0xFFFF_FFFF),
        ("SEP_NMI_VEC", 0x180, 0xC000_0100, 0xFFFF_FFFE),  # bit 0 is rsvd
        ("EXT_TRNG_SRC_SEL", 0x190, 0x7, 0x7),         # sel[2:0] = 0x7
        ("EXT_TRNG_SRC_SEL_LOCK", 0x198, 0x0, 0x1),    # distinct type, must NOT alias to _SEL
        ("SEP_VERSION_ID", 0x1000, 0xDEAD_BEEF, 0xFFFF_FFFF),
    ]
    failures = []
    for name, offset, reset, mask in checks:
        got = (cpu.offset(name), cpu.reset32(name), cpu.mask32(name))
        want = (offset, reset, mask)
        if got != want:
            failures.append(f"{name}: got {tuple(hex(v) for v in got)} want {tuple(hex(v) for v in want)}")

    # Every TIMEOUT_COUNT_* instance must resolve its own offset but share the
    # type's shape via _TYPE_ALIAS. Both masks are pinned, and the pair is what
    # makes this a tripwire for the reserved-field exclusion itself rather than a
    # re-baselined constant: the lone field is declared `sw=rw; hw=r` yet named
    # `reserved` (sep_cpu_ctrl.rdl:76-80), so it is real STORAGE (mask_all 0x1)
    # that is NOT software-usable (mask 0x0). If the generator ever renames the
    # field, or the exclusion regex stops matching it, these disagree and fail.
    for name in _TYPE_ALIAS:
        if cpu.mask32(name) != 0x0:
            failures.append(f"{name}: implemented mask {hex(cpu.mask32(name))} != 0x0")
        if cpu.mask32_all(name) != 0x1:
            failures.append(f"{name}: storage mask {hex(cpu.mask32_all(name))} != 0x1")
        if cpu.reset32(name) != 0x0:
            failures.append(f"{name}: reset {hex(cpu.reset32(name))} != 0x0")

    # Same pairing for the two named placeholders and for the one register whose
    # implemented/storage masks differ by exactly the reserved bit.
    if cpu.mask32_all("TIMEOUT_ENABLE") != 0x1:
        failures.append(
            f"TIMEOUT_ENABLE: storage mask {hex(cpu.mask32_all('TIMEOUT_ENABLE'))} != 0x1")
    if cpu.mask32_all("SEP_NMI_VEC") != 0xFFFF_FFFF:
        failures.append(
            f"SEP_NMI_VEC: storage mask {hex(cpu.mask32_all('SEP_NMI_VEC'))} != 0xffffffff")
    if cpu.offset("TIMEOUT_COUNT_DMA") == cpu.offset("TIMEOUT_COUNT_SYS_IN"):
        failures.append("TIMEOUT_COUNT_* instances collapsed to one offset")

    # Fabric-walk blocks the sequence value-checks.
    block_checks = [
        (SEP_RESET_CTRL, "SW_RESET_N", 0x1080_3000, 0x0000_001E),
        (OTBN, "INTR_STATE", 0x1090_0000, 0x0),
        (HMAC, "INTR_STATE", 0x1091_1000, 0x0),
        (KMAC, "INTR_STATE", 0x1091_3000, 0x0),
    ]
    for block, name, addr, reset in block_checks:
        got = (block.addr(name), block.reset32(name))
        if got != (addr, reset):
            failures.append(
                f"{block.block}.{name}: got {tuple(hex(v) for v in got)} "
                f"want {(hex(addr), hex(reset))}"
            )

    # An unknown register must raise, never silently return a wrong value.
    try:
        cpu.reset("NO_SUCH_REGISTER")
    except KeyError:
        pass
    else:
        failures.append("unknown register did not raise KeyError")

    regs = iter_registers()
    # Only registers with OFFSET+ADDR+DEFAULT (and a field struct) are
    # sweepable. Array instances without a per-index DEFAULT are skipped
    # on purpose rather than guessed.
    if len(regs) < 100:
        failures.append(f"iter_registers returned {len(regs)} entries; expected 100+")
    by_key = {(info.block, info.name): info for info in regs}
    nmi = by_key.get(("SEP_CPU_CTRL", "SEP_NMI_VEC"))
    if nmi is None or nmi.addr != 0x10A3_0180 or nmi.reset != 0xC000_0100:
        failures.append(f"iter_registers missed SEP_NMI_VEC: {nmi}")
    scratch = by_key.get(("SEP_SCRATCH_COLD", "SCRATCH_0_"))
    if scratch is None or scratch.addr != 0x1080_2000 or scratch.reset != 0:
        failures.append(f"iter_registers missed scratch[0]: {scratch}")
    filt = by_key.get(("INBOUND_FILTER_CTRL_0_", "FILTER_CONFIG"))
    if filt is None or (filt.reset & 0xFFFF) != 0x3000:
        failures.append(f"iter_registers missed inbound filter config: {filt}")
    if block_size("KM_MAILBOX_SEP") != 0x1C:
        failures.append(f"KM_MAILBOX_SEP size {hex(block_size('KM_MAILBOX_SEP'))} != 0x1c")
    if ot_reg_map_size("csrng") != 0x60:
        failures.append(f"csrng size {hex(ot_reg_map_size('csrng'))} != 0x60")
    if ot_reg_map_size("edn") != 0x48:
        failures.append(f"edn size {hex(ot_reg_map_size('edn'))} != 0x48")
    if ot_reg_map_size("entropy_source") != 0x17C:
        failures.append(
            f"entropy_source size {hex(ot_reg_map_size('entropy_source'))} != 0x17c")

    if failures:
        for line in failures:
            print(f"FAIL {line}")
        return 1
    total = len(checks) + len(_TYPE_ALIAS) + len(block_checks)
    print(f"sep_reg_meta: {total} register(s) match the generated RDL header")
    return 0


if __name__ == "__main__":
    sys.exit(_selftest())
