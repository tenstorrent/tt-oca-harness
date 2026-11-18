# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The CLA debug interrupt is PLIC source 322, and the clock-stop source 321 stays idle.

`dfd.adoc` Interrupts lists the two CLA-driven sources, CLA clock stop and CLA
debug interrupt; `interrupts.adoc` places them on raw vector bits 320 and 321
and maps raw bits 0 to 327 onto PLIC IDs 1 to 328, so the clock stop is PLIC
source 321 and the debug interrupt PLIC source 322. `dfd.adoc` Actions and
Cross-Triggering makes the debug interrupt "an ordinary maskable PLIC source".
The bench ties `tdr_dbg_ctrl_clock_stop_en_i` low, so source 321 can only ever
read 0 here.

The debug-interrupt action code is measured as `smc_dfd_cla_action_seq_utils`
measures it: `Action0` of node 0 pair 0 is walked under an activating relation
until `tb_cla_interrupt` rises. `tb_plic_pending_321` and `tb_plic_pending_322`
are sampled on every `clk_smc_i` rise from before the arm to after the rise:
source 322 is 0 on every sample before the line rises and 1 within four polls
after it, and source 321 is 0 on every sample. The release of the line is the
subject of `smc_dfd_cla_irq_w2c_release_test` and is not graded here.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge

from .smc_dfd_cla_action_seq_utils import SAMPLE_CYCLES, SmcDfdClaActionSeq

CHK = "CHK-CLA-IRQ-PLIC-322"
_PENDING_POLLS = 4
_SOURCES = ("tb_plic_pending_321", "tb_plic_pending_322", "tb_cla_interrupt")


class _Sampler:
    """Per clk_smc_i rise, the two CLA PLIC pending bits and the interrupt line."""

    def __init__(self) -> None:
        self.samples: dict[str, list[int]] = {name: [] for name in _SOURCES}
        self.stop = False

    async def run(self) -> None:
        top = cocotb.top
        while not self.stop:
            await RisingEdge(top.clk_smc_i)
            await ReadOnly()
            for name in _SOURCES:
                value = getattr(top, name).value
                assert value.is_resolvable, f"{name} is X/Z ({value})"
                self.samples[name].append(int(value))


class smc_dfd_cla_irq_plic_source_test_seq(SmcDfdClaActionSeq):
    """Fire the debug-interrupt action and grade the PLIC pending bits 321 and 322."""

    def __init__(self, name: str = "smc_dfd_cla_irq_plic_source_test_seq") -> None:
        super().__init__(name)
        self.action = -1
        self.pending_polls = -1
        self.sample_count = 0

    async def body(self) -> None:
        await self.wait_fuse_sense_done()
        sampler = _Sampler()
        task = cocotb.start_soon(sampler.run())
        await self._write(self._eap(), {}, "reset")
        await self._write_ctrl(1, 1, 1, "arm")
        self.action, _activating, _quiet = await self._discover("tb_cla_interrupt", "plic")
        pending = -1
        for poll in range(_PENDING_POLLS):
            pending = self._pin("tb_plic_pending_322")
            if pending == 1:
                self.pending_polls = poll + 1
                break
            await ClockCycles(cocotb.top.clk_smc_i, SAMPLE_CYCLES)
        await RisingEdge(cocotb.top.clk_smc_i)
        sampler.stop = True
        await task

        irq = sampler.samples["tb_cla_interrupt"]
        p322 = sampler.samples["tb_plic_pending_322"]
        p321 = sampler.samples["tb_plic_pending_321"]
        self.sample_count = len(irq)
        assert 1 in irq, f"{CHK} FAIL: tb_cla_interrupt never read 1 in {len(irq)} samples"
        first_irq = irq.index(1)
        assert pending == 1, (
            f"{CHK} FAIL: tb_plic_pending_322 still 0 after {_PENDING_POLLS} polls with "
            f"tb_cla_interrupt 1 since sample {first_irq} (Action0 {self.action})"
        )
        assert not any(p322[:first_irq]), (
            f"{CHK} FAIL: tb_plic_pending_322 set at sample {p322.index(1)}, before "
            f"tb_cla_interrupt first rose at sample {first_irq}"
        )
        assert not any(p321), (
            f"{CHK} FAIL: tb_plic_pending_321 set at sample {p321.index(1)} of {len(p321)} with "
            f"tdr_dbg_ctrl_clock_stop_en_i tied low; the debug interrupt is source 322"
        )
        cocotb.log.info(
            "%s: Action0 %d of node 0 pair 0 raised tb_cla_interrupt at sample %d of %d; "
            "tb_plic_pending_322 was 0 on every sample before that and read 1 within %d of "
            "%d polls after it; tb_plic_pending_321 was 0 on all %d samples",
            CHK,
            self.action,
            first_irq,
            self.sample_count,
            self.pending_polls,
            _PENDING_POLLS,
            len(p321),
        )
