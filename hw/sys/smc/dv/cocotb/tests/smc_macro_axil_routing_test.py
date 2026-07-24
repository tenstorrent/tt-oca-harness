# SPDX-License-Identifier: Apache-2.0
"""Routing verification for the peripheral AXI-Lite external-macro windows.

smc drives four external-macro AXI-Lite master ports (PLL, PVT, DTP CSR,
peripheral extension). This test issues real SEP_IN CSR reads and checks how
far each window is actually reachable from the SEP_IN master, using the
per-port ``tb_axil_<macro>_active`` observables plus the AXI response.

Two classes of window (from the generated crossbar RTL):

* ROUTABLE from SEP_IN (PLL 0xC0003000, PVT 0xC0007000, extension 0xC0400000,
  DTP CSR 0xC000F000): the smc_local_xbar forwards these to periph_reg and the
  periph AXI-Lite xbar decodes/routes them to the matching external master port.
  For each we prove
    1. the port's ``tb_axil_<macro>_active`` pulses during the access,
    2. no other macro port becomes active (isolation), and
    3. the DECERR boundary responder answers (resp = DECERR, data = 0xBADCAB1E).

  DTP CSR became routable via git e9617ae86/#3765, which extended the local-xbar
  periph_main window from [0xC0002000, 0xC000E800) to [0xC0002000, 0xC000F800).
  Before that fix 0xC000F000..0xF7FF was an unmapped local-xbar hole and this
  test asserted the dtp_csr port stayed idle; it now routes to the external
  dtp_csr master port like the other macro windows.

DEFENDS (in scope): SMC's own responsibility toward external macros --
local+periph address decode, routing to the correct master port, mutual
isolation between macro windows, completion of the AXI-Lite response
handshake, and the SEP_IN-reachability boundary of each window. This replaces
the previous idle-only observation (``tb_axil_*_active`` was only ever asserted
== 0), which could not distinguish a correct route from a mis-route or a silent
internal drop.

DOES NOT DEFEND (out of scope): any macro-internal function (PLL locking/clock
config, PVT sensing, DTP trace, extension Cadence-I3C behaviour) or register
read/write data semantics -- the bench uses DECERR bus terminators, not
functional macro models. Those belong to each macro's IP-level DV.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, RisingEdge
from smc_base_test import smc_base_test

from seq_lib.smc_macro_axil_routing_test_seq import smc_macro_axil_read_seq

RESP_DECERR = 3
# Both prim_axi_lite_err_slv (bench boundary responder) and the axi library's
# axi_err_slv (crossbar decode-error slave) answer reads with 0xBADCAB1E, so the
# data alone cannot tell them apart -- the tb_axil_*_active observable does.
BLOCK_DATA = 0xBADCAB1E

# (name, tb_axil active observable, base address) for windows the SEP_IN master
# can actually reach through smc_local_xbar -> periph AXI-Lite xbar. Addresses
# from meta/crossbars/configs/smc_periph_axi_lite_xbar.yaml.
#
# DTP_CSR (0xC000_F000) is now routable: git e9617ae86/#3765 extended the local
# xbar periph_main window to 0xC000_F800 (was 0xC000_E800), so the SEP_IN access
# now forwards to the dtp_csr external master port, which the OSS bench
# terminates with the DECERR boundary responder (same as PLL/PVT/extension).
_ROUTABLE = [
    ("PLL",       "tb_axil_pll_active",       0xC000_3000),
    ("PVT",       "tb_axil_pvt_active",       0xC000_7000),
    ("EXTENSION", "tb_axil_extension_active", 0xC040_0000),
    ("DTP_CSR",   "tb_axil_dtp_csr_active",   0xC000_F000),
]

# No SEP_IN-unroutable macro windows remain after the #3765 periph_main fix.
_UNROUTABLE_FROM_SEP_IN: list[tuple[str, str, int]] = []

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
    """Prove routable macro windows reach their own port; unroutable stay idle."""

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

        # Baseline: with no CSR traffic every macro port must be idle.
        await ClockCycles(dut.clk_smc_i, 8)
        for name in _ALL_ACTIVE:
            sig = getattr(dut, name)
            assert sig.value.is_resolvable and int(sig.value) == 0, (
                f"{name} not idle before any macro access"
            )

        # --- Routable windows: prove decode/route to the matching port. ---
        for macro_name, active_attr, addr in _ROUTABLE:
            seq = await self._read_window(mon, macro_name, addr)

            # 1) Positive routing: the matching macro port must have pulsed.
            assert mon.latched[active_attr] == 1, (
                f"{macro_name} read (0x{addr:08x}) did not assert {active_attr}; "
                f"decode/route to the {macro_name} master port failed"
            )
            # 2) Isolation: no other observed macro port may have pulsed.
            for other in _ALL_ACTIVE:
                if other == active_attr:
                    continue
                assert mon.latched[other] == 0, (
                    f"{macro_name} read (0x{addr:08x}) spuriously asserted {other}"
                )
            # 3) Response path: the DECERR boundary responder answered (no hang).
            assert not seq.timed_out, (
                f"{macro_name} read (0x{addr:08x}) timed out; boundary responder silent"
            )
            assert seq.resp_code == RESP_DECERR, (
                f"{macro_name} read (0x{addr:08x}) resp={seq.resp_code}, "
                f"expected DECERR({RESP_DECERR})"
            )
            assert (seq.rdata & 0xFFFF_FFFF) == BLOCK_DATA, (
                f"{macro_name} read (0x{addr:08x}) data=0x{seq.rdata:x}, "
                f"expected 0x{BLOCK_DATA:08x}"
            )
            cocotb.log.info(
                "macro routing OK: %s @ 0x%08x -> %s pulsed, resp=DECERR, data=0x%08x",
                macro_name, addr, active_attr, seq.rdata & 0xFFFF_FFFF,
            )

        # --- Unroutable window: prove it decode-errors upstream, port idle. ---
        for macro_name, active_attr, addr in _UNROUTABLE_FROM_SEP_IN:
            seq = await self._read_window(mon, macro_name, addr)

            # The SEP_IN access must complete (local xbar answers) with DECERR ...
            assert not seq.timed_out, (
                f"{macro_name} read (0x{addr:08x}) timed out; expected upstream DECERR"
            )
            assert seq.resp_code == RESP_DECERR, (
                f"{macro_name} read (0x{addr:08x}) resp={seq.resp_code}, "
                f"expected DECERR({RESP_DECERR}) from the local xbar decode-error slave"
            )
            # ... and NO external macro port may have been driven, in particular
            # the dtp_csr port, since the request never left the local xbar.
            for other in _ALL_ACTIVE:
                assert mon.latched[other] == 0, (
                    f"{macro_name} read (0x{addr:08x}) unexpectedly asserted {other}; "
                    f"0x{addr:08x} is an unmapped local-xbar hole and must not route out"
                )
            cocotb.log.info(
                "macro routing OK: %s @ 0x%08x is SEP_IN-unreachable "
                "(DECERR upstream, no external port driven)",
                macro_name, addr,
            )

        mon._run = False
        cocotb.log.info(
            "Routing verified: %d routable window(s) reached their port; "
            "%d window(s) confirmed SEP_IN-unreachable",
            len(_ROUTABLE), len(_UNROUTABLE_FROM_SEP_IN),
        )
