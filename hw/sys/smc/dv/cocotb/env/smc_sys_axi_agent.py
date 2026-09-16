# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS SEP-input AXI UVM agent.

Drives real AXI traffic through the tb_top ``s_axi_*`` bridge into
``smc.sep_axi_in_req_i``. This mirrors the SEP OSS AXI agent pattern.
"""

from __future__ import annotations

from enum import Enum

import cocotb
from cocotb.handle import Immediate
from cocotb.triggers import RisingEdge, with_timeout
from ocah_axi_vip import OcahAxiMasterAgent, OcahAxiMasterSequence, clear_profile
from pyuvm import (
    ConfigDB,
    uvm_agent,
    uvm_analysis_port,
    uvm_driver,
    uvm_sequence_item,
    uvm_sequencer,
)

try:
    from cocotb.result import SimTimeoutError
except ImportError:
    from cocotb.triggers import SimTimeoutError


# How long a DUT-generated reset is given to take a defined value before the VIP
# is attached to it. The reset tree settles within a few clocks of the cold reset
# being applied; this is generous enough not to be a tuning knob and short enough
# that a reset which never resolves is reported rather than waited on forever.
_RESET_RESOLVE_CYCLES = 200


async def await_reset_resolved(reset_signal, clock, label: str) -> None:
    """Hold until `reset_signal` reads 0 or 1 rather than X.

    The VIP decides whether it is in reset by evaluating this signal, and an X
    reads as de-asserted. It then starts sampling handshake lines that are
    themselves X, and cocotb raises `Cannot convert Logic('X') to bool` out of
    the stream driver before the test has run a single check.

    The resets these agents watch are DUT outputs, not the cold reset the bench
    drives, so they are X until the reset tree has propagated. On a two-state
    simulator every signal is resolved from time 0 and this returns on the first
    look; on a four-state one it defers attachment until the tree has settled,
    which still lands well before reset is released.
    """
    for _ in range(_RESET_RESOLVE_CYCLES):
        if reset_signal.value.is_resolvable:
            return
        await RisingEdge(clock)
    raise AssertionError(
        f"{label} reset never took a defined value within {_RESET_RESOLVE_CYCLES} "
        f"clocks, so the VIP cannot tell whether it is in reset. Attaching anyway "
        f"would make it sample X handshake lines and fail somewhere less obvious."
    )


# The request-side lines an AXI-Lite master drives. On this bench they are
# inputs to the DUT wrapper, so nothing drives them until the bench does.
_AXIL_MASTER_DRIVEN = ("awvalid", "wvalid", "arvalid", "bready", "rready")


def idle_axil_master_inputs(dut, prefix: str) -> None:
    """Park an AXI-Lite master's own request lines low before a VIP attaches.

    The VIP only initialises VALID when its `_valid_init` is set, and zeroes it
    otherwise only on seeing reset asserted. An agent built after reset has been
    released hits neither path, so the line keeps whatever the bench left it at
    -- for a top-level input nothing has driven yet, that is Z. The VIP then
    samples its own VALID and cocotb raises out of the stream driver, before any
    checker runs and naming no signal.

    On `ej_axi` the DUT drives `ej_axi_awready` (it reads 1 once out of reset)
    while `ej_axi_awvalid` is a top-level input nothing has driven: the undriven
    line is the bench's, not the design's.

    The write is immediate because the VIP reads these lines during
    `from_prefix`, before a scheduled write would land.
    """
    for suffix in _AXIL_MASTER_DRIVEN:
        signal = getattr(dut, f"{prefix}_{suffix}", None)
        if signal is not None:
            signal.value = Immediate(0)


class SmcSysAxiOp(Enum):
    READ = "read"
    WRITE = "write"


class SmcSysAxiItem(uvm_sequence_item):
    """A single AXI access through the SMC SEP_IN AXI input."""

    def __init__(self, name: str = "SmcSysAxiItem") -> None:
        super().__init__(name)
        self.op: SmcSysAxiOp = SmcSysAxiOp.READ
        self.addr: int = 0
        self.length: int = 4
        self.wdata: int = 0
        self.expected: int | None = None
        self.expected_resp: int | None = None
        self.rdata: int = 0
        self.resp_code: int | None = None
        self.resp_ok: bool = False
        self.allow_error: bool = False
        # Negative-path probe: this access MUST return a real error response
        # (SLVERR/DECERR), not OKAY and not a wedge. The scoreboard enforces this
        # structurally (fails on OKAY or timeout), so a wrongly-OKAY blocked
        # access fails at the checker layer, not only in the sequence body.
        # Implies allow_error for the driver (the error response is expected).
        self.expect_error: bool = False
        # Soft-complete on AXI timeout. Default False. A call site that sets it
        # True states why incomplete traffic is acceptable there.
        self.allow_timeout: bool = False
        self.timed_out: bool = False
        self.timeout_ns: int | None = None
        # U1-3: TB-local SmcMemoryModel golden (not a DUT backdoor).
        # OKAY WR with update_golden updates the model; OKAY RD with
        # check_golden compares rdata against the model in the scoreboard.
        self.update_golden: bool = False
        self.check_golden: bool = False
        self.memory_region: str | None = None
        # AXI AxPROT. Default 0 (unprivileged); GPIO ACCESS_FILTER tests program
        # this to 1 (privileged).
        self.prot: int = 0
        # AXI AxBURST encoding: 0 FIXED, 1 INCR, 2 WRAP. `length` picks AxSIZE,
        # so a 1- or 2-byte access is a narrow transfer with the strobes the
        # backend derives from the address.
        self.burst: int = 1
        # Beats in the burst: the transfer is `beats` x `length` bytes, so
        # `beats` > 1 drives AxLEN = beats - 1 and `wdata` / `rdata` carry the
        # whole burst little-endian, first beat in the low bytes.
        self.beats: int = 1
        # Channel timing for this access only (an ocah_axi_vip AxiTimingProfile).
        # The driver arms it before the transaction and returns the master to
        # the backend default after, so a profile never leaks into the next item.
        self.timing = None
        # Stamped by the driver that actually drove this item (its `bus_name`),
        # so the scoreboard can keep a MEASURED per-port access tally. A test
        # never sets this: the point is that the count comes from the driver that
        # completed the access, not from the test that claims to have issued it.
        self.bus_name: str = ""

    @property
    def transfer_bytes(self) -> int:
        """Bytes the whole transfer moves: one beat per `length` bytes."""
        return self.length * self.beats

    def __str__(self) -> str:
        exp = "None" if self.expected is None else f"0x{self.expected:x}"
        return (
            f"{self.op.value} addr=0x{self.addr:014x} len={self.length} "
            f"beats={self.beats} burst={self.burst} "
            f"wdata=0x{self.wdata:x} rdata=0x{self.rdata:x} exp={exp} "
            f"ok={self.resp_ok}"
        )


class SmcSysAxiGroupItem(uvm_sequence_item):
    """Accesses the manager keeps outstanding at the same time.

    AXI transactions are pipelined: a manager may present the next address
    before the subordinate has answered the previous one. A driver that waits
    for each response before starting the next can never present more than one,
    so the subordinate's ready-side flow control is never exercised. The driver
    starts every member of a group before awaiting any of them; each member is
    a plain `SmcSysAxiItem` and reaches the scoreboard on its own, so every
    access in the group keeps its own expectation and its own check.
    """

    def __init__(self, name: str, items: list[SmcSysAxiItem], timing=None) -> None:
        super().__init__(name)
        assert items, "a SmcSysAxiGroupItem needs at least one access"
        self.items = list(items)
        self.timing = timing


class SmcSysAxiDriver(uvm_driver):
    """Drives SmcSysAxiItem transactions through ocah_axi_vip.OcahAxiMasterSequence."""

    bus_prefix = "s_axi"
    bus_name = "SEP_IN AXI"

    def build_phase(self) -> None:
        self.cfg = ConfigDB().get(self, "", "cfg")
        self.ap = uvm_analysis_port("ap", self)
        self.axi: OcahAxiMasterSequence | None = None

    async def run_phase(self) -> None:
        dut = cocotb.top
        await await_reset_resolved(dut.rst_primary_smc_clk_no, dut.clk_smc_i, self.bus_name)
        self.axi = OcahAxiMasterAgent.from_prefix(
            dut,
            self.bus_prefix,
            dut.clk_smc_i,
            dut.rst_primary_smc_clk_no,
            name=f"smc_{self.bus_prefix}",
            reset_active_level=False,
        ).sequence
        await self.cfg.reset_done.wait()
        self.logger.info("SMC %s OcahAxiMasterSequence ready on %s", self.bus_name, self.bus_prefix)

        while True:
            item = await self.seq_item_port.get_next_item()
            members = self._members(item)
            for member in members:
                member.bus_name = self.bus_name
            await self._drive(item)
            for member in members:
                self.ap.write(member)
            self.seq_item_port.item_done()

    @staticmethod
    def _members(item) -> list:
        """The accesses an item carries: a group's members, or the item itself."""
        return list(item.items) if isinstance(item, SmcSysAxiGroupItem) else [item]

    async def _drive(self, item) -> None:
        """Drive one item or group, under its own channel timing when it has one."""
        if item.timing is None:
            await self._drive_transfers(item)
            return
        self.axi.driver.set_timing(item.timing)
        try:
            await self._drive_transfers(item)
        finally:
            clear_profile(self.axi.driver)

    async def _drive_transfers(self, item) -> None:
        """Start every member on the bus, then collect the responses.

        A group's members are all started before any of them is awaited, so
        the manager keeps them outstanding at once and the address channels
        stay valid while the subordinate is still answering earlier ones.
        """
        members = self._members(item)
        events = [self._start_transfer(member) for member in members]
        for member, event in zip(members, events):
            await self._collect_transfer(member, event)

    def _start_transfer(self, item: SmcSysAxiItem):
        if item.op is SmcSysAxiOp.READ:
            return self.axi.init_read(
                address=item.addr,
                length=item.transfer_bytes,
                size=self._axi_size(item.length),
                burst=int(item.burst),
                prot=int(item.prot),
            )
        if item.op is SmcSysAxiOp.WRITE:
            return self.axi.init_write(
                address=item.addr,
                data=item.wdata.to_bytes(item.transfer_bytes, "little"),
                size=self._axi_size(item.length),
                burst=int(item.burst),
                prot=int(item.prot),
            )
        raise ValueError(f"unknown SMC SYS AXI op {item.op}")

    async def _collect_transfer(self, item: SmcSysAxiItem, event) -> None:
        what = item.op.value
        resp = await self._timed_event(event, item, what)
        if resp is None:
            item.resp_ok = item.allow_timeout
            return
        item.resp_code = self._resp_code(resp)
        _raw_ok = self._resp_ok(resp)
        item.resp_ok = _raw_ok or item.allow_error
        if item.op is SmcSysAxiOp.READ:
            item.rdata = int.from_bytes(resp.data, "little")
            self.logger.info(
                "%s read  0x%014x -> 0x%x ok=%s%s",
                self.bus_name,
                item.addr,
                item.rdata,
                item.resp_ok,
                self._tolerated_note(_raw_ok, item.resp_code),
            )
        else:
            self.logger.info(
                "%s write 0x%014x <- 0x%x ok=%s%s",
                self.bus_name,
                item.addr,
                item.wdata,
                item.resp_ok,
                self._tolerated_note(_raw_ok, item.resp_code),
            )

    @staticmethod
    def _tolerated_note(raw_ok: bool, resp_code: int) -> str:
        """Suffix that makes a TOLERATED error response visible in the log.

        `item.resp_ok` is `self._resp_ok(resp) or item.allow_error`, so without
        this suffix a SLVERR/DECERR that a sequence chose to tolerate renders as
        a bare `ok=True`, byte-identical to a genuine OKAY. The kept log is what
        a reader uses to decide what a testcase proved, so a tolerated error has
        to stay visible in it. The OKAY case keeps the plain format.
        """
        if raw_ok:
            return ""
        name = {1: "EXOKAY", 2: "SLVERR", 3: "DECERR"}.get(resp_code, f"resp={resp_code}")
        return f" [{name} TOLERATED via allow_error]"

    async def _timed_event(self, event, item: SmcSysAxiItem, what: str):
        timeout_ns = item.timeout_ns or self.cfg.axi_timeout_ns
        try:
            await with_timeout(event.wait(), timeout_ns, "ns")
            return event.data
        except SimTimeoutError as exc:
            item.timed_out = True
            if item.allow_timeout:
                self.logger.info(
                    "%s %s @ 0x%014x reached expected timeout after %d ns",
                    self.bus_name,
                    what,
                    item.addr,
                    timeout_ns,
                )
                return None
            raise AssertionError(
                f"{self.bus_name} {what} @ 0x{item.addr:014x} did not complete within "
                f"{timeout_ns} ns"
            ) from exc

    @staticmethod
    def _resp_code(resp) -> int | None:
        code = getattr(resp, "resp", None)
        if code is None:
            return None
        try:
            codes = code if isinstance(code, (list, tuple)) else [code]
            if not codes:
                return None
            return int(codes[0])
        except Exception:
            return None

    @staticmethod
    def _resp_ok(resp) -> bool:
        code = getattr(resp, "resp", None)
        if code is None:
            return False
        try:
            codes = code if isinstance(code, (list, tuple)) else [code]
            return len(codes) > 0 and all(int(c) <= 1 for c in codes)
        except Exception:
            return False

    @staticmethod
    def _axi_size(length: int) -> int:
        """Return AXI AxSIZE encoding for single-beat CSR accesses."""
        if length not in (1, 2, 4, 8):
            raise ValueError(f"unsupported CSR access length {length}")
        return {1: 0, 2: 1, 4: 2, 8: 3}[length]


class SmcSysAxiAgent(uvm_agent):
    def build_phase(self) -> None:
        self.sequencer = uvm_sequencer("sequencer", self)
        self.driver = SmcSysAxiDriver("driver", self)

    def connect_phase(self) -> None:
        self.driver.seq_item_port.connect(self.sequencer.seq_item_export)
        self.ap = self.driver.ap


class SmcSysInAxiDriver(SmcSysAxiDriver):
    """Drives transactions through the SMC SYS_IN AXI input."""

    bus_prefix = "sys_axi"
    bus_name = "SYS_IN AXI"


class SmcSysInAxiAgent(uvm_agent):
    def build_phase(self) -> None:
        self.sequencer = uvm_sequencer("sequencer", self)
        self.driver = SmcSysInAxiDriver("driver", self)

    def connect_phase(self) -> None:
        self.driver.seq_item_port.connect(self.sequencer.seq_item_export)
        self.ap = self.driver.ap


class SmcJtagAxiDriver(SmcSysAxiDriver):
    """Drives transactions through the SMC JTAG AXI input fabric port."""

    bus_prefix = "jtag_axi"
    bus_name = "JTAG AXI"


class SmcJtagAxiAgent(uvm_agent):
    def build_phase(self) -> None:
        self.sequencer = uvm_sequencer("sequencer", self)
        self.driver = SmcJtagAxiDriver("driver", self)

    def connect_phase(self) -> None:
        self.driver.seq_item_port.connect(self.sequencer.seq_item_export)
        self.ap = self.driver.ap
