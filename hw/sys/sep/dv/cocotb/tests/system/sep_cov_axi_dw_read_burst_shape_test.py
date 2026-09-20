# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Read-path burst shapes into the 64-to-32 crypto downsizers."""

from __future__ import annotations

import pyuvm
from env.sep_axi_agent import SepAxiOp
from sep_base_test import sep_base_test
from seq_lib.sep_cov_axi_burst_seq import (
    BURST_FIXED,
    BURST_INCR,
    BURST_WRAP,
    SIZE_8B,
    SepCovAxiStim,
    incr_bytes,
)

# The two crypto endpoints the read shapes are aimed through. Both sit behind
# one `axi_dw_downsizer` each in `sep_crypto_axi_interconnect.sv:236-266`
# (64-bit AXI in, 32-bit AXI-Lite out), which is the logic being driven; the
# endpoint itself is only what terminates the burst.
# Addresses: hw/sys/sep/regs/gen/sv/sep_addrmap_pkg.sv
# (OCH_SEP_TOP_OTBN_DMEM_BASE_ADDR, OCH_SEP_TOP_HMAC_BASE_ADDR).
TARGETS = (("otbn_dmem", 0x1090_8000), ("hmac", 0x1091_1000))

# 129 beats of 8 bytes. conv_ratio=2 makes the master-side burst 257 beats,
# above the 255 AXI4 maximum, which is the entry condition for
# R_SPLIT_INCR_DOWNSIZE. 1032 bytes from an 8-byte-aligned page start stays
# inside one 4 KB page, so the master issues it as a single AR.
SPLIT_BEATS = 129
SPLIT_BYTES = incr_bytes(SPLIT_BEATS)

# WRAP needs a burst-length power of two and an address aligned to the total
# transfer size: 4 beats x 8 bytes = 32 bytes.
WRAP_BEATS = 4
WRAP_BYTES = incr_bytes(WRAP_BEATS)
WRAP_OFFSET = 0x40

FIXED_BEATS = 4
FIXED_BYTES = incr_bytes(FIXED_BEATS)


@pyuvm.test()
class sep_cov_axi_dw_read_burst_shape_test(sep_base_test):
    """Stimulus only. No contract is asserted; a PASS means the path was driven,
    nothing more.

    Read burst shapes through the crypto `axi_dw_downsizer` instances: the
    over-255-beat INCR split, single-beat and multi-beat FIXED, and WRAP. The
    suite drives single-beat INCR everywhere else, so the downsizer's FIXED,
    WRAP and split-continuation arms are never entered.

    The stimulus runs on the SMN inbound master, which reaches `sep_crypto`
    through slave port 4 of `sep_local_axi_xbar`. Response codes are logged,
    not graded: what a crypto endpoint answers to a shape it never sees in
    normal traffic is not this leaf's subject.
    """

    # Coverage stimulus: this leaf grades nothing, so the own-evidence floor
    # in sep_base_test._finalize_evidence does not apply to it.
    stimulus_only = True

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        stim = SepCovAxiStim(self)
        await stim.open_windows()

        for name, base in TARGETS:
            await stim.burst(
                f"{name}_incr_split",
                op=SepAxiOp.READ,
                addr=base,
                length=SPLIT_BYTES,
                size=SIZE_8B,
                burst=BURST_INCR,
            )
            await stim.settle()
            await stim.burst(
                f"{name}_fixed_1beat",
                op=SepAxiOp.READ,
                addr=base,
                length=1 << SIZE_8B,
                size=SIZE_8B,
                burst=BURST_FIXED,
            )
            await stim.settle()
            await stim.burst(
                f"{name}_fixed_4beat",
                op=SepAxiOp.READ,
                addr=base,
                length=FIXED_BYTES,
                size=SIZE_8B,
                burst=BURST_FIXED,
            )
            await stim.settle()
            await stim.burst(
                f"{name}_wrap_4beat",
                op=SepAxiOp.READ,
                addr=base + WRAP_OFFSET,
                length=WRAP_BYTES,
                size=SIZE_8B,
                burst=BURST_WRAP,
            )
            await stim.settle()

        stim.record(
            "COV-AXI-DW-READ-SHAPE",
            "INCR split, FIXED single, FIXED multi-beat and WRAP reads at "
            f"AxSIZE=3 on {len(TARGETS)} crypto downsizer targets",
        )
