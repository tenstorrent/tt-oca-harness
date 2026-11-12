# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Boot ROM cold-boot PMP programming, graded on the CSR values and order the ROM writes.

rom.adoc, Physical Memory Protection and Execution Fencing:

* SEP-ROM-PMP-010: "From PMP programming (before the first C instruction) until the hand-off
  release (<<sec:handoff>>), instruction fetch shall be possible only from the Boot ROM region
  (`0x1004_0000`, 64 KiB). A fetch from any other region shall trap (fatal, per
  SEP-ROM-CPU-070)."
* SEP-ROM-PMP-020: "The fences shall bind the privilege mode the ROM actually runs in. The ROM
  executes exclusively in machine mode, and unlocked PMP entries do not constrain M-mode
  accesses; therefore the fence entries shall either carry the lock bit (`L=1`) or an
  equivalent machine-mode-binding mechanism (e.g. Smepmp `mseccfg.MMWP`) shall be in effect."
* SEP-ROM-PMP-030: "The regions that will hold next-stage code (SEP SRAM and ICCM) shall be
  writable but *non-executable* (`RW-`) for the entire validation portion of the boot. Execute
  permission for whichever region BL1 was loaded into shall be granted only at hand-off, after
  the pre-hand-off self-check passes."
* SEP-ROM-PMP-040: "Data windows shall be limited to the regions the ROM demonstrably needs:
  DCCM (`RW`), the SEP peripheral block (`0x1080_0000`–`0x10BF_FFFF`: DMA, scratch, crypto,
  lifecycle, efuse, SPI hosts), the XIP flash controller registers and XIP window (when
  fitted), the SMC window (`0x4000_0000`), SEP SRAM and ICCM (`RW`, for staging). Everything
  else shall have no PMP grant."
* SEP-ROM-PMP-060: "The ROM shall set `mseccfg.RLB=1` *before* programming any locked PMP rule
  (the RTL write-gate makes a late set impossible), and shall program all fence rules with
  `L=1`."
* SEP-ROM-PMP-070: "After the locked rule set is programmed, the ROM shall set
  `mseccfg.MMWP=1`, establishing machine-mode default-deny: any access matching no rule
  faults. No catch-all entry is used; a window the rule set fails to grant shall manifest as
  a precise trap (fatal per SEP-ROM-CPU-070), never as silent access."

The expected windows are tbl:pmp_regions ("Reference PMP region set"), whose bases, sizes and
permissions agree with PMP-040. PMP-040 grants the XIP windows only "when fitted", and "The open
SEP fits the OpenTitan SPI host; a memory-mapped (XIP) controller is fitted only by a build that
supplies its driver", so they join the expected set only when the ROM image links an XIP driver.

The rule set graded is the PMP CSR writes before the BOOTROM_PRESTART_DONE status ("PMP
programmed" in tbl:stage_trace) and before the hand-off mret; the hand-off release is not graded.
PMP-010 and PMP-030 are covered only as the cold rule set granting execute to the Boot ROM
window alone; fetch traps, the release and the MMWP binding alternative of PMP-020 are not graded.
The readback of the rules is reported, not graded: the trace has no CSR read value.
PMP-070 "a window the rule set fails to grant shall manifest as a precise trap" is behavioural
and not graded here; PMP writes after BOOTROM_PRESTART_DONE belong to the release test.
"""

from __future__ import annotations

import pyuvm
from env.sep_rom_observer import ROM_BUILD
from env.sep_rv32_trace_decode import (
    CSR_MSECCFG,
    CSR_PMPADDR0,
    CSR_PMPCFG0,
    MSECCFG_MMWP,
    MSECCFG_RLB,
    PMPCFG_A_MASK,
    PMPCFG_A_NAPOT,
    PMPCFG_L,
    PMPCFG_R,
    PMPCFG_W,
    PMPCFG_X,
    decode_csr,
    pmp_napot,
)
from rom_fw.sep_rom_observe_base import sep_rom_observe_base

# rom.adoc tbl:pmp_regions and SEP-ROM-PMP-040: (region, base, size, perms, spec location).
_SPEC_WINDOWS: tuple[tuple[str, int | None, int | None, str, str], ...] = (
    ("Boot ROM", 0x1004_0000, 64 << 10, "rx", "tbl:pmp_regions entry 0"),
    ("DCCM", 0xC004_0000, 128 << 10, "rw", "tbl:pmp_regions entry 1"),
    ("SEP SRAM", 0x1000_0000, 256 << 10, "rw", "tbl:pmp_regions entry 3"),
    ("Peripherals", 0x1080_0000, 4 << 20, "rw", "tbl:pmp_regions entry 4"),
    ("ICCM", 0xC000_0000, 256 << 10, "rw", "tbl:pmp_regions entry 5"),
    ("SMC boot aperture", 0x4000_0000, 8 << 20, "rw", "tbl:pmp_regions entry 6"),
)
_SPEC_XIP_WINDOWS: tuple[tuple[str, int | None, int | None, str, str], ...] = (
    ("XIP controller registers", None, None, "rw", "SEP-ROM-PMP-040 when fitted"),
    ("XIP window", 0x3000_0000, None, "rw", "SEP-ROM-PMP-040 when fitted"),
)
# STATUS_ENCODE(DEBUG 0x80, BL0 1, SEP_MSG_BOOTROM_PRESTART_DONE 0x56);
# the code is in hw/sys/sep/doc/gen/status_values.adoc.
_STATUS_PRESTART_DONE = 0x8001_0056
# pmpNcfg.A encodings other than NAPOT (RISC-V privileged spec).
_A_TOR = 1 << 3
_A_NA4 = 2 << 3
_CFG_LO, _CFG_HI = CSR_PMPCFG0, CSR_PMPCFG0 + 15
_ADDR_LO, _ADDR_HI = CSR_PMPADDR0, CSR_PMPADDR0 + 63
_SPACE = 1 << 32


def _hex(v: int | None) -> str:
    return "none" if v is None else f"0x{v:08x}"


def _apply(old: int | None, kind: str, value: int | None) -> int | None:
    """CSR value after a csrrw, csrrs or csrrc with a known or unknown operand."""
    if value is None or (kind != "rw" and old is None):
        return None
    return value if kind == "rw" else old | value if kind == "rs" else old & ~value


def _sym_types() -> dict[str, str]:
    """nm type letter of every ROM symbol; load_rom_syms drops the type."""
    out = {}
    for line in (ROM_BUILD / "boot_rom.sym").read_text().splitlines():
        parts = line.split()
        if len(parts) == 3:
            out[parts[2]] = parts[1]
    return out


def _perms(cfg: int) -> str:
    return "".join(p for p, bit in (("r", PMPCFG_R), ("w", PMPCFG_W), ("x", PMPCFG_X)) if cfg & bit)


def _windows(cfg: dict[int, int], addr: dict[int, int | None]) -> tuple[set, list[int]]:
    """(base, size, perms) of every active entry, and the active entries whose range is unknown."""
    got, unresolved = set(), []
    for i in sorted(cfg):
        a = cfg[i] & PMPCFG_A_MASK
        if not a:
            continue
        reg = addr.get(i)
        prev = addr.get(i - 1, None) if i else 0
        if reg is None or (a == _A_TOR and prev is None):
            unresolved.append(i)
        elif a == PMPCFG_A_NAPOT:
            got.add((*pmp_napot(reg), _perms(cfg[i])))
        elif a == _A_NA4:
            got.add((reg << 2, 4, _perms(cfg[i])))
        else:
            got.add((prev << 2, max((reg - prev) << 2, 0), _perms(cfg[i])))
    return got, unresolved


def _win(w) -> str:
    return f"{_hex(w[0])}+{_hex(w[1])}:{w[2]}"


@pyuvm.test()
class sep_rom_pmp_program_test(sep_rom_observe_base):
    required_evidence = (
        "CHK-PMP-VALUES-KNOWN",
        "CHK-RLB-FIRST",
        "CHK-ALL-LOCKED",
        "CHK-MMWP-AFTER-RULES",
        "CHK-NO-CATCH-ALL",
        "CHK-WINDOWS-MATCH-SPEC",
        "CHK-ONLY-ROM-EXEC",
    )

    def grade(self, obs, chk) -> None:
        mret_t = obs.pre_mret[-1].t_ps if obs.pre_mret else None
        prestart_t = obs.status_t(_STATUS_PRESTART_DONE)
        cold = mret_t is not None and prestart_t is not None and prestart_t < mret_t
        chk.ctrl(
            "COLD-WINDOW",
            cold,
            prestart_ps=prestart_t if prestart_t is not None else -1,
            mret_ps=mret_t if mret_t is not None else -1,
        )
        end = prestart_t if cold else -1
        pmp_w = [r for r in obs.csr_writes(_CFG_LO, _ADDR_HI) if r.t_ps < end]
        sec_w = [r for r in obs.csr_writes(CSR_MSECCFG) if r.t_ps < end]
        cfg_w = [r for r in pmp_w if decode_csr(r.insn).csr <= _CFG_HI]
        addr_w = [r for r in pmp_w if decode_csr(r.insn).csr >= _ADDR_LO]
        unknown = [_hex(r.pc) for r in pmp_w + sec_w if r.csr_value is None]
        chk.ok(
            "PMP-VALUES-KNOWN",
            bool(cfg_w) and bool(addr_w) and bool(sec_w) and not unknown,
            pmpcfg_writes=len(cfg_w),
            pmpaddr_writes=len(addr_w),
            mseccfg_writes=len(sec_w),
            unknown_pcs=unknown,
        )

        # Final rule set: each pmpcfg CSR and pmpaddr entry after its writes, in program order.
        cfg_reg: dict[int, int | None] = {}
        addr: dict[int, int | None] = {}
        first_lock_t = None
        for r in pmp_w:
            op = decode_csr(r.insn)
            if op.csr <= _CFG_HI:
                cfg_reg[op.csr] = _apply(cfg_reg.get(op.csr, 0), op.kind, r.csr_value)
                v = cfg_reg[op.csr]
                if first_lock_t is None and (
                    v is None or any((v >> (8 * k)) & PMPCFG_L for k in range(4))
                ):
                    first_lock_t = r.t_ps
            else:
                i = op.csr - _ADDR_LO
                addr[i] = _apply(addr.get(i), op.kind, r.csr_value)
        cfg = {
            (csr - _CFG_LO) * 4 + k: (v >> (8 * k)) & 0xFF
            for csr, v in cfg_reg.items()
            if v is not None
            for k in range(4)
        }

        def sets(r, bit: int) -> bool:
            op = decode_csr(r.insn)
            return r.csr_value is not None and op.kind != "rc" and bool(r.csr_value & bit)

        def clears(r, bit: int) -> bool:
            op = decode_csr(r.insn)
            v = r.csr_value
            return (
                v is None
                or (op.kind == "rw" and not v & bit)
                or (op.kind == "rc" and bool(v & bit))
            )

        rlb = next((r for r in sec_w if sets(r, MSECCFG_RLB)), None)
        rlb_lost = [
            _hex(r.pc)
            for r in sec_w
            if rlb is not None
            and first_lock_t is not None
            and rlb.t_ps < r.t_ps < first_lock_t
            and clears(r, MSECCFG_RLB)
        ]
        chk.ok(
            "RLB-FIRST",
            rlb is not None
            and first_lock_t is not None
            and rlb.t_ps < first_lock_t
            and not rlb_lost,
            rlb_ps=rlb.t_ps if rlb else -1,
            rlb_value=_hex(rlb.csr_value if rlb else None),
            first_lock_ps=first_lock_t if first_lock_t is not None else -1,
            rlb_cleared_at=rlb_lost,
        )

        active = {i: v for i, v in cfg.items() if v & PMPCFG_A_MASK}
        unlocked = [i for i, v in active.items() if not v & PMPCFG_L]
        unknown_cfg = [_hex(c) for c, v in cfg_reg.items() if v is None]
        chk.ok(
            "ALL-LOCKED",
            bool(active) and not unlocked and not unknown_cfg,
            active=sorted(active),
            unlocked=unlocked,
            unknown_cfg_csrs=unknown_cfg,
            pmpcfg=[f"{_hex(c)}={_hex(v)}" for c, v in sorted(cfg_reg.items())],
        )

        last_rule_t = max((r.t_ps for r in pmp_w), default=None)
        mmwp = next((r for r in sec_w if sets(r, MSECCFG_MMWP)), None)
        chk.ok(
            "MMWP-AFTER-RULES",
            mmwp is not None and last_rule_t is not None and mmwp.t_ps > last_rule_t,
            mmwp_ps=mmwp.t_ps if mmwp else -1,
            mmwp_value=_hex(mmwp.csr_value if mmwp else None),
            last_rule_ps=last_rule_t if last_rule_t is not None else -1,
        )
        reads = [
            _hex(r.pc)
            for r in obs.retires
            if (op := decode_csr(r.insn)) is not None
            and not op.writes
            and (op.csr == CSR_MSECCFG or _CFG_LO <= op.csr <= _ADDR_HI)
            and r.t_ps < end
        ]
        chk.obs("PMP-READBACK", reads=reads)

        got, unresolved = _windows(cfg, addr)
        catch_all = [_win(w) for w in got if w[0] == 0 and w[1] >= _SPACE]
        chk.ok("NO-CATCH-ALL", bool(got) and not catch_all, catch_all=catch_all)

        types = _sym_types()
        ot_spi = types.get("ot_spi_init") == "T"
        xip = types.get("spi_init") == "T"
        # Exactly one boot-flash transport is linked, so "XIP when fitted" is determinate.
        chk.ctrl("FLASH-TRANSPORT", ot_spi != xip, ot_spi=ot_spi, xip_driver=xip)
        spec = _SPEC_WINDOWS + (_SPEC_XIP_WINDOWS if xip else ())
        want = {(b, s, p) for _, b, s, p, _ in spec}
        where = {(b, s, p): f"{n}@{loc}" for n, b, s, p, loc in spec}
        chk.ok(
            "WINDOWS-MATCH-SPEC",
            bool(want) and got == want and not unresolved,
            missing=[f"{where[w]}={_win(w)}" for w in sorted(want - got, key=str)],
            extra=[_win(w) for w in sorted(got - want, key=str)],
            unresolved_entries=unresolved,
            xip_expected=xip,
        )
        execs = sorted((b, s) for b, s, p in got if "x" in p)
        spec_exec = sorted((b, s) for _, b, s, p, _ in spec if "x" in p)
        chk.ok(
            "ONLY-ROM-EXEC",
            bool(spec_exec) and execs == spec_exec,
            execs=[f"{_hex(b)}+{_hex(s)}" for b, s in execs],
            spec=[f"{_hex(b)}+{_hex(s)}" for b, s in spec_exec],
        )
