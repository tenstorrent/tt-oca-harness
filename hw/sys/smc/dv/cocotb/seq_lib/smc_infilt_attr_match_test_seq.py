# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Inbound filter attribute match: AxPROT[1] equality, fall-through, src_id and group_id.

Contract SMC_FILTER_21, anchor smc_infilt_attr_match_test.
Allocated scenarios: INFILT-NS-MATCH.S1-S5, INFILT-SRCID-MATCH.S1, S3, S4.
Spec sources: fabric.adoc Non-Secure Bit Filtering, axi_filter index.adoc Match Then Permit,
filter_ctrl.rdl FILTER_CONFIG.

Inbound entries 2 and 3 are programmed over SEP_IN, SYS_IN reads and writes with chosen AxPROT
hit one SPM page, and both entries return to their reset words. Entry 0 and every lock stay
untouched.
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
_RESET_CFG = reg_reset_word(_FILTER_H, "FILTER_CTRL", "FILTER_CONFIG")
_RESET_START = reg_reset_word(_FILTER_H, "FILTER_CTRL", "START_ADDR")
_RESET_END = reg_reset_word(_FILTER_H, "FILTER_CTRL", "END_ADDR")

# Contract words; the read-back adds data_bus_width 3.
_PERMIT_NS0 = 0x0000_0000_0100_0013
_PERMIT_NS1 = 0x0000_0000_0100_0113
_DENY_NS0 = 0x0000_0000_0100_0010
_PERMIT_SRC5 = 0x0000_0000_0105_0013
_PERMIT_GRP10 = 0x0000_0000_01A0_0013
_READBACK_BITS = 0x3000
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


class smc_infilt_attr_match_test_seq(SmcCsrSeq):
    """Program inbound entries 2 and 3, then drive SYS_IN accesses with chosen AxPROT."""

    def __init__(self, name: str = "smc_infilt_attr_match_test_seq") -> None:
        super().__init__(name)
        self.sys_accesses = 0
        self._stamps: list[tuple[str, int]] = []
        self._chk_marks: list[tuple[str, int]] = []
        self._waits: list[str] = []
        self._watch = None

    def _mark_step(self, step_id: str) -> None:
        self._stamps.append((step_id, int(get_sim_time("ps"))))

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
    ) -> str:
        """One SYS_IN access: assert its response, read data and the hit vector of its channel."""
        item = SmcSysAxiItem(f"sys_in_{tag}")
        item.op = op
        item.addr = addr
        item.length = 8
        item.wdata = wdata
        item.prot = prot
        if resp == _DECERR:
            item.allow_error = True
            item.expect_error = True
        else:
            item.expected = want
        self._watch.clear()
        await _OneShot(item, f"sys_in_{tag}_os").start(self.env.sys_in_axi_agent.sequencer)
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
        return (
            f"{name} prot {prot:#05b} 0x{addr:x} resp {item.resp_code} hit 0x{chan['hit']:x} "
            f"isolate {chan['isolate']}"
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
            "unreachable at this bench (SF-024) and is not claimed",
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
        watcher.kill()
        self._mark_step("S9")

        self._waits.append(
            f"SEP_IN and SYS_IN AXI accesses bound {_AXI_BOUND_NS} ns, allow_timeout False, "
            f"{self.accesses} SEP_IN and {self.sys_accesses} SYS_IN completed; hit watcher is a "
            "passive sampler with no wait"
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
