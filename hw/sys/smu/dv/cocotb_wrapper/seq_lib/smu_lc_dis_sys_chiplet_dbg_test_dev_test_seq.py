# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""In TEST_DEV a SYS_DIS CHIPLET_DBG bit closes the Case 2 and Case 3 debug paths and no other.

Spec: hw/sys/sep/doc/lifecycle_controller.adoc ("Disable vector bit table", "Per-LC-state
feature control profile", "DTP path feature gates"), hw/sys/sep/regs/blocks/sep_efuse_map/
sep_efuse_map.rdl (SYS_DIS), hw/sys/dtp/doc/jtag.adoc (SMC fabric bridge),
hw/ip/jtag/jtag_stap/doc/architecture.adoc (disabled STAP) and
hw/ip/jtag/jtag_intf_unit/doc/architecture.adoc (iJTAG SIBs).

The TEST_DEV eFuse shadow image named by ``+sep_shadow_reg_preload`` sets SYS_DIS bit 1 only and
is the only stimulus besides the JTAG accesses. The steps run in this order:

S1, setup: the image is the leaf's own and ``sep_fuse_sense_done_o`` rises within its bound.
S2, feature control: ``lcc_feat_ctrl_o`` has bit 1 clear and every other bit set.
S3, Case 1 control: the I/O STAP host TMS follows the PTAP TMS and the DFD SIB opens with its
    bench cell in the loop.
S4, fabric: an SMC fabric SINGLE_OP read and write launch nothing.
S5, SMC debug STAP: host TMS parked, TDO enable low, 3DCR Select captured 0.
S6, extra STAP: the same.
S7, DFT non-secure SIB: captures 0 and the DR stays 3 bits long.
S8, SEP debug STAP: the same as S5.
S9, DFT secure SIB: the same as S7.
Every bounded wait reports its bound, the cycles it used and the last observed state.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge

from seq_lib.smu_boundary_regs import (
    SMU_SEP_STAP_ORDER,
    ptap_prefixed,
    stap_3dcr_scan_word,
    stap_sib_pattern,
)
from seq_lib.smu_compose_helpers import hier
from seq_lib.smu_dtp_scan_chain_boundary_seq import (
    DTP_IR_SELECT_IJTAG,
    ijtag_chain,
    ijtag_shift,
    ijtag_word,
)
from seq_lib.smu_dtp_sep_dm_dmi_test_seq import MIN_PTAP_TMS_EDGES
from seq_lib.smu_jtag_helpers import (
    DTP_IR_TAP_3DCR,
    DTP_IR_WIDTH,
    PTAP_3DCR_WIDTH,
    ptap_3dcr_value,
)
from seq_lib.smu_lc_export_seq import (
    FEAT_CTRL_ALL_ENABLED,
    FEAT_CTRL_RESET,
    IJTAG_CLOSED_DR_BITS,
    IJTAG_DR_BIT,
    IJTAG_FLUSH_CAPTURE,
    IJTAG_FLUSH_OPEN_REQUEST,
    IJTAG_SCAN_BITS,
    LANE_DISABLED,
    NOT_LAUNCHED,
    STAP_SCANS,
    STAP_SELECT_CAPTURED,
    STAP_SELECT_WRITTEN,
    STAP_TMS_PARKED,
    ExportSpec,
)
from seq_lib.smu_lc_sec_dis_over_sigint_prod_test_seq import (
    STAP_OEN_PATH,
    STAP_TMS_PATH,
    smu_lc_sec_dis_over_sigint_prod_test_seq,
)
from seq_lib.smu_sep_stap_hold_reset_test_seq import (
    SIB_COUNT,
    STAP_3DCR_BITS,
    TMS_WINDOW_CYCLES,
)

IMAGE = "sep_efuse_shadow_lc_test_dev_sys_dis_chiplet_dbg.preload"

#: hw/sys/sep/doc/lifecycle_controller.adoc, "Disable vector bit table": SYS_DIS bit 1 is
#: CHIPLET_DBG; the image holds the 64-bit vector 64'h2 (hw/sys/sep/regs/blocks/sep_efuse_map/
#: sep_efuse_map.rdl, SYS_DIS).
SYS_DIS_VECTOR = 1 << 1
#: Same chapter, "Per-LC-state feature control profile": TEST_DEV enables every term and the
#: disable vectors are ORed and inverted, so a set SYS_DIS bit clears exactly its feature-control
#: bit.
FEAT_CTRL_CHIPLET_DBG_CLOSED = FEAT_CTRL_ALL_ENABLED & ~SYS_DIS_VECTOR

SPEC = ExportSpec(
    state="TEST_DEV",
    tag="SYS-DIS-CHIPLET-DBG",
    image=IMAGE,
    feat_ctrl=FEAT_CTRL_CHIPLET_DBG_CLOSED,
    lane=LANE_DISABLED,
)

#: hw/ip/jtag/jtag_intf_unit/doc/architecture.adoc, "iJTAG Network": with the DFD SIB open the DR
#: is the three SIB bits and the DFD bench cell. The scan is wider than that chain.
#: Flush patterns shifted behind the SIB bits: mixed and nonzero.
IJTAG_CONTROL_SCAN_BITS = 8
IJTAG_CONTROL_FLUSH_OPEN = 0b10101
IJTAG_CONTROL_FLUSH_CAPTURE = 0b1011
#: Same page: a SIB that captures 1 is open.
SIB_OPEN_CAPTURED = 1
SIB_CLOSED_CAPTURED = 0
DFD_ONLY = frozenset({"dfd"})

STAP_NAMES = {"smc": "SMC debug", "extra0": "extra", "sep": "SEP debug"}


class smu_lc_dis_sys_chiplet_dbg_test_dev_test_seq(smu_lc_sec_dis_over_sigint_prod_test_seq):
    """TEST_DEV with SYS_DIS CHIPLET_DBG: Case 1 paths open, Case 2 and Case 3 paths shut."""

    def __init__(self, test) -> None:
        super().__init__(test)
        self.spec = SPEC
        self.case1_ok = False

    async def _stap_parked_named(self, name: str) -> tuple[list[int], int, int, int, int]:
        """The select scans of STAP ``name`` with its SIB open: (host TMS levels, host edges,
        TDO-enable highs, PTAP edges, captured Select)."""
        await self._ensure_tap()
        sibs_from = SIB_COUNT - SMU_SEP_STAP_ORDER.index(name)
        oen = hier(self.dut, STAP_OEN_PATH[name])
        sel_write = stap_3dcr_scan_word(
            name, config_hold=0, stap_sel=STAP_SELECT_WRITTEN, tms_hold=STAP_TMS_PARKED, sib_en=1
        )
        sel_off = stap_3dcr_scan_word(
            name, config_hold=0, stap_sel=0, tms_hold=STAP_TMS_PARKED, sib_en=0
        )
        scans = [
            ("TAP_3DCR IR", lambda: self._scan_ir(DTP_IR_TAP_3DCR, DTP_IR_WIDTH, "TAP_3DCR")),
            (
                "PTAP select",
                lambda: self._scan_dr(
                    ptap_3dcr_value(config_hold=1, select=1), PTAP_3DCR_WIDTH, "PTAP select"
                ),
            ),
            (
                f"open {name} SIB",
                lambda: self._scan_dr(
                    *ptap_prefixed(stap_sib_pattern(name, 1), SIB_COUNT), f"open {name} SIB"
                ),
            ),
            (
                "write 3DCR select",
                lambda: self._scan_dr(*ptap_prefixed(*sel_write), "write 3DCR select"),
            ),
            (
                "capture 3DCR",
                lambda: self._scan_dr(*ptap_prefixed(*sel_write), "capture 3DCR"),
            ),
            (
                "PTAP deselect",
                lambda: self._scan_dr(
                    *ptap_prefixed(*sel_off, config_hold=0, select=0), "PTAP deselect"
                ),
            ),
        ]
        assert len(scans) == STAP_SCANS
        levels: set[int] = set()
        host_edges = oen_highs = ptap_edges = capture = 0
        for index, (label, scan) in enumerate(scans, start=1):
            win = {"scan_done": False}
            monitor = cocotb.start_soon(
                self._tms_monitor(win, oen, STAP_TMS_PATH[name], TMS_WINDOW_CYCLES)
            )
            captured = await scan()
            win["scan_done"] = True
            obs = await monitor
            done = obs["done"]
            self._record(
                f"stap_window_{name}_{index}",
                TMS_WINDOW_CYCLES,
                done if done is not None else TMS_WINDOW_CYCLES,
                "cycles",
                f"{label} levels={sorted(obs['levels'])} ptap_edges={obs['ptap_edges']} "
                f"host_edges={obs['sep_edges']} oen_highs={obs['oen_highs']}",
                expired=done is None,
            )
            levels |= obs["levels"]
            host_edges += obs["sep_edges"]
            oen_highs += obs["oen_highs"]
            ptap_edges += obs["ptap_edges"]
            if label == "capture 3DCR":
                capture = (captured >> sibs_from) & ((1 << STAP_3DCR_BITS) - 1)
        self._log(
            f"CELL stap_capture {name} payload=0b{capture:03b} (tms_hold, select, config_hold; "
            "measured and logged only except select)"
        )
        return sorted(levels), host_edges, oen_highs, ptap_edges, (capture >> 1) & 1

    def _check_parked(
        self, chk: str, who: str, probe: tuple[list[int], int, int, int, int]
    ) -> None:
        levels, host_edges, oen_highs, ptap_edges, select_read = probe
        self._check(
            chk,
            f"{who} STAP host TMS levels={levels} want=[{STAP_TMS_PARKED}] "
            f"host_edges={host_edges} tdo_enable_highs={oen_highs} ptap_tms_edges={ptap_edges} "
            f"(witness want >={MIN_PTAP_TMS_EDGES}) select_capture={select_read} "
            f"want={STAP_SELECT_CAPTURED}",
            (levels, host_edges, oen_highs, ptap_edges >= MIN_PTAP_TMS_EDGES, select_read),
            ([STAP_TMS_PARKED], 0, 0, True, STAP_SELECT_CAPTURED),
        )

    async def _ijtag_select(self) -> None:
        await self._ensure_tap()
        await self.jtag.shift_ir(DTP_IR_SELECT_IJTAG, back_to_rti=True)

    async def _dfd_control(self) -> tuple[int, bool, bool, int, int]:
        """Open the DFD SIB, then capture and close it: (DFD capture, open scan matches its
        model, capture scan matches its model, DFD host selects, other host selects)."""
        await self._tlr()
        await self._ijtag_select()
        closed = frozenset()
        bits = IJTAG_CONTROL_SCAN_BITS
        open_word = ijtag_word(closed, DFD_ONLY, IJTAG_CONTROL_FLUSH_OPEN, bits)
        cap_word = ijtag_word(DFD_ONLY, closed, IJTAG_CONTROL_FLUSH_CAPTURE, bits)
        want_open = ijtag_shift(closed, open_word, bits)[0]
        want_cap = ijtag_shift(DFD_ONLY, cap_word, bits)[0]
        got_open, _ = await self._ijtag_scan(open_word, "control_1", bits)
        got_cap, counts = await self._ijtag_scan(cap_word, "control_2", bits)
        chain = ijtag_chain(DFD_ONLY)
        dfd_bit = (got_cap >> (len(chain) - 1 - chain.index(("sib", "dfd")))) & 1
        other = sum(counts[name] for name in IJTAG_DR_BIT if name != "dfd")
        self._log(
            f"CELL ijtag_control open out=0x{got_open:x} want=0x{want_open:x} "
            f"capture out=0x{got_cap:x} want=0x{want_cap:x} chain_cells={len(chain)}"
        )
        return dfd_bit, got_open == want_open, got_cap == want_cap, counts["dfd"], other

    async def _sib_closed_leg(self, name: str, chk: str) -> None:
        """Shift 1 into one SIB of the closed DR, then capture it."""
        await self._ijtag_select()
        closed = frozenset()
        bits = IJTAG_SCAN_BITS
        open_word = ijtag_word(closed, frozenset({name}), IJTAG_FLUSH_OPEN_REQUEST, bits)
        cap_word = ijtag_word(closed, closed, IJTAG_FLUSH_CAPTURE, bits)
        want_open = ijtag_shift(closed, open_word, bits)[0]
        want_cap = ijtag_shift(closed, cap_word, bits)[0]
        got_open, counts_open = await self._ijtag_scan(open_word, f"{name}_1")
        got_cap, counts_cap = await self._ijtag_scan(cap_word, f"{name}_2")
        flush_ok = got_open == want_open and got_cap == want_cap
        selects = sum(counts_open[n] + counts_cap[n] for n in IJTAG_DR_BIT)
        tcks = min(counts_open["tck"], counts_cap["tck"])
        bit = IJTAG_DR_BIT[name]
        self._log(
            f"CELL ijtag_flush {name} open_request out=0x{got_open:x} want=0x{want_open:x} "
            f"capture out=0x{got_cap:x} want=0x{want_cap:x} dr_bits={IJTAG_CLOSED_DR_BITS}"
        )
        self._check(
            chk,
            f"{name} DR bit {bit} capture={(got_cap >> bit) & 1} want={SIB_CLOSED_CAPTURED} "
            f"flush_returned={int(flush_ok)} host_selects={selects} tck_seen={tcks} "
            f"(witness want >={IJTAG_SCAN_BITS})",
            ((got_cap >> bit) & 1, flush_ok, selects, tcks >= IJTAG_SCAN_BITS),
            (SIB_CLOSED_CAPTURED, True, 0, True),
        )

    async def run(self) -> None:
        await self._mark(
            "SETUP: TEST_DEV image with SYS_DIS CHIPLET_DBG, wait for sep_fuse_sense_done_o"
        )
        await self._setup()

        await self._mark("sample lcc_feat_ctrl_o")
        await RisingEdge(self.dut.clk_smu_i)
        word = self._rd("lcc_feat_ctrl_o")
        done = self._rd("sep_fuse_sense_done_o")
        self._check(
            "CHK-LC-FEATCTRL-SYS-DIS-CHIPLET-DBG-TEST-DEV",
            f"lcc_feat_ctrl_o=0x{word:016x} want=0x{FEAT_CTRL_CHIPLET_DBG_CLOSED:016x} "
            f"reset=0x{FEAT_CTRL_RESET:016x} sense_done={done}",
            (word, done, word != FEAT_CTRL_RESET),
            (FEAT_CTRL_CHIPLET_DBG_CLOSED, 1, True),
        )

        await self._mark("CASE 1 CONTROL: I/O STAP follows the PTAP TMS, the DFD SIB opens")
        io_obs = await self._stap_follow("io")
        follows = self._follows(io_obs)
        dfd_bit, open_ok, cap_ok, dfd_selects, other_selects = await self._dfd_control()
        self.case1_ok = (
            all(follows)
            and dfd_bit == SIB_OPEN_CAPTURED
            and open_ok
            and cap_ok
            and dfd_selects >= IJTAG_CONTROL_SCAN_BITS
            and other_selects == 0
        )
        self._check(
            "CHK-LC-CASE1-CONTROL-SYS-DIS-CHIPLET-DBG",
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

        await self._mark("SMC fabric SINGLE_OP read then write, DTP-to-SMC AR/AW/B counters")
        await self._tlr()
        lane_before = self._rd("lcc_dbg_disable_smc_jtag2axi_o")
        start, end, delta = await self._fabric_deltas(launches=False)
        lane_after = self._rd("lcc_dbg_disable_smc_jtag2axi_o")
        self._check(
            "CHK-LC-FABRIC-NOLAUNCH-SYS-DIS-CHIPLET-DBG",
            f"AR/AW/B deltas={delta} counts {start}->{end} lane before={lane_before} "
            f"after={lane_after} want_lane={LANE_DISABLED} case1_control_ok={int(self.case1_ok)}",
            (delta, lane_before, lane_after, self.case1_ok),
            (NOT_LAUNCHED, LANE_DISABLED, LANE_DISABLED, True),
        )

        await self._mark("SMC debug STAP select write while the PTAP TMS toggles")
        self._check_parked(
            "CHK-LC-STAP-SMC-PARKED-SYS-DIS-CHIPLET-DBG",
            STAP_NAMES["smc"],
            await self._stap_parked_named("smc"),
        )

        await self._mark("extra STAP select write while the PTAP TMS toggles")
        self._check_parked(
            "CHK-LC-STAP-EXTRA-PARKED-SYS-DIS-CHIPLET-DBG",
            STAP_NAMES["extra0"],
            await self._stap_parked_named("extra0"),
        )

        await self._mark("SELECT_IJTAG: shift 1 into the DFT non-secure SIB, then capture")
        await self._sib_closed_leg("dft", "CHK-LC-SIB-NONSECURE-CLOSED-SYS-DIS-CHIPLET-DBG")

        await self._mark("SEP debug STAP select write while the PTAP TMS toggles")
        self._check_parked(
            "CHK-LC-STAP-SEP-PARKED-SYS-DIS-CHIPLET-DBG",
            STAP_NAMES["sep"],
            await self._stap_parked_probe(),
        )

        await self._mark("SELECT_IJTAG: shift 1 into the DFT secure SIB, then capture")
        await self._sib_closed_leg("dft_secure", "CHK-LC-SIB-SECURE-CLOSED-SYS-DIS-CHIPLET-DBG")

        labels = [
            "sense_done",
            "stap_window_io",
            "ijtag_window_control_1",
            "ijtag_window_control_2",
            "fabric_window_read",
            "fabric_window_write",
            *[f"stap_window_smc_{i}" for i in range(1, STAP_SCANS + 1)],
            *[f"stap_window_extra0_{i}" for i in range(1, STAP_SCANS + 1)],
            "ijtag_window_dft_1",
            "ijtag_window_dft_2",
            *[f"stap_window_{i}" for i in range(1, STAP_SCANS + 1)],
            "ijtag_window_dft_secure_1",
            "ijtag_window_dft_secure_2",
        ]
        await self._finish(sorted(labels))
