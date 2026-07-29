# SPDX-License-Identifier: Apache-2.0
"""Routing verification for the peripheral AXI-Lite external-macro windows.

``smc_wrapper`` / ``smc`` drive four external-macro AXI-Lite master ports
(PLL, PVT, DTP CSR, peripheral extension). This test issues real SEP_IN CSR
reads and checks how far each window is reachable from the SEP_IN master,
using the per-port ``tb_axil_<macro>_active`` observables plus the AXI
response.

Per-window completion under ``smc_wrapper`` (real ``smc_local_xbar`` map):

* PLL / PVT — ``periph_reg`` window (0xC000_2000..0xC000_E800) reaches
  ``smc_ip_integration`` ``pll_wrap`` / ``pvt_wrap`` (OKAY + 0).
* EXTENSION — ``periph_reg`` ext window (0xC040_0000..) →
  ``u_axil_extension_err_slv`` (DECERR + 0).
* DTP CSR (0xC000_F000..0xC000_F800) — present on ``smc_periph_axi_lite_xbar``
  but **outside** the local ``periph_reg`` decode (ends 0xC000_E800). From
  SEP_IN the access hits the local default slave (DECERR + 0xBADCAB1E) and
  must **not** pulse ``tb_axil_dtp_csr_active``.

For each routable window we prove (1) matching ``tb_axil_*_active`` pulse,
(2) isolation from other macro ports, (3) the expected response/data.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, RisingEdge
from smc_base_test import smc_base_test

from seq_lib.smc_macro_axil_routing_test_seq import smc_macro_axil_read_seq

RESP_OKAY = 0
RESP_DECERR = 3
ERR_SLAVE_DATA = 0xBADCAB1E

# (name, active observable, base, expected resp, expected data)
_ROUTABLE = [
    ("PLL",       "tb_axil_pll_active",       0xC000_3000, RESP_OKAY,   0x0),
    ("PVT",       "tb_axil_pvt_active",       0xC000_7000, RESP_OKAY,   0x0),
    ("EXTENSION", "tb_axil_extension_active", 0xC040_0000, RESP_DECERR, 0x0),
]

# Outside local periph_reg window — local default slave, no macro-port pulse.
_UNROUTABLE_FROM_SEP_IN = [
    ("DTP_CSR", "tb_axil_dtp_csr_active", 0xC000_F000),
]

_ALL_ACTIVE = [m[1] for m in _ROUTABLE] + [m[1] for m in _UNROUTABLE_FROM_SEP_IN]


class _AxilActiveMonitor:
    """Sticky per-port latch of the tb_axil_*_active observables."""

    def __init__(self, dut) -> None:
        self.dut = dut
        self.sigs = {name: getattr(dut, name) for name in _ALL_ACTIVE}
        self.latched = {name: 0 for name in _ALL_ACTIVE}
        self._run = True

    def reset(self) -> None:
        self.latched = {name: 0 for name in _ALL_ACTIVE}

    async def run(self) -> None:
        while self._run:
            await RisingEdge(self.dut.clk_smc_i)
            for name, sig in self.sigs.items():
                v = sig.value
                if v.is_resolvable and int(v):
                    self.latched[name] = 1


@pyuvm.test()
class smc_macro_axil_routing_test(smc_base_test):
    """Prove routable macro windows reach their own port with expected resp."""

    auto_protocol_vip = False

    async def _read_window(self, mon, macro_name, addr):
        """Drain, clear latches, issue one SEP_IN read to `addr`, settle."""
        await ClockCycles(cocotb.top.clk_smc_i, 10)
        mon.reset()
        seq = smc_macro_axil_read_seq(f"macro_rd_{macro_name}", addr)
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await ClockCycles(cocotb.top.clk_smc_i, 4)
        return seq

    async def run_scenario(self) -> None:
        dut = cocotb.top
        mon = _AxilActiveMonitor(dut)
        cocotb.start_soon(mon.run())

        await ClockCycles(dut.clk_smc_i, 8)
        for name in _ALL_ACTIVE:
            sig = getattr(dut, name)
            assert sig.value.is_resolvable and int(sig.value) == 0, (
                f"{name} not idle before any macro access"
            )

        for macro_name, active_attr, addr, exp_resp, exp_data in _ROUTABLE:
            seq = await self._read_window(mon, macro_name, addr)

            assert mon.latched[active_attr] == 1, (
                f"{macro_name} read (0x{addr:08x}) did not assert {active_attr}; "
                f"decode/route to the {macro_name} master port failed"
            )
            for other in _ALL_ACTIVE:
                if other == active_attr:
                    continue
                assert mon.latched[other] == 0, (
                    f"{macro_name} read (0x{addr:08x}) spuriously asserted {other}"
                )
            assert not seq.timed_out, (
                f"{macro_name} read (0x{addr:08x}) timed out; responder silent"
            )
            assert seq.resp_code == exp_resp, (
                f"{macro_name} read (0x{addr:08x}) resp={seq.resp_code}, "
                f"expected {exp_resp}"
            )
            assert (seq.rdata & 0xFFFF_FFFF) == exp_data, (
                f"{macro_name} read (0x{addr:08x}) data=0x{seq.rdata:x}, "
                f"expected 0x{exp_data:08x}"
            )
            cocotb.log.info(
                "macro routing OK: %s @ 0x%08x -> %s pulsed, resp=%d, data=0x%08x",
                macro_name, addr, active_attr, seq.resp_code, seq.rdata & 0xFFFF_FFFF,
            )

        # Outside local periph_reg (ends 0xC000_E800): SEP_IN sees local default
        # DECERR and must not pulse any macro-port active (incl. DTP).
        for macro_name, active_attr, addr in _UNROUTABLE_FROM_SEP_IN:
            seq = await self._read_window(mon, macro_name, addr)
            assert not seq.timed_out, (
                f"{macro_name} read (0x{addr:08x}) timed out; expected upstream DECERR"
            )
            assert seq.resp_code == RESP_DECERR, (
                f"{macro_name} read (0x{addr:08x}) resp={seq.resp_code}, "
                f"expected DECERR({RESP_DECERR}) from the local xbar"
            )
            assert (seq.rdata & 0xFFFF_FFFF) == ERR_SLAVE_DATA, (
                f"{macro_name} read (0x{addr:08x}) data=0x{seq.rdata:x}, "
                f"expected default-slave 0x{ERR_SLAVE_DATA:08x}"
            )
            for other in _ALL_ACTIVE:
                assert mon.latched[other] == 0, (
                    f"{macro_name} read (0x{addr:08x}) unexpectedly asserted {other}"
                )

        mon._run = False
        cocotb.log.info(
            "Routing verified: %d routable window(s) reached their port",
            len(_ROUTABLE),
        )
