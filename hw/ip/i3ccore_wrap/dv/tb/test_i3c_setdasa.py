# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""
I3C Controller-Target Large Private Write/Read Tests

Register-level tests (no i3c_api) for private transfers that exceed the TX/RX
FIFO depths, refilling and draining on threshold interrupts.
"""

import logging
import os
import sys

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge, Timer
from cocotbext.axi import AxiLiteBus, AxiLiteMaster

# Add path to register headers
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../data/registers/py_headers"))

from I3CCSR_reg import (
    # DAT memory
    DAT_MEM_BASE_ADDR,
    I3C_EC_SOCMGMTIF_T_F_REG_REG_ADDR,
    I3C_EC_SOCMGMTIF_T_FREE_REG_REG_ADDR,
    I3C_EC_SOCMGMTIF_T_HD_DAT_REG_REG_ADDR,
    I3C_EC_SOCMGMTIF_T_HD_STA_REG_REG_ADDR,
    I3C_EC_SOCMGMTIF_T_HIGH_REG_REG_ADDR,
    I3C_EC_SOCMGMTIF_T_LOW_REG_REG_ADDR,
    # Timing registers
    I3C_EC_SOCMGMTIF_T_R_REG_REG_ADDR,
    I3C_EC_SOCMGMTIF_T_SU_DAT_REG_REG_ADDR,
    I3C_EC_SOCMGMTIF_T_SU_STA_REG_REG_ADDR,
    I3C_EC_SOCMGMTIF_T_SU_STO_REG_REG_ADDR,
    # Standby controller mode
    I3C_EC_STDBYCTRLMODE_STBY_CR_CONTROL_REG_ADDR,
    I3C_EC_STDBYCTRLMODE_STBY_CR_DEVICE_ADDR_REG_ADDR,
    I3C_EC_TTI_DATA_BUFFER_THLD_CTRL_REG_ADDR,
    I3C_EC_TTI_INTERRUPT_ENABLE_REG_ADDR,
    I3C_EC_TTI_INTERRUPT_FORCE_REG_ADDR,
    # TTI registers
    I3C_EC_TTI_INTERRUPT_STATUS_REG_ADDR,
    I3C_EC_TTI_RX_DATA_PORT_REG_ADDR,
    I3C_EC_TTI_RX_DESC_QUEUE_PORT_REG_ADDR,
    I3C_EC_TTI_TX_DATA_PORT_REG_ADDR,
    I3C_EC_TTI_TX_DESC_QUEUE_PORT_REG_ADDR,
    I3CBASE_CONTROLLER_DEVICE_ADDR_REG_ADDR,
    # Base registers
    I3CBASE_HC_CONTROL_REG_ADDR,
    # PIO registers
    PIOCONTROL_COMMAND_PORT_REG_ADDR,
    PIOCONTROL_DATA_BUFFER_THLD_CTRL_REG_ADDR,
    PIOCONTROL_PIO_CONTROL_REG_ADDR,
    PIOCONTROL_PIO_INTR_SIGNAL_ENABLE_REG_ADDR,
    PIOCONTROL_PIO_INTR_STATUS_ENABLE_REG_ADDR,
    PIOCONTROL_PIO_INTR_STATUS_REG_ADDR,
    PIOCONTROL_QUEUE_THLD_CTRL_REG_ADDR,
    PIOCONTROL_RESPONSE_PORT_REG_ADDR,
    PIOCONTROL_RX_DATA_PORT_REG_ADDR,
    PIOCONTROL_TX_DATA_PORT_REG_ADDR,
)

# =============================================================================
# Address Mapping
# =============================================================================
# Instance 0 (Controller): 0x0000 - 0x0FFF
# Instance 1 (Target):     0x1000 - 0x1FFF

CTRL_BASE = 0x0000  # Controller (instance 0)
TGT_BASE = 0x1000  # Target (instance 1)

# Target static address to use
TARGET_STATIC_ADDR = 0x10
# Dynamic address to assign via SETDASA (same as static for this test)
TARGET_DYNAMIC_ADDR = 0x10


# =============================================================================
# Register Addresses (from I3CCSR_reg.py)
# =============================================================================

# Base registers
HC_CONTROL = I3CBASE_HC_CONTROL_REG_ADDR
CONTROLLER_DEVICE_ADDR = I3CBASE_CONTROLLER_DEVICE_ADDR_REG_ADDR

# PIO registers
COMMAND_PORT = PIOCONTROL_COMMAND_PORT_REG_ADDR
RESPONSE_PORT = PIOCONTROL_RESPONSE_PORT_REG_ADDR
RESPONSE_QUEUE_PORT = PIOCONTROL_RESPONSE_PORT_REG_ADDR  # Alias
TX_DATA_PORT = PIOCONTROL_TX_DATA_PORT_REG_ADDR
RX_DATA_PORT = PIOCONTROL_RX_DATA_PORT_REG_ADDR
QUEUE_THLD_CTRL = PIOCONTROL_QUEUE_THLD_CTRL_REG_ADDR
DATA_BUFFER_THLD_CTRL = PIOCONTROL_DATA_BUFFER_THLD_CTRL_REG_ADDR
PIO_INTR_STATUS = PIOCONTROL_PIO_INTR_STATUS_REG_ADDR
PIO_INTR_STATUS_ENABLE = PIOCONTROL_PIO_INTR_STATUS_ENABLE_REG_ADDR
PIO_INTR_SIGNAL_ENABLE = PIOCONTROL_PIO_INTR_SIGNAL_ENABLE_REG_ADDR
PIO_CONTROL = PIOCONTROL_PIO_CONTROL_REG_ADDR

# DAT (Device Address Table)
DAT_BASE = DAT_MEM_BASE_ADDR

# Standby Controller Mode registers
STBY_CR_CONTROL = I3C_EC_STDBYCTRLMODE_STBY_CR_CONTROL_REG_ADDR
STBY_CR_DEVICE_ADDR = I3C_EC_STDBYCTRLMODE_STBY_CR_DEVICE_ADDR_REG_ADDR

# Timing registers
T_R_REG = I3C_EC_SOCMGMTIF_T_R_REG_REG_ADDR
T_F_REG = I3C_EC_SOCMGMTIF_T_F_REG_REG_ADDR
T_SU_DAT_REG = I3C_EC_SOCMGMTIF_T_SU_DAT_REG_REG_ADDR
T_HD_DAT_REG = I3C_EC_SOCMGMTIF_T_HD_DAT_REG_REG_ADDR
T_HIGH_REG = I3C_EC_SOCMGMTIF_T_HIGH_REG_REG_ADDR
T_LOW_REG = I3C_EC_SOCMGMTIF_T_LOW_REG_REG_ADDR
T_HD_STA_REG = I3C_EC_SOCMGMTIF_T_HD_STA_REG_REG_ADDR
T_SU_STA_REG = I3C_EC_SOCMGMTIF_T_SU_STA_REG_REG_ADDR
T_SU_STO_REG = I3C_EC_SOCMGMTIF_T_SU_STO_REG_REG_ADDR
T_FREE_REG = I3C_EC_SOCMGMTIF_T_FREE_REG_REG_ADDR

# TTI (Target Transaction Interface) registers
TTI_INTERRUPT_STATUS = I3C_EC_TTI_INTERRUPT_STATUS_REG_ADDR
TTI_INTERRUPT_ENABLE = I3C_EC_TTI_INTERRUPT_ENABLE_REG_ADDR
TTI_INTERRUPT_FORCE = I3C_EC_TTI_INTERRUPT_FORCE_REG_ADDR
TTI_RX_DESC_QUEUE_PORT = I3C_EC_TTI_RX_DESC_QUEUE_PORT_REG_ADDR
TTI_RX_DATA_PORT = I3C_EC_TTI_RX_DATA_PORT_REG_ADDR
TTI_TX_DESC_QUEUE_PORT = I3C_EC_TTI_TX_DESC_QUEUE_PORT_REG_ADDR
TTI_TX_DATA_PORT = I3C_EC_TTI_TX_DATA_PORT_REG_ADDR
TTI_DATA_BUFFER_THLD_CTRL = I3C_EC_TTI_DATA_BUFFER_THLD_CTRL_REG_ADDR


# =============================================================================
# Bit Field Definitions (not in I3CCSR_reg.py)
# =============================================================================

# DATA_BUFFER_THLD_CTRL bit fields (ThldIsPow=1: threshold = 2^(N+1))
TX_BUF_THLD_MASK = 0x00000007  # bits [2:0]
TX_START_THLD_SHIFT = 16  # bits [18:16]
TX_START_THLD_MASK = 0x00070000
RX_BUF_THLD_SHIFT = 8  # bits [10:8]
RX_BUF_THLD_MASK = 0x00000700  # bits [10:8]
RX_START_THLD_SHIFT = 24  # bits [26:24]
RX_START_THLD_MASK = 0x07000000  # bits [26:24]

# PIO_INTR_STATUS bits
PIO_TX_THLD_STAT = 1 << 0  # TX queue threshold status
PIO_RX_THLD_STAT = 1 << 1  # RX queue threshold status
PIO_IBI_STATUS_THLD_STAT = 1 << 2  # IBI queue threshold status
PIO_CMD_QUEUE_READY_STAT = 1 << 3  # CMD queue ready status
PIO_RESP_READY_STAT = 1 << 4  # Response ready status

# TTI DATA_BUFFER_THLD_CTRL bit fields (ThldIsPow=1: threshold = 2^(N+1))
TTI_TX_DATA_THLD_SHIFT = 0  # bits [2:0]
TTI_TX_DATA_THLD_MASK = 0x00000007
TTI_TX_START_THLD_SHIFT = 16  # bits [18:16]
TTI_TX_START_THLD_MASK = 0x00070000
TTI_RX_DATA_THLD_SHIFT = 8  # bits [10:8]
TTI_RX_DATA_THLD_MASK = 0x00000700
TTI_RX_START_THLD_SHIFT = 24  # bits [26:24]
TTI_RX_START_THLD_MASK = 0x07000000

# TTI interrupt bit definitions (same positions for ENABLE and FORCE registers)
TTI_RX_DESC_STAT = 1 << 0  # RX_DESC_STAT interrupt (bit 0)
TTI_TX_DATA_THLD_STAT = 1 << 8  # TX_DATA_THLD_STAT interrupt (bit 8)
TTI_RX_DATA_THLD_STAT = 1 << 9  # RX_DATA_THLD_STAT interrupt (bit 9)


# =============================================================================
# Register Bit Definitions
# =============================================================================

# HC_CONTROL bits
HC_CONTROL_BUS_ENABLE = 1 << 31

# PIO_CONTROL bits
PIO_CONTROL_ENABLE = 1 << 0

# STBY_CR_CONTROL bits
STBY_CR_ENABLE_INIT_ACM_INIT = 0b01 << 30  # ACM_INIT mode (active controller)
STBY_CR_ENABLE_INIT_SCM_RUNNING = 0b10 << 30  # SCM_RUNNING mode (standby/target)
STBY_CR_DAA_SETDASA_ENABLE = 1 << 14
STBY_CR_DAA_ENTDAA_ENABLE = 1 << 13
STBY_CR_DAA_SETAASA_ENABLE = 1 << 12
STBY_CR_TARGET_XACT_ENABLE = 1 << 12

# STBY_CR_DEVICE_ADDR bits
STBY_CR_STATIC_ADDR_VALID = 1 << 15


class TB:
    """
    Testbench class for I3C SETDASA test.
    """

    def __init__(self, dut):
        self.dut = dut
        self.log = logging.getLogger("cocotb.tb")
        self.log.setLevel(logging.INFO)
        self.axi_master = None

    async def setup_axi_master(self):
        """Setup AXI-Lite master interface."""
        await Timer(100, units="ns")

        bus = AxiLiteBus.from_prefix(self.dut, "axi")
        self.axi_master = AxiLiteMaster(bus, self.dut.clk, self.dut.rst_n, reset_active_level=False)

        # Suppress verbose AXI logging
        self.axi_master.write_if.log.setLevel(logging.ERROR)
        self.axi_master.read_if.log.setLevel(logging.ERROR)

        self.log.info("AXI-Lite master connected")

    async def wait_for_reset(self):
        """Wait for DUT reset to complete."""
        self.log.info("Waiting for reset release...")
        while self.dut.rst_n.value == 0:
            await RisingEdge(self.dut.clk)
        await ClockCycles(self.dut.clk, 5)
        self.log.info("Reset released")

    async def read_register(self, addr: int) -> int:
        """Read a 32-bit register via AXI-Lite."""
        if self.axi_master is None:
            raise RuntimeError("AXI-Lite master not initialized")
        data = await self.axi_master.read_dword(addr)
        self.log.debug(f"Read  [0x{addr:08X}] = 0x{data:08X}")
        return data

    async def write_register(self, addr: int, data: int):
        """Write a 32-bit register via AXI-Lite."""
        if self.axi_master is None:
            raise RuntimeError("AXI-Lite master not initialized")
        await self.axi_master.write_dword(addr, data)
        self.log.debug(f"Write [0x{addr:08X}] = 0x{data:08X}")

    async def write_and_verify(
        self, addr: int, data: int, name: str = "", mask: int = 0xFFFFFFFF
    ) -> int:
        """Write register and poll-read to confirm (comparing only masked bits).

        Args:
            addr: Register address
            data: Data to write
            name: Register name for logging
            mask: Bitmask of writable bits to compare (default: all bits)
        """
        await self.write_register(addr, data)
        await ClockCycles(self.dut.clk, 2)
        readback = await self.read_register(addr)

        # Compare only the bits we wrote (some registers have RO bits with reset values)
        if (readback & mask) == (data & mask):
            self.log.info(
                f"  {name} @ 0x{addr:03X}: wrote 0x{data:08X}, verified OK (mask=0x{mask:08X})"
            )
        else:
            self.log.error(
                f"  {name} @ 0x{addr:03X}: wrote 0x{data:08X}, "
                f"read 0x{readback:08X} (MISMATCH, mask=0x{mask:08X})"
            )
            raise AssertionError(
                f"{name}: wrote 0x{data:08X}, read 0x{readback:08X} (mask=0x{mask:08X})"
            )

        return readback

    async def configure_tx_thresholds(self, base_addr: int, tx_buf_thld: int, tx_start_thld: int):
        """Configure TX FIFO thresholds for large transfers.

        Note: ThldIsPow=1, so actual threshold = 2^(value+1)
        - tx_buf_thld: Interrupt when this many free entries (0=disabled, 1=4, 2=8, 3=16, 4=32, 5=64)
        - tx_start_thld: Wait for this many filled entries before starting (0=disabled)
        """
        # Read current value to preserve RX thresholds
        current = await self.read_register(base_addr + DATA_BUFFER_THLD_CTRL)
        self.log.info(f"  DATA_BUFFER_THLD_CTRL before: 0x{current:08X}")

        # Clear TX fields and set new values
        new_val = current & ~(TX_BUF_THLD_MASK | TX_START_THLD_MASK)
        new_val |= (tx_buf_thld & 0x7) | ((tx_start_thld & 0x7) << TX_START_THLD_SHIFT)
        await self.write_register(base_addr + DATA_BUFFER_THLD_CTRL, new_val)

        # Verify the write
        readback = await self.read_register(base_addr + DATA_BUFFER_THLD_CTRL)
        self.log.info(f"  DATA_BUFFER_THLD_CTRL: wrote 0x{new_val:08X}, readback 0x{readback:08X}")

        self.log.info(
            f"  TX thresholds: TX_BUF_THLD={tx_buf_thld} (>={2 ** (tx_buf_thld + 1)} free entries), "
            f"TX_START_THLD={tx_start_thld} ({'disabled' if tx_start_thld == 0 else f'>={2 ** (tx_start_thld + 1)} filled'})"
        )

    async def configure_rx_thresholds(
        self, base_addr: int, rx_buf_thld: int, rx_data_thld: int = 0
    ):
        """Configure RX FIFO thresholds for large transfers.

        Note: ThldIsPow=1, so actual threshold = 2^(value+1)
        - rx_buf_thld: Interrupt when this many filled entries (0=disabled, 1=4, 2=8, 3=16, 4=32, 5=64)
        - rx_data_thld: unused for controller RX
        """
        # Read current value to preserve TX thresholds
        current = await self.read_register(base_addr + DATA_BUFFER_THLD_CTRL)
        self.log.info(f"  DATA_BUFFER_THLD_CTRL before: 0x{current:08X}")

        # Clear RX fields and set new values
        new_val = current & ~(RX_BUF_THLD_MASK | RX_START_THLD_MASK)
        new_val |= (rx_buf_thld & 0x7) << RX_BUF_THLD_SHIFT
        await self.write_register(base_addr + DATA_BUFFER_THLD_CTRL, new_val)

        # Verify the write
        readback = await self.read_register(base_addr + DATA_BUFFER_THLD_CTRL)
        self.log.info(f"  DATA_BUFFER_THLD_CTRL: wrote 0x{new_val:08X}, readback 0x{readback:08X}")

        self.log.info(
            f"  RX thresholds: RX_BUF_THLD={rx_buf_thld} (>={2 ** (rx_buf_thld + 1)} filled entries)"
        )

    async def enable_pio_interrupt(self, base_addr: int, interrupt_bits: int):
        """Enable PIO interrupt status monitoring.

        The PIO_INTR_STATUS_ENABLE register gates which status bits get updated
        from hardware. When TX_THLD_STAT_EN is set, the TX_THLD_STAT status bit
        will be updated from hci_tx_ready_thld_trig_o on each clock.
        """
        current = await self.read_register(base_addr + PIO_INTR_STATUS_ENABLE)
        new_value = current | interrupt_bits
        await self.write_register(base_addr + PIO_INTR_STATUS_ENABLE, new_value)

        # Verify the enable was written correctly
        readback = await self.read_register(base_addr + PIO_INTR_STATUS_ENABLE)
        self.log.info(
            f"  PIO_INTR_STATUS_ENABLE: wrote 0x{new_value:08X}, readback 0x{readback:08X}"
        )

        # Wait a few cycles for status bit to be sampled from HW
        await ClockCycles(self.dut.clk, 5)

        # Check status immediately after enabling
        status = await self.read_register(base_addr + PIO_INTR_STATUS)
        self.log.info(f"  PIO_INTR_STATUS after enable: 0x{status:08X}")
        self.log.info(f"  Enabled PIO interrupts: 0x{interrupt_bits:08X}")

    async def poll_pio_interrupt(
        self, base_addr: int, interrupt_bits: int, max_polls: int = 10000
    ) -> bool:
        """Poll for PIO interrupt status bits to be set.

        Returns True if interrupt detected, False if timeout.
        """
        for i in range(max_polls):
            status = await self.read_register(base_addr + PIO_INTR_STATUS)
            if status & interrupt_bits:
                self.log.info(
                    f"  PIO interrupt 0x{interrupt_bits:X} detected after {i + 1} polls (status=0x{status:08X})"
                )
                return True
            await ClockCycles(self.dut.clk, 10)
        self.log.warning(
            f"  PIO interrupt 0x{interrupt_bits:X} not detected after {max_polls} polls"
        )
        return False

    async def configure_tti_rx_thresholds(
        self, base_addr: int, rx_data_thld: int, rx_start_thld: int
    ):
        """Configure TTI RX FIFO thresholds for large transfers.

        Note: ThldIsPow=1, so actual threshold = 2^(value+1)
        - rx_data_thld: Interrupt when this many filled entries (0=2, 1=4, 2=8, 3=16, 4=32, 5=64)
        - rx_start_thld: Wait for this many entries before starting (usually 0)
        """
        # Read current value to preserve TX thresholds
        current = await self.read_register(base_addr + TTI_DATA_BUFFER_THLD_CTRL)
        # Clear RX fields and set new values
        new_val = current & ~(TTI_RX_DATA_THLD_MASK | TTI_RX_START_THLD_MASK)
        new_val |= (rx_data_thld & 0x7) << TTI_RX_DATA_THLD_SHIFT
        new_val |= (rx_start_thld & 0x7) << TTI_RX_START_THLD_SHIFT
        await self.write_register(base_addr + TTI_DATA_BUFFER_THLD_CTRL, new_val)
        self.log.info(
            f"  TTI RX thresholds: RX_DATA_THLD={rx_data_thld} (>={2 ** (rx_data_thld + 1)} entries), "
            f"RX_START_THLD={rx_start_thld}"
        )

    async def configure_tti_tx_thresholds(
        self, base_addr: int, tx_data_thld: int, tx_start_thld: int
    ):
        """Configure TTI TX FIFO thresholds for large transfers.

        Note: ThldIsPow=1, so actual threshold = 2^(value+1)
        - tx_data_thld: Interrupt when this many free entries (0=2, 1=4, 2=8, 3=16, 4=32, 5=64)
        - tx_start_thld: Wait for this many filled entries before starting (usually 0)
        """
        # Read current value to preserve RX thresholds
        current = await self.read_register(base_addr + TTI_DATA_BUFFER_THLD_CTRL)
        # Clear TX fields and set new values
        new_val = current & ~(TTI_TX_DATA_THLD_MASK | TTI_TX_START_THLD_MASK)
        new_val |= (tx_data_thld & 0x7) << TTI_TX_DATA_THLD_SHIFT
        new_val |= (tx_start_thld & 0x7) << TTI_TX_START_THLD_SHIFT
        await self.write_register(base_addr + TTI_DATA_BUFFER_THLD_CTRL, new_val)
        self.log.info(
            f"  TTI TX thresholds: TX_DATA_THLD={tx_data_thld} (>={2 ** (tx_data_thld + 1)} free entries), "
            f"TX_START_THLD={tx_start_thld}"
        )

    async def enable_tti_interrupt(self, base_addr: int, interrupt_bits: int):
        """Enable TTI interrupt status monitoring."""
        current = await self.read_register(base_addr + TTI_INTERRUPT_ENABLE)
        await self.write_register(base_addr + TTI_INTERRUPT_ENABLE, current | interrupt_bits)
        self.log.info(f"  Enabled TTI interrupts: 0x{interrupt_bits:08X}")

    async def check_tti_interrupt(self, base_addr: int, interrupt_bits: int) -> bool:
        """Check if TTI interrupt status bits are set (non-blocking).

        Returns True if interrupt is set.
        """
        status = await self.read_register(base_addr + TTI_INTERRUPT_STATUS)
        return (status & interrupt_bits) != 0

    async def clear_tti_interrupt(self, base_addr: int, interrupt_bits: int):
        """Clear TTI interrupt status bits (write 1 to clear)."""
        await self.write_register(base_addr + TTI_INTERRUPT_STATUS, interrupt_bits)


# =============================================================================
# Test Cases
# =============================================================================


@cocotb.test(skip=True)
async def test_large_private_write(dut):
    """
    Test private write that exceeds both TX and RX FIFO depths.

    TX FIFO depth = 64 entries x 4 bytes = 256 bytes
    RX FIFO depth = 64 entries x 1 byte = 64 bytes
    Test transfer = 272 bytes (68 entries)

    This test demonstrates threshold-based FIFO management for large transfers:
    - Controller TX: Refill TX FIFO when TX_THLD_STAT triggers (>=32 free entries)
    - Target RX: Drain RX FIFO when RX_DATA_THLD_STAT triggers (>=32 entries filled)

    Flow:
    1. Setup controller and target
    2. Configure TX thresholds: TX_START_THLD=0, TX_BUF_THLD=4 (32 entries)
    3. Configure RX thresholds: RX_START_THLD=0, RX_DATA_THLD=4 (32 entries)
    4. Fill TX FIFO with first 64 entries (256 bytes)
    5. Issue command for the 272-byte transfer
    6. Main loop (concurrent TX refill + RX drain):
       - Check TX_THLD_STAT: Refill TX FIFO if triggered
       - Check RX_DATA_THLD_STAT: Drain RX FIFO if triggered
       - Exit when response is ready
    7. Read remaining RX data after transfer completes
    8. Verify all 272 bytes received correctly (no RX overflow error)
    """
    tb = TB(dut)

    tb.log.info("=" * 60)
    tb.log.info("Starting Large Private Write Test (268 bytes)")
    tb.log.info("=" * 60)
    tb.log.info("TX FIFO depth: 64 entries (256 bytes)")
    tb.log.info("Transfer size: 67 entries (268 bytes)")

    # Wait for simulation to initialize
    await Timer(500, units="ns")

    # Setup AXI-Lite master
    await tb.setup_axi_master()

    # Wait for reset release
    await tb.wait_for_reset()

    # =========================================================================
    # Step 1: Configure Controller (Instance 0)
    # =========================================================================
    tb.log.info("-" * 40)
    tb.log.info("Configuring Controller (Instance 0)")
    tb.log.info("-" * 40)

    await tb.write_and_verify(
        CTRL_BASE + HC_CONTROL, HC_CONTROL_BUS_ENABLE, "HC_CONTROL", mask=0x80000000
    )

    await tb.write_and_verify(
        CTRL_BASE + PIO_CONTROL, PIO_CONTROL_ENABLE, "PIO_CONTROL", mask=0x00000001
    )

    # Configure timing registers
    tb.log.info("  Configuring timing registers...")
    await tb.write_register(CTRL_BASE + T_HIGH_REG, 10)
    await tb.write_register(CTRL_BASE + T_LOW_REG, 10)
    await tb.write_register(CTRL_BASE + T_R_REG, 1)
    await tb.write_register(CTRL_BASE + T_F_REG, 1)
    await tb.write_register(CTRL_BASE + T_HD_STA_REG, 1)
    await tb.write_register(CTRL_BASE + T_SU_STA_REG, 1)
    await tb.write_register(CTRL_BASE + T_SU_STO_REG, 1)
    await tb.write_register(CTRL_BASE + T_SU_DAT_REG, 1)
    await tb.write_register(CTRL_BASE + T_HD_DAT_REG, 1)
    await tb.write_register(CTRL_BASE + T_FREE_REG, 1)

    await tb.write_and_verify(
        CTRL_BASE + STBY_CR_CONTROL,
        STBY_CR_ENABLE_INIT_ACM_INIT,
        "STBY_CR_CONTROL (controller)",
        mask=0xC0000000,
    )

    # Configure DAT entry 0
    dat_entry_lo = (TARGET_STATIC_ADDR << 0) | (TARGET_DYNAMIC_ADDR << 16)
    await tb.write_and_verify(CTRL_BASE + DAT_BASE, dat_entry_lo, "DAT[0] (low)", mask=0x00FF007F)

    # =========================================================================
    # Step 2: Configure Target (Instance 1)
    # =========================================================================
    tb.log.info("-" * 40)
    tb.log.info("Configuring Target (Instance 1)")
    tb.log.info("-" * 40)

    stby_cr_device_addr = TARGET_STATIC_ADDR | STBY_CR_STATIC_ADDR_VALID
    await tb.write_and_verify(
        TGT_BASE + STBY_CR_DEVICE_ADDR, stby_cr_device_addr, "STBY_CR_DEVICE_ADDR", mask=0x0000807F
    )

    stby_cr_control = (
        STBY_CR_ENABLE_INIT_SCM_RUNNING | STBY_CR_DAA_SETDASA_ENABLE | STBY_CR_TARGET_XACT_ENABLE
    )
    await tb.write_and_verify(
        TGT_BASE + STBY_CR_CONTROL, stby_cr_control, "STBY_CR_CONTROL", mask=0xC0005000
    )

    # =========================================================================
    # Step 3: Perform SETDASA
    # =========================================================================
    tb.log.info("-" * 40)
    tb.log.info("Performing SETDASA")
    tb.log.info("-" * 40)

    cmd_desc_lo = (
        (0x2 << 0)
        | (0x0 << 3)
        | (0x87 << 7)
        | (0x0 << 16)
        | (0x1 << 26)
        | (0x1 << 30)
        | (0x1 << 31)
    )
    cmd_desc_hi = 0x00000000
    await tb.write_register(CTRL_BASE + COMMAND_PORT, cmd_desc_lo)
    await tb.write_register(CTRL_BASE + COMMAND_PORT, cmd_desc_hi)

    # Wait for SETDASA response
    response = await tb.read_register(CTRL_BASE + RESPONSE_PORT)
    tb.log.info(f"  SETDASA Response: 0x{response:08X}")

    # Verify target got dynamic address
    max_polls = 1000
    for _ in range(max_polls):
        device_addr_reg = await tb.read_register(TGT_BASE + STBY_CR_DEVICE_ADDR)
        if (device_addr_reg >> 31) & 0x1:
            tb.log.info("  Target dynamic address assigned")
            break
        await ClockCycles(dut.clk, 10)

    # =========================================================================
    # Step 4: Configure TX/RX Thresholds for Large Transfer
    # =========================================================================
    tb.log.info("-" * 40)
    tb.log.info("Configuring TX/RX Thresholds")
    tb.log.info("-" * 40)

    # Controller TX: TX_START_THLD=0 (disabled), TX_BUF_THLD=4 (interrupt when >=32 free entries)
    await tb.configure_tx_thresholds(CTRL_BASE, tx_buf_thld=4, tx_start_thld=0)
    # Enable both TX_THLD_STAT and RESP_READY_STAT so we can see them in PIO_INTR_STATUS
    await tb.enable_pio_interrupt(CTRL_BASE, PIO_TX_THLD_STAT | PIO_RESP_READY_STAT)

    # Target RX: RX_DATA_THLD=0 (interrupt when >=2 entries filled), RX_START_THLD=0
    # RX_DATA_THLD=0 fires at 2 entries, so a tail batch shorter than 32 entries still interrupts
    await tb.configure_tti_rx_thresholds(TGT_BASE, rx_data_thld=0, rx_start_thld=0)
    await tb.enable_tti_interrupt(TGT_BASE, TTI_RX_DATA_THLD_STAT)

    # =========================================================================
    # Step 5: Generate Test Data (272 bytes = 68 entries)
    # =========================================================================
    tb.log.info("-" * 40)
    tb.log.info("Generating Test Data")
    tb.log.info("-" * 40)

    total_bytes = 272
    total_tx_entries = (total_bytes + 3) // 4  # 68 entries (32-bit TX FIFO)
    tx_batch_size = 32  # Write 32 entries per batch (matches TX_BUF_THLD=4 threshold)
    rx_batch_size = 2  # Read 2 entries per batch (matches RX_DATA_THLD=1 threshold)

    # Generate predictable pattern: byte N = N & 0xFF
    test_data = [i & 0xFF for i in range(total_bytes)]
    tb.log.info(f"  Total bytes: {total_bytes}")
    tb.log.info(f"  TX entries (32-bit): {total_tx_entries}")
    tb.log.info(f"  TX batch size: {tx_batch_size} entries (threshold = 2^(4+1) = 32)")
    tb.log.info(f"  RX batch size: {rx_batch_size} entries (threshold = 2^(4+1) = 32)")

    # =========================================================================
    # Step 6: Fill Initial TX FIFO (before issuing command)
    # =========================================================================
    tb.log.info("-" * 40)
    tb.log.info("Filling Initial TX FIFO")
    tb.log.info("-" * 40)

    # Helper function to write a batch of TX entries
    async def write_tx_batch(start_entry: int, num_entries: int):
        bytes_written = 0
        tb.log.info(f"      write_tx_batch: start_entry={start_entry}, num_entries={num_entries}")
        for i in range(num_entries):
            entry_idx = start_entry + i
            byte_offset = entry_idx * 4
            word = 0
            bytes_in_word = 0
            for j in range(4):
                if byte_offset + j < total_bytes:
                    word |= test_data[byte_offset + j] << (j * 8)
                    bytes_in_word += 1
            await tb.write_register(CTRL_BASE + TX_DATA_PORT, word)
            bytes_written += bytes_in_word
        tb.log.info(f"      write_tx_batch: wrote {num_entries} entries ({bytes_written} bytes)")
        return num_entries

    # Collected RX data (populated during transfer)
    received_bytes = []

    # Helper function to read a batch of RX data (8-bit entries packed into 32-bit words)
    async def read_rx_batch(max_bytes: int):
        """Read up to max_bytes from target RX FIFO."""
        bytes_read: list[int] = []
        # RX FIFO is 8-bit entries, but we read 32-bit words (4 bytes per read)
        words_to_read = (max_bytes + 3) // 4
        tb.log.info(f"      read_rx_batch: max_bytes={max_bytes}, words_to_read={words_to_read}")
        for i in range(words_to_read):
            rx_word = await tb.read_register(TGT_BASE + TTI_RX_DATA_PORT)
            for j in range(4):
                if len(bytes_read) < max_bytes:
                    bytes_read.append((rx_word >> (j * 8)) & 0xFF)
        tb.log.info(f"      read_rx_batch: read {len(bytes_read)} bytes")
        return bytes_read

    tx_entries_written = 0

    # First batch: TX_THLD_STAT should be TRUE after reset (FIFO empty = 64 free entries >= 32)
    tb.log.info("  Waiting for TX_THLD_STAT (should be immediate, FIFO empty)...")
    if not await tb.poll_pio_interrupt(CTRL_BASE, PIO_TX_THLD_STAT, max_polls=100):
        tb.log.error("  TX_THLD_STAT not set after reset - unexpected!")

    # Write first 32 entries (128 bytes)
    entries_to_write = min(tx_batch_size, total_tx_entries - tx_entries_written)
    tb.log.info(
        f"  Writing initial batch 1: {entries_to_write} entries ({entries_to_write * 4} bytes)..."
    )
    await write_tx_batch(tx_entries_written, entries_to_write)
    tx_entries_written += entries_to_write
    tb.log.info(
        f"  Batch 1 complete: {tx_entries_written} entries written, {total_tx_entries - tx_entries_written} remaining"
    )

    # After writing 32 entries: 32 entries in FIFO, 32 free, still >= 32 threshold
    # Write second 32 entries
    tb.log.info("  Checking TX_THLD_STAT before batch 2 (32 free >= 32 threshold)...")
    if not await tb.poll_pio_interrupt(CTRL_BASE, PIO_TX_THLD_STAT, max_polls=100):
        tb.log.warning("  TX_THLD_STAT not set - FIFO may have different state")

    entries_to_write = min(tx_batch_size, total_tx_entries - tx_entries_written)
    if entries_to_write > 0:
        tb.log.info(
            f"  Writing initial batch 2: {entries_to_write} entries ({entries_to_write * 4} bytes)..."
        )
        await write_tx_batch(tx_entries_written, entries_to_write)
        tx_entries_written += entries_to_write
        tb.log.info(
            f"  Batch 2 complete: {tx_entries_written} entries written, {total_tx_entries - tx_entries_written} remaining"
        )

    # Now FIFO has 64 entries (full), 0 free entries, TX_THLD_STAT = FALSE
    tb.log.info(f"  TX FIFO filled with {tx_entries_written} entries before issuing command")

    # Debug: Check PIO status after filling FIFO
    pio_after_fill = await tb.read_register(CTRL_BASE + PIO_INTR_STATUS)
    tb.log.info(f"  PIO_INTR_STATUS after fill: 0x{pio_after_fill:08X}")
    tb.log.info(
        f"  TX_THLD_STAT after fill: {'SET' if pio_after_fill & PIO_TX_THLD_STAT else 'CLEAR'} (should be CLEAR if FIFO full)"
    )

    # =========================================================================
    # Step 7: Issue Private Write Command
    # =========================================================================
    tb.log.info("-" * 40)
    tb.log.info("Issuing Private Write Command (268 bytes)")
    tb.log.info("-" * 40)

    data_length = total_bytes
    cmd_desc_lo = (
        (0x0 << 0)  # attr = RegularTransfer
        | (0x1 << 3)  # tid = 1
        | (0x0 << 7)  # cmd = 0 (private write)
        | (0x0 << 15)  # cp = 0
        | (0x0 << 16)  # dev_idx = 0
        | (0x0 << 29)  # rnw = 0 (WRITE)
        | (0x1 << 30)  # wroc = 1
        | (0x1 << 31)  # toc = 1
    )
    cmd_desc_hi = data_length << 16

    tb.log.info(f"  Command descriptor: 0x{cmd_desc_hi:08X}_{cmd_desc_lo:08X}")
    await tb.write_register(CTRL_BASE + COMMAND_PORT, cmd_desc_lo)
    await tb.write_register(CTRL_BASE + COMMAND_PORT, cmd_desc_hi)

    # Debug: Check PIO status right after issuing command
    await ClockCycles(dut.clk, 10)
    pio_after_cmd = await tb.read_register(CTRL_BASE + PIO_INTR_STATUS)
    tb.log.info(f"  PIO_INTR_STATUS after command: 0x{pio_after_cmd:08X}")

    # =========================================================================
    # Step 8: Concurrent TX Refilling and RX Draining
    # =========================================================================
    tb.log.info("-" * 40)
    tb.log.info("Concurrent TX Refilling and RX Draining")
    tb.log.info("-" * 40)

    # Main loop: alternate between checking TX and RX status until transfer completes
    # - TX: Refill when TX_THLD_STAT triggers (controller FIFO has space)
    # - RX: Drain when RX_DATA_THLD_STAT triggers (target FIFO has data)
    # - Exit when response is ready

    remaining_tx_entries = total_tx_entries - tx_entries_written
    tb.log.info(f"  Remaining TX entries: {remaining_tx_entries}")
    tb.log.info(f"  Expected RX bytes: {total_bytes}")

    max_iterations = 50000
    response = 0
    tx_refill_count = 0
    rx_drain_count = 0

    # Debug: track when we first see TX_THLD_STAT
    tx_thld_first_seen = -1
    last_pio_status = -1  # Use -1 to force first log
    debug_interval = 500  # Log status every N iterations

    # Initial status read for debugging
    initial_pio_status = await tb.read_register(CTRL_BASE + PIO_INTR_STATUS)
    initial_enable = await tb.read_register(CTRL_BASE + PIO_INTR_STATUS_ENABLE)
    tb.log.info(f"  Initial PIO_INTR_STATUS: 0x{initial_pio_status:08X}")
    tb.log.info(f"  Initial PIO_INTR_STATUS_ENABLE: 0x{initial_enable:08X}")
    tb.log.info(f"  PIO_TX_THLD_STAT bit mask: 0x{PIO_TX_THLD_STAT:08X}")
    tb.log.info(
        f"  TX_THLD_STAT in initial: {'SET' if initial_pio_status & PIO_TX_THLD_STAT else 'CLEAR'}"
    )
    tb.log.info("  Decoding PIO_INTR_STATUS bits:")
    tb.log.info(f"    TX_THLD_STAT (bit 0): {'SET' if initial_pio_status & (1 << 0) else 'CLEAR'}")
    tb.log.info(f"    RX_THLD_STAT (bit 1): {'SET' if initial_pio_status & (1 << 1) else 'CLEAR'}")
    tb.log.info(
        f"    IBI_STATUS_THLD_STAT (bit 2): {'SET' if initial_pio_status & (1 << 2) else 'CLEAR'}"
    )
    tb.log.info(
        f"    CMD_QUEUE_READY_STAT (bit 3): {'SET' if initial_pio_status & (1 << 3) else 'CLEAR'}"
    )
    tb.log.info(
        f"    RESP_READY_STAT (bit 4): {'SET' if initial_pio_status & (1 << 4) else 'CLEAR'}"
    )
    tb.log.info(
        f"    TRANSFER_ABORT_STAT (bit 5): {'SET' if initial_pio_status & (1 << 5) else 'CLEAR'}"
    )
    tb.log.info(
        f"    TRANSFER_ERR_STAT (bit 9): {'SET' if initial_pio_status & (1 << 9) else 'CLEAR'}"
    )

    for iteration in range(max_iterations):
        # Debug: Log first few iterations and then periodically
        if iteration < 5 or iteration % debug_interval == 0:
            tb.log.info(f"  [iter {iteration}] Loop running, remaining_tx={remaining_tx_entries}")

        # Poll PIO_INTR_STATUS for the TX threshold
        pio_status = await tb.read_register(CTRL_BASE + PIO_INTR_STATUS)

        # Debug: Log when PIO status changes or periodically
        if pio_status != last_pio_status or iteration < 5:
            tb.log.info(
                f"    [iter {iteration}] PIO_INTR_STATUS: 0x{pio_status:08X} "
                f"(TX_THLD={'SET' if pio_status & PIO_TX_THLD_STAT else 'CLR'}, "
                f"RESP_RDY={'SET' if pio_status & PIO_RESP_READY_STAT else 'CLR'})"
            )
            last_pio_status = pio_status

        # Check TX: Need to refill controller TX FIFO?
        if remaining_tx_entries > 0 and (pio_status & PIO_TX_THLD_STAT):
            if tx_thld_first_seen < 0:
                tx_thld_first_seen = iteration
                tb.log.info(f"    [iter {iteration}] TX_THLD_STAT first detected!")

            entries_to_write = min(tx_batch_size, remaining_tx_entries)
            tb.log.info(f"    [iter {iteration}] Writing {entries_to_write} TX entries...")
            await write_tx_batch(tx_entries_written, entries_to_write)
            tx_entries_written += entries_to_write
            remaining_tx_entries -= entries_to_write
            tx_refill_count += 1
            tb.log.info(
                f"    TX refill #{tx_refill_count}: wrote {entries_to_write} entries "
                f"(total: {tx_entries_written}, remaining: {remaining_tx_entries})"
            )

        # Check RX: Need to drain target RX FIFO? (only check occasionally to avoid blocking)
        if iteration % 10 == 0:
            tti_status = await tb.read_register(TGT_BASE + TTI_INTERRUPT_STATUS)
            if tti_status & TTI_RX_DATA_THLD_STAT:
                bytes_to_read = min(rx_batch_size * 4, total_bytes - len(received_bytes))
                if bytes_to_read > 0:
                    batch_data = await read_rx_batch(bytes_to_read)
                    received_bytes.extend(batch_data)
                    rx_drain_count += 1
                    tb.log.info(
                        f"    RX drain #{rx_drain_count}: read {len(batch_data)} bytes "
                        f"(total: {len(received_bytes)})"
                    )
                await tb.clear_tti_interrupt(TGT_BASE, TTI_RX_DATA_THLD_STAT)

        # Check if transfer is complete via RESP_READY_STAT in PIO_INTR_STATUS
        # (avoids reading RESPONSE_PORT which might block)
        if pio_status & PIO_RESP_READY_STAT:
            response = await tb.read_register(CTRL_BASE + RESPONSE_PORT)
            tb.log.info(f"    [iter {iteration}] Response detected: 0x{response:08X}")
            if remaining_tx_entries > 0:
                tb.log.warning(
                    f"  Response received but {remaining_tx_entries} TX entries remaining!"
                )
            tb.log.info(f"  Transfer complete after {iteration + 1} iterations")
            break

        # Small delay to allow bus activity
        await ClockCycles(dut.clk, 10)

    if response == 0:
        tb.log.error(f"  TIMEOUT: No response after {max_iterations} iterations")

    tb.log.info(f"  TX refills: {tx_refill_count}")
    tb.log.info(f"  RX drains: {rx_drain_count}")
    tb.log.info(f"  Bytes received during transfer: {len(received_bytes)}")

    # =========================================================================
    # Step 9: Parse Response and Drain Remaining RX Data
    # =========================================================================
    tb.log.info("-" * 40)
    tb.log.info("Parsing Response and Draining Remaining RX")
    tb.log.info("-" * 40)

    if response != 0:
        tb.log.info(f"  Response: 0x{response:08X}")
        err_status = (response >> 28) & 0xF
        tid = (response >> 24) & 0xF
        resp_data_len = response & 0xFFFF
        tb.log.info(
            f"    ERR_STATUS: {err_status} {'(Success)' if err_status == 0 else '(ERROR!)'}"
        )
        tb.log.info(f"    TID: {tid}")
        tb.log.info(f"    DATA_LENGTH: {resp_data_len}")

    # Wait a bit for any remaining data to arrive at target
    await ClockCycles(dut.clk, 500)

    # Read any remaining RX data from target FIFO
    remaining_bytes = total_bytes - len(received_bytes)
    if remaining_bytes > 0:
        tb.log.info(f"  Reading remaining {remaining_bytes} bytes from target RX FIFO...")
        # Force the RX interrupt to read below-threshold data
        await tb.write_register(TGT_BASE + TTI_INTERRUPT_FORCE, TTI_RX_DATA_THLD_STAT)
        await ClockCycles(dut.clk, 10)

        remaining_data = await read_rx_batch(remaining_bytes)
        received_bytes.extend(remaining_data)
        tb.log.info(f"  Total bytes received: {len(received_bytes)}")

    # =========================================================================
    # Step 10: Read RX Descriptor and Verify Data
    # =========================================================================
    tb.log.info("-" * 40)
    tb.log.info("Reading RX Descriptor and Verifying Data")
    tb.log.info("-" * 40)

    # Force RX_DESC_STAT to allow reading descriptor
    await tb.write_register(TGT_BASE + TTI_INTERRUPT_FORCE, TTI_RX_DESC_STAT)
    await ClockCycles(dut.clk, 10)

    # Read RX descriptor to get transfer info
    rx_desc = await tb.read_register(TGT_BASE + TTI_RX_DESC_QUEUE_PORT)
    rx_byte_count = rx_desc & 0xFFFF
    rx_err_status = (rx_desc >> 28) & 0xF
    tb.log.info(f"  RX Descriptor: 0x{rx_desc:08X}")
    tb.log.info(f"    Byte count: {rx_byte_count}")
    tb.log.info(
        f"    Error status: {rx_err_status} {'(Success)' if rx_err_status == 0 else '(ERROR!)'}"
    )

    # Verify data
    tb.log.info("-" * 40)
    tb.log.info("Verifying Received Data")
    tb.log.info("-" * 40)

    tb.log.info(f"  Expected bytes: {len(test_data)}")
    tb.log.info(f"  Received bytes: {len(received_bytes)}")

    data_match = True
    mismatch_count = 0
    for i in range(min(len(test_data), len(received_bytes))):
        if test_data[i] != received_bytes[i]:
            if mismatch_count < 10:  # Only log first 10 mismatches
                tb.log.error(
                    f"    Byte {i}: expected 0x{test_data[i]:02X}, got 0x{received_bytes[i]:02X}"
                )
            mismatch_count += 1
            data_match = False

    if len(received_bytes) != len(test_data):
        tb.log.error(f"  Length mismatch: expected {len(test_data)}, got {len(received_bytes)}")
        data_match = False

    if data_match:
        tb.log.info(f"  SUCCESS: All {len(test_data)} bytes match!")
    else:
        tb.log.error(f"  FAILED: {mismatch_count} byte mismatches detected")

    # =========================================================================
    # Summary
    # =========================================================================
    tb.log.info("=" * 60)
    tb.log.info("Large Private Write Test Completed")
    tb.log.info("=" * 60)
    tb.log.info(f"  Transfer size: {total_bytes} bytes")
    tb.log.info("  TX FIFO depth: 64 entries (256 bytes)")
    tb.log.info("  RX FIFO depth: 64 entries (64 bytes)")
    tb.log.info(f"  TX refills during transfer: {tx_refill_count}")
    tb.log.info(f"  RX drains during transfer: {rx_drain_count}")
    tb.log.info(f"  RX descriptor byte count: {rx_byte_count}")
    tb.log.info(f"  RX descriptor error: {rx_err_status}")
    tb.log.info(f"  Data verification: {'PASS' if data_match else 'FAIL'}")

    await ClockCycles(dut.clk, 100)


@cocotb.test(skip=True)
async def test_large_private_read(dut):
    """
    Test large private read transfer that exceeds FIFO depth.

    This test verifies that a 272-byte (68-entry) private read transfer
    works correctly when it exceeds the FIFO depths:
    - Target TX FIFO: 64 entries (256 bytes)
    - Controller RX FIFO: 64 entries (256 bytes)

    Data flow: Target TX -> I3C bus -> Controller RX

    The test uses threshold interrupts to:
    - Refill target TX FIFO when TTI_TX_DATA_THLD_STAT triggers (32+ free entries)
    - Drain controller RX FIFO when PIO_RX_THLD_STAT triggers (4+ filled entries)
    """
    tb = TB(dut)

    tb.log.info("=" * 60)
    tb.log.info("Starting Large Private Read Test (272 bytes = 68 entries)")
    tb.log.info("=" * 60)

    # Wait for simulation to initialize
    await Timer(500, units="ns")

    # Setup AXI-Lite master
    await tb.setup_axi_master()

    # Wait for reset release
    await tb.wait_for_reset()

    # =========================================================================
    # Step 1: Configure Controller (Instance 0)
    # =========================================================================
    tb.log.info("-" * 40)
    tb.log.info("Configuring Controller (Instance 0)")
    tb.log.info("-" * 40)

    await tb.write_and_verify(
        CTRL_BASE + HC_CONTROL, HC_CONTROL_BUS_ENABLE, "HC_CONTROL", mask=0x80000000
    )

    await tb.write_and_verify(
        CTRL_BASE + PIO_CONTROL, PIO_CONTROL_ENABLE, "PIO_CONTROL", mask=0x00000001
    )

    # Configure timing registers
    tb.log.info("  Configuring timing registers...")
    await tb.write_register(CTRL_BASE + T_HIGH_REG, 10)
    await tb.write_register(CTRL_BASE + T_LOW_REG, 10)
    await tb.write_register(CTRL_BASE + T_R_REG, 1)
    await tb.write_register(CTRL_BASE + T_F_REG, 1)
    await tb.write_register(CTRL_BASE + T_HD_STA_REG, 1)
    await tb.write_register(CTRL_BASE + T_SU_STA_REG, 1)
    await tb.write_register(CTRL_BASE + T_SU_STO_REG, 1)
    await tb.write_register(CTRL_BASE + T_SU_DAT_REG, 1)
    await tb.write_register(CTRL_BASE + T_HD_DAT_REG, 1)
    await tb.write_register(CTRL_BASE + T_FREE_REG, 1)

    await tb.write_and_verify(
        CTRL_BASE + STBY_CR_CONTROL,
        STBY_CR_ENABLE_INIT_ACM_INIT,
        "STBY_CR_CONTROL (controller)",
        mask=0xC0000000,
    )

    # Configure DAT entry 0
    dat_entry_lo = (TARGET_STATIC_ADDR << 0) | (TARGET_DYNAMIC_ADDR << 16)
    await tb.write_and_verify(CTRL_BASE + DAT_BASE, dat_entry_lo, "DAT[0] (low)", mask=0x00FF007F)

    # =========================================================================
    # Step 2: Configure Target (Instance 1)
    # =========================================================================
    tb.log.info("-" * 40)
    tb.log.info("Configuring Target (Instance 1)")
    tb.log.info("-" * 40)

    stby_cr_device_addr = TARGET_STATIC_ADDR | STBY_CR_STATIC_ADDR_VALID
    await tb.write_and_verify(
        TGT_BASE + STBY_CR_DEVICE_ADDR, stby_cr_device_addr, "STBY_CR_DEVICE_ADDR", mask=0x0000807F
    )

    stby_cr_control = (
        STBY_CR_ENABLE_INIT_SCM_RUNNING | STBY_CR_DAA_SETDASA_ENABLE | STBY_CR_TARGET_XACT_ENABLE
    )
    await tb.write_and_verify(
        TGT_BASE + STBY_CR_CONTROL, stby_cr_control, "STBY_CR_CONTROL", mask=0xC0005000
    )

    # =========================================================================
    # Step 3: Perform SETDASA
    # =========================================================================
    tb.log.info("-" * 40)
    tb.log.info("Performing SETDASA")
    tb.log.info("-" * 40)

    cmd_desc_lo = (
        (0x2 << 0)
        | (0x0 << 3)
        | (0x87 << 7)
        | (0x0 << 16)
        | (0x1 << 26)
        | (0x1 << 30)
        | (0x1 << 31)
    )
    cmd_desc_hi = 0x00000000
    await tb.write_register(CTRL_BASE + COMMAND_PORT, cmd_desc_lo)
    await tb.write_register(CTRL_BASE + COMMAND_PORT, cmd_desc_hi)

    # Wait for SETDASA response
    response = await tb.read_register(CTRL_BASE + RESPONSE_PORT)
    tb.log.info(f"  SETDASA Response: 0x{response:08X}")

    # Verify target got dynamic address
    max_polls = 1000
    for _ in range(max_polls):
        device_addr_reg = await tb.read_register(TGT_BASE + STBY_CR_DEVICE_ADDR)
        if (device_addr_reg >> 31) & 0x1:
            tb.log.info("  Target dynamic address assigned")
            break
        await ClockCycles(dut.clk, 10)

    # =========================================================================
    # Step 4: Configure TX/RX Thresholds for Large Read Transfer
    # =========================================================================
    tb.log.info("-" * 40)
    tb.log.info("Configuring TX/RX Thresholds for Large Read")
    tb.log.info("-" * 40)

    total_bytes = 256  # 68 entries * 4 bytes = 272 bytes

    # Target TX threshold: interrupt when >= 32 free entries (tx_data_thld=4, 2^(4+1)=32)
    await tb.configure_tti_tx_thresholds(TGT_BASE, tx_data_thld=4, tx_start_thld=0)
    tb.log.info("  Configured target TX threshold: tx_data_thld=4 (32 free entries)")

    # Controller RX threshold: interrupt when >= 4 filled entries (rx_buf_thld=1, 2^(1+1)=4)
    await tb.configure_rx_thresholds(CTRL_BASE, rx_buf_thld=1, rx_data_thld=0)
    tb.log.info("  Configured controller RX threshold: rx_buf_thld=1 (4 filled entries)")

    # Enable target TX threshold interrupt
    await tb.enable_tti_interrupt(TGT_BASE, TTI_TX_DATA_THLD_STAT)
    tb.log.info("  Enabled TTI_TX_DATA_THLD_STAT interrupt on target")

    # Enable controller RX threshold and response ready interrupts
    await tb.enable_pio_interrupt(CTRL_BASE, PIO_RX_THLD_STAT | PIO_RESP_READY_STAT)
    tb.log.info("  Enabled PIO_RX_THLD_STAT and PIO_RESP_READY_STAT on controller")

    # =========================================================================
    # Step 5: Generate test data
    # =========================================================================
    tb.log.info("-" * 40)
    tb.log.info("Generating test data pattern")
    tb.log.info("-" * 40)

    test_data = bytes([i & 0xFF for i in range(total_bytes)])
    tb.log.info(f"  Generated {len(test_data)} bytes of test data")

    # =========================================================================
    # Step 6: Fill target TX FIFO with first 64 entries (256 bytes)
    # =========================================================================
    tb.log.info("-" * 40)
    tb.log.info("Pre-filling target TX FIFO with first 256 bytes")
    tb.log.info("-" * 40)

    entries_to_prefill = 64  # Max FIFO depth
    bytes_prefilled = 0

    for i in range(entries_to_prefill):
        byte_offset = i * 4
        if byte_offset + 4 <= total_bytes:
            word = (
                test_data[byte_offset + 3] << 24
                | test_data[byte_offset + 2] << 16
                | test_data[byte_offset + 1] << 8
                | test_data[byte_offset]
            )
            await tb.write_register(TGT_BASE + TTI_TX_DATA_PORT, word)
            bytes_prefilled += 4

    tb.log.info(
        f"  Pre-filled {bytes_prefilled} bytes ({entries_to_prefill} entries) to target TX FIFO"
    )

    # Write TX descriptor - tells target total bytes to send
    tx_desc = total_bytes << 16  # byte count in upper 16 bits
    await tb.write_register(TGT_BASE + TTI_TX_DESC_QUEUE_PORT, tx_desc)
    tb.log.info(f"  Wrote TX descriptor: byte_count={total_bytes}")

    # =========================================================================
    # Step 7: Issue READ command from controller
    # =========================================================================
    tb.log.info("-" * 40)
    tb.log.info("Issuing private read command from controller")
    tb.log.info("-" * 40)

    cmd_desc_lo = (
        (0x0 << 0)  # attr = RegularTransfer
        | (0x3 << 3)  # tid = 3
        | (0x0 << 7)  # cmd = 0 (private, no CCC)
        | (0x0 << 15)  # cp = 0 (command not present)
        | (0x0 << 16)  # dev_idx = 0 (target in DAT[0])
        | (0x0 << 26)  # mode = 0 (SDR0)
        | (0x1 << 29)  # rnw = 1 (READ)
        | (0x1 << 30)  # wroc = 1
        | (0x1 << 31)  # toc = 1
    )
    cmd_desc_hi = total_bytes << 16  # data_length

    await tb.write_register(CTRL_BASE + COMMAND_PORT, cmd_desc_lo)
    await tb.write_register(CTRL_BASE + COMMAND_PORT, cmd_desc_hi)
    tb.log.info(
        f"  Issued READ command for {total_bytes} bytes from DAT[0] (addr 0x{TARGET_DYNAMIC_ADDR:02x})"
    )

    # =========================================================================
    # Step 8: Main loop - refill target TX and drain controller RX
    # =========================================================================
    tb.log.info("-" * 40)
    tb.log.info("Transfer loop - refill target TX, drain controller RX")
    tb.log.info("-" * 40)

    tx_bytes_remaining = total_bytes - bytes_prefilled  # Remaining to send to target TX
    tx_byte_offset = bytes_prefilled
    tx_refill_count = 0

    received_bytes = []
    rx_drain_count = 0

    response_ready = False
    max_iterations = 50000
    iteration = 0

    while not response_ready and iteration < max_iterations:
        iteration += 1
        await ClockCycles(dut.clk, 10)

        # Check target TTI interrupt status for TX threshold
        if tx_bytes_remaining > 0:
            tti_status = await tb.read_register(TGT_BASE + TTI_INTERRUPT_STATUS)

            if tti_status & TTI_TX_DATA_THLD_STAT:
                # Clear the interrupt
                await tb.write_register(TGT_BASE + TTI_INTERRUPT_STATUS, TTI_TX_DATA_THLD_STAT)

                # Refill TX FIFO with up to 32 entries (128 bytes)
                entries_to_write = min(32, tx_bytes_remaining // 4)
                bytes_written = 0

                for _ in range(entries_to_write):
                    if tx_byte_offset + 4 <= total_bytes:
                        word = (
                            test_data[tx_byte_offset + 3] << 24
                            | test_data[tx_byte_offset + 2] << 16
                            | test_data[tx_byte_offset + 1] << 8
                            | test_data[tx_byte_offset]
                        )
                        await tb.write_register(TGT_BASE + TTI_TX_DATA_PORT, word)
                        tx_byte_offset += 4
                        bytes_written += 4
                        tx_bytes_remaining -= 4

                tx_refill_count += 1
                tb.log.info(
                    f"  [Iter {iteration}] TX refill #{tx_refill_count}: wrote {bytes_written} bytes, {tx_bytes_remaining} remaining"
                )

        # Check controller PIO interrupt status
        pio_status = await tb.read_register(CTRL_BASE + PIO_INTR_STATUS)

        # Drain RX FIFO if threshold reached
        if pio_status & PIO_RX_THLD_STAT:
            # Clear the interrupt
            await tb.write_register(CTRL_BASE + PIO_INTR_STATUS, PIO_RX_THLD_STAT)

            # Read available data (read up to 4 entries at a time since RX_BUF_THLD = 1 (2^(1+1)=2))
            bytes_read = 0
            for _ in range(4):
                rx_word = await tb.read_register(CTRL_BASE + RX_DATA_PORT)
                for j in range(4):
                    received_bytes.append((rx_word >> (j * 8)) & 0xFF)
                bytes_read += 4

            rx_drain_count += 1
            tb.log.info(
                f"  [Iter {iteration}] RX drain #{rx_drain_count}: read {bytes_read} bytes, total {len(received_bytes)} received"
            )

        # Check for response ready
        if pio_status & PIO_RESP_READY_STAT:
            tb.log.info(f"  [Iter {iteration}] Response ready detected")
            response_ready = True

    if not response_ready:
        tb.log.error(f"  Timeout after {max_iterations} iterations waiting for response")

    # Read response descriptor
    resp_lo = await tb.read_register(CTRL_BASE + RESPONSE_QUEUE_PORT)
    rx_byte_count = (resp_lo >> 11) & 0xFFFF
    rx_err_status = (resp_lo >> 28) & 0xF
    tb.log.info(f"  Response: byte_count={rx_byte_count}, err_status={rx_err_status}")

    tb.log.info(f"  Total bytes received: {len(received_bytes)}")

    # =========================================================================
    # Verify received data
    # =========================================================================
    tb.log.info("-" * 40)
    tb.log.info("Verifying received data")
    tb.log.info("-" * 40)

    # Trim received bytes to expected length
    received_bytes = received_bytes[:total_bytes]

    data_match = True
    mismatch_count = 0

    for i in range(min(len(received_bytes), len(test_data))):
        if received_bytes[i] != test_data[i]:
            if mismatch_count < 10:
                tb.log.error(
                    f"  Mismatch at byte {i}: expected 0x{test_data[i]:02x}, got 0x{received_bytes[i]:02x}"
                )
            mismatch_count += 1
            data_match = False

    if len(received_bytes) != len(test_data):
        tb.log.error(f"  Length mismatch: expected {len(test_data)}, got {len(received_bytes)}")
        data_match = False

    if data_match:
        tb.log.info(f"  SUCCESS: All {len(test_data)} bytes match!")
    else:
        tb.log.error(f"  FAILED: {mismatch_count} byte mismatches detected")

    # =========================================================================
    # Summary
    # =========================================================================
    tb.log.info("=" * 60)
    tb.log.info("Large Private Read Test Completed")
    tb.log.info("=" * 60)
    tb.log.info(f"  Transfer size: {total_bytes} bytes")
    tb.log.info("  Target TX FIFO depth: 64 entries (256 bytes)")
    tb.log.info("  Controller RX FIFO depth: 64 entries (256 bytes)")
    tb.log.info(f"  TX refills during transfer: {tx_refill_count}")
    tb.log.info(f"  RX drains during transfer: {rx_drain_count}")
    tb.log.info(f"  RX descriptor byte count: {rx_byte_count}")
    tb.log.info(f"  RX descriptor error: {rx_err_status}")
    tb.log.info(f"  Data verification: {'PASS' if data_match else 'FAIL'}")

    await ClockCycles(dut.clk, 100)
