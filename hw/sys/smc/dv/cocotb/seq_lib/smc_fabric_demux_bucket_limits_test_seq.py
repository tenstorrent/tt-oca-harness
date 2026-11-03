# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The fabric demultiplexers withhold the same-ID read past their stated bucket limit.

Spec source: fabric.adoc SMC Fabric Transaction Limits (`smc_pkg::FabricMaxTrans` 32 per AXI
ID bucket in the fabric demultiplexers; `smc_local_xbar_pkg::XbarCfg.MaxMstTrans` 8 per manager
of the local AXI4 crossbar).

The vendored `axi_demux` sizes its per-ID-bucket in-flight counter to `clog2(MaxTrans)` bits
and reports the bucket full when the counter is all ones, so the design admits `MaxTrans - 1`
per bucket (31 and 7). This leaf is the reproducer: it grades the stated numbers and is
expected to fail with the measured ones.
"""

from __future__ import annotations

from .smc_addr_map import REGION_SIZE_RESET, smc_addr
from .smc_fabric_limit_probe_utils import read_item
from .smc_fabric_limit_seq_base import SmcFabricLimitSeqBase

FABRIC_MAX_TRANS = 32
LOCAL_XBAR_MAX_MST_TRANS = 8
SAME_ID = 5
# Reads offered past each limit: the limit plus the pipeline registers between the SEP_IN
# port and the limiter, plus one, so the limiter sees a withheld AR behind its bound.
BUCKET_OFFERED = 40
LOCAL_OFFERED = 12
REGION_SIZE_ADDR = smc_addr("SMC_TOP_SMC_BASE_CONFIG_REGION_SIZE_BASE_ADDR")


class smc_fabric_demux_bucket_limits_test_seq(SmcFabricLimitSeqBase):
    """RREADY-held same-ID read groups past the demux bucket limits of 32 and 8.

    Each leg grades its invariants at once: one ID on every AR, an AR withheld at the
    peak, the next AR accepted only after an R-last, every read accepted, and the port
    behind the demux withholding nothing, so the demux's own counter is what withheld. The
    peak against the chapter's number is graded last and the collected failure names it;
    the counter width admits one fewer, so that failure is the expected one.
    """

    PROBES = (
        ("tb_sep_demux", {"with_id": True}),
        ("tb_sep_errslv", {"witness": "tb_sep_errslv_rfifo_full"}),
        ("tb_lxbar_sep", {}),
        ("tb_lxbar_lreg", {}),
    )

    def __init__(self, name: str = "smc_fabric_demux_bucket_limits_test_seq") -> None:
        super().__init__(name)

    async def body(self) -> None:
        await self._setup(seed_spm=False)
        try:
            await self._step_fabric_bucket()
            await self._step_local_manager()
        finally:
            await self._teardown()

    @staticmethod
    def _cfg_reads(label: str, count: int) -> list:
        return [
            read_item(f"{label}_{k}", REGION_SIZE_ADDR, REGION_SIZE_RESET, 8, SAME_ID)
            for k in range(count)
        ]

    async def _step_fabric_bucket(self) -> None:
        token = "CHK-FABRIC-33RD-WAITS-FOR-RETIRE"
        ids = [SAME_ID] * BUCKET_OFFERED
        await self.run_free("bucket_free", self.decerr_reads("BUCKET_FREE", BUCKET_OFFERED, ids))
        free_ar = self.probes["tb_sep_demux"].ar_hs
        run = await self.run_held(
            "bucket_held", self.decerr_reads("BUCKET_HELD", BUCKET_OFFERED, ids), "tb_sep_demux"
        )
        errslv = self.probes["tb_sep_errslv"]
        self.require(
            token, run.ids == [SAME_ID], f"ids seen at the demux {run.ids}, want [{SAME_ID}]"
        )
        self.require(token, run.withheld >= 1, f"no AR withheld at the peak; {run.text()}")
        self.require(
            token,
            run.retire_first(),
            f"the first AR accepted after the release did not follow the first R-last; {run.text()}",
        )
        self.require(
            token,
            run.final_ar_hs == BUCKET_OFFERED,
            f"{run.final_ar_hs} of {BUCKET_OFFERED} ARs accepted",
        )
        self.require(
            token,
            errslv.withheld == 0 and errslv.witness_hits == 0,
            f"the error subordinate behind the demux withheld {errslv.withheld} cycles with its "
            f"read FIFO full on {errslv.witness_hits}, so the stall is not the demux's own",
        )
        self.check(
            token,
            run.peak == FABRIC_MAX_TRANS,
            f"{BUCKET_OFFERED} DECERR reads of the outside-window page on AXI ID {SAME_ID} with "
            f"SEP_IN RREADY held: the SEP region demux admitted {run.peak} on that ID bucket "
            f"(chapter FabricMaxTrans {FABRIC_MAX_TRANS}) and withheld the next AR while its "
            f"error subordinate held {errslv.peak} and withheld nothing; after the release the "
            f"first AR accepted followed the first R-last; {run.text()}; positive control with "
            f"RREADY free: {free_ar} AR handshakes at the demux, all {BUCKET_OFFERED} answered DECERR",
        )

    async def _step_local_manager(self) -> None:
        token = "CHK-LOCAL-XBAR-9TH-WAITS"
        await self.run_free("local_mgr_free", self._cfg_reads("LOCAL_MGR_FREE", LOCAL_OFFERED))
        free_ar = self.probes["tb_lxbar_sep"].ar_hs
        run = await self.run_held(
            "local_mgr_held", self._cfg_reads("LOCAL_MGR_HELD", LOCAL_OFFERED), "tb_lxbar_sep"
        )
        lreg = self.probes["tb_lxbar_lreg"]
        self.require(token, run.withheld >= 1, f"no AR withheld at the peak; {run.text()}")
        self.require(
            token,
            run.retire_first(),
            f"the first AR accepted after the release did not follow the first R-last; {run.text()}",
        )
        self.require(
            token,
            run.final_ar_hs == LOCAL_OFFERED,
            f"{run.final_ar_hs} of {LOCAL_OFFERED} ARs accepted",
        )
        self.require(
            token,
            lreg.withheld == 0,
            f"the internal CSR port behind the demux withheld {lreg.withheld} cycles at its peak "
            f"{lreg.peak}, so the stall is not the demux's own",
        )
        self.check(
            token,
            run.peak == LOCAL_XBAR_MAX_MST_TRANS,
            f"{LOCAL_OFFERED} REGION_SIZE reads on AXI ID {SAME_ID} with SEP_IN RREADY held: the "
            f"local crossbar's SEP_IN demux admitted {run.peak} on that ID bucket (chapter "
            f"MaxMstTrans {LOCAL_XBAR_MAX_MST_TRANS}) and withheld the next AR while the internal "
            f"CSR port behind it held {lreg.peak} and withheld nothing; after the release the first "
            f"AR accepted followed the first R-last; {run.text()}; positive control with RREADY "
            f"free: {free_ar} AR handshakes at the demux, all {LOCAL_OFFERED} answered "
            f"0x{REGION_SIZE_RESET:X}",
        )
