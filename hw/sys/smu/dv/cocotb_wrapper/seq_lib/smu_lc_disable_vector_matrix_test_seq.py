# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Debug-path posture of one lifecycle image and SIP_DIS / SYS_DIS pair, named by the preload.

Spec: hw/sys/sep/doc/lifecycle_controller.adoc ("Disable Vector Format", "Per-LC-state Feature
Control Profile", "Debug and Test Port Path Gating", "DTP path feature gates"),
hw/sys/sep/regs/blocks/sep_efuse_map/sep_efuse_map.rdl (LC_STATE, LC_DISABLE, SIP_DIS, SYS_DIS)
through the generated sep_addr.h and sep_efuse_map.h, hw/ip/jtag/jtag_stap/doc/architecture.adoc
(disabled STAP) and hw/ip/jtag/jtag_intf_unit/doc/architecture.adoc (iJTAG SIBs).

The eFuse shadow image named by ``+sep_shadow_reg_preload`` is the stimulus; it is one of the ten
files of ``PRELOAD_SET``. The expected feature-control word, the exported LC_STATE word and the
open or shut verdict of each walked path are computed from the image and the two vectors read
from that file. The seed draws only the order in which the four gated paths are walked.

S1, setup: the image is one of the set, ``+lc_sigint_inject`` is absent and
    ``sep_fuse_sense_done_o`` rises within its bound.
S2, image: ``lc_state_o`` and ``lc_sigint_err_o``, and the two outputs sampled by the leaf on the
    last ``clk_smu_i`` edge before ``sep_fuse_sense_done_o`` rose (the INVALID encoding and the
    all-disabled feature word).
S3, feature control: ``lcc_feat_ctrl_o`` against the profile word of the image and the pair.
S4..S7, the four gated paths in the drawn order: the I/O STAP host path (Case 1) and the SEP
    debug STAP host path (Case 3) by their host TMS and TDO-enable taps, the SMC fabric JTAG2AXI
    path (Case 2) by the DTP-to-SMC AR, AW and B counters, the secure DFT SIB (Case 3) by its
    host select and its captured SIB bit.
S8, read-back: under the TEST_DEV file with neither vector set, LC_STATE, SIP_DIS and SYS_DIS
    over the SEP debug module's system bus; under every other file the same request scans run
    over the shut SEP debug STAP, whose host TMS and TDO enable must not move.
Every bounded wait reports its bound, the cycles or polls it used and the last observed state.
"""

from __future__ import annotations

import random
from pathlib import Path

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from cocotb.utils import get_sim_time

from seq_lib.smu_addr_map import c_header_u32
from seq_lib.smu_compose_helpers import hier
from seq_lib.smu_dtp_scan_chain_boundary_seq import ijtag_chain, ijtag_shift, ijtag_word
from seq_lib.smu_dtp_sep_dm_dmi_test_seq import (
    DMCONTROL_ADDR,
    DMCONTROL_DMACTIVE,
    DMI_OP_NOP,
    DMI_OP_READ,
    DMI_OP_WRITE,
    DMSTATUS_ADDR,
    MIN_PTAP_TMS_EDGES,
    SEP_STAP_TMS,
    SEP_TAP_IR_DMI,
    network_ir_scan,
    pack_dmi,
    unpack_dmi,
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
from seq_lib.smu_jtag_helpers import DTP_IR_TAP_3DCR, J2A_OP_READ, J2A_OP_WRITE
from seq_lib.smu_lc_dis_sys_chiplet_dbg_test_dev_test_seq import (
    IJTAG_CONTROL_FLUSH_CAPTURE,
    IJTAG_CONTROL_FLUSH_OPEN,
    IJTAG_CONTROL_SCAN_BITS,
    SIB_CLOSED_CAPTURED,
    SIB_OPEN_CAPTURED,
    smu_lc_dis_sys_chiplet_dbg_test_dev_test_seq,
)
from seq_lib.smu_lc_export_seq import (
    IJTAG_DR_BIT,
    IJTAG_FLUSH_CAPTURE,
    IJTAG_FLUSH_OPEN_REQUEST,
    IJTAG_SCAN_BITS,
    LANE_DISABLED,
    LANE_ENABLED,
    ExportSpec,
)
from seq_lib.smu_lc_sec_dis_over_sigint_prod_test_seq import (
    STAP_IDCODE_WINDOW_CYCLES,
    STAP_OEN_PATH,
)
from seq_lib.smu_lifecycle_table import (
    LC_RAW,
    LC_STATE_PRESENSE,
    lc_state_word,
)

_REPO_ROOT = Path(__file__).resolve().parents[6]
_SEP_C = _REPO_ROOT / "hw" / "sys" / "sep" / "regs" / "gen" / "c"
_SEP_ADDR_H = _SEP_C / "sep_addr.h"
_SEP_EFUSE_MAP_H = _SEP_C / "blocks" / "sep_efuse_map.h"


def _lcd(field: str) -> int:
    return c_header_u32(_SEP_EFUSE_MAP_H, f"SEP_EFUSE_MAP__LC_DISABLE__{field}_bm")


def _sep(symbol: str) -> int:
    return c_header_u32(_SEP_ADDR_H, symbol)


#: sep_efuse_map.rdl LC_DISABLE: SEP_DBG bit 0, CHIPLET_DBG bit 1, SIP_DBG bit 24.
SEP_DBG = _lcd("SEP_DEBUG")
CHIPLET_DBG = _lcd("CHIPLET_DBG")
SIP_DBG = _lcd("SIP_DEBUG")
#: lifecycle_controller.adoc "Disable Vector Format": DBG_1 [23:0], DBG_2 [47:24], Function
#: [63:48]; the groups are the unions of the LC_DISABLE fields the generated header lists.
DBG_1 = (
    SEP_DBG
    | CHIPLET_DBG
    | _lcd("SEP_FUSE_DBG")
    | _lcd("SMC_FUSE_DBG")
    | _lcd("DEBUG_RESERVED_DBG1")
)
DBG_2 = SIP_DBG | _lcd("DEBUG_RESERVED_DBG2")
FUNCTION = _lcd("FUNC_RESERVED")
VECTOR_ALL = DBG_1 | DBG_2 | FUNCTION
assert VECTOR_ALL == (1 << 64) - 1, "LC_DISABLE fields do not cover the 64-bit register"

#: Word offsets of LC_STATE, SIP_DIS and SYS_DIS in the shadow image, one 32-bit word per line.
MAP_BASE = _sep("SEP_TOP_SEP_EFUSE_MAP_BASE_ADDR")
LC_STATE_ADDR = _sep("SEP_TOP_SEP_EFUSE_MAP_LC_STATE_BASE_ADDR")
SIP_DIS_ADDR = _sep("SEP_TOP_SEP_EFUSE_MAP_SIP_DIS_BASE_ADDR")
SYS_DIS_ADDR = _sep("SEP_TOP_SEP_EFUSE_MAP_SYS_DIS_BASE_ADDR")

#: The preload set: image and the (SIP_DIS, SYS_DIS) pair each file is meant to carry. The pair
#: is read from the file at run time and must equal this row.
PRELOAD_SET: dict[str, tuple[str, int, int]] = {
    "sep_efuse_shadow_lc_test_dev.preload": ("TEST_DEV", 0, 0),
    "sep_efuse_shadow_lc_test_dev_sip_dis_sep_dbg.preload": ("TEST_DEV", SEP_DBG, 0),
    "sep_efuse_shadow_lc_test_dev_sys_dis_chiplet_dbg.preload": ("TEST_DEV", 0, CHIPLET_DBG),
    "sep_efuse_shadow_lc_test_dev_sip_dis_sep_dbg_sys_dis_chiplet_dbg.preload": (
        "TEST_DEV",
        SEP_DBG,
        CHIPLET_DBG,
    ),
    "sep_efuse_shadow_lc_test_dev_dis_all.preload": ("TEST_DEV", VECTOR_ALL, VECTOR_ALL),
    "sep_efuse_shadow_lc_prod.preload": ("PROD", 0, 0),
    "sep_efuse_shadow_lc_prod_sip_dis_sep_dbg.preload": ("PROD", SEP_DBG, 0),
    "sep_efuse_shadow_lc_prod_sys_dis_chiplet_dbg.preload": ("PROD", 0, CHIPLET_DBG),
    "sep_efuse_shadow_lc_prod_sip_dis_sep_dbg_sys_dis_chiplet_dbg.preload": (
        "PROD",
        SEP_DBG,
        CHIPLET_DBG,
    ),
    "sep_efuse_shadow_lc_prod_dis_all.preload": ("PROD", VECTOR_ALL, VECTOR_ALL),
}
#: The one file under which the SEP debug STAP host path is open and the read-back runs.
READBACK_FILE = "sep_efuse_shadow_lc_test_dev.preload"

#: lifecycle_controller.adoc "DTP path feature gates": the gating case of each walked path.
PATH_CASE = {"io_stap": 1, "smc_fabric": 2, "sep_stap": 3, "dft_secure_sib": 3}
PATHS = tuple(PATH_CASE)
OPEN = "open"
SHUT = "shut"

#: A SINGLE_OP read launches one AR and a write one AW and one B (hw/sys/dtp/doc/jtag.adoc).
FABRIC_OPEN_DELTA = (1, 1, 1)
FABRIC_SHUT_DELTA = (0, 0, 0)
STEP_CLOCK_GAP = 2
WORD32 = 0xFFFF_FFFF
#: lifecycle_controller.adoc: INVALID, the encoding before sensing, is F / F / F with SEC_DIS 0.
FEAT_PRESENSE = 0
#: clk_ref_i cycles for the request scans of the five read-back words (one IDCODE window each
#: of select, IR and every scan, with margin).
READBACK_WINDOW_CYCLES = 32 * STAP_IDCODE_WINDOW_CYCLES


def preload_words(path: str) -> list[int]:
    """The 32-bit words of a shadow image, one per non-comment line."""
    return [
        int(line.split("//", 1)[0], 16)
        for line in Path(path).read_text().splitlines()
        if line.split("//", 1)[0].strip()
    ]


def vector64(words: list[int], addr: int) -> int:
    """A 64-bit LC_DISABLE register of the image, low word first."""
    index = (addr - MAP_BASE) // 4
    return words[index] | (words[index + 1] << 32)


def profile_word(state: str, sip_dis: int, sys_dis: int) -> int:
    """lifecycle_controller.adoc "Per-LC-state Feature Control Profile", SEC_DIS 0, no demotion.

    TEST_DEV: DBG_1, DBG_2 and Function are each ``~(SIP_DIS | SYS_DIS)``; PROD: DBG_1 and DBG_2
    are F and Function is ``~(SIP_DIS | SYS_DIS)``.
    """
    enable = ~(sip_dis | sys_dis) & VECTOR_ALL
    if state == "TEST_DEV":
        return enable
    if state == "PROD":
        return enable & FUNCTION
    raise AssertionError(f"no profile row for {state} in the preload set")


def case_open(word: int, case: int) -> bool:
    """lifecycle_controller.adoc "DTP access cases": Case 1 SIP_DBG, Case 2 adds CHIPLET_DBG,
    Case 3 adds SEP_DBG, each evaluated on the positive-logic feature word."""
    terms = {1: SIP_DBG, 2: SIP_DBG | CHIPLET_DBG, 3: SIP_DBG | CHIPLET_DBG | SEP_DBG}[case]
    return word & terms == terms


def expected_verdicts(word: int) -> dict[str, str]:
    return {path: OPEN if case_open(word, case) else SHUT for path, case in PATH_CASE.items()}


async def sample_pre_sense(dut, out: dict) -> None:
    """From the first clk_smu_i edge until ``sep_fuse_sense_done_o`` reads 1: the number of
    resolved samples and the last resolved ``lc_state_o`` and ``lcc_feat_ctrl_o``."""
    pins = (dut.sep_fuse_sense_done_o, dut.lc_state_o, dut.lcc_feat_ctrl_o)
    while True:
        await RisingEdge(dut.clk_smu_i)
        values = [pin.value for pin in pins]
        if not all(getattr(v, "is_resolvable", True) for v in values):
            continue
        done, lc, feat = (int(v) for v in values)
        if done:
            return
        out["samples"] += 1
        out["lc"], out["feat"] = lc, feat


class smu_lc_disable_vector_matrix_test_seq(smu_lc_dis_sys_chiplet_dbg_test_dev_test_seq):
    """One preload file of the disable-vector set: image, feature word, four gated paths."""

    def __init__(self, test) -> None:
        super().__init__(test)
        self.seed = test.random_seed()
        self.rng = random.Random(self.seed)
        preload = str(cocotb.plusargs.get("sep_shadow_reg_preload", ""))
        self.image = Path(preload).name
        assert self.image in PRELOAD_SET, (
            f"+sep_shadow_reg_preload {preload!r} is not a file of the disable-vector set"
        )
        state, sip_row, sys_row = PRELOAD_SET[self.image]
        words = preload_words(preload)
        self.state = state
        self.sip_dis = vector64(words, SIP_DIS_ADDR)
        self.sys_dis = vector64(words, SYS_DIS_ADDR)
        assert (self.sip_dis, self.sys_dis) == (sip_row, sys_row), (
            f"{self.image} carries SIP_DIS=0x{self.sip_dis:016x} SYS_DIS=0x{self.sys_dis:016x}, "
            f"not the pair of its set row"
        )
        self.file_words = {
            "LC_STATE": words[(LC_STATE_ADDR - MAP_BASE) // 4],
            "SIP_DIS_LO": self.sip_dis & WORD32,
            "SIP_DIS_HI": self.sip_dis >> 32,
            "SYS_DIS_LO": self.sys_dis & WORD32,
            "SYS_DIS_HI": self.sys_dis >> 32,
        }
        self.feat_want = profile_word(state, self.sip_dis, self.sys_dis)
        self.want = expected_verdicts(self.feat_want)
        self.order = list(PATHS)
        self.rng.shuffle(self.order)
        self.readback = self.image == READBACK_FILE
        self.spec = ExportSpec(
            state=state,
            tag="LCVEC",
            image=self.image,
            feat_ctrl=self.feat_want,
            lane=LANE_ENABLED if self.want["smc_fabric"] == OPEN else LANE_DISABLED,
        )
        self.verdicts: dict[str, str] = {}
        self.details: dict[str, str] = {}
        self.feat_seen = 0
        self.done = False

    def _log_grade(self, token: str) -> None:
        self._log(f"{token}: graded, file={self.image} drawn walk order={self.order}")

    # ------------------------------------------------------------------
    # Path probes. Each returns the verdict its observation supports: open, shut or neither.
    # ------------------------------------------------------------------

    async def _probe_stap(self, name: str) -> tuple[str, str]:
        obs = await self._stap_follow(name)
        follows = self._follows(obs)
        detail = (
            f"host_edges={obs['sep_edges']} ptap_edges={obs['ptap_edges']} "
            f"oen_highs={obs['oen_highs']} levels={sorted(obs['levels'])}"
        )
        if all(follows):
            return OPEN, detail
        parked = (
            obs["sep_edges"] == 0
            and obs["oen_highs"] == 0
            and sorted(obs["levels"]) == [0]
            and obs["ptap_edges"] >= MIN_PTAP_TMS_EDGES
        )
        return (SHUT if parked else "neither"), detail

    async def _probe_fabric(self) -> tuple[str, str]:
        await self._tlr()
        lane_before = self._rd("lcc_dbg_disable_smc_jtag2axi_o")
        start = self._counts()
        await self._fabric_op("read", J2A_OP_READ, 0, launches=False)
        await self._fabric_op("write", J2A_OP_WRITE, 2, launches=False)
        end = self._counts()
        delta = tuple(b - a for a, b in zip(start, end))
        lane_after = self._rd("lcc_dbg_disable_smc_jtag2axi_o")
        self._log(
            f"OBSERVATION lcc_dbg_disable_smc_jtag2axi_o before={lane_before} after={lane_after}"
            " (measured and logged only)"
        )
        detail = f"AR/AW/B deltas={delta} counts {start}->{end}"
        if delta == FABRIC_OPEN_DELTA:
            return OPEN, detail
        return (SHUT if delta == FABRIC_SHUT_DELTA else "neither"), detail

    async def _probe_sib_open(self) -> tuple[str, str]:
        """Open the secure DFT SIB, then capture and close it."""
        await self._tlr()
        await self._ijtag_select()
        closed = frozenset()
        target = frozenset({"dft_secure"})
        bits = IJTAG_CONTROL_SCAN_BITS
        open_word = ijtag_word(closed, target, IJTAG_CONTROL_FLUSH_OPEN, bits)
        cap_word = ijtag_word(target, closed, IJTAG_CONTROL_FLUSH_CAPTURE, bits)
        want_open = ijtag_shift(closed, open_word, bits)[0]
        want_cap = ijtag_shift(target, cap_word, bits)[0]
        got_open, _ = await self._ijtag_scan(open_word, "sib_open_1", bits)
        got_cap, counts = await self._ijtag_scan(cap_word, "sib_open_2", bits)
        chain = ijtag_chain(target)
        bit = (got_cap >> (len(chain) - 1 - chain.index(("sib", "dft_secure")))) & 1
        other = sum(counts[name] for name in IJTAG_DR_BIT if name != "dft_secure")
        selects = counts["dft_secure"]
        detail = (
            f"open-probe capture={bit} open_scan_ok={int(got_open == want_open)} "
            f"capture_scan_ok={int(got_cap == want_cap)} selects={selects} other={other}"
        )
        if (
            bit == SIB_OPEN_CAPTURED
            and got_open == want_open
            and got_cap == want_cap
            and selects >= bits
            and other == 0
        ):
            return OPEN, detail
        return (SHUT if bit == SIB_CLOSED_CAPTURED and selects == 0 else "neither"), detail

    async def _probe_sib_shut(self) -> tuple[str, str]:
        """Shift 1 into the secure DFT SIB of the closed DR, then capture it."""
        await self._tlr()
        await self._ijtag_select()
        closed = frozenset()
        bits = IJTAG_SCAN_BITS
        open_word = ijtag_word(closed, frozenset({"dft_secure"}), IJTAG_FLUSH_OPEN_REQUEST, bits)
        cap_word = ijtag_word(closed, closed, IJTAG_FLUSH_CAPTURE, bits)
        want_open = ijtag_shift(closed, open_word, bits)[0]
        want_cap = ijtag_shift(closed, cap_word, bits)[0]
        got_open, counts_open = await self._ijtag_scan(open_word, "sib_shut_1")
        got_cap, counts_cap = await self._ijtag_scan(cap_word, "sib_shut_2")
        flush_ok = got_open == want_open and got_cap == want_cap
        selects = counts_open["dft_secure"] + counts_cap["dft_secure"]
        tcks = min(counts_open["tck"], counts_cap["tck"])
        bit = (got_cap >> IJTAG_DR_BIT["dft_secure"]) & 1
        detail = (
            f"shut-probe capture={bit} flush_returned={int(flush_ok)} selects={selects} "
            f"tck_seen={tcks}"
        )
        if bit == SIB_CLOSED_CAPTURED and flush_ok and selects == 0 and tcks >= bits:
            return SHUT, detail
        return (OPEN if selects > 0 or bit == SIB_OPEN_CAPTURED else "neither"), detail

    async def _walk(self, path: str) -> None:
        if path == "io_stap":
            verdict, detail = await self._probe_stap("io")
        elif path == "sep_stap":
            verdict, detail = await self._probe_stap("sep")
        elif path == "smc_fabric":
            verdict, detail = await self._probe_fabric()
        elif self.want[path] == OPEN:
            verdict, detail = await self._probe_sib_open()
        else:
            verdict, detail = await self._probe_sib_shut()
        self.verdicts[path] = verdict
        self.details[path] = detail
        self._log(
            f"CELL path {path} case={PATH_CASE[path]} verdict={verdict} want={self.want[path]} "
            f"{detail}"
        )

    # ------------------------------------------------------------------
    # Read-back over the SEP debug module's system bus.
    # ------------------------------------------------------------------

    async def _sba_read(self, sba, label: str, addr: int) -> int:
        jtag = self.jtag
        await sba._dmi(
            jtag,
            SBCS_ADDR,
            SBCS_SBACCESS_32 | SBCS_SBREADONADDR | SBCS_SBERROR_W1C,
            DMI_OP_WRITE,
        )
        await sba._dmi(jtag, SBADDRESS0_ADDR, addr, DMI_OP_WRITE)
        sbcs, polls = SBCS_SBBUSY, 0
        while polls < SBA_POLLS and sbcs & SBCS_SBBUSY:
            sbcs = await sba._dmi(jtag, SBCS_ADDR, 0, DMI_OP_READ)
            polls += 1
        sberror = (sbcs >> SBCS_SBERROR_SHIFT) & SBCS_SBERROR_MASK
        self._record(
            f"sba_read_{label}",
            SBA_POLLS,
            polls,
            "polls",
            f"sbcs=0x{sbcs:08x} sberror={sberror}",
            expired=bool(sbcs & SBCS_SBBUSY),
        )
        if sberror or sbcs & SBCS_SBBUSYERROR:
            raise AssertionError(f"system-bus read {label} @0x{addr:08x}: sbcs=0x{sbcs:08x}")
        return await sba._dmi(jtag, SBDATA0_ADDR, 0, DMI_OP_READ)

    async def _read_back_closed(self) -> tuple[dict, dict[str, int]]:
        """The read-back's request scans over the shut SEP debug STAP; returns the host TMS and
        TDO-enable observation and the dmi words captured."""
        await self._tlr()
        sba = smu_dtp_sep_dm_sba_test_seq(self.test)
        jtag = self.jtag
        await sba._select_sep_stap(jtag)
        win = {"scan_done": False}
        monitor = cocotb.start_soon(
            self._tms_monitor(
                win, hier(self.dut, STAP_OEN_PATH["sep"]), SEP_STAP_TMS, READBACK_WINDOW_CYCLES
            )
        )
        ir_value, ir_width = network_ir_scan(DTP_IR_TAP_3DCR, SEP_TAP_IR_DMI)
        await jtag.shift_ir(ir_value, width=ir_width, back_to_rti=True)
        sbcs = SBCS_SBACCESS_32 | SBCS_SBREADONADDR | SBCS_SBERROR_W1C
        captured = {}
        for label, addr in self._readback_addrs():
            await sba._dmi_scan(jtag, pack_dmi(SBCS_ADDR, sbcs, op=DMI_OP_WRITE))
            await sba._dmi_scan(jtag, pack_dmi(SBADDRESS0_ADDR, addr, op=DMI_OP_WRITE))
            await sba._dmi_scan(jtag, pack_dmi(SBDATA0_ADDR, 0, op=DMI_OP_READ))
            word = await sba._dmi_scan(jtag, pack_dmi(SBDATA0_ADDR, 0, op=DMI_OP_NOP))
            captured[label] = unpack_dmi(word)[1]
        win["scan_done"] = True
        obs = await monitor
        done = obs["done"]
        self._record(
            "readback_window",
            READBACK_WINDOW_CYCLES,
            done if done is not None else READBACK_WINDOW_CYCLES,
            "cycles",
            f"levels={sorted(obs['levels'])} ptap_edges={obs['ptap_edges']} "
            f"host_edges={obs['sep_edges']} oen_highs={obs['oen_highs']}",
            expired=done is None,
        )
        return obs, captured

    @staticmethod
    def _readback_addrs() -> tuple[tuple[str, int], ...]:
        return (
            ("LC_STATE", LC_STATE_ADDR),
            ("SIP_DIS_LO", SIP_DIS_ADDR),
            ("SIP_DIS_HI", SIP_DIS_ADDR + 4),
            ("SYS_DIS_LO", SYS_DIS_ADDR),
            ("SYS_DIS_HI", SYS_DIS_ADDR + 4),
        )

    async def _read_back(self) -> dict[str, int]:
        await self._tlr()
        sba = smu_dtp_sep_dm_sba_test_seq(self.test)
        jtag = self.jtag
        await sba._select_sep_stap(jtag)
        ir_value, ir_width = network_ir_scan(DTP_IR_TAP_3DCR, SEP_TAP_IR_DMI)
        await jtag.shift_ir(ir_value, width=ir_width, back_to_rti=True)
        await sba._dmi(jtag, DMCONTROL_ADDR, DMCONTROL_DMACTIVE, DMI_OP_WRITE)
        dmstatus = await sba._dmi(jtag, DMSTATUS_ADDR, 0, DMI_OP_READ)
        self._log(f"OBSERVATION dmstatus=0x{dmstatus:08x} (measured and logged only)")
        got = {}
        for label, addr in self._readback_addrs():
            got[label] = await self._sba_read(sba, label, addr) & WORD32
        return got

    # ------------------------------------------------------------------
    # Run.
    # ------------------------------------------------------------------

    def _wait_labels(self) -> list[str]:
        sib = "sib_open" if self.want["dft_secure_sib"] == OPEN else "sib_shut"
        labels = [
            "sense_done",
            "stap_window_io",
            "stap_window_sep",
            "fabric_window_read",
            "fabric_window_write",
            f"ijtag_window_{sib}_1",
            f"ijtag_window_{sib}_2",
        ]
        if self.readback:
            labels += [f"sba_read_{label}" for label in self.file_words]
        else:
            labels.append("readback_window")
        return sorted(labels)

    async def run(self) -> None:
        want_shut = sorted(p for p, v in self.want.items() if v == SHUT)
        want_open = sorted(p for p, v in self.want.items() if v == OPEN)
        self._log(
            f"SEED: RANDOM_SEED={self.seed} drawn walk order={self.order}; file={self.image} "
            f"image={self.state} SIP_DIS=0x{self.sip_dis:016x} SYS_DIS=0x{self.sys_dis:016x} "
            f"feat_want=0x{self.feat_want:016x} open={want_open} shut={want_shut}"
        )

        await self._mark(f"SETUP: {self.image}, wait for sep_fuse_sense_done_o")
        await self._setup()

        await self._mark("IMAGE: lc_state_o and lc_sigint_err_o")
        await RisingEdge(self.dut.clk_smu_i)
        lc = self._rd("lc_state_o")
        sigint = self._rd("lc_sigint_err_o")
        lc_want = lc_state_word(LC_RAW[self.state])
        pre = self.test.pre_sense
        self._log(
            f"CELL pre-sense samples={pre['samples']} lc_state_o={pre['lc']} "
            f"lcc_feat_ctrl_o={pre['feat']} (last clk_smu_i edge before sep_fuse_sense_done_o)"
        )
        self._log(
            f"OBSERVATION lcc_demote_state_1_o={self._rd('lcc_demote_state_1_o')} "
            f"lcc_demote_state_2_o={self._rd('lcc_demote_state_2_o')} "
            f"lcc_dbg_disable_o=0x{self._rd('lcc_dbg_disable_o'):04x} (measured and logged only)"
        )
        self.sb.expect_eq(
            f"CHK-LCVEC-IMAGE (a pre-sense sample, its lc_state_o and lcc_feat_ctrl_o) and "
            f"lc_state_o and lc_sigint_err_o after sensing, file={self.image} "
            f"pre_sense=0x{LC_STATE_PRESENSE:02x}",
            ((pre["samples"] > 0, pre["lc"], pre["feat"]), (lc, sigint)),
            ((True, LC_STATE_PRESENSE, FEAT_PRESENSE), (lc_want, 0)),
            evidence="CHK-LCVEC-IMAGE",
        )
        self._log_grade("CHK-LCVEC-IMAGE")

        await self._mark("FEATURE CONTROL: lcc_feat_ctrl_o")
        await RisingEdge(self.dut.clk_smu_i)
        self.feat_seen = self._rd("lcc_feat_ctrl_o")
        self.sb.expect_eq(
            f"CHK-LCVEC-FEAT lcc_feat_ctrl_o profile word of {self.state} with "
            f"SIP_DIS=0x{self.sip_dis:016x} SYS_DIS=0x{self.sys_dis:016x} file={self.image}",
            self.feat_seen,
            self.feat_want,
            evidence="CHK-LCVEC-FEAT",
        )
        self._log_grade("CHK-LCVEC-FEAT")

        for path in self.order:
            await self._mark(f"PATH {path} (Case {PATH_CASE[path]}), drawn order {self.order}")
            await self._walk(path)

        seen_shut = sorted(p for p, v in self.verdicts.items() if v == SHUT)
        seen_open = sorted(p for p, v in self.verdicts.items() if v == OPEN)
        detail = "; ".join(f"{p}: {self.details[p]}" for p in self.order)
        self.sb.expect_eq(
            f"CHK-LCVEC-SHUT paths that admit nothing, file={self.image}, drawn order "
            f"{self.order}; {detail}",
            (seen_shut, len(self.verdicts)),
            (want_shut, len(PATHS)),
            evidence="CHK-LCVEC-SHUT",
        )
        self._log_grade("CHK-LCVEC-SHUT")
        debug_bits = self.feat_seen & (DBG_1 | DBG_2)
        self.sb.expect_eq(
            f"CHK-LCVEC-OPEN paths that admit, file={self.image}, drawn order {self.order}; "
            f"debug bits of lcc_feat_ctrl_o=0x{debug_bits:012x} zero when no path is open",
            (seen_open, debug_bits == 0 if not want_open else True),
            (want_open, True),
            evidence="CHK-LCVEC-OPEN",
        )
        self._log_grade("CHK-LCVEC-OPEN")

        if self.readback:
            await self._mark("READ-BACK: LC_STATE, SIP_DIS and SYS_DIS over the system bus")
            got = await self._read_back()
            self.sb.expect_eq(
                f"CHK-LCVEC-READBACK system-bus words equal the words of {self.image}",
                got,
                self.file_words,
                evidence="CHK-LCVEC-READBACK",
            )
            self._log_grade("CHK-LCVEC-READBACK")
        else:
            await self._mark("READ-BACK PATH: the read-back request scans over the shut SEP STAP")
            obs, captured = await self._read_back_closed()
            self._log(f"OBSERVATION dmi words captured over the shut path {captured} (logged only)")
            self.sb.expect_eq(
                f"CHK-LCVEC-READBACK read-back request scans under {self.image} reach no SEP TAP: "
                f"(host TMS edges, host TMS levels, TDO-enable highs, PTAP TMS edges at least "
                f"{MIN_PTAP_TMS_EDGES})",
                (
                    obs["sep_edges"],
                    sorted(obs["levels"]),
                    obs["oen_highs"],
                    obs["ptap_edges"] >= MIN_PTAP_TMS_EDGES,
                ),
                (0, [0], 0, True),
                evidence="CHK-LCVEC-READBACK",
            )
            self._log_grade("CHK-LCVEC-READBACK")

        await self._finish_matrix(want_open)
        self.done = True

    async def _finish_matrix(self, want_open: list[str]) -> None:
        clk = self.dut.clk_smu_i
        await self._mark("TIMEOUT: bounded waits and last state")
        for rec in self.records:
            state = "EXPIRED" if rec["expired"] else "ok"
            self._log(
                f"TIMEOUT-PATH {rec['label']}: bound={rec['bound']} {rec['unit']} "
                f"used={rec['used']} {state} last={rec['last']}"
            )
        expired = sum(1 for rec in self.records if rec["expired"])
        self._log(f"CHK-TIMEOUT-PATHS: records={len(self.records)} expired={expired}")
        self.sb.expect_eq("expired TIMEOUT-PATH records", expired, 0, evidence="CHK-TIMEOUT-PATHS")
        self.sb.expect_eq(
            "bounded wait labels named by the steps, each exactly once",
            sorted(rec["label"] for rec in self.records),
            self._wait_labels(),
            evidence="CHK-TIMEOUT-PATHS",
        )

        await ClockCycles(clk, STEP_CLOCK_GAP)
        self.step_ts["PASS"] = get_sim_time("ns")
        order = [*self.step_names, "PASS"]
        text = " ".join(f"{k}={self.step_ts[k]:.2f}ns" for k in order)
        self._log(f"OBSERVATION step fence {text} (logged, not compared)")
        seen_shut = [p for p, v in self.verdicts.items() if v == SHUT]
        seen_open = [p for p, v in self.verdicts.items() if v == OPEN]
        counts = (
            len(self.verdicts),
            bool(seen_shut) == (self.image != READBACK_FILE),
            bool(seen_open) == bool(want_open),
        )
        self._log(f"CHK-NONVAC: verdicts {self.verdicts} file={self.image}")
        self.sb.expect_eq(
            f"CHK-NONVAC four paths walked, a shut path on every file but {READBACK_FILE}, an "
            f"open path on every file whose pair leaves a debug group open, file={self.image}",
            counts,
            (len(PATHS), True, True),
            evidence="CHK-NONVAC",
        )
