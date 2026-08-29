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
import json
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


# TODO(#1302): temporary, and DV-owned on purpose.
#
# Per-field software access lives in the RDL and only the JSON exporter emits it
# (tools/regs/rdljson.py). rdlpyhdr.py compiles the same RDL and drops `sw`,
# `woclr`, `onwrite` and `onread`, so the Python header this module otherwise
# reads cannot answer "may software write this register".
#
# The generated JSON is not usable directly: `**/regs/gen/json/**` is gitignored,
# no DV stage and no CI sim job runs `make ocah-regen-regs-json`, so on a clean
# checkout the file does not exist and every caller here fails at import. These
# are byte-identical copies committed under dv/, next to the other DV-owned
# register artifacts (models/regs/sep_external.rdl).
#
# FIXME(#1302): retire this when rdlpyhdr.py emits per-register software access: point the
# accessors below at the generated Python header and delete these files.
#
# Refresh with:
#     make ocah-regen-regs-json
#     cp hw/ip/entropy_source/regs/gen/json/entropy_source.json \
#        hw/sys/sep/dv/models/regs/entropy_source_sw_access.json
# `cmp` against that generator output is the staleness check; _json_model() also
# cross-checks every register name against the generated Python header, which IS
# regenerated and gated in CI, so an RDL edit cannot leave this copy stale and
# quiet.
_DV_MODEL_REGS = Path(__file__).resolve().parents[2] / "models" / "regs"
_JSON_EXPORTS = {
    "entropy_source": _DV_MODEL_REGS / "entropy_source_sw_access.json",
}


def _json_model(block: str) -> dict:
    """Load a DV-owned JSON register model, cross-checked and cached."""
    cache = getattr(_json_model, "_cache", None)
    if cache is None:
        cache = _json_model._cache = {}
    if block not in cache:
        try:
            path = _JSON_EXPORTS[block]
        except KeyError:
            raise KeyError(
                f"no JSON register model for {block!r}; add a copy under "
                f"{_DV_MODEL_REGS} and an entry in _JSON_EXPORTS here"
            ) from None
        if not path.is_file():
            raise FileNotFoundError(
                f"{path} is missing; refresh it from the generator -- see the "
                f"comment above _JSON_EXPORTS"
            )
        model = json.loads(path.read_text(encoding="utf-8"))
        _check_json_matches_header(block, model, path)
        cache[block] = model
    return cache[block]


def _check_json_matches_header(block: str, model: dict, path: Path) -> None:
    """Fail if the committed copy has drifted from the RDL.

    The copy is hand-refreshed, so an RDL edit would otherwise leave it stale and
    the register sweeps would exclude the wrong set without any log changing.
    The generated Python header IS regenerated and gated by the regen-regs CI
    job, so comparing against it turns a silent drift into an import failure.
    """
    header = {name for name, _off in ot_reg_offsets(block)}
    in_json = {reg["inst_name"] for reg, _fields in _iter_json_regs(model)}
    missing = header - in_json
    extra = in_json - header
    if missing or extra:
        raise RuntimeError(
            f"{path} has drifted from {block!r}: "
            f"{len(missing)} register(s) in the generated header and not the "
            f"copy {sorted(missing)[:5]}, {len(extra)} in the copy and not the "
            f"header {sorted(extra)[:5]}. Refresh the copy -- see the comment "
            f"above _JSON_EXPORTS."
        )


def _iter_json_regs(node):
    """Yield every ``reg`` node with its field children."""
    if isinstance(node, dict):
        children = node.get("children", [])
        if node.get("type") == "reg":
            yield node, [c for c in children if c.get("type") == "field"]
        for child in children:
            yield from _iter_json_regs(child)
    elif isinstance(node, list):
        for child in node:
            yield from _iter_json_regs(child)


def reg_sw_readonly(block: str) -> frozenset[str]:
    """Registers of ``block`` that software can read but never write.

    A register qualifies when every field declares ``sw_access = "r"``: no bus
    write can store into it, so it can never be the target of an aliased or
    wrapped write. entropy_source has 26 -- health-test counters, alert tallies,
    FIFO and observation status, and the component ID.

    Source is the generated JSON model, the only export that carries per-field
    software access. ``rdlpyhdr.py`` emits offsets, defaults and field structs
    and drops ``sw_access`` / ``woclr`` / ``onwrite`` / ``onread``, so a caller
    that needs access type must come here rather than infer it from a register
    name. Enable a block by adding its id to ``OCAH_REG_JSON_BLOCKS``
    (``hw/common/regs/classify.mk``) and a path to ``_JSON_EXPORTS`` above.
    """
    names = {
        reg["inst_name"]
        for reg, fields in _iter_json_regs(_json_model(block))
        if fields and all(f.get("sw_access") == "r" for f in fields)
    }
    if not names:
        raise RuntimeError(
            f"no software-read-only registers found in the {block!r} JSON model; "
            f"the export schema changed and a caller filtering on this would "
            f"silently filter nothing"
        )
    return frozenset(names)


@dataclass(frozen=True)
class RegisterWalk:
    """``_REG_OFFSET`` symbols versus the sweepable inventory."""

    regs: tuple[RegInfo, ...]
    export: int
    # Dropped OFFSET symbols, split by cause so a change of cause is visible
    # rather than absorbed into one figure. All three are real code paths.
    no_default: int = 0     # no _REG_DEFAULT / field struct, even after _TYPE_ALIAS
    unknown_block: int = 0  # the symbol stem matches no known block prefix
    duplicate: int = 0      # a (block, register) pair already walked

    @property
    def nometa(self) -> int:
        """Every OFFSET symbol not in the inventory, whatever the cause."""
        return self.no_default + self.unknown_block + self.duplicate

    @property
    def inventory(self) -> int:
        return len(self.regs)


def iter_register_walk() -> RegisterWalk:
    """Walk every generated ``_REG_OFFSET`` and keep those with addr/reset/mask.

    ``export`` is the OFFSET-symbol count. ``inventory`` is ``export - nometa``.
    A silent drop is a bug, so every dropped symbol is counted under the reason
    it was dropped for:

    * ``no_default``    -- no ``_REG_DEFAULT`` or field struct, even after
      ``_TYPE_ALIAS``, so there is no source-derived reset to check.
    * ``unknown_block`` -- the stem matches no known block prefix. Zero today;
      a new top-level RDL that is not in ``block_names()`` would land here.
    * ``duplicate``     -- the ``(block, register)`` pair was already walked.
      Zero today; a generator that emits an instance twice would land here.

    Reporting one figure would let a change of cause pass unnoticed, so the
    three are kept apart and ``nometa`` sums them.
    """
    names = block_names()
    found: list[RegInfo] = []
    seen: set[tuple[str, str]] = set()
    export = 0
    no_default = unknown_block = duplicate = 0
    for sym_name in vars(sep_reg):
        if not sym_name.endswith("_REG_OFFSET"):
            continue
        export += 1
        stem = sym_name[: -len("_REG_OFFSET")]
        block = None
        reg = None
        for candidate in names:
            prefix = candidate + "_"
            if stem.startswith(prefix):
                block = candidate
                reg = stem[len(prefix):]
                break
        if block is None:
            unknown_block += 1
            continue
        if (block, reg) in seen:
            duplicate += 1
            continue
        seen.add((block, reg))
        view = RegBlock(block)
        try:
            addr = view.addr(reg)
            reset = view.reset32(reg)
            mask = view.mask32(reg)
            mask_all = view.mask32_all(reg)
        except KeyError:
            no_default += 1
            continue
        found.append(RegInfo(block, reg, addr, reset, mask, mask_all))
    found.sort(key=lambda info: (info.addr, info.block, info.name))
    return RegisterWalk(tuple(found), export, no_default, unknown_block, duplicate)


# Registers hardware owns but never changes after reset. `sw = r` means hardware
# drives the value, so by default its value at an arbitrary read time is not the
# POR value; these are the exceptions, opted back in by name so a reset compare
# on them stays real coverage. Keyed by block.
_CONSTANT_RO: dict[str, frozenset[str]] = {
    # entropy_source.rdl COMPONENT_ID: hardwired identity, reset 0x0100_0001.
    "entropy_source": frozenset({"COMPONENT_ID"}),
}


def reg_hw_updating(block: str) -> frozenset[str]:
    """Registers whose value hardware may change while the design runs.

    ``sw = r`` minus the constants in ``_CONSTANT_RO``. Two different checks need
    this same set and must not drift apart:

    * a reset compare on one measures elapsed time, not the DUT's reset value;
    * a dead-space store compare on one measures the same drift and reports it
      as an aliased write.

    Default is "hardware may change it", so a newly added ``sw = r`` register is
    excluded until someone shows it is constant -- the safe direction.
    """
    readonly = reg_sw_readonly(block)
    constant = _CONSTANT_RO.get(block, frozenset())
    unknown = constant - readonly
    if unknown:
        raise RuntimeError(
            f"_CONSTANT_RO[{block!r}] names absent from the export: "
            f"{sorted(unknown)}; the register was renamed or its access changed"
        )
    return readonly - constant


def reg_write_destructive(block: str) -> frozenset[str]:
    """Registers a sampled value cannot be written back to.

    Covers both write-one-to-clear and write-one-to-set fields. On a `woclr`
    field every bit that read as 1 is CLEARED by the write-back, so the restore
    destroys the state it claims to put back. On a `woset` field the write-back
    is simply ignored for a sampled 0 and re-asserts for a sampled 1, so the
    register is not restored either -- entropy_source FIPS_LOCK.LOCK is the one
    instance. Anything that snapshots and restores must skip both.

    Both spellings are checked: the export carries a boolean `woclr` field AND
    an `onwrite` string ("", "woclr", "woset"), and `woset` appears only in the
    latter.

    `onread` in this export is only ever "" or "ruser", and `singlepulse` only
    appears on INTR_TEST and NOISE_OBS_CTRL.FLUSH, which callers already drop by
    name suffix, so those flavours need no entry here.
    """
    return frozenset(
        reg["inst_name"]
        for reg, fields in _iter_json_regs(_json_model(block))
        if any(f.get("woclr") or f.get("onwrite") in ("woclr", "woset")
               for f in fields)
    )


def iter_registers() -> list[RegInfo]:
    """Sweepable generated registers (those with offset, address, and reset)."""
    return list(iter_register_walk().regs)


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
        ("RAS_BANK_INFO", 0x170, 0x0, 0xFF),           # bank_chip[3:0] + bank_instance[7:4]
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

    walk = iter_register_walk()
    regs = list(walk.regs)
    # Only registers with OFFSET+ADDR+DEFAULT (and a field struct) are
    # sweepable. Array instances without a per-index DEFAULT are skipped
    # on purpose rather than guessed; the walk must count those drops.
    if walk.export != walk.inventory + walk.nometa:
        failures.append(
            f"iter_register_walk identity failed: export={walk.export} "
            f"inventory={walk.inventory} nometa={walk.nometa}"
        )
    if (walk.export, walk.inventory, walk.nometa) != (1032, 873, 159):
        failures.append(
            f"iter_register_walk counts {walk.export}/{walk.inventory}/"
            f"{walk.nometa} != 1032/873/159"
        )
    if walk.inventory < 100:
        failures.append(
            f"iter_registers returned {walk.inventory} entries; expected 100+"
        )
    esrc_ro = reg_sw_readonly("entropy_source")
    if len(esrc_ro) != 26:
        failures.append(
            f"entropy_source sw-readonly count {len(esrc_ro)} != 26"
        )
    if "HT_WATERMARK" not in esrc_ro or "HT_WATERMARK_NUM" in esrc_ro:
        failures.append(f"entropy_source sw-readonly set is wrong: {sorted(esrc_ro)}")
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
    print(
        f"sep_reg_meta: {total} register(s) match the generated RDL header; "
        f"export={walk.export} inventory={walk.inventory} nometa={walk.nometa}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(_selftest())
