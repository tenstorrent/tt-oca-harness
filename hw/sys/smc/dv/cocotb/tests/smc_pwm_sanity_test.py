# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smc_pwm_sanity_test: the SMC PWM from its registers to the waveform on GPIO pads 59-62.

Each pad is observed as (lsio select, core2pad_en, core2pad) on the bench top. The seed
draws the PWM configurations the waveform checks grade. Tokens, in the order the
sequence must emit them:
  CHK-PWM-RESET        every PWM register reads its generated reset word.
  CHK-PWM-PAD-RESET    PAD_EN reads 0 and pads 59-62 are neither selected nor driven.
  CHK-PWM-RW           CFG, PWM_EN, INVERT and each channel's PWM_PARAM, DUTY_CYCLE and
                       BLINK_PARAM hold distinct writable-bit patterns written before any
                       is read back, then the same patterns with every writable bit flipped.
  CHK-PWM-STROBE       a single-lane (wstrb=0b0001) write to PWM_PARAM_0 answers SLVERR
                       and leaves the register unchanged.
  CHK-PWM-PAST-END     a read of the first word past the decoded extent answers DECERR
                       with the memory map's past-extent read data.
  CHK-PWM-PAD-SW       with PAD_EN=0, software GPIO drives pad 60 to 1, then 0, then
                       releases it.
  CHK-PWM-PAD-CLAIM    with PAD_EN and PWM_EN set on every channel, each of pads 59-62
                       switches to the PWM (select 1) and drives out (core2pad_en 1), and
                       its GPIO DATA_CTRL.lsio_enable status bit reads 1.
  CHK-PWM-PAD-WAVE     for each of 8 seeded configurations of CLK_DIV, DC_RESN and each
                       channel's DUTY_CYCLE.A, PHASE_DELAY and INVERT, every pad's period,
                       active time and leading-edge offset from pad 59 match the settings
                       to the clock, over 4 periods.
  CHK-PWM-PAD-IDLE     with PWM_EN[0] clear and PAD_EN[0] set, pad 59 holds 0 for a period,
                       then 1 for a period once INVERT[0] is set; with PWM_EN[0] set again
                       every pad matches the configuration.
  CHK-PWM-PAD-VETO     DATA_CTRL.lsio_disable on pad 61 makes the pad follow its GPIO
                       registers and clears lsio_enable; clearing the veto restores the
                       configured waveform.
  CHK-PWM-REGWEN       with REGWEN cleared, writes to CFG, PWM_EN, INVERT and the last
                       DUTY_CYCLE leave their running values, REGWEN stays 0, and every
                       pad still matches the configuration.
  CHK-PWM-PAD-RELEASE  clearing PAD_EN with PWM_EN still set deselects and stops driving
                       all four pads.
  CHK-PAD-MOVED        pad 64 (Cool Reset Out) is selected, drives 0 and is output-enabled
                       while cool reset is asserted; pad 63 (Cool Reset In) is not selected.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_pwm_sanity_test_seq import CHK_ORDER, smc_pwm_sanity_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_pwm_sanity_test(smc_base_test):
    """Program the PWM over SEP_IN and grade its waveforms on GPIO pads 59-62."""

    required_evidence = tuple(sorted(CHK_ORDER))
    min_evidence = len(CHK_ORDER)

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_pwm_sanity_test_seq("pwm_sanity_seq", seed=self.random_seed())
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        missing = set(CHK_ORDER) - set(seq.chk_seen)
        assert not missing, f"missing CHK tokens {sorted(missing)} (seen={seq.chk_seen})"
