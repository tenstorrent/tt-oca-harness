# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Stimulus only. No contract is asserted; a PASS means the path was driven, nothing more.

Coverage stimulus: every entry of both axi_filter banks, programmed and driven.

The suite programs one or two filter entries with one window each, so
``traffic_filter.cfg_start_addr_i`` and ``cfg_end_addr_i`` hold their reset
value on almost every instance while the decode itself runs on every beat. This
test writes the whole of both banks -- 16 inbound entries and 32 outbound --
through the address field and the FILTER_CONFIG field combinations, then drives
one allowed and one blocked outbound beat per outbound entry.

The value walk runs with ``entry_enabled`` clear on every entry, so it changes
no access decision anywhere: it moves the configuration inputs and nothing else.
The traffic phase then enables exactly one entry at a time, over a window inside
the outbound target aperture that the test itself issues into. No rule is
randomised, and no window covers the CPU-LSU register path this test drives.

no_cpu, +skip_fuse_sense: both filter CSR banks and the outbound path are
reachable from the CPU-LSU master without a real fuse sense.
"""

from __future__ import annotations

import pyuvm
from sep_base_test import sep_base_test
from seq_lib.sep_cov_remap_filter_seq import (
    OUTBOUND_TARGET_BASE,
    OUTFILT_ENTRIES,
    SepCovFilterBank,
    SepCovOutputRemap,
    cov_read_seq,
    cov_write_seq,
    filter_config_word,
)

# One 8-byte granule per outbound entry inside the target aperture, so entry k
# owns a window no other entry's traffic touches.
_ENTRY_GRANULE = 8


@pyuvm.test()
class sep_cov_filter_rule_bank_sweep_test(sep_base_test):
    """Stimulus only. No contract is asserted; a PASS means the path was driven, nothing more.

    Drive every inbound and outbound filter entry's configuration and window.
    """

    # Coverage stimulus: this leaf grades nothing, so the own-evidence floor
    # in sep_base_test._finalize_evidence does not apply to it.
    stimulus_only = True

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()

        bank = SepCovFilterBank(self)
        remap = SepCovOutputRemap(self)

        # Both banks start with every entry disabled, so nothing below can be
        # decided by a rule left over from bring-up.
        await bank.disable_all(inbound=True)
        await bank.disable_all(inbound=False)

        inbound_writes = await bank.value_walk(inbound=True)
        outbound_writes = await bank.value_walk(inbound=False)
        self.logger.info(
            "filter bank value walk: %d inbound writes, %d outbound writes",
            inbound_writes,
            outbound_writes,
        )

        # AP region 0 carries the outbound traffic: its offset puts the beat at
        # the target aperture the outbound filter windows below describe.
        await remap.set_offset(ap=True, region=0, offset=OUTBOUND_TARGET_BASE)

        for entry in range(OUTFILT_ENTRIES):
            intra = entry * _ENTRY_GRANULE
            access = SepCovOutputRemap.access_addr(ap=True, region=0, intra=intra)
            target = SepCovOutputRemap.remapped_addr(OUTBOUND_TARGET_BASE, intra)

            await bank.disable_all(inbound=False)
            await bank.write_window(inbound=False, entry=entry, start=target, end=target)
            await bank.write_config(
                inbound=False,
                entry=entry,
                word=filter_config_word(entry_enabled=True, src_id=0),
            )
            await self.start_seq(cov_write_seq(access, 0xC0FF_EE00 | entry))
            await self.start_seq(cov_read_seq(access))

            # Same beat with the entry disabled. Every other entry of the bank
            # is disabled too, so the outbound filter blocks by default and the
            # beat completes from its error slave.
            await bank.write_config(inbound=False, entry=entry, word=0)
            mon = getattr(self.env, "axi_monitor", None)
            if mon is not None:
                # Intentional error beats: credit the monitor so an
                # unexpected DECERR elsewhere still fails it.
                mon.arm_expected_decerr(2)
            await self.start_seq(cov_read_seq(access, allow_error=True))
            await self.start_seq(cov_write_seq(access, 0xDEAD_0000 | entry, allow_error=True))

        # Leave the bank inert for whatever runs after this scenario.
        await bank.disable_all(inbound=False)
        self.logger.info(
            "outbound entry traffic: %d entries driven allowed then blocked", OUTFILT_ENTRIES
        )
