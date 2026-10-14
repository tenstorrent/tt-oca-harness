# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""REGION_SIZE zero collapse and the reset-based recovery of the fabric.

Spec sources: fabric.adoc Local and Remote Resource Access, Fabric Topology, Outbound Traffic
Flow; smc-programming.adoc Address Map; smc_base_config.rdl GLOBAL_BASE, REGION_SIZE.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge
from cocotb.utils import get_sim_time
from env.smc_reset_item import SmcResetItem, SmcResetOp
from env.smc_sys_axi_agent import SmcSysAxiGroupItem, SmcSysAxiItem, SmcSysAxiOp

from ._one_shot import _OneShot
from .smc_addr_map import smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_output_fabric_vip_utils import (
    INBOUND0_END,
    INBOUND0_FILTER_CONFIG,
    INBOUND0_START,
    OUTPUT_FABRIC_ADDR,
    PASS_ALL_CONFIG,
    RESPONDER_OBS_TIMEOUT_CYCLES,
    check_output_responder_delta,
    output_responder_counts,
)
from .smc_rdl_regmap import rdl_contract
from .smc_reset_seq_base import SmcResetSeqBase

_WORD = 8
RESP_OKAY = 0
RESP_DECERR = 3
PASS_ALL_END = 0x00FF_FFFF_FFFF_FFFF
_SCRATCH_OFFSET = 0x2800

_GLOBAL_BASE = smc_addr("SMC_TOP_SMC_BASE_CONFIG_GLOBAL_BASE_BASE_ADDR")
_LOCAL_BASE = smc_addr("SMC_TOP_SMC_BASE_CONFIG_LOCAL_BASE_BASE_ADDR")
_REGION_SIZE = smc_addr("SMC_TOP_SMC_BASE_CONFIG_REGION_SIZE_BASE_ADDR")
_SCRATCH_SYM = "SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_SCRATCH_BASE_ADDR"
_RESET = {
    name: rdl_contract(f"smc_base_config/{name}").reset_word
    for name in ("GLOBAL_BASE", "LOCAL_BASE", "REGION_SIZE")
}
_FILTER_RESET = {
    reg: rdl_contract(f"smc_inbound_filter_ctrl/{reg}").reset_word
    for reg in ("START_ADDR", "END_ADDR", "FILTER_CONFIG")
}
_SCRATCH_RESET = rdl_contract("smc_misc_wrap/scratch_cold/SCRATCH[0]").reset_word

# Test-chosen values for the reprogrammed window.
_GLOBAL_BASE_PROGRAMMED = 0x8000_0000
_REGION_SIZE_PROGRAMMED = 0x0200_0000

# TB ceilings in clk_smc_i / clk_ref_i edges, not latency claims. Expiry fails with the last state.
HS_POLL_CYCLES = 200
HOLD_POLL_CYCLES = 400
QUIET_WINDOW_CYCLES = 64
COLD_ASSERT_BOUND_REF = 400
COLD_RELEASE_BOUND_REF = 2000
FUSE_CLEAR_BOUND_REF = 2000
FUSE_SENSE_BOUND = 200_000
AXI_TIMEOUT_NS = 50_000

_OUTSTANDING_READS = 8
_OUTSTANDING_WRITES = 4

# Sequential SEP_IN accesses the stimulus issues (outstanding groups excluded).
MIN_SEP_IN_ACCESSES = 44

_STEPS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7")
_TERMS = (
    "SETUP",
    "REGION_ZERO_DECERR",
    "REGION_ZERO_JTAG",
    "RESET_RECOVERY",
    "RESET_INBOUND",
    "RESET_OUTBOUND",
    "RESET_RESTORES",
)
_CHECKERS = (
    ("CHK-REGION-ZERO-DECERR", "S2"),
    ("CHK-REGION-ZERO-JTAG-OUTBOUND", "S3"),
    ("CHK-REGION-ZERO-RESET-RECOVERY", "S4"),
    ("CHK-RESET-MID-INBOUND", "S5"),
    ("CHK-RESET-MID-OUTBOUND", "S6"),
    ("CHK-RESET-RESTORES-WINDOW", "S7"),
)


def _scratch(n: int) -> int:
    return smc_indexed_addr(_SCRATCH_SYM, n)


class _OutputWatch:
    """Records the SYS_OUT address handshakes on every clk_smc_i edge."""

    def __init__(self) -> None:
        self.stop = False
        self.error: str | None = None
        self.samples = 0
        self.aw_hs: list[int] = []
        self.ar_hs: list[int] = []

    def _bit(self, name: str) -> int:
        value = getattr(cocotb.top, name).value
        if not value.is_resolvable:
            self.error = f"{name} is X/Z ({value}) at sample {self.samples}"
            return 0
        return int(value)

    async def run(self) -> None:
        top = cocotb.top
        while not self.stop:
            await RisingEdge(top.clk_smc_i)
            self.samples += 1
            if self._bit("tb_output_axi_awvalid") and self._bit("tb_output_axi_awready"):
                self.aw_hs.append(int(top.tb_output_axi_awaddr.value))
            if self._bit("tb_output_axi_arvalid") and self._bit("tb_output_axi_arready"):
                self.ar_hs.append(int(top.tb_output_axi_araddr.value))


class smc_region_zero_reset_recovery_test_seq(SmcResetSeqBase, SmcCsrSeq):
    """Collapses the window over SEP_IN, then recovers the fabric only through cold resets."""

    ASSERT_BOUND_REF_CYCLES = COLD_ASSERT_BOUND_REF
    RELEASE_BOUND_REF_CYCLES = COLD_RELEASE_BOUND_REF

    def __init__(self, name: str = "smc_region_zero_reset_recovery_test_seq") -> None:
        super().__init__(name)
        self.dispatch_reset = None
        self.finished = False
        self.port_accesses = {"sys": 0, "jtag": 0}
        self._stamps: list[tuple[str, int]] = []
        self._chk_marks: list[tuple[str, int]] = []
        self._waits: list[str] = []
        self._watch = _OutputWatch()

    async def _dispatch_reset_item(self, item: SmcResetItem) -> None:
        await self.dispatch_reset(item)

    def _mark_step(self, step_id: str) -> None:
        self._stamps.append((step_id, int(get_sim_time("ps"))))

    def _log_chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self._chk_marks.append((chk_id, int(get_sim_time("ps"))))

    @staticmethod
    def _sig(name: str) -> int:
        value = getattr(cocotb.top, name).value
        assert value.is_resolvable, f"{name} is X/Z ({value})"
        return int(value)

    # -- accesses -----------------------------------------------------------

    def _item(self, op, addr, data=None, *, resp=RESP_OKAY, expected=None, length=_WORD):
        item = SmcSysAxiItem(f"zero_{op.value}_0x{addr:x}")
        item.op = op
        item.addr = addr
        item.length = length
        if data is not None:
            item.wdata = data
        item.expected = expected
        if resp != RESP_OKAY:
            item.allow_error = True
            item.expect_error = True
            item.expected_resp = resp
        return item

    async def _axi(self, port, op, addr, data=None, **kw) -> SmcSysAxiItem:
        """One access on `port` (sep, sys or jtag); the response code is asserted."""
        want = kw.get("resp", RESP_OKAY)
        item = self._item(op, addr, data, **kw)
        if port == "sep":
            await self.start_item(item)
            await self.finish_item(item)
            self.accesses += 1
        else:
            agent = self.env.sys_in_axi_agent if port == "sys" else self.env.jtag_axi_agent
            await _OneShot(item, f"{item.get_name()}_os").start(agent.sequencer)
            self.port_accesses[port] += 1
        assert item.resp_code == want, (
            f"{port} {op.value} at 0x{addr:x} answered resp {item.resp_code}, want {want}"
        )
        return item

    async def _rd(self, port, label, addr, expected=None, **kw) -> int:
        item = await self._axi(port, SmcSysAxiOp.READ, addr, expected=expected, **kw)
        if expected is not None:
            assert item.rdata == expected, (
                f"{label} read 0x{item.rdata:x}, want 0x{expected:x} (resp {item.resp_code})"
            )
        return item.rdata

    async def _wr(self, port, addr, data, **kw) -> None:
        await self._axi(port, SmcSysAxiOp.WRITE, addr, data, **kw)

    async def _program(self, label: str, addr: int, value: int) -> None:
        await self._wr("sep", addr, value)
        await self._rd("sep", f"{label}_RB", addr, expected=value)

    async def _inbound_pass_all(self) -> None:
        await self._program("INBOUND0_START", INBOUND0_START, 0)
        await self._program("INBOUND0_END", INBOUND0_END, PASS_ALL_END)
        await self._program("INBOUND0_CONFIG", INBOUND0_FILTER_CONFIG, PASS_ALL_CONFIG)

    # -- bounded waits ------------------------------------------------------

    async def _poll(self, label: str, bound: int, probe) -> None:
        """Wait for `probe()` to return (True, state); expiry fails with the last state."""
        state = "never sampled"
        for _ in range(bound):
            done, state = probe()
            assert self._watch.error is None, self._watch.error
            if done:
                self._waits.append(f"{label} bound={bound} clk_smc_i last {state}")
                return
            await RisingEdge(cocotb.top.clk_smc_i)
        raise AssertionError(f"{label}: not reached within {bound} clk_smc_i edges, last {state}")

    async def _await_hs(self, label: str, hs: list[int], base: int, addr: int) -> None:
        def probe():
            seen = hs[base:]
            return addr in seen, f"handshakes {[hex(a) for a in seen]}"

        await self._poll(f"{label} want 0x{addr:x}", HS_POLL_CYCLES, probe)

    async def _await_low(self, name: str, bound: int, label: str) -> None:
        sig = getattr(cocotb.top, name)
        last = None
        for _ in range(bound):
            last = self._sig(name)
            if last == 0:
                self._waits.append(f"{label} bound={bound} clk_ref_i last {name}={last}")
                return
            await RisingEdge(cocotb.top.clk_ref_i)
        raise AssertionError(f"{label}: {sig._name} stayed {last} for {bound} clk_ref_i edges")

    async def _quiet(self, label: str, names: tuple[str, ...]) -> None:
        for _ in range(QUIET_WINDOW_CYCLES):
            await RisingEdge(cocotb.top.clk_smc_i)
            levels = {n: self._sig(n) for n in names}
            assert not any(levels.values()), f"{label}: {levels} inside the quiet window"
        self._waits.append(
            f"{label} bound={QUIET_WINDOW_CYCLES} clk_smc_i window last "
            + ",".join(f"{n}=0" for n in names)
        )

    async def _no_unowned_response(self, label: str, ar_base: int, aw_base: int) -> None:
        """B and R handshake counters stay within the requests issued since the bases."""
        for _ in range(QUIET_WINDOW_CYCLES):
            await RisingEdge(cocotb.top.clk_smc_i)
            writes, reads = output_responder_counts()
            aw, ar = len(self._watch.aw_hs) - aw_base, len(self._watch.ar_hs) - ar_base
            assert writes <= aw and reads <= ar, (
                f"{label}: write_count {writes} for {aw} AW and read_count {reads} for {ar} AR "
                f"handshakes since the reset: a response without a request"
            )
        self._waits.append(
            f"{label} bound={QUIET_WINDOW_CYCLES} clk_smc_i window last write_count={writes} "
            f"read_count={reads} aw={aw} ar={ar}"
        )

    async def _fuse_sense(self, label: str) -> None:
        await self.wait_fuse_sense_done(FUSE_SENSE_BOUND)
        state = ",".join(
            f"{n}={self._sig(n)}"
            for n in ("tb_fuse_sense_done", "tb_fuse_reset_n", "tb_rst_warm_smc_clk_n")
        )
        self._waits.append(
            f"wait_fuse_sense_done[{label}] 3 sub-waits bound={FUSE_SENSE_BOUND} {state}"
        )

    async def _cold_reset(self, tag: str) -> None:
        await self._send(SmcResetOp.COLD_RST_LO)
        await self._wait_state(
            f"COLD_ASSERT_{tag}",
            expect_powergood_stable=1,
            expect_rst_cold_stable_ref_clk_n=0,
            expect_rst_primary_ref_clk_n=0,
            expect_rst_primary_smc_clk_n=0,
            expect_left_stable=True,
        )
        await self._await_low("tb_fuse_sense_done", FUSE_CLEAR_BOUND_REF, f"FUSE_CLEARED_{tag}")
        await self._send(SmcResetOp.COLD_RST_HI)
        await self._wait_released(f"COLD_RELEASE_{tag}")

    async def _recover(self, tag: str) -> None:
        await self._cold_reset(tag)
        await self._fuse_sense(f"after_reset_{tag}")

    # -- outstanding groups -------------------------------------------------

    def _group(self, port: str, members: list[SmcSysAxiItem]) -> tuple[object, list]:
        for item in members:
            item.allow_timeout = True
            item.allow_error = True
        group = SmcSysAxiGroupItem(f"zero_{port}_group", members)
        agent = {
            "sep": self.env.sys_axi_agent,
            "sys": self.env.sys_in_axi_agent,
            "jtag": self.env.jtag_axi_agent,
        }[port]
        task = cocotb.start_soon(_OneShot(group, f"zero_{port}_group_os").start(agent.sequencer))
        return task, members

    @staticmethod
    def _fates(members: list[SmcSysAxiItem]) -> str:
        return ",".join(
            f"{'W' if m.op is SmcSysAxiOp.WRITE else 'R'}:"
            f"{'timeout' if m.timed_out else f'resp{m.resp_code}'}"
            for m in members
        )

    def _inbound_members(self, port: str, tag: int) -> list[SmcSysAxiItem]:
        members = [
            self._item(SmcSysAxiOp.READ, _scratch(n), length=4) for n in range(_OUTSTANDING_READS)
        ]
        members += [
            self._item(SmcSysAxiOp.WRITE, _scratch(n), (tag << 24) | n, length=4)
            for n in range(_OUTSTANDING_WRITES)
        ]
        return members

    # -- body ---------------------------------------------------------------

    async def body(self) -> None:
        top = cocotb.top
        responder = self.cfg.sys_out_mem
        assert responder is not None, "SYS_OUT responder not bound"
        for knob in (
            "tb_sep_axi_r_hold",
            "tb_sep_axi_b_hold",
            "tb_sys_axi_r_hold",
            "tb_output_axi_resp_hold",
        ):
            assert self._sig(knob) == 0, f"{knob} not idle"
        watcher = cocotb.start_soon(self._watch.run())
        try:
            await self._scenario(responder)
        finally:
            for knob in (
                "tb_sep_axi_r_hold",
                "tb_sep_axi_b_hold",
                "tb_sys_axi_r_hold",
                "tb_output_axi_resp_hold",
            ):
                getattr(top, knob).value = 0
            self._watch.stop = True
            await watcher

    async def _scenario(self, responder) -> None:
        top = cocotb.top
        await self._fuse_sense("initial")

        # S1: pass-all inbound entry 0 and the window registers at their reset words.
        await self._rd("sep", "GLOBAL_BASE_RESET", _GLOBAL_BASE, _RESET["GLOBAL_BASE"])
        local_base = await self._rd("sep", "LOCAL_BASE_RESET", _LOCAL_BASE, _RESET["LOCAL_BASE"])
        global_base = _RESET["GLOBAL_BASE"]
        await self._rd("sep", "REGION_SIZE_RESET", _REGION_SIZE, _RESET["REGION_SIZE"])
        await self._inbound_pass_all()
        self._mark_step("S1")

        # S2: REGION_SIZE 0, then both ports decode LOCAL_BASE and GLOBAL_BASE to DECERR.
        await self._wr("sep", _REGION_SIZE, 0)
        self.env.axi_monitor.expected_decerr_addrs.update({local_base, global_base})
        codes = []
        for port in ("sep", "sys"):
            for base in (local_base, global_base):
                await self._rd(port, f"{port}_RD_0x{base:x}", base, resp=RESP_DECERR)
                await self._wr(port, base, 0xD0D0_0000_0000_0000 | base, resp=RESP_DECERR)
                codes.append(f"{port}@0x{base:x}:R3,W3")
        self._mark_step("S2")
        self._log_chk(
            "CHK-REGION-ZERO-DECERR",
            f"after REGION_SIZE=0 a read and a write at LOCAL_BASE 0x{local_base:x} and "
            f"GLOBAL_BASE "
            f"0x{global_base:x} answered DECERR (3) on sep_axi_in and sys_axi_in ({len(codes) * 2} "
            f"cases: {' '.join(codes)}); inbound entry 0 held pass-all, hit probes "
            f"read_hit0={self._sig_bit('tb_inb_read_hit', 0)} "
            f"write_hit0={self._sig_bit('tb_inb_write_hit', 0)} (observed)",
        )

        # S3: jtag at LOCAL_BASE+0x2800 and GLOBAL_BASE+0x2800 leaves through output_axi.
        scratch0_pre = _scratch(0)
        assert scratch0_pre == local_base + _SCRATCH_OFFSET
        seen = []
        for base, seed, word in (
            (local_base, 0x3A3A_0000_0000_0001, 0x3B3B_0000_0000_0001),
            (global_base, 0x3A3A_0000_0000_0002, 0x3B3B_0000_0000_0002),
        ):
            addr = base + _SCRATCH_OFFSET
            responder.write_int(addr, seed, _WORD)
            w0, r0 = output_responder_counts()
            ar_base, aw_base = len(self._watch.ar_hs), len(self._watch.aw_hs)
            got = await self._rd("jtag", f"JTAG_RD_0x{addr:x}", addr, expected=seed)
            await self._await_hs("AR_at_output_axi", self._watch.ar_hs, ar_base, addr)
            await self._wr("jtag", addr, word)
            await self._await_hs("AW_at_output_axi", self._watch.aw_hs, aw_base, addr)
            await check_output_responder_delta(
                start_writes=w0, start_reads=r0, write_delta=1, read_delta=1
            )
            self._waits.append(
                f"output_responder[0x{addr:x}] bound={RESPONDER_OBS_TIMEOUT_CYCLES} "
                f"last write_count={output_responder_counts()[0]}"
            )
            held = responder.read_int(addr, _WORD)
            assert held == word, f"SYS_OUT 0x{addr:x} holds 0x{held:016x}, want 0x{word:016x}"
            seen.append(f"0x{addr:x}:read 0x{got:x} written 0x{word:x}")
        self._mark_step("S3")
        self._log_chk(
            "CHK-REGION-ZERO-JTAG-OUTBOUND",
            f"with REGION_SIZE=0 jtag_axi_in reads and writes answered OKAY from the SYS_OUT "
            f"responder with AR and AW on tb_output_axi_araddr/awaddr equal to the 56-bit "
            f"address ({'; '.join(seen)}); the SMC register at 0x{scratch0_pre:x} is read after "
            f"the reset in CHK-REGION-ZERO-RESET-RECOVERY",
        )

        # S4: the reset is the recovery from REGION_SIZE 0.
        await self._recover("ZERO")
        size = await self._rd("sep", "REGION_SIZE_AFTER", _REGION_SIZE, _RESET["REGION_SIZE"])
        base = await self._rd("sep", "GLOBAL_BASE_AFTER", _GLOBAL_BASE, _RESET["GLOBAL_BASE"])
        await self._rd("sep", "LOCAL_BASE_AFTER", _LOCAL_BASE, _RESET["LOCAL_BASE"])
        scratch0 = await self._rd(
            "sep", "SCRATCH_COLD0_AFTER", _scratch(0), _SCRATCH_RESET, length=4
        )
        self._mark_step("S4")
        self._log_chk(
            "CHK-REGION-ZERO-RESET-RECOVERY",
            f"after the cold reset REGION_SIZE read 0x{size:08x} and GLOBAL_BASE 0x{base:08x} "
            f"through sep_axi_in with OKAY, SCRATCH_COLD[0] read 0x{scratch0:x} (reset word)",
        )

        # S5: reset with 12 inbound accesses outstanding on each inbound port.
        await self._inbound_pass_all()
        for knob in ("tb_sep_axi_r_hold", "tb_sep_axi_b_hold", "tb_sys_axi_r_hold"):
            getattr(top, knob).value = 1
        sep_task, sep_members = self._group("sep", self._inbound_members("sep", 0x5C))
        sys_task, sys_members = self._group("sys", self._inbound_members("sys", 0x5D))

        def r_pending():
            raw = {n: self._sig(n) for n in ("tb_sep_axi_r_raw_valid", "tb_sys_axi_r_raw_valid")}
            return all(raw.values()), f"{raw}"

        await self._poll("R_held_at_inbound_ports", HOLD_POLL_CYCLES, r_pending)
        assert not sep_task.done() and not sys_task.done(), "outstanding group ended before reset"
        await self._recover("INBOUND")
        stale = {n: self._sig(n) for n in ("tb_sep_axi_r_raw_valid", "tb_sys_axi_r_raw_valid")}
        assert not any(stale.values()), f"stale R response presented after the reset: {stale}"
        for knob in ("tb_sep_axi_r_hold", "tb_sep_axi_b_hold", "tb_sys_axi_r_hold"):
            getattr(top, knob).value = 0
        await self._quiet(
            "inbound_stale_window", ("tb_sep_axi_r_raw_valid", "tb_sys_axi_r_raw_valid")
        )
        await sep_task
        await sys_task
        self._waits.append(
            f"outstanding_groups bound={AXI_TIMEOUT_NS} ns per member allow_timeout=True "
            f"(interrupted by the reset, not specified, measured) sep[{self._fates(sep_members)}] "
            f"sys[{self._fates(sys_members)}]"
        )
        first = await self._rd(
            "sep", "REGION_SIZE_POST_INBOUND", _REGION_SIZE, _RESET["REGION_SIZE"]
        )
        landed = [
            await self._rd("sep", f"SCRATCH_COLD{n}", _scratch(n), length=4) for n in range(4)
        ]
        self._mark_step("S5")
        self._log_chk(
            "CHK-RESET-MID-INBOUND",
            f"after a cold reset with {_OUTSTANDING_READS} reads and {_OUTSTANDING_WRITES} writes "
            f"outstanding on each of sep_axi_in and sys_axi_in the first read of REGION_SIZE "
            f"answered OKAY with 0x{first:08x}; r_raw_valid read 0 on both ports at the release "
            f"and for {QUIET_WINDOW_CYCLES} cycles after the holds cleared; pre-reset accesses "
            f"(observe-only, not specified, measured) sep[{self._fates(sep_members)}] "
            f"sys[{self._fates(sys_members)}]; "
            f"SCRATCH_COLD[0..3] read {[hex(v) for v in landed]} (observed)",
        )

        # S6: reset with a jtag read and write pending at output_axi.
        top.tb_output_axi_resp_hold.value = 1
        ar_base, aw_base = len(self._watch.ar_hs), len(self._watch.aw_hs)
        jtag_members = [
            self._item(SmcSysAxiOp.READ, OUTPUT_FABRIC_ADDR),
            self._item(SmcSysAxiOp.WRITE, OUTPUT_FABRIC_ADDR, 0x6A6A_0000_0000_0001),
        ]
        jtag_task, _ = self._group("jtag", jtag_members)
        await self._await_hs("AR_pending", self._watch.ar_hs, ar_base, OUTPUT_FABRIC_ADDR)
        await self._await_hs("AW_pending", self._watch.aw_hs, aw_base, OUTPUT_FABRIC_ADDR)
        assert not jtag_task.done(), "the pending jtag group ended before the reset"
        ar_reset, aw_reset = len(self._watch.ar_hs), len(self._watch.aw_hs)
        await self._cold_reset("OUTBOUND")
        top.tb_output_axi_resp_hold.value = 0
        await self._fuse_sense("after_reset_OUTBOUND")
        await self._no_unowned_response("output_stale_window", ar_reset, aw_reset)
        replayed = OUTPUT_FABRIC_ADDR in (
            self._watch.ar_hs[ar_reset:] + self._watch.aw_hs[aw_reset:]
        )
        await jtag_task
        self._waits.append(
            f"pending_jtag_group bound={AXI_TIMEOUT_NS} ns per member allow_timeout=True "
            f"(interrupted by the reset, not specified, measured) [{self._fates(jtag_members)}]"
        )
        post_word = 0x6B6B_0000_0000_0001
        await self._wr("jtag", OUTPUT_FABRIC_ADDR, post_word)
        got = await self._rd("jtag", "JTAG_POST_RESET", OUTPUT_FABRIC_ADDR, expected=post_word)
        size = await self._rd(
            "sep", "REGION_SIZE_POST_OUTBOUND", _REGION_SIZE, _RESET["REGION_SIZE"]
        )
        self._mark_step("S6")
        self._log_chk(
            "CHK-RESET-MID-OUTBOUND",
            f"after a cold reset with the output_axi response held, the jtag write and read at "
            f"0x{OUTPUT_FABRIC_ADDR:x} answered OKAY and read back 0x{got:x}, REGION_SIZE read "
            f"0x{size:08x} from sep_axi_in; the B and R handshake counters never "
            f"exceeded the AW/AR handshakes issued since the reset over {QUIET_WINDOW_CYCLES} "
            f"cycles after the hold cleared (pre-reset address re-issued at output_axi: "
            f"{replayed}, observed); pre-reset accesses "
            f"(observe-only, not specified, measured) [{self._fates(jtag_members)}]",
        )

        # S7: a reprogrammed window does not survive the reset.
        await self._program("GLOBAL_BASE_PROG", _GLOBAL_BASE, _GLOBAL_BASE_PROGRAMMED)
        await self._program("REGION_SIZE_PROG", _REGION_SIZE, _REGION_SIZE_PROGRAMMED)
        await self._recover("RESTORES")
        base = await self._rd("sep", "GLOBAL_BASE_FINAL", _GLOBAL_BASE, _RESET["GLOBAL_BASE"])
        size = await self._rd("sep", "REGION_SIZE_FINAL", _REGION_SIZE, _RESET["REGION_SIZE"])
        await self._rd("sep", "LOCAL_BASE_FINAL", _LOCAL_BASE, _RESET["LOCAL_BASE"])
        for label, addr, reg in (
            ("INBOUND0_START", INBOUND0_START, "START_ADDR"),
            ("INBOUND0_END", INBOUND0_END, "END_ADDR"),
            ("INBOUND0_CONFIG", INBOUND0_FILTER_CONFIG, "FILTER_CONFIG"),
        ):
            await self._rd("sep", f"{label}_FINAL", addr, _FILTER_RESET[reg])
        for n in range(4):
            await self._rd("sep", f"SCRATCH_COLD{n}_FINAL", _scratch(n), _SCRATCH_RESET, length=4)
        self._mark_step("S7")
        self._log_chk(
            "CHK-RESET-RESTORES-WINDOW",
            f"after GLOBAL_BASE=0x{_GLOBAL_BASE_PROGRAMMED:x} and "
            f"REGION_SIZE=0x{_REGION_SIZE_PROGRAMMED:x} (both read back) and a cold reset, "
            f"GLOBAL_BASE read 0x{base:08x} and REGION_SIZE 0x{size:08x}; LOCAL_BASE, inbound "
            f"entry 0 and SCRATCH_COLD[0..3] read their reset words",
        )
        self.finished = True
        self._nonvac_fence()

    def _sig_bit(self, name: str, bit: int) -> int:
        return (self._sig(name) >> bit) & 1

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
        self._waits.append(
            f"axi_access bound={AXI_TIMEOUT_NS} ns allow_timeout=False (outstanding groups: True) "
            f"SEP_IN accesses {self.accesses}, SYS_IN {self.port_accesses['sys']}, "
            f"JTAG {self.port_accesses['jtag']}"
        )
        self._waits.extend(self._timeout_paths)
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: %d bounded waits: %s",
            len(self._waits),
            " | ".join(self._waits),
        )
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; stamps %s; SEP_IN accesses %d "
            "(floor %d), SYS_IN accesses %d, JTAG accesses %d, output_axi samples %d",
            "<".join(f"{t}@{s}" for t, s in zip(_TERMS, _STEPS)),
            ",".join(chk_ids),
            ",".join(f"{s}={t}" for s, t in self._stamps),
            self.accesses,
            MIN_SEP_IN_ACCESSES,
            self.port_accesses["sys"],
            self.port_accesses["jtag"],
            self._watch.samples,
        )
