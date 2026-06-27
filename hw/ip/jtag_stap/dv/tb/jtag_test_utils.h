/* SPDX-License-Identifier: Apache-2.0 */
/* (c) 2026 Tenstorrent USA Inc */

#ifndef JTAG_TEST_UTILS_H
#define JTAG_TEST_UTILS_H

#include <verilated.h>
#include <verilated_vcd_c.h>

/**
 * @file jtag_test_utils.h
 * @brief Shared utility functions for JTAG testbenches
 * 
 * This header provides common clock generation and timing utilities
 * used across all JTAG test modules.
 */

/**
 * @brief Advance the clock by one or more full cycles (falling edge then rising edge)
 * 
 * @tparam TopType The Verilator top module type (e.g., Vjtag_tap_tb)
 * @tparam TbType The testbench module type (e.g., Vjtag_tap_tb_jtag_tap_tb)
 * @param top Pointer to the top-level Verilator module
 * @param tb Pointer to the testbench module containing the tck signal
 * @param tfp Pointer to the VCD trace file
 * @param time_counter Reference to the simulation time counter
 * @param clock_period The clock period in simulation time units
 * @param cycles Number of clock cycles to advance (default: 1)
 */
template<typename TopType, typename TbType>
void advance_clock(TopType* top, TbType* tb, VerilatedVcdC* tfp, 
                   vluint64_t& time_counter, vluint64_t clock_period, int cycles = 1) {
    for (int i = 0; i < cycles; i++) {
        // Falling edge
        tb->tck = 0;
        top->eval();
        tfp->dump(time_counter);
        time_counter += clock_period/2;
        
        // Rising edge
        tb->tck = 1;
        top->eval();
        tfp->dump(time_counter);
        time_counter += clock_period/2;
    }
}

/**
 * @brief Advance the clock by one or more half cycles (toggle TCK state)
 * 
 * This function is useful for precise timing control, particularly
 * for checking signals that update on specific clock edges.
 * 
 * @tparam TopType The Verilator top module type
 * @tparam TbType The testbench module type containing the tck signal
 * @param top Pointer to the top-level Verilator module
 * @param tb Pointer to the testbench module
 * @param tfp Pointer to the VCD trace file
 * @param time_counter Reference to the simulation time counter
 * @param clock_period The clock period in simulation time units
 * @param half_cycles Number of half clock cycles to advance (default: 1)
 */
template<typename TopType, typename TbType>
void advance_half_clock(TopType* top, TbType* tb, VerilatedVcdC* tfp,
                        vluint64_t& time_counter, vluint64_t clock_period, int half_cycles = 1) {
    for (int i = 0; i < half_cycles; i++) {
        // Toggle TCK
        tb->tck = !tb->tck;
        top->eval();
        tfp->dump(time_counter);
        time_counter += clock_period/2;
    }
}

/**
 * @brief Initialize simulation timing and VCD tracing
 * 
 * @tparam TopType The Verilator top module type
 * @param top Pointer to the top-level Verilator module
 * @param tfp Pointer to the VCD trace file
 * @param vcd_filename Name of the VCD output file
 * @param time_counter Reference to the simulation time counter (will be initialized to 0)
 */
template<typename TopType>
void init_simulation(TopType* top, VerilatedVcdC* tfp, const char* vcd_filename,
                      vluint64_t& time_counter) {
    // Enable VCD tracing
    Verilated::traceEverOn(true);
    top->trace(tfp, 99);
    tfp->open(vcd_filename);
    
    // Initialize time
    time_counter = 0;
}

/**
 * @brief Finalize simulation and close VCD file
 * 
 * @param tfp Pointer to the VCD trace file
 */
inline void finalize_simulation(VerilatedVcdC* tfp) {
    tfp->close();
}

#endif // JTAG_TEST_UTILS_H

