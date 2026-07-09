/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*******************************************************************************
 * SEP eFuse JTAG/EL2 CPU mux arbitration firmware.
 *
 * The EL2 CPU continuously issues normal eFuse MMIO traffic while the UVM test
 * drives the SEP-local OTP JTAG AXI-Lite port. Scratch registers provide a
 * lightweight handshake and a loop counter visible to UVM.
 ******************************************************************************/

#include <stdint.h>
#include <stdio.h>

#include "efuse_fw_test_common.h"
#include "sep_outbound_filter.h"
#include "test_completion.h"

#define SYNC_CPU_READY_REG OCH_SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(0)
#define SYNC_UVM_DONE_REG OCH_SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(1)
#define SYNC_CPU_COUNT_REG OCH_SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(2)

#define CPU_READY_MARKER 0xE9050001u
#define UVM_DONE_MARKER 0xE90500D0u

#define MIN_CPU_EFUSE_LOOPS 256u
#define MAX_CPU_EFUSE_LOOPS 200000u

static void cpu_efuse_traffic_loop(void) {
    uint32_t loop_count = 0;
    uint32_t done = 0;

    while (loop_count < MAX_CPU_EFUSE_LOOPS) {
        uint32_t pattern = 0xE9051000u | (loop_count & 0x0FFFu);

        /*
         * Use MMR token input CSRs for side-effect-free normal eFuse traffic.
         * JTAG also targets this region in the paired UVM test, so both masters
         * meet at efuse_interface_controller.u_axi_lite_mux.
         */
        WRITE_REG(OCH_SEP_TOP_EFUSE_MMR_RMA_SIP_TOKEN_I_BASE_ADDR(1), pattern);
        (void)READ_REG(OCH_SEP_TOP_EFUSE_MMR_RMA_SIP_TOKEN_I_BASE_ADDR(1));
        (void)READ_REG(OCH_SEP_TOP_EFUSE_INTERFACE_CTRL_EFUSE_INTERFACE_CTRL_STATUS_BASE_ADDR);
        WRITE_REG(OCH_SEP_TOP_EFUSE_MMR_RMA_SIP_TOKEN_I_BASE_ADDR(2), pattern ^ 0x00FF00FFu);

        loop_count++;
        WRITE_REG(SYNC_CPU_COUNT_REG, loop_count);

        done = READ_REG(SYNC_UVM_DONE_REG);
        if (done == UVM_DONE_MARKER && loop_count >= MIN_CPU_EFUSE_LOOPS) {
            break;
        }
    }

    if (loop_count >= MAX_CPU_EFUSE_LOOPS) {
        printf("ERROR: UVM did not signal DONE, loop_count=%u\n", loop_count);
        test_fail(1);
    }

    printf("EL2 eFuse traffic loops completed: %u\n", loop_count);
}

int main(void) {
    sep_outbound_filter_init();

    printf("SEP eFuse JTAG/EL2 CPU mux arbitration FW test\n");

    if (efuse_wait_sense_done() != 0) {
        test_fail(1);
    }

    WRITE_REG(SYNC_UVM_DONE_REG, 0);
    WRITE_REG(SYNC_CPU_COUNT_REG, 0);
    WRITE_REG(SYNC_CPU_READY_REG, CPU_READY_MARKER);
    printf("CPU ready marker written: 0x%08x\n", CPU_READY_MARKER);

    cpu_efuse_traffic_loop();

    printf("*** SEP eFuse JTAG/EL2 CPU mux arbitration FW PASSED ***\n");
    test_pass(0);
    while (1) {
        __asm__("wfi");
    }
}
