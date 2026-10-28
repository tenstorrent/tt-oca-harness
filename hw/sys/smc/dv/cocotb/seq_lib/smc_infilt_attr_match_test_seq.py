# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Inbound filter attribute match: AxPROT[1] equality, fall-through, src_id and group_id,
same-page ranges of entries 4 to 15 and entry-15 INCR bursts.

Spec sources: fabric.adoc Non-Secure Bit Filtering, axi_filter index.adoc Match Then Permit and
Address Range Granule, filter_ctrl.rdl FILTER_CONFIG, START_ADDR and END_ADDR.

Inbound entries 2 and 3 are programmed over SEP_IN, SYS_IN reads and writes with chosen AxPROT
hit one SPM page, and both entries return to their reset words. Entries 4 to 15 are then each
programmed alone over a sub-range of their own SPM page, and entry 15 alone over two pages decides
SYS_IN INCR bursts by allow_burst, src_id and its permission bits. Entries 0 and 1 and every lock
stay untouched, and entries 4 to 15 return to their reset words.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ReadOnly, RisingEdge
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from ._one_shot import _OneShot
from .smc_addr_map import _REPO, _field_mask, reg_reset_word, smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq

_FILTER_H = _REPO / "hw" / "ip" / "axi_filter" / "regs" / "gen" / "c" / "filter_ctrl.h"
_ENTRY_ENABLED = _field_mask(_FILTER_H, "FILTER_CTRL__FILTER_CONFIG__ENTRY_ENABLED_bm")
_READ_ALLOWED = _field_mask(_FILTER_H, "FILTER_CTRL__FILTER_CONFIG__READ_ALLOWED_bm")
_WRITE_ALLOWED = _field_mask(_FILTER_H, "FILTER_CTRL__FILTER_CONFIG__WRITE_ALLOWED_bm")
_ALLOW_BURST = _field_mask(_FILTER_H, "FILTER_CTRL__FILTER_CONFIG__ALLOW_BURST_bm")
_SRC_ID = _field_mask(_FILTER_H, "FILTER_CTRL__FILTER_CONFIG__SRC_ID_bm")
_RESET_CFG = reg_reset_word(_FILTER_H, "FILTER_CTRL", "FILTER_CONFIG")
_RESET_START = reg_reset_word(_FILTER_H, "FILTER_CTRL", "START_ADDR")
_RESET_END = reg_reset_word(_FILTER_H, "FILTER_CTRL", "END_ADDR")

# Register words; the read-back adds data_bus_width 3.
_PERMIT_NS0 = 0x0000_0000_0100_0013
_PERMIT_NS1 = 0x0000_0000_0100_0113
_DENY_NS0 = 0x0000_0000_0100_0010
_PERMIT_SRC5 = 0x0000_0000_0105_0013
_PERMIT_GRP10 = 0x0000_0000_01A0_0013
_READBACK_BITS = _RESET_CFG
_PAGE = smc_addr("SMC_TOP_SPM_MEMORY_BASE_ADDR") + 0x5_0000
_PAGE_END = _PAGE + 0xFFF
_WORDS = 9
_PROT_NS1 = 0b010
_DECERR = 3
_AXI_BOUND_NS = 50_000
_FUSE_BOUND = 200_000
_FLOOR = 83
_STEPS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9")
_TERMS = "SEEDED<NS_EQUALITY<FALLTHROUGH<PROT_BITS<PER_CHANNEL<SRCID_LEGS<GROUPID<CLEANED"
_SPM = smc_addr("SMC_TOP_SPM_MEMORY_BASE_ADDR")
_PAGE_ENTRIES = tuple(range(4, 16))
_IN_PAGE = (0x000, 0x800, 0xFF8)
_OUT_PAGE = (-0x8, 0x1000)
_Q = _SPM + 0x8_0000
_Q_WORDS = 4
_Q_DENY = _Q + 0x100
_BURSTS = ((1, _Q + 0x1000), (3, _Q + 0x1100), (7, _Q + 0x1200), (15, _Q + 0x1400))
_E15 = 15
_E15_HIT = 1 << _E15
_RW_BURST = _ENTRY_ENABLED | _READ_ALLOWED | _WRITE_ALLOWED | _ALLOW_BURST
_CONTRACT_START = 0x0
_CONTRACT_END = 0x7
_CONTRACT_CFG = 0x3000
_NEW_TERMS = (
    "PAGE-WALK",
    "PAGE-OUTSIDE",
    "GRANULE",
    "E15-PERMIT",
    "E15-NOBURST",
    "E15-SRCID",
    "E15-PERM",
    "RESTORE",
)
_NEW_CHECKERS = (
    ("CHK-INB-PAGE-WIDEN", "PAGE-WALK"),
    ("CHK-INB-PAGE-HIT", "PAGE-WALK"),
    ("CHK-INB-PAGE-OUTSIDE", "PAGE-OUTSIDE"),
    ("CHK-INB-GRANULE-WIDEN", "GRANULE"),
    ("CHK-INB-E15-BURST-PERMIT", "E15-PERMIT"),
    ("CHK-INB-E15-BURST-DISALLOWED", "E15-NOBURST"),
    ("CHK-INB-E15-SRCID-MISMATCH", "E15-SRCID"),
    ("CHK-INB-E15-PERM-DENY", "E15-PERM"),
)
_CHECKERS = (
    ("CHK-INB-NS0-EQUALITY", "S2"),
    ("CHK-INB-NS1-EQUALITY", "S2"),
    ("CHK-INB-NS-FALLTHROUGH", "S3"),
    ("CHK-INB-PROT-BITS-IGNORED", "S4"),
    ("CHK-INB-NS-PER-CHANNEL", "S5"),
    ("CHK-INB-SRCID-WILDCARD-ZERO", "S6"),
    ("CHK-INB-SRCID-NONZERO-VS-ZERO", "S7"),
    ("CHK-INB-GROUPID-INERT", "S8"),
)


def _seed(index: int) -> int:
    return 0xA11C_0000_0000_0000 | (index << 32) | (0x5A5A_0000 + index)


def _page(entry: int) -> int:
    return _SPM + 0x6_0000 + entry * 0x2000


def _page_seed(entry: int, slot: int) -> int:
    return 0xB4A6_0000_0000_0000 | (entry << 40) | (slot << 32) | (0x7E57_0000 + 16 * entry + slot)


def _q_seed(index: int) -> int:
    return 0xE15E_0000_0000_0000 | (index << 32) | (0x0E15_0000 + index)


def _burst_word(tag: int, beat: int) -> int:
    return 0xB0B5_0000_0000_0000 | (tag << 40) | (beat << 32) | (0xDA7A_0000 + 256 * tag + beat)


def _pack(words: list[int]) -> int:
    return sum(w << (64 * i) for i, w in enumerate(words))


def _reg(reg: str, entry: int) -> int:
    return smc_indexed_addr(f"SMC_TOP_SMC_INBOUND_FILTER_CTRL_{reg}_BASE_ADDR", entry)


class _HitWatch:
    """Accumulates the inbound hit and isolate probes for each SYS_IN request.

    The filter probes show a request's decision on the clk_smc_i sample after the one that
    first shows its valid high, so a sample counts when the same channel's valid was high at the
    previous sample.
    """

    def __init__(self, dut) -> None:
        self.dut = dut
        self.clear()

    def clear(self) -> None:
        self.read = {"hit": 0, "isolate": 0, "cycles": 0}
        self.write = {"hit": 0, "isolate": 0, "cycles": 0}
        self.unresolved = 0
        self.rbeats: list[int] = []
        self.r_unresolved = 0

    async def run(self) -> None:
        dut = self.dut
        prev = {"read": 0, "write": 0}
        while True:
            await RisingEdge(dut.clk_smc_i)
            await ReadOnly()
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
            self._sample_r_beat()

    def _sample_r_beat(self) -> None:
        """Record RRESP of every R beat whose valid and ready are both high at the sample."""
        dut = self.dut
        rvalid, rready = dut.sys_axi_rvalid.value, dut.sys_axi_rready.value
        if not (rvalid.is_resolvable and rready.is_resolvable):
            self.r_unresolved += 1
            return
        if int(rvalid) and int(rready):
            rresp = dut.sys_axi_rresp.value
            if rresp.is_resolvable:
                self.rbeats.append(int(rresp))
            else:
                self.r_unresolved += 1


class smc_infilt_attr_match_test_seq(SmcCsrSeq):
    """Program inbound entries 2 and 3, then drive SYS_IN accesses with chosen AxPROT."""

    def __init__(self, name: str = "smc_infilt_attr_match_test_seq") -> None:
        super().__init__(name)
        self.sys_accesses = 0
        self._stamps: list[tuple[str, int]] = []
        self._chk_marks: list[tuple[str, int]] = []
        self._waits: list[str] = []
        self._wait_records: list[dict] = []
        self._watch = None
        self._terms: list[tuple[str, int, int]] = []
        self._last_sys = ""

    def _mark_step(self, step_id: str) -> None:
        self._stamps.append((step_id, int(get_sim_time("ps"))))

    def _record_access_wait(self, item: SmcSysAxiItem, tag: str) -> None:
        """Log one bounded AXI wait with the bound and timeout flags its item carried."""
        bound = item.timeout_ns or self.cfg.axi_timeout_ns
        rec = {
            "bus": item.bus_name,
            "bound_ns": bound,
            "allow_timeout": item.allow_timeout,
            "timed_out": item.timed_out,
        }
        self._wait_records.append(rec)
        data = item.rdata if item.op is SmcSysAxiOp.READ else item.wdata
        cocotb.log.info(
            "WAIT-RECORD[%d]: %s %s %s 0x%x bound %d ns, allow_timeout=%s, expiry raises "
            "AssertionError in SmcSysAxiDriver._timed_event; last state timed_out=%s resp=%s "
            "data=0x%x",
            len(self._wait_records),
            tag,
            item.bus_name,
            item.op.value,
            item.addr,
            bound,
            item.allow_timeout,
            item.timed_out,
            item.resp_code,
            data,
        )
        assert bound == _AXI_BOUND_NS, f"{tag}: AXI bound in force {bound} ns, want {_AXI_BOUND_NS}"
        assert not item.allow_timeout, f"{tag}: allow_timeout set on a bounded access"
        assert not item.timed_out, f"{tag}: access expired after {bound} ns"

    async def finish_item(self, item) -> None:
        if not isinstance(item, SmcSysAxiItem):
            await super().finish_item(item)
            return
        if item.timeout_ns is None:
            item.timeout_ns = _AXI_BOUND_NS
        await super().finish_item(item)
        self._record_access_wait(item, item.get_name())

    def _log_chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self._chk_marks.append((chk_id, int(get_sim_time("ps"))))

    @staticmethod
    def _probe(sig) -> int:
        assert sig.value.is_resolvable, f"{sig._name} is X/Z ({sig.value})"
        return int(sig.value)

    async def _sys_in(
        self,
        tag: str,
        op: SmcSysAxiOp,
        addr: int,
        prot: int,
        resp: int,
        *,
        hit: int | None,
        want: int | None = None,
        wdata: int = 0,
        beats: int = 1,
    ) -> str:
        """One SYS_IN access: assert its response, read data and the hit vector of its channel.

        A burst of `beats` > 1 also requires a DECERR to be the declared code and every R beat of
        a read burst to carry `resp`.
        """
        item = SmcSysAxiItem(f"sys_in_{tag}")
        item.op = op
        item.addr = addr
        item.length = 8
        item.beats = beats
        item.wdata = wdata
        item.prot = prot
        item.timeout_ns = _AXI_BOUND_NS
        if resp == _DECERR:
            item.allow_error = True
            item.expect_error = True
            if beats > 1:
                item.expected_resp = _DECERR
        else:
            item.expected = want
        self._watch.clear()
        await _OneShot(item, f"sys_in_{tag}_os").start(self.env.sys_in_axi_agent.sequencer)
        self._record_access_wait(item, f"sys_in_{tag}")
        self.sys_accesses += 1
        chan = self._watch.read if op is SmcSysAxiOp.READ else self._watch.write
        assert self._watch.unresolved == 0, f"{tag}: X/Z on a SYS_IN valid or filter probe"
        assert chan["cycles"] > 0, f"{tag}: no valid cycle sampled"
        assert item.resp_code == resp, f"{tag}: resp {item.resp_code}, want {resp}"
        if resp == 0 and op is SmcSysAxiOp.READ:
            assert item.rdata == want, f"{tag}: rdata 0x{item.rdata:x}, want 0x{want:x}"
        if hit is not None:
            assert chan["hit"] == hit, (
                f"{tag}: hit vector 0x{chan['hit']:x}, want 0x{hit:x}; isolate {chan['isolate']} "
                f"over {chan['cycles']} valid cycles"
            )
        name = "read" if op is SmcSysAxiOp.READ else "write"
        burst = ""
        if beats > 1:
            burst = f" AxLEN {beats - 1}"
            if op is SmcSysAxiOp.READ:
                rbeats = self._watch.rbeats
                assert self._watch.r_unresolved == 0, f"{tag}: X/Z on SYS_IN R valid/ready/resp"
                assert rbeats == [resp] * beats, (
                    f"{tag}: R beat resps {rbeats}, want {beats}x{resp}"
                )
                burst += f" beats {len(rbeats)} rresp {sorted(set(rbeats))}"
        self._last_sys = (
            f"{tag} {name}{burst} prot {prot:#05b} 0x{addr:x} resp {item.resp_code} "
            f"hit 0x{chan['hit']:x}"
        )
        return (
            f"{name}{burst} prot {prot:#05b} 0x{addr:x} resp {item.resp_code} "
            f"hit 0x{chan['hit']:x} isolate {chan['isolate']}"
        )

    async def _read(self, tag: str, prot: int, resp: int, hit: int | None, index: int = 0) -> str:
        want = _seed(index) if resp == 0 else None
        return await self._sys_in(
            tag, SmcSysAxiOp.READ, _PAGE + 8 * index, prot, resp, hit=hit, want=want
        )

    async def _program(self, entry: int, word: int, ranges: bool = False) -> None:
        if ranges:
            for reg, val in (("START_ADDR", _PAGE), ("END_ADDR", _PAGE_END)):
                await self.csr_write(f"IB{entry}_{reg}", _reg(reg, entry), val, length=8)
        await self.csr_write(f"IB{entry}_CFG", _reg("FILTER_CONFIG", entry), word, length=8)
        await self.csr_read(
            f"IB{entry}_CFG_RB",
            _reg("FILTER_CONFIG", entry),
            expected=word | _READBACK_BITS,
            length=8,
        )
        if ranges:
            for reg, val in (("START_ADDR", _PAGE), ("END_ADDR", _PAGE_END)):
                await self.csr_read(f"IB{entry}_{reg}_RB", _reg(reg, entry), expected=val, length=8)

    async def _sep_word(self, tag: str, index: int, want: int) -> None:
        got = await self.csr_read(tag, _PAGE + 8 * index, expected=want, length=8)
        assert got == want, f"{tag}: 0x{got:x}, want 0x{want:x}"

    async def body(self) -> None:
        top = cocotb.top
        edges = [0]

        async def _count_edges() -> None:
            while True:
                await RisingEdge(top.clk_smc_i)
                edges[0] += 1

        counter = cocotb.start_soon(_count_edges())
        await self.wait_fuse_sense_done(max_cycles=_FUSE_BOUND)
        counter.kill()
        fuse = [
            self._probe(s)
            for s in (top.tb_fuse_sense_done, top.tb_fuse_reset_n, top.tb_rst_warm_smc_clk_n)
        ]
        self._wait_records.append(
            {"bus": "fuse-sense", "bound_cycles": _FUSE_BOUND, "timed_out": False}
        )
        cocotb.log.info(
            "WAIT-RECORD[%d]: fuse-sense wait_fuse_sense_done(max_cycles=%d) bound %d clk_smc_i "
            "per probe, expiry raises AssertionError in wait_fuse_sense_done; last state after "
            "%d clk_smc_i: tb_fuse_sense_done=%d tb_fuse_reset_n=%d tb_rst_warm_smc_clk_n=%d",
            len(self._wait_records),
            _FUSE_BOUND,
            _FUSE_BOUND,
            edges[0],
            *fuse,
        )
        self._waits.append(
            f"tb_fuse_sense_done bound {_FUSE_BOUND} clk_smc_i last {fuse[0]}; tb_fuse_reset_n "
            f"bound {_FUSE_BOUND} last {fuse[1]}; tb_rst_warm_smc_clk_n bound {_FUSE_BOUND} "
            f"last {fuse[2]}; returned after {edges[0]} clk_smc_i"
        )
        self._watch = _HitWatch(top)
        watcher = cocotb.start_soon(self._watch.run())

        # S1: entries 2 and 3 start disabled; the page words are seeded over SEP_IN.
        for entry in (2, 3):
            cfg = await self.csr_read(f"IB{entry}_QUIET", _reg("FILTER_CONFIG", entry), length=8)
            assert not cfg & _ENTRY_ENABLED, f"inbound {entry} enabled: 0x{cfg:x}"
            for reg, want in (("START_ADDR", _RESET_START), ("END_ADDR", _RESET_END)):
                await self.csr_read(f"IB{entry}_{reg}_QUIET", _reg(reg, entry), want, length=8)
        for index in range(_WORDS):
            await self.csr_write(f"SEED{index}", _PAGE + 8 * index, _seed(index), length=8)
        for index in range(_WORDS):
            await self._sep_word(f"SEED{index}_RB", index, _seed(index))
        self._mark_step("S1")

        # S2: allow_ns equality in both polarities.
        await self._program(2, _PERMIT_NS0, ranges=True)
        ns0 = [await self._read("NS0_P0", 0, 0, 1 << 2)]
        ns0.append(await self._read("NS0_P2", _PROT_NS1, _DECERR, 0))
        await self._program(2, _PERMIT_NS1)
        ns1 = [await self._read("NS1_P2", _PROT_NS1, 0, 1 << 2)]
        ns1.append(await self._read("NS1_P0", 0, _DECERR, 0))
        self._mark_step("S2")
        self._log_chk(
            "CHK-INB-NS0-EQUALITY",
            f"allow_ns 0 entry 2 admits prot 0 with the seeded word and refuses prot 0b010: {ns0}",
        )
        self._log_chk(
            "CHK-INB-NS1-EQUALITY",
            f"allow_ns 1 entry 2 admits prot 0b010 and refuses prot 0 with hit vector 0: {ns1}",
        )

        # S3: a mismatching deny entry falls through to the permit entry behind it.
        await self._program(2, _DENY_NS0)
        await self._program(3, _PERMIT_NS1, ranges=True)
        fall = [await self._read("FALL_P2", _PROT_NS1, 0, 1 << 3)]
        fall.append(await self._read("FALL_P0", 0, _DECERR, None))
        self._mark_step("S3")
        self._log_chk(
            "CHK-INB-NS-FALLTHROUGH",
            f"prot 0b010 falls through deny entry 2 to entry 3 (hit bit 3 set, bit 2 clear); "
            f"prot 0 matches deny entry 2 (hit vector printed, not graded): {fall}",
        )

        # S4: only AxPROT[1] decides.
        await self._program(2, _PERMIT_NS0)
        await self._program(3, 0)
        prot = []
        for p in range(8):
            admitted = not p & _PROT_NS1
            prot.append(
                await self._read(
                    f"PROT{p}", p, 0 if admitted else _DECERR, (1 << 2) if admitted else 0, p
                )
            )
        self._mark_step("S4")
        self._log_chk(
            "CHK-INB-PROT-BITS-IGNORED",
            f"entry 2 allow_ns 0, entry 3 disabled: prot 0,1,4,5 OKAY with hit bit 2 and "
            f"prot 2,3,6,7 DECERR with hit 0: {prot}",
        )

        # S5: each channel decides by its own AxPROT.
        new = 0xC0DE_0000_0000_0000 | 0x5A5A
        word = _WORDS - 1
        addr = _PAGE + 8 * word
        chan = [await self._read("CH_RD_P0", 0, 0, 1 << 2)]
        chan.append(
            await self._sys_in(
                "CH_WR_P2", SmcSysAxiOp.WRITE, addr, _PROT_NS1, _DECERR, hit=0, wdata=new
            )
        )
        await self._sep_word("CH_WR_P2_RB", word, _seed(word))
        chan.append(await self._read("CH_RD_P2", _PROT_NS1, _DECERR, 0))
        chan.append(
            await self._sys_in("CH_WR_P0", SmcSysAxiOp.WRITE, addr, 0, 0, hit=1 << 2, wdata=new)
        )
        await self._sep_word("CH_WR_P0_RB", word, new)
        self._mark_step("S5")
        self._log_chk(
            "CHK-INB-NS-PER-CHANNEL",
            f"read prot 0 and write prot 0 OKAY, read and write prot 0b010 DECERR; refused write "
            f"left the seed and the admitted write landed 0x{new:x} over SEP_IN: {chan}",
        )

        # S6: src_id 0 matches a master presenting AxUSER 0.
        await self._program(2, _PERMIT_NS0)
        s6 = await self._read("SRC0", 0, 0, 1 << 2)
        self._mark_step("S6")
        self._log_chk(
            "CHK-INB-SRCID-WILDCARD-ZERO",
            f"src_id 0 entry matches AxUSER 0 (OKAY, hit bit 2): {s6}; the any-ID half is "
            "unreachable at this bench (not specified, measured) and is not claimed",
        )

        # S7: a non-zero src_id does not match AxUSER 0.
        await self._program(2, _PERMIT_SRC5)
        s7 = await self._read("SRC5", 0, _DECERR, 0)
        self._mark_step("S7")
        self._log_chk(
            "CHK-INB-SRCID-NONZERO-VS-ZERO",
            f"src_id 5 entry does not match AxUSER 0 (DECERR, hit vector 0): {s7}",
        )

        # S8: group_id plays no part in the match.
        await self._program(2, _PERMIT_GRP10)
        s8 = await self._read("GRP10", 0, 0, 1 << 2)
        self._mark_step("S8")
        self._log_chk(
            "CHK-INB-GROUPID-INERT",
            f"group_id 10 entry still admits the read (OKAY, hit bit 2): {s8}",
        )

        # S9: entries 2 and 3 return to their reset words.
        for entry in (2, 3):
            for reg, val in (
                ("FILTER_CONFIG", _RESET_CFG),
                ("START_ADDR", _RESET_START),
                ("END_ADDR", _RESET_END),
            ):
                await self.csr_restore(f"IB{entry}_{reg}", _reg(reg, entry), val)
        self._mark_step("S9")

        await self._page_and_burst_legs()
        watcher.kill()

        axi = [r for r in self._wait_records if "bound_ns" in r]
        bounds = sorted({r["bound_ns"] for r in axi})
        allowed = sum(r["allow_timeout"] for r in axi)
        self._waits.append(
            f"SEP_IN and SYS_IN AXI accesses bound {bounds} ns (read from each item), "
            f"allow_timeout set on {allowed}, {self.accesses} SEP_IN and {self.sys_accesses} "
            "SYS_IN completed; hit watcher is a passive sampler with no wait"
        )
        self._nonvac_fence()

    def _term(self, name: str, count: int, entry: int | None = None) -> None:
        assert count > 0, f"fence term {name} completed with count 0"
        self._terms.append(
            (name if entry is None else f"{name}[{entry}]", count, int(get_sim_time("ps")))
        )

    async def _restore_entry(self, entry: int) -> None:
        for reg, val in (
            ("FILTER_CONFIG", _CONTRACT_CFG),
            ("START_ADDR", _CONTRACT_START),
            ("END_ADDR", _CONTRACT_END),
        ):
            await self.csr_restore(f"IB{entry}_{reg}", _reg(reg, entry), val)

    async def _program_entry(self, entry: int, start: int, end: int, word: int) -> None:
        for reg, val in (("START_ADDR", start), ("END_ADDR", end)):
            await self.csr_write(f"IB{entry}_{reg}", _reg(reg, entry), val, length=8)
        await self._config(entry, word)

    async def _config(self, entry: int, word: int) -> None:
        await self.csr_write(f"IB{entry}_CFG", _reg("FILTER_CONFIG", entry), word, length=8)
        await self.csr_read(
            f"IB{entry}_CFG_RB",
            _reg("FILTER_CONFIG", entry),
            expected=word | _READBACK_BITS,
            length=8,
        )

    async def _range_readback(self, entry: int, start: int, end: int) -> list[str]:
        got = []
        for reg, want in (("START_ADDR", start), ("END_ADDR", end)):
            val = await self.csr_read(f"IB{entry}_{reg}_RB", _reg(reg, entry), want, length=8)
            assert val == want, f"inbound {entry} {reg} reads 0x{val:x}, want 0x{want:x}"
            got.append(f"0x{val:x}")
        return got

    async def _q_burst(
        self, tag: str, op: SmcSysAxiOp, addr: int, resp: int, hit: int | None, words: list[int]
    ) -> str:
        """An AxLEN 3 SYS_IN INCR burst at `addr`; `words` is the write data or the read expectation."""
        packed = _pack(words)
        if op is SmcSysAxiOp.READ:
            return await self._sys_in(
                tag, op, addr, 0, resp, hit=hit, want=packed if resp == 0 else None, beats=4
            )
        return await self._sys_in(tag, op, addr, 0, resp, hit=hit, wdata=packed, beats=4)

    async def _page_and_burst_legs(self) -> None:
        q_seeds = [_q_seed(i) for i in range(2 * _Q_WORDS)]
        q_addrs = [_Q + 8 * i for i in range(_Q_WORDS)] + [_Q_DENY + 8 * i for i in range(_Q_WORDS)]

        # Setup: entries 0, 1 and 4 to 15 are disabled and 4 to 15 hold the reset range; the
        # page words and the entry-15 words are seeded over SEP_IN.
        for entry in (0, 1, *_PAGE_ENTRIES):
            cfg = await self.csr_read(f"IB{entry}_QUIET", _reg("FILTER_CONFIG", entry), length=8)
            assert not cfg & _ENTRY_ENABLED, f"inbound {entry} enabled: 0x{cfg:x}"
        for entry in _PAGE_ENTRIES:
            await self._range_readback(entry, _CONTRACT_START, _CONTRACT_END)
        seeded = [
            (_page(e) + off, _page_seed(e, k))
            for e in _PAGE_ENTRIES
            for k, off in enumerate(_IN_PAGE)
        ] + list(zip(q_addrs, q_seeds))
        for index, (addr, word) in enumerate(seeded):
            await self.csr_write(f"PSEED{index}", addr, word, length=8)
        for index, (addr, word) in enumerate(seeded):
            got = await self.csr_read(f"PSEED{index}_RB", addr, expected=word, length=8)
            assert got == word, f"seed 0x{addr:x}: 0x{got:x}, want 0x{word:x}"
        self._term("SETUP", 2 + 3 * len(_PAGE_ENTRIES) + 2 * len(seeded))

        # Same-page walk and the reads outside the page, one entry at a time.
        widen, hits, outside = [], [], []
        for entry in _PAGE_ENTRIES:
            base = _page(entry)
            await self._program_entry(entry, base + 0x100, base + 0x2FF, _RW_BURST)
            rb = await self._range_readback(entry, base, base + 0xFFF)
            widen.append(f"e{entry}={rb[0]}..{rb[1]}")
            for k, off in enumerate(_IN_PAGE):
                hits.append(
                    await self._sys_in(
                        f"PG{entry}_IN{k}",
                        SmcSysAxiOp.READ,
                        base + off,
                        0,
                        0,
                        hit=1 << entry,
                        want=_page_seed(entry, k),
                    )
                )
            self._term("PAGE-WALK", 2 + len(_IN_PAGE), entry)
            for k, off in enumerate(_OUT_PAGE):
                outside.append(
                    await self._sys_in(
                        f"PG{entry}_OUT{k}", SmcSysAxiOp.READ, base + off, 0, _DECERR, hit=0
                    )
                )
            await self._restore_entry(entry)
            self._term("PAGE-OUTSIDE", len(_OUT_PAGE), entry)
        self._log_chk(
            "CHK-INB-PAGE-WIDEN",
            f"{len(widen)}/{len(_PAGE_ENTRIES)} entries start=page base end=page+0xFFF "
            f"(programmed page+0x100..page+0x2FF, allow_burst 1): {widen}",
        )
        self._log_chk(
            "CHK-INB-PAGE-HIT",
            f"{len(_PAGE_ENTRIES)} entries x {len(_IN_PAGE)} offsets, {len(hits)}/"
            f"{len(_PAGE_ENTRIES) * len(_IN_PAGE)} OKAY with seed, hit==1<<e: {hits}",
        )
        self._log_chk(
            "CHK-INB-PAGE-OUTSIDE",
            f"{len(_PAGE_ENTRIES)} entries x {len(_OUT_PAGE)} addresses, {len(outside)}/"
            f"{len(_PAGE_ENTRIES) * len(_OUT_PAGE)} DECERR, hit==0: {outside}",
        )

        # 8-byte granule write-back with allow_burst 0.
        base = _page(4)
        await self._program_entry(4, base + 0x11, base + 0x13, _ENTRY_ENABLED | _READ_ALLOWED)
        rb = await self._range_readback(4, base + 0x10, base + 0x17)
        await self._restore_entry(4)
        self._term("GRANULE", 2)
        self._log_chk(
            "CHK-INB-GRANULE-WIDEN",
            f"start=P4+0x10 end=P4+0x17 (P4 0x{base:x}, programmed P4+0x11..P4+0x13, "
            f"allow_burst 0): read back {rb[0]}..{rb[1]}",
        )

        # Entry 15 alone over two pages admits INCR bursts of every length.
        for entry in range(_E15):
            cfg = await self.csr_read(f"IB{entry}_OFF", _reg("FILTER_CONFIG", entry), length=8)
            assert not cfg & _ENTRY_ENABLED, f"inbound {entry} enabled before entry 15: 0x{cfg:x}"
        await self._program_entry(_E15, _Q, _Q + 0x1FFF, _RW_BURST)
        permit, beats = [], 0
        for axlen, addr in _BURSTS:
            words = [_burst_word(axlen, b) for b in range(axlen + 1)]
            permit.append(
                await self._sys_in(
                    f"E15_WR{axlen}",
                    SmcSysAxiOp.WRITE,
                    addr,
                    0,
                    0,
                    hit=_E15_HIT,
                    wdata=_pack(words),
                    beats=axlen + 1,
                )
            )
        for axlen, addr in _BURSTS:
            words = [_burst_word(axlen, b) for b in range(axlen + 1)]
            permit.append(
                await self._sys_in(
                    f"E15_RD{axlen}",
                    SmcSysAxiOp.READ,
                    addr,
                    0,
                    0,
                    hit=_E15_HIT,
                    want=_pack(words),
                    beats=axlen + 1,
                )
            )
            beats += axlen + 1
        self._term("E15-PERMIT", 2 * len(_BURSTS))
        self._log_chk(
            "CHK-INB-E15-BURST-PERMIT",
            f"AxLEN 1/3/7/15 writes OKAY hit=0x{_E15_HIT:x}, reads {beats}/{beats} beats == "
            f"written, hit=0x{_E15_HIT:x}: {permit}",
        )

        # allow_burst 0: the burst falls through and is refused, a single beat is admitted.
        await self._config(_E15, _ENTRY_ENABLED | _READ_ALLOWED | _WRITE_ALLOWED)
        noburst = [await self._q_burst("E15_NOBURST", SmcSysAxiOp.READ, _Q, _DECERR, 0, [])]
        noburst.append(
            await self._sys_in(
                "E15_SINGLE", SmcSysAxiOp.READ, _Q, 0, 0, hit=_E15_HIT, want=q_seeds[0]
            )
        )
        self._term("E15-NOBURST", 2)
        self._log_chk(
            "CHK-INB-E15-BURST-DISALLOWED",
            f"burst DECERR hit=0; single beat OKAY hit=0x{_E15_HIT:x}: {noburst}",
        )

        # src_id 5 does not match AxUSER 0; src_id 0 does.
        src5 = _RW_BURST | (5 * (_SRC_ID & -_SRC_ID))
        await self._config(_E15, src5)
        srcid = [await self._q_burst("E15_SRC5", SmcSysAxiOp.READ, _Q, _DECERR, 0, [])]
        await self._config(_E15, _RW_BURST)
        srcid.append(
            await self._q_burst("E15_SRC0", SmcSysAxiOp.READ, _Q, 0, _E15_HIT, q_seeds[:_Q_WORDS])
        )
        self._term("E15-SRCID", 2)
        self._log_chk(
            "CHK-INB-E15-SRCID-MISMATCH",
            f"src_id=5 DECERR hit=0; src_id=0 OKAY hit=0x{_E15_HIT:x} (AxUSER 0): {srcid}",
        )

        # The matching entry's permission bit decides each channel.
        landed = [_burst_word(0x30 + i, i) for i in range(_Q_WORDS)]
        refused = [_burst_word(0x40 + i, i) for i in range(_Q_WORDS)]
        await self._config(_E15, _ENTRY_ENABLED | _WRITE_ALLOWED | _ALLOW_BURST)
        perm = [await self._q_burst("E15_RD_DENY", SmcSysAxiOp.READ, _Q, _DECERR, None, [])]
        perm.append(await self._q_burst("E15_WR_OK", SmcSysAxiOp.WRITE, _Q, 0, None, landed))
        await self._config(_E15, _ENTRY_ENABLED | _READ_ALLOWED | _ALLOW_BURST)
        perm.append(
            await self._q_burst("E15_WR_DENY", SmcSysAxiOp.WRITE, _Q_DENY, _DECERR, None, refused)
        )
        for i in range(_Q_WORDS):
            addr = _Q_DENY + 8 * i
            got = await self.csr_read(
                f"E15_WR_DENY_RB{i}", addr, expected=q_seeds[_Q_WORDS + i], length=8
            )
            assert got == q_seeds[_Q_WORDS + i], f"refused write changed 0x{addr:x} to 0x{got:x}"
        perm.append(await self._q_burst("E15_RD_OK", SmcSysAxiOp.READ, _Q, 0, None, landed))
        self._term("E15-PERM", 4 + _Q_WORDS)
        self._log_chk(
            "CHK-INB-E15-PERM-DENY",
            f"rd-deny DECERR, wr OKAY; wr-deny DECERR words unchanged, rd OKAY with the landed "
            f"words (refused-burst hit vectors measured, not compared): {perm}",
        )

        for entry in _PAGE_ENTRIES:
            await self._restore_entry(entry)
        self._term("RESTORE", 3 * len(_PAGE_ENTRIES))

    def _nonvac_fence(self) -> None:
        ids = tuple(s for s, _ in self._stamps)
        assert ids == _STEPS, f"step ids {ids}, want {_STEPS}"
        times = [t for _, t in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"stamps not increasing: {times}"
        old_marks = self._chk_marks[: len(_CHECKERS)]
        new_marks = self._chk_marks[len(_CHECKERS) :]
        assert tuple(c for c, _ in old_marks) == tuple(c for c, _ in _CHECKERS)
        assert tuple(c for c, _ in new_marks) == tuple(c for c, _ in _NEW_CHECKERS)
        stamp_of = dict(self._stamps)
        for (chk_id, when), (_, step) in zip(old_marks, _CHECKERS):
            assert when >= stamp_of[step], f"{chk_id} printed before step {step}"
        terms = self._fence_terms(times[-1])
        for (chk_id, when), (_, term) in zip(new_marks, _NEW_CHECKERS):
            assert when >= terms[term][2], f"{chk_id} printed before term {term} completed"
        total = self.accesses + self.sys_accesses
        assert total >= _FLOOR, f"{total} accesses, floor {_FLOOR}"
        fence = " < ".join(("EXISTING-S1..S9", *_NEW_TERMS))
        cocotb.log.info(
            "CHK-NONVAC: %s (counts and times per term: EXISTING-S1..S9=%d@%d..%d ps, %s); "
            "existing fence %s; setup %d accesses@%d ps; checker lines %s; accesses %d "
            "(%d SEP_IN + %d SYS_IN) vs floor %d; stamps %s",
            fence,
            len(self._stamps),
            times[0],
            times[-1],
            ", ".join(f"{n}={terms[n][0]}@{terms[n][1]}..{terms[n][2]} ps" for n in _NEW_TERMS),
            _TERMS,
            terms["SETUP"][0],
            terms["SETUP"][2],
            ",".join(c for c, _ in self._chk_marks),
            total,
            self.accesses,
            self.sys_accesses,
            _FLOOR,
            ",".join(f"{s}={t}" for s, t in self._stamps),
        )
        recs = self._wait_records
        axi = [r for r in recs if "bound_ns" in r]
        by_bus = {}
        for r in axi:
            by_bus[r["bus"]] = by_bus.get(r["bus"], 0) + 1
        expired = sum(r["timed_out"] for r in recs)
        assert len(axi) == self.accesses + self.sys_accesses, (
            f"{len(axi)} AXI wait records for {self.accesses + self.sys_accesses} accesses"
        )
        assert expired == 0, f"{expired} bounded waits expired"
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: %d bounded waits, bound/last-state per wait in WAIT-RECORD[1..%d] "
            "(fuse-sense bound %d clk_smc_i; AXI waits per bus %s, bounds in force %s ns, "
            "allow_timeout set on %d), %d expired; last SYS_IN state %s: %s",
            len(recs),
            len(recs),
            _FUSE_BOUND,
            by_bus,
            sorted({r["bound_ns"] for r in axi}),
            sum(r["allow_timeout"] for r in axi),
            expired,
            self._last_sys,
            " | ".join(self._waits),
        )

    def _fence_terms(self, existing_end: int) -> dict[str, tuple[int, int, int]]:
        """Fold the term records into name -> (count, first time, last time) and check order.

        SETUP follows the existing S9, each page entry's walk precedes its outside reads which
        precede the next entry's walk, and the terms complete in the contract order.
        """
        names = [n.split("[")[0] for n, _, _ in self._terms]
        times = [t for _, _, t in self._terms]
        assert all(b > a for a, b in zip(times, times[1:])), f"term times not increasing: {times}"
        walk = ["PAGE-WALK", "PAGE-OUTSIDE"] * len(_PAGE_ENTRIES)
        want = ["SETUP", *walk, *_NEW_TERMS[2:]]
        assert names == want, f"fence terms {names}, want {want}"
        walked = [n for n, _, _ in self._terms if n.startswith("PAGE-")]
        want_walk = [f"{t}[{e}]" for e in _PAGE_ENTRIES for t in ("PAGE-WALK", "PAGE-OUTSIDE")]
        assert walked == want_walk, f"page terms {walked}, want {want_walk}"
        assert times[0] > existing_end, "SETUP did not follow the existing S9"
        folded: dict[str, tuple[int, int, int]] = {}
        for (name, count, when), base in zip(self._terms, names):
            c, first, _ = folded.get(base, (0, when, when))
            folded[base] = (c + count, first, when)
        return folded
