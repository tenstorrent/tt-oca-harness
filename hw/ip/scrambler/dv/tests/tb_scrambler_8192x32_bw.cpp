/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

//-----------------------------------------------------------------------------
// Verilator Testbench Driver — scrambler_8192x32, BYTE_WISE=1
// Copyright 2026 Tenstorrent Inc.
//-----------------------------------------------------------------------------
#include "verilated.h"
#include "Vscrambler_8192x32.h"
#include "tb_scrambler_common.h"

int main(int argc, char **argv) {
    Verilated::commandArgs(argc, argv);
    Vscrambler_8192x32 dut;
    int rc = run_bytewise_tests(dut, 8192, "8192x32");
    dut.final();
    return rc ? 1 : 0;
}
