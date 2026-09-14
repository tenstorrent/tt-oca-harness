# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS PyUVM canonical high-density smoke test."""

from __future__ import annotations

import pyuvm
from seq_lib._one_shot import _OneShot
from seq_lib.smc_canonical_smoke_test_seq import smc_canonical_smoke_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_canonical_smoke_test(smc_base_test):
    """Run six-agent observability across the reset recovery matrix."""

    required_evidence = (
        "CHK-CANONICAL-SMOKE",
        "CHK-RESET-WAIT-COLD_PRIMARY_ASSERTED",
        "CHK-RESET-WAIT-COLD_RELEASED",
        "CHK-RESET-WAIT-COOL_PRIMARY_ASSERTED",
        "CHK-RESET-WAIT-COOL_RELEASED",
        "CHK-RESET-WAIT-PG_ASSERTED",
        "CHK-RESET-WAIT-PG_RELEASED",
    )
    min_evidence = 7

    # Seven of this testcase's compares are idle-zero reads: the four AXIL
    # activity bits, the sync/uart IRQ aggregates and I2C `cg_en`. These
    # controls drive the producers of five of them (the efuse-bank and
    # any-master AXIL probes are covered as a side effect of the external-window
    # read), require each probe observed at 1 inside a bounded window and back
    # at 0, and credit the run-scoped liveness ledger the scoreboard consults
    # ([NEGATIVE-NEEDS-POSITIVE-CONTROL]). `tb_axil_dtp_csr_active` is
    # unbackable in this TB (tb_top ties `axil_dtp_csr_resp = '0'`) and the
    # scoreboard books it OBSERVED-ONLY, never as checked evidence.
    probe_positive_controls = (
        "sync_irq",
        "uart_irq_any",
        "gpio_irq_any",
        "i2c_cg_en",
        "axil_external_active",
        "axil_efuse_bank_active",
    )

    async def run_scenario(self) -> None:
        seq = smc_canonical_smoke_test_seq("canonical_smoke_seq")

        async def _mk(sequencer):
            async def dispatch(item):
                await _OneShot(item, "os").start(sequencer)

            return dispatch

        seq.dispatch_reset = await _mk(self.env.reset_agent.sequencer)
        seq.dispatch_i2c = await _mk(self.env.i2c_agent.sequencer)
        seq.dispatch_clk = await _mk(self.env.clk_agent.sequencer)
        seq.dispatch_irq = await _mk(self.env.irq_agent.sequencer)
        seq.dispatch_gpio = await _mk(self.env.gpio_agent.sequencer)
        seq.dispatch_axil = await _mk(self.env.axil_agent.sequencer)
        seq.cfg = self.env.cfg
        await seq.start(self.env.reset_agent.sequencer)
