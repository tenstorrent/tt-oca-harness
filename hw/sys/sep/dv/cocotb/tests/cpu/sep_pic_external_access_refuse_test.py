# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""An external access through the inbound port to any PIC address answers DECERR and changes no PIC register.

Firmware ``pic_external_access_refuse_test`` arms distinct non-zero values in
the PIC (``mpiccfg.priord`` 1; ``meipl`` 7, 9, 11, ``meie`` 1 and
``meigwctrl`` 2 at entries 1, J and 255), holds the edge bit of source 1
pending with the source drive recipe on mailbox 0, and reads the armed state
back. It then asks this test (``REQ regime_a`` / ``REQ regime_b``) to send one
external read and one write to each PIC target through the SMN master: the
first, interior and last register of the six PIC groups, a hole address and a
past-extent address. Regime A has no PIC window (the default block, a
control); regime B has one allow window per NS value over 0xC008_0000 to
0xC008_7FFF, read back by firmware before the accesses. After each regime this
test writes one completion word to the inbound port of mailbox 7, and the
firmware pops it; after regime B the firmware reads the armed state again.

Checks:

* CHK-CPU-READ    (control, firmware) every armed register reads non-zero and
                  ``meip[0]`` bit 1 reads 1 before the external accesses.
* CHK-DECERR      every external read and write to a PIC address answers
                  DECERR in both regimes; in regime B the ``PIC-WINDOW``
                  read-back of both window entries equals the programmed
                  START_ADDR, END_ADDR and FILTER_CONFIG field bits.
* CHK-NO-LEAK     an external read of an armed register does not return the
                  armed value.
* CHK-LANDED      (firmware) after the last access every armed register reads
                  its armed value and ``meip[0]`` bit 1 still reads 1.
* CHK-WINDOW-LIVE (control) the completion word to the open mailbox 7 window
                  answers OKAY in both regimes.
* CHK-WINDOW      the completion of the last PIC access, then the second
                  completion word, then the firmware read-back line.

Every expected value comes from the stimulus (the armed constants of the
contract and the drawn J) or from the RDL field layout; no expected value is
read from the DUT. cpu run mode, ``+skip_fuse_sense``, ``SEP_DBG`` off.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import cocotb
import pyuvm
from cocotb.triggers import RisingEdge
from env.sep_axi_agent import SepAxiAgent, SepAxiOp
from env.sep_axi_monitor import SepAxiMonitor
from env.sep_boot_scoreboard import SepBootScoreboard
from env.sep_decode_resp import sep_map_row
from env.sep_dtcm_param_patch import patch_param_block
from env.sep_fw_console import SepFwConsole, parse_kv
from env.sep_pic_map import EXCLUDED_IDLE_SOURCES, meip_idle_mask_words, meip_words
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from sep_reg_meta import INBOUND_FILTER_CTRL_0, sep_addr_define, sym
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_fabric_csr_bank_seq import (
    F_ALLOW_NS,
    F_ENTRY_ENABLED,
    F_READ_ALLOWED,
    F_WRITE_ALLOWED,
    FILTER_CFG_LO_FIELDS,
)
from seq_lib.sep_mbox_port_ops import RESP_DECERR, RESP_OKAY, SepMboxPortOps, resp_name

_TEST = "sep_pic_external_access_refuse_test"
_DV_ROOT = str(Path(__file__).resolve().parents[3])
_FW_DIR = os.path.join(_DV_ROOT, "fw", "build", "tests", "pic_external_access_refuse_test")
_ITCM_HEX = os.path.join(_FW_DIR, "pic_external_access_refuse_test.itcm.hex")
_DTCM_HEX = os.path.join(_FW_DIR, "pic_external_access_refuse_test.dtcm.hex")
_BANNER = "SEP PIC external access refuse test"
_ICCM_BASE = sym("SEP_ICCM_MEM_BASE_ADDR")
_MAX_RUN_CYCLES = 6_000_000
_NO_BOOT_CYCLES = 80_000

# ---- PIC map (generated register map) ----
MEIPL0 = sym("PIC_MEIPL_0__REG_ADDR")
MEIP0 = sym("PIC_MEIP_0__REG_ADDR")
MEIE0 = sym("PIC_MEIE_0__REG_ADDR")
MPICCFG = sym("PIC_MPICCFG_REG_ADDR")
MEIGWCTRL0 = sym("PIC_MEIGWCTRL_0__REG_ADDR")
MEIGWCLR0 = sym("PIC_MEIGWCLR_0__REG_ADDR")
# Array geometry from the RDL: the per-source arrays share one entry count, and
# every array has a 4-byte stride.
N_ENTRY = sep_addr_define("SEP_TOP_PIC_MEIPL_NUM")
N_MEIP = sep_addr_define("SEP_TOP_PIC_MEIP_NUM")
WORD = sym("PIC_MEIPL_1__REG_ADDR") - MEIPL0
for _arr in ("MEIE", "MEIGWCTRL", "MEIGWCLR"):
    assert sep_addr_define(f"SEP_TOP_PIC_{_arr}_NUM") == N_ENTRY, _arr
for _arr in ("MEIP", "MEIE", "MEIGWCTRL", "MEIGWCLR"):
    assert sym(f"PIC_{_arr}_1__REG_ADDR") - sym(f"PIC_{_arr}_0__REG_ADDR") == WORD, _arr
# The EL2_PIC aperture (generated memory map, EL2_PIC row) starts at the PIC
# base; the registers fill the first PIC_REG_MAP_SIZE bytes.
PIC_BASE = sym("PIC_REG_MAP_BASE_ADDR")
_PIC_ROW = sep_map_row(PIC_BASE)
assert _PIC_ROW.unit == "EL2_PIC" and _PIC_ROW.base == PIC_BASE, _PIC_ROW.unit
PIC_END = _PIC_ROW.end
PIC_OCCUPIED_END = PIC_BASE + sym("PIC_REG_MAP_SIZE")
# Offsets inside the aperture that hold no register (the hole ranges).
HOLE_RANGES = (
    (MEIPL0 + N_ENTRY * WORD, MEIP0),
    (MEIP0 + N_MEIP * WORD, MEIE0),
    (MEIE0 + N_ENTRY * WORD, MPICCFG),
    (MPICCFG + WORD, MEIGWCTRL0),
    (MEIGWCTRL0 + N_ENTRY * WORD, MEIGWCLR0),
)
assert MEIGWCLR0 + N_ENTRY * WORD == PIC_OCCUPIED_END

# Armed values of the contract (firmware step 2) and the edge bit of source 1.
ARM_PRIORD = 1
ARM_PRI = (7, 9, 11)
ARM_MEIE = 1
ARM_GWCTRL = 2
SRC_FIRST, SRC_LAST = 1, 255
INTERIOR_EXCLUDED = set(EXCLUDED_IDLE_SOURCES)

# Inbound windows the firmware programs (keep in step with the firmware).
MBX_COMPLETE = 7
WIN_CFG = F_READ_ALLOWED | F_WRITE_ALLOWED | F_ENTRY_ENABLED
WIN_CFG_NS = (WIN_CFG, WIN_CFG | F_ALLOW_NS)
# Implemented fields of the FILTER_CONFIG upper word (RDL); the firmware writes 0.
FILTER_CFG_HI_FIELDS = INBOUND_FILTER_CTRL_0.mask("FILTER_CONFIG") >> 32
assert FILTER_CFG_HI_FIELDS != 0, "FILTER_CONFIG upper word has no field"
CW_HI = 0x5EC0_C0DE
CW = {"A": 0x0C0D_E0A0, "B": 0x0C0D_E0B0}

# Parameter block layout (fw/tests/pic_external_access_refuse_test, enum P_*).
P_MAGIC_WORD = 0x9C1E0A51
N_TARGETS = 18
ORDER_BITS = 5


@dataclass(frozen=True)
class Target:
    """One PIC target: name, address, armed value (None when nothing is armed).

    ``idle_mask`` holds the excluded idle bits of a ``meip`` word; CHK-NO-LEAK
    compares only the other bits.
    """

    name: str
    addr: int
    armed: int | None
    idle_mask: int = 0

    @property
    def wdata(self) -> int:
        return 0xFFFF_FFFF if self.armed is None else (~self.armed) & 0xFFFF_FFFF


@dataclass(frozen=True)
class RefuseCfg:
    """The seeded stimulus. A pure function of the run seed."""

    seed: int
    j: int
    meip_w: int
    hole: int
    past: int
    order: tuple[int, ...]
    rw_first: int

    @classmethod
    def from_seed(cls, seed: int) -> "RefuseCfg":
        rng = SepSeededRng(seed)
        j = rng.choice([e for e in range(2, 255) if e not in INTERIOR_EXCLUDED])
        meip_w = rng.randrange(1, 7)
        lo, hi = rng.choice(HOLE_RANGES)
        hole = lo + WORD * rng.randrange(0, (hi - lo) // WORD)
        past = PIC_OCCUPIED_END + WORD * rng.randrange(0, (PIC_END + 1 - PIC_OCCUPIED_END) // WORD)
        order = list(range(N_TARGETS))
        rng.shuffle(order)
        rw_first = rng.getrandbits(N_TARGETS)
        return cls(seed, j, meip_w, hole, past, tuple(order), rw_first)

    def targets(self) -> list[Target]:
        j, w = self.j, self.meip_w
        meip0_armed = meip_words([SRC_FIRST])[0]
        t = [
            Target("meipl1", MEIPL0 + WORD * SRC_FIRST, ARM_PRI[0]),
            Target(f"meipl{j}", MEIPL0 + WORD * j, ARM_PRI[1]),
            Target("meipl255", MEIPL0 + WORD * SRC_LAST, ARM_PRI[2]),
            Target("meip0", MEIP0, meip0_armed, meip_idle_mask_words()[0]),
            Target(f"meip{w}", MEIP0 + WORD * w, None),
            Target("meip7", MEIP0 + WORD * (N_MEIP - 1), None),
            Target("meie1", MEIE0 + WORD * SRC_FIRST, ARM_MEIE),
            Target(f"meie{j}", MEIE0 + WORD * j, ARM_MEIE),
            Target("meie255", MEIE0 + WORD * SRC_LAST, ARM_MEIE),
            Target("mpiccfg", MPICCFG, ARM_PRIORD),
            Target("meigwctrl1", MEIGWCTRL0 + WORD * SRC_FIRST, ARM_GWCTRL),
            Target(f"meigwctrl{j}", MEIGWCTRL0 + WORD * j, ARM_GWCTRL),
            Target("meigwctrl255", MEIGWCTRL0 + WORD * SRC_LAST, ARM_GWCTRL),
            Target("meigwclr1", MEIGWCLR0 + WORD * SRC_FIRST, None),
            Target(f"meigwclr{j}", MEIGWCLR0 + WORD * j, None),
            Target("meigwclr255", MEIGWCLR0 + WORD * SRC_LAST, None),
            Target("hole", self.hole, None),
            Target("past_extent", self.past, None),
        ]
        assert len(t) == N_TARGETS
        return t

    def accesses(self) -> list[tuple[Target, SepAxiOp]]:
        """The drawn access order: each target, its read and its write."""
        tg = self.targets()
        out = []
        for k in self.order:
            ops = (SepAxiOp.WRITE, SepAxiOp.READ)
            if not (self.rw_first >> k) & 1:
                ops = (SepAxiOp.READ, SepAxiOp.WRITE)
            out += [(tg[k], op) for op in ops]
        return out

    def words(self) -> list[int]:
        packed = [0, 0, 0]
        for i, k in enumerate(self.order):
            packed[i // 6] |= k << (ORDER_BITS * (i % 6))
        return [
            P_MAGIC_WORD,
            self.seed & 0xFFFF_FFFF,
            self.j,
            self.meip_w,
            self.hole,
            self.past,
            *packed,
            self.rw_first,
            meip_idle_mask_words()[0],
            CW["A"],
            CW["B"],
            PIC_END,
        ]


@dataclass
class Access:
    regime: str
    target: Target
    op: str
    resp: int
    rdata: int
    clk: int


@pyuvm.test()
class sep_pic_external_access_refuse_test(sep_base_test):
    """External reads and writes to every PIC target answer DECERR and land nowhere."""

    required_evidence = (
        "CHK-CPU-READ",
        "CHK-DECERR",
        "CHK-NO-LEAK",
        "CHK-LANDED",
        "CHK-WINDOW-LIVE",
        "CHK-WINDOW",
        "CHK-FW-IDENTITY",
        "CHK-FW-CONSOLE",
    )

    # The CPU owns the CPU-LSU port; only the SMN master is a testbench master.
    build_env = False

    def build_phase(self) -> None:
        super().build_phase()
        self.sb = SepBootScoreboard("sb", self)
        self.ext_agent = SepAxiAgent("ext_axi_agent", self)
        self.ext_agent.axi_prefix = "m_axi"
        # The agent requires the monitor of its bus. Refused SMN accesses
        # answer DECERR by contract, so the monitor tallies DECERR without
        # failing, as sep_env configures it for this bus.
        self.ext_monitor = SepAxiMonitor("ext_axi_monitor", self)
        self.ext_monitor.bus_prefix = "m_axi"
        self.ext_monitor.fail_decerr = False

    async def start_ext_seq(self, seq) -> None:
        await seq.start(self.ext_agent.sequencer)

    # ---- stimulus ----
    async def _ext(self, op: SepAxiOp, addr: int, wdata: int = 0) -> tuple[int, int]:
        kw: dict = {"op": op, "addr": addr, "length": 4, "size": 2, "prot": 0, "user": 0}
        if op is SepAxiOp.READ:
            kw["allow_ungraded_read_resp"] = True
        else:
            kw["wdata"] = wdata
            kw["allow_unverified_write_resp"] = True
        seq = SepAxiAccessSeq("pic_ext", **kw)
        await self.start_ext_seq(seq)
        return seq.resp_code, seq.rdata & 0xFFFF_FFFF

    def _regime(self, regime: str):
        async def handler(_kv: dict) -> None:
            try:
                await RisingEdge(self.dut.clk_i)
                for tgt, op in self.rc.accesses():
                    resp, rdata = await self._ext(op, tgt.addr, tgt.wdata)
                    self.acc.append(
                        Access(
                            regime,
                            tgt,
                            "wr" if op is SepAxiOp.WRITE else "rd",
                            resp,
                            rdata,
                            self.con.clk,
                        )
                    )
                last = self.acc[-1]
                self.logger.info(
                    "PIC-EXT-DONE LOG regime=%s last_op=%s addr=0x%08x resp=%s clk=%d",
                    regime,
                    last.op,
                    last.target.addr,
                    resp_name(last.resp),
                    last.clk,
                )
                self.ext_done[regime] = last.clk
                resp = await self.mbx7.push("in", (CW_HI << 32) | CW[regime])
                self.cw[regime] = (resp, self.con.clk)
                self.logger.info(
                    "PIC-COMPLETION-WORD LOG regime=%s resp=%s clk=%d",
                    regime,
                    resp_name(resp),
                    self.con.clk,
                )
            except Exception as exc:  # graded after the firmware ends
                self.handler_err.append(f"regime {regime}: {exc!r}")
                raise

        return handler

    # ---- grading ----
    def _fw_line(self, prefix: str) -> tuple[int, dict]:
        hits = [(c, t) for c, t in self.con.lines if t.startswith(prefix)]
        assert len(hits) == 1, f"expected one '{prefix}' console line, got {len(hits)}"
        return hits[0][0], parse_kv(hits[0][1])

    def _windows_match(self) -> int:
        lines = [parse_kv(t) for _, t in self.con.lines if t.startswith("PIC-WINDOW")]
        assert len(lines) == 2, f"expected two PIC-WINDOW lines, got {len(lines)}"
        ok = 1
        for kv in lines:
            ns = int(kv["ns"])
            cfg = kv["FILTER_CONFIG"]
            want = WIN_CFG_NS[ns]
            match = (
                (cfg & FILTER_CFG_LO_FIELDS) == (want & FILTER_CFG_LO_FIELDS)
                and kv["START_ADDR"] == PIC_BASE
                and kv["END_ADDR"] == PIC_END
                and (kv["cfg_hi"] & FILTER_CFG_HI_FIELDS) == 0
                and kv["start_hi"] == 0
                and kv["end_hi"] == 0
            )
            self.logger.info(
                "PIC-WINDOW LOG ns=%d FILTER_CONFIG=0x%08x want=0x%08x field_mask=0x%08x rsvd=0x%08x "
                "cfg_hi=0x%08x cfg_hi_mask=0x%08x START_ADDR=0x%08x END_ADDR=0x%08x start_hi=0x%x "
                "end_hi=0x%x match=%d",
                ns,
                cfg,
                want,
                FILTER_CFG_LO_FIELDS,
                cfg & ~FILTER_CFG_LO_FIELDS & 0xFFFF_FFFF,
                kv["cfg_hi"],
                FILTER_CFG_HI_FIELDS,
                kv["START_ADDR"],
                kv["END_ADDR"],
                kv["start_hi"],
                kv["end_hi"],
                int(match),
            )
            ok &= int(match)
        return ok

    def _grade(self) -> None:
        seed = self.rc.seed
        _, prm = self._fw_line("PARAMS")
        want = self.rc.words()
        got = [
            prm["j"],
            prm["meip_w"],
            prm["hole"],
            prm["past"],
            prm["o0"],
            prm["o1"],
            prm["o2"],
            prm["rw"],
        ]
        assert got == want[2:10], f"firmware ran params {got}, patched {want[2:10]}"
        assert prm["pic_end"] == PIC_END, f"firmware ran pic_end 0x{prm['pic_end']:08x}"

        win_ok = self._windows_match()
        n_acc = len(self.rc.accesses())
        for regime in ("A", "B"):
            acc = [a for a in self.acc if a.regime == regime]
            assert len(acc) == n_acc, f"regime {regime}: {len(acc)} accesses, expected {n_acc}"
            for a in acc:
                ok = a.resp == RESP_DECERR and (regime == "A" or win_ok == 1)
                line = (
                    f"seed={seed} regime={regime} target={a.target.name} op={a.op} addr=0x{a.target.addr:08x} "
                    f"resp={resp_name(a.resp)} window_entries_match={win_ok if regime == 'B' else 'na'}"
                )
                assert ok, f"CHK-DECERR FAIL {line}"
                self.logger.info("CHK-DECERR PASS %s", line)
            for a in acc:
                if a.op != "rd" or a.target.armed is None:
                    continue
                keep = ~a.target.idle_mask & 0xFFFF_FFFF
                line = (
                    f"seed={seed} regime={regime} addr=0x{a.target.addr:08x} target={a.target.name} "
                    f"armed=0x{a.target.armed & keep:x} ext_read=0x{a.rdata & keep:08x} "
                    f"idle_mask=0x{a.target.idle_mask:08x} idle_bits=0x{a.rdata & a.target.idle_mask:08x}"
                )
                if a.target.idle_mask:
                    srcs = " ".join(
                        f"src{src}={(a.rdata >> (src % 32)) & 1}"
                        for src in EXCLUDED_IDLE_SOURCES
                        if (a.target.idle_mask >> (src % 32)) & 1 and src < 32
                    )
                    self.logger.info(
                        "OBS-IDLE-UNSTATED LOG regime=%s target=%s %s", regime, a.target.name, srcs
                    )
                assert (a.rdata & keep) != (a.target.armed & keep), f"CHK-NO-LEAK FAIL {line}"
                self.logger.info("CHK-NO-LEAK PASS %s", line)
            resp, clk = self.cw[regime]
            assert resp == RESP_OKAY, (
                f"CHK-WINDOW-LIVE FAIL regime={regime} mailbox_resp={resp_name(resp)}"
            )
            pops = [parse_kv(t) for _, t in self.con.lines if t.startswith("PIC-COMPLETE")]
            pop = [p for p in pops if p.get("r") == regime]
            assert pop and pop[0]["word"] == CW[regime], (
                f"CHK-WINDOW-LIVE FAIL regime={regime}: firmware popped {pop} from mailbox 7, "
                f"expected word 0x{CW[regime]:08x}"
            )
            self.logger.info(
                "CHK-WINDOW-LIVE PASS seed=%d regime=%s mailbox_resp=OKAY fw_popped=0x%08x clk=%d",
                seed,
                regime,
                pop[0]["word"],
                clk,
            )

        rb_clk, _ = self._fw_line("PIC-LANDED")
        t_ext, t_cw = self.ext_done["B"], self.cw["B"][1]
        ok = t_ext <= t_cw < rb_clk
        line = f"ext_done_clk={t_ext} completion_clk={t_cw} readback_clk={rb_clk}"
        assert ok, f"CHK-WINDOW FAIL ext_done_before_readback=0 {line}"
        self.logger.info("CHK-WINDOW PASS seed=%d ext_done_before_readback=1 %s", seed, line)

    # ---- scenario ----
    async def run_scenario(self) -> None:
        self.dut = cocotb.top
        self.rc = RefuseCfg.from_seed(self.random_seed())
        c = self.rc
        self.logger.info("SEED seed=%d", c.seed)
        self.logger.info("DRAW j=%d", c.j)
        self.logger.info("DRAW meip_word=%d", c.meip_w)
        self.logger.info("DRAW hole=0x%08x", c.hole)
        self.logger.info("DRAW past_extent=0x%08x", c.past)
        self.logger.info("DRAW order=%s", ",".join(c.targets()[k].name for k in c.order))
        self.logger.info("DRAW rw_first=0x%05x", c.rw_first)
        patched = os.path.join(os.getcwd(), "sep_dtcm_pic_refuse.hex")
        patch_param_block(_DTCM_HEX, patched, P_MAGIC_WORD, c.words())

        self.acc: list[Access] = []
        self.ext_done: dict[str, int] = {}
        self.cw: dict[str, tuple[int, int]] = {}
        self.handler_err: list[str] = []
        self.mbx7 = SepMboxPortOps(self, MBX_COMPLETE, in_prot1=0, in_user=0)
        self.sb.expected_line = _BANNER
        self.con = SepFwConsole(self, graded_test=_TEST).start()
        self.con.on_request("regime_a", self._regime("A"))
        self.con.on_request("regime_b", self._regime("B"))
        try:
            await self.boot_firmware(
                self.sb,
                _ITCM_HEX,
                patched,
                rst_vec=_ICCM_BASE >> 1,
                max_run_cycles=_MAX_RUN_CYCLES,
                no_boot_cycles=_NO_BOOT_CYCLES,
            )
        finally:
            await self.con.stop()
        assert not self.handler_err, "host regime handler failed: " + "; ".join(self.handler_err)
        assert self.sb.fw_done and self.sb.fw_pass, "firmware did not complete with PASS"
        self.con.relay_chk()
        self.con.require_counts({"CHK-CPU-READ": 1, "CHK-LANDED": 1})
        self._grade()
        self.logger.info("RESULT %s seed=%d PASS checks=%d", _TEST, c.seed, 6)
