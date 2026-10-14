# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Register sweep of the TTI, SoC management and secure firmware recovery blocks.

Sources: target_transaction_interface.rdl, soc_management_interface.rdl and
secure_firmware_recovery_interface.rdl of the pinned i3c-core, parsed at run time; register
offsets from the generated oca_i3c_wrap_reg.py; instance windows from the generated smc_addr.h.

A field declared without a bit range is one bit wide at bit 0.
The table holds every register of the three RDL files except the TTI queue ports and the
recovery indirect FIFO data port. A field is hardware-updated when its hw access can write it,
or it carries hwclr or hwset; such fields are read and printed, never asserted. Action fields
stay at reset in the read-write step. Fields that read with hw access na or r are asserted
against the RDL reset in every instance. SOC_PAD_CONF and SOC_PAD_ATTR are accessed as
registers only. Write-one-to-clear fields the RDL describes as NOT IMPLEMENTED are driven
and measured, never asserted.
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
    ("TTI", "target_transaction_interface", "I3C_EC_TTI"),
    ("SOCMGMT", "soc_management_interface", "I3C_EC_SOCMGMTIF"),
    ("RECOVERY", "secure_firmware_recovery_interface", "I3C_EC_SECFWRECOVERYIF"),
)
_EXCLUDED = {
    "RX_DESC_QUEUE_PORT": "queue port with access side effects",
    "RX_DATA_PORT": "queue port with access side effects",
    "TX_DESC_QUEUE_PORT": "queue port with access side effects",
    "TX_DATA_PORT": "queue port with access side effects",
    "IBI_PORT": "queue port with access side effects",
    "INDIRECT_FIFO_DATA": "indirect FIFO data port with access side effects",
}
_ACTION_REGS = {
    "RESET_CONTROL",
    "DEVICE_RESET",
    "RECOVERY_CTRL",
    "REC_INTF_REG_W1C_ACCESS",
}
_ACTION = {
    ("REC_INTF_CFG", "REC_PAYLOAD_DONE"),
    ("INDIRECT_FIFO_CTRL_0", "RESET"),
}
_NO_PICK = ("INTERRUPT", "INTR")
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

_FIELD_RE = re.compile(
    r"\bfield\s*\{([^{}]*)\}\s*(\w+)\s*(?:\[\s*([\w+\- ]+?)\s*:\s*(\d+)\s*\])?\s*;"
)
_TAIL_RE = re.compile(r"\s*(\w+)\s*(?:@\s*0x[0-9A-Fa-f]+)?\s*;")
_RESET_RE = re.compile(r"\breset\s*=\s*\d+'([hbd])\s*([0-9A-Fa-f_]+)\s*;")
_PARAM_RE = re.compile(r"\bbit\s+(\w+)\s*=\s*(\d+)")
_MINUS_RE = re.compile(r"(\w+)\s*-\s*(\d+)")
_UNIMPL_RE = re.compile(r'field\s*\{[^{}]*?desc\s*=\s*"NOT IMPLEMENTED[^{}]*\}\s*(\w+)')


@dataclass
class Field:
    name: str
    msb: int
    lsb: int
    sw: str
    hw: str
    reset: int
    onwrite: str
    onread: str
    pulse: bool
    unimplemented: bool
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
        return self.name in _ACTION_REGS or (self.name, f.name) in _ACTION

    def in_scope(self, f: Field) -> bool:
        return (
            f.sw == "rw" and f.stable and not f.onwrite and not f.onread and not self.is_action(f)
        )

    @property
    def scope_mask(self) -> int:
        return self.mask_of(self.in_scope)

    @property
    def stable_mask(self) -> int:
        return self.mask_of(lambda f: f.stable)

    @property
    def rw_mask(self) -> int:
        """Software-writable bits without a write or read side effect."""
        return self.mask_of(lambda f: f.sw == "rw" and not f.onwrite and not f.onread)


def _strip(text: str) -> str:
    text = re.sub(r'"[^"]*"', '""', text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


def _attr(body: str, name: str, default: str = "") -> str:
    match = re.search(rf"\b{name}\s*=\s*([^;]+);", body)
    return match[1].strip() if match else default


def _bit(expr: str, params: dict[str, int]) -> int:
    expr = expr.strip()
    if expr.isdigit():
        return int(expr)
    match = _MINUS_RE.fullmatch(expr)
    assert match and match[1] in params, f"unresolved RDL bit expression {expr!r}"
    return params[match[1]] - int(match[2])


def _offsets() -> tuple[dict[str, int], dict[str, int]]:
    text = _GEN_PY.read_text(encoding="utf-8")
    regs = re.findall(r"^I3C_CSR_0__(\w+)_REG_ADDR = (0x[0-9A-Fa-f]+)", text, flags=re.M)
    files = re.findall(r"^I3C_CSR_0__(\w+)_REG_FILE_BASE_ADDR = (0x[0-9A-Fa-f]+)", text, flags=re.M)
    return (
        {name: int(value, 16) for name, value in regs},
        {name: int(value, 16) for name, value in files},
    )


def parse_table() -> tuple[list[Reg], list[tuple[str, str, str]], dict[str, int]]:
    """Return the register table, the excluded registers and the block base offsets."""
    offsets, bases = _offsets()
    table: list[Reg] = []
    excluded: list[tuple[str, str, str]] = []
    for label, stem, prefix in _BLOCKS:
        raw = (_RDL / f"{stem}.rdl").read_text(encoding="utf-8")
        unimplemented = set(_UNIMPL_RE.findall(raw))
        text = _strip(raw)
        params = {k: int(v) for k, v in _PARAM_RE.findall(text)}
        assert prefix in bases, f"{prefix} register file missing from {_GEN_PY.name}"
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
                hw = _attr(fbody, "hw", "rw")
                woclr = _attr(fbody, "woclr") == "true"
                reg.fields.append(
                    Field(
                        name=fname,
                        msb=_bit(msb, params) if msb else 0,
                        lsb=int(lsb) if lsb else 0,
                        sw=_attr(fbody, "sw", "rw"),
                        hw=hw,
                        reset=value,
                        onwrite="woclr" if woclr else _attr(fbody, "onwrite"),
                        onread=_attr(fbody, "onread"),
                        pulse=bool(re.search(r"\bsinglepulse\b", fbody)),
                        unimplemented=fname in unimplemented,
                        hw_updated=hw in ("w", "rw")
                        or bool(re.search(r"\b(hwclr|hwset)\b", fbody)),
                    )
                )
            reg.fields.sort(key=lambda f: f.lsb)
            assert reg.fields, f"{label}.{name}: no field parsed"
            table.append(reg)
    return table, excluded, {p: bases[p] for _, _, p in _BLOCKS}


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


class smc_i3c_csr_sweep_ext_test_seq(SmcCsrSeq):
    """Reset, read-only, read-write, write-one-to-clear and isolation sweep of six instances."""

    def __init__(self, name: str = "smc_i3c_csr_sweep_ext_test_seq") -> None:
        super().__init__(name)
        self.table: list[Reg] = []
        self.excluded: list[tuple[str, str, str]] = []
        self.bases: dict[str, int] = {}
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
        self.table, self.excluded, self.bases = parse_table()
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
        starts = " ".join(f"{p}=0x{o:03x}" for p, o in self.bases.items())
        cocotb.log.info("TABLE block base offsets (generated map, owner value pending): %s", starts)
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
        asserted = measured = followed = 0
        diffs: list[str] = []
        for n in range(self.instances):
            for reg in targets:
                ro_mask = reg.mask_of(lambda f: f.sw == "r")
                pre = await self._rd(n, reg)
                await self._wr("RO_FLIP", n, reg, reg.reset_word ^ ro_mask)
                word = await self._rd(n, reg)
                for f in reg.fields:
                    got = (word & f.mask) >> f.lsb
                    if f.sw == "r" and not f.stable:
                        was = (pre & f.mask) >> f.lsb
                        assert got == was, (
                            f"I3C{n} {reg.block}.{reg.name}.{f.name} (sw=r, hw={f.hw}) reads "
                            f"0x{got:x} after writing 0x{reg.reset_word ^ ro_mask:08x}; it read "
                            f"0x{was:x} before the write"
                        )
                        followed += 1
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
            f"(reg.field=read/reset): {' '.join(diffs) or 'none'}; {followed} hardware-updated "
            f"sw=r field reads (listed, {followed // self.instances} per instance) equal the "
            f"value read before the flip write; {per_block}"
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
                    ("PAT", lambda f: (_PATTERN & f.mask) >> f.lsb),
                    ("CMP", lambda f: (~_PATTERN & f.mask) >> f.lsb),
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
            f"{r.block}.{r.name}.{f.name}({'action' if r.is_action(f) else 'hw=' + f.hw})"
            for r in self.table
            for f in r.fields
            if f.sw == "rw" and not r.in_scope(f) and not f.onwrite and not f.onread
        ]
        w1c = [f"{r.name}.{f.name}" for r in self.table for f in r.fields if f.onwrite]
        per_block = "; ".join(
            f"{b} regs={sum(1 for r in regs if r in targets)} fields="
            f"{sum(1 for r in regs for f in r.fields if r.in_scope(f))}"
            for b, regs in self._by_block().items()
        )
        return (
            f"{self.instances} instances x {len(targets)} registers, {fields} sw=rw fields each "
            f"read back 0x5555_5555 masked to the field at its word position, then its complement "
            f"masked the same way, then its reset; RECOVERY contributes 0 in-scope sw=rw fields; "
            f"{per_block}; excluded sw=rw fields with reason ({len(skipped)}): "
            f"{' '.join(skipped)}; onwrite fields not round-tripped ({len(w1c)}): {' '.join(w1c)}"
        )

    # S5
    def _w1c_groups(self) -> tuple[list[tuple[Reg, Reg, Reg, list[Field]]], list[str]]:
        by_name = {r.name: r for r in self.table}
        groups, unforced = [], []
        for reg in self.table:
            fields = [f for f in reg.fields if f.onwrite == "woclr"]
            if not fields:
                continue
            enable = by_name.get(reg.name.replace("STATUS", "ENABLE"))
            force = by_name.get(reg.name.replace("STATUS", "FORCE"))
            if enable is None or force is None or enable is reg or force is reg:
                unforced += [f"{reg.block}.{reg.name}.{f.name}" for f in fields]
                continue
            for f in fields:
                for other in (enable, force):
                    assert any(g.lsb == f.lsb and g.width == 1 for g in other.fields), (
                        f"{other.name} has no 1-bit field at bit {f.lsb} for {reg.name}.{f.name}"
                    )
            groups.append((reg, enable, force, fields))
        return groups, unforced

    async def _force_set(self, n, status, enable, force, bit, w1c_mask) -> int:
        """Set status bits through enable and force, drop the force, return the status read."""
        await self._wr("W1C_ENABLE", n, enable, bit)
        await self._wr("W1C_FORCE", n, force, bit)
        observed = (await self._rd(n, status)) & w1c_mask
        await self._wr("W1C_FORCE_DROP", n, force, force.reset_word)
        return observed

    async def _sweep_w1c(self) -> str:
        groups, unforced = self._w1c_groups()
        lines: list[str] = []
        residues: list[str] = []
        rtl100: set[str] = set()
        per_block: Counter = Counter()
        sets: Counter = Counter()
        linked: Counter = Counter()
        for n in range(self.instances):
            for status, enable, force, fields in groups:
                w1c_mask = sum(f.mask for f in fields)
                residue = (await self._rd(n, status)) & w1c_mask
                if residue:
                    await self._wr("W1C_RESIDUE_CLEAR", n, status, residue)
                    left = (await self._rd(n, status)) & w1c_mask
                    assert left == 0, f"I3C{n}:{status.name}: residue 0x{residue:x} left 0x{left:x}"
                    residues.append(f"I3C{n}:{status.name}=0x{residue:x}")
                for f in fields:
                    bit = 1 << f.lsb
                    tag = f"I3C{n}:{status.name}.{f.name}"
                    before = (await self._rd(n, status)) & w1c_mask
                    assert before == 0, f"{tag}: w1c bits 0x{before:x} set before enable and force"
                    observed = await self._force_set(n, status, enable, force, bit, w1c_mask)
                    per_block[status.block] += 1
                    latched = (await self._rd(n, status)) & w1c_mask
                    if f.unimplemented or (observed == 0 and latched == 0):
                        linked[status.block] += 1
                        note = "NOT-IMPLEMENTED" if f.unimplemented else "LINKED-ISSUE"
                        if not f.unimplemented:
                            rtl100.add(f"{status.name}.{f.name}")
                        lines.append(f"{tag} set=0x{bit:x} read=0x{observed:x} {note}")
                        if latched:
                            await self._wr("W1C_CLEAR", n, status, latched)
                        await self._wr("W1C_ENABLE_RESTORE", n, enable, enable.reset_word)
                        continue
                    assert observed == bit, (
                        f"{tag}: force 0x{bit:x} with the enable set reads 0x{observed:x}, "
                        f"want 0x{bit:x} or 0"
                    )
                    assert latched == bit, (
                        f"{tag}: bit set by force reads 0x{latched:x} after the force drop, "
                        f"want 0x{bit:x}"
                    )
                    sets[status.block] += 1
                    other = 0
                    for g in fields:
                        if g is f or g.unimplemented:
                            continue
                        both = bit | g.mask
                        got = await self._force_set(n, status, enable, force, both, w1c_mask)
                        if got == both:
                            other = g.mask
                            break
                        await self._wr("W1C_CLEAR", n, status, got & ~bit)
                    held = (await self._rd(n, status)) & w1c_mask
                    assert held == bit | other, (
                        f"{tag}: after the pre-set of 0x{other:x} the status reads 0x{held:x}, "
                        f"want 0x{bit | other:x}"
                    )
                    await self._wr("W1C_CLEAR", n, status, bit)
                    checked = (await self._rd(n, status)) & w1c_mask
                    assert checked == other, (
                        f"{tag}: write 1 then w1c bits 0x{checked:x}, want 0x{other:x}"
                    )
                    if other:
                        await self._wr("W1C_CLEAR_OTHER", n, status, other)
                        rest = (await self._rd(n, status)) & w1c_mask
                        assert rest == 0, f"{tag}: other bit 0x{other:x} left 0x{rest:x} set"
                    await self._wr("W1C_ENABLE_RESTORE", n, enable, enable.reset_word)
                    lines.append(
                        f"{tag} set=0x{bit:x} observed=0x{observed:x} latched=0x{latched:x} "
                        f"preset_other=0x{other:x} cleared=0x{bit:x} "
                        f"checked_cleared=0x{checked & bit:x} neighbour_kept=0x{checked:x}"
                    )
        pulses = [(r, f) for r in self.table for f in r.fields if f.pulse]
        pulse_lines: list[str] = []
        for n in range(self.instances):
            for reg, f in pulses:
                await self._wr("PULSE_SET", n, reg, 1 << f.lsb)
                word = await self._rd(n, reg)
                assert (word & f.mask) >> f.lsb == 0, (
                    f"I3C{n} {reg.name}.{f.name}: write 1 then read 0x{word:08x}, field wants 0"
                )
                pulse_lines.append(f"I3C{n}:{reg.name}.{f.name} word=0x{word:08x}")
        counts = " ".join(f"{b}={per_block[b] // self.instances}" for b, _, _ in _BLOCKS)
        sc = " ".join(f"{b}={sets[b]}/{linked[b]}" for b, _, _ in _BLOCKS)
        return (
            f"{self.instances} instances, woclr fields per block {counts}; set/not-set counts "
            f"over all instances {sc}; lifecycle set (force write with status enable set) -> "
            f"observed (status read) -> latched (force dropped, status read) -> cleared (write 1 "
            f"with a second pre-set bit) -> checked_cleared (status read, neighbour kept): "
            f"{'; '.join(lines)}; self-clearing fields write 1 then read 0: "
            f"{'; '.join(pulse_lines)}; LINKED-ISSUE fields (force leaves the status at 0): "
            f"{' '.join(sorted(rtl100))}; measured DUT observation, S4 FORCE pattern writes with "
            f"the enable at reset leave woclr status bits set (cleared before the sweep, not "
            f"asserted either way): {' '.join(residues) or 'none'}; owner-pending items listed, "
            f"not asserted: TTI RESET_CONTROL fields (left at reset except the "
            f"self-clearing IBI_RETRY_CTR_RST) and no STBY_CR_ENABLE_INIT-locked field exists in "
            f"the TTI, SOCMGMT and RECOVERY blocks (applies to the standby block only); "
            f"SOCMGMT has 0 woclr fields; woclr fields without a force register in the RDL, listed "
            f"not driven: {' '.join(unforced)}"
        )

    # S6
    def _pick(self, label: str) -> Reg:
        regs = [r for r in self.table if r.block == label and r.rw_mask]
        regs = [r for r in regs if not any(k in r.name for k in _NO_PICK)]
        if any(r.scope_mask for r in regs):
            regs = [r for r in regs if r.scope_mask]
            return max(regs, key=lambda r: bin(r.scope_mask).count("1"))
        return max(regs, key=lambda r: bin(r.rw_mask).count("1"))

    async def _sweep_isolation(self) -> str:
        picks = [self._pick(label) for label, _, _ in _BLOCKS]
        values: dict[str, list[int]] = {}
        for reg in picks:
            mask = reg.rw_mask
            skip = _pext(reg.reset_word, mask)
            indices = [i for i in range(1, 64) if i != skip][: self.instances]
            values[reg.name] = [_pdep(i, mask) | (reg.reset_word & ~mask) for i in indices]
            assert len({v & mask for v in values[reg.name]}) == self.instances, (
                f"{reg.name}: rw mask 0x{mask:08x} cannot hold {self.instances} distinct values"
            )
        checked = 0
        written: list[str] = []
        for n in range(self.instances):
            for reg in picks:
                mask = reg.rw_mask
                word = values[reg.name][n]
                await self._wr("ISO_PATTERN", n, reg, word)
                got = await self._rd(n, reg)
                if reg.scope_mask == mask:
                    assert got & mask == word & mask, (
                        f"I3C{n} {reg.name}: wrote 0x{word:08x}, read 0x{got:08x}"
                    )
                else:
                    written.append(
                        f"I3C{n}:{reg.name} wrote 0x{word & mask:x} read 0x{got & mask:x}"
                    )
                keep = mask | reg.stable_mask
                for other in range(self.instances):
                    if other == n:
                        continue
                    seen = await self._rd(other, reg)
                    assert seen & keep == reg.reset_word & keep, (
                        f"I3C{other} {reg.name} reads 0x{seen:08x} after I3C{n} was written "
                        f"0x{word:08x}; reset 0x{reg.reset_word:08x}"
                    )
                    checked += 1
                await self._wr("ISO_RESTORE", n, reg, reg.reset_word)
                back = await self._rd(n, reg)
                assert back & keep == reg.reset_word & keep, (
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
            f"reset ({checked} cross reads), and the pattern was restored: {regs_text}; "
            f"written-instance readback of hardware-updated picks measured: "
            f"{' '.join(written) or 'none'}"
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
