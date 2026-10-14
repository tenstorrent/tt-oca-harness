# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Inbound filter address-range, enable, 56-bit, span, START = END and burst match.

Spec sources: fabric.adoc Filtering and Protection, axi_filter index.adoc Match Then Permit and
Address Range Granule, filter_ctrl.rdl FILTER_CONFIG.

Inbound entries 2 and 3 are programmed over SEP_IN, SYS_IN 8-byte accesses around their ranges
hit the SPM, one SMC register is read through its global alias, and both entries return to
their reset words. Entry 0 and every lock stay untouched.
"""

from __future__ import annotations

import sys

import cocotb
from cocotb.triggers import ReadOnly, RisingEdge
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from ._one_shot import _OneShot
from .smc_addr_map import (
    _REPO,
    GLOBAL_BASE_RESET,
    LOCAL_BASE_RESET,
    _field_mask,
    reg_reset_word,
    smc_addr,
    smc_indexed_addr,
)
from .smc_csr_seq_utils import SmcCsrSeq

_SMC_REG_PY = _REPO / "hw" / "sys" / "smc" / "regs" / "gen" / "py"
if str(_SMC_REG_PY) not in sys.path:
    sys.path.insert(0, str(_SMC_REG_PY))

from smc_reg import CHIP_CONFIG_VERSION_LO_REG_DEFAULT  # noqa: E402

_FILTER_H = _REPO / "hw" / "ip" / "axi_filter" / "regs" / "gen" / "c" / "filter_ctrl.h"
_ENTRY_ENABLED = _field_mask(_FILTER_H, "FILTER_CTRL__FILTER_CONFIG__ENTRY_ENABLED_bm")
_RESET_CFG = reg_reset_word(_FILTER_H, "FILTER_CTRL", "FILTER_CONFIG")
_RESET_START = reg_reset_word(_FILTER_H, "FILTER_CTRL", "START_ADDR")
_RESET_END = reg_reset_word(_FILTER_H, "FILTER_CTRL", "END_ADDR")

# Register words; the read-back adds data_bus_width 3.
_PERMIT_B1 = 0x0000_0000_0100_0013
_PERMIT_B0 = 0x0000_0000_0000_0013
_DISABLED_B1 = 0x0000_0000_0100_0003
_READBACK_BITS = _RESET_CFG
_P0 = smc_addr("SMC_TOP_SPM_MEMORY_BASE_ADDR") + 0x4_0000
_VERSION_ALIAS = GLOBAL_BASE_RESET + (
    smc_addr("SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_VERSION_LO_BASE_ADDR") - LOCAL_BASE_RESET
)
_HIGH_LOW_ADDR = 0x0000_C006_5800
_HIGH_ADDR = 0x00AB_C006_5800
_DECERR = 3
_AXI_BOUND_NS = 50_000
_FUSE_BOUND = 200_000
_FLOOR = 96
_PROBE_OFFSETS = (
    0x0FF8, 0x1800, 0x2000, 0x3038, 0x3040, 0x3048, 0x7FF8, 0x8000, 0x9FF8, 0xAFF8,
    0xB000, 0xBFF8, 0xC000, 0xCFF8, 0xD000, 0xE000, 0xE008,
)  # fmt: skip
_STEPS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9")
_TERMS = "SEEDED<C1_C2<C3<C4<C5<C6<C7<C8<CLEANED"
_CHECKERS = (
    ("CHK-INB-ADDR-GRANULE", "S2"),
    ("CHK-INB-DISABLED-NO-MATCH", "S3"),
    ("CHK-INB-ADDR-HIGH-BITS-GLOBAL", "S4"),
    ("CHK-INB-SPAN-WHOLE", "S5"),
    ("CHK-INB-START-EQ-END", "S6"),
    ("CHK-INB-BURST0-SINGLE-ONLY", "S7"),
    ("CHK-INB-BURST-FALLTHROUGH", "S8"),
)


def _seed(offset: int) -> int:
    return 0xA11C_0000_0000_0000 | (offset << 16) | 0x5A5A


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


class smc_infilt_addr_burst_match_test_seq(SmcCsrSeq):
    """Program inbound entries 2 and 3, then drive SYS_IN reads around their ranges."""

    def __init__(self, name: str = "smc_infilt_addr_burst_match_test_seq") -> None:
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

    async def _read(
        self,
        tag: str,
        addr: int,
        resp: int | None,
        hit: int | None,
        *,
        want: int | None = None,
        length: int = 8,
        beats: int = 1,
    ) -> str:
        """One SYS_IN read: assert response, data and hit vector; resp None only reports."""
        item = SmcSysAxiItem(f"sys_in_{tag}")
        item.op = SmcSysAxiOp.READ
        item.addr = addr
        item.length = length
        item.beats = beats
        if resp == _DECERR:
            item.allow_error = True
            item.expect_error = True
        elif resp is None:
            item.allow_error = True
        else:
            item.expected = want
        self._watch.clear()
        await _OneShot(item, f"sys_in_{tag}_os").start(self.env.sys_in_axi_agent.sequencer)
        self.sys_accesses += 1
        chan = self._watch.read
        assert self._watch.unresolved == 0, f"{tag}: X/Z on a SYS_IN valid or filter probe"
        assert chan["cycles"] > 0, f"{tag}: no valid cycle sampled"
        if resp is not None:
            assert item.resp_code == resp, f"{tag}: resp {item.resp_code}, want {resp}"
        if resp == 0:
            assert item.rdata == want, f"{tag}: rdata 0x{item.rdata:x}, want 0x{want:x}"
        if hit is not None:
            assert chan["hit"] == hit, (
                f"{tag}: hit vector 0x{chan['hit']:x}, want 0x{hit:x}; isolate {chan['isolate']} "
                f"over {chan['cycles']} valid cycles"
            )
        return (
            f"read 0x{addr:x} beats {beats} resp {item.resp_code} hit 0x{chan['hit']:x} "
            f"isolate {chan['isolate']}"
        )

    async def _probe_read(self, tag: str, offset: int, resp: int, hit: int) -> str:
        want = _seed(offset) if resp == 0 else None
        return await self._read(tag, _P0 + offset, resp, hit, want=want)

    async def _program(
        self, entry: int, word: int, start: int | None = None, end: int | None = None
    ) -> dict[str, int]:
        """Program one entry, the word first so its allow_burst governs the range write.

        The range read-backs are returned, not compared.
        """
        ranges = (("START_ADDR", start), ("END_ADDR", end)) if start is not None else ()
        await self.csr_write(f"IB{entry}_CFG", _reg("FILTER_CONFIG", entry), word, length=8)
        await self.csr_read(
            f"IB{entry}_CFG_RB",
            _reg("FILTER_CONFIG", entry),
            expected=word | _READBACK_BITS,
            length=8,
        )
        for reg, val in ranges:
            await self.csr_write(f"IB{entry}_{reg}", _reg(reg, entry), val, length=8)
        return {
            reg: await self.csr_read(f"IB{entry}_{reg}_RB", _reg(reg, entry), length=8)
            for reg, _ in ranges
        }

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

        # S1: entries 2 and 3 start disabled; every probe word is seeded over SEP_IN.
        for entry in (2, 3):
            cfg = await self.csr_read(f"IB{entry}_QUIET", _reg("FILTER_CONFIG", entry), length=8)
            assert not cfg & _ENTRY_ENABLED, f"inbound {entry} enabled: 0x{cfg:x}"
            for reg, want in (("START_ADDR", _RESET_START), ("END_ADDR", _RESET_END)):
                await self.csr_read(f"IB{entry}_{reg}_QUIET", _reg(reg, entry), want, length=8)
        for off in _PROBE_OFFSETS:
            await self.csr_write(f"SEED_{off:X}", _P0 + off, _seed(off), length=8)
        for off in _PROBE_OFFSETS:
            await self.csr_read(f"SEED_{off:X}_RB", _P0 + off, expected=_seed(off), length=8)
        self._mark_step("S1")

        # S2: 4 KiB granule with allow_burst 1, 8-byte granule with allow_burst 0.
        await self._program(2, _PERMIT_B1, _P0 + 0x1000, _P0 + 0x1FFF)
        c1 = [
            await self._probe_read("C1_IN", 0x1800, 0, 1 << 2),
            await self._probe_read("C1_BELOW", 0x0FF8, _DECERR, 0),
            await self._probe_read("C1_ABOVE", 0x2000, _DECERR, 0),
        ]
        c2_rb = await self._program(2, _PERMIT_B0, _P0 + 0x3040, _P0 + 0x3047)
        c2 = [
            await self._probe_read("C2_IN", 0x3040, 0, 1 << 2),
            await self._probe_read("C2_BELOW", 0x3038, _DECERR, 0),
            await self._probe_read("C2_ABOVE", 0x3048, _DECERR, 0),
        ]
        self._mark_step("S2")
        self._log_chk(
            "CHK-INB-ADDR-GRANULE",
            f"allow_burst 1 over a 4 KiB granule admits the inside read (seeded word, hit bit 2) "
            f"and refuses one granule below and above with hit 0: {c1}; allow_burst 0 over an "
            f"8-byte granule holds the same: {c2}; "
            f"range read-backs START 0x{c2_rb['START_ADDR']:x} END 0x{c2_rb['END_ADDR']:x} "
            "(printed, not compared)",
        )

        # S3: entry_enabled clear removes the match.
        await self._program(2, _DISABLED_B1, _P0 + 0x1000, _P0 + 0x1FFF)
        c3 = await self._probe_read("C3", 0x1800, _DECERR, 0)
        self._mark_step("S3")
        self._log_chk(
            "CHK-INB-DISABLED-NO-MATCH",
            f"entry_enabled clear over the admitting range answers DECERR with hit 0: {c3}",
        )

        # S4: the global alias of an SMC register and a 56-bit range.
        await self._program(2, _PERMIT_B1, 0x4000_2000, 0x4000_2FFF)
        ver = await self._read(
            "C4_VERSION",
            _VERSION_ALIAS,
            0,
            1 << 2,
            want=CHIP_CONFIG_VERSION_LO_REG_DEFAULT,
            length=4,
        )
        await self._program(2, _PERMIT_B1, 0x00AB_C006_5000, 0x00AB_C006_5FFF)
        mon = self.env.output_axi_monitor
        mon.allow_slverr = True
        mon.allow_decerr = True
        high = await self._read("C4_HIGH_HIT", _HIGH_ADDR, None, 1 << 2)
        mon.allow_slverr = False
        mon.allow_decerr = False
        low = await self._read("C4_HIGH_DIFF", _HIGH_LOW_ADDR, _DECERR, 0)
        self._mark_step("S4")
        self._log_chk(
            "CHK-INB-ADDR-HIGH-BITS-GLOBAL",
            f"VERSION_LO through alias 0x{_VERSION_ALIAS:x} reads 0x"
            f"{CHIP_CONFIG_VERSION_LO_REG_DEFAULT:x}: {ver}; 56-bit entry hits bit 2 at "
            f"0x{_HIGH_ADDR:x} (downstream response printed, not graded): {high}; bits [55:32] "
            f"differing give hit 0 and DECERR: {low}",
        )

        # S5: a three-granule span.
        await self._program(2, _PERMIT_B1, _P0 + 0x8000, _P0 + 0xAFFF)
        inside = [
            await self._probe_read(f"C5_IN{off:X}", off, 0, 1 << 2)
            for off in (0x8000, 0x9FF8, 0xAFF8)
        ]
        outside = [
            await self._probe_read(f"C5_OUT{off:X}", off, _DECERR, 0) for off in (0x7FF8, 0xB000)
        ]
        self._mark_step("S5")
        self._log_chk(
            "CHK-INB-SPAN-WHOLE",
            f"the three reads inside the three-granule span are OKAY with hit bit 2: {inside}; "
            f"the two reads outside answer DECERR with hit 0: {outside}",
        )

        # S6: START_ADDR = END_ADDR admits the whole granule.
        point = _P0 + 0xC123
        await self._program(2, _PERMIT_B1, point, point)
        s6_in = [
            await self._probe_read(f"C6_IN{off:X}", off, 0, 1 << 2) for off in (0xC000, 0xCFF8)
        ]
        s6_out = [
            await self._probe_read(f"C6_OUT{off:X}", off, _DECERR, 0) for off in (0xBFF8, 0xD000)
        ]
        self._mark_step("S6")
        self._log_chk(
            "CHK-INB-START-EQ-END",
            f"START = END = 0x{point:x} admits the 4 KiB granule edges: {s6_in}; the neighbouring "
            f"granules answer DECERR with hit 0: {s6_out}",
        )

        # S7: allow_burst 0 admits a single beat and refuses a 2-beat burst.
        await self._program(2, _PERMIT_B0, _P0 + 0xE000, _P0 + 0xE007)
        single = await self._probe_read("C7_SINGLE", 0xE000, 0, 1 << 2)
        burst_data = _seed(0xE000) | (_seed(0xE008) << 64)
        burst = await self._read("C7_BURST", _P0 + 0xE000, _DECERR, 0, beats=2)
        self._mark_step("S7")
        self._log_chk(
            "CHK-INB-BURST0-SINGLE-ONLY",
            f"allow_burst 0 admits the single-beat read (hit bit 2): {single}; the 2-beat INCR "
            f"read answers DECERR with hit 0: {burst}",
        )

        # S8: entry 3 with allow_burst 1 admits the burst entry 2 refuses.
        await self._program(3, _PERMIT_B1, _P0 + 0xE000, _P0 + 0xEFFF)
        fall = await self._read("C8_BURST", _P0 + 0xE000, 0, 1 << 3, want=burst_data, beats=2)
        self._mark_step("S8")
        self._log_chk(
            "CHK-INB-BURST-FALLTHROUGH",
            f"the 2-beat read refused by entry 2 is admitted by entry 3 with the 16 seeded bytes "
            f"0x{burst_data:x}, hit bit 3 set and bit 2 clear: {fall}",
        )

        # S9: entries 2 and 3 return to their reset words.
        for entry in (2, 3):
            for reg, val in (
                ("FILTER_CONFIG", _RESET_CFG),
                ("START_ADDR", _RESET_START),
                ("END_ADDR", _RESET_END),
            ):
                await self.csr_restore(f"IB{entry}_{reg}", _reg(reg, entry), val)
            await self.csr_read(
                f"IB{entry}_CFG_FINAL", _reg("FILTER_CONFIG", entry), _RESET_CFG, length=8
            )
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
