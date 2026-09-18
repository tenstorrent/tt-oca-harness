/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

//-----------------------------------------------------------------------------
// File: test_jtag_stap_tb.cpp
// Description: Verilator C++ driver for JTAG STAP testbench
//              Clock driver for --timing mode; the test logic is in SystemVerilog
//-----------------------------------------------------------------------------

#include "Vjtag_stap_tb.h"
#include "Vjtag_stap_tb_jtag_stap_tb.h"
#include "verilated.h"
#include "verilated_vcd_c.h"
#include "jtag_test_utils.h"
#include <stdio.h>

int main(int argc, char **argv) {
    Verilated::commandArgs(argc, argv);
    Vjtag_stap_tb *top = new Vjtag_stap_tb;
    VerilatedVcdC *tfp = new VerilatedVcdC;
    vluint64_t time_counter;
    init_simulation(top, tfp, "jtag_stap_tb.vcd", time_counter);

    const vluint64_t clock_period = 10; // 10 time units = 100MHz

    // Clock generation loop - SystemVerilog runs tests and calls $finish
    while (!Verilated::gotFinish()) {
        // Generate clock edges for --timing mode
        top->jtag_stap_tb->tck = !top->jtag_stap_tb->tck;
        top->eval();
        tfp->dump(time_counter);
        time_counter += clock_period / 2;
    }

    // Cleanup
    finalize_simulation(tfp);
    delete top;
    delete tfp;

    return 0;
}
