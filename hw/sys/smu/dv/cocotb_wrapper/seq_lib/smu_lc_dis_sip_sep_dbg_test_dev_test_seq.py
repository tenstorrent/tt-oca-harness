# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""In TEST_DEV a SIP_DIS SEP_DBG bit closes the Case 3 debug paths and no other.

Spec: hw/sys/sep/doc/lifecycle_controller.adoc ("Disable vector bit table", "Per-LC-state
feature control profile", "DTP access cases", "DTP path feature gates"),
hw/sys/sep/regs/blocks/sep_efuse_map/sep_efuse_map.rdl (SIP_DIS), hw/sys/dtp/doc/jtag.adoc
(SMC fabric bridge), hw/ip/jtag/jtag_stap/doc/architecture.adoc (disabled STAP) and
hw/ip/jtag/jtag_intf_unit/doc/architecture.adoc (iJTAG SIBs).

The TEST_DEV eFuse shadow image named by ``+sep_shadow_reg_preload`` sets SIP_DIS bit 0 only and
is the only stimulus besides the JTAG accesses. The steps run in this order:

S1, setup: the image is the leaf's own and ``sep_fuse_sense_done_o`` rises within its bound.
S2, feature control: ``lcc_feat_ctrl_o`` has bit 0 clear and every other bit set.
S3, fabric: an SMC fabric SINGLE_OP read and write launch AR, AW and B.
S4, SMC debug STAP: selected over the PTAP, its host TMS follows the PTAP TMS.
S5, extra STAP: the same.
S6, DFT non-secure SIB: opens, captures 1 and its bench cell joins the loop.
S7, Case 1 control: the I/O STAP host TMS follows the PTAP TMS and the DFD SIB opens with its
    bench cell in the loop.
S8, SEP debug STAP: host TMS parked, TDO enable low, 3DCR Select captured 0.
S9, DFT secure SIB: captures 0 and the DR stays 3 bits long.
Every bounded wait reports its bound, the cycles it used and the last observed state.
"""

from __future__ import annotations

from cocotb.triggers import RisingEdge

from seq_lib.smu_dtp_scan_chain_boundary_seq import ijtag_chain, ijtag_shift, ijtag_word
from seq_lib.smu_lc_dis_sys_chiplet_dbg_test_dev_test_seq import (
    IJTAG_CONTROL_FLUSH_CAPTURE,
    IJTAG_CONTROL_FLUSH_OPEN,
    IJTAG_CONTROL_SCAN_BITS,
    SIB_OPEN_CAPTURED,
    STAP_NAMES,
    smu_lc_dis_sys_chiplet_dbg_test_dev_test_seq,
)
from seq_lib.smu_lc_export_seq import (
    FEAT_CTRL_ALL_ENABLED,
    FEAT_CTRL_RESET,
    IJTAG_DR_BIT,
    LANE_ENABLED,
    LAUNCHED_AR_AW_B,
    STAP_SCANS,
    ExportSpec,
)

IMAGE = "sep_efuse_shadow_lc_test_dev_sip_dis_sep_dbg.preload"

#: hw/sys/sep/doc/lifecycle_controller.adoc, "Disable vector bit table": SIP_DIS bit 0 is
#: SEP_DBG; the image holds the 64-bit vector 64'h1 (hw/sys/sep/regs/blocks/sep_efuse_map/
#: sep_efuse_map.rdl, SIP_DIS).
SIP_DIS_VECTOR = 1 << 0
#: Same chapter, "Per-LC-state feature control profile": TEST_DEV enables every term and the
#: disable vectors are ORed and inverted, so a set SIP_DIS bit clears exactly its feature-control bit.
FEAT_CTRL_SEP_DBG_CLOSED = FEAT_CTRL_ALL_ENABLED & ~SIP_DIS_VECTOR

SPEC = ExportSpec(
    state="TEST_DEV",
    tag="SIP-DIS-SEP-DBG",
    image=IMAGE,
    feat_ctrl=FEAT_CTRL_SEP_DBG_CLOSED,
    lane=LANE_ENABLED,
)

#: hw/ip/jtag/jtag_intf_unit/doc/architecture.adoc, "iJTAG Network": with the DFT non-secure SIB
#: open the DR is the three SIB bits and the DFT bench cell.
DFT_ONLY = frozenset({"dft"})

OPEN_STAPS = ("smc", "extra0")
OPEN_STAP_CHECKS = {
    "smc": "CHK-LC-STAP-SMC-OPEN-SIP-DIS-SEP-DBG",
    "extra0": "CHK-LC-STAP-EXTRA-OPEN-SIP-DIS-SEP-DBG",
}


class smu_lc_dis_sip_sep_dbg_test_dev_test_seq(smu_lc_dis_sys_chiplet_dbg_test_dev_test_seq):
    """TEST_DEV with SIP_DIS SEP_DBG: the Case 1 and Case 2 paths open, the Case 3 paths shut."""

    def __init__(self, test) -> None:
        super().__init__(test)
        self.spec = SPEC

    async def _dft_open(self) -> tuple[int, bool, bool, int, int]:
        """Open the DFT non-secure SIB, then capture and close it: (DFT capture, open scan matches
        its model, capture scan matches its model, DFT host selects, other host selects)."""
        await self._tlr()
        await self._ijtag_select()
        closed = frozenset()
        bits = IJTAG_CONTROL_SCAN_BITS
        open_word = ijtag_word(closed, DFT_ONLY, IJTAG_CONTROL_FLUSH_OPEN, bits)
        cap_word = ijtag_word(DFT_ONLY, closed, IJTAG_CONTROL_FLUSH_CAPTURE, bits)
        want_open = ijtag_shift(closed, open_word, bits)[0]
        want_cap = ijtag_shift(DFT_ONLY, cap_word, bits)[0]
        got_open, _ = await self._ijtag_scan(open_word, "dft_open_1", bits)
        got_cap, counts = await self._ijtag_scan(cap_word, "dft_open_2", bits)
        chain = ijtag_chain(DFT_ONLY)
        dft_bit = (got_cap >> (len(chain) - 1 - chain.index(("sib", "dft")))) & 1
        other = sum(counts[name] for name in IJTAG_DR_BIT if name != "dft")
        self._log(
            f"CELL ijtag_dft_open open out=0x{got_open:x} want=0x{want_open:x} "
            f"capture out=0x{got_cap:x} want=0x{want_cap:x} chain_cells={len(chain)}"
        )
        return dft_bit, got_open == want_open, got_cap == want_cap, counts["dft"], other

    async def run(self) -> None:
        await self._mark(
            "SETUP: TEST_DEV image with SIP_DIS SEP_DBG, wait for sep_fuse_sense_done_o"
        )
        await self._setup()

        await self._mark("sample lcc_feat_ctrl_o")
        await RisingEdge(self.dut.clk_smu_i)
        word = self._rd("lcc_feat_ctrl_o")
        done = self._rd("sep_fuse_sense_done_o")
        self._check(
            "CHK-LC-FEATCTRL-SIP-DIS-SEP-DBG-TEST-DEV",
            f"lcc_feat_ctrl_o=0x{word:016x} want=0x{FEAT_CTRL_SEP_DBG_CLOSED:016x} "
            f"reset=0x{FEAT_CTRL_RESET:016x} sense_done={done}",
            (word, done, word != FEAT_CTRL_RESET),
            (FEAT_CTRL_SEP_DBG_CLOSED, 1, True),
        )

        await self._mark("SMC fabric SINGLE_OP read then write, DTP-to-SMC AR/AW/B counters")
        await self._tlr()
        lane_before = self._rd("lcc_dbg_disable_smc_jtag2axi_o")
        start, end, delta = await self._fabric_deltas(launches=True)
        lane_after = self._rd("lcc_dbg_disable_smc_jtag2axi_o")
        self._check(
            "CHK-LC-FABRIC-LAUNCH-SIP-DIS-SEP-DBG-TEST-DEV",
            f"AR/AW/B deltas={delta} counts {start}->{end} lane before={lane_before} "
            f"after={lane_after} want_lane={LANE_ENABLED}",
            (delta, lane_before, lane_after),
            (LAUNCHED_AR_AW_B, LANE_ENABLED, LANE_ENABLED),
        )

        for name in OPEN_STAPS:
            await self._mark(
                f"{STAP_NAMES[name]} STAP selected over the PTAP while the PTAP TMS toggles"
            )
            obs = await self._stap_follow(name)
            follows = self._follows(obs)
            self._check(
                OPEN_STAP_CHECKS[name],
                f"{STAP_NAMES[name]} STAP host_edges={obs['sep_edges']} "
                f"ptap_edges={obs['ptap_edges']} oen_highs={obs['oen_highs']} "
                f"levels={sorted(obs['levels'])}",
                (follows, obs["sep_edges"] > 0),
                ((True, True, True, True), True),
            )

        await self._mark("SELECT_IJTAG: shift 1 into the DFT non-secure SIB, then capture")
        dft_bit, open_ok, cap_ok, dft_selects, other_selects = await self._dft_open()
        self._check(
            "CHK-LC-SIB-NONSECURE-OPEN-SIP-DIS-SEP-DBG",
            f"DFT SIB capture={dft_bit} open_scan_ok={int(open_ok)} "
            f"capture_scan_ok={int(cap_ok)} dft_selects={dft_selects} "
            f"other_selects={other_selects}",
            (
                dft_bit,
                open_ok,
                cap_ok,
                dft_selects >= IJTAG_CONTROL_SCAN_BITS,
                other_selects,
            ),
            (SIB_OPEN_CAPTURED, True, True, True, 0),
        )

        await self._mark("CASE 1 CONTROL: I/O STAP follows the PTAP TMS, the DFD SIB opens")
        io_obs = await self._stap_follow("io")
        follows = self._follows(io_obs)
        dfd_bit, open_ok, cap_ok, dfd_selects, other_selects = await self._dfd_control()
        self._check(
            "CHK-LC-CASE1-CONTROL-SIP-DIS-SEP-DBG",
            f"I/O STAP host_edges={io_obs['sep_edges']} ptap_edges={io_obs['ptap_edges']} "
            f"oen_highs={io_obs['oen_highs']} levels={sorted(io_obs['levels'])}; DFD SIB "
            f"capture={dfd_bit} open_scan_ok={int(open_ok)} capture_scan_ok={int(cap_ok)} "
            f"dfd_selects={dfd_selects} other_selects={other_selects}",
            (
                follows,
                dfd_bit,
                open_ok,
                cap_ok,
                dfd_selects >= IJTAG_CONTROL_SCAN_BITS,
                other_selects,
            ),
            ((True, True, True, True), SIB_OPEN_CAPTURED, True, True, True, 0),
        )

        await self._mark("SEP debug STAP select write while the PTAP TMS toggles")
        self._check_parked(
            "CHK-LC-STAP-SEP-PARKED-SIP-DIS-SEP-DBG",
            STAP_NAMES["sep"],
            await self._stap_parked_probe(),
        )

        await self._mark("SELECT_IJTAG: shift 1 into the DFT secure SIB, then capture")
        await self._tlr()
        await self._sib_closed_leg("dft_secure", "CHK-LC-SIB-SECURE-CLOSED-SIP-DIS-SEP-DBG")

        labels = [
            "sense_done",
            "fabric_ar",
            "fabric_b",
            "stap_window_smc",
            "stap_window_extra0",
            "ijtag_window_dft_open_1",
            "ijtag_window_dft_open_2",
            "stap_window_io",
            "ijtag_window_control_1",
            "ijtag_window_control_2",
            *[f"stap_window_{i}" for i in range(1, STAP_SCANS + 1)],
            "ijtag_window_dft_secure_1",
            "ijtag_window_dft_secure_2",
        ]
        await self._finish(sorted(labels))
