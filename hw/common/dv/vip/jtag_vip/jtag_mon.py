# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""
JTAG Monitor for CocoTB

This module provides a comprehensive JTAG monitor that can track JTAG signals,
decode transactions, and provide analysis capabilities for verification.
Compatible with JTAG BFM signal definitions and conventions.

Author: Andrew Hsiao (ahsiao@tenstorrent.com)
"""

import cocotb
from cocotb.triggers import RisingEdge, FallingEdge, ReadOnly, Timer
import logging
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from collections import deque

from .jtag_enum import JTAG_TAP_State_e, JTAG_TAP_FSM


class JTAGProtocolError(AssertionError):
    """Raised on a JTAG protocol violation in strict mode."""


@dataclass
class JTAGTransaction:
    """Represents a complete JTAG transaction"""

    transaction_type: str  # "IR" or "DR"
    start_time: float
    end_time: Optional[float] = None
    tdi_data: List[int] = field(default_factory=list)
    tdo_data: List[int] = field(default_factory=list)
    bit_count: int = 0
    instruction: Optional[int] = None

    def __post_init__(self):
        if self.end_time is None:
            self.end_time = self.start_time

    @property
    def duration(self) -> float:
        """Transaction duration in simulation time"""
        return self.end_time - self.start_time if self.end_time else 0

    @property
    def tdi_value(self) -> int:
        """TDI data as integer (LSB first)"""
        if not self.tdi_data:
            return 0
        value = 0
        for i, bit in enumerate(self.tdi_data):
            if bit:
                value |= 1 << i
        return value

    @property
    def tdo_value(self) -> int:
        """TDO data as integer (LSB first)"""
        if not self.tdo_data:
            return 0
        value = 0
        for i, bit in enumerate(self.tdo_data):
            if bit:
                value |= 1 << i
        return value


class JTAG_Monitor:
    """
    Comprehensive JTAG Monitor for CocoTB

    Monitors JTAG signals and provides transaction-level analysis.
    Compatible with jtag_intf.sv interface signal naming convention.
    """

    def __init__(self, jtag_intf, name: str = "JTAG_Monitor", strict: bool = True):
        """
        Initialize JTAG Monitor using interface signal definitions

        Args:
            jtag_intf: JTAG interface handle (jtag_intf.sv instance)
            name: Monitor instance name
            strict: if True, a protocol violation raises JTAGProtocolError from
                    the monitoring task (fails the test); if False, violations
                    accumulate for report().
        """
        self.jtag_intf = jtag_intf
        self.name = name
        self.strict = strict
        self.log = jtag_intf._log if hasattr(jtag_intf, "_log") else None

        # Signal handles - access interface signals using standard JTAG naming
        self.tck = jtag_intf.tck
        self.tms = jtag_intf.tms
        self.tdi = jtag_intf.tdi
        self.tdo = jtag_intf.tdo
        self.tdo_oen = jtag_intf.tdo_oen
        self.trst = jtag_intf.trst

        # State tracking
        self.current_state = JTAG_TAP_State_e.TEST_LOGIC_RESET
        self.previous_state = JTAG_TAP_State_e.TEST_LOGIC_RESET
        self.state_history = deque(maxlen=1000)

        # Transaction tracking
        self.current_transaction: Optional[JTAGTransaction] = None
        self.completed_transactions: List[JTAGTransaction] = []
        self.current_instruction = None

        # Statistics
        self.stats = {
            "total_clocks": 0,
            "ir_transactions": 0,
            "dr_transactions": 0,
            "state_changes": 0,
            "resets": 0,
            "protocol_violations": 0,
        }

        # Violations
        self.violations: List[str] = []

        # Configuration
        self.log_level = logging.INFO
        self.max_transaction_history = 1000

        # Monitoring control
        self._monitoring = False
        self._monitor_task = None
        self._oen_task = None

    @staticmethod
    def _read_int(sig) -> Optional[int]:
        if sig is None:
            return None
        try:
            return int(sig.value)
        except ValueError:
            return None

    def _violation(self, msg: str):
        self.stats["protocol_violations"] += 1
        full = f"{self.name}: PROTOCOL VIOLATION - {msg}"
        self.violations.append(full)
        if self.log:
            self.log.error(full)
        if self.strict:
            raise JTAGProtocolError(full)

    def report(self):
        """Raise if any violation was recorded (non-strict/collect mode)."""
        if self.violations:
            raise JTAGProtocolError(
                f"{self.name}: {len(self.violations)} protocol violation(s):\n  " +
                "\n  ".join(self.violations))

    async def start_monitoring(self):
        """Start JTAG signal monitoring"""
        if self._monitoring:
            self.log.warning("Monitor already running")
            return

        self._monitoring = True
        self.log.info(f"Starting JTAG monitoring on {self.name}")

        # Start the monitoring coroutines
        self._monitor_task = cocotb.start_soon(self._monitor_signals())
        self._oen_task = cocotb.start_soon(self._monitor_tdo_oen())

        # Log initial state
        await Timer(1, units="ns")  # Small delay to ensure signals are stable
        self._log_state_change(self.current_state, self.current_state, force=True)

    async def stop_monitoring(self):
        """Stop JTAG signal monitoring"""
        if not self._monitoring:
            return

        self._monitoring = False
        if self._monitor_task:
            self._monitor_task.kill()
            self._monitor_task = None
        if self._oen_task:
            self._oen_task.kill()
            self._oen_task = None

        self.log.info(f"Stopped JTAG monitoring on {self.name}")
        self._print_summary()

    async def _monitor_signals(self):
        """Main monitoring coroutine"""
        try:
            while self._monitoring:
                # Wait for TCK rising edge
                await RisingEdge(self.tck)
                self.stats["total_clocks"] += 1

                # Sample signals
                tms_val = int(self.tms.value)
                tdi_val = int(self.tdi.value)
                tdo_val = int(self.tdo.value)

                # Check for reset
                if self.trst and int(self.trst.value) == 0:
                    await self._handle_reset()
                    continue

                # Update TAP state
                await self._update_tap_state(tms_val)

                # Process data based on current state
                await self._process_data_bits(tdi_val, tdo_val)

        except Exception as e:
            self.log.error(f"Monitor error: {e}")
        finally:
            if self.current_transaction:
                self._complete_current_transaction()

    async def _monitor_tdo_oen(self):
        """Check the PTAP client TDO output-enable never drives TDO while the
        TAP is quiescent.

        Per IEEE 1149.1 (and jtag_tap_ctrlr.sv: tdo_oen = state in
        {SHIFT_DR, SHIFT_IR}, registered on the TCK falling edge) TDO is
        actively driven only during the Shift states. Rather than assert the
        exact "only in Shift" bound — which the half-cycle-registered enable
        makes prone to NBA/boundary false-fires we cannot validate without a
        sim — this checks the robust, skew-immune invariant: TDO_OEN must NOT
        be asserted in Test-Logic-Reset or Run-Test/Idle, both of which are
        two or more TAP transitions away from any Shift state. That catches a
        real "TDO driven while idle/reset" bus-contention / leak bug. The
        tighter STAP-side property is covered by stap_sva_intf.sv.

        Sampled at the TCK falling edge (when the registered enable and the
        state are both settled), reading post-NBA values via ReadOnly.
        """
        quiescent = (JTAG_TAP_State_e.TEST_LOGIC_RESET, JTAG_TAP_State_e.RUN_TEST_IDLE)
        while self._monitoring:
            await FallingEdge(self.tck)
            await ReadOnly()
            if self.trst is not None and self._read_int(self.trst) == 0:
                continue  # in reset; TDO behavior is don't-care
            oen = self._read_int(self.tdo_oen)
            if oen is None:
                self._violation("TDO_OEN is X/Z out of reset")
                continue
            if oen == 1 and self.current_state in quiescent:
                self._violation(
                    f"TDO_OEN asserted while TAP quiescent (state={self.current_state.name}); "
                    f"TDO must not be driven outside Shift-DR/Shift-IR")

    async def _handle_reset(self):
        """Handle TRST assertion"""
        self.stats["resets"] += 1
        old_state = self.current_state
        self.current_state = JTAG_TAP_State_e.TEST_LOGIC_RESET
        self._log_state_change(old_state, self.current_state)

        if self.current_transaction:
            self.log.warning("Transaction interrupted by reset")
            self._complete_current_transaction()

    async def _update_tap_state(self, tms_val: int):
        """Update TAP state machine based on TMS value using BFM-style logic"""
        old_state = self.current_state

        self.current_state = JTAG_TAP_FSM.get_next_state(self.current_state, tms_val)

        if self.current_state != old_state:
            self.previous_state = old_state
            self.stats["state_changes"] += 1
            self._log_state_change(old_state, self.current_state)

            # Handle state-specific actions
            await self._handle_state_entry(self.current_state)

    async def _handle_state_entry(self, new_state: JTAG_TAP_State_e):
        """Handle actions when entering specific states"""
        sim_time = cocotb.utils.get_sim_time(units="ns")

        if new_state == JTAG_TAP_State_e.SHIFT_IR:
            # Start IR transaction
            if not self.current_transaction:
                self.current_transaction = JTAGTransaction(
                    transaction_type="IR", start_time=sim_time
                )
                self.log.debug("Started IR transaction")

        elif new_state == JTAG_TAP_State_e.SHIFT_DR:
            # Start DR transaction
            if not self.current_transaction:
                self.current_transaction = JTAGTransaction(
                    transaction_type="DR",
                    start_time=sim_time,
                    instruction=self.current_instruction,
                )
                self.log.debug("Started DR transaction")

        elif new_state == JTAG_TAP_State_e.UPDATE_IR:
            # Complete IR transaction
            if (
                self.current_transaction
                and self.current_transaction.transaction_type == "IR"
            ):
                self._complete_current_transaction()
                # Update current instruction
                if self.current_transaction:
                    self.current_instruction = self.current_transaction.tdi_value

        elif new_state == JTAG_TAP_State_e.UPDATE_DR:
            # Complete DR transaction
            if (
                self.current_transaction
                and self.current_transaction.transaction_type == "DR"
            ):
                self._complete_current_transaction()

        elif new_state == JTAG_TAP_State_e.TEST_LOGIC_RESET:
            # Reset state - complete any ongoing transaction
            if self.current_transaction:
                self.log.warning("Transaction interrupted by reset")
                self._complete_current_transaction()
            self.current_instruction = None

    async def _process_data_bits(self, tdi_val: int, tdo_val: int):
        """Process TDI/TDO data bits during shift states"""
        if self.current_transaction and self.current_state in [
            JTAG_TAP_State_e.SHIFT_IR,
            JTAG_TAP_State_e.SHIFT_DR,
        ]:
            self.current_transaction.tdi_data.append(tdi_val)
            self.current_transaction.tdo_data.append(tdo_val)
            self.current_transaction.bit_count += 1

    def _complete_current_transaction(self):
        """Complete the current transaction and add to history"""
        if not self.current_transaction:
            return

        self.current_transaction.end_time = cocotb.utils.get_sim_time(units="ns")

        # Update statistics
        if self.current_transaction.transaction_type == "IR":
            self.stats["ir_transactions"] += 1
        else:
            self.stats["dr_transactions"] += 1

        # Add to completed transactions
        self.completed_transactions.append(self.current_transaction)

        # Limit history size
        if len(self.completed_transactions) > self.max_transaction_history:
            self.completed_transactions.pop(0)

        # Log transaction completion
        self._log_transaction_complete(self.current_transaction)

        self.current_transaction = None

    def _log_state_change(
        self,
        old_state: JTAG_TAP_State_e,
        new_state: JTAG_TAP_State_e,
        force: bool = False,
    ):
        """Log TAP state changes"""
        # Add to history
        sim_time = cocotb.utils.get_sim_time(units="ns")
        self.state_history.append((sim_time, old_state, new_state))

        if force or self.log.level <= logging.DEBUG:
            if old_state != new_state:
                self.log.debug(f"State: {old_state.name} -> {new_state.name}")
            else:
                self.log.debug(f"State: {new_state.name}")

    def _log_transaction_complete(self, transaction: JTAGTransaction):
        """Log completed transaction"""
        log_msg = (
            f"{transaction.transaction_type} Transaction: "
            f"{transaction.bit_count} bits, "
            f"TDI=0x{transaction.tdi_value:X}, "
            f"TDO=0x{transaction.tdo_value:X}, "
            f"Duration={transaction.duration:.1f}ns"
        )

        if transaction.instruction is not None and transaction.transaction_type == "DR":
            log_msg += f", Instruction=0x{transaction.instruction:X}"

        self.log.info(log_msg)

    def _print_summary(self):
        """Print monitoring summary"""
        self.log.info("=== JTAG Monitor Summary ===")
        self.log.info(f"Total TCK cycles: {self.stats['total_clocks']}")
        self.log.info(f"State changes: {self.stats['state_changes']}")
        self.log.info(f"IR transactions: {self.stats['ir_transactions']}")
        self.log.info(f"DR transactions: {self.stats['dr_transactions']}")
        self.log.info(f"Resets: {self.stats['resets']}")
        self.log.info(f"Final state: {self.current_state.name}")

    # Analysis and utility methods

    def get_transaction_history(
        self, transaction_type: str = None
    ) -> List[JTAGTransaction]:
        """Get transaction history, optionally filtered by type"""
        if transaction_type is None:
            return self.completed_transactions.copy()
        return [
            tx
            for tx in self.completed_transactions
            if tx.transaction_type == transaction_type
        ]

    def get_current_state(self) -> JTAG_TAP_State_e:
        """Get current TAP state"""
        return self.current_state

    def get_state_history(
        self,
    ) -> List[Tuple[float, JTAG_TAP_State_e, JTAG_TAP_State_e]]:
        """Get state change history"""
        return list(self.state_history)

    def get_statistics(self) -> Dict[str, Any]:
        """Get monitoring statistics"""
        return self.stats.copy()

    def find_transactions_by_instruction(
        self, instruction: int
    ) -> List[JTAGTransaction]:
        """Find DR transactions with specific instruction"""
        return [
            tx
            for tx in self.completed_transactions
            if tx.transaction_type == "DR" and tx.instruction == instruction
        ]

    def get_instruction_usage(self) -> Dict[int, int]:
        """Get instruction usage statistics"""
        usage = {}
        for tx in self.completed_transactions:
            if tx.transaction_type == "DR" and tx.instruction is not None:
                usage[tx.instruction] = usage.get(tx.instruction, 0) + 1
        return usage

    def export_transactions_csv(self, filename: str):
        """Export transaction history to CSV file"""
        try:
            import csv

            with open(filename, "w", newline="") as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(
                    [
                        "Type",
                        "Start_Time",
                        "End_Time",
                        "Duration",
                        "Bit_Count",
                        "TDI_Value",
                        "TDO_Value",
                        "Instruction",
                    ]
                )

                for tx in self.completed_transactions:
                    writer.writerow(
                        [
                            tx.transaction_type,
                            tx.start_time,
                            tx.end_time,
                            tx.duration,
                            tx.bit_count,
                            f"0x{tx.tdi_value:X}",
                            f"0x{tx.tdo_value:X}",
                            f"0x{tx.instruction:X}"
                            if tx.instruction is not None
                            else "",
                        ]
                    )
            self.log.info(
                f"Exported {len(self.completed_transactions)} transactions to {filename}"
            )
        except Exception as e:
            self.log.error(f"Failed to export CSV: {e}")


# Convenience function for easy instantiation
def create_jtag_monitor(jtag_intf, name: str = "JTAG_Monitor",
                        strict: bool = True) -> JTAG_Monitor:
    """
    Create and return a JTAG monitor instance compatible with jtag_intf.sv

    Args:
        jtag_intf: JTAG interface handle (jtag_intf.sv instance)
        name: Monitor instance name
        strict: fail the test on a protocol violation (True) or accumulate for
                report() (False)

    Returns:
        JTAG_Monitor instance
    """
    return JTAG_Monitor(jtag_intf, name=name, strict=strict)


# Example usage in a CocoTB test:
"""
@cocotb.test()
async def test_with_jtag_monitor(dut):
    # Access the JTAG interface instance from the testbench
    jtag_intf = dut.jtag_ptap_if  # Assuming interface is named 'jtag_if' in testbench

    # Create JTAG monitor using the interface
    jtag_mon = create_jtag_monitor(jtag_intf, name="Main_JTAG_Monitor")

    # Start monitoring
    await jtag_mon.start_monitoring()

    # Run your test...
    await Timer(1000, units='ns')

    # Stop monitoring and get results
    await jtag_mon.stop_monitoring()

    # Analyze results
    ir_transactions = jtag_mon.get_transaction_history("IR")
    dr_transactions = jtag_mon.get_transaction_history("DR")

    print(f"Found {len(ir_transactions)} IR transactions")
    print(f"Found {len(dr_transactions)} DR transactions")

    # Export to CSV for further analysis
    jtag_mon.export_transactions_csv("jtag_transactions.csv")
"""
