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
PR-EXT-RSP ``pr_ext``       b: resp id; r: resp id last (the PR-EXT replies)
PR-DMACSR  ``pr_dmacsr``    aw, ar: addr
PR-CPU-LSU ``pr_cpu_lsu``   aw, ar: prot (raw CPU LSU request; graded)
PR-CPU-IFU ``pr_cpu_ifu``   ar: prot (raw CPU IFU request; graded)
PR-DMA-RAW ``pr_dma_raw``   aw, ar: prot (raw DMA master request; graded)
PR-INFLT   ``pr_inflt``     aw, ar: addr (global, out of the inbound filter)
PR-ALIAS   ``pr_alias_in``, aw, ar: addr cache prot (input and output of the
           ``pr_alias_out`` local-master alias remap)
PR-XEXT    ``xbar_ext_in``  aw, ar: addr (approved probe)
PR-CSR     ``sys_csr_axil`` aw, ar: addr (approved probe)
PR-SRAM    ``pr_sram``      req: addr we wdata strb (req and gnt high);
                            rsp: rdata (rvalid high)
PR-ROM     ``pr_rom``       as PR-SRAM
========== ================ ==================================================

A field that resolves to X or Z is recorded as None, so a check that needs a
known value fails on it instead of reading 0. A VALID or READY that resolves to
X or Z while the monitor runs fails the leaf with ``TAP-XZ FAIL``, so a check
that counts no handshake cannot pass on an unknown handshake. Verilator is
2-state; the X checks of the leaves therefore run on VCS.

Usage::

    tap = SepFabricTap("PR-OUT")
    tap.start()
    mark = tap.mark()
    ...stimulus...
    beats = tap.since(mark, "aw")
    await tap.stop()
"""

from __future__ import annotations

import logging
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
    "PR-EXT-RSP": ("pr_ext", {"b": ("resp", "id"), "r": ("resp", "id", "last")}, "axi"),
    "PR-DMACSR": ("pr_dmacsr", {"aw": ("addr",), "ar": ("addr",)}, "axi"),
    "PR-CPU-LSU": ("pr_cpu_lsu", {"aw": ("prot",), "ar": ("prot",)}, "axi"),
    "PR-CPU-IFU": ("pr_cpu_ifu", {"ar": ("prot",)}, "axi"),
    "PR-DMA-RAW": ("pr_dma_raw", {"aw": ("prot",), "ar": ("prot",)}, "axi"),
    "PR-INFLT": ("pr_inflt", {"aw": ("addr",), "ar": ("addr",)}, "axi"),
    "PR-ALIAS-IN": (
        "pr_alias_in",
        {"aw": ("addr", "cache", "prot"), "ar": ("addr", "cache", "prot")},
        "axi",
    ),
    "PR-ALIAS-OUT": (
        "pr_alias_out",
        {"aw": ("addr", "cache", "prot"), "ar": ("addr", "cache", "prot")},
        "axi",
    ),
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


def _known(sig) -> bool:
    return sig is None or sig.value.is_resolvable


class TapXZError(AssertionError):
    """A tap handshake signal resolved to X or Z."""


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

    def __init__(self, name: str, dut=None, *, xz_fail: bool = True) -> None:
        if name not in TAPS:
            raise KeyError(f"unknown tap {name}; known: {', '.join(TAPS)}")
        self.name = name
        # False for a log-only monitor: an edge with X or Z on VALID or READY
        # is skipped instead of failing the leaf.
        self.xz_fail = xz_fail
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
                if not (_known(valid) and _known(ready)):
                    if not self.xz_fail:
                        continue
                    msg = (
                        f"TAP-XZ FAIL: {self.name} {ch} valid={valid.value} "
                        f"ready={'na' if ready is None else ready.value} "
                        f"t={get_sim_time('ps')}ps"
                    )
                    logging.getLogger("cocotb.sep_fabric_tap").error(msg)
                    raise TapXZError(msg)
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


def log_axprot(logger, tap: "SepFabricTap", master: str, ch: str, mode: str) -> None:
    """One log-only line of the AxPROT values that a master drove on a channel."""
    vals = [b.prot for b in tap.beats if b.ch == ch]
    known = sorted({v for v in vals if v is not None})
    prot = f"0b{known[0]:03b}" if len(known) == 1 else ("none" if not known else "mixed")
    logger.info(
        "OBS-AXPROT: master=%s ch=%s mode=%s prot=%s count=%d distinct=%s",
        master,
        ch,
        mode,
        prot,
        len(vals),
        "{" + ",".join(f"0b{v:03b}" for v in known) + ("" if None not in vals else ",X") + "}",
    )


# AxPROT of the SEP bus masters, from ``hw/sys/sep/doc/cpu.adoc``, table
# ``sep-cpu-axprot-table``: bit 0 privileged, bit 1 non-secure, bit 2 instruction.
AXPROT_IFU_AR = 0b101  # IFU reads: privileged, secure, instruction
AXPROT_LSU = 0b001  # LSU reads and writes: privileged, secure, data
AXPROT_DMA = 0b001  # secure DMA master reads and writes: privileged, secure, data


def check_axprot(logger, chk: str, tap: "SepFabricTap", master: str, ch: str, expect: int) -> None:
    """Grade every AxPROT a master drove on one channel against ``expect``.

    Fails when the channel carried no beat, when any beat holds X or Z, or
    when any beat differs from ``expect``.
    """
    vals = [b.prot for b in tap.beats if b.ch == ch]
    bad = [v for v in vals if v != expect]
    seen = (
        "{" + ",".join("X" if v is None else f"0b{v:03b}" for v in sorted(set(vals), key=str)) + "}"
    )
    if not vals or bad:
        msg = (
            f"{chk} FAIL: master={master} ch={ch} count={len(vals)} mismatches={len(bad)} "
            f"seen={seen} expect=0b{expect:03b} (cpu.adoc, sep-cpu-axprot-table)"
        )
        logger.error(msg)
        raise AssertionError(msg)
    logger.info(
        f"{chk} PASS: master={master} ch={ch} prot={seen} count={len(vals)} expect=0b{expect:03b}"
    )


def start_taps(*names: str, dut=None) -> dict[str, SepFabricTap]:
    """Start one monitor per tap name; returns them by name."""
    return {n: SepFabricTap(n, dut).start() for n in names}


async def stop_taps(taps: dict[str, SepFabricTap]) -> None:
    for t in taps.values():
        await t.stop()
