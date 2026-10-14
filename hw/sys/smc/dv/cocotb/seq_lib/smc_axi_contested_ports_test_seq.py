# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Contested inbound traffic: same-cycle multi-port, pending plus new, overlap, reset.

Spec sources: fabric.adoc Topology, memmap.adoc Memory Map, scratch.rdl SCRATCH, port_table.adoc.

SEP_IN, SYS_IN and JTAG reads of SCRATCH_COLD(0) are released from one clk_smc_i edge; the
cycle bound is the 50 us driver guard (no bound is stated). The outcome of an access
interrupted by a cool reset is printed and never graded (the outcome is not specified). The
global-window response is printed, and its data is compared only when the response is OKAY.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import (
    ClockCycles,
    FallingEdge,
    ReadOnly,
    RisingEdge,
    SimTimeoutError,
    with_timeout,
)
from cocotb.utils import get_sim_time
from env.smc_reset_item import SmcResetItem, SmcResetOp
from env.smc_sys_axi_agent import SmcSysAxiGroupItem, SmcSysAxiItem, SmcSysAxiOp
from ocah_axi_vip import AxiTimingProfile

from ._one_shot import _OneShot
from .smc_addr_map import smc_addr, smc_indexed_addr
from .smc_base_test_seq import wait_fuse_sense_done
from .smc_csr_field_catalog import catalog_entry
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_output_fabric_vip_utils import PASS_ALL_CONFIG
from .smc_reset_seq_base import SmcResetSeqBase

FUSE_SENSE_BOUND = 200_000
AXI_TIMEOUT_NS = 50_000
JOIN_BOUND_NS = 100_000
HANDSHAKE_BOUND_CYCLES = 200
ASSERT_BOUND_REF = 400
RELEASE_BOUND_REF = 4000
LAUNCH_REF_CYCLES = 28
SYS_SEP_ROUNDS = 16
THREE_PORT_ROUNDS = 16
GLOBAL_ROUNDS = 4
PENDING_R_READY_DELAY = 32
RESET_W_DELAY = 16
RESET_R_READY_DELAY = 64
LOCAL_BASE = 0xC000_0000
GLOBAL_BASE = 0x4000_0000
PASS_ALL_END = 0x00FF_FFFF_FFFF_FFFF
WORD0 = 0xC0DE_0A00
WORD1 = 0xC0DE_0A01
RESET_CFG, RESET_START, RESET_END = 0x3000, 0x0, 0x7
EXPECTED_ACCESSES = 132
PORTS = ("SEP", "SYS", "JTAG")
PREFIX = {"SEP": "s_axi", "SYS": "sys_axi", "JTAG": "jtag_axi"}
RESP_NAMES = {0: "OKAY", 1: "EXOKAY", 2: "SLVERR", 3: "DECERR"}

SCRATCH_0 = smc_indexed_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_SCRATCH_BASE_ADDR", 0)
SCRATCH_1 = smc_indexed_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_SCRATCH_BASE_ADDR", 1)
VERSION_LO = smc_addr("SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_VERSION_LO_BASE_ADDR")
GLOBAL_SCRATCH_0 = SCRATCH_0 - LOCAL_BASE + GLOBAL_BASE
assert GLOBAL_SCRATCH_0 == 0x4000_2800, f"global SCRATCH_COLD(0) is 0x{GLOBAL_SCRATCH_0:x}"


def _filt(reg: str) -> int:
    return smc_indexed_addr(f"SMC_TOP_SMC_INBOUND_FILTER_CTRL_{reg}_BASE_ADDR", 0)


FILTER_START, FILTER_END, FILTER_CONFIG = (
    _filt("START_ADDR"),
    _filt("END_ADDR"),
    _filt("FILTER_CONFIG"),
)

STEPS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7")
CHECKERS = (
    ("CHK-CONT-SYS-SEP", "S2"),
    ("CHK-CONT-THREE-PORTS", "S3"),
    ("CHK-CONT-PENDING-NEW", "S4"),
    ("CHK-CONT-LOCAL-GLOBAL", "S5"),
    ("CHK-CONT-RESET-MID", "S6"),
)


def _value(sig, label: str) -> int:
    assert sig.value.is_resolvable, f"{label} is X/Z ({sig.value})"
    return int(sig.value)


class _ArWatch:
    """Samples ARVALID of each port per clk_smc_i edge and the SYS_IN filter probes."""

    def __init__(self, ports: tuple[str, ...]) -> None:
        self.ports = ports
        self.stop = False
        self.samples = 0
        self.first_ar: dict[str, int] = {}
        self.read_hit = 0
        self.isolate_read = 0

    async def run(self) -> None:
        dut = cocotb.top
        while not self.stop:
            await RisingEdge(dut.clk_smc_i)
            await ReadOnly()
            for port in self.ports:
                name = f"{PREFIX[port]}_arvalid"
                if _value(getattr(dut, name), name) and port not in self.first_ar:
                    self.first_ar[port] = self.samples
            self.read_hit |= _value(dut.tb_inb_read_hit, "tb_inb_read_hit")
            self.isolate_read |= _value(dut.tb_inb_isolate_read, "tb_inb_isolate_read")
            self.samples += 1

    def skew(self) -> int:
        assert set(self.first_ar) == set(self.ports), (
            f"ARVALID seen on {sorted(self.first_ar)} of {self.ports} in {self.samples} samples"
        )
        return max(self.first_ar.values()) - min(self.first_ar.values())


class _PendingWatch:
    """Counts SEP_IN requests presented while the first read response is still pending."""

    def __init__(self) -> None:
        self.stop = False
        self.pending_cycles = 0
        self.presented_while_pending = 0
        self.r_stall = 0
        self._pending = False
        self._done = False

    async def run(self) -> None:
        dut = cocotb.top
        while not self.stop:
            await RisingEdge(dut.clk_smc_i)
            await ReadOnly()
            sig = {
                n: _value(getattr(dut, f"s_axi_{n}"), f"s_axi_{n}")
                for n in ("arvalid", "arready", "awvalid", "wvalid", "rvalid", "rready")
            }
            if not self._done and sig["arvalid"] and sig["arready"]:
                self._pending = True
            if self._pending and not self._done:
                self.pending_cycles += 1
                if sig["rvalid"] and not sig["rready"]:
                    self.r_stall += 1
                if sig["arvalid"] or sig["awvalid"] or sig["wvalid"]:
                    self.presented_while_pending += 1
                if sig["rvalid"] and sig["rready"]:
                    self._done = True


class smc_axi_contested_ports_test_seq(SmcResetSeqBase, SmcCsrSeq):
    """Same-cycle reads on the inbound ports, a pending read plus new requests, a cool reset."""

    ASSERT_BOUND_REF_CYCLES = ASSERT_BOUND_REF
    RELEASE_BOUND_REF_CYCLES = RELEASE_BOUND_REF

    def __init__(self, name: str = "smc_axi_contested_ports_test_seq") -> None:
        super().__init__(name)
        self.dispatch_reset = None
        self._stamps: list[tuple[str, int]] = []
        self._chk_marks: list[tuple[str, int]] = []
        self._step = "S1"
        self._axi_count: dict[str, int] = {}
        self._axi_last: dict[str, str] = {}
        self.last_access = "none"

    async def _dispatch_reset_item(self, item: SmcResetItem) -> None:
        await self.dispatch_reset(item)

    def _mark_step(self, step_id: str) -> None:
        self._stamps.append((step_id, int(get_sim_time("ps"))))

    def _log_chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self._chk_marks.append((chk_id, int(get_sim_time("ps"))))

    def _sequencer(self, port: str):
        agent = {
            "SEP": self.env.sys_axi_agent,
            "SYS": self.env.sys_in_axi_agent,
            "JTAG": self.env.jtag_axi_agent,
        }[port]
        return agent.sequencer

    @staticmethod
    def _item(port: str, op: SmcSysAxiOp, label: str, addr: int, data: int = 0, expected=None):
        item = SmcSysAxiItem(f"{port.lower()}_{label}")
        item.op = op
        item.addr = addr
        item.length = 4
        item.wdata = data
        item.expected = expected
        return item

    def _start(self, port: str, item: SmcSysAxiItem, label: str):
        return cocotb.start_soon(
            _OneShot(item, f"{port.lower()}_{label}_os").start(self._sequencer(port))
        )

    async def _join(self, port: str, task, item: SmcSysAxiItem, label: str) -> None:
        try:
            await with_timeout(task, JOIN_BOUND_NS, "ns")
        except SimTimeoutError as exc:
            raise AssertionError(
                f"{self._step} {port} {label}: access not finished within {JOIN_BOUND_NS} ns "
                f"(last access {self.last_access})"
            ) from exc
        self.accesses += 1
        self._axi_count[self._step] = self._axi_count.get(self._step, 0) + 1
        code = RESP_NAMES.get(item.resp_code, item.resp_code)
        self.last_access = (
            f"{port} {label} @0x{item.addr:08x} resp={code} rdata=0x{item.rdata & 0xFFFFFFFF:x}"
            f" timed_out={item.timed_out}"
        )
        self._axi_last[self._step] = self.last_access

    async def _access(self, port: str, item: SmcSysAxiItem, label: str) -> SmcSysAxiItem:
        await FallingEdge(cocotb.top.clk_smc_i)
        await self._join(port, self._start(port, item, label), item, label)
        return item

    async def _okay(self, port, op, label, addr, data=0, expected=None) -> SmcSysAxiItem:
        item = await self._access(port, self._item(port, op, label, addr, data, expected), label)
        assert item.resp_code == 0, f"{self.last_access}: not OKAY"
        if op is SmcSysAxiOp.READ and expected is not None:
            got = item.rdata & 0xFFFF_FFFF
            assert got == expected, f"{self.last_access}: read 0x{got:x}, want 0x{expected:x}"
        return item

    async def _csr8(self, label: str, addr: int, data: int) -> None:
        item = self._item("SEP", SmcSysAxiOp.WRITE, label, addr, data)
        item.length = 8
        await self._access("SEP", item, label)
        assert item.resp_code == 0, f"{self.last_access}: not OKAY"

    async def _program_filter(self, tag: str, cfg: int, start: int, end: int) -> None:
        if cfg == PASS_ALL_CONFIG:
            order = (
                ("START", FILTER_START, start),
                ("END", FILTER_END, end),
                ("CONFIG", FILTER_CONFIG, cfg),
            )
        else:
            order = (
                ("CONFIG", FILTER_CONFIG, cfg),
                ("START", FILTER_START, start),
                ("END", FILTER_END, end),
            )
        for reg, addr, data in order:
            await self._csr8(f"{tag}_{reg}", addr, data)

    async def _fuse_sense(self, label: str) -> None:
        await wait_fuse_sense_done(FUSE_SENSE_BOUND)
        for sub in ("tb_fuse_sense_done", "tb_fuse_reset_n", "tb_rst_warm_smc_clk_n"):
            self._timeout_paths.append(f"{label}.{sub}: bound={FUSE_SENSE_BOUND}smc_cycles last=1")

    async def _contest(self, ports: tuple[str, ...], label: str, addr: int, want: int):
        """Release one read per port from a single clk_smc_i edge; return items and skew."""
        clk = cocotb.top.clk_smc_i
        await FallingEdge(clk)
        watch = _ArWatch(ports)
        watcher = cocotb.start_soon(watch.run())
        items = {p: self._item(p, SmcSysAxiOp.READ, label, addr, expected=want) for p in ports}
        await RisingEdge(clk)
        tasks = {p: self._start(p, items[p], label) for p in ports}
        for port in ports:
            await self._join(port, tasks[port], items[port], label)
        watch.stop = True
        await watcher
        await FallingEdge(clk)
        return items, watch

    async def _contested_rounds(self, ports, rounds, tag) -> tuple[int, int, int, int]:
        skews, hits, isolates = [], 0, 0
        for n in range(rounds):
            items, watch = await self._contest(ports, f"{tag}_r{n}", SCRATCH_0, WORD0)
            for port, item in items.items():
                got = item.rdata & 0xFFFF_FFFF
                assert item.resp_code == 0 and got == WORD0, (
                    f"{tag} round {n} {port}: resp={RESP_NAMES.get(item.resp_code)} "
                    f"rdata=0x{got:x}, want OKAY 0x{WORD0:x}"
                )
            skews.append(watch.skew())
            hits |= watch.read_hit
            isolates |= watch.isolate_read
        assert max(skews) == 0, f"{tag}: ports released from one edge showed ARVALID skew {skews}"
        return rounds, max(skews), hits, isolates

    async def _s4_pending(self) -> str:
        group_items = [
            self._item("SEP", SmcSysAxiOp.READ, "pend_rd0", SCRATCH_0, expected=WORD0),
            self._item("SEP", SmcSysAxiOp.READ, "pend_rd1", SCRATCH_1, expected=WORD1),
            self._item("SEP", SmcSysAxiOp.WRITE, "pend_wr1", SCRATCH_1, WORD1),
        ]
        group = SmcSysAxiGroupItem(
            "pending_new", group_items, timing=AxiTimingProfile(r_ready_delay=PENDING_R_READY_DELAY)
        )
        clk = cocotb.top.clk_smc_i
        await FallingEdge(clk)
        watch = _PendingWatch()
        watcher = cocotb.start_soon(watch.run())
        await RisingEdge(clk)
        task = cocotb.start_soon(_OneShot(group, "pending_new_os").start(self._sequencer("SEP")))
        try:
            await with_timeout(task, JOIN_BOUND_NS, "ns")
        except SimTimeoutError as exc:
            raise AssertionError(
                f"S4 pending group not finished within {JOIN_BOUND_NS} ns (last {self.last_access})"
            ) from exc
        self.accesses += len(group_items)
        self._axi_count["S4"] = len(group_items)
        watch.stop = True
        await watcher
        await FallingEdge(clk)
        rd0, rd1, wr1 = group_items
        self._axi_last["S4"] = (
            f"rd0 resp={rd0.resp_code} rd1 resp={rd1.resp_code} wr1 resp={wr1.resp_code}"
        )
        assert rd0.resp_code == 0 and rd0.rdata & 0xFFFF_FFFF == WORD0, self._axi_last["S4"]
        assert rd1.resp_code == 0 and rd1.rdata & 0xFFFF_FFFF == WORD1, self._axi_last["S4"]
        assert wr1.resp_code == 0, f"held-read write not OKAY: {self._axi_last['S4']}"
        assert watch.r_stall > 0 and watch.presented_while_pending > 0, (
            f"first read not pending while new requests arrived: stall {watch.r_stall}, "
            f"presented {watch.presented_while_pending}, pending {watch.pending_cycles}"
        )
        return (
            f"the held read (r_ready_delay={PENDING_R_READY_DELAY}) returned "
            f"0x{rd0.rdata & 0xFFFFFFFF:08X}, the read of SCRATCH_COLD(1) behind it returned "
            f"0x{rd1.rdata & 0xFFFFFFFF:08X} and the write answered {RESP_NAMES[wr1.resp_code]}; "
            f"R stalled {watch.r_stall} cycles and {watch.presented_while_pending} request "
            f"samples were presented in {watch.pending_cycles} pending cycles, all within "
            f"{AXI_TIMEOUT_NS} ns"
        )

    async def _s5_local_global(self) -> str:
        self.env.axi_monitor.expected_decerr_addrs.add(GLOBAL_SCRATCH_0)
        clk = cocotb.top.clk_smc_i
        glob = []
        for n in range(GLOBAL_ROUNDS):
            await FallingEdge(clk)
            watch = _ArWatch(("SEP", "SYS"))
            watcher = cocotb.start_soon(watch.run())
            local = self._item("SEP", SmcSysAxiOp.READ, f"lg_local{n}", SCRATCH_0, expected=WORD0)
            remote = self._item("SYS", SmcSysAxiOp.READ, f"lg_global{n}", GLOBAL_SCRATCH_0)
            remote.allow_error = True
            await RisingEdge(clk)
            tasks = {
                "SEP": self._start("SEP", local, f"lg_local{n}"),
                "SYS": self._start("SYS", remote, f"lg_global{n}"),
            }
            await self._join("SEP", tasks["SEP"], local, f"lg_local{n}")
            await self._join("SYS", tasks["SYS"], remote, f"lg_global{n}")
            watch.stop = True
            await watcher
            await FallingEdge(clk)
            assert local.resp_code == 0 and local.rdata & 0xFFFF_FFFF == WORD0, (
                f"round {n} local read resp={RESP_NAMES.get(local.resp_code)} "
                f"rdata=0x{local.rdata & 0xFFFFFFFF:x}"
            )
            assert not remote.timed_out and remote.resp_code is not None, (
                f"round {n} global read did not complete"
            )
            if remote.resp_code == 0:
                assert remote.rdata & 0xFFFF_FFFF == WORD0, (
                    f"round {n} OKAY global read returned 0x{remote.rdata & 0xFFFFFFFF:x}"
                )
            glob.append(f"{RESP_NAMES.get(remote.resp_code)}:0x{remote.rdata & 0xFFFFFFFF:X}")
            assert watch.skew() == 0, f"round {n}: ARVALID skew {watch.first_ar}"
        return (
            f"in all {GLOBAL_ROUNDS} rounds both reads completed within {AXI_TIMEOUT_NS} ns; "
            f"the local read at 0x{SCRATCH_0:08X} returned 0x{WORD0:08X} OKAY; global read at "
            f"0x{GLOBAL_SCRATCH_0:08X} responses (printed, observe-only) {' '.join(glob)}"
        )

    async def _poll_request(self, port: str, channel: str, label: str) -> int:
        dut = cocotb.top
        name = f"{PREFIX[port]}_{channel}"
        for n in range(1, HANDSHAKE_BOUND_CYCLES + 1):
            await RisingEdge(dut.clk_smc_i)
            await ReadOnly()
            if _value(getattr(dut, name), name):
                self._timeout_paths.append(
                    f"{label}.{name}: bound={HANDSHAKE_BOUND_CYCLES}smc_cycles seen at {n}"
                )
                return n
        raise AssertionError(
            f"{label}: {name} never high within {HANDSHAKE_BOUND_CYCLES} clk_smc_i samples"
        )

    async def _pending_until_reset(self, task, label: str) -> bool:
        """Return whether the access was still pending at the last sample before the reset."""
        dut = cocotb.top
        sig = dut.rst_primary_smc_clk_no
        pending = False
        for n in range(1, ASSERT_BOUND_REF + 1):
            await RisingEdge(dut.clk_ref_i)
            await ReadOnly()
            if not _value(sig, "rst_primary_smc_clk_no"):
                self._timeout_paths.append(
                    f"{label}.port_reset_seen: bound={ASSERT_BOUND_REF}ref_cycles seen at {n}"
                )
                return pending
            pending = not task.done()
        raise AssertionError(
            f"{label}: rst_primary_smc_clk_no never fell within {ASSERT_BOUND_REF} clk_ref_i "
            f"samples (last pending={pending})"
        )

    async def _reset_leg(self, port: str, direction: str, version: int) -> str:
        label = f"S6.{port}.{direction}"
        clk = cocotb.top.clk_smc_i
        if direction == "write":
            item = self._item(port, SmcSysAxiOp.WRITE, "rst_wr", SCRATCH_1, WORD1)
            item.timing = AxiTimingProfile(w_delay=RESET_W_DELAY)
            channel = "awvalid"
        else:
            item = self._item(port, SmcSysAxiOp.READ, "rst_rd", SCRATCH_0)
            item.timing = AxiTimingProfile(r_ready_delay=RESET_R_READY_DELAY)
            channel = "arvalid"
        item.allow_error = True
        item.allow_timeout = True
        await FallingEdge(clk)
        await self._send(SmcResetOp.COOL_RST_LO, item_name=f"{label}.cool_lo")
        await ClockCycles(cocotb.top.clk_ref_i, LAUNCH_REF_CYCLES)
        self._timeout_paths.append(
            f"{label}.launch_align: bound={LAUNCH_REF_CYCLES}ref_cycles after cool_rst_lo"
        )
        await FallingEdge(clk)
        task = self._start(port, item, f"rst_{direction}")
        seen = await self._poll_request(port, channel, label)
        await FallingEdge(clk)
        pending_launch = not task.done()
        pending_before_effect = await self._pending_until_reset(task, label)
        await FallingEdge(clk)
        await self._wait_state(
            f"{label}.COOL_ASSERT", bound=ASSERT_BOUND_REF, expect_rst_primary_smc_clk_n=0
        )
        assert pending_launch and pending_before_effect, (
            f"{label}: access not in flight when the reset took effect "
            f"(pending after request {pending_launch}, at the last sample before "
            f"rst_primary_smc_clk_no=0 {pending_before_effect}); last access {self.last_access}"
        )
        await self._send(SmcResetOp.COOL_RST_HI, item_name=f"{label}.cool_hi")
        await self._wait_released(f"{label}.COOL_RELEASE", bound=RELEASE_BOUND_REF)
        await self._fuse_sense(label)
        await self._program_filter(f"{label}_REPROG", PASS_ALL_CONFIG, 0, PASS_ALL_END)
        await self._join(port, task, item, f"rst_{direction}")
        if item.timed_out:
            outcome = f"abandoned (no response within {AXI_TIMEOUT_NS} ns)"
        elif item.resp_code is None:
            outcome = "abandoned (flushed by the manager VIP at reset)"
        elif item.resp_code in (0, 1):
            outcome = f"completed {RESP_NAMES[item.resp_code]}"
        else:
            outcome = f"error {RESP_NAMES.get(item.resp_code)}"
        post = await self._okay(
            port, SmcSysAxiOp.READ, f"{label}_VERSION", VERSION_LO, expected=version
        )
        return (
            f"{port} {direction}: request seen at sample {seen}, pending after request "
            f"{pending_launch}, pending at the last sample before the port reset "
            f"{pending_before_effect}, "
            f"interrupted access {outcome}; VERSION_LO after release "
            f"0x{post.rdata & 0xFFFFFFFF:X} OKAY"
        )

    async def body(self) -> None:
        await self._fuse_sense("S1")
        await self._program_filter("PASS_ALL", PASS_ALL_CONFIG, 0, PASS_ALL_END)
        await self._okay("SEP", SmcSysAxiOp.WRITE, "S1_SCRATCH0", SCRATCH_0, WORD0)
        await self._okay("SEP", SmcSysAxiOp.WRITE, "S1_SCRATCH1", SCRATCH_1, WORD1)
        version = catalog_entry("CHIP_CONFIG_VERSION_LO", VERSION_LO, writable=False).expected
        await self._okay("SEP", SmcSysAxiOp.READ, "S1_VERSION", VERSION_LO, expected=version)
        self._mark_step("S1")

        self._step = "S2"
        rounds, skew, hit, iso = await self._contested_rounds(("SEP", "SYS"), SYS_SEP_ROUNDS, "S2")
        self._mark_step("S2")
        self._log_chk(
            "CHK-CONT-SYS-SEP",
            f"in all {rounds} rounds both reads completed OKAY within the {AXI_TIMEOUT_NS} ns "
            f"guard and each returned 0x{WORD0:08X}; ARVALID skew {skew} cycles; "
            f"tb_inb_read_hit seen 0x{hit:x}, tb_inb_isolate_read seen {iso}",
        )

        self._step = "S3"
        rounds, skew, hit, iso = await self._contested_rounds(PORTS, THREE_PORT_ROUNDS, "S3")
        self._mark_step("S3")
        self._log_chk(
            "CHK-CONT-THREE-PORTS",
            f"in all {rounds} rounds the three reads completed OKAY within the "
            f"{AXI_TIMEOUT_NS} ns guard and each returned 0x{WORD0:08X}; ARVALID skew {skew} "
            f"cycles",
        )

        self._step = "S4"
        text = await self._s4_pending()
        self._mark_step("S4")
        self._log_chk("CHK-CONT-PENDING-NEW", text)

        self._step = "S5"
        text = await self._s5_local_global()
        self._mark_step("S5")
        self._log_chk("CHK-CONT-LOCAL-GLOBAL", text)

        self._step = "S6"
        legs = [
            await self._reset_leg(port, direction, version)
            for port in PORTS
            for direction in ("write", "read")
        ]
        self._mark_step("S6")
        self._log_chk(
            "CHK-CONT-RESET-MID",
            f"on each of the {len(legs)} legs the read of VERSION_LO after reset release "
            f"completed OKAY within the guard and returned V=0x{version:X}; "
            f"interrupted-access outcomes are printed and not graded (owner value pending): "
            f"{' | '.join(legs)}",
        )

        self._step = "S7"
        await self._okay("SEP", SmcSysAxiOp.WRITE, "S7_SCRATCH0", SCRATCH_0, 0)
        await self._okay("SEP", SmcSysAxiOp.WRITE, "S7_SCRATCH1", SCRATCH_1, 0)
        await self._program_filter("RESTORE", RESET_CFG, RESET_START, RESET_END)
        self._mark_step("S7")

        assert self.accesses == EXPECTED_ACCESSES, (
            f"issued {self.accesses} accesses, expected {EXPECTED_ACCESSES}"
        )
        self._timeout_paths.append(
            f"watcher_stop: bound=1clk_smc_i_edge per round ({SYS_SEP_ROUNDS + THREE_PORT_ROUNDS}"
            f"+{GLOBAL_ROUNDS}+1 rounds)"
        )
        for step in STEPS:
            if step in self._axi_count:
                self._timeout_paths.append(
                    f"{step}.axi_access: driver bound={AXI_TIMEOUT_NS}ns join "
                    f"bound={JOIN_BOUND_NS}ns n={self._axi_count[step]} "
                    f"last={self._axi_last[step]}"
                )
        self._log_chk(
            "CHK-TIMEOUT-PATHS",
            f"{len(self._timeout_paths)} bounded waits: {'; '.join(self._timeout_paths)}; "
            "every expiry raises AssertionError with the last state",
        )
        self._nonvac_fence()

    def _nonvac_fence(self) -> None:
        ids = tuple(s for s, _ in self._stamps)
        assert ids == STEPS, f"step ids {ids}, want {STEPS}"
        times = [t for _, t in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"step stamps not increasing: {times}"
        marks = [(c, t) for c, t in self._chk_marks if c != "CHK-TIMEOUT-PATHS"]
        assert tuple(c for c, _ in marks) == tuple(c for c, _ in CHECKERS), (
            f"checker lines {[c for c, _ in marks]}"
        )
        stamp_of = dict(self._stamps)
        for (chk_id, when), (_, step) in zip(marks, CHECKERS):
            assert when >= stamp_of[step], f"{chk_id} printed before its step {step} stamp"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; stamps %s",
            "<".join(STEPS),
            ",".join(c for c, _ in self._chk_marks),
            ",".join(f"{s}={t}" for s, t in self._stamps),
        )
