# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS SEP-input AXI UVM agent.

Drives real AXI traffic through the tb_top ``s_axi_*`` bridge into
``smc.sep_axi_in_req_i``. This mirrors the SEP OSS AXI agent pattern and the
legacy SMC DV ``sep_in_master`` access path.
"""

from __future__ import annotations

from enum import Enum

import cocotb
from cocotb.triggers import with_timeout
from ocah_axi_vip import OcahAxiMasterAgent, OcahAxiMasterSequence
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
        # Soft-complete on AXI timeout. Default False. Setting True requires a
        # comment at the call site explaining why incomplete traffic is OK and
        self.allow_timeout: bool = False
        self.timed_out: bool = False
        self.timeout_ns: int | None = None
        # U1-3: TB-local SmcMemoryModel golden (not a DUT backdoor).
        # OKAY WR with update_golden updates the model; OKAY RD with
        # check_golden compares rdata against the model in the scoreboard.
        self.update_golden: bool = False
        self.check_golden: bool = False
        self.memory_region: str | None = None
        # AXI AxPROT. Default 0 (unprivileged) matches historical SEP_IN CSR
        # traffic. GPIO ACCESS_FILTER tests program this to 1 (privileged).
        self.prot: int = 0

    def __str__(self) -> str:
        exp = "None" if self.expected is None else f"0x{self.expected:x}"
        return (
            f"{self.op.value} addr=0x{self.addr:014x} len={self.length} "
            f"wdata=0x{self.wdata:x} rdata=0x{self.rdata:x} exp={exp} "
            f"ok={self.resp_ok}"
        )


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
            await self._drive(item)
            self.ap.write(item)
            self.seq_item_port.item_done()

    async def _drive(self, item: SmcSysAxiItem) -> None:
        if item.op is SmcSysAxiOp.READ:
            event = self.axi.init_read(
                address=item.addr,
                length=item.length,
                size=self._axi_size(item.length),
                prot=int(item.prot),
            )
            resp = await self._timed_event(event, item, "read")
            if resp is None:
                item.resp_ok = item.allow_timeout
                return
            item.rdata = int.from_bytes(resp.data, "little")
            item.resp_code = self._resp_code(resp)
            item.resp_ok = self._resp_ok(resp) or item.allow_error
            self.logger.info("%s read  0x%014x -> 0x%x ok=%s",
                             self.bus_name, item.addr, item.rdata, item.resp_ok)
        elif item.op is SmcSysAxiOp.WRITE:
            event = self.axi.init_write(
                address=item.addr,
                data=item.wdata.to_bytes(item.length, "little"),
                size=self._axi_size(item.length),
                prot=int(item.prot),
            )
            resp = await self._timed_event(event, item, "write")
            if resp is None:
                item.resp_ok = item.allow_timeout
                return
            item.resp_code = self._resp_code(resp)
            item.resp_ok = self._resp_ok(resp) or item.allow_error
            self.logger.info("%s write 0x%014x <- 0x%x ok=%s",
                             self.bus_name, item.addr, item.wdata, item.resp_ok)
        else:
            raise ValueError(f"unknown SMC SYS AXI op {item.op}")

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
