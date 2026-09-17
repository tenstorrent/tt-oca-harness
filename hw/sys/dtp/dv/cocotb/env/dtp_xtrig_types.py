# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP XTRIG register constants and lightweight reference helpers.

Register offsets, strides, and field masks come from the generated SystemRDL
Python headers of the cross-trigger IP, ``cross_trigger_matrix_reg`` and
``cross_trigger_port_reg`` under ``hw/ip/cross_trigger/*/regs/gen/py`` (on the
import path through the DTP sim config ``python_paths``). Two numbers have no
generated Python export and cite ``cross_trigger_network_pkg``: the CTP window
base (``CSR_ADDR_CTM_SIZE``) and the per-CTP window stride
(``CSR_ADDR_CTP_SIZE``), both also stated in
``hw/ip/cross_trigger/cross_trigger_network/doc/memmap.adoc``. The port counts
cite the same package (``DEFAULT_NUM_CTP``, ``DEFAULT_NUM_INT_CT``) and are
checked against the generated select-field width at import.
"""

from __future__ import annotations

import re
from ctypes import Structure
from dataclasses import dataclass

import cross_trigger_matrix_reg as _ctm_reg
import cross_trigger_port_reg as _ctp_reg

_RESERVED_FIELD_RE = re.compile(r"^(?:rsvd|reserved)(?:_\d+)?$")


def _field_masks(struct: type[Structure]) -> dict[str, int]:
    """Bit mask per field of a generated ctypes bitfield struct, LSB first."""
    masks: dict[str, int] = {}
    offset = 0
    for name, _ctype, width in struct._fields_:
        masks[name] = ((1 << width) - 1) << offset
        offset += width
    return masks


def _software_mask(masks: dict[str, int]) -> int:
    """Union of the implemented, non-reserved fields."""
    return sum(mask for name, mask in masks.items() if not _RESERVED_FIELD_RE.match(name))


def _place(value: int, mask: int) -> int:
    """Shift ``value`` into the field that ``mask`` selects."""
    shift = (mask & -mask).bit_length() - 1
    return (value << shift) & mask


_CTP_CONFIG = _field_masks(_ctp_reg.CROSS_TRIGGER_PORT_CONFIG_reg_t)
_CTP_STATUS = _field_masks(_ctp_reg.CROSS_TRIGGER_PORT_STATUS_reg_t)
_CTP_STRETCH = _field_masks(_ctp_reg.CROSS_TRIGGER_PORT_STRETCH_MULT_reg_t)
_CTM_SELECT = _field_masks(_ctm_reg.CT_SRC_CONFIG_0_reg_t)

# cross_trigger_network_pkg DEFAULT_NUM_CTP and DEFAULT_NUM_INT_CT; the matrix
# carries one CT_SRC register and one CT_DST_SELECT bit per port.
XTRIG_NUM_CTP = 16
XTRIG_NUM_INT_CT = 10
XTRIG_NUM_CTM_PORTS = XTRIG_NUM_CTP + XTRIG_NUM_INT_CT

XTRIG_CTM_SELECT_MASK = _CTM_SELECT["ct_dst_select"]
if XTRIG_CTM_SELECT_MASK != (1 << XTRIG_NUM_CTM_PORTS) - 1:
    raise ImportError(
        f"CT_DST_SELECT is {XTRIG_CTM_SELECT_MASK.bit_length()} bits wide; the bench "
        f"assumes {XTRIG_NUM_CTM_PORTS} CTM ports"
    )

# Cross-trigger network CSR windows: the CTM block at offset 0, then one
# window per external CTP (cross_trigger_network_pkg CSR_ADDR_CTM_SIZE and
# CSR_ADDR_CTP_SIZE).
XTRIG_CTM_BASE = _ctm_reg.CROSS_TRIGGER_MATRIX_REG_MAP_BASE_ADDR
XTRIG_CTM_STRIDE = _ctm_reg.CT_SRC_1__CONFIG_0_REG_ADDR - _ctm_reg.CT_SRC_0__CONFIG_0_REG_ADDR
XTRIG_CTP_BASE = 0x200
XTRIG_CTP_STRIDE = 0x10
XTRIG_CSR_END = XTRIG_CTP_BASE + (XTRIG_NUM_CTP * XTRIG_CTP_STRIDE)
XTRIG_UNMAPPED_BASE = XTRIG_CSR_END

# Read data the crossbar's error subordinate returns alongside DECERR on an
# unmapped XTRIG address (the low word of the pulp axi_err_slv response word).
XTRIG_DECERR_DATA = 0xBADC_AB1E

XTRIG_CTP_CONFIG_OFFSET = _ctp_reg.CONFIG_REG_OFFSET
XTRIG_CTP_STATUS_OFFSET = _ctp_reg.STATUS_REG_OFFSET
XTRIG_CTP_STRETCH_MULT_OFFSET = _ctp_reg.STRETCH_MULT_REG_OFFSET

XTRIG_CTP_CONFIG_MODE_MASK = _CTP_CONFIG["mode"]
XTRIG_CTP_CONFIG_INVERT_MASK = _CTP_CONFIG["invert"]
XTRIG_CTP_CONFIG_RESET_MASK = _CTP_CONFIG["reset"]
XTRIG_CTP_CONFIG_MASK = _software_mask(_CTP_CONFIG)
XTRIG_CTP_STRETCH_MASK = _CTP_STRETCH["stretch_mult"]

# CONFIG.MODE encoding (cross_trigger_port.rdl): 0 wire-OR, 1 point-to-point.
XTRIG_CTP_MODE_WIRE_OR = 0
XTRIG_CTP_MODE_P2P = 1

XTRIG_CTP_STATUS_BUSY = _CTP_STATUS["busy"]
XTRIG_CTP_STATUS_REQ_OUT = _CTP_STATUS["req_out"]
XTRIG_CTP_STATUS_ACK_IN = _CTP_STATUS["ack_in"]
XTRIG_CTP_STATUS_REQ_IN = _CTP_STATUS["req_in"]
XTRIG_CTP_STATUS_ACK_OUT = _CTP_STATUS["ack_out"]


def ctm_config_addr(output_port: int) -> int:
    """CSR address of ``CT_SRC[output_port].CONFIG_0`` (generated per-instance address)."""
    check_ctm_port(output_port, "CTM output port")
    return XTRIG_CTM_BASE + getattr(_ctm_reg, f"CT_SRC_{output_port}__CONFIG_0_REG_ADDR")


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
    """Pack the CTP CONFIG fields at their generated positions."""
    return (
        _place(mode, XTRIG_CTP_CONFIG_MODE_MASK)
        | _place(invert, XTRIG_CTP_CONFIG_INVERT_MASK)
        | _place(reset, XTRIG_CTP_CONFIG_RESET_MASK)
    )


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


class DtpXtrigCtpShadow:
    """Programmed CONFIG.MODE and CONFIG.INVERT of every external CTP.

    Held by the env cfg, so it outlives a scenario pass: the DUT keeps its CTP
    configuration from one pass to the next. A system reset or a CONFIG clear
    returns every CTP to wire-OR, not inverted (the register reset value).
    """

    def __init__(self) -> None:
        self.modes = [XTRIG_CTP_MODE_WIRE_OR] * XTRIG_NUM_CTP
        self.inverts = [0] * XTRIG_NUM_CTP

    def clear(self) -> None:
        self.modes = [XTRIG_CTP_MODE_WIRE_OR] * XTRIG_NUM_CTP
        self.inverts = [0] * XTRIG_NUM_CTP

    def note(self, ctp_idx: int, *, mode: int, invert: int) -> None:
        check_ctp_idx(ctp_idx)
        self.modes[ctp_idx] = mode
        self.inverts[ctp_idx] = invert

    @property
    def p2p_mask(self) -> int:
        return sum(1 << i for i, mode in enumerate(self.modes) if mode == XTRIG_CTP_MODE_P2P)

    @property
    def invert_mask(self) -> int:
        return sum(1 << i for i, inv in enumerate(self.inverts) if inv)


class DtpCtmRefModel:
    """CTM routing model from the register contract.

    ``CT_SRC[k].CONFIG_0.CT_DST_SELECT`` (cross_trigger_matrix.rdl) holds one
    bit per CT_Dst input port; the pulses of the selected inputs are OR'd onto
    CT_Src output ``k``. ``route`` returns the output vector a set of input
    pulses reaches.
    """

    def __init__(self) -> None:
        self.select = [0 for _ in range(XTRIG_NUM_CTM_PORTS)]

    def program(self, output_port: int, input_mask: int) -> None:
        check_ctm_port(output_port, "CTM output port")
        self.select[output_port] = input_mask & XTRIG_CTM_SELECT_MASK

    def route(self, input_pulses: int) -> int:
        input_pulses &= XTRIG_CTM_SELECT_MASK
        routed = 0
        for output_port, input_mask in enumerate(self.select):
            if input_pulses & input_mask:
                routed |= 1 << output_port
        return routed & XTRIG_CTM_SELECT_MASK
