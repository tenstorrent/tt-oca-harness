# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Burst, exclusive, hole and past-end rules of memmap.adoc graded over SEP_IN.

Spec sources: memmap.adoc "Address Space Organization" (a burst that starts between unit
apertures answers DECERR for every beat) and "Generated Register Blocks" (an unoccupied
offset answers OKAY with 0 and takes no write; an offset past the last register answers
SLVERR when it reaches the block; the remap and filter arrays answer OKAY in their padding;
exclusive access answers OKAY, never EXOKAY) and the TRM memory_map.adoc "Decode Response
Codes" (the error data word is what a 32-bit read returns in either half of a 64-bit read; an
offset past a block's last register answers SLVERR with read data 0). The register inventory,
the block sizes, the array strides and the gap response word come from the generated
smc_addr.h, smc_memory_map.py and smc_memory_map.rdl.

Every read beat and write response is taken from a passive sampler of the SEP_IN R and B
handshakes, so a multi-beat burst is graded per beat.
"""

from __future__ import annotations

import re
from pathlib import Path

import cocotb
from cocotb.triggers import RisingEdge
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import (
    _SMC_ADDR_H,
    HANG_DET_THR_VALUE,
    LOCAL_BASE_RESET,
    _parse_indexed_bases,
    _parse_simple_defines,
    cpu_ctrl_u32,
    generated_decoded_extent,
    generated_unit_at,
    smc_addr,
    smc_indexed_addr,
)
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_sep_in_resp_sampler import SepInRespSampler

OKAY, EXOKAY, SLVERR, DECERR = 0, 1, 2, 3
_RESP = {OKAY: "OKAY", EXOKAY: "EXOKAY", SLVERR: "SLVERR", DECERR: "DECERR", None: "none"}
BURST_INCR = 1
FUSE_WAIT_BOUND_SMC_CYCLES = 200_000
AXI_TIMEOUT_NS = 50_000
ONES32 = 0xFFFF_FFFF
ONES64 = 0xFFFF_FFFF_FFFF_FFFF
EXCL_PATTERN = {4: 0x5EC0_A5A5, 8: 0x5EC0_A5A5_C3C3_1E1E}
GAP_OFFSET = 0xC000
GAP_BURST_BEATS = (4, 16)

# Generated blocks whose fabric decode is exact: (unit, register width in bytes). A hole is
# an aligned slot below the block's decoded extent that no register of the block occupies.
HOLE_BLOCKS = (("smc_reset_unit", 4), ("smc_cpu_ctrl", 8))
# Live registers read before and after the hole writes of each block.
HOLE_WITNESSES = {
    "smc_reset_unit": (
        "SMC_TOP_SMC_RESET_UNIT_SS_CONFIG_BASE_ADDR",
        "SMC_TOP_SMC_RESET_UNIT_SS_CONFIG_HOLD_BASE_ADDR",
        "SMC_TOP_SMC_RESET_UNIT_SS_DEBUG_HOLD_BASE_ADDR",
        "SMC_TOP_SMC_RESET_UNIT_SS_RESET_COMPLETE_BASE_ADDR",
        "SMC_TOP_SMC_RESET_UNIT_SYNC_REG_BASE_ADDR",
        "SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_REG_BASE_ADDR",
    ),
    "smc_cpu_ctrl": (
        "SMC_TOP_SMC_CPU_CTRL_RESET_TIMEOUT_BASE_ADDR",
        "SMC_TOP_SMC_CPU_CTRL_WDT_TIMEOUT_BASE_ADDR",
        "SMC_TOP_SMC_CPU_CTRL_WDT_TIMEOUT_RESET_BASE_ADDR",
        "SMC_TOP_SMC_CPU_CTRL_TEST_CTRL_BASE_ADDR",
        "SMC_TOP_SMC_CPU_CTRL_SMC_ATTRIBUTES_BASE_ADDR",
    ),
}

_CHECKERS = (
    "CHK-GAP-BURST-ALL-BEATS-DECERR",
    "CHK-EXCL-OKAY-NEVER-EXOKAY",
    "CHK-REGBLOCK-HOLE-OKAY-ZERO",
    "CHK-REGBLOCK-PAST-END-SLVERR",
    "CHK-ARRAY-PADDING-OKAY",
    "CHK-TIMEOUT-PATHS",
)


def _rname(code: int | None) -> str:
    return _RESP.get(code, str(code))


def rdl_gap_resp() -> dict:
    """``ocah_gap_resp`` of smc_memory_map.rdl: the answer of an address between unit apertures."""
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
    codes = {"OKAY": OKAY, "SLVERR": SLVERR, "DECERR": DECERR}
    return {"rresp": codes[m.group(1)], "rdata": int(m.group(2), 16), "bresp": codes[m.group(3)]}


def block_holes(unit: str, width: int) -> list[int]:
    """Aligned slots below ``unit``'s decoded extent that no generated register occupies."""
    prefix = f"SMC_TOP_{unit.upper()}_"
    base = smc_addr(prefix + "BASE_ADDR")
    size = generated_decoded_extent(unit)
    occupied: set[int] = set()
    for name, addr in _parse_simple_defines(_SMC_ADDR_H).items():
        if name.startswith(prefix) and name.endswith("_BASE_ADDR") and name != prefix + "BASE_ADDR":
            occupied.add(addr)
    counts = _parse_simple_defines(_SMC_ADDR_H)
    for name, (first, stride) in _parse_indexed_bases(_SMC_ADDR_H).items():
        if not name.startswith(prefix):
            continue
        count = counts[name[: -len("_BASE_ADDR")] + "_NUM"]
        occupied.update(first + i * stride for i in range(count))
    assert occupied, f"{unit}: no register symbol in {_SMC_ADDR_H}"
    assert all(base <= a < base + size for a in occupied), f"{unit}: register outside the extent"
    return [base + off for off in range(0, size, width) if base + off not in occupied]


class smc_memmap_access_rules_test_seq(SmcCsrSeq):
    """Drive the gap burst, exclusive, hole, past-end and array-padding accesses over SEP_IN."""

    def __init__(self, name: str = "smc_memmap_access_rules_test_seq") -> None:
        super().__init__(name)
        self.chk_seen: set[str] = set()
        self.sampler: SepInRespSampler | None = None
        self.fuse_state = "not waited"
        self.last_access = "none"
        self.wide: dict[str, tuple[int, int, int]] = {}
        self.locks_seen: set[int] = set()

    def _log_chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self.chk_seen.add(chk_id)

    async def _access(
        self,
        label: str,
        op: SmcSysAxiOp,
        addr: int,
        width: int,
        data: int = 0,
        beats: int = 1,
        lock: int = 0,
    ) -> tuple[list, list, SmcSysAxiItem]:
        """One SEP_IN access; returns the sampled R beats and B responses it produced."""
        assert self.sampler is not None
        self.sampler.take()
        item = SmcSysAxiItem(f"{op.value}_{label}")
        item.op = op
        item.addr = addr
        item.length = width
        item.beats = beats
        item.burst = BURST_INCR
        item.wdata = data
        item.axi_lock = lock
        item.allow_error = True
        self.env.axi_monitor.expected_decerr_addrs.update(addr + i * width for i in range(beats))
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        await RisingEdge(cocotb.top.clk_smc_i)
        await RisingEdge(cocotb.top.clk_smc_i)
        r, b, ar, aw = self.sampler.take()
        self.last_access = (
            f"{op.value} {label}@0x{addr:08x} width={width} beats={beats} lock={lock}"
        )
        assert not item.timed_out, f"{self.last_access}: no response within {AXI_TIMEOUT_NS} ns"
        carried = ar if op is SmcSysAxiOp.READ else aw
        assert carried == [lock], (
            f"{'CHK-EXCL-OKAY-NEVER-EXOKAY FAIL: ' if lock else ''}{self.last_access}: "
            f"{'ARLOCK' if op is SmcSysAxiOp.READ else 'AWLOCK'} sampled {carried} at the "
            f"address handshake, want [{lock}]"
        )
        self.locks_seen.add(lock)
        if op is SmcSysAxiOp.READ:
            assert len(r) == beats and not b, (
                f"{self.last_access}: {len(r)} R beats and {len(b)} B sampled, want {beats} R"
            )
            assert r[-1][2] == 1 and all(beat[2] == 0 for beat in r[:-1]), (
                f"{self.last_access}: RLAST {[beat[2] for beat in r]}"
            )
        else:
            assert len(b) == 1 and not r, (
                f"{self.last_access}: {len(b)} B and {len(r)} R sampled, want one B"
            )
        return r, b, item

    async def _read(self, label: str, addr: int, width: int, lock: int = 0) -> tuple[int, int]:
        r, _, _ = await self._access(label, SmcSysAxiOp.READ, addr, width, lock=lock)
        resp, data, _ = r[0]
        assert resp is not None and data is not None, f"{self.last_access}: RRESP or RDATA X"
        lane = (addr % 8) * 8 if width == 4 else 0
        return resp, (data >> lane) & ((1 << (8 * width)) - 1)

    async def _write(self, label: str, addr: int, width: int, data: int, lock: int = 0) -> int:
        _, b, _ = await self._access(label, SmcSysAxiOp.WRITE, addr, width, data, lock=lock)
        assert b[0] is not None, f"{self.last_access}: BRESP X"
        return b[0]

    async def _read_okay(self, label: str, addr: int, width: int) -> int:
        resp, data = await self._read(label, addr, width)
        assert resp == OKAY, f"{self.last_access}: RRESP {_rname(resp)}, want OKAY"
        return data

    async def _write_okay(self, label: str, addr: int, width: int, data: int) -> None:
        resp = await self._write(label, addr, width, data)
        assert resp == OKAY, f"{self.last_access}: BRESP {_rname(resp)}, want OKAY"

    async def _gap_bursts(self) -> None:
        gap = rdl_gap_resp()
        start = LOCAL_BASE_RESET + GAP_OFFSET
        for beats in GAP_BURST_BEATS:
            for off in range(0, beats * 8, 8):
                assert generated_unit_at(GAP_OFFSET + off) is None, (
                    f"0x{GAP_OFFSET + off:x} is inside a decoded extent"
                )
        rows = []
        for beats in GAP_BURST_BEATS:
            r, _, _ = await self._access("GAP_RBURST", SmcSysAxiOp.READ, start, 8, beats=beats)
            want_word = gap["rdata"] | (gap["rdata"] << 32)
            bad = [
                (i, _rname(resp), data)
                for i, (resp, data, _) in enumerate(r)
                if resp != gap["rresp"] or data != want_word
            ]
            assert not bad, (
                f"CHK-GAP-BURST-ALL-BEATS-DECERR FAIL: INCR len={beats - 1} read at "
                f"0x{start:08x}: beats (index, rresp, rdata) {bad} differ from "
                f"{_rname(gap['rresp'])} 0x{want_word:016x}"
            )
            payload = int.from_bytes((EXCL_PATTERN[8]).to_bytes(8, "little") * beats, "little")
            _, b, _ = await self._access(
                "GAP_WBURST", SmcSysAxiOp.WRITE, start, 8, payload, beats=beats
            )
            assert b[0] == gap["bresp"], (
                f"CHK-GAP-BURST-ALL-BEATS-DECERR FAIL: INCR len={beats - 1} write at "
                f"0x{start:08x}: BRESP {_rname(b[0])}, want {_rname(gap['bresp'])}"
            )
            rows.append(
                f"len={beats - 1}: {len(r)} R beats all {_rname(gap['rresp'])}/0x{want_word:016x}, "
                f"B {_rname(b[0])}"
            )
        # Positive control: the gap's neighbour below the same crossbar rule answers OKAY.
        local_base = smc_addr("SMC_TOP_SMC_BASE_CONFIG_LOCAL_BASE_BASE_ADDR")
        got = await self._read_okay("GAP_CONTROL", local_base, 8)
        assert got == LOCAL_BASE_RESET, f"LOCAL_BASE read 0x{got:x}, want 0x{LOCAL_BASE_RESET:x}"
        self._log_chk(
            "CHK-GAP-BURST-ALL-BEATS-DECERR",
            f"INCR read and write bursts starting in the gap at 0x{start:08x} (no unit decodes "
            f"any beat address): {'; '.join(rows)}; LOCAL_BASE reads OKAY 0x{got:x} afterwards",
        )

    async def _exclusive(self) -> None:
        # (name, address, access width, writable field mask)
        targets = (
            (
                "base_config.HANG_DET_SYS_AXI_TIMEOUT_THRESHOLD",
                smc_addr("SMC_TOP_SMC_BASE_CONFIG_HANG_DET_SYS_AXI_TIMEOUT_THRESHOLD_BASE_ADDR"),
                8,
                HANG_DET_THR_VALUE,
            ),
            (
                "misc_wrap.scratch_cold.SCRATCH[5]",
                smc_indexed_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_SCRATCH_BASE_ADDR", 5),
                4,
                ONES32,
            ),
            (
                "cpu_ctrl.SCRATCH[2]",
                smc_indexed_addr("SMC_TOP_SMC_CPU_CTRL_SCRATCH_BASE_ADDR", 2),
                8,
                cpu_ctrl_u32("CPU_CTRL__SCRATCH__DATA_bm"),
            ),
        )
        rows = []
        for name, addr, width, field in targets:
            plain = await self._read_okay(f"EXCL_PLAIN_{name}", addr, width)
            resp, got = await self._read(f"EXCL_RD_{name}", addr, width, lock=1)
            assert resp == OKAY, (
                f"CHK-EXCL-OKAY-NEVER-EXOKAY FAIL: exclusive read of {name} 0x{addr:08x}: RRESP "
                f"{_rname(resp)}, want OKAY"
            )
            assert got == plain, f"{name}: exclusive read 0x{got:x}, ordinary read 0x{plain:x}"
            pattern = EXCL_PATTERN[width] & field
            assert pattern != plain, f"{name}: pattern equals the stored word 0x{plain:x}"
            resp = await self._write(f"EXCL_WR_{name}", addr, width, pattern, lock=1)
            assert resp == OKAY, (
                f"CHK-EXCL-OKAY-NEVER-EXOKAY FAIL: exclusive write of {name} 0x{addr:08x}: BRESP "
                f"{_rname(resp)}, want OKAY"
            )
            after = await self._read_okay(f"EXCL_AFTER_{name}", addr, width)
            assert after == pattern, (
                f"CHK-EXCL-OKAY-NEVER-EXOKAY FAIL: {name} reads 0x{after:x} after the exclusive "
                f"write of 0x{pattern:x}; the write took no effect"
            )
            await self._write_okay(f"EXCL_RESTORE_{name}", addr, width, plain)
            got = await self._read_okay(f"EXCL_RESTORED_{name}", addr, width)
            assert got == plain, f"{name}: restore read 0x{got:x}, want 0x{plain:x}"
            rows.append(
                f"{name}@0x{addr:08x}: AxLOCK=1 read OKAY 0x{plain:x}, AxLOCK=1 write OKAY, "
                f"reads back 0x{after:x}, restored"
            )
        assert self.locks_seen == {0, 1}, f"AxLOCK values carried on SEP_IN: {self.locks_seen}"
        self._log_chk(
            "CHK-EXCL-OKAY-NEVER-EXOKAY",
            f"{len(targets)} generated blocks on three crossbar paths, AxLOCK sampled 1 at the "
            f"AR or AW handshake of every exclusive access and 0 at every other: {'; '.join(rows)}",
        )

    async def _holes(self) -> None:
        rows = []
        probed = 0
        for unit, width in HOLE_BLOCKS:
            holes = block_holes(unit, width)
            assert holes, f"{unit}: no unoccupied slot below its decoded extent"
            witnesses = [smc_addr(sym) for sym in HOLE_WITNESSES[unit]]
            before = [await self._read_okay(f"HOLE_WITNESS_{unit}", a, width) for a in witnesses]
            ones = ONES32 if width == 4 else ONES64
            for addr in holes:
                resp, data = await self._read(f"HOLE_RD_{unit}", addr, width)
                assert (resp, data) == (OKAY, 0), (
                    f"CHK-REGBLOCK-HOLE-OKAY-ZERO FAIL: {unit} hole 0x{addr:08x} reads "
                    f"{_rname(resp)} 0x{data:x}, want OKAY 0"
                )
                resp = await self._write(f"HOLE_WR_{unit}", addr, width, ones)
                assert resp == OKAY, (
                    f"CHK-REGBLOCK-HOLE-OKAY-ZERO FAIL: {unit} hole 0x{addr:08x} write of ones "
                    f"answers {_rname(resp)}, want OKAY"
                )
                resp, data = await self._read(f"HOLE_RB_{unit}", addr, width)
                assert (resp, data) == (OKAY, 0), (
                    f"CHK-REGBLOCK-HOLE-OKAY-ZERO FAIL: {unit} hole 0x{addr:08x} reads "
                    f"{_rname(resp)} 0x{data:x} after a write of ones, want OKAY 0"
                )
                probed += 1
            after = [await self._read_okay(f"HOLE_WITNESS_{unit}", a, width) for a in witnesses]
            assert after == before, (
                f"CHK-REGBLOCK-HOLE-OKAY-ZERO FAIL: {unit} live registers "
                f"{[hex(a) for a in witnesses]} read {[hex(v) for v in after]} after the hole "
                f"writes, were {[hex(v) for v in before]}"
            )
            assert any(before), f"{unit}: every witness register read 0"
            rows.append(
                f"{unit} ({width}-byte slots): holes {' '.join(f'0x{a - LOCAL_BASE_RESET:x}' for a in holes)} "
                f"read OKAY/0 before and after a write of ones answered OKAY; {len(witnesses)} "
                f"live registers unchanged"
            )
        assert probed >= 10, f"{probed} holes probed"
        self._log_chk("CHK-REGBLOCK-HOLE-OKAY-ZERO", f"{probed} holes: {'; '.join(rows)}")

    async def _past_end(self) -> None:
        last = smc_indexed_addr("SMC_TOP_SMC_CPU_CTRL_DUMMY_ROM_NULL_BASE_ADDR", 3)
        extent = smc_addr("SMC_TOP_SMC_CPU_CTRL_BASE_ADDR") + generated_decoded_extent(
            "smc_cpu_ctrl"
        )
        assert last + 8 == extent, f"DUMMY_ROM_NULL[3] 0x{last:x} is not the last 8-byte slot"
        orig = await self._read_okay("PAST_LAST", last, 8)
        held = EXCL_PATTERN[8] ^ orig
        await self._write_okay("PAST_LAST_SEED", last, 8, held)
        r, _, _ = await self._access("PAST_RBURST", SmcSysAxiOp.READ, last, 8, beats=2)
        (r0, d0, _), (r1, d1, _) = r
        assert (r0, d0) == (OKAY, held), (
            f"CHK-REGBLOCK-PAST-END-SLVERR FAIL: beat 0 at 0x{last:08x} {_rname(r0)} 0x{d0:x}, "
            f"want OKAY 0x{held:x}"
        )
        assert (r1, d1) == (SLVERR, 0), (
            f"CHK-REGBLOCK-PAST-END-SLVERR FAIL: beat 1 at 0x{last + 8:08x}, past the last "
            f"register of smc_cpu_ctrl, answers {_rname(r1)} 0x{d1:x}, want SLVERR 0"
        )
        payload = held | (EXCL_PATTERN[8] << 64)
        _, b, _ = await self._access("PAST_WBURST", SmcSysAxiOp.WRITE, last, 8, payload, beats=2)
        assert b[0] == SLVERR, (
            f"CHK-REGBLOCK-PAST-END-SLVERR FAIL: two-beat write from 0x{last:08x} answers "
            f"{_rname(b[0])}, want SLVERR (last beat past the end)"
        )
        got = await self._read_okay("PAST_LAST_AFTER", last, 8)
        assert got == held, f"DUMMY_ROM_NULL[3] 0x{got:x} after the burst, was 0x{held:x}"
        await self._write_okay("PAST_LAST_RESTORE", last, 8, orig)
        # The 32-bit blocks: a 64-bit read at the last 32-bit register has its upper word
        # past the extent, and the fabric decodes that word.
        rows = []
        for unit, sym in (
            (
                "smc_reset_unit",
                "SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_FLR_RESET_COUNTER_VALUE_BASE_ADDR",
            ),
            (
                "smc_base_config",
                "SMC_TOP_SMC_BASE_CONFIG_HANG_DET_DATA_ACCEL_TIMEOUT_THRESHOLD_BASE_ADDR",
            ),
        ):
            addr = smc_addr(sym)
            size = generated_decoded_extent(unit)
            assert addr + 4 == smc_addr(f"SMC_TOP_{unit.upper()}_BASE_ADDR") + size
            low = await self._read_okay(f"WIDE_LOW_{unit}", addr, 4)
            resp, data = await self._read(f"WIDE_{unit}", addr, 8)
            rows.append(
                f"{unit} 64-bit read at 0x{addr:08x} (extent ends at +4): {_rname(resp)} "
                f"0x{data:016x}, 32-bit word there 0x{low:08x}"
            )
            self.wide[unit] = (resp, data, low)
        cocotb.log.info("INFO-WIDE-READ-PAST-END (recorded, not compared): %s", "; ".join(rows))
        self._log_chk(
            "CHK-REGBLOCK-PAST-END-SLVERR",
            f"smc_cpu_ctrl: 2-beat INCR read from DUMMY_ROM_NULL[3] 0x{last:08x} seeded with "
            f"0x{held:x}: beat 0 OKAY 0x{held:x}, beat 1 at 0x{last + 8:08x} SLVERR 0x{d1:x}; "
            f"2-beat INCR write BRESP {_rname(b[0])}, DUMMY_ROM_NULL[3] unchanged and restored",
        )

    async def _array_padding(self) -> None:
        entries = (
            ("alias_remap REGION[0]", "SMC_TOP_SMC_ALIAS_REMAP_WRAP_ALIAS_REMAP_REGION"),
            ("inbound FILTER_CTRL[0]", "SMC_TOP_SMC_INBOUND_FILTER_CTRL_WRAP_FILTER_CTRL"),
        )
        rows = []
        for name, sym in entries:
            entry, stride = _parse_indexed_bases(_SMC_ADDR_H)[sym + "_BASE_ADDR"]
            size = smc_addr(sym + "_SIZE")
            # The entry's registers and the next entry's first register witness the padding.
            assert size < stride, f"{name}: size 0x{size:x} is not below the stride 0x{stride:x}"
            regs = [*range(entry, entry + size, 8), entry + stride]
            before = [await self._read_okay(f"PAD_ENTRY_{name}", a, 8) for a in regs]
            for pad in range(entry + size, entry + stride, 8):
                resp, data = await self._read(f"PAD_RD_{name}", pad, 8)
                assert (resp, data) == (OKAY, 0), (
                    f"CHK-ARRAY-PADDING-OKAY FAIL: {name} padding 0x{pad:08x} reads "
                    f"{_rname(resp)} 0x{data:x}, want OKAY 0"
                )
                resp = await self._write(f"PAD_WR_{name}", pad, 8, ONES64)
                assert resp == OKAY, (
                    f"CHK-ARRAY-PADDING-OKAY FAIL: {name} padding 0x{pad:08x} write answers "
                    f"{_rname(resp)}, want OKAY"
                )
                resp, data = await self._read(f"PAD_RB_{name}", pad, 8)
                assert (resp, data) == (OKAY, 0), (
                    f"CHK-ARRAY-PADDING-OKAY FAIL: {name} padding 0x{pad:08x} reads "
                    f"{_rname(resp)} 0x{data:x} after a write of ones, want OKAY 0"
                )
            after = [await self._read_okay(f"PAD_ENTRY_{name}", a, 8) for a in regs]
            assert after == before, (
                f"CHK-ARRAY-PADDING-OKAY FAIL: {name} registers read {[hex(v) for v in after]} "
                f"after the padding writes, were {[hex(v) for v in before]}"
            )
            rows.append(
                f"{name} entry 0x{entry:08x} size 0x{size:x} stride 0x{stride:x}: padding "
                f"0x{entry + size:08x}..0x{entry + stride - 8:08x} reads OKAY/0 before and after a "
                f"write of ones answered OKAY, {len(regs) - 1} entry registers and the next "
                f"entry's first register unchanged"
            )
        self._log_chk("CHK-ARRAY-PADDING-OKAY", "; ".join(rows))

    async def body(self) -> None:
        await self.wait_fuse_sense_done(FUSE_WAIT_BOUND_SMC_CYCLES)
        dut = cocotb.top
        states = []
        for name in ("tb_fuse_sense_done", "tb_fuse_reset_n", "tb_rst_warm_smc_clk_n"):
            sig = getattr(dut, name)
            assert sig.value.is_resolvable, f"{name} is X/Z after the wait"
            states.append(f"{name}={int(sig.value)}")
        self.fuse_state = ",".join(states)
        self.sampler = SepInRespSampler(dut)
        try:
            await self._gap_bursts()
            await self._exclusive()
            await self._holes()
            await self._past_end()
            await self._array_padding()
        finally:
            self.sampler.stop()
        assert self.sampler.unresolved == 0, (
            f"{self.sampler.unresolved} clk_smc_i edges with an unresolved SEP_IN handshake pin"
        )
        self._log_chk(
            "CHK-TIMEOUT-PATHS",
            f"wait_fuse_sense_done sub-waits tb_fuse_sense_done, tb_fuse_reset_n, "
            f"tb_rst_warm_smc_clk_n each bounded {FUSE_WAIT_BOUND_SMC_CYCLES} clk_smc_i rises, "
            f"last observed {self.fuse_state}; {self.accesses} SEP_IN accesses each bounded by the "
            f"driver timeout {AXI_TIMEOUT_NS} ns (allow_timeout False), all answered, last "
            f"{self.last_access}; no other wait",
        )
