# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""
JTAG Interface Usage Example for CocoTB

This example demonstrates how to use the unified JTAG interface (jtag_intf.sv)
with the JTAG BFM (jtag_mst_bfm.py) and Monitor (jtag_mon.py) in CocoTB tests.

The interface defines the standard signal naming convention:
- tck  : Test Clock 
- tms  : Test Mode Select
- tdi  : Test Data In
- tdo  : Test Data Out  
- trst : Test Reset (optional)

Author: Andrew Hsiao (ahsiao@tenstorrent.com)
"""

import cocotb
from cocotb.triggers import Timer, RisingEdge
from cocotb.clock import Clock
import logging

# Import JTAG components using unified interface
from jtag_vip.jtag_mst_bfm import JTAG_Master_BFM, TAPState
from jtag_vip.jtag_mon import create_jtag_monitor


@cocotb.test()
async def test_jtag_basic_operations(dut):
    """
    Basic JTAG test using the unified interface approach.
    
    This test demonstrates:
    1. Interface instantiation and access
    2. BFM and Monitor initialization using the interface
    3. Basic JTAG operations (reset, IR/DR scans)
    4. Transaction monitoring and analysis
    """
    
    # Access the JTAG interface from the testbench
    # The interface should be instantiated in your SystemVerilog testbench as 'jtag_ptap_if'
    jtag_intf = dut.jtag_ptap_if
    
    # Initialize logging
    dut._log.info("Starting JTAG test with unified interface")
    
    # Create JTAG BFM using the interface
    jtag_vip = JTAG_Master_BFM(jtag_intf, tck_period_ns=10)
    dut._log.info("JTAG BFM initialized with interface")
    
    # Create JTAG Monitor using the interface  
    jtag_mon = create_jtag_monitor(jtag_intf, name="Main_JTAG_Monitor")
    dut._log.info("JTAG Monitor initialized with interface")
    
    # Start monitoring JTAG transactions
    await jtag_mon.start_monitoring()
    dut._log.info("JTAG monitoring started")
    
    # Perform JTAG operations
    try:
        # 1. Reset the JTAG TAP
        await jtag_vip.reset()
        dut._log.info("JTAG reset completed")
        
        # 2. Perform Instruction Register scan
        ir_result = await jtag_vip.scan_ir(0x5, 4)  # 4-bit instruction
        dut._log.info(f"IR scan result: 0x{ir_result:X}")
        
        # 3. Perform Data Register scan  
        dr_result = await jtag_vip.scan_dr(0xDEADBEEF, 32)  # 32-bit data
        dut._log.info(f"DR scan result: 0x{dr_result:X}")
        
        # 4. Another IR scan with different instruction
        ir_result2 = await jtag_vip.scan_ir(0xA, 4)
        dut._log.info(f"Second IR scan result: 0x{ir_result2:X}")
        
        # 5. Burst of DR operations
        for i in range(3):
            data = 0x12345678 + i
            result = await jtag_vip.scan_dr(data, 32)
            dut._log.info(f"DR scan {i}: TDI=0x{data:X}, TDO=0x{result:X}")
        
        # Allow some time for final transactions to complete
        await Timer(100, units='ns')
        
    except Exception as e:
        dut._log.error(f"JTAG test error: {e}")
        raise
    
    finally:
        # Stop monitoring and analyze results
        await jtag_mon.stop_monitoring()
        dut._log.info("JTAG monitoring stopped")
        
        # Analyze the captured transactions
        ir_transactions = jtag_mon.get_transaction_history("IR")
        dr_transactions = jtag_mon.get_transaction_history("DR")
        
        dut._log.info(f"Captured {len(ir_transactions)} IR transactions")
        dut._log.info(f"Captured {len(dr_transactions)} DR transactions")
        
        # Detailed transaction analysis
        for i, tx in enumerate(ir_transactions):
            dut._log.info(f"IR Transaction {i}: TDI=0x{tx.tdi_value:X}, "
                         f"TDO=0x{tx.tdo_value:X}, Duration={tx.duration:.1f}ns")
        
        for i, tx in enumerate(dr_transactions):
            dut._log.info(f"DR Transaction {i}: TDI=0x{tx.tdi_value:X}, "
                         f"TDO=0x{tx.tdo_value:X}, Duration={tx.duration:.1f}ns")
        
        # Export results for further analysis
        jtag_mon.export_transactions_csv("jtag_test_results.csv")
        dut._log.info("Transaction data exported to CSV")
        
        # Get final statistics
        stats = jtag_mon.get_statistics()
        dut._log.info(f"Final statistics: {stats}")


@cocotb.test()
async def test_jtag_error_injection(dut):
    """
    Advanced JTAG test demonstrating error injection and monitoring.
    
    This test shows how to use the interface for more complex scenarios
    including error conditions and protocol violations.
    """
    
    # Access the JTAG interface
    jtag_intf = dut.jtag_ptap_if
    
    # Create components
    jtag_vip = JTAG_Master_BFM(jtag_intf, tck_period_ns=20)  # Slower clock
    jtag_mon = create_jtag_monitor(jtag_intf, name="Error_Test_Monitor")
    
    # Start monitoring
    await jtag_mon.start_monitoring()
    
    try:
        # Test with various error conditions
        dut._log.info("Testing JTAG error scenarios")
        
        # 1. Test reset behavior
        await jtag_vip.reset()
        current_state = jtag_mon.get_current_state()
        assert current_state == TAPState.RUN_TEST_IDLE, f"Expected IDLE state, got {current_state}"
        
        # 2. Test state machine navigation
        await jtag_vip.goto_state(TAPState.SHIFT_IR)
        current_state = jtag_mon.get_current_state()
        assert current_state == TAPState.SHIFT_IR, f"Expected SHIFT_IR, got {current_state}"
        
        # 3. Test interrupted transactions
        # (The BFM includes random interruption logic)
        for i in range(5):
            result = await jtag_vip.scan_dr(0xA5A5A5A5, 32)
            dut._log.info(f"Interrupted scan {i}: result=0x{result:X}")
        
        dut._log.info("Error injection test completed successfully")
        
    except Exception as e:
        dut._log.error(f"Error injection test failed: {e}")
        raise
    
    finally:
        await jtag_mon.stop_monitoring()
        
        # Analyze for any protocol violations or unexpected behavior
        stats = jtag_mon.get_statistics()
        dut._log.info(f"Error test statistics: {stats}")


@cocotb.test()  
async def test_jtag_concurrent_operations(dut):
    """
    Test concurrent JTAG operations using multiple BFM instances.
    
    This advanced test shows how multiple components can share
    the same interface for different operations.
    """
    
    # Access the JTAG interface
    jtag_intf = dut.jtag_ptap_if
    
    # Create multiple BFM instances (though only one should drive at a time)
    jtag_vip1 = JTAG_Master_BFM(jtag_intf, tck_period_ns=10)
    jtag_vip2 = JTAG_Master_BFM(jtag_intf, tck_period_ns=15)  # Different timing
    
    # Single monitor observes all activity
    jtag_mon = create_jtag_monitor(jtag_intf, name="Concurrent_Monitor")
    await jtag_mon.start_monitoring()
    
    try:
        # Sequential operations with different BFMs
        dut._log.info("Testing sequential BFM operations")
        
        # BFM1 operations
        await jtag_vip1.reset()
        await jtag_vip1.scan_ir(0x1, 4)
        await jtag_vip1.scan_dr(0x11111111, 32)
        
        # Switch to BFM2 (different timing characteristics)
        await jtag_vip2.goto_run_test_idle()  # Ensure clean state
        await jtag_vip2.scan_ir(0x2, 4)
        await jtag_vip2.scan_dr(0x22222222, 32)
        
        # Back to BFM1
        await jtag_vip1.scan_ir(0x3, 4)
        await jtag_vip1.scan_dr(0x33333333, 32)
        
        dut._log.info("Concurrent operations test completed")
        
    finally:
        await jtag_mon.stop_monitoring()
        
        # Analyze all transactions
        all_transactions = jtag_mon.get_transaction_history()
        dut._log.info(f"Total transactions observed: {len(all_transactions)}")
        
        # Group by transaction type
        ir_count = len(jtag_mon.get_transaction_history("IR"))
        dr_count = len(jtag_mon.get_transaction_history("DR"))
        dut._log.info(f"IR transactions: {ir_count}, DR transactions: {dr_count}")


# Utility function to demonstrate interface access patterns
def demonstrate_interface_access(dut):
    """
    Utility function showing different ways to access the JTAG interface
    and its signals in CocoTB tests.
    """
    
    # Method 1: Direct interface access
    jtag_intf = dut.jtag_ptap_if
    
    # Method 2: Access individual signals through interface
    tck_signal = jtag_intf.tck
    tms_signal = jtag_intf.tms
    tdi_signal = jtag_intf.tdi
    tdo_signal = jtag_intf.tdo
    trst_signal = jtag_intf.trst
    
    # Method 3: Check if interface has expected attributes
    required_signals = ['tck', 'tms', 'tdi', 'tdo', 'trst']
    for signal_name in required_signals:
        if hasattr(jtag_intf, signal_name):
            signal = getattr(jtag_intf, signal_name)
            print(f"Interface has {signal_name}: {signal}")
        else:
            print(f"WARNING: Interface missing {signal_name}")
    
    return jtag_intf


# Example of how the testbench SystemVerilog file should look:
"""
// Example testbench_top.sv
module testbench_top;

    // Instantiate the JTAG interface
    jtag_intf #(
        .ENABLE_TRST(1'b1)
    ) jtag_ptap_if ();
    
    // Instantiate your DUT and connect the interface
    your_dut dut (
        .jtag_tck(jtag_ptap_if.tck),
        .jtag_tms(jtag_ptap_if.tms),
        .jtag_tdi(jtag_ptap_if.tdi),
        .jtag_tdo(jtag_ptap_if.tdo),
        .jtag_trst(jtag_ptap_if.trst)
    );
    
    // CocoTB will access the interface as dut.jtag_ptap_if
    initial begin
        $dumpfile("jtag_test.vcd");
        $dumpvars(0, testbench_top);
    end

endmodule
"""
