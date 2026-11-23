# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Boot ROM PMP release and jump to BL1, graded on the retirements up to the hand-off mret.

rom.adoc, Physical Memory Protection and Execution Fencing:

* SEP-ROM-PMP-010: "From PMP programming (before the first C instruction) until the hand-off
  release (<<sec:handoff>>), instruction fetch shall be possible only from the Boot ROM region
  (`0x1004_0000`, 64 KiB). A fetch from any other region shall trap (fatal, per
  SEP-ROM-CPU-070)."
* SEP-ROM-PMP-030: "The regions that will hold next-stage code (SEP SRAM and ICCM) shall be
  writable but *non-executable* (`RW-`) for the entire validation portion of the boot. Execute
  permission for whichever region BL1 was loaded into shall be granted only at hand-off, after
  the pre-hand-off self-check passes."
* SEP-ROM-PMP-080: "The hand-off release (SEP-ROM-HOFF-060) shall be implemented as a single
  rewrite of the locked BL1-region rule from `RW-` to executable — legal only while
  `mseccfg.RLB=1` — executed strictly after the pre-hand-off self-check passes. The ROM shall
  not clear `mseccfg.MMWP` (it cannot) and shall not modify any other rule at release."
  "The disposition of `mseccfg.RLB` at the jump itself — leave set for BL1 to manage its own
  fencing of BL2, or clear to freeze the rule set — is a deferred sub-decision owned by the
  BL1 specification; verification shall parameterize it."

rom.adoc, Hand-off to BL1, Release and Jump:

* SEP-ROM-HOFF-060: "Only after the self-check passes shall the ROM release the PMP execution
  fence for the region BL1 was loaded into — a single rewrite of the locked BL1-region rule
  under `mseccfg.RLB=1` (SEP-ROM-PMP-080, <<sec:pmp_mechanism>>). The release shall be the
  last write before the jump sequence."
* Item 2 of the same list: "The BL1 image is copied from its staged payload location to its TOC
  entry's `load_addr`, and control transfers to `load_addr + entry_point`
  (SEP-ROM-MAN-050/-060)."
* SEP-ROM-HOFF-070: "The jump shall order memory correctly for freshly written code:
  `mepc ← entry`, `fence.i` (IFU sees the new SRAM contents), `fence` (stores complete), then
  `mret`. The ROM never expects control back; the only re-entry paths are cold reset and the
  warm-reset protocol (<<sec:warm_reset>>)."

The release window opens at the BOOTROM_PRESTART_DONE ("PMP programmed") status, so this leaf
and sep_rom_pmp_program_test together see every PMP and mseccfg write before the hand-off mret.
The BL1-region rule is the lowest-numbered active rule, replayed from the trace, that covers
the BL1 entry the manifest TOC gives. An mseccfg write that changes MMWP or MML or sets RLB is a
rule-set change; one whose only effect is clearing RLB is the parameterized RLB disposition,
accepted and logged as OBS-RLB-AT-JUMP.

PMP-010 "possible only from the Boot ROM region" is carried at rule level by
sep_rom_pmp_program_test ONLY-ROM-EXEC plus SINGLE-RELEASE here; FETCH-ROM-ONLY is the
behavioural part: no retirement outside the Boot ROM from the first PMP write to the release.

Partial coverage of "after the self-check passes" (HOFF-060, PMP-030, PMP-080): the release is
graded only as following the progress codes MANIFEST_VALIDATED, FUSE_SECRETS_LOCKED and the
[S29] entry code HANDOFF_CHECK. The "passes" clause is logged as blocked: no spec status reports
a passed self-check, and the gate-ledger self-check is not on this tree (rom.adoc gap note).

HOFF-060 "last write" is graded on CSR writes after the release; the stores are listed as OBS.

The jump sequence is graded on order, which is what the spec lists; adjacency is reported.

Not graded: the fetch trap of PMP-010, the first sentence of PMP-030 beyond "no PMP write
between the cold rule set and the release", the BL1 copy itself, the mepc operand (its
register is not a tracked constant; the post-mret PC grades the entry) and "never expects
control back".
"""

from __future__ import annotations

import re

import cocotb
import pyuvm
from env import sep_manifest_mutate as mm
from env import sep_payload_mutate as pm
from env.sep_rom_observer import STORE_LAG_MAX_CYCLES
from env.sep_rv32_trace_decode import (
    CSR_MEPC,
    CSR_MSECCFG,
    CSR_PMPADDR0,
    CSR_PMPCFG0,
    INSN_MRET,
    MSECCFG_MML,
    MSECCFG_MMWP,
    MSECCFG_RLB,
    PMPCFG_A_MASK,
    PMPCFG_A_NAPOT,
    PMPCFG_L,
    PMPCFG_R,
    PMPCFG_W,
    PMPCFG_X,
    decode_csr,
    is_fence,
    is_fence_i,
    is_store,
    pmp_napot,
)
from env.sep_smc_mem import SMC_MANIFEST_OFFSET_DEFAULT, load_verilog_hex
from rom_fw.sep_rom_observe_base import sep_rom_observe_base

# Boot ROM region, the only executable region before the release.
_ROM_LO = 0x1004_0000
_ROM_HI = _ROM_LO + (64 << 10)
# RV_PMP_ENTRIES of the fitted core (rom.adoc, Fence Binding and Release Mechanism).
_PMP_ENTRIES = 16
_A_NA4 = 2 << 3
# SEP view of the SMC SRAM window the packed manifest+BL1 image is loaded at.
_SMC_SRAM_BASE = 0x4006_0000
# STATUS_ENCODE(type, BL0 1, code); codes from hw/sys/sep/doc/gen/status_values.adoc.
_STATUS_PRESTART_DONE = 0x8001_0056
_STATUS_STARTING_BL1 = 0x0101_0043
_TYPE_INFO_EXT = 0x81
_PROGRESS_STATUS = (
    ("MANIFEST_VALIDATED", 0x0101_0053),
    ("FUSE_SECRETS_LOCKED", 0x0101_021C),
    ("HANDOFF_CHECK", 0x8001_0208),
)
# FENCE pred field bit PW: prior stores are ordered.
_FENCE_PRED_W = 1 << 24
_JUMP_RE = re.compile(r"BL1_JUMP=0x([0-9a-fA-F]{8})")
_CFG_LO, _CFG_HI = CSR_PMPCFG0, CSR_PMPCFG0 + 15
_ADDR_LO, _ADDR_HI = CSR_PMPADDR0, CSR_PMPADDR0 + 63
_OUTSIDE_CAP = 32


def _hex(v: int | None) -> str:
    return "none" if v is None else f"0x{v:08x}"


def _apply(old: int | None, kind: str, value: int | None) -> int | None:
    """CSR value after a csrrw, csrrs or csrrc with a known or unknown operand."""
    if value is None or (kind != "rw" and old is None):
        return None
    return value if kind == "rw" else old | value if kind == "rs" else old & ~value


def _in_rom(pc: int) -> bool:
    return _ROM_LO <= pc < _ROM_HI


def _status_entry(words: list[int]) -> int | None:
    """Entry address from the two INFO_EXT words after STARTING_BL1, high half first."""
    if _STATUS_STARTING_BL1 not in words:
        return None
    tail = words[words.index(_STATUS_STARTING_BL1) + 1 :]
    ext = [w & 0xFFFF for w in tail if w >> 24 == _TYPE_INFO_EXT]
    return (ext[0] << 16) | ext[1] if len(ext) >= 2 else None


def _toc_entry(path) -> tuple[int | None, str]:
    """load_addr + entry_point of the BL1 TOC entry in the packed SMC image, and its summary."""
    if not isinstance(path, str):
        return None, f"no +sep_smc_mem_hex ({path!r})"
    buf = bytearray()
    for addr, data in load_verilog_hex(path):
        off = addr - _SMC_SRAM_BASE
        buf.extend(b"\xff" * max(off + len(data) - len(buf), 0))
        buf[off : off + len(data)] = data
    slot = "primary"
    if mm.slot_base(slot) != SMC_MANIFEST_OFFSET_DEFAULT or pm.is_encrypted(buf, slot):
        return None, f"manifest not at 0x{SMC_MANIFEST_OFFSET_DEFAULT:x} or payload encrypted"
    entry = pm.bl1_field(buf, slot, pm.E_LOAD_ADDR) + pm.bl1_field(buf, slot, pm.E_ENTRY_POINT)
    return entry, pm.describe_bl1(buf, slot)


def _covering_rule(target, cfg_reg, addr) -> tuple[int, int, int] | None:
    """(entry, base, size) of the lowest-numbered active PMP rule that covers target."""
    if target is None:
        return None
    for i in range(_PMP_ENTRIES):
        reg = cfg_reg.get(_CFG_LO + i // 4, 0)
        if reg is None:
            return None
        a = (reg >> (8 * (i % 4))) & PMPCFG_A_MASK
        if not a:
            continue
        cur = addr.get(i)
        prev = addr.get(i - 1, 0) if i else 0
        if cur is None or prev is None:
            return None
        if a == PMPCFG_A_NAPOT:
            base, size = pmp_napot(cur)
        elif a == _A_NA4:
            base, size = cur << 2, 4
        else:
            base, size = prev << 2, max((cur - prev) << 2, 0)
        if base <= target < base + size:
            return i, base, size
    return None


def _desc(r) -> str:
    op = decode_csr(r.insn)
    return f"{_hex(r.pc)}:csr{op.kind}:0x{op.csr:03x}={_hex(r.csr_value)}"


@pyuvm.test()
class sep_rom_pmp_release_handoff_test(sep_rom_observe_base):
    required_evidence = (
        "CHK-FETCH-ROM-ONLY",
        "CHK-SINGLE-RELEASE",
        "CHK-RELEASE-ADDS-ONLY-X",
        "CHK-RELEASE-UNDER-RLB",
        "CHK-RELEASE-AFTER-PROGRESS",
        "CHK-RELEASE-LAST-CSR-WRITE",
        "CHK-JUMP-SEQUENCE",
        "CHK-JUMP-TARGET",
    )
    observer_kwargs = {"pc_window": (_ROM_LO, _ROM_HI)}

    def grade(self, obs, chk) -> None:
        mret = obs.pre_mret[-1] if obs.pre_mret else None
        mret_t = mret.t_ps if mret is not None else -1
        post = obs.post_mret
        prestart_t = obs.status_t(_STATUS_PRESTART_DONE)
        chk.ctrl(
            "HANDOFF-WINDOW",
            mret is not None and prestart_t is not None and prestart_t < mret_t,
            prestart_ps=prestart_t if prestart_t is not None else -1,
            mret_ps=mret_t,
        )
        start = prestart_t if prestart_t is not None else mret_t + 1
        toc_entry, toc_desc = _toc_entry(cocotb.plusargs.get("sep_smc_mem_hex"))
        chk.ctrl("TOC-ENTRY", toc_entry is not None, entry=_hex(toc_entry), toc=toc_desc)

        rules_w = [r for r in obs.csr_writes(_CFG_LO, _ADDR_HI) if r.t_ps <= mret_t]
        sec_w = [r for r in obs.csr_writes(CSR_MSECCFG) if r.t_ps <= mret_t]
        late_rules = [r for r in rules_w if r.t_ps >= start]
        sec = 0
        rlb_clears, late_sec = [], []
        for r in sec_w:
            new = _apply(sec, decode_csr(r.insn).kind, r.csr_value)
            if r.t_ps >= start:
                known = sec is not None and new is not None
                diff = (sec ^ new) if known else ~0
                if not known or diff & (MSECCFG_MMWP | MSECCFG_MML) or new & ~sec & MSECCFG_RLB:
                    late_sec.append(r)
                elif diff & MSECCFG_RLB:
                    rlb_clears.append(r)
            sec = new
        rel = late_rules[0] if len(late_rules) == 1 else None
        chk.ok(
            "SINGLE-RELEASE",
            rel is not None and decode_csr(rel.insn).csr <= _CFG_HI and not late_sec,
            rule_writes=[_desc(r) for r in late_rules],
            mseccfg_rule_changes=[_desc(r) for r in late_sec],
        )
        rel_t = rel.t_ps if rel is not None else mret_t
        chk.obs(
            "RLB-AT-JUMP",
            cleared=bool(rlb_clears),
            rlb_clear_writes=[_desc(r) for r in rlb_clears],
            mseccfg=_hex(sec),
        )

        # Rule set in force just before the release.
        cfg: dict[int, int | None] = {}
        addr: dict[int, int | None] = {}
        for r in rules_w:
            if r.t_ps >= rel_t:
                continue
            op = decode_csr(r.insn)
            if op.csr <= _CFG_HI:
                cfg[op.csr] = _apply(cfg.get(op.csr, 0), op.kind, r.csr_value)
            else:
                i = op.csr - _ADDR_LO
                addr[i] = _apply(addr.get(i, 0), op.kind, r.csr_value)
        rule = _covering_rule(toc_entry, cfg, addr)
        want_csr = byte = old = new = old_b = None
        if rule is not None:
            want_csr, byte = _CFG_LO + rule[0] // 4, rule[0] % 4
        if rel is not None:
            op = decode_csr(rel.insn)
            old = cfg.get(op.csr, 0)
            new = _apply(old, op.kind, rel.csr_value)
        if old is not None and byte is not None:
            old_b = (old >> (8 * byte)) & 0xFF
        rw_locked = PMPCFG_L | PMPCFG_R | PMPCFG_W
        chk.ok(
            "RELEASE-ADDS-ONLY-X",
            rel is not None
            and want_csr is not None
            and decode_csr(rel.insn).csr == want_csr
            and old_b is not None
            and new is not None
            and old_b & (rw_locked | PMPCFG_X) == rw_locked
            and bool(old_b & PMPCFG_A_MASK)
            and new ^ old == PMPCFG_X << (8 * byte),
            bl1_entry=_hex(toc_entry),
            bl1_rule=rule[0] if rule else -1,
            rule_base=_hex(rule[1] if rule else None),
            rule_size=_hex(rule[2] if rule else None),
            want_csr=_hex(want_csr),
            release=_desc(rel) if rel else "none",
            before=_hex(old),
            after=_hex(new),
        )

        sec_at = 0
        for r in sec_w:
            if r.t_ps < rel_t:
                sec_at = _apply(sec_at, decode_csr(r.insn).kind, r.csr_value)
        chk.ok(
            "RELEASE-UNDER-RLB",
            rel is not None
            and sec_at is not None
            and bool(sec_at & MSECCFG_RLB)
            and bool(sec_at & MSECCFG_MMWP),
            mseccfg_at_release=_hex(sec_at),
        )
        # BL1 fetches from a rule the cold set left RW- under MMWP only if the release took effect.
        chk.ctrl(
            "RELEASE-EFFECT",
            post is not None
            and not (post.exc or post.interrupt)
            and rule is not None
            and rule[1] <= post.pc < rule[1] + rule[2]
            and obs.verdict_pass() is True,
            post_mret_pc=_hex(post.pc if post else None),
            verdict_pass=bool(obs.verdict_pass()),
        )

        # A status record trails its store, so a record before the release proves the store was.
        marks = [
            (name, max((t for t, w in obs.status if w == word and t < mret_t), default=None))
            for name, word in _PROGRESS_STATUS
        ]
        chk.ok(
            "RELEASE-AFTER-PROGRESS",
            rel is not None and all(t is not None and t < rel.t_ps for _, t in marks),
            markers=[f"{n}@{t if t is not None else -1}" for n, t in marks],
            release_ps=rel.t_ps if rel else -1,
        )
        chk.blocked(
            "RELEASE-AFTER-SELF-CHECK-PASSES",
            "no spec status reports a passed self-check; the gate ledger is not on this tree",
        )

        kept = [r for r in obs.retires if r.t_ps <= mret_t]
        mepc = next(
            (
                r
                for r in reversed(kept)
                if (op := decode_csr(r.insn)) is not None and op.csr == CSR_MEPC and op.kind == "rw"
            ),
            None,
        )
        after = [r for r in kept if mepc is not None and r.t_ps > mepc.t_ps]
        fi = next((r for r in after if is_fence_i(r.insn)), None)
        fe = next(
            (
                r
                for r in after
                if fi is not None
                and r.t_ps > fi.t_ps
                and is_fence(r.insn)
                and r.insn & _FENCE_PRED_W
            ),
            None,
        )
        tail = [r.insn for r in obs.pre_mret[-4:]]
        seq = [r.insn for r in (mepc, fi, fe) if r is not None] + [INSN_MRET]
        chk.ok(
            "JUMP-SEQUENCE",
            mepc is not None
            and fi is not None
            and fe is not None
            and mret is not None
            and mret.insn == INSN_MRET
            and fe.t_ps < mret_t,
            mepc=_hex(mepc.pc if mepc else None),
            fence_i=_hex(fi.pc if fi else None),
            fence_w=_hex(fe.insn if fe else None),
            mret=_hex(mret.pc if mret else None),
            adjacent=tail == seq,
        )

        seq_t = mepc.t_ps if mepc is not None else mret_t
        span = [r for r in kept if rel is not None and rel.t_ps < r.t_ps < seq_t]
        csr_w = [
            r
            for r in span
            if (op := decode_csr(r.insn)) is not None and op.writes and r not in rlb_clears
        ]
        chk.ok(
            "RELEASE-LAST-CSR-WRITE",
            rel is not None and not csr_w,
            csr_writes_after_release=[_desc(r) for r in csr_w],
            rlb_clears=len([r for r in span if r in rlb_clears]),
        )
        head = obs.first
        period = (head[-1].t_ps - head[0].t_ps) // max(head[-1].cycle - head[0].cycle, 1)
        # Console lines whose stores retired before the mret, allowing for the record lag.
        lag_end = mret_t + STORE_LAG_MAX_CYCLES * period
        stores = [r for r in span if is_store(r.insn)]
        chk.obs(
            "STORES-AFTER-RELEASE",
            count=len(stores),
            stores=[f"{_hex(r.pc)}->{_hex(r.mem_addr)}" for r in stores[:12]],
            console_before_jump=[
                line for t, line in obs.console if rel and rel.t_ps < t <= lag_end
            ],
        )

        status_entry = _status_entry([w for t, w in obs.status if t < mret_t])
        chk.ok(
            "JUMP-TARGET",
            post is not None
            and toc_entry is not None
            and not (post.exc or post.interrupt)
            and post.pc == toc_entry == status_entry,
            post_mret_pc=_hex(post.pc if post else None),
            toc_entry=_hex(toc_entry),
            status_entry=_hex(status_entry),
        )
        jump = next((m for m in map(_JUMP_RE.search, obs.lines()) if m), None)
        chk.obs("CONSOLE-BL1-JUMP", value=_hex(int(jump.group(1), 16) if jump else None))

        pmp_t = min((r.t_ps for r in rules_w + sec_w), default=None)
        chk.ctrl(
            "WINDOW-LIVE",
            post is not None
            and not _in_rom(post.pc)
            and len(obs.pre_mret) == 64
            and all(_in_rom(r.pc) for r in obs.pre_mret)
            and bool(obs.first)
            and all(_in_rom(r.pc) for r in obs.first if r.t_ps <= mret_t),
            first=len(obs.first),
            pre_mret=len(obs.pre_mret),
            post_mret_pc=_hex(post.pc if post else None),
        )
        fenced = [r for r in obs.outside_window if pmp_t is not None and pmp_t <= r.t_ps <= rel_t]
        chk.ok(
            "FETCH-ROM-ONLY",
            pmp_t is not None
            and rel is not None
            and not fenced
            and len(obs.outside_window) < _OUTSIDE_CAP,
            pmp_programmed_ps=pmp_t if pmp_t is not None else -1,
            release_ps=rel_t,
            outside=[_hex(r.pc) for r in fenced[:8]],
            outside_total=len(obs.outside_window),
        )
