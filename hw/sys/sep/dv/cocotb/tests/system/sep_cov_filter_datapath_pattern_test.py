# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Stimulus only. No contract is asserted; a PASS means the path was driven, nothing more.

Coverage stimulus: AXI payload patterns through and around the inbound filter.

Every existing access on the external master is a single 4-byte beat with
AxID 0 and one data value, so ``axi_in_req_i``, the filter's error-slave copy
``err_slv_req`` and ``axi_filtered_out_req_o`` hold most of their payload bits
at reset. This test sweeps AxID over the full 6-bit external instance width
(``dv/tb/tb_top.sv`` gives the ``m_axi`` master ``ID_WIDTH(6)``), AxLEN over
1, 2, 4, 8 and 16 INCR beats, the ARUSER/AWUSER group-id slice ``user[7:4]``,
the beat offset inside the granted page, and the write payload as a walking one
and a walking zero. Each sweep runs twice: once on an allowed address, so the
pass-through copy of the request moves, and once on a blocked address, so the
error-slave copy moves.

The allow window is one entry over the scratch page, opened with
``allow_burst`` so ``axi_filter_wrap`` widens it to the whole 4 KiB page and the
multi-beat sweeps are inside it. Every other entry is disabled, so a blocked
address is decided by block-by-default and not by a leftover rule.

no_cpu with a real PROD fuse sense: ``feat_ctrl.sep_debug`` must be 0 for the
inbound filter to be active, which is what makes the blocked leg reach the
error slave at all.
"""

from __future__ import annotations

import pyuvm
from env.sep_lcc_golden import LC_PROD
from sep_base_test import sep_base_test
from sep_reg_meta import sym
from seq_lib.sep_cov_remap_filter_seq import (
    cov_read_seq,
    cov_write_seq,
    walking_data,
)
from seq_lib.sep_inbound_filter_rule_seq import (
    SepInboundFilter,
    SepInboundFilterCfg,
)
from seq_lib.sep_scratch_reset_seq import SCRATCH_COLD_0

# Distinct non-zero disable vectors, so the sensed FEAT_CTRL is not all-zero.
_SIP_DIS = 0x0F0F_0F0F_0F0F_0F0F
_SYS_DIS = 0x00FF_00FF_00FF_00FF
_MAX_SENSE_CYCLES = 20_000

# m_axi ID width is 6 (dv/tb/tb_top.sv), so the instance ID range is 0..63.
_EXT_ID_WIDTH = 6
# The cold scratch bank is eight 64-bit registers: 64 bytes of plain RW storage
# inside the granted page, so a 16-beat 4-byte burst from its base stays on
# real registers.
_SCRATCH_BYTES = 64
_BURST_LENGTHS = (4, 8, 16, 32, 64)
# A WDT register one page below the scratch page. It is a real register the
# external master reaches when its own page is granted, so the blocked leg is
# the filter's answer and not an address-decode hole.
_BLOCKED_ADDR = sym("WDT_TIMER_WDOG_BARK_THOLD_REG_ADDR")
# Bounded so the denied burst stays short: the error slave answers every beat.
_BLOCKED_LENGTHS = (4, 8, 16)


@pyuvm.test()
class sep_cov_filter_datapath_pattern_test(sep_base_test):
    """Stimulus only. No contract is asserted; a PASS means the path was driven, nothing more.

    Sweep AxID, AxLEN, user group-id, address offset and write data.
    """

    # Coverage stimulus: this leaf grades nothing, so the own-evidence floor
    # in sep_base_test._finalize_evidence does not apply to it.
    stimulus_only = True

    async def _bring_up_prod(self) -> None:
        """Real-sense a PROD image so the inbound filter is active."""
        image = self.select_efuse_image(
            lc_raw=LC_PROD, fixed={"SIP_DIS": _SIP_DIS, "SYS_DIS": _SYS_DIS}
        )
        self.write_efuse_image(image)
        await self.bring_up_and_wait_fuse_sense(max_cycles=_MAX_SENSE_CYCLES)

    async def _drive(
        self,
        addr: int,
        *,
        length: int = 4,
        axi_id: int = 0,
        user: int = 0,
        data: int = 0,
        blocked: bool = False,
    ) -> None:
        burst = 1 if length > 4 else None  # AxBURST INCR once there is a second beat
        await self.start_ext_seq(
            cov_read_seq(
                addr,
                length=length,
                axi_id=axi_id,
                user=user,
                burst=burst,
                allow_error=blocked,
            )
        )
        await self.start_ext_seq(
            cov_write_seq(
                addr,
                data,
                length=length,
                axi_id=axi_id,
                user=user,
                burst=burst,
                allow_error=blocked,
            )
        )

    async def run_scenario(self) -> None:
        await self._bring_up_prod()

        filt = SepInboundFilter(self)
        await filt.disable_all()
        # allow_burst with START and END in one page: axi_filter_wrap widens the
        # window to the whole page, which is what carries the multi-beat sweeps.
        window = SepInboundFilterCfg(entry=0, allow_addr=SCRATCH_COLD_0)
        await filt.program_rule(
            window,
            read_allowed=True,
            write_allowed=True,
            allow_burst=True,
            end_addr=SCRATCH_COLD_0 + 8,
            expect_page_widen=True,
        )

        # AxID over the full external instance width, with the beat offset
        # stepping through the bank so the low address bits move with it.
        for axi_id in range(1 << _EXT_ID_WIDTH):
            offset = (axi_id * 8) % _SCRATCH_BYTES
            await self._drive(
                SCRATCH_COLD_0 + offset,
                axi_id=axi_id,
                data=walking_data(4, axi_id),
            )

        # AxLEN 0, 1, 3, 7 and 15 INCR, with a walking-one then a walking-zero
        # payload over the whole multi-beat write.
        for length in _BURST_LENGTHS:
            for bit in range(0, length * 8, 7):
                await self._drive(
                    SCRATCH_COLD_0,
                    length=length,
                    data=walking_data(length, bit),
                )
                await self._drive(
                    SCRATCH_COLD_0,
                    length=length,
                    data=walking_data(length, bit, invert=True),
                )

        # The group-id slice of AxUSER. user[3:0] stays 0 so the match-all
        # src_id of the window keeps granting the beat.
        for group in range(16):
            await self._drive(
                SCRATCH_COLD_0 + (group * 4) % _SCRATCH_BYTES,
                user=group << 4,
                data=walking_data(4, group),
            )

        # The same payload sweep on a blocked address, so the error-slave copy
        # of the request carries the ID, the length and the data too.
        for axi_id in range(1 << _EXT_ID_WIDTH):
            await self._drive(
                _BLOCKED_ADDR,
                axi_id=axi_id,
                data=walking_data(4, axi_id, invert=True),
                blocked=True,
            )
        for length in _BLOCKED_LENGTHS:
            for bit in range(0, length * 8, 11):
                await self._drive(
                    _BLOCKED_ADDR,
                    length=length,
                    data=walking_data(length, bit),
                    blocked=True,
                )
        for group in range(16):
            await self._drive(
                _BLOCKED_ADDR, user=group << 4, data=walking_data(4, group), blocked=True
            )

        await filt.disable_all()
        self.logger.info(
            "filter payload sweep: ids 0..%d, lengths %s allowed / %s blocked",
            (1 << _EXT_ID_WIDTH) - 1,
            _BURST_LENGTHS,
            _BLOCKED_LENGTHS,
        )
