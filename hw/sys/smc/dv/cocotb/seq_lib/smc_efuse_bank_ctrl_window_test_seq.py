# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SHIM control window forwarding and efuse_bank_ctrl per-channel handshake counts.

Sources: smu-smc.adoc (eFuse Interface), efuse_shim_ctrl.rdl, efuse_interface_ctrl.rdl.

A sampler counts the 0 to 1 transitions of the five bank-control channel valids on every
clk_smc_i rising edge; every window access is bracketed by two counter snapshots.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import (
    ClockCycles,
    NextTimeStep,
    ReadOnly,
    RisingEdge,
    SimTimeoutError,
    with_timeout,
)
from cocotb.utils import get_sim_time
from env.smc_reset_item import SmcResetOp
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import _REPO, _field_mask, smc_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_efuse_vip_utils import EFUSE_BANK_INIT_TIME_RESET, EFUSE_SHIM_CTRL_WINDOW
from .smc_reset_seq_base import SmcResetSeqBase

_STATUS = smc_addr("SMC_TOP_EFUSE_INTERFACE_CTRL_EFUSE_INTERFACE_CTRL_STATUS_BASE_ADDR")
_READ_REQ_TIMEOUT = smc_addr("SMC_TOP_EFUSE_INTERFACE_CTRL_EFUSE_READ_REQ_TIMEOUT_BASE_ADDR")
_LOCKS = smc_addr("SMC_TOP_SMC_EFUSE_MAP_LOCKS_BASE_ADDR")
_READ_REQ_TIMEOUT_RESET = _field_mask(
    _REPO / "hw" / "ip" / "efuse" / "regs" / "gen" / "c" / "efuse_interface_ctrl.h",
    "EFUSE_INTERFACE_CTRL__EFUSE_READ_REQ_TIMEOUT__READ_REQ_TIMEOUT_CYCLES_reset",
)
_STEPS = ("S1", "S2", "S3", "S4", "S5", "S6")
_CHANNELS = ("aw", "w", "ar", "b", "r")
_OKAY = 0
_FULL_STROBE = 0xF
_WRITE_VALUES = (0x15, 0x3A)
_RESENSE_VALUE = 0x40
_IDLE_SAMPLE_CYCLES = 16
_SENSE_BOUND_CYCLES = 200_000
_FIRST_CMD_BOUND_CYCLES = 2_000
_DRIVER_MARGIN_NS = 10_000
_SIGNALS = (
    "tb_efuse_bank_awvalid",
    "tb_efuse_bank_wvalid",
    "tb_efuse_bank_arvalid",
    "tb_efuse_bank_bvalid",
    "tb_efuse_bank_rvalid",
    "tb_efuse_shim_cmd_valid",
    "rst_primary_smc_clk_no",
)


class smc_efuse_bank_ctrl_window_test_seq(SmcResetSeqBase, SmcCsrSeq):
    """Window read and write accesses with exact per-channel handshake counts."""

    def __init__(self, name: str = "smc_efuse_bank_ctrl_window_test_seq") -> None:
        super().__init__(name)
        self.dispatch_reset = None
        self.access_floor = 0
        self._events: list[tuple[str, str]] = []
        self._stamps: list[tuple[str, int]] = []
        self._totals: dict[str, int] = {}
        self._waits: list[tuple[str, int, str]] = []
        self._counts = dict.fromkeys(_CHANNELS, 0)
        self._busy_cycles = 0
        self._last_window = "no window access completed"
        self._cycle = 0
        self._releases: list[list[int | None]] = []

    async def _dispatch_reset_item(self, item) -> None:
        await self.dispatch_reset(item)

    # --- fence ----------------------------------------------------------
    def _done(self, step: str) -> None:
        self._stamps.append((step, int(get_sim_time("ps"))))
        self._events.append(("step", step))
        self._totals[step] = sum(self._counts.values())

    def _chk(self, chk_id: str, fmt: str, *args) -> None:
        self._events.append(("chk", chk_id))
        cocotb.log.info("%s: " + fmt, chk_id, *args)

    # --- probes ---------------------------------------------------------
    @staticmethod
    def _sig(name: str) -> int:
        dut = cocotb.top
        assert hasattr(dut, name), f"{name} is not a signal of the testbench top"
        value = getattr(dut, name).value
        assert value.is_resolvable, f"{name} is X/Z: {value}"
        return int(value)

    def _channel_state(self) -> str:
        return ",".join(f"{ch}valid={self._sig(f'tb_efuse_bank_{ch}valid')}" for ch in _CHANNELS)

    async def _sampler(self) -> None:
        clk = cocotb.top.clk_smc_i
        prev = [self._sig(name) for name in _SIGNALS]
        while True:
            await RisingEdge(clk)
            self._cycle += 1
            now = [self._sig(name) for name in _SIGNALS]
            for k, ch in enumerate(_CHANNELS):
                if now[k] and not prev[k]:
                    self._counts[ch] += 1
            if any(now[:5]):
                self._busy_cycles += 1
            if now[6] and not prev[6]:
                self._releases.append([self._cycle, None])
            if now[5] and self._releases and self._releases[-1][1] is None:
                self._releases[-1][1] = self._cycle
            prev = now

    async def _snap(self) -> dict[str, int]:
        await ReadOnly()
        snap = dict(self._counts)
        snap["busy"] = self._busy_cycles
        await NextTimeStep()
        return snap

    @staticmethod
    def _delta(before: dict[str, int], after: dict[str, int]) -> dict[str, int]:
        return {key: after[key] - before[key] for key in after}

    # --- waits ----------------------------------------------------------
    async def _sense_wait(self, label: str) -> None:
        try:
            await self.wait_fuse_sense_done(_SENSE_BOUND_CYCLES)
        except AssertionError as exc:
            raise AssertionError(f"{label}: {exc}; {self._channel_state()}") from exc
        state = (
            f"tb_fuse_sense_done={self._sig('tb_fuse_sense_done')},"
            f"tb_fuse_reset_n={self._sig('tb_fuse_reset_n')},"
            f"tb_rst_warm_smc_clk_n={self._sig('tb_rst_warm_smc_clk_n')}"
        )
        self._waits.append((label, _SENSE_BOUND_CYCLES, state))

    async def _cold_reset(self, label: str) -> int:
        """Cold reset through the reset agent, then the sense; returns the release index."""
        assert self._sig("tb_fuse_sense_done") == 1, f"{label}: sense not done before the reset"
        index = len(self._releases)
        await self._send(SmcResetOp.COLD_RST_LO)
        await self._wait_state(
            f"{label} cold assert",
            expect_powergood_stable=1,
            expect_rst_cold_stable_ref_clk_n=0,
            expect_rst_primary_ref_clk_n=0,
            expect_rst_primary_smc_clk_n=0,
            expect_left_stable=True,
        )
        assert self._sig("tb_fuse_sense_done") == 0, (
            f"{label}: tb_fuse_sense_done is still 1 with the cold reset asserted"
        )
        await self._send(SmcResetOp.COLD_RST_HI)
        await self._wait_released(f"{label} cold release")
        await self._sense_wait(f"{label}_sense")
        for _ in range(_FIRST_CMD_BOUND_CYCLES):
            if len(self._releases) > index and self._releases[index][1] is not None:
                break
            await RisingEdge(cocotb.top.clk_smc_i)
        else:
            raise AssertionError(
                f"{label}: no tb_efuse_shim_cmd_valid after the reset release within "
                f"{_FIRST_CMD_BOUND_CYCLES} smc clocks; releases={self._releases}"
            )
        release, first = self._releases[index]
        self._waits.append(
            (
                f"{label}_first_cmd",
                _FIRST_CMD_BOUND_CYCLES,
                f"release_cycle={release},first_cmd_cycle={first}",
            )
        )
        return index

    # --- accesses -------------------------------------------------------
    async def _access(
        self, label: str, addr: int, *, write: int | None = None, expect: int | None = None
    ) -> tuple[int, int, dict[str, int]]:
        """One strict SEP_IN access; returns (read data, response, channel edge delta)."""
        item = SmcSysAxiItem(f"{'wr' if write is not None else 'rd'}_{label}")
        item.addr = addr
        item.length = 4
        if write is None:
            item.op = SmcSysAxiOp.READ
            item.expected = expect
        else:
            item.op = SmcSysAxiOp.WRITE
            item.wdata = write
            item.wstrb = _FULL_STROBE
        bound_ns = self.cfg.axi_timeout_ns
        item.timeout_ns = bound_ns + _DRIVER_MARGIN_NS
        before = await self._snap()
        try:
            await self.start_item(item)
            await with_timeout(self.finish_item(item), bound_ns, "ns")
        except SimTimeoutError as exc:
            raise AssertionError(
                f"{label}: window access 0x{addr:08x} {item.op.name} did not finish within "
                f"{bound_ns} ns; {self._channel_state()}"
            ) from exc
        except AssertionError as exc:
            raise AssertionError(f"{label}: {exc}; {self._channel_state()}") from exc
        self.accesses += 1
        after = await self._snap()
        assert item.resp_code == _OKAY, (
            f"{label}: response code {item.resp_code}, expected OKAY; {self._channel_state()}"
        )
        data = int(item.rdata) & 0xFFFF_FFFF if write is None else 0
        if expect is not None:
            assert data == expect, f"{label}: read 0x{data:08x}, expected 0x{expect:08x}"
        done_ps = int(get_sim_time("ps"))
        self.records.append((label, data, item.resp_code, done_ps))
        if addr == EFUSE_SHIM_CTRL_WINDOW:
            self._last_window = (
                f"{label}@0x{addr:08x} resp={item.resp_code} done={done_ps}ps "
                f"{self._channel_state()}"
            )
        return data, item.resp_code, self._delta(before, after)

    @staticmethod
    def _expect_edges(label: str, delta: dict[str, int], **expected: int) -> None:
        want = {ch: expected.get(ch, 0) for ch in _CHANNELS}
        got = {ch: delta[ch] for ch in _CHANNELS}
        assert got == want, f"{label}: channel edges {got}, expected {want}"

    async def _read_window(self, label: str, expect: int | None = None) -> int:
        data, _resp, delta = await self._access(label, EFUSE_SHIM_CTRL_WINDOW, expect=expect)
        self._expect_edges(label, delta, ar=1, r=1)
        return data

    async def _write_window(self, label: str, value: int) -> None:
        _data, _resp, delta = await self._access(label, EFUSE_SHIM_CTRL_WINDOW, write=value)
        self._expect_edges(label, delta, aw=1, w=1, b=1)

    # --- body -----------------------------------------------------------
    async def body(self) -> None:
        reset = EFUSE_BANK_INIT_TIME_RESET
        v1, v2 = _WRITE_VALUES
        assert len({reset, v1, v2, _RESENSE_VALUE}) == 4, "the write values are not distinct"
        assert _READ_REQ_TIMEOUT_RESET != 0x1000, "the timeout probe value equals its reset"
        self.records: list[tuple[str, int, int, int]] = []
        bound_ns = self.cfg.axi_timeout_ns

        # S1
        await self._sense_wait("sense1")
        sampler = cocotb.start_soon(self._sampler())
        self._done("S1")
        try:
            await self._scenario(reset, v1, v2, bound_ns)
        finally:
            sampler.cancel()

    async def _scenario(self, reset: int, v1: int, v2: int, bound_ns: int) -> None:
        floor = 0
        zero = dict.fromkeys(_CHANNELS, 0)

        # S2
        idx0 = await self._cold_reset("idle")
        for k in range(3):
            _d, _r, delta = await self._access(f"STATUS{k}", _STATUS)
            self._expect_edges(f"STATUS{k}", delta)
        probe = 0x1000
        _d, _r, delta = await self._access("RRT_WR", _READ_REQ_TIMEOUT, write=probe)
        self._expect_edges("RRT_WR", delta)
        await self._access("RRT_RB", _READ_REQ_TIMEOUT, expect=probe)
        await self._access("RRT_RESTORE", _READ_REQ_TIMEOUT, write=_READ_REQ_TIMEOUT_RESET)
        await self._access("RRT_RESTORE_RB", _READ_REQ_TIMEOUT, expect=_READ_REQ_TIMEOUT_RESET)
        _d, _r, delta = await self._access("LOCKS_RD", _LOCKS)
        self._expect_edges("LOCKS_RD", delta)
        floor += 8
        idle = await self._snap()
        assert {ch: idle[ch] for ch in _CHANNELS} == zero and idle["busy"] == 0, (
            f"idle leg moved the bank-control channels: {idle}"
        )
        base_release, base_first = self._releases[idx0]
        baseline = base_first - base_release
        self._done("S2")

        # S3
        value = await self._read_window("WINDOW_RD", expect=reset)
        single_read = (value, _OKAY)
        floor += 1
        self._done("S3")
        self._chk(
            "CHK-WINDOW-READ",
            "window read at 0x%08x returned 0x%08x with response OKAY and exactly one ar and "
            "one r edge (aw/w/b 0)",
            EFUSE_SHIM_CTRL_WINDOW,
            value,
        )

        # S4
        readbacks = {}
        for n, wv in enumerate((v1, v2)):
            await self._write_window(f"WINDOW_WR{n}", wv)
            readbacks[wv] = await self._read_window(f"WINDOW_WR{n}_RB", expect=wv)
        await self._write_window("WINDOW_RESTORE", reset)
        await self._read_window("WINDOW_RESTORE_RB", expect=reset)
        floor += 6
        moved = {ch: self._counts[ch] for ch in _CHANNELS}
        assert all(moved[ch] > 0 for ch in _CHANNELS), f"dead probe, counts {moved}"
        self._done("S4")
        self._chk(
            "CHK-WINDOW-WRITE",
            "writes of 0x%08x and 0x%08x with strobe 0x%x each gave one aw, one w and one b edge "
            "and read back equal (one ar and one r edge each); 0x%08x restored and re-read",
            v1,
            v2,
            _FULL_STROBE,
            reset,
        )
        self._chk(
            "CHK-BANKCTRL-IDLE",
            "across the cold reset, the sense, 3 STATUS reads, a READ_REQ_TIMEOUT write 0x%08x/"
            "read/restore to 0x%08x and a LOCKS read the edges aw/w/ar/b/r were 0/0/0/0/0 with "
            "%d busy cycles; positive control: the same counters later reached %s",
            probe,
            _READ_REQ_TIMEOUT_RESET,
            idle["busy"],
            "/".join(str(moved[ch]) for ch in _CHANNELS),
        )

        # S5
        self.records.clear()
        await self._read_window("SEQ_A_RD0")
        await self._read_window("SEQ_A_RD1")
        await self._write_window("SEQ_B_WR", v1)
        await self._read_window("SEQ_B_RD")
        await self._read_window("SEQ_C_RD")
        await self._write_window("SEQ_C_WR", v2)
        await self._write_window("SEQ_END_RESTORE", reset)
        await self._read_window("SEQ_END_RD")
        floor += 8
        want = [
            ("SEQ_A_RD0", single_read[0]),
            ("SEQ_A_RD1", single_read[0]),
            ("SEQ_B_WR", 0),
            ("SEQ_B_RD", readbacks[v1]),
            ("SEQ_C_RD", readbacks[v1]),
            ("SEQ_C_WR", 0),
            ("SEQ_END_RESTORE", 0),
            ("SEQ_END_RD", single_read[0]),
        ]
        got = [(label, data) for label, data, _r, _t in self.records]
        assert [d for _l, d in got] == [d for _l, d in want], f"window data {got}, expected {want}"
        assert all(resp == single_read[1] for _l, _d, resp, _t in self.records)
        for cycle in range(_IDLE_SAMPLE_CYCLES):
            assert not any(self._sig(f"tb_efuse_bank_{ch}valid") for ch in _CHANNELS), (
                f"a bank-control valid is high {cycle} cycles after the last access: "
                f"{self._channel_state()}"
            )
            await ClockCycles(cocotb.top.clk_smc_i, 1)
        self._done("S5")
        self._chk(
            "CHK-BANKCTRL-ORDER",
            "back-to-back serialized window accesses R,R then W,R then R,W returned the expected "
            "data with OKAY: %s; all five valids read 0 for %d cycles afterwards",
            ", ".join(f"{label}=0x{data:08x}" for label, data in got),
            _IDLE_SAMPLE_CYCLES,
        )

        # S6
        await self._write_window("RESENSE_WR", _RESENSE_VALUE)
        await self._read_window("RESENSE_PRE_RB", expect=_RESENSE_VALUE)
        idx1 = await self._cold_reset("resense")
        post = await self._read_window("RESENSE_POST_RD")
        floor += 3
        survived = post == _RESENSE_VALUE
        if survived:
            await self._write_window("RESENSE_RESTORE", reset)
            await self._read_window("RESENSE_RESTORE_RB", expect=reset)
            floor += 2
        release, first = self._releases[idx1]
        resense = first - release
        self._done("S6")
        self._chk(
            "CHK-INITTIME-RESENSE",
            "init time 0x%08x was read back through the window before the reset; cycles from "
            "release to the first tb_efuse_shim_cmd_valid: baseline (reset value 0x%08x) %d, "
            "with 0x%08x %d, difference %d; post-sense window read 0x%08x (%s)",
            _RESENSE_VALUE,
            reset,
            baseline,
            _RESENSE_VALUE,
            resense,
            resense - baseline,
            post,
            "register survived the reset" if survived else "register did not survive the reset",
        )
        self.access_floor = floor

        # fence
        assert [s for s, _t in self._stamps] == list(_STEPS), (
            f"steps completed {[s for s, _t in self._stamps]}, expected {list(_STEPS)}"
        )
        times = [t for _s, t in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"stamps not increasing: {times}"
        totals = [self._totals[s] for s in _STEPS[1:]]
        assert totals[0] == 0 < totals[1] < totals[2] < totals[3] < totals[4], (
            f"cumulative edge totals not strictly increasing: {totals}"
        )
        chk_step = {
            "CHK-WINDOW-READ": "S3",
            "CHK-WINDOW-WRITE": "S4",
            "CHK-BANKCTRL-IDLE": "S4",
            "CHK-BANKCTRL-ORDER": "S5",
            "CHK-INITTIME-RESENSE": "S6",
        }
        printed = [ident for kind, ident in self._events if kind == "chk"]
        assert printed == list(chk_step), f"checker lines printed {printed}"
        for index, (kind, ident) in enumerate(self._events):
            if kind == "chk":
                assert ("step", chk_step[ident]) in self._events[:index], (
                    f"{ident} printed before step {chk_step[ident]} completed"
                )
        cocotb.log.info(
            "CHK-NONVAC: ordered fence IDLE_LEG_ZERO_EDGES(%d) < WINDOW_READ_ONE_EDGE(%d) < "
            "WINDOW_WRITE_ONE_EDGE(%d) < SEQUENCES(%d) < INIT_TIME_RESENSE(%d) as cumulative "
            "bank-control edges at the end of S2..S6; checker lines %s; stamps %s ps",
            *totals,
            ", ".join(printed),
            ", ".join(f"{s}={t}" for s, t in self._stamps),
        )
        waits = list(self._waits)
        waits.append(
            (
                "window_access",
                f"{bound_ns} (driver item bound {bound_ns + _DRIVER_MARGIN_NS})",
                self._last_window,
            )
        )
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: %d bounded waits: %s",
            len(waits),
            " ".join(
                f"{name}={bound}(fails with AssertionError on expiry) last={state}"
                for name, bound, state in waits
            ),
        )
