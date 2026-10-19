# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""In RMA_SIP the SYS_DIS vector does not bind: every DTP path stays open.

Spec: hw/sys/sep/doc/lifecycle_controller.adoc ("Disable vector bit table", "Disable vector
applicability", "Per-LC-state feature control profile", "DTP access cases", "DTP path feature
gates"), hw/sys/sep/regs/blocks/sep_efuse_map/sep_efuse_map.rdl (SIP_DIS, SYS_DIS),
hw/sys/sep/doc/otp_fuse_controller.adoc ("Shadow Register and JTAG Access Control": SYS_DIS is
readable; in RMA_SIP the JTAG port reaches only the eFuse MMR token block, so the read-back goes
over the SEP debug module's system bus), hw/sys/dtp/doc/jtag.adoc (SMC fabric bridge),
hw/ip/jtag/jtag_stap/doc/architecture.adoc (selected STAP) and
hw/ip/jtag/jtag_intf_unit/doc/architecture.adoc (iJTAG SIBs).

The RMA_SIP eFuse shadow image named by ``+sep_shadow_reg_preload`` sets SYS_DIS bits 0, 1 and 24
with SIP_DIS clear and is the only stimulus besides the JTAG accesses. The steps run in this order:

S1, setup: the image is the leaf's own and ``sep_fuse_sense_done_o`` rises within its bound; the
    flag is the bench's ``+skip_fuse_sense`` substitute, a recorded precondition and not graded.
S2, SEP debug STAP: its host TMS follows the PTAP TMS and its TDO enable asserts.
S3, DFT secure SIB: opens, captures 1 and its bench cell joins the loop.
S4, SMC debug STAP: the same as S2.
S5, I/O STAP: the same as S2.
S6, DFD SIB: opens, captures 1 and its bench cell joins the loop.
S7, fabric: an SMC fabric SINGLE_OP read and write launch AR, AW and B.
S8, read-back, witness and feature control: the SEP STAP is selected over the PTAP 3DCR with the
    configuration held, the debug module comes out of reset and its system bus reads the two
    SYS_DIS words the DUT holds; then ``lc_state_o`` is the RMA_SIP word and ``lcc_feat_ctrl_o``
    has every bit set although the DUT-held SYS_DIS word, equal to the image's, has the three
    bits. The held selection survives Test-Logic-Reset, so this leg runs last.
Every bounded wait reports its bound, the cycles it used and the last observed state.
"""

from __future__ import annotations

from pathlib import Path

import cocotb
from cocotb.triggers import RisingEdge

from seq_lib.smu_addr_map import c_header_u32
from seq_lib.smu_dtp_scan_chain_boundary_seq import ijtag_chain, ijtag_shift, ijtag_word
from seq_lib.smu_dtp_sep_dm_dmi_test_seq import (
    DMCONTROL_ADDR,
    DMCONTROL_DMACTIVE,
    DMI_OP_READ,
    DMI_OP_WRITE,
    DMSTATUS_ADDR,
    DMSTATUS_VERSION_SPEC_0_13,
    SEP_TAP_IR_DMI,
    network_ir_scan,
)
from seq_lib.smu_dtp_sep_dm_sba_test_seq import (
    SBA_POLLS,
    SBADDRESS0_ADDR,
    SBCS_ADDR,
    SBCS_SBACCESS_32,
    SBCS_SBBUSY,
    SBCS_SBBUSYERROR,
    SBCS_SBERROR_MASK,
    SBCS_SBERROR_SHIFT,
    SBCS_SBERROR_W1C,
    SBCS_SBREADONADDR,
    SBDATA0_ADDR,
    smu_dtp_sep_dm_sba_test_seq,
)
from seq_lib.smu_jtag_helpers import DTP_IR_TAP_3DCR
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
    ExportSpec,
)

_SEP_ADDR_H = Path(__file__).resolve().parents[6] / "hw" / "sys" / "sep" / "regs" / "gen" / "c"
_SEP_ADDR_H = _SEP_ADDR_H / "sep_addr.h"

IMAGE = "sep_efuse_shadow_lc_rma_sip_0_sys_dis.preload"

#: hw/sys/sep/doc/lifecycle_controller.adoc, "Disable vector bit table": SYS_DIS bit 0 is
#: SEP_DBG, bit 1 CHIPLET_DBG and bit 24 SIP_DBG; the image holds the 64-bit vector
#: 64'h0000_0000_0100_0003 (hw/sys/sep/regs/blocks/sep_efuse_map/sep_efuse_map.rdl, SYS_DIS).
SYS_DIS_BIT_SEP_DBG = 0
SYS_DIS_BIT_CHIPLET_DBG = 1
SYS_DIS_BIT_SIP_DBG = 24
SYS_DIS_VECTOR = (
    (1 << SYS_DIS_BIT_SEP_DBG) | (1 << SYS_DIS_BIT_CHIPLET_DBG) | (1 << SYS_DIS_BIT_SIP_DBG)
)
#: Same chapter, "Disable vector applicability" and "Per-LC-state feature control profile": RMA_SIP
#: honours SIP_DIS only and the image's SIP_DIS is clear, so every feature-control bit stays set.
SIP_DIS_VECTOR = 0
FEAT_CTRL_RMA_SIP_SYS_DIS = FEAT_CTRL_ALL_ENABLED

#: hw/sys/sep/regs/gen/c/sep_addr.h: byte offsets of the SIP_DIS and SYS_DIS vectors in the eFuse
#: shadow image, each stored low word first.
SIP_DIS_OFFSET = c_header_u32(
    _SEP_ADDR_H, "SEP_TOP_SEP_EFUSE_MAP_SIP_DIS_BASE_ADDR"
) - c_header_u32(_SEP_ADDR_H, "SEP_TOP_SEP_EFUSE_MAP_BASE_ADDR")
SYS_DIS_OFFSET = c_header_u32(
    _SEP_ADDR_H, "SEP_TOP_SEP_EFUSE_MAP_SYS_DIS_BASE_ADDR"
) - c_header_u32(_SEP_ADDR_H, "SEP_TOP_SEP_EFUSE_MAP_BASE_ADDR")
#: hw/sys/sep/regs/gen/c/sep_addr.h: the SYS_DIS shadow register on the SEP map, read as two
#: 32-bit words, low word first, over the debug module's system bus (RISC-V Debug Specification
#: 0.13, "System Bus Access"). hw/sys/sep/doc/otp_fuse_controller.adoc, "Shadow Register and
#: JTAG Access Control": SYS_DIS is SW readable and the image sets no read-lock; the SEP OTP JTAG
#: bridge is closed to it in RMA_SIP, so the system bus is the read-back path.
SYS_DIS_ADDR = c_header_u32(_SEP_ADDR_H, "SEP_TOP_SEP_EFUSE_MAP_SYS_DIS_BASE_ADDR")
SYS_DIS_WORD_BYTES = 4

SPEC = ExportSpec(
    state="RMA_SIP_0",
    tag="RMA-SIP",
    image=IMAGE,
    feat_ctrl=FEAT_CTRL_RMA_SIP_SYS_DIS,
    lane=LANE_ENABLED,
)

#: hw/ip/jtag/jtag_intf_unit/doc/architecture.adoc, "iJTAG Network": with one SIB open the DR is
#: the three SIB bits and that SIB's bench cell.
SECURE_ONLY = frozenset({"dft_secure"})

DIS_BITS = {
    "SEP-DBG": ("CHK-LC-SYSDIS-SEP-DBG-IGNORED-RMA-SIP", SYS_DIS_BIT_SEP_DBG),
    "CHIPLET-DBG": ("CHK-LC-SYSDIS-CHIPLET-DBG-IGNORED-RMA-SIP", SYS_DIS_BIT_CHIPLET_DBG),
    "SIP-DBG": ("CHK-LC-SYSDIS-SIP-DBG-IGNORED-RMA-SIP", SYS_DIS_BIT_SIP_DBG),
}


def _image_vector(offset: int) -> int:
    """The 64-bit disable vector at byte ``offset`` of the shadow image, low word first."""
    preload = str(cocotb.plusargs.get("sep_shadow_reg_preload", ""))
    words = [
        int(line.split("//", 1)[0], 16)
        for line in Path(preload).read_text().splitlines()
        if line.split("//", 1)[0].strip()
    ]
    return words[offset // 4] | (words[offset // 4 + 1] << 32)


class smu_lc_dis_sys_not_binding_rma_sip_test_seq(smu_lc_dis_sys_chiplet_dbg_test_dev_test_seq):
    """RMA_SIP with SYS_DIS bits 0, 1 and 24 set: no SYS_DIS bit closes a path."""

    def __init__(self, test) -> None:
        super().__init__(test)
        self.spec = SPEC

    async def _sba_read32(self, sba, addr: int, label: str) -> int:
        """One 32-bit system-bus read; the sbcs poll is a recorded bounded wait."""
        jtag = self.jtag
        await sba._dmi(
            jtag,
            SBCS_ADDR,
            SBCS_SBACCESS_32 | SBCS_SBREADONADDR | SBCS_SBERROR_W1C,
            DMI_OP_WRITE,
        )
        await sba._dmi(jtag, SBADDRESS0_ADDR, addr, DMI_OP_WRITE)
        last = "no sbcs read"
        for poll in range(1, SBA_POLLS + 1):
            sbcs = await sba._dmi(jtag, SBCS_ADDR, 0, DMI_OP_READ)
            last = f"sbcs=0x{sbcs:08x}"
            if sbcs & SBCS_SBBUSY:
                continue
            sberror = (sbcs >> SBCS_SBERROR_SHIFT) & SBCS_SBERROR_MASK
            if sberror or (sbcs & SBCS_SBBUSYERROR):
                raise AssertionError(f"system-bus read 0x{addr:08x}: {last} sberror={sberror}")
            self._record(label, SBA_POLLS, poll, "polls", last)
            break
        else:
            self._record(label, SBA_POLLS, SBA_POLLS, "polls", last, expired=True)
        return await sba._dmi(jtag, SBDATA0_ADDR, 0, DMI_OP_READ)

    async def _sys_dis_read_back(self) -> tuple[int, int]:
        """(SYS_DIS word the DUT holds, dmstatus.version): the SEP STAP selected over the PTAP
        3DCR with the configuration held, the debug module active, two system-bus reads of the
        SYS_DIS shadow register. The held selection outlives Test-Logic-Reset
        (hw/ip/jtag/jtag_stap/doc/architecture.adoc, Config-Hold), so no STAP scan follows."""
        await self._tlr()
        sba = smu_dtp_sep_dm_sba_test_seq(self.test)
        await sba._select_sep_stap(self.jtag)
        ir_value, ir_width = network_ir_scan(DTP_IR_TAP_3DCR, SEP_TAP_IR_DMI)
        await self.jtag.shift_ir(ir_value, width=ir_width, back_to_rti=True)
        await sba._dmi(self.jtag, DMCONTROL_ADDR, DMCONTROL_DMACTIVE, DMI_OP_WRITE)
        version = (await sba._dmi(self.jtag, DMSTATUS_ADDR, 0, DMI_OP_READ)) & 0xF
        low = await self._sba_read32(sba, SYS_DIS_ADDR, "sba_sys_dis_low")
        high = await self._sba_read32(sba, SYS_DIS_ADDR + SYS_DIS_WORD_BYTES, "sba_sys_dis_high")
        word = ((high & 0xFFFF_FFFF) << 32) | (low & 0xFFFF_FFFF)
        self._log(
            f"CELL sys_dis_read_back @0x{SYS_DIS_ADDR:08x} low=0x{low:08x} high=0x{high:08x} "
            f"word=0x{word:016x} dmstatus.version={version} "
            f"(want_version={DMSTATUS_VERSION_SPEC_0_13}, measured and logged only)"
        )
        return word, version

    def _check_open(self, chk: str, who: str, obs: dict) -> None:
        self._check(
            chk,
            f"{who} STAP host_edges={obs['sep_edges']} ptap_edges={obs['ptap_edges']} "
            f"oen_highs={obs['oen_highs']} levels={sorted(obs['levels'])}",
            (self._follows(obs), obs["sep_edges"] > 0),
            (((True, True, True, True)), True),
        )

    async def _secure_open(self) -> tuple[int, bool, bool, int, int]:
        """Open the DFT secure SIB, then capture and close it: (SIB capture, open scan matches
        its model, capture scan matches its model, secure host selects, other host selects)."""
        await self._tlr()
        await self._ijtag_select()
        closed = frozenset()
        bits = IJTAG_CONTROL_SCAN_BITS
        open_word = ijtag_word(closed, SECURE_ONLY, IJTAG_CONTROL_FLUSH_OPEN, bits)
        cap_word = ijtag_word(SECURE_ONLY, closed, IJTAG_CONTROL_FLUSH_CAPTURE, bits)
        want_open = ijtag_shift(closed, open_word, bits)[0]
        want_cap = ijtag_shift(SECURE_ONLY, cap_word, bits)[0]
        got_open, _ = await self._ijtag_scan(open_word, "secure_open_1", bits)
        got_cap, counts = await self._ijtag_scan(cap_word, "secure_open_2", bits)
        chain = ijtag_chain(SECURE_ONLY)
        secure_bit = (got_cap >> (len(chain) - 1 - chain.index(("sib", "dft_secure")))) & 1
        other = sum(counts[name] for name in IJTAG_DR_BIT if name != "dft_secure")
        self._log(
            f"CELL ijtag_secure_open open out=0x{got_open:x} want=0x{want_open:x} "
            f"capture out=0x{got_cap:x} want=0x{want_cap:x} chain_cells={len(chain)}"
        )
        return secure_bit, got_open == want_open, got_cap == want_cap, counts["dft_secure"], other

    def _check_sib_open(self, chk: str, who: str, probe: tuple[int, bool, bool, int, int]) -> None:
        bit, open_ok, cap_ok, selects, other = probe
        self._check(
            chk,
            f"{who} SIB capture={bit} open_scan_ok={int(open_ok)} capture_scan_ok={int(cap_ok)} "
            f"selects={selects} other_selects={other}",
            (bit, open_ok, cap_ok, selects >= IJTAG_CONTROL_SCAN_BITS, other),
            (SIB_OPEN_CAPTURED, True, True, True, 0),
        )

    async def run(self) -> None:
        await self._mark(
            "SETUP: RMA_SIP image with SYS_DIS bits 0, 1 and 24, wait for sep_fuse_sense_done_o"
        )
        await self._setup()
        sys_dis_image = _image_vector(SYS_DIS_OFFSET)
        sip_dis_image = _image_vector(SIP_DIS_OFFSET)

        await self._mark("SEP debug STAP selected over the PTAP while the PTAP TMS toggles")
        self._check_open(
            "CHK-LC-STAP-SEP-OPEN-RMA-SIP-SYS-DIS",
            STAP_NAMES["sep"],
            await self._stap_follow("sep"),
        )

        await self._mark("SELECT_IJTAG: shift 1 into the DFT secure SIB, then capture")
        self._check_sib_open(
            "CHK-LC-SIB-SECURE-OPEN-RMA-SIP-SYS-DIS", "DFT secure", await self._secure_open()
        )

        await self._mark("SMC debug STAP selected over the PTAP while the PTAP TMS toggles")
        self._check_open(
            "CHK-LC-STAP-SMC-OPEN-RMA-SIP-SYS-DIS",
            STAP_NAMES["smc"],
            await self._stap_follow("smc"),
        )

        await self._mark("I/O STAP selected over the PTAP while the PTAP TMS toggles")
        self._check_open(
            "CHK-LC-STAP-IO-OPEN-RMA-SIP-SYS-DIS", "I/O", await self._stap_follow("io")
        )

        await self._mark("SELECT_IJTAG: shift 1 into the DFD SIB, then capture")
        self._check_sib_open(
            "CHK-LC-SIB-DFD-OPEN-RMA-SIP-SYS-DIS", "DFD", await self._dfd_control()
        )

        await self._mark("SMC fabric SINGLE_OP read then write, DTP-to-SMC AR/AW/B counters")
        await self._tlr()
        lane_before = self._rd("lcc_dbg_disable_smc_jtag2axi_o")
        start, end, delta = await self._fabric_deltas(launches=True)
        lane_after = self._rd("lcc_dbg_disable_smc_jtag2axi_o")
        self._check(
            "CHK-LC-FABRIC-CONTROL-RMA-SIP-SYS-DIS",
            f"AR/AW/B deltas={delta} counts {start}->{end} lane before={lane_before} "
            f"after={lane_after} want_lane={LANE_ENABLED}",
            (delta, lane_before, lane_after),
            (LAUNCHED_AR_AW_B, LANE_ENABLED, LANE_ENABLED),
        )

        await self._mark(
            "READ-BACK: SYS_DIS over the SEP debug module's system bus, then lc_state_o and "
            "lcc_feat_ctrl_o"
        )
        sys_dis_dut, _ = await self._sys_dis_read_back()
        await RisingEdge(self.dut.clk_smu_i)
        word = self._rd("lcc_feat_ctrl_o")
        lc_state = self._rd("lc_state_o")
        done = self._rd("sep_fuse_sense_done_o")
        for who, (chk, bit) in DIS_BITS.items():
            self._check(
                chk,
                f"{who} SYS_DIS bit {bit}: lcc_feat_ctrl_o=0x{word:016x} bit={(word >> bit) & 1} "
                f"want=0x{FEAT_CTRL_RMA_SIP_SYS_DIS:016x} reset=0x{FEAT_CTRL_RESET:016x} "
                f"lc_state_o=0x{lc_state:02x} want=0x{SPEC.lc_word:02x} sense_done={done} "
                f"DUT SYS_DIS=0x{sys_dis_dut:016x} bit_set={(sys_dis_dut >> bit) & 1} "
                f"image SYS_DIS=0x{sys_dis_image:016x} image SIP_DIS=0x{sip_dis_image:016x}",
                (
                    word,
                    (word >> bit) & 1,
                    lc_state,
                    word != FEAT_CTRL_RESET,
                    sys_dis_dut,
                    (sys_dis_dut >> bit) & 1,
                    sys_dis_image,
                    sip_dis_image,
                ),
                (
                    FEAT_CTRL_RMA_SIP_SYS_DIS,
                    1,
                    SPEC.lc_word,
                    True,
                    SYS_DIS_VECTOR,
                    1,
                    SYS_DIS_VECTOR,
                    SIP_DIS_VECTOR,
                ),
            )

        labels = [
            "sense_done",
            "sba_sys_dis_low",
            "sba_sys_dis_high",
            "stap_window_sep",
            "ijtag_window_secure_open_1",
            "ijtag_window_secure_open_2",
            "stap_window_smc",
            "stap_window_io",
            "ijtag_window_control_1",
            "ijtag_window_control_2",
            "fabric_ar",
            "fabric_b",
        ]
        await self._finish(sorted(labels))
