/*
 * sep_smu_remap - SMU-level SEP AP/STEE output-remap CSR frontdoor.
 *
 * Programs region-0 offsets via AXI-lite CSR (no TB Force of remap_table),
 * then parks in pass/fail loops for cocotb PC classification.
 *
 * Known offsets (must match cocotb golden check):
 *   AP   region0 = 0x00ABC00000
 *   STEE region0 = 0x0055000000
 */

#include <stdint.h>

#include "och_sep_common.h"
#include "och_sep_top_reg.h"
#include "sep_outbound_filter.h"

#define AP_REGION0_OFFSET   0x00ABC00000ull
#define STEE_REGION0_OFFSET 0x0055000000ull

static int program_output_remap(void)
{
    OUTPUT_REMAP_REGION_REGION_ATTRS_reg_u ap;
    OUTPUT_REMAP_REGION_REGION_ATTRS_reg_u stee;

    /* Write-only programming; cocotb observes remap_table after pass_loop. */
    ap.val = 0;
    ap.f.offset = AP_REGION0_OFFSET;
    WRITE_REG64(AP_OUTPUT_REMAP_CTRL_0__REGION_REGION_ATTRS_REG_ADDR, ap.val);

    stee.val = 0;
    stee.f.offset = STEE_REGION0_OFFSET;
    WRITE_REG64(STEE_OUTPUT_REMAP_CTRL_0__REGION_REGION_ATTRS_REG_ADDR, stee.val);

    return 0;
}

__attribute__((used, noinline, noreturn))
void smu_sep_remap_pass_loop(void)
{
    while (1) {
        __asm__ volatile("wfi");
        __asm__ volatile("nop");
    }
}

/* Distinct body from pass_loop so ICF cannot fold the symbols together. */
__attribute__((used, noinline, noreturn))
void smu_sep_remap_fail_loop(void)
{
    while (1) {
        __asm__ volatile("wfi");
        __asm__ volatile("nop");
        __asm__ volatile("nop");
    }
}

static void (*const keep_fail)(void) = smu_sep_remap_fail_loop;

int main(void)
{
    (void)keep_fail;
    sep_outbound_filter_init();
    if (program_output_remap() == 0) {
        smu_sep_remap_pass_loop();
    } else {
        keep_fail();
    }
}
