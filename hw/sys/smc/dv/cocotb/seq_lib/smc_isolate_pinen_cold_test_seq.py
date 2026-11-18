# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""ISOLATE_REQ_PINEN_REG across a cold reset with the isolation pin high and with it low.

``clk_rst.adoc`` "Isolation Controls": ``ISOLATE_REQ_PINEN_REG`` has a conditional synchronous
clear: it clears on cold reset only while the synchronized isolation pin is low. "Isolation
Connections": ``ISOLATE_REQ_PINEN_REG`` is not reset by the cold reset while the pin is high, so
the isolation holds across it.

The pin is the Isolate Request pad of the integrator pad table, driven through the bench GPIO
external drive. The cold reset is ``rst_cold_ni`` held low for a fixed number of ``clk_ref_i``
cycles; the fall of the warm smc-clock reset proves the pulse reached the DUT. With the pin high,
``tb_isolate_req_o[3]`` is sampled on every ``clk_smc_i`` rise from before the cold assert until
the warm domain is back and the fuse sense has completed, and the register is read back once the
CSR path answers. With the pin low, the readback after the same pulse is 0 and the pin raised
afterwards no longer asserts ``tb_isolate_req_o[3]``.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge

from .smc_addr_map import smc_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_isolate_pin_utils import (
    ISOLATE_REQ_PINEN_REG,
    await_skip_mem_repair,
    drive_isolate_pin,
)

ISO_REG = smc_addr("SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_REG_BASE_ADDR")
BIT3 = 1 << 3
#: ``clk_ref_i`` cycles ``rst_cold_ni`` is held low; longer than the pin de-glitch filter.
COLD_LOW_REF = 128
#: Ceiling in ``clk_smc_i`` rises for an output to follow its inputs; expiry fails.
_BOUND = 128
#: Consecutive rises on which a held level must agree.
_HOLD = 32
#: Ceiling in ``clk_smc_i`` rises for the warm domain to come back after the cold release.
_RECOVERY_SMC = 50_000
#: Fewest ``clk_smc_i`` samples the cold-pulse monitor must have taken (8 per reference cycle).
_MIN_COLD_SAMPLES = COLD_LOW_REF * 4

CHK_SURVIVES = "CHK-PINEN-SURVIVES-COLD-PIN-HIGH"
CHK_CLEARS = "CHK-PINEN-CLEARS-COLD-PIN-LOW"


def _int(sig) -> int:
    assert sig.value.is_resolvable, f"X/Z on {sig._name}: {sig.value}"
    return int(sig.value)


class _ColdMon:
    """Per-``clk_smc_i`` sampler of ``tb_isolate_req_o[3]`` and the warm smc-clock reset."""

    def __init__(self) -> None:
        self.samples = 0
        self.iso_low = 0
        self.iso_high = 0
        self.warm_falls = 0
        self._prev_warm = 1
        self._task = None

    def start(self) -> None:
        dut = cocotb.top
        self.samples = self.iso_low = self.iso_high = self.warm_falls = 0
        self._prev_warm = _int(dut.tb_rst_warm_smc_clk_n) & 1
        self._task = cocotb.start_soon(self._run())

    def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None

    async def _run(self) -> None:
        dut = cocotb.top
        while True:
            await RisingEdge(dut.clk_smc_i)
            self.samples += 1
            if (_int(dut.tb_isolate_req_o) >> 3) & 1:
                self.iso_high += 1
            else:
                self.iso_low += 1
            warm = _int(dut.tb_rst_warm_smc_clk_n) & 1
            if self._prev_warm and not warm:
                self.warm_falls += 1
            self._prev_warm = warm


class smc_isolate_pinen_cold_test_seq(SmcCsrSeq):
    """PINEN[3] set, then one cold pulse with the pin high and one with it low."""

    def __init__(self, name: str = "smc_isolate_pinen_cold_test_seq") -> None:
        super().__init__(name)
        self.legs = 0

    def _iso3(self) -> int:
        return (_int(cocotb.top.tb_isolate_req_o) >> 3) & 1

    async def _await_iso3(self, want: int, label: str) -> int:
        last = -1
        for cycle in range(1, _BOUND + 1):
            await RisingEdge(cocotb.top.clk_smc_i)
            last = self._iso3()
            if last == want:
                return cycle
        raise AssertionError(
            f"{label}: tb_isolate_req_o[3] stayed {last} for {_BOUND}, want {want}"
        )

    async def _hold_iso3(self, want: int, label: str) -> None:
        for n in range(_HOLD):
            await RisingEdge(cocotb.top.clk_smc_i)
            got = self._iso3()
            assert got == want, (
                f"{label}: rise {n + 1}/{_HOLD} tb_isolate_req_o[3]={got}, want {want}"
            )

    async def _cold_pulse(self, mon: _ColdMon, label: str) -> None:
        """Hold ``rst_cold_ni`` low, release it, wait the warm domain and the fuse sense back."""
        dut = cocotb.top
        dut.rst_cold_ni.value = 0
        for _ in range(COLD_LOW_REF):
            await RisingEdge(dut.clk_ref_i)
        dut.rst_cold_ni.value = 1
        last = None
        for _ in range(_RECOVERY_SMC):
            await RisingEdge(dut.clk_smc_i)
            last = _int(dut.tb_rst_warm_smc_clk_n) & 1
            if last == 1:
                break
        else:
            raise AssertionError(f"{label}: warm smc clk reset still {last} after the cold release")
        await self.wait_fuse_sense_done()
        assert mon.warm_falls >= 1, (
            f"{label}: the warm smc clk reset never fell: no cold reset seen"
        )

    async def body(self) -> None:
        dut = cocotb.top
        for name in (
            "tb_isolate_req_o",
            "tb_skip_mem_repair_o",
            "tb_cfg_flr_pf_active",
            "tb_rst_warm_smc_clk_n",
            "tb_gpio_ext_drive_en",
            "tb_gpio_ext_drive_value",
        ):
            assert hasattr(dut, name), f"{name} missing from tb_top"
        await self.wait_fuse_sense_done()
        dut.tb_cfg_flr_pf_active.value = 0
        dut.rst_cool_ni.value = 1
        drive_isolate_pin(dut, 0)
        await await_skip_mem_repair(dut, 0, "pin low at start")
        await self.csr_read("ISO_REG_IDLE", ISO_REG, expected=0)
        await self.csr_read("PINEN_IDLE", ISOLATE_REQ_PINEN_REG, expected=0)
        await self._hold_iso3(0, "IDLE")

        # Arm: PINEN[3] set and the pin high assert isolate_req_o[3] before any cold reset.
        await self.csr_write("PINEN_SET", ISOLATE_REQ_PINEN_REG, BIT3)
        await self.csr_read("PINEN_SET_RB", ISOLATE_REQ_PINEN_REG, expected=BIT3)
        drive_isolate_pin(dut, 1)
        pin_arrived = await await_skip_mem_repair(dut, 1, "pin high before the cold pulse")
        up = await self._await_iso3(1, "ARM_UP")
        await self._hold_iso3(1, "ARM_HOLD")

        # Cold pulse with the pin high: the enable and the request hold through it.
        mon = _ColdMon()
        mon.start()
        try:
            await self._cold_pulse(mon, "COLD_PIN_HIGH")
            await self._hold_iso3(1, "POST_COLD_PIN_HIGH")
        finally:
            mon.stop()
        pinen_after_high = await self.csr_read("PINEN_AFTER_COLD_PIN_HIGH", ISOLATE_REQ_PINEN_REG)
        assert mon.samples >= _MIN_COLD_SAMPLES, (
            f"{CHK_SURVIVES} FAIL: monitor took {mon.samples} clk_smc_i samples, "
            f"fewer than {_MIN_COLD_SAMPLES}"
        )
        assert mon.iso_low == 0 and pinen_after_high == BIT3, (
            f"{CHK_SURVIVES} FAIL: with the pin high across a {COLD_LOW_REF}-ref-cycle cold pulse "
            f"tb_isolate_req_o[3] read 0 on {mon.iso_low} of {mon.samples} clk_smc_i samples and "
            f"ISOLATE_REQ_PINEN_REG read 0x{pinen_after_high:x} afterwards, want 0 low samples "
            f"and 0x{BIT3:x}"
        )
        self.legs += 1
        cocotb.log.info(
            "%s: PINEN[3] set and the pin high (seen by skip_mem_repair_o after %d rises, "
            "tb_isolate_req_o[3]=1 after %d rises); rst_cold_ni held low %d clk_ref_i cycles, the "
            "warm smc clk reset fell %d time(s); tb_isolate_req_o[3] read 1 on %d of %d clk_smc_i "
            "samples from the assert until the fuse sense completed, held 1 on %d further rises, "
            "and ISOLATE_REQ_PINEN_REG read back 0x%x",
            CHK_SURVIVES,
            pin_arrived,
            up,
            COLD_LOW_REF,
            mon.warm_falls,
            mon.iso_high,
            mon.samples,
            _HOLD,
            pinen_after_high,
        )

        # Cold pulse with the pin low: the enable clears and the pin raised afterwards has no
        # effect until software programs it again.
        drive_isolate_pin(dut, 0)
        await await_skip_mem_repair(dut, 0, "pin low before the second cold pulse")
        down = await self._await_iso3(0, "PIN_DROP")
        await self.csr_read("PINEN_BEFORE_COLD_PIN_LOW", ISOLATE_REQ_PINEN_REG, expected=BIT3)
        mon = _ColdMon()
        mon.start()
        try:
            await self._cold_pulse(mon, "COLD_PIN_LOW")
        finally:
            mon.stop()
        pinen_after_low = await self.csr_read("PINEN_AFTER_COLD_PIN_LOW", ISOLATE_REQ_PINEN_REG)
        drive_isolate_pin(dut, 1)
        pin_arrived_again = await await_skip_mem_repair(dut, 1, "pin high after the clearing cold")
        iso_after = []
        for _ in range(_HOLD):
            await RisingEdge(dut.clk_smc_i)
            iso_after.append(self._iso3())
        assert pinen_after_low == 0 and not any(iso_after), (
            f"{CHK_CLEARS} FAIL: with the pin low across a {COLD_LOW_REF}-ref-cycle cold pulse "
            f"ISOLATE_REQ_PINEN_REG read 0x{pinen_after_low:x} afterwards (want 0) and with the pin "
            f"raised again tb_isolate_req_o[3] read 1 on {sum(iso_after)} of {_HOLD} rises (want 0)"
        )
        self.legs += 1
        cocotb.log.info(
            "%s: ISOLATE_REQ_PINEN_REG read 0x%x before the pulse with the pin low "
            "(tb_isolate_req_o[3] fell %d rises after the pin dropped); rst_cold_ni held low %d "
            "clk_ref_i cycles, the warm smc clk reset fell %d time(s); the register read back 0x%x "
            "and with the pin high again (seen after %d rises) tb_isolate_req_o[3] read 0 on %d of "
            "%d rises",
            CHK_CLEARS,
            BIT3,
            down,
            COLD_LOW_REF,
            mon.warm_falls,
            pinen_after_low,
            pin_arrived_again,
            _HOLD - sum(iso_after),
            _HOLD,
        )

        drive_isolate_pin(dut, 0)
        await await_skip_mem_repair(dut, 0, "pin low at the end")
        drive_isolate_pin(dut, None)
        await self.csr_restore("PINEN", ISOLATE_REQ_PINEN_REG, 0)
