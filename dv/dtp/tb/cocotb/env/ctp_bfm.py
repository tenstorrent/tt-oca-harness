"""
CTP Bus Functional Model for CocoTB

This module provides a Cross-Trigger Port (CTP) Bus Functional Model (BFM)
that can respond to cross-trigger transactions in both WIRE-OR and POINT-TO-POINT modes.
Compatible with ctp_intf.sv interface signal definitions and conventions.

CTP Modes:
- WIRE-OR (mode=0): Simple wired-OR configuration with pulse stretching
- POINT-TO-POINT (mode=1): Handshake-based point-to-point protocol

Features:
- Full CTP functionality for both modes
- Configurable pulse stretching for WIRE-OR mode
- Automatic handshake response for POINT-TO-POINT mode
- Pulse detection and generation
- Synchronization and timing control
- Comprehensive logging and debugging

Author: Andrew Hsiao (ahsiao@tenstorrent.com)
"""

import cocotb
from cocotb.triggers import RisingEdge, FallingEdge, Timer, First, Edge
from cocotb.handle import SimHandleBase
from cocotb.binary import Logic
import logging
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass
from collections import deque
import os

@dataclass
class CTPTriggerEvent:
    """Represents a CTP trigger event"""
    timestamp: int      # Simulation time
    mode: int          # CTP mode when event occurred
    source: str        # Source of trigger (e.g., "ct_req_out_din", "ct_req_in_din")

    def __str__(self):
        mode_str = "WIRE-OR" if self.mode == 0 else "POINT-TO-POINT"
        return f"CTP Trigger @ {self.timestamp}ns [Mode={mode_str}, Source={self.source}]"


class CTPBFM:
    """
    CTP Bus Functional Model

    Provides full CTP functionality using the ctp_intf.sv interface.
    Responds to cross-trigger events and manages handshake protocol.
    """

    # CT REQ/ACK Default Output Values
    # Note: Index 0 is WIRE-OR mode, Index 1 is POINT-TO-POINT mode
    CT_REQ_OUT_DOUT_EN = [0, 1]
    CT_REQ_OUT_DOUT    = [0, 0]
    CT_REQ_OUT_DIN_EN  = [1, 0]

    CT_REQ_IN_DOUT_EN  = [0, 0]
    CT_REQ_IN_DOUT     = [0, 0]
    CT_REQ_IN_DIN_EN   = [0, 1]

    CT_ACK_IN_DOUT_EN  = [0, 0]
    CT_ACK_IN_DOUT     = [0, 0]
    CT_ACK_IN_DIN_EN   = [0, 1]

    CT_ACK_OUT_DOUT_EN = [0, 1]
    CT_ACK_OUT_DOUT    = [0, 0]
    CT_ACK_OUT_DIN_EN  = [0, 0]
    CT_ACK_OUT_DIN     = [0, 0]

    def __init__(self, ctp_intf, clock, name: str = "CTP_BFM"):
        """
        Initialize CTP BFM using interface

        Args:
            ctp_intf: CTP interface handle (ctp_intf.sv instance)
            clock: Clock signal for synchronization
            name: BFM instance name
        """
        self.ctp_intf = ctp_intf
        self.clock = clock
        self.name = name

        # Log instance - use standard Python logging for compatibility
        self.log = logging.getLogger(f"{name}")
        # Ensure logger propagates to root logger
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
        # Don't add our own handler - rely on propagation to root logger
        # CocoTB sets up the root logger with proper handlers
        # Print BFM name
        self.log.info(f"CTP BFM: {self.name} initialized")

        # Interface signal handles
        self.clk = ctp_intf.clk
        self.rst_n = ctp_intf.rst_n

        # Control signals
        self.ct_src = ctp_intf.ct_src
        self.ct_dst = ctp_intf.ct_dst
        self.busy = ctp_intf.busy

        # CT_Req_out pad signals
        self.ct_req_out_dout_en = ctp_intf.ct_req_out_dout_en
        self.ct_req_out_din_en = ctp_intf.ct_req_out_din_en
        self.ct_req_out_dout = ctp_intf.ct_req_out_dout
        self.ct_req_out_din = ctp_intf.ct_req_out_din

        # CT_Req_in pad signals
        self.ct_req_in_dout_en = ctp_intf.ct_req_in_dout_en
        self.ct_req_in_dout = ctp_intf.ct_req_in_dout
        self.ct_req_in_din_en = ctp_intf.ct_req_in_din_en
        self.ct_req_in_din = ctp_intf.ct_req_in_din

        # CT_Ack_in pad signals
        self.ct_ack_in_dout_en = ctp_intf.ct_ack_in_dout_en
        self.ct_ack_in_dout = ctp_intf.ct_ack_in_dout
        self.ct_ack_in_din_en = ctp_intf.ct_ack_in_din_en
        self.ct_ack_in_din = ctp_intf.ct_ack_in_din

        # CT_Ack_out pad signals
        self.ct_ack_out_dout_en = ctp_intf.ct_ack_out_dout_en
        self.ct_ack_out_dout = ctp_intf.ct_ack_out_dout
        self.ct_ack_out_din_en = ctp_intf.ct_ack_out_din_en
        self.ct_ack_out_din = ctp_intf.ct_ack_out_din

        # Configuration signals
        self.config_mode = ctp_intf.config_mode
        self.config_invert = ctp_intf.config_invert
        self.config_reset = ctp_intf.config_reset

        # Configuration
        self.auto_respond = True  # Automatically respond to triggers
        self.response_delay_cycles = 10  # Cycles to wait before responding
        self.ack_pulse_cycles = 3  # Duration of ACK pulse in POINT-TO-POINT mode
        self.p2p_response_delay_cycles = 10 # Cycles to wait before responding to P2P request
        self.stretch_mult = 10 # Stretch multiplier for WIRE-OR mode

        # Event tracking
        self.trigger_events: deque = deque(maxlen=100)
        self.trigger_callback: Optional[Callable] = None

        # Statistics
        self.stats = {
            'wire_or_triggers': 0,
            'p2p_triggers': 0,
            'total_triggers': 0,
            'ack_responses': 0
        }

        # Running flag
        self.running = False

        # Initialize outputs
        self._reset_signals()

    def _reset_signals(self):
        """Reset all output signals to default values"""
        # Drive output signals to known state
        self.ct_req_out_dout_en.value = self.CT_REQ_OUT_DOUT_EN[self.config_mode.value]
        self.ct_req_out_din_en.value = self.CT_REQ_OUT_DIN_EN[self.config_mode.value]
        self.ct_req_out_dout.value = self.CT_REQ_OUT_DOUT[self.config_mode.value]

        self.ct_req_in_din_en.value = self.CT_REQ_IN_DIN_EN[self.config_mode.value]
        self.ct_req_in_dout_en.value = 0
        self.ct_req_in_dout.value = 0

        self.ct_ack_in_dout_en.value = 0
        self.ct_ack_in_dout.value = 0
        self.ct_ack_in_din_en.value = self.CT_ACK_IN_DIN_EN[self.config_mode.value]

        self.ct_ack_out_dout_en.value = self.CT_ACK_OUT_DOUT_EN[self.config_mode.value]
        self.ct_ack_out_dout.value = self.CT_ACK_OUT_DOUT[self.config_mode.value]
        self.ct_ack_out_din_en.value = 0

    async def wait_for_reset_deassertion(self):
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

        if self.log:
            self.log.debug(f"{self.name}: Reset deasserted, BFM starts running")

    async def wait_for_reset_assertion(self):
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

        if self.log:
            self.log.debug(f"{self.name}: Reset asserted, BFM stops running")

    def set_trigger_callback(self, callback: Callable[[CTPTriggerEvent], None]):
        """
        Set a custom callback for trigger events

        Args:
            callback: Function that takes CTPTriggerEvent
        """
        self.trigger_callback = callback

    async def _log_trigger_event(self, source: str):
        """Log a trigger event"""
        current_time = cocotb.utils.get_sim_time(units='ns')
        current_mode = int(self.config_mode.value)

        event = CTPTriggerEvent(
            timestamp=current_time,
            mode=current_mode,
            source=source
        )

        self.trigger_events.append(event)
        self.stats['total_triggers'] += 1

        if current_mode == 0:
            self.stats['wire_or_triggers'] += 1
        else:
            self.stats['p2p_triggers'] += 1

        if self.log:
            self.log.debug(f"{self.name}: {event}")

        # Call custom callback if set
        if self.trigger_callback:
            self.trigger_callback(event)

    async def _wait_cycles_with_reset_check(self, num_cycles: int, context: str = "") -> bool:
        """
        Wait for specified number of cycles while checking for reset.

        Args:
            num_cycles: Number of clock cycles to wait
            context: Context string for logging

        Returns:
            True if completed normally, False if reset was asserted
        """
        for _ in range(num_cycles):
            await RisingEdge(self.clock)
            if int(self.rst_n.value) == 0:
                if self.log and context:
                    self.log.debug(f"{self.name}: Reset asserted during {context}")
                return False
        return True

    async def _wait_for_signal_with_reset_check(self, signal, target_value: int, context: str = "") -> bool:
        """
        Wait for signal to reach target value while checking for reset.

        Args:
            signal: Signal to monitor
            target_value: Target value to wait for
            context: Context string for logging

        Returns:
            True if signal reached target, False if reset was asserted
        """
        while int(signal.value) != target_value:
            await RisingEdge(self.clock)
            if int(self.rst_n.value) == 0:
                if self.log and context:
                    self.log.debug(f"{self.name}: Reset asserted during {context}")
                return False
        return True

    async def assert_handshake_reset_in_p2p_mode(self):
        """Assert handshake reset in P2P mode"""
        self.ct_req_out_dout_en.value = self.CT_REQ_OUT_DOUT_EN[self.config_mode.value] # Enabled in P2P mode
        self.ct_req_out_din_en.value = self.CT_REQ_OUT_DIN_EN[self.config_mode.value] # Disabled in P2P mode
        self.ct_req_out_dout.value = self.get_output_value_against_invert(self.CT_REQ_OUT_DOUT[self.config_mode.value]) # Deasserted in P2P mode for handshake reset
        self.ct_req_in_din_en.value = self.CT_REQ_IN_DIN_EN[self.config_mode.value] # Enabled in P2P mode
        self.ct_ack_in_din_en.value = self.CT_ACK_IN_DIN_EN[self.config_mode.value] # Enabled in P2P mode
        self.ct_ack_out_dout_en.value = self.CT_ACK_OUT_DOUT_EN[self.config_mode.value] # Enabled in P2P mode
        self.ct_ack_out_dout.value = self.get_output_value_against_invert(self.CT_ACK_OUT_DOUT[self.config_mode.value]) # Deasserted in P2P mode for handshake reset

    async def _assign_gpio_values_for_wire_or_mode(self):
        """Assign GPIO values for WIRE-OR mode"""
        # REQ_OUT
        self.ct_req_out_dout.value = self.get_output_value_against_invert(self.CT_REQ_OUT_DOUT[self.config_mode.value])
        self.ct_req_out_dout_en.value = self.CT_REQ_OUT_DOUT_EN[self.config_mode.value]
        self.ct_req_out_din_en.value = self.CT_REQ_OUT_DIN_EN[self.config_mode.value]
        # REQ_IN
        self.ct_req_in_din_en.value = self.CT_REQ_IN_DIN_EN[self.config_mode.value]
        self.ct_req_in_dout_en.value = self.CT_REQ_IN_DOUT_EN[self.config_mode.value]
        self.ct_req_in_dout.value = self.get_output_value_against_invert(self.CT_REQ_IN_DOUT[self.config_mode.value])
        # ACK_OUT
        self.ct_ack_out_dout.value = self.get_output_value_against_invert(self.CT_ACK_OUT_DOUT[self.config_mode.value])
        self.ct_ack_out_dout_en.value = self.CT_ACK_OUT_DOUT_EN[self.config_mode.value]
        self.ct_ack_out_din_en.value = self.CT_ACK_OUT_DIN_EN[self.config_mode.value]
        # ACK_IN
        self.ct_ack_in_din_en.value = self.CT_ACK_IN_DIN_EN[self.config_mode.value]
        self.ct_ack_in_dout_en.value = self.CT_ACK_IN_DOUT_EN[self.config_mode.value]
        self.ct_ack_in_dout.value = self.get_output_value_against_invert(self.CT_ACK_IN_DOUT[self.config_mode.value])

    async def _assign_gpio_en_values_for_p2p_sender(self): # REQ Sender (REQ_OUT) and ACK Listener (ACK_IN)
        """Assign enable values for P2P sender"""
        self.ct_req_out_dout_en.value = self.CT_REQ_OUT_DOUT_EN[self.config_mode.value]
        self.ct_req_out_din_en.value = self.CT_REQ_OUT_DIN_EN[self.config_mode.value]
        self.ct_ack_in_dout_en.value = self.CT_ACK_IN_DOUT_EN[self.config_mode.value]
        self.ct_ack_in_din_en.value = self.CT_ACK_IN_DIN_EN[self.config_mode.value]

    async def _assign_gpio_en_values_for_p2p_receiver(self): # REQ Listener (REQ_IN) and ACK Responder (ACK_OUT)
        """Assign enable values for P2P receiver"""
        self.ct_req_in_dout_en.value = self.CT_REQ_IN_DOUT_EN[self.config_mode.value]
        self.ct_req_in_din_en.value = self.CT_REQ_IN_DIN_EN[self.config_mode.value]
        self.ct_ack_out_dout_en.value = self.CT_ACK_OUT_DOUT_EN[self.config_mode.value]
        self.ct_ack_out_din_en.value = self.CT_ACK_OUT_DIN_EN[self.config_mode.value]

    def get_output_value_against_invert(self, value: int) -> int:
        """Get output value against invert configuration"""
        if int(self.config_invert.value) == 1:
            return 0 if value == 1 else 1
        else:
            return 1 if value == 1 else 0

    async def _handle_wire_or_mode(self):
        """
        Handle WIRE-OR mode operation

        In WIRE-OR mode:
        - Set output enables and control signals
        - Monitor ct_req_out_din for incoming triggers
        - Log trigger events when detected
        """
        while True:
            # Wait for mode to be WIRE-OR
            while int(self.config_mode.value) != 0: # WIRE_OR mode
                await RisingEdge(self.clock)
                if int(self.rst_n.value) == 0:
                    if self.log:
                        self.log.debug(f"{self.name}: Reset asserted during WIRE-OR mode")
                    return

            # Set all outputs to fixed values for WIRE-OR mode
            self.ct_req_out_dout.value = self.get_output_value_against_invert(self.CT_REQ_OUT_DOUT[self.config_mode.value])
            self.ct_req_out_din_en.value = self.CT_REQ_OUT_DIN_EN[self.config_mode.value]
            self.ct_req_in_din_en.value = self.CT_REQ_IN_DIN_EN[self.config_mode.value]
            self.ct_ack_in_din_en.value = self.CT_ACK_IN_DIN_EN[self.config_mode.value]
            self.ct_ack_out_dout_en.value = self.CT_ACK_OUT_DOUT_EN[self.config_mode.value]

            # Get previous value
            prev_val = Logic(str(self.ct_req_out_din.value).lower())

            # Wait for the signal edge (falling edge indicates trigger)
            while True:
                await RisingEdge(self.clock)
                if Logic(str(self.ct_req_out_din.value).lower()) == Logic(self.get_output_value_against_invert(0)):
                    break
                if Logic(str(self.rst_n.value)) == Logic(0):
                    if self.log:
                        self.log.debug(f"{self.name}: Reset asserted during WIRE-OR mode")
                    return

            # Get current value
            curr_val = Logic(str(self.ct_req_out_din.value).lower())

            # Check if transition was from 'Z' to 0
            if prev_val == Logic('x'):
                # Error condition
                self.log.error(f"{self.name}: Detected X->0 transition on ct_req_out_din")
                raise Exception(f"{self.name}: Detected X->0 transition on ct_req_out_din")
            elif prev_val != curr_val:
                # Current value should be 0
                if curr_val == Logic(self.get_output_value_against_invert(0)):
                    await self._log_trigger_event("ct_req_out_din")
                    if self.log:
                        self.log.debug(f"{self.name}: Detected Z->0 transition on ct_req_out_din")

                    # Synchronize the pulse (simulate 2-3 cycle synchronizer)
                    for _ in range(self.response_delay_cycles):
                        await RisingEdge(self.clock)

                    if self.log:
                        self.log.debug(f"{self.name}: WIRE-OR trigger processed (Z->0)")

    async def _handle_p2p_mode_req_from_peer(self):
        """
        Handle P2P mode operation when receiving request from peer

        In P2P mode:
        - Monitor ct_req_in_din (request from peer)
        - Respond with ct_ack_out_dout (acknowledge to peer)
        - Handle reset: stop all actions and drive outputs to 0 when reset is asserted
        """
        while True:
            # Wait for mode to be POINT-TO-POINT
            while int(self.config_mode.value) != 1 and int(self.rst_n.value) == 1 and int(self.config_reset.value) == 0: # POINT-TO-POINT mode
                await RisingEdge(self.clock)
            if int(self.rst_n.value) == 0 or int(self.config_reset.value) == 1:
                self.log.debug(f"{self.name}: Reset or RESET bit asserted during P2P mode")
                await RisingEdge(self.clock)
                continue

            # Reset the handshake state machine
            #   Note: REQ_IN and ACK_OUT
            await self._assign_gpio_en_values_for_p2p_receiver()
            self.ct_req_in_dout.value = self.get_output_value_against_invert(0)
            self.ct_ack_out_dout.value = self.get_output_value_against_invert(0)

            # Wait for request assertion from peer
            while int(self.rst_n.value)==1 and int(self.config_reset.value)==0:
                # Assign the correct values for the GPIOs according to the invert configuration
                await self._assign_gpio_en_values_for_p2p_receiver()
                self.ct_req_in_dout.value = self.get_output_value_against_invert(0)
                self.ct_ack_out_dout.value = self.get_output_value_against_invert(0)
                # Align with the positive edge of the clock
                await RisingEdge(self.clock)
                # Check if the request from peer is asserted
                # Fallback to IDLE state (not active) when signal is unresolvable (X/Z)
                idle_val = self.get_output_value_against_invert(0)
                ct_req_in_din_val = int(self.ct_req_in_din.value) if self.ct_req_in_din.value.is_resolvable else idle_val
                if ct_req_in_din_val == self.get_output_value_against_invert(1):
                    self.log.debug(f"{self.name}: P2P request detected on ct_req_in_din (ct_req_in_din={self.get_output_value_against_invert(1)}), handshake step 1 and complete")
                    break
            if int(self.rst_n.value) == 0 or int(self.config_reset.value) == 1:
                self.log.debug(f"{self.name}: Reset or RESET bit asserted during P2P mode")
                await RisingEdge(self.clock)
                continue


            # Wait for ACK delay cycles
            for _ in range(self.p2p_response_delay_cycles):
                # Assign the correct values for the GPIOs according to the invert configuration
                await self._assign_gpio_en_values_for_p2p_receiver()
                self.ct_req_in_dout.value = self.get_output_value_against_invert(0)
                self.ct_ack_out_dout.value = self.get_output_value_against_invert(0) # Still not asserted
                # Align with the positive edge of the clock
                await RisingEdge(self.clock)
                if int(self.rst_n.value) == 0 or int(self.config_reset.value) == 1:
                    break
            if int(self.rst_n.value) == 0 or int(self.config_reset.value) == 1:
                self.log.debug(f"{self.name}: Reset or RESET bit asserted during P2P mode")
                await RisingEdge(self.clock)
                continue

            # Assert ACK
            await RisingEdge(self.clock)
            self.ct_ack_out_dout.value = self.get_output_value_against_invert(1)

            self.log.debug(f"{self.name}: P2P ACK asserted (ct_ack_out_dout=1) after {self.p2p_response_delay_cycles} cycles, handshake step 2")

            # Wait for request deassertion
            while int(self.rst_n.value) == 1 and int(self.config_reset.value) == 0:
                # Assign the correct values for the GPIOs according to the invert configuration
                await self._assign_gpio_en_values_for_p2p_receiver()
                self.ct_req_in_dout.value = self.get_output_value_against_invert(0)
                # Aligned with the positive edge of the clock
                await RisingEdge(self.clock)
                # Check if the request from peer is deasserted
                # Fallback to ACTIVE state when signal is unresolvable (X/Z) - keeps waiting
                active_val = self.get_output_value_against_invert(1)
                ct_req_in_din_val = int(self.ct_req_in_din.value) if self.ct_req_in_din.value.is_resolvable else active_val
                if ct_req_in_din_val == self.get_output_value_against_invert(0):
                    self.log.debug(f"{self.name}: P2P request deasserted (ct_req_in_din={self.get_output_value_against_invert(0)}), handshake step 3 and complete")
                    break
            if int(self.rst_n.value) == 0 or int(self.config_reset.value) == 1:
                self.log.debug(f"{self.name}: Reset or RESET bit asserted during P2P mode")
                await RisingEdge(self.clock)
                continue

            # Deassert ACK
            await RisingEdge(self.clock)
            self.ct_ack_out_dout.value = self.get_output_value_against_invert(0)

            self.log.debug(f"{self.name}: P2P ACK deasserted (ct_ack_out_dout={self.get_output_value_against_invert(0)}), handshake step 4 and complete")

    async def _handle_p2p_mode_req_to_peer(self):
        """
        Handle P2P mode operation when sending request to peer

        In P2P mode:
        - Monitor ct_req_out_dout (request to peer)
        - Respond with ct_ack_in_din (acknowledge to peer)
        - Handle reset: stop all actions and drive outputs to 0 when reset is asserted
        """
        while True:
            # Wait for mode to be POINT-TO-POINT
            while int(self.config_mode.value) != 1 and int(self.rst_n.value) == 1 and int(self.config_reset.value) == 0: # POINT-TO-POINT mode
                await RisingEdge(self.clock)
            if int(self.rst_n.value) == 0 or int(self.config_reset.value) == 1:
                self.log.debug(f"{self.name}: Reset or RESET bit asserted during P2P mode")
                await RisingEdge(self.clock)
                continue

            # Reset the handshake state machine
            #   Note: REQ_OUT and ACK_IN are driven by the peer
            await self._assign_gpio_en_values_for_p2p_sender()
            self.ct_req_out_dout.value = self.get_output_value_against_invert(0)
            self.ct_ack_in_dout.value = self.get_output_value_against_invert(0)

            # Wait for ACK_IN assertion from peer
            while int(self.rst_n.value)==1 and int(self.config_reset.value)==0:
                # Assign the correct values for the GPIOs according to the invert configuration
                await self._assign_gpio_en_values_for_p2p_sender()
                self.ct_ack_in_dout.value = self.get_output_value_against_invert(0)
                # Aligned with the positive edge of the clock
                await RisingEdge(self.clock)
                # Check if the ACK_IN from peer is asserted
                # Fallback to IDLE state (not active) when signal is unresolvable (X/Z)
                idle_val = self.get_output_value_against_invert(0)
                ct_ack_in_din_val = int(self.ct_ack_in_din.value) if self.ct_ack_in_din.value.is_resolvable else idle_val
                if ct_ack_in_din_val == self.get_output_value_against_invert(1):
                    self.log.debug(f"{self.name}: P2P ACK_IN asserted (ct_ack_in_din={self.get_output_value_against_invert(1)}), handshake step 1 and complete")
                    break
            if int(self.rst_n.value) == 0 or int(self.config_reset.value) == 1:
                self.log.debug(f"{self.name}: Reset or RESET bit asserted during P2P mode")
                await RisingEdge(self.clock)
                continue

            # Wait for response delay cycles
            for _ in range(self.p2p_response_delay_cycles):
                # Assign the correct values for the GPIOs according to the invert configuration
                await self._assign_gpio_en_values_for_p2p_sender()
                # Aligned with the positive edge of the clock
                await RisingEdge(self.clock)
                if int(self.rst_n.value) == 0 or int(self.config_reset.value) == 1:
                    break
            if int(self.rst_n.value) == 0 or int(self.config_reset.value) == 1:
                self.log.debug(f"{self.name}: Reset or RESET bit asserted during P2P mode")
                await RisingEdge(self.clock)
                continue
            # Deassert REQ_OUT after p2p_response_delay_cycles
            self.ct_req_out_dout.value = self.get_output_value_against_invert(0)

            self.log.debug(f"{self.name}: P2P REQ_OUT deasserted (ct_req_out_dout=0), handshake step 2")

            # Wait for ACK_IN deassertion from peer
            while int(self.rst_n.value)==1 and int(self.config_reset.value)==0:
                # Assign the correct values for the GPIOs according to the invert configuration
                await self._assign_gpio_en_values_for_p2p_sender()
                self.ct_ack_in_dout.value = self.get_output_value_against_invert(0)
                # Aligned with the positive edge of the clock
                await RisingEdge(self.clock)
                # Check if the ACK_IN from peer is deasserted
                # Fallback to ACTIVE state when signal is unresolvable (X/Z) - keeps waiting
                active_val = self.get_output_value_against_invert(1)
                ct_ack_in_din_val = int(self.ct_ack_in_din.value) if self.ct_ack_in_din.value.is_resolvable else active_val
                if ct_ack_in_din_val == self.get_output_value_against_invert(0):
                    self.log.debug(f"{self.name}: P2P ACK_IN deasserted (ct_ack_in_din={self.get_output_value_against_invert(0)}), handshake step 3 and complete")
                    break
            if int(self.rst_n.value) == 0 or int(self.config_reset.value) == 1:
                self.log.debug(f"{self.name}: Reset or RESET bit asserted during P2P mode")
                await RisingEdge(self.clock)
                continue

    async def send_trigger(self, mode: int = None):
        """
        Send a cross-trigger pulse to the peer

        Args:
            mode: CTP mode (if None, uses current mode)
        """
        if mode is None:
            mode = int(self.config_mode.value)

        if mode == 0: # WIRE-OR mode
            if self.log:
                self.log.info(f"{self.name}: Sending WIRE-OR trigger via ct_req_out_din")

            # In WIRE-OR mode, drive the line high
            await RisingEdge(self.clock)
            self.ct_req_out_dout_en.value = 1
            self.ct_req_out_dout.value = self.get_output_value_against_invert(0)

            # Hold for pulse duration
            for _ in range(self.stretch_mult):  # Fixed pulse width
                await RisingEdge(self.clock)

            # In WIRE-OR mode, deassert the output driver
            await RisingEdge(self.clock)
            self.ct_req_out_dout_en.value = 0

        else:  # POINT_TO_POINT
            if self.log:
                self.log.info(f"{self.name}: Sending P2P trigger via ct_req_in_din")

            # In P2P mode, assert request to peer
            await RisingEdge(self.clock)
            self.ct_req_out_dout.value = self.get_output_value_against_invert(1)


    async def send_request(self, mode: int = None):
        """
        Send a request pulse

        Args:
            mode: CTP mode (if None, uses current mode)
        """
        if mode is None:
            mode = int(self.config_mode.value)

        if mode == 0: # WIRE-OR mode
            if self.log:
                self.log.info(f"{self.name}: Sending WIRE-OR request via ct_req_out_din")

            # In WIRE-OR mode, drive the line high
            await RisingEdge(self.clock)
            self.ct_req_out_dout_en.value = 1
            self.ct_req_out_dout.value = self.get_output_value_against_invert(0)

            # Hold for pulse duration
            for _ in range(self.stretch_mult):  # Fixed pulse width
                await RisingEdge(self.clock)

            # In WIRE-OR mode, deassert the output driver
            await RisingEdge(self.clock)
            self.ct_req_out_dout_en.value = 0

            if self.log:
                self.log.info(f"{self.name}: WIRE-OR request sent via ct_req_out_din")
        else:
            if self.log:
                self.log.info(f"{self.name}: Sending P2P request via ct_req_out_dout")

            # In P2P mode, assert request
            await RisingEdge(self.clock)
            self.ct_req_out_dout.value = self.get_output_value_against_invert(1)


    async def run(self):
        """Run the BFM"""
        await self.wait_for_reset_deassertion()
        while True:
            self._reset_signals()
            self.wire_or_task = cocotb.start_soon(self._handle_wire_or_mode())
            self.p2p_req_from_peer_task = cocotb.start_soon(self._handle_p2p_mode_req_from_peer())
            self.p2p_req_to_peer_task = cocotb.start_soon(self._handle_p2p_mode_req_to_peer())
            await self.wait_for_reset_assertion()
            self.wire_or_task.cancel()
            self.p2p_req_from_peer_task.cancel()
            self.p2p_req_to_peer_task.cancel()
            await self.wait_for_reset_deassertion()

    def start(self):
        """Start the BFM"""
        self.wire_or_task = cocotb.start_soon(self._handle_wire_or_mode())
        self.p2p_task = cocotb.start_soon(self._handle_point_to_point_mode())
        if self.log:
            self.log.info(f"{self.name}: BFM started")

    def stop(self):
        """Stop the BFM"""
        self.wire_or_task.cancel()
        self.p2p_task.cancel()
        if self.log:
            self.log.info(f"{self.name}: BFM stopped")

    # Utility Methods

    def configure(self, **kwargs):
        """Configure BFM parameters"""
        if 'auto_respond' in kwargs:
            self.auto_respond = kwargs['auto_respond']
        if 'response_delay_cycles' in kwargs:
            self.response_delay_cycles = kwargs['response_delay_cycles']
        if 'ack_pulse_cycles' in kwargs:
            self.ack_pulse_cycles = kwargs['ack_pulse_cycles']

    def get_statistics(self) -> Dict[str, Any]:
        """Get BFM statistics"""
        return self.stats.copy()

    def reset_statistics(self):
        """Reset BFM statistics"""
        for key in self.stats:
            self.stats[key] = 0

    def get_trigger_events(self) -> List[CTPTriggerEvent]:
        """Get list of trigger events"""
        return list(self.trigger_events)

    def clear_trigger_events(self):
        """Clear trigger event history"""
        self.trigger_events.clear()


# Convenience function for easy instantiation
def create_ctp_bfm(ctp_intf, clock, name: str = "CTP_BFM") -> CTPBFM:
    """
    Create and return a CTP BFM instance

    Args:
        ctp_intf: CTP interface handle (ctp_intf.sv instance)
        clock: Clock signal for synchronization
        name: BFM instance name

    Returns:
        CTPBFM instance
    """
    return CTPBFM(ctp_intf, clock, name=name)


# Example usage in a CocoTB test:
"""
@cocotb.test()
async def test_ctp_bfm(dut):
    # Start clock
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    # Access the CTP interface from testbench
    ctp_intf = dut.ctp_if

    # Create CTP BFM using the interface
    ctp_bfm = create_ctp_bfm(ctp_intf, dut.clk, name="Test_CTP")

    # Configure
    ctp_bfm.configure(
        auto_respond=True,
        response_delay_cycles=3
    )

    # Set trigger callback
    def on_trigger(event):
        print(f"Trigger detected: {event}")

    ctp_bfm.set_trigger_callback(on_trigger)

    # Start the BFM
    ctp_bfm.start()

    # Run test...
    await Timer(1000, units='ns')

    # Get statistics
    stats = ctp_bfm.get_statistics()
    print(f"BFM Statistics: {stats}")

    # Get trigger events
    events = ctp_bfm.get_trigger_events()
    for event in events:
        print(f"Event: {event}")

    # Stop the BFM
    ctp_bfm.stop()
"""
