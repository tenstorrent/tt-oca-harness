# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The FIFO-bounded fabric limits withhold the read past their stated number.

Spec source: fabric.adoc SMC Fabric Transaction Limits (`smc_pkg::ErrSlvMaxTrans` 32 across all
IDs for each error subordinate; `smc_internal_axi_lite_xbar_pkg::XbarCfg.MaxMstTrans` 4 for
each manager of the local fabric AXI4-Lite crossbar).
"""

from __future__ import annotations

from .smc_addr_map import REGION_SIZE_RESET, smc_addr
from .smc_fabric_limit_probe_utils import read_item
from .smc_fabric_limit_seq_base import SmcFabricLimitSeqBase
from .smc_output_fabric_vip_utils import INBOUND0_FILTER_CONFIG, PASS_ALL_CONFIG

ERR_SLV_MAX_TRANS = 32
AXIL_MAX_MST_TRANS = 4
# Reads offered past each limit: the limit plus the pipeline registers between the SEP_IN
# port and the limiter, plus one, so the limiter sees a withheld AR behind its bound. The
# AXI-Lite leg uses distinct IDs so no per-ID bucket upstream caps it first.
ERRSLV_OFFERED = 40
AXIL_OFFERED = 24
REGION_SIZE_ADDR = smc_addr("SMC_TOP_SMC_BASE_CONFIG_REGION_SIZE_BASE_ADDR")


class smc_fabric_errslv_axil_limits_test_seq(SmcFabricLimitSeqBase):
    """RREADY-held read groups past the error subordinate and AXI-Lite crossbar limits."""

    PROBES = (
        ("tb_sep_errslv", {"witness": "tb_sep_errslv_rfifo_full"}),
        ("tb_lite_demux", {"rsp": ("rvalid", "rready"), "witness": "tb_lite_demux_rfifo_full"}),
        ("tb_lite_cfg", {"rsp": ("rvalid", "rready")}),
    )

    def __init__(self, name: str = "smc_fabric_errslv_axil_limits_test_seq") -> None:
        super().__init__(name)

    async def body(self) -> None:
        await self._setup(seed_spm=False)
        try:
            await self._step_errslv()
            await self._step_axil_manager()
        finally:
            await self._teardown()

    async def _step_errslv(self) -> None:
        ids = list(range(ERRSLV_OFFERED))
        await self.run_free("errslv_free", self.decerr_reads("ERRSLV_FREE", ERRSLV_OFFERED, ids))
        free_ar = self.probes["tb_sep_errslv"].ar_hs
        run = await self.run_held(
            "errslv_held", self.decerr_reads("ERRSLV_HELD", ERRSLV_OFFERED, ids), "tb_sep_errslv"
        )
        self.check(
            "CHK-ERRSLV-33RD-WAITS-FOR-RETIRE",
            run.peak == ERR_SLV_MAX_TRANS
            and run.withheld >= 1
            and run.witness_hits == run.withheld
            and run.retire_first()
            and run.final_ar_hs == ERRSLV_OFFERED,
            f"{ERRSLV_OFFERED} DECERR reads of the outside-window page on {ERRSLV_OFFERED} "
            f"distinct AXI IDs with SEP_IN RREADY held: the SEP region error subordinate "
            f"admitted exactly {run.peak} (ErrSlvMaxTrans {ERR_SLV_MAX_TRANS}) and withheld the "
            f"next AR with its read FIFO full; after the release the first AR accepted "
            f"followed the first R-last; {run.text()}; positive control with RREADY free: "
            f"{free_ar} AR handshakes at the error subordinate, all {ERRSLV_OFFERED} answered "
            f"DECERR",
        )

    def _cfg_reads(self, label: str, count: int, alternate: bool) -> list:
        """`count` 8-byte reads on distinct IDs of SMC_BASE_CONFIG REGION_SIZE, or alternating
        with the inbound filter entry 0 configuration (another AXI-Lite subordinate)."""
        items = []
        for k in range(count):
            if alternate and k % 2:
                items.append(
                    read_item(f"{label}_INB0_{k}", INBOUND0_FILTER_CONFIG, PASS_ALL_CONFIG, 8, k)
                )
            else:
                items.append(
                    read_item(f"{label}_RS_{k}", REGION_SIZE_ADDR, REGION_SIZE_RESET, 8, k)
                )
        return items

    async def _step_axil_manager(self) -> None:
        await self.run_free("axil_mgr_free", self._cfg_reads("AXIL_MGR_FREE", AXIL_OFFERED, True))
        free_ar = self.probes["tb_lite_demux"].ar_hs
        run = await self.run_held(
            "axil_mgr_held", self._cfg_reads("AXIL_MGR_HELD", AXIL_OFFERED, True), "tb_lite_demux"
        )
        cfg_peak = self.probes["tb_lite_cfg"].peak
        self.check(
            "CHK-AXIL-XBAR-5TH-WAITS",
            run.peak == AXIL_MAX_MST_TRANS
            and run.withheld >= 1
            and run.witness_hits == run.withheld
            and run.retire_first()
            and run.final_ar_hs == AXIL_OFFERED,
            f"{AXIL_OFFERED} reads on distinct AXI IDs alternating REGION_SIZE and inbound "
            f"filter entry 0 configuration with SEP_IN RREADY held: the internal CSR crossbar's "
            f"manager port demux admitted exactly {run.peak} (MaxMstTrans {AXIL_MAX_MST_TRANS}) "
            f"and withheld the next AR with its read FIFO full, the SMC_BASE_CONFIG subordinate "
            f"port holding at most {cfg_peak} (the crossbar has one manager, so this demux is "
            f"the only read bound a subordinate port sees); after the release the first AR "
            f"accepted "
            f"followed the first R; {run.text()}; positive control with RREADY free: {free_ar} "
            f"AR handshakes at the demux, all {AXIL_OFFERED} answered their reset word",
        )
