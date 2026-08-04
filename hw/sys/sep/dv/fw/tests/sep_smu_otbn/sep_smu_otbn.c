/*
 * sep_smu_otbn - SMU-level SEP OTBN CSR programming smoke test.
 *
 * This first SMU-level OTBN testcase only exercises benign CSR writes. Full
 * OTBN IMEM/DMEM load and EXECUTE flow can be layered on once the basic SMU
 * integration path is stable.
 */

#include <stdint.h>

#include "och_sep_common.h"
#include "och_sep_top_reg.h"
#include "sep_outbound_filter.h"

static volatile int g_otbn_status;

static int run_otbn_programming_sequence(void)
{
    WRITE_REG(OTBN_INTR_ENABLE_REG_ADDR, 0x1u);
    WRITE_REG(OTBN_INTR_STATE_REG_ADDR, 0xFFFFFFFFu);
    WRITE_REG(OTBN_ERR_BITS_REG_ADDR, 0xFFFFFFFFu);
    WRITE_REG(OTBN_INSN_CNT_REG_ADDR, 0xFFFFFFFFu);
    WRITE_REG(OTBN_LOAD_CHECKSUM_REG_ADDR, 0x0u);

    return g_otbn_status;
}

__attribute__((used, noinline, noreturn))
void smu_sep_otbn_pass_loop(void)
{
    while (1) {
        __asm__ volatile("wfi");
    }
}

__attribute__((used, noinline, noreturn))
void smu_sep_otbn_fail_loop(void)
{
    while (1) {
        __asm__ volatile("wfi");
    }
}

int main(void)
{
    sep_outbound_filter_init();
    if (run_otbn_programming_sequence() == 0) {
        smu_sep_otbn_pass_loop();
    } else {
        smu_sep_otbn_fail_loop();
    }
}
