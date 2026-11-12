# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Reset-entry order of the Boot ROM, graded on the first retirements.

rom.adoc, Reset Entry:

* "The core enters at `_start` in the Boot ROM. *Hart 0* is the hart whose `mhartid` CSR
  reads zero."
* "The following actions occur strictly in order, before any other memory or MMIO access:"
* SEP-ROM-CPU-010: "Only hart 0 shall execute the boot flow. Any other hart shall set its
  trap vector and park permanently in a `wfi` loop."
* SEP-ROM-CPU-020: "The trap vector (`mtvec`) shall be programmed before the first MMIO
  access, so that any early bus fault produces a diagnosable trap rather than a silent hang."
* SEP-ROM-CPU-030: "The VeeR MRAC CSR (`0x7C0`) shall be configured (value `0xAAAAAAA8`:
  side-effect, non-cacheable attributes for device regions) before the warm-scratch register
  is read, so the read is performed with correct memory attributes."

The fitted core is single-hart, so only the hart-0 side of SEP-ROM-CPU-010 is reachable:
the ROM must read `mhartid` before any data access and hart 0 must never enter the park loop.
The first load or store of the run is the bound for every action, which also covers the
first MMIO access and the warm-scratch read.
"""

from __future__ import annotations

import pyuvm
from env.sep_rom_observer import ROM_BUILD, load_rom_syms
from env.sep_rv32_trace_decode import (
    CSR_MHARTID,
    CSR_MRAC,
    CSR_MTVEC,
    decode_csr,
    is_load,
    is_store,
)
from rom_fw.sep_rom_observe_base import sep_rom_observe_base

_SPEC_MRAC = 0xAAAA_AAA8
_HEAD = 512


def _first(seq, pred) -> int | None:
    return next((i for i, r in enumerate(seq) if pred(r)), None)


def _csr(r, csr: int, write: bool) -> bool:
    op = decode_csr(r.insn)
    return op is not None and op.csr == csr and op.writes == write


def _hart_read(r) -> bool:
    # A read into x0 discards mhartid and gates nothing.
    return _csr(r, CSR_MHARTID, False) and decode_csr(r.insn).rd != 0


def _before(idx: int | None, bound: int | None) -> bool:
    return idx is not None and bound is not None and idx < bound


def _next_text_sym(addr: int) -> int:
    """Start of the code that follows addr; load_rom_syms keeps one address per repeated name."""
    starts = []
    for line in (ROM_BUILD / "boot_rom.sym").read_text().splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[1] in "tT" and int(parts[0], 16) > addr:
            starts.append(int(parts[0], 16))
    return min(starts)


def _hex(v: int | None) -> str:
    return "none" if v is None else f"0x{v:08x}"


@pyuvm.test()
class sep_rom_reset_entry_order_test(sep_rom_observe_base):
    required_evidence = (
        "CHK-HART-GATE",
        "CHK-HART-NO-PARK",
        "CHK-MTVEC-FIRST",
        "CHK-MRAC-FIRST",
        "CHK-MRAC-VALUE",
        "CHK-ENTRY-ORDER",
    )
    # Every retirement is kept so a park-loop retirement anywhere in the run is seen.
    observer_kwargs = {"head": _HEAD, "keep": lambda insn: True}

    def grade(self, obs, chk) -> None:
        syms = load_rom_syms()
        head = obs.first
        mem = _first(head, lambda r: is_load(r.insn) or is_store(r.insn))
        # Indexes into the head are program order only if it starts at reset entry and holds the access.
        chk.ctrl(
            "HEAD-RESET-ENTRY",
            bool(head) and head[0].pc == syms["_start"] and mem is not None,
            head=len(head),
            first_pc=_hex(head[0].pc if head else None),
            start_sym=_hex(syms["_start"]),
            first_mem=mem,
            first_mem_pc=_hex(head[mem].pc if mem is not None else None),
        )
        hart = _first(head, _hart_read)
        mtvec = _first(head, lambda r: _csr(r, CSR_MTVEC, True))
        mrac = _first(head, lambda r: _csr(r, CSR_MRAC, True))

        chk.ok("HART-GATE", _before(hart, mem), hart=hart, first_mem=mem)
        park = syms["secondary_hart"]
        park_end = _next_text_sym(park)
        parked = [r for r in obs.retires if park <= r.pc < park_end]
        chk.ok(
            "HART-NO-PARK",
            len(obs.retires) == obs.retired and not parked and obs.verdict_pass() is True,
            park=f"[{_hex(park)},{_hex(park_end)})",
            parked=len(parked),
            kept=len(obs.retires),
            retired=obs.retired,
            verdict=obs.verdict_pass(),
        )
        chk.ok("MTVEC-FIRST", _before(mtvec, mem), mtvec=mtvec, first_mem=mem)
        chk.ok("MRAC-FIRST", _before(mrac, mem), mrac=mrac, first_mem=mem)

        # The MRAC value in force at the first access is the last write before it.
        last = max((i for i in range(mem or 0) if _csr(head[i], CSR_MRAC, True)), default=None)
        op = decode_csr(head[last].insn) if last is not None else None
        written = head[last].csr_value if last is not None else None
        chk.ok(
            "MRAC-VALUE",
            op is not None and op.kind == "rw" and written == _SPEC_MRAC,
            index=last,
            kind=op.kind if op else None,
            written=_hex(written),
            spec=_hex(_SPEC_MRAC),
        )
        chk.ok(
            "ENTRY-ORDER",
            _before(hart, mtvec) and _before(mtvec, mrac) and _before(mrac, mem),
            hart=hart,
            mtvec=mtvec,
            mrac=mrac,
            first_mem=mem,
        )
