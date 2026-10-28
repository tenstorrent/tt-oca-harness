# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Proves SepRomObserver records an SMC-SRAM boot to BL1 before any leaf relies on it.

The boot reaches BL1 and its PASS verdict, but the DV SMC status ring is invalid, so the
ROM also reports STATUS_REPORTING_INVALID; this leaf grades the observer, not the ROM.
Each record kind is checked against a value rom.adoc states or against a second,
independent observation, so a wrong lane, a wrong time base or a broken register
tracker fails here rather than in a later leaf:

* "The core enters at `_start` in the Boot ROM." Boot ROM base `0x10040000`, 64 KiB.
* `cold_scratch[n]` at `0x10802000 + 8·n`; `cold_scratch[1]`: "every `STATUS_OUT()`
  encoded status word lands here", STATUS_ENCODE = type << 24 | SEP_STATUS_ID << 16 |
  value, "1 = BL0", types INFO 0x01, WARN 0x08, ERROR 0x0F, DEBUG 0x80, INFO_EXT 0x81.
* Hand-off: "`STARTING_BL1` → `INFO_EXT` ×2 (entry address)".
* Reference PMP region set, entry 0 Boot ROM: `pmpaddr` `0x04011FFF`.
* `cold_scratch[0]` after hand-off: "`0xACAFACA1` PASS ... in DV".
"""

from __future__ import annotations

import re

import pyuvm
from env.sep_rom_observer import STORE_LAG_MAX_CYCLES, load_rom_syms
from env.sep_rv32_trace_decode import (
    CSR_PMPADDR0,
    INSN_MRET,
    OP_SYSTEM,
    is_fence,
    is_fence_i,
    is_store,
    opcode,
)
from env.sep_verdict import TEST_PASS_CODE
from rom_fw.sep_rom_observe_base import RUN_PULSE_CYCLES, sep_rom_observe_base

_SPEC_ROM_BASE = 0x1004_0000
_SPEC_ROM_SIZE = 64 * 1024
_SPEC_PMPADDR0 = 0x0401_1FFF
_SPEC_COLD_SCRATCH_1 = 0x1080_2000 + 8 * 1
_STATUS_ID_BL0 = 1
_TYPE_INFO = 0x01
_TYPE_INFO_EXT = 0x81
_STATUS_TYPES = frozenset({_TYPE_INFO, 0x08, 0x0F, 0x80, _TYPE_INFO_EXT})
# SEP_MSG_STARTING_BL1 in bootrom/prod/include/status_values.h.
_MSG_STARTING_BL1 = 0x43
_RUN_REQ = "i_cpu_run_req_i"
_BL1_JUMP = re.compile(r"BL1_JUMP=0x([0-9a-fA-F]{8})")


def _bl0_status(word: int) -> bool:
    return (word >> 16) & 0xFF == _STATUS_ID_BL0 and (word >> 24) & 0xFF in _STATUS_TYPES


def _hex(v: int | None) -> str:
    return "none" if v is None else f"0x{v:08x}"


def _bl1_entry(words: list[int]) -> int | None:
    """Entry address from the two INFO_EXT words after STARTING_BL1, high half first."""
    start = (_TYPE_INFO << 24) | (_STATUS_ID_BL0 << 16) | _MSG_STARTING_BL1
    if start not in words:
        return None
    ext = [w & 0xFFFF for w in words[words.index(start) + 1 :] if w >> 24 == _TYPE_INFO_EXT]
    return (ext[0] << 16) | ext[1] if len(ext) >= 2 else None


def _store_lags(status, stores, period: int) -> tuple[list[int], int]:
    """Cycles from each status change back to the store that wrote it, and the unmatched count.

    Writes reach the register in retirement order, so each change matches the latest
    not-yet-matched store of the same value that retired before it.
    """
    lags: list[int] = []
    unmatched = 0
    j = 0
    for t, w in status:
        hit = None
        for k in range(j, len(stores)):
            if stores[k].t_ps >= t:
                break
            if stores[k].mem_data == w:
                hit = k
        if hit is None:
            unmatched += 1
            continue
        lags.append((t - stores[hit].t_ps) // period)
        j = hit + 1
    return lags, unmatched


@pyuvm.test()
class sep_rom_observer_smoke_test(sep_rom_observe_base):
    required_evidence = (
        "CHK-OBS-RETIRE",
        "CHK-OBS-KEEP",
        "CHK-OBS-RESET-VECTOR",
        "CHK-OBS-STATUS-ENCODE",
        "CHK-OBS-STORE-LAG",
        "CHK-OBS-CONSOLE",
        "CHK-OBS-MRET",
        "CHK-OBS-PC",
        "CHK-OBS-WATCH",
        "CHK-OBS-TRACKER",
        "CHK-OBS-VERDICT",
    )

    @property
    def observer_kwargs(self) -> dict:
        return {
            "pc_window": (_SPEC_ROM_BASE, _SPEC_ROM_BASE + _SPEC_ROM_SIZE),
            "pc_watch": frozenset({self.syms["rom_main"]}),
            "watch": (_RUN_REQ,),
        }

    async def run_scenario(self) -> None:
        self.syms = load_rom_syms()
        self.mon_at_stop: tuple[int, int] | None = None
        await super().run_scenario()

    def done(self, obs) -> bool:
        hit = super().done(obs)
        if hit:
            self.mon_at_stop = (self.cpu_trace_mon.trace_count, obs.retired)
        return hit

    def grade(self, obs, chk) -> None:
        mret = obs.pre_mret[-1] if obs.pre_mret else None
        mret_t = mret.t_ps if mret is not None else -1
        post = obs.post_mret
        period = (post.t_ps - obs.first[0].t_ps) // (post.cycle - obs.first[0].cycle) if post else 1

        # cpu_trace_mon counts the same trace at the clk_i edge, before the ReadOnly sample.
        mon, seen = self.mon_at_stop or (-1, -1)
        chk.ok(
            "OBS-RETIRE",
            self.mon_at_stop is not None and abs(mon - seen) <= 1 and not obs.traps,
            retired=seen,
            cpu_trace_mon=mon,
            traps=len(obs.traps),
        )
        kept = [r.insn for r in obs.retires]
        chk.ok(
            "OBS-KEEP",
            any(is_store(i) for i in kept)
            and any(is_fence(i) or is_fence_i(i) for i in kept)
            and any(opcode(i) == OP_SYSTEM for i in kept),
            stores=sum(is_store(i) for i in kept),
            fences=sum(is_fence(i) or is_fence_i(i) for i in kept),
            system=sum(opcode(i) == OP_SYSTEM for i in kept),
        )
        first_pc = obs.first[0].pc if obs.first else None
        chk.ok(
            "OBS-RESET-VECTOR",
            first_pc == _SPEC_ROM_BASE == self.syms["_start"] and len(obs.first) == 256,
            first_pc=_hex(first_pc),
            start_sym=_hex(self.syms["_start"]),
            head=len(obs.first),
        )

        # Lane proof: these words carry the STATUS_ENCODE BL0 layout, so they are cold_scratch[1].
        pre = [(t, w) for t, w in obs.status[1:] if t < mret_t]
        good = [w for _, w in pre if w and _bl0_status(w)]
        chk.ok(
            "OBS-STATUS-ENCODE",
            len(good) > 5,
            bl0_words=len(good),
            other_words=sum(1 for _, w in pre if w and not _bl0_status(w)),
            last_pre_mret=_hex(pre[-1][1] if pre else None),
        )
        stores = [
            r
            for r in obs.retires
            if is_store(r.insn) and r.mem_addr == _SPEC_COLD_SCRATCH_1 and r.t_ps < mret_t
        ]
        lags, unmatched = _store_lags(pre, stores, period)
        chk.ok(
            "OBS-STORE-LAG",
            len(lags) >= 10 and all(1 <= lag <= STORE_LAG_MAX_CYCLES for lag in lags),
            matched=len(lags),
            unmatched=unmatched,
            stores=len(stores),
            min_cycles=min(lags, default=-1),
            max_cycles=max(lags, default=-1),
            bound=STORE_LAG_MAX_CYCLES,
        )

        manifest_t = obs.line_t("MANIFEST_OK")
        jump = next((m for m in map(_BL1_JUMP.search, obs.lines()) if m), None)
        jump_pc = int(jump.group(1), 16) if jump else None
        chk.ok(
            "OBS-CONSOLE",
            manifest_t is not None
            and manifest_t < mret_t
            and post is not None
            and jump_pc == post.pc,
            lines=len(obs.console),
            manifest_ok_ps=manifest_t if manifest_t is not None else -1,
            bl1_jump=_hex(jump_pc),
        )
        entry = _bl1_entry([w for _, w in pre])
        chk.ok(
            "OBS-MRET",
            len(obs.pre_mret) == 64
            and mret is not None
            and mret.insn == INSN_MRET
            and post is not None
            and post.pc == entry,
            pre_mret=len(obs.pre_mret),
            mret_pc=_hex(mret.pc if mret else None),
            post_mret_pc=_hex(post.pc if post else None),
            status_entry=_hex(entry),
        )
        chk.ok(
            "OBS-PC",
            bool(obs.pc_hits) and not obs.outside_window,
            rom_main_hits=len(obs.pc_hits),
            outside_window=len(obs.outside_window),
        )

        # bring_up_cpu_boot holds the run request for RUN_PULSE_CYCLES clk cycles.
        req = obs.watched[_RUN_REQ]
        rise = next((t for t, v in req if v == 1), None)
        fall = next((t for t, v in req if v == 0 and rise is not None and t > rise), None)
        width = (fall - rise) // period if rise is not None and fall is not None else -1
        chk.ok(
            "OBS-WATCH",
            [v for _, v in req] == [0, 1, 0] and width == RUN_PULSE_CYCLES,
            changes=len(req),
            width_cycles=width,
            expect=RUN_PULSE_CYCLES,
        )
        pmp0 = [r.csr_value for r in obs.csr_writes(CSR_PMPADDR0)]
        chk.ok(
            "OBS-TRACKER",
            bool(pmp0) and all(v == _SPEC_PMPADDR0 for v in pmp0),
            pmpaddr0=[_hex(v) for v in pmp0],
            expect=_hex(_SPEC_PMPADDR0),
        )
        word = obs.verdict[-1][1] if obs.verdict else None
        chk.ok(
            "OBS-VERDICT",
            obs.verdict_pass() is True and word == TEST_PASS_CODE,
            verdict=_hex(word),
        )
