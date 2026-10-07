# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Monitors for the fabric observation taps of tb_top.

Each tap is a read-only copy of a DUT net that tb_top brings out on
``<prefix>_<ch><field>_o`` ports (docs/SEP_TB_ARCH.adoc, observation-probe
list; port comments in tb/sep_tb_signal_list.svh). A monitor records every
handshake of the channels it watches: VALID and READY high on a rising edge of
``clk_i``, sampled in the read-only phase.

Taps:

========== ================ ==================================================
Name       Prefix           Channels and fields
========== ================ ==================================================
PR-OUT     ``pr_out``       aw, ar: addr id user cache prot len size burst;
                            w: data strb last
PR-SMC     ``pr_smc``       as PR-OUT
PR-EXT     ``pr_ext``       as PR-OUT (32-bit address)
PR-DMACSR  ``pr_dmacsr``    aw, ar: addr
PR-ALIAS   ``pr_alias_in``, aw, ar: addr cache prot (input and output of the
           ``pr_alias_out`` local-master alias remap)
PR-XEXT    ``xbar_ext_in``  aw, ar: addr (approved probe)
PR-CSR     ``sys_csr_axil`` aw, ar: addr (approved probe)
PR-SRAM    ``pr_sram``      req: addr we wdata strb (req and gnt high);
                            rsp: rdata (rvalid high)
PR-ROM     ``pr_rom``       as PR-SRAM
========== ================ ==================================================

A field that resolves to X or Z is recorded as None, so a check that needs a
known value fails on it instead of reading 0. Verilator is 2-state; the X
checks of the leaves therefore run on VCS.

Usage::

    tap = SepFabricTap("PR-OUT")
    tap.start()
    mark = tap.mark()
    ...stimulus...
    beats = tap.since(mark, "aw")
    await tap.stop()
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cocotb
from cocotb.triggers import ReadOnly, RisingEdge
from cocotb.utils import get_sim_time

_AXI_FULL = ("addr", "id", "user", "cache", "prot", "len", "size", "burst")
_W_FIELDS = ("data", "strb", "last")

# name -> (prefix, {channel: fields}, kind)
TAPS: dict[str, tuple[str, dict[str, tuple[str, ...]], str]] = {
    "PR-OUT": ("pr_out", {"aw": _AXI_FULL, "ar": _AXI_FULL, "w": _W_FIELDS}, "axi"),
    "PR-SMC": ("pr_smc", {"aw": _AXI_FULL, "ar": _AXI_FULL, "w": _W_FIELDS}, "axi"),
    "PR-EXT": ("pr_ext", {"aw": _AXI_FULL, "ar": _AXI_FULL, "w": _W_FIELDS}, "axi"),
    "PR-DMACSR": ("pr_dmacsr", {"aw": ("addr",), "ar": ("addr",)}, "axi"),
    "PR-ALIAS-IN": ("pr_alias_in", {"aw": ("addr", "cache", "prot"), "ar": ("addr", "cache", "prot")}, "axi"),
    "PR-ALIAS-OUT": ("pr_alias_out", {"aw": ("addr", "cache", "prot"), "ar": ("addr", "cache", "prot")}, "axi"),
    "PR-XEXT": ("xbar_ext_in", {"aw": ("addr",), "ar": ("addr",)}, "axi"),
    "PR-CSR": ("sys_csr_axil", {"aw": ("addr",), "ar": ("addr",)}, "axi"),
    "PR-SRAM": ("pr_sram", {"req": ("addr", "we", "wdata", "strb"), "rsp": ("rdata",)}, "mem"),
    "PR-ROM": ("pr_rom", {"req": ("addr", "we", "wdata", "strb"), "rsp": ("rdata",)}, "mem"),
}


def _val(sig) -> int | None:
    v = sig.value
    if not v.is_resolvable:
        return None
    return int(v)


def _hi(sig) -> bool:
    v = sig.value
    return v.is_resolvable and int(v) == 1


@dataclass
class TapBeat:
    """One handshake on one channel."""

    ch: str
    t_ps: int
    seq: int
    """Position of the beat in the record of the tap, all channels together."""
    fields: dict[str, int | None] = field(default_factory=dict)

    def __getattr__(self, name: str):
        try:
            return self.fields[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def has_unknown(self) -> bool:
        return any(v is None for v in self.fields.values())

    def fmt(self) -> str:
        parts = []
        for k, v in self.fields.items():
            parts.append(f"{k}=" + ("X" if v is None else f"0x{v:x}"))
        return f"{self.ch}[" + " ".join(parts) + "]"


class SepFabricTap:
    """Records the handshakes of one tap until stopped."""

    def __init__(self, name: str, dut=None) -> None:
        if name not in TAPS:
            raise KeyError(f"unknown tap {name}; known: {', '.join(TAPS)}")
        self.name = name
        self.dut = dut if dut is not None else cocotb.top
        prefix, chans, kind = TAPS[name]
        self.kind = kind
        self.beats: list[TapBeat] = []
        self._task = None
        self._sigs: dict[str, tuple[object, object, dict[str, object]]] = {}
        for ch, names in chans.items():
            if kind == "axi":
                valid = getattr(self.dut, f"{prefix}_{ch}valid_o")
                ready = getattr(self.dut, f"{prefix}_{ch}ready_o")
                flds = {n: getattr(self.dut, f"{prefix}_{ch}{n}_o") for n in names}
            elif ch == "req":
                valid = getattr(self.dut, f"{prefix}_req_o")
                ready = getattr(self.dut, f"{prefix}_gnt_o")
                flds = {n: getattr(self.dut, f"{prefix}_{n}_o") for n in names}
            else:
                valid = getattr(self.dut, f"{prefix}_rvalid_o")
                ready = None
                flds = {n: getattr(self.dut, f"{prefix}_{n}_o") for n in names}
            self._sigs[ch] = (valid, ready, flds)

    async def _run(self) -> None:
        clk = self.dut.clk_i
        while True:
            await RisingEdge(clk)
            await ReadOnly()
            for ch, (valid, ready, flds) in self._sigs.items():
                if _hi(valid) and (ready is None or _hi(ready)):
                    t = get_sim_time("ps")
                    self.beats.append(
                        TapBeat(ch, t, len(self.beats), {n: _val(s) for n, s in flds.items()})
                    )

    def start(self) -> "SepFabricTap":
        if self._task is None:
            self._task = cocotb.start_soon(self._run())
        return self

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None

    def mark(self) -> int:
        """A position in the record; ``since`` returns the beats after it."""
        return len(self.beats)

    def since(self, mark: int, ch: str | None = None) -> list[TapBeat]:
        return [b for b in self.beats[mark:] if ch is None or b.ch == ch]

    def count(self, mark: int = 0, ch: str | None = None) -> int:
        return len(self.since(mark, ch))

    def addrs(self, mark: int = 0, ch: str | None = None) -> list[int | None]:
        return [b.fields.get("addr") for b in self.since(mark, ch)]


def start_taps(*names: str, dut=None) -> dict[str, SepFabricTap]:
    """Start one monitor per tap name; returns them by name."""
    return {n: SepFabricTap(n, dut).start() for n in names}


async def stop_taps(taps: dict[str, SepFabricTap]) -> None:
    for t in taps.values():
        await t.stop()
