# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""
I3C Test API - Minimal modular Python API for I3CCore I3C tests

This module provides reusable classes for initializing and operating I3C
controller and target devices using cocotb and AXI-Lite.

Usage:
    from env.i3c_api import I3CHelper, I3CController, I3CTarget

    helper = I3CHelper(axi_master, dut)
    ctrl = I3CController(0x0000, helper)
    tgt = I3CTarget(0x1000, helper)

    await ctrl.initialize()
    await ctrl.configure_timing_od_i3c()
    await tgt.initialize(0x10)
    ok, resp = await ctrl.send_setdasa(0x10, 0x10)
"""

import logging
import os
import sys

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from cocotbext.axi import AxiResp

# CCC Command Codes (Direct GET commands)
CCC_GETBCR = 0x8E  # Get Bus Characteristics Register
CCC_GETMWL = 0x8B  # Get Max Write Length
CCC_GETMRL = 0x8C  # Get Max Read Length

# CCC Command Codes (Direct SET commands)
CCC_SETMWL = 0x89  # Set Max Write Length
CCC_SETMRL = 0x8A  # Set Max Read Length
CCC_RSTACT = 0x9A  # Direct Reset Action

# CCC Command Codes (Broadcast — bit7=0; see MIPI I3C Basic Table 16)
CCC_ENEC_BCAST = 0x00  # Broadcast Enable Target Events
CCC_DISEC_BCAST = 0x01  # Broadcast Disable Target Events
CCC_RSTDAA = 0x06  # Broadcast Reset Dynamic Address Assignment

# Generated register model (make regen-regs TARGET=oca_i3c_wrap)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../regs/gen/py"))

import oca_i3c_wrap_reg as _csr

# Generated ctypes union names encode FIFO/table sizes that change across RDL
# regens, so resolve them by reg-name suffix (see _union_by_suffix) rather than
# pinning the full identifier; addresses are imported by name.

# Register addresses (each `<NAME>_REG_ADDR` symbol from the header).
I3CBASE_HC_CONTROL_REG_ADDR = _csr.I3C_CSR_0__I3CBASE_HC_CONTROL_REG_ADDR
PIOCONTROL_COMMAND_PORT_REG_ADDR = _csr.I3C_CSR_0__PIOCONTROL_COMMAND_PORT_REG_ADDR
PIOCONTROL_RESPONSE_PORT_REG_ADDR = _csr.I3C_CSR_0__PIOCONTROL_RESPONSE_PORT_REG_ADDR
PIOCONTROL_TX_DATA_PORT_REG_ADDR = _csr.I3C_CSR_0__PIOCONTROL_TX_DATA_PORT_REG_ADDR
PIOCONTROL_RX_DATA_PORT_REG_ADDR = _csr.I3C_CSR_0__PIOCONTROL_RX_DATA_PORT_REG_ADDR
PIOCONTROL_DATA_BUFFER_THLD_CTRL_REG_ADDR = (
    _csr.I3C_CSR_0__PIOCONTROL_DATA_BUFFER_THLD_CTRL_REG_ADDR
)
PIOCONTROL_QUEUE_THLD_CTRL_REG_ADDR = _csr.I3C_CSR_0__PIOCONTROL_QUEUE_THLD_CTRL_REG_ADDR
PIOCONTROL_QUEUE_SIZE_REG_ADDR = _csr.I3C_CSR_0__PIOCONTROL_QUEUE_SIZE_REG_ADDR
PIOCONTROL_PIO_INTR_STATUS_REG_ADDR = _csr.I3C_CSR_0__PIOCONTROL_PIO_INTR_STATUS_REG_ADDR
PIOCONTROL_PIO_INTR_STATUS_ENABLE_REG_ADDR = (
    _csr.I3C_CSR_0__PIOCONTROL_PIO_INTR_STATUS_ENABLE_REG_ADDR
)
PIOCONTROL_PIO_INTR_SIGNAL_ENABLE_REG_ADDR = (
    _csr.I3C_CSR_0__PIOCONTROL_PIO_INTR_SIGNAL_ENABLE_REG_ADDR
)
PIOCONTROL_PIO_INTR_FORCE_REG_ADDR = _csr.I3C_CSR_0__PIOCONTROL_PIO_INTR_FORCE_REG_ADDR
PIOCONTROL_PIO_CONTROL_REG_ADDR = _csr.I3C_CSR_0__PIOCONTROL_PIO_CONTROL_REG_ADDR
I3C_EC_STDBYCTRLMODE_STBY_CR_CONTROL_REG_ADDR = (
    _csr.I3C_CSR_0__I3C_EC_STDBYCTRLMODE_STBY_CR_CONTROL_REG_ADDR
)
I3C_EC_STDBYCTRLMODE_STBY_CR_DEVICE_ADDR_REG_ADDR = (
    _csr.I3C_CSR_0__I3C_EC_STDBYCTRLMODE_STBY_CR_DEVICE_ADDR_REG_ADDR
)
I3C_EC_TTI_INTERRUPT_STATUS_REG_ADDR = _csr.I3C_CSR_0__I3C_EC_TTI_INTERRUPT_STATUS_REG_ADDR
I3C_EC_TTI_INTERRUPT_ENABLE_REG_ADDR = _csr.I3C_CSR_0__I3C_EC_TTI_INTERRUPT_ENABLE_REG_ADDR
I3C_EC_TTI_RX_DATA_PORT_REG_ADDR = _csr.I3C_CSR_0__I3C_EC_TTI_RX_DATA_PORT_REG_ADDR
I3C_EC_TTI_TX_DATA_PORT_REG_ADDR = _csr.I3C_CSR_0__I3C_EC_TTI_TX_DATA_PORT_REG_ADDR
I3C_EC_TTI_RX_DESC_QUEUE_PORT_REG_ADDR = _csr.I3C_CSR_0__I3C_EC_TTI_RX_DESC_QUEUE_PORT_REG_ADDR
I3C_EC_TTI_TX_DESC_QUEUE_PORT_REG_ADDR = _csr.I3C_CSR_0__I3C_EC_TTI_TX_DESC_QUEUE_PORT_REG_ADDR
I3C_EC_TTI_DATA_BUFFER_THLD_CTRL_REG_ADDR = (
    _csr.I3C_CSR_0__I3C_EC_TTI_DATA_BUFFER_THLD_CTRL_REG_ADDR
)
I3C_EC_TTI_QUEUE_THLD_CTRL_REG_ADDR = _csr.I3C_CSR_0__I3C_EC_TTI_QUEUE_THLD_CTRL_REG_ADDR
I3C_EC_TTI_QUEUE_STATUS_REG_ADDR = _csr.I3C_CSR_0__I3C_EC_TTI_QUEUE_STATUS_REG_ADDR
I3C_EC_SOCMGMTIF_T_R_REG_REG_ADDR = _csr.I3C_CSR_0__I3C_EC_SOCMGMTIF_T_R_REG_REG_ADDR
I3C_EC_SOCMGMTIF_T_F_REG_REG_ADDR = _csr.I3C_CSR_0__I3C_EC_SOCMGMTIF_T_F_REG_REG_ADDR
I3C_EC_SOCMGMTIF_T_SU_DAT_REG_REG_ADDR = _csr.I3C_CSR_0__I3C_EC_SOCMGMTIF_T_SU_DAT_REG_REG_ADDR
I3C_EC_SOCMGMTIF_T_HD_DAT_REG_REG_ADDR = _csr.I3C_CSR_0__I3C_EC_SOCMGMTIF_T_HD_DAT_REG_REG_ADDR
I3C_EC_SOCMGMTIF_T_HIGH_REG_REG_ADDR = _csr.I3C_CSR_0__I3C_EC_SOCMGMTIF_T_HIGH_REG_REG_ADDR
I3C_EC_SOCMGMTIF_T_HIGH_OD_REG_REG_ADDR = _csr.I3C_CSR_0__I3C_EC_SOCMGMTIF_T_HIGH_OD_REG_REG_ADDR
I3C_EC_SOCMGMTIF_T_HIGH_INIT_OD_REG_REG_ADDR = (
    _csr.I3C_CSR_0__I3C_EC_SOCMGMTIF_T_HIGH_INIT_OD_REG_REG_ADDR
)
I3C_EC_SOCMGMTIF_T_LOW_REG_REG_ADDR = _csr.I3C_CSR_0__I3C_EC_SOCMGMTIF_T_LOW_REG_REG_ADDR
I3C_EC_SOCMGMTIF_T_LOW_OD_REG_REG_ADDR = _csr.I3C_CSR_0__I3C_EC_SOCMGMTIF_T_LOW_OD_REG_REG_ADDR
I3C_EC_SOCMGMTIF_T_HD_STA_REG_REG_ADDR = _csr.I3C_CSR_0__I3C_EC_SOCMGMTIF_T_HD_STA_REG_REG_ADDR
I3C_EC_SOCMGMTIF_T_HD_RSTA_REG_REG_ADDR = _csr.I3C_CSR_0__I3C_EC_SOCMGMTIF_T_HD_RSTA_REG_REG_ADDR
I3C_EC_SOCMGMTIF_T_SU_STA_REG_REG_ADDR = _csr.I3C_CSR_0__I3C_EC_SOCMGMTIF_T_SU_STA_REG_REG_ADDR
I3C_EC_SOCMGMTIF_T_SU_STO_REG_REG_ADDR = _csr.I3C_CSR_0__I3C_EC_SOCMGMTIF_T_SU_STO_REG_REG_ADDR
I3C_EC_SOCMGMTIF_T_DS_OD_REG_REG_ADDR = _csr.I3C_CSR_0__I3C_EC_SOCMGMTIF_T_DS_OD_REG_REG_ADDR
I3C_EC_SOCMGMTIF_T_FREE_REG_REG_ADDR = _csr.I3C_CSR_0__I3C_EC_SOCMGMTIF_T_FREE_REG_REG_ADDR
I3C_EC_SOCMGMTIF_T_AVAL_REG_REG_ADDR = _csr.I3C_CSR_0__I3C_EC_SOCMGMTIF_T_AVAL_REG_REG_ADDR
I3C_EC_SOCMGMTIF_T_IDLE_REG_REG_ADDR = _csr.I3C_CSR_0__I3C_EC_SOCMGMTIF_T_IDLE_REG_REG_ADDR
PIOCONTROL_IBI_PORT_REG_ADDR = _csr.I3C_CSR_0__PIOCONTROL_IBI_PORT_REG_ADDR
I3C_EC_TTI_CONTROL_REG_ADDR = _csr.I3C_CSR_0__I3C_EC_TTI_CONTROL_REG_ADDR
I3C_EC_TTI_STATUS_REG_ADDR = _csr.I3C_CSR_0__I3C_EC_TTI_STATUS_REG_ADDR
I3C_EC_TTI_IBI_PORT_REG_ADDR = _csr.I3C_CSR_0__I3C_EC_TTI_IBI_PORT_REG_ADDR
DAT_MEM_BASE_ADDR = _csr.I3C_CSR_0__DAT_MEM_BASE_ADDR


def _union_by_suffix(suffix, prefix="", exclude=None):
    """Resolve a ctypes union by its `_<REG>_reg_u` suffix (only prefix+suffix are
    stable across regens). `prefix` disambiguates regs that exist in >1 reg file;
    `exclude` drops a longer name that also ends with the same suffix (CONTROL vs
    RESET_CONTROL)."""
    matches = [
        getattr(_csr, n)
        for n in dir(_csr)
        if n.startswith(prefix)
        and n.endswith(suffix + "_reg_u")
        and (exclude is None or exclude not in n)
    ]
    if not matches:
        raise ImportError(f"No ctypes union '{prefix}*{suffix}_reg_u' in oca_i3c_wrap_reg")
    if len(matches) > 1:
        raise ImportError(
            f"Ambiguous ctypes union '{prefix}*{suffix}_reg_u': {len(matches)} matches"
        )
    return matches[0]


# Short aliases for ctypes Union classes (resolved by reg-file prefix + reg-name suffix).
_PIO = "PIOREGS_"
_TTI = "TARGETTRANSACTIONINTERFACEREGISTERS_"


def _union_by_contains(needle, exclude=None):
    """Resolve a ctypes union whose name contains `needle` (for regs like
    PIO_INTR_STATUS whose generated name has no stable suffix)."""
    matches = [
        getattr(_csr, n)
        for n in dir(_csr)
        if n.endswith("_reg_u") and needle in n and (exclude is None or exclude not in n)
    ]
    if len(matches) != 1:
        raise ImportError(f"Expected 1 ctypes union containing '{needle}', got {len(matches)}")
    return matches[0]


HcControl = _union_by_suffix("HC_CONTROL")
PioControl = _union_by_suffix("PIO_CONTROL")
PioIntrStatus = _union_by_contains("_PIO_INTR_STATUS_CMD_QUEUE_READY_STAT", exclude="_ENABLE")
PioIntrStatusEnable = _union_by_suffix("PIO_INTR_STATUS_ENABLE")
PioIntrSignalEnable = _union_by_suffix("PIO_INTR_SIGNAL_ENABLE")
PioIntrForce = _union_by_suffix("PIO_INTR_FORCE")
DataBufferThldCtrl = _union_by_suffix("DATA_BUFFER_THLD_CTRL", _PIO)
QueueThldCtrl = _union_by_suffix("QUEUE_THLD_CTRL", _PIO)
StbyCrControl = _union_by_suffix("STBY_CR_CONTROL")
StbyCrDeviceAddr = _union_by_suffix("STBY_CR_DEVICE_ADDR")
TtiDataBufferThldCtrl = _union_by_suffix("DATA_BUFFER_THLD_CTRL", _TTI)
TtiQueueThldCtrl = _union_by_suffix("QUEUE_THLD_CTRL", _TTI)
TtiQueueStatus = _union_by_suffix("QUEUE_STATUS", _TTI)
TtiIntrStatus = _union_by_suffix("INTERRUPT_STATUS", _TTI)
TtiControl = _union_by_suffix("CONTROL", _TTI, exclude="RESET_CONTROL")
TtiTargetErrCtrl = _union_by_suffix("TARGET_ERR_CTRL", _TTI)


def _bit(union, field):
    """Return the bit offset of `field` in a generated register union.

    The generated map is authoritative; deriving offsets makes renamed or moved
    fields fail loudly instead of silently masking the wrong bit.
    """
    struct = dict((f[0], f[1]) for f in union._fields_)["f"]
    offset = 0
    for entry in struct._fields_:
        name, width = entry[0], (entry[2] if len(entry) > 2 else None)
        if name == field:
            return offset
        if width is None:
            raise TypeError(f"{union.__name__}.{name} is not a bit-field")
        offset += width
    raise AttributeError(f"{union.__name__}: no bit-field {field!r} in the generated register map")


# TTI Interrupt Status bit positions, resolved from the generated union above.
TTI_INTR_TX_DATA_THLD_BIT = _bit(TtiIntrStatus, "tx_data_thld_stat")
TTI_INTR_RX_DATA_THLD_BIT = _bit(TtiIntrStatus, "rx_data_thld_stat")
TTI_INTR_TX_DESC_THLD_BIT = _bit(TtiIntrStatus, "tx_desc_thld_stat")
TTI_INTR_RX_DESC_THLD_BIT = _bit(TtiIntrStatus, "rx_desc_thld_stat")
TTI_INTR_IBI_THLD_BIT = _bit(TtiIntrStatus, "ibi_thld_stat")
TTI_INTR_IBI_DONE_BIT = _bit(TtiIntrStatus, "ibi_done")
TTI_INTR_TX_DESC_COMPLETE_BIT = _bit(TtiIntrStatus, "tx_desc_complete")

# TTI Control register bit positions.
TTI_CTRL_IBI_EN_BIT = _bit(TtiControl, "ibi_en")

# Target error-detection enables (TTI.TARGET_ERR_CTRL). These gate the target's
# protocol-error checks at the detection source, e.g. te2_err_det_en_i in
# i3c_target_fsm.sv, so a test that expects an error must enable its class first.
TTI_ERR_CTRL_TE2_DET_EN_BIT = _bit(TtiTargetErrCtrl, "te2_err_det_en")


def build_immediate_write_cmd(data_bytes, dat_idx=0, tid=0):
    """Build an immediate-write command descriptor (64-bit) -> (cmd_lo, cmd_hi).

    Immediate transfers carry 1-4 data bytes inside the descriptor itself, but still
    put real data bytes + T-bits on the bus, so they are the cheapest way to drive a
    data phase without any TX FIFO management.

    Descriptor format (i3c_pkg.sv immediate_data_trans_direct_desc_t):
      DWORD 0: [31] toc, [30] wroc, [29] rnw, [28:26] mode, [25:23] dtt,
               [20:16] dev_idx, [15] cp, [14:7] cmd, [6:3] tid, [2:0] attr
      DWORD 1: data bytes, little-endian ([7:0] = byte 0)

    """
    dtt = len(data_bytes)
    attr = 0x1  # ImmediateDataTransfer

    cmd_lo = (
        (attr << 0)  # [2:0] attr = 1 (ImmediateDataTransfer)
        | (tid << 3)  # [6:3] tid
        | (0 << 7)  # [14:7] cmd (unused for private)
        | (0 << 15)  # [15] cp = 0 (no command)
        | (dat_idx << 16)  # [20:16] dev_idx
        | (dtt << 23)  # [25:23] dtt (number of valid bytes)
        | (0 << 26)  # [28:26] mode = SDR0
        | (0 << 29)  # [29] rnw = 0 (write)
        | (1 << 30)  # [30] wroc = 1 (response on completion)
        | (1 << 31)  # [31] toc = 1 (terminate on completion)
    )

    cmd_hi = 0
    for i, byte in enumerate(data_bytes[:4]):
        cmd_hi |= (byte & 0xFF) << (i * 8)

    return cmd_lo, cmd_hi


class I3CHelper:
    """Low-level register I/O wrapper for I3C registers via AXI-Lite."""

    def __init__(self, axi_master, dut, log=None):
        self.axi = axi_master
        self.dut = dut
        self.log = log or logging.getLogger("i3c_api")
        # Verilator + cocotbext-axi can miss a 1-cycle B/R: the DUT retires
        # the beat while the Python sink still samples the pre-NBA value.
        # Touching the handshake handles each posedge forces a VPI refresh.
        cocotb.start_soon(self._verilator_axi_keepalive())

    async def _verilator_axi_keepalive(self):
        names = (
            "axi_awvalid",
            "axi_awready",
            "axi_wvalid",
            "axi_wready",
            "axi_bvalid",
            "axi_bready",
            "axi_arvalid",
            "axi_arready",
            "axi_rvalid",
            "axi_rready",
        )
        while True:
            await RisingEdge(self.dut.clk)
            for name in names:
                sig = getattr(self.dut, name, None)
                if sig is not None:
                    _ = sig.value

    async def write(self, addr, data, *, expect_resp=AxiResp.OKAY):
        """Write 32-bit value and require the AXI BRESP to match expect_resp.

        Uses the response-returning master API (not write_dword), so SLVERR /
        DECERR cannot silently pass. Pass expect_resp=AxiResp.SLVERR (etc.) for
        intentional negative-protocol checks.
        """
        wresp = await self.axi.write(addr, int(data).to_bytes(4, "little"))
        if wresp.resp != expect_resp:
            raise AssertionError(
                f"AXI write BRESP @0x{addr:X}: got {wresp.resp.name}, expected {expect_resp.name}"
            )

    async def read(self, addr, *, expect_resp=AxiResp.OKAY):
        """Read 32-bit value and require the AXI RRESP to match expect_resp.

        Uses the response-returning master API (not read_dword), so SLVERR /
        DECERR cannot silently pass.
        """
        rresp = await self.axi.read(addr, 4)
        if rresp.resp != expect_resp:
            raise AssertionError(
                f"AXI read RRESP @0x{addr:X}: got {rresp.resp.name}, expected {expect_resp.name}"
            )
        return int.from_bytes(rresp.data, "little")

    async def read_into(self, addr, reg_class):
        """Read register and return as ctypes Union instance for field access."""
        val = await self.read(addr)
        reg = reg_class()
        reg.val = val
        return reg

    async def write_verify(self, addr, data, mask=0xFFFFFFFF):
        """Write register and verify readback matches (with optional mask)."""
        await self.write(addr, data)
        await ClockCycles(self.dut.clk, 2)
        rb = await self.read(addr)
        if (rb & mask) != (data & mask):
            self.log.error(f"Verify fail @0x{addr:X}: wrote 0x{data:X}, read 0x{rb:X}")
        return rb

    async def poll_field(self, addr, reg_class, field_name, max_polls=10000, interval=10):
        """Poll until a specific field in a ctypes register is non-zero."""
        for _ in range(max_polls):
            reg = await self.read_into(addr, reg_class)
            if getattr(reg.f, field_name):
                return True, reg
            await ClockCycles(self.dut.clk, interval)
        return False, None

    async def poll_field_clear(self, addr, reg_class, field_name, max_polls=10000, interval=10):
        """Poll until a specific field in a ctypes register is zero."""
        for _ in range(max_polls):
            reg = await self.read_into(addr, reg_class)
            if not getattr(reg.f, field_name):
                return True, reg
            await ClockCycles(self.dut.clk, interval)
        return False, None

    @staticmethod
    def pack_bytes(byte_list):
        """Pack up to 4 bytes into 32-bit word (little-endian)."""
        word = 0
        for i, b in enumerate(byte_list[:4]):
            word |= (b & 0xFF) << (i * 8)
        return word

    @staticmethod
    def unpack_bytes(word, count=4):
        """Unpack 32-bit word into bytes (little-endian)."""
        return [(word >> (i * 8)) & 0xFF for i in range(count)]


class I3CController:
    """I3C Controller initialization and transfer functions."""

    def __init__(self, base_addr, helper):
        self.base = base_addr
        self.h = helper
        self.tx_thld = 1  # Default: 2^(1+1) = 4 bytes
        self.rx_thld = 1
        self.bcr_cache = {}  # Store BCR per dat_idx for setmrl

    async def set_iba_include(self, enable=True):
        """Set HC_CONTROL.IBA_INCLUDE and return the read-back bit.

        Controls whether the I3C Broadcast Address (7'h7E) precedes private transfers.
        Per HCI v1.2 section 7.4.2 this bit resets to 0, and "if the I3C Broadcast
        Address is not included for private transfers, then IBIs driven from Target
        Devices might not win the Arbitration".

        Only an Address Header that follows a START is arbitrable (I3C Basic, rules
        991-1006), and 7'h7E = 7'b1111110 is deliberately near-maximal, so under
        open-drain arbitration any Target's own address beats it at the first differing
        bit. Setting this bit is therefore what makes an IBI's preemption of a private
        transfer deterministic instead of a race.

        Call AFTER initialize(), which rewrites HC_CONTROL wholesale.

        Returns:
            int: HC_CONTROL.iba_include as read back.
        """
        reg = HcControl()
        reg.val = await self.h.read(self.base + I3CBASE_HC_CONTROL_REG_ADDR)
        reg.f.iba_include = 1 if enable else 0
        await self.h.write(self.base + I3CBASE_HC_CONTROL_REG_ADDR, reg.val)

        back = HcControl()
        back.val = await self.h.read(self.base + I3CBASE_HC_CONTROL_REG_ADDR)
        self.h.log.info(f"HC_CONTROL = 0x{back.val:08X} (iba_include={back.f.iba_include})")
        return back.f.iba_include

    async def initialize(self):
        """Full controller init: HC_CONTROL, PIO enable, interrupts, RS=1."""
        # 1. Read queue sizes (optional, for info)
        qsize = await self.h.read(self.base + PIOCONTROL_QUEUE_SIZE_REG_ADDR)
        self.h.log.info(f"Queue sizes: 0x{qsize:08X}")

        # 2. Enable PIO mode + bus using ctypes
        hc_ctrl = HcControl()
        hc_ctrl.f.bus_enable = 1
        hc_ctrl.f.mode_selector = 1  # PIO mode
        await self.h.write(self.base + I3CBASE_HC_CONTROL_REG_ADDR, hc_ctrl.val)

        # Active Controller Mode: Table-5 encoding (3); legacy 0b01 won't activate,
        # so queued CCCs never execute. TARGET_XACT_ENABLE also required.
        stby_cr = StbyCrControl()
        stby_cr.f.stby_cr_enable_init = 3  # MODE_CONTROLLER (Active Controller)
        stby_cr.f.target_xact_enable = 1
        await self.h.write(self.base + I3C_EC_STDBYCTRLMODE_STBY_CR_CONTROL_REG_ADDR, stby_cr.val)

        # 4. Enable PIO interrupts (status enable)
        intr_en = PioIntrStatusEnable()
        intr_en.f.tx_thld_stat_en = 1
        intr_en.f.rx_thld_stat_en = 1
        intr_en.f.resp_ready_stat_en = 1
        intr_en.f.cmd_queue_ready_stat_en = 1
        await self.h.write(self.base + PIOCONTROL_PIO_INTR_STATUS_ENABLE_REG_ADDR, intr_en.val)

        # 5. Enable PIO interrupts (signal enable)
        sig_en = PioIntrSignalEnable()
        sig_en.f.tx_thld_signal_en = 1
        sig_en.f.rx_thld_signal_en = 1
        sig_en.f.resp_ready_signal_en = 1
        await self.h.write(self.base + PIOCONTROL_PIO_INTR_SIGNAL_ENABLE_REG_ADDR, sig_en.val)

        # 6. Enable PIO queues with RS=1
        pio_ctrl = PioControl()
        pio_ctrl.f.enable = 1
        pio_ctrl.f.rs = 1
        await self.h.write(self.base + PIOCONTROL_PIO_CONTROL_REG_ADDR, pio_ctrl.val)

    async def configure_timing_od_i3c(self):
        """Program the controller's open-drain bus timing (mirrors upstream boot_init;
        the OD-specific timings incl. T_HIGH_INIT_OD are needed to drive SCL)."""
        await self.h.write(self.base + I3C_EC_SOCMGMTIF_T_R_REG_REG_ADDR, 0)
        await self.h.write(self.base + I3C_EC_SOCMGMTIF_T_F_REG_REG_ADDR, 0)
        await self.h.write(self.base + I3C_EC_SOCMGMTIF_T_SU_DAT_REG_REG_ADDR, 2)
        await self.h.write(self.base + I3C_EC_SOCMGMTIF_T_HD_DAT_REG_REG_ADDR, 2)
        await self.h.write(self.base + I3C_EC_SOCMGMTIF_T_HIGH_REG_REG_ADDR, 14)
        await self.h.write(self.base + I3C_EC_SOCMGMTIF_T_HIGH_OD_REG_REG_ADDR, 20)
        await self.h.write(self.base + I3C_EC_SOCMGMTIF_T_HIGH_INIT_OD_REG_REG_ADDR, 70)
        await self.h.write(self.base + I3C_EC_SOCMGMTIF_T_LOW_REG_REG_ADDR, 14)
        await self.h.write(self.base + I3C_EC_SOCMGMTIF_T_LOW_OD_REG_REG_ADDR, 70)
        await self.h.write(self.base + I3C_EC_SOCMGMTIF_T_HD_STA_REG_REG_ADDR, 13)
        await self.h.write(self.base + I3C_EC_SOCMGMTIF_T_SU_STA_REG_REG_ADDR, 9)
        await self.h.write(self.base + I3C_EC_SOCMGMTIF_T_SU_STO_REG_REG_ADDR, 8)
        await self.h.write(self.base + I3C_EC_SOCMGMTIF_T_HD_RSTA_REG_REG_ADDR, 9)
        await self.h.write(self.base + I3C_EC_SOCMGMTIF_T_DS_OD_REG_REG_ADDR, 24)
        await self.h.write(self.base + I3C_EC_SOCMGMTIF_T_FREE_REG_REG_ADDR, 13)
        # T_AVAL: Bus available time (target waits this before sending IBI)
        await self.h.write(self.base + I3C_EC_SOCMGMTIF_T_AVAL_REG_REG_ADDR, 333)
        # T_IDLE: Bus idle time
        await self.h.write(self.base + I3C_EC_SOCMGMTIF_T_IDLE_REG_REG_ADDR, 66600)

    async def configure_timing_pp(self):
        """Retain call-site compatibility; PP timing derives from T_HIGH/T_LOW."""
        return

    async def configure_thresholds(
        self, tx_buf=1, tx_start=0, rx_buf=1, rx_start=0, cmd_empty_buf=1, resp_buf=1
    ):
        """Configure DATA_BUFFER_THLD_CTRL and QUEUE_THLD_CTRL using ctypes.

        Data buffer threshold = 2^(val+1) entries.
        Queue threshold = val+1 entries.
        """
        self.tx_thld = tx_buf
        self.rx_thld = rx_buf

        # Configure DATA_BUFFER_THLD_CTRL
        thld = DataBufferThldCtrl()
        thld.f.tx_buf_thld = tx_buf
        thld.f.rx_buf_thld = rx_buf
        thld.f.tx_start_thld = tx_start
        thld.f.rx_start_thld = rx_start
        await self.h.write(self.base + PIOCONTROL_DATA_BUFFER_THLD_CTRL_REG_ADDR, thld.val)

        # Configure QUEUE_THLD_CTRL (controls CMD_QUEUE_READY_STAT and RESP_READY_STAT)
        queue_thld = QueueThldCtrl()
        queue_thld.f.cmd_empty_buf_thld = cmd_empty_buf
        queue_thld.f.resp_buf_thld = resp_buf
        await self.h.write(self.base + PIOCONTROL_QUEUE_THLD_CTRL_REG_ADDR, queue_thld.val)

    async def enable_ibi_interrupts(self, ibi_threshold=1):
        """Enable IBI interrupts on the controller.

        Args:
            ibi_threshold: IBI status queue threshold (interrupt fires when >= threshold entries)
        """
        # Enable IBI_STATUS_THLD_STAT interrupt using ctypes field access
        intr_en = await self.h.read_into(
            self.base + PIOCONTROL_PIO_INTR_STATUS_ENABLE_REG_ADDR, PioIntrStatusEnable
        )
        intr_en.f.ibi_status_thld_stat_en = 1
        await self.h.write(self.base + PIOCONTROL_PIO_INTR_STATUS_ENABLE_REG_ADDR, intr_en.val)

        # Configure IBI status threshold in QUEUE_THLD_CTRL
        queue_thld = await self.h.read_into(
            self.base + PIOCONTROL_QUEUE_THLD_CTRL_REG_ADDR, QueueThldCtrl
        )
        queue_thld.f.ibi_status_thld = ibi_threshold
        await self.h.write(self.base + PIOCONTROL_QUEUE_THLD_CTRL_REG_ADDR, queue_thld.val)

        # Enable IBI signal using ctypes field access
        sig_en = await self.h.read_into(
            self.base + PIOCONTROL_PIO_INTR_SIGNAL_ENABLE_REG_ADDR, PioIntrSignalEnable
        )
        sig_en.f.ibi_status_thld_signal_en = 1
        await self.h.write(self.base + PIOCONTROL_PIO_INTR_SIGNAL_ENABLE_REG_ADDR, sig_en.val)

        self.h.log.info(f"Controller IBI interrupts enabled (threshold={ibi_threshold})")

    async def wait_ibi_received(self, max_polls=10000, interval=10):
        """Wait for controller to receive IBI (IBI_STATUS_THLD_STAT fires).

        Returns:
            (success, reg) where reg is the PioIntrStatus register value when IBI is ready
        """
        self.h.log.debug("Waiting for IBI to be received on controller...")
        ok, reg = await self.h.poll_field(
            self.base + PIOCONTROL_PIO_INTR_STATUS_REG_ADDR,
            PioIntrStatus,
            "ibi_status_thld_stat",
            max_polls,
            interval,
        )
        return ok, reg

    async def read_ibi(self):
        """Read IBI from controller's IBI_PORT.

        Reads IBI status descriptors and data according to HCI Table 147.
        The IBI status descriptor format:
            [31]    ibi_sts      - IBI Received Status
            [30]    error        - Error indicator
            [29:27] status_type  - Status Type (000=RegularIbi, etc.)
            [26]    reserved
            [25]    ts           - IBI Timestamp Present
            [24]    last_status  - Last IBI Status for transaction
            [23:16] chunks       - Valid data chunks (DMA mode)
            [15:8]  ibi_id       - IBI Received ID (target address)
            [7:0]   data_length  - IBI Data Length (bytes)

        For RegularIbi, the first data byte is the MDB (Mandatory Data Byte).

        Returns:
            (success, ibi_id, mdb, payload_bytes) where:
            - ibi_id: Target address that sent the IBI
            - mdb: Mandatory Data Byte (first byte of data)
            - payload_bytes: Remaining payload data bytes (after MDB)
        """
        bytes_per_entry = 4
        all_data = []
        ibi_id = 0
        max_status_descriptors = 64

        # Loop reading IBI status descriptors until last_status is set
        for status_idx in range(1, max_status_descriptors + 1):
            # Read IBI status descriptor
            ibi_status = await self.h.read(self.base + PIOCONTROL_IBI_PORT_REG_ADDR)

            # Parse IBI status descriptor fields from i3c_pkg.sv
            ibi_sts = (ibi_status >> 31) & 0x1
            error = (ibi_status >> 30) & 0x1
            status_type = (ibi_status >> 27) & 0x7
            ts = (ibi_status >> 25) & 0x1
            last_status = (ibi_status >> 24) & 0x1
            chunks = (ibi_status >> 16) & 0xFF
            ibi_id = (ibi_status >> 8) & 0xFF
            data_length = ibi_status & 0xFF

            self.h.log.debug(
                f"read_ibi: status=0x{ibi_status:08X}, ibi_sts={ibi_sts}, error={error}, "
                f"status_type={status_type}, ts={ts}, last_status={last_status}, "
                f"chunks={chunks}, ibi_id=0x{ibi_id:02X}, data_length={data_length}"
            )

            # Check for error
            if error:
                self.h.log.error(f"read_ibi: IBI error detected, status_type={status_type}")
                return False, ibi_id, 0, []

            # Read data_length bytes from IBI_PORT
            bytes_remaining = data_length
            while bytes_remaining > 0:
                word = await self.h.read(self.base + PIOCONTROL_IBI_PORT_REG_ADDR)
                bytes_to_take = min(bytes_per_entry, bytes_remaining)
                unpacked = self.h.unpack_bytes(word, bytes_to_take)
                self.h.log.debug(
                    f"read_ibi: data word=0x{word:08X} -> {[f'0x{b:02X}' for b in unpacked]}"
                )
                all_data.extend(unpacked)
                bytes_remaining -= bytes_to_take

            # Exit loop if this is the last status descriptor
            if last_status:
                break
        else:
            self.h.log.error(
                f"read_ibi: timeout — last_status never set after {max_status_descriptors} "
                f"descriptors (bytes_so_far={len(all_data)})"
            )
            return False, ibi_id, 0, []

        # For RegularIbi (status_type=0), first byte is MDB
        if len(all_data) > 0:
            mdb = all_data[0]
            payload_bytes = all_data[1:]
        else:
            mdb = 0
            payload_bytes = []

        self.h.log.debug(
            f"read_ibi: complete - ibi_id=0x{ibi_id:02X}, mdb=0x{mdb:02X}, "
            f"payload={[f'0x{b:02X}' for b in payload_bytes]}"
        )
        return True, ibi_id, mdb, payload_bytes

    async def set_dat_entry(self, idx, static_addr, dynamic_addr, ibi_payload=False):
        """Write DAT entry for device address table.

        ibi_payload: set the DAT entry's IBI Payload bit (dat_entry_t.ibi_payload,
        bit 12 per controller_pkg.sv). The controller aborts an inbound IBI unless
        this bit is set for the target (ibi_abort = ibi_reject | ~ibi_payload), so
        targets whose BCR[2]=1 must have it programmed to receive IBI MDB/payload.
        """
        dat_lo = (static_addr & 0x7F) | ((dynamic_addr & 0x7F) << 16)
        if ibi_payload:
            dat_lo |= 1 << 12
        dat_hi = 0
        await self.h.write(self.base + DAT_MEM_BASE_ADDR + idx * 8, dat_lo)
        await self.h.write(self.base + DAT_MEM_BASE_ADDR + idx * 8 + 4, dat_hi)

    async def configure_target_ibi(self, dat_idx, static_addr, dynamic_addr):
        """Program the DAT entry's IBI-payload policy from the target's BCR[2].

        Call after the target's dynamic address is assigned (GETBCR must succeed).
        The controller aborts an inbound IBI unless DAT.ibi_payload is set
        (ibi_abort = ibi_reject | ~ibi_payload), so a target whose BCR[2]=1 must
        have it programmed to receive the IBI MDB/payload. Returns the bit set.
        """
        ok, bcr = await self.getbcr(dat_idx=dat_idx)
        ibi_payload = bool(ok and ((bcr >> 2) & 0x1))
        await self.set_dat_entry(dat_idx, static_addr, dynamic_addr, ibi_payload=ibi_payload)
        self.h.log.info(
            f"configure_target_ibi: dat[{dat_idx}] bcr=0x{bcr:02X} "
            f"-> ibi_payload={int(ibi_payload)}"
        )
        return ibi_payload

    async def send_setdasa(self, static_addr, dynamic_addr, dat_idx=0):
        """Send SETDASA CCC to assign dynamic address. Returns (success, response)."""
        await self.set_dat_entry(dat_idx, static_addr, dynamic_addr)
        # Build command descriptor: attr=2 (AddrAssign), cmd=0x87, wroc=1, toc=1 see i3c_pkg.sv
        cmd_lo = (0x2 << 0) | (0x87 << 7) | (dat_idx << 16) | (1 << 26) | (1 << 30) | (1 << 31)
        cmd_hi = 0
        await self.h.write(self.base + PIOCONTROL_COMMAND_PORT_REG_ADDR, cmd_lo)
        await self.h.write(self.base + PIOCONTROL_COMMAND_PORT_REG_ADDR, cmd_hi)

        self.h.log.debug(f"setdasa: command issued (cmd_lo=0x{cmd_lo:08X}, cmd_hi=0x{cmd_hi:08X})")
        # Wait for response using ctypes
        ok, reg = await self.h.poll_field(
            self.base + PIOCONTROL_PIO_INTR_STATUS_REG_ADDR, PioIntrStatus, "resp_ready_stat"
        )
        if ok:
            resp = await self.h.read(self.base + PIOCONTROL_RESPONSE_PORT_REG_ADDR)
            err = (resp >> 28) & 0xF
            return err == 0, resp
        return False, 0

    async def private_write(
        self, data_bytes, target, dat_idx=0, bytes_per_entry=4, expect_error=False
    ):
        """
        Private write with interleaved target RX drain.
        Returns (success, response, rx_data).

        Args:
            data_bytes: Data to write
            target: I3CTarget instance
            dat_idx: DAT index for target
            bytes_per_entry: Bytes per FIFO entry (default 4, matches TtiRxDataWidth=32)
            expect_error: If True, a non-zero controller err_status is logged at INFO
                (expected negative path) instead of ERROR, so TTEM fail patterns do not
                trip while the caller asserts the failure. Timeouts / length mismatches
                always log ERROR.
        """
        data_len = len(data_bytes)

        # Controller TX threshold (in bytes)
        tx_entries_per_interrupt = 1 << (self.tx_thld + 1)
        tx_bytes_per_interrupt = tx_entries_per_interrupt * bytes_per_entry

        # Target RX threshold (in entries and bytes)
        rx_entries_per_interrupt = 1 << (target.rx_thld + 1)
        rx_bytes_per_interrupt = rx_entries_per_interrupt * bytes_per_entry

        TTI_RX_DATA_THLD_STAT = 1 << TTI_INTR_RX_DATA_THLD_BIT

        self.h.log.debug(
            f"private_write: {data_len} bytes, "
            f"tx_thld={tx_bytes_per_interrupt} bytes ({tx_entries_per_interrupt} entries), "
            f"rx_thld={rx_bytes_per_interrupt} bytes ({rx_entries_per_interrupt} entries)"
        )

        # Wait for command queue to have space
        ok, _ = await self.h.poll_field(
            self.base + PIOCONTROL_PIO_INTR_STATUS_REG_ADDR, PioIntrStatus, "cmd_queue_ready_stat"
        )
        if not ok:
            self.h.log.error("private_write: timeout waiting for command queue ready")
            return False, 0, []

        # Issue command (see i3c_pkg.sv for descriptor format):
        cmd_lo = (0x0 << 0) | (dat_idx << 16) | (1 << 30) | (1 << 31)
        cmd_hi = data_len << 16
        await self.h.write(self.base + PIOCONTROL_COMMAND_PORT_REG_ADDR, cmd_lo)
        await self.h.write(self.base + PIOCONTROL_COMMAND_PORT_REG_ADDR, cmd_hi)
        self.h.log.debug(
            f"private_write: command issued (cmd_lo=0x{cmd_lo:08X}, cmd_hi=0x{cmd_hi:08X})"
        )

        bytes_written = 0
        bytes_read = 0
        rx_data = []

        # Loop until controller response is ready
        # During the loop: write TX data and drain target RX data when threshold interrupts fire
        max_loops = 10000
        for loop_count in range(1, max_loops + 1):
            if loop_count % 100 == 0:
                self.h.log.debug(
                    f"private_write: loop {loop_count}, written={bytes_written}/{data_len}, read={bytes_read}/{data_len} "
                    f"rx_data={len(rx_data)}"
                )

            # Check if controller response is ready
            ctrl_status = await self.h.read_into(
                self.base + PIOCONTROL_PIO_INTR_STATUS_REG_ADDR, PioIntrStatus
            )
            if ctrl_status.f.resp_ready_stat:
                self.h.log.debug(
                    f"private_write: controller response descriptor ready, bytes_written={bytes_written}, rx_data={len(rx_data)}"
                )
                break

            # Fill controller TX FIFO when TX_THLD_STAT fires
            if bytes_written < data_len and ctrl_status.f.tx_thld_stat:
                remaining_tx = data_len - bytes_written
                chunk = min(tx_bytes_per_interrupt, remaining_tx)
                for i in range(0, chunk, bytes_per_entry):
                    word = self.h.pack_bytes(
                        data_bytes[bytes_written + i : bytes_written + i + bytes_per_entry]
                    )
                    await self.h.write(self.base + PIOCONTROL_TX_DATA_PORT_REG_ADDR, word)
                bytes_written += chunk
                self.h.log.debug(
                    f"private_write: wrote {chunk} bytes to TX, total={bytes_written}/{data_len}"
                )

            # Drain target RX FIFO when TTI_RX_DATA_THLD_STAT fires naturally
            tgt_status = await self.h.read(target.base + I3C_EC_TTI_INTERRUPT_STATUS_REG_ADDR)
            if tgt_status & TTI_RX_DATA_THLD_STAT:
                # Read up to threshold entries, but never more bytes than still expected
                for entry_idx in range(rx_entries_per_interrupt):
                    if bytes_read >= data_len:
                        break
                    word = await self.h.read(target.base + I3C_EC_TTI_RX_DATA_PORT_REG_ADDR)
                    bytes_to_take = min(bytes_per_entry, data_len - bytes_read)
                    unpacked = self.h.unpack_bytes(word, bytes_to_take)
                    self.h.log.debug(
                        f"private_write: RX entry[{bytes_read // 4 + entry_idx}] word=0x{word:08X} -> {[f'0x{b:02X}' for b in unpacked]}"
                    )
                    rx_data.extend(unpacked)
                    bytes_read += bytes_to_take
                self.h.log.debug(f"private_write: drained target RX, total={len(rx_data)}")

            await ClockCycles(self.h.dut.clk, 10)
        else:
            self.h.log.error(
                f"private_write: timeout waiting for resp_ready "
                f"(loops={max_loops}, written={bytes_written}/{data_len}, "
                f"read={bytes_read}/{data_len}, rx_len={len(rx_data)})"
            )
            return False, 0, []

        # Read controller response descriptor
        resp = await self.h.read(self.base + PIOCONTROL_RESPONSE_PORT_REG_ADDR)
        resp_data_length = resp & 0xFFFF
        err_status = (resp >> 28) & 0xF
        self.h.log.debug(
            f"private_write: response=0x{resp:08X}, data_length={resp_data_length}, err={err_status}"
        )

        # Check for errors
        if err_status != 0:
            msg = f"private_write: transfer error, err_status={err_status}"
            if expect_error:
                self.h.log.info(msg + " (expected)")
            else:
                self.h.log.error(msg)
            return False, resp, rx_data

        # Validate resp_data_length is 0 (all bytes have been received)
        if resp_data_length != 0:
            self.h.log.error(
                f"private_write: response descriptor data_length={resp_data_length} "
                f"(expected 0 — not all bytes received)"
            )
            return False, resp, rx_data

        # Wait for target RX descriptor to be posted (QUEUE_STATUS, not THLD interrupt —
        # same FW-owns-queue model as TX data; THLD_STAT is not a reliable ready signal).
        ok, _ = await self.h.poll_field_clear(
            target.base + I3C_EC_TTI_QUEUE_STATUS_REG_ADDR,
            TtiQueueStatus,
            "rx_desc_queue_empty",
            max_polls=1000,
            interval=10,
        )
        if not ok:
            self.h.log.error("private_write: timeout waiting for target RX descriptor")
            return False, resp, rx_data

        # Read target RX descriptor (format: {rx_error[31:20], reserved[19:16], byte_counter[15:0]})
        tgt_rx_desc = await self.h.read(target.base + I3C_EC_TTI_RX_DESC_QUEUE_PORT_REG_ADDR)
        tgt_rx_data_length = tgt_rx_desc & 0xFFFF
        tgt_rx_error = (tgt_rx_desc >> 20) & 0xFFF
        self.h.log.debug(
            f"private_write: target RX descriptor=0x{tgt_rx_desc:08X}, "
            f"data_length={tgt_rx_data_length}, error={tgt_rx_error}"
        )

        if tgt_rx_error != 0:
            self.h.log.error(f"private_write: target RX descriptor reports error={tgt_rx_error}")
            return False, resp, rx_data

        if tgt_rx_data_length != data_len:
            self.h.log.error(
                f"private_write: target RX data_length={tgt_rx_data_length}, expected {data_len}"
            )
            return False, resp, rx_data

        # Drain any remaining bytes not read during threshold interrupts (I3C HCI 6.8.1)
        remaining_bytes = tgt_rx_data_length - bytes_read
        if remaining_bytes > 0:
            self.h.log.debug(
                f"private_write: draining remaining {remaining_bytes} bytes (bytes_read={bytes_read})"
            )
            drain_entry_idx = 0
            while remaining_bytes > 0:
                word = await self.h.read(target.base + I3C_EC_TTI_RX_DATA_PORT_REG_ADDR)
                bytes_to_take = min(bytes_per_entry, remaining_bytes)
                unpacked = self.h.unpack_bytes(word, bytes_to_take)
                self.h.log.debug(
                    f"private_write: drain entry[{bytes_read // 4 + drain_entry_idx}] word=0x{word:08X} -> {[f'0x{b:02X}' for b in unpacked]}"
                )
                rx_data.extend(unpacked)
                remaining_bytes -= bytes_to_take
                drain_entry_idx += 1
            self.h.log.debug(f"private_write: final rx_data length={len(rx_data)}")

        if len(rx_data) != data_len:
            self.h.log.error(
                f"private_write: drained payload length={len(rx_data)} != expected {data_len}"
            )
            return False, resp, rx_data

        return True, resp, rx_data

    async def private_read(self, target, tx_data, dat_idx=0, bytes_per_entry=4, expect_error=False):
        """
        Private read with interleaved target TX fill and controller RX drain.
        Returns (success, response, rx_data).

        Args:
            target: I3CTarget instance
            tx_data: Data for target to transmit
            dat_idx: DAT index for target
            bytes_per_entry: Bytes per FIFO entry (default 4)
            expect_error: If True, a non-zero controller err_status / early response is
                logged at INFO (expected negative path) instead of ERROR.
        """
        data_len = len(tx_data)

        # Controller RX threshold (in bytes)
        rx_entries_per_interrupt = 1 << (self.rx_thld + 1)
        rx_bytes_per_interrupt = rx_entries_per_interrupt * bytes_per_entry

        # Target TX threshold (in bytes)
        tx_entries_per_interrupt = 1 << (target.tx_thld + 1)
        tx_bytes_per_interrupt = tx_entries_per_interrupt * bytes_per_entry

        TTI_TX_DESC_COMPLETE = 1 << TTI_INTR_TX_DESC_COMPLETE_BIT

        self.h.log.debug(
            f"private_read: {data_len} bytes, "
            f"ctrl_rx_thld={rx_bytes_per_interrupt} bytes ({rx_entries_per_interrupt} entries), "
            f"tgt_tx_thld={tx_bytes_per_interrupt} bytes ({tx_entries_per_interrupt} entries)"
        )

        bytes_written = 0  # bytes written to target TX FIFO
        bytes_read = 0  # bytes read from controller RX FIFO
        rx_data = []

        # Arm the target TX (descriptor + first chunk) BEFORE issuing the read: the
        # target NACKs a read with an empty TX queue (no clock-stretch), and the
        # controller treats that NACK as terminal -> TX_DESC_COMPLETE never fires.

        # Wait for target TX descriptor queue to have space via QUEUE_STATUS
        # (not TX_DESC_THLD_STAT — that interrupt is not a reliable ready signal here).
        ok, _ = await self.h.poll_field_clear(
            target.base + I3C_EC_TTI_QUEUE_STATUS_REG_ADDR,
            TtiQueueStatus,
            "tx_desc_queue_full",
            max_polls=1000,
            interval=10,
        )
        if not ok:
            self.h.log.error("private_read: timeout waiting for TX descriptor queue space")
            return False, 0, []

        # Write TX descriptor to target - tells target how many bytes to send
        # Format: byte_count in upper 16 bits
        tx_desc = data_len << 16
        await self.h.write(target.base + I3C_EC_TTI_TX_DESC_QUEUE_PORT_REG_ADDR, tx_desc)
        self.h.log.debug(
            f"private_read: wrote TX descriptor 0x{tx_desc:08X} (byte_count={data_len})"
        )

        # Pre-fill the target TX queue through its available capacity before issuing
        # the read. The target NACKs until the message is startable, and this API
        # does not retry NACKs.
        if data_len > 0:
            while bytes_written < data_len:
                qs = await self.h.read_into(
                    target.base + I3C_EC_TTI_QUEUE_STATUS_REG_ADDR, TtiQueueStatus
                )
                if qs.f.tx_data_queue_full:
                    break  # queue full: >capacity message streams the rest below
                word = self.h.pack_bytes(tx_data[bytes_written : bytes_written + bytes_per_entry])
                await self.h.write(target.base + I3C_EC_TTI_TX_DATA_PORT_REG_ADDR, word)
                bytes_written += min(bytes_per_entry, data_len - bytes_written)
            self.h.log.debug(
                f"private_read: pre-filled {bytes_written}/{data_len} bytes to target TX"
            )

        # Issue the read command AFTER the target is armed
        cmd_lo = (0x0 << 0) | (dat_idx << 16) | (1 << 29) | (1 << 30) | (1 << 31)  # rnw=1
        cmd_hi = data_len << 16
        await self.h.write(self.base + PIOCONTROL_COMMAND_PORT_REG_ADDR, cmd_lo)
        await self.h.write(self.base + PIOCONTROL_COMMAND_PORT_REG_ADDR, cmd_hi)
        self.h.log.debug(
            f"private_read: command issued (cmd_lo=0x{cmd_lo:08X}, cmd_hi=0x{cmd_hi:08X})"
        )

        # Main loop - wait for target TX_DESC_COMPLETE (bounded; do not rely on module timeout)
        max_loops = 10000
        for loop_count in range(1, max_loops + 1):
            if loop_count % 100 == 0:
                self.h.log.debug(
                    f"private_read: loop {loop_count}, written={bytes_written}/{data_len}, "
                    f"read={bytes_read}/{data_len}"
                )

            # Check if target TX transaction is complete
            tgt_status = await self.h.read(target.base + I3C_EC_TTI_INTERRUPT_STATUS_REG_ADDR)
            if tgt_status & TTI_TX_DESC_COMPLETE:
                self.h.log.debug(
                    f"private_read: target TX_DESC_COMPLETE, bytes_written={bytes_written}, "
                    f"bytes_read={bytes_read}"
                )
                break

            # Poll QUEUE_STATUS.tx_data_queue_full because this core does not provide
            # TX_DATA_THLD_STAT for this FW-owned queue.
            while bytes_written < data_len:
                qs = await self.h.read_into(
                    target.base + I3C_EC_TTI_QUEUE_STATUS_REG_ADDR, TtiQueueStatus
                )
                if qs.f.tx_data_queue_full:
                    break
                _word = self.h.pack_bytes(tx_data[bytes_written : bytes_written + bytes_per_entry])
                await self.h.write(target.base + I3C_EC_TTI_TX_DATA_PORT_REG_ADDR, _word)
                bytes_written += bytes_per_entry

            # Drain controller RX FIFO when RX_THLD_STAT fires
            ctrl_status = await self.h.read_into(
                self.base + PIOCONTROL_PIO_INTR_STATUS_REG_ADDR, PioIntrStatus
            )
            if ctrl_status.f.rx_thld_stat:
                self.h.log.debug(f"private_read: ctrl_status raw=0x{ctrl_status.val:08X}")

                for entry_idx in range(rx_entries_per_interrupt):
                    if bytes_read >= data_len:
                        break
                    word = await self.h.read(self.base + PIOCONTROL_RX_DATA_PORT_REG_ADDR)
                    bytes_to_take = min(bytes_per_entry, data_len - bytes_read)
                    unpacked = self.h.unpack_bytes(word, bytes_to_take)
                    self.h.log.debug(
                        f"private_read: RX entry[{bytes_read // 4 + entry_idx}] word=0x{word:08X} -> "
                        f"{[f'0x{b:02X}' for b in unpacked]}"
                    )
                    rx_data.extend(unpacked)
                    bytes_read += bytes_to_take
                self.h.log.debug(f"private_read: drained controller RX, total={bytes_read}")

            # Fail fast: a terminal controller response (e.g. NACK) posts resp_ready
            # while TX_DESC_COMPLETE never fires. Do not fall through to a green return.
            if ctrl_status.f.resp_ready_stat:
                resp = await self.h.read(self.base + PIOCONTROL_RESPONSE_PORT_REG_ADDR)
                err_status = (resp >> 28) & 0xF
                msg = (
                    "private_read: controller posted response before "
                    f"target TX_DESC_COMPLETE (resp=0x{resp:08X}, err={err_status})"
                )
                if expect_error:
                    self.h.log.info(msg + " (expected)")
                else:
                    self.h.log.error(msg)
                return False, resp, rx_data

            await ClockCycles(self.h.dut.clk, 10)
        else:
            self.h.log.error(
                f"private_read: timeout waiting for TX_DESC_COMPLETE "
                f"(loops={max_loops}, written={bytes_written}/{data_len}, "
                f"read={bytes_read}/{data_len})"
            )
            return False, 0, []

        # Wait for controller response descriptor
        ok, _ = await self.h.poll_field(
            self.base + PIOCONTROL_PIO_INTR_STATUS_REG_ADDR, PioIntrStatus, "resp_ready_stat"
        )
        if not ok:
            self.h.log.error("private_read: timeout waiting for controller response")
            return False, 0, []

        # Read and validate controller response
        resp = await self.h.read(self.base + PIOCONTROL_RESPONSE_PORT_REG_ADDR)
        resp_data_length = resp & 0xFFFF
        err_status = (resp >> 28) & 0xF
        self.h.log.debug(
            f"private_read: response=0x{resp:08X}, data_length={resp_data_length}, err={err_status}"
        )

        if err_status != 0:
            msg = f"private_read: transfer error, err_status={err_status}"
            if expect_error:
                self.h.log.info(msg + " (expected)")
            else:
                self.h.log.error(msg)
            return False, resp, rx_data

        # For private_read, DATA_LENGTH = bytes received (should match data_len)
        if resp_data_length != data_len:
            self.h.log.error(f"private_read: DATA_LENGTH={resp_data_length} != expected {data_len}")
            return False, resp, rx_data

        # Drain remaining bytes not read during threshold interrupts
        remaining_bytes = resp_data_length - bytes_read
        if remaining_bytes > 0:
            self.h.log.debug(
                f"private_read: draining remaining {remaining_bytes} bytes (bytes_read={bytes_read})"
            )
            drain_entry_idx = 0
            while remaining_bytes > 0:
                word = await self.h.read(self.base + PIOCONTROL_RX_DATA_PORT_REG_ADDR)
                bytes_to_take = min(bytes_per_entry, remaining_bytes)
                unpacked = self.h.unpack_bytes(word, bytes_to_take)
                self.h.log.debug(
                    f"private_read: drain entry[{bytes_read // 4 + drain_entry_idx}] word=0x{word:08X} -> "
                    f"{[f'0x{b:02X}' for b in unpacked]}"
                )
                rx_data.extend(unpacked)
                remaining_bytes -= bytes_to_take
                drain_entry_idx += 1
            self.h.log.debug(f"private_read: final rx_data length={len(rx_data)}")

        if len(rx_data) != data_len:
            self.h.log.error(
                f"private_read: drained payload length={len(rx_data)} != expected {data_len}"
            )
            return False, resp, rx_data

        return True, resp, rx_data

    async def get_ccc(self, ccc_code, max_data_len, dat_idx=0):
        """
        Send a Direct CCC GET command and read response data.

        Args:
            ccc_code: CCC command code (e.g., 0x8E for GETBCR)
            max_data_len: Maximum number of bytes expected (used in command descriptor)
            dat_idx: DAT index for target device

        Returns:
            (success, data_bytes) tuple where data_bytes is a list of received bytes.
            The actual number of bytes is determined from the response descriptor's DATA_LENGTH field.
        """
        bytes_per_entry = 4

        self.h.log.debug(
            f"get_ccc: ccc_code=0x{ccc_code:02X}, max_data_len={max_data_len}, dat_idx={dat_idx}"
        )

        # Wait for command queue to have space
        ok, _ = await self.h.poll_field(
            self.base + PIOCONTROL_PIO_INTR_STATUS_REG_ADDR, PioIntrStatus, "cmd_queue_ready_stat"
        )
        if not ok:
            self.h.log.error("get_ccc: timeout waiting for command queue ready")
            return False, []

        # Build command descriptor for CCC read:
        # attr=0 (RegularTransfer), cp=1 (command present), rnw=1 (read)
        cmd_lo = (
            (0 << 0)  # attr = 0 (RegularTransfer)
            | (ccc_code << 7)  # cmd = CCC code
            | (1 << 15)  # cp = 1 (command present)
            | (dat_idx << 16)  # dev_idx
            | (1 << 29)  # rnw = 1 (read)
            | (1 << 30)  # wroc = 1 (response on completion)
            | (1 << 31)  # toc = 1 (terminate on completion)
        )
        cmd_hi = max_data_len << 16  # data_length in bits [31:16]

        # Issue command
        await self.h.write(self.base + PIOCONTROL_COMMAND_PORT_REG_ADDR, cmd_lo)
        await self.h.write(self.base + PIOCONTROL_COMMAND_PORT_REG_ADDR, cmd_hi)
        self.h.log.debug(f"get_ccc: command issued (cmd_lo=0x{cmd_lo:08X}, cmd_hi=0x{cmd_hi:08X})")

        # Wait for response descriptor
        ok, _ = await self.h.poll_field(
            self.base + PIOCONTROL_PIO_INTR_STATUS_REG_ADDR, PioIntrStatus, "resp_ready_stat"
        )
        if not ok:
            self.h.log.error("get_ccc: timeout waiting for response")
            return False, []

        # Read response descriptor
        resp = await self.h.read(self.base + PIOCONTROL_RESPONSE_PORT_REG_ADDR)
        resp_data_length = resp & 0xFFFF
        err_status = (resp >> 28) & 0xF
        self.h.log.debug(
            f"get_ccc: response=0x{resp:08X}, data_length={resp_data_length}, err={err_status}"
        )

        if err_status != 0:
            self.h.log.error(f"get_ccc: transfer error, err_status={err_status}")
            return False, []

        # Drain received bytes from RX FIFO
        rx_data = []
        bytes_remaining = resp_data_length
        while bytes_remaining > 0:
            word = await self.h.read(self.base + PIOCONTROL_RX_DATA_PORT_REG_ADDR)
            bytes_to_take = min(bytes_per_entry, bytes_remaining)
            unpacked = self.h.unpack_bytes(word, bytes_to_take)
            self.h.log.debug(f"get_ccc: RX word=0x{word:08X} -> {[f'0x{b:02X}' for b in unpacked]}")
            rx_data.extend(unpacked)
            bytes_remaining -= bytes_to_take

        self.h.log.debug(
            f"get_ccc: received {len(rx_data)} bytes: {[f'0x{b:02X}' for b in rx_data]}"
        )
        return True, rx_data

    async def getbcr(self, dat_idx=0):
        """
        Get Bus Characteristics Register (BCR) from target.

        Args:
            dat_idx: DAT index for target device

        Returns:
            (success, bcr_value) where bcr_value is a single byte (0-255)
        """
        ok, data = await self.get_ccc(CCC_GETBCR, 1, dat_idx)
        if not ok or len(data) < 1:
            return False, 0
        bcr = data[0]
        self.bcr_cache[dat_idx] = bcr  # Cache for setmrl
        return True, bcr

    async def getmwl(self, dat_idx=0):
        """
        Get Max Write Length (MWL) from target.

        Args:
            dat_idx: DAT index for target device

        Returns:
            (success, mwl) where mwl is a 16-bit value
        """
        ok, data = await self.get_ccc(CCC_GETMWL, 2, dat_idx)
        if not ok or len(data) < 2:
            return False, 0
        # Per I3C spec: MWL is transmitted MSB first
        mwl = (data[0] << 8) | data[1]
        return True, mwl

    async def getmrl(self, dat_idx=0):
        """
        Get Max Read Length (MRL) and IBI Payload Size from target.

        Note: IBI Payload Size is only valid if BCR[2] (IBI Payload) is set.
        Call getbcr() first to check BCR[2] before using ibi_payload_size.

        Args:
            dat_idx: DAT index for target device

        Returns:
            (success, mrl, ibi_payload_size)
            - mrl: 16-bit Max Read Length
            - ibi_payload_size: 8-bit IBI Payload Size (0 if only 2 bytes received, i.e., BCR[2]=0)
        """
        # Request up to 3 bytes - actual received count comes from response descriptor
        ok, data = await self.get_ccc(CCC_GETMRL, 3, dat_idx)
        if not ok or len(data) < 2:
            return False, 0, 0
        # Per I3C spec: MRL is transmitted MSB first
        mrl = (data[0] << 8) | data[1]
        # IBI payload size is third byte if target sent 3 bytes (BCR[2]=1), else 0
        ibi_payload_size = data[2] if len(data) >= 3 else 0
        return True, mrl, ibi_payload_size

    async def set_ccc(self, ccc_code, data_bytes, dat_idx=0):
        """
        Send a Direct CCC SET command with data.

        Args:
            ccc_code: CCC command code (e.g., 0x89 for SETMWL)
            data_bytes: List of bytes to send (1-4 bytes uses immediate descriptor)
            dat_idx: DAT index for target device

        Returns:
            (success, response) tuple
        """
        data_len = len(data_bytes)
        use_immediate = data_len <= 4

        self.h.log.debug(
            f"set_ccc: ccc_code=0x{ccc_code:02X}, data_len={data_len}, "
            f"dat_idx={dat_idx}, immediate={use_immediate}"
        )

        # Wait for command queue space
        ok, _ = await self.h.poll_field(
            self.base + PIOCONTROL_PIO_INTR_STATUS_REG_ADDR, PioIntrStatus, "cmd_queue_ready_stat"
        )
        if not ok:
            self.h.log.error("set_ccc: timeout waiting for command queue ready")
            return False, 0

        if use_immediate:
            # Immediate descriptor (attr=1): data embedded in descriptor
            # Pack data bytes into upper 32 bits (byte1 in bits[7:0], byte2 in [15:8], etc.)
            data_word = 0
            for i, b in enumerate(data_bytes):
                data_word |= (b & 0xFF) << (i * 8)

            cmd_lo = (
                (1 << 0)  # attr = 1 (ImmediateDataTransfer)
                | (ccc_code << 7)  # cmd = CCC code
                | (1 << 15)  # cp = 1 (command present)
                | (dat_idx << 16)  # dev_idx
                | (data_len << 23)  # dtt = data byte count
                | (0 << 29)  # rnw = 0 (write)
                | (1 << 30)  # wroc = 1
                | (1 << 31)  # toc = 1
            )
            cmd_hi = data_word

            await self.h.write(self.base + PIOCONTROL_COMMAND_PORT_REG_ADDR, cmd_lo)
            await self.h.write(self.base + PIOCONTROL_COMMAND_PORT_REG_ADDR, cmd_hi)
        else:
            # Regular descriptor (attr=0): data goes to TX FIFO
            cmd_lo = (
                (0 << 0)  # attr = 0 (RegularTransfer)
                | (ccc_code << 7)  # cmd = CCC code
                | (1 << 15)  # cp = 1 (command present)
                | (dat_idx << 16)  # dev_idx
                | (0 << 29)  # rnw = 0 (write)
                | (1 << 30)  # wroc = 1
                | (1 << 31)  # toc = 1
            )
            cmd_hi = data_len << 16

            await self.h.write(self.base + PIOCONTROL_COMMAND_PORT_REG_ADDR, cmd_lo)
            await self.h.write(self.base + PIOCONTROL_COMMAND_PORT_REG_ADDR, cmd_hi)

            # Wait for TX threshold before pushing data
            ok, _ = await self.h.poll_field(
                self.base + PIOCONTROL_PIO_INTR_STATUS_REG_ADDR, PioIntrStatus, "tx_thld_stat"
            )
            if not ok:
                self.h.log.error("set_ccc: timeout waiting for tx_thld_stat")
                return False, 0

            # Push data to TX FIFO
            bytes_per_entry = 4
            for i in range(0, data_len, bytes_per_entry):
                chunk = data_bytes[i : i + bytes_per_entry]
                word = self.h.pack_bytes(chunk)
                await self.h.write(self.base + PIOCONTROL_TX_DATA_PORT_REG_ADDR, word)

        self.h.log.debug(f"set_ccc: command issued (cmd_lo=0x{cmd_lo:08X}, cmd_hi=0x{cmd_hi:08X})")

        # Wait for response
        ok, _ = await self.h.poll_field(
            self.base + PIOCONTROL_PIO_INTR_STATUS_REG_ADDR, PioIntrStatus, "resp_ready_stat"
        )
        if not ok:
            self.h.log.error("set_ccc: timeout waiting for response")
            return False, 0

        # Read response descriptor
        resp = await self.h.read(self.base + PIOCONTROL_RESPONSE_PORT_REG_ADDR)
        err_status = (resp >> 28) & 0xF
        self.h.log.debug(f"set_ccc: response=0x{resp:08X}, err={err_status}")

        if err_status != 0:
            self.h.log.error(f"set_ccc: transfer error, err_status={err_status}")
            return False, resp

        return True, resp

    async def broadcast_set_ccc(self, ccc_code, data_bytes=None):
        """
        Send a Broadcast CCC SET (MIPI I3C Basic: Command Codes 0x00–0x7F).

        HCI framing uses an Immediate/Regular Transfer Command with CP=1.
        DEV_INDEX is unused for Broadcast CCCs and is forced to 0
        (MIPI I3C HCI §6.7 / §6.3). The controller selects Broadcast vs Direct
        framing from CCC bit7 (0 = Broadcast).

        Args:
            ccc_code: Broadcast CCC opcode (must be < 0x80), e.g. 0x00 ENEC
            data_bytes: Optional defining/data bytes (None or [] for no payload)

        Returns:
            (success, response) tuple
        """
        if data_bytes is None:
            data_bytes = []
        if ccc_code & 0x80:
            raise ValueError(
                f"broadcast_set_ccc: 0x{ccc_code:02X} is a Direct CCC "
                f"(bit7=1); use set_ccc()/rstact() instead"
            )
        return await self.set_ccc(ccc_code, data_bytes, dat_idx=0)

    async def send_rstdaa(self):
        """
        Broadcast RSTDAA (0x06) — clear Dynamic Address on all Targets.

        Returns:
            (success, response) tuple
        """
        return await self.broadcast_set_ccc(CCC_RSTDAA, [])

    async def setmwl(self, mwl, dat_idx=0):
        """
        Set Max Write Length (MWL) on target.

        Args:
            mwl: 16-bit Max Write Length value
            dat_idx: DAT index for target device

        Returns:
            (success, response)
        """
        # Per I3C spec: MWL is transmitted MSB first
        data = [(mwl >> 8) & 0xFF, mwl & 0xFF]
        return await self.set_ccc(CCC_SETMWL, data, dat_idx)

    async def setmrl(self, mrl, ibi_payload_size=0, dat_idx=0):
        """
        Set Max Read Length (MRL) on target.

        The IBI Payload Size byte is only sent if BCR[2] is set for this target.
        Call getbcr() before using this function to populate the BCR cache.

        Args:
            mrl: 16-bit Max Read Length value
            ibi_payload_size: 8-bit IBI Payload Size (only used if BCR[2]=1)
            dat_idx: DAT index for target device

        Returns:
            (success, response)
        """
        # Check cached BCR for this target
        bcr = self.bcr_cache.get(dat_idx, 0)
        has_ibi_payload = (bcr >> 2) & 0x1

        # Per I3C spec: MRL is transmitted MSB first
        data = [(mrl >> 8) & 0xFF, mrl & 0xFF]
        if has_ibi_payload:
            data.append(ibi_payload_size & 0xFF)

        self.h.log.debug(
            f"setmrl: mrl={mrl}, ibi_payload_size={ibi_payload_size}, "
            f"bcr=0x{bcr:02X}, has_ibi_payload={has_ibi_payload}, data_len={len(data)}"
        )

        return await self.set_ccc(CCC_SETMRL, data, dat_idx)

    async def rstact(self, defining_byte, dat_idx=0):
        """
        Send Direct RSTACT CCC (Target Reset Action).

        Args:
            defining_byte: Reset action type:
                0x00 = No reset
                0x01 = Peripheral reset
                0x02 = Target reset
                0x03 = Debug adapter reset
                0x04 = Virtual target detect
            dat_idx: DAT index for target device

        Returns:
            (success, response) tuple
        """
        self.h.log.debug(f"rstact: defining_byte=0x{defining_byte:02X}, dat_idx={dat_idx}")

        # Wait for command queue space
        ok, _ = await self.h.poll_field(
            self.base + PIOCONTROL_PIO_INTR_STATUS_REG_ADDR, PioIntrStatus, "cmd_queue_ready_stat"
        )
        if not ok:
            self.h.log.error("rstact: timeout waiting for command queue ready")
            return False, 0

        # Immediate descriptor with defining byte:
        # dtt = 5 means: defining byte present, 0 data bytes (data_length = dtt - 5 = 0)
        cmd_lo = (
            (1 << 0)  # attr = 1 (ImmediateDataTransfer)
            | (CCC_RSTACT << 7)  # cmd = 0x9A (Direct RSTACT)
            | (1 << 15)  # cp = 1 (command present)
            | (dat_idx << 16)  # dev_idx
            | (5 << 23)  # dtt = 5 (defining byte, 0 data bytes)
            | (0 << 29)  # rnw = 0 (write)
            | (1 << 30)  # wroc = 1
            | (1 << 31)  # toc = 1
        )
        # Defining byte goes in def_or_data_byte1 position (bits [7:0] of cmd_hi)
        cmd_hi = defining_byte & 0xFF

        await self.h.write(self.base + PIOCONTROL_COMMAND_PORT_REG_ADDR, cmd_lo)
        await self.h.write(self.base + PIOCONTROL_COMMAND_PORT_REG_ADDR, cmd_hi)

        self.h.log.debug(f"rstact: command issued (cmd_lo=0x{cmd_lo:08X}, cmd_hi=0x{cmd_hi:08X})")

        # Wait for response
        ok, _ = await self.h.poll_field(
            self.base + PIOCONTROL_PIO_INTR_STATUS_REG_ADDR, PioIntrStatus, "resp_ready_stat"
        )
        if not ok:
            self.h.log.error("rstact: timeout waiting for response")
            return False, 0

        # Read response descriptor
        resp = await self.h.read(self.base + PIOCONTROL_RESPONSE_PORT_REG_ADDR)
        err_status = (resp >> 28) & 0xF
        self.h.log.debug(f"rstact: response=0x{resp:08X}, err={err_status}")

        if err_status != 0:
            self.h.log.error(f"rstact: transfer error, err_status={err_status}")
            return False, resp

        return True, resp


class I3CTarget:
    """I3C Target initialization and transaction handling."""

    def __init__(self, base_addr, helper):
        self.base = base_addr
        self.h = helper
        self.rx_thld = 1
        self.tx_thld = 1

    async def initialize(self, static_addr):
        """Target init: set static addr, enable SETDASA and private xact using ctypes."""
        # Target PHY/ACK path is gated on HC_CONTROL.BUS_ENABLE (configuration.sv
        # phy_en); without it the target ignores the bus and NACKs the address header.
        hc_ctrl = HcControl()
        hc_ctrl.f.bus_enable = 1
        await self.h.write(self.base + I3CBASE_HC_CONTROL_REG_ADDR, hc_ctrl.val)

        # Set STBY_CR_DEVICE_ADDR with static address valid
        addr_reg = StbyCrDeviceAddr()
        addr_reg.f.static_addr = static_addr
        addr_reg.f.static_addr_valid = 1
        await self.h.write(
            self.base + I3C_EC_STDBYCTRLMODE_STBY_CR_DEVICE_ADDR_REG_ADDR, addr_reg.val
        )

        # Configure STBY_CR_CONTROL
        ctrl = StbyCrControl()
        ctrl.f.stby_cr_enable_init = 0b10  # SCM_RUNNING
        ctrl.f.daa_setdasa_enable = 1
        ctrl.f.target_xact_enable = 1
        await self.h.write(self.base + I3C_EC_STDBYCTRLMODE_STBY_CR_CONTROL_REG_ADDR, ctrl.val)

        # Enable TTI interrupts for data thresholds, descriptor thresholds, TX completion, and IBI
        TTI_TX_DATA_THLD_STAT_EN = 1 << TTI_INTR_TX_DATA_THLD_BIT
        TTI_RX_DATA_THLD_STAT_EN = 1 << TTI_INTR_RX_DATA_THLD_BIT
        TTI_TX_DESC_THLD_STAT_EN = 1 << TTI_INTR_TX_DESC_THLD_BIT
        TTI_RX_DESC_THLD_STAT_EN = 1 << TTI_INTR_RX_DESC_THLD_BIT
        TTI_IBI_THLD_STAT_EN = 1 << TTI_INTR_IBI_THLD_BIT
        TTI_IBI_DONE_EN = 1 << TTI_INTR_IBI_DONE_BIT
        TTI_TX_DESC_COMPLETE_EN = 1 << TTI_INTR_TX_DESC_COMPLETE_BIT
        tti_intr_en = (
            TTI_TX_DATA_THLD_STAT_EN
            | TTI_RX_DATA_THLD_STAT_EN
            | TTI_TX_DESC_THLD_STAT_EN
            | TTI_RX_DESC_THLD_STAT_EN
            | TTI_IBI_THLD_STAT_EN
            | TTI_IBI_DONE_EN
            | TTI_TX_DESC_COMPLETE_EN
        )
        await self.h.write(self.base + I3C_EC_TTI_INTERRUPT_ENABLE_REG_ADDR, tti_intr_en)

    async def configure_timing_od_i3c(self):
        """Program the target's open-drain bus timing (must match the controller's;
        without the OD edge/START-STOP timings the target mis-times its ACK/SDA)."""
        await self.h.write(self.base + I3C_EC_SOCMGMTIF_T_R_REG_REG_ADDR, 0)
        await self.h.write(self.base + I3C_EC_SOCMGMTIF_T_F_REG_REG_ADDR, 0)
        await self.h.write(self.base + I3C_EC_SOCMGMTIF_T_SU_DAT_REG_REG_ADDR, 2)
        await self.h.write(self.base + I3C_EC_SOCMGMTIF_T_HD_DAT_REG_REG_ADDR, 2)
        await self.h.write(self.base + I3C_EC_SOCMGMTIF_T_HIGH_REG_REG_ADDR, 14)
        await self.h.write(self.base + I3C_EC_SOCMGMTIF_T_HIGH_OD_REG_REG_ADDR, 20)
        await self.h.write(self.base + I3C_EC_SOCMGMTIF_T_HIGH_INIT_OD_REG_REG_ADDR, 70)
        await self.h.write(self.base + I3C_EC_SOCMGMTIF_T_LOW_REG_REG_ADDR, 14)
        await self.h.write(self.base + I3C_EC_SOCMGMTIF_T_LOW_OD_REG_REG_ADDR, 70)
        await self.h.write(self.base + I3C_EC_SOCMGMTIF_T_HD_STA_REG_REG_ADDR, 13)
        await self.h.write(self.base + I3C_EC_SOCMGMTIF_T_SU_STA_REG_REG_ADDR, 9)
        await self.h.write(self.base + I3C_EC_SOCMGMTIF_T_SU_STO_REG_REG_ADDR, 8)
        await self.h.write(self.base + I3C_EC_SOCMGMTIF_T_HD_RSTA_REG_REG_ADDR, 9)
        await self.h.write(self.base + I3C_EC_SOCMGMTIF_T_DS_OD_REG_REG_ADDR, 24)
        await self.h.write(self.base + I3C_EC_SOCMGMTIF_T_FREE_REG_REG_ADDR, 13)
        await self.h.write(self.base + I3C_EC_SOCMGMTIF_T_AVAL_REG_REG_ADDR, 333)
        await self.h.write(self.base + I3C_EC_SOCMGMTIF_T_IDLE_REG_REG_ADDR, 66600)

    async def configure_timing_pp(self):
        """Retain call-site compatibility; this core has no dedicated PP timing."""
        return

    async def configure_thresholds(
        self, tx_buf=1, tx_start=0, rx_buf=1, rx_start=0, tx_desc=1, rx_desc=1
    ):
        """Configure TTI_DATA_BUFFER_THLD_CTRL and TTI_QUEUE_THLD_CTRL using ctypes.

        Data buffer threshold = 2^(val+1) entries.
        Queue threshold = val+1 entries.
        """
        self.tx_thld = tx_buf
        self.rx_thld = rx_buf

        # Configure TTI_DATA_BUFFER_THLD_CTRL
        thld = TtiDataBufferThldCtrl()
        thld.f.tx_data_thld = tx_buf
        thld.f.rx_data_thld = rx_buf
        thld.f.tx_start_thld = tx_start
        thld.f.rx_start_thld = rx_start
        await self.h.write(self.base + I3C_EC_TTI_DATA_BUFFER_THLD_CTRL_REG_ADDR, thld.val)

        # Configure TTI_QUEUE_THLD_CTRL (controls TX_DESC_THLD_STAT and RX_DESC_THLD_STAT)
        queue_thld = TtiQueueThldCtrl()
        queue_thld.f.tx_desc_thld = tx_desc
        queue_thld.f.rx_desc_thld = rx_desc
        await self.h.write(self.base + I3C_EC_TTI_QUEUE_THLD_CTRL_REG_ADDR, queue_thld.val)

    async def enable_ibi_mode(self):
        """Enable IBI (In-Band Interrupt) mode on target.

        Sets TTI_CONTROL.IBI_EN bit to enable IBI transmission capability.

        IBI_EN resets asserted, so this call is normally idempotent. Use
        disable_ibi_mode() to suppress IBI generation.
        """
        # Read TTI_CONTROL register
        tti_ctrl_val = await self.h.read(self.base + I3C_EC_TTI_CONTROL_REG_ADDR)

        # Set IBI_EN bit
        IBI_EN_BIT = 1 << TTI_CTRL_IBI_EN_BIT
        tti_ctrl_val |= IBI_EN_BIT

        await self.h.write(self.base + I3C_EC_TTI_CONTROL_REG_ADDR, tti_ctrl_val)
        self.h.log.info("Target IBI mode enabled")

    async def disable_ibi_mode(self):
        """Disable IBI generation on the target and return the read-back ibi_en bit.

        Clears TTI_CONTROL.IBI_EN. Needed because that bit is SET at reset
        (TTI_CONTROL reset value 0x1400), so simply not calling enable_ibi_mode()
        leaves IBI generation ENABLED. The RTL gates transmission on this bit.

        Returns:
            int: TTI_CONTROL.ibi_en as read back, so the caller can assert it is 0.
        """
        IBI_EN_BIT = 1 << TTI_CTRL_IBI_EN_BIT
        tti_ctrl_val = await self.h.read(self.base + I3C_EC_TTI_CONTROL_REG_ADDR)
        await self.h.write(self.base + I3C_EC_TTI_CONTROL_REG_ADDR, tti_ctrl_val & ~IBI_EN_BIT)

        readback = await self.h.read(self.base + I3C_EC_TTI_CONTROL_REG_ADDR)
        ibi_en = (readback >> TTI_CTRL_IBI_EN_BIT) & 0x1
        self.h.log.info(f"Target IBI mode disabled: TTI_CONTROL=0x{readback:08X}, ibi_en={ibi_en}")
        return ibi_en

    async def write_ibi(self, mdb, payload_bytes):
        """Write IBI descriptor and payload to target's IBI queue.

        Args:
            mdb: Mandatory Data Byte (8-bit value, typically encodes IBI type)
            payload_bytes: List of payload bytes (0 to max_ibi_payload_len)

        Returns:
            success (bool)
        """
        bytes_per_entry = 4
        payload_len = len(payload_bytes)

        # Validate payload length
        if payload_len > 255:
            self.h.log.error(f"write_ibi: payload too long ({payload_len} > 255)")
            return False

        # Build IBI descriptor header
        ibi_header = (mdb << 24) | (payload_len & 0xFF)

        self.h.log.debug(
            f"write_ibi: mdb=0x{mdb:02X}, payload_len={payload_len}, header=0x{ibi_header:08X}"
        )

        # Wait for IBI queue to have space via QUEUE_STATUS (not IBI_THLD_STAT —
        # that interrupt is not a reliable ready signal on this core).
        ok, _ = await self.h.poll_field_clear(
            self.base + I3C_EC_TTI_QUEUE_STATUS_REG_ADDR,
            TtiQueueStatus,
            "ibi_queue_full",
            max_polls=1000,
            interval=10,
        )
        if not ok:
            self.h.log.error("write_ibi: timeout waiting for IBI queue space")
            return False

        # Write IBI descriptor header
        await self.h.write(self.base + I3C_EC_TTI_IBI_PORT_REG_ADDR, ibi_header)
        self.h.log.debug("write_ibi: wrote descriptor header")

        # Write payload data if present
        if payload_len > 0:
            bytes_written = 0
            while bytes_written < payload_len:
                chunk = payload_bytes[bytes_written : bytes_written + bytes_per_entry]
                word = self.h.pack_bytes(chunk)
                await self.h.write(self.base + I3C_EC_TTI_IBI_PORT_REG_ADDR, word)
                self.h.log.debug(f"write_ibi: wrote payload chunk {[f'0x{b:02X}' for b in chunk]}")
                bytes_written += len(chunk)

        self.h.log.info(f"Target IBI sent: mdb=0x{mdb:02X}, payload_len={payload_len}")
        return True

    async def wait_ibi_done(self, max_polls=10000, interval=10):
        """Wait for target's IBI transmission to complete.

        Returns:
            (success, last_ibi_status)

        Polls TTI_INTERRUPT_STATUS.IBI_DONE_STAT (bit 13) until set.
        Also returns TTI_STATUS.LAST_IBI_STATUS for diagnostic info.
        """
        self.h.log.debug("Waiting for target IBI transmission complete...")

        TTI_IBI_DONE_STAT = 1 << TTI_INTR_IBI_DONE_BIT
        for _ in range(max_polls):
            tgt_intr_status = await self.h.read(self.base + I3C_EC_TTI_INTERRUPT_STATUS_REG_ADDR)
            if tgt_intr_status & TTI_IBI_DONE_STAT:
                # Read TTI_STATUS for diagnostics
                tgt_status = await self.h.read(self.base + I3C_EC_TTI_STATUS_REG_ADDR)
                last_ibi_status = (tgt_status >> 12) & 0x7  # Bits [14:12]
                return True, last_ibi_status
            await ClockCycles(self.h.dut.clk, interval)

        self.h.log.error(
            f"wait_ibi_done: timeout after {max_polls} polls (interval={interval} cycles)"
        )
        return False, 0

    async def wait_dynamic_addr(self, max_polls=1000):
        """Wait for dynamic address assignment using ctypes."""
        for _ in range(max_polls):
            addr_reg = await self.h.read_into(
                self.base + I3C_EC_STDBYCTRLMODE_STBY_CR_DEVICE_ADDR_REG_ADDR, StbyCrDeviceAddr
            )
            if addr_reg.f.dynamic_addr_valid:
                return True, addr_reg.f.dynamic_addr
            await ClockCycles(self.h.dut.clk, 10)
        return False, 0

    async def wait_dynamic_addr_cleared(self, max_polls=1000):
        """Wait until DYNAMIC_ADDR_VALID clears (e.g. after Broadcast RSTDAA)."""
        for _ in range(max_polls):
            addr_reg = await self.h.read_into(
                self.base + I3C_EC_STDBYCTRLMODE_STBY_CR_DEVICE_ADDR_REG_ADDR, StbyCrDeviceAddr
            )
            if not addr_reg.f.dynamic_addr_valid:
                return True
            await ClockCycles(self.h.dut.clk, 10)
        self.h.log.error(
            f"wait_dynamic_addr_cleared: DYNAMIC_ADDR_VALID still set after {max_polls} polls"
        )
        return False


# Register offsets are imported from generated map symbols rather than copied,
# keeping the generated map authoritative across register regeneration.

I3CBASE_INTR_STATUS_REG_ADDR = _csr.I3C_CSR_0__I3CBASE_INTR_STATUS_REG_ADDR
I3CBASE_INTR_STATUS_ENABLE_REG_ADDR = _csr.I3C_CSR_0__I3CBASE_INTR_STATUS_ENABLE_REG_ADDR
I3CBASE_INTR_SIGNAL_ENABLE_REG_ADDR = _csr.I3C_CSR_0__I3CBASE_INTR_SIGNAL_ENABLE_REG_ADDR
I3CBASE_INTR_FORCE_REG_ADDR = _csr.I3C_CSR_0__I3CBASE_INTR_FORCE_REG_ADDR
I3CBASE_RESET_CONTROL_REG_ADDR = _csr.I3C_CSR_0__I3CBASE_RESET_CONTROL_REG_ADDR
PIOCONTROL_ALT_QUEUE_SIZE_REG_ADDR = _csr.I3C_CSR_0__PIOCONTROL_ALT_QUEUE_SIZE_REG_ADDR
I3C_EC_TTI_DATA_QUEUE_DEPTH_REG_ADDR = _csr.I3C_CSR_0__I3C_EC_TTI_DATA_QUEUE_DEPTH_REG_ADDR
I3C_EC_TTI_DESC_QUEUE_DEPTH_REG_ADDR = _csr.I3C_CSR_0__I3C_EC_TTI_DESC_QUEUE_DEPTH_REG_ADDR

_BASEREGS = "BASEREGS_"

# INTR_STATUS has no stable name suffix (the generated identifier embeds a hash
# per field), so resolve it by a substring that is unique across the map.
IntrStatus = _union_by_contains("_INTR_STATUS_HC_ERR_CMD_SEQ_TIMEOUT_STAT")
IntrStatusEnable = _union_by_suffix("INTR_STATUS_ENABLE", _BASEREGS)
IntrSignalEnable = _union_by_suffix("INTR_SIGNAL_ENABLE", _BASEREGS)
IntrForce = _union_by_suffix("INTR_FORCE", _BASEREGS)
ResetControl = _union_by_suffix("RESET_CONTROL", _BASEREGS)
QueueSize = _union_by_suffix("QUEUE_SIZE", _PIO, exclude="ALT_")
AltQueueSize = _union_by_suffix("ALT_QUEUE_SIZE", _PIO)
TtiDataQueueDepth = _union_by_suffix("DATA_QUEUE_DEPTH", _TTI)
TtiDescQueueDepth = _union_by_suffix("DESC_QUEUE_DEPTH", _TTI)

# BASE INTR_STATUS / _ENABLE / _SIGNAL_ENABLE / _FORCE bit positions
# (HCI 7.4.7 Table 23 .. 7.4.10 Table 26), derived from the generated map so a
# regeneration that moves a field breaks loudly instead of silently masking the
# wrong bit.
HC_INTERNAL_ERR_STAT_BIT = _bit(IntrStatus, "hc_internal_err_stat")
HC_SEQ_CANCEL_STAT_BIT = _bit(IntrStatus, "hc_seq_cancel_stat")
HC_WARN_CMD_SEQ_STALL_STAT_BIT = _bit(IntrStatus, "hc_warn_cmd_seq_stall_stat")
HC_ERR_CMD_SEQ_TIMEOUT_STAT_BIT = _bit(IntrStatus, "hc_err_cmd_seq_timeout_stat")
SCHED_CMD_MISSED_TICK_STAT_BIT = _bit(IntrStatus, "sched_cmd_missed_tick_stat")

# Ordered (name, bit) pairs for the five general Host Controller interrupt
# events; the interrupt decode walk iterates exactly this set.
HC_INTR_BITS = (
    ("HC_INTERNAL_ERR_STAT", HC_INTERNAL_ERR_STAT_BIT),
    ("HC_SEQ_CANCEL_STAT", HC_SEQ_CANCEL_STAT_BIT),
    ("HC_WARN_CMD_SEQ_STALL_STAT", HC_WARN_CMD_SEQ_STALL_STAT_BIT),
    ("HC_ERR_CMD_SEQ_TIMEOUT_STAT", HC_ERR_CMD_SEQ_TIMEOUT_STAT_BIT),
    ("SCHED_CMD_MISSED_TICK_STAT", SCHED_CMD_MISSED_TICK_STAT_BIT),
)
# Mask of the R/W bits of INTR_STATUS_ENABLE / INTR_SIGNAL_ENABLE: bits [14:10].
HC_INTR_RW_MASK = sum(1 << b for _, b in HC_INTR_BITS)

# PIO_INTR_STATUS bit positions (HCI 7.5.9 Table 45), likewise derived.
PIO_INTR_TX_THLD_BIT = _bit(PioIntrStatus, "tx_thld_stat")
PIO_INTR_RX_THLD_BIT = _bit(PioIntrStatus, "rx_thld_stat")
PIO_INTR_IBI_STATUS_THLD_BIT = _bit(PioIntrStatus, "ibi_status_thld_stat")
PIO_INTR_CMD_QUEUE_READY_BIT = _bit(PioIntrStatus, "cmd_queue_ready_stat")
PIO_INTR_RESP_READY_BIT = _bit(PioIntrStatus, "resp_ready_stat")
PIO_INTR_TRANSFER_ABORT_BIT = _bit(PioIntrStatus, "transfer_abort_stat")
PIO_INTR_TRANSFER_ERR_BIT = _bit(PioIntrStatus, "transfer_err_stat")

# BASE RESET_CONTROL bit positions (queue/FIFO reset; cleanup use only).
RESET_CTRL_CMD_QUEUE_RST_BIT = _bit(ResetControl, "cmd_queue_rst")
RESET_CTRL_RESP_QUEUE_RST_BIT = _bit(ResetControl, "resp_queue_rst")
RESET_CTRL_TX_FIFO_RST_BIT = _bit(ResetControl, "tx_fifo_rst")
RESET_CTRL_RX_FIFO_RST_BIT = _bit(ResetControl, "rx_fifo_rst")

# Response Descriptor ERR_STATUS field (HCI Table 146 / TCRI 6.4.1 Table 1).
RESP_ERR_STATUS_SHIFT = 28
RESP_ERR_STATUS_MASK = 0xF
RESP_ERR_SUCCESS = 0x0
RESP_ERR_NACK = 0x5
