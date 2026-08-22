# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

import enum
import random
import math
import logging

import cocotb
from cocotb.triggers import Timer, FallingEdge

from .jtag_enum import JTAG_TAP_State_e, JTAG_TAP_FSM


class JTAG_Master_BFM:
    """
    A reusable JTAG Bus Functional Model (BFM) for Cocotb.

    This BFM correctly navigates the IEEE 1149.1 TAP state machine and
    includes advanced features for robust verification, such as randomized
    interruption of scan chains by visiting PAUSE states.

    Compatible with jtag_intf.sv interface signal naming convention.
    """

    def __init__(self, jtag_intf, tck_period_ns=10, log_level=logging.INFO):
        self.jtag_intf = jtag_intf
        self.log = logging.getLogger(f"JTAG_Master_BFM")
        self.log.setLevel(log_level)
        self.tck_period_ns = tck_period_ns
        self.current_state = JTAG_TAP_State_e.TEST_LOGIC_RESET

        # Assign interface signals using standard JTAG naming convention
        self.tck = jtag_intf.tck
        self.tms = jtag_intf.tms
        self.tdi = jtag_intf.tdi
        self.tdo = jtag_intf.tdo
        self.tdo_oen = jtag_intf.tdo_oen
        self.trst = jtag_intf.trst

        # Assign the initial values to the interface signals
        self.tck.value = 0
        self.tms.value = 0
        self.tdi.value = 0
        self.trst.value = 1

        # Pre-compute half-period used for TCK generation
        self._tck_half_period = max(self.tck_period_ns / 2.0, 1)

    async def _cycle_tck(self):
        """Drives one TCK cycle under BFM control."""
        # Ensure we always start the cycle with TCK low to emulate
        # synchronous JTAG behavior.
        self.tck.value = 0
        await Timer(self._tck_half_period, units="ns")

        # Rising edge – TAP samples TMS/TDI here
        self.tck.value = 1
        await Timer(self._tck_half_period, units="ns")

        # Return to low so the next caller begins from a known state
        self.tck.value = 0

    def _update_state(self, tms_val):
        """Internal method to track the current TAP state."""
        # This logic directly implements the IEEE 1149.1 state diagram
        old_state = self.current_state
        self.current_state = JTAG_TAP_FSM.get_next_state(old_state, tms_val)
        self.log.debug(
            f"State transition -> {old_state.name} -> {self.current_state.name}"
        )

    async def set_tms(self, tms_val):
        """Sets TMS, cycles TCK, and updates the internal state tracker."""
        self.log.debug(f"Setting TMS to {tms_val}")
        self.tms.value = tms_val
        await self._cycle_tck()
        self._update_state(tms_val)

    async def reset(self, cycles=10):
        """Drives TRST and navigates to RUN_TEST_IDLE."""
        self.log.info("Performing JTAG Reset...")
        self.trst.value = 0
        for _ in range(cycles):
            self.tms.value = 1
            self.tdi.value = 0
            await self._cycle_tck()
        self.trst.value = 1
        self.current_state = JTAG_TAP_State_e.TEST_LOGIC_RESET
        self.log.info("JTAG Reset complete. Current state: TEST_LOGIC_RESET")

    async def goto_test_logic_reset(self):
        for _ in range(5):
            await self.set_tms(1)
        await self.set_tms(0)
        self.current_state = JTAG_TAP_State_e.TEST_LOGIC_RESET
        self.log.debug(
            f"Navigated to TEST_LOGIC_RESET. Current state: {self.current_state.name}"
        )

    async def goto_run_test_idle(self):
        tms_list = JTAG_TAP_FSM.get_tms_list(
            self.current_state, JTAG_TAP_State_e.RUN_TEST_IDLE
        )
        self.log.debug(f"Navigating to RUN_TEST_IDLE from {self.current_state.name}")
        self.log.debug(f"TMS list: {tms_list}")
        for tms in tms_list:
            await self.set_tms(tms)
        self.current_state = JTAG_TAP_State_e.RUN_TEST_IDLE
        self.log.debug(
            f"Navigated to RUN_TEST_IDLE. Current state: {self.current_state.name}"
        )

    async def goto_shift_ir(self):
        tms_list = JTAG_TAP_FSM.get_tms_list(
            self.current_state, JTAG_TAP_State_e.SHIFT_IR
        )
        for tms in tms_list:
            await self.set_tms(tms)
        self.current_state = JTAG_TAP_State_e.SHIFT_IR
        self.log.debug(
            f"Navigated to SHIFT_IR. Current state: {self.current_state.name}"
        )

    async def goto_shift_dr(self):
        tms_list = JTAG_TAP_FSM.get_tms_list(
            self.current_state, JTAG_TAP_State_e.SHIFT_DR
        )
        for tms in tms_list:
            await self.set_tms(tms)
        self.current_state = JTAG_TAP_State_e.SHIFT_DR
        self.log.debug(
            f"Navigated to SHIFT_DR. Current state: {self.current_state.name}"
        )

    async def goto_state(self, target_state: JTAG_TAP_State_e):
        old_state = self.current_state
        tms_list = JTAG_TAP_FSM.get_tms_list(self.current_state, target_state)
        for tms in tms_list:
            await self.set_tms(tms)
        self.current_state = target_state
        self.log.debug(f"Navigated from {old_state.name} to {target_state.name}")

    async def _capture_tdo(self, tdo_val):
        """Capture TDO and TDO_OEN after the clock edge"""
        await FallingEdge(self.tck)
        await Timer(self.tck_period_ns // 10, units="ns")

        # Check if TDO_OEN is resolvable
        if not self.tdo_oen.value.is_resolvable:
            self.log.debug(
                "TDO_OEN unresolved at time %s; skipping capture",
                cocotb.utils.get_sim_time(units="ns"),
            )
            tdo_val.append(0)
            return

        tdo_oen_bit = int(self.tdo_oen.value)
        self.log.debug(
            "TDO_OEN captured: %d at time %s",
            tdo_oen_bit,
            cocotb.utils.get_sim_time(units="ns"),
        )

        # Only capture TDO if TDO_OEN is asserted
        if tdo_oen_bit == 1:
            # Check if TDO is resolvable
            if not self.tdo.value.is_resolvable:
                self.log.debug(
                    "TDO unresolved at time %s; defaulting to 0",
                    cocotb.utils.get_sim_time(units="ns"),
                )
                tdo_val.append(0)
            else:
                captured_bit = int(self.tdo.value)
                tdo_val.append(captured_bit)
                self.log.debug(
                    "TDO captured: %d at time %s",
                    captured_bit,
                    cocotb.utils.get_sim_time(units="ns"),
                )
        else:
            tdo_val.append(0)

    async def _scan_register(self, data_in, width):
        """
        Internal scan function.
        """
        tdo_val = []
        captured_tdo = None
        for i in range(width):
            # --- Regular Scan Operation ---
            self.tdi.value = data_in[i]
            self.log.debug(f"TDI: {data_in[i]}")

            # Set TMS high on the last bit to exit, otherwise stay in SHIFT state
            is_last_bit = i == width - 1
            if is_last_bit:
                captured_tdo = cocotb.start_soon(self._capture_tdo(tdo_val))
            else:
                cocotb.start_soon(self._capture_tdo(tdo_val))
            # Assert TMS high on the last bit to exit, otherwise stay in SHIFT state
            await self.set_tms(1 if is_last_bit else 0)
            self.log.debug(f"TMS: {1 if is_last_bit else 0}")
        if captured_tdo is not None:
            await captured_tdo
        return tdo_val

    async def _scan_register_interruptible(self, data_in, width):
        """
        Internal scan function with randomized interruptions.
        This is the core of the advanced BFM behavior.
        """
        tdo_val = []
        captured_tdo = None
        for i in range(width):
            # --- Random Interruption Logic ---
            # Randomly decide to interrupt the scan (with a low probability)
            if i > 0 and i < (width - 1) and random.random() < 0.25:  # 25% chance
                self.log.debug(f"--- Interrupting scan at bit {i} ---")
                await self.set_tms(1)  # SHIFT -> EXIT1
                await self.set_tms(0)  # EXIT1 -> PAUSE

                # Stay in PAUSE for a random number of cycles
                pause_cycles = random.randint(1, 5)
                self.log.debug(f"Pausing for {pause_cycles} TCK cycles.")
                for _ in range(pause_cycles):
                    await self.set_tms(0)  # PAUSE -> PAUSE

                await self.set_tms(1)  # PAUSE -> EXIT2
                await self.set_tms(0)  # EXIT2 -> SHIFT (Resume scan)
                self.log.debug(f"--- Resuming scan at bit {i} ---")

            # --- Regular Scan Operation ---
            self.tdi.value = data_in[i]
            # Set TMS high on the last bit to exit, otherwise stay in SHIFT state
            is_last_bit = i == width - 1
            if is_last_bit:
                captured_tdo = cocotb.start_soon(self._capture_tdo(tdo_val))
            else:
                cocotb.start_soon(self._capture_tdo(tdo_val))
            # Assert TMS high on the last bit to exit, otherwise stay in SHIFT state
            await self.set_tms(1 if is_last_bit else 0)
            self.log.debug(f"TMS: {1 if is_last_bit else 0}")
        # Wait for the captured TDO to be completed
        if captured_tdo is not None:
            await captured_tdo
        self.log.debug(f"TDO captured: {tdo_val}")
        return tdo_val

    async def scan_ir(self, instruction, width, interruptible=False, back_to_rti=False):
        """
        Performs an Instruction Register scan with potential random interruptions.
        """
        self.log.debug(f"Starting IR Scan: instruction={instruction}, width={width}")
        await self.goto_shift_ir()

        if interruptible:
            tdo_val = await self._scan_register_interruptible(instruction, width)
        else:
            tdo_val = await self._scan_register(instruction, width)

        # Go to Reset-Test-Idle or Select-DR-Scan
        if back_to_rti:
            await self.goto_run_test_idle()
        else:
            await self.goto_state(JTAG_TAP_State_e.SELECT_DR_SCAN)

        self.log.debug(
            f"IR Scan complete. TDO captured: {tdo_val}"
        )
        return tdo_val

    async def scan_dr(self, data_in, width, interruptible=False, back_to_rti=False):
        """
        Performs a Data Register scan with potential random interruptions.
        """
        self.log.debug(f"Starting DR Scan: data_in={data_in}, width={width}")
        await self.goto_shift_dr()

        if interruptible:
            tdo_val = await self._scan_register_interruptible(data_in, width)
        else:
            tdo_val = await self._scan_register(data_in, width)

        # Go to Reset-Test-Idle or Select-DR-Scan
        if back_to_rti:
            await self.goto_run_test_idle()
        else:
            await self.goto_state(JTAG_TAP_State_e.SELECT_DR_SCAN)
        self.log.debug(
            f"DR Scan complete. TDO captured: {tdo_val}"
        )
        return tdo_val
