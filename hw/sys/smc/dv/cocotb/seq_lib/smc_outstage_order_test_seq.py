# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Outbound stage order: alias remap, output remap, outbound filter, output_axi.

Spec sources: fabric.adoc Outbound Filtering and Fabric Topology, alias_remap.rdl,
output_remap.rdl, filter_ctrl.rdl, axi_filter index.adoc Blocked Transactions.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge
from cocotb.utils import get_sim_time
from env.smc_reset_item import SmcResetItem, SmcResetOp
from env.smc_sys_axi_agent import SmcSysAxiGroupItem, SmcSysAxiItem, SmcSysAxiOp

from ._one_shot import _OneShot
from .smc_addr_map import _REPO, reg_field_encode, smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_output_fabric_vip_utils import (
    RESPONDER_OBS_TIMEOUT_CYCLES,
    check_output_responder_delta,
    output_responder_counts,
)
from .smc_rdl_regmap import rdl_contract, smc_reg_addr
from .smc_reset_seq_base import SmcResetSeqBase

_FILTER_H = _REPO / "hw" / "ip" / "axi_filter" / "regs" / "gen" / "c" / "filter_ctrl.h"

_WORD = 8
RESP_OKAY = 0
RESP_DECERR = 3
_SENTINEL = 0x5A5A_5A5A_5A5A_5A5A
_SLOT_MASK = (1 << 20) - 1

# Test-chosen region words in the field layout of output_remap.rdl REGION_ATTRS
# (offset[55:0], valid at bit 63) and alias_remap.rdl REGION_START / REGION_END /
# REGION_ATTRS, whose offset is added to the input address.
_VALID = 1 << 63
_M0_TARGET = 0x0240_0000
_X0_TARGET = 0x0260_0000
_M0_WORD = _VALID | _M0_TARGET
_X0_WORD = _VALID | _X0_TARGET
_ALIAS_START = 0x0300_0000
_ALIAS_END = 0x0300_1000
_ALIAS_OFFSET = 0xBE00_0000
_ALIAS_WORD = _VALID | _ALIAS_OFFSET
_ALIAS_REGION = 2

_MMODE_WINDOW = smc_addr("SMC_TOP_MMODE_REGION_BASE_ADDR")
_XVISOR_WINDOW = smc_addr("SMC_TOP_XVISOR_REGION_BASE_ADDR")

# filter_ctrl.rdl FILTER_CONFIG field layout: the test-chosen DENY_B1 word enables the
# entry with allow_burst (4 KiB granule) and no read or write permission; its readback
# carries data_bus_width = 3.
_DENY_B1 = 0x0000_0000_0100_0010
_DENY_B1_READBACK = 0x0000_0000_0100_3010
_GRANULE = 0x1000

_OUT = "SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_{reg}_BASE_ADDR"
_REMAP_ATTRS = "SMC_{unit}_REMAP_0__REGION_REGION_ATTRS_REG_ADDR"
_ENTRY_REGS = ("FILTER_CONFIG", "START_ADDR", "END_ADDR")

# Test-chosen stimulus addresses (SYS_OUT memory, post-remap).
_DENIED_M_WORD_ADDR = _MMODE_WINDOW + 0x40
_DENIED_X_WORD_ADDR = _XVISOR_WINDOW + 0x40
_ALIAS_ADDR = 0x0300_0100
_BLOCK_ADDR = _MMODE_WINDOW + 0x200
_CONTROL_ADDR = _MMODE_WINDOW + 0x1000
_DMA_SRC = 0x0200_0000
_DMA_DST = 0x0200_B000
_DMA_WORD = 0x1122_3344_5566_7788
_SIM_JTAG_ADDR = _MMODE_WINDOW + 0x300
_PEND_DIRECT = 0x0200_C000
_PEND_REMAP = _MMODE_WINDOW + 0x400
_FLIGHT_ADDR = 0x0200_D000
_FRESH_ADDR = 0x0200_E000

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
_DMA_CONFIG_RESET = 0
_DMA_POLLS = 50
_DMA_POLL_CYCLES = 20

# TB ceilings in clk_smc_i edges, not latency claims. Expiry fails with the last state.
AW_POLL_CYCLES = 200
BLOCKED_WINDOW_CYCLES = 64
COLD_ASSERT_BOUND_REF = 400
COLD_RELEASE_BOUND_REF = 2000
FUSE_SENSE_BOUND = 200_000
FUSE_CLEAR_BOUND_REF = 2000
AXI_TIMEOUT_NS = 50_000

# Deterministic SEP_IN accesses (the DMA DONE polls beyond the first add more).
MIN_SEP_IN_ACCESSES = 91

_STEPS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8")
_TERMS = (
    "REGIONS_PROGRAMMED",
    "FILTER_ORDER",
    "ALIAS_THEN_OUTPUT",
    "BLOCKED_LEG",
    "SIMULTANEOUS",
    "PENDING_LEG",
    "RESET_IN_FLIGHT",
    "RECOVERY",
)
_CHECKERS = (
    ("CHK-STAGE-FILTER-POST-REMAP", "S2"),
    ("CHK-INT-REMAP-FILTER", "S2"),
    ("CHK-STAGE-ALIAS-THEN-OUTPUT", "S3"),
    ("CHK-STAGE-BLOCKED-NOTHING-ON-OUTPUT", "S4"),
    ("CHK-STAGE-SIMULTANEOUS", "S5"),
    ("CHK-STAGE-SECOND-WHILE-PENDING", "S6"),
    ("CHK-STAGE-RESET-IN-FLIGHT", "S7"),
)


def _outbound(reg: str, entry: int) -> int:
    return smc_indexed_addr(_OUT.format(reg=reg), entry)


class _OutputWatch:
    """Samples the SYS_OUT address, data and response handshakes on every clk_smc_i edge."""

    def __init__(self) -> None:
        self.stop = False
        self.error: str | None = None
        self.aw_valid_cycles = 0
        self.w_valid_cycles = 0
        self.ar_valid_cycles = 0
        self.samples = 0
        self.aw_hs: list[tuple[int, int]] = []
        self.b_hs: list[int] = []

    def _bit(self, name: str) -> int:
        value = getattr(cocotb.top, name).value
        if not value.is_resolvable:
            self.error = f"{name} is X/Z ({value}) at sample {self.samples}"
            return 0
        return int(value)

    async def run(self) -> None:
        while not self.stop:
            await RisingEdge(cocotb.top.clk_smc_i)
            await ReadOnly()
            self.samples += 1
            awv = self._bit("tb_output_axi_awvalid")
            self.aw_valid_cycles += awv
            self.w_valid_cycles += self._bit("tb_output_axi_wvalid")
            self.ar_valid_cycles += self._bit("tb_output_axi_arvalid")
            now = int(get_sim_time("ps"))
            if awv and self._bit("tb_output_axi_awready"):
                self.aw_hs.append((int(cocotb.top.tb_output_axi_awaddr.value), now))
            if self._bit("tb_output_axi_bvalid") and self._bit("tb_output_axi_bready"):
                self.b_hs.append(now)

    def mark(self) -> tuple[int, int, int, int, int]:
        assert self.error is None, self.error
        return (
            self.aw_valid_cycles,
            self.w_valid_cycles,
            self.ar_valid_cycles,
            len(self.aw_hs),
            len(self.b_hs),
        )


class smc_outstage_order_test_seq(SmcResetSeqBase, SmcCsrSeq):
    """Programs the remap regions and outbound entries over SEP_IN and drives JTAG and DMA."""

    ASSERT_BOUND_REF_CYCLES = COLD_ASSERT_BOUND_REF
    RELEASE_BOUND_REF_CYCLES = COLD_RELEASE_BOUND_REF

    def __init__(self, name: str = "smc_outstage_order_test_seq") -> None:
        super().__init__(name)
        self.dispatch_reset = None
        self.finished = False
        self.jtag_accesses = 0
        self._stamps: list[tuple[str, int]] = []
        self._chk_marks: list[tuple[str, int]] = []
        self._waits: list[str] = []
        self._fuse_calls = 0
        self._watch = _OutputWatch()
        self._resets = {
            reg: rdl_contract(f"smc_outbound_filter_ctrl/{reg}").reset_word for reg in _ENTRY_REGS
        }

    async def _dispatch_reset_item(self, item: SmcResetItem) -> None:
        await self.dispatch_reset(item)

    def _mark_step(self, step_id: str) -> None:
        self._stamps.append((step_id, int(get_sim_time("ps"))))

    def _log_chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self._chk_marks.append((chk_id, int(get_sim_time("ps"))))

    # -- primitives -------------------------------------------------------

    async def _fuse_sense(self, label: str) -> None:
        await self.wait_fuse_sense_done(FUSE_SENSE_BOUND)
        self._fuse_calls += 1
        dut = cocotb.top
        state = ",".join(
            f"{n}={int(getattr(dut, n).value)}"
            for n in ("tb_fuse_sense_done", "tb_fuse_reset_n", "tb_rst_warm_smc_clk_n")
        )
        self._waits.append(
            f"wait_fuse_sense_done[{label}] 3 sub-waits bound={FUSE_SENSE_BOUND} {state}"
        )

    def _jtag_item(
        self, op: SmcSysAxiOp, addr: int, data: int | None = None, *, refused: bool = False
    ) -> SmcSysAxiItem:
        item = SmcSysAxiItem(f"outstage_{op.value}_0x{addr:x}")
        item.op = op
        item.addr = addr
        item.length = _WORD
        if data is not None:
            item.wdata = data
        if refused:
            item.allow_error = True
            item.expect_error = True
            item.expected_resp = RESP_DECERR
        return item

    async def _jtag(
        self, op: SmcSysAxiOp, addr: int, data: int | None = None, *, refused: bool = False
    ) -> SmcSysAxiItem:
        item = self._jtag_item(op, addr, data, refused=refused)
        await _OneShot(item, f"{item.get_name()}_os").start(self.env.jtag_axi_agent.sequencer)
        self.jtag_accesses += 1
        want = RESP_DECERR if refused else RESP_OKAY
        assert item.resp_code == want, (
            f"JTAG {op.value} at 0x{addr:x} answered resp {item.resp_code}, want {want}"
        )
        return item

    def _land(self, label: str, addr: int, word: int, land: int, *, check_source: bool) -> None:
        responder = self.cfg.sys_out_mem
        landed = responder.read_int(land, _WORD)
        assert landed == word, (
            f"[{label}] SYS_OUT 0x{land:x} holds 0x{landed:016x}, want the written 0x{word:016x}"
        )
        if check_source and land != addr:
            kept = responder.read_int(addr, _WORD)
            assert kept == _SENTINEL, (
                f"[{label}] SYS_OUT 0x{addr:x} holds 0x{kept:016x}, want its sentinel"
            )

    def _seed(self, *addrs: int) -> None:
        for addr in addrs:
            self.cfg.sys_out_mem.write_int(addr, _SENTINEL, _WORD)

    async def _write_lands(self, label: str, addr: int, word: int, land: int) -> int:
        """OKAY JTAG write, one B at output_axi and the word at the post-remap address."""
        w0, r0 = output_responder_counts()
        await self._jtag(SmcSysAxiOp.WRITE, addr, word)
        await check_output_responder_delta(
            start_writes=w0, start_reads=r0, write_delta=1, read_delta=0
        )
        w1, r1 = output_responder_counts()
        self._waits.append(
            f"output_responder[{label}] bound={RESPONDER_OBS_TIMEOUT_CYCLES} "
            f"last write_count={w1} read_count={r1}"
        )
        self._land(label, addr, word, land, check_source=True)
        return w1

    async def _refused_write(self, label: str, addr: int, word: int, window: int) -> dict:
        """DECERR JTAG write; no AW/W valid and no write_count advance for ``window`` cycles."""
        w0, _ = output_responder_counts()
        before = self._watch.mark()
        item = await self._jtag(SmcSysAxiOp.WRITE, addr, word, refused=True)
        for _ in range(window):
            await RisingEdge(cocotb.top.clk_smc_i)
        after = self._watch.mark()
        w1, _ = output_responder_counts()
        deltas = tuple(b - a for a, b in zip(before, after))
        assert deltas[0] == 0 and deltas[1] == 0, (
            f"[{label}] awvalid {deltas[0]} and wvalid {deltas[1]} cycles at output_axi for a "
            f"refused write"
        )
        assert w1 == w0, f"[{label}] write_count {w0} -> {w1} across a refused write"
        return {"resp": item.resp_code, "aw": deltas[0], "w": deltas[1], "wc": w1, "cycles": window}

    async def _read_back(self, label: str, addr: int, want: int) -> None:
        await self.csr_read(label, addr, expected=want, length=_WORD)

    async def _program(self, label: str, addr: int, value: int, readback: int | None = None):
        await self.csr_write(label, addr, value, length=_WORD)
        await self._read_back(f"{label}_RB", addr, value if readback is None else readback)

    async def _program_entry(self, entry: int, start: int, end: int, config: int, rb: int) -> None:
        await self._program(f"OB{entry}_START", _outbound("START_ADDR", entry), start)
        await self._program(f"OB{entry}_END", _outbound("END_ADDR", entry), end)
        await self._program(f"OB{entry}_CONFIG", _outbound("FILTER_CONFIG", entry), config, rb)

    async def _disable_entry(self, entry: int) -> None:
        word = self._resets["FILTER_CONFIG"]
        await self._program(f"OB{entry}_CONFIG_OFF", _outbound("FILTER_CONFIG", entry), word)

    async def _restore_entry(self, entry: int) -> None:
        for reg in _ENTRY_REGS:
            await self._program(
                f"OB{entry}_{reg}_RESTORE", _outbound(reg, entry), self._resets[reg]
            )

    # -- bounded polls ------------------------------------------------------

    async def _await_aw(self, label: str, base: int, count: int) -> list[tuple[int, int]]:
        for _ in range(AW_POLL_CYCLES):
            assert self._watch.error is None, self._watch.error
            if len(self._watch.aw_hs) - base >= count:
                break
            await RisingEdge(cocotb.top.clk_smc_i)
        got = self._watch.aw_hs[base:]
        self._waits.append(
            f"aw_handshakes[{label}] bound={AW_POLL_CYCLES} last count={len(got)} of {count}"
        )
        assert len(got) >= count, (
            f"{label}: {len(got)} AW handshakes at output_axi within {AW_POLL_CYCLES} cycles, "
            f"want {count} (last {[hex(a) for a, _ in got]})"
        )
        return got

    async def _await_low(self, name: str, bound: int, label: str) -> None:
        sig = getattr(cocotb.top, name)
        last = None
        for _ in range(bound):
            value = sig.value
            assert value.is_resolvable, f"{label}: {name} is X/Z ({value})"
            last = int(value)
            if last == 0:
                self._waits.append(f"{label} bound={bound} clk_ref_i last {name}={last}")
                return
            await RisingEdge(cocotb.top.clk_ref_i)
        raise AssertionError(f"{label}: {name} stayed {last} for {bound} clk_ref_i edges")

    # -- DMA --------------------------------------------------------------

    async def _dma_submit(self, src: int, dst: int) -> int:
        baseline = await self.csr_read("DMA_DONE_BASE", _DMA["DONE_0"])
        await self.csr_write("DMA_CONFIG", _DMA["CONFIG"], _DMA_CONFIG_ENABLED_ND)
        for name, value in (
            ("DST_ADDRESS_LO", dst & 0xFFFF_FFFF),
            ("DST_ADDRESS_HI", dst >> 32),
            ("SRC_ADDRESS_LO", src & 0xFFFF_FFFF),
            ("SRC_ADDRESS_HI", src >> 32),
            ("LENGTH_LO", _WORD),
            ("LENGTH_HI", 0),
            ("DST_STRIDE_LO", 0),
            ("DST_STRIDE_HI", 0),
            ("SRC_STRIDE_LO", 0),
            ("SRC_STRIDE_HI", 0),
            ("NUM_REPETITIONS_LO", 1),
            ("NUM_REPETITIONS_HI", 0),
        ):
            await self.csr_write(f"DMA_{name}", _DMA[name], value)
        return baseline

    async def _dma_done(self, baseline: int) -> tuple[int, int]:
        last = baseline
        for poll in range(1, _DMA_POLLS + 1):
            last = await self.csr_read("DMA_DONE_POLL", _DMA["DONE_0"])
            if last > baseline:
                self._waits.append(
                    f"dma_done bound={_DMA_POLLS}x{_DMA_POLL_CYCLES} cycles last DONE_0={last} "
                    f"after {poll} polls"
                )
                return poll, int(get_sim_time("ps"))
            await ClockCycles(cocotb.top.clk_smc_i, _DMA_POLL_CYCLES)
        status = await self.csr_read("DMA_STATUS", _DMA["STATUS_0"])
        raise AssertionError(
            f"DMA DONE_0 stayed at {baseline} over {_DMA_POLLS} polls, STATUS 0x{status:x}"
        )

    # -- cold reset ---------------------------------------------------------

    async def _cold_reset(self) -> None:
        await self._send(SmcResetOp.COLD_RST_LO)
        await self._wait_state(
            "COLD_ASSERT",
            expect_powergood_stable=1,
            expect_rst_cold_stable_ref_clk_n=0,
            expect_rst_primary_ref_clk_n=0,
            expect_rst_primary_smc_clk_n=0,
            expect_left_stable=True,
        )
        await self._await_low("tb_fuse_sense_done", FUSE_CLEAR_BOUND_REF, "FUSE_SENSE_CLEARED")
        await self._send(SmcResetOp.COLD_RST_HI)
        await self._wait_released("COLD_RELEASE")

    # -- body ---------------------------------------------------------------

    async def body(self) -> None:
        dut = cocotb.top
        responder = self.cfg.sys_out_mem
        assert responder is not None, "SYS_OUT responder not bound"
        assert dut.tb_output_axi_resp_hold.value.is_resolvable
        assert int(dut.tb_output_axi_resp_hold.value) == 0, "tb_output_axi_resp_hold not idle"
        watcher = cocotb.start_soon(self._watch.run())
        try:
            await self._scenario(responder)
        finally:
            dut.tb_output_axi_resp_hold.value = 0
            self._watch.stop = True
        await watcher
        assert self._watch.error is None, self._watch.error

    async def _scenario(self, responder) -> None:
        dut = cocotb.top
        resets = self._resets
        assert resets["FILTER_CONFIG"] == 0x3000, (
            f"FILTER_CONFIG reset 0x{resets['FILTER_CONFIG']:x}"
        )
        deny_encoded = reg_field_encode(
            _FILTER_H, "FILTER_CTRL", "FILTER_CONFIG", entry_enabled=1, allow_burst=1
        )
        assert deny_encoded == _DENY_B1, f"DENY_B1 encodes as 0x{deny_encoded:x}"
        m_attrs = smc_reg_addr(_REMAP_ATTRS.format(unit="MMODE"))
        x_attrs = smc_reg_addr(_REMAP_ATTRS.format(unit="XVISOR"))
        alias = {
            name: smc_reg_addr(f"SMC_ALIAS_REMAP_{_ALIAS_REGION}__REGION_REGION_{name}_REG_ADDR")
            for name in ("START", "END", "ATTRS")
        }
        remap_default = smc_reg_addr("OUTPUT_REMAP_REGION_REGION_ATTRS_REG_DEFAULT")

        # S1: regions programmed, outbound entries 1 and 2 clear, probe words seeded.
        await self._fuse_sense("initial")
        await self._program("M0_ATTRS", m_attrs, _M0_WORD)
        await self._program("X0_ATTRS", x_attrs, _X0_WORD)
        await self._program("ALIAS2_START", alias["START"], _ALIAS_START)
        await self._program("ALIAS2_END", alias["END"], _ALIAS_END)
        await self._program("ALIAS2_ATTRS", alias["ATTRS"], _ALIAS_WORD)
        for entry in (1, 2):
            got = await self.csr_read(
                f"OB{entry}_CONFIG_IDLE",
                _outbound("FILTER_CONFIG", entry),
                expected=resets["FILTER_CONFIG"],
                length=_WORD,
            )
            assert got & 0x10 == 0, f"outbound entry {entry} entry_enabled set (0x{got:x})"
        m_word = _M0_TARGET + (_DENIED_M_WORD_ADDR - _MMODE_WINDOW)
        x_word = _X0_TARGET + (_DENIED_X_WORD_ADDR - _XVISOR_WINDOW)
        self._seed(_DENIED_M_WORD_ADDR, _DENIED_X_WORD_ADDR, m_word, x_word)
        self._mark_step("S1")

        # S2: the outbound filter decides on the post-remap address.
        for entry, target in ((1, _M0_TARGET), (2, _X0_TARGET)):
            await self._program_entry(
                entry, target, target + _GRANULE - 1, _DENY_B1, _DENY_B1_READBACK
            )
        word_m, word_x = 0xA2A2_0000_0000_0040, 0xB2B2_0000_0000_0040
        refused_m = await self._refused_write("DENY_M", _DENIED_M_WORD_ADDR, word_m, 0)
        refused_x = await self._refused_write("DENY_X", _DENIED_X_WORD_ADDR, word_x, 0)
        for addr in (m_word, x_word, _DENIED_M_WORD_ADDR, _DENIED_X_WORD_ADDR):
            kept = responder.read_int(addr, _WORD)
            assert kept == _SENTINEL, (
                f"SYS_OUT 0x{addr:x} holds 0x{kept:016x} after a refused write"
            )
        for entry, window in ((1, _MMODE_WINDOW), (2, _XVISOR_WINDOW)):
            await self._program_entry(
                entry, window, window + _GRANULE - 1, _DENY_B1, _DENY_B1_READBACK
            )
        wc_m = await self._write_lands("WINDOW_M", _DENIED_M_WORD_ADDR, word_m, m_word)
        wc_x = await self._write_lands("WINDOW_X", _DENIED_X_WORD_ADDR, word_x, x_word)
        self._mark_step("S2")
        self._log_chk(
            "CHK-STAGE-FILTER-POST-REMAP",
            f"entries over 0x{_M0_TARGET:x} and 0x{_X0_TARGET:x} answered DECERR "
            f"(resp {refused_m['resp']},{refused_x['resp']}) at 0x{_DENIED_M_WORD_ADDR:x} and "
            f"0x{_DENIED_X_WORD_ADDR:x} with the sentinels kept at 0x{m_word:x} and 0x{x_word:x}; "
            f"entries over the window addresses answered OKAY and the words landed at "
            f"0x{m_word:x} and 0x{x_word:x} (write_count {wc_m},{wc_x})",
        )
        self._log_chk(
            "CHK-INT-REMAP-FILTER",
            f"M-mode word decided on 0x{m_word:x} (refused, awvalid {refused_m['aw']} wvalid "
            f"{refused_m['w']} cycles, then landed once only the window entry existed) and Xvisor "
            f"word decided on 0x{x_word:x} (refused, awvalid {refused_x['aw']} wvalid "
            f"{refused_x['w']}, then landed); probes resolvable over {self._watch.samples} samples",
        )

        # S3: alias remap then output remap.
        await self._disable_entry(1)
        await self._disable_entry(2)
        alias_land = _M0_TARGET + (_ALIAS_ADDR + _ALIAS_OFFSET - _MMODE_WINDOW)
        window_alias = _ALIAS_ADDR + _ALIAS_OFFSET
        self._seed(_ALIAS_ADDR, window_alias, alias_land)
        alias_word = 0xA3A3_0000_0000_0100
        await self._write_lands("ALIAS_THEN_OUTPUT", _ALIAS_ADDR, alias_word, alias_land)
        for addr in (_ALIAS_ADDR, window_alias):
            kept = responder.read_int(addr, _WORD)
            assert kept == _SENTINEL, f"SYS_OUT 0x{addr:x} holds 0x{kept:016x}, want its sentinel"
        self._mark_step("S3")
        self._log_chk(
            "CHK-STAGE-ALIAS-THEN-OUTPUT",
            f"write at 0x{_ALIAS_ADDR:x} landed at 0x{alias_land:x}; 0x{window_alias:x} and "
            f"0x{_ALIAS_ADDR:x} kept their sentinels",
        )

        # S4: a blocked request leaves output_axi idle.
        await self._program_entry(
            1, _M0_TARGET, _M0_TARGET + _GRANULE - 1, _DENY_B1, _DENY_B1_READBACK
        )
        block_land = _M0_TARGET + (_BLOCK_ADDR - _MMODE_WINDOW)
        control_land = _M0_TARGET + (_CONTROL_ADDR - _MMODE_WINDOW)
        self._seed(_BLOCK_ADDR, block_land, control_land, _CONTROL_ADDR)
        refused = await self._refused_write("BLOCKED", _BLOCK_ADDR, 0xA4A4_0000_0000_0200, 64)
        for addr in (block_land, _BLOCK_ADDR):
            kept = responder.read_int(addr, _WORD)
            assert kept == _SENTINEL, f"SYS_OUT 0x{addr:x} holds 0x{kept:016x}, want its sentinel"
        wc_ctl = await self._write_lands(
            "CONTROL", _CONTROL_ADDR, 0xA4A4_0000_0000_1000, control_land
        )
        assert wc_ctl == refused["wc"] + 1, f"control write_count {refused['wc']} -> {wc_ctl}"
        self._mark_step("S4")
        self._log_chk(
            "CHK-STAGE-BLOCKED-NOTHING-ON-OUTPUT",
            f"write at 0x{_BLOCK_ADDR:x} answered DECERR (resp {refused['resp']}); over "
            f"{refused['cycles']} cycles awvalid {refused['aw']} and wvalid {refused['w']} "
            f"cycles read 1 and write_count stayed {refused['wc']}; sentinels at 0x{block_land:x} "
            f"and 0x{_BLOCK_ADDR:x} kept; control write at 0x{_CONTROL_ADDR:x} landed at "
            f"0x{control_land:x} and write_count advanced {refused['wc']} -> {wc_ctl}",
        )

        # S5: DMA on the direct path and JTAG on the remap path together.
        await self._disable_entry(1)
        sim_land = _M0_TARGET + (_SIM_JTAG_ADDR - _MMODE_WINDOW)
        responder.write_int(_DMA_SRC, _DMA_WORD, _WORD)
        self._seed(_DMA_DST, sim_land, _SIM_JTAG_ADDR)
        sim_word = 0xA5A5_0000_0000_0300
        aw_base = len(self._watch.aw_hs)
        baseline = await self._dma_submit(_DMA_SRC, _DMA_DST)
        sim_item = self._jtag_item(SmcSysAxiOp.WRITE, _SIM_JTAG_ADDR, sim_word)
        sim_task = cocotb.start_soon(
            _OneShot(sim_item, "sim_jtag_os").start(self.env.jtag_axi_agent.sequencer)
        )
        await self.csr_read("DMA_NEXT_ID", _DMA["NEXT_ID_0"])
        polls, done_ps = await self._dma_done(baseline)
        await sim_task
        self.jtag_accesses += 1
        assert sim_item.resp_code == RESP_OKAY, f"simultaneous JTAG write resp {sim_item.resp_code}"
        hs = dict(self._watch.aw_hs[aw_base:])
        assert _SIM_JTAG_ADDR - _MMODE_WINDOW + _M0_TARGET in hs, (
            f"no AW at 0x{sim_land:x} (saw {[hex(a) for a in hs]})"
        )
        jtag_ps = hs[sim_land]
        assert jtag_ps < done_ps, f"JTAG AW at {jtag_ps} ps after DONE_0 advanced at {done_ps} ps"
        self._land("DMA", _DMA_DST, _DMA_WORD, _DMA_DST, check_source=False)
        self._land("JTAG", _SIM_JTAG_ADDR, sim_word, sim_land, check_source=True)
        await self.csr_restore("DMA_CONFIG", _DMA["CONFIG"], _DMA_CONFIG_RESET)
        self._mark_step("S5")
        self._log_chk(
            "CHK-STAGE-SIMULTANEOUS",
            f"DONE_0 advanced after {polls} polls (bound {_DMA_POLLS}x{_DMA_POLL_CYCLES} cycles) "
            f"at {done_ps} ps, the JTAG AW at output_axi was accepted at {jtag_ps} ps before it; "
            f"DMA payload 0x{_DMA_WORD:016x} landed at 0x{_DMA_DST:x} and the JTAG word at "
            f"0x{sim_land:x}; output AW handshakes {[hex(a) for a in hs]}",
        )

        # S6: a second request is accepted while the first awaits its response.
        pend_land = _M0_TARGET + (_PEND_REMAP - _MMODE_WINDOW)
        self._seed(_PEND_DIRECT, pend_land, _PEND_REMAP)
        words = (0xA6A6_0000_0000_C000, 0xA6A6_0000_0000_0400)
        group = SmcSysAxiGroupItem(
            "outstage_pending",
            [
                self._jtag_item(SmcSysAxiOp.WRITE, _PEND_DIRECT, words[0]),
                self._jtag_item(SmcSysAxiOp.WRITE, _PEND_REMAP, words[1]),
            ],
        )
        w_before, _ = output_responder_counts()
        aw_base = len(self._watch.aw_hs)
        marks = self._watch.mark()
        dut.tb_output_axi_resp_hold.value = 1
        group_task = cocotb.start_soon(
            _OneShot(group, "pending_group_os").start(self.env.jtag_axi_agent.sequencer)
        )
        try:
            got = await self._await_aw("PENDING", aw_base, 2)
            w_during, _ = output_responder_counts()
            during = self._watch.mark()
            assert not group_task.done(), "the JTAG group completed while responses were held"
            assert all(m.resp_code is None for m in group.items), "a B reached the initiator"
            assert during[4] == marks[4], f"{during[4] - marks[4]} B handshakes under hold"
            assert w_during == w_before, f"write_count {w_before} -> {w_during} under hold"
        finally:
            dut.tb_output_axi_resp_hold.value = 0
        await group_task
        self.jtag_accesses += 2
        codes = [m.resp_code for m in group.items]
        assert codes == [RESP_OKAY, RESP_OKAY], f"pending group answered {codes}"
        assert {a for a, _ in got} == {_PEND_DIRECT, pend_land}, (
            f"AW addresses {[hex(a) for a, _ in got]}"
        )
        self._land("PEND_DIRECT", _PEND_DIRECT, words[0], _PEND_DIRECT, check_source=False)
        self._land("PEND_REMAP", _PEND_REMAP, words[1], pend_land, check_source=True)
        self._mark_step("S6")
        self._log_chk(
            "CHK-STAGE-SECOND-WHILE-PENDING",
            f"under tb_output_axi_resp_hold two AW handshakes at "
            f"{[hex(a) for a, _ in got]} (bound {AW_POLL_CYCLES} cycles) with write_count "
            f"{w_before}->{w_during} and no B handshake; after the release both answered "
            f"{codes} and landed at 0x{_PEND_DIRECT:x} and 0x{pend_land:x}",
        )

        # S7: cold reset with a write in flight (observe-only fate, owner value pending).
        responder.write_int(_FLIGHT_ADDR, _SENTINEL, _WORD)
        flight_word = 0xA7A7_0000_0000_D000
        flight = self._jtag_item(SmcSysAxiOp.WRITE, _FLIGHT_ADDR, flight_word)
        flight.allow_timeout = True
        flight.allow_error = True
        aw_base = len(self._watch.aw_hs)
        dut.tb_output_axi_resp_hold.value = 1
        flight_task = cocotb.start_soon(
            _OneShot(flight, "flight_os").start(self.env.jtag_axi_agent.sequencer)
        )
        try:
            seen = await self._await_aw("IN_FLIGHT", aw_base, 1)
            assert seen[0][0] == _FLIGHT_ADDR, f"in-flight AW at 0x{seen[0][0]:x}"
            w_flight, r_flight = output_responder_counts()
            assert not flight_task.done(), "the in-flight write completed before the reset"
            await self._cold_reset()
        finally:
            dut.tb_output_axi_resp_hold.value = 0
        await self._fuse_sense("after_cold_reset")
        await flight_task
        self.jtag_accesses += 1
        fate = (
            f"timed_out={flight.timed_out} resp={flight.resp_code} "
            f"memory=0x{responder.read_int(_FLIGHT_ADDR, _WORD):016x}"
        )
        fresh_word = 0xA7A7_0000_0000_E000
        await self._jtag(SmcSysAxiOp.WRITE, _FRESH_ADDR, fresh_word)
        got = await self._jtag(SmcSysAxiOp.READ, _FRESH_ADDR)
        assert got.rdata == fresh_word, f"fresh read 0x{got.rdata:016x}, want 0x{fresh_word:016x}"
        self._land("FRESH", _FRESH_ADDR, fresh_word, _FRESH_ADDR, check_source=False)
        w_after, r_after = output_responder_counts()
        probes = ",".join(
            f"{n}={int(getattr(dut, n).value)}"
            for n in ("tb_output_axi_awvalid", "tb_output_axi_wvalid", "tb_output_axi_arvalid")
        )
        self._mark_step("S7")
        self._log_chk(
            "CHK-STAGE-RESET-IN-FLIGHT",
            f"fate of the interrupted write at 0x{_FLIGHT_ADDR:x} (observe-only, owner "
            f"value pending, not compared): {fate}; counters before reset write_count={w_flight} "
            f"read_count={r_flight}, after recovery write_count={w_after} read_count={r_after}; "
            f"{probes}; the fresh JTAG write and read at 0x{_FRESH_ADDR:x} answered OKAY "
            f"and read back 0x{got.rdata:016x}",
        )

        # S8: every programmed register is back at its reset word.
        for entry in (1, 2):
            await self.csr_read(
                f"OB{entry}_CONFIG_AFTER_RESET",
                _outbound("FILTER_CONFIG", entry),
                expected=resets["FILTER_CONFIG"],
                length=_WORD,
            )
        await self.csr_read("M0_AFTER_RESET", m_attrs, expected=remap_default, length=_WORD)
        for entry in (1, 2):
            await self._restore_entry(entry)
        for label, addr in (("M0", m_attrs), ("X0", x_attrs), ("ALIAS2_ATTRS", alias["ATTRS"])):
            await self._program(f"{label}_RESTORE", addr, remap_default)
        for label in ("START", "END"):
            await self._program(f"ALIAS2_{label}_RESTORE", alias[label], remap_default)
        self._mark_step("S8")
        self.finished = True
        self._nonvac_fence()

    def _nonvac_fence(self) -> None:
        ids = tuple(s for s, _ in self._stamps)
        assert ids == _STEPS, f"step ids {ids}, want {_STEPS}"
        times = [t for _, t in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"step stamps not increasing: {times}"
        stamp_of = dict(self._stamps)
        chk_ids = tuple(c for c, _ in self._chk_marks)
        assert chk_ids == tuple(c for c, _ in _CHECKERS), f"checker lines {chk_ids}"
        for (chk_id, when), (_, step) in zip(self._chk_marks, _CHECKERS):
            assert when >= stamp_of[step], f"{chk_id} printed before its step {step} stamp"
        assert self._watch.error is None, self._watch.error
        scoreboard_jtag = self.env.scoreboard.axi_accesses_by_bus.get("JTAG AXI", 0)
        assert scoreboard_jtag >= self.jtag_accesses - 1, (
            f"scoreboard counted {scoreboard_jtag} JTAG accesses, sequence issued "
            f"{self.jtag_accesses} (the interrupted write may time out)"
        )
        self._waits.append(
            f"axi_access bound={AXI_TIMEOUT_NS} ns allow_timeout=False (interrupted write: True) "
            f"JTAG accesses {self.jtag_accesses}, SEP_IN accesses {self.accesses}"
        )
        self._waits.append(
            f"output_axi_window bound={BLOCKED_WINDOW_CYCLES} clk_smc_i cycles awvalid/wvalid "
            f"never 1, last aw_valid_cycles={self._watch.aw_valid_cycles}"
        )
        self._waits.extend(self._timeout_paths)
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: %d bounded waits: %s",
            len(self._waits),
            " | ".join(self._waits),
        )
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; stamps %s; SEP_IN accesses %d "
            "(floor %d), JTAG accesses %d, output_axi samples %d",
            "<".join(f"{t}@{s}" for t, s in zip(_TERMS, _STEPS)),
            ",".join(chk_ids),
            ",".join(f"{s}={t}" for s, t in self._stamps),
            self.accesses,
            MIN_SEP_IN_ACCESSES,
            self.jtag_accesses,
            self._watch.samples,
        )
