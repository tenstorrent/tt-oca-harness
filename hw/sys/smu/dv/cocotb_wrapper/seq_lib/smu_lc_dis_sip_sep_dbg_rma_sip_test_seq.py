# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""In RMA_SIP a SIP_DIS SEP_DBG bit closes the Case 3 debug paths and no other.

Spec: hw/sys/sep/doc/lifecycle_controller.adoc ("Disable vector bit table", "Per-LC-state
feature control profile", "DTP access cases", "DTP path feature gates"),
hw/sys/sep/regs/blocks/sep_efuse_map/sep_efuse_map.rdl (SIP_DIS), hw/sys/dtp/doc/jtag.adoc
(SMC fabric bridge), hw/ip/jtag/jtag_stap/doc/architecture.adoc (disabled STAP) and
hw/ip/jtag/jtag_intf_unit/doc/architecture.adoc (iJTAG SIBs).

The RMA_SIP eFuse shadow image named by ``+sep_shadow_reg_preload`` sets SIP_DIS bit 0 only and
is the only stimulus besides the JTAG accesses. The steps run in this order:

S1, setup: the image is the leaf's own and ``sep_fuse_sense_done_o`` rises within its bound.
S2, feature control: ``lcc_feat_ctrl_o`` has bit 0 clear and every other bit set.
S3, Case 1 control: the I/O STAP host TMS follows the PTAP TMS and the DFD SIB opens with its
    bench cell in the loop.
S4, Case 2 control: the SMC debug STAP host TMS follows the PTAP TMS and an SMC fabric
    SINGLE_OP read and write launch AR, AW and B.
S5, SEP debug STAP: host TMS parked, TDO enable low, 3DCR Select captured 0.
S6, DFT secure SIB: captures 0 and the DR stays 3 bits long.
Every bounded wait reports its bound, the cycles it used and the last observed state.
"""

from __future__ import annotations

from cocotb.triggers import RisingEdge

from seq_lib.smu_lc_dis_sys_chiplet_dbg_test_dev_test_seq import (
    IJTAG_CONTROL_SCAN_BITS,
    SIB_OPEN_CAPTURED,
    STAP_NAMES,
    smu_lc_dis_sys_chiplet_dbg_test_dev_test_seq,
)
from seq_lib.smu_lc_export_seq import (
    FEAT_CTRL_ALL_ENABLED,
    FEAT_CTRL_RESET,
    LANE_ENABLED,
    LAUNCHED_AR_AW_B,
    STAP_SCANS,
    ExportSpec,
)

IMAGE = "sep_efuse_shadow_lc_rma_sip_0_sip_dis_sep_dbg.preload"

#: hw/sys/sep/doc/lifecycle_controller.adoc, "Disable vector bit table": SIP_DIS bit 0 is
#: SEP_DBG; the image holds the 64-bit vector 64'h1
#: (hw/sys/sep/regs/blocks/sep_efuse_map/sep_efuse_map.rdl, SIP_DIS).
SIP_DIS_VECTOR = 1 << 0
#: Same chapter, "Per-LC-state feature control profile": RMA_SIP applies ~SIP_DIS per group, so a
#: set SIP_DIS bit clears exactly its feature-control bit and the SYS_DIS vector of 0 clears none.
FEAT_CTRL_RMA_SIP_SEP_DBG_CLOSED = FEAT_CTRL_ALL_ENABLED & ~SIP_DIS_VECTOR

SPEC = ExportSpec(
    state="RMA_SIP_0",
    tag="SIP-DIS-SEP-DBG-RMA-SIP",
    image=IMAGE,
    feat_ctrl=FEAT_CTRL_RMA_SIP_SEP_DBG_CLOSED,
    lane=LANE_ENABLED,
)


class smu_lc_dis_sip_sep_dbg_rma_sip_test_seq(smu_lc_dis_sys_chiplet_dbg_test_dev_test_seq):
    """RMA_SIP with SIP_DIS SEP_DBG: the Case 1 and Case 2 paths open, the Case 3 paths shut."""

    def __init__(self, test) -> None:
        super().__init__(test)
        self.spec = SPEC

    async def run(self) -> None:
        await self._mark(
            "SETUP: RMA_SIP image with SIP_DIS SEP_DBG, wait for sep_fuse_sense_done_o"
        )
        await self._setup()

        await self._mark("sample lcc_feat_ctrl_o")
        await RisingEdge(self.dut.clk_smu_i)
        word = self._rd("lcc_feat_ctrl_o")
        done = self._rd("sep_fuse_sense_done_o")
        self._check(
            "CHK-LC-FEATCTRL-SIP-DIS-SEP-DBG-RMA-SIP",
            f"lcc_feat_ctrl_o=0x{word:016x} want=0x{FEAT_CTRL_RMA_SIP_SEP_DBG_CLOSED:016x} "
            f"reset=0x{FEAT_CTRL_RESET:016x} sense_done={done}",
            (word, done, word != FEAT_CTRL_RESET),
            (FEAT_CTRL_RMA_SIP_SEP_DBG_CLOSED, 1, True),
        )

        await self._mark("CASE 1 CONTROL: I/O STAP follows the PTAP TMS, the DFD SIB opens")
        io_obs = await self._stap_follow("io")
        follows = self._follows(io_obs)
        dfd_bit, open_ok, cap_ok, dfd_selects, other_selects = await self._dfd_control()
        self._check(
            "CHK-LC-CASE1-CONTROL-SIP-DIS-RMA-SIP",
            f"I/O STAP host_edges={io_obs['sep_edges']} ptap_edges={io_obs['ptap_edges']} "
            f"oen_highs={io_obs['oen_highs']} levels={sorted(io_obs['levels'])}; DFD SIB "
            f"capture={dfd_bit} open_scan_ok={int(open_ok)} capture_scan_ok={int(cap_ok)} "
            f"dfd_selects={dfd_selects} other_selects={other_selects}",
            (
                follows,
                io_obs["sep_edges"] > 0,
                dfd_bit,
                open_ok,
                cap_ok,
                dfd_selects >= IJTAG_CONTROL_SCAN_BITS,
                other_selects,
            ),
            ((True, True, True, True), True, SIB_OPEN_CAPTURED, True, True, True, 0),
        )

        await self._mark("CASE 2 CONTROL: SMC debug STAP follows the PTAP TMS, the fabric launches")
        smc_obs = await self._stap_follow("smc")
        smc_follows = self._follows(smc_obs)
        await self._tlr()
        start, end, delta = await self._fabric_deltas(launches=True)
        self._check(
            "CHK-LC-CASE2-CONTROL-SIP-DIS-RMA-SIP",
            f"{STAP_NAMES['smc']} STAP host_edges={smc_obs['sep_edges']} "
            f"ptap_edges={smc_obs['ptap_edges']} oen_highs={smc_obs['oen_highs']} "
            f"levels={sorted(smc_obs['levels'])}; AR/AW/B deltas={delta} counts {start}->{end}",
            (smc_follows, smc_obs["sep_edges"] > 0, delta),
            ((True, True, True, True), True, LAUNCHED_AR_AW_B),
        )

        await self._mark("SEP debug STAP select write while the PTAP TMS toggles")
        self._check_parked(
            "CHK-LC-CASE3-CLOSED-SEP-STAP-RMA-SIP",
            STAP_NAMES["sep"],
            await self._stap_parked_probe(),
        )

        await self._mark("SELECT_IJTAG: shift 1 into the DFT secure SIB, then capture")
        await self._tlr()
        await self._sib_closed_leg("dft_secure", "CHK-LC-CASE3-CLOSED-SECURE-SIB-RMA-SIP")

        labels = [
            "sense_done",
            "stap_window_io",
            "ijtag_window_control_1",
            "ijtag_window_control_2",
            "stap_window_smc",
            "fabric_ar",
            "fabric_b",
            *[f"stap_window_{i}" for i in range(1, STAP_SCANS + 1)],
            "ijtag_window_dft_secure_1",
            "ijtag_window_dft_secure_2",
        ]
        await self._finish(sorted(labels))
