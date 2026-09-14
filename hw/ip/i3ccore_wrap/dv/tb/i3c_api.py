# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""
I3C Test API - Minimal modular Python API for I3CCore I3C tests

This module provides reusable classes for initializing and operating I3C
controller and target devices using cocotb and AXI-Lite.

Usage:
    from i3c_api import I3CHelper, I3CController, I3CTarget

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

from cocotb.triggers import ClockCycles

# CCC Command Codes (Direct GET commands)
CCC_GETBCR = 0x8E  # Get Bus Characteristics Register
CCC_GETMWL = 0x8B  # Get Max Write Length
CCC_GETMRL = 0x8C  # Get Max Read Length

# CCC Command Codes (Direct SET commands)
CCC_SETMWL = 0x89  # Set Max Write Length
CCC_SETMRL = 0x8A  # Set Max Read Length
CCC_RSTACT = 0x9A  # Direct Reset Action

# Add path to register headers
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../data/registers/py_headers"))

from I3CCSR_reg import (
    # DAT memory
    DAT_MEM_BASE_ADDR,
    I3C_EC_SOCMGMTIF_T_AVAL_REG_REG_ADDR,
    I3C_EC_SOCMGMTIF_T_F_PP_REG_REG_ADDR,
    I3C_EC_SOCMGMTIF_T_F_REG_REG_ADDR,
    I3C_EC_SOCMGMTIF_T_FREE_REG_REG_ADDR,
    I3C_EC_SOCMGMTIF_T_HD_DAT_REG_REG_ADDR,
    I3C_EC_SOCMGMTIF_T_HD_PP_REG_REG_ADDR,
    I3C_EC_SOCMGMTIF_T_HD_STA_REG_REG_ADDR,
    I3C_EC_SOCMGMTIF_T_HIGH_PP_REG_REG_ADDR,
    I3C_EC_SOCMGMTIF_T_HIGH_REG_REG_ADDR,
    I3C_EC_SOCMGMTIF_T_IDLE_REG_REG_ADDR,
    I3C_EC_SOCMGMTIF_T_LOW_PP_REG_REG_ADDR,
    I3C_EC_SOCMGMTIF_T_LOW_REG_REG_ADDR,
    # Timing registers (PP)
    I3C_EC_SOCMGMTIF_T_R_PP_REG_REG_ADDR,
    # Timing registers (OD)
    I3C_EC_SOCMGMTIF_T_R_REG_REG_ADDR,
    I3C_EC_SOCMGMTIF_T_SU_DAT_REG_REG_ADDR,
    I3C_EC_SOCMGMTIF_T_SU_PP_REG_REG_ADDR,
    I3C_EC_SOCMGMTIF_T_SU_STA_REG_REG_ADDR,
    I3C_EC_SOCMGMTIF_T_SU_STO_REG_REG_ADDR,
    # Standby controller mode
    I3C_EC_STDBYCTRLMODE_STBY_CR_CONTROL_REG_ADDR,
    I3C_EC_STDBYCTRLMODE_STBY_CR_DEVICE_ADDR_REG_ADDR,
    I3C_EC_TTI_CONTROL_REG_ADDR,
    I3C_EC_TTI_DATA_BUFFER_THLD_CTRL_REG_ADDR,
    I3C_EC_TTI_IBI_PORT_REG_ADDR,
    I3C_EC_TTI_INTERRUPT_ENABLE_REG_ADDR,
    # TTI (target)
    I3C_EC_TTI_INTERRUPT_STATUS_REG_ADDR,
    I3C_EC_TTI_QUEUE_THLD_CTRL_REG_ADDR,
    I3C_EC_TTI_RX_DATA_PORT_REG_ADDR,
    I3C_EC_TTI_RX_DESC_QUEUE_PORT_REG_ADDR,
    I3C_EC_TTI_STATUS_REG_ADDR,
    I3C_EC_TTI_TX_DATA_PORT_REG_ADDR,
    I3C_EC_TTI_TX_DESC_QUEUE_PORT_REG_ADDR,
    # Base registers
    I3CBASE_HC_CONTROL_REG_ADDR,
    # PIO registers
    PIOCONTROL_COMMAND_PORT_REG_ADDR,
    PIOCONTROL_DATA_BUFFER_THLD_CTRL_REG_ADDR,
    # IBI registers
    PIOCONTROL_IBI_PORT_REG_ADDR,
    PIOCONTROL_PIO_CONTROL_REG_ADDR,
    PIOCONTROL_PIO_INTR_SIGNAL_ENABLE_REG_ADDR,
    PIOCONTROL_PIO_INTR_STATUS_ENABLE_REG_ADDR,
    PIOCONTROL_PIO_INTR_STATUS_REG_ADDR,
    PIOCONTROL_QUEUE_SIZE_REG_ADDR,
    PIOCONTROL_QUEUE_THLD_CTRL_REG_ADDR,
    PIOCONTROL_RESPONSE_PORT_REG_ADDR,
    PIOCONTROL_RX_DATA_PORT_REG_ADDR,
    PIOCONTROL_TX_DATA_PORT_REG_ADDR,
    # Ctypes Union classes for bitfield access
    BASEREGS_PIO_OFFSET_80_EXT_OFFSET_100_DAT_TABLE_SIZE_F_DAT_OFFSET_300_DCT_TABLE_SIZE_F_DCT_OFFSET_400_MIPI_COMMANDS_35_HC_CONTROL_reg_u,
    PIOREGS_CMD_FIFO_SIZE_8_RESP_FIFO_SIZE_8_IBI_FIFO_SIZE_8_TX_FIFO_SIZE_8_RX_FIFO_SIZE_8_EXT_IBI_SIZE_0_DATA_BUFFER_THLD_CTRL_reg_u,
    PIOREGS_CMD_FIFO_SIZE_8_RESP_FIFO_SIZE_8_IBI_FIFO_SIZE_8_TX_FIFO_SIZE_8_RX_FIFO_SIZE_8_EXT_IBI_SIZE_0_PIO_CONTROL_reg_u,
    PIOREGS_CMD_FIFO_SIZE_8_RESP_FIFO_SIZE_8_IBI_FIFO_SIZE_8_TX_FIFO_SIZE_8_RX_FIFO_SIZE_8_EXT_IBI_SIZE_0_PIO_INTR_FORCE_reg_u,
    PIOREGS_CMD_FIFO_SIZE_8_RESP_FIFO_SIZE_8_IBI_FIFO_SIZE_8_TX_FIFO_SIZE_8_RX_FIFO_SIZE_8_EXT_IBI_SIZE_0_PIO_INTR_SIGNAL_ENABLE_reg_u,
    PIOREGS_CMD_FIFO_SIZE_8_RESP_FIFO_SIZE_8_IBI_FIFO_SIZE_8_TX_FIFO_SIZE_8_RX_FIFO_SIZE_8_EXT_IBI_SIZE_0_PIO_INTR_STATUS_CMD_QUEUE_READY_STAT_d0716a40_IBI_STATUS_THLD_STAT_a69a4555_RESP_READY_STAT_976af25d_RX_THLD_STAT_0f2071bf_TRANSFER_ABORT_STAT_1fe261ad_TRANSFER_ERR_STAT_8815d17d_TX_THLD_STAT_9fe979f6_reg_u,
    PIOREGS_CMD_FIFO_SIZE_8_RESP_FIFO_SIZE_8_IBI_FIFO_SIZE_8_TX_FIFO_SIZE_8_RX_FIFO_SIZE_8_EXT_IBI_SIZE_0_PIO_INTR_STATUS_ENABLE_reg_u,
    PIOREGS_CMD_FIFO_SIZE_8_RESP_FIFO_SIZE_8_IBI_FIFO_SIZE_8_TX_FIFO_SIZE_8_RX_FIFO_SIZE_8_EXT_IBI_SIZE_0_QUEUE_THLD_CTRL_reg_u,
    STANDBYCONTROLLERMODEREGISTERS_PID_HI_RESET_7FFF_PID_LO_RESET_5A00A5_VIRTUAL_PID_HI_RESET_7FFF_VIRTUAL_PID_LO_RESET_5A10A5_STBY_CR_CONTROL_reg_u,
    STANDBYCONTROLLERMODEREGISTERS_PID_HI_RESET_7FFF_PID_LO_RESET_5A00A5_VIRTUAL_PID_HI_RESET_7FFF_VIRTUAL_PID_LO_RESET_5A10A5_STBY_CR_DEVICE_ADDR_reg_u,
    TARGETTRANSACTIONINTERFACEREGISTERS_RX_DESC_FIFO_SIZE_8_TX_DESC_FIFO_SIZE_8_RX_FIFO_SIZE_8_TX_FIFO_SIZE_8_IBI_FIFO_SIZE_8_DATA_BUFFER_THLD_CTRL_reg_u,
    TARGETTRANSACTIONINTERFACEREGISTERS_RX_DESC_FIFO_SIZE_8_TX_DESC_FIFO_SIZE_8_RX_FIFO_SIZE_8_TX_FIFO_SIZE_8_IBI_FIFO_SIZE_8_INTERRUPT_STATUS_reg_u,
    TARGETTRANSACTIONINTERFACEREGISTERS_RX_DESC_FIFO_SIZE_8_TX_DESC_FIFO_SIZE_8_RX_FIFO_SIZE_8_TX_FIFO_SIZE_8_IBI_FIFO_SIZE_8_QUEUE_THLD_CTRL_reg_u,
)

# Short aliases for ctypes Union classes
HcControl = BASEREGS_PIO_OFFSET_80_EXT_OFFSET_100_DAT_TABLE_SIZE_F_DAT_OFFSET_300_DCT_TABLE_SIZE_F_DCT_OFFSET_400_MIPI_COMMANDS_35_HC_CONTROL_reg_u
PioControl = PIOREGS_CMD_FIFO_SIZE_8_RESP_FIFO_SIZE_8_IBI_FIFO_SIZE_8_TX_FIFO_SIZE_8_RX_FIFO_SIZE_8_EXT_IBI_SIZE_0_PIO_CONTROL_reg_u
PioIntrStatus = PIOREGS_CMD_FIFO_SIZE_8_RESP_FIFO_SIZE_8_IBI_FIFO_SIZE_8_TX_FIFO_SIZE_8_RX_FIFO_SIZE_8_EXT_IBI_SIZE_0_PIO_INTR_STATUS_CMD_QUEUE_READY_STAT_d0716a40_IBI_STATUS_THLD_STAT_a69a4555_RESP_READY_STAT_976af25d_RX_THLD_STAT_0f2071bf_TRANSFER_ABORT_STAT_1fe261ad_TRANSFER_ERR_STAT_8815d17d_TX_THLD_STAT_9fe979f6_reg_u
PioIntrStatusEnable = PIOREGS_CMD_FIFO_SIZE_8_RESP_FIFO_SIZE_8_IBI_FIFO_SIZE_8_TX_FIFO_SIZE_8_RX_FIFO_SIZE_8_EXT_IBI_SIZE_0_PIO_INTR_STATUS_ENABLE_reg_u
PioIntrSignalEnable = PIOREGS_CMD_FIFO_SIZE_8_RESP_FIFO_SIZE_8_IBI_FIFO_SIZE_8_TX_FIFO_SIZE_8_RX_FIFO_SIZE_8_EXT_IBI_SIZE_0_PIO_INTR_SIGNAL_ENABLE_reg_u
PioIntrForce = PIOREGS_CMD_FIFO_SIZE_8_RESP_FIFO_SIZE_8_IBI_FIFO_SIZE_8_TX_FIFO_SIZE_8_RX_FIFO_SIZE_8_EXT_IBI_SIZE_0_PIO_INTR_FORCE_reg_u
DataBufferThldCtrl = PIOREGS_CMD_FIFO_SIZE_8_RESP_FIFO_SIZE_8_IBI_FIFO_SIZE_8_TX_FIFO_SIZE_8_RX_FIFO_SIZE_8_EXT_IBI_SIZE_0_DATA_BUFFER_THLD_CTRL_reg_u
QueueThldCtrl = PIOREGS_CMD_FIFO_SIZE_8_RESP_FIFO_SIZE_8_IBI_FIFO_SIZE_8_TX_FIFO_SIZE_8_RX_FIFO_SIZE_8_EXT_IBI_SIZE_0_QUEUE_THLD_CTRL_reg_u
StbyCrControl = STANDBYCONTROLLERMODEREGISTERS_PID_HI_RESET_7FFF_PID_LO_RESET_5A00A5_VIRTUAL_PID_HI_RESET_7FFF_VIRTUAL_PID_LO_RESET_5A10A5_STBY_CR_CONTROL_reg_u
StbyCrDeviceAddr = STANDBYCONTROLLERMODEREGISTERS_PID_HI_RESET_7FFF_PID_LO_RESET_5A00A5_VIRTUAL_PID_HI_RESET_7FFF_VIRTUAL_PID_LO_RESET_5A10A5_STBY_CR_DEVICE_ADDR_reg_u
TtiDataBufferThldCtrl = TARGETTRANSACTIONINTERFACEREGISTERS_RX_DESC_FIFO_SIZE_8_TX_DESC_FIFO_SIZE_8_RX_FIFO_SIZE_8_TX_FIFO_SIZE_8_IBI_FIFO_SIZE_8_DATA_BUFFER_THLD_CTRL_reg_u
TtiQueueThldCtrl = TARGETTRANSACTIONINTERFACEREGISTERS_RX_DESC_FIFO_SIZE_8_TX_DESC_FIFO_SIZE_8_RX_FIFO_SIZE_8_TX_FIFO_SIZE_8_IBI_FIFO_SIZE_8_QUEUE_THLD_CTRL_reg_u
TtiIntrStatus = TARGETTRANSACTIONINTERFACEREGISTERS_RX_DESC_FIFO_SIZE_8_TX_DESC_FIFO_SIZE_8_RX_FIFO_SIZE_8_TX_FIFO_SIZE_8_IBI_FIFO_SIZE_8_INTERRUPT_STATUS_reg_u

# TTI Interrupt Status bit positions (from target_transaction_interface.rdl)
# Used for bit-testing TTI_INTERRUPT_STATUS register
TTI_INTR_TX_DATA_THLD_BIT = 8  # tx_data_thld_stat
TTI_INTR_RX_DATA_THLD_BIT = 9  # rx_data_thld_stat
TTI_INTR_TX_DESC_THLD_BIT = 10  # tx_desc_thld_stat
TTI_INTR_RX_DESC_THLD_BIT = 11  # rx_desc_thld_stat
TTI_INTR_IBI_THLD_BIT = 12  # ibi_thld_stat
TTI_INTR_IBI_DONE_BIT = 13  # ibi_done
TTI_INTR_TX_DESC_COMPLETE_BIT = 26  # tx_desc_complete

# TTI Control register bit positions
TTI_CTRL_IBI_EN_BIT = 12  # ibi_en - IBI transmission enable


class I3CHelper:
    """Low-level register I/O wrapper for I3C registers via AXI-Lite."""

    def __init__(self, axi_master, dut, log=None):
        self.axi = axi_master
        self.dut = dut
        self.log = log or logging.getLogger("i3c_api")

    async def write(self, addr, data):
        """Write 32-bit value (can pass reg.val from ctypes Union)."""
        await self.axi.write_dword(addr, data)

    async def read(self, addr):
        """Read 32-bit value from register."""
        return await self.axi.read_dword(addr)

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

        # 3. Set Active Controller Mode (ACM_INIT) - required to drive the bus
        stby_cr = StbyCrControl()
        stby_cr.f.stby_cr_enable_init = 0b01  # ACM_INIT = Active Controller Mode
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
        """Configure open-drain timing for I3C (hardcoded values)."""
        await self.h.write(self.base + I3C_EC_SOCMGMTIF_T_HIGH_REG_REG_ADDR, 10)
        await self.h.write(self.base + I3C_EC_SOCMGMTIF_T_LOW_REG_REG_ADDR, 10)
        await self.h.write(self.base + I3C_EC_SOCMGMTIF_T_R_REG_REG_ADDR, 8)
        await self.h.write(self.base + I3C_EC_SOCMGMTIF_T_F_REG_REG_ADDR, 2)
        await self.h.write(self.base + I3C_EC_SOCMGMTIF_T_HD_STA_REG_REG_ADDR, 5)
        await self.h.write(self.base + I3C_EC_SOCMGMTIF_T_SU_STA_REG_REG_ADDR, 5)
        await self.h.write(self.base + I3C_EC_SOCMGMTIF_T_SU_STO_REG_REG_ADDR, 5)
        await self.h.write(self.base + I3C_EC_SOCMGMTIF_T_SU_DAT_REG_REG_ADDR, 5)
        await self.h.write(self.base + I3C_EC_SOCMGMTIF_T_HD_DAT_REG_REG_ADDR, 2)
        await self.h.write(self.base + I3C_EC_SOCMGMTIF_T_FREE_REG_REG_ADDR, 500)
        # T_AVAL: Bus available time (target waits this before sending IBI)
        await self.h.write(self.base + I3C_EC_SOCMGMTIF_T_AVAL_REG_REG_ADDR, 1000)
        # T_IDLE: Bus idle time
        await self.h.write(self.base + I3C_EC_SOCMGMTIF_T_IDLE_REG_REG_ADDR, 2000)

    async def configure_timing_pp(self):
        """Configure push-pull timing (hardcoded values)."""
        await self.h.write(self.base + I3C_EC_SOCMGMTIF_T_R_PP_REG_REG_ADDR, 1)
        await self.h.write(self.base + I3C_EC_SOCMGMTIF_T_F_PP_REG_REG_ADDR, 1)
        await self.h.write(self.base + I3C_EC_SOCMGMTIF_T_HIGH_PP_REG_REG_ADDR, 3)
        await self.h.write(self.base + I3C_EC_SOCMGMTIF_T_LOW_PP_REG_REG_ADDR, 3)
        await self.h.write(self.base + I3C_EC_SOCMGMTIF_T_SU_PP_REG_REG_ADDR, 1)
        await self.h.write(self.base + I3C_EC_SOCMGMTIF_T_HD_PP_REG_REG_ADDR, 1)

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

        # Loop reading IBI status descriptors until last_status is set
        while True:
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

    async def set_dat_entry(self, idx, static_addr, dynamic_addr):
        """Write DAT entry for device address table."""
        dat_lo = (static_addr & 0x7F) | ((dynamic_addr & 0x7F) << 16)
        dat_hi = 0
        await self.h.write(self.base + DAT_MEM_BASE_ADDR + idx * 8, dat_lo)
        await self.h.write(self.base + DAT_MEM_BASE_ADDR + idx * 8 + 4, dat_hi)

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

    async def private_write(self, data_bytes, target, dat_idx=0, bytes_per_entry=4):
        """
        Private write with interleaved target RX drain.
        Returns (success, response, rx_data).

        Args:
            data_bytes: Data to write
            target: I3CTarget instance
            dat_idx: DAT index for target
            bytes_per_entry: Bytes per FIFO entry (default 4, matches TtiRxDataWidth=32)
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
            self.h.log.warning("private_write: timeout waiting for command queue ready")

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
        loop_count = 0

        # Loop until controller response is ready
        # During the loop: write TX data and drain target RX data when threshold interrupts fire
        while True:
            loop_count += 1
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
                # Read rx_entries_per_interrupt entries
                for entry_idx in range(rx_entries_per_interrupt):
                    word = await self.h.read(target.base + I3C_EC_TTI_RX_DATA_PORT_REG_ADDR)
                    unpacked = self.h.unpack_bytes(word, bytes_per_entry)
                    self.h.log.debug(
                        f"private_write: RX entry[{bytes_read // 4 + entry_idx}] word=0x{word:08X} -> {[f'0x{b:02X}' for b in unpacked]}"
                    )
                    rx_data.extend(unpacked)
                bytes_read += rx_bytes_per_interrupt
                self.h.log.debug(
                    f"private_write: drained {rx_bytes_per_interrupt} bytes from target RX, total={len(rx_data)}"
                )

            await ClockCycles(self.h.dut.clk, 10)

        # Read controller response descriptor
        resp = await self.h.read(self.base + PIOCONTROL_RESPONSE_PORT_REG_ADDR)
        resp_data_length = resp & 0xFFFF
        err_status = (resp >> 28) & 0xF
        self.h.log.debug(
            f"private_write: response=0x{resp:08X}, data_length={resp_data_length}, err={err_status}"
        )

        # Check for errors
        if err_status != 0:
            self.h.log.error(f"private_write: transfer error, err_status={err_status}")
            return False, resp, rx_data

        # Validate resp_data_length is 0 (all bytes have been received)
        if resp_data_length != 0:
            self.h.log.warning(
                "private_write: response descriptor data_length is not 0. This means you have not received all bytes"
            )

        # Wait for target RX descriptor to be ready (RX_DESC_THLD_STAT)
        TTI_RX_DESC_THLD_STAT = 1 << TTI_INTR_RX_DESC_THLD_BIT
        for _ in range(1000):
            tgt_status = await self.h.read(target.base + I3C_EC_TTI_INTERRUPT_STATUS_REG_ADDR)
            if tgt_status & TTI_RX_DESC_THLD_STAT:
                break
            await ClockCycles(self.h.dut.clk, 10)
        else:
            self.h.log.warning("private_write: timeout waiting for target RX descriptor")

        # Read target RX descriptor (format: {rx_error[31:20], reserved[19:16], byte_counter[15:0]})
        tgt_rx_desc = await self.h.read(target.base + I3C_EC_TTI_RX_DESC_QUEUE_PORT_REG_ADDR)
        tgt_rx_data_length = tgt_rx_desc & 0xFFFF
        tgt_rx_error = (tgt_rx_desc >> 20) & 0xFFF
        self.h.log.debug(
            f"private_write: target RX descriptor=0x{tgt_rx_desc:08X}, "
            f"data_length={tgt_rx_data_length}, error={tgt_rx_error}"
        )

        if tgt_rx_error != 0:
            self.h.log.warning(f"private_write: target RX descriptor reports error={tgt_rx_error}")

        if tgt_rx_data_length != data_len:
            self.h.log.error(
                f"private_write: read {tgt_rx_data_length} bytes, but needed to read {data_len} bytes"
            )

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

        return True, resp, rx_data[:data_len]

    async def private_read(self, target, tx_data, dat_idx=0, bytes_per_entry=4):
        """
        Private read with interleaved target TX fill and controller RX drain.
        Returns (success, response, rx_data).

        Args:
            target: I3CTarget instance
            tx_data: Data for target to transmit
            dat_idx: DAT index for target
            bytes_per_entry: Bytes per FIFO entry (default 4)
        """
        data_len = len(tx_data)

        # Controller RX threshold (in bytes)
        rx_entries_per_interrupt = 1 << (self.rx_thld + 1)
        rx_bytes_per_interrupt = rx_entries_per_interrupt * bytes_per_entry

        # Target TX threshold (in bytes)
        tx_entries_per_interrupt = 1 << (target.tx_thld + 1)
        tx_bytes_per_interrupt = tx_entries_per_interrupt * bytes_per_entry

        TTI_TX_DATA_THLD_STAT = 1 << TTI_INTR_TX_DATA_THLD_BIT
        TTI_TX_DESC_COMPLETE = 1 << TTI_INTR_TX_DESC_COMPLETE_BIT

        self.h.log.debug(
            f"private_read: {data_len} bytes, "
            f"ctrl_rx_thld={rx_bytes_per_interrupt} bytes ({rx_entries_per_interrupt} entries), "
            f"tgt_tx_thld={tx_bytes_per_interrupt} bytes ({tx_entries_per_interrupt} entries)"
        )

        # Issue read command FIRST (before filling target TX)
        cmd_lo = (0x0 << 0) | (dat_idx << 16) | (1 << 29) | (1 << 30) | (1 << 31)  # rnw=1
        cmd_hi = data_len << 16
        await self.h.write(self.base + PIOCONTROL_COMMAND_PORT_REG_ADDR, cmd_lo)
        await self.h.write(self.base + PIOCONTROL_COMMAND_PORT_REG_ADDR, cmd_hi)
        self.h.log.debug(
            f"private_read: command issued (cmd_lo=0x{cmd_lo:08X}, cmd_hi=0x{cmd_hi:08X})"
        )

        bytes_written = 0  # bytes written to target TX FIFO
        bytes_read = 0  # bytes read from controller RX FIFO
        rx_data = []
        loop_count = 0

        # Wait for target TX descriptor queue to have space
        TTI_TX_DESC_THLD_STAT = 1 << TTI_INTR_TX_DESC_THLD_BIT
        for _ in range(1000):
            tgt_status = await self.h.read(target.base + I3C_EC_TTI_INTERRUPT_STATUS_REG_ADDR)
            if tgt_status & TTI_TX_DESC_THLD_STAT:
                break
            await ClockCycles(self.h.dut.clk, 10)
        else:
            self.h.log.warning("private_read: timeout waiting for TX descriptor queue ready")

        # Write TX descriptor to target - tells target how many bytes to send
        # Format: byte_count in upper 16 bits
        tx_desc = data_len << 16
        await self.h.write(target.base + I3C_EC_TTI_TX_DESC_QUEUE_PORT_REG_ADDR, tx_desc)
        self.h.log.debug(
            f"private_read: wrote TX descriptor 0x{tx_desc:08X} (byte_count={data_len})"
        )

        # Main loop - wait for target TX_DESC_COMPLETE
        while True:
            loop_count += 1
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

            # Fill target TX FIFO when TX_DATA_THLD_STAT fires
            if bytes_written < data_len and (tgt_status & TTI_TX_DATA_THLD_STAT):
                remaining_tx = data_len - bytes_written
                chunk = min(tx_bytes_per_interrupt, remaining_tx)
                for i in range(0, chunk, bytes_per_entry):
                    word = self.h.pack_bytes(
                        tx_data[bytes_written + i : bytes_written + i + bytes_per_entry]
                    )
                    await self.h.write(target.base + I3C_EC_TTI_TX_DATA_PORT_REG_ADDR, word)
                bytes_written += chunk
                self.h.log.debug(
                    f"private_read: wrote {chunk} bytes to target TX, total={bytes_written}/{data_len}"
                )

            # Drain controller RX FIFO when RX_THLD_STAT fires
            ctrl_status = await self.h.read_into(
                self.base + PIOCONTROL_PIO_INTR_STATUS_REG_ADDR, PioIntrStatus
            )
            if ctrl_status.f.rx_thld_stat:
                self.h.log.debug(f"private_read: ctrl_status raw=0x{ctrl_status.val:08X}")

                for entry_idx in range(rx_entries_per_interrupt):
                    word = await self.h.read(self.base + PIOCONTROL_RX_DATA_PORT_REG_ADDR)
                    unpacked = self.h.unpack_bytes(word, bytes_per_entry)
                    self.h.log.debug(
                        f"private_read: RX entry[{bytes_read // 4 + entry_idx}] word=0x{word:08X} -> "
                        f"{[f'0x{b:02X}' for b in unpacked]}"
                    )
                    rx_data.extend(unpacked)
                bytes_read += rx_bytes_per_interrupt
                self.h.log.debug(
                    f"private_read: drained {rx_bytes_per_interrupt} bytes from controller RX, "
                    f"total={bytes_read}"
                )

            await ClockCycles(self.h.dut.clk, 10)

        # Wait for controller response descriptor
        ok, _ = await self.h.poll_field(
            self.base + PIOCONTROL_PIO_INTR_STATUS_REG_ADDR, PioIntrStatus, "resp_ready_stat"
        )
        if not ok:
            self.h.log.warning("private_read: timeout waiting for controller response")
            return False, 0, []

        # Read and validate controller response
        resp = await self.h.read(self.base + PIOCONTROL_RESPONSE_PORT_REG_ADDR)
        resp_data_length = resp & 0xFFFF
        err_status = (resp >> 28) & 0xF
        self.h.log.debug(
            f"private_read: response=0x{resp:08X}, data_length={resp_data_length}, err={err_status}"
        )

        if err_status != 0:
            self.h.log.error(f"private_read: transfer error, err_status={err_status}")
            return False, resp, rx_data

        # For private_read, DATA_LENGTH = bytes received (should match data_len)
        if resp_data_length != data_len:
            self.h.log.warning(
                f"private_read: DATA_LENGTH={resp_data_length} != expected {data_len}"
            )

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

        return True, resp, rx_data[:data_len]

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
            self.h.log.warning("get_ccc: timeout waiting for command queue ready")

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
            self.h.log.warning("set_ccc: timeout waiting for command queue ready")
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
                self.h.log.warning("set_ccc: timeout waiting for tx_thld_stat")

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
            self.h.log.warning("rstact: timeout waiting for command queue ready")
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
        """Configure the target's T_HD_DAT, T_AVAL and T_IDLE open-drain timing."""
        await self.h.write(self.base + I3C_EC_SOCMGMTIF_T_HD_DAT_REG_REG_ADDR, 2)
        # T_AVAL: Bus available time (target waits this before sending IBI)
        await self.h.write(self.base + I3C_EC_SOCMGMTIF_T_AVAL_REG_REG_ADDR, 1000)
        # T_IDLE: Bus idle time
        await self.h.write(self.base + I3C_EC_SOCMGMTIF_T_IDLE_REG_REG_ADDR, 2000)

    async def configure_timing_pp(self):
        """Configure push-pull timing for I3C target (same as controller)."""
        await self.h.write(self.base + I3C_EC_SOCMGMTIF_T_R_PP_REG_REG_ADDR, 1)
        await self.h.write(self.base + I3C_EC_SOCMGMTIF_T_F_PP_REG_REG_ADDR, 1)
        await self.h.write(self.base + I3C_EC_SOCMGMTIF_T_HIGH_PP_REG_REG_ADDR, 3)
        await self.h.write(self.base + I3C_EC_SOCMGMTIF_T_LOW_PP_REG_REG_ADDR, 3)
        await self.h.write(self.base + I3C_EC_SOCMGMTIF_T_SU_PP_REG_REG_ADDR, 1)
        await self.h.write(self.base + I3C_EC_SOCMGMTIF_T_HD_PP_REG_REG_ADDR, 1)

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
        """
        # Read TTI_CONTROL register
        tti_ctrl_val = await self.h.read(self.base + I3C_EC_TTI_CONTROL_REG_ADDR)

        # Set IBI_EN bit
        IBI_EN_BIT = 1 << TTI_CTRL_IBI_EN_BIT
        tti_ctrl_val |= IBI_EN_BIT

        await self.h.write(self.base + I3C_EC_TTI_CONTROL_REG_ADDR, tti_ctrl_val)
        self.h.log.info("Target IBI mode enabled")

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

        # Wait for IBI queue to have space (check TTI_IBI_THLD_STAT)
        TTI_IBI_THLD_STAT = 1 << TTI_INTR_IBI_THLD_BIT
        for _ in range(1000):
            tgt_status = await self.h.read(self.base + I3C_EC_TTI_INTERRUPT_STATUS_REG_ADDR)
            if tgt_status & TTI_IBI_THLD_STAT:
                break
            await ClockCycles(self.h.dut.clk, 10)
        else:
            self.h.log.warning("write_ibi: timeout waiting for IBI queue threshold")

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
                last_ibi_status = (tgt_status >> 14) & 0x3  # Bits [15:14]
                return True, last_ibi_status
            await ClockCycles(self.h.dut.clk, interval)

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
