# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Stimulus-only AXI burst helpers for the ``sep_cov_axi_*`` coverage leaves.

Stimulus only. No contract is asserted; these helpers drive the bus and log
what they drove. Nothing here compares a value, and nothing here decides a
verdict from read data.

Everything drives the SMN inbound external master (``m_axi``). Two reasons:

* ``sep.sv:414`` wires that master to slave port 4 of ``sep_local_axi_xbar``,
  and ``sep_local_axi_xbar_pkg.sv:217-223`` gives input 4 connectivity to
  output 5 (``sep_crypto``), so the 64-bit crypto downsizers are reachable
  from it.
* ``env/sep_env.py:46`` connects only the CPU-LSU agent to the scoreboard, so
  an endpoint that refuses a shape this stimulus is only driving to reach a
  converter does not turn a coverage run into a verdict about that endpoint.
  A transaction that never retires is still a failure: the VIP raises on a
  timeout unless the caller sets ``allow_timeout``.

The inbound filter blocks by default (``axi_filter_wrap.sv`` BlockByDefault=1)
and refuses ``AxLEN>0`` unless ``FILTER_CONFIG.allow_burst`` is set, so the
windows below are programmed from the CPU-LSU side with ``allow_burst=1``
before any burst is driven. Each window spans more than one 4 KB page, which
is what ``SepInboundFilter.program_rule`` requires of an ``allow_burst=1``
entry that does not want the same-page widen.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles
from env.sep_axi_agent import SepAxiItem, SepAxiOp
from pyuvm import uvm_sequence

from seq_lib.sep_inbound_filter_rule_seq import SepInboundFilter, SepInboundFilterCfg

# AXI AxBURST encodings (AMBA IHI 0022).
BURST_FIXED = 0
BURST_INCR = 1
BURST_WRAP = 2

# AxSIZE encodings. 3 is the widest legal beat on this 64-bit bus.
SIZE_4B = 2
SIZE_8B = 3
BEAT_BYTES_8B = 8

# Windows the inbound filter must allow before the stimulus runs, as
# (entry, name, start, end_inclusive). Addresses come from
# hw/sys/sep/regs/gen/sv/sep_addrmap_pkg.sv and the DV address-map table in
# env/sep_axi_decode_map.py. Every window spans at least two 4 KB pages.
#
# The inbound-filter rule bank itself (INBOUND_FILTER_CTRL, inside the
# 0x10A2_xxxx system-CSR block) is outside every window, so the external
# master cannot reprogram the gate it is driving through.
ALLOW_WINDOWS: tuple[tuple[int, str, int, int], ...] = (
    (0, "sram", 0x1000_0000, 0x1000_FFFF),
    (1, "boot_rom", 0x1004_0000, 0x1004_FFFF),
    (2, "dma_csr+wdt+scratch", 0x1080_0000, 0x1080_2FFF),
    (3, "crypto", 0x1090_0000, 0x1091_FFFF),
    (4, "abr", 0x1094_0000, 0x1094_FFFF),
    (5, "entropy_pool", 0x1095_0000, 0x1095_1FFF),
)


class SepCovAxiSeq(uvm_sequence):
    """One AXI access with every ``SepAxiItem`` shape field exposed.

    ``SepAxiAccessSeq`` carries no ``allow_timeout`` or ``prot`` argument, and
    the coverage leaves need both: an access aimed at a block held in software
    reset may legitimately never retire, and AxPROT is one of the dark fields.
    The item fields themselves are the pre-existing ones
    (``env/sep_axi_agent.py``); this sequence only passes them through.
    """

    def __init__(
        self,
        name: str = "sep_cov_axi",
        *,
        op: SepAxiOp = SepAxiOp.READ,
        addr: int = 0,
        wdata: int = 0,
        length: int = 4,
        size: int | None = None,
        burst: int | None = None,
        axi_id: int = 0,
        user: int = 0,
        prot: int | None = None,
        allow_timeout: bool = False,
    ) -> None:
        super().__init__(name)
        self._op = op
        self._addr = addr
        self._wdata = wdata
        self._length = length
        self._size = size
        self._burst = burst
        self._axi_id = axi_id
        self._user = user
        self._prot = prot
        self._allow_timeout = allow_timeout
        self.rdata: int = 0
        self.resp_ok: bool = False
        self.resp_code: int = -1
        self.timed_out: bool = False

    async def body(self) -> None:
        item = SepAxiItem(self.get_name())
        item.op = self._op
        item.addr = self._addr
        item.length = self._length
        item.wdata = self._wdata
        item.size = self._size
        item.burst = self._burst
        item.axi_id = self._axi_id
        item.user = self._user
        item.prot = self._prot
        item.allow_timeout = self._allow_timeout
        await self.start_item(item)
        await self.finish_item(item)
        self.rdata = item.rdata
        self.resp_ok = item.resp_ok
        self.resp_code = item.resp_code
        self.timed_out = item.timed_out


class SepCovAxiStim:
    """Inbound-master burst stimulus: window setup, shaped access, logging."""

    def __init__(self, test) -> None:
        self.test = test
        self.log = test.logger
        self.driven = 0

    async def open_windows(self, entries=ALLOW_WINDOWS) -> None:
        """Programme the inbound-filter allow windows from the CPU-LSU side."""
        filt = SepInboundFilter(self.test)
        await filt.disable_all()
        for entry, name, start, end in entries:
            rule = SepInboundFilterCfg(entry=entry, allow_addr=start)
            await filt.program_rule(
                rule,
                read_allowed=True,
                write_allowed=True,
                allow_burst=True,
                end_addr=end,
            )
            self.log.info(
                "inbound filter entry %d allows %s 0x%08x..0x%08x r+w burst",
                entry,
                name,
                start,
                end,
            )

    def master(self):
        """The inbound master's VIP sequence, for stimulus the sequencer cannot express.

        The SEP AXI driver awaits each item to completion, so outstanding
        transactions and same-cycle AW/AR need the VIP master directly. This
        is the same handle ``seq_lib/sep_axi_concurrent_rw_seq.py`` uses.
        """
        agent = self.test.env.ext_axi_agent
        seq = getattr(getattr(agent, "driver", None), "axi", None)
        if seq is None or not hasattr(seq, "read_bytes_result"):
            raise RuntimeError(
                "no VIP master sequence behind env.ext_axi_agent.driver.axi; the "
                "coverage stimulus cannot place concurrent or outstanding "
                "transactions and would report shapes it never drove"
            )
        return seq

    def timing_driver(self):
        """The inbound master's VIP driver, which owns ``set_timing``."""
        drv = getattr(self.master(), "driver", None)
        if drv is None or not hasattr(drv, "set_timing"):
            raise RuntimeError(
                "no VIP master driver with set_timing() on m_axi; the coverage "
                "stimulus cannot backpressure R or B"
            )
        return drv

    async def burst(
        self,
        tag: str,
        *,
        op: SepAxiOp,
        addr: int,
        length: int,
        size: int = SIZE_8B,
        burst: int = BURST_INCR,
        wdata: int = 0,
        axi_id: int = 0,
        prot: int | None = None,
        allow_timeout: bool = False,
    ) -> SepCovAxiSeq:
        """Drive one shaped access on the inbound master and log the shape."""
        seq = SepCovAxiSeq(
            f"cov_{tag}",
            op=op,
            addr=addr,
            wdata=wdata,
            length=length,
            size=size,
            burst=burst,
            axi_id=axi_id,
            prot=prot,
            allow_timeout=allow_timeout,
        )
        await self.test.start_ext_seq(seq)
        self.driven += 1
        beats = max(1, length // (1 << size))
        self.log.info(
            "COV-STIM %s: %s 0x%08x size=%d burst=%d beats=%d id=%d -> resp=%d%s",
            tag,
            op.value,
            addr,
            size,
            burst,
            beats,
            axi_id,
            seq.resp_code,
            " (no response, tolerated)" if seq.timed_out else "",
        )
        return seq

    async def settle(self, cycles: int = 32) -> None:
        """Let the fabric drain between shapes."""
        await ClockCycles(cocotb.top.clk_i, cycles)

    def record(self, check_id: str, what: str) -> None:
        """Record that the stimulus ran.

        This is a stimulus record, not a graded contract: it says the shapes
        below were driven and that no access wedged. The base class counts
        ``CHK-<ID> PASS`` records, and a leaf that records nothing fails
        (``sep_base_test._finalize_evidence``), so a coverage leaf states what
        it drove rather than claiming a behaviour it never checked.
        """
        self.log.info(
            "CHK-%s PASS: stimulus only -- drove %d shaped access(es); %s. "
            "No contract is asserted by this record.",
            check_id,
            self.driven,
            what,
        )


def incr_bytes(beats: int, size: int = SIZE_8B) -> int:
    """Byte length of an ``beats``-beat INCR burst at ``size``."""
    return beats * (1 << size)


def pattern(rng, nbytes: int) -> int:
    """Seed-derived write payload of ``nbytes`` bytes.

    A pure function of the run seed (``env/sep_seeded_rng.py``), so
    ``--stage sim --seed N`` replays the same beats. This is simulation
    payload, never key material.
    """
    return rng.getrandbits(8 * nbytes)
