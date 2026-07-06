/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include <stdint.h>

#include "smc_io.h"
#include "smc_test.h"

// AXI hang detector system-level sanity test.
//
// Configures each of the three SMC hang detectors (sys_axi, sep_axi,
// data_accel) through their smc_base_config CSRs and uses CTRL.irq_test to force the
// detector's irq high without needing a real bus stall. A cocotb sequence
// observes the OR'd fault output (smc_base.axi_hang_irq_o) after each phase to
// confirm every detector propagates independently and that the three irqs are
// OR'd correctly.
//
// Handshake: firmware writes the current phase id to scratch[5] and waits until
// the cocotb side echoes that id back in scratch[6] before advancing. cocotb
// checks axi_hang_irq_o for each phase, then acks.

#define STATUS_SCRATCH   5   // firmware -> cocotb: current phase id
#define ACK_SCRATCH      6   // cocotb -> firmware: acked phase id

// Publish a phase to cocotb and block until it acks the same id.
static inline void sync_phase(uint32_t phase) {
    write_scratch(STATUS_SCRATCH, phase);
    while (read_scratch(ACK_SCRATCH) != phase) {
        // spin until cocotb has checked this phase
    }
}

int main(void) {
    // CTRL value that forces a detector's irq high without a real bus stall:
    // enable + irq_en + irq_test.
    smc_base_config__HANG_DET_CTRL_t fire;
    fire.w        = 0;
    fire.f.enable   = 0x1;
    fire.f.irq_en   = 0x1;
    fire.f.irq_test = 0x1;

    // Phases start at 1: scratch[6] (the ack) resets to 0, so a phase-0 ack
    // would race (the wait would pass before cocotb acks). The first real phase
    // also serves as the "firmware booted" signal.

    // --- Per-detector propagation (others held off) ---
    // Phase 1: sys_axi fires -> expect axi_hang_irq_o == 1
    write_reg(SMC_TOP_SMC_BASE_CONFIG_HANG_DET_SYS_AXI_CTRL_BASE_ADDR,    fire.w);
    sync_phase(1);
    // Phase 2: clear -> expect 0
    write_reg(SMC_TOP_SMC_BASE_CONFIG_HANG_DET_SYS_AXI_CTRL_BASE_ADDR,    0);
    sync_phase(2);

    // Phase 3: sep_axi fires -> expect 1
    write_reg(SMC_TOP_SMC_BASE_CONFIG_HANG_DET_SEP_AXI_CTRL_BASE_ADDR,    fire.w);
    sync_phase(3);
    // Phase 4: clear -> expect 0
    write_reg(SMC_TOP_SMC_BASE_CONFIG_HANG_DET_SEP_AXI_CTRL_BASE_ADDR,    0);
    sync_phase(4);

    // Phase 5: data_accel fires -> expect 1
    write_reg(SMC_TOP_SMC_BASE_CONFIG_HANG_DET_DATA_ACCEL_CTRL_BASE_ADDR, fire.w);
    sync_phase(5);
    // Phase 6: clear -> expect 0
    write_reg(SMC_TOP_SMC_BASE_CONFIG_HANG_DET_DATA_ACCEL_CTRL_BASE_ADDR, 0);
    sync_phase(6);

    // --- OR behaviour ---
    // Phase 7: all three fire -> expect 1
    write_reg(SMC_TOP_SMC_BASE_CONFIG_HANG_DET_SYS_AXI_CTRL_BASE_ADDR,    fire.w);
    write_reg(SMC_TOP_SMC_BASE_CONFIG_HANG_DET_SEP_AXI_CTRL_BASE_ADDR,    fire.w);
    write_reg(SMC_TOP_SMC_BASE_CONFIG_HANG_DET_DATA_ACCEL_CTRL_BASE_ADDR, fire.w);
    sync_phase(7);
    // Phase 8: clear sys + sep, leave data_accel -> OR still 1
    write_reg(SMC_TOP_SMC_BASE_CONFIG_HANG_DET_SYS_AXI_CTRL_BASE_ADDR,    0);
    write_reg(SMC_TOP_SMC_BASE_CONFIG_HANG_DET_SEP_AXI_CTRL_BASE_ADDR,    0);
    sync_phase(8);
    // Phase 9: clear the last -> OR drops to 0
    write_reg(SMC_TOP_SMC_BASE_CONFIG_HANG_DET_DATA_ACCEL_CTRL_BASE_ADDR, 0);
    sync_phase(9);

    // --- Real bus stall (no irq_test) ---
    // Phase 10: arm the sep_axi detector with a real (small) threshold and let
    // cocotb create an actual outstanding-with-no-completion stall on sep_axi.
    // This proves the detector catches a genuine hang, not just the irq_test bit.
    smc_base_config__HANG_DET_TIMEOUT_THRESHOLD_t thr;
    thr.w     = 0;
    thr.f.value = 0x80;   // 128 cycles -> fires quickly under a real stall
    write_reg(SMC_TOP_SMC_BASE_CONFIG_HANG_DET_SEP_AXI_TIMEOUT_THRESHOLD_BASE_ADDR, thr.w);

    smc_base_config__HANG_DET_CTRL_t real_en;
    real_en.w      = 0;
    real_en.f.enable = 0x1;
    real_en.f.irq_en = 0x1;   // note: irq_test stays 0 -> only a real hang fires
    write_reg(SMC_TOP_SMC_BASE_CONFIG_HANG_DET_SEP_AXI_CTRL_BASE_ADDR, real_en.w);
    sync_phase(10);

    // Phase 11: same real-stall check on sys_axi. Disable sep_axi first so only
    // the sys_axi detector is armed when cocotb stalls the sys_axi (ext_in) bus.
    write_reg(SMC_TOP_SMC_BASE_CONFIG_HANG_DET_SEP_AXI_CTRL_BASE_ADDR,           0);
    write_reg(SMC_TOP_SMC_BASE_CONFIG_HANG_DET_SYS_AXI_TIMEOUT_THRESHOLD_BASE_ADDR, thr.w);
    write_reg(SMC_TOP_SMC_BASE_CONFIG_HANG_DET_SYS_AXI_CTRL_BASE_ADDR,           real_en.w);
    sync_phase(11);

    // Pass the test.
    test_pass(0);

    // Wait forever
    while (1) {
        __asm__("wfi");
    }

    return 0;
}

int secondary_main(void) {
    return main();
}