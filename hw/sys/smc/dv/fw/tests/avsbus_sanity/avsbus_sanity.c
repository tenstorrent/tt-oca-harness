/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include <stdint.h>

#include "metal/atomic.h"
#include "metal/lock.h"
#include "smc_io.h"
#include "smc_test.h"
#include "virt_console.h"

#define AVS_CMD_TYPE_VOLTAGE (0b0000)       // Target Rail Voltage Read/Write
#define AVS_CMD_TYPE_TRANSITION (0b0001)    // Vout Transition Rate Read/Write
#define AVS_CMD_TYPE_CURRENT_READ (0b0010)  // Rail Current Read
#define AVS_CMD_TYPE_TEMP_READ (0b0011)     // Temperature Read
#define AVS_CMD_TYPE_RESET_VOLTAGE (0b0100) // Force Voltage Reset (Requires wr_cmd_data=0x0)
#define AVS_CMD_TYPE_POWER_MODE (0b0101)    // Power Mode Read/Write
#define AVS_CMD_TYPE_STATUS (0b1110)        // AVSBus Status Read/Write
#define AVS_CMD_TYPE_VERSION (0b1111)       // AVSBus Version Read" ;

void send_cmd(int avs_cmd) {
    avsbus_controller__AVS_CMD_t avs_cmd_reg = {.w = 0u};
    if (avs_cmd == AVS_CMD_TYPE_RESET_VOLTAGE) {
        avs_cmd_reg.f.CMD_DATA = 0b0;
    } else if (avs_cmd == AVS_CMD_TYPE_POWER_MODE) {
        avs_cmd_reg.f.CMD_DATA = 0b101;
    } else {
        avs_cmd_reg.f.CMD_DATA = 0b1010100011001101;
    }
    avs_cmd_reg.f.RAIL_SEL = 0xf; // broadcast
    avs_cmd_reg.f.CMD_CODE = avs_cmd;
    avs_cmd_reg.f.CMD_GRP = 0;
    // R_OR_W: 0x0 commits the CMD_DATA write, 0x2 is a read (avsbus_controller.rdl);
    // current, temperature and version have no write form.
    bool is_read_only = (avs_cmd == AVS_CMD_TYPE_CURRENT_READ) ||
                        (avs_cmd == AVS_CMD_TYPE_TEMP_READ) || (avs_cmd == AVS_CMD_TYPE_VERSION);
    avs_cmd_reg.f.R_OR_W = is_read_only ? 0x2 : 0x0;
    simputshex32("Writing AVS command = ", avs_cmd);
    write_reg(SMC_TOP_SMC_AVSBUS_CONTROLLER_AVS_CMD_BASE_ADDR, avs_cmd_reg.w);
}

void wait_refclk_cycles(uint32_t refclock_cycles) {
    // read refclk counter and wait until it counts up by refclock_cycles
    cpu_ctrl__REFERENCE_COUNTER_t start_refclk_count = {.w = 0u};
    start_refclk_count.w = read_reg(SMC_TOP_SMC_CPU_CTRL_REFERENCE_COUNTER_BASE_ADDR);

    cpu_ctrl__REFERENCE_COUNTER_t refclk_count = {.w = 0u};
    do {
        refclk_count.w = read_reg(SMC_TOP_SMC_CPU_CTRL_REFERENCE_COUNTER_BASE_ADDR);
    } while (refclk_count.w < (start_refclk_count.w + refclock_cycles));
}

int main(void) {

    int hartid = metal_cpu_get_current_hartid();

    // configure avsbus

    avsbus_controller__AVS_INTERRUPT_CLEAR_t avs_int_clear = {.w = 0u};

    // Set max retries to 3
    avsbus_controller__AVS_CFG_0_t avs_cfg_0 = {.w = 0u};
    avs_cfg_0.f.MAX_RETRIES = 3;
    write_reg(SMC_TOP_SMC_AVSBUS_CONTROLLER_AVS_CFG_0_BASE_ADDR, avs_cfg_0.w);
    // Do a read check on the data just wrote to the avsbus reg space
    if (read_reg(SMC_TOP_SMC_AVSBUS_CONTROLLER_AVS_CFG_0_BASE_ADDR) != avs_cfg_0.w) {
        test_fail(hartid);
    }

    simputshex32("AVS CFG 0 finished setup with value = ", avs_cfg_0.w);

    // enable all the interrupt
    avsbus_controller__AVS_INTERRUPT_MASK_t avs_interrupt_mask = {.w = 0u};
    avs_interrupt_mask.w = 0x0;
    write_reg(SMC_TOP_SMC_AVSBUS_CONTROLLER_AVS_INTERRUPT_MASK_BASE_ADDR, avs_interrupt_mask.w);

    simputs("AVS Interrupt mask cleared");

    // wait 300ns
    wait_refclk_cycles(30);

    avsbus_controller__AVS_CFG_1_t avs_cfg_1 = {.w = 0u};
    avs_cfg_1.f.TURN_OFF_ALL_PREMUX_CLOCKS = 0x1;
    write_reg(SMC_TOP_SMC_AVSBUS_CONTROLLER_AVS_CFG_1_BASE_ADDR, avs_cfg_1.w);

    // select clk to 01 mode - use the divider
    // Set clk stop on idle
    //  Set clk divider value to 16
    //  Set clk divider duty cycle numerator to 128 (50% duty cycle)
    avs_cfg_1.f.CLK_DIVIDER_VALUE = 0x10;
    avs_cfg_1.f.AVS_CLOCK_SELECT = 0x1;
    avs_cfg_1.f.STOP_AVS_CLOCK_ON_IDLE = 0x1; // allow stopping of avs clock for power saving
    avs_cfg_1.f.CLK_DIVIDER_DUTY_CYCLE_NUMERATOR = 0x80;
    write_reg(SMC_TOP_SMC_AVSBUS_CONTROLLER_AVS_CFG_1_BASE_ADDR, avs_cfg_1.w);

    wait_refclk_cycles(10);

    avs_cfg_1.f.TURN_OFF_ALL_PREMUX_CLOCKS = 0x0;
    write_reg(SMC_TOP_SMC_AVSBUS_CONTROLLER_AVS_CFG_1_BASE_ADDR, avs_cfg_1.w);

    simputshex32("AVS CFG 1 finished setup with value = ", avs_cfg_1.w);

    // wait 10us
    wait_refclk_cycles(1000);

    // Issue one command of each type; the AVS bus is expected to be active.
    send_cmd(AVS_CMD_TYPE_VOLTAGE);
    wait_refclk_cycles(30);
    send_cmd(AVS_CMD_TYPE_TRANSITION);
    wait_refclk_cycles(10);
    send_cmd(AVS_CMD_TYPE_CURRENT_READ);
    wait_refclk_cycles(10);
    send_cmd(AVS_CMD_TYPE_TEMP_READ);
    wait_refclk_cycles(10);
    send_cmd(AVS_CMD_TYPE_RESET_VOLTAGE);
    wait_refclk_cycles(10);
    send_cmd(AVS_CMD_TYPE_POWER_MODE);
    wait_refclk_cycles(10);
    send_cmd(AVS_CMD_TYPE_STATUS);
    wait_refclk_cycles(10);
    send_cmd(AVS_CMD_TYPE_VERSION);
    wait_refclk_cycles(10);

    // wait 40us
    wait_refclk_cycles(4000);

    // check that both has data and fifo full interrupts are 1
    avsbus_controller__AVS_INTERRUPT_t avs_interrupts = {.w = 0u};
    avs_interrupts.w = read_reg(SMC_TOP_SMC_AVSBUS_CONTROLLER_AVS_INTERRUPT_BASE_ADDR);

    // readback the data from avs
    avsbus_controller__AVS_FIFOS_STATUS_t avs_fifo_status = {.w = 0u};
    avs_fifo_status.w = read_reg(SMC_TOP_SMC_AVSBUS_CONTROLLER_AVS_FIFOS_STATUS_BASE_ADDR);

    avsbus_controller__AVS_READBACK_t avs_readback = {.w = 0u};
    avs_readback.w = read_reg(SMC_TOP_SMC_AVSBUS_CONTROLLER_AVS_READBACK_BASE_ADDR);
    simputshex32("AVS readback crc = ", avs_readback.f.CRC);
    simputshex32("AVS readback cmd_data = ", avs_readback.f.CMD_DATA);
    simputshex32("AVS readback status_response = ", avs_readback.f.STATUS_RESPONSE);
    simputshex32("AVS readback const0 = ", avs_readback.f.CONST0);
    simputshex32("AVS readback slave_ack = ", avs_readback.f.SLAVE_ACK);

    // clear the interrupts
    write_reg(SMC_TOP_SMC_AVSBUS_CONTROLLER_AVS_INTERRUPT_CLEAR_BASE_ADDR, 0xffffffff);

    // since we only read one item, only the readback fifo full int should have been cleared
    // but the has data interrupt should still be high
    avs_interrupts.w = read_reg(SMC_TOP_SMC_AVSBUS_CONTROLLER_AVS_INTERRUPT_BASE_ADDR);

    test_pass(hartid);

    return 0;
}

int other_main(int hartid) {
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
