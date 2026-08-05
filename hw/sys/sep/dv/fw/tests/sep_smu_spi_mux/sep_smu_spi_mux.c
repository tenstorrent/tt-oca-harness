/*
 * sep_smu_spi_mux - Program SPI_MUX_CTRL via SEP CSR frontdoor only.
 *
 * Does not touch Cadence/OT SPI command paths (no external flash wait).
 *   spi_sel = 0 (Cadence), cs_force_high = 1
 */

#include <stdint.h>

#include "och_sep_common.h"
#include "sep.h"
#include "sep_outbound_filter.h"

#define SPI_MUX_CTRL_ADDR \
    OCH_SEP_TOP_SEP_AXI_EXTENSION_OCH_SEP_SPI_MUX_CTRL_SPI_MUX_CTRL_BASE_ADDR

static int program_spi_mux(void)
{
    och_sep_spi_mux_ctrl__SPI_MUX_CTRL_t mux = {
        .w = OCH_SEP_SPI_MUX_CTRL__SPI_MUX_CTRL_reset
    };
    /* Write-only: SPI_MUX readback can hang the AXI-extension path in SMU
     * SEP_RTL (same rationale as sep_smu_modules SPI_PROBE_MODE=0). */
    mux.f.spi_sel = 0;
    mux.f.cs_force_high = 1;
    WRITE_REG(SPI_MUX_CTRL_ADDR, mux.w);
    return 0;
}

__attribute__((used, noinline, noreturn))
void smu_sep_spi_mux_pass_loop(void)
{
    while (1) {
        __asm__ volatile("wfi");
        __asm__ volatile("nop");
    }
}

__attribute__((used, noinline, noreturn))
void smu_sep_spi_mux_fail_loop(void)
{
    while (1) {
        __asm__ volatile("wfi");
        __asm__ volatile("nop");
        __asm__ volatile("nop");
    }
}

/* Keep fail_loop alive for cocotb symbol classification (prevent ICF drop). */
static void (*const keep_fail)(void) = smu_sep_spi_mux_fail_loop;

int main(void)
{
    (void)keep_fail;
    sep_outbound_filter_init();
    if (program_spi_mux() == 0) {
        smu_sep_spi_mux_pass_loop();
    } else {
        keep_fail();
    }
}
