# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Inbound filter default block, enable lifecycle, simultaneous ports, denial floods, reconfig.

Contract SMC_FILTER_19, anchor smc_infilt_default_liveness_test.
Allocated scenarios: INFILT-DEFAULT-BLOCK.S1-S3, INFILT-SYS-REG-ACCESS.S1, S3, S4,
INFILT-PRIORITY-PERM.S6, INFILT-DENY-RESPONSE.S4, S5.
Spec sources: fabric.adoc Filtering and Protection, axi_filter index.adoc Match Then Permit and
Blocked Transactions, filter_ctrl.rdl FILTER_CONFIG.

Inbound entries 1..4 are programmed over SEP_IN while SYS_IN traffic runs against the reset
default, non-matching entries, an admitting entry, a denying entry of lower index, a flood of
denied writes and a reconfiguration under load. Entry 0 and every lock stay untouched.
"""

from __future__ import annotations

import sys

import cocotb
from cocotb.triggers import ReadOnly, RisingEdge, SimTimeoutError, with_timeout
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiGroupItem, SmcSysAxiItem, SmcSysAxiOp
from ocah_axi_vip import AxiTimingProfile

from ._one_shot import _OneShot
from .smc_addr_map import _REPO, smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq

_SMC_REG_PY = _REPO / "hw" / "sys" / "smc" / "regs" / "gen" / "py"
if str(_SMC_REG_PY) not in sys.path:
    sys.path.insert(0, str(_SMC_REG_PY))

from smc_reg import CHIP_CONFIG_VERSION_LO_REG_DEFAULT  # noqa: E402

# Contract words; a read-back adds data_bus_width 3.
_PERMIT_B1 = 0x0000_0000_0100_0013
_PERMIT_NS1 = 0x0000_0000_0100_0113
_DENY_B1 = 0x0000_0000_0100_0010
_DISABLED_B1 = 0x0000_0000_0100_0003
_NO_WRITE_B1 = 0x0000_0000_0100_0011
_READBACK_BITS = 0x3000
_RESET_CFG = 0x3000
_RESET_START = 0
_RESET_END = 7
_WIN_START = 0xC000_0000
_WIN_END = 0xC0FF_FFFF
_OTHER_START = 0x0200_0000
_OTHER_END = 0x0200_0FFF
_VERSION_LO = smc_addr("SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_VERSION_LO_BASE_ADDR")
_PAGE_A = smc_addr("SMC_TOP_SPM_MEMORY_BASE_ADDR") + 0x1_0000
_PAGE_D = smc_addr("SMC_TOP_SPM_MEMORY_BASE_ADDR") + 0x2_0000
_PAGE_BYTES = 0x1000
_DECERR = 3
_AXI_BOUND_NS = 50_000
_FUSE_BOUND = 200_000
_HOLD = AxiTimingProfile(b_ready_delay=64)
_FLOOD_WRITES = 40
_FLOOD_WORDS = 8
_RECONFIG_WRITES = 12
_RECONFIG_BASE = 0x100
_SYS_ACCESSES = 74
_STEPS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9")
_TERMS = (
    "RESET_BLOCKED",
    "UNMATCHED_BLOCKED",
    "BRINGUP_ADMIT",
    "DISABLE_BLOCK",
    "SIMULTANEOUS",
    "DENY_ADMIT_GROUP",
    "FLOOD",
    "RECONFIG",
)
_CHECKERS = (
    ("CHK-INB-RESET-BLOCKS-SYS-IN", "S2"),
    ("CHK-INB-UNMATCHED-STAYS-BLOCKED", "S3"),
    ("CHK-INB-SEP-NOT-FILTERED", "S2"),
    ("CHK-INB-READ-FILTER-CONFIG", "S4"),
    ("CHK-INB-ENABLE-LIFECYCLE", "S4"),
    ("CHK-INB-SIMULTANEOUS-PORTS", "S5"),
    ("CHK-INB-ADMIT-AFTER-DENY", "S6"),
    ("CHK-INB-DENY-FLOOD", "S7"),
    ("CHK-INB-RECONFIG-OUTSTANDING", "S8"),
)


def _scratch(index: int) -> int:
    return smc_indexed_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_SCRATCH_BASE_ADDR", index)


def _reg(reg: str, entry: int) -> int:
    return smc_indexed_addr(f"SMC_TOP_SMC_INBOUND_FILTER_CTRL_{reg}_BASE_ADDR", entry)


def _scratch_seed(index: int) -> int:
    return 0xC01D_0000 | (index << 8) | index


def _a_seed(k: int) -> int:
    return 0xA0A0_0000_0000_0000 | (k << 16) | 0x1111


def _d_seed(k: int) -> int:
    return 0xD0D0_0000_0000_0000 | (k << 16) | 0x2222


def _r_seed(i: int) -> int:
    return 0xBA5E_0000_0000_0000 | (i << 8) | 0x55


def _r_new(i: int) -> int:
    return 0x8E70_0000_0000_0000 | (i << 8) | 0xAA


class _SysWatch:
    """Samples the inbound hit and isolate probes and the sys_axi write handshakes.

    The filter probes show a request's decision on the clk_smc_i sample after the one that
    first shows its valid high, so a hit or isolate sample counts when the same channel's valid
    was high at the previous sample.
    """

    def __init__(self, dut) -> None:
        self.dut = dut
        self.aw = 0
        self.b = 0
        self.unresolved = 0
        self.peak = 0
        self._aw0 = 0
        self._b0 = 0
        self.clear()

    def clear(self) -> None:
        self.read = {"hit": 0, "isolate": 0, "cycles": 0}
        self.write = {"hit": 0, "isolate": 0, "cycles": 0}

    def mark(self) -> None:
        self._aw0, self._b0, self.peak = self.aw, self.b, 0

    @property
    def aw_since_mark(self) -> int:
        return self.aw - self._aw0

    @property
    def b_since_mark(self) -> int:
        return self.b - self._b0

    async def run(self) -> None:
        dut = self.dut
        prev = {"read": 0, "write": 0}
        while True:
            await RisingEdge(dut.clk_smc_i)
            await ReadOnly()
            hs = (dut.sys_axi_awvalid, dut.sys_axi_awready, dut.sys_axi_bvalid, dut.sys_axi_bready)
            if all(s.value.is_resolvable for s in hs):
                self.aw += int(hs[0].value) & int(hs[1].value)
                self.b += int(hs[2].value) & int(hs[3].value)
                self.peak = max(self.peak, self.aw_since_mark - self.b_since_mark)
            else:
                self.unresolved += 1
            for name, acc, valid, hit, iso in (
                (
                    "read",
                    self.read,
                    dut.sys_axi_arvalid,
                    dut.tb_inb_read_hit,
                    dut.tb_inb_isolate_read,
                ),
                (
                    "write",
                    self.write,
                    dut.sys_axi_awvalid,
                    dut.tb_inb_write_hit,
                    dut.tb_inb_isolate_write,
                ),
            ):
                if not (
                    valid.value.is_resolvable
                    and hit.value.is_resolvable
                    and iso.value.is_resolvable
                ):
                    self.unresolved += 1
                    continue
                if prev[name]:
                    acc["hit"] |= int(hit.value)
                    acc["isolate"] |= int(iso.value)
                    acc["cycles"] += 1
                prev[name] = int(valid.value)


class smc_infilt_default_liveness_test_seq(SmcCsrSeq):
    """Program inbound entries 1..4 over SEP_IN and drive SYS_IN traffic against them."""

    def __init__(self, name: str = "smc_infilt_default_liveness_test_seq") -> None:
        super().__init__(name)
        self.sys_accesses = 0
        self._stamps: list[tuple[str, int]] = []
        self._term_stamps: list[tuple[str, int]] = []
        self._chk_marks: list[tuple[str, int]] = []
        self._waits: list[str] = []
        self._watch: _SysWatch | None = None
        self._blocked: list[tuple[str, dict, int | None]] = []
        self._deferred: list[tuple[str, str]] = []

    def _mark_step(self, step_id: str) -> None:
        self._stamps.append((step_id, int(get_sim_time("ps"))))

    def _mark_term(self, term: str) -> None:
        self._term_stamps.append((term, int(get_sim_time("ps"))))

    def _log_chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self._chk_marks.append((chk_id, int(get_sim_time("ps"))))

    def _defer_chk(self, chk_id: str, text: str) -> None:
        self._deferred.append((chk_id, text))

    def _flush_chk(self) -> None:
        for chk_id, text in self._deferred:
            self._log_chk(chk_id, text)
        self._deferred = []

    @staticmethod
    def _probe(sig) -> int:
        assert sig.value.is_resolvable, f"{sig._name} is X/Z ({sig.value})"
        return int(sig.value)

    @staticmethod
    def _item(
        tag: str,
        op: SmcSysAxiOp,
        addr: int,
        *,
        length: int = 8,
        wdata: int = 0,
        expected: int | None = None,
        refused: bool = False,
        tolerate: bool = False,
    ) -> SmcSysAxiItem:
        item = SmcSysAxiItem(f"sys_in_{tag}")
        item.op = op
        item.addr = addr
        item.length = length
        item.wdata = wdata
        item.prot = 0
        if refused:
            item.allow_error = True
            item.expect_error = True
            item.expected_resp = _DECERR
        elif tolerate:
            item.allow_error = True
        else:
            item.expected = expected
        return item

    async def _sys_one(self, item: SmcSysAxiItem, *, defer: bool = False) -> dict:
        """One SYS_IN access; returns the hit and isolate sample of its own channel."""
        self._watch.clear()
        await _OneShot(item, f"{item.get_name()}_os").start(self.env.sys_in_axi_agent.sequencer)
        self.sys_accesses += 1
        assert self._watch.unresolved == 0, f"{item.get_name()}: X/Z on a SYS_IN or filter probe"
        chan = dict(self._watch.read if item.op == SmcSysAxiOp.READ else self._watch.write)
        assert chan["cycles"] > 0, f"{item.get_name()}: no valid cycle sampled"
        if item.expect_error:
            assert item.resp_code == _DECERR, f"{item.get_name()}: resp {item.resp_code}, want 3"
        elif not item.allow_error:
            assert item.resp_code == 0, f"{item.get_name()}: resp {item.resp_code}, want OKAY"
        return chan

    async def _blocked_access(
        self, tag: str, op: SmcSysAxiOp, addr: int, length: int, *, wdata: int = 0, iso=None
    ) -> str:
        item = self._item(tag, op, addr, length=length, wdata=wdata, refused=True)
        chan = await self._sys_one(item)
        self._blocked.append((tag, chan, iso))
        return f"{tag} resp {item.resp_code} hit 0x{chan['hit']:x} isolate {chan['isolate']}"

    def _grade_blocked(self) -> None:
        """Grade the all-zero hit readings once an admitted access has set its entry's bit."""
        for tag, chan, iso in self._blocked:
            assert chan["hit"] == 0, f"{tag}: hit vector 0x{chan['hit']:x}, want 0"
            if iso is not None:
                assert chan["isolate"] == iso, f"{tag}: isolate {chan['isolate']}, want {iso}"
        self._blocked = []

    async def _admitted(
        self, tag: str, op: SmcSysAxiOp, addr: int, length: int, *, wdata=0, expected=None, bit=2
    ) -> str:
        item = self._item(tag, op, addr, length=length, wdata=wdata, expected=expected)
        chan = await self._sys_one(item)
        assert chan["hit"] == 1 << bit, (
            f"{tag}: hit vector 0x{chan['hit']:x}, want 0x{1 << bit:x}; isolate {chan['isolate']}"
        )
        if op == SmcSysAxiOp.READ and expected is not None:
            assert item.rdata == expected, f"{tag}: rdata 0x{item.rdata:x}, want 0x{expected:x}"
        return f"{tag} OKAY hit 0x{chan['hit']:x} isolate {chan['isolate']}"

    async def _run_group(
        self, label: str, items: list[SmcSysAxiItem], bound_ns: int, timing=None, rec=None
    ) -> None:
        group = SmcSysAxiGroupItem(label, items, timing=timing)
        seq = self.env.sys_in_axi_agent.sequencer
        if rec is not None:
            rec["start"] = int(get_sim_time("ps"))
        await _OneShot(group, f"{label}_os").start(seq)
        if rec is not None:
            rec["end"] = int(get_sim_time("ps"))
        self.sys_accesses += len(items)

    async def _join(self, label: str, task, bound_ns: int) -> None:
        t0 = int(get_sim_time("ns"))
        try:
            await with_timeout(task, bound_ns, "ns")
        except SimTimeoutError as exc:
            raise AssertionError(
                f"{label}: group not finished within {bound_ns} ns (SYS_IN accesses completed "
                f"{self.sys_accesses}, AW {self._watch.aw} B {self._watch.b})"
            ) from exc
        elapsed = int(get_sim_time("ns")) - t0
        self._waits.append(f"{label} join bound {bound_ns} ns last elapsed {elapsed} ns")

    async def _group(self, label: str, items, bound_ns: int, timing=None) -> None:
        task = cocotb.start_soon(self._run_group(label, items, bound_ns, timing))
        await self._join(label, task, bound_ns)

    async def _program(
        self, entry: int, word: int, start: int | None = None, end: int | None = None
    ) -> None:
        """Write FILTER_CONFIG first so its allow_burst governs the range writes."""
        await self.csr_write(f"IB{entry}_CFG", _reg("FILTER_CONFIG", entry), word, length=8)
        await self.csr_read(
            f"IB{entry}_CFG_RB",
            _reg("FILTER_CONFIG", entry),
            expected=word | _READBACK_BITS,
            length=8,
        )
        if start is not None:
            await self.csr_write(f"IB{entry}_START", _reg("START_ADDR", entry), start, length=8)
            await self.csr_write(f"IB{entry}_END", _reg("END_ADDR", entry), end, length=8)

    async def body(self) -> None:
        await self.wait_fuse_sense_done()
        top = cocotb.top
        fuse = [
            self._probe(s)
            for s in (top.tb_fuse_sense_done, top.tb_fuse_reset_n, top.tb_rst_warm_smc_clk_n)
        ]
        self._waits.append(
            f"tb_fuse_sense_done bound {_FUSE_BOUND} clk_smc_i last {fuse[0]}; tb_fuse_reset_n "
            f"bound {_FUSE_BOUND} last {fuse[1]}; tb_rst_warm_smc_clk_n bound {_FUSE_BOUND} "
            f"last {fuse[2]}"
        )
        self._watch = _SysWatch(top)
        watcher = cocotb.start_soon(self._watch.run())
        rd, wr = SmcSysAxiOp.READ, SmcSysAxiOp.WRITE

        # S1: entries 1..4 start disabled; scratch registers and page words are seeded.
        for entry in (1, 2, 3, 4):
            cfg = await self.csr_read(f"IB{entry}_QUIET", _reg("FILTER_CONFIG", entry), length=8)
            assert not cfg & 0x10, f"inbound entry {entry} enabled at reset: 0x{cfg:x}"
        for i in range(1, 7):
            await self.csr_write(f"SEED_SCR{i}", _scratch(i), _scratch_seed(i))
        for k in range(4):
            await self.csr_write(f"SEED_A{k}", _PAGE_A + 8 * k, _a_seed(k), length=8)
        for i in range(_RECONFIG_WRITES):
            await self.csr_write(
                f"SEED_R{i}", _PAGE_A + _RECONFIG_BASE + 8 * i, _r_seed(i), length=8
            )
        for k in range(_FLOOD_WORDS):
            await self.csr_write(f"SEED_D{k}", _PAGE_D + 8 * k, _d_seed(k), length=8)
        self._mark_step("S1")

        # S2: nothing programmed; SYS_IN is refused while SEP_IN is not filtered.
        s2_rd = await self._blocked_access("S2_RD_VERSION", rd, _VERSION_LO, 4, iso=1)
        s2_wr = await self._blocked_access(
            "S2_WR_SCR1", wr, _scratch(1), 4, wdata=0x5A5A_1111, iso=None
        )
        sep_scr = await self.csr_read("S2_SEP_SCR1", _scratch(1), expected=_scratch_seed(1))
        sep_ver = await self.csr_read(
            "S2_SEP_VERSION", _VERSION_LO, expected=CHIP_CONFIG_VERSION_LO_REG_DEFAULT
        )
        self._mark_step("S2")
        self._mark_term("RESET_BLOCKED")

        # S3: an enabled entry elsewhere and an allow_ns mismatch leave SYS_IN blocked.
        await self._program(3, _PERMIT_B1, _OTHER_START, _OTHER_END)
        await self._program(4, _PERMIT_NS1, _WIN_START, _WIN_END)
        s3_rd = await self._blocked_access("S3_RD_VERSION", rd, _VERSION_LO, 4)
        s3_wr = await self._blocked_access("S3_WR_SCR1", wr, _scratch(1), 4, wdata=0x5A5A_1111)
        self._mark_step("S3")
        self._mark_term("UNMATCHED_BLOCKED")

        # S4: entry 2 admits, then is disabled again.
        await self.csr_write("IB3_OFF", _reg("FILTER_CONFIG", 3), 0, length=8)
        await self.csr_read("IB3_OFF_RB", _reg("FILTER_CONFIG", 3), _RESET_CFG, length=8)
        await self.csr_write("IB4_OFF", _reg("FILTER_CONFIG", 4), 0, length=8)
        await self.csr_read("IB4_OFF_RB", _reg("FILTER_CONFIG", 4), _RESET_CFG, length=8)
        await self._program(2, _PERMIT_B1, _WIN_START, _WIN_END)
        set_leg = "SEP_IN write of PERMIT_WIN_B1 to entry 2 answered OKAY and read back"
        s4_cfg = await self._admitted(
            "S4_RD_ENTRY7_CFG",
            rd,
            _reg("FILTER_CONFIG", 7),
            8,
            expected=_RESET_CFG,
        )
        self._grade_blocked()
        self._defer_chk(
            "CHK-INB-RESET-BLOCKS-SYS-IN",
            f"at reset the SYS_IN read of VERSION_LO ({s2_rd}) and write to SCRATCH_COLD_1 "
            f"({s2_wr}) answer DECERR; SCRATCH_COLD_1 still reads 0x{sep_scr:08X} over SEP_IN; "
            "hit vector 0 and isolate 1 during the read, graded after the first admitted "
            "access set its entry's bit",
        )
        self._defer_chk(
            "CHK-INB-UNMATCHED-STAYS-BLOCKED",
            f"with entry 3 enabled over 0x{_OTHER_START:x}..0x{_OTHER_END:x} and entry 4 "
            f"enabled with allow_ns over the window, SYS_IN read ({s3_rd}) and write ({s3_wr}) "
            "answer DECERR with no hit bit set",
        )
        self._defer_chk(
            "CHK-INB-SEP-NOT-FILTERED",
            f"while every SYS_IN access answered DECERR, SEP_IN read VERSION_LO 0x{sep_ver:08X} "
            f"(generated reset) and SCRATCH_COLD_1 0x{sep_scr:08X} (seeded word), both OKAY",
        )
        self._mark_term("BRINGUP_ADMIT")
        self._defer_chk(
            "CHK-INB-READ-FILTER-CONFIG",
            f"once entry 2 admits, the SYS_IN 8-byte read of entry 7 FILTER_CONFIG returns "
            f"0x{_RESET_CFG:016X} with OKAY: {s4_cfg}",
        )
        cocotb.log.info("LIFECYCLE CHK-INB-ENABLE-LIFECYCLE set: %s", set_leg)
        s4_wr = await self._admitted("S4_WR_SCR2", wr, _scratch(2), 4, wdata=0x5A5A_2222)
        s4_rb = await self._admitted("S4_RD_SCR2", rd, _scratch(2), 4, expected=0x5A5A_2222)
        cocotb.log.info(
            "LIFECYCLE CHK-INB-ENABLE-LIFECYCLE observed: %s; %s; hit vector bit 2 set",
            s4_wr,
            s4_rb,
        )
        await self.csr_write("S4_SCR2_SEED", _scratch(2), _scratch_seed(2))
        await self.csr_write("IB2_DISABLE", _reg("FILTER_CONFIG", 2), _DISABLED_B1, length=8)
        await self.csr_read(
            "IB2_DISABLE_RB",
            _reg("FILTER_CONFIG", 2),
            expected=_DISABLED_B1 | _READBACK_BITS,
            length=8,
        )
        cocotb.log.info(
            "LIFECYCLE CHK-INB-ENABLE-LIFECYCLE cleared: SEP_IN write of DISABLED_B1 to entry 2 "
            "answered OKAY and read back"
        )
        s4_off = await self._blocked_access("S4_RD_VERSION_OFF", rd, _VERSION_LO, 4)
        self._grade_blocked()
        cocotb.log.info(
            "LIFECYCLE CHK-INB-ENABLE-LIFECYCLE checked_cleared: SYS_IN read of VERSION_LO "
            "answers DECERR with the hit vector 0: %s",
            s4_off,
        )
        self._mark_step("S4")
        self._mark_term("DISABLE_BLOCK")
        self._defer_chk(
            "CHK-INB-ENABLE-LIFECYCLE",
            "SYS_IN blocked before programming (DECERR), admitted after entry 2 was enabled "
            f"over SEP_IN (scratch round trip 0x5A5A2222 exact, hit bit 2) and blocked again "
            f"after entry_enabled was cleared ({s4_off})",
        )

        self._flush_chk()

        # S5: a SYS_IN read group and a SEP_IN sequence run at the same time.
        await self._program(2, _PERMIT_B1)
        sys_rec: dict = {}
        group_items = [
            self._item(f"S5_RD_SCR{i}_{rep}", rd, _scratch(i), length=4, expected=_scratch_seed(i))
            for rep in range(2)
            for i in range(1, 5)
        ]
        task = cocotb.start_soon(
            self._run_group("sys_in_read_group", group_items, _AXI_BOUND_NS, rec=sys_rec)
        )
        sep_start = int(get_sim_time("ps"))
        w5 = (0x5E50_0005, 0x5E50_0105)
        w6 = (0x5E60_0006, 0x5E60_0106)
        for n in range(2):
            await self.csr_write(f"S5_WR_SCR5_{n}", _scratch(5), w5[n])
            await self.csr_write(f"S5_WR_SCR6_{n}", _scratch(6), w6[n])
        for n in range(2):
            await self.csr_read(f"S5_RD_SCR5_{n}", _scratch(5), expected=w5[1])
            await self.csr_read(f"S5_RD_SCR6_{n}", _scratch(6), expected=w6[1])
        sep_end = int(get_sim_time("ps"))
        await self._join("S5 SYS_IN read group", task, _AXI_BOUND_NS)
        assert sys_rec["start"] < sep_end and sep_start < sys_rec["end"], (
            f"S5 SYS_IN group {sys_rec} and SEP_IN sequence [{sep_start}, {sep_end}] ps "
            "did not overlap"
        )
        assert sep_end - sep_start <= _AXI_BOUND_NS * 1000, "S5 SEP_IN sequence beyond 50 us"
        assert all(it.resp_code == 0 for it in group_items), "S5 SYS_IN read not OKAY"
        self._mark_step("S5")
        self._mark_term("SIMULTANEOUS")
        self._log_chk(
            "CHK-INB-SIMULTANEOUS-PORTS",
            f"8 SYS_IN reads of SCRATCH_COLD_1..4 (seeded words) in [{sys_rec['start']}, "
            f"{sys_rec['end']}] ps and 8 SEP_IN accesses in [{sep_start}, {sep_end}] ps overlap; "
            f"all 16 OKAY with exact data inside the {_AXI_BOUND_NS} ns bound",
        )

        # S6: a denying entry of lower index sits ahead of the admitting entry 2.
        await self._program(1, _DENY_B1, _PAGE_D, _PAGE_D + _PAGE_BYTES - 1)
        wa1, wa2 = 0x6A6A_0000_0000_0001, 0x6A6A_0000_0000_0002
        members = [
            self._item("S6_WR_D0", wr, _PAGE_D + 0x20, wdata=0x6D6D_0000_0000_0001, refused=True),
            self._item("S6_WR_A0", wr, _PAGE_A + 0x8, wdata=wa1),
            self._item("S6_RD_D0", rd, _PAGE_D, refused=True),
            self._item("S6_RD_A0", rd, _PAGE_A, expected=_a_seed(0)),
            self._item("S6_WR_A1", wr, _PAGE_A + 0x10, wdata=wa2),
            self._item("S6_WR_D1", wr, _PAGE_D + 0x28, wdata=0x6D6D_0000_0000_0002, refused=True),
        ]
        await self._group("S6 outstanding group", members, _AXI_BOUND_NS)
        codes = [m.resp_code for m in members]
        assert codes == [3, 0, 3, 0, 0, 3], f"S6 responses {codes}, want [3, 0, 3, 0, 0, 3]"
        assert members[3].rdata == _a_seed(0), f"S6 read A rdata 0x{members[3].rdata:x}"
        await self.csr_read("S6_A1", _PAGE_A + 0x8, expected=wa1, length=8)
        await self.csr_read("S6_A2", _PAGE_A + 0x10, expected=wa2, length=8)
        await self.csr_read("S6_D4", _PAGE_D + 0x20, expected=_d_seed(4), length=8)
        await self.csr_read("S6_D5", _PAGE_D + 0x28, expected=_d_seed(5), length=8)
        self._mark_step("S6")
        self._mark_term("DENY_ADMIT_GROUP")
        self._log_chk(
            "CHK-INB-ADMIT-AFTER-DENY",
            f"one outstanding group [wr D, wr A, rd D, rd A, wr A, wr D] answered {codes} "
            f"(3 = DECERR, 0 = OKAY); the page A read returned the seeded word "
            f"0x{members[3].rdata:x}, the page A writes read back over SEP_IN, page D words "
            f"unchanged, all inside the {_AXI_BOUND_NS} ns bound",
        )

        # S7: 40 denied writes outstanding under the hold profile.
        flood = [
            self._item(
                f"S7_WR_D{n}",
                wr,
                _PAGE_D + 8 * (n % _FLOOD_WORDS),
                wdata=0x7F00_0000_0000_0000 | n,
                refused=True,
            )
            for n in range(_FLOOD_WRITES)
        ]
        self._watch.mark()
        await self._group("S7 flood group", flood, _AXI_BOUND_NS * _FLOOD_WRITES, timing=_HOLD)
        peak, aw_n, b_n = self._watch.peak, self._watch.aw_since_mark, self._watch.b_since_mark
        assert all(f.resp_code == _DECERR for f in flood), (
            f"S7 responses {[f.resp_code for f in flood]}, want 40 x DECERR"
        )
        assert aw_n == _FLOOD_WRITES and b_n == _FLOOD_WRITES, (
            f"S7 sys_axi handshakes AW {aw_n} B {b_n}, want {_FLOOD_WRITES} each"
        )
        assert peak >= 2, f"S7 peak outstanding (AW - B) {peak}: the writes never overlapped"
        for k in range(_FLOOD_WORDS):
            await self.csr_read(f"S7_D{k}", _PAGE_D + 8 * k, expected=_d_seed(k), length=8)
        self._mark_step("S7")
        self._mark_term("FLOOD")
        self._log_chk(
            "CHK-INB-DENY-FLOOD",
            f"all {_FLOOD_WRITES} denied writes to page D answered DECERR (b_ready_delay 64, "
            f"per-access bound {_AXI_BOUND_NS} ns), page D words unchanged over SEP_IN; "
            f"peak of AW handshakes - B handshakes {peak}, AW {aw_n} B {b_n}",
        )

        # S8: a SEP_IN write clears write_allowed on entry 2 while 12 writes are outstanding.
        await self._program(2, _PERMIT_B1)
        writes = [
            self._item(
                f"S8_WR_A{i}", wr, _PAGE_A + _RECONFIG_BASE + 8 * i, wdata=_r_new(i), tolerate=True
            )
            for i in range(_RECONFIG_WRITES)
        ]
        self._watch.mark()
        task = cocotb.start_soon(
            self._run_group("sys_in_reconfig_group", writes, _AXI_BOUND_NS, timing=_HOLD)
        )
        await self.csr_write("S8_IB2_NO_WRITE", _reg("FILTER_CONFIG", 2), _NO_WRITE_B1, length=8)
        in_flight = _RECONFIG_WRITES - self._watch.b_since_mark
        aw_at_cfg = self._watch.aw_since_mark
        await self._join("S8 reconfig group", task, _AXI_BOUND_NS * _RECONFIG_WRITES)
        await self.csr_read(
            "S8_IB2_NO_WRITE_RB",
            _reg("FILTER_CONFIG", 2),
            expected=_NO_WRITE_B1 | _READBACK_BITS,
            length=8,
        )
        assert in_flight >= 1, (
            f"S8 no SYS_IN write was outstanding when the SEP_IN write completed "
            f"(AW {aw_at_cfg}, B {self._watch.b_since_mark})"
        )
        resp = [w.resp_code for w in writes]
        assert all(r in (0, _DECERR) for r in resp), f"S8 responses {resp}"
        words = [
            await self.csr_read(f"S8_RB{i}", _PAGE_A + _RECONFIG_BASE + 8 * i, length=8)
            for i in range(_RECONFIG_WRITES)
        ]
        for i, (r, w) in enumerate(zip(resp, words)):
            want = _r_new(i) if r == 0 else _r_seed(i)
            assert w == want, f"S8 write {i} resp {r}: word 0x{w:x}, want 0x{want:x}"
        flips = sum(1 for a, b in zip(resp, resp[1:]) if a == 0 and b == _DECERR)
        assert flips <= 1, f"S8 responses {resp}: {flips} OKAY-to-DECERR transitions"
        assert not any(a == _DECERR and b == 0 for a, b in zip(resp, resp[1:])), (
            f"S8 responses {resp}: an OKAY after a DECERR"
        )
        self._mark_step("S8")
        self._mark_term("RECONFIG")
        self._log_chk(
            "CHK-INB-RECONFIG-OUTSTANDING",
            f"all 12 writes completed with responses {resp} (3 = DECERR, 0 = OKAY); each OKAY "
            f"changed its word and each DECERR left it; {flips} OKAY-to-DECERR transition(s) in "
            f"issue order; {in_flight} write(s) still outstanding and AW {aw_at_cfg} accepted "
            "when the SEP_IN reconfiguration completed; LINKED-ISSUE SF-009 (the point from "
            "which the new entry governs is not stated)",
        )

        # S9: every programmed entry and scratch register returns to its reset word.
        for entry in (1, 2, 3, 4):
            await self.csr_write(
                f"IB{entry}_CFG_RESTORE", _reg("FILTER_CONFIG", entry), _RESET_CFG, length=8
            )
            await self.csr_write(
                f"IB{entry}_START_RESTORE", _reg("START_ADDR", entry), _RESET_START, length=8
            )
            await self.csr_write(
                f"IB{entry}_END_RESTORE", _reg("END_ADDR", entry), _RESET_END, length=8
            )
        for i in range(1, 7):
            await self.csr_restore(f"SCR{i}", _scratch(i), 0)
        for entry in (1, 2, 3, 4):
            await self.csr_read(
                f"IB{entry}_CFG_FINAL", _reg("FILTER_CONFIG", entry), _RESET_CFG, length=8
            )
        assert self._watch.unresolved == 0, f"{self._watch.unresolved} X/Z probe samples"
        watcher.cancel()
        self._mark_step("S9")

        self._waits.append(
            f"SEP_IN and SYS_IN AXI accesses bound {_AXI_BOUND_NS} ns each, allow_timeout False, "
            f"{self.accesses} SEP_IN and {self.sys_accesses} SYS_IN completed; the hit and "
            "handshake watcher is a passive sampler with no wait"
        )
        self._nonvac_fence()

    def _nonvac_fence(self) -> None:
        ids = tuple(s for s, _ in self._stamps)
        assert ids == _STEPS, f"step ids {ids}, want {_STEPS}"
        times = [t for _, t in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"stamps not increasing: {times}"
        terms = tuple(t for t, _ in self._term_stamps)
        assert terms == _TERMS, f"fence terms {terms}, want {_TERMS}"
        term_times = [t for _, t in self._term_stamps]
        assert all(b > a for a, b in zip(term_times, term_times[1:])), (
            f"fence stamps not increasing: {term_times}"
        )
        assert tuple(c for c, _ in self._chk_marks) == tuple(c for c, _ in _CHECKERS)
        stamp_of = dict(self._stamps)
        for (chk_id, when), (_, step) in zip(self._chk_marks, _CHECKERS):
            assert when >= stamp_of[step], f"{chk_id} printed before step {step}"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; stamps %s",
            " < ".join(_TERMS),
            ",".join(c.replace("LIFECYCLE", "LIFE-CYCLE") for c, _ in self._chk_marks),
            ",".join(f"{s}={t}" for s, t in self._term_stamps),
        )
        cocotb.log.info("CHK-TIMEOUT-PATHS: %s", " | ".join(self._waits))
