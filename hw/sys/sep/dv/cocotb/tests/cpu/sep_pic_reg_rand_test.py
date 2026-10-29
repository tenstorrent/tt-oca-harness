# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The PIC register map, its reset state, its holes, entry 0 and source 0 meet the EL2_PIC contract.

Firmware ``pic_reg_rand_test`` reads and writes the PIC registers from the CPU
and prints one record line per check (``fw/tests/common/sep_console_rec.h``).
This test draws the entries, values, ``meigwclr`` values, hole addresses and
group order from the run seed, patches them into the firmware parameter block,
follows the console live (``env/sep_fw_console``: graded window on ``M G`` /
``M C``) and grades:

* CHK-RESET    (firmware) every PIC field reads its RDL reset value before the
               first PIC write;
               ``meip`` with the six excluded idle bits masked
               (``OBS-IDLE-UNSTATED``).
* CHK-RESET-X  (host, VCS) no reset read returns X: ``pic_rd_data_probe_o``
               samples each reset read, its count per group equals the
               firmware read count, and at the ``CHK-RW`` read-backs the probe
               equals the read value the firmware prints (control).
* CHK-HOLE     (firmware) a CPU access to each of the five holes and to the
               past-extent range reads 0, traps nothing, and leaves the seven
               armed alias targets unchanged; the armed fields read 0 after
               their restore writes.
* CHK-RW       (firmware) each implemented field holds the written value; for
               a drawn 0 the read-back of the inverse write first equals the
               field mask.
* CHK-ENTRY0   (firmware) entry 0 of the four arrays reads 0 after an all-ones
               write, and the write does not land in entry 1.
* CHK-GWCLR0   (firmware) ``meigwclr`` reads 0 after a write with the
               ``clear`` bit 1 (each drawn value has it set), and the
               ``meigwctrl`` write before it reads back the written value;
               control: the same write drops a held edge pending bit of
               source 1.
* CHK-MEIP-WR  (firmware) a 4-byte store of 0, then of all ones, to ``meip[0]``
               leaves the word unchanged (``meip`` access R): the read
               before each store holds the bit of a held edge source 1 and
               no other graded bit (else the store is not issued and the
               check fails), and the read after the store equals it, with
               the six excluded idle bits masked. The store response (trap
               or not) is logged as ``OBS-PIC-MEIP-WR``. The
               ``cp_group_x_dir[meip_wr]`` sample is the same compare: read
               after == read before, non-zero, idle bits masked.
* CHK-MEIP-WR-STORE (host) each CHK-MEIP-WR instance has exactly one PIC
               register write at the ``meip[0]`` offset on ``pic_wr_probe_o``
               (the core PIC write strobe), from the ``meip_wr`` marker or the
               CHK line of the instance before to the CHK line of the instance,
               so a store that never reaches the PIC fails. The owner-318 cells
               of the leg release only after both instances passed this check.
* CHK-SRC0     (firmware) source 0 never sets and never takes a handler, in the
               all-ones and the level active-low legs; control: the source 1
               handler runs once.

Each graded firmware leg (``M G``) holds only accesses that its CHK lines
grade. The owner-318 access and value cells of ``sep_pic_reg_map_cg`` are held
by the sampler and released by bit ``PIC_FW_PASS_PIC_REG`` of the
``pic_fw_pass`` label, which this test raises once every CHK line of the graded
leg (``release_plan``) has passed. The test writes bit ``PIC_FW_PASS_DROP_318``
at every ``M G`` line and on every FAIL line; its rise, the next window open of
the owner and a reset drop the held cells, so a cell of a failed leg never
samples on the pass of a later leg.

Expected values are the RDL reset and field layout
(``hw/sys/sep/regs/gen/adoc/blocks/el2_pic.adoc``) and the drawn stimulus,
never a DUT read-back. cpu run mode, ``+skip_fuse_sense``; VCS grades
CHK-RESET-X. Verilator is two-state, so it logs each group as
``OBS-BLOCKED CHK-RESET-X reason=two_state``, runs the value checks, and grades
the probe compare as the control ``CTRL-RESET-X``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge
from env.sep_boot_scoreboard import SepBootScoreboard
from env.sep_dtcm_param_patch import patch_param_block
from env.sep_fcov_gate import (
    PIC_FW_PASS_DROP_318,
    PIC_FW_PASS_PIC_REG,
    close_graded_window,
    set_pic_fw_pass,
)
from env.sep_fw_console import SepFwConsole
from env.sep_pic_map import meip_idle_mask_words
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from sep_reg_meta import RegBlock, sep_addr_define, sym

TEST = "sep_pic_reg_rand_test"
_DV_ROOT = str(Path(__file__).resolve().parents[3])
_FW_DIR = os.path.join(_DV_ROOT, "fw", "build", "tests", "pic_reg_rand_test")
_ITCM_HEX = os.path.join(_FW_DIR, "pic_reg_rand_test.itcm.hex")
_DTCM_HEX = os.path.join(_FW_DIR, "pic_reg_rand_test.dtcm.hex")
_BANNER = "SEP PIC register map test"
_ICCM_BASE = sym("SEP_ICCM_MEM_BASE_ADDR")
PIC_BASE = sym("PIC_REG_MAP_BASE_ADDR")
# meip[0] offset inside the PIC aperture (the pic_wr_probe_o address bits [14:0]).
MEIP0_OFF = sym("PIC_MEIP_0__REG_OFFSET")
_MAX_RUN_CYCLES = 8_000_000
_NO_BOOT_CYCLES = 80_000

# Parameter block (fw/tests/pic_reg_rand_test, enum P_*).
P_MAGIC = 0x318E6A11
NE_MAX = 12
N_HOLE = 6
HOLD_ITERS = 2000
WAIT_ITERS = 20_000
ANCHORS = (1, 43, 44, 128, 255)
RANGES = ((2, 42), (45, 127), (129, 254))
GROUPS = ("meipl", "meie", "meigwctrl")
EL2_PIC = RegBlock("EL2_PIC")
FIELD_MAX = {
    "meipl": EL2_PIC.mask32("MEIPL"),
    "meie": EL2_PIC.mask32("MEIE"),
    "meigwctrl": EL2_PIC.mask32("MEIGWCTRL"),
}
# The only RDL field of meigwclr; every drawn meigwclr value has it set.
GWCLR_CLEAR = EL2_PIC.field_mask("MEIGWCLR", "clear")

# Hole ranges inside the 32 KiB aperture and the past-extent range (offsets).
# Each address keeps an entry index K (1..254) in bits [9:2]; a range is a set
# of 1 KiB pages, and a page holds K * 4 from its base.
HOLE_PAGES = (
    ("hole_meipl", (0x0400, 0x0800, 0x0C00), 1),
    ("hole_meip", (0x1000, 0x1400, 0x1800, 0x1C00), 8),  # page 0x1000: K >= 8 (0x1020)
    ("hole_meie", (0x2400, 0x2800, 0x2C00), 1),
    ("hole_mpiccfg", (0x3000, 0x3400, 0x3800, 0x3C00), 1),
    ("hole_meigwctrl", (0x4400, 0x4800, 0x4C00), 1),
    ("past_extent", tuple(range(0x5400, 0x8000, 0x400)), 1),
)


def _array_span(name: str) -> tuple[str, int, int]:
    """(group, first offset, end offset) of a PIC register array, from the RDL."""
    lo = sym(f"PIC_{name}_0__REG_OFFSET")
    stride = sym(f"PIC_{name}_1__REG_OFFSET") - lo
    return name.lower(), lo, lo + stride * sep_addr_define(f"SEP_TOP_PIC_{name}_NUM")


# Register group of a PIC read address (offset bits [14:0]) for the probe count.
_RD_GROUPS = (
    _array_span("MEIPL"),
    _array_span("MEIP"),
    _array_span("MEIE"),
    ("mpiccfg", sym("PIC_MPICCFG_REG_OFFSET"), sym("PIC_MPICCFG_REG_OFFSET") + 4),
    _array_span("MEIGWCTRL"),
    _array_span("MEIGWCLR"),
)


def release_plan(ne: int) -> dict[str, tuple[str, int]]:
    """Graded firmware leg -> (CHK name, PASS lines) that release its held cells.

    The CHK lines of the ``gwclr`` leg print in the control leg after it, so a
    record counts toward the last graded leg.
    """
    return {
        "reset": ("CHK-RESET", 6),
        "hole": ("CHK-HOLE", N_HOLE),
        "array": ("CHK-RW", 3 * ne + 2),
        "entry0": ("CHK-ENTRY0", 1),
        "gwclr": ("CHK-GWCLR0", ne),
        "meip_wr": ("CHK-MEIP-WR", 2),
        "src0_allones": ("CHK-SRC0", 1),
        "src0_lowlevel": ("CHK-SRC0", 1),
    }


def rd_group(off: int) -> str:
    for name, lo, hi in _RD_GROUPS:
        if lo <= off < hi:
            return name
    return "other"


@dataclass
class PicRegCfg:
    """The seeded stimulus. A pure function of the run seed."""

    seed: int
    entries: list[int] = field(default_factory=list)
    vals: dict[str, list[int]] = field(default_factory=dict)
    gwclr: list[int] = field(default_factory=list)
    holes: list[int] = field(default_factory=list)
    gorder: list[int] = field(default_factory=list)

    @classmethod
    def from_seed(cls, seed: int) -> "PicRegCfg":
        rng = SepSeededRng(seed)
        ents = list(ANCHORS)
        for lo, hi in RANGES:
            ents.append(rng.randrange(lo, hi + 1))
        n_extra = rng.randrange(0, NE_MAX - len(ents) + 1)
        while n_extra:
            n = rng.randrange(1, 256)
            if n not in ents:
                ents.append(n)
                n_extra -= 1
        rng.shuffle(ents)
        ne = len(ents)
        meipl = [rng.randrange(0, FIELD_MAX["meipl"] + 1) for _ in range(ne)]
        meie = [rng.randrange(0, FIELD_MAX["meie"] + 1) for _ in range(ne)]
        gw = [rng.randrange(0, FIELD_MAX["meigwctrl"] + 1) for _ in range(ne)]
        # Every meigwctrl value at least once, and the four (meie, meipl)
        # arming cells (0,0) (1,0) (0,nz) (1,nz) at least once, every seed.
        idx = rng.sample(range(ne), 4)
        for v, i in zip(rng.sample(range(4), 4), idx, strict=True):
            gw[i] = v
        idx = rng.sample(range(ne), 4)
        for (ie, nz), i in zip(((0, 0), (1, 0), (0, 1), (1, 1)), idx, strict=True):
            meie[i] = ie
            meipl[i] = rng.randrange(1, 16) if nz else 0
        gwclr = [rng.randrange(0, 1 << 32) | GWCLR_CLEAR for _ in range(ne)]
        holes = []
        for _, pages, kmin in HOLE_PAGES:
            page = rng.choice(pages)
            k = rng.randrange(kmin if page == pages[0] else 1, 255)
            holes.append(PIC_BASE + page + 4 * k)
        gorder = [0, 1, 2]
        rng.shuffle(gorder)
        return cls(
            seed, ents, {"meipl": meipl, "meie": meie, "meigwctrl": gw}, gwclr, holes, gorder
        )

    def words(self) -> list[int]:
        ne = len(self.entries)
        pad = [0] * (NE_MAX - ne)
        gorder = self.gorder[0] | (self.gorder[1] << 4) | (self.gorder[2] << 8)
        return [
            P_MAGIC,
            self.seed & 0xFFFF_FFFF,
            ne,
            gorder,
            HOLD_ITERS,
            WAIT_ITERS,
            *meip_idle_mask_words(),
            *self.holes,
            *self.entries,
            *pad,
            *self.vals["meipl"],
            *pad,
            *self.vals["meie"],
            *pad,
            *self.vals["meigwctrl"],
            *pad,
            *self.gwclr,
            *pad,
        ]

    def draw_lines(self) -> list[str]:
        out = [
            "DRAW entries=" + ",".join(str(e) for e in self.entries),
            "DRAW group_order=" + ",".join(GROUPS[g] for g in self.gorder),
        ]
        for g in GROUPS:
            out.append(f"DRAW {g}=" + ",".join(str(v) for v in self.vals[g]))
        out.append("DRAW meigwclr=" + ",".join(f"0x{v:08x}" for v in self.gwclr))
        for (name, _, _), a in zip(HOLE_PAGES, self.holes, strict=True):
            out.append(f"DRAW hole range={name} addr=0x{a:08x} k={(a >> 2) & 0xFF}")
        return out


@pyuvm.test()
class sep_pic_reg_rand_test(sep_base_test):
    """PIC register map, reset state, holes, entry 0 and source 0 meet the EL2_PIC contract."""

    build_env = False
    required_evidence: tuple[str, ...] = (
        "CHK-RESET",
        "CHK-HOLE",
        "CHK-RW",
        "CHK-ENTRY0",
        "CHK-GWCLR0",
        "CHK-MEIP-WR",
        "CHK-MEIP-WR-STORE",
        "CHK-SRC0",
    )

    def build_phase(self) -> None:
        super().build_phase()
        self.sb = SepBootScoreboard("sb", self)

    async def _probe(self) -> None:
        """Every PIC register read on ``pic_rd_data_probe_o`` (valid when bit 47 is 1)
        and every PIC register write on ``pic_wr_probe_o`` (valid when bit 15 is 1)."""
        dut = cocotb.top
        sig = dut.pic_rd_data_probe_o
        wsig = dut.pic_wr_probe_o
        while True:
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            w = wsig.value
            if w.is_resolvable:
                iw = int(w)
                if (iw >> 15) & 1:
                    self.writes.append((self.con.clk, iw & 0x7FFF))
            else:
                self.writes.append((self.con.clk, -1))
            v = sig.value
            if v.is_resolvable:
                iv = int(v)
                if (iv >> 47) & 1:
                    self.reads.append((self.con.clk, (iv >> 32) & 0x7FFF, iv & 0xFFFF_FFFF, True))
                continue
            s = v.binstr[::-1]  # index 0 = bit 0
            if s[47] == "1":
                addr = int(s[32:47][::-1].replace("x", "0").replace("z", "0"), 2)
                self.reads.append((self.con.clk, addr, None, False))
            elif s[47] not in "01":
                self.reads.append((self.con.clk, -1, None, False))

    def _meip_stores(self) -> tuple[list[int], list[int]]:
        """(meip[0] writes, other PIC writes) per CHK-MEIP-WR instance.

        Instance k spans the console clocks from the ``M G meip_wr`` line (k = 0)
        or the CHK-MEIP-WR line of instance k - 1 to its own CHK-MEIP-WR line.
        A write with an X or Z bit counts as another write.
        """
        want = MEIP0_OFF
        start = None
        ends: list[int] = []
        for clk, text in self.con.lines:
            if text == "M G meip_wr":
                start = clk
            elif start is not None and text.startswith("CHK-MEIP-WR "):
                ends.append(clk)
            elif start is not None and text.startswith("M "):
                break
        mine: list[int] = []
        other: list[int] = []
        lo = start if start is not None else 0
        for hi in ends:
            win = [off for clk, off in self.writes if lo <= clk < hi]
            mine.append(sum(1 for off in win if off == want))
            other.append(sum(1 for off in win if off != want))
            lo = hi
        return mine, other

    async def _pass_label(self, plan: dict[str, tuple[str, int]]) -> None:
        """Raise the ``pic_fw_pass`` bits of this test: release and drop.

        Follows the console lines in order, after each rising edge (a write is
        legal there). A ``M G`` line starts a leg and writes the drop bit
        (``PIC_FW_PASS_DROP_318``), so the cells still held from an earlier leg
        never sample in the new one; each CHK record counts toward the last
        graded leg. When the leg's check printed its planned number of PASS
        lines and no CHK line of the leg failed, the release bit
        (``PIC_FW_PASS_PIC_REG``) is written. Any FAIL line writes the drop
        bit. The ``meip_wr`` leg also needs one PIC write at ``meip[0]`` per
        instance (CHK-MEIP-WR-STORE) before its release; a missing write drops
        it. Each bit is held two clocks and written 0, in the order of the
        console lines.
        """
        dut = cocotb.top
        drop = 1 << PIC_FW_PASS_DROP_318
        seen = 0
        leg = None
        count = 0
        failed = released = False
        while True:
            await RisingEdge(dut.clk_i)
            lines = self.con.lines
            acts: list[int] = []
            while seen < len(lines):
                text = lines[seen][1]
                seen += 1
                if text.startswith("M G "):
                    leg = text.split(None, 2)[2]
                    count = 0
                    failed = released = False
                    acts.append(drop)
                    continue
                if not text.startswith("CHK-"):
                    continue
                name, _, rest = text.partition(" ")
                if rest.startswith("FAIL"):
                    failed = True
                    acts.append(drop)
                    continue
                if leg not in plan:
                    continue
                if name == plan[leg][0] and rest.startswith("PASS"):
                    count += 1
                if not failed and not released and count == plan[leg][1]:
                    if leg == "meip_wr" and self._meip_stores()[0] != [1] * count:
                        failed = True
                        acts.append(drop)
                        continue
                    released = True
                    acts.append(1 << PIC_FW_PASS_PIC_REG)
            for bits in acts:
                set_pic_fw_pass(bits, self.logger)
                await ClockCycles(dut.clk_i, 2)
                set_pic_fw_pass(0, self.logger)

    def _leg_clk(self, leg: str) -> tuple[int, int]:
        """(start, end) console clock of leg ``leg``: its marker to the next marker."""
        legs = self.con.legs
        for i, (clk, _, name) in enumerate(legs):
            if name == leg:
                end = legs[i + 1][0] if i + 1 < len(legs) else 1 << 62
                return clk, end
        raise AssertionError(f"CHK-FW-CONSOLE FAIL: leg '{leg}' never started")

    def _chk_reset_x(self, four_state: bool) -> int:
        ne = len(self.tcfg.entries)
        fw_reads = {
            "meipl": ne,
            "meie": ne,
            "meigwctrl": ne,
            "meigwclr": ne,
            "mpiccfg": 1,
            "meip": 8,
        }
        lo, hi = self._leg_clk("reset")
        rst = [r for r in self.reads if lo <= r[0] < hi]
        # Control: the CHK-RW read-backs of the array corner, in order. A cell with
        # a drawn 0 reads twice: the inverse read-back (raw_inv), then the cell (raw).
        arr_lo, arr_hi = self._leg_clk("array")
        arr = [r for r in self.reads if arr_lo <= r[0] < arr_hi]
        rw = [r for r in self.con.records("CHK-RW") if arr_lo <= r.clk]
        seq = [
            (rec.kv.get("group"), key, rec.kv.get(key))
            for rec in rw
            for key in ("raw_inv", "raw")
            if key in rec.kv
        ]
        n_inv = sum(1 for rec in rw if "raw_inv" in rec.kv)
        ctrl_reads = len(seq)
        ctrl_match = 0
        ctrl_nonzero = 0
        mism: list[tuple] = []
        for i, (grp, key, raw) in enumerate(seq):
            if i < len(arr) and arr[i][3] and arr[i][2] == raw:
                ctrl_match += 1
                ctrl_nonzero += int(raw != 0)
            elif len(mism) < 4:
                got = arr[i][2] if i < len(arr) else None
                mism.append((i, grp, key, raw, got))
        ctrl_ok = (
            len(rw) == 3 * ne + 2
            and ctrl_reads == len(rw) + n_inv
            and len(arr) == ctrl_reads
            and ctrl_match == ctrl_reads
            and ctrl_nonzero >= 1
        )
        n = 0
        for grp, want in fw_reads.items():
            mine = [r for r in rst if r[1] >= 0 and rd_group(r[1]) == grp]
            x_seen = sum(1 for r in mine if not r[3]) + sum(1 for r in rst if r[1] < 0)
            ok = len(mine) == want and x_seen == 0 and ctrl_ok
            body = (
                f"group={grp} reads_sampled={len(mine)} fw_reads={want} x_seen={x_seen} "
                f"ctrl_reads={ctrl_reads} ctrl_sampled={len(arr)} ctrl_match={ctrl_match} "
                f"ctrl_nonzero={ctrl_nonzero}"
            )
            if not four_state:
                self.logger.info("OBS-BLOCKED CHK-RESET-X reason=two_state %s", body)
                continue
            if not ok:
                raise AssertionError(
                    f"CHK-RESET-X FAIL seed={self.tcfg.seed} {body} other={len(rst)} mism={mism}"
                )
            self.logger.info("CHK-RESET-X PASS seed=%d %s", self.tcfg.seed, body)
            n += 1
        if not four_state:
            if not ctrl_ok:
                raise AssertionError(
                    f"CTRL-RESET-X FAIL: probe read-backs do not match the firmware ({ctrl_match}/"
                    f"{ctrl_reads}, sampled {len(arr)}) mism={mism}"
                )
            self.logger.info(
                "CTRL-RESET-X LOG ctrl_reads=%d ctrl_sampled=%d ctrl_match=%d ctrl_nonzero=%d",
                ctrl_reads,
                len(arr),
                ctrl_match,
                ctrl_nonzero,
            )
        return n

    async def run_scenario(self) -> None:
        seed = self.random_seed()
        self.tcfg = PicRegCfg.from_seed(seed)
        self.logger.info("SEED seed=%d", seed)
        for line in self.tcfg.draw_lines():
            self.logger.info("%s", line)
        four_state = cocotb.SIM_NAME.lower() not in ("verilator",)
        if four_state:
            self.required_evidence = (*type(self).required_evidence, "CHK-RESET-X")
        dtcm = os.path.join(os.getcwd(), "sep_dtcm_pic_reg.hex")
        patch_param_block(_DTCM_HEX, dtcm, P_MAGIC, self.tcfg.words())
        self.sb.expected_line = _BANNER
        self.reads: list[tuple[int, int, int | None, bool]] = []
        self.writes: list[tuple[int, int]] = []
        self.con = SepFwConsole(self, graded_test=TEST).start()
        probe = cocotb.start_soon(self._probe())
        lbl = cocotb.start_soon(self._pass_label(release_plan(len(self.tcfg.entries))))
        close_graded_window(self.logger)
        set_pic_fw_pass(0, self.logger)
        try:
            await self.boot_firmware(
                self.sb,
                _ITCM_HEX,
                dtcm,
                rst_vec=_ICCM_BASE >> 1,
                max_run_cycles=_MAX_RUN_CYCLES,
                no_boot_cycles=_NO_BOOT_CYCLES,
            )
        finally:
            probe.cancel()
            lbl.cancel()
            await self.con.stop()
        if not (self.sb.fw_done and self.sb.fw_pass):
            self.con.relay_chk()
            raise AssertionError("firmware did not complete with PASS")
        prm = self.con.text_lines("PARAMS")
        want = f"seed=0x{seed & 0xFFFF_FFFF:08x} ne={len(self.tcfg.entries)}"
        if not prm or want not in prm[0]:
            raise AssertionError(f"firmware did not run the patched block: {prm} (want {want})")

        n_fw = self.con.relay_chk()
        ne = len(self.tcfg.entries)
        self.con.require_counts(
            {
                "CHK-RESET": 6,
                "CHK-HOLE": N_HOLE,
                "CHK-RW": 3 * ne + 2,
                "CHK-ENTRY0": 1,
                "CHK-GWCLR0": ne,
                "CHK-MEIP-WR": 2,
                "CHK-SRC0": 3,
            }
        )
        # The drawn values are the ones the firmware wrote (stimulus model).
        rw = [r for r in self.con.records("CHK-RW") if r.kv.get("group") != "mpiccfg"]
        exp = []
        for i, n in enumerate(self.tcfg.entries):
            for g in self.tcfg.gorder:
                exp.append((GROUPS[g], n, self.tcfg.vals[GROUPS[g]][i] & FIELD_MAX[GROUPS[g]]))
        got = [(r.kv.get("group"), int(r.kv.get("src", -1)), r.kv.get("wr")) for r in rw]
        if got != exp:
            raise AssertionError(f"CHK-RW FAIL: firmware cells {got[:6]} != drawn {exp[:6]}")
        holes = [r.kv.get("addr") for r in self.con.records("CHK-HOLE")]
        if holes != self.tcfg.holes:
            raise AssertionError(
                f"CHK-HOLE FAIL: firmware addresses {holes} != drawn {self.tcfg.holes}"
            )
        for name in ("OBS-IDLE-UNSTATED", "OBS-PIC-MEIP-WR"):
            for rec in self.con.records(name):
                self.logger.info("%s", rec.text)
        n_host = self._chk_reset_x(four_state)
        n_host += self._chk_meip_store()
        self.result_pass(TEST, seed, n_fw + n_host)

    def _chk_meip_store(self) -> int:
        """CHK-MEIP-WR-STORE: one PIC write at ``meip[0]`` per CHK-MEIP-WR instance."""
        mine, other = self._meip_stores()
        wrs = [r.kv.get("wr", -1) for r in self.con.records("CHK-MEIP-WR")]
        if len(mine) != 2:
            raise AssertionError(
                f"CHK-MEIP-WR-STORE FAIL: {len(mine)} CHK-MEIP-WR instances in the meip_wr leg, "
                "expected 2"
            )
        for k, (n, o) in enumerate(zip(mine, other)):
            body = (
                f"instance={k} wr=0x{wrs[k] if k < len(wrs) else -1:x} "
                f"pic_writes_meip0={n} expect=1 pic_writes_other={o}(logged) "
                f"offset=0x{MEIP0_OFF:04x}"
            )
            if n != 1:
                raise AssertionError(f"CHK-MEIP-WR-STORE FAIL: {body}")
            self.logger.info("CHK-MEIP-WR-STORE PASS: %s", body)
        return len(mine)
