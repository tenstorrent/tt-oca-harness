# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""
JTAG Slave BFM for CocoTB

This module provides a comprehensive JTAG slave model that implements the IEEE 1149.1
TAP controller state machine from the slave perspective. It allows users to configure
custom instructions with variable-width Test Data Registers (TDR).

Key Features:
- Full IEEE 1149.1 TAP state machine implementation
- Configurable instruction set with user-defined opcodes
- Variable-width Test Data Registers (TDR) per instruction
- Automatic BYPASS (1-bit) for undefined instructions
- FIFO-like shift register implementation per IEEE standard
- Proper sampling (rising edge) and update (falling edge) timing
- Support for IDCODE, BYPASS, and custom instructions

Author: Andrew Hsiao (ahsiao@tenstorrent.com)
"""

import cocotb
from cocotb.triggers import RisingEdge, FallingEdge, Edge
from cocotb.handle import SimHandleBase
import logging
from typing import Dict, List, Optional, Callable
from collections import deque
import enum

# Import JTAG_TAP_State_e from jtag_enum.py
from .jtag_enum import JTAG_TAP_State_e


class JTAGInstruction:
    """
    Class to represent a JTAG instruction with its associated data register.

    Attributes:
        opcode: Instruction opcode value
        name: Human-readable instruction name
        dr_width: Width of the data register for this instruction
        capture_value: Value to load into DR during CAPTURE-DR state
    """

    def __init__(
        self,
        opcode: int,
        dr_width: int,
        name: Optional[str] = None,
        capture_value: Optional[int] = None,
    ):
        self.opcode = opcode
        self.name = name if name is not None else f"INSTR_0x{opcode:X}"
        self.dr_width = dr_width
        self.capture_value = capture_value if capture_value is not None else 0


class JTAG_Slave_BFM:
    """
    JTAG Slave Bus Functional Model for CocoTB.

    This BFM implements a JTAG slave device that responds to JTAG master transactions.
    It tracks the TAP state machine and provides configurable instruction/data registers.

    The slave samples TMS and TDI on rising edges of TCK and updates TDO on falling edges,
    following IEEE 1149.1 timing requirements.

    Example usage:
        # Create slave BFM
        jtag_slave = JTAG_Slave_BFM(jtag_intf, ir_width=5, idcode=0x12345678)

        # Register custom instruction with 32-bit data register
        jtag_slave.register_instruction(
            opcode=0x08,
            dr_width=32,
            name="CUSTOM_REG",
            capture_value=0xDEADBEEF
        )

        # Start the slave BFM
        cocotb.start_soon(jtag_slave.run())
    """

    # Standard JTAG instructions (IEEE 1149.1)
    BYPASS_OPCODE = 0xFFFFFFFF  # All 1's for BYPASS
    IDCODE_OPCODE = 0x01  # Standard IDCODE instruction

    def __init__(
        self,
        jtag_intf,
        ir_width: int = 5,
        idcode: Optional[int] = None,
        log_level: int = logging.INFO,
        log_name: str = "JTAG_Slave_BFM",
    ):
        """
        Initialize JTAG Slave BFM.

        Args:
            jtag_intf: JTAG interface handle (should have tck, tms, tdi, tdo signals)
            ir_width: Width of instruction register in bits (default: 5)
            idcode: Optional 32-bit IDCODE value (enables IDCODE instruction if provided)
            log_level: Logging level (default: INFO)
        """
        self.jtag_intf = jtag_intf
        self.ir_width = ir_width
        self.idcode = idcode

        # Setup logging
        self.log = logging.getLogger(log_name)
        self.log.setLevel(log_level)

        # Assign interface signals using standard JTAG naming convention
        self.tck = jtag_intf.tck
        self.tms = jtag_intf.tms
        self.tdi = jtag_intf.tdi
        self.tdo = jtag_intf.tdo
        self.trst = jtag_intf.trst if hasattr(jtag_intf, "trst") else None

        # TAP state machine
        self.current_state = JTAG_TAP_State_e.TEST_LOGIC_RESET

        # Instruction Register (IR) - holds current instruction
        self.ir_shift_reg = 0  # Shift register for IR
        self.ir_current = self.BYPASS_OPCODE & (
            (1 << ir_width) - 1
        )  # Current instruction

        # Data Register (DR) - changes based on current instruction
        self.dr_shift_reg = 0  # Shift register for DR
        self.dr_parallel = 0  # Parallel output register

        # Instruction set - maps opcode to JTAGInstruction
        self.instructions: Dict[int, JTAGInstruction] = {}

        # Register standard instructions
        self._register_standard_instructions()

        # Current instruction object
        self.current_instruction = self.instructions[self.ir_current]

        # Bit counter for shift operations
        self.shift_count = 0

        # TDO state
        self.tdo_value = 0

    def _register_standard_instructions(self):
        """Register standard JTAG instructions (BYPASS, IDCODE if applicable)."""
        # BYPASS instruction - always available with 1-bit DR
        bypass_opcode = (1 << self.ir_width) - 1  # All 1's
        self.register_instruction(
            opcode=bypass_opcode, dr_width=1, name="BYPASS", capture_value=0
        )

        # IDCODE instruction - if IDCODE provided
        if self.idcode is not None:
            self.register_instruction(
                opcode=self.IDCODE_OPCODE,
                dr_width=32,
                name="IDCODE",
                capture_value=self.idcode,
            )
            self.log.info(f"IDCODE instruction registered: 0x{self.idcode:08X}")

    def register_instruction(
        self,
        opcode: int,
        dr_width: int,
        name: str,
        capture_value: Optional[int] = None,
    ):
        """
        Register a custom JTAG instruction with its data register configuration.

        Args:
            opcode: Instruction opcode value
            dr_width: Width of data register in bits for this instruction
            name: Human-readable name for the instruction
            capture_value: Value to load into DR during CAPTURE-DR (default: 0)

        Example:
            # Register a 32-bit control register instruction
            jtag_slave.register_instruction(
                opcode=0x08,
                dr_width=32,
                name="CTRL_REG",
                capture_value=0x0,
            )
        """
        # Validate opcode fits in IR width
        max_opcode = (1 << self.ir_width) - 1
        if opcode > max_opcode:
            self.log.warning(
                f"Opcode 0x{opcode:X} exceeds IR width {self.ir_width}, will be truncated"
            )
            opcode = opcode & max_opcode

        instruction = JTAGInstruction(
            opcode=opcode,
            dr_width=dr_width,
            name=name,
            capture_value=capture_value,
        )

        self.instructions[opcode] = instruction
        self.log.info(
            f"Registered instruction: {instruction.name} (opcode=0x{opcode:X}, dr_width={dr_width})"
        )

    def _get_instruction_for_opcode(self, opcode: int) -> JTAGInstruction:
        """
        Get instruction object for given opcode.
        Returns BYPASS instruction if opcode not registered.
        """
        if opcode in self.instructions:
            return self.instructions[opcode]
        else:
            # Undefined instruction - default to BYPASS
            bypass_opcode = (1 << self.ir_width) - 1
            self.log.debug(f"Undefined opcode 0x{opcode:X}, using BYPASS")
            return self.instructions[bypass_opcode]

    def _update_tap_state(self, tms: int):
        """
        Update TAP state machine based on TMS value.
        Implements IEEE 1149.1 state diagram.
        """
        old_state = self.current_state

        if self.current_state == JTAG_TAP_State_e.TEST_LOGIC_RESET:
            self.current_state = (
                JTAG_TAP_State_e.RUN_TEST_IDLE
                if not tms
                else JTAG_TAP_State_e.TEST_LOGIC_RESET
            )
        elif self.current_state == JTAG_TAP_State_e.RUN_TEST_IDLE:
            self.current_state = (
                JTAG_TAP_State_e.SELECT_DR_SCAN
                if tms
                else JTAG_TAP_State_e.RUN_TEST_IDLE
            )
        elif self.current_state == JTAG_TAP_State_e.SELECT_DR_SCAN:
            self.current_state = (
                JTAG_TAP_State_e.SELECT_IR_SCAN if tms else JTAG_TAP_State_e.CAPTURE_DR
            )
        elif self.current_state == JTAG_TAP_State_e.CAPTURE_DR:
            self.current_state = (
                JTAG_TAP_State_e.EXIT1_DR if tms else JTAG_TAP_State_e.SHIFT_DR
            )
        elif self.current_state == JTAG_TAP_State_e.SHIFT_DR:
            self.current_state = (
                JTAG_TAP_State_e.EXIT1_DR if tms else JTAG_TAP_State_e.SHIFT_DR
            )
        elif self.current_state == JTAG_TAP_State_e.EXIT1_DR:
            self.current_state = (
                JTAG_TAP_State_e.UPDATE_DR if tms else JTAG_TAP_State_e.PAUSE_DR
            )
        elif self.current_state == JTAG_TAP_State_e.PAUSE_DR:
            self.current_state = (
                JTAG_TAP_State_e.EXIT2_DR if tms else JTAG_TAP_State_e.PAUSE_DR
            )
        elif self.current_state == JTAG_TAP_State_e.EXIT2_DR:
            self.current_state = (
                JTAG_TAP_State_e.UPDATE_DR if tms else JTAG_TAP_State_e.SHIFT_DR
            )
        elif self.current_state == JTAG_TAP_State_e.UPDATE_DR:
            self.current_state = (
                JTAG_TAP_State_e.SELECT_DR_SCAN
                if tms
                else JTAG_TAP_State_e.RUN_TEST_IDLE
            )
        elif self.current_state == JTAG_TAP_State_e.SELECT_IR_SCAN:
            self.current_state = (
                JTAG_TAP_State_e.TEST_LOGIC_RESET
                if tms
                else JTAG_TAP_State_e.CAPTURE_IR
            )
        elif self.current_state == JTAG_TAP_State_e.CAPTURE_IR:
            self.current_state = (
                JTAG_TAP_State_e.EXIT1_IR if tms else JTAG_TAP_State_e.SHIFT_IR
            )
        elif self.current_state == JTAG_TAP_State_e.SHIFT_IR:
            self.current_state = (
                JTAG_TAP_State_e.EXIT1_IR if tms else JTAG_TAP_State_e.SHIFT_IR
            )
        elif self.current_state == JTAG_TAP_State_e.EXIT1_IR:
            self.current_state = (
                JTAG_TAP_State_e.UPDATE_IR if tms else JTAG_TAP_State_e.PAUSE_IR
            )
        elif self.current_state == JTAG_TAP_State_e.PAUSE_IR:
            self.current_state = (
                JTAG_TAP_State_e.EXIT2_IR if tms else JTAG_TAP_State_e.PAUSE_IR
            )
        elif self.current_state == JTAG_TAP_State_e.EXIT2_IR:
            self.current_state = (
                JTAG_TAP_State_e.UPDATE_IR if tms else JTAG_TAP_State_e.SHIFT_IR
            )
        elif self.current_state == JTAG_TAP_State_e.UPDATE_IR:
            self.current_state = (
                JTAG_TAP_State_e.SELECT_DR_SCAN
                if tms
                else JTAG_TAP_State_e.RUN_TEST_IDLE
            )

        if old_state != self.current_state:
            self.log.debug(f"TAP state: {old_state.name} -> {self.current_state.name}")

    def _handle_capture_dr(self):
        """Handle CAPTURE-DR state - load parallel data into shift register."""
        capture_val = self.current_instruction.capture_value
        self.dr_shift_reg = capture_val
        self.shift_count = 0

        # Output current LSB to TDO (will be updated on falling edge)
        self.tdo_value = self.dr_shift_reg & 0x1
        self.log.debug(
            f"CAPTURE-DR: Loaded 0x{capture_val:X} into DR shift register "
            + f"({self.current_instruction.name}, width={self.current_instruction.dr_width})"
        )

    def _handle_shift_dr(self, tdi: int):
        """
        Handle SHIFT-DR state - shift data through DR.
        TDI shifts in from LSB, TDO shifts out from LSB.
        """
        dr_width = self.current_instruction.dr_width

        # Shift register right, insert TDI at MSB position
        self.dr_shift_reg = (self.dr_shift_reg >> 1) | ((tdi & 0x1) << (dr_width - 1))
        self.shift_count += 1

        # Output current LSB to TDO (will be updated on falling edge)
        self.tdo_value = self.dr_shift_reg & 0x1
        self.log.debug(
            f"SHIFT-DR: bit {self.shift_count}, TDI={tdi}, TDO={self.tdo_value}, "
            + f"DR=0x{self.dr_shift_reg:X}"
        )

    def _handle_update_dr(self):
        """Handle UPDATE-DR state - update parallel output register."""
        self.dr_parallel = self.dr_shift_reg
        self.log.debug(
            f"UPDATE-DR: {self.current_instruction.name} = 0x{self.dr_parallel:X} "
            + f"({self.shift_count} bits shifted)"
        )
        self.current_instruction.capture_value = self.dr_parallel

    def _handle_capture_ir(self):
        """Handle CAPTURE-IR state - load fixed pattern into IR shift register."""
        # IEEE 1149.1: IR capture loads fixed pattern (typically ...10)
        # LSB must be 1, bit[1] must be 0 for proper operation
        capture_pattern = 0x01  # Pattern: ...0001
        self.ir_shift_reg = capture_pattern
        self.shift_count = 0

        # Output current LSB to TDO (will be updated on falling edge)
        self.tdo_value = self.ir_shift_reg & 0x1
        self.log.debug(f"CAPTURE-IR: Loaded pattern 0x{capture_pattern:X}, IR=0x{self.ir_shift_reg:X}")

    def _handle_shift_ir(self, tdi: int):
        """
        Handle SHIFT-IR state - shift data through IR.
        TDI shifts in from LSB, TDO shifts out from LSB.
        """
        # Shift register right, insert TDI at MSB position
        self.ir_shift_reg = (self.ir_shift_reg >> 1) | (
            (tdi & 0x1) << (self.ir_width - 1)
        )
        self.shift_count += 1

        # Output current LSB to TDO (will be updated on falling edge)
        self.tdo_value = self.ir_shift_reg & 0x1
        self.log.debug(
            f"SHIFT-IR: bit {self.shift_count}, TDI={tdi}, TDO={self.tdo_value}, "
            + f"IR=0x{self.ir_shift_reg:X}"
        )

    def _handle_update_ir(self):
        """Handle UPDATE-IR state - update current instruction register."""
        # Mask to IR width
        self.ir_current = self.ir_shift_reg & ((1 << self.ir_width) - 1)

        # Get instruction object for new opcode
        self.current_instruction = self._get_instruction_for_opcode(self.ir_current)

        self.log.debug(
            f"UPDATE-IR: Instruction = {self.current_instruction.name} "
            + f"(0x{self.ir_current:X}, {self.shift_count} bits shifted)"
        )

    #------------------------------------------------------------------------------------------------
    # Debug and Information Functions
    #------------------------------------------------------------------------------------------------
    def _update_ir_debug_registers(self, is_falling_edge: bool = False):
        """
        Update the IR debug registers.
        """
        self.jtag_intf.ir_capture_reg.value = self.ir_shift_reg
        self.jtag_intf.ir_shift_reg.value = self.ir_shift_reg
        self.jtag_intf.ir_update_reg.value = self.ir_current
        self.log.debug(
            f"[{'FALLING' if is_falling_edge else 'RISING'} EDGE] IR debug registers updated: capture=0x{self.ir_shift_reg:X}, shift=0x{self.ir_shift_reg:X}, update=0x{self.ir_current:X}"
        )

    def _update_dr_debug_registers(self, is_falling_edge: bool = False):
        """
        Update the DR debug registers.
        """
        self.jtag_intf.dr_capture_reg.value = self.dr_shift_reg
        self.jtag_intf.dr_shift_reg.value = self.dr_shift_reg
        self.jtag_intf.dr_update_reg.value = self.dr_parallel
        self.log.debug(
            f"[{'FALLING' if is_falling_edge else 'RISING'} EDGE] DR debug registers updated: capture=0x{self.dr_shift_reg:X}, shift=0x{self.dr_shift_reg:X}, update=0x{self.dr_parallel:X}"
        )

    #------------------------------------------------------------------------------------------------
    # Getters for instruction information
    #------------------------------------------------------------------------------------------------
    def get_instruction_dict(self) -> Dict[int, str]:
        """
        Get dictionary of registered instructions.
        Key is the opcode, value is the instruction name.
        """
        return {opcode: instruction.name for opcode, instruction in self.instructions.items()}
    def get_instruction_name_list(self) -> list[str]:
        """
        Get list of registered instruction names.
        """
        return [instruction.name for opcode, instruction in self.instructions.items()]
    def get_instruction_opcode_list(self) -> list[int]:
        """
        Get list of registered instruction opcodes.
        """
        return [opcode for opcode, instruction in self.instructions.items()]
    def get_instruction_name_by_opcode(self, opcode: int) -> str:
        """
        Get name of instruction for a given opcode.
        """
        return self.instructions[opcode].name

    #------------------------------------------------------------------------------------------------
    # Getters for data register information
    #------------------------------------------------------------------------------------------------
    def get_current_dr_value(self) -> int:
        """
        Get current value of the current instruction's data register (parallel output).
        """
        return self.current_instruction.capture_value

    def get_instruction_dr_value(self, op_code: int) -> int:
        """
        Get value of the data register for a given instruction opcode.
        """
        return self.instructions[op_code].capture_value

    def set_current_dr_capture_value(self, value: int):
        """
        Set the capture value for the current instruction's data register.
        This value will be loaded during the next CAPTURE-DR state.

        Args:
            value: Value to load during CAPTURE-DR
        """
        self.current_instruction.capture_value = value
        self.log.debug(
            f"Set capture value for {self.current_instruction.name}: 0x{value:X}"
        )

    def set_instruction_dr_capture_value(self, op_code: int, value: int):
        """
        Set the capture value for the current instruction's data register.
        This value will be loaded during the next CAPTURE-DR state.

        Args:
            op_code: Instruction opcode
            value: Value to load during CAPTURE-DR
        """
        self.instructions[op_code].capture_value = value
        self.log.debug(
            f"Set capture value for {self.instructions[op_code].name}: 0x{value:X}"
        )

    #------------------------------------------------------------------------------------------------
    # Main coroutine to run the JTAG slave BFM
    #------------------------------------------------------------------------------------------------
    async def run(self):
        """
        Main coroutine to run the JTAG slave BFM.
        This should be started with cocotb.start_soon() or as a cocotb.fork().

        The slave monitors TCK and responds to JTAG transactions:
        - Samples TMS and TDI on rising edge of TCK
        - Updates TDO on falling edge of TCK
        - Tracks TAP state machine and handles IR/DR operations
        """
        self.log.info(f"JTAG Slave BFM started (IR width={self.ir_width})")

        # Initialize TDO to high-Z (represented as 0 with TDO_OEN low)
        self.tdo.value = 0

        while True:
            # Wait for rising edge of TCK - sample TMS and TDI
            await RisingEdge(self.tck)

            # Sample inputs
            tms = int(self.tms.value) if self.tms.value.is_resolvable else 0
            tdi = int(self.tdi.value) if self.tdi.value.is_resolvable else 0

            # Store previous state for state change detection
            prev_state = self.current_state

            # Update TAP state machine
            self._update_tap_state(tms)

            # Handle state entry actions
            if self.current_state != prev_state:
                # State entry actions
                if self.current_state == JTAG_TAP_State_e.CAPTURE_DR:
                    self._handle_capture_dr()
                    self._update_dr_debug_registers()
                elif self.current_state == JTAG_TAP_State_e.CAPTURE_IR:
                    self._handle_capture_ir()
                    self._update_ir_debug_registers()
                elif self.current_state == JTAG_TAP_State_e.UPDATE_DR:
                    self._handle_update_dr()
                    self._update_dr_debug_registers()
                elif self.current_state == JTAG_TAP_State_e.UPDATE_IR:
                    self._handle_update_ir()
                    self._update_ir_debug_registers()
                elif self.current_state == JTAG_TAP_State_e.TEST_LOGIC_RESET:
                    # Reset to BYPASS instruction
                    bypass_opcode = (1 << self.ir_width) - 1
                    self.ir_current = bypass_opcode
                    self.current_instruction = self._get_instruction_for_opcode(
                        bypass_opcode
                    )
                    self.log.info("TAP reset - returned to BYPASS instruction")
                    self._update_ir_debug_registers()
                    self._update_dr_debug_registers()

            # Handle state continuous actions (while in state)
            if self.current_state == JTAG_TAP_State_e.SHIFT_DR or self.current_state == JTAG_TAP_State_e.EXIT1_DR:
                self._handle_shift_dr(tdi)
                self._update_dr_debug_registers()
            elif self.current_state == JTAG_TAP_State_e.SHIFT_IR or self.current_state == JTAG_TAP_State_e.EXIT1_IR:
                self._handle_shift_ir(tdi)
                self._update_ir_debug_registers()

            # Wait for falling edge of TCK - update TDO
            await FallingEdge(self.tck)

            # Update TDO output
            self.tdo.value = self.tdo_value

            # Update debug registers
            self._update_dr_debug_registers()
            self._update_ir_debug_registers()


def create_jtag_slave_bfm(
    jtag_intf,
    ir_width: int = 5,
    idcode: Optional[int] = None,
    log_level: int = logging.INFO,
    log_name: str = "JTAG_Slave_BFM",
) -> JTAG_Slave_BFM:
    """
    Convenience function to create and return a JTAG Slave BFM instance.

    Args:
        jtag_intf: JTAG interface handle
        ir_width: Width of instruction register (default: 5 bits)
        idcode: Optional 32-bit IDCODE value
        log_level: Logging level (default: INFO)
        log_name: Logging name (default: "JTAG_Slave_BFM")
    Returns:
        JTAG_Slave_BFM instance

    Example:
        slave = create_jtag_slave_bfm(dut.jtag_intf, ir_width=5, idcode=0x12345678, log_name="JTAG_Slave_BFM")
        slave.register_instruction(0x08, 32, "CTRL_REG")
        cocotb.start_soon(slave.run())
    """
    return JTAG_Slave_BFM(jtag_intf, ir_width, idcode, log_level, log_name)
