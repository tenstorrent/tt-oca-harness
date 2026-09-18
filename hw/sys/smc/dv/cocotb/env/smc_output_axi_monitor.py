# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Passive AXI response monitor for SMC SYS_OUT (output fabric) bus (U6-2).

Snoops ``tb_output_axi_{b,r}*`` lifted from ``output_axi_req/resp`` in tb_top.
Tallies OKAY / SLVERR / DECERR on B and R channels. Both error codes are a hard
fail unless the testcase opts in (``allow_slverr`` / ``allow_decerr``).
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge
from pyuvm import ConfigDB, uvm_component


def _hi(sig) -> bool:
    try:
        return int(sig.value) == 1
    except Exception:
        return False


def _value(sig):
    try:
        return int(sig.value)
    except Exception:
        return None


_RESP_NAME = {0: "OKAY", 1: "EXOKAY", 2: "SLVERR", 3: "DECERR", None: "unparsable"}


class SmcOutputAxiMonitor(uvm_component):
    """Independent SYS_OUT AXI B/R response monitor."""

    def build_phase(self) -> None:
        self.cfg = ConfigDB().get(self, "", "cfg")
        self.errors: list[str] = []
        self.r_beats = 0
        self.b_resps = 0
        self.last_araddr: int | None = None
        self.last_awaddr: int | None = None
        self.r_resp_tally = {0: 0, 1: 0, 2: 0, 3: 0, None: 0}
        self.b_resp_tally = {0: 0, 1: 0, 2: 0, 3: 0, None: 0}
        # SYS_OUT slave may inject SLVERR or DECERR (U1-2). Default False for
        # both: a testcase that expects one opts in with `mon.allow_slverr` /
        # `mon.allow_decerr` (smc_output_fabric_slverr_inject_test), so an
        # unexpected error response stays a hard fail everywhere else.
        self.allow_slverr = False
        self.allow_decerr = False

    def snapshot(self) -> dict[str, int]:
        return {
            "r_beats": self.r_beats,
            "b_resps": self.b_resps,
            "r_okay": self.r_resp_tally[0],
            "r_slverr": self.r_resp_tally[2],
            "b_okay": self.b_resp_tally[0],
            "b_slverr": self.b_resp_tally[2],
            "r_decerr": self.r_resp_tally[3],
            "b_decerr": self.b_resp_tally[3],
        }

    def _fail(self, msg: str) -> None:
        self.errors.append(msg)
        self.logger.error("SMC SYS_OUT AXI MONITOR FAIL: %s", msg)

    async def run_phase(self) -> None:
        dut = cocotb.top
        required = (
            "tb_output_axi_rvalid",
            "tb_output_axi_rready",
            "tb_output_axi_rresp",
            "tb_output_axi_bvalid",
            "tb_output_axi_bready",
            "tb_output_axi_bresp",
        )
        if any(not hasattr(dut, name) for name in required):
            self.logger.info("tb_output_axi_* response ports missing; SYS_OUT monitor idle")
            return

        await self.cfg.reset_done.wait()
        self.logger.info("SMC SYS_OUT AXI monitor active on tb_output_axi_*")

        while True:
            await RisingEdge(dut.clk_smc_i)
            if (
                hasattr(dut, "tb_output_axi_arvalid")
                and _hi(dut.tb_output_axi_arvalid)
                and _hi(dut.tb_output_axi_arready)
            ):
                self.last_araddr = _value(dut.tb_output_axi_araddr)
            if (
                hasattr(dut, "tb_output_axi_awvalid")
                and _hi(dut.tb_output_axi_awvalid)
                and _hi(dut.tb_output_axi_awready)
            ):
                self.last_awaddr = _value(dut.tb_output_axi_awaddr)

            if _hi(dut.tb_output_axi_rvalid) and _hi(dut.tb_output_axi_rready):
                self.r_beats += 1
                code = _value(dut.tb_output_axi_rresp)
                key = code if code in (0, 1, 2, 3) else None
                self.r_resp_tally[key] += 1
                where = f" @ AR 0x{self.last_araddr:x}" if self.last_araddr is not None else ""
                if code == 3 and not self.allow_decerr:
                    self._fail(f"R beat DECERR on SYS_OUT{where}")
                elif code == 2 and not self.allow_slverr:
                    self._fail(f"R beat SLVERR on SYS_OUT{where}")

            if _hi(dut.tb_output_axi_bvalid) and _hi(dut.tb_output_axi_bready):
                self.b_resps += 1
                code = _value(dut.tb_output_axi_bresp)
                key = code if code in (0, 1, 2, 3) else None
                self.b_resp_tally[key] += 1
                where = f" @ AW 0x{self.last_awaddr:x}" if self.last_awaddr is not None else ""
                if code == 3 and not self.allow_decerr:
                    self._fail(f"B beat DECERR on SYS_OUT{where}")
                elif code == 2 and not self.allow_slverr:
                    self._fail(f"B beat SLVERR on SYS_OUT{where}")

    def check_phase(self) -> None:
        assert not self.errors, (
            f"SMC SYS_OUT AXI monitor found {len(self.errors)} error(s): "
            + "; ".join(self.errors[:8])
        )
        self.logger.info(
            "SMC SYS_OUT AXI monitor: %d R / %d B; R {%s}; B {%s}; 0 errors",
            self.r_beats,
            self.b_resps,
            ", ".join(f"{_RESP_NAME[k]}={v}" for k, v in self.r_resp_tally.items() if v),
            ", ".join(f"{_RESP_NAME[k]}={v}" for k, v in self.b_resp_tally.items() if v),
        )
