"""
CTM Bus Functional Model for CocoTB

This module provides a simplified Cross-Trigger Matrix (CTM) Bus Functional Model (BFM)
that can drive and monitor cross-trigger transactions on internal CT signals.
Compatible with ctm_intf.sv interface signal definitions and conventions.

The CTM BFM is split into two categories:
- Master BFM: Drives ctm_dst_req, monitors ctm_dst_ack, monitors ctm_src_req, drives ctm_src_ack
- Slave BFM: Drives ctm_src_req, monitors ctm_src_ack, monitors ctm_dst_req, drives ctm_dst_ack

Author: Andrew Hsiao (ahsiao@tenstorrent.com)
"""

import cocotb
from cocotb.triggers import RisingEdge, FallingEdge, Timer
from cocotb.handle import SimHandleBase
import logging
from typing import Optional
import os
import random


class CTMMasterBFM:
    """
    CTM Master Bus Functional Model

    Drives ctm_dst_req and monitors ctm_dst_ack for requests.
    Monitors ctm_src_req and drives ctm_src_ack for responses.
    """

    def __init__(self, ctm_intf, clock, name: str = "CTM_Master_BFM"):
        """
        Initialize CTM Master BFM using interface

        Args:
            ctm_intf: CTM interface handle (ctm_intf.sv instance)
            clock: Clock signal for synchronization
            name: BFM instance name
        """
        self.ctm_intf = ctm_intf
        self.clock = clock
        self.name = name

        # Log instance
        self.log = logging.getLogger(f"CTMMasterBFM__{name}")
        self.log.propagate = True

        # Get log level from environment
        log_level_str = os.environ.get("COCOTB_LOG_LEVEL", "INFO").upper()
        log_level_map = {
            "DEBUG": logging.DEBUG,
            "INFO": logging.INFO,
            "WARNING": logging.WARNING,
            "ERROR": logging.ERROR,
        }
        log_level = log_level_map.get(log_level_str, logging.INFO)
        self.log.setLevel(log_level)

        self.log.info(f"CTM Master BFM: {self.name} initialized")

        # Interface signal handles
        self.clk = ctm_intf.clk
        self.rst_n = ctm_intf.rst_n

        # Cross trigger signals (Master perspective)
        self.ctm_src_req = ctm_intf.ctm_src_req  # Input: Monitor incoming requests
        self.ctm_src_ack = ctm_intf.ctm_src_ack  # Output: Acknowledge incoming requests
        self.ctm_dst_req = ctm_intf.ctm_dst_req  # Output: Send requests
        self.ctm_dst_ack = ctm_intf.ctm_dst_ack  # Input: Monitor acknowledgments

        # Get number of channels
        self.num_channels = int(ctm_intf.XTRIG_NUM_INT_CT.value)

        # Configuration
        self.ack_min_delay = 1  # Minimum ack delay cycles
        self.ack_max_delay = 5  # Maximum ack delay cycles
        self.timeout_cycles = 1000  # Timeout for waiting ack

        # Initialize outputs
        self._reset_signals()

    def _reset_signals(self):
        """Reset all output signals to default values"""
        self.ctm_dst_req.value = 0
        self.ctm_src_ack.value = 0

    async def _wait_for_reset_deassertion(self):
        """Wait for reset deassertion"""
        while True:
            try:
                reset_val = int(self.rst_n.value)
            except ValueError:
                # Value contains X/Z, treat as not yet asserted
                reset_val = 0
            if reset_val == 1:
                break
            await RisingEdge(self.clock)
        self.log.info(f"{self.name}: Reset deasserted, BFM ready")

    async def _wait_for_reset_assertion(self):
        """Wait for reset assertion"""
        while True:
            try:
                reset_val = int(self.rst_n.value)
            except ValueError:
                # Value contains X/Z, treat as not yet asserted
                reset_val = 1
            if reset_val == 0:
                break
            await RisingEdge(self.clock)
        self.log.info(f"{self.name}: Reset asserted")

    async def send_request(self, channel: int, pulse_width: int = 1):
        """
        Send a cross-trigger request on specified channel.
        Asserts ctm_dst_req for at least pulse_width cycles and keeps it asserted.
        The request will be deasserted by the background task _monitor_dst_ack
        when the corresponding ACK is received.

        Args:
            channel: Channel index to trigger
            pulse_width: Minimum pulse width in cycles before ACK can deassert
        """
        if channel >= self.num_channels:
            self.log.error(f"{self.name}: Invalid channel {channel} (max {self.num_channels-1})")
            raise Exception(f"{self.name}: Invalid channel {channel} (max {self.num_channels-1})")

        self.log.info(f"{self.name}: Sending request on channel {channel}")

        # Wait for clock edge
        await RisingEdge(self.clock)

        # Assert request
        if self.num_channels == 1:
            self.ctm_dst_req.value = 1
        else:
            current_val = int(self.ctm_dst_req.value)
            self.ctm_dst_req.value = current_val | (1 << channel)

        # Hold for minimum pulse width, 1 cycle if pulse_width is 0
        if pulse_width > 0:
            for _ in range(pulse_width):
                await RisingEdge(self.clock)
        else:
            await RisingEdge(self.clock)

        # Deassert request
        if self.num_channels == 1:
            self.ctm_dst_req.value = 0
        else:
            current_val = int(self.ctm_dst_req.value)
            self.ctm_dst_req.value = current_val & ~(1 << channel)

        # Request stays asserted - will be deasserted by _monitor_dst_ack when ACK is received
        self.log.debug(f"{self.name}: Request asserted on channel {channel}, waiting for ACK")

    async def _monitor_dst_ack(self):
        """Background task to monitor ctm_dst_ack and deassert ctm_dst_req when ACK is received"""
        prev_val = 0

        while True:
            await RisingEdge(self.clock)

            if int(self.rst_n.value) == 0:
                prev_val = 0
                continue

            # Read current ack value
            if self.num_channels == 1:
                curr_val = int(self.ctm_dst_ack.value)

                # Detect rising edge - ACK received, deassert request
                if curr_val == 1 and prev_val == 0:
                    self.log.info(f"{self.name}: ACK received on channel 0, deasserting request")
                    self.ctm_dst_req.value = 0

                prev_val = curr_val
            else:
                curr_val = int(self.ctm_dst_ack.value)

                # Check each channel for edge transitions
                for ch in range(self.num_channels):
                    curr_bit = (curr_val >> ch) & 0x1
                    prev_bit = (prev_val >> ch) & 0x1

                    # Rising edge - ACK received, deassert request for this channel
                    if curr_bit == 1 and prev_bit == 0:
                        self.log.info(f"{self.name}: ACK received on channel {ch}, deasserting request")
                        current_req = int(self.ctm_dst_req.value)
                        self.ctm_dst_req.value = current_req & ~(1 << ch)

                prev_val = curr_val

    async def _monitor_and_ack_src_req(self):
        """Monitor ctm_src_req and automatically acknowledge with random delay"""
        prev_val = 0

        while True:
            await RisingEdge(self.clock)

            if int(self.rst_n.value) == 0:
                prev_val = 0
                self.ctm_src_ack.value = 0
                continue

            # Read current value
            if self.num_channels == 1:
                curr_val = int(self.ctm_src_req.value)

                # Detect rising edge
                if curr_val == 1 and prev_val == 0:
                    self.log.info(f"{self.name}: Received src_req on channel 0")

                    # Random delay before ack
                    delay = random.randint(self.ack_min_delay, self.ack_max_delay)
                    for _ in range(delay):
                        await RisingEdge(self.clock)

                    # Assert ack
                    self.ctm_src_ack.value = 1
                    self.log.debug(f"{self.name}: ACK asserted for channel 0 after {delay} cycles")

                # Detect falling edge
                elif curr_val == 0 and prev_val == 1:
                    # Deassert ack
                    self.ctm_src_ack.value = 0
                    self.log.debug(f"{self.name}: ACK deasserted for channel 0")

                prev_val = curr_val
            else:
                curr_val = int(self.ctm_src_req.value)

                # Check each channel for edge transitions
                for ch in range(self.num_channels):
                    curr_bit = (curr_val >> ch) & 0x1
                    prev_bit = (prev_val >> ch) & 0x1

                    # Rising edge - assert ack with random delay
                    if curr_bit == 1 and prev_bit == 0:
                        self.log.info(f"{self.name}: Received src_req on channel {ch}")

                        # Random delay before ack
                        delay = random.randint(self.ack_min_delay, self.ack_max_delay)
                        for _ in range(delay):
                            await RisingEdge(self.clock)

                        # Assert ack for this channel
                        current_ack = int(self.ctm_src_ack.value)
                        self.ctm_src_ack.value = current_ack | (1 << ch)
                        self.log.debug(f"{self.name}: ACK asserted for channel {ch} after {delay} cycles")

                    # Falling edge - deassert ack
                    elif curr_bit == 0 and prev_bit == 1:
                        current_ack = int(self.ctm_src_ack.value)
                        self.ctm_src_ack.value = current_ack & ~(1 << ch)
                        self.log.debug(f"{self.name}: ACK deasserted for channel {ch}")

                prev_val = curr_val

    async def run(self):
        """Run the BFM (starts monitoring and responding)"""
        await self._wait_for_reset_deassertion()
        while True:
            self.monitor_src_task = cocotb.start_soon(self._monitor_and_ack_src_req())
            #self.monitor_dst_task = cocotb.start_soon(self._monitor_dst_ack())
            await self._wait_for_reset_assertion()
            self.monitor_src_task.cancel()
            #self.monitor_dst_task.cancel()
            self._reset_signals()
            await self._wait_for_reset_deassertion()

    def start(self):
        """Start the BFM monitoring"""
        self.monitor_src_task = cocotb.start_soon(self._monitor_and_ack_src_req())
        #self.monitor_dst_task = cocotb.start_soon(self._monitor_dst_ack())
        self.log.info(f"{self.name}: BFM started")

    def stop(self):
        """Stop the BFM"""
        self.monitor_src_task.cancel()
        #self.monitor_dst_task.cancel()
        self.log.info(f"{self.name}: BFM stopped")

    def configure(self, **kwargs):
        """Configure BFM parameters"""
        if 'ack_min_delay' in kwargs:
            self.ack_min_delay = kwargs['ack_min_delay']
        if 'ack_max_delay' in kwargs:
            self.ack_max_delay = kwargs['ack_max_delay']
        if 'timeout_cycles' in kwargs:
            self.timeout_cycles = kwargs['timeout_cycles']


class CTMSlaveBFM:
    """
    CTM Slave Bus Functional Model

    Drives ctm_src_req and monitors ctm_src_ack for requests.
    Monitors ctm_dst_req and drives ctm_dst_ack for responses.
    """

    def __init__(self, ctm_intf, clock, name: str = "CTM_Slave_BFM"):
        """
        Initialize CTM Slave BFM using interface

        Args:
            ctm_intf: CTM interface handle (ctm_intf.sv instance)
            clock: Clock signal for synchronization
            name: BFM instance name
        """
        self.ctm_intf = ctm_intf
        self.clock = clock
        self.name = name

        # Log instance
        self.log = logging.getLogger(f"CTMSlaveBFM__{name}")
        self.log.propagate = True

        # Get log level from environment
        log_level_str = os.environ.get("COCOTB_LOG_LEVEL", "INFO").upper()
        log_level_map = {
            "DEBUG": logging.DEBUG,
            "INFO": logging.INFO,
            "WARNING": logging.WARNING,
            "ERROR": logging.ERROR,
        }
        log_level = log_level_map.get(log_level_str, logging.INFO)
        self.log.setLevel(log_level)

        self.log.info(f"CTM Slave BFM: {self.name} initialized")

        # Interface signal handles
        self.clk = ctm_intf.clk
        self.rst_n = ctm_intf.rst_n

        # Cross trigger signals (Slave perspective - opposite of master)
        self.ctm_src_req = ctm_intf.ctm_src_req  # Output: Send requests
        self.ctm_src_ack = ctm_intf.ctm_src_ack  # Input: Monitor acknowledgments
        self.ctm_dst_req = ctm_intf.ctm_dst_req  # Input: Monitor incoming requests
        self.ctm_dst_ack = ctm_intf.ctm_dst_ack  # Output: Acknowledge incoming requests

        # Get number of channels
        self.num_channels = int(ctm_intf.XTRIG_NUM_INT_CT.value)

        # Configuration
        self.ack_min_delay = 1  # Minimum ack delay cycles
        self.ack_max_delay = 5  # Maximum ack delay cycles
        self.timeout_cycles = 1000  # Timeout for waiting ack

        # Initialize outputs
        self._reset_signals()

    def _reset_signals(self):
        """Reset all output signals to default values"""
        self.ctm_src_req.value = 0
        self.ctm_dst_ack.value = 0

    async def _wait_for_reset_deassertion(self):
        """Wait for reset deassertion"""
        while True:
            await RisingEdge(self.clock)
            try:
                reset_val = int(self.rst_n.value)
            except ValueError:
                # Value contains X/Z, treat as not yet asserted
                reset_val = 0
            if reset_val == 1:
                break
        await RisingEdge(self.clock)
        self.log.info(f"{self.name}: Reset deasserted, BFM ready")

    async def _wait_for_reset_assertion(self):
        """Wait for reset assertion"""
        while True:
            await RisingEdge(self.clock)
            try:
                reset_val = int(self.rst_n.value)
            except ValueError:
                # Value contains X/Z, treat as not yet asserted
                reset_val = 1
            if reset_val == 0:
                break
        await RisingEdge(self.clock)
        self.log.info(f"{self.name}: Reset asserted")

    async def send_request(self, channel: int, pulse_width: int = 1):
        """
        Send a cross-trigger source request on specified channel.
        Asserts ctm_src_req for at least pulse_width cycles and keeps it asserted.
        The request will be deasserted by the background task _monitor_src_ack
        when the corresponding ACK is received.

        Args:
            channel: Channel index to trigger
            pulse_width: Minimum pulse width in cycles before ACK can deassert
        """
        if channel >= self.num_channels:
            self.log.error(f"{self.name}: Invalid channel {channel} (max {self.num_channels-1})")
            return

        self.log.info(f"{self.name}: Sending source request on channel {channel}")

        # Wait for clock edge
        await RisingEdge(self.clock)

        # Assert request
        if self.num_channels == 1:
            self.ctm_src_req.value = 1
        else:
            current_val = int(self.ctm_src_req.value)
            self.ctm_src_req.value = current_val | (1 << channel)

        # Hold for minimum pulse width
        for _ in range(pulse_width):
            await RisingEdge(self.clock)

        # Request stays asserted - will be deasserted by _monitor_src_ack when ACK is received
        self.log.debug(f"{self.name}: Source request asserted on channel {channel}, waiting for ACK")

    async def _monitor_src_ack(self):
        """Background task to monitor ctm_src_ack and deassert ctm_src_req when ACK is received"""
        prev_val = 0

        while True:
            await RisingEdge(self.clock)

            if int(self.rst_n.value) == 0:
                prev_val = 0
                continue

            # Read current ack value
            if self.num_channels == 1:
                curr_val = int(self.ctm_src_ack.value)

                # Detect rising edge - ACK received, deassert request
                if curr_val == 1 and prev_val == 0:
                    self.log.info(f"{self.name}: ACK received on channel 0, deasserting request")
                    self.ctm_src_req.value = 0

                prev_val = curr_val
            else:
                curr_val = int(self.ctm_src_ack.value)

                # Check each channel for edge transitions
                for ch in range(self.num_channels):
                    curr_bit = (curr_val >> ch) & 0x1
                    prev_bit = (prev_val >> ch) & 0x1

                    # Rising edge - ACK received, deassert request for this channel
                    if curr_bit == 1 and prev_bit == 0:
                        self.log.info(f"{self.name}: ACK received on channel {ch}, deasserting request")
                        current_req = int(self.ctm_src_req.value)
                        self.ctm_src_req.value = current_req & ~(1 << ch)

                prev_val = curr_val

    async def _monitor_and_ack_dst_req(self):
        """Monitor ctm_dst_req and automatically acknowledge with random delay"""
        prev_val = 0

        while True:
            await RisingEdge(self.clock)

            if int(self.rst_n.value) == 0:
                prev_val = 0
                self.ctm_dst_ack.value = 0
                continue

            # Read current value
            if self.num_channels == 1:
                curr_val = int(self.ctm_dst_req.value)

                # Detect rising edge
                if curr_val == 1 and prev_val == 0:
                    self.log.info(f"{self.name}: Received dst_req on channel 0")

                    # Random delay before ack
                    delay = random.randint(self.ack_min_delay, self.ack_max_delay)
                    for _ in range(delay):
                        await RisingEdge(self.clock)

                    # Assert ack
                    self.ctm_dst_ack.value = 1
                    self.log.debug(f"{self.name}: ACK asserted for channel 0 after {delay} cycles")

                # Detect falling edge
                elif curr_val == 0 and prev_val == 1:
                    # Deassert ack
                    self.ctm_dst_ack.value = 0
                    self.log.debug(f"{self.name}: ACK deasserted for channel 0")

                prev_val = curr_val
            else:
                curr_val = int(self.ctm_dst_req.value)

                # Check each channel for edge transitions
                for ch in range(self.num_channels):
                    curr_bit = (curr_val >> ch) & 0x1
                    prev_bit = (prev_val >> ch) & 0x1

                    # Rising edge - assert ack with random delay
                    if curr_bit == 1 and prev_bit == 0:
                        self.log.info(f"{self.name}: Received dst_req on channel {ch}")

                        # Random delay before ack
                        delay = random.randint(self.ack_min_delay, self.ack_max_delay)
                        for _ in range(delay):
                            await RisingEdge(self.clock)

                        # Assert ack for this channel
                        current_ack = int(self.ctm_dst_ack.value)
                        self.ctm_dst_ack.value = current_ack | (1 << ch)
                        self.log.debug(f"{self.name}: ACK asserted for channel {ch} after {delay} cycles")

                    # Falling edge - deassert ack
                    elif curr_bit == 0 and prev_bit == 1:
                        current_ack = int(self.ctm_dst_ack.value)
                        self.ctm_dst_ack.value = current_ack & ~(1 << ch)
                        self.log.debug(f"{self.name}: ACK deasserted for channel {ch}")

                prev_val = curr_val

    async def run(self):
        """Run the BFM (starts monitoring and responding)"""
        await self._wait_for_reset_deassertion()
        while True:
            self.monitor_dst_task = cocotb.start_soon(self._monitor_and_ack_dst_req())
            self.monitor_src_task = cocotb.start_soon(self._monitor_src_ack())
            await self._wait_for_reset_assertion()
            self.monitor_dst_task.cancel()
            self.monitor_src_task.cancel()
            self._reset_signals()
            await self._wait_for_reset_deassertion()

    def start(self):
        """Start the BFM monitoring"""
        self.monitor_dst_task = cocotb.start_soon(self._monitor_and_ack_dst_req())
        self.monitor_src_task = cocotb.start_soon(self._monitor_src_ack())
        self.log.info(f"{self.name}: BFM started")

    def stop(self):
        """Stop the BFM"""
        self.monitor_dst_task.cancel()
        self.monitor_src_task.cancel()
        self.log.info(f"{self.name}: BFM stopped")

    def configure(self, **kwargs):
        """Configure BFM parameters"""
        if 'ack_min_delay' in kwargs:
            self.ack_min_delay = kwargs['ack_min_delay']
        if 'ack_max_delay' in kwargs:
            self.ack_max_delay = kwargs['ack_max_delay']
        if 'timeout_cycles' in kwargs:
            self.timeout_cycles = kwargs['timeout_cycles']


# Convenience functions for easy instantiation
def create_ctm_master_bfm(ctm_intf, clock, name: str = "CTM_Master_BFM") -> CTMMasterBFM:
    """
    Create and return a CTM Master BFM instance

    Args:
        ctm_intf: CTM interface handle (ctm_intf.sv instance)
        clock: Clock signal for synchronization
        name: BFM instance name

    Returns:
        CTMMasterBFM instance
    """
    return CTMMasterBFM(ctm_intf, clock, name=name)


def create_ctm_slave_bfm(ctm_intf, clock, name: str = "CTM_Slave_BFM") -> CTMSlaveBFM:
    """
    Create and return a CTM Slave BFM instance

    Args:
        ctm_intf: CTM interface handle (ctm_intf.sv instance)
        clock: Clock signal for synchronization
        name: BFM instance name

    Returns:
        CTMSlaveBFM instance
    """
    return CTMSlaveBFM(ctm_intf, clock, name=name)


# Example usage in a CocoTB test:
"""
@cocotb.test()
async def test_ctm_bfm(dut):
    # Start clock
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    # Access the CTM interface from testbench
    ctm_intf = dut.ctm_if

    # Create CTM Master BFM
    ctm_master = create_ctm_master_bfm(ctm_intf, dut.clk, name="CTM_Master")

    # Configure
    ctm_master.configure(
        ack_min_delay=1,
        ack_max_delay=5,
        timeout_cycles=100
    )

    # Start the BFM (begins monitoring and auto-responding to src_req,
    # and monitoring dst_ack for our requests)
    ctm_master.start()

    # Send a request on channel 0 (fire-and-forget, ACK handled by background task)
    await ctm_master.send_request(channel=0, pulse_width=1)

    # Stop the BFM
    ctm_master.stop()
"""
