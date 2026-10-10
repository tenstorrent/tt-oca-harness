# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Cell inventory and register model of the address-map row response matrix.

Every expected value comes from generated sources, never from the DUT:

* ``hw/sys/sep/regs/gen/py/sep_memory_map.py`` (through ``env.sep_decode_resp``):
  each row's aperture, Decoded Extent and the Hole in Extent and Past Extent
  cells for a 32-bit access (``doc/trm/src/memory_map.adoc``, Decode Response
  Codes);
* ``hw/sys/sep/regs/gen/ipxact/sep.xml`` (through ``env.sep_reg_meta``): the
  register allocation of each extent, the field layout, the field access, the
  RDL reset values, and the ``volatile`` and ``readAction`` attributes;
* ``hw/sys/sep/regs/gen/py/sep_reg.py``: the memory windows of a unit
  (``<UNIT>_<NAME>_MEM_BASE_ADDR`` / ``_SIZE``).

A hole is a 32-bit word of a decoded extent that no register and no memory
window backs. A hole cell is an 8-byte word whose two halves are both holes.

A stable register has an RDL reset on every field, no ``volatile`` field (no
field that hardware updates), no ``readAction`` (no read side effect, so no
RMOD and no FIFO pop) and is not write-only. The live word of a row is the
highest-offset stable register of the extent; for the entropy source and ABR,
whose holes answer OKAY with 0, it is the highest-offset stable register with a
non-zero reset value. ABR has none (``live_word`` returns None for it), so the
leaf grades the ABR live word at the value that its hole-write control leaves
in the hole neighbour, which is non-zero.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from env.sep_decode_resp import MapRow, expected_unbacked, sep_map_rows
from sep_reg_meta import (
    _IPXACT_NS,
    HMAC,
    SEP_RESET_CTRL,
    _ipxact_num,
    _iter_ipxact_registers,
    iter_addrs,
    sep_reg,
)

NS = _IPXACT_NS

# Row keys and the base address of their row in the generated table.
ROW_BASE = {
    "dma": sep_reg.SECURE_DMA_REG_MAP_BASE_ADDR,
    "wdt": sep_reg.WDT_TIMER_REG_MAP_BASE_ADDR,
    "reset_ctrl": sep_reg.SEP_RESET_CTRL_REG_MAP_BASE_ADDR,
    "otbn": sep_reg.OTBN_REG_MAP_BASE_ADDR,
    "aes": sep_reg.AES_REG_MAP_BASE_ADDR,
    "hmac": sep_reg.HMAC_REG_MAP_BASE_ADDR,
    "kmac": sep_reg.KMAC_REG_MAP_BASE_ADDR,
    "csrng": sep_reg.CSRNG_REG_MAP_BASE_ADDR,
    "edn": sep_reg.EDN_REG_MAP_BASE_ADDR,
    "esrc": sep_reg.ENTROPY_SOURCE_REG_MAP_BASE_ADDR,
    "lc": sep_reg.SEP_LIFECYCLE_CTRL_REG_MAP_BASE_ADDR,
    "km_mbox": sep_reg.KM_MAILBOX_SEP_REG_MAP_BASE_ADDR,
    "abr": sep_reg.ABR_REG_MAP_BASE_ADDR,
}
# The 8 Reserved rows this leaf grades, by base address. Each must be a
# Reserved row of the generated table (checked by ``reserved_row``).
RESERVED_BASES = (
    0x1005_0000,
    0x1080_4000,
    0x1091_4000,
    0x1092_1000,
    0x1093_0600,
    0x1096_0000,
    0x10C0_0000,
    0x1200_0000,
)
# Rows whose past-extent cells this leaf grades from SI.
PAST_ROWS = ("dma", "wdt", "otbn", "aes", "csrng", "edn", "esrc", "lc")
# Rows whose hole-in-extent cells this leaf grades from SI.
HOLE_ROWS = ("otbn", "hmac", "kmac", "esrc", "abr")
# Rows with a live-word cell graded from SI (reset control is graded from the LSU).
LIVE_SI_ROWS = (
    "dma",
    "wdt",
    "otbn",
    "aes",
    "hmac",
    "kmac",
    "csrng",
    "edn",
    "esrc",
    "lc",
    "km_mbox",
    "abr",
)
# The crypto region (hw/sys/sep/doc/crypto.adoc, Single-Beat Access Only).
CRYPTO_LO = 0x1090_0000
CRYPTO_HI = 0x1094_FFFF
# The burst windows of the burst leg.
BURST_ROWS = ("otbn", "hmac", "kmac", "esrc", "abr")
# Units whose holes answer OKAY with 0: their live word needs a non-zero value.
NONZERO_LIVE = ("esrc", "abr")

# Reset control (hw/sys/sep/regs/gen/adoc/blocks/sep_reset_ctrl.adoc).
SW_RESET_N = SEP_RESET_CTRL.addr("SW_RESET_N")
SW_RESET_N_FIELDS = SEP_RESET_CTRL.mask("SW_RESET_N")
SW_RESET_N_REF = SEP_RESET_CTRL.reset("SW_RESET_N")

# Key Manager mailbox, SEP side (hw/ip/key_manager/regs/gen/adoc/km_mailbox_sep.adoc).
KM_WRITE_DATA = sep_reg.KM_MAILBOX_SEP_SEP_WRITE_DATA_REG_ADDR
KM_SEPARATOR = sep_reg.KM_MAILBOX_SEP_SEP_WRITE_SEPARATOR_REG_ADDR
KM_READ_DATA = sep_reg.KM_MAILBOX_SEP_SEP_READ_DATA_REG_ADDR
KM_BASELINE = (
    sep_reg.KM_MAILBOX_SEP_SEP_STATUS_REG_ADDR,
    sep_reg.KM_MAILBOX_SEP_SEP_IRQ_STATUS_REG_ADDR,
    sep_reg.KM_MAILBOX_SEP_SEP_CTRL_REG_ADDR,
    sep_reg.KM_MAILBOX_SEP_SEP_IRQ_ENABLE_REG_ADDR,
)
KM_IRQ_ENABLE = sep_reg.KM_MAILBOX_SEP_SEP_IRQ_ENABLE_REG_ADDR
KM_IRQ_ENABLE_CTL = 0x1C

# HMAC CFG one-hot fields (hmac.hjson, CFG): an unsupported value maps to None.
HMAC_CFG = sep_reg.HMAC_CFG_REG_ADDR
_HMAC_DS_LSB = HMAC.field_lsb("CFG", "digest_size")
_HMAC_DS_W = HMAC.field_width("CFG", "digest_size")
_HMAC_KL_LSB = HMAC.field_lsb("CFG", "key_length")
_HMAC_KL_W = HMAC.field_width("CFG", "key_length")
_HMAC_DS_NONE, _HMAC_KL_NONE = 0x8, 0x20
_HMAC_DS_LEGAL = (0x1, 0x2, 0x4)
_HMAC_KL_LEGAL = (0x1, 0x2, 0x4, 0x8, 0x10)

_RSVD_NAMES = ("rsvd", "reserved")


@dataclass(frozen=True)
class Field:
    name: str
    lsb: int
    width: int
    access: str
    reset: int | None
    volatile: bool
    read_action: bool
    w1c_w1s: bool

    @property
    def mask(self) -> int:
        return ((1 << self.width) - 1) << self.lsb

    @property
    def reserved(self) -> bool:
        base = self.name.lower().split("_")[0]
        return base in _RSVD_NAMES and self.reset is None


@dataclass(frozen=True)
class Reg:
    addr: int
    width: int
    name: str
    fields: tuple[Field, ...]

    @property
    def words(self) -> tuple[int, ...]:
        return tuple(self.addr + 4 * k for k in range(max(self.width // 32, 1)))

    @property
    def stable(self) -> bool:
        return (
            all(f.reset is not None for f in self.fields)
            and not any(f.volatile or f.read_action for f in self.fields)
            and not all(f.access == "write-only" for f in self.fields)
        )

    @property
    def readable(self) -> bool:
        return not any(f.read_action for f in self.fields) and not all(
            f.access == "write-only" for f in self.fields
        )

    @property
    def reset(self) -> int:
        v = 0
        for f in self.fields:
            if f.reset is not None:
                v |= (f.reset & ((1 << f.width) - 1)) << f.lsb
        return v

    def word_mask(self, addr: int) -> int:
        """RDL field bits of the 32-bit word at ``addr`` (Reserved with no reset excluded)."""
        shift = 8 * (addr - self.addr)
        m = 0
        for f in self.fields:
            if not f.reserved:
                m |= f.mask
        return (m >> shift) & 0xFFFF_FFFF

    def rw_mask(self, addr: int) -> int:
        shift = 8 * (addr - self.addr)
        m = 0
        for f in self.fields:
            if f.access == "read-write" and not f.reserved and not f.w1c_w1s:
                m |= f.mask
        return (m >> shift) & 0xFFFF_FFFF


@lru_cache(maxsize=1)
def all_regs() -> tuple[Reg, ...]:
    """Every register of the generated IP-XACT, with its field attributes."""
    names = {addr: name for _block, name, addr in iter_addrs()}
    regs = []
    for addr, width, nodes in _iter_ipxact_registers():
        fields = []
        for f in nodes:
            rst = f.find(f"{NS}resets/{NS}reset/{NS}value")
            fields.append(
                Field(
                    f.findtext(NS + "name") or "",
                    _ipxact_num(f.findtext(NS + "bitOffset")) or 0,
                    _ipxact_num(f.findtext(NS + "bitWidth")) or 1,
                    f.findtext(NS + "access") or "read-write",
                    None if rst is None else _ipxact_num(rst.text),
                    (f.findtext(NS + "volatile") or "") == "true",
                    f.find(NS + "readAction") is not None,
                    (f.findtext(NS + "modifiedWriteValue") or "") in ("oneToClear", "oneToSet"),
                )
            )
        regs.append(Reg(addr, width, names.get(addr, f"0x{addr:08x}"), tuple(fields)))
    if not regs:
        raise RuntimeError("the generated IP-XACT yielded no registers")
    return tuple(sorted(regs, key=lambda r: r.addr))


@lru_cache(maxsize=1)
def reg_by_word() -> dict[int, Reg]:
    out: dict[int, Reg] = {}
    for r in all_regs():
        for w in r.words:
            out[w] = r
    return out


@lru_cache(maxsize=1)
def mem_windows() -> tuple[tuple[str, int, int], ...]:
    """(name, base, size) of every memory window in the generated register header."""
    out = []
    for name in vars(sep_reg):
        if name.endswith("_MEM_BASE_ADDR"):
            out.append(
                (
                    name[: -len("_MEM_BASE_ADDR")],
                    int(getattr(sep_reg, name)),
                    int(getattr(sep_reg, name.replace("_BASE_ADDR", "_SIZE"))),
                )
            )
    return tuple(sorted(out, key=lambda t: t[1]))


def map_row(key_or_base) -> MapRow:
    base = ROW_BASE[key_or_base] if isinstance(key_or_base, str) else key_or_base
    for row in sep_map_rows():
        if row.base == base:
            return row
    raise KeyError(f"no memory-map row at 0x{base:08x}")


def reserved_row(base: int) -> MapRow:
    """The Reserved row at ``base``; raises if the table has another row there."""
    row = map_row(base)
    if row.unit != "Reserved":
        raise KeyError(f"memory-map row at 0x{base:08x} is {row.unit!r}, not Reserved")
    return row


def past_bounds(key: str) -> tuple[int, int, int]:
    """First past-extent byte, last 8-byte word of the row, and the next row base."""
    row = map_row(key)
    return row.base + row.extent, row.end + 1 - 8, row.end + 1


def row_regs(key: str) -> tuple[Reg, ...]:
    row = map_row(key)
    return tuple(r for r in all_regs() if row.base <= r.addr < row.base + row.extent)


def in_mem_window(addr: int) -> bool:
    return any(b <= addr < b + s for _n, b, s in mem_windows())


@lru_cache(maxsize=None)
def hole_words(key: str) -> tuple[int, ...]:
    """8-byte-aligned words of ``key`` whose two 32-bit halves are both holes."""
    row = map_row(key)
    backed = set(reg_by_word())
    out = []
    for a in range(row.base, row.base + row.extent, 8):
        if all(w not in backed and not in_mem_window(w) for w in (a, a + 4)):
            out.append(a)
    if not out:
        raise RuntimeError(f"{key}: no 8-byte hole word in the extent")
    return tuple(out)


def live_word(key: str) -> Reg | None:
    """The live word of ``key`` (see the module docstring); None when none exists."""
    if key == "reset_ctrl":
        return reg_by_word()[SW_RESET_N]
    cands = [r for r in row_regs(key) if r.stable]
    if key in NONZERO_LIVE:
        cands = [r for r in cands if r.reset & r.word_mask(r.addr)]
    return max(cands, key=lambda r: r.addr) if cands else None


def stable_regs(key: str) -> tuple[Reg, ...]:
    return tuple(r for r in row_regs(key) if r.stable)


# Burst-start registers: an RW register at an 8-byte-aligned address that the
# leaf may write and restore. The stable set is used where it has one; OTBN and
# HMAC have no stable RW register at an 8-byte-aligned address, so their start is
# a register that hardware changes only while the unit runs a command
# (LOAD_CHECKSUM: a memory write; CFG: a hash run). The units are idle here.
_IDLE_STABLE_START = {"otbn": ("LOAD_CHECKSUM",), "hmac": ("CFG",)}
# A start register whose write starts or reconfigures an operation is not drawn.
_START_EXCLUDE = ("SHADOWED", "REGWEN", "CTRL", "ENABLE", "CONF", "CONFIG", "LOCK")


def burst_start_regs(key: str) -> tuple[Reg, ...]:
    if key in _IDLE_STABLE_START:
        names = _IDLE_STABLE_START[key]
        return tuple(r for r in row_regs(key) if r.name in names and r.addr % 8 == 0)
    return tuple(
        r
        for r in stable_regs(key)
        if r.addr % 8 == 0
        and any(f.access == "read-write" for f in r.fields)
        and not set(r.name.upper().strip("_").split("_")) & set(_START_EXCLUDE)
    )


def snapshot_regs(key: str) -> tuple[Reg, ...]:
    """Registers the burst leg reads before and after a write burst."""
    regs = {r.addr: r for r in stable_regs(key)}
    for r in burst_start_regs(key):
        regs[r.addr] = r
    return tuple(regs[a] for a in sorted(regs))


def write_readback(addr: int, current: int, wdata: int) -> tuple[int, int]:
    """(expected read value, compare mask) after a 32-bit write of ``wdata``.

    RW fields take the written value, other fields keep ``current``. HMAC CFG
    maps an unsupported ``digest_size`` and ``key_length`` to None (hmac.hjson,
    CFG). The compare mask is the RDL field bits of the word.
    """
    reg = reg_by_word()[addr]
    rw = reg.rw_mask(addr)
    mask = reg.word_mask(addr)
    val = (wdata & rw) | (current & ~rw)
    if addr == HMAC_CFG:
        ds = (val >> _HMAC_DS_LSB) & ((1 << _HMAC_DS_W) - 1)
        kl = (val >> _HMAC_KL_LSB) & ((1 << _HMAC_KL_W) - 1)
        if ds not in _HMAC_DS_LEGAL:
            ds = _HMAC_DS_NONE
        if kl not in _HMAC_KL_LEGAL:
            kl = _HMAC_KL_NONE
        val &= ~(
            (((1 << _HMAC_DS_W) - 1) << _HMAC_DS_LSB) | (((1 << _HMAC_KL_W) - 1) << _HMAC_KL_LSB)
        )
        val |= (ds << _HMAC_DS_LSB) | (kl << _HMAC_KL_LSB)
    return val & 0xFFFF_FFFF, mask


def hmac_cfg_reference(rng) -> int:
    """A legal HMAC CFG value with hmac_en and sha_en clear, unlike its reset value."""
    swaps = rng.getrandbits(3) << 2
    ds = rng.choice(_HMAC_DS_LEGAL)
    kl = rng.choice(_HMAC_KL_LEGAL)
    return swaps | (ds << _HMAC_DS_LSB) | (kl << _HMAC_KL_LSB)


def word_reset(addr: int) -> int:
    reg = reg_by_word()[addr]
    return (reg.reset >> (8 * (addr - reg.addr))) & 0xFFFF_FFFF


def expected_cell(addr: int, op: str):
    """The table cell for an unbacked 32-bit word (``env.sep_decode_resp``)."""
    return expected_unbacked(addr, op)


def in_crypto_region(addr: int) -> bool:
    return CRYPTO_LO <= addr <= CRYPTO_HI
