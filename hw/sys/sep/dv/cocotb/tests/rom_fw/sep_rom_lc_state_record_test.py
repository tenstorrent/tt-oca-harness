# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The ROM records the validated lifecycle state in bl0_state and reports it.

rom.adoc, Fuse and System State, Lifecycle State ([S11]):

* SEP-ROM-FUSE-030: "The validated LC state shall be recorded in `bl0_state.lc_state` for
  consumption by later stages and by BL1, and shall be reported on the status channel."
* "The 4-bit lifecycle state is read from the low nibble of `SEP_EFUSE_MAP_LC_STATE`
  (`0x1093_000C`)." Legal raw values (Lifecycle states table): `TEST_DEV` `0x0`, `PROD` `0x1`,
  `RMA_SiP` `0x2`-`0x3`, `RMA_CHIPLET` `0x6`-`0x7`, `PROD_END` `0x8`.

rom.adoc, `bl0_state` Hand-off Block: "placed at the very top of DCCM (`0xC0040000 + 0x20000 −
sizeof`) so BL1 can discover it by magic and size from the DCCM end"; fields in order
`start_magic` u32 (`0x53304C42`), three u32, `boot_mode` u32, `secure_boot` bool, `sboot_dis`
bool, `lc_state` u32 "Validated lifecycle state", ..., `size`, `end_magic` u32 x2.

rom.adoc, Status and POST Codes: `STATUS_ENCODE(type, value) = (type & 0xFF) << 24 |
(SEP_STATUS_ID) << 16 | (value & 0xFFFF)`, "1 = BL0", `INFO` `0x01`, `INFO_EXT` `0x81`; status
scratch `cold_scratch[1]`: "Every `STATUS_OUT()` word". Stage trace: "[S11] lifecycle |
`FUSE_LC_STATE` → `INFO_EXT` (state); `LIFECYCLE_VALID`".

One testlist entry per legal raw value (`+sep_rom_lc=<raw>`). The record is graded on the
PR-TCM DCCM write port: after the ROM's first `LC_STATE` read, a write of the raw value
zero-extended to the `lc_state` word, and that word still holds the raw value at the hand-off
mret, or at the FAIL verdict of a part that refuses its image. The block is found as BL1 finds
it, from `size` and `end_magic` at the DCCM end. The report is graded on `cold_scratch[1]` only:
the DV SMC status ring is invalid, so the ring channel is not graded and the
`STATUS_REPORTING_INVALID` word each ring insert adds is skipped. Reads of `lc_state` by later
stages and by BL1 are not graded. The console `LC_STATE=` line is debug text and only logged.
"""

from __future__ import annotations

from bisect import bisect_right

import cocotb
import pyuvm
from cocotb.triggers import Edge, ReadOnly
from cocotb.utils import get_sim_time
from env.sep_efuse_image import LC_WORD_IDX, SepEfuseImage
from env.sep_fabric_tap import SepFabricTap
from env.sep_rom_observer import STORE_LAG_MAX_CYCLES
from env.sep_rv32_trace_decode import INSN_MRET, funct3, is_store
from env.sep_tcm_flip import DATA_BITS, DCCM_BASE, DCCM_BYTES
from rom_fw.sep_rom_observe_base import sep_rom_observe_base
from sep_reg_meta import sym

_LC_PLUSARG = "sep_rom_lc"
_LC_REG = sym("SEP_EFUSE_MAP_LC_STATE_REG_ADDR")
_SHADOW = "efuse_shadow_probe_o"
_WORD = 0xFFFF_FFFF
# PR-TCM DCCM geometry: 2 banks, bank = byte offset bit 2, row = byte offset bits 16:3.
_BANKS = 2
_AW = 14
_DCCM_END = DCCM_BASE + DCCM_BYTES
_MIN_PROBES = 16
_BL0_MAGIC = 0x5330_4C42
# Spec field order under ilp32 alignment: four u32, two 1-byte bool, 2 bytes padding.
_LC_OFFSET = 20
_STATUS_ID_BL0 = 1
_TYPE_INFO = 0x01
_TYPE_INFO_EXT = 0x81
_TYPE_ERROR = 0x0F
# SEP_MSG_* values from the generated status code table; FUSE_LC_STATE and LIFECYCLE_VALID are INFO.
_MSG_FUSE_LC_STATE = 0x0020
_MSG_LIFECYCLE_VALID = 0x002C
_MSG_STATUS_REPORTING_INVALID = 0x0079


def _status(kind: int, code: int) -> int:
    return (kind << 24) | (_STATUS_ID_BL0 << 16) | (code & 0xFFFF)


# Each insert into the invalid DV status ring adds this word to cold_scratch[1].
_RING_INVALID = _status(_TYPE_ERROR, _MSG_STATUS_REPORTING_INVALID)


def _slot(addr: int) -> tuple[int, int]:
    off = addr - DCCM_BASE
    return (off >> 2) & (_BANKS - 1), off >> 3


def _hex(v: int | None) -> str:
    return "none" if v is None else f"0x{v:08x}"


def _value_at(records: list[tuple[int, int]], t: int) -> int | None:
    v = None
    for rt, rv in records:
        if rt > t:
            break
        v = rv
    return v


def _held(writes: list[tuple[int, int | None]]) -> int | None:
    return writes[-1][1] if writes else None


@pyuvm.test()
class sep_rom_lc_state_record_test(sep_rom_observe_base):
    required_evidence = ("CHK-LC-RECORDED", "CHK-LC-REPORTED")

    def build_efuse_image(self) -> SepEfuseImage:
        self.image = SepEfuseImage().set_lc_state(self.raw)
        return self.image

    async def run_scenario(self) -> None:
        arg = cocotb.plusargs.get(_LC_PLUSARG)
        if arg is None:
            raise ValueError(f"add +{_LC_PLUSARG}=<raw LC code> to the testlist entry")
        self.raw = int(arg, 0)
        self.shadow: list[tuple[int, int]] = []
        self.shadow_edges = 0
        self.tap_start_ps = int(get_sim_time("ps"))
        self.tcm = SepFabricTap("PR-TCM").start()
        self.tcm_mark = self.tcm.mark()
        self.lsu = SepFabricTap("PR-LSU-XBAR").start()
        self.lsu_mark = self.lsu.mark()
        await super().run_scenario()

    def _lc_word(self, *, known: bool = False) -> int:
        sh = 32 * LC_WORD_IDX
        sig = getattr(cocotb.top, _SHADOW)
        return (self.rd(sig, _WORD << sh, allow_unknown=not known) >> sh) & _WORD

    async def stimulus(self, obs) -> None:
        # Records every change of the sensed LC shadow word, so each LC_STATE read has its value.
        sig = getattr(cocotb.top, _SHADOW)
        self.shadow.append((int(get_sim_time("ps")), self._lc_word()))
        while True:
            await Edge(sig)
            await ReadOnly()
            self.shadow_edges += 1
            w = self._lc_word()
            if w != self.shadow[-1][1]:
                self.shadow.append((int(get_sim_time("ps")), w))

    async def before_grade(self, obs) -> None:
        self.shadow_end = self._lc_word(known=True)
        self.tap_stop_ps = int(get_sim_time("ps"))
        await self.tcm.stop()
        await self.lsu.stop()

    def _end(self, obs, chk) -> int | None:
        """Hand-off mret time, or the FAIL verdict time of a refused boot."""
        mret = obs.pre_mret[-1] if obs.pre_mret else None
        handoff = mret is not None and mret.insn == INSN_MRET and obs.post_mret is not None
        verdict = obs.verdict_pass()
        end_t = mret.t_ps if handoff else (obs.verdict[-1][0] if verdict is False else None)
        chk.ctrl(
            "RUN-END",
            end_t is not None,
            end="handoff" if handoff else "fail-verdict" if end_t is not None else "none",
            end_ps=end_t if end_t is not None else -1,
            verdict=verdict,
        )
        return end_t

    def _stimulus_ctrl(self, obs, chk, end_t: int | None) -> int | None:
        """Checks the LC shadow word every LC_STATE read returned; returns the first read time."""
        ar = self.lsu.since(self.lsu_mark, "ar")
        unknown = sum(1 for b in ar if b.addr is None)
        reads = [b for b in ar if b.addr == _LC_REG and (end_t is None or b.t_ps <= end_t)]
        expect = self.image.shadow_word(LC_WORD_IDX)
        seen = [_value_at(self.shadow, b.t_ps) for b in reads]
        first_t = obs.first[0].t_ps if obs.first else None
        covered = (
            first_t is not None
            and end_t is not None
            and self.tap_start_ps <= first_t
            and self.tap_stop_ps >= end_t
        )
        chk.ctrl(
            "LC-STIMULUS",
            covered
            and not unknown
            and self.image.lc_raw() == self.raw
            and expect & 0xF == self.raw
            and bool(reads)
            and all(v == expect for v in seen)
            and len(self.shadow) >= 2
            and self.shadow[-1][1] == self.shadow_end == expect,
            raw=f"0x{self.raw:x}",
            image_raw=f"0x{self.image.lc_raw():x}",
            expect_shadow=_hex(expect),
            lc_reads=len(reads),
            read_values=sorted({_hex(v) for v in seen}),
            shadow_changes=[f"{_hex(w)}@{t}" for t, w in self.shadow],
            shadow_edges=self.shadow_edges,
            shadow_end=_hex(self.shadow_end),
            ar_unknown=unknown,
        )
        return reads[0].t_ps if reads else None

    def _dccm_writes(self, end_t: int | None) -> tuple[dict, int, int]:
        """DCCM writes per slot as (time, data) lists, the write count and unknown lanes."""
        writes: dict[tuple[int, int], list[tuple[int, int | None]]] = {}
        n = unknown = 0
        for b in self.tcm.since(self.tcm_mark, "dccm"):
            if end_t is not None and b.t_ps > end_t:
                break
            for bank in range(_BANKS):
                en = b.lane("clken", bank, 1)
                if not en:
                    unknown += en is None
                    continue
                we = b.lane("wren", bank, 1)
                row = b.lane("addr", bank, _AW)
                if we is None or row is None:
                    unknown += 1
                    continue
                if we:
                    writes.setdefault((bank, row), []).append(
                        (b.t_ps, b.lane("wdata", bank, DATA_BITS))
                    )
                    n += 1
        return writes, n, unknown

    def _slot_map_ctrl(self, obs, chk, writes, end_t: int | None) -> bool:
        """A sw of a known nonzero word lands on its slot near its retirement; a wrong map misses."""
        win_ps = STORE_LAG_MAX_CYCLES * int(round(self.cfg.sys_clk_period_ns * 1000))
        stores = [
            r
            for r in obs.retires
            if is_store(r.insn)
            and not (r.exc or r.interrupt)
            and r.mem_addr is not None
            and DCCM_BASE <= r.mem_addr < _DCCM_END
            and (end_t is None or r.t_ps <= end_t)
        ]
        by_word: dict[int, list[int]] = {}
        for r in stores:
            by_word.setdefault(r.mem_addr & ~3, []).append(r.t_ps)

        def coalesces(r) -> bool:
            times = by_word[r.mem_addr & ~3]
            return bisect_right(times, r.t_ps + win_ps) > bisect_right(times, r.t_ps)

        probes = [
            r
            for r in stores
            if funct3(r.insn) == 2 and r.mem_data and r.mem_addr % 4 == 0 and not coalesces(r)
        ]

        def hits(slot_of) -> int:
            n = 0
            for r in probes:
                w = writes.get(slot_of(r.mem_addr), [])
                n += any(abs(t - r.t_ps) <= win_ps and d == r.mem_data for t, d in w)
            return n

        matched = hits(_slot)
        swap = hits(lambda a: (_slot(a)[0] ^ 1, _slot(a)[1]))
        word = hits(lambda a: (_slot(a)[0], (a - DCCM_BASE) >> 2))
        ok = (
            DCCM_BYTES == _BANKS * (1 << _AW) * 4
            and len(probes) >= _MIN_PROBES
            and matched == len(probes)
            and swap < len(probes)
            and word < len(probes)
        )
        chk.ctrl(
            "SLOT-MAP",
            ok,
            probes=len(probes),
            matched=matched,
            bank_swapped=swap,
            word_index=word,
            window_ps=win_ps,
        )
        return ok

    def grade(self, obs, chk) -> None:
        end_t = self._end(obs, chk)
        read_t = self._stimulus_ctrl(obs, chk, end_t)

        writes, n_writes, unknown = self._dccm_writes(end_t)
        first_t = obs.first[0].t_ps if obs.first else None
        tcm_live = (
            end_t is not None
            and first_t is not None
            and self.tap_start_ps <= first_t
            and self.tap_stop_ps >= end_t
            and n_writes > 0
            and unknown == 0
        )
        chk.ctrl(
            "TCM-LIVE",
            tcm_live,
            tap_ps=f"{self.tap_start_ps}..{self.tap_stop_ps}",
            writes=n_writes,
            unknown=unknown,
        )
        slot_ok = self._slot_map_ctrl(obs, chk, writes, end_t)

        # BL1 finds the block from size and end_magic at the DCCM end.
        last = writes if end_t is not None else {}
        size = _held(last.get(_slot(_DCCM_END - 8), []))
        end_magic = _held(last.get(_slot(_DCCM_END - 4), []))
        base = _DCCM_END - size if size and size % 4 == 0 and _LC_OFFSET < size else None
        ok_base = base is not None and base >= DCCM_BASE
        start_magic = _held(last.get(_slot(base), [])) if ok_base else None
        block_ok = start_magic == _BL0_MAGIC and end_magic == _BL0_MAGIC
        chk.ctrl(
            "BL0-BLOCK",
            block_ok,
            base=_hex(base),
            size=_hex(size),
            start_magic=_hex(start_magic),
            end_magic=_hex(end_magic),
        )

        field = base + _LC_OFFSET if ok_base else None
        lc_writes = last.get(_slot(field), []) if field is not None else []
        after = [d for t, d in lc_writes if read_t is not None and t > read_t]
        held = _held(lc_writes)
        chk.ok(
            "LC-RECORDED",
            tcm_live
            and slot_ok
            and block_ok
            and read_t is not None
            and self.raw in after
            and held == self.raw,
            field=_hex(field),
            expect=_hex(self.raw),
            held_at_end=_hex(held),
            writes_after_read=[_hex(d) for d in after],
            writes=len(lc_writes),
            lc_read_ps=read_t if read_t is not None else -1,
        )

        fuse_lc = _status(_TYPE_INFO, _MSG_FUSE_LC_STATE)
        ext = _status(_TYPE_INFO_EXT, self.raw)
        valid = _status(_TYPE_INFO, _MSG_LIFECYCLE_VALID)
        words = obs.status
        i = next((k for k, (_, w) in enumerate(words) if w == fuse_lc), None)
        tail = [(t, w) for t, w in words[i + 1 :] if w != _RING_INVALID] if i is not None else []
        nxt = tail[0] if tail else None
        valid_after = any(w == valid for _, w in tail[1:])
        chk.ok(
            "LC-REPORTED",
            nxt is not None
            and nxt[1] == ext
            and read_t is not None
            and nxt[0] > read_t
            and valid_after,
            fuse_lc_state=_hex(fuse_lc) if i is not None else "none",
            next_word=_hex(nxt[1] if nxt else None),
            expect=_hex(ext),
            lifecycle_valid_after=valid_after,
            fuse_lc_state_words=sum(1 for _, w in words if w == fuse_lc),
        )

        chk.obs(
            "LC-CONSOLE",
            lc_line=next((ln for ln in obs.lines() if ln.startswith("LC_STATE=")), "none"),
            name_line=next((ln for ln in obs.lines() if ln.startswith("LC=")), "none"),
            last_status=_hex(words[-1][1] if words else None),
            verdict=obs.verdict_pass(),
        )
