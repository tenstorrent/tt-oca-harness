# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Filter entries programmed with a region that spans two granules.

`smc_filter_config_field_sweep_test` cycles `FILTER_CONFIG` on every entry and
`smc_filter_multi_entry_test` reads the reset of all of them. A sweep cannot
program `START_ADDR` and `END_ADDR` into a region: its ones and zeros patterns
give both registers the same value, so the start and the end always land in
the same granule. `smc_dma_sanity_test_seq` programs a spanning region on
entry 0 of each filter only.

This leaf programs such a region on entries 1 to 15, and drives traffic
through one of them.

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

The observable there is memory rather than the response: the backend is
elaborated with `ErrorCap(idma_pkg::NO_ERROR_HANDLING)`, so a refused write
raises no error the DMA reports. The JTAG2AXI bridge seeds and reads those
addresses; it enters the fabric on the inbound side rather than the outbound
side this entry sits on, so it cannot be the master under test.

**Nothing is left behind.** The entry under test is restored to its RDL reset,
`FILTER_CONFIG.locked` is never written, and the inbound entry this leaf reads
to establish that no lower-numbered entry can mask its own is saved and written
back word for word rather than assumed to reset.

**The inbound leg at 56-bit addresses.** After the outbound legs the global
SMC window is relocated through `SMC_BASE_CONFIG.GLOBAL_BASE` so that address
bits [55:32] read 0x0000AB, and one inbound entry that reads disabled is
enabled over that window plus one granule beyond it. `fabric.adoc` sends the
system input through the inbound filter and then a region demux: the SMC
window reaches the local fabric rebased onto the local base, every other
address answers DECERR. So the SYS_IN read and write of CPU_CTRL `SCRATCH[1]`
through the relocated window have to answer OKAY and agree with the SEP_IN
local access, the address one half-granule past the window has to answer
DECERR although the entry admits it, and with the entry's `read_allowed` and
`write_allowed` clear the same register has to answer DECERR and keep its
value. The read data of a DECERR is logged, not compared (SF-021). The entry
and `GLOBAL_BASE` are written back to the words read before the leg.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from ._one_shot import _OneShot
from .smc_addr_map import (
    _REPO,
    _SMC_BASE_CFG_H,
    LOCAL_BASE_RESET,
    _field_mask,
    reg_field_encode,
    smc_addr,
    smc_indexed_addr,
)
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
# models. Start and end sit in different granules.
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


# -- the inbound leg at 56-bit addresses ------------------------------------

_IN = "SMC_TOP_SMC_INBOUND_FILTER_CTRL_"
_FILTER_H = _REPO / "hw" / "ip" / "axi_filter" / "regs" / "gen" / "c" / "filter_ctrl.h"
_CFG_MASK = {
    name: _field_mask(_FILTER_H, f"FILTER_CTRL__FILTER_CONFIG__{name.upper()}_bm")
    for name in ("entry_enabled", "allow_burst", "data_bus_width")
}
_DBW_LSB = _field_mask(_FILTER_H, "FILTER_CTRL__FILTER_CONFIG__DATA_BUS_WIDTH_bp")
_GLOBAL_BASE = smc_addr("SMC_TOP_SMC_BASE_CONFIG_GLOBAL_BASE_BASE_ADDR")
_REGION_SIZE = smc_addr("SMC_TOP_SMC_BASE_CONFIG_REGION_SIZE_BASE_ADDR")
# CPU_CTRL SCRATCH[1]: data [31:0] RW (cpu_ctrl.adoc), at offset 0x39088 of the SMC window.
_SCRATCH1_OFFSET = 0x39088
_SCRATCH1_LOCAL = smc_indexed_addr("SMC_TOP_SMC_CPU_CTRL_SCRATCH_BASE_ADDR", 1)
assert _SCRATCH1_LOCAL == LOCAL_BASE_RESET + _SCRATCH1_OFFSET, (
    f"the generated map places CPU_CTRL SCRATCH[1] at 0x{_SCRATCH1_LOCAL:x}, not at "
    f"LOCAL_BASE 0x{LOCAL_BASE_RESET:x} + 0x{_SCRATCH1_OFFSET:x}"
)
_HIGH_BITS = 0xAB
_HIGH_SHIFT = 32
_SYS_IN_PROT = 0
_HIGH_WDATA = 0x0000_0000_5A5A_A5A5
_SCRATCH_DATA_MASK = 0xFFFF_FFFF
_OKAY = 0
_DECERR = 3
_AXI_BOUND_NS = 50_000
_FENCE = (
    "EXISTING-LEGS",
    "PRECONDITION",
    "RELOCATED",
    "PASS-MAPPED",
    "PASS-UNMAPPED",
    "DENY",
    "RESTORED",
)


def _in_spec(register: str) -> tuple[str, str, str, str]:
    return (
        f"smc_inbound_filter_ctrl/{register}",
        f"{_IN}{register}_BASE_ADDR",
        f"{_IN}{register}_NUM",
        f"SMC_INBOUND_FILTER_CTRL_{{index}}__{register}_REG_ADDR",
    )


def _cfg_word(**fields: int) -> int:
    return reg_field_encode(_FILTER_H, "FILTER_CTRL", "FILTER_CONFIG", **fields)


# FILTER_CONFIG.data_bus_width is R: every readback carries its reset value.
_CFG_RO_BITS = _cfg_word(
    data_bus_width=_field_mask(_FILTER_H, "FILTER_CTRL__FILTER_CONFIG__DATA_BUS_WIDTH_reset")
)
_GLOBAL_BASE_MASK = _field_mask(_SMC_BASE_CFG_H, "SMC_BASE_CONFIG__GLOBAL_BASE__BASE_bm")
_REGION_SIZE_MASK = _field_mask(_SMC_BASE_CFG_H, "SMC_BASE_CONFIG__REGION_SIZE__SIZE_bm")


class smc_filter_region_span_test_seq(SmcCsrSeq):
    """Program a two-granule filter region on every entry, and drive one."""

    def __init__(self, name: str = "smc_filter_region_span_test_seq") -> None:
        super().__init__(name)
        self.spanning = 0
        self.rounded = 0
        self.denied = 0
        self.allowed = 0
        self.jtag_accesses = 0
        self.sys_in_accesses = 0
        self._fence: list[tuple[str, int, int]] = []
        self._term_start = 0
        self._last_access = "none"

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
        self.jtag_accesses += 1
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

    # -- the inbound leg at 56-bit addresses ----------------------------

    def _close_term(self, term: str) -> None:
        total = self.accesses + self.sys_in_accesses + self.jtag_accesses
        self._fence.append((term, int(get_sim_time("ps")), total - self._term_start))
        self._term_start = total

    async def _sep_rd(self, name: str, addr: int) -> int:
        self._last_access = f"SEP_IN read {name} 0x{addr:x}"
        value = await self.csr_read(name, addr, length=8)
        self._last_access += f" -> 0x{value:x}"
        return value

    async def _sep_wr(self, name: str, addr: int, value: int) -> None:
        self._last_access = f"SEP_IN write {name} 0x{addr:x} <- 0x{value:x}"
        await self.csr_write(name, addr, value, length=8)

    async def _sys_in(
        self, tag: str, op: SmcSysAxiOp, addr: int, resp: int, data: int | None = None
    ) -> SmcSysAxiItem:
        """One bounded 8-byte SYS_IN access whose response code must be `resp`."""
        assert self.env is not None, "sequence env is not initialized"
        item = SmcSysAxiItem(f"sys_in_{tag}")
        item.op = op
        item.addr = addr
        item.length = 8
        item.prot = _SYS_IN_PROT
        item.timeout_ns = _AXI_BOUND_NS
        if data is not None:
            item.wdata = data
        if resp == _DECERR:
            item.allow_error = True
            item.expect_error = True
            item.expected_resp = _DECERR
        self._last_access = f"SYS_IN {op.value} {tag} 0x{addr:014x}"
        await _OneShot(item, f"sys_in_{tag}_os").start(self.env.sys_in_axi_agent.sequencer)
        self.sys_in_accesses += 1
        assert not item.timed_out, f"{self._last_access}: no response within {_AXI_BOUND_NS} ns"
        self._last_access += f" resp {item.resp_code}"
        assert item.resp_code == resp, (
            f"SYS_IN {op.value} {tag} at 0x{addr:014x} answered resp {item.resp_code}; "
            f"the documented response is {resp}"
        )
        return item

    async def _inbound_high_leg(self) -> None:
        """S2-S7 of the inbound filter leg at addresses with bits [55:32] set."""
        assert self.cfg is not None, "sequence cfg is not initialized"
        sep_bound = self.cfg.axi_timeout_ns
        assert sep_bound == _AXI_BOUND_NS, (
            f"SEP_IN accesses are bounded at {sep_bound} ns; this leg bounds every access "
            f"at {_AXI_BOUND_NS} ns"
        )
        self._close_term("EXISTING-LEGS")

        # S2: save all 16 inbound entries, GLOBAL_BASE and REGION_SIZE.
        groups = {name: reg_instances(*_in_spec(name)) for name in _ENTRY_REGS}
        count = len(groups["FILTER_CONFIG"])
        assert count == 16, f"the generated map declares {count} inbound filter entries"
        saved: dict[str, list[int]] = {}
        for name in _ENTRY_REGS:
            saved[name] = [
                await self._sep_rd(f"IN{inst.index}_{name}_SAVE", inst.addr)
                for inst in groups[name]
            ]
        gb_saved = await self._sep_rd("GLOBAL_BASE_SAVE", _GLOBAL_BASE)
        rs_saved = await self._sep_rd("REGION_SIZE_SAVE", _REGION_SIZE)
        size = rs_saved & _REGION_SIZE_MASK
        assert size and size & (size - 1) == 0, (
            f"REGION_SIZE reads 0x{rs_saved:x}; smc_base_config.adoc requires a non-zero "
            f"power of two"
        )
        g = (gb_saved & _GLOBAL_BASE_MASK) | (_HIGH_BITS << _HIGH_SHIFT)
        assert (g >> _HIGH_SHIFT) == _HIGH_BITS, (
            f"GLOBAL_BASE reads 0x{gb_saved:x}; OR-ing 0x{_HIGH_BITS:x} into bits [55:32] "
            f"gives 0x{g:x}, whose bits [55:32] are not 0x0000{_HIGH_BITS:02X}"
        )
        assert g % size == 0, (
            f"G = 0x{g:x} is not aligned to REGION_SIZE 0x{size:x} (smc_base_config.adoc)"
        )
        hi = g + size + 0xFFF
        cocotb.log.info(
            "inbound filter entries before the leg (SF-006, logged): %s",
            ", ".join(
                f"{i}: cfg=0x{saved['FILTER_CONFIG'][i]:x} start=0x{saved['START_ADDR'][i]:x} "
                f"end=0x{saved['END_ADDR'][i]:x}"
                for i in range(count)
            ),
        )
        enabled = [
            i for i in range(count) if saved["FILTER_CONFIG"][i] & _CFG_MASK["entry_enabled"]
        ]
        disabled = [i for i in range(count) if i not in enabled]
        assert disabled, "every inbound filter entry reads entry_enabled = 1; none is free"
        n = disabled[0]
        for i in enabled:
            cfg = saved["FILTER_CONFIG"][i]
            if cfg & _CFG_MASK["allow_burst"]:
                granule = _GRANULE
            else:
                granule = 1 << ((cfg & _CFG_MASK["data_bus_width"]) >> _DBW_LSB)
            lo_i = saved["START_ADDR"][i] & ~(granule - 1)
            hi_i = saved["END_ADDR"][i] | (granule - 1)
            assert hi_i < g or lo_i > hi, (
                f"inbound entry {i} is enabled over 0x{lo_i:x}..0x{hi_i:x}, which covers part "
                f"of 0x{g:x}..0x{hi:x}; the leg would measure that entry's rule"
            )
        self._close_term("PRECONDITION")

        # S3: relocate the global SMC window to G.
        gb_word = reg_field_encode(_SMC_BASE_CFG_H, "SMC_BASE_CONFIG", "GLOBAL_BASE", base=g)
        await self._sep_wr("GLOBAL_BASE_HIGH", _GLOBAL_BASE, gb_word)
        gb_rb = await self._sep_rd("GLOBAL_BASE_HIGH_RB", _GLOBAL_BASE)
        assert gb_rb == gb_word, f"GLOBAL_BASE reads 0x{gb_rb:x} after writing 0x{gb_word:x}"
        self._close_term("RELOCATED")

        # S4: entry n spans the relocated window; SYS_IN read and write of SCRATCH[1].
        cfg_inst = groups["FILTER_CONFIG"][n]
        start_inst = groups["START_ADDR"][n]
        end_inst = groups["END_ADDR"][n]
        allow_ns = (_SYS_IN_PROT >> 1) & 1
        permit = _cfg_word(
            allow_burst=1,
            entry_enabled=1,
            read_allowed=1,
            write_allowed=1,
            allow_ns=allow_ns,
            src_id=0,
        )
        await self._sep_wr(f"IN{n}_START_HIGH", start_inst.addr, g)
        await self._sep_wr(f"IN{n}_END_HIGH", end_inst.addr, hi)
        await self._sep_wr(f"IN{n}_CFG_PERMIT", cfg_inst.addr, permit)
        for label, inst, want in (
            ("CFG_PERMIT", cfg_inst, permit | _CFG_RO_BITS),
            ("START_HIGH", start_inst, g),
            ("END_HIGH", end_inst, hi),
        ):
            got = await self._sep_rd(f"IN{n}_{label}_RB", inst.addr)
            assert got == want, (
                f"inbound entry {n} {label} reads 0x{got:x}, programmed 0x{want:x}; the start "
                f"and end sit in different granules, so filter_ctrl.adoc returns them as "
                f"programmed"
            )
        addr = g + _SCRATCH1_OFFSET
        rd = await self._sys_in("HIGH_RD", SmcSysAxiOp.READ, addr, _OKAY)
        local = await self._sep_rd("SCRATCH1_LOCAL", _SCRATCH1_LOCAL)
        assert rd.rdata == local, (
            f"SYS_IN read 0x{addr:014x} returned 0x{rd.rdata:x}, the SEP_IN read of SCRATCH[1] "
            f"at 0x{_SCRATCH1_LOCAL:x} returns 0x{local:x}; fabric.adoc rebases both onto the "
            f"same register"
        )
        cocotb.log.info(
            "CHK-INFILT-HIGH-READ: entry %d G=0x%x, SYS_IN rd 0x%014x resp OKAY data=0x%x == "
            "local 0x%x",
            n,
            g,
            addr,
            rd.rdata,
            local,
        )
        restore = local
        assert restore & _SCRATCH_DATA_MASK != _HIGH_WDATA & _SCRATCH_DATA_MASK, (
            f"SCRATCH[1] already holds 0x{restore:x}; the SYS_IN write would not be visible"
        )
        await self._sys_in("HIGH_WR", SmcSysAxiOp.WRITE, addr, _OKAY, data=_HIGH_WDATA)
        after = await self._sep_rd("SCRATCH1_AFTER_WR", _SCRATCH1_LOCAL)
        assert after & _SCRATCH_DATA_MASK == _HIGH_WDATA & _SCRATCH_DATA_MASK, (
            f"SCRATCH[1] data reads 0x{after & _SCRATCH_DATA_MASK:x} after the SYS_IN write of "
            f"0x{_HIGH_WDATA:x} at 0x{addr:014x}"
        )
        cocotb.log.info(
            "CHK-INFILT-HIGH-WRITE: SYS_IN wr 0x%014x resp OKAY, local SCRATCH[1][31:0]=0x%08X",
            addr,
            after & _SCRATCH_DATA_MASK,
        )
        await self._sep_wr("SCRATCH1_RESTORE", _SCRATCH1_LOCAL, restore)
        held = await self._sep_rd("SCRATCH1_RESTORE_RB", _SCRATCH1_LOCAL)
        assert held == restore, f"SCRATCH[1] reads 0x{held:x} after restoring 0x{restore:x}"
        self._close_term("PASS-MAPPED")

        # S5: inside entry n, outside the SMC window.
        u = g + size + 0x800
        ur = await self._sys_in("UNMAPPED_RD", SmcSysAxiOp.READ, u, _DECERR)
        cocotb.log.info(
            "CHK-INFILT-HIGH-UNMAPPED-RD: rd 0x%014x resp DECERR data=0x%x (logged, SF-021)",
            u,
            ur.rdata,
        )
        await self._sys_in("UNMAPPED_WR", SmcSysAxiOp.WRITE, u, _DECERR, data=_HIGH_WDATA)
        cocotb.log.info("CHK-INFILT-HIGH-UNMAPPED-WR: wr 0x%014x resp DECERR", u)
        self._close_term("PASS-UNMAPPED")

        # S6: entry n still enabled, read and write denied.
        deny = _cfg_word(allow_burst=1, entry_enabled=1, allow_ns=allow_ns, src_id=0)
        await self._sep_wr(f"IN{n}_CFG_DENY", cfg_inst.addr, deny)
        deny_rb = await self._sep_rd(f"IN{n}_CFG_DENY_RB", cfg_inst.addr)
        assert deny_rb == deny | _CFG_RO_BITS, (
            f"inbound entry {n} FILTER_CONFIG reads 0x{deny_rb:x}, programmed 0x{deny:x}"
        )
        dr = await self._sys_in("DENY_RD", SmcSysAxiOp.READ, addr, _DECERR)
        await self._sys_in("DENY_WR", SmcSysAxiOp.WRITE, addr, _DECERR, data=_HIGH_WDATA)
        kept = await self._sep_rd("SCRATCH1_AFTER_DENY", _SCRATCH1_LOCAL)
        assert kept == restore, (
            f"SCRATCH[1] reads 0x{kept:x} after a denied SYS_IN write; it held 0x{restore:x}"
        )
        cocotb.log.info(
            "CHK-INFILT-HIGH-DENY: entry %d cfg=0x%x, rd DECERR (data=0x%x logged), wr DECERR, "
            "SCRATCH[1] unchanged at 0x%x (S4 pass at same address 0x%014x)",
            n,
            deny_rb,
            dr.rdata,
            kept,
            addr,
        )
        self._close_term("DENY")

        # S7: entry n and GLOBAL_BASE back to their S2 words.
        for name in _ENTRY_REGS:
            inst = groups[name][n]
            await self._sep_wr(f"IN{n}_{name}_RESTORE", inst.addr, saved[name][n])
        for name in _ENTRY_REGS:
            inst = groups[name][n]
            got = await self._sep_rd(f"IN{n}_{name}_RESTORE_RB", inst.addr)
            assert got == saved[name][n], (
                f"inbound entry {n} {name} reads 0x{got:x} after restoring 0x{saved[name][n]:x}"
            )
        await self._sep_wr("GLOBAL_BASE_RESTORE", _GLOBAL_BASE, gb_saved)
        gb_back = await self._sep_rd("GLOBAL_BASE_RESTORE_RB", _GLOBAL_BASE)
        assert gb_back == gb_saved, (
            f"GLOBAL_BASE reads 0x{gb_back:x} after restoring 0x{gb_saved:x}"
        )
        self._close_term("RESTORED")

        terms = tuple(term for term, _, _ in self._fence)
        assert terms == _FENCE, f"fence terms {terms}, want {_FENCE}"
        times = [when for _, when, _ in self._fence]
        assert all(b > a for a, b in zip(times, times[1:])), f"fence times not increasing: {times}"
        assert all(c > 0 for _, _, c in self._fence), f"a fence term made no access: {self._fence}"
        cocotb.log.info(
            "CHK-NONVAC: %s (accesses@ps per term: %s); RESTORED reads entry %d and GLOBAL_BASE "
            "back at their S2 words",
            " < ".join(_FENCE),
            ", ".join(f"{t}={c}@{w}" for t, w, c in self._fence),
            n,
        )
        waits = self.accesses + self.sys_in_accesses + self.jtag_accesses + 2
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: %d bounded waits, 0 expired: %d SEP_IN accesses bound %d ns and "
            "%d JTAG accesses bound %d ns (driver axi_timeout_ns, allow_timeout False: expiry "
            "raises naming the access); %d SYS_IN accesses bound %d ns each (allow_timeout "
            "False, timed_out 0, expiry raises naming the access); 2 DMA DONE polls bound %d "
            "reads x 20 clk_smc_i (expiry raises with DONE and STATUS); last access: %s",
            waits,
            self.accesses,
            sep_bound,
            self.jtag_accesses,
            sep_bound,
            self.sys_in_accesses,
            _AXI_BOUND_NS,
            _DMA_POLLS,
            self._last_access,
        )

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

        await self._inbound_high_leg()
