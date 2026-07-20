/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */


/* SMC Defines - Register access and utility functions
 */

#ifndef SMC_DEFINES_H
#define SMC_DEFINES_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "smc_top_regs.h"
#include "smc_rom_defs.h"
#include "smc_strap.h"

#define NUM_EXTERNAL_INTERRUPTS (256)           /* 4-core: NUM_EXT_INTERRUPTS=256 */
#define MAILBOX_INTERUPT_ID_BASE (289)          /* cpu_interrupts_o[288] -> PLIC ID 289 (4-core) */

#define SMC_ROM_STACK_END 0xC0066400 /* ROM stack end + safety margin (high watermark 23.7KB based on tests, allocating 25KB) */

/* OCCP-accessible SRAM region (starts after ROM-owned regions) */
#define SMC_SRAM_OCCP_BASE_ADDR SMC_ROM_STACK_END                 /* OCCP accessible SRAM base - starts after ROM sections */

/* PLL/CGM Configuration Constants */
#define SMC_CGM_COUNT (7)              // SMC has CGM0-6 (7 total CGMs)
#define SMC_CGM_STATUS_REG_INTERVAL (0x100)  // CGM status registers at 0x100 byte intervals

static inline void write_reg(uint64_t addr, uint32_t value)
{
  volatile uint32_t *p_addr = (volatile uint32_t *)(uintptr_t)addr;
  *p_addr = value;
}

static inline uint32_t read_reg(uint64_t addr)
{
  volatile uint32_t *p_addr = (volatile uint32_t *)(uintptr_t)addr;
  return *p_addr;
}

static inline uint64_t read_reg_64(uint64_t addr)
{
  volatile uint64_t *p_addr = (volatile uint64_t *)(uintptr_t)addr;
  return *p_addr;
}

static inline void write64_reg(uint64_t addr, uint64_t value)
{
  volatile uint64_t *p_addr = (volatile uint64_t *)(uintptr_t)addr;
  *p_addr = value;
}

static inline uint64_t read64_reg(uint64_t addr)
{
  volatile uint64_t *p_addr = (volatile uint64_t *)(uintptr_t)addr;
  return *p_addr;
}

static inline void write16_reg(uint64_t addr, uint16_t value)
{
  volatile uint16_t *p_addr = (volatile uint16_t *)(uintptr_t)addr;
  *p_addr = value;
}

static inline uint16_t read16_reg(uint64_t addr)
{
  volatile uint16_t *p_addr = (volatile uint16_t *)(uintptr_t)addr;
  return *p_addr;
}

static inline void write_periph_reg(uint64_t offset, uint64_t value)
{
  volatile uint64_t *p_addr =
      (volatile uint64_t *)(uintptr_t)(SMC_CPU_CTRL_REG_MAP_BASE_ADDR + offset);
  *p_addr = value;
}

static inline uint64_t read_periph_reg(uint64_t offset)
{
  volatile uint64_t *p_addr =
      (volatile uint64_t *)(uintptr_t)(SMC_CPU_CTRL_REG_MAP_BASE_ADDR + offset);
  return *p_addr;
}

static inline void write_dma_ctrl_reg(uint64_t offset, uint64_t value)
{
  volatile uint64_t *p_addr =
      (volatile uint64_t *)(uintptr_t)(DMA_CTRL_REG_MAP_BASE_ADDR + //replace
                                       offset);
  *p_addr = value;
}

static inline uint64_t read_dma_ctrl_reg(uint64_t offset)
{
  volatile uint64_t *p_addr =
      (volatile uint64_t *)(uintptr_t)(DMA_CTRL_REG_MAP_BASE_ADDR + //replace
                                       offset);
  return *p_addr;
}

static inline void write_zeroer_ctrl_reg(uint64_t offset, uint64_t value)
{
  volatile uint64_t *p_addr =
      (volatile uint64_t *)(uintptr_t)(ZEROER_CTRL_REG_MAP_BASE_ADDR + //replace
                                       offset);
  *p_addr = value;
}

static inline uint64_t read_zeroer_ctrl_reg(uint64_t offset)
{
  volatile uint64_t *p_addr =
      (volatile uint64_t *)(uintptr_t)(ZEROER_CTRL_REG_MAP_BASE_ADDR + //replace
                                       offset);
  return *p_addr;
}

static inline void write_spm(uint64_t offset, uint64_t value)
{
  volatile uint64_t *p_addr =
      (volatile uint64_t *)(uintptr_t)(SPM_MEMORY_MEM_BASE_ADDR + offset);
  *p_addr = value;
}

static inline void write_spm64(uint64_t offset, uint64_t value)
{
  volatile uint64_t *p_addr =
      (volatile uint64_t *)(uintptr_t)(SPM_MEMORY_MEM_BASE_ADDR + offset);
  *p_addr = value;
}

static inline uint64_t read_spm(uint64_t offset)
{
  volatile uint64_t *p_addr =
      (volatile uint64_t *)(uintptr_t)(SPM_MEMORY_MEM_BASE_ADDR + offset);
  return *p_addr;
}

static inline uint64_t read_spm64(uint64_t offset)
{
  volatile uint64_t *p_addr =
      (volatile uint64_t *)(uintptr_t)(SPM_MEMORY_MEM_BASE_ADDR + offset);
  return *p_addr;
}

static inline void write_smc_reg(uint64_t offset, uint64_t value)
{
  volatile uint64_t *addr_ptr =
      (volatile uint64_t *)(uintptr_t)(SMC_CPU_CTRL_REG_MAP_BASE_ADDR + offset);
  *addr_ptr = value;
}

static inline uint64_t read_smc_reg(uint64_t offset)
{
  volatile uint64_t *addr_ptr =
      (volatile uint64_t *)(uintptr_t)(SMC_CPU_CTRL_REG_MAP_BASE_ADDR + offset);
  return *addr_ptr;
}

static inline void write_scratch(uint8_t scratch_num, uint32_t value)
{
  volatile uint32_t *addr =
      (volatile uint32_t *)(uintptr_t)(SMC_CPU_CTRL_SCRATCH_0__REG_ADDR +
                                       (scratch_num * sizeof(uint64_t)));
  *addr = value;
}

static inline uint32_t read_scratch(uint8_t scratch_num)
{
  volatile uint32_t *addr =
      (volatile uint32_t *)(uintptr_t)(SMC_CPU_CTRL_SCRATCH_0__REG_ADDR +
                                       (scratch_num * sizeof(uint64_t)));
  return *addr;
}

/* Legacy POST code function - writes to scratch register 0 (pass/fail)
 * For structured POST code management, use smc_post_code.h API instead */
static inline void write_postcode(uint32_t value) { write_scratch(0, value); }

static inline void write_mailbox(uint8_t mailbox_num, uint8_t is_inbound,
                                 uint32_t offset, uint64_t value)
{
  volatile uint64_t *p_addr =
      (volatile uint64_t *)(uintptr_t)(SMC_MAILBOX_OUTBOUND_MAILBOX_0_REG_MAP_BASE_ADDR +
                                       (mailbox_num * 0x1000 +
                                        is_inbound * 0x800) +
                                       offset);
  *p_addr = value;
}

static inline uint64_t read_mailbox(uint8_t mailbox_num, uint8_t is_inbound,
                                    uint32_t offset)
{
  volatile uint64_t *p_addr =
      (volatile uint64_t *)(uintptr_t)(SMC_MAILBOX_OUTBOUND_MAILBOX_0_REG_MAP_BASE_ADDR +
                                       (mailbox_num * 0x1000 +
                                        is_inbound * 0x800) +
                                       offset);
  return *p_addr;
}

static inline void write_gpio_shim(uint8_t gpio_num, uint32_t offset,
                                   uint32_t value)
{
  uint32_t gpio_spacing = 0x20;
  volatile uint32_t *p_addr =
      (volatile uint32_t *)(uintptr_t)((GPIO_CTRL_0__REG_MAP_BASE_ADDR +
                                        gpio_num * gpio_spacing) +
                                       offset);
  *p_addr = value;
}

static inline uint32_t read_gpio_shim(uint8_t gpio_num, uint32_t offset)
{
  uint32_t gpio_spacing = 0x20;
  volatile uint32_t *p_addr =
      (volatile uint32_t *)(uintptr_t)((GPIO_CTRL_0__REG_MAP_BASE_ADDR +
                                        gpio_num * gpio_spacing) +
                                       offset);
  return *p_addr;
}

static inline void write_gpio(uint8_t gpio_num, uint32_t offset,
                              uint32_t value)
{
  uint32_t gpio_spacing = 0x10;
  volatile uint32_t *p_addr =
      (volatile uint32_t *)(uintptr_t)((GPIO_INTF_0__REG_MAP_BASE_ADDR +
                                        gpio_num * gpio_spacing) +
                                       offset);
  *p_addr = value;
}

static inline uint32_t read_gpio(uint8_t gpio_num, uint32_t offset)
{
  uint32_t gpio_spacing = 0x10;
  volatile uint32_t *p_addr =
      (volatile uint32_t *)(uintptr_t)((GPIO_INTF_0__REG_MAP_BASE_ADDR +
                                        gpio_num * gpio_spacing) +
                                       offset);
  return *p_addr;
}

// static inline void write_ptp_timer(uint32_t offset, uint32_t value)
// {
//   volatile uint32_t *p_addr =
//       (volatile uint32_t *)(uintptr_t)(PTP_TIMER_REG_MAP_BASE_ADDR + offset);
//   *p_addr = value;
// }

// static inline uint32_t read_ptp_timer(uint32_t offset)
// {
//   volatile uint32_t *p_addr =
//       (volatile uint32_t *)(uintptr_t)(PTP_TIMER_REG_MAP_BASE_ADDR + offset);
//   return *p_addr;
// }

// static inline void write_zeros(const uint32_t addr, const uint32_t size,
//                                const bool int_en)
// {
//   write_zeroer_ctrl_reg(AXI_DATA_ACCEL_AXI_ZEROER_CTRL_DEST_ADDR_REG_OFFSET,
//                         addr);
//   write_zeroer_ctrl_reg(AXI_DATA_ACCEL_AXI_ZEROER_CTRL_SIZE_REG_OFFSET, size);
//   write_zeroer_ctrl_reg(AXI_DATA_ACCEL_AXI_ZEROER_CTRL_CTRL_STATUS_REG_OFFSET,
//                         int_en);

//   while (read_zeroer_ctrl_reg(
//       AXI_DATA_ACCEL_AXI_ZEROER_CTRL_CTRL_STATUS_REG_OFFSET))
//     ;
// }

static inline void write_pll_ctrl_reg(uint32_t offset, uint32_t value)
{
  volatile uint16_t *p_addr =
      (volatile uint16_t *)(uintptr_t)(SMC_PLL_WRAP_PLL_CNTL_REG_MAP_BASE_ADDR +
                                       offset);
  *p_addr = value;
}

static inline uint32_t read_pll_ctrl_reg(uint32_t offset)
{
  volatile uint16_t *p_addr =
      (volatile uint16_t *)(uintptr_t)(SMC_PLL_WRAP_PLL_CNTL_REG_MAP_BASE_ADDR +
                                       offset);
  return *p_addr;
}

static inline void write_apb2avsbus_ctrl_reg(uint32_t offset, uint32_t value)
{
  volatile uint16_t *p_addr =
      (volatile uint16_t *)(uintptr_t)(SMC_AVSBUS_CONTROLLER_REG_MAP_BASE_ADDR + offset); //replace
  *p_addr = value;
}

static inline uint32_t read_abp2avsbus_ctrl_reg(uint32_t offset)
{
  volatile uint16_t *p_addr =
      (volatile uint16_t *)(uintptr_t)(SMC_AVSBUS_CONTROLLER_REG_MAP_BASE_ADDR + offset); //replace
  return *p_addr;
}

static inline void write_cgm_pll_reg(uint32_t id, uint32_t offset,
                                     uint32_t value)
{
  volatile uint16_t *p_addr =
      (volatile uint16_t *)(uintptr_t)(SMC_PLL_WRAP_PLL_CNTL_CGM_0_STATUS_REG_ADDR + id * 0x100 +
                                       offset);
  *p_addr = value;
}

static inline uint32_t read_cgm_pll_reg(uint32_t id, uint32_t offset)
{
  volatile uint16_t *p_addr =
      (volatile uint16_t *)(uintptr_t)(SMC_PLL_WRAP_PLL_CNTL_CGM_0_STATUS_REG_ADDR + id * 0x100 +
                                       offset);
  return *p_addr;
}

#ifndef SMC_PERIPH_PLL
static inline void write_awm_pll_reg(uint32_t id, uint32_t offset,
                                     uint16_t value)
{
  volatile uint16_t *p_addr =
      (volatile uint16_t *)(uintptr_t)(SMC_PLL_WRAP_AWM_0_REG_MAP_BASE_ADDR + id * 0x600 + //replace
                                       offset);
  *p_addr = value;
}

static inline uint16_t read_awm_pll_reg(uint32_t id, uint32_t offset)
{
  volatile uint16_t *p_addr =
      (volatile uint16_t *)(uintptr_t)(SMC_PLL_WRAP_AWM_0_REG_MAP_BASE_ADDR + id * 0x600 + //replace
                                       offset);
  return *p_addr;
}
#endif

static inline void write_uart_reg(int uart_id, uint32_t offset,
                                  uint32_t value)
{
  uint32_t BASE_ADDRESS_UART;
  if (uart_id == 0)
  {
    BASE_ADDRESS_UART = SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_0__UART_REG_MAP_BASE_ADDR;
  }
  else if (uart_id == 1)
  {
    BASE_ADDRESS_UART = SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_1__UART_REG_MAP_BASE_ADDR;
  }
  else if (uart_id == 2)
  {
    BASE_ADDRESS_UART = SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_2__UART_REG_MAP_BASE_ADDR;
  }
  else
  {
    BASE_ADDRESS_UART = SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_3__UART_REG_MAP_BASE_ADDR;
  }

  volatile uint16_t *p_addr =
      (volatile uint16_t *)(uintptr_t)(BASE_ADDRESS_UART + offset);
  *p_addr = value;
}

static inline uint32_t read_uart_reg(int uart_id, uint32_t offset)
{
  uint32_t BASE_ADDRESS_UART;
  if (uart_id == 0)
  {
    BASE_ADDRESS_UART = SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_0__UART_REG_MAP_BASE_ADDR;
  }
  else if (uart_id == 1)
  {
    BASE_ADDRESS_UART = SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_1__UART_REG_MAP_BASE_ADDR;
  }
  else if (uart_id == 2)
  {
    BASE_ADDRESS_UART = SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_2__UART_REG_MAP_BASE_ADDR;
  }
  else
  {
    BASE_ADDRESS_UART = SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_3__UART_REG_MAP_BASE_ADDR;
  }

  volatile uint16_t *p_addr =
      (volatile uint16_t *)(uintptr_t)(BASE_ADDRESS_UART + offset);
  return *p_addr;
}

static inline void write_uart_engine_reg(int uart_id, uint32_t offset,
                                         uint32_t value)
{
  uint32_t BASE_ADDRESS_UART;
  if (uart_id == 0)
  {
    BASE_ADDRESS_UART = SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_0__LOG_ENGINE_REG_MAP_BASE_ADDR;
  }
  else if (uart_id == 1)
  {
    BASE_ADDRESS_UART = SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_1__LOG_ENGINE_REG_MAP_BASE_ADDR;
  }
  else if (uart_id == 2)
  {
    BASE_ADDRESS_UART = SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_2__LOG_ENGINE_REG_MAP_BASE_ADDR;
  }
  else
  {
    BASE_ADDRESS_UART = SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_3__LOG_ENGINE_REG_MAP_BASE_ADDR;
  }

  volatile uint16_t *p_addr =
      (volatile uint16_t *)(uintptr_t)(BASE_ADDRESS_UART + offset);
  *p_addr = value;
}

static inline uint32_t read_uart_engine_reg(int uart_id, uint32_t offset)
{
  uint32_t BASE_ADDRESS_UART;
  if (uart_id == 0)
  {
    BASE_ADDRESS_UART = SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_0__LOG_ENGINE_REG_MAP_BASE_ADDR;
  }
  else if (uart_id == 1)
  {
    BASE_ADDRESS_UART = SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_1__LOG_ENGINE_REG_MAP_BASE_ADDR;
  }
  else if (uart_id == 2)
  {
    BASE_ADDRESS_UART = SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_2__LOG_ENGINE_REG_MAP_BASE_ADDR;
  }
  else
  {
    BASE_ADDRESS_UART = SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_3__LOG_ENGINE_REG_MAP_BASE_ADDR;
  }

  volatile uint16_t *p_addr =
      (volatile uint16_t *)(uintptr_t)(BASE_ADDRESS_UART + offset);
  return *p_addr;
}

static inline void write_beu_reg(int hartid, uint64_t offset, uint64_t value)
{
  uint64_t BASE_ADDRESS_BEU;
  if (hartid == 0)
  {
    BASE_ADDRESS_BEU = SMC_CLUSTER_CORE0_BEU_REG_MAP_BASE_ADDR;
  }
  else if (hartid == 1)
  {
    BASE_ADDRESS_BEU = SMC_CLUSTER_CORE1_BEU_REG_MAP_BASE_ADDR;
  }
  else if (hartid == 2)
  {
    BASE_ADDRESS_BEU = SMC_CLUSTER_CORE2_BEU_REG_MAP_BASE_ADDR;
  }
  else
  {
    BASE_ADDRESS_BEU = SMC_CLUSTER_CORE3_BEU_REG_MAP_BASE_ADDR;
  }

  volatile uint64_t *p_addr =
      (volatile uint64_t *)(uintptr_t)(BASE_ADDRESS_BEU + offset);
  *p_addr = value;
}

static inline uint64_t read_beu_reg(int hartid, uint64_t offset)
{
  uint64_t BASE_ADDRESS_BEU;
  if (hartid == 0)
  {
    BASE_ADDRESS_BEU = SMC_CLUSTER_CORE0_BEU_REG_MAP_BASE_ADDR;
  }
  else if (hartid == 1)
  {
    BASE_ADDRESS_BEU = SMC_CLUSTER_CORE1_BEU_REG_MAP_BASE_ADDR;
  }
  else if (hartid == 2)
  {
    BASE_ADDRESS_BEU = SMC_CLUSTER_CORE2_BEU_REG_MAP_BASE_ADDR;
  }
  else
  {
    BASE_ADDRESS_BEU = SMC_CLUSTER_CORE3_BEU_REG_MAP_BASE_ADDR;
  }

  volatile uint64_t *p_addr =
      (volatile uint64_t *)(uintptr_t)(BASE_ADDRESS_BEU + offset);
  return *p_addr;
}

static inline void write_wdt_reg(int hartid, uint64_t offset, uint64_t value)
{
  uint64_t BASE_ADDRESS_WDT;
  if (hartid == 0)
  {
    BASE_ADDRESS_WDT = SMC_CLUSTER_CORE0_WDT_REG_MAP_BASE_ADDR;
  }
  else if (hartid == 1)
  {
    BASE_ADDRESS_WDT = SMC_CLUSTER_CORE1_WDT_REG_MAP_BASE_ADDR;
  }
  else if (hartid == 2)
  {
    BASE_ADDRESS_WDT = SMC_CLUSTER_CORE2_WDT_REG_MAP_BASE_ADDR;
  }
  else
  {
    BASE_ADDRESS_WDT = SMC_CLUSTER_CORE3_WDT_REG_MAP_BASE_ADDR;
  }

  volatile uint64_t *p_addr =
      (volatile uint64_t *)(uintptr_t)(BASE_ADDRESS_WDT + offset);
  *p_addr = value;
}

static inline uint64_t read_wdt_reg(int hartid, uint64_t offset)
{
  uint64_t BASE_ADDRESS_WDT;
  if (hartid == 0)
  {
    BASE_ADDRESS_WDT = SMC_CLUSTER_CORE0_WDT_REG_MAP_BASE_ADDR;
  }
  else if (hartid == 1)
  {
    BASE_ADDRESS_WDT = SMC_CLUSTER_CORE1_WDT_REG_MAP_BASE_ADDR;
  }
  else if (hartid == 2)
  {
    BASE_ADDRESS_WDT = SMC_CLUSTER_CORE2_WDT_REG_MAP_BASE_ADDR;
  }
  else
  {
    BASE_ADDRESS_WDT = SMC_CLUSTER_CORE3_WDT_REG_MAP_BASE_ADDR;
  }

  volatile uint64_t *p_addr =
      (volatile uint64_t *)(uintptr_t)(BASE_ADDRESS_WDT + offset);
  return *p_addr;
}

// static inline void peripherals_out_of_reset(void)
// {
//   // Take all peripherals out of reset
//   SMC_WRAP_RESET_UNIT_MASTER_PERIPHERAL_RESETS_reg_u peripheral_reset_ctrl;
//   peripheral_reset_ctrl.val = read_reg(RESET_UNIT_PERIPHERAL_RESETS_REG_ADDR);
//   peripheral_reset_ctrl.f.avs_reset_n_n0_scan = 1;
//   peripheral_reset_ctrl.f.i2c_reset_n_n0_scan = 1;
//   peripheral_reset_ctrl.f.i3c_reset_n_n0_scan = 1;
//   peripheral_reset_ctrl.f.ptp_reset_n_n0_scan = 1;
//   peripheral_reset_ctrl.f.pvt_reset_n_n0_scan = 1;
//   peripheral_reset_ctrl.f.uart_reset_n_n0_scan = 1;
//   peripheral_reset_ctrl.f.telemetry_reset_n_n0_scan = 1;
//   write_reg(RESET_UNIT_PERIPHERAL_RESETS_REG_ADDR, peripheral_reset_ctrl.val);
// }

#ifndef SMC_PERIPH_PLL
#define LOCAL_SMC_PLL_CNTL_AG_MUX_SELECT_reg_u SMC_PLL_CNTL_AG_MUX_SELECT_reg_u
#define LOCAL_SMC_WRAP_PLL_CNTL_SMC_PLL_CNTL_AG_MUX_SELECT_REG_ADDR SMC_PLL_WRAP_PLL_CNTL_AG_MUX_SELECT_REG_ADDR //replace
#define LOCAL_SMC_PLL_CNTL_GPIO_CLK_OBS_CTRL_reg_u SMC_PLL_CNTL_GPIO_CLK_OBS_CTRL_reg_u
#define LOCAL_SMC_PLL_CNTL_GPIO_CLK_OBS_CTRL_REG_DEFAULT SMC_PLL_CNTL_GPIO_CLK_OBS_CTRL_REG_DEFAULT
#define LOCAL_SMC_WRAP_PLL_CNTL_SMC_PLL_CNTL_GPIO_CLK_OBS_CTRL_REG_ADDR SMC_PLL_WRAP_PLL_CNTL_GPIO_CLK_OBS_CTRL_REG_ADDR //replace
#define LOCAL_SMC_WRAP_PLL_CNTL_SMC_PLL_CNTL_CGM_0_STATUS_REG_OFFSET SMC_WRAP_PLL_CNTL_SMC_PLL_CNTL_CGM_0_STATUS_REG_OFFSET
#define LOCAL_SMC_WRAP_PLL_CNTL_SMC_PLL_CNTL_CGM_1_STATUS_REG_OFFSET SMC_WRAP_PLL_CNTL_SMC_PLL_CNTL_CGM_1_STATUS_REG_OFFSET
#define LOCAL_SMC_WRAP_PLL_CNTL_CGM_0_ENABLES_REG_OFFSET SMC_WRAP_PLL_CNTL_CGM_0_ENABLES_REG_OFFSET
#define LOCAL_SMC_PLL_CNTL_CGM_STATUS_reg_u SMC_PLL_CNTL_CGM_STATUS_reg_u
#else
#define LOCAL_SMC_PLL_CNTL_AG_MUX_SELECT_reg_u SMC_PERIPH_PLL_CNTL_CGM_AG_MUX_SELECT_reg_u
#define LOCAL_SMC_WRAP_PLL_CNTL_SMC_PLL_CNTL_AG_MUX_SELECT_REG_ADDR SMC_WRAP_PLL_CNTL_SMC_PERIPH_PLL_CNTL_CGM_AG_MUX_SELECT_REG_ADDR
#define LOCAL_SMC_PLL_CNTL_GPIO_CLK_OBS_CTRL_reg_u SMC_PERIPH_PLL_CNTL_GPIO_CLK_OBS_CTRL_reg_u
#define LOCAL_SMC_WRAP_PLL_CNTL_SMC_PLL_CNTL_GPIO_CLK_OBS_CTRL_REG_ADDR SMC_WRAP_PLL_CNTL_SMC_PERIPH_PLL_CNTL_GPIO_CLK_OBS_CTRL_REG_ADDR
#define LOCAL_SMC_WRAP_PLL_CNTL_SMC_PLL_CNTL_CGM_0_STATUS_REG_OFFSET SMC_WRAP_PLL_CNTL_CGM_0_CGM_STATUS_REG_OFFSET
#define LOCAL_SMC_WRAP_PLL_CNTL_SMC_PLL_CNTL_CGM_1_STATUS_REG_OFFSET SMC_WRAP_PLL_CNTL_CGM_1_CGM_STATUS_REG_OFFSET
#define LOCAL_SMC_PLL_CNTL_GPIO_CLK_OBS_CTRL_REG_DEFAULT SMC_PERIPH_PLL_CNTL_GPIO_CLK_OBS_CTRL_REG_DEFAULT
#define LOCAL_SMC_PLL_CNTL_CGM_STATUS_reg_u SMC_PERIPH_PLL_CNTL_CGM_STATUS_reg_u
#endif

static inline void switch_pll_mux_functional(void)
{
  // Set select line to 1 to select pll output for awm and cgm muxes
  PLL_CNTL_AG_MUX_SELECT_reg_u ag_mux_sel;
  ag_mux_sel.val = read_reg(SMC_PLL_WRAP_PLL_CNTL_AG_MUX_SELECT_REG_ADDR);
#ifndef SMC_PERIPH_PLL
  ag_mux_sel.f.cgm_clkmux_sel = 0xFF;
#endif
  ag_mux_sel.f.cgm_ag_mux_sel = 0xFF;
#ifndef SMC_PERIPH_PLL
  ag_mux_sel.f.awm_clkmux_sel = 0x3F;
  ag_mux_sel.f.awm_ag_mux_sel = 0x3F;
#endif
  write_reg(SMC_PLL_WRAP_PLL_CNTL_AG_MUX_SELECT_REG_ADDR, ag_mux_sel.val);
}

static inline void select_clock_for_gpio_obs(int clk_id)
{
  PLL_CNTL_GPIO_CLK_OBS_CTRL_reg_u gpio_clk_obs_ctrl = {
      .val = PLL_CNTL_GPIO_CLK_OBS_CTRL_REG_DEFAULT};

  gpio_clk_obs_ctrl.f.gpio_mux_sel = clk_id & 0b111;
  gpio_clk_obs_ctrl.f.postdiv_update_div = 0x1;
  gpio_clk_obs_ctrl.f.postdiv_divider = 0x1; // divide value is programmed + 1
  gpio_clk_obs_ctrl.f.clk_obs_en = 0x1;

  write_reg(SMC_PLL_WRAP_PLL_CNTL_GPIO_CLK_OBS_CTRL_REG_ADDR,
            gpio_clk_obs_ctrl.val);
}

// Recipe to program the CGM plls.  The recipe was borrowed from example:
// /vendor_ip/movellus/mvls-cgm0814-full-release/mvls-cgm0802-simulation/cgm/sim/snps/vcs/tb_cgm_apb.sv
static inline int program_cgm(uint32_t pll_num, uint16_t fcw_int, uint16_t fcw_frac, uint16_t prediv,
                              uint16_t postdiv0, uint16_t postdiv1, uint16_t postdiv2, uint16_t postdiv3,
                              uint16_t postdiv0_config, uint16_t postdiv1_config,
                              uint16_t postdiv2_config, uint16_t postdiv3_config,
                              uint16_t freq_lock_threshold)
{

  uint32_t pll_ctrl_cgm_status_reg_offsets[] = {SMC_PLL_WRAP_PLL_CNTL_CGM_0_STATUS_REG_OFFSET,
                                                SMC_PLL_WRAP_PLL_CNTL_CGM_1_STATUS_REG_OFFSET};

  uint32_t max_num_supported_cgms = sizeof(pll_ctrl_cgm_status_reg_offsets) / sizeof(pll_ctrl_cgm_status_reg_offsets[0]);

  if (pll_num >= max_num_supported_cgms)
  {
    // Error out.  Tried to program a cgm that is not supported
    return -1;
  }

  CGM_ENABLES_reg_u cgm_0_enables;
  cgm_0_enables.val = read_cgm_pll_reg(pll_num, SMC_PLL_WRAP_CGM_0_ENABLES_REG_OFFSET);

  // enable CGM
  cgm_0_enables.f.cgm_enable = 1;
  cgm_0_enables.f.freq_acq_enable = 1;
  write_cgm_pll_reg(pll_num, SMC_PLL_WRAP_CGM_0_ENABLES_REG_OFFSET, cgm_0_enables.val);

  // set integer freq control - refclk * 16
  write_cgm_pll_reg(pll_num, SMC_PLL_WRAP_CGM_0_FCW_INT_REG_OFFSET, fcw_int);

  // set frac freq control - don't use
  write_cgm_pll_reg(pll_num, SMC_PLL_WRAP_CGM_0_FCW_FRAC_REG_OFFSET, fcw_frac);

  // set prediv - div refclk freq by 2^0 == 1
  write_cgm_pll_reg(pll_num, SMC_PLL_WRAP_CGM_0_PREDIV_REG_OFFSET, prediv);

  // set postdivs
  CGM_POSTDIV_ARRAY_0_reg_u postdivs;
  postdivs.val = CGM_POSTDIV_ARRAY_0_REG_DEFAULT;
  postdivs.f.postdiv0 = postdiv0; // 2^(set value) - 16 / (2^1) = 8
  postdivs.f.postdiv1 = postdiv1; // 2^(set value)
  postdivs.f.postdiv2 = postdiv2; // 2^(set value)
  postdivs.f.postdiv3 = postdiv3; // 2^(set value)

  write_cgm_pll_reg(pll_num, SMC_PLL_WRAP_CGM_0_POSTDIV_ARRAY_0_REG_OFFSET, postdivs.val);

  // set postdivs control
  CGM_POSTDIV_CONFIG_reg_u postdiv_config;
  postdiv_config.val = CGM_POSTDIV_CONFIG_REG_DEFAULT;
  postdiv_config.f.postdiv0_config =
      postdiv0_config;                                // bypass clkref until cgm is locked
  postdiv_config.f.postdiv1_config = postdiv1_config; // force clock gate
  postdiv_config.f.postdiv2_config = postdiv2_config; // force clock gate
  postdiv_config.f.postdiv3_config = postdiv3_config; // force clock gate

  write_cgm_pll_reg(pll_num, SMC_PLL_WRAP_CGM_0_POSTDIV_CONFIG_REG_OFFSET,
                    postdiv_config.val);

  // set freq lock threshold - 1% jitter (copied value from programming guide)
  write_cgm_pll_reg(pll_num, SMC_PLL_WRAP_CGM_0_LOCK_CONFIG_REG_OFFSET,
                    (freq_lock_threshold &
                     0x7F)); // todo i dont think this is hex 11 -> 11 = 0xB

  // reg update to push all values
  write_cgm_pll_reg(pll_num, SMC_PLL_WRAP_CGM_0_REG_UPDATE_REG_OFFSET, 0x1);

  // poll for lock
  PLL_CNTL_CGM_STATUS_reg_u pll_ctrl_cgm_status;
  do
  {
    // FIXME - make this either CGM0 or CGM1
    pll_ctrl_cgm_status.val = read_pll_ctrl_reg(pll_ctrl_cgm_status_reg_offsets[pll_num]);
  } while (pll_ctrl_cgm_status.f.lock_detect != 1);

  return 0;
}

static inline void wait_for_cgm_lock_smc(uint32_t pll_num)
{
  // Auxiliary chiplets only - other chiplet types delegate clock config to SEP ROM
  if (pll_num >= SMC_CGM_COUNT) {
    return; // Invalid CGM number for this chiplet type
  }

  // CGM status registers at regular intervals
  uint32_t status_reg_offset = SMC_CGM_STATUS_REG_INTERVAL + (pll_num * SMC_CGM_STATUS_REG_INTERVAL);

  // Poll for lock - CGM configured automatically from efuse
  PLL_CNTL_CGM_STATUS_reg_u pll_ctrl_cgm_status;
  do
  {
    pll_ctrl_cgm_status.val = read_pll_ctrl_reg(status_reg_offset);
  } while (pll_ctrl_cgm_status.f.lock_detect != 1);
}

#ifndef SMC_PERIPH_PLL
static inline void program_awm_freq_unit(uint32_t awm_id, uint32_t freq_unit,
                                         uint16_t fcw_int, uint16_t fcw_frac,
                                         uint16_t prediv, uint16_t postdiv,
                                         uint16_t postdiv_config,
                                         uint16_t freq_lock_threshold)
{
  uint32_t freq_unit_base_offset =
      SMC_PLL_WRAP_AWM_0_AWM_FREQUENCY0_A_REG_MAP_BASE_ADDR - SMC_PLL_WRAP_AWM_0_REG_MAP_BASE_ADDR;
  uint32_t fcw_int0_reg_offset = freq_unit_base_offset +
                                 SMC_PLL_WRAP_AWM_0_AWM_FREQUENCY0_A_FCW_INT0_REG_OFFSET +
                                 freq_unit * 0x40;
  uint32_t fcw_frac_reg_offset = freq_unit_base_offset +
                                 SMC_PLL_WRAP_AWM_0_AWM_FREQUENCY0_A_FCW_FRAC_REG_OFFSET +
                                 freq_unit * 0x40;
  uint32_t prediv_reg_offset = freq_unit_base_offset +
                               SMC_PLL_WRAP_AWM_0_AWM_FREQUENCY0_A_PREDIV_REG_OFFSET +
                               freq_unit * 0x40;
  uint32_t freq_acq_en_reg_offset =
      freq_unit_base_offset +
      SMC_PLL_WRAP_AWM_0_AWM_FREQUENCY0_A_FREQ_ACQ_ENABLES_REG_OFFSET + freq_unit * 0x40;

  // Set multiplcation factor: 30
  FREQUENCY0_FCW_INT0_reg_u frequency0_a_fcw_int0;
  frequency0_a_fcw_int0.val = read_awm_pll_reg(awm_id, fcw_int0_reg_offset);
  frequency0_a_fcw_int0.f.fcw_int = fcw_int;
  write_awm_pll_reg(awm_id, fcw_int0_reg_offset, frequency0_a_fcw_int0.val);

  // Set fractional factor: 0
  FREQUENCY0_FCW_FRAC_reg_u frequency0_a_fcw_frac;
  frequency0_a_fcw_frac.val = read_awm_pll_reg(awm_id, fcw_frac_reg_offset);
  frequency0_a_fcw_frac.f.fcw_frac = fcw_frac;
  write_awm_pll_reg(awm_id, fcw_frac_reg_offset, frequency0_a_fcw_frac.val);

  FREQUENCY0_PREDIV_reg_u awm_div_config;
  awm_div_config.val = read_awm_pll_reg(awm_id, prediv_reg_offset);
  awm_div_config.f.prediv = prediv; // do not pre-divide refclk
  awm_div_config.f.postdiv =
      postdiv; // minimum settings for post divider is divide-by-2 (value 1)
  awm_div_config.f.postdiv_config =
      postdiv_config; // bypass refclk before the lock and automatically switch
                      // to post-divided output after the lock
  awm_div_config.f.freq_lock_threshold =
      freq_lock_threshold; // indicate locked when the peak-to-peak period
                           // jitter is +/-1%
  write_awm_pll_reg(awm_id, prediv_reg_offset, awm_div_config.val);

  // Frequency acquisition enable
  FREQUENCY0_FREQ_ACQ_ENABLES_reg_u awm_freq_acq_config;
  awm_freq_acq_config.val = read_awm_pll_reg(awm_id, freq_acq_en_reg_offset);
  awm_freq_acq_config.f.freq_acq_enable = 1;
  write_awm_pll_reg(awm_id, freq_acq_en_reg_offset, awm_freq_acq_config.val);
}

// static inline void program_awm_freq_unit_floor(uint32_t awm_id, uint32_t freq_unit,
//                                                uint32_t floor,
//                                                uint8_t fcw_int, uint16_t fcw_frac,
//                                                uint8_t watch_duration, uint8_t floor_duration)
// {
//   uint32_t freq_unit_base_offset =
//       SMC_PLL_WRAP_AWM_0_AWM_FREQUENCY0_A_REG_MAP_BASE_ADDR - SMC_PLL_WRAP_AWM_0_REG_MAP_BASE_ADDR; //replace

//   uint32_t fcw_int_floor_reg_offset = SMC_PLL_WRAP_AWM_0_AWM_GLOBAL_A_FCW_INT_BOUND_REG_OFFSET;
//   uint16_t fcw_int_floor_shift = (floor % 2) ? 8 : 0;
//   uint16_t fcw_int_floor_mask = (floor % 2) ? 0xFF00 : 0x00FF;
//   uint32_t fcw_frac_floor_reg_offset = SMC_PLL_WRAP_AWM_0_AWM_GLOBAL_A_FCW_FRAC_UPPERBOUND_REG_OFFSET;
//   uint32_t dynamic_scheme_reg_offset = SMC_WRAP_PLL_CNTL_AWM_0_AWM_GLOBAL_A_DYNAMIC_SCHEME_2_REG_OFFSET;
//   if (floor == 3)
//   {
//     fcw_int_floor_reg_offset = SMC_WRAP_PLL_CNTL_AWM_0_AWM_FREQUENCY0_A_FCW_INT1_REG_OFFSET;
//     fcw_frac_floor_reg_offset = SMC_WRAP_PLL_CNTL_AWM_0_AWM_FREQUENCY0_A_FCW_FRAC3_REG_OFFSET;
//     dynamic_scheme_reg_offset = SMC_WRAP_PLL_CNTL_AWM_0_AWM_GLOBAL_A_DYNAMIC_SCHEME_4_REG_OFFSET;
//   }
//   else if (floor == 2)
//   {
//     fcw_int_floor_reg_offset = SMC_WRAP_PLL_CNTL_AWM_0_AWM_FREQUENCY0_A_FCW_INT1_REG_OFFSET;
//     fcw_frac_floor_reg_offset = SMC_WRAP_PLL_CNTL_AWM_0_AWM_FREQUENCY0_A_FCW_FRAC2_REG_OFFSET;
//     dynamic_scheme_reg_offset = SMC_WRAP_PLL_CNTL_AWM_0_AWM_GLOBAL_A_DYNAMIC_SCHEME_3_REG_OFFSET;
//   }
//   else if (floor == 1)
//   {
//     fcw_int_floor_reg_offset = SMC_WRAP_PLL_CNTL_AWM_0_AWM_FREQUENCY0_A_FCW_INT0_REG_OFFSET;
//     fcw_frac_floor_reg_offset = SMC_WRAP_PLL_CNTL_AWM_0_AWM_FREQUENCY0_A_FCW_FRAC1_REG_OFFSET;
//     dynamic_scheme_reg_offset = SMC_WRAP_PLL_CNTL_AWM_0_AWM_GLOBAL_A_DYNAMIC_SCHEME_2_REG_OFFSET;
//   }
//   else
//   {
//     fcw_int_floor_reg_offset = SMC_WRAP_PLL_CNTL_AWM_0_AWM_FREQUENCY0_A_FCW_INT0_REG_OFFSET;
//     fcw_frac_floor_reg_offset = SMC_WRAP_PLL_CNTL_AWM_0_AWM_FREQUENCY0_A_FCW_FRAC_REG_OFFSET;
//   }

//   uint32_t fcw_int_reg_offset = freq_unit_base_offset +
//                                 fcw_int_floor_reg_offset +
//                                 freq_unit * 0x40;
//   uint32_t fcw_frac_reg_offset = freq_unit_base_offset +
//                                  fcw_frac_floor_reg_offset +
//                                  freq_unit * 0x40;

//   // Set multiplcation factor: 30
//   uint16_t frequency0_a_fcw_int0;
//   frequency0_a_fcw_int0 = read_awm_pll_reg(awm_id, fcw_int_reg_offset);
//   uint16_t fcw_int_new_val = (frequency0_a_fcw_int0 & ~fcw_int_floor_mask) | (fcw_int << fcw_int_floor_shift);
//   write_awm_pll_reg(awm_id, fcw_int_reg_offset, fcw_int_new_val);

//   // Set fractional factor: 0
//   FREQUENCY0_FCW_FRAC_reg_u frequency0_a_fcw_frac;
//   frequency0_a_fcw_frac.val = read_awm_pll_reg(awm_id, fcw_frac_reg_offset);
//   frequency0_a_fcw_frac.f.fcw_frac = fcw_frac;
//   write_awm_pll_reg(awm_id, fcw_frac_reg_offset, frequency0_a_fcw_frac.val);

//   if (floor != 0)
//   {
//     GLOBAL_DYNAMIC_SCHEME_2_reg_u global_dynamic_scheme;
//     global_dynamic_scheme.val = read_awm_pll_reg(awm_id, dynamic_scheme_reg_offset);
//     global_dynamic_scheme.f.watch_duration_1 = watch_duration;
//     global_dynamic_scheme.f.floor_duration_1 = floor_duration;
//     write_awm_pll_reg(awm_id, dynamic_scheme_reg_offset, global_dynamic_scheme.val);
//   }
// }

// static inline void program_awm0_functional(void)
// {
//   // -----------------------------
//   // PROGRAM AWM 0, clk 0: NoC - 1500 MHz
//   //                clk 1: N/A
//   //                clk 2: Static clock for Peripherals - 200 MHz
//   // -----------------------------

//   // CLOCK 0 - Dynamic w/ 2 DVFS Modes, 3 Floors per Mode

//   // -- DVFS Mode 0 --
//   // Mode 0 Main Frequency (F0) - 1500 Mhz
//   uint16_t freq0_fcw_int = 30;
//   uint16_t freq0_fcw_frac = 0;
//   uint16_t freq0_prediv = 0;
//   uint16_t freq0_postdiv = 1;
//   uint16_t freq0_postdiv_config = 0;
//   uint16_t freq0_freq_lock_threshold = 11;

//   program_awm_freq_unit(0, 0, freq0_fcw_int, freq0_fcw_frac, freq0_prediv,
//                         freq0_postdiv, freq0_postdiv_config,
//                         freq0_freq_lock_threshold);

//   // Setup 3 Floors for DVFS Mode 0
//   // Mode 0 Floor 1 (F1) - 1450 Mhz
//   uint8_t floor1_fcw_int = 29;
//   uint16_t floor1_fcw_frac = 0;
//   uint8_t floor1_watch_duration = 1;
//   uint8_t floor1_floor_duration = 1;
//   program_awm_freq_unit_floor(0, 0, 1, floor1_fcw_int, floor1_fcw_frac,
//                               floor1_watch_duration, floor1_floor_duration);

//   // Mode 0 Floor 2 (F2) - 1400 Mhz
//   uint8_t floor2_fcw_int = 28;
//   uint16_t floor2_fcw_frac = 0;
//   uint8_t floor2_watch_duration = 1;
//   uint8_t floor2_floor_duration = 1;
//   program_awm_freq_unit_floor(0, 0, 2, floor2_fcw_int, floor2_fcw_frac,
//                               floor2_watch_duration, floor2_floor_duration);

//   // Mode 0 Floor 3 (F3) - 1350 Mhz
//   uint8_t floor3_fcw_int = 27;
//   uint16_t floor3_fcw_frac = 0;
//   uint8_t floor3_watch_duration = 1;
//   uint8_t floor3_floor_duration = 1;
//   program_awm_freq_unit_floor(0, 0, 3, floor3_fcw_int, floor3_fcw_frac,
//                               floor3_watch_duration, floor3_floor_duration);

//   // -- DVFS Mode 1 --
//   // Mode 1 Main Frequency (F0) -  - 1300 Mhz
//   uint16_t freq1_fcw_int = 26;
//   uint16_t freq1_fcw_frac = 0;
//   uint16_t freq1_prediv = 0;
//   uint16_t freq1_postdiv = 1;
//   uint16_t freq1_postdiv_config = 0;
//   uint16_t freq1_freq_lock_threshold = 11;

//   program_awm_freq_unit(0, 1, freq1_fcw_int, freq1_fcw_frac, freq1_prediv,
//                         freq1_postdiv, freq1_postdiv_config,
//                         freq1_freq_lock_threshold);

//   // Mode 1 Floor 1 (F1) - 1250 Mhz
//   floor1_fcw_int = 25;
//   floor1_fcw_frac = 0;
//   floor1_watch_duration = 1;
//   floor1_floor_duration = 1;
//   program_awm_freq_unit_floor(0, 1, 1, floor1_fcw_int, floor1_fcw_frac,
//                               floor1_watch_duration, floor1_floor_duration);

//   // Mode 1 Floor 2 (F2) - 1200 Mhz
//   floor2_fcw_int = 24;
//   floor2_fcw_frac = 0;
//   floor2_watch_duration = 1;
//   floor2_floor_duration = 1;
//   program_awm_freq_unit_floor(0, 1, 2, floor2_fcw_int, floor2_fcw_frac,
//                               floor2_watch_duration, floor2_floor_duration);

//   // Mode 1 Floor 3 (F3) - 1150 Mhz
//   floor3_fcw_int = 23;
//   floor3_fcw_frac = 0;
//   floor3_watch_duration = 1;
//   floor3_floor_duration = 1;
//   program_awm_freq_unit_floor(0, 1, 3, floor3_fcw_int, floor3_fcw_frac,
//                               floor3_watch_duration, floor3_floor_duration);

//   // CLOCK 2 - Static Clock for Peripherals
//   uint16_t freq2_fcw_int = 16;
//   uint16_t freq2_fcw_frac = 0;
//   uint16_t freq2_prediv = 0;
//   uint16_t freq2_postdiv = 3;
//   uint16_t freq2_postdiv_config = 0;
//   uint16_t freq2_freq_lock_threshold = 11;

//   program_awm_freq_unit(0, 2, freq2_fcw_int, freq2_fcw_frac, freq2_prediv,
//                         freq2_postdiv, freq2_postdiv_config,
//                         freq2_freq_lock_threshold);

//   // Enable Clock Generation Moduel and the Oscillator
//   CGM2_ENABLES_reg_u awm_cgm2_config;
//   awm_cgm2_config.val = read_reg(SMC_PLL_WRAP_AWM_0_AWM_CGM2_A_ENABLES_REG_ADDR); //replace
//   awm_cgm2_config.f.static_cgm_enable = 1;
//   write_reg(SMC_PLL_WRAP_AWM_0_AWM_CGM2_A_ENABLES_REG_ADDR, awm_cgm2_config.val); //replace

//   // Programming AWM 0 as 1 Dynamic clock w/ 2-DVFS Modes (Hop-based) + 1 Static Clock
//   GLOBAL_RESOURCE_CONFIGURATION_ENABLES_reg_u global_resource_configuration_enables = {0};
//   global_resource_configuration_enables.f.resource_configuration_dynamic_ramp = 0;
//   global_resource_configuration_enables.f.resource_configuration_dynamic_hop = 2;
//   global_resource_configuration_enables.f.resource_configuration_static = 1;
//   global_resource_configuration_enables.f.droop_response_enable = 1;
//   write_reg(SMC_PLL_WRAP_AWM_0_AWM_GLOBAL_A_RESOURCE_CONFIGURATION_ENABLES_REG_ADDR, global_resource_configuration_enables.val); //replace

//   GLOBAL_DYNAMIC_SCHEME_0_reg_u awm_global_dynamic_scheme_0;
//   awm_global_dynamic_scheme_0.f.dvfs_mode = 0; // 2 DVFS Hop
//   write_reg(SMC_PLL_WRAP_AWM_0_AWM_GLOBAL_A_DYNAMIC_SCHEME_0_REG_ADDR, awm_global_dynamic_scheme_0.val); //replace

//   // Out clock selection
//   SMC_PLL_CNTL_AWM_CTRL_reg_u awm_0_ctrl;
//   awm_0_ctrl.f.freq_sel_one_hot_clk0 = 1; // out 0 select clock 0
//   awm_0_ctrl.f.freq_sel_one_hot_clk1 = 1;
//   awm_0_ctrl.f.freq_sel_one_hot_clk2 = 4; // out 2 select clock 2 (100)
//   write_pll_ctrl_reg(SMC_WRAP_PLL_CNTL_SMC_PLL_CNTL_AWM_0_CTRL_REG_OFFSET, awm_0_ctrl.val);

//   // All register writes done above become effective only after toggling
//   // reg_update. reg_update is self-cleared
//   write_reg(SMC_PLL_WRAP_AWM_0_AWM_GLOBAL_A_REG_UPDATE_REG_ADDR, 1); //replace

//   // Poll for lock
//   SMC_PLL_CNTL_AWM_STATUS_reg_u pll_ctrl_awm_status;
//   do
//   {
//     pll_ctrl_awm_status.val =
//         read_pll_ctrl_reg(SMC_WRAP_PLL_CNTL_SMC_PLL_CNTL_AWM_0_STATUS_REG_OFFSET);
//   } while (pll_ctrl_awm_status.f.lock_detect != 7); // lock = 111 - All three CGMs are used and need to lock
// }

// static inline void program_awm1_functional(void)
// {
//   // -----------------------------
//   // PROGRAM AWM 1, clk 0: DM - 2000 MHz
//   // -----------------------------

//   uint16_t freq0_fcw_int = 40;
//   uint16_t freq0_fcw_frac = 0;
//   uint16_t freq0_prediv = 0;
//   uint16_t freq0_postdiv = 1;
//   uint16_t freq0_postdiv_config = 0;
//   uint16_t freq0_freq_lock_threshold = 11;

//   program_awm_freq_unit(1, 0, freq0_fcw_int, freq0_fcw_frac, freq0_prediv,
//                         freq0_postdiv, freq0_postdiv_config,
//                         freq0_freq_lock_threshold);

//   // -- DVFS Mode 1 --
//   // Mode 1 Main Frequency (F0) -  - 1950 Mhz
//   uint16_t freq1_fcw_int = 39;
//   uint16_t freq1_fcw_frac = 0;
//   uint16_t freq1_prediv = 0;
//   uint16_t freq1_postdiv = 1;
//   uint16_t freq1_postdiv_config = 0;
//   uint16_t freq1_freq_lock_threshold = 11;

//   program_awm_freq_unit(1, 1, freq1_fcw_int, freq1_fcw_frac, freq1_prediv,
//                         freq1_postdiv, freq1_postdiv_config,
//                         freq1_freq_lock_threshold);

//   // -- DVFS Mode 2 --
//   // Mode 2 Main Frequency (F0) -  - 1900 Mhz
//   uint16_t freq2_fcw_int = 38;
//   uint16_t freq2_fcw_frac = 0;
//   uint16_t freq2_prediv = 0;
//   uint16_t freq2_postdiv = 1;
//   uint16_t freq2_postdiv_config = 0;
//   uint16_t freq2_freq_lock_threshold = 11;

//   program_awm_freq_unit(1, 2, freq2_fcw_int, freq2_fcw_frac, freq2_prediv,
//                         freq2_postdiv, freq2_postdiv_config,
//                         freq2_freq_lock_threshold);

//   // -- DVFS Mode 3 --
//   // Mode 3 Main Frequency (F0) -  - 1850 Mhz
//   uint16_t freq3_fcw_int = 37;
//   uint16_t freq3_fcw_frac = 0;
//   uint16_t freq3_prediv = 0;
//   uint16_t freq3_postdiv = 1;
//   uint16_t freq3_postdiv_config = 0;
//   uint16_t freq3_freq_lock_threshold = 11;

//   program_awm_freq_unit(1, 3, freq3_fcw_int, freq3_fcw_frac, freq3_prediv,
//                         freq3_postdiv, freq3_postdiv_config,
//                         freq3_freq_lock_threshold);

//   // -- DVFS Mode 4 --
//   // Mode 4 Main Frequency (F0) -  - 1850 Mhz
//   uint16_t freq4_fcw_int = 36;
//   uint16_t freq4_fcw_frac = 0;
//   uint16_t freq4_prediv = 0;
//   uint16_t freq4_postdiv = 1;
//   uint16_t freq4_postdiv_config = 0;
//   uint16_t freq4_freq_lock_threshold = 11;

//   program_awm_freq_unit(1, 4, freq4_fcw_int, freq4_fcw_frac, freq4_prediv,
//                         freq4_postdiv, freq4_postdiv_config,
//                         freq4_freq_lock_threshold);

//   // Programming AWM 1 as 1 Dynamic clock w/ 5-DVFS Modes (Ramp-based)
//   GLOBAL_RESOURCE_CONFIGURATION_ENABLES_reg_u global_resource_configuration_enables = {0};
//   global_resource_configuration_enables.f.resource_configuration_dynamic_ramp = 5;
//   global_resource_configuration_enables.f.resource_configuration_dynamic_hop = 0;
//   global_resource_configuration_enables.f.resource_configuration_static = 0;
//   global_resource_configuration_enables.f.droop_response_enable = 1;
//   write_reg(SMC_PLL_WRAP_AWM_1_AWM_GLOBAL_A_RESOURCE_CONFIGURATION_ENABLES_REG_ADDR, global_resource_configuration_enables.val); //replace

//   GLOBAL_DYNAMIC_SCHEME_0_reg_u awm_global_dynamic_scheme_0;
//   awm_global_dynamic_scheme_0.f.dvfs_mode = 0; // 2 DVFS Hop
//   write_reg(SMC_PLL_WRAP_AWM_1_AWM_GLOBAL_A_DYNAMIC_SCHEME_0_REG_ADDR, awm_global_dynamic_scheme_0.val); //replace

//   SMC_PLL_CNTL_AWM_CTRL_reg_u awm_0_ctrl;
//   awm_0_ctrl.f.freq_sel_one_hot_clk0 = 1;
//   awm_0_ctrl.f.freq_sel_one_hot_clk1 = 1;
//   awm_0_ctrl.f.freq_sel_one_hot_clk2 = 1;
//   write_pll_ctrl_reg(SMC_WRAP_PLL_CNTL_SMC_PLL_CNTL_AWM_1_CTRL_REG_OFFSET, awm_0_ctrl.val);

//   // All register writes done above become effective only after toggling
//   // reg_update. reg_update is self-cleared
//   write_reg(SMC_PLL_WRAP_AWM_1_AWM_GLOBAL_A_REG_UPDATE_REG_ADDR, 1); //replace

//   // Poll for lock
//   SMC_PLL_CNTL_AWM_STATUS_reg_u pll_ctrl_awm_1_status;
//   do
//   {
//     pll_ctrl_awm_1_status.val =
//         read_pll_ctrl_reg(SMC_WRAP_PLL_CNTL_SMC_PLL_CNTL_AWM_1_STATUS_REG_OFFSET);
//   } while (pll_ctrl_awm_1_status.f.lock_detect != 1);
// }

/* Auxiliary chiplet PLL configuration functions */

// static inline void wait_for_cgm_locks_smc(void)
// {
//   // Wait for all CGMs to lock (CGM0 to CGM_COUNT-1)
//   // CGM configuration values come from efuse shadow registers via i_cgm_init_code
//   // Hardware automatically programs: fcw_int, fcw_frac, prediv, postdiv0-3,
//   // cgm_enable, freq_acq_enable, freq_lock_threshold
//   for (int cgm = 0; cgm < SMC_CGM_COUNT; cgm++) {
//     wait_for_cgm_lock_smc(cgm);
//   }
// }

// static inline void configure_cgm2_peripheral_200mhz(void)
// {
//   // Configure CGM2 to generate 200MHz peripheral clock from 100MHz reference clock
//   // This is only needed for auxiliary chiplets when using refclk mode
//   // Formula: Fout = Fref × FCW_INT / 2^POSTDIV
//   // Calculate: FCW_INT = Fout / Fref = 200MHz / 100MHz = 2, POSTDIV = 0
//   uint16_t fcw_int = PERIPHERAL_REFCLK_OUTPUT_FREQ_MHZ / REFCLK_FREQ_MHZ;

//   // Enable CGM2
//   CGM_ENABLES_reg_u cgm_2_enables;
//   cgm_2_enables.val = read_cgm_pll_reg(2, SMC_WRAP_PLL_CNTL_CGM_0_ENABLES_REG_OFFSET);
//   cgm_2_enables.f.cgm_enable = 1;
//   cgm_2_enables.f.freq_acq_enable = 1;
//   write_cgm_pll_reg(2, SMC_WRAP_PLL_CNTL_CGM_0_ENABLES_REG_OFFSET, cgm_2_enables.val);

//   // Set frequency control word for calculated multiplication
//   write_cgm_pll_reg(2, SMC_WRAP_PLL_CNTL_CGM_0_FCW_INT_REG_OFFSET, fcw_int);

//   // Set fractional part to 0 (not used)
//   write_cgm_pll_reg(2, SMC_WRAP_PLL_CNTL_CGM_0_FCW_FRAC_REG_OFFSET, 0);

//   // Set predivider to 0 (no pre-division)
//   write_cgm_pll_reg(2, SMC_WRAP_PLL_CNTL_CGM_0_PREDIV_REG_OFFSET, 0);

//   // Set post-dividers (POSTDIV0 = 0 for divide by 1)
//   CGM_POSTDIV_ARRAY_0_reg_u postdivs;
//   postdivs.val = CGM_POSTDIV_ARRAY_0_REG_DEFAULT;
//   postdivs.f.postdiv0 = 0;  // 2^0 = 1 (no division)
//   postdivs.f.postdiv1 = 0;
//   postdivs.f.postdiv2 = 0;
//   postdivs.f.postdiv3 = 0;
//   write_cgm_pll_reg(2, SMC_WRAP_PLL_CNTL_CGM_0_POSTDIV_ARRAY_0_REG_OFFSET, postdivs.val);

//   // Set post-divider configuration (bypass refclk until locked)
//   CGM_POSTDIV_CONFIG_reg_u postdiv_config;
//   postdiv_config.val = CGM_POSTDIV_CONFIG_REG_DEFAULT;
//   postdiv_config.f.postdiv0_config = 0; // Bypass clkref until cgm is locked
//   postdiv_config.f.postdiv1_config = 1; // Force clock gate
//   postdiv_config.f.postdiv2_config = 1; // Force clock gate
//   postdiv_config.f.postdiv3_config = 1; // Force clock gate
//   write_cgm_pll_reg(2, SMC_WRAP_PLL_CNTL_CGM_0_POSTDIV_CONFIG_REG_OFFSET, postdiv_config.val);

//   // Set frequency lock threshold
//   write_cgm_pll_reg(2, SMC_WRAP_PLL_CNTL_CGM_0_LOCK_CONFIG_REG_OFFSET, 0x0B); // 1% jitter

//   // Trigger register update
//   write_cgm_pll_reg(2, SMC_WRAP_PLL_CNTL_CGM_0_REG_UPDATE_REG_OFFSET, 0x1);

//   // Wait for CGM2 lock
//   wait_for_cgm_lock_smc(2);
// }


// static inline uint32_t get_peripheral_clock_frequency_mhz(void)
// {
//   // Determine the current peripheral clock frequency based on actual CGM mux configuration
//   // All chiplets must configure peripherals with correct frequency regardless of chiplet type
//   //
//   // IMPORTANT: Don't rely solely on BL0_PLLCLK strap - individual CGM muxes can override!
//   // Even when BL0_PLLCLK is deasserted, specific CGMs may still use PLL via mux configuration.

//   // Check CGM2 mux configuration to determine actual clock source
//   // CGM2 is used for peripheral clock on all chiplets
//   // AG_MUX_SELECT register: "0 for refclk and 1 for pll"
//   // CGM2 uses bits 8-11 (4 bits per CGM, CGM2 is index 2: bits 8-11)
//   uint32_t ag_mux_select = read_reg(LOCAL_SMC_WRAP_PLL_CNTL_SMC_PLL_CNTL_AG_MUX_SELECT_REG_ADDR);
//   uint32_t cgm2_mux_bits = (ag_mux_select >> 8) & 0xF; // Extract CGM2 mux bits [11:8]

//   if (cgm2_mux_bits != 0) {
//     // CGM2 mux is configured to use PLL - calculate frequency from CGM2 registers
//     // Hardware automatically configures CGM registers from efuse via i_cgm_init_code
//     //
//     // RTL Reference: CGM instances have i_init_code input interface
//     // - tt_cgm_pll_wrapper.sv:211 shows i_init_code[i] input (80 bits per CGM)
//     // - Movellus vendor IP automatically loads configuration from efuse shadow registers

//     // Read CGM2 frequency control word and dividers from registers
//     uint16_t fcw_int = read_cgm_pll_reg(2, SMC_WRAP_PLL_CNTL_CGM_0_FCW_INT_REG_OFFSET);
//     uint16_t postdiv_array = read_cgm_pll_reg(2, SMC_WRAP_PLL_CNTL_CGM_0_POSTDIV_ARRAY_0_REG_OFFSET);
//     uint16_t postdiv0 = postdiv_array & 0x7;  // Extract postdiv0 (bits 2:0)

//     // Calculate frequency using Movellus CGM vendor formula: Fout = Fref * FCW / 2^POSTDIV
//     // Source: cgm.rdl:52 - "Integer part of FCW... Fout=Fref*FCW/2**postdiv"
//     // Where Fref = 100MHz (reference clock)
//     uint32_t frequency_mhz = (REFCLK_FREQ_MHZ * fcw_int) >> postdiv0;
//     return frequency_mhz;
//   } else {
//     // CGM2 mux is configured to use reference clock
//     // Peripheral clock should run at 200MHz in refclk mode
//     // Configured by configure_cgm2_peripheral_200mhz()
//     return PERIPHERAL_REFCLK_OUTPUT_FREQ_MHZ;
//   }
// }

// static inline uint32_t get_core_clock_frequency_mhz(void)
// {
//   // Determine the current core clock frequency based on actual CGM mux configuration
//   // All chiplets must configure core with correct frequency regardless of chiplet type
//   //
//   // Check CGM0 mux configuration to determine actual clock source
//   // CGM0 is used for core clock (SMC System Clock) on all chiplets
//   // AG_MUX_SELECT register: "0 for refclk and 1 for pll"
//   // CGM0 uses bits 0-3 (4 bits per CGM, CGM0 is index 0: bits 3:0)
//   uint32_t ag_mux_select = read_reg(LOCAL_SMC_WRAP_PLL_CNTL_SMC_PLL_CNTL_AG_MUX_SELECT_REG_ADDR);
//   uint32_t cgm0_mux_bits = ag_mux_select & 0xF; // Extract CGM0 mux bits [3:0]

//   if (cgm0_mux_bits != 0) {
//     // CGM0 mux is configured to use PLL - calculate frequency from CGM0 registers
//     // Hardware automatically configures CGM registers from efuse via i_cgm_init_code
//     //
//     // RTL Reference: CGM instances have i_init_code input interface
//     // - tt_cgm_pll_wrapper.sv:211 shows i_init_code[i] input (80 bits per CGM)
//     // - Movellus vendor IP automatically loads configuration from efuse shadow registers

//     // Read CGM0 frequency control word and dividers from registers
//     uint16_t fcw_int = read_cgm_pll_reg(0, SMC_WRAP_PLL_CNTL_CGM_0_FCW_INT_REG_OFFSET);
//     uint16_t postdiv_array = read_cgm_pll_reg(0, SMC_WRAP_PLL_CNTL_CGM_0_POSTDIV_ARRAY_0_REG_OFFSET);
//     uint16_t postdiv0 = postdiv_array & 0x7;  // Extract postdiv0 (bits 2:0)

//     // Calculate frequency using Movellus CGM vendor formula: Fout = Fref * FCW / 2^POSTDIV
//     // Source: cgm.rdl:52 - "Integer part of FCW... Fout=Fref*FCW/2**postdiv"
//     // Where Fref = 100MHz (reference clock)
//     uint32_t frequency_mhz = (REFCLK_FREQ_MHZ * fcw_int) >> postdiv0;
//     return frequency_mhz;
//   } else {
//     // CGM0 mux is configured to use reference clock
//     // In refclk mode, core runs directly from the reference clock at 100MHz
//     return REFCLK_FREQ_MHZ;
//   }
// }

// static inline void switch_pll_mux_functional(void)
// {
//   // Switch all CGM muxes to PLL sources
//   write_reg(LOCAL_SMC_WRAP_PLL_CNTL_SMC_PLL_CNTL_AG_MUX_SELECT_REG_ADDR, 0x01111111); // Main PLL clock mux select
//   write_reg(LOCAL_SMC_WRAP_PLL_CNTL_SMC_PLL_CNTL_AG_MUX_SELECT_REG_ADDR + 0x8, 0x01111111); // Peripheral PLL clock mux select
// }

// static inline void program_clocks(void)
// {
//   // Hardware automatically configures CGM registers from efuse values
//   // via i_cgm_init_code inputs. SMC ROM only needs to configure mux selection.

//   if (smc_strap_is_bl0_pllclk_enabled()) {
//     // PLL mode: Wait for PLL lock completion (CGMs configured automatically from efuse)
//     wait_for_cgm_locks_smc();

//     // Switch all clock muxes to use PLL sources
//     switch_pll_mux_functional();
//   } else {
//     // RefClk mode: Core runs directly from 100MHz refclk, only configure peripheral clock
//     configure_cgm2_peripheral_200mhz();   // CGM2: Peripheral clock at 200MHz
//   }
// }

#endif
#endif /* SMC_DEFINES_H */
