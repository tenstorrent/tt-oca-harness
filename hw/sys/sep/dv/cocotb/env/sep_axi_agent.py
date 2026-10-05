# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP AXI UVM agent.

PyUVM adapter over ``ocah_axi_vip.OcahAxiMasterSequence``. The driver
translates ``SepAxiItem`` into the VIP ``*_result`` API, then broadcasts
the completed item on an analysis port for the SEP scoreboard. Protocol
timeout, response codes, and result packaging live in the common VIP.

The agent is parameterized by bus ``prefix`` so the same machinery drives both
SEP master interfaces brought out in tb_top:
  * ``s_axi`` — the CPU-LSU master splice (primary stimulus; no inbound filter).
  * ``m_axi`` — the SMN-inbound external master (traverses the inbound filter;
    block-by-default, skipped only when feat_ctrl.sep_debug=1). Used by the
    inbound-filter-gating test to prove external AXI is blocked/allowed.
Set ``agent.axi_prefix`` right after constructing a second agent; it defaults to
``s_axi``.
"""

from __future__ import annotations

from enum import Enum

import cocotb
from ocah_axi_vip import OcahAxiMasterAgent, OcahAxiMasterSequence
from pyuvm import (
    ConfigDB,
    uvm_agent,
    uvm_analysis_port,
    uvm_driver,
    uvm_sequence_item,
    uvm_sequencer,
)


class SepAxiOp(Enum):
    READ = "read"
    WRITE = "write"


class SepAxiItem(uvm_sequence_item):
    """A single AXI access on s_axi (CPU-LSU) or m_axi (SMN-inbound)."""

    def __init__(self, name: str = "SepAxiItem") -> None:
        super().__init__(name)
        self.op: SepAxiOp = SepAxiOp.READ
        self.addr: int = 0
        self.length: int = 4  # bytes
        # AXI AxSIZE encoding (2 => 4-byte beat). None lets cocotbext-axi pick the
        # full bus width (64-bit). OTBN IMEM/DMEM are 32-bit SECDED words and
        # reject a 64-bit beat (SLVERR), so those accesses force size=2.
        self.size: int | None = None
        self.wdata: int = 0
        # Expected read data (low length*8 bits); None => scoreboard skips the
        # value check (still checks the AXI response).
        self.expected: int | None = None
        # Some target windows acknowledge writes in a way cocotbext-axi cannot
        # classify, while a following readback still proves the write landed.
        self.allow_unverified_write_resp: bool = False
        # Read-side counterpart, for a read the specification refuses without
        # naming the response code (a read-locked eFuse shadow). The scoreboard
        # does not grade a non-OKAY response on such a read; the caller grades
        # the returned data and side effects. A timed-out read still fails
        # unless allow_timeout is also set; the sequence then grades the wedge.
        self.allow_ungraded_read_resp: bool = False
        # When True a non-completing access (no response within the timeout) is
        # NOT a test-fatal wedge but an explicitly expected outcome for a specific
        # sequence. Most negative-path checks should require a real error response
        # instead (for example, the inbound-filter-gating test requires DECERR).
        # The driver then sets timed_out=True and resp_ok=False rather than raising.
        self.allow_timeout: bool = False
        # Negative-path probe: this access expects a non-OKAY response and the
        # sequence/test asserts the exact resp_code itself. On the s_axi agent,
        # the only one sep_env connects to the scoreboard, the scoreboard then
        # tolerates resp_ok=False (instead of failing) and, conversely, fails if a
        # probe marked expect_error returns OKAY (the access was NOT blocked). On
        # the m_axi (external) agent nothing grades this flag, so the caller must
        # assert the response itself.
        # Independent of allow_timeout: an expect_error probe still requires a real
        # error response, not a wedge, unless allow_timeout is also set.
        self.expect_error: bool = False
        # Read-data X/Z policy. cocotbext-axi converts each R beat with int(),
        # which raises on any X/Z bit, so a read through this driver fails at
        # the read when RDATA carries an unknown bit in any lane. SepAxiMonitor
        # checks the accessed lanes on the bus independently: an OKAY/EXOKAY
        # beat with an X/Z bit in a lane this read accesses fails the run. True
        # skips only that monitor lane check for this read; it does not stop
        # cocotbext-axi from raising on an X/Z bit.
        self.allow_unknown_rdata: bool = False
        # Packed AWUSER/ARUSER. The inbound filter matches FILTER_CONFIG.src_id
        # against user[3:0] (SRC_ID_USER_BIT_START=0, SRC_ID_WIDTH=4).
        self.user: int = 0
        # AXI AxBURST. None lets the VIP default (INCR). Leave None everywhere
        # except the inbound-filter burst checkers, which opt in with INCR and
        # a multi-beat length so AxLEN != 0.
        self.burst: int | None = None
        # AXI AxID. Every access defaults to 0. A test that wants the
        # transaction ID as a dimension sets it. The crossbars prepend
        # the master index to it, and the demux keeps one outstanding counter
        # per ID, so an access that never leaves 0 exercises one ID slot.
        self.axi_id: int = 0
        # AxPROT. None keeps the VIP default (data, non-secure, unprivileged).
        # The inbound filter matches prot[1] against FILTER_CONFIG.allow_ns.
        self.prot: int | None = None
        # AxLOCK / AxCACHE / AxQOS / AxREGION, and WUSER on a write. An absent
        # key keeps the VIP default (normal access, cache 0b0011, 0, 0, 0).
        self.attrs: dict[str, int] = {}
        # Filled in by the driver. resp_ok defaults False (fail closed): only a
        # confirmed OKAY response sets it True. resp_code is the worst (max) AXI
        # response code observed (OKAY=0, EXOKAY=1, SLVERR=2, DECERR=3), or -1 if
        # none was returned (e.g. a tolerated timeout). Lets a blocked-access test
        # require a SPECIFIC error response (DECERR) rather than accept any
        # non-OKAY / a wedge.
        self.rdata: int = 0
        self.resp_ok: bool = False
        self.resp_code: int = -1
        # Per-beat responses. resp_code is the worst of these, which cannot say
        # HOW MANY beats carried an error -- a caller crediting a monitor per
        # beat needs the list.
        self.resp_list: tuple[int, ...] = ()
        # BID / RID (the last read beat's) as sampled on the bus, or None when
        # the bus carries no ID.
        self.resp_id: int | None = None
        self.timed_out: bool = False

    def __str__(self) -> str:
        exp = "None" if self.expected is None else f"0x{self.expected:x}"
        return (
            f"{self.op.value} addr=0x{self.addr:08x} len={self.length} "
            f"wdata=0x{self.wdata:x} rdata=0x{self.rdata:x} exp={exp} "
            f"ok={self.resp_ok}"
        )


class SepAxiDriver(uvm_driver):
    """Drives SepAxiItem transactions through ocah_axi_vip.OcahAxiMasterSequence."""

    def build_phase(self) -> None:
        self.cfg = ConfigDB().get(self, "", "cfg")
        self.ap = uvm_analysis_port("ap", self)
        self.axi: OcahAxiMasterSequence | None = None
        self.monitor = None

    async def run_phase(self) -> None:
        dut = cocotb.top
        # Bus prefix: "s_axi" (CPU-LSU splice, default) or "m_axi" (SMN-inbound
        # external master). The agent sets driver.axi_prefix in its build_phase;
        # falls back to s_axi for the default single-master env.
        self.prefix = getattr(self, "axi_prefix", "s_axi")
        # Construct the master immediately so it drives the bus to a clean idle
        # from time 0 (the CPU-LSU splice drives the bus from t=0; the external
        # m_axi master must also idle from t=0 so the inbound port never X-props).
        # Only the transaction loop waits for reset release.
        # data_width=64 matches s_axi / m_axi. raise_on_error=False: the SEP
        # scoreboard owns OKAY vs expect_error; the VIP must not raise first.
        self.axi = OcahAxiMasterAgent.from_prefix(
            dut,
            self.prefix,
            dut.clk_i,
            dut.rst_ni,
            name=f"sep_{self.prefix}",
            reset_active_level=False,
            data_width=64,
            timeout_ns=self.cfg.axi_timeout_ns,
            raise_on_error=False,
        ).sequence
        # The bus monitor for this prefix owns the read-data X/Z check. The
        # driver needs it only to open the exemption window for a read that
        # sets allow_unknown_rdata, and to drop the AR of a timed-out read.
        try:
            self.monitor = ConfigDB().get(self, "", f"sep_axi_monitor_{self.prefix}")
        except Exception:
            self.monitor = None
        await self.cfg.reset_done.wait()
        self.logger.info("OcahAxiMasterSequence ready on %s bus", self.prefix)

        while True:
            item = await self.seq_item_port.get_next_item()
            await self._drive(item)
            self.ap.write(item)
            self.seq_item_port.item_done()

    async def _drive(self, item: SepAxiItem) -> None:
        # Byte-length helpers, not write_result/read_result: those encode one
        # beat from data_width/size, which would widen a length=4 access on
        # this 64-bit bus. SepAxiItem.length is the transfer size.
        common = {
            "size": item.size,
            "burst": item.burst,
            "id": item.axi_id,
            "prot": item.prot,
            "check_response": False,
            "timeout_ns": self.cfg.axi_timeout_ns,
            "allow_timeout": item.allow_timeout,
            "user": item.user,
        }
        if item.attrs:
            common["attrs"] = dict(item.attrs)
        if item.op is SepAxiOp.READ:
            exempt = item.allow_unknown_rdata and self.monitor is not None
            if item.allow_unknown_rdata and self.monitor is None:
                raise AssertionError(
                    f"allow_unknown_rdata read at 0x{item.addr:08x} on {self.prefix}: "
                    "no SepAxiMonitor is registered for this bus, so the exemption "
                    "cannot be scoped to this read"
                )
            if exempt:
                self.monitor.open_unknown_rdata_window()
            try:
                result = await self.axi.read_bytes_result(item.addr, item.length, **common)
            finally:
                if exempt:
                    self.monitor.close_unknown_rdata_window()
            self._apply_result(item, result, "read")
            if item.timed_out:
                if self.monitor is not None:
                    self.monitor.forget_pending_reads(item.axi_id)
                return
            # cocotbext-axi raised already if any RDATA bit of the read was X/Z,
            # so the bytes here are known values.
            item.rdata = (
                int.from_bytes(result.data_bytes, "little") if result.data_bytes else result.data
            )
            self.logger.info(
                "AXI read  0x%08x -> 0x%x (ok=%s resp=%d)",
                item.addr,
                item.rdata,
                item.resp_ok,
                item.resp_code,
            )
        elif item.op is SepAxiOp.WRITE:
            result = await self.axi.write_bytes_result(
                item.addr, item.wdata.to_bytes(item.length, "little"), **common
            )
            self._apply_result(item, result, "write")
            if item.timed_out:
                return
            self.logger.info(
                "AXI write 0x%08x <- 0x%x (ok=%s resp=%d)",
                item.addr,
                item.wdata,
                item.resp_ok,
                item.resp_code,
            )
        else:
            raise ValueError(f"unknown SEP AXI op {item.op}")

    def _apply_result(self, item: SepAxiItem, result, what: str) -> None:
        item.timed_out = result.timed_out
        item.resp_ok = result.ok
        item.resp_code = result.resp
        item.resp_list = tuple(getattr(result, "resp_list", ()) or ())
        item.resp_id = getattr(result, "observed_id", None)
        if result.timed_out:
            self.logger.info(
                "AXI %s @ 0x%08x timed out (allowed by this sequence)",
                what,
                item.addr,
            )


class SepAxiAgent(uvm_agent):
    def build_phase(self) -> None:
        self.sequencer = uvm_sequencer("sequencer", self)
        self.driver = SepAxiDriver("driver", self)
        # Propagate the per-agent bus prefix (set by the env after construction;
        # defaults to s_axi) to the driver. Build is top-down, so the env has
        # already set self.axi_prefix on a second (m_axi) agent by now.
        self.driver.axi_prefix = getattr(self, "axi_prefix", "s_axi")

    def connect_phase(self) -> None:
        self.driver.seq_item_port.connect(self.sequencer.seq_item_export)
        # Expose the driver's completed-transaction stream as the agent's port.
        self.ap = self.driver.ap
