# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Output-fabric protocol VIP helpers for SMC OSS tests."""

from __future__ import annotations

import re
import sys
from functools import lru_cache
from pathlib import Path

import cocotb
from cocotb.triggers import ClockCycles
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from ._one_shot import _OneShot
from .smc_csr_seq_utils import SmcCsrSeq

# Generated PeakRDL map (hw/sys/smc/regs/gen/py/smc_reg.py).
_SMC_REG_PY = Path(__file__).resolve().parents[3] / "regs" / "gen" / "py"
if str(_SMC_REG_PY) not in sys.path:
    sys.path.insert(0, str(_SMC_REG_PY))

from smc_reg import (  # noqa: E402
    SMC_INBOUND_FILTER_CTRL_0__END_ADDR_REG_ADDR,
    SMC_INBOUND_FILTER_CTRL_0__FILTER_CONFIG_REG_ADDR,
    SMC_INBOUND_FILTER_CTRL_0__START_ADDR_REG_ADDR,
    SMC_OUTBOUND_FILTER_CTRL_0__END_ADDR_REG_ADDR,
    SMC_OUTBOUND_FILTER_CTRL_0__FILTER_CONFIG_REG_ADDR,
    SMC_OUTBOUND_FILTER_CTRL_0__START_ADDR_REG_ADDR,
)

INBOUND0_FILTER_CONFIG = SMC_INBOUND_FILTER_CTRL_0__FILTER_CONFIG_REG_ADDR
INBOUND0_START = SMC_INBOUND_FILTER_CTRL_0__START_ADDR_REG_ADDR
INBOUND0_END = SMC_INBOUND_FILTER_CTRL_0__END_ADDR_REG_ADDR
OUTBOUND0_FILTER_CONFIG = SMC_OUTBOUND_FILTER_CTRL_0__FILTER_CONFIG_REG_ADDR
OUTBOUND0_START = SMC_OUTBOUND_FILTER_CTRL_0__START_ADDR_REG_ADDR
OUTBOUND0_END = SMC_OUTBOUND_FILTER_CTRL_0__END_ADDR_REG_ADDR

# SYS_OUT fabric window (served by the TB SYS_OUT responder; not an SMC CSR address).
OUTPUT_FABRIC_ADDR = 0x0200_0000
OUTPUT_FABRIC_ALT_ADDR = 0x0200_0008
OUTPUT_FABRIC_DATA = 0x1122_3344_5566_7788
OUTPUT_FABRIC_ALT_DATA = 0x8877_6655_4433_2211
OUTPUT_FABRIC_MODEL_REGION = "output_fabric"
OUTPUT_FABRIC_MODEL_BASE = 0x0200_0000
OUTPUT_FABRIC_MODEL_SIZE = 0x0001_0000

# --- Register field packing from the generated register header ---------------
# Bit positions on the proof path are never hand-packed: they are computed from
# the generated C bitfield structs in the flattened SMC register header
# (``hw/sys/smc/bootrom/prod/registers/smc_top_regs.h``, the same authoritative
# map ``smc_addr_map.smc_bootrom_addr`` already reads). PeakRDL emits the fields
# LSB-first, so member order gives the bit offsets.
_REPO = Path(__file__).resolve().parents[6]
_SMC_TOP_REGS_H = _REPO / "hw" / "sys" / "smc" / "bootrom" / "prod" / "registers" / "smc_top_regs.h"
_BITFIELD_STRUCT_RE = re.compile(r"typedef\s+struct\s*\{(.*?)\}\s*(\w+)\s*;", re.S)
_BITFIELD_MEMBER_RE = re.compile(r"uint(?:8|16|32|64)_t\s+(\w+)\s*:\s*(\d+)\s*;")


@lru_cache(maxsize=1)
def _bitfield_layouts() -> dict[str, dict[str, tuple[int, int]]]:
    """``{struct: {field: (lsb, width)}}`` for every generated bitfield struct."""
    text = _SMC_TOP_REGS_H.read_text(encoding="utf-8")
    out: dict[str, dict[str, tuple[int, int]]] = {}
    for body, name in _BITFIELD_STRUCT_RE.findall(text):
        members = _BITFIELD_MEMBER_RE.findall(body)
        if not members:
            continue
        layout: dict[str, tuple[int, int]] = {}
        lsb = 0
        for field, width in members:
            layout[field] = (lsb, int(width))
            lsb += int(width)
        out[name] = layout
    if not out:
        raise RuntimeError(f"no generated bitfield structs parsed from {_SMC_TOP_REGS_H}")
    return out


def reg_field_pack(struct: str, **fields: int) -> int:
    """Pack ``field=value`` into a register word using the generated layout."""
    layouts = _bitfield_layouts()
    try:
        layout = layouts[struct]
    except KeyError as exc:
        raise KeyError(f"{struct} not in {_SMC_TOP_REGS_H}") from exc
    value = 0
    for field, field_value in fields.items():
        try:
            lsb, width = layout[field]
        except KeyError as exc:
            raise KeyError(f"{struct}.{field} not in {_SMC_TOP_REGS_H}") from exc
        assert 0 <= field_value < (1 << width), (
            f"{struct}.{field}={field_value} does not fit in {width} bit(s)"
        )
        value |= field_value << lsb
    return value


_FILTER_CONFIG_STRUCT = "FILTER_CTRL_FILTER_CONFIG_reg_t"
# data_bus_width=3 selects 8-byte beats (the SYS/SEP AXI data width used by
# every fabric access in these tests).
_FILTER_DATA_BUS_WIDTH_8B = 3

# Pass single-beat and burst read/write traffic.
PASS_ALL_CONFIG = reg_field_pack(
    _FILTER_CONFIG_STRUCT,
    read_allowed=1,
    write_allowed=1,
    entry_enabled=1,
    data_bus_width=_FILTER_DATA_BUS_WIDTH_8B,
    allow_burst=1,
)
# Reads only: write_allowed / allow_burst cleared.
READ_ONLY_CONFIG = reg_field_pack(
    _FILTER_CONFIG_STRUCT,
    read_allowed=1,
    entry_enabled=1,
    data_bus_width=_FILTER_DATA_BUS_WIDTH_8B,
)


class output_fabric_pass_all_cfg_seq(SmcCsrSeq):
    """Program input/output filters to pass single-beat read/write traffic."""

    def __init__(self, name: str = "output_fabric_pass_all_cfg_seq") -> None:
        super().__init__(name)

    async def body(self) -> None:
        await self.program_inbound_pass_all()
        await self.program_outbound_pass_all()
        assert self.accesses == 6, "output-fabric pass-all setup mismatch"

    async def program_inbound_pass_all(self) -> None:
        await self.csr_write("INBOUND0_START_PASS_ALL", INBOUND0_START, 0x0, length=8)
        await self.csr_write("INBOUND0_END_PASS_ALL", INBOUND0_END, 0x00FF_FFFF_FFFF_FFFF, length=8)
        await self.csr_write(
            "INBOUND0_FILTER_CONFIG_PASS_ALL", INBOUND0_FILTER_CONFIG, PASS_ALL_CONFIG, length=8
        )

    async def program_outbound_pass_all(self) -> None:
        await self.csr_write("OUTBOUND0_START_PASS_ALL", OUTBOUND0_START, 0x0, length=8)
        await self.csr_write(
            "OUTBOUND0_END_PASS_ALL", OUTBOUND0_END, 0x00FF_FFFF_FFFF_FFFF, length=8
        )
        await self.csr_write(
            "OUTBOUND0_FILTER_CONFIG_PASS_ALL", OUTBOUND0_FILTER_CONFIG, PASS_ALL_CONFIG, length=8
        )


class output_fabric_block_write_cfg_seq(output_fabric_pass_all_cfg_seq):
    """Program filters to pass reads but block writes for a target window."""

    def __init__(
        self,
        name: str = "output_fabric_block_write_cfg_seq",
        start_addr: int = OUTPUT_FABRIC_ADDR,
        end_addr: int = OUTPUT_FABRIC_ADDR + 0xFFF,
    ) -> None:
        super().__init__(name)
        self.start_addr = start_addr
        self.end_addr = end_addr

    async def body(self) -> None:
        await self.program_inbound_pass_all()
        await self.csr_write(
            "OUTBOUND0_START_BLOCK_WRITE", OUTBOUND0_START, self.start_addr, length=8
        )
        await self.csr_write("OUTBOUND0_END_BLOCK_WRITE", OUTBOUND0_END, self.end_addr, length=8)
        await self.csr_write(
            "OUTBOUND0_FILTER_CONFIG_READ_ONLY", OUTBOUND0_FILTER_CONFIG, READ_ONLY_CONFIG, length=8
        )
        assert self.accesses == 6, "output-fabric block-write setup mismatch"


RESP_OKAY = 0
RESP_SLVERR = 2
RESP_DECERR = 3


async def jtag_axi_write(
    test,
    addr: int,
    data: int,
    *,
    allow_error: bool = False,
    expect_error: bool = False,
    expected_resp: int | None = None,
    update_golden: bool = False,
    memory_region: str | None = None,
):
    item = SmcSysAxiItem(f"jtag_output_write_0x{addr:x}")
    item.op = SmcSysAxiOp.WRITE
    item.addr = addr
    item.length = 8
    item.wdata = data
    item.allow_error = allow_error or expect_error
    item.expect_error = expect_error
    item.expected_resp = expected_resp
    item.update_golden = update_golden
    item.memory_region = memory_region
    await _OneShot(item, f"jtag_output_write_0x{addr:x}_os").start(
        test.env.jtag_axi_agent.sequencer
    )
    return item


async def jtag_axi_read(
    test,
    addr: int,
    *,
    expected: int | None = None,
    allow_error: bool = False,
    expect_error: bool = False,
    expected_resp: int | None = None,
    check_golden: bool = False,
    memory_region: str | None = None,
):
    item = SmcSysAxiItem(f"jtag_output_read_0x{addr:x}")
    item.op = SmcSysAxiOp.READ
    item.addr = addr
    item.length = 8
    item.expected = expected
    item.allow_error = allow_error or expect_error
    item.expect_error = expect_error
    item.expected_resp = expected_resp
    item.check_golden = check_golden
    item.memory_region = memory_region
    await _OneShot(item, f"jtag_output_read_0x{addr:x}_os").start(test.env.jtag_axi_agent.sequencer)
    return item


def output_fabric_model(test):
    model = test.env.cfg.memory_model
    if OUTPUT_FABRIC_MODEL_REGION not in model.regions:
        model.add_region(
            OUTPUT_FABRIC_MODEL_REGION,
            OUTPUT_FABRIC_MODEL_BASE,
            OUTPUT_FABRIC_MODEL_SIZE,
        )
    return model


def _resolved_int(sig) -> int | None:
    """Return ``int(sig)`` or ``None`` when the net is X/Z (never guess a value)."""
    value = sig.value
    if not value.is_resolvable:
        return None
    return int(value)


def output_responder_counts(dut=None) -> tuple[int, int]:
    """X-aware sample of the SYS_OUT responder write/read counters.

    Fails (with the offending signal named) instead of letting ``int()`` raise or
    resolve an X/Z observability net arbitrarily.
    """
    dut = dut if dut is not None else cocotb.top
    counts: list[int] = []
    for sig in (dut.tb_output_axi_write_count, dut.tb_output_axi_read_count):
        observed = _resolved_int(sig)
        assert observed is not None, (
            f"{sig._name} is not resolvable (X/Z): the SYS_OUT observability "
            f"counter must be a defined value before it can be sampled "
            f"(value={sig.value})"
        )
        counts.append(observed)
    return counts[0], counts[1]


# Hold window for the "a blocked write produced no output-fabric beat" leg, in
# clk_smc_i cycles. The counter is sampled every cycle of the window and any
# advance fails immediately, so the window only bounds how long the absence is
# required to persist; it is generous relative to the responder pipeline depth.
BLOCKED_WRITE_HOLD_CYCLES = 64


async def hold_output_responder_writes(
    *, expected_writes: int, label: str, hold_cycles: int = BLOCKED_WRITE_HOLD_CYCLES
) -> int:
    """Require the SYS_OUT write counter to stay at ``expected_writes``.

    The negative half of an output-filter block proof: a write the filter must
    reject may not produce an output-fabric write beat. Sampled every
    ``clk_smc_i`` cycle across the window and X-aware, so an advance -- or a
    counter that went unresolvable -- fails naming the value rather than being
    missed by a single post-hoc sample.

    On its own this is a pure negative check (a dead counter passes it too); the
    caller's positive control is the pass-phase write in the same test, which is
    required to advance the very same counter. Returns the final observed count.
    """
    dut = cocotb.top
    observed = expected_writes
    for cycle in range(1, hold_cycles + 1):
        await ClockCycles(dut.clk_smc_i, 1)
        observed = _resolved_int(dut.tb_output_axi_write_count)
        assert observed is not None, (
            f"{label}: tb_output_axi_write_count became unresolvable (X/Z) "
            f"{cycle} clk_smc_i cycle(s) into the {hold_cycles}-cycle hold "
            f"window (value={dut.tb_output_axi_write_count.value})"
        )
        assert observed == expected_writes, (
            f"{label}: tb_output_axi_write_count advanced to {observed} "
            f"(expected it to stay at {expected_writes}) {cycle} clk_smc_i "
            f"cycle(s) after the blocked write -- a write the output filter must "
            f"reject reached the output fabric"
        )
    return observed


# Bound for the SYS_OUT responder observability handshake. The JTAG AXI master
# handshake has already completed when this is called; the responder-side
# counters / last_* registers only need the TB pipeline to update, so anything
# beyond this bound is a real observability failure, not slow timing.
RESPONDER_OBS_TIMEOUT_CYCLES = 200


async def check_output_responder_delta(
    *,
    start_writes: int,
    start_reads: int,
    write_delta: int,
    read_delta: int,
    last_addr: int | None = None,
    last_wdata: int | None = None,
    exact_writes: bool = True,
    timeout_cycles: int = RESPONDER_OBS_TIMEOUT_CYCLES,
) -> None:
    """Wait (bounded) until the SYS_OUT responder shows the expected observation.

    Poll-until-condition on the real observables instead of a fixed settle:
    expiry raises with the last observed state ([TIMEOUT-MUST-FAIL]), and every
    sample is X-aware ([X-AWARE-CHECK]) so a non-resolvable net is reported by
    name rather than silently resolved by ``int()``.

    ``exact_writes`` (default ``True``) makes the write counter an exact
    expectation: ``write_count`` must equal ``start_writes + write_delta``, and a
    counter already past it fails immediately. Every caller passes the exact
    number of fabric writes its scenario issues, so a write the scenario did not
    expect -- e.g. one that leaked through a read-only output filter and left the
    counter at ``start + 2`` -- is a failure ([EXACT-EXPECTATION]). Pass ``exact_writes=False``
    only for
    a scenario where extra write beats are genuinely expected, and say why at the
    call site.

    The read counter keeps ``>=``: timing-seed / fabric side traffic can add
    extra read beats on the output responder.
    """
    dut = cocotb.top
    want_writes = start_writes + write_delta
    want_reads = start_reads + read_delta
    last: dict[str, int | None] = {}
    for _ in range(timeout_cycles):
        last["write_count"] = _resolved_int(dut.tb_output_axi_write_count)
        last["read_count"] = _resolved_int(dut.tb_output_axi_read_count)
        last["last_addr"] = _resolved_int(dut.tb_output_axi_last_addr)
        last["last_wdata"] = _resolved_int(dut.tb_output_axi_last_wdata)
        if exact_writes and last["write_count"] is not None and last["write_count"] > want_writes:
            raise AssertionError(
                "SYS_OUT responder saw MORE writes than this scenario issued: "
                f"write_count={last['write_count']} > expected exactly "
                f"{want_writes} (start={start_writes} + delta={write_delta}). A "
                "write reached the output fabric that the scenario did not "
                "expect -- e.g. a filter-blocked write leaked through"
            )
        satisfied = (
            last["write_count"] is not None
            and last["read_count"] is not None
            and (
                last["write_count"] == want_writes
                if exact_writes
                else last["write_count"] >= want_writes
            )
            and last["read_count"] >= want_reads
        )
        if satisfied and last_addr is not None:
            satisfied = last["last_addr"] == last_addr
        if satisfied and last_wdata is not None:
            satisfied = last["last_wdata"] == last_wdata
        if satisfied:
            cocotb.log.info(
                "output responder observation reached: write_count=%d (%s%d) "
                "read_count=%d (>=%d) last_addr=%s last_wdata=%s",
                last["write_count"],
                "==" if exact_writes else ">=",
                want_writes,
                last["read_count"],
                want_reads,
                "n/a" if last_addr is None else f"0x{last['last_addr']:x}",
                "n/a" if last_wdata is None else f"0x{last['last_wdata']:x}",
            )
            return
        await ClockCycles(dut.clk_smc_i, 1)

    def _fmt(key: str) -> str:
        value = last.get(key)
        return "X/Z" if value is None else f"0x{value:x}"

    raise AssertionError(
        "output responder observation never reached within "
        f"{timeout_cycles} clk_smc_i cycles: "
        f"write_count={_fmt('write_count')} "
        f"(want {'==' if exact_writes else '>='} {want_writes}), "
        f"read_count={_fmt('read_count')} (want >= {want_reads}), "
        f"last_addr={_fmt('last_addr')} "
        f"(want {'n/a' if last_addr is None else hex(last_addr)}), "
        f"last_wdata={_fmt('last_wdata')} "
        f"(want {'n/a' if last_wdata is None else hex(last_wdata)})"
    )
