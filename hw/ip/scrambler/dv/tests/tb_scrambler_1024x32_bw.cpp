//-----------------------------------------------------------------------------
// Verilator Testbench Driver — scrambler_1024x32, BYTE_WISE=1
// Copyright 2026 Tenstorrent Inc.
//-----------------------------------------------------------------------------
#include "verilated.h"
#include "Vscrambler_1024x32.h"
#include "tb_scrambler_common.h"

int main(int argc, char** argv) {
    Verilated::commandArgs(argc, argv);
    Vscrambler_1024x32 dut;
    int rc = run_bytewise_tests(dut, 1024, "1024x32");
    dut.final();
    return rc ? 1 : 0;
}
