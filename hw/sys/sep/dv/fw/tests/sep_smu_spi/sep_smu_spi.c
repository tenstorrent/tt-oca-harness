/*
 * sep_smu_spi - SMU-level SEP SPI write/read command test.
 *
 * Goal:
 *   Run a minimal OpenTitan SPI command sequence in SMU SEP_RTL mode without
 *   requiring an external flash model, then park the CPU in explicit pass/fail
 *   loops so the cocotb test can classify the result by SEP PC.
 */

#include <stdint.h>

#include "och_sep_common.h"
#include "sep_reg.h"
#include "sep_outbound_filter.h"

#define SPI_TIMEOUT 100000
#define SPI_OK 0
#define SPI_ERR_WAIT_READY_CMD 1
#define SPI_ERR_WAIT_IDLE_CMD 2
#define SPI_ERR_WAIT_READY_ADDR 3
#define SPI_ERR_WAIT_READY_RX 4
#define SPI_ERR_WAIT_IDLE_RX 5
#define SPI_ERR_STATUS 6

static void configure_spi_mux_ot(void)
{
    OCH_SEP_SPI_MUX_CTRL_SPI_MUX_CTRL_reg_u spi_mux = {
        .val = OCH_SEP_SPI_MUX_CTRL_SPI_MUX_CTRL_REG_DEFAULT
    };
    spi_mux.f.spi_sel = 1;       /* Route to OpenTitan SPI controller */
    spi_mux.f.cs_force_high = 0;
    WRITE_REG(SEP_AXI_EXTENSION_OCH_SEP_SPI_MUX_CTRL_SPI_MUX_CTRL_REG_ADDR, spi_mux.val);
}

static void spi_controller_init(void)
{
    SPI_CONTROLLER_CTRL_reg_u ctrl = {.val = SPI_CONTROLLER_CTRL_REG_DEFAULT};
    SPI_CONTROLLER_CFG_reg_u cfg = {.val = 0};

    ctrl.f.spien = 1;
    ctrl.f.output_en = 1;
    WRITE_REG(SPI_CONTROLLER_CTRL_REG_ADDR, ctrl.val);

    cfg.f.clkdiv = 9;
    cfg.f.cpol = 0;
    cfg.f.cpha = 0;
    cfg.f.csnidle = 2;
    cfg.f.csnlead = 2;
    cfg.f.csntrail = 2;
    WRITE_REG(SPI_CONTROLLER_CFG_REG_ADDR, cfg.val);

    WRITE_REG(SPI_CONTROLLER_CSID_REG_ADDR, 0);
    WRITE_REG(SPI_CONTROLLER_ERROR_STATUS_REG_ADDR, 0xFFFFFFFFu);
}

static int wait_ready(void)
{
    SPI_CONTROLLER_STATUS_reg_u status;
    int t = SPI_TIMEOUT;
    while (t-- > 0) {
        status.val = READ_REG(SPI_CONTROLLER_STATUS_REG_ADDR);
        if (status.f.ready) return 0;
    }
    return -1;
}

static int wait_idle(void)
{
    SPI_CONTROLLER_STATUS_reg_u status;
    int t = SPI_TIMEOUT;
    while (t-- > 0) {
        status.val = READ_REG(SPI_CONTROLLER_STATUS_REG_ADDR);
        if (!status.f.active) return 0;
    }
    return -1;
}

static int run_spi_txrx_sequence(void)
{
    SPI_CONTROLLER_CMD_reg_u cmd = {.val = 0};
    SPI_CONTROLLER_ERROR_STATUS_reg_u err = {.val = 0};

    configure_spi_mux_ot();
    spi_controller_init();

    /* Step 1: TX single-byte command (0x9F). */
    if (wait_ready() != 0) return SPI_ERR_WAIT_READY_CMD;
    WRITE_REG(SPI_CONTROLLER_TXDATA_REG_ADDR, 0x9F000000u);
    cmd.val = 0;
    cmd.f.len = 0;          /* one byte */
    cmd.f.csaat = 0;
    cmd.f.speed = 0;        /* standard */
    cmd.f.direction = 2;    /* TX */
    WRITE_REG(SPI_CONTROLLER_CMD_REG_ADDR, cmd.val);
    if (wait_idle() != 0) return SPI_ERR_WAIT_IDLE_CMD;

    /* Step 2: TX address phase (4 bytes) with CS held. */
    if (wait_ready() != 0) return SPI_ERR_WAIT_READY_ADDR;
    WRITE_REG(SPI_CONTROLLER_TXDATA_REG_ADDR, 0x03001000u);
    cmd.val = 0;
    cmd.f.len = 3;          /* four bytes */
    cmd.f.csaat = 1;        /* hold CS */
    cmd.f.speed = 0;
    cmd.f.direction = 2;    /* TX */
    WRITE_REG(SPI_CONTROLLER_CMD_REG_ADDR, cmd.val);

    /* Step 3: RX 4 bytes and release CS. */
    if (wait_ready() != 0) return SPI_ERR_WAIT_READY_RX;
    cmd.val = 0;
    cmd.f.len = 3;          /* four bytes */
    cmd.f.csaat = 0;        /* release CS */
    cmd.f.speed = 0;
    cmd.f.direction = 1;    /* RX */
    WRITE_REG(SPI_CONTROLLER_CMD_REG_ADDR, cmd.val);
    if (wait_idle() != 0) return SPI_ERR_WAIT_IDLE_RX;

    /* Hard failures: malformed command / invalid CSID. */
    err.val = READ_REG(SPI_CONTROLLER_ERROR_STATUS_REG_ADDR);
    if (err.f.cmdinval || err.f.csidinval) return SPI_ERR_STATUS;

    return SPI_OK;
}

/*
 * Exported labels for cocotb PC-based pass/fail classification.
 * Do not rename without updating smu_sep_spi_test.py symbol lookup.
 */
__attribute__((used, noinline, noreturn))
void smu_sep_spi_pass_loop(void)
{
    while (1) {
        __asm__ volatile("wfi");
    }
}

__attribute__((used, noinline, noreturn))
void smu_sep_spi_fail_loop(void)
{
    while (1) {
        __asm__ volatile("wfi");
    }
}

__attribute__((used, noinline, noreturn))
void smu_sep_spi_fail_wait_ready_cmd_loop(void)
{
    while (1) {
        __asm__ volatile("wfi");
    }
}

__attribute__((used, noinline, noreturn))
void smu_sep_spi_fail_wait_idle_cmd_loop(void)
{
    while (1) {
        __asm__ volatile("wfi");
    }
}

__attribute__((used, noinline, noreturn))
void smu_sep_spi_fail_wait_ready_addr_loop(void)
{
    while (1) {
        __asm__ volatile("wfi");
    }
}

__attribute__((used, noinline, noreturn))
void smu_sep_spi_fail_wait_ready_rx_loop(void)
{
    while (1) {
        __asm__ volatile("wfi");
    }
}

__attribute__((used, noinline, noreturn))
void smu_sep_spi_fail_wait_idle_rx_loop(void)
{
    while (1) {
        __asm__ volatile("wfi");
    }
}

__attribute__((used, noinline, noreturn))
void smu_sep_spi_fail_error_status_loop(void)
{
    while (1) {
        __asm__ volatile("wfi");
    }
}

int main(void)
{
    /*
     * Keep outbound filter init aligned with other SMU SEP tests. This test
     * does not rely on STDOUT for completion; cocotb keys off SEP PC symbols.
     */
    sep_outbound_filter_init();

    int rc = run_spi_txrx_sequence();

    if (rc == SPI_OK) smu_sep_spi_pass_loop();
    if (rc == SPI_ERR_WAIT_READY_CMD) smu_sep_spi_fail_wait_ready_cmd_loop();
    if (rc == SPI_ERR_WAIT_IDLE_CMD) smu_sep_spi_fail_wait_idle_cmd_loop();
    if (rc == SPI_ERR_WAIT_READY_ADDR) smu_sep_spi_fail_wait_ready_addr_loop();
    if (rc == SPI_ERR_WAIT_READY_RX) smu_sep_spi_fail_wait_ready_rx_loop();
    if (rc == SPI_ERR_WAIT_IDLE_RX) smu_sep_spi_fail_wait_idle_rx_loop();
    if (rc == SPI_ERR_STATUS) smu_sep_spi_fail_error_status_loop();

    smu_sep_spi_fail_loop();
}
