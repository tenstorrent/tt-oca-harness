# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Outbound deny entries answer DECERR under many outstanding denials and a concurrent DMA job.

Contract SMC_FILTER_18, anchor smc_outfilt_deny_concurrency_test.
Allocated scenarios: OUTFILT-DENY-RESPONSE.S1, S5, S6 and S7, OUTFILT-PRIORITY-PERM.S6.
Spec sources: axi_filter index.adoc (Blocked Transactions, Match Then Permit), fabric.adoc
(Outbound Filtering, Configuration Parameters), filter_ctrl.rdl FILTER_CONFIG.

Outbound entries 1..4 are programmed over SEP_IN. JTAG reads and writes that a deny entry
matches answer DECERR on every returned beat, raise no AR, AW or W beat at SYS_OUT and leave
the SYS_OUT words at their sentinel. Forty denied writes stay outstanding together, a DMA job
completes while a denied JTAG write is answered, and an entry reprogrammed from permit to deny
while twelve JTAG writes are in flight yields OKAY responses that landed and then DECERR
responses that did not. Every entry and the DMA configuration are restored at the end.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiGroupItem, SmcSysAxiItem, SmcSysAxiOp
from ocah_axi_vip import AxiTimingProfile

from ._one_shot import _OneShot
from .smc_addr_map import _REPO, reg_field_encode, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_output_fabric_vip_utils import (
    BLOCKED_WRITE_HOLD_CYCLES,
    RESP_DECERR,
    RESP_OKAY,
    RESPONDER_OBS_TIMEOUT_CYCLES,
    check_output_responder_delta,
    hold_output_responder_writes,
    output_responder_counts,
)
from .smc_rdl_regmap import rdl_contract, smc_reg_addr

_FILTER_H = _REPO / "hw" / "ip" / "axi_filter" / "regs" / "gen" / "c" / "filter_ctrl.h"
_SENTINEL = 0x5A5A_5A5A_5A5A_5A5A
_PAYLOAD = 0x1122_3344_5566_7788
_WORD = 8
_FUSE_BOUND = 200_000
_AXI_TIMEOUT_NS = 50_000
_READ_HOLD_CYCLES = 64
_B_HOLD_CYCLES = 64
_INFLIGHT_BOUND = 200
_DMA_POLLS = 50
_DMA_POLL_CYCLES = 20
_FLOOD = 40
_RECONFIG = 12
_ENTRIES = (1, 2, 3, 4)
_SEP_FLOOR = 71
_JTAG_COUNT = 3 + 3 + _FLOOD + 1 + _RECONFIG


def _config(**fields: int) -> int:
    return reg_field_encode(_FILTER_H, "FILTER_CTRL", "FILTER_CONFIG", **fields)


DENY_B1 = _config(entry_enabled=1, allow_burst=1)
DENY_NS1_B1 = _config(entry_enabled=1, allow_ns=1, allow_burst=1)
DENY_B0 = _config(entry_enabled=1)
PERMIT_B1 = _config(read_allowed=1, write_allowed=1, entry_enabled=1, allow_burst=1)
DISABLED = 0

_READ_RANGE = (0x0200_2000, 0x0200_2FFF)
_NS_RANGE = (0x0200_4000, 0x0200_4FFF)
_B0_RANGE = (0x0200_6000, 0x0200_6007)
_B1_RANGE = (0x0200_6000, 0x0200_6FFF)
_FLOOD_RANGE = (0x0200_8000, 0x0200_8FFF)
_RECONFIG_RANGE = (0x0200_C000, 0x0200_CFFF)
_SRC = 0x0200_0000
_DST = 0x0200_A000
_DMA_DENIED = 0x0200_8800
_FLOOD_BASE = 0x0200_8000
_RECONFIG_BASE = 0x0200_C000
_SINGLE_READ = 0x0200_2100
_BURST_READ = 0x0200_2200
_CONTROL_READ = 0x0200_3000
_CONTROL_WORD = 0x0123_4567_89AB_CDEF
_CLASS1 = 0x0200_2400
_CLASS2 = 0x0200_4100
_CLASS3 = 0x0200_6000
_BURST_BEATS = 4
_SEEDS = (
    [_BURST_READ + 8 * i for i in range(_BURST_BEATS)]
    + [_SINGLE_READ, _CLASS1, _CLASS2, _DST, _DMA_DENIED]
    + [_CLASS3 + 8 * i for i in range(_BURST_BEATS)]
    + [_FLOOD_BASE + 8 * k for k in range(_FLOOD)]
    + [_RECONFIG_BASE + 8 * k for k in range(_RECONFIG)]
)

_DMA_NAMES = (
    "CONFIG", "DONE_0", "NEXT_ID_0", "STATUS_0", "DST_ADDRESS_LO", "DST_ADDRESS_HI",
    "SRC_ADDRESS_LO", "SRC_ADDRESS_HI", "LENGTH_LO", "LENGTH_HI", "DST_STRIDE_LO",
    "DST_STRIDE_HI", "SRC_STRIDE_LO", "SRC_STRIDE_HI", "NUM_REPETITIONS_LO",
    "NUM_REPETITIONS_HI",
)  # fmt: skip
_DMA = {name: smc_reg_addr(f"DMA_CTRL_{name}_REG_ADDR") for name in _DMA_NAMES}
_DMA_CONFIG_ENABLED_ND = 1 << 10

STEPS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7")
FENCE_TERMS = (
    ("SEEDED", "S1"),
    ("DENIED_READS", "S2"),
    ("CLASSES", "S3"),
    ("FLOOD_40", "S4"),
    ("DMA_AND_JTAG", "S5"),
    ("RECONFIG_GROUP", "S6"),
    ("CLEANED", "S7"),
)
CHECKERS = (
    ("CHK-OUT-DENY-READ-RRESP", "S2"),
    ("CHK-OUT-DENY-CLASSES", "S3"),
    ("CHK-OUT-DENY-FLOOD", "S4"),
    ("CHK-OUT-DENY-ADMIT-SIMULTANEOUS", "S5"),
    ("CHK-OUT-RECONFIG-OUTSTANDING", "S6"),
)


def _outbound(reg: str, entry: int) -> int:
    return smc_indexed_addr(f"SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_{reg}_BASE_ADDR", entry)


class smc_outfilt_deny_concurrency_test_seq(SmcCsrSeq):
    """Program outbound deny entries and drive denied JTAG traffic and one DMA job."""

    def __init__(self, name: str = "smc_outfilt_deny_concurrency_test_seq") -> None:
        super().__init__(name)
        self.chk_seen: dict[str, str] = {}
        self.jtag_accesses = 0
        self._stamps: list[tuple[str, int]] = []
        self._chk_marks: list[tuple[str, int]] = []
        self._waits: dict[str, list] = {}
        self._beats = {"awvalid": 0, "wvalid": 0, "arvalid": 0}
        self._r_beats: list[int] = []
        self._aw_hs = 0
        self._b_hs = 0
        self._peak = 0
        self._resets: dict[str, int] = {}

    def _mark_step(self, step_id: str) -> None:
        self._stamps.append((step_id, int(get_sim_time("ps"))))

    def _log_chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self._chk_marks.append((chk_id, int(get_sim_time("ps"))))
        self.chk_seen[chk_id] = "printed"

    def _wait(self, name: str, bound: str, last: object) -> None:
        self._waits[name] = [bound, last]

    async def _watch(self) -> None:
        top = cocotb.top
        while True:
            await RisingEdge(top.clk_smc_i)
            await ReadOnly()
            for name in self._beats:
                sig = getattr(top, f"tb_output_axi_{name}")
                assert sig.value.is_resolvable, f"tb_output_axi_{name} is X/Z ({sig.value})"
                self._beats[name] += int(sig.value)
            sample = {}
            for name in ("awvalid", "awready", "bvalid", "bready", "rvalid", "rready", "rresp"):
                sig = getattr(top, f"jtag_axi_{name}")
                assert sig.value.is_resolvable, f"jtag_axi_{name} is X/Z ({sig.value})"
                sample[name] = int(sig.value)
            self._aw_hs += sample["awvalid"] & sample["awready"]
            self._b_hs += sample["bvalid"] & sample["bready"]
            self._peak = max(self._peak, self._aw_hs - self._b_hs)
            if sample["rvalid"] and sample["rready"]:
                self._r_beats.append(sample["rresp"])

    async def _program(self, label: str, entry: int, span: tuple[int, int], config: int) -> None:
        """Disable `entry`, write its range and configuration, and read the configuration back."""
        await self.csr_write(f"{label}_OFF", _outbound("FILTER_CONFIG", entry), DISABLED, _WORD)
        await self.csr_write(f"{label}_START", _outbound("START_ADDR", entry), span[0], _WORD)
        await self.csr_write(f"{label}_END", _outbound("END_ADDR", entry), span[1], _WORD)
        await self.csr_write(f"{label}_CFG", _outbound("FILTER_CONFIG", entry), config, _WORD)
        await self.csr_read(
            f"{label}_CFG_RB",
            _outbound("FILTER_CONFIG", entry),
            expected=config | self._resets["FILTER_CONFIG"],
            length=_WORD,
        )

    def _write_item(
        self, name: str, addr: int, data: int, *, prot: int = 0, beats: int = 1, deny: bool = True
    ) -> SmcSysAxiItem:
        item = SmcSysAxiItem(name)
        item.op, item.addr, item.length, item.beats = SmcSysAxiOp.WRITE, addr, _WORD, beats
        item.prot, item.wdata = prot, data
        item.allow_error = True
        if deny:
            item.expect_error = True
            item.expected_resp = RESP_DECERR
        return item

    async def _jtag(self, item) -> None:
        await _OneShot(item, f"{item.get_name()}_os").start(self.env.jtag_axi_agent.sequencer)
        self.jtag_accesses += 1

    async def _jtag_group(self, name: str, items: list[SmcSysAxiItem]) -> None:
        hold = AxiTimingProfile(b_ready_delay=_B_HOLD_CYCLES)
        group = SmcSysAxiGroupItem(name, items, timing=hold)
        await _OneShot(group, f"{name}_os").start(self.env.jtag_axi_agent.sequencer)
        self.jtag_accesses += len(items)

    async def _hold_reads(self, label: str, reads0: int, arvalid0: int) -> None:
        top = cocotb.top
        self._wait("hold_output_read_count", f"{_READ_HOLD_CYCLES} clk_smc_i", reads0)
        for cycle in range(1, _READ_HOLD_CYCLES + 1):
            await ClockCycles(top.clk_smc_i, 1)
            _w, reads = output_responder_counts()
            assert reads == reads0, f"{label}: read_count advanced to {reads} (was {reads0})"
            assert self._beats["arvalid"] == arvalid0, (
                f"{label}: tb_output_axi_arvalid was 1 {cycle} cycles after the denied read"
            )

    async def _deny_read(self, addr: int, beats: int) -> str:
        """A denied JTAG read: DECERR on every R beat, no AR, read_count unchanged."""
        _w, reads0 = output_responder_counts()
        arvalid0, r0 = self._beats["arvalid"], len(self._r_beats)
        item = SmcSysAxiItem(f"jtag_deny_read_0x{addr:x}")
        item.op, item.addr, item.length, item.beats = SmcSysAxiOp.READ, addr, _WORD, beats
        item.allow_error = item.expect_error = True
        item.expected_resp = RESP_DECERR
        await self._jtag(item)
        assert item.resp_code == RESP_DECERR, (
            f"denied JTAG read at 0x{addr:x} answered resp {item.resp_code}, want {RESP_DECERR}"
        )
        got = self._r_beats[r0:]
        assert got and all(r == RESP_DECERR for r in got), (
            f"denied JTAG read at 0x{addr:x} R beat responses {got}, want all {RESP_DECERR}"
        )
        await self._hold_reads(f"read 0x{addr:x}", reads0, arvalid0)
        return (
            f"0x{addr:x} arlen{beats - 1}=DECERR rbeats{len(got)}(all DECERR) "
            f"rdata0x{item.rdata:x}(printed,not graded) ar0 read_count+0"
        )

    async def _deny_write(self, label: str, addr: int, prot: int, beats: int) -> str:
        """A denied JTAG write: DECERR, no SYS_OUT write beat, sentinels kept."""
        writes0, _r = output_responder_counts()
        beats0 = dict(self._beats)
        data = 0
        for beat in range(beats):
            data |= (0xC0DE_0000_0000_0000 | (beat << 32) | (addr & 0xFFFF)) << (64 * beat)
        item = self._write_item(f"jtag_deny_{label}_0x{addr:x}", addr, data, prot=prot, beats=beats)
        await self._jtag(item)
        assert item.resp_code == RESP_DECERR, (
            f"{label}: denied JTAG write at 0x{addr:x} prot {prot} answered resp "
            f"{item.resp_code}, want {RESP_DECERR}"
        )
        self._wait("hold_output_write_count", f"{BLOCKED_WRITE_HOLD_CYCLES} clk_smc_i", writes0)
        await hold_output_responder_writes(expected_writes=writes0, label=f"{label} 0x{addr:x}")
        for beat in range(beats):
            held = self.cfg.sys_out_mem.read_int(addr + 8 * beat, _WORD)
            assert held == _SENTINEL, f"{label}: 0x{addr + 8 * beat:x} holds 0x{held:x}"
        seen = {n: self._beats[n] - beats0[n] for n in self._beats}
        assert seen["awvalid"] == 0 and seen["wvalid"] == 0, f"{label}: SYS_OUT valids {seen}"
        return f"{label} 0x{addr:x} prot{prot} b{beats}=DECERR sentinel kept aw0 w0"

    async def _dma_with_denied_write(self) -> tuple[str, int]:
        """Submit one DMA descriptor and issue a denied JTAG write before polling DONE."""
        baseline = await self.csr_read("DMA_DONE_BASE", _DMA["DONE_0"])
        await self.csr_write("DMA_CONFIG", _DMA["CONFIG"], _DMA_CONFIG_ENABLED_ND)
        for name, value in (
            ("DST_ADDRESS_LO", _DST & 0xFFFF_FFFF), ("DST_ADDRESS_HI", _DST >> 32),
            ("SRC_ADDRESS_LO", _SRC & 0xFFFF_FFFF), ("SRC_ADDRESS_HI", _SRC >> 32),
            ("LENGTH_LO", _WORD), ("LENGTH_HI", 0),
            ("DST_STRIDE_LO", 0), ("DST_STRIDE_HI", 0),
            ("SRC_STRIDE_LO", 0), ("SRC_STRIDE_HI", 0),
            ("NUM_REPETITIONS_LO", 1), ("NUM_REPETITIONS_HI", 0),
        ):  # fmt: skip
            await self.csr_write(f"DMA_{name}", _DMA[name], value)
        item = self._write_item("jtag_deny_dma_0x8800", _DMA_DENIED, 0xC0DE_0000_0000_8800)
        await self.csr_read("DMA_NEXT_ID", _DMA["NEXT_ID_0"])
        jtag = cocotb.start_soon(self._jtag(item))
        polls = 0
        for polls in range(1, _DMA_POLLS + 1):
            done = await self.csr_read("DMA_DONE_POLL", _DMA["DONE_0"])
            bound = f"{_DMA_POLLS}x{_DMA_POLL_CYCLES} clk_smc_i"
            self._wait("dma_done_poll", bound, f"done={done}")
            if done > baseline:
                break
            await ClockCycles(cocotb.top.clk_smc_i, _DMA_POLL_CYCLES)
        else:
            status = await self.csr_read("DMA_STATUS", _DMA["STATUS_0"])
            raise AssertionError(
                f"DMA to 0x{_DST:x} never completed: DONE stayed at {baseline} over "
                f"{_DMA_POLLS} polls, STATUS 0x{status:x}"
            )
        done_at = int(get_sim_time("ps"))
        await jtag
        jtag_at = int(get_sim_time("ps"))
        assert item.resp_code == RESP_DECERR, (
            f"denied JTAG write at 0x{_DMA_DENIED:x} answered resp {item.resp_code}"
        )
        return (
            f"DONE_0 {baseline}->{done} after {polls} polls (done seen {done_at} ps, jtag "
            f"answered {jtag_at} ps)"
        ), baseline

    async def body(self) -> None:
        responder = self.cfg.sys_out_mem
        assert responder is not None, "SYS_OUT responder not bound"
        top = cocotb.top
        await self.wait_fuse_sense_done()
        for sig in ("tb_fuse_sense_done", "tb_fuse_reset_n", "tb_rst_warm_smc_clk_n"):
            state = getattr(top, sig).value
            assert state.is_resolvable, f"{sig} is X/Z after wait_fuse_sense_done"
            self._wait(f"wait_fuse_sense_done.{sig}", f"{_FUSE_BOUND} clk_smc_i", f"{sig}={state}")
        self._wait("jtag_axi_access", f"{_AXI_TIMEOUT_NS}ns", "none")
        self._wait("sep_in_axi_access", f"{_AXI_TIMEOUT_NS}ns", "none")
        self._wait("group_inflight_poll", f"{_INFLIGHT_BOUND} clk_smc_i", "none")
        self._wait(
            "output_responder_obs", f"{RESPONDER_OBS_TIMEOUT_CYCLES} clk_smc_i", "none"
        )  # fmt: skip
        for reg in ("FILTER_CONFIG", "START_ADDR", "END_ADDR"):
            self._resets[reg] = rdl_contract(f"smc_outbound_filter_ctrl/{reg}").reset_word
        watcher = cocotb.start_soon(self._watch())

        # S1
        for entry in _ENTRIES:
            got = await self.csr_read(
                f"OB{entry}_CFG_RESET", _outbound("FILTER_CONFIG", entry), length=_WORD
            )
            assert got == self._resets["FILTER_CONFIG"], f"entry {entry} reads 0x{got:x} at start"
            assert not got & DENY_B0, f"entry {entry} is enabled at start (0x{got:x})"
        dma_config0 = await self.csr_read("DMA_CONFIG_RESET", _DMA["CONFIG"])
        for addr in _SEEDS:
            responder.write_int(addr, _SENTINEL, _WORD)
        responder.write_int(_SRC, _PAYLOAD, _WORD)
        responder.write_int(_CONTROL_READ, _CONTROL_WORD, _WORD)
        for addr in _SEEDS:
            assert responder.read_int(addr, _WORD) == _SENTINEL, f"sentinel at 0x{addr:x}"
        assert responder.read_int(_SRC, _WORD) == _PAYLOAD, "payload seed"
        self._mark_step("S1")

        # S2
        await self._program("S2", 1, _READ_RANGE, DENY_B1)
        single = await self._deny_read(_SINGLE_READ, 1)
        burst = await self._deny_read(_BURST_READ, _BURST_BEATS)
        _w, reads0 = output_responder_counts()
        arvalid0 = self._beats["arvalid"]
        ctl = SmcSysAxiItem("jtag_control_read_0x3000")
        ctl.op, ctl.addr, ctl.length = SmcSysAxiOp.READ, _CONTROL_READ, _WORD
        ctl.expected = _CONTROL_WORD
        await self._jtag(ctl)
        assert ctl.resp_code == RESP_OKAY, f"control read answered resp {ctl.resp_code}"
        assert ctl.rdata == _CONTROL_WORD, f"control read returned 0x{ctl.rdata:x}"
        await check_output_responder_delta(
            start_writes=_w, start_reads=reads0, write_delta=0, read_delta=1
        )
        _w, reads1 = output_responder_counts()
        assert reads1 == reads0 + 1, f"control read advanced read_count by {reads1 - reads0}"
        assert self._beats["arvalid"] > arvalid0, "no arvalid for the permitted control read"
        self._mark_step("S2")
        self._log_chk(
            "CHK-OUT-DENY-READ-RRESP",
            f"entry 1 deny 0x{DENY_B1:x} over 0x{_READ_RANGE[0]:x}..0x{_READ_RANGE[1]:x}: "
            f"{single}; {burst}; control read 0x{_CONTROL_READ:x} OKAY read_count+1 "
            f"arvalid seen ({self._beats['arvalid'] - arvalid0} cycles)",
        )

        # S3
        c1 = await self._deny_write("class1-permission", _CLASS1, 0, 1)
        await self._program("S3NS", 2, _NS_RANGE, DENY_NS1_B1)
        c2 = await self._deny_write("class2-ns", _CLASS2, 2, 1)
        await self._program("S3B0", 3, _B0_RANGE, DENY_B0)
        await self._program("S3B1", 4, _B1_RANGE, DENY_B1)
        c3 = await self._deny_write("class3-burst", _CLASS3, 0, _BURST_BEATS)
        self._mark_step("S3")
        self._log_chk(
            "CHK-OUT-DENY-CLASSES",
            f"{c1}; entry 2 deny 0x{DENY_NS1_B1:x}: {c2}; entry 3 deny 0x{DENY_B0:x} and entry 4 "
            f"deny 0x{DENY_B1:x}: {c3}",
        )

        # S4
        await self._program("S4", 1, _FLOOD_RANGE, DENY_B1)
        writes0, _r = output_responder_counts()
        items = [
            self._write_item(f"jtag_flood_{k}", _FLOOD_BASE + 8 * k, 0xF100_0000 | k)
            for k in range(_FLOOD)
        ]
        self._peak = self._aw_hs - self._b_hs
        await self._jtag_group("jtag_flood", items)
        codes = [i.resp_code for i in items]
        assert codes == [RESP_DECERR] * _FLOOD, f"flood responses {codes}"
        for k in range(_FLOOD):
            held = responder.read_int(_FLOOD_BASE + 8 * k, _WORD)
            assert held == _SENTINEL, f"flood word {k} holds 0x{held:x}"
        writes1, _r = output_responder_counts()
        assert writes1 == writes0, f"flood advanced write_count {writes0}->{writes1}"
        peak = self._peak
        self._mark_step("S4")
        self._log_chk(
            "CHK-OUT-DENY-FLOOD",
            f"{_FLOOD} denied writes over 0x{_FLOOD_RANGE[0]:x}..0x{_FLOOD_RANGE[1]:x} under "
            f"b_ready_delay {_B_HOLD_CYCLES}: {codes.count(RESP_DECERR)} DECERR, {_FLOOD} "
            f"sentinels kept, write_count+0, peak (AW - B handshakes) on jtag_axi {peak} "
            f"(printed)",
        )

        # S5
        dma_text, _base = await self._dma_with_denied_write()
        landed = responder.read_int(_DST, _WORD)
        assert landed == _PAYLOAD, f"0x{_DST:x} holds 0x{landed:x}, want 0x{_PAYLOAD:x}"
        held = responder.read_int(_DMA_DENIED, _WORD)
        assert held == _SENTINEL, f"denied word 0x{_DMA_DENIED:x} holds 0x{held:x}"
        self._mark_step("S5")
        self._log_chk(
            "CHK-OUT-DENY-ADMIT-SIMULTANEOUS",
            f"denied JTAG write at 0x{_DMA_DENIED:x} DECERR sentinel kept; DMA 0x{_SRC:x} -> "
            f"0x{_DST:x}: {dma_text}; 0x{_DST:x} holds 0x{landed:x}",
        )

        # S6
        await self._program("S6", 1, _RECONFIG_RANGE, PERMIT_B1)
        writes0, _r = output_responder_counts()
        words = [0xE000_0000_0000_0000 | k for k in range(_RECONFIG)]
        items = [
            self._write_item(f"jtag_reconfig_{k}", _RECONFIG_BASE + 8 * k, words[k], deny=False)
            for k in range(_RECONFIG)
        ]
        aw0 = self._aw_hs
        group = cocotb.start_soon(self._jtag_group("jtag_reconfig", items))
        waited = 0
        while self._aw_hs == aw0 and waited < _INFLIGHT_BOUND:
            await ClockCycles(top.clk_smc_i, 1)
            waited += 1
        self._wait("group_inflight_poll", f"{_INFLIGHT_BOUND} clk_smc_i", f"aw+{self._aw_hs - aw0}")
        assert self._aw_hs > aw0, f"no JTAG AW handshake within {_INFLIGHT_BOUND} cycles"
        b_at_write = self._b_hs
        await self.csr_write("S6_RECONFIG_CFG", _outbound("FILTER_CONFIG", 1), DENY_B1, _WORD)
        await group
        codes = [i.resp_code for i in items]
        assert all(c in (RESP_OKAY, RESP_DECERR) for c in codes), f"reconfig responses {codes}"
        n_ok = codes.count(RESP_OKAY)
        assert codes == [RESP_OKAY] * n_ok + [RESP_DECERR] * (_RECONFIG - n_ok), (
            f"reconfig responses in issue order {codes}: more than one OKAY-to-DECERR transition"
        )
        await check_output_responder_delta(
            start_writes=writes0, start_reads=0, write_delta=n_ok, read_delta=0
        )
        for k, code in enumerate(codes):
            got = responder.read_int(_RECONFIG_BASE + 8 * k, _WORD)
            want = words[k] if code == RESP_OKAY else _SENTINEL
            assert got == want, f"write {k} resp {code}: 0x{got:x} landed, want 0x{want:x}"
        await self.csr_read(
            "S6_RECONFIG_CFG_RB",
            _outbound("FILTER_CONFIG", 1),
            expected=DENY_B1 | self._resets["FILTER_CONFIG"],
            length=_WORD,
        )
        self._mark_step("S6")
        self._log_chk(
            "CHK-OUT-RECONFIG-OUTSTANDING",
            f"entry 1 permit 0x{PERMIT_B1:x} -> deny 0x{DENY_B1:x} with {_RECONFIG} writes in "
            f"flight (B handshakes before the SEP_IN write {b_at_write}); responses "
            f"{''.join('O' if c == RESP_OKAY else 'D' for c in codes)}: {n_ok} OKAY landed, "
            f"{_RECONFIG - n_ok} DECERR kept sentinel, one transition at most "
            f"(SF-009 observe-only: transition index {n_ok})",
        )

        # S7
        restored = []
        for entry in _ENTRIES:
            for reg, word in (
                ("FILTER_CONFIG", self._resets["FILTER_CONFIG"]),
                ("START_ADDR", self._resets["START_ADDR"]),
                ("END_ADDR", self._resets["END_ADDR"]),
            ):
                addr = _outbound(reg, entry)
                await self.csr_write(f"OB{entry}_{reg}_RESTORE", addr, word, _WORD)
            got = await self.csr_read(
                f"OB{entry}_CFG_RESTORE_RB",
                _outbound("FILTER_CONFIG", entry),
                expected=self._resets["FILTER_CONFIG"],
                length=_WORD,
            )
            restored.append(f"OB{entry}.FILTER_CONFIG=0x{got:x}")
        await self.csr_write("DMA_CONFIG_RESTORE", _DMA["CONFIG"], dma_config0)
        got = await self.csr_read("DMA_CONFIG_RESTORE_RB", _DMA["CONFIG"], expected=dma_config0)
        restored.append(f"DMA.CONFIG=0x{got:x}")
        self._mark_step("S7")
        watcher.cancel()
        self._finish(restored)

    def _finish(self, restored: list[str]) -> None:
        assert self.accesses >= _SEP_FLOOR, f"{self.accesses} SEP_IN accesses, floor {_SEP_FLOOR}"
        assert self.jtag_accesses == _JTAG_COUNT, f"{self.jtag_accesses} JTAG accesses"
        waits = " ".join(f"{n}={b} last={s}" for n, (b, s) in self._waits.items())
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: %d bounded waits: %s; expiry raises AssertionError",
            len(self._waits),
            waits,
        )
        self.chk_seen["CHK-TIMEOUT-PATHS"] = "printed"
        steps = tuple(s for s, _ in self._stamps)
        assert steps == STEPS, f"step order {steps}"
        times = [t for _, t in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"stamps not increasing {times}"
        seen = [c for c, _ in self._chk_marks]
        assert seen == [c for c, _ in CHECKERS], f"checker lines out of order {seen}"
        stamp_of = dict(self._stamps)
        for (chk_id, when), (_c, step) in zip(self._chk_marks, CHECKERS):
            assert when >= stamp_of[step], f"{chk_id} printed before step {step}"
        fence_times = [stamp_of[s] for _, s in FENCE_TERMS]
        assert all(b > a for a, b in zip(fence_times, fence_times[1:])), "fence terms out of order"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; stamps %s; %d SEP_IN accesses "
            "(floor %d) and %d JTAG accesses; restored %s",
            " < ".join(t for t, _ in FENCE_TERMS),
            ",".join(seen),
            ",".join(f"{s}={t}" for s, t in self._stamps),
            self.accesses,
            _SEP_FLOOR,
            self.jtag_accesses,
            " ".join(restored),
        )
        self.chk_seen["CHK-NONVAC"] = "ordered"
