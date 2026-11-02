# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Things the Boot ROM must never do during a boot to a BL1 PASS, graded up to the hand-off mret.

rom.adoc, Cold Boot Environment Setup and Watchdog Posture:

* SEP-ROM-CPU-040: "The SEP outbound AXI filter shall block all egress by default; the ROM
  shall open no outbound window at all. All ROM status and verdict reporting stays on
  `cold_scratch`."
* SEP-ROM-CPU-050: "Interrupts shall remain disabled for the entire ROM execution: `mie` is
  cleared and `mstatus.MIE` is cleared at entry, and no ROM stage re-enables them."
* SEP-ROM-CPU-080: "The ROM shall not arm the watchdog timer. WDT ownership belongs to BL1;
  the ROM's only WDT-related obligation is the warm-reset re-entry protocol."
* SEP-ROM-CPU-150: "The stack and the C globals shall live in DCCM. The stub sets the stack
  pointer to `__stack_top` and the global pointer to `__global_pointer$`, both placed in DCCM
  by the linker script `link/rom.ld`."

CPU-040 is covered in part: "open no outbound window", as no CPU write to any
OUTBOUND_FILTER_CTRL register; default-deny and cold_scratch-only reporting are not graded.
CPU-050 "at entry" is graded at its place in the cold-boot list, after the "entered `_start`"
status store and before the PMP programming; a write that sets mstatus.MPIE counts as a
re-enable, and the MPIE reset value is not graded.
Every check ends at the hand-off mret; the absence checks are zero-event observations whose
controls prove only that the record is live.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ReadOnly, RisingEdge
from cocotb.utils import get_sim_time
from env.sep_fabric_tap import SepFabricTap
from env.sep_rom_observer import keep_system_fence_store, load_rom_syms
from env.sep_rv32_trace_decode import (
    CSR_MEPC,
    CSR_MIE,
    CSR_MSECCFG,
    CSR_MSTATUS,
    CSR_MTVEC,
    CSR_PMPADDR0,
    CSR_PMPCFG0,
    INSN_MRET,
    MASK32,
    MSTATUS_MIE,
    OP_AUIPC,
    decode_csr,
    is_fence,
    is_fence_i,
    is_store,
    opcode,
    writes_rd,
)
from env.sep_tcm_flip import DCCM_BASE, DCCM_BYTES
from rom_fw.sep_rom_observe_base import sep_rom_observe_base
from sep_reg_meta import sym

_SP = 2
_GP = 3
_HEAD = 512
_DCCM_END = DCCM_BASE + DCCM_BYTES
_WDT_LO = sym("WDT_TIMER_REG_MAP_BASE_ADDR")
_WDT_HI = _WDT_LO + sym("WDT_TIMER_REG_MAP_SIZE")
_COLD_LO = sym("SEP_SCRATCH_COLD_REG_MAP_BASE_ADDR")
_COLD_HI = _COLD_LO + sym("SEP_SCRATCH_COLD_REG_MAP_SIZE")
_COLD_1 = sym("SEP_SCRATCH_COLD_SCRATCH_1__REG_ADDR")
# STATUS_ENCODE(DEBUG 0x80, BL0 1, SEP_MSG_BOOTROM_START 0x44 in rom.adoc tbl:sep_msg_codes).
_STATUS_ENTERED_START = 0x8001_0044
# STATUS_ENCODE(INFO 0x01, BL0 1, SEP_MSG_STARTING_BL1 0x43 in rom.adoc tbl:sep_msg_codes).
_STATUS_STARTING_BL1 = 0x0101_0043
_TYPE_INFO_EXT = 0x81
_MSTATUS_MPIE = 1 << 7
# mseccfg, pmpcfg0..15 and pmpaddr0..63: the PMP programming that follows the clear.
_PMP_CSRS = frozenset({CSR_MSECCFG, *range(CSR_PMPCFG0, CSR_PMPADDR0 + 64)})
_WDT_PORTS = ("wdt_wdog_count_o", "wdt_bark_probe_o", "wdt_alert_probe_o")
# Linker symbols that bound the stack, the global pointer, .data and .bss.
_DCCM_SYMS = (
    "__stack_top",
    "__stack_bottom",
    "__global_pointer$",
    "__data_start",
    "__data_end",
    "__bss_start",
    "__bss_end",
)
_VECTOR_SYMS = ("trap_vector_early", "trap_vector")


def _filter_window() -> tuple[int, int]:
    """Address span of every OUTBOUND_FILTER_CTRL_n slot in the RDL map."""
    last = 0
    while True:
        try:
            sym(f"OUTBOUND_FILTER_CTRL_{last + 1}__REG_MAP_BASE_ADDR")
        except KeyError:
            break
        last += 1
    lo = sym("OUTBOUND_FILTER_CTRL_0__REG_MAP_BASE_ADDR")
    hi = sym(f"OUTBOUND_FILTER_CTRL_{last}__REG_MAP_BASE_ADDR")
    return lo, hi + sym(f"OUTBOUND_FILTER_CTRL_{last}__REG_MAP_SIZE")


_FILTER_LO, _FILTER_HI = _filter_window()


def _keep(insn: int) -> bool:
    # sp and gp writers are kept so a write the tracker cannot resolve is still counted.
    return keep_system_fence_store(insn) or writes_rd(insn) in (_SP, _GP)


def _trapped(r) -> bool:
    return r.exc or r.interrupt


def _sets_mie(r) -> bool:
    op = decode_csr(r.insn)
    if _trapped(r) or op is None or not op.writes or op.kind == "rc":
        return False
    if op.csr == CSR_MIE:
        return r.csr_value is None or r.csr_value != 0
    if op.csr == CSR_MSTATUS:
        return r.csr_value is None or bool(r.csr_value & (MSTATUS_MIE | _MSTATUS_MPIE))
    return False


def _writes_csr(r, csrs) -> bool:
    op = decode_csr(r.insn)
    return not _trapped(r) and op is not None and op.writes and op.csr in csrs


def _clears_mstatus_mie(r) -> bool:
    op = decode_csr(r.insn)
    if op is None or op.csr != CSR_MSTATUS or not op.writes or r.csr_value is None:
        return False
    if op.kind == "rc":
        return bool(r.csr_value & MSTATUS_MIE)
    return op.kind == "rw" and not r.csr_value & MSTATUS_MIE


def _clears_mie_reg(r) -> bool:
    op = decode_csr(r.insn)
    if op is None or op.csr != CSR_MIE or not op.writes or r.csr_value is None:
        return False
    return (op.kind == "rw" and r.csr_value == 0) or (op.kind == "rc" and r.csr_value == MASK32)


def _first(seq, pred) -> int | None:
    return next((i for i, r in enumerate(seq) if pred(r)), None)


def _between(lo: int | None, idx: int | None, hi: int | None) -> bool:
    return None not in (lo, idx, hi) and lo < idx < hi


def _in_dccm(v: int | None) -> bool:
    # A stack top or section end may equal the end of DCCM.
    return v is not None and DCCM_BASE <= v <= _DCCM_END


def _hex(v: int | None) -> str:
    return "none" if v is None else f"0x{v:08x}"


def _bl1_entry(words: list[int]) -> int | None:
    """Entry address from the two INFO_EXT words after STARTING_BL1, high half first."""
    if _STATUS_STARTING_BL1 not in words:
        return None
    after = words[words.index(_STATUS_STARTING_BL1) + 1 :]
    ext = [w & 0xFFFF for w in after if w >> 24 == _TYPE_INFO_EXT]
    return (ext[0] << 16) | ext[1] if len(ext) >= 2 else None


def _handoff_tail(ring) -> bool:
    """The ring ends with the hand-off sequence: mepc write, fence.i, fence, mret."""
    if len(ring) < 4:
        return False
    mepc, fi, fe, mret = (r.insn for r in ring[-4:])
    op = decode_csr(mepc)
    return (
        op is not None
        and op.csr == CSR_MEPC
        and op.writes
        and is_fence_i(fi)
        and is_fence(fe)
        and mret == INSN_MRET
    )


def _value_at(records: list[tuple[int, int]], t: int) -> int | None:
    """Value of a watched port in force at time t."""
    v = None
    for rt, rv in records:
        if rt > t:
            break
        v = rv
    return v


@pyuvm.test()
class sep_rom_boot_quiet_invariants_test(sep_rom_observe_base):
    required_evidence = (
        "CHK-NO-FILTER-WRITE",
        "CHK-NO-IRQ",
        "CHK-NO-MIE-SET",
        "CHK-MIE-CLEAR-ORDER",
        "CHK-NO-WDT",
        "CHK-STACK-GLOBALS-DCCM",
    )

    @property
    def observer_kwargs(self) -> dict:
        return {
            "keep": _keep,
            "head": _HEAD,
            "watch": _WDT_PORTS,
            "pc_watch": frozenset(self.vectors | {self.syms["_start"]}),
        }

    async def run_scenario(self) -> None:
        self.syms = load_rom_syms()
        self.wdt_known: list[bool] = []
        self.vectors = frozenset(self.syms[n] for n in _VECTOR_SYMS)
        # Both taps start before reset release so the first ROM access is in the record.
        self.tap_start_ps = int(get_sim_time("ps"))
        self.out_tap = SepFabricTap("PR-OUT").start()
        self.lsu_tap = SepFabricTap("PR-LSU-XBAR").start()
        self.out_mark = self.out_tap.mark()
        self.lsu_mark = self.lsu_tap.mark()
        await super().run_scenario()

    def _sample_wdt_known(self) -> None:
        dut = cocotb.top
        self.wdt_known.append(all(getattr(dut, n).value.is_resolvable for n in _WDT_PORTS))

    async def stimulus(self, obs) -> None:
        # The observer reads the WDT ports with X as 0, so known-ness is sampled here.
        await RisingEdge(cocotb.top.cpu_trace_valid_o)
        await ReadOnly()
        self._sample_wdt_known()

    async def before_grade(self, obs) -> None:
        self._sample_wdt_known()
        # The taps sample every clk_i edge until stop, so this is their last sample time.
        self.tap_stop_ps = int(get_sim_time("ps"))
        await self.out_tap.stop()
        await self.lsu_tap.stop()

    def _tap_covers(self, tap: SepFabricTap, obs, handoff_t: int | None) -> bool:
        return (
            handoff_t is not None
            and bool(obs.first)
            and bool(tap.stop_clk)
            and self.tap_start_ps <= obs.first[0].t_ps
            and self.tap_stop_ps >= handoff_t
        )

    def grade(self, obs, chk) -> None:
        syms = self.syms
        mret = obs.pre_mret[-1] if obs.pre_mret else None
        handoff_t = mret.t_ps if mret is not None else None
        bl1_pc = obs.post_mret.pc if obs.post_mret else None
        entry = _bl1_entry(obs.statuses())
        tail = _handoff_tail(obs.pre_mret)
        # The window ends at the hand-off only if the mret is the ROM's jump to the BL1 entry.
        live = (
            handoff_t is not None
            and tail
            and bl1_pc is not None
            and bl1_pc == entry
            and obs.verdict_pass() is True
        )

        def in_rom(t: int) -> bool:
            return live and t <= handoff_t

        chk.ctrl(
            "HANDOFF",
            live,
            handoff_ps=handoff_t if handoff_t is not None else -1,
            tail=tail,
            bl1_pc=_hex(bl1_pc),
            status_entry=_hex(entry),
            verdict=obs.verdict_pass(),
        )

        out_beats = [b for b in self.out_tap.since(self.out_mark) if in_rom(b.t_ps)]
        chk.obs(
            "PR-OUT-BEATS",
            covered=self._tap_covers(self.out_tap, obs, handoff_t),
            tap_ps=f"{self.tap_start_ps}..{self.tap_stop_ps}",
            beats=len(out_beats),
            first=[b.fmt() for b in out_beats[:4]],
        )
        lsu_aw = [b for b in self.lsu_tap.since(self.lsu_mark, "aw") if in_rom(b.t_ps)]
        unknown_aw = sum(1 for b in lsu_aw if b.addr is None)
        cold_aw = sum(1 for b in lsu_aw if b.addr is not None and _COLD_LO <= b.addr < _COLD_HI)
        # cold_scratch writes prove the tap records ROM register writes with their address.
        lsu_live = self._tap_covers(self.lsu_tap, obs, handoff_t) and cold_aw > 0 and not unknown_aw
        chk.ctrl("LSU-AW-LIVE", lsu_live, aw=len(lsu_aw), cold_aw=cold_aw, unknown=unknown_aw)
        filt = [b.addr for b in lsu_aw if b.addr is not None and _FILTER_LO <= b.addr < _FILTER_HI]
        chk.ok(
            "NO-FILTER-WRITE",
            lsu_live and not filt,
            window=f"[{_hex(_FILTER_LO)},{_hex(_FILTER_HI)})",
            writes=len(filt),
            addrs=[_hex(a) for a in filt[:8]],
        )

        # No interrupt is taken and none is enabled before the hand-off.
        mtvec = [r for r in obs.csr_writes(CSR_MTVEC) if in_rom(r.t_ps)]
        installed = {r.csr_value for r in mtvec}
        # The watch sees an interrupt entry only if every installed vector is a watched direct one.
        vec_live = (
            live
            and bool(mtvec)
            and None not in installed
            and all(v & 3 == 0 and v in self.vectors for v in installed)
            and any(pc == syms["_start"] for _, pc in obs.pc_hits)
        )
        chk.ctrl(
            "VECTORS-WATCHED",
            vec_live,
            installed=sorted(_hex(v) for v in installed),
            watched=[_hex(v) for v in sorted(self.vectors)],
        )
        vec_hits = [pc for t, pc in obs.pc_hits if pc in self.vectors and in_rom(t)]
        irq = [r for r in obs.traps if r.interrupt and in_rom(r.t_ps)]
        chk.ok(
            "NO-IRQ",
            vec_live and not vec_hits and not irq,
            vector_entries=len(vec_hits),
            interrupt_traps=len(irq),
            pcs=[_hex(r.pc) for r in irq[:8]],
        )
        mie_w = [r for r in obs.retires if _writes_csr(r, {CSR_MIE}) and in_rom(r.t_ps)]
        ms_w = [r for r in obs.retires if _writes_csr(r, {CSR_MSTATUS}) and in_rom(r.t_ps)]
        # The record holds the mie and mstatus writes that NO-MIE-SET reasons over.
        csr_live = live and bool(mie_w) and bool(ms_w)
        chk.ctrl("CSR-RECORD-LIVE", csr_live, mie_writes=len(mie_w), mstatus_writes=len(ms_w))
        mie_set = [r for r in obs.retires if _sets_mie(r) and in_rom(r.t_ps)]
        chk.ok(
            "NO-MIE-SET",
            csr_live and not mie_set,
            writes=len(mie_set),
            pcs=[_hex(r.pc) for r in mie_set[:8]],
        )
        head = obs.first
        # The "entered _start" status store to cold_scratch[1] that precedes the clear.
        status = _first(
            head,
            lambda r: (
                is_store(r.insn)
                and not _trapped(r)
                and r.mem_addr == _COLD_1
                and r.mem_data == _STATUS_ENTERED_START
            ),
        )
        # The first PMP CSR write, which follows the clear.
        pmp = _first(head, lambda r: _writes_csr(r, _PMP_CSRS))
        # Indexes into the head are program order only if it starts at reset entry and holds both.
        chk.ctrl(
            "HEAD-RESET-ENTRY",
            bool(head) and head[0].pc == syms["_start"] and status is not None and pmp is not None,
            head=len(head),
            first_pc=_hex(head[0].pc if head else None),
            status_store=status,
            pmp_first=pmp,
        )
        ms = _first(head, _clears_mstatus_mie)
        mi = _first(head, _clears_mie_reg)
        last = max((i for i in (ms, mi) if i is not None), default=len(head))
        early_irq = sum(1 for r in head[: last + 1] if r.interrupt)
        chk.ok(
            "MIE-CLEAR-ORDER",
            _between(status, ms, pmp) and _between(status, mi, pmp) and not early_irq,
            status_store=status,
            mie_clear=mi,
            mstatus_mie_clear=ms,
            pmp_first=pmp,
            interrupts_before=early_irq,
            mie_clear_pc=_hex(head[mi].pc if mi is not None else None),
            mstatus_clear_pc=_hex(head[ms].pc if ms is not None else None),
        )

        # No WDT register write and no WDT count, bark or alert activity.
        wdt_aw = [b.addr for b in lsu_aw if b.addr is not None and _WDT_LO <= b.addr < _WDT_HI]
        t0 = obs.first[0].t_ps if obs.first else None
        ports = {}
        for name, recs in obs.watched.items():
            start = _value_at(recs, t0) if t0 is not None else None
            moves = sum(1 for t, _ in recs if t0 is not None and t0 < t and in_rom(t))
            ports[name] = (start, moves)
        port_live = (
            t0 is not None
            and self.wdt_known == [True, True]
            and all(start is not None for start, _ in ports.values())
        )
        chk.ctrl("WDT-PORTS-KNOWN", port_live, samples=self.wdt_known)
        quiet = all(start == 0 and moves == 0 for start, moves in ports.values())
        chk.ok(
            "NO-WDT",
            lsu_live and port_live and not wdt_aw and quiet,
            window=f"[{_hex(_WDT_LO)},{_hex(_WDT_HI)})",
            writes=len(wdt_aw),
            addrs=[_hex(a) for a in wdt_aw[:8]],
            ports=[f"{n}:start={_hex(s)}:moves={m}" for n, (s, m) in ports.items()],
        )

        # sp and gp hold DCCM addresses, and the linker places them in DCCM.
        bad_syms = [f"{n}={_hex(syms.get(n))}" for n in _DCCM_SYMS if not _in_dccm(syms.get(n))]
        known = {(t, reg): v for t, reg, v in obs.reg_writes if reg in (_SP, _GP) and in_rom(t)}
        writers = {
            (r.t_ps, writes_rd(r.insn)): r.insn
            for r in obs.retires
            if writes_rd(r.insn) in (_SP, _GP) and not _trapped(r) and in_rom(r.t_ps)
        }
        unresolved = [k for k in writers if k not in known]
        # An auipc of an la pair holds the pc-relative upper part, not the address the pair sets.
        held = {k: v for k, v in known.items() if opcode(writers.get(k, 0)) != OP_AUIPC}
        sp = [v for (_, reg), v in held.items() if reg == _SP]
        gp = [v for (_, reg), v in held.items() if reg == _GP]
        outside = sorted({v for v in sp + gp if not _in_dccm(v)})
        chk.ok(
            "STACK-GLOBALS-DCCM",
            live
            and not bad_syms
            and syms.get("__stack_top") in sp
            and syms.get("__global_pointer$") in gp
            and not outside
            and not unresolved,
            dccm=f"[{_hex(DCCM_BASE)},{_hex(_DCCM_END)}]",
            bad_syms=bad_syms,
            stack_top=_hex(syms.get("__stack_top")),
            global_pointer=_hex(syms.get("__global_pointer$")),
            sp_writes=len(sp),
            auipc_skipped=len(known) - len(held),
            gp_values=[_hex(v) for v in sorted(set(gp))],
            sp_range=f"{_hex(min(sp, default=None))}..{_hex(max(sp, default=None))}",
            outside=[_hex(v) for v in outside[:8]],
            unresolved=len(unresolved),
        )
