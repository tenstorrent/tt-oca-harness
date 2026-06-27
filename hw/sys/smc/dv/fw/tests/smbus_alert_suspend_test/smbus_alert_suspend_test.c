/* SPDX-License-Identifier: Apache-2.0 */
/* (c) 2026 Tenstorrent USA Inc */

// #include <stdint.h>
// #include <stdbool.h>

// #include "smc_io.h"
// #include "smc_test.h"

// static inline uint32_t smb_base_addr(uint32_t i2c_idx)
// {
//     return I2C_0_DWC_I2C_SMBUS_BLOCK_A_REG_MAP_BASE_ADDR + (0x200 * i2c_idx);
// }

// static inline uint32_t op_base_addr(uint32_t i2c_idx)
// {
//     return I2C_0_DWC_I2C_OPERATIONAL_BLOCK_A_REG_MAP_BASE_ADDR + (0x200 * i2c_idx);
// }

// static inline uint32_t i2c_block_base_addr(uint32_t i2c_idx)
// {
//     return I2C_0_DWC_I2C_I2C_BLOCK_A_REG_MAP_BASE_ADDR + (0x200 * i2c_idx);
// }

// static void i2c_assert_reset(uint32_t i2c_idx)
// {
//     I2C_CTRL_STATUS_I2C_CTRL_STATUS_reg_u i2c_ctrl;
//     i2c_ctrl.w = 0x0;
//     i2c_ctrl.f.i2c_reset_n_n0_scan = 0x0;
//     i2c_ctrl.f.i2c_reg_reset_n_n0_scan = 0x0;
//     write_reg(I2C_CTRL_STATUS_I2C_0_CTRL_STATUS_REG_ADDR + (i2c_idx * 0x4), i2c_ctrl.w);
// }
// static void i2c_release_reset_set_mode(uint32_t i2c_idx, bool host_mode)
// {
//     I2C_CTRL_STATUS_I2C_CTRL_STATUS_reg_u i2c_ctrl;
//     i2c_ctrl.w = 0x0;
//     i2c_ctrl.f.i2c_reset_n_n0_scan = 0x1;
//     i2c_ctrl.f.i2c_reg_reset_n_n0_scan = 0x1;
//     i2c_ctrl.f.i2c_master_mode = host_mode ? 0x1 : 0x0;
//     write_reg(I2C_CTRL_STATUS_I2C_0_CTRL_STATUS_REG_ADDR + (i2c_idx * 0x4), i2c_ctrl.w);

//     // Make sure block is disabled before timing/programming
//     DWC_I2C_OPERATIONAL_BLOCK_IC_ENABLE_reg_u ic_enable;
//     ic_enable.w = read_reg(op_base_addr(i2c_idx) + I2C_0_DWC_I2C_OPERATIONAL_BLOCK_A_IC_ENABLE_REG_OFFSET);
//     ic_enable.f.enable = 0x0;
//     write_reg(op_base_addr(i2c_idx) + I2C_0_DWC_I2C_OPERATIONAL_BLOCK_A_IC_ENABLE_REG_OFFSET, ic_enable.w);
// }

// static void i2c_set_tar(uint32_t i2c_idx, uint32_t seven_bit_addr)
// {
//     const uint32_t base = i2c_block_base_addr(i2c_idx);
//     // For 7-bit addr, write straight to TAR low bits
//     write_reg(base + I2C_0_DWC_I2C_I2C_BLOCK_A_IC_TAR_REG_OFFSET, seven_bit_addr & 0x7F);
// }

// static void i2c_configure_block(uint32_t i2c_idx, bool host_mode)
// {
//     const uint32_t base = i2c_block_base_addr(i2c_idx);

//     // Configure SCL timing (matching known-good i2c_sanity values)
//     write_reg(base + I2C_0_DWC_I2C_I2C_BLOCK_A_IC_SCL_HCNT_REG_OFFSET, 0x1A);
//     write_reg(base + I2C_0_DWC_I2C_I2C_BLOCK_A_IC_SCL_LCNT_REG_OFFSET, 0x32);

//     // Configure SDA timing
//     DWC_I2C_I2C_BLOCK_IC_SDA_HOLD_reg_u sda_hold;
//     sda_hold.w = read_reg(base + I2C_0_DWC_I2C_I2C_BLOCK_A_IC_SDA_HOLD_REG_OFFSET);
//     sda_hold.f.ic_sda_tx_hold = 0x2 + 0x3; // spike_len(2) + 3
//     sda_hold.f.ic_sda_rx_hold = 0x0;
//     write_reg(base + I2C_0_DWC_I2C_I2C_BLOCK_A_IC_SDA_HOLD_REG_OFFSET, sda_hold.w);
//     write_reg(base + I2C_0_DWC_I2C_I2C_BLOCK_A_IC_SDA_SETUP_REG_OFFSET, 0x2);

//     // Spike length
//     write_reg(base + I2C_0_DWC_I2C_I2C_BLOCK_A_IC_SPKLEN_REG_OFFSET, 0x2);

//     // Optional: set stuck-at-low timeouts similar to i2c_sanity
//     write_reg(base + I2C_0_DWC_I2C_I2C_BLOCK_A_IC_SCL_STUCK_AT_LOW_TIMEOUT_REG_OFFSET, 0xffffffff);
//     write_reg(base + I2C_0_DWC_I2C_I2C_BLOCK_A_IC_SCL_STUCK_AT_LOW_TIMEOUT_MAX_REG_OFFSET, 0xffffffff);
//     write_reg(base + I2C_0_DWC_I2C_I2C_BLOCK_A_IC_SDA_STUCK_AT_LOW_TIMEOUT_REG_OFFSET, 0xffffffff);

//     // Clear & enable I2C interrupts (like i2c_sanity)
//     DWC_I2C_I2C_BLOCK_IC_INTR_CLR_reg_u intr_clr;
//     intr_clr.w = read_reg(base + I2C_0_DWC_I2C_I2C_BLOCK_A_IC_INTR_CLR_REG_OFFSET);
//     intr_clr.f.clr_intr = 0x1;
//     write_reg(base + I2C_0_DWC_I2C_I2C_BLOCK_A_IC_INTR_CLR_REG_OFFSET, intr_clr.w);

//     DWC_I2C_I2C_BLOCK_IC_INTR_MASK_reg_u intr_en;
//     intr_en.w = read_reg(base + I2C_0_DWC_I2C_I2C_BLOCK_A_IC_INTR_MASK_REG_OFFSET);
//     intr_en.f.m_rx_under = 0x1;
//     intr_en.f.m_rx_over = 0x1;
//     intr_en.f.m_rx_full = 0x1;
//     intr_en.f.m_tx_over = 0x1;
//     intr_en.f.m_tx_empty = 0x1;
//     intr_en.f.m_rd_req = 0x1;
//     intr_en.f.m_tx_trmnt = 0x1;
//     intr_en.f.m_rx_done = 0x1;
//     intr_en.f.m_activity = 0x1;
//     intr_en.f.m_stop_det = 0x1;
//     intr_en.f.m_start_det = 0x1;
//     intr_en.f.m_gen_call = 0x1;
//     intr_en.f.m_restart_det = 0x1;
//     intr_en.f.m_ctrlr_on_hold = 0x1;
//     intr_en.f.m_scl_stuck_at_low = 0x1;
//     write_reg(base + I2C_0_DWC_I2C_I2C_BLOCK_A_IC_INTR_MASK_REG_OFFSET, intr_en.w);

//     // Control register: set controller/target op_mode like i2c_sanity and configure speed
//     DWC_I2C_I2C_BLOCK_IC_CTRL_reg_u ic_ctrl_reg;
//     ic_ctrl_reg.w = read_reg(base + I2C_0_DWC_I2C_I2C_BLOCK_A_IC_CTRL_REG_OFFSET);
//     ic_ctrl_reg.f.ic_op_mode = host_mode ? 0x1 : 0x0; // 1=controller(host), 0=target(device)
//     ic_ctrl_reg.f.SPEED = 0x2;            // fastmode
//     ic_ctrl_reg.f.ic_10bitaddr_tgt = 0x0; // 7-bit
//     ic_ctrl_reg.f.stop_det_ifaddressed = 0x0;
//     ic_ctrl_reg.f.tx_empty_ctrl = 0x0;
//     ic_ctrl_reg.f.rx_fifo_full_hld_ctrl = 0x0;
//     ic_ctrl_reg.f.stop_det_if_ctrlr_active = 0x0;
//     ic_ctrl_reg.f.bus_clear_feature_ctrl = 0x0;
//     write_reg(base + I2C_0_DWC_I2C_I2C_BLOCK_A_IC_CTRL_REG_OFFSET, ic_ctrl_reg.w);

//     // FIFO thresholds
//     write_reg(base + I2C_0_DWC_I2C_I2C_BLOCK_A_IC_RX_TL_REG_OFFSET, 0x0);
//     write_reg(base + I2C_0_DWC_I2C_I2C_BLOCK_A_IC_TX_TL_REG_OFFSET, 0x0);

//     // DMA control & thresholds
//     DWC_I2C_I2C_BLOCK_IC_DMA_CR_reg_u dma_ctrl;
//     dma_ctrl.w = read_reg(base + I2C_0_DWC_I2C_I2C_BLOCK_A_IC_DMA_CR_REG_OFFSET);
//     dma_ctrl.f.rdmae = 0x0;
//     dma_ctrl.f.tdmae = 0x0;
//     write_reg(base + I2C_0_DWC_I2C_I2C_BLOCK_A_IC_DMA_CR_REG_OFFSET, dma_ctrl.w);
//     write_reg(base + I2C_0_DWC_I2C_I2C_BLOCK_A_IC_DMA_TDLR_REG_OFFSET, 0x0);
//     write_reg(base + I2C_0_DWC_I2C_I2C_BLOCK_A_IC_DMA_RDLR_REG_OFFSET, 0x0);

//     // SMBus: bus idle timeout similar to i2c_sanity
//     DWC_I2C_SMBUS_BLOCK_IC_SMBUS_THIGH_MAX_IDLE_COUNT_reg_u max_idle_cnt;
//     const uint32_t smb_base = smb_base_addr(i2c_idx);
//     max_idle_cnt.w = read_reg(smb_base + I2C_0_DWC_I2C_SMBUS_BLOCK_A_IC_SMBUS_THIGH_MAX_IDLE_COUNT_REG_OFFSET);
//     max_idle_cnt.f.smbus_thigh_max_bus_idle_cnt = 0xee;
//     write_reg(smb_base + I2C_0_DWC_I2C_SMBUS_BLOCK_A_IC_SMBUS_THIGH_MAX_IDLE_COUNT_REG_OFFSET, max_idle_cnt.w);

//     // Register timeout
//     write_reg(base + I2C_0_DWC_I2C_I2C_BLOCK_A_IC_REG_TIMEOUT_RST_REG_OFFSET, 0x8);

//     // Finally enable operational block
//     DWC_I2C_OPERATIONAL_BLOCK_IC_ENABLE_reg_u ic_enable;
//     ic_enable.w = read_reg(op_base_addr(i2c_idx) + I2C_0_DWC_I2C_OPERATIONAL_BLOCK_A_IC_ENABLE_REG_OFFSET);
//     ic_enable.f.enable = 0x1;
//     write_reg(op_base_addr(i2c_idx) + I2C_0_DWC_I2C_OPERATIONAL_BLOCK_A_IC_ENABLE_REG_OFFSET, ic_enable.w);
// }

// static void i2c_host_read_bytes(uint32_t i2c_idx, uint32_t num_bytes)
// {
//     const uint32_t base = i2c_block_base_addr(i2c_idx);
//     DWC_I2C_I2C_BLOCK_IC_DATA_CMD_reg_u dc;
//     for (uint32_t i = 0; i < num_bytes; ++i) {
//         dc.w = 0;
//         dc.f.cmd = 1;                 // read
//         dc.f.restart = (i == 0) ? 1 : 0;
//         dc.f.STOP = (i == (num_bytes - 1)) ? 1 : 0;
//         write_reg(base + I2C_0_DWC_I2C_I2C_BLOCK_A_IC_DATA_CMD_REG_OFFSET, dc.w);
//     }
//     // Drain RX FIFO
//     uint32_t received = 0;
//     while (received < num_bytes) {
//         uint32_t rxflr = read_reg(base + I2C_0_DWC_I2C_I2C_BLOCK_A_IC_RXFLR_REG_OFFSET) & 0xFF;
//         while (rxflr && received < num_bytes) {
//             (void)read_reg(base + I2C_0_DWC_I2C_I2C_BLOCK_A_IC_DATA_CMD_REG_OFFSET);
//             received++;
//             rxflr--;
//         }
//     }
// }

// static void smbus_set_alert_enable(uint32_t i2c_idx, bool enable)
// {
//     const uint32_t base = smb_base_addr(i2c_idx);
//     DWC_I2C_SMBUS_BLOCK_IC_SMBUS_CTRL_reg_u ctrl;
//     ctrl.w = read_reg(base + I2C_0_DWC_I2C_SMBUS_BLOCK_A_IC_SMBUS_CTRL_REG_OFFSET);
//     ctrl.f.ic_dar_smbus_alert_en = enable ? 1 : 0;
//     write_reg(base + I2C_0_DWC_I2C_SMBUS_BLOCK_A_IC_SMBUS_CTRL_REG_OFFSET, ctrl.w);
// }

// static void smbus_set_suspend_enable(uint32_t i2c_idx, bool enable)
// {
//     const uint32_t base = smb_base_addr(i2c_idx);
//     DWC_I2C_SMBUS_BLOCK_IC_SMBUS_CTRL_reg_u ctrl;
//     ctrl.w = read_reg(base + I2C_0_DWC_I2C_SMBUS_BLOCK_A_IC_SMBUS_CTRL_REG_OFFSET);
//     ctrl.f.smbus_suspend_en = enable ? 1 : 0;
//     write_reg(base + I2C_0_DWC_I2C_SMBUS_BLOCK_A_IC_SMBUS_CTRL_REG_OFFSET, ctrl.w);
// }

// static bool smbus_get_alert_status(uint32_t i2c_idx)
// {
//     const uint32_t base = smb_base_addr(i2c_idx);
//     DWC_I2C_SMBUS_BLOCK_IC_SMBUS_STATUS_reg_u st;
//     st.w = read_reg(base + I2C_0_DWC_I2C_SMBUS_BLOCK_A_IC_SMBUS_STATUS_REG_OFFSET);
//     return st.f.smbus_alert_status ? true : false;
// }

// static bool smbus_get_suspend_status(uint32_t i2c_idx)
// {
//     const uint32_t base = smb_base_addr(i2c_idx);
//     DWC_I2C_SMBUS_BLOCK_IC_SMBUS_STATUS_reg_u st;
//     st.w = read_reg(base + I2C_0_DWC_I2C_SMBUS_BLOCK_A_IC_SMBUS_STATUS_REG_OFFSET);
//     return st.f.smbus_suspend_status ? true : false;
// }

// static bool smbus_irq_alert_stat(uint32_t i2c_idx)
// {
//     const uint32_t base = smb_base_addr(i2c_idx);
//     DWC_I2C_SMBUS_BLOCK_IC_SMBUS_INTR_STAT_reg_u st;
//     st.w = read_reg(base + I2C_0_DWC_I2C_SMBUS_BLOCK_A_IC_SMBUS_INTR_STAT_REG_OFFSET);
//     return st.f.r_smbus_alert_det ? true : false;
// }

// static bool smbus_irq_suspend_stat(uint32_t i2c_idx)
// {
//     const uint32_t base = smb_base_addr(i2c_idx);
//     DWC_I2C_SMBUS_BLOCK_IC_SMBUS_INTR_STAT_reg_u st;
//     st.w = read_reg(base + I2C_0_DWC_I2C_SMBUS_BLOCK_A_IC_SMBUS_INTR_STAT_REG_OFFSET);
//     return st.f.r_smbus_suspend_det ? true : false;
// }

// static void smbus_clear_alert_irq(uint32_t i2c_idx)
// {
//     const uint32_t base = smb_base_addr(i2c_idx);
//     DWC_I2C_SMBUS_BLOCK_IC_SMBUS_INTR_CLR_reg_u clr;
//     clr.w = 0;
//     clr.f.clr_smbus_alert_det = 1;
//     write_reg(base + I2C_0_DWC_I2C_SMBUS_BLOCK_A_IC_SMBUS_INTR_CLR_REG_OFFSET, clr.w);
// }

// static void smbus_clear_suspend_irq(uint32_t i2c_idx)
// {
//     const uint32_t base = smb_base_addr(i2c_idx);
//     DWC_I2C_SMBUS_BLOCK_IC_SMBUS_INTR_CLR_reg_u clr;
//     clr.w = 0;
//     clr.f.clr_smbus_suspend_det = 1;
//     write_reg(base + I2C_0_DWC_I2C_SMBUS_BLOCK_A_IC_SMBUS_INTR_CLR_REG_OFFSET, clr.w);
// }

// static bool wait_until(bool (*cond_fn)(uint32_t), uint32_t idx, bool expected, uint32_t timeout_cycles)
// {
//     while (timeout_cycles--) {
//         if (cond_fn(idx) == expected) {
//             return true;
//         }
//     }
//     return false;
// }

// static bool check_capabilities(uint32_t i2c_idx)
// {
//     const uint32_t base = op_base_addr(i2c_idx);
//     DWC_I2C_OPERATIONAL_BLOCK_IC_SMBUS_CAPABILITIES_reg_u caps;
//     caps.w = read_reg(base + I2C_0_DWC_I2C_OPERATIONAL_BLOCK_A_IC_SMBUS_CAPABILITIES_REG_OFFSET);
//     return caps.f.ic_smbus_suspend_alert ? true : false;
// }

// int main(void)
// {
//     simputs("[SMBUS] smbus_alert_suspend_test: start\n");
//     init_test(0);
//     simputs("[SMBUS] Peripherals out of reset and test seeded\n");

//     for (uint32_t host_idx = 0; host_idx < 3; host_idx++) {
//         uint32_t other1 = (host_idx + 1) % 3;
//         uint32_t other2 = (host_idx + 2) % 3;
//         uint32_t device_idx = (get_random_int() & 0x1) ? other1 : other2;
//         simputshex32("Testing Host: ", host_idx);
//         simputshex32("Testing Device: ", device_idx);

//         // Reset and configure selected pair
//         for (uint32_t i = 0; i < 3; i++) {
//             i2c_assert_reset(i);
//         }
//         i2c_release_reset_set_mode(device_idx, /*host_mode*/false);
//         i2c_release_reset_set_mode(host_idx, /*host_mode*/true);
//         i2c_configure_block(device_idx, /*host_mode*/false);
//         i2c_configure_block(host_idx, /*host_mode*/true);
//         i2c_set_tar(host_idx, 0x55);

//         // Capabilities
//         if (!check_capabilities(device_idx) || !check_capabilities(host_idx)) {
//             raise_fatal_s(0, "SMBus suspend/alert capability not present");
//         }

//         // Clear initial state
//         smbus_set_alert_enable(device_idx, false);
//         smbus_set_alert_enable(host_idx, false);
//         smbus_set_suspend_enable(device_idx, false);
//         smbus_set_suspend_enable(host_idx, false);
//         simputs("[SMBUS] Initial state cleared (ALERT=0, SUSPEND=0)\n");

//         // ALERT: Device -> Host
//         smbus_clear_alert_irq(host_idx);
//         simputs("[SMBUS][ALERT] Device asserts ALERT -> expect Host=1 (and IRQ)\n");
//         smbus_set_alert_enable(device_idx, true);
//         if (!wait_until(smbus_get_alert_status, host_idx, true, 20000)) {
//             raise_fatal_s(0, "SMBus ALERT did not propagate Device->Host");
//         }
//         if (!wait_until(smbus_irq_alert_stat, host_idx, true, 20000)) {
//             raise_fatal_s(0, "SMBus ALERT IRQ not observed on Host");
//         }
//         simputs("[SMBUS][ALERT] Observed Host status=1 and IRQ asserted\n");
//         i2c_set_tar(host_idx, 0x0C);
//         i2c_host_read_bytes(host_idx, 2);
//         if (!wait_until(smbus_get_alert_status, host_idx, false, 20000)) {
//             raise_fatal_s(0, "SMBus ALERT release (ARA) did not clear Host status");
//         }
//         smbus_clear_alert_irq(host_idx);
//         if (!wait_until(smbus_irq_alert_stat, host_idx, false, 20000)) {
//             raise_fatal_s(0, "SMBus ALERT IRQ did not clear on Host after ARA");
//         }
//         simputs("[SMBUS][ALERT] Host performed ARA read; status=0 and IRQ cleared\n");

//         // SUSPEND: Host -> Device
//         smbus_clear_suspend_irq(device_idx);
//         simputs("[SMBUS][SUSPEND] Host asserts SUSPEND -> expect Device=1 (and IRQ)\n");
//         smbus_set_suspend_enable(host_idx, true);
//         if (!wait_until(smbus_get_suspend_status, device_idx, true, 20000)) {
//             raise_fatal_s(0, "SMBus SUSPEND did not propagate Host->Device");
//         }
//         if (!wait_until(smbus_irq_suspend_stat, device_idx, true, 20000)) {
//             raise_fatal_s(0, "SMBus SUSPEND IRQ not observed on Device");
//         }
//         simputs("[SMBUS][SUSPEND] Observed Device status=1 and IRQ asserted\n");
//         smbus_set_suspend_enable(host_idx, false);
//         if (!wait_until(smbus_get_suspend_status, device_idx, false, 20000)) {
//             raise_fatal_s(0, "SMBus SUSPEND deassert did not propagate Host->Device");
//         }
//         smbus_clear_suspend_irq(device_idx);
//         if (!wait_until(smbus_irq_suspend_stat, device_idx, false, 20000)) {
//             raise_fatal_s(0, "SMBus SUSPEND IRQ did not clear on Device");
//         }
//         simputs("[SMBUS][SUSPEND] Observed Device status=0 and IRQ cleared\n");
//     }

//     test_pass(0);
// }


#include <stdint.h>

#include "smc_io.h"
#include "smc_test.h"


int main(void) {

  test_pass(0);

  while (true) {
    __asm__("wfi");
  }

  return 0;
}

int secondary_main(void) {

  return main();

}