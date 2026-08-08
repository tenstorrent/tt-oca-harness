# SPDX-License-Identifier: Apache-2.0
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
``TIMEOUT_ENABLE``, ``CLOCK_GATE_CTRL``, …) implement a single bit today, so a
32-bit pattern reads back as just that bit.

Usage:
    from sep_reg_meta import SEP_CPU_CTRL as CPU_CTRL
    CPU_CTRL.addr("EXT_TRNG_SRC_SEL")   # 0x10A3_0190
    CPU_CTRL.reset("EXT_TRNG_SRC_SEL")  # 0x7
    CPU_CTRL.mask("EXT_TRNG_SRC_SEL")   # 0x7
"""

from __future__ import annotations

import sys
from pathlib import Path

# The generated header is not a package and is not on `python_paths`, so resolve it
# repo-relatively. This keeps the module self-contained: it works both inside a sim
# (where `cocotb/env` is on the path) and standalone, e.g. for the self-test below
# via `python3 cocotb/env/sep_reg_meta.py`.
_GEN_PY = Path(__file__).resolve().parents[3] / "regs" / "gen" / "py"
if _GEN_PY.is_dir() and str(_GEN_PY) not in sys.path:
    sys.path.insert(0, str(_GEN_PY))

import sep_reg  # noqa: E402  (path bootstrap must precede the import)

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


class RegBlock:
    """Metadata view of one generated register block (e.g. ``SEP_CPU_CTRL``)."""

    def __init__(self, block: str) -> None:
        self.block = block

    def _sym(self, name: str, suffix: str, *, alias_ok: bool):
        key = f"{self.block}_{name}_{suffix}"
        value = getattr(sep_reg, key, None)
        if value is not None:
            return value
        if alias_ok and name in _TYPE_ALIAS:
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
        """Union of the register's implemented field bits.

        Each bitfield is set to all-ones on a fresh union and the raw value is
        OR-ed in, so the result reflects the fields' real bit positions.
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
        ("TIMEOUT_ENABLE", 0x068, 0x0, 0x1),           # reserved[0:0], placeholder
        ("SEP_LOCAL_BASE_ADDR", 0x0C8, 0xD000_0000, 0xFFFF_FFFF),
        ("SEP_REGION_SIZE", 0x0D0, 0x0100_0000, 0xFFFF_FFFF),
        ("RAS_BANK_INFO", 0x170, 0x0, 0xFF),           # bank_chip[3:0] + bank_instance[7:4]
        ("SEP_NMI_VEC", 0x180, 0xC000_0100, 0xFFFF_FFFF),
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
    # type's 1-bit mask via _TYPE_ALIAS.
    for name in _TYPE_ALIAS:
        if cpu.mask32(name) != 0x1:
            failures.append(f"{name}: mask {hex(cpu.mask32(name))} != 0x1")
        if cpu.reset32(name) != 0x0:
            failures.append(f"{name}: reset {hex(cpu.reset32(name))} != 0x0")
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

    if failures:
        for line in failures:
            print(f"FAIL {line}")
        return 1
    total = len(checks) + len(_TYPE_ALIAS) + len(block_checks)
    print(f"sep_reg_meta: {total} register(s) match the generated RDL header")
    return 0


if __name__ == "__main__":
    sys.exit(_selftest())
