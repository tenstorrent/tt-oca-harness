# SPDX-License-Identifier: Apache-2.0
"""DTP XTRIG register constants and lightweight reference helpers."""

from __future__ import annotations

from dataclasses import dataclass

XTRIG_NUM_CTP = 16
XTRIG_NUM_INT_CT = 10
XTRIG_NUM_CTM_PORTS = XTRIG_NUM_CTP + XTRIG_NUM_INT_CT

XTRIG_CTM_BASE = 0x000
XTRIG_CTM_STRIDE = 0x8
XTRIG_CTP_BASE = 0x200
XTRIG_CTP_STRIDE = 0x10
XTRIG_CSR_END = XTRIG_CTP_BASE + (XTRIG_NUM_CTP * XTRIG_CTP_STRIDE)
XTRIG_UNMAPPED_BASE = XTRIG_CSR_END

XTRIG_CTP_CONFIG_OFFSET = 0x0
XTRIG_CTP_STATUS_OFFSET = 0x4
XTRIG_CTP_STRETCH_MULT_OFFSET = 0x8

XTRIG_CTP_CONFIG_MODE_MASK = 0x1
XTRIG_CTP_CONFIG_INVERT_MASK = 0x2
XTRIG_CTP_CONFIG_RESET_MASK = 0x4
XTRIG_CTP_CONFIG_MASK = (
    XTRIG_CTP_CONFIG_MODE_MASK | XTRIG_CTP_CONFIG_INVERT_MASK | XTRIG_CTP_CONFIG_RESET_MASK
)
XTRIG_CTP_STRETCH_MASK = 0xFFFF
XTRIG_CTM_SELECT_MASK = (1 << XTRIG_NUM_CTM_PORTS) - 1

XTRIG_CTP_MODE_WIRE_OR = 0
XTRIG_CTP_MODE_P2P = 1

XTRIG_CTP_STATUS_BUSY = 1 << 0
XTRIG_CTP_STATUS_REQ_OUT = 1 << 4
XTRIG_CTP_STATUS_ACK_IN = 1 << 5
XTRIG_CTP_STATUS_REQ_IN = 1 << 6
XTRIG_CTP_STATUS_ACK_OUT = 1 << 7


def ctm_config_addr(src_idx: int) -> int:
    """Return the CTM CT_SRC[src_idx].CONFIG_0 CSR address."""
    check_ctm_port(src_idx, "ctm source")
    return XTRIG_CTM_BASE + (src_idx * XTRIG_CTM_STRIDE)


def ctp_base_addr(ctp_idx: int) -> int:
    """Return the base CSR address for an external CTP."""
    check_ctp_idx(ctp_idx)
    return XTRIG_CTP_BASE + (ctp_idx * XTRIG_CTP_STRIDE)


def ctp_config_addr(ctp_idx: int) -> int:
    return ctp_base_addr(ctp_idx) + XTRIG_CTP_CONFIG_OFFSET


def ctp_status_addr(ctp_idx: int) -> int:
    return ctp_base_addr(ctp_idx) + XTRIG_CTP_STATUS_OFFSET


def ctp_stretch_addr(ctp_idx: int) -> int:
    return ctp_base_addr(ctp_idx) + XTRIG_CTP_STRETCH_MULT_OFFSET


def check_ctp_idx(ctp_idx: int) -> None:
    if not 0 <= ctp_idx < XTRIG_NUM_CTP:
        raise ValueError(f"CTP index must be 0..{XTRIG_NUM_CTP - 1}, got {ctp_idx}")


def check_ctm_port(port_idx: int, name: str = "CTM port") -> None:
    if not 0 <= port_idx < XTRIG_NUM_CTM_PORTS:
        raise ValueError(f"{name} must be 0..{XTRIG_NUM_CTM_PORTS - 1}, got {port_idx}")


def external_ctp_port(ctp_idx: int) -> int:
    """CTM port number for external CTP[idx]."""
    check_ctp_idx(ctp_idx)
    return ctp_idx


def internal_ct_port(int_idx: int) -> int:
    """CTM port number for internal CT[idx]."""
    if not 0 <= int_idx < XTRIG_NUM_INT_CT:
        raise ValueError(f"internal CT index must be 0..{XTRIG_NUM_INT_CT - 1}, got {int_idx}")
    return XTRIG_NUM_CTP + int_idx


def ctp_mask(*indices: int) -> int:
    mask = 0
    for idx in indices:
        mask |= 1 << external_ctp_port(idx)
    return mask


def internal_ct_mask(*indices: int) -> int:
    mask = 0
    for idx in indices:
        mask |= 1 << internal_ct_port(idx)
    return mask


def project_internal_mask(ctm_mask: int) -> int:
    """Project full CTM-port mask into the DTP top-level internal CT vector."""
    return (ctm_mask >> XTRIG_NUM_CTP) & ((1 << XTRIG_NUM_INT_CT) - 1)


def project_ctp_mask(ctm_mask: int) -> int:
    """Project full CTM-port mask into the external CTP vector."""
    return ctm_mask & ((1 << XTRIG_NUM_CTP) - 1)


def pack_ctp_config(*, mode: int = XTRIG_CTP_MODE_WIRE_OR, invert: int = 0, reset: int = 0) -> int:
    """Pack the public CTP CONFIG fields."""
    return ((mode & 0x1) << 0) | ((invert & 0x1) << 1) | ((reset & 0x1) << 2)


def apply_wstrb(old_value: int, new_value: int, wstrb: int) -> int:
    """Apply AXI-Lite byte strobes to a 32-bit word."""
    merged = old_value & 0xFFFFFFFF
    for byte_idx in range(4):
        if (wstrb >> byte_idx) & 0x1:
            mask = 0xFF << (8 * byte_idx)
            merged = (merged & ~mask) | (new_value & mask)
    return merged & 0xFFFFFFFF


@dataclass
class DtpCtpCfg:
    mode: int = XTRIG_CTP_MODE_WIRE_OR
    invert: int = 0
    reset: int = 0
    stretch_mult: int = 0

    @property
    def config_word(self) -> int:
        return pack_ctp_config(mode=self.mode, invert=self.invert, reset=self.reset)


class DtpCtmRefModel:
    """Small CTM model matching the OR-of-selected-destinations RTL behavior."""

    def __init__(self) -> None:
        self.select = [0 for _ in range(XTRIG_NUM_CTM_PORTS)]

    def program(self, src_idx: int, dst_mask: int) -> None:
        check_ctm_port(src_idx, "CTM source")
        self.select[src_idx] = dst_mask & XTRIG_CTM_SELECT_MASK

    def route(self, dst_value: int) -> int:
        dst_value &= XTRIG_CTM_SELECT_MASK
        routed = 0
        for src_idx, dst_mask in enumerate(self.select):
            if dst_value & dst_mask:
                routed |= 1 << src_idx
        return routed & XTRIG_CTM_SELECT_MASK
