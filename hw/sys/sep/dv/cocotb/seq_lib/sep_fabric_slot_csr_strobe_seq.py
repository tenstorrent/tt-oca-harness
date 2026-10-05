# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Byte-strobe, access-size and lock sweep over every fabric remap and filter slot.

Every slot of the five System-block fabric banks -- 16 local-master alias-remap
regions, 16 AP and 16 STEE output-remap regions, 32 outbound and 16 inbound
filter entries -- is its own register block behind its own AXI-Lite port, so a
strobe, lock or back-pressure rule has to hold at each slot, not at one.

The expected value of every register comes from a per-register model built
from the generated IP-XACT (``sep_reg_meta.register_fields``): each field's
access, reset and write-once-set flag. Bits outside every field are reserved and
read 0. Nothing is taken from the RTL.

The write rule is the AMBA AXI write-strobe rule (IHI 0022, "Write strobes"):
a byte lane whose WSTRB bit is 0 carries no data, whatever the master drives on
it. The master here drives seeded fill data on every inactive lane, as a CPU
store that replicates its byte across the bus does, so a register that ignored
the strobe would take the fill and fail the readback. The TB counts the fill at
both ends of the fabric: on the ``s_axi`` pins and at the AXI-Lite W port of
each slot register block (``fabric_slot_w_*`` in ``tb/tb_top.sv``), so the
sweep shows the fill reaches the block that applies WSTRB, on every slot. The
fill always sets the write-once-set ``FILTER_CONFIG.locked`` bit and the
alias-remap ``REGION_ATTRS.valid`` bit when their lane is inactive: a block that
ignored the strobe there would lock the entry or arm the remap.

``START_ADDR`` and ``END_ADDR`` of a filter entry are ``hw = rw``. The model
applies the write-back that ``filter_ctrl.rdl`` describes: when both land in
the same granule (4 KB with ``allow_burst`` set, 2^``data_bus_width`` bytes
without), they read back as start rounded down and end rounded up to it.

While ``FILTER_CONFIG.locked`` is set, a write to the entry's
``FILTER_CONFIG``, ``START_ADDR`` or ``END_ADDR`` leaves the entry unchanged
and completes DECERR (``filter_ctrl.rdl`` ``locked``: the write is steered to
the AXI error subordinate). Every refused write's response code is graded.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

import cocotb
from cocotb.triggers import RisingEdge
from env.sep_axi_agent import SepAxiOp
from env.sep_seeded_rng import SepSeededRng
from ocah_axi_vip import AxiTimingProfile
from sep_reg_meta import FieldMeta, indexed_block_count, register_fields, sym

from seq_lib.sep_axi_access_seq import SepAxiAccessSeq

RESP_OKAY = 0
RESP_DECERR = 3

# AXI IDs of the overlapped write/read pair. Non-zero, so the pair does not
# queue behind background ID-0 reads on s_axi.
PIPE_WR_ID = 1
PIPE_RD_ID = 2

SLOT_PROBES = ("fabric_slot_w_beats_o", "fabric_slot_w_fill_beats_o", "fabric_slot_w_fill_seen_o")
RESP_NAME = {0: "OKAY", 1: "EXOKAY", 2: "SLVERR", 3: "DECERR", -1: "none"}

# AxSIZE per transfer length in bytes; every access is naturally aligned.
SIZE_OF = {1: 0, 2: 1, 4: 2, 8: 3}

# filter_ctrl.rdl allow_burst: "4KB when it is 1".
FILTER_BURST_GRANULE_LOG2 = 12

# (bank tag, generated block prefix, registers of one slot). The register
# names are the RDL instance names in the generated header.
BANKS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "alias",
        "LOCAL_MASTER_ALIAS_REMAP_CTRL",
        ("REGION_REGION_START", "REGION_REGION_END", "REGION_REGION_ATTRS"),
    ),
    ("ap", "AP_OUTPUT_REMAP_CTRL", ("REGION_REGION_ATTRS",)),
    ("stee", "STEE_OUTPUT_REMAP_CTRL", ("REGION_REGION_ATTRS",)),
    ("outfilt", "OUTBOUND_FILTER_CTRL", ("FILTER_CONFIG", "START_ADDR", "END_ADDR")),
    ("infilt", "INBOUND_FILTER_CTRL", ("FILTER_CONFIG", "START_ADDR", "END_ADDR")),
)
FILTER_BANKS = ("outfilt", "infilt")

# Fields the sweep never sets through an active lane, and always sets through
# an inactive one. An alias region with `valid` set rewrites the CPU-LSU
# traffic this test runs on; `locked` is permanent and has its own phase.
GUARDED: dict[tuple[str, str], str] = {
    ("alias", "REGION_REGION_ATTRS"): "valid",
    ("outfilt", "FILTER_CONFIG"): "locked",
    ("infilt", "FILTER_CONFIG"): "locked",
}


def lane_bits(offset: int, nbytes: int) -> int:
    """Bit mask of byte lanes [offset, offset + nbytes) of a 64-bit word."""
    return ((1 << (8 * nbytes)) - 1) << (8 * offset)


@dataclass
class RegModel:
    bank: str
    slot: int
    name: str
    addr: int
    width: int
    fields: tuple[FieldMeta, ...]
    value: int = 0
    rw_mask: int = 0
    set_mask: int = 0
    guard_mask: int = 0

    def __post_init__(self) -> None:
        for f in self.fields:
            if f.access != "read-write":
                continue
            if f.one_to_set:
                self.set_mask |= f.mask
            else:
                self.rw_mask |= f.mask
        guard = GUARDED.get((self.bank, self.name))
        if guard is not None:
            self.guard_mask = self.field(guard).mask
        self.value = self.reset

    @property
    def reset(self) -> int:
        value = 0
        for f in self.fields:
            if f.reset is None:
                raise ValueError(f"{self.tag} field {f.name} declares no reset")
            value |= (f.reset << f.lsb) & f.mask
        return value

    @property
    def writable(self) -> int:
        return self.rw_mask | self.set_mask

    @property
    def tag(self) -> str:
        return f"{self.bank}[{self.slot}].{self.name}"

    def field(self, name: str) -> FieldMeta:
        for f in self.fields:
            if f.name == name:
                return f
        raise KeyError(f"{self.tag} has no field {name}")

    def field_value(self, name: str) -> int:
        f = self.field(name)
        return (self.value & f.mask) >> f.lsb

    def apply_write(self, offset: int, nbytes: int, data: int) -> None:
        """The AXI strobe rule over the RDL field access."""
        en = lane_bits(offset, nbytes)
        d = (data << (8 * offset)) & en
        self.value = (self.value & ~(en & self.rw_mask)) | (d & self.rw_mask)
        self.value |= d & self.set_mask

    def expect(self, offset: int, nbytes: int) -> int:
        return (self.value >> (8 * offset)) & ((1 << (8 * nbytes)) - 1)


@dataclass
class SlotModel:
    bank: str
    index: int
    regs: dict[str, RegModel]
    locked: bool = False
    lock_resp: Counter = field(default_factory=Counter)

    @property
    def tag(self) -> str:
        return f"{self.bank}[{self.index}]"

    @property
    def is_filter(self) -> bool:
        return self.bank in FILTER_BANKS

    def settle(self) -> None:
        """Apply the filter START/END granule write-back (filter_ctrl.rdl)."""
        if not self.is_filter:
            return
        cfg = self.regs["FILTER_CONFIG"]
        start = self.regs["START_ADDR"]
        end = self.regs["END_ADDR"]
        if cfg.field_value("allow_burst"):
            g = FILTER_BURST_GRANULE_LOG2
        else:
            g = cfg.field_value("data_bus_width")
        sf = start.field("start_addr")
        ef = end.field("end_addr")
        s = (start.value & sf.mask) >> sf.lsb
        e = (end.value & ef.mask) >> ef.lsb
        if s >> g == e >> g:
            low = (1 << g) - 1
            start.value = (start.value & ~sf.mask) | (((s & ~low) << sf.lsb) & sf.mask)
            end.value = (end.value & ~ef.mask) | (((e | low) << ef.lsb) & ef.mask)


def build_slots() -> list[SlotModel]:
    """Every slot of every bank; counts and addresses from the register export."""
    slots: list[SlotModel] = []
    for bank, prefix, names in BANKS:
        for idx in range(indexed_block_count(prefix)):
            regs = {}
            for name in names:
                addr = sym(f"{prefix}_{idx}__{name}_REG_ADDR")
                width, fields = register_fields(addr)
                regs[name] = RegModel(bank, idx, name, addr, width, fields)
            slots.append(SlotModel(bank, idx, regs))
    return slots


@dataclass(frozen=True)
class Access:
    offset: int
    nbytes: int


def random_access(rng: SepSeededRng) -> Access:
    nbytes = rng.choice((1, 2, 4, 8))
    return Access(rng.randrange(0, 8, nbytes), nbytes)


class SepFabricSlotCsrStrobe:
    """Drives the sweep and grades every readback against the RDL model."""

    def __init__(self, test, seed: int) -> None:
        self.test = test
        self.log = test.logger
        self.rng = SepSeededRng(seed)
        self.slots = build_slots()
        self.regs = [r for s in self.slots for r in s.regs.values()]
        agent = test.env.axi_agent
        self._master = agent.driver.axi
        self._drv = self._master.driver
        self._w_channel = self._drv.channels["w_delay"]
        self._fill: int | None = None
        self.mismatches: list[str] = []
        self.stats: Counter = Counter()
        # Slot-port W probe before and after the strobe sweep (tb_top.sv).
        self.slot_probe_before: tuple[int, int, int] = (0, 0, 0)
        self.slot_probe_after: tuple[int, int, int] = (0, 0, 0)
        self.slot_probe_width = 0
        # Per-pair s_axi pin observations of the pipeline sweep.
        self.pipe_obs: list[dict] = []

    # ------------------------------------------------------------------
    # Inactive-lane fill
    # ------------------------------------------------------------------
    def _arm_fill(self, fill: int) -> None:
        """Drive ``fill`` on every inactive lane of the next W beats.

        The backend zero-pads inactive lanes. The wrapper replaces those bytes
        on the beat object just before it is queued, and keeps WSTRB as is.
        """
        self._fill = fill
        if "send" in vars(self._w_channel):
            return
        original = self._w_channel.send

        async def send(beat, _orig=original):
            if self._fill is not None:
                strb = int(beat.wstrb)
                active = 0
                for lane in range(8):
                    if strb >> lane & 1:
                        active |= 0xFF << (8 * lane)
                beat.wdata = (int(beat.wdata) & active) | (self._fill & ~active)
            await _orig(beat)

        self._w_channel.send = send

    def _disarm_fill(self) -> None:
        self._fill = None

    def restore_w_channel(self) -> None:
        self._fill = None
        if "send" in vars(self._w_channel):
            del self._w_channel.send

    def _fill_for(self, reg: RegModel, acc: Access) -> tuple[int, bool]:
        """Seeded inactive-lane fill, and whether it would move ``reg``.

        Guarded bits are always 1 on an inactive lane. The flag says the fill
        differs from the register on at least one writable inactive bit, so a
        block that ignored the strobe would read back changed.
        """
        en = lane_bits(acc.offset, acc.nbytes)
        fill = self.rng.getrandbits(64) | (reg.guard_mask & ~en)
        moved = (fill ^ reg.value) & reg.rw_mask & ~en
        moved |= fill & ~reg.value & reg.set_mask & ~en
        return fill, bool(moved)

    # ------------------------------------------------------------------
    # Accesses
    # ------------------------------------------------------------------
    async def _read(self, reg: RegModel, acc: Access, chk: str) -> None:
        exp = reg.expect(acc.offset, acc.nbytes)
        seq = SepAxiAccessSeq(
            f"slot_rd_{reg.bank}{reg.slot}",
            op=SepAxiOp.READ,
            addr=reg.addr + acc.offset,
            length=acc.nbytes,
            size=SIZE_OF[acc.nbytes],
            expected=exp,
        )
        await self.test.start_seq(seq)
        got = seq.rdata & ((1 << (8 * acc.nbytes)) - 1)
        self.stats[f"{chk}_reads"] += 1
        if not seq.resp_ok:
            self.mismatches.append(
                f"{chk} {reg.tag} +{acc.offset}/{acc.nbytes}B read resp="
                f"{RESP_NAME.get(seq.resp_code, seq.resp_code)}"
            )
        elif got != exp:
            self.mismatches.append(
                f"{chk} {reg.tag} +{acc.offset}/{acc.nbytes}B read 0x{got:0{2 * acc.nbytes}x}"
                f" != model 0x{exp:0{2 * acc.nbytes}x}"
            )

    async def _write(self, reg: RegModel, acc: Access, data: int, *, locked: bool) -> int:
        """One strobed write with inactive-lane fill; returns the response code."""
        fill, moved = self._fill_for(reg, acc)
        if not locked:
            self.stats["inactive_fill_writes"] += moved
        self._arm_fill(fill)
        mon = self.test.env.axi_monitor
        if locked:
            mon.arm_expected_decerr(1)
        try:
            seq = SepAxiAccessSeq(
                f"slot_wr_{reg.bank}{reg.slot}",
                op=SepAxiOp.WRITE,
                addr=reg.addr + acc.offset,
                wdata=data & ((1 << (8 * acc.nbytes)) - 1),
                length=acc.nbytes,
                size=SIZE_OF[acc.nbytes],
                allow_unverified_write_resp=locked,
            )
            await self.test.start_seq(seq)
        finally:
            self._disarm_fill()
        if locked and (seq.timed_out or seq.resp_code != RESP_DECERR):
            mon.release_expected_decerr(1)
        return seq.resp_code

    def _data_for(self, reg: RegModel, acc: Access) -> int:
        """Seeded data with the guarded field held at 0 on the active lanes."""
        data = self.rng.getrandbits(8 * acc.nbytes)
        return data & ~(reg.guard_mask >> (8 * acc.offset))

    # ------------------------------------------------------------------
    # Phases
    # ------------------------------------------------------------------
    async def reset_walk(self) -> None:
        """CHK-SLOT-RESET: every register reads its RDL reset, whole and by word."""
        order = list(self.regs)
        self.rng.shuffle(order)
        for reg in order:
            await self._read(reg, Access(0, 8), "CHK-SLOT-RESET")
            await self._read(reg, Access(self.rng.choice((0, 4)), 4), "CHK-SLOT-RESET")

    def _plan(self) -> list[Access]:
        """One full write, one write per byte lane, and two random-size writes."""
        lanes = [Access(lane, 1) for lane in range(8)]
        plan = [Access(0, 8), *lanes]
        for _ in range(2):
            nbytes = self.rng.choice((2, 4))
            plan.append(Access(self.rng.randrange(0, 8, nbytes), nbytes))
        self.rng.shuffle(plan)
        return plan

    async def _watch_w_lanes(self) -> None:
        """Count W handshakes on the TB port that carry data on an inactive lane.

        Sampled on the pins, so it shows the fill reached the bus rather than
        the beat object.
        """
        dut = cocotb.top
        while True:
            await RisingEdge(dut.clk_i)
            if dut.s_axi_wvalid.value != 1 or dut.s_axi_wready.value != 1:
                continue
            strb = int(dut.s_axi_wstrb.value)
            inactive = 0
            for lane in range(8):
                if not strb >> lane & 1:
                    inactive |= 0xFF << (8 * lane)
            self.stats["w_beats"] += 1
            self.stats["w_beats_inactive_data"] += bool(int(dut.s_axi_wdata.value) & inactive)

    def _slot_probe(self) -> tuple[int, int, int]:
        """Read the slot-port W counters and the per-slot fill-seen vector."""
        vals = []
        for name in SLOT_PROBES:
            v = getattr(cocotb.top, name).value
            if not v.is_resolvable:
                raise AssertionError(f"CHK-SLOT-STROBE FAIL: {name} is unresolvable ({v})")
            vals.append(int(v))
        self.slot_probe_width = len(cocotb.top.fabric_slot_w_fill_seen_o.value)
        return vals[0], vals[1], vals[2]

    def slots_without_fill(self) -> list[str]:
        """Slots whose register-block W port saw no fill during the strobe sweep."""
        seen = self.slot_probe_after[2]
        return [s.tag for k, s in enumerate(self.slots) if not seen >> k & 1]

    async def strobe_sweep(self) -> None:
        """CHK-SLOT-STROBE: each write lands on exactly its enabled lanes."""
        self.slot_probe_before = self._slot_probe()
        watch = cocotb.start_soon(self._watch_w_lanes())
        try:
            await self._strobe_sweep()
        finally:
            watch.kill()
        await RisingEdge(cocotb.top.clk_i)
        self.slot_probe_after = self._slot_probe()

    async def _strobe_sweep(self) -> None:
        order = list(self.slots)
        self.rng.shuffle(order)
        for slot in order:
            regs = list(slot.regs.values())
            self.rng.shuffle(regs)
            for reg in regs:
                for acc in self._plan():
                    data = self._data_for(reg, acc)
                    before = reg.value
                    resp = await self._write(reg, acc, data, locked=False)
                    if resp != RESP_OKAY:
                        self.mismatches.append(
                            f"CHK-SLOT-STROBE {reg.tag} +{acc.offset}/{acc.nbytes}B write "
                            f"resp={RESP_NAME.get(resp, resp)} on an unlocked slot"
                        )
                    reg.apply_write(acc.offset, acc.nbytes, data)
                    slot.settle()
                    self.stats["strobe_writes"] += 1
                    self.stats["strobe_writes_moved"] += reg.value != before
                    await self._read(reg, random_access(self.rng), "CHK-SLOT-STROBE")
                await self._read(reg, Access(0, 8), "CHK-SLOT-STROBE")

    async def _watch_pair(self, obs: dict) -> None:
        """Sample the s_axi pins for one overlapped pair.

        Records the first cycle AWVALID (ID ``PIPE_WR_ID``) and WVALID are high,
        the cycles in which both the write and the read have been accepted
        (AW and AR handshakes done) and neither response has handshaked yet,
        and the cycles B or R waited with VALID high and READY low.
        """
        dut = cocotb.top
        cycle = 0
        aw_acc = ar_acc = b_done = r_done = False
        while True:
            await RisingEdge(dut.clk_i)
            cycle += 1
            if aw_acc and ar_acc and not b_done and not r_done:
                obs["overlap"] += 1
            awv = dut.s_axi_awvalid.value == 1
            if awv and int(dut.s_axi_awid.value) == PIPE_WR_ID:
                if obs["first_aw"] is None:
                    obs["first_aw"] = cycle
                aw_acc |= dut.s_axi_awready.value == 1
            if dut.s_axi_wvalid.value == 1 and obs["first_w"] is None:
                obs["first_w"] = cycle
            if dut.s_axi_arvalid.value == 1 and int(dut.s_axi_arid.value) == PIPE_RD_ID:
                ar_acc |= dut.s_axi_arready.value == 1
            if dut.s_axi_bvalid.value == 1 and int(dut.s_axi_bid.value) == PIPE_WR_ID:
                if dut.s_axi_bready.value == 1:
                    b_done = True
                else:
                    obs["b_wait"] += 1
            if dut.s_axi_rvalid.value == 1 and int(dut.s_axi_rid.value) == PIPE_RD_ID:
                if dut.s_axi_rready.value == 1:
                    r_done = True
                else:
                    obs["r_wait"] += 1

    async def _pair(self, slot: SlotModel, profile: AxiTimingProfile, kind: str) -> None:
        """A lo-word write and a hi-word read of one register, issued together.

        The read targets the half the write does not strobe, so its value is
        the same whichever order the DUT serves them in. The s_axi pins are
        graded for the overlap: both accepted and unanswered in one cycle; for
        ``hold`` both responses wait on READY; for ``w_first`` WVALID rises
        before AWVALID.
        """
        reg = self.rng.choice(list(slot.regs.values()))
        wacc, racc = Access(0, 4), Access(4, 4)
        data = self._data_for(reg, wacc)
        exp_rd = reg.expect(racc.offset, racc.nbytes)
        fill, moved = self._fill_for(reg, wacc)
        self.stats["inactive_fill_writes"] += moved
        self._arm_fill(fill)
        self._drv.set_timing(profile)
        obs = {
            "kind": kind,
            "overlap": 0,
            "first_aw": None,
            "first_w": None,
            "b_wait": 0,
            "r_wait": 0,
        }
        watch = cocotb.start_soon(self._watch_pair(obs))
        try:
            wr = cocotb.start_soon(
                self._master.write_bytes_result(
                    reg.addr,
                    data.to_bytes(4, "little"),
                    size=SIZE_OF[4],
                    id=PIPE_WR_ID,
                    check_response=False,
                )
            )
            rd = cocotb.start_soon(
                self._master.read_bytes_result(
                    reg.addr + racc.offset,
                    4,
                    size=SIZE_OF[4],
                    id=PIPE_RD_ID,
                    check_response=False,
                )
            )
            wres = await wr
            rres = await rd
        finally:
            watch.kill()
            self._drv.set_timing(AxiTimingProfile())
            self._disarm_fill()
        reg.apply_write(wacc.offset, wacc.nbytes, data)
        slot.settle()
        self.stats["pairs"] += 1
        self.pipe_obs.append(obs)
        where = f"CHK-SLOT-PIPE {reg.tag} [{kind}: {profile.summary()}]"
        if not obs["overlap"]:
            self.mismatches.append(
                f"{where} no cycle on s_axi with both the write and the read accepted "
                "and unanswered"
            )
        if kind == "hold" and not (obs["b_wait"] and obs["r_wait"]):
            self.mismatches.append(
                f"{where} B waited {obs['b_wait']} and R waited {obs['r_wait']} cycles on "
                "READY; the hold did not reach both response channels"
            )
        if kind == "w_first" and not (
            obs["first_w"] is not None
            and obs["first_aw"] is not None
            and obs["first_w"] < obs["first_aw"]
        ):
            self.mismatches.append(
                f"{where} WVALID first high at cycle {obs['first_w']}, AWVALID at "
                f"{obs['first_aw']}; W did not lead AW on s_axi"
            )
        got = int.from_bytes(rres.data_bytes, "little") if rres.data_bytes else rres.data
        if wres.resp != RESP_OKAY or rres.resp != RESP_OKAY:
            self.mismatches.append(
                f"CHK-SLOT-PIPE {reg.tag} [{profile.summary()}] write resp="
                f"{RESP_NAME.get(wres.resp, wres.resp)} read resp="
                f"{RESP_NAME.get(rres.resp, rres.resp)}"
            )
        elif got != exp_rd:
            self.mismatches.append(
                f"CHK-SLOT-PIPE {reg.tag} [{profile.summary()}] hi-word read 0x{got:08x}"
                f" != model 0x{exp_rd:08x}"
            )
        await self._read(reg, Access(0, 8), "CHK-SLOT-PIPE")

    async def pipeline_sweep(self) -> None:
        """CHK-SLOT-PIPE: a write and a read outstanding together at s_axi, per slot.

        One pair holds BREADY and RREADY for longer than a response takes to
        arrive (the hold counts from the request), so both responses wait;
        the other presents W ahead of AW with RREADY held. Overlap is graded
        on the s_axi pins only, not at the slot's own AXI-Lite port.
        """
        order = list(self.slots)
        self.rng.shuffle(order)
        for slot in order:
            await self._pair(
                slot,
                AxiTimingProfile(
                    b_ready_delay=self.rng.randrange(40, 72),
                    r_ready_delay=self.rng.randrange(40, 72),
                ),
                "hold",
            )
            await self._pair(
                slot,
                AxiTimingProfile(
                    aw_delay=self.rng.randrange(1, 5),
                    r_ready_delay=self.rng.randrange(16, 48),
                ),
                "w_first",
            )

    def _refused_access(self, slot: SlotModel, reg: RegModel) -> tuple[Access, int]:
        """An access and data that would move the entry if the write were taken.

        Checked on a copy of the slot model with the granule write-back
        applied, so a write the write-back would undo is never chosen.
        """
        for _ in range(256):
            acc = random_access(self.rng)
            data = self.rng.getrandbits(8 * acc.nbytes)
            saved = {name: r.value for name, r in slot.regs.items()}
            reg.apply_write(acc.offset, acc.nbytes, data)
            slot.settle()
            moved = any(r.value != saved[name] for name, r in slot.regs.items())
            for name, r in slot.regs.items():
                r.value = saved[name]
            if moved:
                return acc, data
        raise RuntimeError(f"{reg.tag}: no write found that would move the locked entry")

    async def lock_sweep(self, writes_per_entry: int = 4) -> None:
        """CHK-SLOT-LOCK: every filter entry locks, then ignores its writes."""
        order = [s for s in self.slots if s.is_filter]
        self.rng.shuffle(order)
        for slot in order:
            cfg = slot.regs["FILTER_CONFIG"]
            lock = cfg.field("locked")
            lane = lock.lsb // 8
            acc = self.rng.choice((Access(lane, 1), Access(4, 4), Access(0, 8)))
            data = self._data_for(cfg, acc) | (lock.mask >> (8 * acc.offset))
            resp = await self._write(cfg, acc, data, locked=False)
            if resp != RESP_OKAY:
                self.mismatches.append(
                    f"CHK-SLOT-LOCK {cfg.tag} lock-setting write resp="
                    f"{RESP_NAME.get(resp, resp)}; the entry is unlocked before this write"
                )
            cfg.apply_write(acc.offset, acc.nbytes, data)
            slot.settle()
            slot.locked = True
            await self._read(cfg, Access(0, 8), "CHK-SLOT-LOCK")
            for _ in range(writes_per_entry):
                reg = self.rng.choice(list(slot.regs.values()))
                racc, rdata = self._refused_access(slot, reg)
                code = await self._write(reg, racc, rdata, locked=True)
                self._grade_locked_resp(reg, code)
                slot.lock_resp[RESP_NAME.get(code, str(code))] += 1
                self.stats["locked_writes"] += 1
                await self._read(reg, random_access(self.rng), "CHK-SLOT-LOCK")
            # Writing 0 to the lock bit leaves it set (onwrite = woset).
            code = await self._write(cfg, Access(lane, 1), 0, locked=True)
            self._grade_locked_resp(cfg, code)
            slot.lock_resp[RESP_NAME.get(code, str(code))] += 1
            self.stats["locked_writes"] += 1
            for reg in slot.regs.values():
                await self._read(reg, Access(0, 8), "CHK-SLOT-LOCK")

    def _grade_locked_resp(self, reg: RegModel, code: int) -> None:
        """A write to a locked entry completes DECERR (filter_ctrl.rdl ``locked``)."""
        if code != RESP_DECERR:
            self.mismatches.append(
                f"CHK-SLOT-LOCK {reg.tag} write to a locked entry resp="
                f"{RESP_NAME.get(code, code)}, expected DECERR"
            )

    async def final_walk(self) -> None:
        """CHK-SLOT-FINAL: every register still holds its own model value."""
        order = list(self.regs)
        self.rng.shuffle(order)
        for reg in order:
            await self._read(reg, Access(0, 8), "CHK-SLOT-FINAL")

    def lock_codes(self) -> Counter:
        total: Counter = Counter()
        for slot in self.slots:
            total.update(slot.lock_resp)
        return total
