"""
JTAG VIP Package for CocoTB

A comprehensive JTAG verification environment with Bus Functional Models (BFM),
Monitor, and interface support for CocoTB testbenches.

This package provides:
- JTAG_Master_BFM: Full-featured JTAG controller (master)
- JTAG_Slave_BFM: Full-featured JTAG slave with configurable instructions
- JTAG_Monitor: Transaction monitoring and analysis
- TAPState: IEEE 1149.1 TAP state enumeration
- Interface-based design with unified signal naming

Example usage:
    from jtag_vip import JTAG_Master_BFM, JTAG_Slave_BFM, create_jtag_monitor, TAPState

    # Create JTAG master BFM
    jtag_master = JTAG_Master_BFM(jtag_intf, tck_period_ns=10)

    # Create JTAG slave BFM
    jtag_slave = JTAG_Slave_BFM(jtag_intf, ir_width=5, idcode=0x12345678)
    jtag_slave.register_instruction(0x08, 32, "CUSTOM_REG")
    cocotb.start_soon(jtag_slave.run())

    # Create monitor
    jtag_monitor = create_jtag_monitor(jtag_intf, "JTAG_Monitor")
"""

# Import main classes and functions
from .jtag_enum import JTAG_TAP_State_e, JTAG_TAP_FSM
from .jtag_mst_bfm import JTAG_Master_BFM
from .jtag_slv_bfm import JTAG_Slave_BFM, JTAGInstruction, create_jtag_slave_bfm
from .jtag_mon import JTAG_Monitor, JTAGTransaction, JTAGProtocolError, create_jtag_monitor

# Package metadata
__version__ = "1.0.0"
__author__ = "Andrew Hsiao (ahsiao@tenstorrent.com)"
__description__ = "JTAG Master/Slave BFMs and Monitor package for CocoTB"

# Define what gets imported with "from jtag_vip import *"
__all__ = [
    # Main BFM classes
    "JTAG_Master_BFM",
    "JTAG_Slave_BFM",
    # Monitor classes and functions
    "JTAG_Monitor",
    "JTAGTransaction",
    "JTAGProtocolError",
    "create_jtag_monitor",
    # Slave BFM support classes
    "JTAGInstruction",
    "create_jtag_slave_bfm",
    # Enums and constants
    "JTAG_TAP_State_e",
    "JTAG_TAP_FSM",
    # Package metadata
    "__version__",
    "__author__",
    "__description__",
]

# Convenience aliases
JtagMasterBfm = JTAG_Master_BFM  # Alternative naming
JtagMonitor = JTAG_Monitor  # Alternative naming


def get_version():
    """Get package version information"""
    return __version__


def get_package_info():
    """Get comprehensive package information"""
    return {
        "name": "jtag_vip",
        "version": __version__,
        "description": __description__,
        "author": __author__,
        "components": [
            "JTAG_Master_BFM - Full-featured JTAG controller (master)",
            "JTAG_Slave_BFM - Full-featured JTAG slave with configurable instructions",
            "JTAG_Monitor - Transaction monitoring and analysis",
            "JTAG_TAP_State_e - IEEE 1149.1 TAP state enumeration",
            "JTAG_TAP_FSM - IEEE 1149.1 TAP state machine",
            "Interface support - Unified signal naming",
        ],
    }


# Validate imports on package load
def _validate_package():
    """Validate that all required components are available"""
    required_classes = [
        "JTAG_Master_BFM",
        "JTAG_Slave_BFM",
        "JTAG_Monitor",
        "JTAG_TAP_State_e",
        "JTAG_TAP_FSM",
    ]
    missing = []

    for cls_name in required_classes:
        if cls_name not in globals():
            missing.append(cls_name)

    if missing:
        raise ImportError(f"JTAG VIP package incomplete. Missing: {missing}")


# Run validation
_validate_package()
