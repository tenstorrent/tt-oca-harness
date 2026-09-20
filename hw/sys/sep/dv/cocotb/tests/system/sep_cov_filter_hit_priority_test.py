# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Stimulus only. No contract is asserted; a PASS means the path was driven, nothing more.

Coverage stimulus: overlapping inbound-filter windows and the hit index.

``axi_filter_wrap`` builds a per-entry ``read_filter_hit`` / ``write_filter_hit``
vector and resolves it with a leading-zero count, but the suite enables one
entry at a time over one window, so only the low bits of the hit vector and one
value of the resolved index are ever produced.

This test drives two configurations of the same probe address. First it enables
entries cumulatively -- entry 0, then 0 and 1, up to the whole bank -- with
every window covering the probe, so the hit vector fills in from the bottom and
more than one bit is set at once. Then it enables exactly one entry at a time,
so the resolved index steps over the whole bank.

Every configuration keeps the probe allowed for both read and write, so the
beat is never blocked and every window is one the test itself issues into.

no_cpu with a real PROD fuse sense: the inbound filter is active only when
``feat_ctrl.sep_debug`` is 0, and an inactive filter resolves no hit at all.
"""

from __future__ import annotations

import pyuvm
from env.sep_lcc_golden import LC_PROD
from sep_base_test import sep_base_test
from seq_lib.sep_cov_remap_filter_seq import cov_read_seq, cov_write_seq
from seq_lib.sep_inbound_filter_rule_seq import (
    INFILT_N_ENTRIES,
    SepInboundFilter,
    SepInboundFilterCfg,
)
from seq_lib.sep_scratch_reset_seq import SCRATCH_COLD_0

_SIP_DIS = 0x0F0F_0F0F_0F0F_0F0F
_SYS_DIS = 0x00FF_00FF_00FF_00FF
_MAX_SENSE_CYCLES = 20_000

# The probe sits at the base of the cold scratch bank and every window below
# starts there, so each extra entry widens the overlap without moving the beat.
_PROBE = SCRATCH_COLD_0
_GRANULE = 8


@pyuvm.test()
class sep_cov_filter_hit_priority_test(sep_base_test):
    """Stimulus only. No contract is asserted; a PASS means the path was driven, nothing more.

    Drive overlapping allow windows, then one window at a time.
    """

    # Coverage stimulus: this leaf grades nothing, so the own-evidence floor
    # in sep_base_test._finalize_evidence does not apply to it.
    stimulus_only = True

    async def _bring_up_prod(self) -> None:
        image = self.select_efuse_image(
            lc_raw=LC_PROD, fixed={"SIP_DIS": _SIP_DIS, "SYS_DIS": _SYS_DIS}
        )
        self.write_efuse_image(image)
        await self.bring_up_and_wait_fuse_sense(max_cycles=_MAX_SENSE_CYCLES)

    async def _program_entry(self, filt: SepInboundFilter, entry: int) -> None:
        """One allow window from the probe to ``entry`` granules above it.

        Every window contains the probe, so enabling several entries sets
        several hit bits for the same beat. ``allow_burst`` stays clear, so the
        wrap does not widen the window to the whole page and the programmed
        bounds are what the compare sees.
        """
        cell = SepInboundFilterCfg(entry=entry, allow_addr=_PROBE)
        await filt.program_rule(
            cell,
            read_allowed=True,
            write_allowed=True,
            end_addr=_PROBE + _GRANULE * (entry + 1),
        )

    async def run_scenario(self) -> None:
        await self._bring_up_prod()
        filt = SepInboundFilter(self)

        # Cumulative overlap: entries 0..n-1 all cover the probe at once.
        await filt.disable_all()
        for count in range(1, INFILT_N_ENTRIES + 1):
            await self._program_entry(filt, count - 1)
            await self.start_ext_seq(cov_read_seq(_PROBE))
            await self.start_ext_seq(cov_write_seq(_PROBE, 0x0000_1000 | count))
        self.logger.info("cumulative overlap: %d entries enabled together", INFILT_N_ENTRIES)

        # One entry at a time, so the resolved hit index steps over the bank.
        for entry in range(INFILT_N_ENTRIES):
            await filt.disable_all()
            await self._program_entry(filt, entry)
            await self.start_ext_seq(cov_read_seq(_PROBE))
            await self.start_ext_seq(cov_write_seq(_PROBE, 0x0000_2000 | entry))
        self.logger.info("single-entry walk: hit index stepped over %d entries", INFILT_N_ENTRIES)

        await filt.disable_all()
