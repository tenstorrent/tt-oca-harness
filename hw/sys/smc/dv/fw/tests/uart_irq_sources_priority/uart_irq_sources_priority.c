#include <stdint.h>

#include "metal/uart.h"
#include "smc_io.h"
#include "smc_test.h"

// UART interrupt ID mapping (IIR.interrupt_id).
// Corresponds to the RTL `IntrID` enum and the specification's priority:
// FIFO_ERROR(0x7) > RECEIVER_LINE_STATUS(0x3) > RECEPTION_TIMEOUT(0x6) >
// RECEIVED_DATA_READY(0x2) > THR_EMPTY(0x1) > MODEM_STATUS(0x0)
#define UART_INTR_ID_FIFO_ERROR                       (0x7u)
#define UART_INTR_ID_RECEIVER_LINE_STATUS             (0x3u)
#define UART_INTR_ID_RECEPTION_TIMEOUT                (0x6u)
#define UART_INTR_ID_RECEIVED_DATA_READY              (0x2u)
#define UART_INTR_ID_TRANSMITTER_HOLDING_REGISTER_EMPTY (0x1u)
#define UART_INTR_ID_MODEM_STATUS                     (0x0u)

// Get UART register map base (same style as other UART tests).
static inline uint32_t get_uart_reg_base(uint32_t idx)
{
    if (idx == 0) return SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0);
    if (idx == 1) return SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(1);
    if (idx == 2) return SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(2);
    return SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(3);
}

static inline uint32_t get_uart_ctrl_reg_addr(uint32_t idx)
{
    if (idx == 0) return SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LOG_ENGINE_CTRL_CTRL_BASE_ADDR(0);
    if (idx == 1) return SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LOG_ENGINE_CTRL_CTRL_BASE_ADDR(1);
    if (idx == 2) return SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LOG_ENGINE_CTRL_CTRL_BASE_ADDR(2);
    return SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LOG_ENGINE_CTRL_CTRL_BASE_ADDR(3);
}

static void uart_enable_single(uint32_t idx)
{
    uart_log_engine_ctrl__CTRL_t uart_enables;
    uart_enables.w = read_reg(SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LOG_ENGINE_CTRL_CTRL_BASE_ADDR(0));
    uart_enables.f.UART_EN = 0x1;

    uint32_t ctrl_addr = get_uart_ctrl_reg_addr(idx);
    write_reg(ctrl_addr, uart_enables.w);
}

// Clear IER/ITR/IIR/LSR/MSR to a known state to avoid residue from previous subtests.
static void uart_clear_all_status(uint32_t uart_base)
{
    uart_16550_main__IER_t ier;
    uart_16550_main__ITR_t itr;
    uart_16550_main__IIR_t iir;

    ier.w = 0;
    itr.w = 0;

    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IER_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)), ier.w);
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ITR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)), itr.w);

    // Read IIR/LSR/MSR to clear any existing status (if present).
    (void)read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LSR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
    (void)read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_MSR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));

    // Read IIR until there is no pending interrupt or until the loop limit is reached.
    for (int i = 0; i < 8; i++) {
        iir.w = read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IIR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
        if (iir.f.INTERRUPT_PENDING != 0u) {
            break;
        }
    }
}

// Simply poll IIR, wait for a pending interrupt, and return the last-read IIR.
static uart_16550_main__IIR_t uart_poll_iir(uint32_t uart_base, int max_iters)
{
    uart_16550_main__IIR_t iir;

    for (int i = 0; i < max_iters; i++) {
        iir.w = read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IIR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
        if (iir.f.INTERRUPT_PENDING == 0u) {
            return iir;
        }
    }

    return iir;
}

// Subtest A: IER gating and single interrupt-source mapping.
static int uart_test_ier_gating_and_mapping(uint32_t uart_base)
{
    uart_16550_main__IER_t ier;
    uart_16550_main__ITR_t itr;
    uart_16550_main__IIR_t iir;
    uart_clear_all_status(uart_base);

    ier.w = 0;
    itr.w = 0;

    // Modem Status
    // 1. Gating: when IER is disabled, this ID should not be seen.
    ier.w = 0;
    itr.w = 0;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IER_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)), ier.w);
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ITR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)), itr.w);
    itr.f.TDSSI = 1;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ITR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)), itr.w);
    iir = uart_poll_iir(uart_base, 8);
    if ((iir.f.INTERRUPT_PENDING == 0u) && (iir.f.INTERRUPT_ID == UART_INTR_ID_MODEM_STATUS)) {
        return -10;
    }
    // 2. Mapping: when IER is enabled, the IIR ID should match the expected value.
    itr.w = 0;
    ier.w = 0;
    ier.f.EDSSI = 1;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IER_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)), ier.w);
    itr.f.TDSSI = 1;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ITR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)), itr.w);
    iir = uart_poll_iir(uart_base, 16);
    if (iir.f.INTERRUPT_PENDING != 0u) {
        return -(10 + 1);
    }
    if (iir.f.INTERRUPT_ID != UART_INTR_ID_MODEM_STATUS) {
        return -(10 + 2);
    }
    // 3. Clear ITR so it does not affect the next test.
    itr.w = 0;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ITR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)), itr.w);

    // THR Empty
    ier.w = 0;
    itr.w = 0;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IER_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)), ier.w);
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ITR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)), itr.w);
    itr.f.TTBEI = 1;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ITR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)), itr.w);
    iir = uart_poll_iir(uart_base, 8);
    if ((iir.f.INTERRUPT_PENDING == 0u) && (iir.f.INTERRUPT_ID == UART_INTR_ID_TRANSMITTER_HOLDING_REGISTER_EMPTY)) {
        return -20;
    }
    itr.w = 0;
    ier.w = 0;
    ier.f.ETBEI = 1;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IER_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)), ier.w);
    itr.f.TTBEI = 1;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ITR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)), itr.w);
    iir = uart_poll_iir(uart_base, 16);
    if (iir.f.INTERRUPT_PENDING != 0u) {
        return -(20 + 1);
    }
    if (iir.f.INTERRUPT_ID != UART_INTR_ID_TRANSMITTER_HOLDING_REGISTER_EMPTY) {
        return -(20 + 2);
    }
    itr.w = 0;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ITR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)), itr.w);

    // RX Data Ready
    ier.w = 0;
    itr.w = 0;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IER_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)), ier.w);
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ITR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)), itr.w);
    itr.f.TRBFI = 1;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ITR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)), itr.w);
    iir = uart_poll_iir(uart_base, 8);
    if ((iir.f.INTERRUPT_PENDING == 0u) && (iir.f.INTERRUPT_ID == UART_INTR_ID_RECEIVED_DATA_READY)) {
        return -30;
    }
    itr.w = 0;
    ier.w = 0;
    ier.f.ERBFI = 1;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IER_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)), ier.w);
    itr.f.TRBFI = 1;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ITR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)), itr.w);
    iir = uart_poll_iir(uart_base, 16);
    if (iir.f.INTERRUPT_PENDING != 0u) {
        return -(30 + 1);
    }
    if (iir.f.INTERRUPT_ID != UART_INTR_ID_RECEIVED_DATA_READY) {
        return -(30 + 2);
    }
    itr.w = 0;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ITR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)), itr.w);

    // RX Timeout (only verify mapping; IER gating is not tested because the RTL design bypasses IER for this).
    itr.w = 0;
    ier.w = 0;
    ier.f.ERBFI = 1;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IER_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)), ier.w);
    itr.f.TRTI = 1;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ITR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)), itr.w);
    iir = uart_poll_iir(uart_base, 16);
    if (iir.f.INTERRUPT_PENDING != 0u) {
        simputs("  [A][RX Timeout][mapping] no pending interrupt seen\n");
        simputshex32("    IER = 0x", ier.w);
        simputshex32("    ITR = 0x", itr.w);
        simputshex32("    IIR = 0x", iir.w);
        simputs("\n");
        return -(40 + 1);
    }
    if (iir.f.INTERRUPT_ID != UART_INTR_ID_RECEPTION_TIMEOUT) {
        simputs("  [A][RX Timeout][mapping] interrupt ID mismatched\n");
        simputshex32("    IER = 0x", ier.w);
        simputshex32("    ITR = 0x", itr.w);
        simputshex32("    IIR = 0x", iir.w);
        simputshex32("    expected ID = 0x", UART_INTR_ID_RECEPTION_TIMEOUT);
        simputshex32("    got ID      = 0x", iir.f.INTERRUPT_ID);
        simputs("\n");
        return -(40 + 2);
    }
    itr.w = 0;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ITR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)), itr.w);

    // Line Status
    ier.w = 0;
    itr.w = 0;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IER_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)), ier.w);
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ITR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)), itr.w);
    itr.f.TLSI = 1;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ITR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)), itr.w);
    iir = uart_poll_iir(uart_base, 8);
    if ((iir.f.INTERRUPT_PENDING == 0u) && (iir.f.INTERRUPT_ID == UART_INTR_ID_RECEIVER_LINE_STATUS)) {
        return -50;
    }
    itr.w = 0;
    ier.w = 0;
    ier.f.ELSI = 1;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IER_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)), ier.w);
    itr.f.TLSI = 1;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ITR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)), itr.w);
    iir = uart_poll_iir(uart_base, 16);
    if (iir.f.INTERRUPT_PENDING != 0u) {
        return -(50 + 1);
    }
    if (iir.f.INTERRUPT_ID != UART_INTR_ID_RECEIVER_LINE_STATUS) {
        return -(50 + 2);
    }
    itr.w = 0;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ITR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)), itr.w);

    // FIFO Error
    ier.w = 0;
    itr.w = 0;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IER_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)), ier.w);
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ITR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)), itr.w);
    itr.f.TFEI = 1;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ITR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)), itr.w);
    iir = uart_poll_iir(uart_base, 8);
    if ((iir.f.INTERRUPT_PENDING == 0u) && (iir.f.INTERRUPT_ID == UART_INTR_ID_FIFO_ERROR)) {
        return -60;
    }
    itr.w = 0;
    ier.w = 0;
    ier.f.EFEI = 1;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IER_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)), ier.w);
    itr.f.TFEI = 1;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ITR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)), itr.w);
    iir = uart_poll_iir(uart_base, 16);
    if (iir.f.INTERRUPT_PENDING != 0u) {
        return -(60 + 1);
    }
    if (iir.f.INTERRUPT_ID != UART_INTR_ID_FIFO_ERROR) {
        return -(60 + 2);
    }
    itr.w = 0;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ITR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)), itr.w);

    return 0;
}

// Subtest B: clear behavior for each interrupt source (simplified).
static int uart_test_clear_behaviour(uint32_t uart_base)
{
    uart_16550_main__IER_t ier;
    uart_16550_main__ITR_t itr;
    uart_16550_main__IIR_t iir;
    uart_16550_main__LSR_t lsr;
    uart_16550_main__MSR_t msr;

    uart_clear_all_status(uart_base);

    // RX Data Ready: read LSR & RBR to clear.
    ier.w = 0;
    itr.w = 0;
    ier.f.ERBFI = 1;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IER_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)), ier.w);
    itr.f.TRBFI = 1;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ITR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)), itr.w);
    iir = uart_poll_iir(uart_base, 16);
    if ((iir.f.INTERRUPT_PENDING != 0u) || (iir.f.INTERRUPT_ID != UART_INTR_ID_RECEIVED_DATA_READY)) {
        return -100;
    }
    lsr.w = read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LSR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
    (void)lsr.w;
    (void)read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_RBR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
    itr.w = 0;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ITR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)), itr.w);
    iir.w = read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IIR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
    if ((iir.f.INTERRUPT_PENDING == 0u) && (iir.f.INTERRUPT_ID == UART_INTR_ID_RECEIVED_DATA_READY)) {
        return -(100 + 1);
    }

    // RX Timeout: read LSR & RBR to clear.
    ier.w = 0;
    itr.w = 0;
    ier.f.ERBFI = 1;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IER_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)), ier.w);
    itr.f.TRTI = 1;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ITR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)), itr.w);
    iir = uart_poll_iir(uart_base, 16);
    if ((iir.f.INTERRUPT_PENDING != 0u) || (iir.f.INTERRUPT_ID != UART_INTR_ID_RECEPTION_TIMEOUT)) {
        return -110;
    }
    lsr.w = read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LSR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
    (void)lsr.w;
    (void)read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_RBR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
    itr.w = 0;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ITR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)), itr.w);
    iir.w = read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IIR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
    if ((iir.f.INTERRUPT_PENDING == 0u) && (iir.f.INTERRUPT_ID == UART_INTR_ID_RECEPTION_TIMEOUT)) {
        return -(110 + 1);
    }

    // THR Empty: write THR to clear.
    ier.w = 0;
    itr.w = 0;
    ier.f.ETBEI = 1;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IER_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)), ier.w);
    itr.f.TTBEI = 1;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ITR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)), itr.w);
    iir = uart_poll_iir(uart_base, 16);
    if ((iir.f.INTERRUPT_PENDING != 0u) || (iir.f.INTERRUPT_ID != UART_INTR_ID_TRANSMITTER_HOLDING_REGISTER_EMPTY)) {
        return -120;
    }
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_RBR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)), 0x5Au);
    itr.w = 0;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ITR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)), itr.w);
    iir.w = read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IIR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
    if ((iir.f.INTERRUPT_PENDING == 0u) && (iir.f.INTERRUPT_ID == UART_INTR_ID_TRANSMITTER_HOLDING_REGISTER_EMPTY)) {
        return -(120 + 1);
    }

    // Line Status: read LSR to clear.
    ier.w = 0;
    itr.w = 0;
    ier.f.ELSI = 1;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IER_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)), ier.w);
    itr.f.TLSI = 1;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ITR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)), itr.w);
    iir = uart_poll_iir(uart_base, 16);
    if ((iir.f.INTERRUPT_PENDING != 0u) || (iir.f.INTERRUPT_ID != UART_INTR_ID_RECEIVER_LINE_STATUS)) {
        return -130;
    }
    lsr.w = read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LSR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
    (void)lsr.w;
    itr.w = 0;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ITR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)), itr.w);
    iir.w = read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IIR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
    if ((iir.f.INTERRUPT_PENDING == 0u) && (iir.f.INTERRUPT_ID == UART_INTR_ID_RECEIVER_LINE_STATUS)) {
        return -(130 + 1);
    }

    // Modem Status: read MSR to clear.
    ier.w = 0;
    itr.w = 0;
    ier.f.EDSSI = 1;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IER_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)), ier.w);
    itr.f.TDSSI = 1;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ITR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)), itr.w);
    iir = uart_poll_iir(uart_base, 16);
    if ((iir.f.INTERRUPT_PENDING != 0u) || (iir.f.INTERRUPT_ID != UART_INTR_ID_MODEM_STATUS)) {
        return -140;
    }
    msr.w = read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_MSR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
    (void)msr.w;
    itr.w = 0;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ITR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)), itr.w);
    iir.w = read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IIR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
    if ((iir.f.INTERRUPT_PENDING == 0u) && (iir.f.INTERRUPT_ID == UART_INTR_ID_MODEM_STATUS)) {
        return -(140 + 1);
    }

    // FIFO Error: read LSR (error bits) to clear.
    ier.w = 0;
    itr.w = 0;
    ier.f.EFEI = 1;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IER_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)), ier.w);
    itr.f.TFEI = 1;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ITR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)), itr.w);
    iir = uart_poll_iir(uart_base, 16);
    if ((iir.f.INTERRUPT_PENDING != 0u) || (iir.f.INTERRUPT_ID != UART_INTR_ID_FIFO_ERROR)) {
        return -150;
    }
    lsr.w = read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LSR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
    (void)lsr.w;
    itr.w = 0;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ITR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)), itr.w);
    iir.w = read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IIR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
    if ((iir.f.INTERRUPT_PENDING == 0u) && (iir.f.INTERRUPT_ID == UART_INTR_ID_FIFO_ERROR)) {
        return -(150 + 1);
    }

    return 0;
}

// Subtest C: verify priority when multiple interrupt sources are pending.
static int uart_test_priority(uint32_t uart_base)
{
    uart_16550_main__IER_t ier;
    uart_16550_main__ITR_t itr;
    uart_16550_main__IIR_t iir;

    uart_clear_all_status(uart_base);

    // LSR(0x3) vs RDR(0x2) -> expected 0x3.
    ier.w = 0;
    itr.w = 0;
    ier.f.ELSI = 1;
    ier.f.ERBFI = 1;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IER_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)), ier.w);
    itr.f.TLSI = 1;
    itr.f.TRBFI = 1;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ITR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)), itr.w);
    iir = uart_poll_iir(uart_base, 16);
    if (iir.f.INTERRUPT_PENDING != 0u) {
        return -200;
    }
    if (iir.f.INTERRUPT_ID != UART_INTR_ID_RECEIVER_LINE_STATUS) {
        return -(200 + 1);
    }
    itr.w = 0;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ITR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)), itr.w);
    uart_clear_all_status(uart_base);

    // RDR(0x2) vs THRE(0x1) -> expected 0x2.
    ier.w = 0;
    itr.w = 0;
    ier.f.ERBFI = 1;
    ier.f.ETBEI = 1;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IER_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)), ier.w);
    itr.f.TRBFI = 1;
    itr.f.TTBEI = 1;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ITR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)), itr.w);
    iir = uart_poll_iir(uart_base, 16);
    if (iir.f.INTERRUPT_PENDING != 0u) {
        return -210;
    }
    if (iir.f.INTERRUPT_ID != UART_INTR_ID_RECEIVED_DATA_READY) {
        return -(210 + 1);
    }
    itr.w = 0;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ITR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)), itr.w);
    uart_clear_all_status(uart_base);

    // THRE(0x1) vs Modem(0x0) -> expected 0x1.
    ier.w = 0;
    itr.w = 0;
    ier.f.ETBEI = 1;
    ier.f.EDSSI = 1;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IER_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)), ier.w);
    itr.f.TTBEI = 1;
    itr.f.TDSSI = 1;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ITR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)), itr.w);
    iir = uart_poll_iir(uart_base, 16);
    if (iir.f.INTERRUPT_PENDING != 0u) {
        return -220;
    }
    if (iir.f.INTERRUPT_ID != UART_INTR_ID_TRANSMITTER_HOLDING_REGISTER_EMPTY) {
        return -(220 + 1);
    }
    itr.w = 0;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ITR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)), itr.w);
    uart_clear_all_status(uart_base);

    // Timeout(0x6) vs RDR(0x2) -> expected 0x6.
    ier.w = 0;
    itr.w = 0;
    ier.f.ERBFI = 1;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IER_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)), ier.w);
    itr.f.TRBFI = 1;
    itr.f.TRTI  = 1;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ITR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)), itr.w);
    iir = uart_poll_iir(uart_base, 16);
    if (iir.f.INTERRUPT_PENDING != 0u) {
        return -230;
    }
    if (iir.f.INTERRUPT_ID != UART_INTR_ID_RECEPTION_TIMEOUT) {
        return -(230 + 1);
    }
    itr.w = 0;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ITR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)), itr.w);
    uart_clear_all_status(uart_base);

    // FIFO Error(0x7) vs Line Status(0x3) -> expected 0x7.
    ier.w = 0;
    itr.w = 0;
    ier.f.ELSI = 1;
    ier.f.EFEI = 1;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IER_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)), ier.w);
    itr.f.TLSI = 1;
    itr.f.TFEI = 1;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ITR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)), itr.w);
    iir = uart_poll_iir(uart_base, 16);
    if (iir.f.INTERRUPT_PENDING != 0u) {
        return -240;
    }
    if (iir.f.INTERRUPT_ID != UART_INTR_ID_FIFO_ERROR) {
        return -(240 + 1);
    }
    itr.w = 0;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ITR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)), itr.w);
    uart_clear_all_status(uart_base);

    return 0;
}

int main(void)
{
    // To control simulation time, this test only verifies interrupt sources and priority for a single UART instance (index 0).
    uint32_t uart_idx  = 0;
    uint32_t uart_base = get_uart_reg_base(uart_idx);
    int ret;

    // peripherals_out_of_reset();

    // Enable the UART under test.
    uart_enable_single(uart_idx);

    simputs("\n");
    simputs("############################################\n");
    simputs("##   UART IRQ Sources & Priority Test    ##\n");
    simputs("############################################\n");
    simputs("\n");

    simputs("UART IRQ test: start\n");
    simputshex32("  uart_idx  = ", uart_idx);
    simputshex32("  uart_base = 0x", uart_base);
    simputs("\n");

    // Subtest A: IER gating + single-source mapping.
    simputs("Subtest A: IER gating & single-source mapping ...\n");
    ret = uart_test_ier_gating_and_mapping(uart_base);
    if (ret != 0) {
        simputs("Subtest A FAILED\n");
        simputshex32("  error code = ", (uint32_t)ret);
        simputs("\n");
        write_scratch(0, 0xBAD0A000);
        test_fail(0);
    }
    simputs("Subtest A PASSED\n");

    // Subtest B: clear behavior for each interrupt source.
    simputs("Subtest B: clear behaviour for each source ...\n");
    ret = uart_test_clear_behaviour(uart_base);
    if (ret != 0) {
        simputs("Subtest B FAILED\n");
        simputshex32("  error code = ", (uint32_t)ret);
        simputs("\n");
        write_scratch(0, 0xBAD0B000);
        test_fail(0);
    }
    simputs("Subtest B PASSED\n");

    // Subtest C: priority with multiple pending sources.
    simputs("Subtest C: multi-source priority ...\n");
    ret = uart_test_priority(uart_base);
    if (ret != 0) {
        simputs("Subtest C FAILED\n");
        simputshex32("  error code = ", (uint32_t)ret);
        simputs("\n");
        write_scratch(0, 0xBAD0C000);
        test_fail(0);
    }
    simputs("Subtest C PASSED\n");

    simputs("\nUART IRQ test: ALL SUBTESTS PASSED\n");

    test_pass(0);

    while (1) {
        __asm__("wfi");
    }

    return 0;
}
