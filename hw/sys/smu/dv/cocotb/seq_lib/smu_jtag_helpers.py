# SPDX-License-Identifier: Apache-2.0
"""SMU JTAG / JTAG2AXI helpers (local constants; avoid DTP ``env`` package clash)."""

from __future__ import annotations

from typing import Optional

import cocotb
from cocotb.triggers import ClockCycles

from ocah_jtag_vip import OcahJtagDevice, OcahJtagMasterDriver

# Lifecycle ungating: use seq_lib.smu_lcc_helpers (SEP=1 eFuse→LCC).
# SEP=0 ties sep_feat_ctrl='0'; Force-based helpers were removed.

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
# Absolute SMC eFuse map window (smc_reg.svh / INTERFACE_SEL decode).
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


def make_smu_jtag_tap(dut, period_ns: float) -> OcahJtagMasterDriver:
    """Build OcahJtagMasterDriver with DEBUG_CONTROL + SMC JTAG2AXI register map."""
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
    jtag = OcahJtagMasterDriver(
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


def _sample_bit(signal, name: str) -> int:
    """Resolve a Logic signal to 0/1; fail closed on X/Z."""
    val = signal.value
    if not val.is_resolvable:
        raise AssertionError(f"X/Z sample on {name}: {val}")
    return int(val) & 1


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
            packed = ctrl.value
            if not packed.is_resolvable:
                raise AssertionError(
                    f"X/Z sample on jtag_smc_reset_ctrl (packed) for {leaf}[{idx}]: "
                    f"{packed}"
                )
            return (int(packed) >> bit) & 1
        except AssertionError:
            raise
        except Exception:  # noqa: BLE001
            pass
        if hasattr(ctrl, "ovrd") and hasattr(ctrl, "val"):
            group = "ovrd" if leaf.endswith("_ovrd") else "val"
            vec = getattr(getattr(ctrl, group), leaf)
            try:
                return _sample_bit(vec[idx], f"jtag_smc_reset_ctrl.{leaf}[{idx}]")
            except Exception:  # noqa: BLE001
                v = vec.value
                if not v.is_resolvable:
                    raise AssertionError(
                        f"X/Z sample on jtag_smc_reset_ctrl.{leaf}: {v}"
                    )
                return (int(v) >> idx) & 1
        raise AssertionError(f"Cannot read jtag_smc_reset_ctrl.{leaf}[{idx}]")

    if leaf not in _SMC_RESET_CTRL_BITS:
        raise AssertionError(f"Unknown jtag_smc_reset_ctrl leaf: {leaf}")
    if hasattr(ctrl, "ovrd") and hasattr(ctrl, "val"):
        group = "ovrd" if leaf.endswith("_ovrd") else "val"
        return _sample_bit(
            getattr(getattr(ctrl, group), leaf),
            f"jtag_smc_reset_ctrl.{leaf}",
        )
    packed = ctrl.value
    if not packed.is_resolvable:
        raise AssertionError(
            f"X/Z sample on jtag_smc_reset_ctrl (packed) for {leaf}: {packed}"
        )
    return (int(packed) >> _SMC_RESET_CTRL_BITS[leaf]) & 1


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
    jtag: OcahJtagMasterDriver,
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
    jtag: OcahJtagMasterDriver,
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
    jtag: OcahJtagMasterDriver,
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
    jtag: OcahJtagMasterDriver,
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
    jtag: OcahJtagMasterDriver,
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


async def wdt_unlock(jtag: OcahJtagMasterDriver, magic: int = 0x51F15E) -> int:
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
