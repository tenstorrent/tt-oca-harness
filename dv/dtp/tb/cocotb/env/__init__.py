"""
Verification Environment for CTP

This package contains the verification environment components for the
Cross-Trigger Port (CTP) module.

Components:
- ctp_bfm: CTP Bus Functional Model
- dtp_enum: DTP Protocol Enumerations
- dtp_fcov: DTP Functional Coverage Model

Templates & Utilities:
- enum_template: Enumeration patterns and best practices for CocoTB

Author: Andrew Hsiao (ahsiao@tenstorrent.com)
"""

from .ctp_bfm import (
    CTPBFM,
    CTPTriggerEvent,
    create_ctp_bfm
)

from .dtp_enum import (
    DTPCTPMode_e,
    DTPJTAGInstr_e,
    DTPJTAGIDCODE_s
)

from .dtp_fcov import (
    DTPFunctionalCoverage,
    CoveragePoint,
    CrossCoveragePoint,
    CoverageBin,
    create_dtp_coverage
)

__all__ = [
    'CTPBFM',
    'CTPTriggerEvent',
    'DTPCTPMode_e',
    'DTPJTAGInstr_e',
    'DTPJTAGIDCODE_s',
    'create_ctp_bfm',
    'DTPFunctionalCoverage',
    'CoveragePoint',
    'CrossCoveragePoint',
    'CoverageBin',
    'create_dtp_coverage'
]

__version__ = "1.0.0"
__author__ = "Andrew Hsiao (ahsiao@tenstorrent.com)"

