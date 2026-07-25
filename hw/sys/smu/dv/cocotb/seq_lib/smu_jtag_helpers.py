# SPDX-License-Identifier: Apache-2.0
"""SMU JTAG / JTAG2AXI helpers (local constants; avoid DTP ``env`` package clash)."""

from __future__ import annotations

from typing import Iterable, Optional

import cocotb
from cocotb.handle import Force, Release
from cocotb.triggers import ClockCycles

from ocah_jtag_vip import OcahJtagDevice, OcahJtagTap

# Mirrors hw/sys/dtp/dv/cocotb/env/{dtp_types,dtp_tap_device}.py
DTP_IR_WIDTH = 6
DTP_DEFAULT_IDCODE = 0x0000_0001
DTP_IR_DEBUG_CONTROL = 0x18
DTP_IR_IC_RESET = 0x0D
DTP_IR_EXTEST = 0x04
DTP_IR_SMC_AXI_SINGLE_OP = 0x28
DTP_IR_SMC_JTAG2AXI_CAPS = 0x27
DTP_IR_SMC_OTP_JTAG2AXI_CAPS = 0x1B
DTP_IR_SMC_OTP_AXI_SINGLE_OP = 0x1C
DTP_IR_SEP_OTP_JTAG2AXI_CAPS = 0x21
DTP_IR_SEP_OTP_AXI_SINGLE_OP = 0x22
DTP_DEBUG_CONTROL_LEN = 5
DTP_JTAG2AXI_CAPS_LEN = 14
# Compact OSS BSR loopback model (scan_in <- scan_out); matches DTP OSS.
DTP_BSR_MODEL_LEN = 8
# One-hot EXTEST decode bit in jtag_instruction_decoded_e.
DTP_EXTEST_DECODED_BIT = DTP_IR_EXTEST
# SMU SEP=0 IC_RESET geometry (smu.sv / jtag_ptap):
#   NUM_SMC = $bits(jtag_smc_reset_ctrl_t)/2 = 68, NUM_SEP = 0, NUM_EXT = 1
#   TDR width = 2*NUM_IC_RESET + 1 (hold) = 139
SMU_IC_RESET_NUM_PORTS = 69
SMU_IC_RESET_LEN = 2 * SMU_IC_RESET_NUM_PORTS + 1
SMU_IC_RESET_DEFAULT = (1 << SMU_IC_RESET_LEN) - 1
SMU_IC_RESET_EXT_PORT = 0
SMU_IC_RESET_SMC_FUSE_PORT = 1
SMU_IC_RESET_SMC_WARM_PORT = 2
SMU_IC_RESET_SMC_COOL_PORT = 3
SMU_IC_RESET_SMC_COLD_PORT = 4  # EXT@0 + SMC fuse/warm/cool/cold
SMU_IC_RESET_SMC_SS_COLD0_PORT = 5
SMU_IC_RESET_SMC_SS_WARM0_PORT = 37

SMC_DBG_SINGLE_OP_LEN = 132  # OP2|SIZE2|WSTRB8|DATA64|ADDR56
SMC_DBG_AXSIZE_8B = 3
SMC_DBG_AXSIZE_4B = 2
# OTP bridge: OP2|SIZE2|WSTRB4|DATA32|ADDR32 = 72
SMC_OTP_SINGLE_OP_LEN = 72
SMC_OTP_AXSIZE_4B = 2
# Relative probe used by P1 CAPS/BUSY (routes to SHIM when MAP base is abs).
SMC_OTP_DEFAULT_PROBE_ADDR = 0x80
# Absolute SMC eFuse map window (smc_top_reg / INTERFACE_SEL decode).
SMC_EFUSE_MAP_BASE = 0xC000_B000
# BIRA word @ +0x80 — WRITE_UNLOCK in smc_efuse_pkg::EfuseFieldMap.
SMC_EFUSE_MAP_BIRA_WORD = SMC_EFUSE_MAP_BASE + 0x80

DBG_BOOT_STALL_BIT = 0
DBG_BOOT_STALL_OVRD_BIT = 1
DBG_CLA_CLOCK_STOP_EN_BIT = 2
DBG_JTAG_CLOCK_STOP_BIT = 3
DBG_CLA_CLOCK_STOP_BIT = 4  # status readback (CLA / CTN OR)

J2A_OP_NOP = 0
J2A_OP_READ = 1
J2A_OP_WRITE = 2
J2A_STATUS_SUCCESS = 0
J2A_STATUS_SLVERR = 1
J2A_STATUS_DECERR = 2
J2A_STATUS_BUSY = 3

# pack_jtag2axi_caps: bus_type | addr[5:0]<<1 | data_enc<<7 | wr_pl<<10 | rd_pl<<12
DTP_EXPECTED_SMC_OTP_JTAG2AXI_CAPS = (
    (0x3 << 12) | (0x3 << 10) | (0x2 << 7) | (32 << 1) | 1
)


def pack_ic_reset_ports(
    *,
    reset_hold: int = 1,
    port_enable: dict[int, int] | None = None,
    port_control: dict[int, int] | None = None,
) -> int:
    """Pack SMU IC_RESET TDR by port index (0=EXT, 4=SMC cold_reset_n)."""
    value = SMU_IC_RESET_DEFAULT & ~0x1
    value |= reset_hold & 0x1
    for idx, en in (port_enable or {}).items():
        bit = 1 + 2 * int(idx)
        value = (value & ~(1 << bit)) | ((en & 0x1) << bit)
    for idx, ctrl in (port_control or {}).items():
        bit = 2 + 2 * int(idx)
        value = (value & ~(1 << bit)) | ((ctrl & 0x1) << bit)
    return value & SMU_IC_RESET_DEFAULT

# SEP=0 ties sep_feat_ctrl to 0 -> JTAG2AXI gated. Prefer forcing the computed
# security_disable net (continuous assign of feat_ctrl may ignore Force on fields).
_SECURITY_DISABLE_CANDIDATES = (
    "u_dut.u_dtp.u_jtag_intf_unit.u_jtag_ptap.smc_jtag2axi_security_disable",
    "u_dut.u_dtp.u_jtag_ptap.smc_jtag2axi_security_disable",
)
_OTP_SECURITY_DISABLE_CANDIDATES = (
    "u_dut.u_dtp.u_jtag_intf_unit.u_jtag_ptap.smc_otp_jtag2axi_security_disable",
    "u_dut.u_dtp.u_jtag_ptap.smc_otp_jtag2axi_security_disable",
)
_SEP_OTP_SECURITY_DISABLE_CANDIDATES = (
    "u_dut.u_dtp.u_jtag_intf_unit.u_jtag_ptap.sep_otp_jtag2axi_security_disable",
    "u_dut.u_dtp.u_jtag_ptap.sep_otp_jtag2axi_security_disable",
)
_FEAT_CTRL_CANDIDATES = (
    "u_dut.sep_feat_ctrl.soc_debug",
    "u_dut.sep_feat_ctrl.ap_debug",
    "u_dut.u_dtp.feat_ctrl_i.soc_debug",
    "u_dut.u_dtp.feat_ctrl_i.ap_debug",
)
_OTP_FEAT_CTRL_CANDIDATES = (
    "u_dut.sep_feat_ctrl.fuse_test",
    "u_dut.sep_feat_ctrl.soc_debug",
    "u_dut.sep_feat_ctrl.ap_debug",
    "u_dut.u_dtp.feat_ctrl_i.fuse_test",
    "u_dut.u_dtp.feat_ctrl_i.soc_debug",
    "u_dut.u_dtp.feat_ctrl_i.ap_debug",
)
_SEP_OTP_FEAT_CTRL_CANDIDATES = (
    "u_dut.sep_feat_ctrl.fuse_test",
    "u_dut.sep_feat_ctrl.sep_debug",
    "u_dut.sep_feat_ctrl.soc_debug",
    "u_dut.sep_feat_ctrl.ap_debug",
    "u_dut.u_dtp.feat_ctrl_i.fuse_test",
    "u_dut.u_dtp.feat_ctrl_i.sep_debug",
    "u_dut.u_dtp.feat_ctrl_i.soc_debug",
    "u_dut.u_dtp.feat_ctrl_i.ap_debug",
)


def pack_debug_control(
    *,
    boot_stall: int = 0,
    boot_stall_ovrd: int = 0,
    cla_clock_stop_en: int = 0,
    jtag_clock_stop: int = 0,
) -> int:
    return (
        ((boot_stall & 0x1) << DBG_BOOT_STALL_BIT)
        | ((boot_stall_ovrd & 0x1) << DBG_BOOT_STALL_OVRD_BIT)
        | ((cla_clock_stop_en & 0x1) << DBG_CLA_CLOCK_STOP_EN_BIT)
        | ((jtag_clock_stop & 0x1) << DBG_JTAG_CLOCK_STOP_BIT)
    )


def pack_single_op(
    op: int,
    addr: int,
    data: int = 0,
    wstrb: int = 0,
    size: int = SMC_DBG_AXSIZE_8B,
) -> int:
    """Pack SMC_AXI_SINGLE_OP DR (LSB-first): OP|SIZE|WSTRB|DATA|ADDR."""
    return (
        (int(op) & 0x3)
        | ((size & 0x3) << 2)
        | ((wstrb & 0xFF) << 4)
        | ((data & ((1 << 64) - 1)) << 12)
        | ((addr & ((1 << 56) - 1)) << 76)
    )


def unpack_single_op(value: int) -> tuple[int, int]:
    """Return (status, rdata) from captured SINGLE_OP DR."""
    status = int(value) & 0x3
    rdata = (int(value) >> 12) & ((1 << 64) - 1)
    return status, rdata


def make_smu_jtag_tap(dut, period_ns: float) -> OcahJtagTap:
    """Build OcahJtagTap with DEBUG_CONTROL + SMC JTAG2AXI register map."""
    device = OcahJtagDevice(
        name="smu_ptap",
        idcode=DTP_DEFAULT_IDCODE,
        ir_width=DTP_IR_WIDTH,
        idle_delay=2,
        add_bypass=True,
    )
    device.add_reg("IDCODE", 32, 0x01)
    device.add_reg("DEBUG_CONTROL", DTP_DEBUG_CONTROL_LEN, DTP_IR_DEBUG_CONTROL, write=True)
    device.add_reg("IC_RESET", SMU_IC_RESET_LEN, DTP_IR_IC_RESET, write=True)
    device.add_reg("EXTEST", DTP_BSR_MODEL_LEN, DTP_IR_EXTEST, write=True)
    device.add_reg("SMC_JTAG2AXI_CAPS", DTP_JTAG2AXI_CAPS_LEN, DTP_IR_SMC_JTAG2AXI_CAPS)
    device.add_reg(
        "SMC_AXI_SINGLE_OP",
        SMC_DBG_SINGLE_OP_LEN,
        DTP_IR_SMC_AXI_SINGLE_OP,
        write=True,
    )
    device.add_reg(
        "SMC_OTP_JTAG2AXI_CAPS",
        DTP_JTAG2AXI_CAPS_LEN,
        DTP_IR_SMC_OTP_JTAG2AXI_CAPS,
    )
    device.add_reg(
        "SMC_OTP_AXI_SINGLE_OP",
        SMC_OTP_SINGLE_OP_LEN,
        DTP_IR_SMC_OTP_AXI_SINGLE_OP,
        write=True,
    )
    device.add_reg(
        "SEP_OTP_JTAG2AXI_CAPS",
        DTP_JTAG2AXI_CAPS_LEN,
        DTP_IR_SEP_OTP_JTAG2AXI_CAPS,
    )
    device.add_reg(
        "SEP_OTP_AXI_SINGLE_OP",
        SMC_OTP_SINGLE_OP_LEN,
        DTP_IR_SEP_OTP_AXI_SINGLE_OP,
        write=True,
    )
    jtag = OcahJtagTap(
        dut,
        name="smu_ptap",
        tck_period_ns=period_ns,
        ir_width=DTP_IR_WIDTH,
        tap_type="ptap",
        signal_map={
            "tck": "jtag_tck",
            "tms": "jtag_tms",
            "tdi": "jtag_tdi",
            "tdo": "jtag_tdo",
            "trst": "jtag_trst",
            "tdo_oen": "jtag_tdo_oen",
        },
    )
    jtag.add_device(device)
    jtag.init_signals()
    return jtag


def _resolve_path(dut, path: str):
    node = dut
    for part in path.split("."):
        if not hasattr(node, part):
            return None
        node = getattr(node, part)
    return node


def _force_security_disable(dut, candidates, value: int, logger=None) -> list:
    """Force security_disable nets; verify readback (Verilator rejects continuous)."""
    forced = []
    for path in candidates:
        handle = _resolve_path(dut, path)
        if handle is None:
            continue
        try:
            handle.value = Force(int(value) & 1)
            if int(handle.value) != (int(value) & 1):
                if logger is not None:
                    logger.debug(
                        "Force %s ignored (readback mismatch); skip", path
                    )
                continue
            forced.append(handle)
            if logger is not None:
                logger.info("Forced %s = %d", path, int(value) & 1)
        except Exception as exc:  # noqa: BLE001
            if logger is not None:
                logger.debug("Could not force %s: %s", path, exc)
    return forced


def force_jtag2axi_lifecycle_enable(dut, logger=None) -> list:
    """Ungate SMC fabric JTAG2AXI under SEP=0 (feat_ctrl tied off).

    Prefer feat_ctrl Force (Verilator-safe with forceable). Do not trust a bare
    Force on continuous security_disable — VPI may ERROR without raising.
    """
    try:
        return force_feat_ctrl_bits(
            dut, {"soc_debug": 1, "ap_debug": 1}, logger
        )
    except AssertionError:
        pass

    forced = _force_security_disable(
        dut, _SECURITY_DISABLE_CANDIDATES, 0, logger
    )
    if forced:
        return forced

    raise AssertionError(
        "Could not Force feat_ctrl enables or smc_jtag2axi_security_disable=0"
    )


def force_jtag2axi_lifecycle_disable(dut, logger=None) -> list:
    """Force-gate SMC fabric JTAG2AXI (clear feat_ctrl or security_disable=1)."""
    try:
        return force_feat_ctrl_bits(
            dut, {"soc_debug": 0, "ap_debug": 0}, logger
        )
    except AssertionError:
        pass

    forced = _force_security_disable(
        dut, _SECURITY_DISABLE_CANDIDATES, 1, logger
    )
    if forced:
        return forced

    raise AssertionError(
        "Could not Force feat_ctrl clear or smc_jtag2axi_security_disable=1"
    )


def force_otp_jtag2axi_lifecycle_enable(dut, logger=None) -> list:
    """Ungate SMC OTP-over-JTAG under SEP=0 (needs fuse_test|soc_debug|ap_debug)."""
    try:
        return force_feat_ctrl_bits(
            dut,
            {"fuse_test": 1, "soc_debug": 1, "ap_debug": 1},
            logger,
        )
    except AssertionError:
        pass

    forced = _force_security_disable(
        dut, _OTP_SECURITY_DISABLE_CANDIDATES, 0, logger
    )
    if forced:
        return forced

    raise AssertionError(
        "Could not Force OTP feat_ctrl enables or smc_otp_jtag2axi_security_disable=0"
    )


def force_otp_jtag2axi_lifecycle_disable(dut, logger=None) -> list:
    """Force-gate SMC OTP-over-JTAG by clearing fuse_test only.

    RTL: security_disable = !fuse_test || !soc_debug || !ap_debug.
    Clearing fuse_test alone gates OTP while leaving fabric (soc|ap) ungated —
    needed when OTP and fabric Forces share one Verilator packed word.
    """
    try:
        return force_feat_ctrl_bits(dut, {"fuse_test": 0}, logger)
    except AssertionError:
        pass

    forced = _force_security_disable(
        dut, _OTP_SECURITY_DISABLE_CANDIDATES, 1, logger
    )
    if forced:
        return forced

    raise AssertionError(
        "Could not Force OTP fuse_test clear or smc_otp_jtag2axi_security_disable=1"
    )


def force_sep_otp_jtag2axi_lifecycle_enable(dut, logger=None) -> list:
    """Force-enable SEP OTP-over-JTAG path (security_disable=0 or feat bits=1)."""
    try:
        return force_feat_ctrl_bits(
            dut,
            {
                "fuse_test": 1,
                "sep_debug": 1,
                "soc_debug": 1,
                "ap_debug": 1,
            },
            logger,
        )
    except AssertionError:
        pass

    forced = _force_security_disable(
        dut, _SEP_OTP_SECURITY_DISABLE_CANDIDATES, 0, logger
    )
    if forced:
        return forced
    raise AssertionError(
        "Could not Force SEP OTP feat_ctrl or sep_otp_jtag2axi_security_disable=0"
    )


def force_sep_otp_jtag2axi_lifecycle_disable(dut, logger=None) -> list:
    """Force-gate SEP OTP-over-JTAG (clear feat_ctrl or security_disable=1)."""
    try:
        return force_feat_ctrl_bits(
            dut,
            {
                "fuse_test": 0,
                "sep_debug": 0,
                "soc_debug": 0,
                "ap_debug": 0,
            },
            logger,
        )
    except AssertionError:
        pass

    forced = _force_security_disable(
        dut, _SEP_OTP_SECURITY_DISABLE_CANDIDATES, 1, logger
    )
    if forced:
        return forced
    raise AssertionError(
        "Could not Force SEP OTP feat_ctrl clear or sep_otp_jtag2axi_security_disable=1"
    )


# jtag_smc_reset_ctrl_t packed [135:0]: ovrd[135:68] | val[67:0]
# Within ovrd/val LSB: fuse, warm, cool, cold, then ss_cold[31:0], ss_warm[31:0].
_SMC_RESET_CTRL_BITS = {
    "fuse_reset_n_ovrd": 68,
    "warm_reset_n_ovrd": 69,
    "cool_reset_n_ovrd": 70,
    "cold_reset_n_ovrd": 71,
    "fuse_reset_n_val": 0,
    "warm_reset_n_val": 1,
    "cool_reset_n_val": 2,
    "cold_reset_n_val": 3,
}


def _ss_reset_ctrl_bit_index(leaf: str, idx: int) -> int:
    """Packed bit index for ss_cold/ss_warm ovrd/val[idx]."""
    if idx < 0 or idx > 31:
        raise AssertionError(f"ss reset index out of range: {idx}")
    if leaf == "ss_cold_reset_n_ovrd":
        return 72 + idx
    if leaf == "ss_warm_reset_n_ovrd":
        return 104 + idx
    if leaf == "ss_cold_reset_n_val":
        return 4 + idx
    if leaf == "ss_warm_reset_n_val":
        return 36 + idx
    raise AssertionError(f"Unknown ss reset leaf: {leaf}")


def read_smc_reset_ctrl_bit(dut, leaf: str, idx: int | None = None) -> int:
    """Read one jtag_smc_reset_ctrl ovrd/val leaf (hierarchical or packed).

    For scalar fuse/warm/cool/cold leaves, pass ``leaf`` only.
    For ss_* vectors, pass ``leaf`` + ``idx`` (0..31).
    """
    ctrl = dut.u_dut.jtag_smc_reset_ctrl
    if idx is not None:
        bit = _ss_reset_ctrl_bit_index(leaf, idx)
        # Prefer packed whole-struct (VCS may expose ss_* as non-indexable GPI).
        try:
            return (int(ctrl.value) >> bit) & 1
        except Exception:  # noqa: BLE001
            pass
        if hasattr(ctrl, "ovrd") and hasattr(ctrl, "val"):
            group = "ovrd" if leaf.endswith("_ovrd") else "val"
            vec = getattr(getattr(ctrl, group), leaf)
            try:
                return int(vec[idx].value) & 1
            except Exception:  # noqa: BLE001
                return (int(vec.value) >> idx) & 1
        raise AssertionError(f"Cannot read jtag_smc_reset_ctrl.{leaf}[{idx}]")

    if leaf not in _SMC_RESET_CTRL_BITS:
        raise AssertionError(f"Unknown jtag_smc_reset_ctrl leaf: {leaf}")
    if hasattr(ctrl, "ovrd") and hasattr(ctrl, "val"):
        group = "ovrd" if leaf.endswith("_ovrd") else "val"
        return int(getattr(getattr(ctrl, group), leaf).value) & 1
    return (int(ctrl.value) >> _SMC_RESET_CTRL_BITS[leaf]) & 1


# Bit positions in sep_efuse_map_lc_disable_reg_t (packed, MSB-first → bit0 = sep_debug).
_FEAT_CTRL_BIT_POS = {
    "sep_debug": 0,
    "soc_debug": 1,
    "ap_debug": 2,
    "ap_trace": 3,
    "sip_debug": 4,
    "fuse_test": 32,
}

_FEAT_CTRL_PACKED_PATHS = (
    "u_dut.sep_feat_ctrl",
    "u_dut.u_dtp.feat_ctrl_i",
    "u_dut.u_dtp.u_jtag_intf_unit.u_jtag_ptap.feat_ctrl_i",
)

# Verilator Force readback returns the continuous (tied-off) value, not the
# Forced word. Keep a path-keyed shadow so sequential Force calls RMW correctly.
_FEAT_CTRL_FORCE_SHADOW: dict[str, int] = {}


def force_feat_ctrl_bits(dut, bit_values: dict, logger=None) -> list:
    """Force selected sep_feat_ctrl / feat_ctrl_i leaf bits.

    bit_values maps leaf name -> 0/1, e.g. {"soc_debug": 0, "ap_debug": 1}.

    VCS exposes packed-struct leaves as hierarchical handles. Verilator exposes
    the whole 64-bit packed word only — fall back to Force on the word with
    known bit positions from sep_efuse_map_lc_disable_reg_t. Packed Forces are
    RMW'd via `_FEAT_CTRL_FORCE_SHADOW` (readback under Force is unreliable).
    """
    forced = []
    prefixes = (
        "u_dut.sep_feat_ctrl.",
        "u_dut.u_dtp.feat_ctrl_i.",
        "u_dut.u_dtp.u_jtag_intf_unit.u_jtag_ptap.feat_ctrl_i.",
    )
    leaf_ok = True
    for leaf, val in bit_values.items():
        hit = False
        for prefix in prefixes:
            path = prefix + leaf
            handle = _resolve_path(dut, path)
            if handle is None:
                continue
            try:
                handle.value = Force(int(val) & 1)
                forced.append(handle)
                hit = True
                if logger is not None:
                    logger.info("Forced %s = %d", path, int(val) & 1)
                break
            except Exception as exc:  # noqa: BLE001
                if logger is not None:
                    logger.debug("Could not force %s: %s", path, exc)
        if not hit:
            leaf_ok = False
            break
    if leaf_ok and forced:
        return forced

    # Verilator / packed-word fallback: RMW via Force shadow (not handle readback).
    packed_forced = []
    for path in _FEAT_CTRL_PACKED_PATHS:
        handle = _resolve_path(dut, path)
        if handle is None:
            continue
        try:
            word = int(_FEAT_CTRL_FORCE_SHADOW.get(path, 0))
            for leaf, val in bit_values.items():
                if leaf not in _FEAT_CTRL_BIT_POS:
                    raise AssertionError(
                        f"Unknown feat_ctrl leaf for packed Force: {leaf}"
                    )
                bit = _FEAT_CTRL_BIT_POS[leaf]
                if int(val) & 1:
                    word |= 1 << bit
                else:
                    word &= ~(1 << bit)
            handle.value = Force(word)
            _FEAT_CTRL_FORCE_SHADOW[path] = word
            packed_forced.append(handle)
            if logger is not None:
                logger.info(
                    "Forced packed %s = 0x%x (Verilator shadow RMW)", path, word
                )
        except Exception as exc:  # noqa: BLE001
            if logger is not None:
                logger.debug("Could not force packed %s: %s", path, exc)
    if not packed_forced:
        missing = ",".join(bit_values.keys())
        raise AssertionError(f"Could not Force feat_ctrl bits ({missing})")
    return packed_forced


def release_forced(handles: Iterable) -> None:
    for handle in handles:
        try:
            handle.value = Release()
        except Exception:
            pass
    # Packed Force shadow is invalid after Release (net returns to continuous).
    _FEAT_CTRL_FORCE_SHADOW.clear()


def pack_otp_single_op(
    op: int,
    addr: int,
    data: int = 0,
    wstrb: int = 0,
    size: int = SMC_OTP_AXSIZE_4B,
) -> int:
    """Pack SMC_OTP_AXI_SINGLE_OP DR: OP|SIZE|WSTRB|DATA32|ADDR32."""
    return (
        (int(op) & 0x3)
        | ((size & 0x3) << 2)
        | ((wstrb & 0xF) << 4)
        | ((data & ((1 << 32) - 1)) << 8)
        | ((addr & ((1 << 32) - 1)) << 40)
    )


def unpack_otp_single_op(value: int) -> tuple[int, int]:
    """Return (status, rdata) from captured OTP SINGLE_OP DR."""
    status = int(value) & 0x3
    rdata = (int(value) >> 8) & ((1 << 32) - 1)
    return status, rdata


async def jtag2axi_single_write(
    jtag: OcahJtagTap,
    addr: int,
    data: int,
    *,
    wstrb: int = 0xFF,
    size: int = SMC_DBG_AXSIZE_8B,
    poll_limit: int = 128,
    require_complete: bool = False,
) -> tuple[int, int]:
    raw = pack_single_op(J2A_OP_WRITE, addr, data, wstrb=wstrb, size=size)
    await jtag.write("SMC_AXI_SINGLE_OP", raw)
    # Allow AXI fabric latency before first status sample.
    await ClockCycles(cocotb.top.clk_smu_i, 32)
    status, rdata = J2A_STATUS_BUSY, 0
    for _ in range(poll_limit):
        capt = await jtag.read("SMC_AXI_SINGLE_OP", shift_value=0)
        status, rdata = unpack_single_op(capt)
        if status != J2A_STATUS_BUSY:
            break
        await ClockCycles(cocotb.top.clk_smu_i, 16)
    if require_complete and status == J2A_STATUS_BUSY:
        raise TimeoutError(
            f"JTAG2AXI write stuck BUSY after {poll_limit} polls @ {addr:#x}"
        )
    return status, rdata


async def jtag2axi_single_read(
    jtag: OcahJtagTap,
    addr: int,
    *,
    size: int = SMC_DBG_AXSIZE_8B,
    poll_limit: int = 128,
    require_complete: bool = False,
) -> tuple[int, int]:
    raw = pack_single_op(J2A_OP_READ, addr, 0, wstrb=0, size=size)
    await jtag.write("SMC_AXI_SINGLE_OP", raw)
    await ClockCycles(cocotb.top.clk_smu_i, 32)
    status, rdata = J2A_STATUS_BUSY, 0
    for _ in range(poll_limit):
        capt = await jtag.read("SMC_AXI_SINGLE_OP", shift_value=0)
        status, rdata = unpack_single_op(capt)
        if status != J2A_STATUS_BUSY:
            break
        await ClockCycles(cocotb.top.clk_smu_i, 16)
    if require_complete and status == J2A_STATUS_BUSY:
        raise TimeoutError(
            f"JTAG2AXI read stuck BUSY after {poll_limit} polls @ {addr:#x}"
        )
    return status, rdata


async def otp_jtag2axi_single_read(
    jtag: OcahJtagTap,
    addr: int,
    *,
    size: int = SMC_OTP_AXSIZE_4B,
    poll_limit: int = 64,
    require_complete: bool = False,
) -> tuple[int, int]:
    raw = pack_otp_single_op(J2A_OP_READ, addr, 0, wstrb=0, size=size)
    await jtag.write("SMC_OTP_AXI_SINGLE_OP", raw)
    await ClockCycles(cocotb.top.clk_smu_i, 32)
    status, rdata = J2A_STATUS_BUSY, 0
    for _ in range(poll_limit):
        capt = await jtag.read("SMC_OTP_AXI_SINGLE_OP", shift_value=0)
        status, rdata = unpack_otp_single_op(capt)
        if status != J2A_STATUS_BUSY:
            break
        await ClockCycles(cocotb.top.clk_smu_i, 16)
    if require_complete and status == J2A_STATUS_BUSY:
        raise TimeoutError(
            f"OTP JTAG2AXI read stuck BUSY after {poll_limit} polls @ {addr:#x}"
        )
    return status, rdata


async def otp_jtag2axi_single_write(
    jtag: OcahJtagTap,
    addr: int,
    data: int,
    *,
    wstrb: int = 0xF,
    size: int = SMC_OTP_AXSIZE_4B,
    poll_limit: int = 64,
    require_complete: bool = False,
) -> tuple[int, int]:
    raw = pack_otp_single_op(J2A_OP_WRITE, addr, data, wstrb=wstrb, size=size)
    await jtag.write("SMC_OTP_AXI_SINGLE_OP", raw)
    await ClockCycles(cocotb.top.clk_smu_i, 32)
    status, rdata = J2A_STATUS_BUSY, 0
    for _ in range(poll_limit):
        capt = await jtag.read("SMC_OTP_AXI_SINGLE_OP", shift_value=0)
        status, rdata = unpack_otp_single_op(capt)
        if status != J2A_STATUS_BUSY:
            break
        await ClockCycles(cocotb.top.clk_smu_i, 16)
    if require_complete and status == J2A_STATUS_BUSY:
        raise TimeoutError(
            f"OTP JTAG2AXI write stuck BUSY after {poll_limit} polls @ {addr:#x}"
        )
    return status, rdata


async def sep_otp_jtag2axi_single_read(
    jtag: OcahJtagTap,
    addr: int,
    *,
    size: int = SMC_OTP_AXSIZE_4B,
    poll_limit: int = 32,
) -> tuple[int, int]:
    """Issue SEP OTP SINGLE_OP read (SEP=0: bridge absent; for idle contrast)."""
    raw = pack_otp_single_op(J2A_OP_READ, addr, 0, wstrb=0, size=size)
    await jtag.write("SEP_OTP_AXI_SINGLE_OP", raw)
    await ClockCycles(cocotb.top.clk_smu_i, 32)
    status, rdata = J2A_STATUS_BUSY, 0
    for _ in range(poll_limit):
        capt = await jtag.read("SEP_OTP_AXI_SINGLE_OP", shift_value=0)
        status, rdata = unpack_otp_single_op(capt)
        if status != J2A_STATUS_BUSY:
            break
        await ClockCycles(cocotb.top.clk_smu_i, 16)
    return status, rdata


async def wdt_unlock(jtag: OcahJtagTap, magic: int = 0x51F15E) -> int:
    """Write WDT KEY (offset 0x1C, upper 32b of 8B lane) to unlock once."""
    st, _ = await jtag2axi_single_write(
        jtag,
        0xC000_001C,
        (magic & 0xFFFF_FFFF) << 32,
        wstrb=0xF0,
        size=SMC_DBG_AXSIZE_4B,
    )
    return st


def shadow_map_word32(dut, byte_off: int) -> Optional[int]:
    """Best-effort 32b word from TB ``smc_shadow_regs`` (packed union).

    Returns None if the handle is not integer-accessible under this simulator.
    """
    word_idx = int(byte_off) // 4
    handle = getattr(dut, "smc_shadow_regs", None)
    if handle is None:
        return None
    # Flat LogicArray / IntegerObject
    try:
        raw = int(handle.value)
        return (raw >> (word_idx * 32)) & 0xFFFF_FFFF
    except (AttributeError, TypeError, ValueError):
        pass
    # Packed union: .values[word] or .values as array
    try:
        values = handle.values
        elem = values[word_idx]
        return int(elem.value if hasattr(elem, "value") else elem) & 0xFFFF_FFFF
    except (AttributeError, TypeError, ValueError, IndexError, KeyError):
        return None
