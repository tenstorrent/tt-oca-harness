# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The Key Manager ROM request stays known across an IC_RESET override of the KM.

RAND-NONE. no_cpu, ``+skip_fuse_sense``: no check reads fuse data. The KM
runs the smoke image (``+km_rom_hex=km_rom.parhex``): one SRAM store, then a
spin loop, so the KM fetches from its ROM on every loop turn.

The stimulus is the real ``jtag_ic_reset_reg`` in ``tb_top`` driving the SEP
reset-control port. The port is ``km_jtag_rst_n``, the TDO-end port of the SEP
slice (``doc/integrator/src/smu.adoc``). The TAP instruction that selects the
TDR is outside this DUT. The walk is the IEEE 1149.1 section 17 order: stage
the reset value with the override off, apply the override, release it. The TDR
field layout is the PTAP IC_RESET fields table in
``hw/ip/jtag/jtag_ptap/doc/architecture.adoc``.

Contract. The prim_rom request is a chip select and must never be X
(``vendor/lowRISC/opentitan/upstream/hw/ip/prim_generic/rtl/prim_rom.sv``
``noXOnCsI``). ``hw/top/sep_ip_integration.sv`` connects that request to the
Key Manager ROM request. The simulator evaluates ``noXOnCsI`` on every clock;
a firing prints an ``Error:`` line and the run fails. Verilator is two-state
and compiles no assertions, so only a four-state run with assertions can fail
this leaf; the testlist entry pins it to VCS.

The cocotb checks prove the path each window exercises:

* CHK-TDR-SELECT     the TDR shifts out its reset value after TRST.
* CHK-KM-LIVE        the KM left SW reset: ROM requests count up and the
                     image stored its SRAM marker.
* CHK-TDR-STAGE      the staged reset value alone does not stop the KM.
* CHK-TDR-APPLY      the applied override holds the KM: no ROM request.
* CHK-TDR-RELEASE    the control-first release restarts the KM: a ROM request
                     comes within 64 cycles of that Update-DR. A second
                     Update-DR disables the override without stopping it.
                     The log gives the latency. The window below starts after
                     both updates.
* CHK-KM-ROM-WINDOW  the KM fetches through a bounded window after that
                     first request. ``noXOnCsI`` grades every cycle of it.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import RisingEdge
from cocotb.utils import get_sim_time
from env.sep_ic_reset_tdr import IC_RESET_IDLE, SepIcResetTdr, port_index, tdr_word
from sep_base_test import sep_base_test
from seq_lib.sep_km_mem_smoke_seq import KM_SMOKE_SRAM_WORD0, sep_km_release_seq

_PORT = "km_jtag_rst_n"
_MAX_KM_CYCLES = 20_000
# Cycles the counter is watched after each TDR update. The override crosses a
# two-flop synchronizer into clk_i, so 64 cycles covers the crossing with room.
_SETTLE_CYCLES = 64
# Fetch window after the release that noXOnCsI grades.
_WINDOW_CYCLES = 4_000
_MIN_WINDOW_FETCHES = 64


@pyuvm.test()
class sep_km_ic_reset_release_test(sep_base_test):
    """The KM ROM request stays known through a km_jtag_rst_n stage, apply and release."""

    required_evidence = (
        "CHK-TDR-SELECT",
        "CHK-KM-LIVE",
        "CHK-TDR-STAGE",
        "CHK-TDR-APPLY",
        "CHK-TDR-RELEASE",
        "CHK-KM-ROM-WINDOW",
    )

    def _count(self) -> int:
        return self.rd_known(cocotb.top.km_rom_req_count_o)

    async def _cycles(self, n: int) -> None:
        for _ in range(n):
            await RisingEdge(cocotb.top.clk_i)

    def _stamp(self, label: str) -> None:
        self.logger.info("STEP %s at %.3f ns", label, get_sim_time("ns"))

    async def run_scenario(self) -> None:
        dut = cocotb.top
        await self.bring_up_no_cpu()
        tdr = SepIcResetTdr(self.rd_known)
        port = port_index(_PORT)

        await tdr.reset_and_select()
        await self._cycles(_SETTLE_CYCLES)
        captured = await tdr.capture_shift_update(IC_RESET_IDLE)
        assert captured == IC_RESET_IDLE, (
            f"CHK-TDR-SELECT FAIL: shifted-out 0x{captured:x}, want the TDR reset value "
            f"0x{IC_RESET_IDLE:x}"
        )
        self.logger.info(
            "CHK-TDR-SELECT PASS: TDR shifted out its reset value 0x%x "
            "(every reset_enable and reset_control at 1); %s is port %d",
            captured,
            _PORT,
            port,
        )

        await self.start_seq(sep_km_release_seq("km_ic_reset_release"))
        polled = 0
        for polled in range(1, _MAX_KM_CYCLES + 1):
            await RisingEdge(dut.clk_i)
            if self._count() > 0 and self.rd(dut.km_sram_word0_o, allow_unknown=True) == (
                KM_SMOKE_SRAM_WORD0
            ):
                break
        word0 = self.rd_known(dut.km_sram_word0_o)
        before = self._count()
        await self._cycles(_SETTLE_CYCLES)
        after = self._count()
        assert word0 == KM_SMOKE_SRAM_WORD0 and after > before > 0, (
            f"CHK-KM-LIVE FAIL: after {polled} cycles word0=0x{word0:08x} "
            f"(want 0x{KM_SMOKE_SRAM_WORD0:08x}) ROM requests {before}->{after}"
        )
        self.logger.info(
            "CHK-KM-LIVE PASS: KM out of SW reset; word0=0x%08x, ROM requests %d->%d "
            "over %d cycles",
            word0,
            before,
            after,
            _SETTLE_CYCLES,
        )

        # Stage: reset_control=0 with reset_enable still 1.
        self._stamp("stage km_jtag_rst_n")
        await tdr.capture_shift_update(tdr_word(hold=(_PORT,)))
        before = self._count()
        await self._cycles(_SETTLE_CYCLES)
        after = self._count()
        assert after > before, (
            f"CHK-TDR-STAGE FAIL: ROM requests {before}->{after}; the staged value "
            "stopped the KM with the override off"
        )
        self.logger.info(
            "CHK-TDR-STAGE PASS: reset_control[%d]=0 with reset_enable[%d]=1; "
            "ROM requests %d->%d, the KM still runs",
            port,
            port,
            before,
            after,
        )

        # Apply: reset_enable=0, reset_control=0.
        self._stamp("apply km_jtag_rst_n")
        await tdr.capture_shift_update(tdr_word(apply=(_PORT,), hold=(_PORT,)))
        await self._cycles(_SETTLE_CYCLES)
        before = self._count()
        await self._cycles(_SETTLE_CYCLES)
        after = self._count()
        assert after == before, (
            f"CHK-TDR-APPLY FAIL: ROM requests {before}->{after} while the override "
            "holds the KM in reset"
        )
        self.logger.info(
            "CHK-TDR-APPLY PASS: reset_enable[%d]=0 reset_control[%d]=0; ROM requests "
            "stay at %d over %d cycles",
            port,
            port,
            after,
            _SETTLE_CYCLES,
        )

        # Release control while the override remains selected. IC_RESET requires
        # control and enable to move in separate Update-DR operations so the
        # downstream reset mux never changes its value and select together.
        self._stamp("release km_jtag_rst_n control")
        held = self._count()
        await tdr.capture_shift_update(tdr_word(apply=(_PORT,)))
        first = None
        for cycle in range(1, _SETTLE_CYCLES + 1):
            await RisingEdge(dut.clk_i)
            if self._count() != held:
                first = cycle
                break
        assert first is not None, (
            f"CHK-TDR-RELEASE FAIL: no ROM request within {_SETTLE_CYCLES} cycles of the "
            "Update-DR that released reset_control"
        )
        before_disable = self._count()
        self._stamp("disable km_jtag_rst_n override")
        await tdr.capture_shift_update(IC_RESET_IDLE)
        await self._cycles(_SETTLE_CYCLES)
        after_disable = self._count()
        assert after_disable > before_disable, (
            f"CHK-TDR-RELEASE FAIL: ROM requests {before_disable}->{after_disable} after "
            "reset_enable returned to 1; disabling the override stopped the KM"
        )
        self.logger.info(
            "CHK-TDR-RELEASE PASS: reset_control released first; the first ROM request "
            "came %d cycles after Update-DR, then reset_enable returned to 1 in a "
            "separate Update-DR and ROM requests advanced %d->%d",
            first,
            before_disable,
            after_disable,
        )

        self._stamp("ROM request window start")
        start = self._count()
        await self._cycles(_WINDOW_CYCLES)
        end = self._count()
        self._stamp("ROM request window end")
        assert end - start >= _MIN_WINDOW_FETCHES, (
            f"CHK-KM-ROM-WINDOW FAIL: {end - start} ROM requests in {_WINDOW_CYCLES} "
            f"cycles after the release (want >= {_MIN_WINDOW_FETCHES})"
        )
        self.logger.info(
            "CHK-KM-ROM-WINDOW PASS: %d ROM requests in %d cycles after the release. "
            "prim_rom noXOnCsI grades the request on every one of those cycles",
            end - start,
            _WINDOW_CYCLES,
        )
