"""
DTP Functional Coverage Model for CocoTB

This module provides a comprehensive functional coverage model for the DTP
(Debug and Trace Port) verification environment. It tracks coverage of:
- JTAG instructions (mandatory, optional, undefined)
- TAP controller states and transitions
- CTP operation modes (Wire-OR, Point-to-Point)
- CTM source/destination routing
- IDCODE field values
- IJTAG SIB configurations
- STAP/3DCR network coverage (IEEE 1838)
- JTAG2AXI operations and responses
- Debug control features
- Cross coverage between different features
- Transitions and sequences

The coverage model is designed to be integrated into CocoTB tests to provide
visibility into verification completeness.

Author: Andrew Hsiao (ahsiao@tenstorrent.com)
"""

import cocotb
from cocotb.log import SimLog
from collections import defaultdict, OrderedDict
from dataclasses import dataclass, field
from typing import Dict, List, Set, Optional, Any, Tuple
from enum import Enum, IntEnum
import json
import time
from datetime import datetime

# Import DTP-specific enumerations
try:
    from .dtp_enum import (
        DTPJTAGInstr_e, DTPCTPMode_e, DTPJTAGIDCODE_s,
        DTPSIBState_e, DTPAXITarget_e, DTPAXIOpOnIssue_e, DTPAXIOpOnResponse_e,
        DTPSTAP3DCR_tms_hold_e, DTPSTAP3DCR_stap_sel_e, DTPSTAP3DCR_config_hold_e,
        DTPCTMDeviceType_e
    )
except ImportError:
    from dtp_enum import (
        DTPJTAGInstr_e, DTPCTPMode_e, DTPJTAGIDCODE_s,
        DTPSIBState_e, DTPAXITarget_e, DTPAXIOpOnIssue_e, DTPAXIOpOnResponse_e,
        DTPSTAP3DCR_tms_hold_e, DTPSTAP3DCR_stap_sel_e, DTPSTAP3DCR_config_hold_e,
        DTPCTMDeviceType_e
    )


# ==============================================================================
# JTAG Instruction Categories
# ==============================================================================

class JTAGInstrCategory_e(IntEnum):
    """JTAG Instruction Categories per IEEE 1149.1"""
    MANDATORY = 0       # BYPASS, IDCODE, SAMPLE/PRELOAD
    OPTIONAL = 1        # EXTEST, INTEST, CLAMP, HIGHZ, RUNBIST
    DEBUG = 2           # DEBUG_CONTROL, JTAG_CAPS
    IJTAG = 3           # SELECT_IJTAG
    JTAG2AXI = 4        # AXI_SINGLE_OP, AXI_SERIES_*
    IEEE_1838 = 5       # TAP_3DCR, TMP_STATUS, IC_RESET
    UNDEFINED = 6       # Undefined instructions (treated as BYPASS)
    RESERVED = 7        # Reserved for RISC-V debug


# Instruction to category mapping
JTAG_INSTR_CATEGORIES = {
    # Mandatory IEEE 1149.1 instructions
    DTPJTAGInstr_e.BYPASS_00: JTAGInstrCategory_e.MANDATORY,
    DTPJTAGInstr_e.BYPASS_3F: JTAGInstrCategory_e.MANDATORY,
    DTPJTAGInstr_e.IDCODE: JTAGInstrCategory_e.MANDATORY,
    DTPJTAGInstr_e.SAMPLE_PRELOAD: JTAGInstrCategory_e.MANDATORY,

    # Optional IEEE 1149.1 instructions
    DTPJTAGInstr_e.EXTEST: JTAGInstrCategory_e.OPTIONAL,
    DTPJTAGInstr_e.EXTEST_TRAIN: JTAGInstrCategory_e.OPTIONAL,
    DTPJTAGInstr_e.EXTEST_PULSE: JTAGInstrCategory_e.OPTIONAL,
    DTPJTAGInstr_e.CLAMP: JTAGInstrCategory_e.OPTIONAL,
    DTPJTAGInstr_e.HIGHZ: JTAGInstrCategory_e.OPTIONAL,
    DTPJTAGInstr_e.INTEST: JTAGInstrCategory_e.OPTIONAL,
    DTPJTAGInstr_e.CLAMP_HOLD: JTAGInstrCategory_e.OPTIONAL,
    DTPJTAGInstr_e.CLAMP_RELEASE: JTAGInstrCategory_e.OPTIONAL,
    DTPJTAGInstr_e.RUNBIST: JTAGInstrCategory_e.OPTIONAL,
    DTPJTAGInstr_e.ZERO_LENGTH_BYPASS: JTAGInstrCategory_e.OPTIONAL,
    DTPJTAGInstr_e.INV_BYPASS: JTAGInstrCategory_e.OPTIONAL,

    # IEEE 1838 (3DIC) instructions
    DTPJTAGInstr_e.TAP_3DCR: JTAGInstrCategory_e.IEEE_1838,
    DTPJTAGInstr_e.TMP_STATUS: JTAGInstrCategory_e.IEEE_1838,
    DTPJTAGInstr_e.IC_RESET: JTAGInstrCategory_e.IEEE_1838,

    # Debug instructions
    DTPJTAGInstr_e.DEBUG_CONTROL: JTAGInstrCategory_e.DEBUG,
    DTPJTAGInstr_e.JTAG_CAPS: JTAGInstrCategory_e.DEBUG,

    # IJTAG (IEEE 1687) instructions
    DTPJTAGInstr_e.SELECT_IJTAG: JTAGInstrCategory_e.IJTAG,

    # JTAG2AXI instructions
    DTPJTAGInstr_e.SMC_OTP_JTAG2AXI_CAPS: JTAGInstrCategory_e.JTAG2AXI,
    DTPJTAGInstr_e.SMC_OTP_AXI_SINGLE_OP: JTAGInstrCategory_e.JTAG2AXI,
    DTPJTAGInstr_e.SMC_OTP_AXI_SERIES_CTRL: JTAGInstrCategory_e.JTAG2AXI,
    DTPJTAGInstr_e.SMC_OTP_AXI_SERIES_DATA_INCR: JTAGInstrCategory_e.JTAG2AXI,
    DTPJTAGInstr_e.SMC_OTP_AXI_SERIES_DATA_NO_INCR: JTAGInstrCategory_e.JTAG2AXI,
    DTPJTAGInstr_e.SMC_OTP_AXI_SERIES_DATA_WITH_ERROR_STATUS: JTAGInstrCategory_e.JTAG2AXI,
    DTPJTAGInstr_e.SEP_OTP_JTAG2AXI_CAPS: JTAGInstrCategory_e.JTAG2AXI,
    DTPJTAGInstr_e.SEP_OTP_AXI_SINGLE_OP: JTAGInstrCategory_e.JTAG2AXI,
    DTPJTAGInstr_e.SEP_OTP_AXI_SERIES_CTRL: JTAGInstrCategory_e.JTAG2AXI,
    DTPJTAGInstr_e.SEP_OTP_AXI_SERIES_DATA_INCR: JTAGInstrCategory_e.JTAG2AXI,
    DTPJTAGInstr_e.SEP_OTP_AXI_SERIES_DATA_NO_INCR: JTAGInstrCategory_e.JTAG2AXI,
    DTPJTAGInstr_e.SEP_OTP_AXI_SERIES_DATA_WITH_ERROR_STATUS: JTAGInstrCategory_e.JTAG2AXI,
    DTPJTAGInstr_e.SMC_JTAG2AXI_CAPS: JTAGInstrCategory_e.JTAG2AXI,
    DTPJTAGInstr_e.SMC_AXI_SINGLE_OP: JTAGInstrCategory_e.JTAG2AXI,
    DTPJTAGInstr_e.SMC_AXI_SERIES_CTRL: JTAGInstrCategory_e.JTAG2AXI,
    DTPJTAGInstr_e.SMC_AXI_SERIES_DATA_INCR: JTAGInstrCategory_e.JTAG2AXI,
    DTPJTAGInstr_e.SMC_AXI_SERIES_DATA_NO_INCR: JTAGInstrCategory_e.JTAG2AXI,
    DTPJTAGInstr_e.SMC_AXI_SERIES_DATA_WITH_ERROR_STATUS: JTAGInstrCategory_e.JTAG2AXI,

    # RISC-V Reserved
    DTPJTAGInstr_e.RISCV_RESERVED_0: JTAGInstrCategory_e.RESERVED,
    DTPJTAGInstr_e.RISCV_RESERVED_1: JTAGInstrCategory_e.RESERVED,
    DTPJTAGInstr_e.RISCV_RESERVED_2: JTAGInstrCategory_e.RESERVED,
    DTPJTAGInstr_e.RISCV_RESERVED_3: JTAGInstrCategory_e.RESERVED,
    DTPJTAGInstr_e.RISCV_RESERVED_4: JTAGInstrCategory_e.RESERVED,
    DTPJTAGInstr_e.RISCV_RESERVED_5: JTAGInstrCategory_e.RESERVED,
    DTPJTAGInstr_e.RISCV_RESERVED_6: JTAGInstrCategory_e.RESERVED,
    DTPJTAGInstr_e.RISCV_RESERVED_7: JTAGInstrCategory_e.RESERVED,

    # Undefined (treated as BYPASS)
    DTPJTAGInstr_e.UNDEFINED_AS_BYPASS_0F: JTAGInstrCategory_e.UNDEFINED,
    DTPJTAGInstr_e.UNDEFINED_AS_BYPASS_2D: JTAGInstrCategory_e.UNDEFINED,
    DTPJTAGInstr_e.UNDEFINED_AS_BYPASS_2E: JTAGInstrCategory_e.UNDEFINED,
    DTPJTAGInstr_e.UNDEFINED_AS_BYPASS_2F: JTAGInstrCategory_e.UNDEFINED,
    DTPJTAGInstr_e.UNDEFINED_AS_BYPASS_30: JTAGInstrCategory_e.UNDEFINED,
    DTPJTAGInstr_e.UNDEFINED_AS_BYPASS_31: JTAGInstrCategory_e.UNDEFINED,
    DTPJTAGInstr_e.UNDEFINED_AS_BYPASS_32: JTAGInstrCategory_e.UNDEFINED,
    DTPJTAGInstr_e.UNDEFINED_AS_BYPASS_33: JTAGInstrCategory_e.UNDEFINED,
    DTPJTAGInstr_e.UNDEFINED_AS_BYPASS_34: JTAGInstrCategory_e.UNDEFINED,
    DTPJTAGInstr_e.UNDEFINED_AS_BYPASS_35: JTAGInstrCategory_e.UNDEFINED,
    DTPJTAGInstr_e.UNDEFINED_AS_BYPASS_36: JTAGInstrCategory_e.UNDEFINED,
    DTPJTAGInstr_e.UNDEFINED_AS_BYPASS_37: JTAGInstrCategory_e.UNDEFINED,
    DTPJTAGInstr_e.UNDEFINED_AS_BYPASS_38: JTAGInstrCategory_e.UNDEFINED,
    DTPJTAGInstr_e.UNDEFINED_AS_BYPASS_39: JTAGInstrCategory_e.UNDEFINED,
    DTPJTAGInstr_e.UNDEFINED_AS_BYPASS_3A: JTAGInstrCategory_e.UNDEFINED,
    DTPJTAGInstr_e.UNDEFINED_AS_BYPASS_3B: JTAGInstrCategory_e.UNDEFINED,
    DTPJTAGInstr_e.UNDEFINED_AS_BYPASS_3C: JTAGInstrCategory_e.UNDEFINED,
}


# TAP State Transitions (per IEEE 1149.1)
TAP_STATE_TRANSITIONS = {
    "TEST_LOGIC_RESET": {"0": "RUN_TEST_IDLE", "1": "TEST_LOGIC_RESET"},
    "RUN_TEST_IDLE": {"0": "RUN_TEST_IDLE", "1": "SELECT_DR_SCAN"},
    "SELECT_DR_SCAN": {"0": "CAPTURE_DR", "1": "SELECT_IR_SCAN"},
    "CAPTURE_DR": {"0": "SHIFT_DR", "1": "EXIT1_DR"},
    "SHIFT_DR": {"0": "SHIFT_DR", "1": "EXIT1_DR"},
    "EXIT1_DR": {"0": "PAUSE_DR", "1": "UPDATE_DR"},
    "PAUSE_DR": {"0": "PAUSE_DR", "1": "EXIT2_DR"},
    "EXIT2_DR": {"0": "SHIFT_DR", "1": "UPDATE_DR"},
    "UPDATE_DR": {"0": "RUN_TEST_IDLE", "1": "SELECT_DR_SCAN"},
    "SELECT_IR_SCAN": {"0": "CAPTURE_IR", "1": "TEST_LOGIC_RESET"},
    "CAPTURE_IR": {"0": "SHIFT_IR", "1": "EXIT1_IR"},
    "SHIFT_IR": {"0": "SHIFT_IR", "1": "EXIT1_IR"},
    "EXIT1_IR": {"0": "PAUSE_IR", "1": "UPDATE_IR"},
    "PAUSE_IR": {"0": "PAUSE_IR", "1": "EXIT2_IR"},
    "EXIT2_IR": {"0": "SHIFT_IR", "1": "UPDATE_IR"},
    "UPDATE_IR": {"0": "RUN_TEST_IDLE", "1": "SELECT_DR_SCAN"},
}


# ==============================================================================
# Coverage Point Data Structures
# ==============================================================================

@dataclass
class CoverageBin:
    """Represents a single coverage bin"""
    name: str
    hit_count: int = 0
    goal: int = 1

    @property
    def is_covered(self) -> bool:
        """Check if bin has been hit at least goal times"""
        return self.hit_count >= self.goal

    @property
    def coverage_percent(self) -> float:
        """Get coverage percentage for this bin"""
        return min(100.0, (self.hit_count / self.goal) * 100.0)

    def hit(self, count: int = 1):
        """Increment hit count"""
        self.hit_count += count


@dataclass
class CoveragePoint:
    """Represents a coverage point with multiple bins"""
    name: str
    description: str
    bins: Dict[Any, CoverageBin] = field(default_factory=dict)
    enabled: bool = True

    def add_bin(self, bin_name: Any, goal: int = 1):
        """Add a bin to this coverage point"""
        if bin_name not in self.bins:
            self.bins[bin_name] = CoverageBin(name=str(bin_name), goal=goal)

    def hit(self, bin_name: Any, count: int = 1):
        """Record a hit on a specific bin"""
        if not self.enabled:
            return

        if bin_name not in self.bins:
            self.add_bin(bin_name)

        self.bins[bin_name].hit(count)

    @property
    def coverage_percent(self) -> float:
        """Calculate coverage percentage"""
        if not self.bins:
            return 0.0

        covered = sum(1 for b in self.bins.values() if b.is_covered)
        return (covered / len(self.bins)) * 100.0

    @property
    def hit_bins(self) -> int:
        """Get number of hit bins"""
        return sum(1 for b in self.bins.values() if b.is_covered)

    @property
    def total_bins(self) -> int:
        """Get total number of bins"""
        return len(self.bins)


@dataclass
class CrossCoveragePoint:
    """Represents cross coverage between two coverage points"""
    name: str
    description: str
    point1_name: str
    point2_name: str
    bins: Dict[Tuple[Any, Any], CoverageBin] = field(default_factory=dict)
    enabled: bool = True

    def add_cross_bin(self, bin1: Any, bin2: Any, goal: int = 1):
        """Add a cross coverage bin"""
        key = (bin1, bin2)
        if key not in self.bins:
            name = f"{bin1} x {bin2}"
            self.bins[key] = CoverageBin(name=name, goal=goal)

    def hit(self, bin1: Any, bin2: Any, count: int = 1):
        """Record a hit on cross coverage"""
        if not self.enabled:
            return

        key = (bin1, bin2)
        if key not in self.bins:
            self.add_cross_bin(bin1, bin2)

        self.bins[key].hit(count)

    @property
    def coverage_percent(self) -> float:
        """Calculate coverage percentage"""
        if not self.bins:
            return 0.0

        covered = sum(1 for b in self.bins.values() if b.is_covered)
        return (covered / len(self.bins)) * 100.0

    @property
    def hit_bins(self) -> int:
        """Get number of hit bins"""
        return sum(1 for b in self.bins.values() if b.is_covered)

    @property
    def total_bins(self) -> int:
        """Get total number of bins"""
        return len(self.bins)


# ==============================================================================
# DTP Functional Coverage Model
# ==============================================================================

class DTPFunctionalCoverage:
    """
    Comprehensive functional coverage model for DTP verification

    Tracks coverage of:
    - JTAG instructions executed
    - TAP controller states visited
    - CTP operation modes used
    - IDCODE field values seen
    - Instruction-State cross coverage
    - Mode transitions
    - Scan lengths
    """

    def __init__(self, name: str = "DTP_Coverage"):
        """Initialize the coverage model"""
        self.name = name
        self.log = SimLog(f"cocotb.{name}")

        # Coverage points
        self.coverpoints: Dict[str, CoveragePoint] = OrderedDict()
        self.cross_coverpoints: Dict[str, CrossCoveragePoint] = OrderedDict()

        # Tracking variables
        self.last_instruction: Optional[int] = None
        self.last_tap_state: Optional[str] = None
        self.last_ctp_mode: Optional[int] = None

        # Statistics
        self.start_time = time.time()
        self.total_samples = 0

        # Initialize coverage points
        self._init_jtag_instruction_coverage()
        self._init_jtag_instruction_category_coverage()
        self._init_tap_state_coverage()
        self._init_tap_state_transition_coverage()
        self._init_ctp_mode_coverage()
        self._init_ctm_coverage()
        self._init_idcode_coverage()
        self._init_scan_length_coverage()
        self._init_ijtag_sib_coverage()
        self._init_stap_3dcr_coverage()
        self._init_jtag2axi_coverage()
        self._init_debug_control_coverage()
        self._init_runbist_security_coverage()
        self._init_cross_coverage()

        self.log.info(f"{self.name}: Functional coverage model initialized")

    # --------------------------------------------------------------------------
    # Coverage Point Initialization
    # --------------------------------------------------------------------------

    def _init_jtag_instruction_coverage(self):
        """Initialize JTAG instruction coverage"""
        cp = CoveragePoint(
            name="jtag_instruction",
            description="JTAG instruction coverage"
        )

        # Add bins for all JTAG instructions
        for instr in DTPJTAGInstr_e:
            cp.add_bin(instr.value, goal=1)

        self.coverpoints["jtag_instruction"] = cp

    def _init_tap_state_coverage(self):
        """Initialize TAP state coverage"""
        cp = CoveragePoint(
            name="tap_state",
            description="TAP controller state coverage"
        )

        # Add bins for all TAP states
        tap_states = [
            "TEST_LOGIC_RESET",
            "RUN_TEST_IDLE",
            "SELECT_DR_SCAN",
            "CAPTURE_DR",
            "SHIFT_DR",
            "EXIT1_DR",
            "PAUSE_DR",
            "EXIT2_DR",
            "UPDATE_DR",
            "SELECT_IR_SCAN",
            "CAPTURE_IR",
            "SHIFT_IR",
            "EXIT1_IR",
            "PAUSE_IR",
            "EXIT2_IR",
            "UPDATE_IR"
        ]

        for state in tap_states:
            cp.add_bin(state, goal=1)

        self.coverpoints["tap_state"] = cp

    def _init_ctp_mode_coverage(self):
        """Initialize CTP mode coverage"""
        cp = CoveragePoint(
            name="ctp_mode",
            description="CTP operation mode coverage"
        )

        # Add bins for CTP modes
        cp.add_bin(DTPCTPMode_e.WIRE_OR, goal=1)
        cp.add_bin(DTPCTPMode_e.POINT_TO_POINT, goal=1)

        self.coverpoints["ctp_mode"] = cp

    def _init_idcode_coverage(self):
        """Initialize IDCODE field coverage"""
        # IDCODE value coverage
        cp_value = CoveragePoint(
            name="idcode_value",
            description="IDCODE value coverage"
        )
        # Dynamic bins will be added as IDCODE values are seen
        self.coverpoints["idcode_value"] = cp_value

        # IDCODE version coverage. The version field is a hardwired constant in
        # this integration, so only the architected version is reachable. Use
        # dynamic bins (added on sample) rather than enumerating all 16 codes.
        cp_version = CoveragePoint(
            name="idcode_version",
            description="IDCODE version field coverage"
        )
        self.coverpoints["idcode_version"] = cp_version

        # IDCODE LSB coverage. LSB is always 1 per IEEE 1149.1; only pre-add the
        # valid bin. A 0 would dynamically appear and flag a real defect.
        cp_lsb = CoveragePoint(
            name="idcode_lsb",
            description="IDCODE LSB validity coverage"
        )
        cp_lsb.add_bin(1, goal=1)  # Valid LSB (always 1)
        self.coverpoints["idcode_lsb"] = cp_lsb

    def _init_scan_length_coverage(self):
        """Initialize scan length coverage"""
        # IR scan length
        cp_ir = CoveragePoint(
            name="ir_scan_length",
            description="IR scan length coverage"
        )
        # Architected IR widths (7/10/16 do not exist in the DTP TAP/STAP)
        for width in [4, 5, 6, 8]:
            cp_ir.add_bin(width, goal=1)
        self.coverpoints["ir_scan_length"] = cp_ir

        # DR scan length
        cp_dr = CoveragePoint(
            name="dr_scan_length",
            description="DR scan length coverage"
        )
        # Common DR widths
        for width in [1, 8, 16, 32, 64, 128]:
            cp_dr.add_bin(width, goal=1)
        self.coverpoints["dr_scan_length"] = cp_dr

    def _init_jtag_instruction_category_coverage(self):
        """Initialize JTAG instruction category coverage"""
        cp = CoveragePoint(
            name="jtag_instr_category",
            description="JTAG instruction category coverage"
        )

        for category in JTAGInstrCategory_e:
            cp.add_bin(category.name, goal=1)

        self.coverpoints["jtag_instr_category"] = cp

    def _init_tap_state_transition_coverage(self):
        """Initialize TAP state transition coverage"""
        cp = CoveragePoint(
            name="tap_state_transition",
            description="TAP controller state transition coverage"
        )

        # Add bins for all valid transitions
        for from_state, transitions in TAP_STATE_TRANSITIONS.items():
            for tms_value, to_state in transitions.items():
                transition_name = f"{from_state}_to_{to_state}_TMS{tms_value}"
                cp.add_bin(transition_name, goal=1)

        self.coverpoints["tap_state_transition"] = cp

    def _init_ctm_coverage(self):
        """Initialize Cross Trigger Matrix (CTM) coverage"""
        # CTM source port coverage
        cp_src = CoveragePoint(
            name="ctm_source",
            description="CTM source port coverage"
        )
        # Ports 0-15: External CTP, Ports 16-24: Internal CLA
        for port in range(25):
            if port < 16:
                cp_src.add_bin(f"CTP_{port}", goal=1)
            else:
                cp_src.add_bin(f"CLA_{port-16}", goal=1)
        self.coverpoints["ctm_source"] = cp_src

        # CTM destination port coverage
        cp_dst = CoveragePoint(
            name="ctm_destination",
            description="CTM destination port coverage"
        )
        for port in range(25):
            if port < 16:
                cp_dst.add_bin(f"CTP_{port}", goal=1)
            else:
                cp_dst.add_bin(f"CLA_{port-16}", goal=1)
        self.coverpoints["ctm_destination"] = cp_dst

        # CTM routing direction coverage
        cp_dir = CoveragePoint(
            name="ctm_routing_direction",
            description="CTM routing direction coverage"
        )
        cp_dir.add_bin("CTP_to_CLA", goal=1)  # External to Internal
        cp_dir.add_bin("CLA_to_CTP", goal=1)  # Internal to External
        cp_dir.add_bin("CTP_to_CTP", goal=1)  # External to External
        cp_dir.add_bin("CLA_to_CLA", goal=1)  # Internal to Internal
        self.coverpoints["ctm_routing_direction"] = cp_dir

    def _init_ijtag_sib_coverage(self):
        """Initialize IJTAG SIB (Segment Insertion Bit) coverage - IEEE 1687"""
        # Individual SIB state coverage
        sib_names = ["SEC_DFT_SIB", "DFT_SIB", "DFD_SIB"]

        for sib_name in sib_names:
            cp = CoveragePoint(
                name=f"{sib_name.lower()}_state",
                description=f"{sib_name} state coverage"
            )
            cp.add_bin("OFF", goal=1)
            cp.add_bin("ON", goal=1)
            self.coverpoints[f"{sib_name.lower()}_state"] = cp

        # SIB configuration pattern coverage
        cp_pattern = CoveragePoint(
            name="ijtag_sib_pattern",
            description="IJTAG SIB configuration pattern coverage"
        )
        # All 8 patterns for 3 SIBs (SEC_DFT, DFT, DFD).
        # Hardware does not enforce mutual exclusion — both SEC_DFT and DFT can be ON simultaneously.
        for sec_dft in [0, 1]:
            for dft in [0, 1]:
                for dfd in [0, 1]:
                    pattern = f"SEC_DFT_{sec_dft}_DFT_{dft}_DFD_{dfd}"
                    cp_pattern.add_bin(pattern, goal=1)
        self.coverpoints["ijtag_sib_pattern"] = cp_pattern

    def _init_stap_3dcr_coverage(self):
        """Initialize STAP/3DCR network coverage - IEEE 1838"""
        # STAP type coverage
        cp_stap_type = CoveragePoint(
            name="stap_type",
            description="STAP type coverage"
        )
        cp_stap_type.add_bin("DOWNSTREAM", goal=1)
        cp_stap_type.add_bin("SEP", goal=1)
        cp_stap_type.add_bin("EXTRA", goal=1)
        self.coverpoints["stap_type"] = cp_stap_type

        # 3DCR TMS Hold coverage
        cp_tms_hold = CoveragePoint(
            name="3dcr_tms_hold",
            description="3DCR TMS Hold bit coverage"
        )
        cp_tms_hold.add_bin(0, goal=1)  # TMS not held
        cp_tms_hold.add_bin(1, goal=1)  # TMS held
        self.coverpoints["3dcr_tms_hold"] = cp_tms_hold

        # 3DCR STAP Select coverage
        cp_stap_sel = CoveragePoint(
            name="3dcr_stap_sel",
            description="3DCR STAP Select bit coverage"
        )
        cp_stap_sel.add_bin(0, goal=1)  # STAP not selected
        cp_stap_sel.add_bin(1, goal=1)  # STAP selected
        self.coverpoints["3dcr_stap_sel"] = cp_stap_sel

        # 3DCR Config Hold coverage (IEEE 1838 Section 5.5.3)
        cp_config_hold = CoveragePoint(
            name="3dcr_config_hold",
            description="3DCR Config Hold bit coverage"
        )
        cp_config_hold.add_bin(0, goal=1)  # Config cleared on TLR
        cp_config_hold.add_bin(1, goal=1)  # Config preserved on TLR
        self.coverpoints["3dcr_config_hold"] = cp_config_hold

        # STAP SIB state coverage
        cp_stap_sib = CoveragePoint(
            name="stap_sib_state",
            description="STAP SIB state coverage"
        )
        cp_stap_sib.add_bin("OFF", goal=1)
        cp_stap_sib.add_bin("ON", goal=1)
        self.coverpoints["stap_sib_state"] = cp_stap_sib

    def _init_jtag2axi_coverage(self):
        """Initialize JTAG2AXI operation coverage"""
        # AXI target coverage
        cp_target = CoveragePoint(
            name="jtag2axi_target",
            description="JTAG2AXI target coverage"
        )
        for target in DTPAXITarget_e:
            cp_target.add_bin(target.name, goal=1)
        self.coverpoints["jtag2axi_target"] = cp_target

        # AXI operation type coverage
        cp_op = CoveragePoint(
            name="jtag2axi_operation",
            description="JTAG2AXI operation type coverage"
        )
        for op in DTPAXIOpOnIssue_e:
            if op != DTPAXIOpOnIssue_e.RESERVED:  # illegal opcode
                cp_op.add_bin(op.name, goal=1)
        self.coverpoints["jtag2axi_operation"] = cp_op

        # AXI response type coverage
        cp_resp = CoveragePoint(
            name="jtag2axi_response",
            description="JTAG2AXI response type coverage"
        )
        # BACKPRESSURE is an issue-time placeholder (response_valid=0); the
        # response path only yields OKAY/SLVERR/DECERR, so it is unreachable.
        for resp in DTPAXIOpOnResponse_e:
            if resp != DTPAXIOpOnResponse_e.BACKPRESSURE:
                cp_resp.add_bin(resp.name, goal=1)
        self.coverpoints["jtag2axi_response"] = cp_resp

        # AXI size coverage
        cp_size = CoveragePoint(
            name="jtag2axi_size",
            description="JTAG2AXI data size coverage"
        )
        # Size field is 2 bits wide (DATA_WIDTH<=64): only 0=1B,1=2B,2=4B,3=8B.
        for size in range(4):
            cp_size.add_bin(f"{2**size}B", goal=1)
        self.coverpoints["jtag2axi_size"] = cp_size

        # AXI series operation mode coverage
        cp_series = CoveragePoint(
            name="jtag2axi_series_mode",
            description="JTAG2AXI series operation mode coverage"
        )
        cp_series.add_bin("SINGLE_OP", goal=1)
        cp_series.add_bin("SERIES_INCR", goal=1)
        cp_series.add_bin("SERIES_NO_INCR", goal=1)
        cp_series.add_bin("SERIES_WITH_ERROR", goal=1)
        self.coverpoints["jtag2axi_series_mode"] = cp_series

        # 4K Boundary crossing coverage
        cp_4k = CoveragePoint(
            name="jtag2axi_4k_boundary",
            description="JTAG2AXI 4K boundary crossing coverage"
        )
        cp_4k.add_bin("WITHIN_PAGE", goal=1)
        cp_4k.add_bin("CROSSING_PAGE", goal=1)
        self.coverpoints["jtag2axi_4k_boundary"] = cp_4k

    def _init_debug_control_coverage(self):
        """Initialize Debug Control coverage"""
        # Boot stall coverage
        cp_boot_stall = CoveragePoint(
            name="debug_boot_stall",
            description="Debug boot stall coverage"
        )
        cp_boot_stall.add_bin(0, goal=1)  # Boot stall disabled
        cp_boot_stall.add_bin(1, goal=1)  # Boot stall enabled
        self.coverpoints["debug_boot_stall"] = cp_boot_stall

        # Boot stall override coverage
        cp_boot_stall_ovrd = CoveragePoint(
            name="debug_boot_stall_ovrd",
            description="Debug boot stall override coverage"
        )
        cp_boot_stall_ovrd.add_bin(0, goal=1)  # Override disabled
        cp_boot_stall_ovrd.add_bin(1, goal=1)  # Override enabled
        self.coverpoints["debug_boot_stall_ovrd"] = cp_boot_stall_ovrd

        # Clock stop coverage
        cp_jtag_clk_stop = CoveragePoint(
            name="debug_jtag_clock_stop",
            description="Debug JTAG clock stop coverage"
        )
        cp_jtag_clk_stop.add_bin(0, goal=1)  # Clock running
        cp_jtag_clk_stop.add_bin(1, goal=1)  # Clock stopped
        self.coverpoints["debug_jtag_clock_stop"] = cp_jtag_clk_stop

        cp_cla_clk_stop = CoveragePoint(
            name="debug_cla_clock_stop",
            description="Debug CLA clock stop coverage"
        )
        cp_cla_clk_stop.add_bin(0, goal=1)  # Clock running
        cp_cla_clk_stop.add_bin(1, goal=1)  # Clock stopped
        self.coverpoints["debug_cla_clock_stop"] = cp_cla_clk_stop

        # CLA clock stop enable coverage
        cp_cla_clk_stop_en = CoveragePoint(
            name="debug_cla_clock_stop_en",
            description="Debug CLA clock stop enable coverage"
        )
        cp_cla_clk_stop_en.add_bin(0, goal=1)  # CLA clock stop disabled
        cp_cla_clk_stop_en.add_bin(1, goal=1)  # CLA clock stop enabled
        self.coverpoints["debug_cla_clock_stop_en"] = cp_cla_clk_stop_en

    def _init_runbist_security_coverage(self):
        """Initialize RUNBIST security gating coverage"""
        cp = CoveragePoint(
            name="runbist_security",
            description="RUNBIST non-secure DFT SIB gating by active-high feat_ctrl_i enables"
        )
        cp.add_bin("RUNBIST_UNGATED", goal=1)   # RUNBIST executes normally with required enables high
        cp.add_bin("RUNBIST_GATED", goal=1)     # RUNBIST DFT SIB blocked by a required enable low
        cp.add_bin("RUNBIST_RESTORED", goal=1)  # RUNBIST re-enabled after required enables restored
        self.coverpoints["runbist_security"] = cp

    def _init_cross_coverage(self):
        """Initialize cross coverage points"""
        # Instruction x State cross coverage
        cross_instr_state = CrossCoveragePoint(
            name="instruction_x_state",
            description="JTAG instruction and TAP state cross coverage",
            point1_name="jtag_instruction",
            point2_name="tap_state"
        )
        self.cross_coverpoints["instruction_x_state"] = cross_instr_state

        # Mode transition coverage
        cross_mode_trans = CrossCoveragePoint(
            name="ctp_mode_transition",
            description="CTP mode transition coverage",
            point1_name="ctp_mode_prev",
            point2_name="ctp_mode_curr"
        )
        # Add expected transitions. Sampled only on a mode change, so the
        # same->same diagonal can never occur and is excluded.
        modes = [DTPCTPMode_e.WIRE_OR, DTPCTPMode_e.POINT_TO_POINT]
        for mode1 in modes:
            for mode2 in modes:
                if mode1 != mode2:
                    cross_mode_trans.add_cross_bin(mode1, mode2, goal=1)
        self.cross_coverpoints["ctp_mode_transition"] = cross_mode_trans

        # JTAG2AXI Target x Operation cross coverage
        cross_target_op = CrossCoveragePoint(
            name="jtag2axi_target_x_op",
            description="JTAG2AXI target and operation cross coverage",
            point1_name="jtag2axi_target",
            point2_name="jtag2axi_operation"
        )
        for target in DTPAXITarget_e:
            for op in DTPAXIOpOnIssue_e:
                if op != DTPAXIOpOnIssue_e.RESERVED:  # Skip reserved
                    cross_target_op.add_cross_bin(target.name, op.name, goal=1)
        self.cross_coverpoints["jtag2axi_target_x_op"] = cross_target_op

        # JTAG2AXI Operation x Response cross coverage
        cross_op_resp = CrossCoveragePoint(
            name="jtag2axi_op_x_response",
            description="JTAG2AXI operation and response cross coverage",
            point1_name="jtag2axi_operation",
            point2_name="jtag2axi_response"
        )
        for op in [DTPAXIOpOnIssue_e.READ, DTPAXIOpOnIssue_e.WRITE]:
            for resp in DTPAXIOpOnResponse_e:
                if resp != DTPAXIOpOnResponse_e.BACKPRESSURE:  # unreachable
                    cross_op_resp.add_cross_bin(op.name, resp.name, goal=1)
        self.cross_coverpoints["jtag2axi_op_x_response"] = cross_op_resp

        # CTM Source Type x Destination Type cross coverage
        cross_ctm_dir = CrossCoveragePoint(
            name="ctm_src_x_dst_type",
            description="CTM source and destination type cross coverage",
            point1_name="ctm_src_type",
            point2_name="ctm_dst_type"
        )
        for src in ["CTP", "CLA"]:
            for dst in ["CTP", "CLA"]:
                cross_ctm_dir.add_cross_bin(src, dst, goal=1)
        self.cross_coverpoints["ctm_src_x_dst_type"] = cross_ctm_dir

        # CTP Mode x CTM Routing cross coverage
        cross_ctp_mode_ctm = CrossCoveragePoint(
            name="ctp_mode_x_ctm_routing",
            description="CTP mode and CTM routing direction cross coverage",
            point1_name="ctp_mode",
            point2_name="ctm_routing_direction"
        )
        for mode in [DTPCTPMode_e.WIRE_OR, DTPCTPMode_e.POINT_TO_POINT]:
            for direction in ["CTP_to_CLA", "CLA_to_CTP", "CTP_to_CTP", "CLA_to_CLA"]:
                cross_ctp_mode_ctm.add_cross_bin(mode, direction, goal=1)
        self.cross_coverpoints["ctp_mode_x_ctm_routing"] = cross_ctp_mode_ctm

        # STAP Type x 3DCR Config cross coverage
        cross_stap_3dcr = CrossCoveragePoint(
            name="stap_type_x_3dcr_config",
            description="STAP type and 3DCR configuration cross coverage",
            point1_name="stap_type",
            point2_name="3dcr_config"
        )
        for stap in ["DOWNSTREAM", "SEP", "EXTRA"]:
            for config_hold in [0, 1]:
                for stap_sel in [0, 1]:
                    config_name = f"CH{config_hold}_SS{stap_sel}"
                    cross_stap_3dcr.add_cross_bin(stap, config_name, goal=1)
        self.cross_coverpoints["stap_type_x_3dcr_config"] = cross_stap_3dcr

        # Instruction Category x TAP State cross coverage
        cross_cat_state = CrossCoveragePoint(
            name="instr_category_x_tap_state",
            description="Instruction category and TAP state cross coverage",
            point1_name="jtag_instr_category",
            point2_name="tap_state"
        )
        self.cross_coverpoints["instr_category_x_tap_state"] = cross_cat_state

    # --------------------------------------------------------------------------
    # Coverage Sampling Methods
    # --------------------------------------------------------------------------

    def sample_jtag_instruction(self, instruction: int):
        """
        Sample JTAG instruction coverage

        Args:
            instruction: JTAG instruction value
        """
        self.coverpoints["jtag_instruction"].hit(instruction)
        self.last_instruction = instruction
        self.total_samples += 1

        # Also sample instruction category
        self.sample_jtag_instruction_category(instruction)

        self.log.debug(f"Sampled JTAG instruction: 0x{instruction:04X}")

    def sample_tap_state(self, state: str):
        """
        Sample TAP state coverage

        Args:
            state: TAP state name
        """
        self.coverpoints["tap_state"].hit(state)

        # Cross coverage with instruction
        if self.last_instruction is not None:
            self.cross_coverpoints["instruction_x_state"].hit(
                self.last_instruction, state
            )

            # Cross coverage with instruction category
            try:
                instr_enum = DTPJTAGInstr_e(self.last_instruction)
                if instr_enum in JTAG_INSTR_CATEGORIES:
                    category = JTAG_INSTR_CATEGORIES[instr_enum]
                    self.cross_coverpoints["instr_category_x_tap_state"].hit(
                        category.name, state
                    )
            except ValueError:
                pass

        self.last_tap_state = state
        self.total_samples += 1

        self.log.debug(f"Sampled TAP state: {state}")

    def sample_ctp_mode(self, mode: int):
        """
        Sample CTP mode coverage

        Args:
            mode: CTP mode value (0=WIRE_OR, 1=POINT_TO_POINT)
        """
        self.coverpoints["ctp_mode"].hit(mode)

        # Mode transition coverage
        if self.last_ctp_mode is not None and self.last_ctp_mode != mode:
            self.cross_coverpoints["ctp_mode_transition"].hit(
                self.last_ctp_mode, mode
            )

        self.last_ctp_mode = mode
        self.total_samples += 1

        mode_str = "WIRE_OR" if mode == 0 else "POINT_TO_POINT"
        self.log.debug(f"Sampled CTP mode: {mode_str}")

    def sample_idcode(self, idcode: int):
        """
        Sample IDCODE coverage

        Args:
            idcode: 32-bit IDCODE value
        """
        # Sample IDCODE value
        self.coverpoints["idcode_value"].hit(idcode)

        # Decode and sample fields
        fields = DTPJTAGIDCODE_s.from_value(idcode)

        self.coverpoints["idcode_version"].hit(fields.version)
        self.coverpoints["idcode_lsb"].hit(fields.lsb)

        self.total_samples += 1

        self.log.debug(f"Sampled IDCODE: 0x{idcode:08X} " +
                      f"(version=0x{fields.version:X}, lsb={fields.lsb})")

    def sample_ir_scan(self, instruction: int, width: int):
        """
        Sample IR scan coverage

        Args:
            instruction: Instruction value
            width: IR scan width in bits
        """
        self.sample_jtag_instruction(instruction)
        self.coverpoints["ir_scan_length"].hit(width)

        self.log.debug(f"Sampled IR scan: instr=0x{instruction:04X}, width={width}")

    def sample_dr_scan(self, width: int):
        """
        Sample DR scan coverage

        Args:
            width: DR scan width in bits
        """
        self.coverpoints["dr_scan_length"].hit(width)

        self.log.debug(f"Sampled DR scan: width={width}")

    def sample_jtag_instruction_category(self, instruction: int):
        """
        Sample JTAG instruction category coverage

        Args:
            instruction: JTAG instruction value
        """
        try:
            instr_enum = DTPJTAGInstr_e(instruction)
            if instr_enum in JTAG_INSTR_CATEGORIES:
                category = JTAG_INSTR_CATEGORIES[instr_enum]
                self.coverpoints["jtag_instr_category"].hit(category.name)
                self.log.debug(f"Sampled instruction category: {category.name}")
        except ValueError:
            # Unknown instruction - categorize as UNDEFINED
            self.coverpoints["jtag_instr_category"].hit("UNDEFINED")
            self.log.debug("Sampled instruction category: UNDEFINED")

    def sample_tap_state_transition(self, from_state: str, to_state: str, tms: int):
        """
        Sample TAP state transition coverage

        Args:
            from_state: Starting TAP state
            to_state: Ending TAP state
            tms: TMS value during transition
        """
        transition_name = f"{from_state}_to_{to_state}_TMS{tms}"
        self.coverpoints["tap_state_transition"].hit(transition_name)

        # Also sample the to_state
        self.sample_tap_state(to_state)

        self.log.debug(f"Sampled TAP transition: {transition_name}")

    def sample_ctm_routing(self, src_port: int, dst_port: int):
        """
        Sample CTM routing coverage

        Args:
            src_port: Source port index (0-24)
            dst_port: Destination port index (0-24)
        """
        # Sample source port
        if src_port < 16:
            src_name = f"CTP_{src_port}"
            src_type = "CTP"
        else:
            src_name = f"CLA_{src_port - 16}"
            src_type = "CLA"
        self.coverpoints["ctm_source"].hit(src_name)

        # Sample destination port
        if dst_port < 16:
            dst_name = f"CTP_{dst_port}"
            dst_type = "CTP"
        else:
            dst_name = f"CLA_{dst_port - 16}"
            dst_type = "CLA"
        self.coverpoints["ctm_destination"].hit(dst_name)

        # Sample routing direction
        direction = f"{src_type}_to_{dst_type}"
        self.coverpoints["ctm_routing_direction"].hit(direction)

        # Sample cross coverage
        self.cross_coverpoints["ctm_src_x_dst_type"].hit(src_type, dst_type)

        self.total_samples += 1
        self.log.debug(f"Sampled CTM routing: {src_name} -> {dst_name} ({direction})")

    def sample_ijtag_sib_config(self, sec_dft_state: int, dft_state: int, dfd_state: int):
        """
        Sample IJTAG SIB configuration coverage

        Args:
            sec_dft_state: Secure DFT SIB state (0=OFF, 1=ON)
            dft_state:     Non-Secure DFT SIB state (0=OFF, 1=ON)
            dfd_state:     DFD SIB state (0=OFF, 1=ON)
        """
        # Sample individual SIB states
        self.coverpoints["sec_dft_sib_state"].hit("ON" if sec_dft_state else "OFF")
        self.coverpoints["dft_sib_state"].hit("ON" if dft_state else "OFF")
        self.coverpoints["dfd_sib_state"].hit("ON" if dfd_state else "OFF")

        # Sample pattern
        pattern = f"SEC_DFT_{sec_dft_state}_DFT_{dft_state}_DFD_{dfd_state}"
        self.coverpoints["ijtag_sib_pattern"].hit(pattern)

        self.total_samples += 1
        self.log.debug(f"Sampled IJTAG SIB config: {pattern}")

    def sample_stap_3dcr(self, stap_type: str, tms_hold: int, stap_sel: int,
                         config_hold: int, sib_state: int):
        """
        Sample STAP/3DCR configuration coverage

        Args:
            stap_type: STAP type ("DOWNSTREAM", "SEP", "EXTRA")
            tms_hold: TMS hold bit value
            stap_sel: STAP select bit value
            config_hold: Config hold bit value
            sib_state: SIB state (0=OFF, 1=ON)
        """
        # Sample STAP type
        self.coverpoints["stap_type"].hit(stap_type)

        # Sample 3DCR bits
        self.coverpoints["3dcr_tms_hold"].hit(tms_hold)
        self.coverpoints["3dcr_stap_sel"].hit(stap_sel)
        self.coverpoints["3dcr_config_hold"].hit(config_hold)

        # Sample SIB state
        self.coverpoints["stap_sib_state"].hit("ON" if sib_state else "OFF")

        # Sample cross coverage
        config_name = f"CH{config_hold}_SS{stap_sel}"
        self.cross_coverpoints["stap_type_x_3dcr_config"].hit(stap_type, config_name)

        self.total_samples += 1
        self.log.debug(f"Sampled STAP 3DCR: {stap_type} TMS_HOLD={tms_hold} " +
                      f"STAP_SEL={stap_sel} CONFIG_HOLD={config_hold} SIB={sib_state}")

    def sample_jtag2axi_operation(self, target: str, operation: str,
                                   response: str = None, size: int = None,
                                   series_mode: str = None,
                                   crosses_4k: bool = None):
        """
        Sample JTAG2AXI operation coverage

        Args:
            target: AXI target ("SMC_OTP", "SEP_OTP", "SMC_FABRIC")
            operation: Operation type ("NO_OP", "READ", "WRITE", "RESERVED")
            response: Response type ("OKAY", "SLVERR", "DECERR", "BACKPRESSURE")
            size: Data size in power of 2 (0-7)
            series_mode: Series mode ("SINGLE_OP", "SERIES_INCR", "SERIES_NO_INCR", "SERIES_WITH_ERROR")
            crosses_4k: Whether operation crosses 4K boundary
        """
        # Sample target
        self.coverpoints["jtag2axi_target"].hit(target)

        # Sample operation
        self.coverpoints["jtag2axi_operation"].hit(operation)

        # Sample response if provided
        if response is not None:
            self.coverpoints["jtag2axi_response"].hit(response)
            # Cross coverage: operation x response
            self.cross_coverpoints["jtag2axi_op_x_response"].hit(operation, response)

        # Sample size if provided
        if size is not None:
            size_name = f"{2**size}B"
            self.coverpoints["jtag2axi_size"].hit(size_name)

        # Sample series mode if provided
        if series_mode is not None:
            self.coverpoints["jtag2axi_series_mode"].hit(series_mode)

        # Sample 4K boundary crossing if provided
        if crosses_4k is not None:
            boundary = "CROSSING_PAGE" if crosses_4k else "WITHIN_PAGE"
            self.coverpoints["jtag2axi_4k_boundary"].hit(boundary)

        # Cross coverage: target x operation
        self.cross_coverpoints["jtag2axi_target_x_op"].hit(target, operation)

        self.total_samples += 1
        self.log.debug(f"Sampled JTAG2AXI: target={target} op={operation} " +
                      f"resp={response} size={size} mode={series_mode}")

    def sample_debug_control(self, boot_stall: int, boot_stall_ovrd: int,
                             cla_clock_stop_en: int, jtag_clock_stop: int,
                             cla_clock_stop: int):
        """
        Sample debug control coverage

        Args:
            boot_stall: Boot stall bit value
            boot_stall_ovrd: Boot stall override bit value
            cla_clock_stop_en: CLA clock stop enable bit value
            jtag_clock_stop: JTAG clock stop bit value
            cla_clock_stop: CLA clock stop bit value
        """
        self.coverpoints["debug_boot_stall"].hit(boot_stall)
        self.coverpoints["debug_boot_stall_ovrd"].hit(boot_stall_ovrd)
        self.coverpoints["debug_cla_clock_stop_en"].hit(cla_clock_stop_en)
        self.coverpoints["debug_jtag_clock_stop"].hit(jtag_clock_stop)
        self.coverpoints["debug_cla_clock_stop"].hit(cla_clock_stop)

        self.total_samples += 1
        self.log.debug(f"Sampled Debug Control: BOOT_STALL={boot_stall} " +
                      f"OVRD={boot_stall_ovrd} CLA_CLK_EN={cla_clock_stop_en} " +
                      f"JTAG_CLK_STOP={jtag_clock_stop} CLA_CLK_STOP={cla_clock_stop}")

    def sample_runbist_security(self, bin_name: str):
        """Sample RUNBIST security gating coverage.

        Args:
            bin_name: One of 'RUNBIST_UNGATED', 'RUNBIST_GATED', 'RUNBIST_RESTORED'
        """
        self.coverpoints["runbist_security"].hit(bin_name)
        self.log.debug(f"Sampled runbist_security: {bin_name}")

    def sample_ctp_mode_with_ctm(self, mode: int, routing_direction: str):
        """
        Sample CTP mode with CTM routing cross coverage

        Args:
            mode: CTP mode value (0=WIRE_OR, 1=POINT_TO_POINT)
            routing_direction: CTM routing direction
        """
        self.sample_ctp_mode(mode)

        mode_enum = DTPCTPMode_e(mode)
        self.cross_coverpoints["ctp_mode_x_ctm_routing"].hit(mode_enum, routing_direction)

        self.log.debug(f"Sampled CTP mode with CTM: mode={mode_enum.name} dir={routing_direction}")

    # --------------------------------------------------------------------------
    # Coverage Query Methods
    # --------------------------------------------------------------------------

    def get_overall_coverage(self) -> float:
        """
        Calculate overall coverage percentage

        Returns:
            Overall coverage percentage (0-100)
        """
        if not self.coverpoints:
            return 0.0

        total_coverage = sum(cp.coverage_percent for cp in self.coverpoints.values())
        return total_coverage / len(self.coverpoints)

    def get_coverpoint_summary(self) -> Dict[str, Dict[str, Any]]:
        """
        Get summary of all coverage points

        Returns:
            Dictionary with coverage point summaries
        """
        summary = {}

        for name, cp in self.coverpoints.items():
            summary[name] = {
                "description": cp.description,
                "coverage_percent": cp.coverage_percent,
                "hit_bins": cp.hit_bins,
                "total_bins": cp.total_bins,
                "enabled": cp.enabled
            }

        return summary

    def get_cross_coverage_summary(self) -> Dict[str, Dict[str, Any]]:
        """
        Get summary of all cross coverage points

        Returns:
            Dictionary with cross coverage summaries
        """
        summary = {}

        for name, cross in self.cross_coverpoints.items():
            summary[name] = {
                "description": cross.description,
                "coverage_percent": cross.coverage_percent,
                "hit_bins": cross.hit_bins,
                "total_bins": cross.total_bins,
                "enabled": cross.enabled
            }

        return summary

    def get_uncovered_bins(self, coverpoint_name: str) -> List[str]:
        """
        Get list of uncovered bins for a coverage point

        Args:
            coverpoint_name: Name of coverage point

        Returns:
            List of uncovered bin names
        """
        if coverpoint_name not in self.coverpoints:
            return []

        cp = self.coverpoints[coverpoint_name]
        return [bin_name for bin_name, bin_obj in cp.bins.items()
                if not bin_obj.is_covered]

    # --------------------------------------------------------------------------
    # Reporting Methods
    # --------------------------------------------------------------------------

    def print_coverage_report(self, detailed: bool = False):
        """
        Print coverage report to log

        Args:
            detailed: If True, print detailed bin information
        """
        self.log.info("")
        self.log.info("=" * 80)
        self.log.info(f"{self.name} - FUNCTIONAL COVERAGE REPORT")
        self.log.info("=" * 80)

        # Overall coverage
        overall = self.get_overall_coverage()
        self.log.info(f"Overall Coverage: {overall:.2f}%")
        self.log.info(f"Total Samples: {self.total_samples}")
        elapsed = time.time() - self.start_time
        self.log.info(f"Collection Time: {elapsed:.2f}s")
        self.log.info("")

        # Coverage points
        self.log.info("-" * 80)
        self.log.info("COVERAGE POINTS")
        self.log.info("-" * 80)

        for name, cp in self.coverpoints.items():
            status = "PASS" if cp.coverage_percent == 100.0 else "FAIL"
            self.log.info(f"{status} {name:30s} {cp.coverage_percent:6.2f}% " +
                         f"({cp.hit_bins}/{cp.total_bins} bins)")

            if detailed:
                # Show uncovered bins
                uncovered = [bn for bn, b in cp.bins.items() if not b.is_covered]
                if uncovered:
                    self.log.info(f"    Uncovered bins: {uncovered[:10]}")
                    if len(uncovered) > 10:
                        self.log.info(f"    ... and {len(uncovered) - 10} more")

        # Cross coverage points
        if self.cross_coverpoints:
            self.log.info("")
            self.log.info("-" * 80)
            self.log.info("CROSS COVERAGE")
            self.log.info("-" * 80)

            for name, cross in self.cross_coverpoints.items():
                status = "PASS" if cross.coverage_percent == 100.0 else "FAIL"
                self.log.info(f"{status} {name:30s} {cross.coverage_percent:6.2f}% " +
                             f"({cross.hit_bins}/{cross.total_bins} bins)")

        self.log.info("")
        self.log.info("=" * 80)

    def save_coverage_report(self, filename: str = "dtp_coverage_report.json"):
        """
        Save coverage report to JSON file

        Args:
            filename: Output filename
        """
        report = {
            "name": self.name,
            "timestamp": datetime.now().isoformat(),
            "overall_coverage": self.get_overall_coverage(),
            "total_samples": self.total_samples,
            "collection_time": time.time() - self.start_time,
            "coverpoints": {},
            "cross_coverage": {}
        }

        # Add coverage points
        for name, cp in self.coverpoints.items():
            bins_data = {}
            for bin_name, bin_obj in cp.bins.items():
                bins_data[str(bin_name)] = {
                    "hit_count": bin_obj.hit_count,
                    "goal": bin_obj.goal,
                    "is_covered": bin_obj.is_covered,
                    "coverage_percent": bin_obj.coverage_percent
                }

            report["coverpoints"][name] = {
                "description": cp.description,
                "coverage_percent": cp.coverage_percent,
                "hit_bins": cp.hit_bins,
                "total_bins": cp.total_bins,
                "bins": bins_data
            }

        # Add cross coverage
        for name, cross in self.cross_coverpoints.items():
            bins_data = {}
            for (bin1, bin2), bin_obj in cross.bins.items():
                key = f"{bin1} x {bin2}"
                bins_data[key] = {
                    "hit_count": bin_obj.hit_count,
                    "goal": bin_obj.goal,
                    "is_covered": bin_obj.is_covered,
                    "coverage_percent": bin_obj.coverage_percent
                }

            report["cross_coverage"][name] = {
                "description": cross.description,
                "coverage_percent": cross.coverage_percent,
                "hit_bins": cross.hit_bins,
                "total_bins": cross.total_bins,
                "bins": bins_data
            }

        # Write to file
        with open(filename, 'w') as f:
            json.dump(report, f, indent=2)

        self.log.info(f"Coverage report saved to: {filename}")

    def generate_html_report(self, filename: str = "dtp_coverage_report.html"):
        """
        Generate HTML coverage report

        Args:
            filename: Output HTML filename
        """
        html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>{self.name} - Coverage Report</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            margin: 20px;
            background-color: #f5f5f5;
        }}
        .header {{
            background-color: #2c3e50;
            color: white;
            padding: 20px;
            border-radius: 5px;
        }}
        .summary {{
            background-color: white;
            padding: 20px;
            margin-top: 20px;
            border-radius: 5px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        .coverpoint {{
            background-color: white;
            padding: 15px;
            margin-top: 10px;
            border-radius: 5px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        .progress-bar {{
            width: 100%;
            height: 30px;
            background-color: #e0e0e0;
            border-radius: 15px;
            overflow: hidden;
            margin-top: 10px;
        }}
        .progress-fill {{
            height: 100%;
            background-color: #4CAF50;
            text-align: center;
            line-height: 30px;
            color: white;
            font-weight: bold;
        }}
        .uncovered {{
            background-color: #ff9800;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 10px;
        }}
        th, td {{
            padding: 8px;
            text-align: left;
            border-bottom: 1px solid #ddd;
        }}
        th {{
            background-color: #2c3e50;
            color: white;
        }}
        tr:hover {{
            background-color: #f5f5f5;
        }}
        .covered {{
            color: #4CAF50;
            font-weight: bold;
        }}
        .not-covered {{
            color: #ff9800;
            font-weight: bold;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>{self.name}</h1>
        <p>Functional Coverage Report</p>
        <p>Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</p>
    </div>

    <div class="summary">
        <h2>Summary</h2>
        <p><strong>Overall Coverage:</strong> {self.get_overall_coverage():.2f}%</p>
        <div class="progress-bar">
            <div class="progress-fill" style="width: {self.get_overall_coverage():.1f}%">
                {self.get_overall_coverage():.1f}%
            </div>
        </div>
        <p><strong>Total Samples:</strong> {self.total_samples}</p>
        <p><strong>Collection Time:</strong> {time.time() - self.start_time:.2f}s</p>
    </div>
"""

        # Add coverage points
        html += """
    <div class="summary">
        <h2>Coverage Points</h2>
"""

        for name, cp in self.coverpoints.items():
            html += f"""
        <div class="coverpoint">
            <h3>{name}</h3>
            <p>{cp.description}</p>
            <p><strong>Coverage:</strong> {cp.coverage_percent:.2f}% ({cp.hit_bins}/{cp.total_bins} bins)</p>
            <div class="progress-bar">
                <div class="progress-fill" style="width: {cp.coverage_percent:.1f}%">
                    {cp.coverage_percent:.1f}%
                </div>
            </div>
"""

            # Add bin details if not too many
            if len(cp.bins) <= 50:
                html += """
            <table>
                <tr>
                    <th>Bin</th>
                    <th>Hit Count</th>
                    <th>Goal</th>
                    <th>Status</th>
                </tr>
"""
                for bin_name, bin_obj in sorted(cp.bins.items(), key=lambda x: x[1].hit_count, reverse=True):
                    status = "covered" if bin_obj.is_covered else "not-covered"
                    status_text = "PASS" if bin_obj.is_covered else "FAIL"
                    html += f"""
                <tr>
                    <td>{bin_name}</td>
                    <td>{bin_obj.hit_count}</td>
                    <td>{bin_obj.goal}</td>
                    <td class="{status}">{status_text}</td>
                </tr>
"""
                html += """
            </table>
"""

            html += """
        </div>
"""

        html += """
    </div>
"""

        # Add cross coverage
        if self.cross_coverpoints:
            html += """
    <div class="summary">
        <h2>Cross Coverage</h2>
"""

            for name, cross in self.cross_coverpoints.items():
                html += f"""
        <div class="coverpoint">
            <h3>{name}</h3>
            <p>{cross.description}</p>
            <p><strong>Coverage:</strong> {cross.coverage_percent:.2f}% ({cross.hit_bins}/{cross.total_bins} bins)</p>
            <div class="progress-bar">
                <div class="progress-fill" style="width: {cross.coverage_percent:.1f}%">
                    {cross.coverage_percent:.1f}%
                </div>
            </div>
        </div>
"""

            html += """
    </div>
"""

        html += """
</body>
</html>
"""

        # Write to file
        with open(filename, 'w') as f:
            f.write(html)

        self.log.info(f"HTML coverage report saved to: {filename}")

    def get_coverage_report(self) -> Dict[str, Any]:
        """
        Get coverage report as a dictionary

        Returns:
            Dictionary containing full coverage data:
            {
                "name": str,
                "timestamp": str,
                "overall_coverage": float,
                "total_samples": int,
                "collection_time": float,
                "coverpoints": { ... },
                "cross_coverage": { ... }
            }
        """
        report = {
            "name": self.name,
            "timestamp": datetime.now().isoformat(),
            "overall_coverage": self.get_overall_coverage(),
            "total_samples": self.total_samples,
            "collection_time": time.time() - self.start_time,
            "coverpoints": {},
            "cross_coverage": {}
        }

        # Add coverage points
        for name, cp in self.coverpoints.items():
            bins_data = {}
            for bin_name, bin_obj in cp.bins.items():
                bins_data[str(bin_name)] = {
                    "hit_count": bin_obj.hit_count,
                    "goal": bin_obj.goal,
                    "is_covered": bin_obj.is_covered,
                    "coverage_percent": bin_obj.coverage_percent
                }

            report["coverpoints"][name] = {
                "description": cp.description,
                "coverage_percent": cp.coverage_percent,
                "hit_bins": cp.hit_bins,
                "total_bins": cp.total_bins,
                "bins": bins_data
            }

        # Add cross coverage
        for name, cross in self.cross_coverpoints.items():
            bins_data = {}
            for (bin1, bin2), bin_obj in cross.bins.items():
                key = f"{bin1} x {bin2}"
                bins_data[key] = {
                    "hit_count": bin_obj.hit_count,
                    "goal": bin_obj.goal,
                    "is_covered": bin_obj.is_covered,
                    "coverage_percent": bin_obj.coverage_percent
                }

            report["cross_coverage"][name] = {
                "description": cross.description,
                "coverage_percent": cross.coverage_percent,
                "hit_bins": cross.hit_bins,
                "total_bins": cross.total_bins,
                "bins": bins_data
            }

        return report

    def get_coverage_summary(self) -> str:
        """
        Get a formatted coverage summary string

        Returns:
            Human-readable coverage summary
        """
        lines = []
        lines.append(f"Coverage Model: {self.name}")
        lines.append(f"Overall Coverage: {self.get_overall_coverage():.2f}%")
        lines.append(f"Total Samples: {self.total_samples}")
        lines.append("")
        lines.append("Coverage Points:")

        for name, cp in self.coverpoints.items():
            status = "✓" if cp.coverage_percent == 100.0 else "○"
            lines.append(f"  {status} {name}: {cp.coverage_percent:.2f}% ({cp.hit_bins}/{cp.total_bins})")

        if self.cross_coverpoints:
            lines.append("")
            lines.append("Cross Coverage:")
            for name, cross in self.cross_coverpoints.items():
                status = "✓" if cross.coverage_percent == 100.0 else "○"
                lines.append(f"  {status} {name}: {cross.coverage_percent:.2f}% ({cross.hit_bins}/{cross.total_bins})")

        return "\n".join(lines)

    def reset(self):
        """
        Reset all coverage data to initial state

        Clears all hit counts while preserving bin definitions
        """
        # Reset all coverage point bins
        for cp in self.coverpoints.values():
            for bin_obj in cp.bins.values():
                bin_obj.hit_count = 0

        # Reset all cross coverage bins
        for cross in self.cross_coverpoints.values():
            for bin_obj in cross.bins.values():
                bin_obj.hit_count = 0

        # Reset counters
        self.total_samples = 0
        self.start_time = time.time()

        self.log.info("Coverage data reset")


# ==============================================================================
# Convenience Functions
# ==============================================================================

def create_dtp_coverage(name: str = "DTP_Coverage") -> DTPFunctionalCoverage:
    """
    Create and return a DTP functional coverage instance

    Args:
        name: Coverage model name

    Returns:
        DTPFunctionalCoverage instance
    """
    return DTPFunctionalCoverage(name=name)


# ==============================================================================
# Example Usage
# ==============================================================================

"""
Example usage in a CocoTB test:

```python
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import Timer
from env.dtp_fcov import create_dtp_coverage
from env.dtp_enum import DTPJTAGInstr_e, DTPCTPMode_e

@cocotb.test()
async def test_with_coverage(dut):
    # Create coverage model
    cov = create_dtp_coverage(name="Test_Coverage")

    # Start clock
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    # Setup test...

    # ============================================================
    # Basic JTAG Coverage
    # ============================================================
    # Sample JTAG instruction (automatically samples category too)
    cov.sample_jtag_instruction(DTPJTAGInstr_e.IDCODE)
    cov.sample_tap_state("SHIFT_IR")
    cov.sample_idcode(0x12345679)

    # Sample TAP state transitions
    cov.sample_tap_state_transition("RUN_TEST_IDLE", "SELECT_DR_SCAN", tms=1)

    # ============================================================
    # CTP/CTM Coverage
    # ============================================================
    # Sample CTP mode
    cov.sample_ctp_mode(DTPCTPMode_e.WIRE_OR)
    cov.sample_ctp_mode(DTPCTPMode_e.POINT_TO_POINT)

    # Sample CTM routing (src_port, dst_port)
    cov.sample_ctm_routing(src_port=0, dst_port=16)  # CTP_0 -> CLA_0
    cov.sample_ctm_routing(src_port=20, dst_port=5)  # CLA_4 -> CTP_5

    # Sample CTP mode with CTM routing cross coverage
    cov.sample_ctp_mode_with_ctm(DTPCTPMode_e.POINT_TO_POINT, "CLA_to_CTP")

    # ============================================================
    # IJTAG Coverage (IEEE 1687)
    # ============================================================
    # Sample IJTAG SIB configuration
    cov.sample_ijtag_sib_config(sec_dft_state=1, dft_state=0, dfd_state=1)  # Secure DFT ON, Non-Secure DFT OFF, DFD ON
    cov.sample_ijtag_sib_config(sec_dft_state=0, dft_state=1, dfd_state=1)  # Secure DFT OFF, Non-Secure DFT ON, DFD ON

    # ============================================================
    # STAP/3DCR Coverage (IEEE 1838)
    # ============================================================
    # Sample STAP 3DCR configuration
    cov.sample_stap_3dcr(
        stap_type="DOWNSTREAM",
        tms_hold=0,
        stap_sel=1,
        config_hold=1,
        sib_state=1
    )

    # ============================================================
    # JTAG2AXI Coverage
    # ============================================================
    # Sample JTAG2AXI operation
    cov.sample_jtag2axi_operation(
        target="SMC_FABRIC",
        operation="WRITE",
        response="OKAY",
        size=2,  # 4 bytes
        series_mode="SINGLE_OP",
        crosses_4k=False
    )

    # Sample with 4K boundary crossing
    cov.sample_jtag2axi_operation(
        target="SMC_OTP",
        operation="READ",
        response="OKAY",
        size=3,  # 8 bytes
        series_mode="SERIES_INCR",
        crosses_4k=True
    )

    # ============================================================
    # Debug Control Coverage
    # ============================================================
    cov.sample_debug_control(
        boot_stall=1,
        boot_stall_ovrd=1,
        cla_clock_stop_en=0,
        jtag_clock_stop=0,
        cla_clock_stop=0
    )

    # ============================================================
    # Run test...
    # ============================================================
    await Timer(1000, units='ns')

    # Print coverage report
    cov.print_coverage_report(detailed=True)

    # Save reports
    cov.save_coverage_report("coverage.json")
    cov.generate_html_report("coverage.html")

    # Check coverage goals
    overall = cov.get_overall_coverage()
    assert overall >= 80.0, f"Coverage goal not met: {overall:.2f}%"
```
"""

# ==============================================================================
# Best Practices
# ==============================================================================

"""
FUNCTIONAL COVERAGE BEST PRACTICES:

1. Sample at Meaningful Points
   - Sample when coverage-worthy events occur
   - Don't sample too frequently (impacts simulation performance)
   - Sample after state transitions complete

2. Define Clear Coverage Goals
   - Set realistic bin goals
   - Focus on important scenarios first
   - Add cross coverage for critical interactions

3. Regular Reporting
   - Generate reports after test completion
   - Review uncovered bins
   - Add targeted tests for missing coverage

4. Coverage-Driven Verification
   - Use coverage to guide test development
   - Identify coverage holes early
   - Track coverage trends over time

5. Integration with Tests
   - Create coverage instance at test start
   - Sample throughout test execution
   - Report and save at test end
   - Use coverage as pass/fail criteria if desired

6. Performance Considerations
   - Disable unused coverage points
   - Limit cross coverage combinations
   - Sample selectively in long-running tests

DTP-SPECIFIC COVERAGE GUIDELINES:

1. JTAG Instruction Coverage
   - Sample all instruction categories (mandatory, optional, debug, etc.)
   - Verify undefined instructions behave as BYPASS
   - Track IEEE 1838 (3DIC) instruction usage

2. TAP State Machine Coverage
   - Cover all 16 TAP states
   - Cover all valid state transitions
   - Track transition sequences

3. CTP/CTM Coverage
   - Cover both Wire-OR and P2P modes
   - Test all CTM source-destination combinations
   - Verify routing direction combinations (CTP↔CLA)

4. IJTAG SIB Coverage (IEEE 1687)
   - Cover all SIB ON/OFF combinations
   - Test hierarchical SIB access (DFD must be ON for downstream)
   - Verify chain length calculations

5. STAP/3DCR Coverage (IEEE 1838)
   - Cover all STAP types (Downstream, SEP, Extra)
   - Test config_hold behavior on TLR
   - Verify stap_sel and tms_hold functionality

6. JTAG2AXI Coverage
   - Cover all AXI targets (SMC_OTP, SEP_OTP, SMC_FABRIC)
   - Test all operation types (READ, WRITE)
   - Cover all response types including errors
   - Test 4K boundary crossing scenarios
   - Cover all series modes (INCR, NO_INCR, WITH_ERROR)

7. Debug Control Coverage
   - Cover boot stall enable/disable
   - Test clock stop functionality
   - Verify override behavior

8. Cross Coverage Focus Areas
   - Instruction category × TAP state
   - JTAG2AXI target × operation
   - CTP mode × CTM routing direction
   - STAP type × 3DCR configuration
"""
