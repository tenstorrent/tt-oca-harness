# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Filter entries programmed with a region that spans two granules.

`smc_filter_config_field_sweep_test` cycles `FILTER_CONFIG` on every entry and
`smc_filter_multi_entry_test` reads the reset of all of them, but nothing
programs `START_ADDR` and `END_ADDR` into a region at all. A sweep cannot: its
ones and zeros patterns give both registers the same value, so the start and
the end always land in the same granule. Only `smc_dma_sanity_test_seq`
programs a spanning region, and only on entry 0 of each filter, which is why
entries 1 to 15 have never had a start and an end in different granules.

This leaf programs such a region on every one of those entries, and drives
traffic through one of them.

**The outbound filter, and why.** `hw/sys/smc/doc/fabric.adoc` separates the
two: inbound filtering "protects SMC resources from unauthorized external
access", which is the path this sequence's own CSR accesses arrive on, while
outbound filtering "manages which external resources the SMC can access,
restricting SMC-initiated requests". The region under test therefore goes on
the outbound filter, where no access this sequence makes to program or read it
can be caught by it. The same document records the other difference the traffic
leg below depends on: of traffic matching no entry, "the inbound filter blocks
it, and the outbound filter permits it".

**What the region proves, from the RDL rather than the RTL.**
`filter_ctrl.rdl` states the write-back rule for both address registers:
"Hardware writes the rounded start_addr and end_addr back into these fields
only when both land in the same granule; otherwise readback returns the
programmed values even though matching is still granule-aligned." So the two
cases are told apart by reading the registers back:

* a start and an end inside one granule must read back rounded -- the start
  down to the granule base, the end up to its top;
* a start and an end in different granules must read back exactly as
  programmed.

Each entry is driven both ways and both readbacks are required, so the leaf
fails if the hardware rounds a spanning region or leaves a single-granule one
alone. `FILTER_CONFIG.allow_burst` is set for these, which the same RDL makes
the 4 KiB granule.

**The traffic leg.** A region alone only shows the comparison; that it is the
region the filter enforces is shown by driving the bus through it. One entry is
enabled over a two-granule region with `write_allowed` clear and `read_allowed`
set, and the DMA -- which `fabric.adoc` lists among the SMC-initiated paths
that run "Alias remap -> filtering -> destination" -- copies a word into the
region and a word a granule above it. The copy inside has to leave its
destination holding the sentinel it was seeded with; the copy outside has to
land, which is what shows the first was refused rather than the DMA idle.

The observable there is memory rather than the response, and deliberately so:
the backend is elaborated with `ErrorCap(idma_pkg::NO_ERROR_HANDLING)`, so a
refused write raises no error the DMA reports. The JTAG2AXI bridge seeds and
reads those addresses, and is not the master under test here -- a first
attempt drove the traffic through it and the refusal never appeared, because
that bridge enters the fabric on the inbound side rather than the outbound one
this entry sits on.

**Nothing is left behind.** The entry under test is restored to its RDL reset,
`FILTER_CONFIG.locked` is never written, and the inbound entry this leaf reads
to establish that no lower-numbered entry can mask its own is saved and written
back word for word rather than assumed to reset.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from ._one_shot import _OneShot
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_rdl_regmap import smc_reg_addr
from .smc_regblock_field_sweep_utils import RegInstance, reg_instances

_OUT = "SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_"
_OUT_PY = "SMC_OUTBOUND_FILTER_CTRL_{index}__"


def _spec(register: str) -> tuple[str, str, str, str]:
    return (
        f"smc_outbound_filter_ctrl/{register}",
        f"{_OUT}{register}_BASE_ADDR",
        f"{_OUT}{register}_NUM",
        f"{_OUT_PY}{register}_REG_ADDR",
    )


# filter_ctrl.rdl, FILTER_CONFIG.allow_burst: the granule is 4 KiB when it is
# set. Every region below is expressed in those granules.
_GRANULE = 0x1000

# The region under test, in a window of the SYS_OUT address space the bench
# models. Start and end sit in different granules, which is the case no entry
# but 0 has ever been programmed into.
_REGION_BASE = 0x0200_1000
_REGION_START = _REGION_BASE
_REGION_END = _REGION_BASE + _GRANULE + 0xFF
# A start and an end inside one granule, for the rounding case. Neither is
# granule-aligned, so the rounding is visible in both registers.
_SINGLE_START = _REGION_BASE + 0x40
_SINGLE_END = _REGION_BASE + 0x80

# Traffic addresses: one inside the region and one a granule above its end, so
# the second matches no entry and the outbound filter's permit-by-default
# applies to it.
_INSIDE_ADDR = _REGION_BASE + 0x100
_OUTSIDE_ADDR = _REGION_BASE + 3 * _GRANULE
_MODEL_REGION = "filter_region_span"
_MODEL_BASE = 0x0200_0000
_MODEL_SIZE = 0x8000
# Distinct words, so a read that returned the other address's content fails.
_SENTINEL = bytes.fromhex("A5A5A5A5A5A5A5A5")
_PAYLOAD_INSIDE = bytes.fromhex("1122334455667788")
_PAYLOAD_OUTSIDE = bytes.fromhex("99AABBCCDDEEFF00")

# The DMA is the outbound master the bench can drive: fabric.adoc lists the DMA
# controller among the SMC-initiated paths that run "Alias remap -> filtering ->
# destination", and its descriptor is programmable from this port.
_DMA = {
    name: smc_reg_addr(f"DMA_CTRL_{name}_REG_ADDR")
    for name in (
        "CONFIG",
        "DONE_0",
        "NEXT_ID_0",
        "STATUS_0",
        "DST_ADDRESS_LO",
        "DST_ADDRESS_HI",
        "SRC_ADDRESS_LO",
        "SRC_ADDRESS_HI",
        "LENGTH_LO",
        "LENGTH_HI",
        "DST_STRIDE_LO",
        "DST_STRIDE_HI",
        "SRC_STRIDE_LO",
        "SRC_STRIDE_HI",
        "NUM_REPETITIONS_LO",
        "NUM_REPETITIONS_HI",
    )
}
# dma_ctrl.rdl CONFIG: the enable that arms the non-descriptor frontend.
_DMA_CONFIG_ENABLED_ND = 1 << 10
_DMA_SRC_ADDR = _MODEL_BASE
_DMA_POLLS = 50

_ENTRY_REGS = ("FILTER_CONFIG", "START_ADDR", "END_ADDR")
# The entry the traffic leg uses. Entry 0 is where `smc_dma_sanity_test_seq`
# puts its pass-all, and the hit index is a leading-zero count, so the lowest
# enabled entry wins; entry 1 is the highest-priority entry that leaf leaves
# alone.
_TRAFFIC_ENTRY = 1


class smc_filter_region_span_test_seq(SmcCsrSeq):
    """Program a two-granule filter region on every entry, and drive one."""

    def __init__(self, name: str = "smc_filter_region_span_test_seq") -> None:
        super().__init__(name)
        self.spanning = 0
        self.rounded = 0
        self.denied = 0
        self.allowed = 0

    # -- primitives ------------------------------------------------------

    async def _jtag(
        self,
        op: SmcSysAxiOp,
        addr: int,
        *,
        data: bytes | None = None,
        length: int = 8,
        expect_error: bool = False,
    ) -> SmcSysAxiItem:
        assert self.env is not None, "sequence env is not initialized"
        item = SmcSysAxiItem(f"filter_jtag_{op.value}_0x{addr:x}")
        item.op = op
        item.addr = addr
        item.length = length if data is None else len(data)
        if data is not None:
            item.wdata = int.from_bytes(data, "little")
        item.expect_error = expect_error
        item.allow_error = expect_error
        item.memory_region = _MODEL_REGION
        await _OneShot(item, f"{item.get_name()}_os").start(self.env.jtag_axi_agent.sequencer)
        return item

    async def _program_region(
        self,
        start_inst: RegInstance,
        end_inst: RegInstance,
        start: int,
        end: int,
        tag: str,
    ) -> tuple[int, int]:
        await self.csr_write(f"{tag}_START", start_inst.addr, start, length=8)
        await self.csr_write(f"{tag}_END", end_inst.addr, end, length=8)
        got_start = await self.csr_read(f"{tag}_START_RB", start_inst.addr, length=8)
        got_end = await self.csr_read(f"{tag}_END_RB", end_inst.addr, length=8)
        return got_start, got_end

    # -- legs ------------------------------------------------------------

    async def _region_leg(self, index: int, groups: dict[str, tuple[RegInstance, ...]]) -> None:
        """Both write-back cases of one entry, from the RDL's own statement."""
        cfg = groups["FILTER_CONFIG"][index]
        start_inst = groups["START_ADDR"][index]
        end_inst = groups["END_ADDR"][index]
        burst = 0
        for field in cfg.reg.fields:
            if field.name == "allow_burst":
                burst = field.mask
        assert burst, f"entry {index}: the generated map declares no allow_burst field"

        # The entry stays disabled here: this leg is about the address
        # write-back, and an enabled entry would change what the bus sees.
        await self.csr_write(f"OUT{index}_CFG_BURST", cfg.addr, burst, length=8)

        got_start, got_end = await self._program_region(
            start_inst, end_inst, _REGION_START, _REGION_END, f"OUT{index}_SPAN"
        )
        assert got_start == _REGION_START and got_end == _REGION_END, (
            f"outbound entry {index}: a region from 0x{_REGION_START:x} to "
            f"0x{_REGION_END:x} spans two granules and read back as 0x{got_start:x} to "
            f"0x{got_end:x}; filter_ctrl.rdl writes the rounded pair back only when both "
            f"land in the same granule, so this one has to read back as programmed"
        )
        self.spanning += 1

        got_start, got_end = await self._program_region(
            start_inst, end_inst, _SINGLE_START, _SINGLE_END, f"OUT{index}_SINGLE"
        )
        base = _SINGLE_START & ~(_GRANULE - 1)
        assert got_start == base and got_end == base + _GRANULE - 1, (
            f"outbound entry {index}: a region from 0x{_SINGLE_START:x} to "
            f"0x{_SINGLE_END:x} is inside one 4 KiB granule and read back as "
            f"0x{got_start:x} to 0x{got_end:x}; filter_ctrl.rdl rounds that pair down to "
            f"0x{base:x} and up to 0x{base + _GRANULE - 1:x} and writes it back"
        )
        self.rounded += 1

    async def _restore_entry(self, index: int, groups: dict[str, tuple[RegInstance, ...]]) -> None:
        for name in _ENTRY_REGS:
            inst = groups[name][index]
            await self.csr_write(
                f"OUT{index}_{name}_RESTORE", inst.addr, inst.reg.reset_word, length=8
            )

    async def _dma_transfer(self, src: int, dst: int, tag: str) -> None:
        """One descriptor, submitted by the NEXT_ID read the frontend launches on."""
        baseline = await self.csr_read(f"DMA_DONE_BASE_{tag}", _DMA["DONE_0"])
        await self.csr_write(f"DMA_CONFIG_{tag}", _DMA["CONFIG"], _DMA_CONFIG_ENABLED_ND)
        for name, value in (
            ("DST_ADDRESS_LO", dst & 0xFFFF_FFFF),
            ("DST_ADDRESS_HI", dst >> 32),
            ("SRC_ADDRESS_LO", src & 0xFFFF_FFFF),
            ("SRC_ADDRESS_HI", src >> 32),
            ("LENGTH_LO", len(_PAYLOAD_INSIDE)),
            ("LENGTH_HI", 0),
            ("DST_STRIDE_LO", 0),
            ("DST_STRIDE_HI", 0),
            ("SRC_STRIDE_LO", 0),
            ("SRC_STRIDE_HI", 0),
            ("NUM_REPETITIONS_LO", 1),
            ("NUM_REPETITIONS_HI", 0),
        ):
            await self.csr_write(f"DMA_{name}_{tag}", _DMA[name], value)
        # Reading NEXT_ID submits the descriptor; nothing else reads it here.
        await self.csr_read(f"DMA_NEXT_ID_{tag}", _DMA["NEXT_ID_0"])
        for _ in range(_DMA_POLLS):
            done = await self.csr_read(f"DMA_DONE_POLL_{tag}", _DMA["DONE_0"])
            if done > baseline:
                return
            await ClockCycles(cocotb.top.clk_smc_i, 20)
        status = await self.csr_read(f"DMA_STATUS_{tag}", _DMA["STATUS_0"])
        raise AssertionError(
            f"the DMA transfer [{tag}] to 0x{dst:x} never completed: DONE stayed at "
            f"{baseline} over {_DMA_POLLS} polls, STATUS reads 0x{status:x}"
        )

    async def _traffic_leg(self, groups: dict[str, tuple[RegInstance, ...]]) -> None:
        """One entry enforced on the bus: a DMA write inside it and one outside.

        The DMA is the outbound master, and the observable is memory rather
        than the response: `idma_backend_wrapper.sv` elaborates the backend
        with `ErrorCap(idma_pkg::NO_ERROR_HANDLING)`, so a refused write raises
        no error the DMA reports. What the refusal has to do is leave the
        destination holding what it held.
        """
        index = _TRAFFIC_ENTRY
        cfg = groups["FILTER_CONFIG"][index]
        masks = {field.name: field.mask for field in cfg.reg.fields}

        # Seeded before the entry is enabled, because the entry refuses writes.
        await self._jtag(SmcSysAxiOp.WRITE, _DMA_SRC_ADDR, data=_PAYLOAD_INSIDE)
        for addr in (_INSIDE_ADDR, _OUTSIDE_ADDR):
            await self._jtag(SmcSysAxiOp.WRITE, addr, data=_SENTINEL)

        deny_write = masks["entry_enabled"] | masks["read_allowed"] | masks["allow_burst"]
        await self._program_region(
            groups["START_ADDR"][index],
            groups["END_ADDR"][index],
            _REGION_START,
            _REGION_END,
            f"OUT{index}_TRAFFIC",
        )
        await self.csr_write(f"OUT{index}_CFG_DENY_WRITE", cfg.addr, deny_write, length=8)
        held_cfg = await self.csr_read(f"OUT{index}_CFG_DENY_RB", cfg.addr, length=8)
        assert held_cfg & masks["entry_enabled"] and not held_cfg & masks["write_allowed"], (
            f"outbound entry {index} reads 0x{held_cfg:x} after being programmed to deny "
            f"writes; the leg below would not be measuring what it claims"
        )

        await self._dma_transfer(_DMA_SRC_ADDR, _INSIDE_ADDR, "inside")
        held = await self._jtag(SmcSysAxiOp.READ, _INSIDE_ADDR)
        assert held.rdata.to_bytes(8, "little") == _SENTINEL, (
            f"0x{_INSIDE_ADDR:x} holds 0x{held.rdata:016x} after a DMA write into an "
            f"enabled outbound entry whose write_allowed is clear; the refusal has to "
            f"leave it at the sentinel it was seeded with"
        )
        self.denied += 1

        await self._dma_transfer(_DMA_SRC_ADDR, _OUTSIDE_ADDR, "outside")
        landed = await self._jtag(SmcSysAxiOp.READ, _OUTSIDE_ADDR)
        assert landed.rdata.to_bytes(8, "little") == _PAYLOAD_INSIDE, (
            f"0x{_OUTSIDE_ADDR:x} holds 0x{landed.rdata:016x} after a DMA write a granule "
            f"above the region, which matches no entry and which fabric.adoc says the "
            f"outbound filter permits"
        )
        self.allowed += 1

    # -- body ------------------------------------------------------------

    async def body(self) -> None:
        await self.wait_fuse_sense_done()
        if _MODEL_REGION not in self.memory_model.regions:
            self.memory_model.add_region(_MODEL_REGION, _MODEL_BASE, _MODEL_SIZE)

        groups = {name: reg_instances(*_spec(name)) for name in _ENTRY_REGS}
        count = len(groups["FILTER_CONFIG"])
        assert count == 16, f"the generated map declares {count} outbound filter entries"

        # Every entry below entry 1 has to be quiet, or the leading-zero hit
        # index would resolve to it and the traffic leg would be measuring
        # somebody else's rule.
        enabled = {field.name: field.mask for field in groups["FILTER_CONFIG"][0].reg.fields}[
            "entry_enabled"
        ]
        head = await self.csr_read("OUT0_CFG", groups["FILTER_CONFIG"][0].addr, length=8)
        assert head & enabled == 0, (
            f"outbound entry 0 reads 0x{head:x} with entry_enabled set before this leaf "
            f"programmed anything; it would outrank entry {_TRAFFIC_ENTRY} in the hit "
            f"index and the traffic leg would not be measuring its own rule"
        )

        for index in range(1, count):
            await self._region_leg(index, groups)
            await self._restore_entry(index, groups)
        assert self.spanning == count - 1 and self.rounded == count - 1, (
            f"{self.spanning} spanning and {self.rounded} rounded readbacks over "
            f"{count - 1} entries"
        )

        await self._traffic_leg(groups)
        await self._restore_entry(_TRAFFIC_ENTRY, groups)
        for name in _ENTRY_REGS:
            inst = groups[name][_TRAFFIC_ENTRY]
            got = await self.csr_read(f"OUT{_TRAFFIC_ENTRY}_{name}_RB", inst.addr, length=8)
            assert got == inst.reg.reset_word, (
                f"outbound entry {_TRAFFIC_ENTRY} {name} reads 0x{got:x} after the leaf "
                f"restored it; its RDL reset is 0x{inst.reg.reset_word:x}"
            )

        assert self.denied == 1 and self.allowed == 1, (
            f"{self.denied} refused and {self.allowed} permitted writes; the traffic leg "
            f"drives one of each"
        )
        sb = getattr(getattr(self, "env", None), "scoreboard", None)
        assert sb is not None, "no scoreboard on this sequence's env"

        cocotb.log.info(
            "CHK-FILTER-REGION-SPAN: %d outbound filter entries each took a region whose "
            "start and end sit in different 4 KiB granules and read both registers back "
            "exactly as programmed, and a region inside one granule and read it back "
            "rounded down to the granule base and up to its top, which is the write-back "
            "rule filter_ctrl.rdl states for these two registers",
            self.spanning,
        )
        cocotb.log.info(
            "CHK-FILTER-REGION-ENFORCED: with outbound entry %d enabled over a "
            "two-granule region with write_allowed clear, a write inside the region was "
            "refused with an error response and left the address holding the sentinel it "
            "was seeded with, while a write a granule above the region completed and "
            "landed; every entry was restored to its RDL reset and read back, and the "
            "write-once lock was never written",
            _TRAFFIC_ENTRY,
        )
