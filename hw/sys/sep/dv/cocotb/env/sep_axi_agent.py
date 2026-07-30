# SPDX-License-Identifier: Apache-2.0
"""SEP AXI UVM agent.

Owns the AXI master mechanics via ``ocah_axi_vip.OcahAxiMaster``: the driver
translates ``SepAxiItem`` transactions into AXI reads/writes against a SEP
master bus, and broadcasts completed transactions (with results) on an analysis
port for the scoreboard. The sequence item lives here too so the whole AXI
mechanism is one self-contained unit.

The agent is parameterized by bus ``prefix`` so the same machinery drives both
SEP master interfaces brought out in tb_top:
  * ``s_axi`` — the CPU-LSU master splice (primary stimulus; no inbound filter).
  * ``m_axi`` — the SMN-inbound external master (traverses the inbound filter;
    block-by-default, skipped only when feat_ctrl.sep_debug=1). Used by the
    inbound-filter-gating test to prove external AXI is blocked/allowed.
Set ``agent.axi_prefix`` right after constructing a second agent; it defaults to
``s_axi`` so existing single-master tests are unchanged.
"""

from __future__ import annotations

from enum import Enum

import cocotb
from cocotb.triggers import with_timeout
from pyuvm import (
    ConfigDB,
    uvm_agent,
    uvm_analysis_port,
    uvm_driver,
    uvm_sequence_item,
    uvm_sequencer,
)

from ocah_axi_vip import OcahAxiMaster

try:  # cocotb < 2.0
    from cocotb.result import SimTimeoutError
except ImportError:  # cocotb >= 2.0
    from cocotb.triggers import SimTimeoutError


class SepAxiOp(Enum):
    READ = "read"
    WRITE = "write"


class SepAxiItem(uvm_sequence_item):
    """A single AXI access on the CPU LSU bus."""

    def __init__(self, name: str = "SepAxiItem") -> None:
        super().__init__(name)
        self.op: SepAxiOp = SepAxiOp.READ
        self.addr: int = 0
        self.length: int = 4          # bytes
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
        # When True a non-completing access (no response within the timeout) is
        # NOT a test-fatal wedge but an explicitly expected outcome for a specific
        # sequence. Most negative-path checks should require a real error response
        # instead (for example, the inbound-filter-gating test requires DECERR).
        # The driver then sets timed_out=True and resp_ok=False rather than raising.
        self.allow_timeout: bool = False
        # Negative-path probe: this access expects a non-OKAY response and the
        # sequence/test asserts the exact resp_code itself. The scoreboard then
        # tolerates resp_ok=False (instead of failing) and, conversely, fails if a
        # probe marked expect_error returns OKAY (the access was NOT blocked).
        # Independent of allow_timeout: an expect_error probe still requires a real
        # error response, not a wedge, unless allow_timeout is also set.
        self.expect_error: bool = False
        # Filled in by the driver. resp_ok defaults False (fail closed): only a
        # confirmed OKAY response sets it True. resp_code is the worst (max) AXI
        # response code observed (OKAY=0, EXOKAY=1, SLVERR=2, DECERR=3), or -1 if
        # none was returned (e.g. a tolerated timeout). Lets a blocked-access test
        # require a SPECIFIC error response (DECERR) rather than accept any
        # non-OKAY / a wedge.
        self.rdata: int = 0
        self.resp_ok: bool = False
        self.resp_code: int = -1
        self.timed_out: bool = False

    def __str__(self) -> str:
        exp = "None" if self.expected is None else f"0x{self.expected:x}"
        return (
            f"{self.op.value} addr=0x{self.addr:08x} len={self.length} "
            f"wdata=0x{self.wdata:x} rdata=0x{self.rdata:x} exp={exp} "
            f"ok={self.resp_ok}"
        )


class SepAxiDriver(uvm_driver):
    """Drives SepAxiItem transactions through ocah_axi_vip.OcahAxiMaster."""

    def build_phase(self) -> None:
        self.cfg = ConfigDB().get(self, "", "cfg")
        self.ap = uvm_analysis_port("ap", self)
        self.axi: OcahAxiMaster | None = None

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
        self.axi = OcahAxiMaster.from_prefix(
            dut,
            self.prefix,
            dut.clk_i,
            dut.rst_ni,
            name=f"sep_{self.prefix}",
            reset_active_level=False,
        )
        await self.cfg.reset_done.wait()
        self.logger.info("OcahAxiMaster ready on %s bus", self.prefix)

        while True:
            item = await self.seq_item_port.get_next_item()
            await self._drive(item)
            self.ap.write(item)
            self.seq_item_port.item_done()

    async def _drive(self, item: SepAxiItem) -> None:
        if item.op is SepAxiOp.READ:
            event = self.axi.init_read(address=item.addr, length=item.length, size=item.size)
            resp = await self._timed_event(event, item, "read")
            if resp is None:                       # allowed timeout (blocked probe)
                return
            item.rdata = int.from_bytes(resp.data, "little")
            item.resp_ok = self._resp_ok(resp)
            item.resp_code = self._resp_code(resp)
            self.logger.info(
                "AXI read  0x%08x -> 0x%x (ok=%s resp=%d)",
                item.addr, item.rdata, item.resp_ok, item.resp_code,
            )
        elif item.op is SepAxiOp.WRITE:
            event = self.axi.init_write(
                address=item.addr,
                data=item.wdata.to_bytes(item.length, "little"),
                size=item.size,
            )
            resp = await self._timed_event(event, item, "write")
            if resp is None:                       # allowed timeout (blocked probe)
                return
            item.resp_ok = self._resp_ok(resp)
            item.resp_code = self._resp_code(resp)
            self.logger.info(
                "AXI write 0x%08x <- 0x%x (ok=%s resp=%d)",
                item.addr, item.wdata, item.resp_ok, item.resp_code,
            )
        else:
            raise ValueError(f"unknown SEP AXI op {item.op}")

    async def _timed_event(self, event, item: SepAxiItem, what: str):
        """Await an AXI op with a local timeout so a wedged bus path fails fast.

        Returns the completed event data, or ``None`` if the op timed out and the
        item explicitly opted into ``allow_timeout`` for a sequence-specific
        non-completing-access check. Otherwise a timeout is a test-fatal wedge.
        """
        try:
            await with_timeout(event.wait(), self.cfg.axi_timeout_ns, "ns")
            return event.data
        except SimTimeoutError as exc:
            if item.allow_timeout:
                item.timed_out = True
                item.resp_ok = False
                self.logger.info(
                    "AXI %s @ 0x%08x timed out (allowed by this sequence)",
                    what, item.addr,
                )
                return None
            raise AssertionError(
                f"AXI {what} @ 0x{item.addr:08x} did not complete within "
                f"{self.cfg.axi_timeout_ns} ns on the {self.prefix} bus - likely wedged"
            ) from exc

    @staticmethod
    def _resp_ok(resp) -> bool:
        """True only if every AXI response beat is OKAY/EXOKAY (resp code <= 1).

        Fails closed: a missing or unparsable response counts as NOT ok, so an
        unexpected cocotbext-axi response shape surfaces as a scoreboard error
        instead of silently passing.
        """
        code = getattr(resp, "resp", None)
        if code is None:
            return False
        try:
            codes = code if isinstance(code, (list, tuple)) else [code]
            return len(codes) > 0 and all(int(c) <= 1 for c in codes)
        except Exception:
            return False

    @staticmethod
    def _resp_code(resp) -> int:
        """Worst (max) AXI response code across all beats, or -1 if unreadable.

        OKAY=0, EXOKAY=1, SLVERR=2, DECERR=3. A blocked external access can then
        be required to return a SPECIFIC error (DECERR) rather than merely
        not-OKAY, so the block check fails on a wedge or an unexpected SLVERR.
        """
        code = getattr(resp, "resp", None)
        if code is None:
            return -1
        try:
            codes = code if isinstance(code, (list, tuple)) else [code]
            return max(int(c) for c in codes) if codes else -1
        except Exception:
            return -1


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
