# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Raw interrupt bit 320 pulses once per rise of the held CLA clock-stop output.

`interrupts.adoc` gives raw bit 320 as a one-cycle pulse when the CLA
clock-stop output rises, and says the output is held until the SMC primary
reset, so PLIC source 321 fires once per rise and needs no acknowledge at the
CLA. `dfd.adoc` says the mask and `tdr_dbg_ctrl_clock_stop_en_i` gate the
output without clearing the held request. Held to that, with the enable and
`DEBUG_CTRL.xtrig_clk_halt_mask` bit 0 set, the halt-clock action raises
`tb_cla_clock_stop` and bit 320 of `tb_cpu_interrupts` is 1 on exactly one
`clk_smc_i` sample. The pair is then quieted, its status cleared by the W2C
and `EnableEap` cleared, so only the held request keeps the output up; source
321 pends, is claimed and completed, and stays clear while the output stays 1. Dropping the enable drops the output with no pulse;
raising it again gives exactly one more pulse and one more pending source 321.

`REGION_SIZE` is opened to 256M so the system port reaches the PLIC, and source
321 is enabled on context 0 at priority 1 with threshold 0 for the
claims; the enable, the priority, the mask and the bench enable are put back
at the end.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge

from .smc_addr_map import REGION_SIZE_RESET, smc_addr, smc_indexed_addr
from .smc_dfd_cla_action_seq_utils import SAMPLE_CYCLES, SmcDfdClaActionSeq
from .smc_dfd_trace_accumulator_fill_test_seq import dfd_register

CHK_PULSE = "CHK-CLA-CLKSTOP-IRQ-PULSE"
CHK_NO_REPEND = "CHK-CLA-CLKSTOP-IRQ-NO-REPEND"
CHK_REARM = "CHK-CLA-CLKSTOP-IRQ-REARM"
RAW_BIT = 320
SOURCE = RAW_BIT + 1
# PLIC ENABLE / PENDING word 10 carries sources 320 to 351.
WORD = SOURCE // 32
WORD_BIT = 1 << (SOURCE % 32)
PLIC = "SMC_TOP_SMC_CLUSTER_PLIC_"
REGION_SIZE = smc_addr("SMC_TOP_SMC_BASE_CONFIG_REGION_SIZE_BASE_ADDR")
# The PLIC sits past the reset REGION_SIZE window of the system port.
REGION_SIZE_256M = 0x1000_0000
THRESHOLD0 = smc_addr(PLIC + "CORE0_MEIP_THRESHOLD_BASE_ADDR")
CLAIM0 = smc_addr(PLIC + "CORE0_MEIP_CLAIM_COMPLETE_BASE_ADDR")
ENABLE0 = smc_indexed_addr(PLIC + "CORE0_MEIP_ENABLE_BASE_ADDR", WORD)
PRIORITY = smc_indexed_addr(PLIC + "PRIORITY_BASE_ADDR", SOURCE)
# dfx_ctrl_status.rdl DEBUG_CTRL.xtrig_clk_halt_mask: bit 0 passes the halt request.
_HALT_MASK_LOWEST = 0x1
# Samples kept after each step, long enough for a level to re-pend after a complete.
_HOLD_SAMPLES = 4 * SAMPLE_CYCLES
_SOURCES = ("tb_cla_clock_stop", "tb_plic_pending_321")


class _Sampler:
    """Per clk_smc_i rise: raw bit 320, the clock-stop output and PLIC pending 321."""

    def __init__(self) -> None:
        self.raw: list[int] = []
        self.samples: dict[str, list[int]] = {name: [] for name in _SOURCES}
        self.stop = False

    async def run(self) -> None:
        top = cocotb.top
        while not self.stop:
            await RisingEdge(top.clk_smc_i)
            await ReadOnly()
            vec = top.tb_cpu_interrupts.value
            assert vec.is_resolvable, f"tb_cpu_interrupts is X/Z ({vec})"
            self.raw.append((int(vec) >> RAW_BIT) & 1)
            for name in _SOURCES:
                value = getattr(top, name).value
                assert value.is_resolvable, f"{name} is X/Z ({value})"
                self.samples[name].append(int(value))

    def mark(self) -> int:
        return len(self.raw)

    def window(self, start: int) -> tuple[list[int], list[int], list[int]]:
        return (
            self.raw[start:],
            self.samples["tb_cla_clock_stop"][start:],
            self.samples["tb_plic_pending_321"][start:],
        )


def _rises(seq: list[int]) -> list[int]:
    return [i for i in range(len(seq)) if seq[i] and (i == 0 or not seq[i - 1])]


class smc_dfd_cla_clock_stop_irq_pulse_test_seq(SmcDfdClaActionSeq):
    """Fire the clock-halt action with the enable set; grade bit 320 and PLIC source 321."""

    def __init__(self, name: str = "smc_dfd_cla_clock_stop_irq_pulse_test_seq") -> None:
        super().__init__(name)

    async def _hold(self) -> None:
        await ClockCycles(cocotb.top.clk_smc_i, _HOLD_SAMPLES)

    async def _claim(self, label: str) -> int:
        return await self.csr_read(f"CLAIM0_{label}", CLAIM0)

    def _grade_one_pulse(self, chk: str, step: str, start: int, sampler: _Sampler) -> str:
        raw, stop, _ = sampler.window(start)
        high = [i for i, v in enumerate(raw) if v]
        stop_rises = _rises(stop)
        assert len(stop_rises) == 1 and all(stop[stop_rises[0] :]), (
            f"{chk} FAIL: {step}: tb_cla_clock_stop rises at samples {stop_rises} of {len(stop)} "
            f"and must rise once and stay 1"
        )
        rise = stop_rises[0]
        assert len(high) == 1 and high[0] in (rise, rise + 1), (
            f"{chk} FAIL: {step}: raw bit {RAW_BIT} high at samples {high[:16]} "
            f"({len(high)} of {len(raw)}), want exactly one sample at the clock-stop rise "
            f"(sample {rise})"
        )
        return f"{step}: clock-stop rose at sample {rise}, bit {RAW_BIT} high only at {high[0]}"

    async def _claim_once(self, chk: str, step: str) -> None:
        pending = self._pin("tb_plic_pending_321")
        assert pending == 1, f"{chk} FAIL: {step}: tb_plic_pending_321={pending} after the pulse"
        claim = await self._claim(f"{step}_claim")
        assert claim == SOURCE, f"{chk} FAIL: {step}: context 0 claim read {claim}, want {SOURCE}"
        await self.csr_write(f"COMPLETE{SOURCE}_{step}", CLAIM0, SOURCE)

    async def _grade_quiet(self, chk: str, step: str, sampler: _Sampler) -> str:
        """After the complete the output stays 1, bit 320 stays 0 and 321 does not re-pend."""
        start = sampler.mark()
        await self._hold()
        raw, stop, pend = sampler.window(start)
        claim = await self._claim(f"{step}_reclaim")
        assert all(stop), f"{chk} FAIL: {step}: tb_cla_clock_stop dropped after the complete"
        assert not any(raw), (
            f"{chk} FAIL: {step}: raw bit {RAW_BIT} high at sample {raw.index(1)} of {len(raw)} "
            f"after the complete with the output held"
        )
        assert not any(pend) and claim == 0, (
            f"{chk} FAIL: {step}: source {SOURCE} pending again after the complete "
            f"(pending samples {sum(pend)} of {len(pend)}, claim read {claim})"
        )
        return f"{step}: {len(raw)} samples after the complete, output 1, bit {RAW_BIT} 0, claim 0"

    async def body(self) -> None:
        top = cocotb.top
        await self.wait_fuse_sense_done()
        debug_ctrl = dfd_register("dfx_ctrl/DEBUG_CTRL")
        await self.csr_write("REGION_SIZE_256M", REGION_SIZE, REGION_SIZE_256M)
        await self.csr_read("REGION_SIZE_256M_RB", REGION_SIZE, expected=REGION_SIZE_256M)
        saved_prio = await self.csr_read("PRIORITY321_SAVE", PRIORITY)
        saved_threshold = await self.csr_read("THRESHOLD0_SAVE", THRESHOLD0)
        saved_enable = await self.csr_read("ENABLE0_W10_SAVE", ENABLE0)
        await self.csr_write("PRIORITY321_ONE", PRIORITY, 1)
        await self.csr_write("THRESHOLD0_ZERO", THRESHOLD0, 0)
        await self.csr_write("ENABLE0_W10_SRC321", ENABLE0, WORD_BIT)
        await self._write(
            debug_ctrl, {"force_clk_en": 1, "xtrig_clk_halt_mask": _HALT_MASK_LOWEST}, "halt_mask"
        )
        top.tb_cla_clock_stop_en.value = 1
        sampler = _Sampler()
        task = cocotb.start_soon(sampler.run())
        await self._write(self._eap(), {}, "reset")
        await self._write_ctrl(1, 1, 0, "arm")
        await self._hold()
        raw, stop, pend = sampler.window(0)
        assert not any(raw) and not any(stop) and not any(pend), (
            f"bit {RAW_BIT}, tb_cla_clock_stop or tb_plic_pending_321 set before the fire"
        )

        start = sampler.mark()
        action, activating, quiet = await self._discover("tb_cla_clock_stop", "stop")
        await self._hold()
        first = self._grade_one_pulse(CHK_PULSE, "fire", start, sampler)
        await self._quiet(action, quiet, "quiet")
        await self._w2c("once")
        assert await self._status_bit("after_w2c") == 0, (
            f"CDbgEapStatus.Node0Eap0 still 1 after the W2C with the pair quiet (op {quiet})"
        )
        await self._write_ctrl(1, 0, 0, "eap_off")
        cocotb.log.info(
            "%s: halt-clock action %d on LogicalOp %d; %s", CHK_PULSE, action, activating, first
        )

        await self._claim_once(CHK_NO_REPEND, "fire")
        quiet = await self._grade_quiet(CHK_NO_REPEND, "fire", sampler)
        cocotb.log.info(
            "%s: source %d claimed and completed once; %s", CHK_NO_REPEND, SOURCE, quiet
        )

        start = sampler.mark()
        top.tb_cla_clock_stop_en.value = 0
        await self._hold()
        raw, stop, _ = sampler.window(start)
        assert not any(raw) and stop and stop[-1] == 0, (
            f"{CHK_REARM} FAIL: enable dropped: tb_cla_clock_stop ends {stop[-1:]} and raw bit "
            f"{RAW_BIT} high on {sum(raw)} samples, want output 0 and no pulse"
        )
        start = sampler.mark()
        top.tb_cla_clock_stop_en.value = 1
        await self._hold()
        second = self._grade_one_pulse(CHK_REARM, "re-enable", start, sampler)
        await self._claim_once(CHK_REARM, "rearm")
        quiet = await self._grade_quiet(CHK_REARM, "rearm", sampler)
        cocotb.log.info(
            "%s: enable 1->0 dropped the output with no pulse; %s; source %d claimed once; %s",
            CHK_REARM,
            second,
            SOURCE,
            quiet,
        )

        sampler.stop = True
        await task
        await RisingEdge(top.clk_smc_i)
        top.tb_cla_clock_stop_en.value = 0
        await self._write(debug_ctrl, {"force_clk_en": 1}, "halt_unmask")
        await self.csr_write("ENABLE0_W10_RESTORE", ENABLE0, saved_enable)
        await self.csr_write("THRESHOLD0_RESTORE", THRESHOLD0, saved_threshold)
        await self.csr_write("PRIORITY321_RESTORE", PRIORITY, saved_prio)
        await self.csr_write("REGION_SIZE_RESTORE", REGION_SIZE, REGION_SIZE_RESET)
