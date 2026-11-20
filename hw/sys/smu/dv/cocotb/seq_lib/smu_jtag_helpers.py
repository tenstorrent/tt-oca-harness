# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMU JTAG / JTAG2AXI helpers.

Every opcode, field position and geometry constant in this module is a
DV-owned table. The instruction opcodes, the JTAG2AXI bridge TDR names and
the DMI and ``sbcs`` encodings come from the DTP bench's ``dtp_types``
module; everything else is transcribed from the PTAP architecture document,
the SMU design specification and the Integrator Guide, cited next to the
value.

A JTAG2AXI access is a RISC-V System Bus Access through the bridge's Debug
Module, reached by scans of its 41-bit DMI TDR.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import cocotb
from dtp_types import (
    DMI_LEN,
    DTMCS_LEN,
    DTP_DMI_SETTLE_TCK,
    DTP_IR_WIDTH,
    JTAG2AXI_TARGETS,
    DtpDmiOp,
    DtpDmiStatus,
    DtpDmReg,
    DtpJtag2AxiTargetCfg,
    DtpJtagInstr,
    pack_dmi,
    pack_sbcs,
    unpack_dmi,
    unpack_sbcs,
)
from ocah_jtag_vip import OcahJtagDevice, OcahJtagMasterDriver

from seq_lib.smu_tb_pins import smu_scope

# Lifecycle ungating: use seq_lib.smu_lcc_helpers (SEP=1 eFuse→LCC).


def dtp_ir_opcode(name: str) -> int:
    """PTAP IR opcode for instruction ``name``.

    ``DtpJtagInstr`` (hw/sys/dtp/dv/cocotb/env/dtp_types.py) transcribes the
    "Instruction Encodings" table of hw/ip/jtag/jtag_intf_unit/doc/interface.adoc.
    """
    try:
        return int(DtpJtagInstr[name])
    except KeyError as exc:
        raise KeyError(f"{name} is not a DtpJtagInstr instruction name") from exc


# hw/ip/jtag/jtag_ptap/doc/architecture.adoc, "JTAG Capabilities" table.
DTP_JTAG_CAPS_SEP_DBG_EN_BIT = 42

# IDCODE with every JTAG_IDCODE_* parameter at the default given in
# doc/integrator/src/smu.adoc, "SMU Default Parameters" (MFR_ID 11'h000,
# PART_NUM 16'h0000, SI_REV 4'h0): only the architecture.adoc "ID Code"
# marker bit (bit 0, always 1) is set.
DTP_DEFAULT_IDCODE = 0x0000_0001
DTP_IR_IDCODE = dtp_ir_opcode("IDCODE")
DTP_IR_DEBUG_CONTROL = dtp_ir_opcode("DEBUG_CONTROL")
DTP_IR_IC_RESET = dtp_ir_opcode("IC_RESET")
DTP_IR_EXTEST = dtp_ir_opcode("EXTEST")
DTP_IR_SAMPLE_PRELOAD = dtp_ir_opcode("SAMPLE_PRELOAD")
DTP_IR_TAP_3DCR = dtp_ir_opcode("TAP_3DCR")

# TAP_3DCR field widths (hw/sys/dtp/doc/jtag.adoc "STAP Secondary Scan Path";
# jtag_ptap architecture "3DCR"). The wrapper's STAP chain order and the
# scan-word packers over it live in smu_boundary_regs.
PTAP_3DCR_WIDTH = 2
STAP_3DCR_WIDTH = 3


def ptap_3dcr_value(*, config_hold: int, select: int) -> int:
    """LSB-first PTAP 3DCR: config_hold then stap_select (DtpStap3dcrModel)."""
    return (config_hold & 0x1) | ((select & 0x1) << 1)


def stap_3dcr_payload(*, config_hold: int, stap_sel: int, tms_hold: int) -> int:
    """LSB-first STAP 3DCR: config_hold, stap_sel, tms_hold."""
    return (config_hold & 0x1) | ((stap_sel & 0x1) << 1) | ((tms_hold & 0x1) << 2)


DTP_IR_JTAG_CAPS = dtp_ir_opcode("JTAG_CAPS")
# IEEE 1149.1 all-ones BYPASS encoding; the instruction table also decodes
# 0x00 as BYPASS.
DTP_IR_BYPASS = dtp_ir_opcode("BYPASS_3F")
DTP_DEBUG_CONTROL_LEN = 5
DTP_JTAG_CAPS_LEN = 60
# Compact OSS BSR loopback model (scan_in <- scan_out); matches DTP OSS.
DTP_BSR_MODEL_LEN = 8
# The 6-bit IR decodes to a 64-wide one-hot bus indexed by opcode
# (architecture.adoc "Module Hierarchy", jtag_inst_reg).
DTP_EXTEST_DECODED_BIT = DTP_IR_EXTEST

# IC_RESET TDR. architecture.adoc "IC_RESET Support" gives the per-port
# layout: bit 0 reset_hold, port n at {reset_enable: 2n+1, reset_control:
# 2n+2}, every bit resetting to 1 (reset_enable=1 is "override disabled"),
# length 2 * ports + 1. doc/integrator/src/smu.adoc "IC_RESET TDR
# Structure" gives the SMU composition: TDI -> SMC slice (68 ports) -> SEP
# slice (0 ports at SEP=0, SMU_IC_RESET_NUM_SEP_PORTS_AT_SEP1 at SEP=1) ->
# external slice -> reset_hold -> TDO, so with LSB-first shifting port 0 is
# the external port and the SMC slice follows.
# The slice widths have to match the DUT exactly: a DR shorter than the TDR by
# 2k bits lands every packed field k ports away from the one it names.
# "SMC slice (TDI to TDO)" lists ss_warm_reset_n[31:0], ss_cold_reset_n[31:0],
# cold, cool, warm, fuse (nearest the SEP slice), [31] nearer TDI than [0]:
# counted from the TDO end that is fuse, warm, cool, cold, ss_cold[0..31],
# ss_warm[0..31]. The external slice type is adopter-defined; the SMU bench
# elaborates one port.
SMU_IC_RESET_NUM_SMC_PORTS = 68
# doc/integrator/src/smu.adoc "IC_RESET TDR Structure": the SEP slice is
# 8 ports at SEP=1 and 0 otherwise. The named tuple is the stimulus list
# (scan order from TDI), not the source of that width: a port added only
# to the tuple must fail this check rather than silently move every SMC
# index and the golden length together.
SMU_IC_RESET_SEP_SLICE_PORTS_AT_SEP1 = 8
SMU_IC_RESET_SEP_PORTS = (
    "abr_jtag_rst_n",
    "trng_jtag_rst_n",
    "sep_reset_n",
    "kmac_jtag_rst_n",
    "hmac_jtag_rst_n",
    "aes_jtag_rst_n",
    "otbn_jtag_rst_n",
    "km_jtag_rst_n",
)
if len(SMU_IC_RESET_SEP_PORTS) != SMU_IC_RESET_SEP_SLICE_PORTS_AT_SEP1:
    raise RuntimeError(
        "SMU_IC_RESET_SEP_PORTS must list the Integrator Guide SEP slice "
        f"({SMU_IC_RESET_SEP_SLICE_PORTS_AT_SEP1} ports at SEP=1)"
    )
SMU_IC_RESET_NUM_SEP_PORTS_AT_SEP1 = SMU_IC_RESET_SEP_SLICE_PORTS_AT_SEP1


def _smu_ic_reset_sep_ports() -> int:
    """SEP IC_RESET slice width for the DUT this run elaborated.

    doc/integrator/src/smu.adoc "IC_RESET TDR Structure" enables the SEP
    slice only at SEP=1. The wrapper (tb_wrapper_top.sv, top module
    smu_wrapper_uvm_top) elaborates SEP=1 and carries the full SEP slice.
    Resolved from the cocotb top handle; outside a simulation, or under any
    other top, it falls back to the SEP=0 shape.
    """
    try:
        name = str(getattr(cocotb.top, "_name", "") or "")
    except Exception:  # noqa: BLE001 - no simulator, e.g. tooling imports
        return 0
    return SMU_IC_RESET_NUM_SEP_PORTS_AT_SEP1 if name == "smu_wrapper_uvm_top" else 0


SMU_IC_RESET_NUM_SEP_PORTS = _smu_ic_reset_sep_ports()
SMU_IC_RESET_NUM_EXT_PORTS = 1
SMU_IC_RESET_NUM_PORTS = (
    SMU_IC_RESET_NUM_SMC_PORTS + SMU_IC_RESET_NUM_SEP_PORTS + SMU_IC_RESET_NUM_EXT_PORTS
)
SMU_IC_RESET_LEN = 2 * SMU_IC_RESET_NUM_PORTS + 1
SMU_IC_RESET_DEFAULT = (1 << SMU_IC_RESET_LEN) - 1
SMU_IC_RESET_EXT_PORT = 0
SMU_IC_RESET_SMC_FUSE_PORT = SMU_IC_RESET_NUM_EXT_PORTS + SMU_IC_RESET_NUM_SEP_PORTS
SMU_IC_RESET_SMC_WARM_PORT = SMU_IC_RESET_SMC_FUSE_PORT + 1
SMU_IC_RESET_SMC_COOL_PORT = SMU_IC_RESET_SMC_FUSE_PORT + 2
SMU_IC_RESET_SMC_COLD_PORT = SMU_IC_RESET_SMC_FUSE_PORT + 3
SMU_IC_RESET_SMC_SS_COLD0_PORT = SMU_IC_RESET_SMC_FUSE_PORT + 4
SMU_IC_RESET_SMC_SS_WARM0_PORT = SMU_IC_RESET_SMC_SS_COLD0_PORT + 32


def ic_reset_enable_bit(port: int) -> int:
    """TDR bit of a port's reset_enable field."""
    return 1 + 2 * int(port)


def ic_reset_control_bit(port: int) -> int:
    """TDR bit of a port's reset_control field."""
    return 2 + 2 * int(port)


# Access sizes as AxSIZE and sbcs.sbaccess both encode them: log2 of the bytes.
SMC_DBG_AXSIZE_8B = 3
SMC_DBG_AXSIZE_4B = 2
SMC_OTP_AXSIZE_4B = 2
# hw/ip/efuse/doc/architecture.adoc, "Access Permissions and Security": the
# eFuse controller's error slave answers with data 0xbadcab1e.
SMC_OTP_ERR_DECODE_DATA = 0xBADC_AB1E
# hw/ip/jtag/jtag_ptap/doc/architecture.adoc Debug Control TDR table:
# bit 0 boot_stall, bit 1 boot_stall_ovrd (no PeakRDL #define).
DBG_BOOT_STALL_BIT = 0
DBG_BOOT_STALL_OVRD_BIT = 1
DBG_CLA_CLOCK_STOP_EN_BIT = 2
DBG_JTAG_CLOCK_STOP_BIT = 3
DBG_CLA_CLOCK_STOP_BIT = 4  # status readback (CLA / CTN OR)

# Outcome of one JTAG2AXI access as the transports below return it.
# System Bus Access reports SLVERR and DECERR alike as sberror 2, which
# returns J2A_STATUS_DECERR, so no access returns J2A_STATUS_SLVERR.
# J2A_STATUS_BUSY is an access outstanding when the poll budget runs out.
J2A_STATUS_SUCCESS = 0
J2A_STATUS_SLVERR = 1
J2A_STATUS_DECERR = 2
J2A_STATUS_BUSY = 3
J2A_STATUS_NAME = {
    J2A_STATUS_SUCCESS: "OKAY",
    J2A_STATUS_DECERR: "bus error",
    J2A_STATUS_BUSY: "BUSY (outstanding)",
}


def pack_ic_reset_ports(
    *,
    reset_hold: int = 1,
    port_enable: dict[int, int] | None = None,
    port_control: dict[int, int] | None = None,
) -> int:
    """Pack the SMU IC_RESET TDR by port index (SMU_IC_RESET_*_PORT)."""
    value = SMU_IC_RESET_DEFAULT & ~0x1
    value |= reset_hold & 0x1
    for idx, en in (port_enable or {}).items():
        bit = ic_reset_enable_bit(idx)
        value = (value & ~(1 << bit)) | ((en & 0x1) << bit)
    for idx, ctrl in (port_control or {}).items():
        bit = ic_reset_control_bit(idx)
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


def apply_axi_wstrb(prev: int, data: int, wstrb: int, nbytes: int) -> int:
    """Merge ``data`` into ``prev`` for each set WSTRB lane in ``nbytes``."""
    out = int(prev)
    for byte_idx in range(nbytes):
        if (wstrb >> byte_idx) & 1:
            shift = 8 * byte_idx
            out = (out & ~(0xFF << shift)) | (((int(data) >> shift) & 0xFF) << shift)
    return out


def add_jtag2axi_regs(device: OcahJtagDevice) -> None:
    """Register every JTAG2AXI bridge's DTMCS and DMI TDR under its instruction name."""
    for cfg in JTAG2AXI_TARGETS.values():
        device.add_reg(cfg.dtmcs_reg, DTMCS_LEN, int(cfg.dtmcs_instr), write=True)
        device.add_reg(cfg.dmi_reg, DMI_LEN, int(cfg.dmi_instr), write=True)


def make_smu_jtag_tap(dut, period_ns: float) -> OcahJtagMasterDriver:
    """Build OcahJtagMasterDriver with DEBUG_CONTROL + JTAG2AXI register map."""
    device = OcahJtagDevice(
        name="smu_ptap",
        idcode=DTP_DEFAULT_IDCODE,
        ir_width=DTP_IR_WIDTH,
        idle_delay=2,
        add_bypass=True,
    )
    device.add_reg("IDCODE", 32, DTP_IR_IDCODE)
    device.add_reg("DEBUG_CONTROL", DTP_DEBUG_CONTROL_LEN, DTP_IR_DEBUG_CONTROL, write=True)
    device.add_reg("JTAG_CAPS", DTP_JTAG_CAPS_LEN, DTP_IR_JTAG_CAPS)
    device.add_reg("IC_RESET", SMU_IC_RESET_LEN, DTP_IR_IC_RESET, write=True)
    device.add_reg("EXTEST", DTP_BSR_MODEL_LEN, DTP_IR_EXTEST, write=True)
    add_jtag2axi_regs(device)
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


# smc_pkg::jtag_smc_reset_ctrl_t as doc/integrator/src/smu.adoc describes it
# ("IC_RESET TDR Structure", "SMC slice (TDI to TDO)"): a packed struct of an
# `.ovrd` half above a `.val` half, each one bit per SMC port, whose fields
# are declared in TDI-to-TDO order -- ss_warm_reset_n[31:0],
# ss_cold_reset_n[31:0], cold, cool, warm, fuse. A packed struct places its
# first-declared field at the MSB, so within each half fuse_reset_n is bit 0
# and ss_warm_reset_n[31] the top bit.
_SMC_RESET_CTRL_HALF_BITS = SMU_IC_RESET_NUM_SMC_PORTS
_SMC_RESET_CTRL_VAL_LSB = 0
_SMC_RESET_CTRL_OVRD_LSB = _SMC_RESET_CTRL_HALF_BITS
_SMC_RESET_CTRL_FIELD_LSB = {
    "fuse_reset_n": 0,
    "warm_reset_n": 1,
    "cool_reset_n": 2,
    "cold_reset_n": 3,
    "ss_cold_reset_n": 4,
    "ss_warm_reset_n": 36,
}
_SMC_RESET_CTRL_SS_WIDTH = 32
_SMC_RESET_CTRL_SCALAR_LEAVES = (
    "fuse_reset_n_ovrd",
    "warm_reset_n_ovrd",
    "cool_reset_n_ovrd",
    "cold_reset_n_ovrd",
    "fuse_reset_n_val",
    "warm_reset_n_val",
    "cool_reset_n_val",
    "cold_reset_n_val",
)


def _smc_reset_ctrl_split(leaf: str) -> tuple[str, str]:
    """Split ``<field>_ovrd`` / ``<field>_val`` into (field, half)."""
    for half in ("ovrd", "val"):
        suffix = f"_{half}"
        if leaf.endswith(suffix):
            return leaf[: -len(suffix)], half
    raise AssertionError(f"Unknown jtag_smc_reset_ctrl leaf: {leaf}")


def smc_reset_ctrl_packed_bit(leaf: str, idx: int | None = None) -> int:
    """Bit index of a leaf in the packed jtag_smc_reset_ctrl_t word."""
    field, half = _smc_reset_ctrl_split(leaf)
    if field not in _SMC_RESET_CTRL_FIELD_LSB:
        raise AssertionError(f"Unknown jtag_smc_reset_ctrl leaf: {leaf}")
    base = _SMC_RESET_CTRL_OVRD_LSB if half == "ovrd" else _SMC_RESET_CTRL_VAL_LSB
    if field.startswith("ss_"):
        if idx is None or idx < 0 or idx >= _SMC_RESET_CTRL_SS_WIDTH:
            raise AssertionError(f"ss reset index out of range: {idx}")
        return base + _SMC_RESET_CTRL_FIELD_LSB[field] + idx
    if idx is not None:
        raise AssertionError(f"{leaf} is scalar; idx={idx} not allowed")
    return base + _SMC_RESET_CTRL_FIELD_LSB[field]


def _ss_reset_ctrl_bit_index(leaf: str, idx: int) -> int:
    """Packed bit index for ss_cold/ss_warm ovrd/val[idx]."""
    if not leaf.startswith("ss_"):
        raise AssertionError(f"Unknown ss reset leaf: {leaf}")
    return smc_reset_ctrl_packed_bit(leaf, idx)


def _sample_bit(signal, name: str) -> int:
    """Resolve a Logic signal to 0/1; fail closed on X/Z."""
    val = signal.value
    if not val.is_resolvable:
        raise AssertionError(f"X/Z sample on {name}: {val}")
    return int(val) & 1


_RESET_CTRL_BRANCH_LOGGED: set[tuple[str, str]] = set()


def _log_reset_ctrl_branch(leaf: str, idx: int | None, branch: str) -> None:
    """Log which access path served a jtag_smc_reset_ctrl read.

    The first read of each (leaf, branch) pair goes to INFO so the kept log
    shows whether a verdict rested on the hierarchical leaf or on the
    DV-owned packed layout; repeats go to DEBUG.
    """
    where = leaf if idx is None else f"{leaf}[{idx}]"
    msg = f"jtag_smc_reset_ctrl read {where} via {branch}"
    key = (leaf, branch)
    if key in _RESET_CTRL_BRANCH_LOGGED:
        cocotb.log.debug(msg)
        return
    _RESET_CTRL_BRANCH_LOGGED.add(key)
    cocotb.log.info(msg)


def read_smc_reset_ctrl_bit(dut, leaf: str, idx: int | None = None) -> int:
    """Read one jtag_smc_reset_ctrl ovrd/val leaf.

    For scalar fuse/warm/cool/cold leaves, pass ``leaf`` only.
    For ss_* vectors, pass ``leaf`` + ``idx`` (0..31).

    The hierarchical leaf is read first (``ctrl.<half>.<field>[idx]``, then
    the vector's own bit ``idx``); only when the simulator exposes neither is
    the whole struct read and the bit taken from the DV-owned packed layout.
    Every read logs the branch it took.
    """
    ctrl = smu_scope(dut).jtag_smc_reset_ctrl
    if idx is None and leaf not in _SMC_RESET_CTRL_SCALAR_LEAVES:
        raise AssertionError(f"Unknown jtag_smc_reset_ctrl leaf: {leaf}")
    field, half = _smc_reset_ctrl_split(leaf)
    bit = smc_reset_ctrl_packed_bit(leaf, idx)
    name = f"jtag_smc_reset_ctrl.{half}.{field}" + ("" if idx is None else f"[{idx}]")

    if hasattr(ctrl, half):
        group = getattr(ctrl, half)
        if hasattr(group, field):
            handle = getattr(group, field)
            if idx is None:
                _log_reset_ctrl_branch(leaf, idx, "hierarchical leaf")
                return _sample_bit(handle, name)
            try:
                elem = handle[idx]
            except Exception:  # noqa: BLE001
                elem = None
            if elem is not None:
                try:
                    value = _sample_bit(elem, name)
                except AssertionError:
                    raise
                except Exception:  # noqa: BLE001
                    value = None
                if value is not None:
                    _log_reset_ctrl_branch(leaf, idx, "hierarchical leaf element")
                    return value
            vec = handle.value
            if not vec.is_resolvable:
                raise AssertionError(f"X/Z sample on {name}: {vec}")
            _log_reset_ctrl_branch(leaf, idx, "hierarchical leaf vector bit")
            return (int(vec) >> idx) & 1

    packed = ctrl.value
    if not packed.is_resolvable:
        raise AssertionError(f"X/Z sample on jtag_smc_reset_ctrl (packed) for {name}: {packed}")
    _log_reset_ctrl_branch(leaf, idx, f"packed struct bit {bit} (DV table)")
    return (int(packed) >> bit) & 1


def require_jtag_tdo_resolved(where: str) -> None:
    """Fail closed if PTAP TDO is X/Z (VIP _logic_int would coerce that to 0)."""
    pin = getattr(cocotb.top, "jtag_tdo", None)
    if pin is None:
        raise AssertionError(f"jtag_tdo unobservable ({where})")
    val = pin.value
    if not val.is_resolvable:
        raise AssertionError(f"X/Z on jtag_tdo during {where}: {val}")


_WORD = 0xFFFF_FFFF


class Jtag2AxiScanPort:
    """A bench's own PTAP data-register scan, in the shape the transports below call.

    ``scan(opcode, value, width, label)`` shifts one PTAP data register from
    Run-Test/Idle back to Run-Test/Idle and returns its capture; it lets a
    bench whose scans also pass through a selected STAP issue JTAG2AXI
    accesses. ``jtag`` drives the Run-Test/Idle cycles between scans.
    """

    _WIDTHS = {
        reg: width
        for cfg in JTAG2AXI_TARGETS.values()
        for reg, width in ((cfg.dtmcs_reg, DTMCS_LEN), (cfg.dmi_reg, DMI_LEN))
    }

    def __init__(self, scan, jtag: OcahJtagMasterDriver) -> None:
        self._scan = scan
        self._jtag = jtag

    async def read(self, reg: str, *, shift_value: int = 0) -> int:
        return await self._scan(int(DtpJtagInstr[reg]), shift_value, self._WIDTHS[reg], reg)

    async def step_tms(self, tms: int) -> int:
        return await self._jtag.step_tms(tms)


async def _dmi_scan(
    jtag: OcahJtagMasterDriver,
    cfg: DtpJtag2AxiTargetCfg,
    address: int,
    data: int,
    op: DtpDmiOp,
    where: str,
) -> int:
    """One DMI scan of ``{address, data, op}``; returns the captured data field.

    The capture carries the status of the previous DMI operation, which stays
    sticky until a DTMCS dmireset once the bridge refuses an operation, so any
    status but success fails. A read or write operation needs
    DTP_DMI_SETTLE_TCK TCK cycles before the next capture to cross into the
    bridge clock domain and back.
    """
    captured = await jtag.read(cfg.dmi_reg, shift_value=pack_dmi(address, data, op))
    require_jtag_tdo_resolved(f"{cfg.dmi_reg} {where}")
    _, captured_data, status = unpack_dmi(captured)
    if status != DtpDmiStatus.SUCCESS:
        raise AssertionError(
            f"{cfg.dmi_reg} {where}: captured DMI status {status}; the bridge refused "
            "the previous DMI operation or had not finished it"
        )
    if op != DtpDmiOp.NOP:
        for _ in range(DTP_DMI_SETTLE_TCK):
            await jtag.step_tms(0)
    return captured_data


async def _dmi_write(
    jtag: OcahJtagMasterDriver, cfg: DtpJtag2AxiTargetCfg, address: DtpDmReg, data: int
) -> None:
    await _dmi_scan(jtag, cfg, address, data, DtpDmiOp.WRITE, f"write {address.name}")


async def _dmi_read(
    jtag: OcahJtagMasterDriver, cfg: DtpJtag2AxiTargetCfg, address: DtpDmReg
) -> int:
    """Read one Debug Module register: the read, then a NOP scan that captures its data."""
    await _dmi_scan(jtag, cfg, address, 0, DtpDmiOp.READ, f"read {address.name}")
    return await _dmi_scan(jtag, cfg, 0, 0, DtpDmiOp.NOP, f"fetch {address.name}")


@dataclass(frozen=True)
class Jtag2AxiAccess:
    """One System Bus Access that ``jtag2axi_start`` launched."""

    target: DtpJtag2AxiTargetCfg
    addr: int
    size: int
    read: bool

    @property
    def lane(self) -> int:
        """Byte offset of the access within the bridge's data beat."""
        return self.addr % self.target.beat_bytes

    @property
    def mask(self) -> int:
        return (1 << (8 << self.size)) - 1


async def _sba_program(
    jtag: OcahJtagMasterDriver, access: Jtag2AxiAccess, data: int
) -> tuple[DtpDmReg, int]:
    """Program the Debug Module for ``access``; returns the register write that starts it.

    A system reset clears dmactive, so every access sets it. The sbcs write
    clears sberror and sbbusyerror. With sbreadonaddr the sbaddress0 write
    starts a read; otherwise the sbdata0 write starts a write of ``data``.
    """
    cfg = access.target
    await _dmi_write(jtag, cfg, DtpDmReg.DMCONTROL, 0x1)
    sbcs = pack_sbcs(
        sbbusyerror=1, sberror=0x7, sbreadonaddr=int(access.read), sbaccess=access.size
    )
    await _dmi_write(jtag, cfg, DtpDmReg.SBCS, sbcs)
    if cfg.addr_width > 32:
        await _dmi_write(jtag, cfg, DtpDmReg.SBADDRESS1, access.addr >> 32)
    if not access.read and access.size > 2:
        await _dmi_write(jtag, cfg, DtpDmReg.SBDATA1, data >> 32)
    if access.read:
        return DtpDmReg.SBADDRESS0, access.addr & _WORD
    await _dmi_write(jtag, cfg, DtpDmReg.SBADDRESS0, access.addr & _WORD)
    return DtpDmReg.SBDATA0, data & _WORD


# Direction of a jtag2axi_start access.
J2A_OP_READ = 1
J2A_OP_WRITE = 2


async def jtag2axi_arm(
    jtag: OcahJtagMasterDriver,
    op: int,
    addr: int,
    data: int = 0,
    *,
    target: str = "smc_axi",
    wstrb: int | None = None,
    size: int | None = None,
) -> tuple[Jtag2AxiAccess, int]:
    """Program a ``jtag2axi_start`` access up to the DMI scan that starts it.

    Returns the access and that scan's DMI value, for a bench that times the
    starting Update-DR itself. The scan needs DTP_DMI_SETTLE_TCK TCK cycles
    before the next DMI capture.

    ``target`` is a ``JTAG2AXI_TARGETS`` key and ``size`` defaults to its full
    beat. A write's ``data`` sits at the access's byte lanes of the beat, as
    on the AXI W channel. System Bus Access writes whole naturally aligned
    words, so a write's ``wstrb``, when given, must be the full strobe of
    those lanes.
    """
    cfg = JTAG2AXI_TARGETS[target]
    size = cfg.data_size if size is None else size
    if op not in (J2A_OP_READ, J2A_OP_WRITE):
        raise ValueError(f"JTAG2AXI op {op} is neither J2A_OP_READ nor J2A_OP_WRITE")
    access = Jtag2AxiAccess(cfg, addr, size, op == J2A_OP_READ)
    nbytes = 1 << size
    if nbytes > cfg.beat_bytes or addr % nbytes:
        raise ValueError(
            f"{cfg.name}: System Bus Access issues naturally aligned accesses of at most "
            f"{cfg.beat_bytes} bytes, not {nbytes} bytes at 0x{addr:x}"
        )
    strobe = ((1 << nbytes) - 1) << access.lane
    if not access.read and wstrb is not None and wstrb != strobe:
        raise ValueError(
            f"{cfg.name}: a {nbytes}-byte write at 0x{addr:x} carries wstrb 0x{strobe:x}; "
            f"System Bus Access cannot issue wstrb 0x{wstrb:x}"
        )
    reg, value = await _sba_program(jtag, access, (data >> (8 * access.lane)) & access.mask)
    return access, pack_dmi(reg, value, DtpDmiOp.WRITE)


async def jtag2axi_start(
    jtag: OcahJtagMasterDriver,
    op: int,
    addr: int,
    data: int = 0,
    *,
    target: str = "smc_axi",
    wstrb: int | None = None,
    size: int | None = None,
) -> Jtag2AxiAccess:
    """Start a ``size`` access of ``addr`` through ``target``'s bridge (``jtag2axi_arm``)."""
    access, trigger = await jtag2axi_arm(
        jtag, op, addr, data, target=target, wstrb=wstrb, size=size
    )
    reg, value, _ = unpack_dmi(trigger)
    await _dmi_write(jtag, access.target, DtpDmReg(reg), value)
    return access


async def jtag2axi_status(jtag: OcahJtagMasterDriver, access: Jtag2AxiAccess) -> tuple[int, int]:
    """Sample ``access`` once.

    Returns ``(J2A_STATUS_BUSY, 0)`` while it is outstanding; otherwise its
    status and, for a read, the data at its byte lanes of the beat.
    """
    cfg = access.target
    sbcs = unpack_sbcs(await _dmi_read(jtag, cfg, DtpDmReg.SBCS))
    if sbcs["sbbusy"]:
        return J2A_STATUS_BUSY, 0
    if sbcs["sbbusyerror"] or sbcs["sberror"] not in (0, 2):
        raise AssertionError(
            f"{cfg.name} access at 0x{access.addr:x}: sbcs sberror={sbcs['sberror']} "
            f"sbbusyerror={sbcs['sbbusyerror']}, a request the bridge refused"
        )
    status = J2A_STATUS_DECERR if sbcs["sberror"] else J2A_STATUS_SUCCESS
    if not access.read:
        return status, 0
    rdata = await _dmi_read(jtag, cfg, DtpDmReg.SBDATA0)
    if access.size > 2:
        rdata |= (await _dmi_read(jtag, cfg, DtpDmReg.SBDATA1)) << 32
    return status, (rdata & access.mask) << (8 * access.lane)


async def jtag2axi_poll(
    jtag: OcahJtagMasterDriver, access: Jtag2AxiAccess, *, poll_limit: int
) -> tuple[int, int, int]:
    """Sample ``access`` until it completes, at most ``poll_limit`` times.

    Returns the last sample's status and read data, and the samples taken.
    """
    status, rdata, polls = J2A_STATUS_BUSY, 0, 0
    while status == J2A_STATUS_BUSY and polls < poll_limit:
        status, rdata = await jtag2axi_status(jtag, access)
        polls += 1
    return status, rdata, polls


async def jtag2axi_wait(
    jtag: OcahJtagMasterDriver,
    access: Jtag2AxiAccess,
    *,
    poll_limit: int,
    require_complete: bool = False,
) -> tuple[int, int]:
    """``jtag2axi_poll`` without the sample count; with ``require_complete`` an
    access outstanding after the last poll raises TimeoutError."""
    status, rdata, _ = await jtag2axi_poll(jtag, access, poll_limit=poll_limit)
    if require_complete and status == J2A_STATUS_BUSY:
        raise TimeoutError(
            f"{access.target.name} access at 0x{access.addr:x} outstanding after {poll_limit} polls"
        )
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
    """Write through the SMC fabric bridge; returns ``(status, 0)``."""
    access = await jtag2axi_start(jtag, J2A_OP_WRITE, addr, data, wstrb=wstrb, size=size)
    return await jtag2axi_wait(
        jtag, access, poll_limit=poll_limit, require_complete=require_complete
    )


async def jtag2axi_single_read(
    jtag: OcahJtagMasterDriver,
    addr: int,
    *,
    size: int = SMC_DBG_AXSIZE_8B,
    poll_limit: int = 128,
    require_complete: bool = False,
) -> tuple[int, int]:
    """Read through the SMC fabric bridge; returns ``(status, beat)``."""
    access = await jtag2axi_start(jtag, J2A_OP_READ, addr, size=size)
    return await jtag2axi_wait(
        jtag, access, poll_limit=poll_limit, require_complete=require_complete
    )


async def otp_jtag2axi_single_read(
    jtag: OcahJtagMasterDriver,
    addr: int,
    *,
    size: int = SMC_OTP_AXSIZE_4B,
    poll_limit: int = 64,
    require_complete: bool = False,
) -> tuple[int, int]:
    """Read through the SMC OTP bridge; returns ``(status, rdata)``."""
    access = await jtag2axi_start(jtag, J2A_OP_READ, addr, target="smc_otp", size=size)
    return await jtag2axi_wait(
        jtag, access, poll_limit=poll_limit, require_complete=require_complete
    )


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
    """Write through the SMC OTP bridge; returns ``(status, 0)``."""
    access = await jtag2axi_start(
        jtag, J2A_OP_WRITE, addr, data, target="smc_otp", wstrb=wstrb, size=size
    )
    return await jtag2axi_wait(
        jtag, access, poll_limit=poll_limit, require_complete=require_complete
    )


async def sep_otp_jtag2axi_single_read(
    jtag: OcahJtagMasterDriver,
    addr: int,
    *,
    size: int = SMC_OTP_AXSIZE_4B,
    poll_limit: int = 32,
) -> tuple[int, int]:
    """Read through the SEP OTP bridge; returns ``(status, rdata)``."""
    access = await jtag2axi_start(jtag, J2A_OP_READ, addr, target="sep_otp", size=size)
    return await jtag2axi_wait(jtag, access, poll_limit=poll_limit)


async def sep_otp_jtag2axi_single_write(
    jtag: OcahJtagMasterDriver,
    addr: int,
    data: int,
    *,
    poll_limit: int = 32,
) -> tuple[int, int]:
    """Write a word through the SEP OTP bridge; returns ``(status, 0)``."""
    access = await jtag2axi_start(jtag, J2A_OP_WRITE, addr, data, target="sep_otp")
    return await jtag2axi_wait(jtag, access, poll_limit=poll_limit)


# PeakRDL wdt.h has no KEY-magic #define. Literal is the SPEC table in
# hw/sys/smc/regs/gen/adoc/blocks/wdt.adoc KEY: "Magic key (0x51F15E)".
# Same paragraph: a KEY read returns 1 if unlocked, 0 otherwise.
WDT_KEY_MAGIC = 0x51F15E
WDT_KEY_UNLOCKED_RD = 1


def axi64_pack32(addr: int, word32: int) -> tuple[int, int]:
    """WSTRB and beat data for a 32b CSR on a 64b J2A lane (from addr[2])."""
    word32 &= 0xFFFF_FFFF
    if addr & 0x4:
        return 0xF0, word32 << 32
    return 0x0F, word32


def axi64_unpack32(addr: int, beat: int) -> int:
    """Extract a 32b CSR from a 64b J2A beat (from addr[2])."""
    beat = int(beat)
    if addr & 0x4:
        return (beat >> 32) & 0xFFFF_FFFF
    return beat & 0xFFFF_FFFF


async def wdt_unlock(jtag: OcahJtagMasterDriver, magic: int = WDT_KEY_MAGIC) -> int:
    """Write CORE0 WDT KEY once; lane packing follows the map address."""
    from seq_lib.smu_addr_map import smc_addr

    key_addr = smc_addr("SMC_TOP_SMC_CLUSTER_CORE0_WDT_KEY_BASE_ADDR")
    wstrb, data = axi64_pack32(key_addr, magic)
    st, _ = await jtag2axi_single_write(
        jtag,
        key_addr,
        data,
        wstrb=wstrb,
        size=SMC_DBG_AXSIZE_4B,
        require_complete=True,
    )
    require_jtag_tdo_resolved("WDT_KEY unlock")
    return st


async def wdt_key_read(jtag: OcahJtagMasterDriver) -> tuple[int, int]:
    """Read KEY from the 64b FEED/KEY lane (KEY sits at +0x4 of that beat)."""
    from seq_lib.smu_addr_map import smc_addr

    key_addr = smc_addr("SMC_TOP_SMC_CLUSTER_CORE0_WDT_KEY_BASE_ADDR")
    lane = key_addr & ~0x7
    st, rdata = await jtag2axi_single_read(
        jtag,
        lane,
        size=SMC_DBG_AXSIZE_8B,
        require_complete=True,
    )
    require_jtag_tdo_resolved("WDT_KEY read")
    return st, axi64_unpack32(key_addr, rdata)


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
