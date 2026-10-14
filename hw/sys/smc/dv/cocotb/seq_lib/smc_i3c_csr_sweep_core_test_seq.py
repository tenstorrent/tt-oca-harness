# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Register sweep of the base, PIO, standby controller and controller config blocks.

Sources: base_registers.rdl, controller_config.rdl, pio_registers.rdl, standby_controller_mode.rdl
and registers.rdl of the pinned i3c-core, parsed at run time; register offsets from the generated
oca_i3c_wrap_reg.py; instance windows from the generated smc_addr.h.

A field declared without a bit range is one bit wide at bit 0.
The table holds every register of the four RDL files except the PIO queue ports and
RESET_CONTROL. A field is hardware-updated when its hw access can write it, or it carries
hwclr or hwset; such fields are read and printed, never asserted. Action fields stay at reset
in the read-write step. Fields that read with hw access na or r are asserted against the RDL
reset in every instance.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import cocotb
from cocotb.utils import get_sim_time

from .smc_addr_map import smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq

_REPO = Path(__file__).resolve().parents[6]
_RDL = _REPO / "vendor" / "chipsalliance" / "i3c-core" / "upstream" / "src" / "rdl"
_GEN_PY = _REPO / "hw" / "ip" / "i3ccore_wrap" / "regs" / "gen" / "py" / "oca_i3c_wrap_reg.py"

# (block label, RDL file stem, prefix of its registers in the generated map)
_BLOCKS = (
    ("BASE", "base_registers", "I3CBASE"),
    ("PIO", "pio_registers", "PIOCONTROL"),
    ("STBY", "standby_controller_mode", "I3C_EC_STDBYCTRLMODE"),
    ("CTRLCFG", "controller_config", "I3C_EC_CTRLCFG"),
)
_EXCLUDED = {
    "COMMAND_PORT": "queue port with access side effects",
    "RESPONSE_PORT": "queue port with access side effects",
    "TX_DATA_PORT": "queue port with access side effects",
    "RX_DATA_PORT": "queue port with access side effects",
    "IBI_PORT": "queue port with access side effects",
    "RESET_CONTROL": "SOFT_RST behaviour open (owner value pending)",
}
_ACTION = {
    ("HC_CONTROL", "BUS_ENABLE"),
    ("HC_CONTROL", "RESUME"),
    ("HC_CONTROL", "ABORT"),
    ("PIO_CONTROL", "ABORT"),
    ("PIO_CONTROL", "RS"),
    ("PIO_CONTROL", "ENABLE"),
    ("STBY_CR_CONTROL", "STBY_CR_ENABLE_INIT"),
    ("STBY_CR_CONTROL", "CR_REQUEST_SEND"),
    ("STBY_CR_CONTROL", "HANDOFF_DEEP_SLEEP"),
}
_STEPS = ("S1", "S2", "S3", "S4", "S5", "S6")
_FENCE = {
    "S1": "TABLE_PARSED",
    "S2": "RESET_SWEPT",
    "S3": "RO_SWEPT",
    "S4": "RW_SWEPT",
    "S5": "W1C_SWEPT",
    "S6": "ISOLATION_SWEPT",
}
_WORD = 0xFFFF_FFFF
_PATTERN = 0x5555_5555

_FIELD_RE = re.compile(r"\bfield\s*\{([^{}]*)\}\s*(\w+)\s*(?:\[\s*(\d+)\s*:\s*(\d+)\s*\])?\s*;")
_TAIL_RE = re.compile(r"\s*(\w+)\s*(?:@\s*0x[0-9A-Fa-f]+)?\s*;")
_RESET_RE = re.compile(r"\breset\s*=\s*\d+'([hbd])\s*([0-9A-Fa-f_]+)\s*;")
_TERNARY_RE = re.compile(r"(\w+)\s*\?\s*(\w+)\s*:\s*(\w+)")


@dataclass
class Field:
    name: str
    msb: int
    lsb: int
    sw: str
    hw: str
    reset: int
    onwrite: str
    intr: bool
    hw_updated: bool

    @property
    def width(self) -> int:
        return self.msb - self.lsb + 1

    @property
    def mask(self) -> int:
        return ((1 << self.width) - 1) << self.lsb

    @property
    def stable(self) -> bool:
        """Read value is asserted: hardware never writes the field."""
        return not self.hw_updated


@dataclass
class Reg:
    block: str
    name: str
    offset: int
    fields: list[Field] = field(default_factory=list)

    @property
    def reset_word(self) -> int:
        return sum(f.reset << f.lsb for f in self.fields)

    def mask_of(self, pick) -> int:
        return sum(f.mask for f in self.fields if pick(f))

    def is_action(self, f: Field) -> bool:
        return (self.name, f.name) in _ACTION

    def in_scope(self, f: Field) -> bool:
        return f.sw == "rw" and f.stable and not f.onwrite and not self.is_action(f)

    @property
    def scope_mask(self) -> int:
        return self.mask_of(self.in_scope)

    @property
    def stable_mask(self) -> int:
        return self.mask_of(lambda f: f.stable)


def _strip(text: str) -> str:
    text = re.sub(r'"[^"]*"', '""', text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


def _params() -> dict[str, str]:
    """Boolean parameters the BaseRegs instance in registers.rdl is elaborated with."""
    text = _strip((_RDL / "registers.rdl").read_text(encoding="utf-8"))
    return dict(re.findall(r"\.(\w+)\(\s*(true|false)\s*\)", text))


def _resolve(expr: str, params: dict[str, str]) -> str:
    match = _TERNARY_RE.fullmatch(expr.strip())
    if not match:
        return expr.strip()
    assert match[1] in params, f"RDL parameter {match[1]} has no value in registers.rdl"
    return match[2] if params[match[1]] == "true" else match[3]


def _attr(body: str, name: str, default: str = "") -> str:
    match = re.search(rf"\b{name}\s*=\s*([^;]+);", body)
    return match[1].strip() if match else default


def _offsets() -> dict[str, int]:
    text = _GEN_PY.read_text(encoding="utf-8")
    pairs = re.findall(r"^I3C_CSR_0__(\w+)_REG_ADDR = (0x[0-9A-Fa-f]+)", text, flags=re.M)
    return {name: int(value, 16) for name, value in pairs}


def parse_table() -> tuple[list[Reg], list[tuple[str, str, str]]]:
    """Return the register table and the excluded registers as (block, name, reason)."""
    params = _params()
    offsets = _offsets()
    table: list[Reg] = []
    excluded: list[tuple[str, str, str]] = []
    for label, stem, prefix in _BLOCKS:
        text = _strip((_RDL / f"{stem}.rdl").read_text(encoding="utf-8"))
        for start in re.finditer(r"\breg\s*\{", text):
            depth, pos = 1, start.end()
            while depth:
                depth += (text[pos] == "{") - (text[pos] == "}")
                pos += 1
            body = text[start.end() : pos - 1]
            name = _TAIL_RE.match(text, pos)[1]
            if name in _EXCLUDED:
                excluded.append((label, name, _EXCLUDED[name]))
                continue
            key = f"{prefix}_{name}"
            assert key in offsets, f"{key}_REG_ADDR missing from {_GEN_PY.name}"
            reg = Reg(label, name, offsets[key])
            for fbody, fname, msb, lsb in _FIELD_RE.findall(body):
                reset = _RESET_RE.search(fbody)
                base = {"h": 16, "b": 2, "d": 10}[reset[1]] if reset else 10
                value = int(reset[2].replace("_", ""), base) if reset else 0
                hw = _resolve(_attr(fbody, "hw", "rw"), params)
                reg.fields.append(
                    Field(
                        name=fname,
                        msb=int(msb) if msb else 0,
                        lsb=int(lsb) if lsb else 0,
                        sw=_resolve(_attr(fbody, "sw", "rw"), params),
                        hw=hw,
                        reset=value,
                        onwrite=_attr(fbody, "onwrite"),
                        intr=bool(re.search(r"\bintr\b", fbody)),
                        hw_updated=hw in ("w", "rw")
                        or bool(re.search(r"\b(hwclr|hwset)\b", fbody)),
                    )
                )
            reg.fields.sort(key=lambda f: f.lsb)
            assert reg.fields, f"{label}.{name}: no field parsed"
            table.append(reg)
    return table, excluded


def _pdep(value: int, mask: int) -> int:
    """Scatter the low bits of ``value`` over the set bits of ``mask``."""
    out, bit = 0, 0
    for pos in range(32):
        if mask >> pos & 1:
            out |= (value >> bit & 1) << pos
            bit += 1
    return out


def _pext(value: int, mask: int) -> int:
    out, bit = 0, 0
    for pos in range(32):
        if mask >> pos & 1:
            out |= (value >> pos & 1) << bit
            bit += 1
    return out


class smc_i3c_csr_sweep_core_test_seq(SmcCsrSeq):
    """Reset, read-only, read-write, write-one-to-clear and isolation sweep of six instances."""

    def __init__(self, name: str = "smc_i3c_csr_sweep_core_test_seq") -> None:
        super().__init__(name)
        self.table: list[Reg] = []
        self.excluded: list[tuple[str, str, str]] = []
        self.stamps: list[tuple[str, int]] = []
        self.chk_order: list[tuple[str, str]] = []
        self.instances = 0

    def _stamp(self, step: str) -> None:
        self.stamps.append((step, int(get_sim_time("ps"))))

    def _chk(self, step: str, chk_id: str, text: str) -> None:
        assert self.stamps and self.stamps[-1][0] == step, f"{chk_id} printed before {step} ended"
        self.chk_order.append((step, chk_id))
        cocotb.log.info("%s: %s", chk_id, text)

    def _addr(self, n: int, reg: Reg) -> int:
        return smc_indexed_addr("SMC_TOP_OCA_I3C_WRAP_I3C_CSR_BASE_ADDR", n) + reg.offset

    async def _rd(self, n: int, reg: Reg) -> int:
        return (await self.csr_read(f"{reg.name}_I{n}", self._addr(n, reg))) & _WORD

    async def _wr(self, tag: str, n: int, reg: Reg, data: int) -> None:
        await self.csr_write(f"{tag}_{reg.name}_I{n}", self._addr(n, reg), data & _WORD)

    def _by_block(self) -> dict[str, list[Reg]]:
        return {label: [r for r in self.table if r.block == label] for label, _, _ in _BLOCKS}

    @staticmethod
    def _fmt_counts(regs: list[Reg]) -> str:
        classes = Counter(f"sw={f.sw}/hw={f.hw}" for r in regs for f in r.fields)
        text = " ".join(f"{k}:{v}" for k, v in sorted(classes.items()))
        return f"regs={len(regs)} fields={sum(len(r.fields) for r in regs)} [{text}]"

    # S1
    def _build_table(self) -> None:
        self.table, self.excluded = parse_table()
        blocks = self._by_block()
        for label, regs in blocks.items():
            cocotb.log.info("TABLE %s: %s", label, self._fmt_counts(regs))
        cocotb.log.info("TABLE total: %s", self._fmt_counts(self.table))
        cocotb.log.info(
            "TABLE excluded: %s",
            "; ".join(f"{b}.{n} ({why})" for b, n, why in self.excluded),
        )
        actions = [f"{r.name}.{f.name}" for r in self.table for f in r.fields if r.is_action(f)]
        cocotb.log.info("TABLE action fields left at reset: %s", " ".join(actions))
        updated = [f"{r.name}.{f.name}" for r in self.table for f in r.fields if not f.stable]
        cocotb.log.info("TABLE hardware-updated fields (%d): %s", len(updated), " ".join(updated))
        offs = "; ".join(f"{r.block}.{r.name}=0x{r.offset:03x}" for r in self.table)
        cocotb.log.info("TABLE offsets (generated map, inside the I3C CSR window): %s", offs)
        assert len(self.excluded) == len(_EXCLUDED), f"excluded {self.excluded}"
        assert all(blocks[label] for label, _, _ in _BLOCKS), "an RDL block parsed empty"

    # S2
    async def _sweep_reset(self) -> str:
        asserted = measured = 0
        diffs: list[str] = []
        for n in range(self.instances):
            for reg in self.table:
                word = await self._rd(n, reg)
                for f in reg.fields:
                    got = (word & f.mask) >> f.lsb
                    if f.stable:
                        assert got == f.reset, (
                            f"I3C{n} {reg.block}.{reg.name}.{f.name} reads 0x{got:x}, RDL reset "
                            f"0x{f.reset:x} (hw={f.hw}, word 0x{word:08x})"
                        )
                        asserted += 1
                    else:
                        measured += 1
                        if got != f.reset:
                            diffs.append(f"I3C{n}:{reg.name}.{f.name}=0x{got:x}/0x{f.reset:x}")
        per_block = "; ".join(f"{b} {self._fmt_counts(r)}" for b, r in self._by_block().items())
        return (
            f"{self.instances} instances x {len(self.table)} registers read; {asserted} field "
            f"reads with hw na/r equal their RDL reset; {measured} hardware-updated field reads "
            f"measured, {len(diffs)} differ from reset (reg.field=read/reset): "
            f"{' '.join(diffs) or 'none'}; per block {per_block}"
        )

    # S3
    async def _sweep_ro(self) -> str:
        targets = [r for r in self.table if r.mask_of(lambda f: f.sw == "r")]
        asserted = measured = 0
        diffs: list[str] = []
        for n in range(self.instances):
            for reg in targets:
                ro_mask = reg.mask_of(lambda f: f.sw == "r")
                await self._wr("RO_FLIP", n, reg, reg.reset_word ^ ro_mask)
                word = await self._rd(n, reg)
                for f in reg.fields:
                    got = (word & f.mask) >> f.lsb
                    if f.stable:
                        assert got == f.reset, (
                            f"I3C{n} {reg.block}.{reg.name}.{f.name} (sw={f.sw}) reads 0x{got:x} "
                            f"after writing 0x{reg.reset_word ^ ro_mask:08x}; RDL reset "
                            f"0x{f.reset:x}"
                        )
                        asserted += 1
                    else:
                        measured += 1
                        if got != f.reset:
                            diffs.append(f"I3C{n}:{reg.name}.{f.name}=0x{got:x}/0x{f.reset:x}")
        per_block = "; ".join(
            f"{b} sw=r regs={sum(1 for r in regs if r in targets)}"
            for b, regs in self._by_block().items()
        )
        return (
            f"{self.instances} instances x {len(targets)} registers with sw=r bits written "
            f"reset XOR sw=r mask; {asserted} field reads with hw na/r equal their reset; "
            f"{measured} hardware-updated field reads measured, {len(diffs)} differ "
            f"(reg.field=read/reset): {' '.join(diffs) or 'none'}; {per_block}"
        )

    # S4
    async def _sweep_rw(self) -> str:
        targets = [r for r in self.table if r.scope_mask]
        fields = sum(1 for r in targets for f in r.fields if r.in_scope(f))
        for n in range(self.instances):
            for reg in targets:
                scope = [f for f in reg.fields if reg.in_scope(f)]
                base = reg.reset_word & ~reg.scope_mask
                for phase, per_field in (
                    ("PAT", lambda f: _PATTERN & ((1 << f.width) - 1)),
                    ("CMP", lambda f: ~_PATTERN & ((1 << f.width) - 1)),
                    ("RST", lambda f: f.reset),
                ):
                    word = base | sum(per_field(f) << f.lsb for f in scope)
                    await self._wr(f"RW_{phase}", n, reg, word)
                    got = await self._rd(n, reg)
                    for f in scope:
                        want = per_field(f)
                        assert (got & f.mask) >> f.lsb == want, (
                            f"I3C{n} {reg.block}.{reg.name}.{f.name} {phase}: wrote 0x{word:08x}, "
                            f"read 0x{got:08x}, field wants 0x{want:x}"
                        )
        skipped = [
            f"{r.name}.{f.name}({'action' if r.is_action(f) else 'hw=' + f.hw})"
            for r in self.table
            for f in r.fields
            if f.sw == "rw" and not r.in_scope(f) and not f.onwrite
        ]
        w1c = [f"{r.name}.{f.name}" for r in self.table for f in r.fields if f.onwrite]
        per_block = "; ".join(
            f"{b} regs={sum(1 for r in regs if r in targets)} fields="
            f"{sum(1 for r in regs for f in r.fields if r.in_scope(f))}"
            for b, regs in self._by_block().items()
        )
        return (
            f"{self.instances} instances x {len(targets)} registers, {fields} sw=rw fields each "
            f"read back 0x5555_5555 masked to the field, then its complement, then its reset; "
            f"{per_block}; excluded sw=rw fields with reason ({len(skipped)}): "
            f"{' '.join(skipped)}; onwrite fields not round-tripped ({len(w1c)}): {' '.join(w1c)}"
        )

    # S5
    def _w1c_groups(self) -> list[tuple[Reg, Reg, Reg, list[Field]]]:
        by_name = {r.name: r for r in self.table}
        groups = []
        for reg in self.table:
            fields = [f for f in reg.fields if f.onwrite == "woclr" and f.intr and f.hw == "w"]
            if not fields:
                continue
            enable = by_name[f"{reg.name}_ENABLE"]
            force = by_name[reg.name.replace("STATUS", "FORCE")]
            for f in fields:
                for other in (enable, force):
                    assert any(g.lsb == f.lsb and g.width == 1 for g in other.fields), (
                        f"{other.name} has no 1-bit field at bit {f.lsb} for {reg.name}.{f.name}"
                    )
            groups.append((reg, enable, force, fields))
        return groups

    async def _sweep_w1c(self) -> str:
        groups = self._w1c_groups()
        lines: list[str] = []
        per_block: Counter = Counter()
        for n in range(self.instances):
            for status, enable, force, fields in groups:
                w1c_mask = sum(f.mask for f in fields)
                for k, f in enumerate(fields):
                    bit = 1 << f.lsb
                    near = 1 << fields[(k + 1) % len(fields)].lsb
                    assert near != bit, f"{status.name}.{f.name} has no w1c neighbour"
                    await self._wr("W1C_ENABLE", n, enable, bit | near)
                    await self._wr("W1C_FORCE_NEIGHBOUR", n, force, near)
                    await self._wr("W1C_FORCE_NEIGHBOUR_DROP", n, force, force.reset_word)
                    await self._wr("W1C_FORCE", n, force, bit)
                    observed = await self._rd(n, status)
                    assert observed & w1c_mask == bit | near, (
                        f"I3C{n} {status.name}.{f.name}: force 0x{bit:x} with status enable set "
                        f"reads 0x{observed:08x}; w1c bits 0x{observed & w1c_mask:x}, want "
                        f"0x{bit | near:x} (neighbour 0x{near:x} forced earlier)"
                    )
                    await self._wr("W1C_FORCE_DROP", n, force, force.reset_word)
                    latched = await self._rd(n, status)
                    assert latched & w1c_mask == bit | near, (
                        f"I3C{n} {status.name}.{f.name}: after the force drop the status reads "
                        f"0x{latched:08x}; w1c bits 0x{latched & w1c_mask:x}, want latched "
                        f"0x{bit | near:x}"
                    )
                    await self._wr("W1C_CLEAR", n, status, bit)
                    checked = await self._rd(n, status)
                    assert checked & w1c_mask == near, (
                        f"I3C{n} {status.name}.{f.name}: write 1 then read 0x{checked:08x}; "
                        f"w1c bits 0x{checked & w1c_mask:x}, want 0x{near:x} (neighbour kept, "
                        f"field cleared; latched 0x{latched:08x})"
                    )
                    await self._wr("W1C_CLEAR_NEIGHBOUR", n, status, near)
                    rest = await self._rd(n, status)
                    assert rest & w1c_mask == 0, (
                        f"I3C{n} {status.name}: neighbour clear leaves 0x{rest:08x}; "
                        f"w1c bits 0x{rest & w1c_mask:x}, want 0"
                    )
                    await self._wr("W1C_FORCE_RESTORE", n, force, force.reset_word)
                    await self._wr("W1C_ENABLE_RESTORE", n, enable, enable.reset_word)
                    per_block[status.block] += 1
                    lines.append(
                        f"I3C{n}:{status.name}.{f.name} set=0x{bit:x} observed=0x{observed & bit:x}"
                        f" latched=0x{latched & bit:x} cleared=0x{bit:x}"
                        f" checked_cleared=0x{checked & bit:x} neighbour_kept=0x{checked & near:x}"
                    )
        counts = " ".join(f"{b}={per_block[b] // self.instances}" for b, _, _ in _BLOCKS)
        return (
            f"{self.instances} instances, woclr intr fields per block {counts}; lifecycle set "
            f"(force write with status enable set) -> observed (status read) -> "
            f"cleared (force dropped and status read latched, write 1 with a second w1c bit set) "
            f"-> checked_cleared (status read, field 0, neighbour kept): {'; '.join(lines)}; "
            f"STBY registers "
            f"declare no woclr field in the pinned RDL; HC_CONTROL.RESUME (woclr, hw=rw action) "
            f"and STBY_CR_CONTROL.HANDOFF_DEEP_SLEEP (wset, hwclr) are listed, not asserted"
        )

    # S6
    async def _sweep_isolation(self) -> str:
        picks: list[Reg] = []
        for label in ("BASE", "PIO", "STBY"):
            regs = [r for r in self.table if r.block == label and r.scope_mask]
            picks.append(max(regs, key=lambda r: bin(r.scope_mask).count("1")))
        values: dict[str, list[int]] = {}
        for reg in picks:
            mask = reg.scope_mask
            skip = _pext(reg.reset_word, mask)
            indices = [i for i in range(1, 64) if i != skip][: self.instances]
            values[reg.name] = [_pdep(i, mask) | (reg.reset_word & ~mask) for i in indices]
            assert len({v & mask for v in values[reg.name]}) == self.instances, (
                f"{reg.name}: scope mask 0x{mask:08x} cannot hold {self.instances} distinct values"
            )
        checked = 0
        for n in range(self.instances):
            for reg in picks:
                mask = reg.scope_mask
                word = values[reg.name][n]
                await self._wr("ISO_PATTERN", n, reg, word)
                got = await self._rd(n, reg)
                assert got & mask == word & mask, (
                    f"I3C{n} {reg.name}: wrote 0x{word:08x}, read 0x{got:08x}"
                )
                for other in range(self.instances):
                    if other == n:
                        continue
                    seen = await self._rd(other, reg)
                    assert seen & reg.stable_mask == reg.reset_word & reg.stable_mask, (
                        f"I3C{other} {reg.name} reads 0x{seen:08x} after I3C{n} was written "
                        f"0x{word:08x}; reset 0x{reg.reset_word:08x}"
                    )
                    checked += 1
                await self._wr("ISO_RESTORE", n, reg, reg.reset_word)
                back = await self._rd(n, reg)
                assert back & mask == reg.reset_word & mask, (
                    f"I3C{n} {reg.name} reads 0x{back:08x} after restore; "
                    f"reset 0x{reg.reset_word:08x}"
                )
        regs_text = "; ".join(
            f"{r.block}.{r.name}@0x{r.offset:03x} patterns "
            + ",".join(f"0x{v:08x}" for v in values[r.name])
            for r in picks
        )
        return (
            f"for n=0..{self.instances - 1} a distinct pattern was written to one register of "
            f"each block in instance n, the other {self.instances - 1} instances read their "
            f"reset ({checked} cross reads), and the pattern was restored: {regs_text}"
        )

    def _fence(self) -> None:
        steps = [s for s, _ in self.stamps]
        assert steps == list(_STEPS), f"fence steps {steps}, expected {list(_STEPS)}"
        times = [t for _, t in self.stamps]
        assert all(a < b for a, b in zip(times, times[1:])), f"fence stamps not increasing {times}"
        printed = [c for _, c in self.chk_order]
        assert [s for s, _ in self.chk_order] == list(_STEPS[1:]), (
            f"checker lines printed at steps {self.chk_order}"
        )
        terms = " < ".join(_FENCE[s] for s in _STEPS)
        stamped = " ".join(f"{_FENCE[s]}={t}ps" for s, t in self.stamps)
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; stamps %s",
            terms,
            " ".join(printed),
            stamped,
        )

    async def body(self) -> None:
        await self.wait_fuse_sense_done()
        self.instances = smc_addr("SMC_TOP_OCA_I3C_WRAP_I3C_CSR_NUM")
        self._build_table()
        self._stamp("S1")

        text = await self._sweep_reset()
        self._stamp("S2")
        self._chk("S2", "CHK-I3C-SWEEP-RESET-READ", text)

        text = await self._sweep_ro()
        self._stamp("S3")
        self._chk("S3", "CHK-I3C-SWEEP-RO-IGNORED", text)

        text = await self._sweep_rw()
        self._stamp("S4")
        self._chk("S4", "CHK-I3C-SWEEP-RW-ROUNDTRIP", text)

        text = await self._sweep_w1c()
        self._stamp("S5")
        self._chk("S5", "CHK-I3C-SWEEP-W1C-CLEAR", text)

        text = await self._sweep_isolation()
        self._stamp("S6")
        self._chk("S6", "CHK-I3C-SWEEP-INSTANCE-ISOLATION", text)

        self._fence()
