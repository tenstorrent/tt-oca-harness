# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Write responses of the SMC map's past-extent, gap and split-burst addresses over SEP_IN.

Spec sources: memmap.adoc "Address Space Organization" (a write burst to a register unit is
split into single-beat writes; its response is the last beat's when that beat answers SLVERR
or DECERR, else SLVERR when an earlier beat answered an error, else OKAY), the generated
memory_map.adoc component rows (ocah_past_extent_resp and ocah_hole_resp of every unit) and
smc_memory_map.rdl ocah_gap_resp.

CHK-BURST-MERGE-RESP grades the merged response of two-beat writes whose beat answers are
declared: the last beat past the last register of smc_cpu_ctrl (SLVERR, from the block) and
of smc_reset_unit (DECERR, from the crossbar), a WRAP burst whose first beat is past the
last register of smc_reset_unit and whose last beat is that register, and a burst inside
scratch_cold. The beat answers are the per-beat RRESP of the same burst read, or the
single-beat responses where the burst is not split, and must equal the declared codes. The OBS-BRESP and OBS-BURST tables record every declared
past-extent and gap address and every other two-beat case beside the declared codes.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

import cocotb
from cocotb.triggers import RisingEdge
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import (
    _COMPONENT_ROWS,
    LOCAL_BASE_RESET,
    REGION_SIZE_RESET,
    cpu_ctrl_u32,
    generated_past_extent_resp,
    reset_unit_u32,
    smc_addr,
    smc_indexed_addr,
)
from .smc_axi_illegal_encoding_inject_test_seq import split_bresp
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_sep_in_resp_sampler import SepInRespSampler

_RESP_NAMES = {0: "OKAY", 1: "EXOKAY", 2: "SLVERR", 3: "DECERR"}
_RESP_CODES = {v: k for k, v in _RESP_NAMES.items()}
WRITE_PATTERN = 0xA5A55A5A
WRITE_PATTERN64 = 0x5A5A_A5A5_A5A5_5A5A
FUSE_WAIT_BOUND_SMC_CYCLES = 200_000
AXI_TIMEOUT_NS = 50_000
BURST_INCR = 1
BURST_WRAP = 2

_INTERNAL_XBAR = {
    "smc_base_config",
    "smc_alias_remap_wrap",
    "smc_mmode_remap_wrap",
    "smc_xvisor_remap_wrap",
    "smc_inbound_filter_ctrl_wrap",
    "smc_outbound_filter_ctrl_wrap",
    "smc_mailbox",
    "dfx_ctrl",
}
_PERIPH_XBAR = {
    "smc_reset_unit",
    "smc_misc_wrap",
    "gpio_intf_wrap",
    "smc_avsbus_controller",
    "smc_i2c_wrap",
    "smc_uart_wrap",
    "smc_efuse_map",
    "efuse_interface_ctrl",
    "smc_telemetry_receiver_wrap",
    "smc_system_timer_octs",
    "dtp_ctrl_reg",
    "oca_i3c_wrap",
    "smc_external",
}

# Offsets from LOCAL_BASE of the first and last 8-byte word of every address range between
# unit apertures that the inbound port reaches at the reset REGION_SIZE.
_UNIT_GAPS = (
    ("gap_after_debug_module", 0x1868, 0x1FF8, "local"),
    ("gap_C000", 0xC000, 0xFFF8, "local"),
    ("gap_17000", 0x1_7000, 0x1_7FF8, "internal"),
    ("gap_38300", 0x3_8300, 0x3_8FF8, "local"),
    ("gap_after_cla", 0x16_4000, 0x3F_FFF8, "local"),
    ("gap_after_external", 0x40_6548, 0xFF_FFF8, "local"),
)

# (unit, point, offset32, offset64) of the sub-block gaps whose hole row declares an error.
_SUBBLOCK_GAPS = (
    ("smc_misc_wrap", "GAP1_FIRST", 0x2820, 0x2820),
    ("smc_misc_wrap", "GAP1_LAST", 0x287C, 0x2878),
    ("smc_misc_wrap", "GAP2_FIRST", 0x28A0, 0x28A0),
    ("smc_misc_wrap", "GAP2_LAST", 0x28FC, 0x28F8),
    ("smc_misc_wrap", "GAP3_FIRST", 0x2910, 0x2910),
    ("smc_misc_wrap", "GAP3_LAST", 0x29FC, 0x29F8),
    ("smc_i2c_wrap", "GAP_I2C0_FIRST", 0x5084, 0x5088),
    ("smc_i2c_wrap", "GAP_I2C0_LAST", 0x51FC, 0x51F8),
    ("smc_i2c_wrap", "GAP_I2C1_FIRST", 0x5284, 0x5288),
    ("smc_i2c_wrap", "GAP_I2C1_LAST", 0x53FC, 0x53F8),
    ("smc_i2c_wrap", "GAP_I2C2_FIRST", 0x5484, 0x5488),
    ("smc_i2c_wrap", "GAP_I2C2_LAST", 0x5DFC, 0x5DF8),
    ("smc_uart_wrap", "W0_GAP_AFTER_CTRL", 0x6004, 0x6008),
    ("smc_uart_wrap", "W0_PAST_UART", 0x6140, 0x6140),
    ("smc_uart_wrap", "W0_PAST_LOG_ENGINE", 0x6280, 0x6280),
    ("smc_uart_wrap", "W0_TOP", 0x63FC, 0x63F8),
    ("smc_uart_wrap", "W3_TOP", 0x6FFC, 0x6FF8),
    ("smc_mailbox", "HOLE_OUT0_FIRST", 0x1_8050, 0x1_8050),
    ("smc_mailbox", "HOLE_OUT0_LAST", 0x1_87FC, 0x1_87F8),
)

_CHECKERS = (
    "CHK-OBS-BRESP-TABLE",
    "CHK-OBS-BURST-TABLE",
    "CHK-BURST-MERGE-RESP",
    "CHK-BURST-LIVE-UNCHANGED",
    "CHK-TIMEOUT-PATHS",
)


def _rname(code) -> str:
    return _RESP_NAMES.get(code, str(code))


def _rdl_gap_resp() -> dict:
    """``ocah_gap_resp`` of the SMC memory-map annotations as the generated map's response dict shape."""
    text = (
        Path(__file__).resolve().parents[3] / "regs" / "include" / "smc_memory_map.rdl"
    ).read_text()
    for name, value in re.findall(r"^`define (\w+) (.+)$", text, re.M):
        text = text.replace(f"`{name}", value)
    m = re.search(
        r"ocah_gap_resp\s*=\s*ocah_resp'\{rresp:\s*ocah_resp_e::(\w+),\s*"
        r"rdata:\s*(0x[0-9A-Fa-f]+),\s*bresp:\s*ocah_resp_e::(\w+)\}",
        text,
    )
    assert m, "ocah_gap_resp not found in smc_memory_map.rdl"
    return {"rresp": m.group(1), "rdata": int(m.group(2), 16), "bresp": m.group(3)}


def _row(unit: str) -> dict:
    for row in _COMPONENT_ROWS:
        if row["key"].rsplit(":", 1)[-1] == unit:
            return row
    raise KeyError(unit)


def _hole(unit: str, kind: str) -> dict:
    for name, resp in _row(unit)["hole_responses"]:
        if name == kind:
            return resp
    raise KeyError(f"{unit}: no '{kind}' hole row")


def _xbar(unit: str) -> str:
    if unit in _INTERNAL_XBAR:
        return "internal"
    if unit in _PERIPH_XBAR:
        return "periph"
    return "local"


class _Probe:
    def __init__(self, unit, point, addr, width, resp, xbar, note=""):
        self.unit = unit
        self.point = point
        self.addr = addr
        self.width = width
        self.resp = resp
        self.xbar = xbar
        self.note = note or "-"


def build_probes() -> list[_Probe]:
    probes: list[_Probe] = []
    reach_end = LOCAL_BASE_RESET + REGION_SIZE_RESET
    for row in _COMPONENT_ROWS:
        unit = row["key"].rsplit(":", 1)[-1]
        xbar = _xbar(unit)
        note = "region_gated_at_reset" if row["base"] >= reach_end else ""
        past = row["past_response"]
        if past is not None:
            first_past = row["base"] + row["occupied_size"]
            top = row["end"] & ~0x7
            probes.append(_Probe(unit, "PAST", first_past, 32, past, xbar, note))
            probes.append(_Probe(unit, "PAST", (first_past + 7) & ~0x7, 64, past, xbar, note))
            probes.append(_Probe(unit, "TOP", top, 32, past, xbar, note))
            probes.append(_Probe(unit, "TOP", top, 64, past, xbar, note))
        for kind, hole in row["hole_responses"]:
            if kind == "" and hole["bresp"] in ("SLVERR", "DECERR"):
                top = row["end"] & ~0x7
                probes.append(_Probe(unit, "HOLE_FIRST", row["base"], 32, hole, xbar, note))
                probes.append(_Probe(unit, "HOLE_FIRST", row["base"], 64, hole, xbar, note))
                probes.append(_Probe(unit, "HOLE_LAST", top, 32, hole, xbar, note))
                probes.append(_Probe(unit, "HOLE_LAST", top, 64, hole, xbar, note))
    for unit, point, off32, off64 in _SUBBLOCK_GAPS:
        hole = _hole(unit, "between sub-blocks")
        probes.append(_Probe(unit, point, LOCAL_BASE_RESET + off32, 32, hole, _xbar(unit)))
        probes.append(_Probe(unit, point, LOCAL_BASE_RESET + off64, 64, hole, _xbar(unit)))
    gap = _rdl_gap_resp()
    for name, first, last, xbar in _UNIT_GAPS:
        for point, off in (("FIRST", first), ("LAST", last)):
            for width in (32, 64):
                probes.append(_Probe(name, point, LOCAL_BASE_RESET + off, width, gap, xbar))
    return probes


class smc_bresp_evidence_test_seq(SmcCsrSeq):
    """Write every declared past-extent and gap address over SEP_IN and record the responses."""

    def __init__(self, name: str = "smc_bresp_evidence_test_seq") -> None:
        super().__init__(name)
        self.chk_seen: set[str] = set()
        self.fuse_state = "not waited"
        self.obs_bresp = 0
        self.obs_burst = 0
        self.bresp_tally: Counter = Counter()
        self.live_results: list[str] = []

    def _log_chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self.chk_seen.add(chk_id)

    async def _rd(self, label: str, addr: int, width: int) -> tuple[int, int]:
        item = SmcSysAxiItem(f"rd_{label}")
        item.op = SmcSysAxiOp.READ
        item.addr = addr
        item.length = width // 8
        item.allow_error = True
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        assert item.resp_code is not None, f"{label} @ 0x{addr:08x}: no rresp recorded"
        mask = (1 << width) - 1
        return item.resp_code, item.rdata & mask

    async def _wr(
        self, label: str, addr: int, width: int, data: int, beats: int = 1, burst: int = BURST_INCR
    ) -> int:
        item = SmcSysAxiItem(f"wr_{label}")
        item.op = SmcSysAxiOp.WRITE
        item.addr = addr
        item.length = width // 8
        item.beats = beats
        item.burst = burst
        item.wdata = data
        item.allow_error = True
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        assert item.resp_code is not None, f"{label} @ 0x{addr:08x}: no bresp recorded"
        return item.resp_code

    async def _probe(self, p: _Probe) -> None:
        self.env.axi_monitor.expected_decerr_addrs.add(p.addr)
        label = f"{p.unit}_{p.point}_{p.width}"
        rresp, rdata = await self._rd(label, p.addr, p.width)
        pattern = WRITE_PATTERN if p.width == 32 else WRITE_PATTERN64
        bresp = await self._wr(label, p.addr, p.width, pattern)
        self.obs_bresp += 1
        self.bresp_tally[_rname(bresp)] += 1
        cocotb.log.info(
            "OBS-BRESP unit=%s addr=0x%08x declared=%s observed=%s rresp_observed=%s "
            "rdata=0x%0*x width=%d point=%s xbar=%s rresp_declared=%s rdata_declared=0x%08x "
            "note=%s",
            p.unit,
            p.addr,
            p.resp["bresp"],
            _rname(bresp),
            _rname(rresp),
            p.width // 4,
            rdata,
            p.width,
            p.point,
            p.xbar,
            p.resp["rresp"],
            p.resp["rdata"],
            p.note,
        )

    async def _burst(
        self,
        case: str,
        label: str,
        xbar: str,
        width: int,
        beat0: int,
        beat1: int,
        kinds: tuple[str | None, str | None],
        note: str = "-",
    ) -> None:
        """Two-beat INCR write from ``beat0`` (``beat0 + width/8`` is ``beat1``).

        ``kinds`` names each beat's word. ``None`` is a live register: the beat rewrites what it
        read, so the register keeps its value. ``"P"`` is scratch or decodes to no register: the
        beat writes the pattern and a scratch word is restored afterwards. ``"W"`` is a write-only
        push register: the beat writes the pattern and the word is neither read nor restored,
        since every write to it pushes one entry.
        """
        nbytes = width // 8
        assert beat1 == beat0 + nbytes, f"{label}: beats 0x{beat0:x}/0x{beat1:x} not adjacent"
        self.env.axi_monitor.expected_decerr_addrs.update((beat0, beat1))
        pattern = WRITE_PATTERN64 if width == 64 else WRITE_PATTERN
        mask = (1 << width) - 1
        before = []
        beat_words = []
        for i, (addr, kind) in enumerate(zip((beat0, beat1), kinds)):
            if kind == "W":
                before.append(None)
                beat_words.append(pattern)
                continue
            _, value = await self._rd(f"{label}_pre{i}", addr, width)
            before.append(value)
            beat_words.append(value if kind is None else pattern)
        singles = []
        for i, (addr, data) in enumerate(zip((beat0, beat1), beat_words)):
            singles.append(await self._wr(f"{label}_single{i}", addr, width, data))
        payload = (beat_words[0] & mask) | ((beat_words[1] & mask) << width)
        bresp = await self._wr(f"{label}_burst", beat0, width, payload, beats=2)
        self.obs_burst += 1
        cocotb.log.info(
            "OBS-BURST case=%s addr=0x%08x len=2 bresp=%s width=%d beat0=0x%08x:%s "
            "beat1=0x%08x:%s label=%s xbar=%s note=%s",
            case,
            beat0,
            _rname(bresp),
            width,
            beat0,
            _rname(singles[0]),
            beat1,
            _rname(singles[1]),
            label,
            xbar,
            note,
        )
        for i, (addr, kind, orig) in enumerate(zip((beat0, beat1), kinds, before)):
            if kind is None:
                _, after = await self._rd(f"{label}_post{i}", addr, width)
                assert after == orig, (
                    f"{label} beat{i} live word 0x{addr:08x}: 0x{after:x} after the burst, "
                    f"was 0x{orig:x}"
                )
                self.live_results.append(f"{label}:0x{addr:08x}=0x{orig:x} unchanged")
            elif kind == "P" and singles[i] == _RESP_CODES["OKAY"]:
                await self._wr(f"{label}_restore{i}", addr, width, orig)
                _, after = await self._rd(f"{label}_restored{i}", addr, width)
                assert after == orig, (
                    f"{label} beat{i} scratch 0x{addr:08x}: 0x{after:x} after restore, "
                    f"want 0x{orig:x}"
                )
                self.live_results.append(f"{label}:0x{addr:08x} restored 0x{orig:x}")

    async def _rd_beats(self, label: str, addr: int, width: int, beats: int) -> list[int]:
        """Per-beat RRESP of an INCR read burst, from the port's R handshakes."""
        sampler = SepInRespSampler(cocotb.top)
        try:
            item = SmcSysAxiItem(f"rd_{label}")
            item.op = SmcSysAxiOp.READ
            item.addr = addr
            item.length = width // 8
            item.beats = beats
            item.burst = BURST_INCR
            item.allow_error = True
            await self.start_item(item)
            await self.finish_item(item)
            self.accesses += 1
            await RisingEdge(cocotb.top.clk_smc_i)
            await RisingEdge(cocotb.top.clk_smc_i)
        finally:
            sampler.stop()
        r, _, _, _ = sampler.take()
        assert sampler.unresolved == 0 and len(r) == beats, (
            f"{label} @ 0x{addr:08x}: {len(r)} R beats sampled for {beats}, "
            f"{sampler.unresolved} unresolved edges"
        )
        codes = [resp for resp, _, _ in r]
        assert None not in codes, f"{label} @ 0x{addr:08x}: RRESP X in {codes}"
        return codes

    async def _merge_rule(self) -> None:
        base = LOCAL_BASE_RESET
        cpu_last = smc_indexed_addr("SMC_TOP_SMC_CPU_CTRL_DUMMY_ROM_NULL_BASE_ADDR", 3)
        ru_last = smc_addr("SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_FLR_RESET_COUNTER_VALUE_BASE_ADDR")
        scratch_2 = smc_indexed_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_SCRATCH_BASE_ADDR", 2)
        assert cpu_last + 8 == base + 0x3_92C0
        assert ru_last + 4 == base + 0x20CC and scratch_2 == base + 0x2808
        rows = []
        okay = _RESP_CODES["OKAY"]
        # Declared beat answers: a live register OKAY; the beat past the last register of
        # smc_cpu_ctrl SLVERR (memmap.adoc, Generated Register Blocks); the word past the
        # decoded extent of smc_reset_unit the generated row's past_response, answered by
        # the crossbar.
        ru_past = _RESP_CODES[generated_past_extent_resp("smc_reset_unit")[1]]
        assert ru_past == _RESP_CODES[generated_past_extent_resp("smc_reset_unit")[0]]
        slverr = _RESP_CODES["SLVERR"]
        # Every beat writes a pattern inside the writable field of its word; a beat the
        # block answers OKAY is shown landed by reading the pattern back, then restored.
        full64 = (1 << 64) - 1
        full32 = (1 << 32) - 1
        null_bm = cpu_ctrl_u32("CPU_CTRL__DUMMY_ROM_NULL__DUMMY_ROM_NULL_bm")
        flr_bm = reset_unit_u32(
            "RESET_UNIT__ISOLATE_REQ_FLR_RESET_COUNTER_VALUE__ISOLATE_REQ_FLR_RESET_COUNTER_VALUE_bm"
        )
        # (label, start, width, burst, per-beat field masks, declared beat answers, evidence)
        cases = (
            (
                "MERGE_cpu_ctrl_last_incr",
                cpu_last,
                64,
                BURST_INCR,
                (null_bm, full64),
                (okay, slverr),
                "read",
            ),
            (
                "MERGE_reset_unit_last_incr",
                ru_last,
                32,
                BURST_INCR,
                (flr_bm, full32),
                (okay, ru_past),
                "read",
            ),
            (
                "MERGE_reset_unit_past_wrap",
                ru_last + 4,
                32,
                BURST_WRAP,
                (full32, flr_bm),
                (ru_past, okay),
                "single",
            ),
            (
                "MERGE_scratch_cold_incr",
                scratch_2,
                32,
                BURST_INCR,
                (full32, full32),
                (okay, okay),
                "read",
            ),
        )
        for label, start, width, burst, fields, declared, evidence in cases:
            nbytes = width // 8
            addrs = (start, start - nbytes) if burst == BURST_WRAP else (start, start + nbytes)
            self.env.axi_monitor.expected_decerr_addrs.update(addrs)
            pattern = WRITE_PATTERN64 if width == 64 else WRITE_PATTERN
            mask = (1 << width) - 1
            before = [await self._rd(f"{label}_pre{i}", a, width) for i, a in enumerate(addrs)]
            words = [pattern & field for field in fields]
            for (_, orig), word, code in zip(before, words, declared):
                assert code != okay or word != orig, f"{label}: pattern equals the held word"
            if evidence == "read":
                codes = await self._rd_beats(label, start, width, 2)
            else:
                codes = [
                    await self._wr(f"{label}_single{i}", a, width, w)
                    for i, (a, w) in enumerate(zip(addrs, words))
                ]
            assert tuple(codes) == declared, (
                f"CHK-BURST-MERGE-RESP FAIL: {label} beats from 0x{start:08x} answer "
                f"{[_rname(c) for c in codes]} ({evidence}), declared "
                f"{[_rname(c) for c in declared]}"
            )
            want = split_bresp(codes)
            payload = (words[0] & mask) | ((words[1] & mask) << width)
            got = await self._wr(f"{label}_burst", start, width, payload, beats=2, burst=burst)
            assert got == want, (
                f"CHK-BURST-MERGE-RESP FAIL: {label} two-beat {'WRAP' if burst == BURST_WRAP else 'INCR'} "
                f"write from 0x{start:08x} answers {_rname(got)}; the beats answer "
                f"{[_rname(c) for c in codes]} so the stated rule gives {_rname(want)}"
            )
            landed = []
            for i, (a, word, code, (_, orig)) in enumerate(zip(addrs, words, declared, before)):
                if code != okay:
                    continue
                _, after = await self._rd(f"{label}_post{i}", a, width)
                assert after == word, (
                    f"CHK-BURST-MERGE-RESP FAIL: {label} beat {i} at 0x{a:08x} answered OKAY but "
                    f"reads 0x{after:x} after the burst, want the written 0x{word:x}"
                )
                await self._wr(f"{label}_restore{i}", a, width, orig)
                _, restored = await self._rd(f"{label}_restored{i}", a, width)
                assert restored == orig, (
                    f"{label} 0x{a:08x}: 0x{restored:x} after restore, was 0x{orig:x}"
                )
                landed.append(f"0x{a:08x}=0x{word:x}")
                self.live_results.append(f"{label}:0x{a:08x} restored 0x{orig:x}")
            rows.append(
                f"{label}: beats {[_rname(c) for c in codes]} ({evidence}) -> {_rname(got)}, "
                f"landed {' '.join(landed)}"
            )
        self._log_chk(
            "CHK-BURST-MERGE-RESP",
            f"{len(cases)} two-beat writes whose merged BRESP equals the stated rule over the "
            f"beat answers: {'; '.join(rows)}",
        )

    async def body(self) -> None:
        await self.wait_fuse_sense_done(FUSE_WAIT_BOUND_SMC_CYCLES)
        dut = cocotb.top
        states = []
        for name in ("tb_fuse_sense_done", "tb_fuse_reset_n", "tb_rst_warm_smc_clk_n"):
            sig = getattr(dut, name)
            assert sig.value.is_resolvable, f"{name} is X/Z after the wait"
            states.append(f"{name}={int(sig.value)}")
        self.fuse_state = ",".join(states)

        probes = build_probes()
        for p in probes:
            await self._probe(p)
        assert self.obs_bresp == len(probes), (
            f"CHK-OBS-BRESP-TABLE FAIL: {self.obs_bresp} OBS-BRESP lines for {len(probes)} probes"
        )
        self._log_chk(
            "CHK-OBS-BRESP-TABLE",
            f"{self.obs_bresp} OBS-BRESP lines recorded, one per probe, over SEP_IN at LOCAL_BASE "
            f"0x{LOCAL_BASE_RESET:08X} (REGION_SIZE reset 0x{REGION_SIZE_RESET:X}); observed "
            f"bresp tally {dict(self.bresp_tally)}; the responses are not graded against the "
            f"declaration",
        )

        base = LOCAL_BASE_RESET
        scratch_cold_7 = smc_indexed_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_SCRATCH_BASE_ADDR", 7)
        scratch_cold_6 = smc_indexed_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_SCRATCH_BASE_ADDR", 6)
        scratch_warm_0 = smc_indexed_addr(
            "SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_WARM_SCRATCH_BASE_ADDR", 0
        )
        assert scratch_cold_7 == base + 0x281C and scratch_cold_6 == base + 0x2818
        assert scratch_warm_0 == base + 0x2880
        gpio_last = smc_indexed_addr("SMC_TOP_GPIO_INTF_WRAP_GPIO_INTF_ACCESS_FILTER_BASE_ADDR", 64)
        assert gpio_last == base + 0x3408
        outfilt_last = (
            smc_indexed_addr("SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_WRAP_FILTER_CTRL_BASE_ADDR", 15)
            + smc_addr("SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_WRAP_FILTER_CTRL_STRIDE")
            - 8
        )
        assert outfilt_last == base + 0x1_61F8
        cpu_last = smc_indexed_addr("SMC_TOP_SMC_CPU_CTRL_DUMMY_ROM_NULL_BASE_ADDR", 3)
        assert cpu_last == base + 0x3_92B8
        alias_0 = smc_indexed_addr(
            "SMC_TOP_SMC_ALIAS_REMAP_WRAP_ALIAS_REMAP_REGION_REGION_START_BASE_ADDR", 0
        )
        assert alias_0 == base + 0x1_2000
        gpio_0 = smc_indexed_addr("SMC_TOP_GPIO_INTF_WRAP_GPIO_INTF_DATA_CTRL_BASE_ADDR", 0)
        assert gpio_0 == base + 0x3000
        mb_wd = smc_addr("SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_WRITE_DATA_BASE_ADDR")
        assert mb_wd == base + 0x1_8000

        # case a: beat0 is the last decoded word of a unit or sub-block, beat1 lies past it.
        # case b: beat0 lies in a gap, beat1 is the first decoded word of the next unit or
        # sub-block. Every pair runs with 64-bit beats and again with 32-bit beats, so the data-
        # width converter of the 32-bit paths and the burst splitter are told apart.
        # (case, label, xbar, beat1 address, beat0 kind, beat1 kind, note); the kinds are those
        # of _burst.
        cases = (
            ("a", "A1_gpio_intf_past", "periph", gpio_last + 8, None, "P", "-"),
            (
                "a",
                "A2_misc_scratch_cold_gap1",
                "periph/misc_wrap",
                scratch_cold_6 + 8,
                "P",
                "P",
                "-",
            ),
            ("a", "A3_outbound_filter_past", "internal", outfilt_last + 8, None, "P", "-"),
            ("a", "A4_cpu_ctrl_past", "local/cluster", cpu_last + 8, None, "P", "-"),
            (
                "b",
                "B1_misc_gap1_scratch_cold_warm",
                "periph/misc_wrap",
                scratch_warm_0,
                "P",
                "P",
                "-",
            ),
            ("b", "B2_base_config_past_alias_remap", "internal", alias_0, "P", None, "-"),
            ("b", "B3_misc_top_gpio_intf", "periph", gpio_0, "P", None, "-"),
            (
                "b",
                "B4_gap_17FF8_mailbox_write_data",
                "internal",
                mb_wd,
                "P",
                "W",
                "each_beat1_write_pushes_one_mailbox_entry",
            ),
            (
                "b",
                "C1_outfilt_top_gap_17000",
                "internal",
                base + 0x1_7000,
                "P",
                "P",
                "both_beats_past_every_rule",
            ),
            (
                "b",
                "C2_gap_FFF8_base_config",
                "local",
                smc_addr("SMC_TOP_SMC_BASE_CONFIG_BASE_ADDR"),
                "P",
                None,
                "beats_straddle_a_local_xbar_rule_boundary",
            ),
        )
        for width in (64, 32):
            for case, label, xbar, beat1, d0, d1, note in cases:
                await self._burst(
                    case, label, xbar, width, beat1 - width // 8, beat1, (d0, d1), note=note
                )
        assert self.obs_burst == 2 * len(cases), (
            f"CHK-OBS-BURST-TABLE FAIL: {self.obs_burst} OBS-BURST lines for {len(cases)} cases "
            f"at two widths"
        )
        self._log_chk(
            "CHK-OBS-BURST-TABLE",
            f"{self.obs_burst} OBS-BURST lines recorded, one per case and width: two-beat INCR "
            f"writes over SEP_IN whose beats fall on either side of a decoded extent; merged BRESP "
            f"recorded beside the single-beat codes",
        )
        await self._merge_rule()
        self._log_chk(
            "CHK-BURST-LIVE-UNCHANGED",
            f"{len(self.live_results)} live or scratch words read back after the bursts: "
            + "; ".join(self.live_results),
        )
        self._log_chk(
            "CHK-TIMEOUT-PATHS",
            f"wait_fuse_sense_done sub-waits tb_fuse_sense_done, tb_fuse_reset_n, "
            f"tb_rst_warm_smc_clk_n each bounded {FUSE_WAIT_BOUND_SMC_CYCLES} clk_smc_i rises, "
            f"last observed {self.fuse_state}; {self.accesses} AXI accesses each bounded by the "
            f"driver timeout {AXI_TIMEOUT_NS} ns (allow_timeout False), all answered; no other "
            f"wait",
        )
