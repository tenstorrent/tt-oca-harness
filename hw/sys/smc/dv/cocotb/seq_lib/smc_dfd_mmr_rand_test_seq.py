# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Seeded DFD MMR visits: drawn register order, write pattern and 32-bit lane.

Specs: vendor/tenstorrent/tt-hw-debug/overlay/regs/dfd/regs/include/dfd_cla.rdl
(`CDbgClaCounter0Cfg` to `CDbgClaCounter3Cfg`), dfd_dst_sink.rdl (`Trdstramcontrol`,
`Trdstramimpl`) and dfd_funnel.rdl (`Trfunnelcontrol`, `Trfunnelimpl`, `Trfunneldisinput`).

Every address, field position, reset value and software-access type comes from the generated
register map (`seq_lib.smc_rdl_regmap`, `seq_lib.smc_cla_regmap`). The bits graded on a CLA
counter are the fields software writes and hardware does not drive (`Target`, `ResetOnTarget`,
`UpperTarget`); `Counter` and `UpperCounter` are hardware-written and `Rsvd` (bit 63) is masked
out of every pattern. On `Trfunneldisinput` the 16-bit source disable mask is graded and bits
31:16, which no field occupies, read 0. On the sink and funnel control and implementation
registers a write carries the pattern in the read-only bits and the read value in every other
bit, except `Trdstramvendorframelength` (software-written, not hardware-driven), which takes a
frame length from the set its description allows, 1, 2, 4 and 8, and is read back; the read-only
fields are printed, not graded.

Pinned cells, run on every seed before the draw: on each CLA counter an all-ones upper-lane
write, a lower-lane write of 0xFFFFFFFE and an all-zeros upper-lane write, so each lane takes a
write that changes every graded bit and each lane write after the first finds the other lane
holding a non-zero value that differs from the written word; on `Trfunneldisinput` the words
0xFFFFFFFF and 0xFFFF0000, which change every mask bit and carry ones in bits 31:16; on each of
the four sink and funnel registers an all-ones write to its read-only bits; on `Trdstramimpl` a
frame length of 8, which differs from its reset value 1.

The seed then draws the visit order of the nine registers, the pattern of each visit (all ones,
all zeros, alternating bits or a random word), on a counter the lane and on `Trdstramimpl` the
frame length. The expected value of
every read comes from a model of the graded bits that the pinned and drawn writes update.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from functools import lru_cache

import cocotb
from cocotb.utils import get_sim_time

from .smc_cla_regmap import cla_field, cla_register
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_rdl_regmap import RdlReg, rdl_registers_under

FUSE_SENSE_BOUND = 200_000
LANE_MASK = 0xFFFF_FFFF
COUNTERS = tuple(f"CDbgClaCounter{n}Cfg" for n in range(4))
SINK_FUNNEL = (
    ("dst_sink", "Trdstramcontrol"),
    ("dst_sink", "Trdstramimpl"),
    ("funnel", "Trfunnelcontrol"),
    ("funnel", "Trfunnelimpl"),
    ("funnel", "Trfunneldisinput"),
)
DISINPUT = "Trfunneldisinput"
RO_REGS = ("Trdstramcontrol", "Trdstramimpl", "Trfunnelcontrol", "Trfunnelimpl")
# Read-only fields printed as controls, with the register that holds each.
RO_FIELDS = (
    ("Trdstramcontrol", "Trdstramempty"),
    ("Trdstramimpl", "Trdstramcomptype"),
    ("Trfunnelcontrol", "Trfunnelempty"),
    ("Trfunnelimpl", "Trfunnelcomptype"),
)
PATTERN_KINDS = ("ones", "zeros", "alt", "random")
# Pinned counter cells: (lane, pattern word) in issue order; lane 0 is bits 31:0. The
# lower-lane word keeps bit 0 (`Counter`) clear so its copy in the upper lane differs from the
# upper lane's graded bits in `ResetOnTarget`.
COUNTER_PINS = ((1, LANE_MASK), (0, 0xFFFF_FFFE), (1, 0))
DISINPUT_PINS = (0xFFFF_FFFF, 0xFFFF_0000)
IMPL = "Trdstramimpl"
FRAME_LENGTH = "Trdstramvendorframelength"
# dfd_dst_sink.rdl Trdstramvendorframelength: only 1, 2, 4 and 8 are supported.
FRAME_LENGTHS = (1, 2, 4, 8)
FRAME_LENGTH_PIN = 8

STEPS = ("S1", "S2", "S3", "S4", "S5", "S6")
CHK_STEPS = (
    ("CHK-DFDR-RESET", "S2"),
    ("CHK-DFDR-RW", "S3"),
    ("CHK-DFDR-LANE", "S3"),
    ("CHK-DFDR-RO", "S5"),
)


def _field_mask(reg: RdlReg, name: str) -> int:
    for field in reg.fields:
        if field.name == name:
            return field.mask
    raise KeyError(f"{reg.path} has no field {name} in the generated map")


def _field_value(reg: RdlReg, name: str, word: int) -> int:
    for field in reg.fields:
        if field.name == name:
            return (word & field.mask) >> field.offset
    raise KeyError(f"{reg.path} has no field {name} in the generated map")


def _field_offset(reg: RdlReg, name: str) -> int:
    for field in reg.fields:
        if field.name == name:
            return field.offset
    raise KeyError(f"{reg.path} has no field {name} in the generated map")


def _ro_mask(reg: RdlReg) -> int:
    mask = 0
    for field in reg.fields:
        if field.access == "read-only":
            mask |= field.mask
    return mask


@lru_cache(maxsize=1)
def dfd_registers() -> dict[str, RdlReg]:
    """The nine visited registers by RDL name, from the generated map."""
    out: dict[str, RdlReg] = {name: cla_register(name) for name in COUNTERS}
    for block, name in SINK_FUNNEL:
        path = f"smc_cla/{block}/{name}"
        found = [r for r in rdl_registers_under(f"smc_cla/{block}") if r.path == path]
        assert len(found) == 1, f"{path} is not one register of the generated map"
        out[name] = found[0]
    return out


@lru_cache(maxsize=1)
def owned_masks() -> dict[str, int]:
    """Graded bits per register: software-written, not hardware-driven (disinput: its mask)."""
    regs = dfd_registers()
    out = {}
    for name in COUNTERS:
        reg = regs[name]
        rsvd = cla_field(reg, "Rsvd").mask
        mask = reg.rw_mask & ~rsvd
        for field in ("Target", "ResetOnTarget", "UpperTarget"):
            assert mask & _field_mask(reg, field) == _field_mask(reg, field), (
                f"{reg.path}.{field} is no longer software-written and not hardware-driven in "
                f"the generated map"
            )
        assert mask == sum(_field_mask(reg, f) for f in ("Target", "ResetOnTarget", "UpperTarget"))
        out[name] = mask
    out[DISINPUT] = _field_mask(regs[DISINPUT], DISINPUT)
    assert regs[DISINPUT].declared_mask == out[DISINPUT] == 0xFFFF
    for name in RO_REGS:
        out[name] = 0
    return out


def _pattern(rng: random.Random, kind: str) -> int:
    if kind == "ones":
        return LANE_MASK
    if kind == "zeros":
        return 0
    if kind == "alt":
        return rng.choice((0xAAAA_AAAA, 0x5555_5555))
    return rng.getrandbits(32)


@dataclass
class Cell:
    """One write and its readback, with the expected graded bits from the model."""

    reg: str
    kind: str
    word: int
    lane: int = -1
    pinned: bool = False
    want: int = 0
    prev: int = 0
    rw_disc: bool = False
    rw_full: bool = False
    lane_disc: bool = False
    frame: int = -1

    def tag(self) -> str:
        lane = f" lane {'upper' if self.lane else 'lower'}" if self.lane >= 0 else ""
        frame = f" frame {self.frame}" if self.frame >= 0 else ""
        pin = "pin" if self.pinned else "draw"
        return f"{self.reg}{lane} {self.kind} 0x{self.word:08x}{frame} ({pin})"


def build_plan(seed: int) -> tuple[list[Cell], list[Cell], list[str]]:
    """Pinned cells, drawn cells and drawn order, with expectations from the model."""
    rng = random.Random(seed)
    masks = owned_masks()
    order = list(COUNTERS) + [name for _, name in SINK_FUNNEL]
    rng.shuffle(order)
    regs = dfd_registers()
    model = {name: regs[name].reset_word & masks[name] for name in masks}
    impl = regs[IMPL]
    model[IMPL] = _field_value(impl, FRAME_LENGTH, impl.reset_word)
    pinned: list[Cell] = []
    drawn: list[Cell] = []

    def apply(cell: Cell) -> None:
        mask = masks[cell.reg]
        if cell.reg in COUNTERS:
            shift = 32 * cell.lane
            lane_mask = (mask >> shift) & LANE_MASK
            other_shift = 32 * (1 - cell.lane)
            other_mask = (mask >> other_shift) & LANE_MASK
            prev_lane = (model[cell.reg] >> shift) & lane_mask
            prev_other = (model[cell.reg] >> other_shift) & other_mask
            cell.prev = model[cell.reg]
            changed = (cell.word ^ prev_lane) & lane_mask
            cell.rw_disc = changed != 0
            cell.rw_full = changed == lane_mask != 0
            cell.lane_disc = prev_other != 0 and prev_other != (cell.word & other_mask)
            model[cell.reg] = (model[cell.reg] & ~(lane_mask << shift)) | (
                (cell.word & lane_mask) << shift
            )
        elif cell.reg == DISINPUT:
            cell.prev = model[cell.reg]
            changed = (cell.word ^ cell.prev) & mask
            cell.rw_disc = changed != 0
            cell.rw_full = changed == mask
            cell.lane_disc = (cell.word & ~mask & LANE_MASK) != 0
            model[cell.reg] = cell.word & mask
        elif cell.reg == IMPL:
            cell.prev = model[IMPL]
            cell.rw_disc = cell.frame != cell.prev
            model[IMPL] = cell.frame
        cell.want = model[cell.reg]

    for name in COUNTERS:
        for lane, word in COUNTER_PINS:
            cell = Cell(name, "pin", word, lane, pinned=True)
            apply(cell)
            pinned.append(cell)
    for word in DISINPUT_PINS:
        cell = Cell(DISINPUT, "pin", word, pinned=True)
        apply(cell)
        pinned.append(cell)
    cell = Cell(IMPL, "pin", 0, pinned=True, frame=FRAME_LENGTH_PIN)
    apply(cell)
    pinned.append(cell)
    for name in order:
        kind = rng.choice(PATTERN_KINDS)
        word = _pattern(rng, kind)
        lane = rng.randrange(2) if name in COUNTERS else -1
        frame = rng.choice(FRAME_LENGTHS) if name == IMPL else -1
        cell = Cell(name, kind, word, lane, frame=frame)
        apply(cell)
        drawn.append(cell)
    check_pins(pinned)
    return pinned, drawn, order


def check_pins(pinned: list[Cell]) -> None:
    """Each counter lane takes a write changing every graded bit and a discriminating lane cell."""
    for name in COUNTERS:
        cells = [c for c in pinned if c.reg == name]
        for lane in (0, 1):
            assert any(c.rw_full for c in cells if c.lane == lane), f"{name} lane {lane} no RW pin"
            assert any(c.lane_disc for c in cells if c.lane == lane), (
                f"{name} lane {lane} no discriminating other-lane pin"
            )
    dis = [c for c in pinned if c.reg == DISINPUT]
    assert all(c.rw_full and c.lane_disc for c in dis), f"{DISINPUT} pins do not discriminate"
    impl = [c for c in pinned if c.reg == IMPL]
    assert [c.frame for c in impl] == [FRAME_LENGTH_PIN] and impl[0].rw_disc, (
        f"{IMPL}.{FRAME_LENGTH} pin {FRAME_LENGTH_PIN} does not differ from its reset value"
    )


class smc_dfd_mmr_rand_test_seq(SmcCsrSeq):
    """Pinned and drawn DFD MMR writes; read back against the register descriptions."""

    def __init__(self, name: str = "smc_dfd_mmr_rand_test_seq", *, seed: int) -> None:
        super().__init__(name)
        self.seed = seed
        self.pinned: list[Cell] = []
        self.drawn: list[Cell] = []
        self.order: list[str] = []
        self.steps: list[tuple[str, int]] = []
        self.chk_lines: list[tuple[str, str]] = []
        self.waits: list[str] = []
        self.ro_log: list[str] = []
        self.visited: set[str] = set()
        self.restored: set[str] = set()
        self.done = False

    # -- plumbing ---------------------------------------------------------

    def _mark(self, step: str) -> None:
        self.steps.append((step, int(get_sim_time("ps"))))

    def _chk(self, step: str, chk_id: str, text: str) -> None:
        assert self.steps and self.steps[-1][0] == step, f"{chk_id} printed before {step} ended"
        self.chk_lines.append((chk_id, step))
        cocotb.log.info("%s: %s", chk_id, text)

    def _drawn(self) -> str:
        cells = "; ".join(c.tag() for c in self.drawn)
        return f"drawn=order {','.join(self.order)}; {cells}"

    async def _read(self, name: str, label: str) -> int:
        reg = dfd_registers()[name]
        value = await self.csr_read(f"{name}:{label}", reg.addr, length=reg.width_bytes)
        return int(value) & ((1 << (8 * reg.width_bytes)) - 1)

    async def _ro_snapshot(self, label: str) -> None:
        regs = dfd_registers()
        parts = []
        for name, field in RO_FIELDS:
            word = await self._read(name, f"ro_{label}")
            parts.append(
                f"{field}={_field_value(regs[name], field, word):#x} "
                f"(reset {_field_value(regs[name], field, regs[name].reset_word):#x})"
            )
        self.ro_log.append(f"{label}: {', '.join(parts)}")

    async def _write_cell(self, cell: Cell) -> None:
        reg = dfd_registers()[cell.reg]
        masks = owned_masks()
        if cell.reg in COUNTERS:
            rsvd_lane = (cla_field(reg, "Rsvd").mask >> (32 * cell.lane)) & LANE_MASK
            data = cell.word & ~rsvd_lane & LANE_MASK
            await self.csr_write(
                f"{cell.reg}:lane{cell.lane}", reg.addr + 4 * cell.lane, data, length=4
            )
            got = await self._read(cell.reg, f"lane{cell.lane}_rb")
            mask = masks[cell.reg]
            lane_mask = LANE_MASK << (32 * cell.lane)
            assert got & mask & lane_mask == cell.want & mask & lane_mask, (
                f"CHK-DFDR-RW {cell.tag()}: graded bits of the written lane read "
                f"0x{got & mask & lane_mask:016x}, want 0x{cell.want & mask & lane_mask:016x}"
            )
            assert got & mask & ~lane_mask == cell.want & mask & ~lane_mask, (
                f"CHK-DFDR-LANE {cell.tag()}: graded bits of the other lane read "
                f"0x{got & mask & ~lane_mask:016x}, want their previous value "
                f"0x{cell.prev & mask & ~lane_mask:016x}"
            )
        elif cell.reg == DISINPUT:
            await self.csr_write(f"{cell.reg}:write", reg.addr, cell.word, length=4)
            got = await self._read(cell.reg, "rb")
            assert got == cell.want, (
                f"CHK-DFDR-RW {cell.tag()}: reads 0x{got:08x}, want the low 16 bits 0x"
                f"{cell.want:04x} and 0 in bits 31:16, which no field occupies"
            )
        else:
            before = await self._read(cell.reg, "before")
            ro = _ro_mask(reg)
            data = (cell.word & ro) | (before & ~ro & LANE_MASK)
            if cell.frame >= 0:
                frame_mask = _field_mask(reg, FRAME_LENGTH)
                offset = _field_offset(reg, FRAME_LENGTH)
                data = (data & ~frame_mask) | (cell.frame << offset)
            await self.csr_write(f"{cell.reg}:ro_write", reg.addr, data, length=4)
            if cell.frame >= 0:
                got = _field_value(reg, FRAME_LENGTH, await self._read(cell.reg, "frame_rb"))
                assert got == cell.want, (
                    f"CHK-DFDR-RW {cell.tag()}: {FRAME_LENGTH} reads {got}, want the written "
                    f"frame length {cell.want} (dfd_dst_sink.rdl, sw rw, hw r)"
                )
            await self._ro_snapshot(f"after {cell.tag()}")
        self.visited.add(cell.reg)

    # -- steps ------------------------------------------------------------

    async def _s1(self) -> None:
        await self.wait_fuse_sense_done(FUSE_SENSE_BOUND)
        self.waits.append(f"fuse_sense_done<={FUSE_SENSE_BOUND} clk_smc_i")
        self.pinned, self.drawn, self.order = build_plan(self.seed)
        ctrl = cla_register("CDbgClaCtrlStatus")
        armed = cla_field(ctrl, "EnableCla").mask | cla_field(ctrl, "EnableEap").mask
        state = await self.csr_read("CDbgClaCtrlStatus:idle", ctrl.addr, length=ctrl.width_bytes)
        assert int(state) & armed == ctrl.reset_word & armed == 0, (
            f"CDbgClaCtrlStatus reads 0x{int(state):x}: EnableCla or EnableEap set before the "
            f"visits, reset 0 in dfd_cla.rdl"
        )
        cocotb.log.info(
            "RAND-SEED: %d; RAND-DRAW: order %s; patterns %s; pinned %d cells (%s)",
            self.seed,
            ",".join(self.order),
            "; ".join(c.tag() for c in self.drawn),
            len(self.pinned),
            "; ".join(c.tag() for c in self.pinned),
        )
        self._mark("S1")

    async def _s2(self) -> None:
        regs = dfd_registers()
        parts = []
        for name in COUNTERS + tuple(n for _, n in SINK_FUNNEL):
            word = await self._read(name, "reset")
            parts.append(f"{name}=0x{word:x} (golden 0x{regs[name].reset_word:x})")
        self._mark("S2")
        self._chk(
            "S2",
            "CHK-DFDR-RESET",
            "logged control, not graded here: " + "; ".join(parts) + "; the reset words are "
            "graded by smc_dfd_cla_mmr_sweep_test (CHK-CLA-MMR-WRITE-SWEEP) and "
            "smc_dfd_sink_mmr_sweep_test (CHK-DFD-SINK-MMR-DECODE)",
        )

    async def _s3(self) -> None:
        for cell in self.pinned + self.drawn:
            await self._write_cell(cell)
        self._mark("S3")
        graded = [
            c
            for c in self.pinned + self.drawn
            if c.reg in COUNTERS or c.reg == DISINPUT or c.frame >= 0
        ]
        rw_disc = sum(1 for c in graded if c.rw_disc)
        lane_cells = [c for c in graded if c.reg in COUNTERS]
        lane_disc = sum(1 for c in lane_cells if c.lane_disc)
        self._chk(
            "S3",
            "CHK-DFDR-RW",
            f"{len(graded)} writes ({len(self.pinned)} pinned) read back the drawn pattern in "
            f"the CLA counter bits Target, ResetOnTarget and UpperTarget of the written lane, "
            f"Trfunneldisinput read the low 16 bits with 0 in bits 31:16 and "
            f"Trdstramimpl.{FRAME_LENGTH} read the written frame length (pinned "
            f"{FRAME_LENGTH_PIN}, drawn from {', '.join(map(str, FRAME_LENGTHS))}); {rw_disc} of "
            f"them changed at least one graded bit (each counter lane and the disinput mask took "
            f"a pinned write changing every graded bit, the frame length a pinned "
            f"{FRAME_LENGTH_PIN} that differs from its reset value); {self._drawn()}",
        )
        self._chk(
            "S3",
            "CHK-DFDR-LANE",
            f"{len(lane_cells)} CLA counter lane writes left the graded bits of the other lane "
            f"at their previous value; {lane_disc} found the other lane non-zero and different "
            f"from the written word (both lanes of every counter by a pinned write); "
            f"{self._drawn()}",
        )

    async def _s4(self) -> None:
        for name in RO_REGS:
            cell = Cell(name, "ones", LANE_MASK, pinned=True)
            await self._write_cell(cell)
        self._mark("S4")

    async def _s5(self) -> None:
        await self._ro_snapshot("after the last visit")
        self._mark("S5")
        self._chk(
            "S5",
            "CHK-DFDR-RO",
            "logged control, not graded here: "
            + " | ".join(self.ro_log)
            + "; the read-only holds are graded by smc_dfd_sink_mmr_sweep_test "
            "(CHK-DFD-SINK-MMR-READONLY) and smc_dfd_ro_mmr_write_test (CHK-DFD-RO-MMR-HELD)",
        )

    async def _s6(self) -> None:
        regs = dfd_registers()
        for name in COUNTERS:
            reg = regs[name]
            reset = reg.reset_word
            await self.csr_write(f"{name}:restore_lo", reg.addr, reset & LANE_MASK, length=4)
            await self.csr_write(f"{name}:restore_hi", reg.addr + 4, reset >> 32, length=4)
        for _, name in SINK_FUNNEL:
            reg = regs[name]
            await self.csr_write(f"{name}:restore", reg.addr, reg.reset_word, length=4)
        for name, reg in regs.items():
            pinned_bits = owned_masks()[name] | reg.rw_mask
            if name in COUNTERS:
                pinned_bits &= ~cla_field(reg, "Rsvd").mask
            got = await self._read(name, "restore_rb")
            assert got & pinned_bits == reg.reset_word & pinned_bits, (
                f"{name}: after the restore the graded bits read 0x{got & pinned_bits:x}, "
                f"reset 0x{reg.reset_word & pinned_bits:x}"
            )
            self.restored.add(name)
        self._mark("S6")
        bound = self.cfg.axi_timeout_ns
        self.waits.append(f"axi_access<={bound} ns per access ({self.accesses} accesses)")
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: %d bounded waits: %s; expiry raises AssertionError",
            len(self.waits),
            "; ".join(self.waits),
        )
        self._nonvac()

    def _nonvac(self) -> None:
        assert [st for st, _ in self.steps] == list(STEPS), f"step order {self.steps}"
        stamps = [ps for _, ps in self.steps]
        assert all(b > a for a, b in zip(stamps, stamps[1:])), f"stamps not increasing {stamps}"
        assert self.chk_lines == list(CHK_STEPS), f"checker lines {self.chk_lines}"
        listed = set(dfd_registers())
        assert self.visited == listed, f"not visited: {sorted(listed - self.visited)}"
        assert self.restored == listed, f"not restored: {sorted(listed - self.restored)}"
        assert {c.reg for c in self.drawn} == listed and len(self.drawn) == len(listed)
        check_pins(self.pinned)
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; stamps %s; checker lines %s; %d registers visited "
            "and restored; every counter lane and the disinput mask took a discriminating "
            "pinned write; %s",
            " < ".join(STEPS),
            ",".join(str(ps) for ps in stamps),
            ",".join(c for c, _ in self.chk_lines),
            len(listed),
            self._drawn(),
        )

    async def body(self) -> None:
        await self._s1()
        await self._s2()
        await self._s3()
        await self._s4()
        await self._s5()
        await self._s6()
        self.done = True
