# SPDX-License-Identifier: Apache-2.0
"""Passive AXI protocol/integrity monitor for the SMC SEP_IN ``s_axi`` bus.

This monitor snoops the top-level ``s_axi_*`` channels independently from the
active cocotbext-axi master. It catches issues that can be hidden once response
data is converted to Python integers, such as fully unresolved read data or a
DECERR response.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge
from pyuvm import ConfigDB, uvm_component


def _hi(sig) -> bool:
    """A handshake bit is asserted only if it resolves to 1."""
    try:
        return int(sig.value) == 1
    except Exception:
        return False


def _value(sig):
    try:
        return int(sig.value)
    except Exception:
        return None


def _is_all_x(sig) -> bool:
    """True only if every bit of a bus is X/Z."""
    try:
        int(sig.value)
        return False
    except Exception:
        text = str(sig.value).lower()
        return len(text) > 0 and all(ch in "xz" for ch in text)


_RESP_NAME = {0: "OKAY", 1: "EXOKAY", 2: "SLVERR", 3: "DECERR", None: "unparsable"}


class SmcAxiMonitor(uvm_component):
    """Independent SMC SEP_IN AXI read/write-response monitor."""

    def build_phase(self) -> None:
        self.cfg = ConfigDB().get(self, "", "cfg")
        self.errors: list[str] = []
        self.r_beats = 0
        self.b_resps = 0
        self.last_araddr: int | None = None
        self.last_awaddr: int | None = None
        self.resp_tally = {0: 0, 1: 0, 2: 0, 3: 0, None: 0}
        # DECERR is normally a hard protocol failure. However, several SEP_IN
        # address windows legitimately DECERR *by design* in the OSS bench:
        #   * external-macro windows (PLL/PVT/extension) are terminated by DECERR
        #     boundary responders (prim_axi_lite_err_slv in tb_top) -- no macro
        #     model exists, so DECERR is the correct response,
        #   * the DTP CSR window (0xC000_F000..0xF7FF) routes to the dtp_csr
        #     external master port (local-xbar periph_main was extended to
        #     0xC000_F800 by #3765), which is DECERR-terminated by the bench
        #     boundary responder like PLL/PVT/extension.
        # GPIO_CTRL / REFCLK (0xC000_4440..0xC000_5000) is U5 RW-stubbed and
        # must return OKAY — not listed here. I3C wraps live at 0xC000_5000
        # (i3ccore_stub → SLVERR, which is not flagged here). Stale catalog
        # addresses around 0xC003_A000 are unmapped holes (DECERR expected).
        # These ranges are seeded as EXPECTED so DECERR on them is tallied but
        # not flagged; DECERR anywhere else (a mapped internal CSR that should
        # answer OKAY) is still a hard error. Tests may add ad-hoc expected
        # addresses via ``expected_decerr_addrs`` or set ``allow_decerr``.
        self.expected_decerr_ranges: list[tuple[int, int]] = [
            (0xC000_3000, 0xC000_4000),  # PLL macro boundary responder
            (0xC000_7000, 0xC000_8000),  # PVT macro boundary responder
            (0xC000_F000, 0xC000_F800),  # DTP CSR (unmapped local-xbar hole)
            (0xC003_A000, 0xC004_0000),  # stale I3C catalog hole (DECERR)
            (0xC040_0000, 0xC080_0000),  # peripheral extension boundary responder
        ]
        self.expected_decerr_addrs: set[int] = set()
        self.allow_decerr = False

    def _decerr_expected(self, addr: int | None) -> bool:
        if self.allow_decerr:
            return True
        if addr is None:
            return False
        if addr in self.expected_decerr_addrs:
            return True
        low = addr & 0xFFFF_FFFF
        return any(base <= low < end for base, end in self.expected_decerr_ranges)

    def _fail(self, msg: str) -> None:
        self.errors.append(msg)
        self.logger.error("SMC AXI MONITOR FAIL: %s", msg)

    async def run_phase(self) -> None:
        dut = cocotb.top
        sig = {
            name: getattr(dut, f"s_axi_{name}", None)
            for name in (
                "arvalid", "arready", "araddr",
                "awvalid", "awready", "awaddr",
                "rvalid", "rready", "rdata", "rresp",
                "bvalid", "bready", "bresp",
            )
        }
        required = ("rvalid", "rready", "rdata", "rresp", "bvalid", "bready", "bresp")
        if any(sig[name] is None for name in required):
            self.logger.info("s_axi response channels not found; SMC AXI monitor idle")
            return

        await self.cfg.reset_done.wait()
        self.logger.info("SMC AXI monitor active on SEP_IN s_axi bus")

        while True:
            await RisingEdge(dut.clk_smc_i)
            if sig["arvalid"] is not None and _hi(sig["arvalid"]) and _hi(sig["arready"]):
                self.last_araddr = _value(sig["araddr"])
            if sig["awvalid"] is not None and _hi(sig["awvalid"]) and _hi(sig["awready"]):
                self.last_awaddr = _value(sig["awaddr"])

            if _hi(sig["rvalid"]) and _hi(sig["rready"]):
                self.r_beats += 1
                code = _value(sig["rresp"])
                self.resp_tally[code if code in (0, 1, 2, 3) else None] += 1
                if _is_all_x(sig["rdata"]):
                    where = (
                        f" @ last AR 0x{self.last_araddr:014x}"
                        if self.last_araddr is not None else ""
                    )
                    self._fail(f"R beat returned all-X data{where}")
                if code == 3:
                    where = (
                        f" @ last AR 0x{self.last_araddr:014x}"
                        if self.last_araddr is not None else ""
                    )
                    if self._decerr_expected(self.last_araddr):
                        self.logger.info("R beat DECERR (expected)%s", where)
                    else:
                        self._fail(f"R beat returned DECERR{where}")

            if _hi(sig["bvalid"]) and _hi(sig["bready"]):
                self.b_resps += 1
                code = _value(sig["bresp"])
                if code == 3:
                    where = (
                        f" @ last AW 0x{self.last_awaddr:014x}"
                        if self.last_awaddr is not None else ""
                    )
                    if self._decerr_expected(self.last_awaddr):
                        self.logger.info("B beat DECERR (expected)%s", where)
                    else:
                        self._fail(f"B beat returned DECERR{where}")

    def check_phase(self) -> None:
        assert not self.errors, (
            f"SMC AXI monitor found {len(self.errors)} protocol error(s): "
            + "; ".join(self.errors[:8])
        )
        self.logger.info(
            "SMC AXI monitor: %d R beats, %d B resps; R-resp tally %s; 0 errors",
            self.r_beats,
            self.b_resps,
            ", ".join(f"{_RESP_NAME[k]}={v}" for k, v in self.resp_tally.items() if v),
        )
