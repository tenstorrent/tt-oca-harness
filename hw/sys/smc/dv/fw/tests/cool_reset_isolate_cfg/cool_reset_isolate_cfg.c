/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include <stdint.h>

#include "smc_io.h"
#include "smc_test.h"

/* Scope: this image programs the cool-reset / FLR isolation configuration and
 * proves the configuration holds. It does not observe a cool reset -- firmware
 * cannot watch its own reset domain go down and come back. The runtime
 * behaviour that configuration selects is scored on the testbench side by
 * smc_cool_reset_from_pcie_test, which samples tb_isolate_req_o and
 * tb_rst_cool_from_flr across a real FLR.
 */

/* Readback-compare a plain storage register and count a mismatch as an error.
 *
 * Every ISOLATE_REQ_* register compared below is `sw = rw; hw = r;` over the
 * full [31:0] in hw/sys/smc/regs/blocks/reset_unit/reset_unit.rdl, so the value
 * written must read back bit for bit. `end_test()` passes iff `_ERROR_CNT == 0`,
 * so these are what give the test its fail path.
 */
static void check_reg(int hartid, uint64_t addr, uint32_t wrote, const char *name) {
    uint32_t got = read_reg(addr);

    if (got != wrote) {
        raise_error_s(hartid, name);
        info_msg_hex32_s(hartid, "  wrote: ", wrote);
        info_msg_hex32_s(hartid, "  read : ", got);
    }
}

int main(void) {

    int hartid = metal_cpu_get_current_hartid();

    init_test(hartid);

    reset_unit__ISOLATE_REQ_SMC_REG_t isolate_req_smc_reg;
    isolate_req_smc_reg.w = read_reg(SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_SMC_REG_BASE_ADDR);
    if (isolate_req_smc_reg.f.isolate_req_smc_reg == 1) {
        info_msg_s(hartid, "isolate_req_smc_reg set;  Clearing now");
        isolate_req_smc_reg.f.isolate_req_smc_reg = 0;
        write_reg(SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_SMC_REG_BASE_ADDR, isolate_req_smc_reg.w);
    }

    // Model the bringing up of all the SSs out of Cold Reset
    write_reg(SMC_TOP_SMC_RESET_UNIT_SS_COLD_RESET_N_BASE_ADDR, 0xFFFFFFFF);

    // Configure the FLR Count register
    uint32_t random_flr_counter = get_random_int() % 16;
    write_reg(SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_FLR_COUNTER_VALUE_BASE_ADDR, random_flr_counter);

    // FLR_RESET_COUNTER_VALUE is drawn from [2, 15]
    uint32_t random_flr_reset_counter = (get_random_int() % 14) + 2;

    write_reg(SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_FLR_RESET_COUNTER_VALUE_BASE_ADDR,
              random_flr_reset_counter);

    // Randomize the SMC-enable and pin-enable isolation masks
    uint32_t random_smcen = get_random_int();
    write_reg(SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_SMCEN_REG_BASE_ADDR, random_smcen);

    uint32_t random_pinen = get_random_int();
    write_reg(SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_PINEN_REG_BASE_ADDR, random_pinen);

    /* SS_COLD_RESET_N is not comparable here: smc_subsystem_resets.sv masks its
     * write with ~ss_cold_reset_lock, so a mismatch would be the lock doing its
     * job. ISOLATE_REQ_SMC_REG is not either -- it is hardware-set from
     * cfg_flr_pf_active, so a software clear can legitimately lose the race.
     * Both stay stimulus-only. */
    check_reg(hartid, SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_FLR_COUNTER_VALUE_BASE_ADDR,
              random_flr_counter, "ISOLATE_REQ_FLR_COUNTER_VALUE readback mismatch");
    check_reg(hartid, SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_FLR_RESET_COUNTER_VALUE_BASE_ADDR,
              random_flr_reset_counter, "ISOLATE_REQ_FLR_RESET_COUNTER_VALUE readback mismatch");
    check_reg(hartid, SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_SMCEN_REG_BASE_ADDR, random_smcen,
              "ISOLATE_REQ_SMCEN_REG readback mismatch");
    check_reg(hartid, SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_PINEN_REG_BASE_ADDR, random_pinen,
              "ISOLATE_REQ_PINEN_REG readback mismatch");

    end_test(hartid);

    while (true) {
        __asm__("wfi");
    }

    return 0;
}

int secondary_main(void) {
    /* Only hart 0 drives the sequence; the rest park. */
    if (metal_cpu_get_current_hartid() != 0) {
        while (true) {
            __asm__("wfi");
        }
    }

    return main();
}
