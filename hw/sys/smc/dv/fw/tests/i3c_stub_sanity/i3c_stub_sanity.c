/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// I3C stub sanity test.
//
// The I3C CSR windows (OCA_I3C_WRAP_0..5) are terminated by i3ccore_stub,
// which ends the I3C register interface with an AXI-Lite error slave that
// returns SLVERR.
//
// The purpose of this test is simply to confirm that accesses to the stubbed
// I3C register space COMPLETE and do not hang the CPU: an SLVERR response lets
// the core continue executing. If the interface were left dangling (ready/valid
// tied off) instead, the first access below would stall the bus forever and the
// test would time out. Reaching test_pass() therefore proves the accesses
// returned. (Bus-error trap behavior is intentionally out of scope here.)

#include <stdint.h>

#include "metal/cpu.h"
#include "smc_io.h"
#include "smc_test.h"
#include "virt_console.h"

// HCI lives at the I3C CSR base in both the open stub window and the vendor
// I3CCSR map the nonfree overlay substitutes.
#define I3C0_CSR_BASE SMC_TOP_OCA_I3C_WRAP_0_I3C_CSR_BASE_ADDR
#define I3C_HCI_VERSION_OFFSET 0x00
#define I3C_HC_CONTROL_OFFSET 0x04
#define I3C_HC_CAPABILITIES_OFFSET 0x0C
#define I3C_PRESENT_STATE_OFFSET 0x14
#define I3C_INTR_STATUS_ENABLE_OFFSET 0x24

// A handful of I3C wrapper (OCA_I3C_WRAP_0) registers to poke. Mix of
// read-only and read/write registers so we exercise both AXI read and write
// channels of the stub.
static const uint64_t I3C_READ_REGS[] = {
    I3C0_CSR_BASE + I3C_HCI_VERSION_OFFSET,
    I3C0_CSR_BASE + I3C_HC_CONTROL_OFFSET,
    I3C0_CSR_BASE + I3C_HC_CAPABILITIES_OFFSET,
    I3C0_CSR_BASE + I3C_PRESENT_STATE_OFFSET,
};

static const uint64_t I3C_WRITE_REGS[] = {
    I3C0_CSR_BASE + I3C_HC_CONTROL_OFFSET,
    I3C0_CSR_BASE + I3C_INTR_STATUS_ENABLE_OFFSET,
};

int main(void) {

    // Test runs on the primary hart (hart 0); status is reported on scratch 0.
    const int hartid = 0;

    simputs("[i3c_stub_sanity] Starting I3C stub access test\n");

    // Reads: each should return (with an SLVERR response under the hood) rather
    // than hang. We log the returned data for visibility but do not assert on it,
    // since the stub returns a fixed error-data pattern.
    for (uint32_t i = 0; i < (sizeof(I3C_READ_REGS) / sizeof(I3C_READ_REGS[0])); i++) {
        uint32_t val = read_reg(I3C_READ_REGS[i]);
        simputshex32("[i3c_stub_sanity] read I3C reg returned = ", val);
    }

    // Writes: each should be accepted/terminated by the stub without stalling.
    for (uint32_t i = 0; i < (sizeof(I3C_WRITE_REGS) / sizeof(I3C_WRITE_REGS[0])); i++) {
        write_reg(I3C_WRITE_REGS[i], 0xDEADBEEF);
        simputshex64("[i3c_stub_sanity] wrote I3C reg @ ", I3C_WRITE_REGS[i]);
    }

    // Read-after-write to confirm the bus is still alive after the writes.
    uint32_t readback =
        read_reg(I3C0_CSR_BASE + I3C_HC_CONTROL_OFFSET);
    simputshex32("[i3c_stub_sanity] post-write readback = ", readback);

    // If we got here, none of the I3C accesses hung the CPU.
    simputs("[i3c_stub_sanity] All I3C stub accesses completed - PASS\n");
    test_pass(hartid);

    while (true) {
        __asm__("wfi");
    }

    return 0;
}

int other_main(int hartid) {
    // Non-primary harts stay idle so they don't access the bus or print to the
    // shared console (which would interleave/corrupt the primary hart's output).
    (void)hartid;
    while (true) {
        __asm__("wfi");
    }
}

int secondary_main(void) {
    int hartid = metal_cpu_get_current_hartid();

    if (hartid == 0) {
        return main();
    } else {
        return other_main(hartid);
    }
}
