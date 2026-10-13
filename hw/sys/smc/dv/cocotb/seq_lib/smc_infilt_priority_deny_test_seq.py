# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Inbound filter lowest-hit priority, per-channel permission and the denial responses.

Contract SMC_FILTER_22, anchor smc_infilt_priority_deny_test.
Allocated scenarios: INFILT-PRIORITY-PERM.S1-S5, INFILT-DENY-RESPONSE.S1-S3.
Spec sources: axi_filter index.adoc Match Then Permit and Blocked Transactions, fabric.adoc
Inbound Filtering, filter_ctrl.rdl FILTER_CONFIG.

Inbound entries 0..2, 7, 8, 14 and 15 are programmed over SEP_IN, SYS_IN reads, writes and
bursts hit SPM pages, every changed or unchanged word is read back over SEP_IN, and the entries
return to their reset words. Entry 0 is never locked.
"""

from __future__ import annotations

import os
import random

import cocotb
from cocotb.triggers import ReadOnly, RisingEdge
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from ._one_shot import _OneShot
from .smc_addr_map import _REPO, _field_mask, reg_reset_word, smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq

_FILTER_H = _REPO / "hw" / "ip" / "axi_filter" / "regs" / "gen" / "c" / "filter_ctrl.h"
_ENTRY_ENABLED = _field_mask(_FILTER_H, "FILTER_CTRL__FILTER_CONFIG__ENTRY_ENABLED_bm")
_RESET_CFG = reg_reset_word(_FILTER_H, "FILTER_CTRL", "FILTER_CONFIG")
_RESET_START = reg_reset_word(_FILTER_H, "FILTER_CTRL", "START_ADDR")
_RESET_END = reg_reset_word(_FILTER_H, "FILTER_CTRL", "END_ADDR")

# Contract words; the read-back adds data_bus_width 3.
_DENY_B1 = 0x0000_0000_0100_0010
_PERMIT_B1 = 0x0000_0000_0100_0013
_RDONLY_B1 = 0x0000_0000_0100_0011
_WRONLY_B1 = 0x0000_0000_0100_0012
_DENY_NS1 = 0x0000_0000_0100_0110
_PERMIT_B0 = 0x0000_0000_0000_0013
_READBACK_BITS = 0x3000
_SPM = smc_addr("SMC_TOP_SPM_MEMORY_BASE_ADDR")
_PAGE_A = _SPM + 0x6_0000
_PAGE_D = _SPM + 0x7_0000
_PAIR_PAGE = _SPM + 0x8_0000
_PAIRS = ((0, 1), (7, 8), (14, 15))
_OVERLAP_OFFSETS = (0x000, 0x400, 0x800)
_USED_ENTRIES = (0, 1, 2, 7, 8, 14, 15)
_DECERR = 3
_AXI_BOUND_NS = 50_000
_FUSE_BOUND = 200_000
_SYS_ACCESSES = 24
_FLOOR = 150
_STEPS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9")
_TERMS = "SEEDED<PRIORITY_LEGS<CHANNEL_LEGS<PAIR_LEGS<DENIED_READS<DENIED_WRITES<CLASSES<CLEANED"
_CHECKERS = (
    ("CHK-INB-PRIO-DENY-OVER-PERMIT", "S2"),
    ("CHK-INB-PRIO-PERMIT-OVER-DENY", "S2"),
    ("CHK-INB-PER-CHANNEL", "S3"),
    ("CHK-INB-RD-WR-DIFF-ENTRY", "S4"),
    ("CHK-INB-PRIO-PAIRS", "S5"),
    ("CHK-INB-DENY-READ-RRESP", "S6"),
    ("CHK-INB-DENY-WRITE-BRESP", "S7"),
    ("CHK-INB-DENY-CLASSES", "S8"),
)
_RD, _WR = SmcSysAxiOp.READ, SmcSysAxiOp.WRITE
_PAGE_A_WORDS = (0x100, 0x200, 0x300)
_PAGE_D_WORDS = (0x000, 0x100, 0x108, 0x110, 0x118, 0x200, 0x300, 0x308)


def _seed(addr: int) -> int:
    return 0x5EED_0000_0000_0000 | ((addr & 0xF_FFFF) << 16) | 0x1357


def _new(addr: int) -> int:
    return 0xC0DE_0000_0000_0000 | ((addr & 0xF_FFFF) << 16) | 0x2468


def _reg(reg: str, entry: int) -> int:
    return smc_indexed_addr(f"SMC_TOP_SMC_INBOUND_FILTER_CTRL_{reg}_BASE_ADDR", entry)


def _pair_page(index: int) -> int:
    return _PAIR_PAGE + 0x1_0000 * index


class _SysWatch:
    """Samples the SYS_IN filter probes and the R, W and B handshakes once per clk_smc_i rise.

    The filter probes show a request's decision on the clk_smc_i sample after the one that
    first shows its valid high, so a hit or isolate sample counts when the same channel's valid
    was high at the previous sample. `flush` takes the sample of the rise an access completed
    on when the watcher task has not reached it yet; one rise is sampled once.
    """

    def __init__(self, dut) -> None:
        self.dut = dut
        self.unresolved = 0
        self._prev = {"read": 0, "write": 0}
        self._edge_ps = -1
        self._sampled_ps = -1
        self.clear()

    def clear(self) -> None:
        self.read = {"hit": 0, "isolate": 0, "cycles": 0}
        self.write = {"hit": 0, "isolate": 0, "cycles": 0}
        self.r_beats: list[tuple[int, int]] = []
        self.w_before_b = 0
        self.b_seen = 0

    def sample(self) -> None:
        now = int(get_sim_time("ps"))
        if now != self._edge_ps or now == self._sampled_ps:
            return
        self._sampled_ps = now
        dut = self.dut
        hs = (
            dut.sys_axi_rvalid,
            dut.sys_axi_rready,
            dut.sys_axi_wvalid,
            dut.sys_axi_wready,
            dut.sys_axi_bvalid,
            dut.sys_axi_bready,
        )
        if all(s.value.is_resolvable for s in hs):
            rv, rr, wv, wr, bv, br = (int(s.value) for s in hs)
            if rv and rr:
                assert dut.sys_axi_rresp.value.is_resolvable, "sys_axi_rresp is X/Z on a beat"
                assert dut.sys_axi_rlast.value.is_resolvable, "sys_axi_rlast is X/Z on a beat"
                self.r_beats.append((int(dut.sys_axi_rresp.value), int(dut.sys_axi_rlast.value)))
            if wv and wr and not self.b_seen:
                self.w_before_b += 1
            if bv and br:
                self.b_seen += 1
        else:
            self.unresolved += 1
        for name, acc, valid, hit, iso in (
            ("read", self.read, dut.sys_axi_arvalid, dut.tb_inb_read_hit, dut.tb_inb_isolate_read),
            (
                "write",
                self.write,
                dut.sys_axi_awvalid,
                dut.tb_inb_write_hit,
                dut.tb_inb_isolate_write,
            ),
        ):
            if not (
                valid.value.is_resolvable and hit.value.is_resolvable and iso.value.is_resolvable
            ):
                self.unresolved += 1
                continue
            if self._prev[name]:
                acc["hit"] |= int(hit.value)
                acc["isolate"] |= int(iso.value)
                acc["cycles"] += 1
            self._prev[name] = int(valid.value)

    async def run(self) -> None:
        while True:
            await RisingEdge(self.dut.clk_smc_i)
            self._edge_ps = int(get_sim_time("ps"))
            await ReadOnly()
            self.sample()

    async def flush(self) -> None:
        await ReadOnly()
        self.sample()


class smc_infilt_priority_deny_test_seq(SmcCsrSeq):
    """Program inbound entries over SEP_IN, then drive SYS_IN accesses against them."""

    def __init__(self, name: str = "smc_infilt_priority_deny_test_seq") -> None:
        super().__init__(name)
        self.sys_accesses = 0
        self._stamps: list[tuple[str, int]] = []
        self._chk_marks: list[tuple[str, int]] = []
        self._pending: list[tuple[str, str]] = []
        self._waits: list[str] = []
        self._watch: _SysWatch | None = None

    def _mark_step(self, step_id: str) -> None:
        self._stamps.append((step_id, int(get_sim_time("ps"))))

    def _log_chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self._chk_marks.append((chk_id, int(get_sim_time("ps"))))

    def _flush_chk(self) -> None:
        for chk_id, text in self._pending:
            self._log_chk(chk_id, text)
        self._pending = []

    @staticmethod
    def _probe(sig) -> int:
        assert sig.value.is_resolvable, f"{sig._name} is X/Z ({sig.value})"
        return int(sig.value)

    async def _sys(
        self,
        tag: str,
        op: SmcSysAxiOp,
        addr: int,
        resp: int,
        *,
        wdata: int = 0,
        want: int | None = None,
        beats: int = 1,
        prot: int = 0,
    ) -> dict:
        """One SYS_IN access of 8-byte beats; asserts the response, returns its observations."""
        item = SmcSysAxiItem(f"sys_in_{tag}")
        item.op = op
        item.addr = addr
        item.length = 8
        item.beats = beats
        item.wdata = wdata
        item.prot = prot
        if resp == _DECERR:
            item.allow_error = True
            item.expect_error = True
            item.expected_resp = _DECERR
        elif op == _RD:
            item.expected = want
        self._watch.clear()
        await _OneShot(item, f"sys_in_{tag}_os").start(self.env.sys_in_axi_agent.sequencer)
        await self._watch.flush()
        self.sys_accesses += 1
        watch = self._watch
        assert watch.unresolved == 0, f"{tag}: X/Z on a SYS_IN handshake or filter probe"
        chan = dict(watch.read if op == _RD else watch.write)
        assert chan["cycles"] > 0, f"{tag}: no valid cycle sampled"
        assert item.resp_code == resp, f"{tag}: resp {item.resp_code}, want {resp}"
        if resp == 0 and op == _RD:
            assert item.rdata == want, f"{tag}: rdata 0x{item.rdata:x}, want 0x{want:x}"
        chan.update(
            resp=item.resp_code,
            rdata=item.rdata,
            r_beats=list(watch.r_beats),
            w_before_b=watch.w_before_b,
            b_seen=watch.b_seen,
        )
        return chan

    @staticmethod
    def _fmt(tag: str, chan: dict) -> str:
        return f"{tag} resp {chan['resp']} hit 0x{chan['hit']:x} isolate {chan['isolate']}"

    async def _cfg(self, entry: int, word: int) -> None:
        await self.csr_write(f"IB{entry}_CFG", _reg("FILTER_CONFIG", entry), word, length=8)
        await self.csr_read(
            f"IB{entry}_CFG_RB",
            _reg("FILTER_CONFIG", entry),
            expected=word | _READBACK_BITS,
            length=8,
        )

    async def _program(self, entry: int, word: int, start: int, end: int) -> None:
        """Write FILTER_CONFIG first so its allow_burst governs the range writes."""
        await self._cfg(entry, word)
        await self.csr_write(f"IB{entry}_START", _reg("START_ADDR", entry), start, length=8)
        await self.csr_write(f"IB{entry}_END", _reg("END_ADDR", entry), end, length=8)

    async def _word(self, tag: str, addr: int, want: int) -> None:
        await self.csr_read(tag, addr, expected=want, length=8)

    async def _pair_probe(self, tag: str, channel: str, addr: int, resp: int) -> dict:
        if channel == "read":
            return await self._sys(tag, _RD, addr, resp, want=_seed(addr))
        chan = await self._sys(tag, _WR, addr, resp, wdata=_new(addr))
        await self._word(f"{tag}_WORD", addr, _new(addr) if resp == 0 else _seed(addr))
        return chan

    async def _s2(self) -> None:
        addr = _PAGE_A + 0x100
        await self._program(1, _DENY_B1, _PAGE_A, _PAGE_A + 0xFFF)
        await self._program(2, _PERMIT_B1, _PAGE_A, _PAGE_A + 0xFFF)
        d_rd = await self._sys("S2_DENY_RD", _RD, addr, _DECERR)
        d_wr = await self._sys("S2_DENY_WR", _WR, addr, _DECERR, wdata=_new(addr))
        await self._word("S2_DENY_WR_WORD", addr, _seed(addr))
        await self._cfg(1, _PERMIT_B1)
        await self._cfg(2, _DENY_B1)
        p_rd = await self._sys("S2_PERMIT_RD", _RD, addr, 0, want=_seed(addr))
        p_wr = await self._sys("S2_PERMIT_WR", _WR, addr, 0, wdata=_new(addr))
        await self._word("S2_PERMIT_WR_WORD", addr, _new(addr))
        for chan, name in ((p_rd, "read"), (p_wr, "write")):
            assert chan["hit"] & 0b110 == 0b110, f"permit-over-deny {name} hit 0x{chan['hit']:x}"
        await self.csr_write("S2_IB1_ZERO", _reg("FILTER_CONFIG", 1), 0, length=8)
        await self.csr_write("S2_IB2_ZERO", _reg("FILTER_CONFIG", 2), 0, length=8)
        self._mark_step("S2")
        self._pending.append(
            (
                "CHK-INB-PRIO-DENY-OVER-PERMIT",
                f"deny entry 1 over permit entry 2: read and write both answer DECERR and the "
                f"word at 0x{addr:x} still reads the seed 0x{_seed(addr):x} over SEP_IN: "
                f"{self._fmt('read', d_rd)}; {self._fmt('write', d_wr)}",
            )
        )
        self._pending.append(
            (
                "CHK-INB-PRIO-PERMIT-OVER-DENY",
                f"permit entry 1 over deny entry 2: read returns the seed and write lands "
                f"0x{_new(addr):x}, both OKAY with hit bits 1 and 2 both set: "
                f"{self._fmt('read', p_rd)}; {self._fmt('write', p_wr)}",
            )
        )
        self._flush_chk()

    async def _s3(self) -> None:
        addr = _PAGE_A + 0x200
        await self._program(1, _RDONLY_B1, _PAGE_A, _PAGE_A + 0xFFF)
        ro_rd = await self._sys("S3_RDONLY_RD", _RD, addr, 0, want=_seed(addr))
        ro_wr = await self._sys("S3_RDONLY_WR", _WR, addr, _DECERR, wdata=_new(addr))
        await self._word("S3_RDONLY_WR_WORD", addr, _seed(addr))
        await self._cfg(1, _WRONLY_B1)
        wo_wr = await self._sys("S3_WRONLY_WR", _WR, addr, 0, wdata=_new(addr))
        await self._word("S3_WRONLY_WR_WORD", addr, _new(addr))
        wo_rd = await self._sys("S3_WRONLY_RD", _RD, addr, _DECERR)
        await self.csr_write("S3_IB1_ZERO", _reg("FILTER_CONFIG", 1), 0, length=8)
        self._mark_step("S3")
        self._log_chk(
            "CHK-INB-PER-CHANNEL",
            f"RDONLY_B1: read OKAY with the seed, write DECERR and word unchanged: "
            f"{self._fmt('read', ro_rd)}; {self._fmt('write', ro_wr)}; WRONLY_B1: write OKAY "
            f"and word changed to 0x{_new(addr):x}, read DECERR: {self._fmt('write', wo_wr)}; "
            f"{self._fmt('read', wo_rd)}",
        )

    async def _s4(self) -> None:
        addr = _PAGE_A + 0x300
        await self._program(1, _DENY_NS1, _PAGE_A, _PAGE_A + 0xFFF)
        await self._program(2, _PERMIT_B1, _PAGE_A, _PAGE_A + 0xFFF)
        rd = await self._sys("S4_NS_RD", _RD, addr, _DECERR, prot=0b010)
        wr = await self._sys("S4_WR", _WR, addr, 0, wdata=_new(addr), prot=0)
        assert rd["hit"] & 0b10, f"read hit 0x{rd['hit']:x} lacks bit 1"
        assert wr["hit"] & 0b100, f"write hit 0x{wr['hit']:x} lacks bit 2"
        assert not wr["hit"] & 0b10, f"write hit 0x{wr['hit']:x} has bit 1 set"
        await self._word("S4_WR_WORD", addr, _new(addr))
        await self.csr_write("S4_IB1_ZERO", _reg("FILTER_CONFIG", 1), 0, length=8)
        await self.csr_write("S4_IB2_ZERO", _reg("FILTER_CONFIG", 2), 0, length=8)
        self._mark_step("S4")
        self._log_chk(
            "CHK-INB-RD-WR-DIFF-ENTRY",
            f"at 0x{addr:x} the prot 0b010 read selects deny entry 1 (DECERR, read hit bit 1) and "
            f"the prot 0 write selects permit entry 2 (OKAY, write hit bit 2 set, bit 1 clear): "
            f"{self._fmt('read', rd)}; {self._fmt('write', wr)}",
        )

    async def _s5(self) -> None:
        rng = random.Random(int(os.environ.get("RANDOM_SEED", "1"), 0))
        visited: set[tuple[int, int, int]] = set()
        cells = []
        for low, high in _PAIRS:
            page = _pair_page(_PAIRS.index((low, high)))
            cell_lines = []
            for iteration, (low_word, high_word, resp) in enumerate(
                ((_DENY_B1, _PERMIT_B1, _DECERR), (_PERMIT_B1, _DENY_B1, 0)), start=1
            ):
                offset = rng.choice(_OVERLAP_OFFSETS)
                channel = rng.choice(("read", "write"))
                if iteration == 1:
                    await self._program(low, low_word, page, page + 0x1FFF)
                    await self._program(high, high_word, page + 0x1000, page + 0x2FFF)
                else:
                    await self._cfg(low, low_word)
                    await self._cfg(high, high_word)
                addr = page + 0x1000 + offset
                chan = await self._pair_probe(f"S5_P{low}_{high}_I{iteration}", channel, addr, resp)
                visited.add((low, high, iteration))
                cell_lines.append(
                    f"({low},{high}) it{iteration} {channel} offset 0x{offset:x} low "
                    f"{'DENY' if resp else 'PERMIT'}: {self._fmt(channel, chan)}"
                )
            await self.csr_write(f"S5_IB{low}_ZERO", _reg("FILTER_CONFIG", low), 0, length=8)
            await self.csr_write(f"S5_IB{high}_ZERO", _reg("FILTER_CONFIG", high), 0, length=8)
            cells.extend(cell_lines)
        want = {(low, high, it) for low, high in _PAIRS for it in (1, 2)}
        assert visited == want, f"visited {sorted(visited)}, want {sorted(want)}"
        self._mark_step("S5")
        self._log_chk(
            "CHK-INB-PRIO-PAIRS",
            f"all three pairs visited with both iterations, seed draw printed per cell; the "
            f"lower entry's decision decides the overlap probe: {'; '.join(cells)}",
        )

    async def _s6(self) -> None:
        await self._program(1, _DENY_B1, _PAGE_D, _PAGE_D + 0xFFF)
        single = await self._sys("S6_RD1", _RD, _PAGE_D, _DECERR)
        burst = await self._sys("S6_RD4", _RD, _PAGE_D + 0x100, _DECERR, beats=4)
        parts = []
        for tag, chan in (("single", single), ("4-beat", burst)):
            beats = chan["r_beats"]
            assert beats, f"{tag} denied read returned no R beat"
            assert all(resp == _DECERR for resp, _ in beats), f"{tag} R beats {beats}"
            assert beats[-1][1] == 1, f"{tag} last returned beat lacks RLAST: {beats}"
            parts.append(
                f"{tag} {len(beats)} R beats rresp {[r for r, _ in beats]} rlast on last "
                f"rdata 0x{chan['rdata']:x} (beat count and rdata printed, not graded) "
                f"{self._fmt(tag, chan)}"
            )
        self._mark_step("S6")
        self._log_chk(
            "CHK-INB-DENY-READ-RRESP",
            f"denied reads over page D with DENY_B1 return DECERR on every returned beat and "
            f"RLAST on the last: {'; '.join(parts)}",
        )

    async def _s7(self) -> None:
        single_addr = _PAGE_D + 0x200
        burst_addr = _PAGE_D + 0x300
        single = await self._sys("S7_WR1", _WR, single_addr, _DECERR, wdata=_new(single_addr))
        data = _new(burst_addr) | (_new(burst_addr + 8) << 64)
        burst = await self._sys("S7_WR2", _WR, burst_addr, _DECERR, wdata=data, beats=2)
        for addr in (single_addr, burst_addr, burst_addr + 8):
            await self._word(f"S7_WORD_{addr & 0xFFF:X}", addr, _seed(addr))
        self._mark_step("S7")
        self._log_chk(
            "CHK-INB-DENY-WRITE-BRESP",
            f"denied single-beat and 2-beat writes over page D answer BRESP DECERR and the three "
            f"words still read their seeds over SEP_IN: {self._fmt('single', single)} W beats "
            f"accepted before B {single['w_before_b']}; {self._fmt('burst', burst)} W beats "
            f"accepted before B {burst['w_before_b']} (printed, not graded)",
        )

    async def _s8(self) -> None:
        await self._cfg(1, 0)
        c1 = await self._sys("S8_NOMATCH", _RD, _PAGE_D, _DECERR)
        assert c1["hit"] == 0, f"no-match read hit 0x{c1['hit']:x}"
        await self._cfg(1, _DENY_B1)
        c2 = await self._sys("S8_DENY", _RD, _PAGE_D, _DECERR)
        await self._cfg(1, _PERMIT_B0)
        pre = await self._sys("S8_B0_SINGLE", _RD, _PAGE_D + 0x100, 0, want=_seed(_PAGE_D + 0x100))
        assert pre["hit"] & 0b10, f"single-beat read hit 0x{pre['hit']:x} lacks bit 1"
        c3 = await self._sys("S8_BURST_MISMATCH", _RD, _PAGE_D + 0x100, _DECERR, beats=2)
        assert c3["hit"] == 0, f"burst-mismatch read hit 0x{c3['hit']:x}"
        self._mark_step("S8")
        self._log_chk(
            "CHK-INB-DENY-CLASSES",
            f"class 1 no match (entry disabled) {self._fmt('read', c1)}; class 2 matching deny "
            f"entry {self._fmt('read', c2)} (hit printed, not graded); class 3 burst mismatch: "
            f"the same entry admits the single-beat read ({self._fmt('read', pre)}) and refuses "
            f"the 2-beat read {self._fmt('read', c3)}; classes 1 and 3 hit vector 0",
        )

    async def _s9(self) -> None:
        for entry in _USED_ENTRIES:
            for reg, val in (
                ("FILTER_CONFIG", _RESET_CFG),
                ("START_ADDR", _RESET_START),
                ("END_ADDR", _RESET_END),
            ):
                await self.csr_write(f"IB{entry}_{reg}_CLEAN", _reg(reg, entry), val, length=8)
            await self.csr_read(
                f"IB{entry}_CFG_FINAL", _reg("FILTER_CONFIG", entry), _RESET_CFG, length=8
            )
        self._mark_step("S9")

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

        # S1: the used entries start disabled; every probe word is seeded over SEP_IN.
        for entry in _USED_ENTRIES:
            cfg = await self.csr_read(f"IB{entry}_QUIET", _reg("FILTER_CONFIG", entry), length=8)
            assert not cfg & _ENTRY_ENABLED, f"inbound {entry} enabled: 0x{cfg:x}"
        seeded = [_PAGE_A + off for off in _PAGE_A_WORDS]
        seeded += [_PAGE_D + off for off in _PAGE_D_WORDS]
        seeded += [_pair_page(i) + 0x1000 + off for i in range(3) for off in _OVERLAP_OFFSETS]
        for addr in seeded:
            await self.csr_write(f"SEED_{addr & 0xFFFFF:X}", addr, _seed(addr), length=8)
        self._mark_step("S1")

        await self._s2()
        await self._s3()
        await self._s4()
        await self._s5()
        await self._s6()
        await self._s7()
        await self._s8()
        await self._s9()
        watcher.kill()

        self._waits.append(
            f"SEP_IN and SYS_IN AXI accesses bound {_AXI_BOUND_NS} ns, allow_timeout False, "
            f"{self.accesses} SEP_IN and {self.sys_accesses} SYS_IN completed; the SYS_IN watcher "
            "is a passive sampler with no wait"
        )
        self._nonvac_fence()

    def _nonvac_fence(self) -> None:
        ids = tuple(s for s, _ in self._stamps)
        assert ids == _STEPS, f"step ids {ids}, want {_STEPS}"
        times = [t for _, t in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"stamps not increasing: {times}"
        assert tuple(c for c, _ in self._chk_marks) == tuple(c for c, _ in _CHECKERS)
        stamp_of = dict(self._stamps)
        for (chk_id, when), (_, step) in zip(self._chk_marks, _CHECKERS):
            assert when >= stamp_of[step], f"{chk_id} printed before step {step}"
        assert self.sys_accesses == _SYS_ACCESSES, f"{self.sys_accesses} SYS_IN accesses"
        total = self.accesses + self.sys_accesses
        assert total >= _FLOOR, f"{total} accesses, floor {_FLOOR}"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; accesses %d (%d SEP_IN + %d SYS_IN) "
            "vs floor %d; stamps %s",
            _TERMS,
            ",".join(c for c, _ in self._chk_marks),
            total,
            self.accesses,
            self.sys_accesses,
            _FLOOR,
            ",".join(f"{s}={t}" for s, t in self._stamps),
        )
        cocotb.log.info("CHK-TIMEOUT-PATHS: %s", " | ".join(self._waits))
