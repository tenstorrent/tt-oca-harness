
#ifndef __SMC_DEFINES_DEFINED__
#define __SMC_DEFINES_DEFINED__

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include "virt_console.h"

#include "smc_top_regs.h"

// SMC Strap bit positions (based on smc_utils.py)
typedef enum
{
  SMC_STRAP_SEP_BYPASS_MEM_REPAIR = 13,
  SMC_STRAP_SEP_TEST_EN = 14,
  SMC_STRAP_BOOT_STALL = 17,
  SMC_STRAP_BOOT_I2C = 18,
  SMC_STRAP_SEP_USE_FUSED_CONFIG = 22,
  SMC_STRAP_PRIMARY_CHIPLET = 25,
  SMC_STRAP_DISABLE_SMC_AUTO_ZERO = 26,
  SMC_STRAP_BOOT_RECOVERY = 19,
  SMC_STRAP_BL0_PLLCLK = 20,
  SMC_STRAP_STATUS_RPT_DISABLE = 21,
  SMC_STRAP_ROTATE_UPDATE = 61,
  SMC_STRAP_CHIP_ID_0 = 57,
  SMC_STRAP_CHIP_ID_1 = 55,
  SMC_STRAP_CHIP_ID_2 = 12,
  SMC_STRAP_CHIP_ID_3 = 11
} SmcStrapBit;

#define NUM_EXTERNAL_INTERRUPTS (256)           /* 4-core: NUM_EXT_INTERRUPTS=256 */
#define MAILBOX_INTERUPT_ID_BASE (288)          /* cpu_interrupts_o[288] */

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

// Read strap value from GPIO_CTRL register's CONTROL field.
// Note: `strap_bit` selects which GPIO_CTRL register (GPIO index), not a bit position within the register.
static inline bool smc_strap_is_set(SmcStrapBit strap_bit)
{
  uint32_t reg_value;

  // Each GPIO_CTRL register is spaced 0x20 apart (GPIO_CTRL_1 - GPIO_CTRL_0 = 0xC0004460 - 0xC0004440)
  uint32_t gpio_ctrl_addr = GPIO_CTRL_0__CONTROL_REG_ADDR + (strap_bit * (GPIO_CTRL_1__REG_MAP_BASE_ADDR - GPIO_CTRL_0__REG_MAP_BASE_ADDR));

  reg_value = read_reg(gpio_ctrl_addr);

  // strap_valid/strap_value are hardware-written fields in GPIO_CTRL_x.CONTROL.
  // Use the generated mask definitions (do NOT use `strap_bit` as a bit index).
  return ((reg_value & GPIO_CTRL_CONTROL_STRAP_VALID_MASK) != 0) &&
         ((reg_value & GPIO_CTRL_CONTROL_STRAP_VALUE_MASK) != 0);
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
      (volatile uint64_t *)(uintptr_t)(DMA_CTRL_REG_MAP_BASE_ADDR +
                                       offset);
  *p_addr = value;
}

static inline uint64_t read_dma_ctrl_reg(uint64_t offset)
{
  volatile uint64_t *p_addr =
      (volatile uint64_t *)(uintptr_t)(DMA_CTRL_REG_MAP_BASE_ADDR +
                                       offset);
  return *p_addr;
}

static inline void write_zeroer_ctrl_reg(uint64_t offset, uint64_t value)
{
  volatile uint64_t *p_addr =
      (volatile uint64_t *)(uintptr_t)(ZEROER_CTRL_REG_MAP_BASE_ADDR +
                                       offset);
  *p_addr = value;
}

static inline uint64_t read_zeroer_ctrl_reg(uint64_t offset)
{
  volatile uint64_t *p_addr =
      (volatile uint64_t *)(uintptr_t)(ZEROER_CTRL_REG_MAP_BASE_ADDR +
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

// I3C DEPRICAED FOR NOW

// Use compound literals for static controller tables
#define CDNS_I3C_BASES                                           \
  ((const uint32_t[6]){SMC_AXIL_EXTENSION_CDNS_I3C_WRAP_0_CADENCE_I3C_REG_MAP_BASE_ADDR, \
                       SMC_AXIL_EXTENSION_CDNS_I3C_WRAP_1_CADENCE_I3C_REG_MAP_BASE_ADDR, \
                       SMC_AXIL_EXTENSION_CDNS_I3C_WRAP_2_CADENCE_I3C_REG_MAP_BASE_ADDR, \
                       SMC_AXIL_EXTENSION_CDNS_I3C_WRAP_3_CADENCE_I3C_REG_MAP_BASE_ADDR, \
                       SMC_AXIL_EXTENSION_CDNS_I3C_WRAP_4_CADENCE_I3C_REG_MAP_BASE_ADDR, \
                       SMC_AXIL_EXTENSION_CDNS_I3C_WRAP_5_CADENCE_I3C_REG_MAP_BASE_ADDR})

#define I3C_CTRL_BASES                                        \
  ((const uint32_t[6]){SMC_AXIL_EXTENSION_CDNS_I3C_WRAP_0_I3C_CTRL_REG_MAP_BASE_ADDR, \
                       SMC_AXIL_EXTENSION_CDNS_I3C_WRAP_1_I3C_CTRL_REG_MAP_BASE_ADDR, \
                       SMC_AXIL_EXTENSION_CDNS_I3C_WRAP_2_I3C_CTRL_REG_MAP_BASE_ADDR, \
                       SMC_AXIL_EXTENSION_CDNS_I3C_WRAP_3_I3C_CTRL_REG_MAP_BASE_ADDR, \
                       SMC_AXIL_EXTENSION_CDNS_I3C_WRAP_4_I3C_CTRL_REG_MAP_BASE_ADDR, \
                       SMC_AXIL_EXTENSION_CDNS_I3C_WRAP_5_I3C_CTRL_REG_MAP_BASE_ADDR})

// Force inline all accessors
static inline __attribute__((always_inline, const)) uint32_t
get_cdns_i3c_base_addr(uint8_t ctrl)
{
  if (__builtin_constant_p(ctrl))
  {
    /* Compile-time known controller: direct array access */
    return CDNS_I3C_BASES[ctrl];
  }
  else
  {
    /* Runtime controller with bounds check */
    return CDNS_I3C_BASES[ctrl < 6 ? ctrl : 0];
  }
}

static inline __attribute__((always_inline, const)) uint32_t
get_i3c_ctrl_reg_base_addr(uint8_t ctrl)
{
  if (__builtin_constant_p(ctrl))
  {
    return I3C_CTRL_BASES[ctrl];
  }
  else
  {
    return I3C_CTRL_BASES[ctrl < 6 ? ctrl : 0];
  }
}

// Memory access operations
#define MAKE_REG_ACCESSOR(name, base_getter)                          \
  static inline __attribute__((always_inline)) void write_##name(     \
      uint8_t ctrl, uint32_t offset, uint32_t val)                    \
  {                                                                   \
    volatile uint32_t *addr =                                         \
        (volatile uint32_t *)(uintptr_t)(base_getter(ctrl) + offset); \
    *addr = val;                                                      \
  }                                                                   \
  static inline __attribute__((always_inline)) uint32_t read_##name(  \
      uint8_t ctrl, uint32_t offset)                                  \
  {                                                                   \
    volatile uint32_t *addr =                                         \
        (volatile uint32_t *)(uintptr_t)(base_getter(ctrl) + offset); \
    return *addr;                                                     \
  }

// Generate all accessors
MAKE_REG_ACCESSOR(i3c, get_cdns_i3c_base_addr)
MAKE_REG_ACCESSOR(i3c_ctrl_reg, get_i3c_ctrl_reg_base_addr)

#undef MAKE_REG_ACCESSOR

static inline void write_gpio(uint8_t gpio_num, uint32_t offset,
                              uint32_t value)
{
  uint32_t gpio_spacing = 0x10;
  volatile uint32_t *p_addr =
      (volatile uint32_t *)(uintptr_t)(GPIO_INTF_0__REG_MAP_BASE_ADDR +
                                       gpio_num * gpio_spacing +
                                       offset);
  *p_addr = value;
}

static inline void write_gpio_shim(uint8_t gpio_num, uint32_t offset,
                                   uint32_t value)
{
  uint32_t gpio_spacing = 0x20;
  volatile uint32_t *p_addr =
      (volatile uint32_t *)(uintptr_t)(GPIO_CTRL_0__REG_MAP_BASE_ADDR +
                                       gpio_num * gpio_spacing +
                                       offset);
  *p_addr = value;
}

static inline uint32_t read_gpio(uint8_t gpio_num, uint32_t offset)
{
  uint32_t gpio_spacing = 0x10;
  volatile uint32_t *p_addr =
      (volatile uint32_t *)(uintptr_t)(GPIO_INTF_0__REG_MAP_BASE_ADDR +
                                       gpio_num * gpio_spacing +
                                       offset);
  return *p_addr;
}

static inline uint32_t read_gpio_shim(uint8_t gpio_num, uint32_t offset)
{
  uint32_t gpio_spacing = 0x20;
  volatile uint32_t *p_addr =
      (volatile uint32_t *)(uintptr_t)(GPIO_CTRL_0__REG_MAP_BASE_ADDR +
                                       gpio_num * gpio_spacing +
                                       offset);
  return *p_addr;
}

static inline void write_zeros(const uint32_t addr, const uint32_t size,
                               const bool int_en)
{
  write_zeroer_ctrl_reg(ZEROER_CTRL_DEST_ADDR_REG_OFFSET,
                        addr);
  write_zeroer_ctrl_reg(ZEROER_CTRL_SIZE_REG_OFFSET, size);
  write_zeroer_ctrl_reg(ZEROER_CTRL_CTRL_STATUS_REG_OFFSET,
                        int_en);

  while (read_zeroer_ctrl_reg(
      ZEROER_CTRL_CTRL_STATUS_REG_OFFSET))
    ;
}

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
      (volatile uint16_t *)(uintptr_t)(SMC_AVSBUS_CONTROLLER_REG_MAP_BASE_ADDR + offset);
  *p_addr = value;
}

static inline uint32_t read_abp2avsbus_ctrl_reg(uint32_t offset)
{
  volatile uint16_t *p_addr =
      (volatile uint16_t *)(uintptr_t)(SMC_AVSBUS_CONTROLLER_REG_MAP_BASE_ADDR + offset);
  return *p_addr;
}

static inline void write_cgm_pll_reg(uint32_t id, uint32_t offset,
                                     uint32_t value)
{
  volatile uint16_t *p_addr =
      (volatile uint16_t *)(uintptr_t)(SMC_PLL_WRAP_CGM_0_REG_MAP_BASE_ADDR + id * 0x100 +
                                       offset);
  *p_addr = value;
}

static inline uint32_t read_cgm_pll_reg(uint32_t id, uint32_t offset)
{
  volatile uint16_t *p_addr =
      (volatile uint16_t *)(uintptr_t)(SMC_PLL_WRAP_CGM_0_REG_MAP_BASE_ADDR + id * 0x100 +
                                       offset);
  return *p_addr;
}

#ifndef SMC_PERIPH_PLL
static inline void write_awm_pll_reg(uint32_t id, uint32_t offset,
                                     uint16_t value)
{
  volatile uint16_t *p_addr =
      (volatile uint16_t *)(uintptr_t)(SMC_PLL_WRAP_AWM_0_REG_MAP_BASE_ADDR + id * 0x600 +
                                       offset);
  *p_addr = value;
}

static inline uint16_t read_awm_pll_reg(uint32_t id, uint32_t offset)
{
  volatile uint16_t *p_addr =
      (volatile uint16_t *)(uintptr_t)(SMC_PLL_WRAP_AWM_0_REG_MAP_BASE_ADDR + id * 0x600 +
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
    BASE_ADDRESS_UART = SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_0__UART_LOG_ENGINE_CTRL_REG_MAP_BASE_ADDR;
  }
  else if (uart_id == 1)
  {
    BASE_ADDRESS_UART = SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_1__UART_LOG_ENGINE_CTRL_REG_MAP_BASE_ADDR;
  }
  else if (uart_id == 2)
  {
    BASE_ADDRESS_UART = SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_2__UART_LOG_ENGINE_CTRL_REG_MAP_BASE_ADDR;
  }
  else
  {
    BASE_ADDRESS_UART = SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_3__UART_LOG_ENGINE_CTRL_REG_MAP_BASE_ADDR;
  }

  volatile uint16_t *p_addr =
      (volatile uint16_t *)(uintptr_t)(BASE_ADDRESS_UART + offset);
  *p_addr = value;
}

// TODO: Check because UART and UART engine registers are the same
static inline uint32_t read_uart_engine_reg(int uart_id, uint32_t offset)
{
  uint32_t BASE_ADDRESS_UART;
  if (uart_id == 0)
  {
    BASE_ADDRESS_UART = SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_0__UART_LOG_ENGINE_CTRL_REG_MAP_BASE_ADDR;
  }
  else if (uart_id == 1)
  {
    BASE_ADDRESS_UART = SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_1__UART_LOG_ENGINE_CTRL_REG_MAP_BASE_ADDR;
  }
  else if (uart_id == 2)
  {
    BASE_ADDRESS_UART = SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_2__UART_LOG_ENGINE_CTRL_REG_MAP_BASE_ADDR;
  }
  else
  {
    BASE_ADDRESS_UART = SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_3__UART_LOG_ENGINE_CTRL_REG_MAP_BASE_ADDR;
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

// No more sw controlled peripherals

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

static inline void switch_pll_mux_functional_mimir(void)
{
  write_reg(0xC0003020, 0x01111111); // set all cgm muxes to pll
  write_reg(0xC0003028, 0x01111111); // set all cgm muxes to pll
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

static inline void program_cgm0_functional(void)
{
  // -----------------------------
  // PROGRAM CGM 0, clk 0: SMC - 800 MHz
  // -----------------------------
  uint32_t pll_num = 0;
  uint16_t fcw_int = 16;
  uint16_t fcw_frac = 0;
  uint16_t prediv = 0;
  uint16_t postdiv0 = 1; // All output clocks share same frequency
  uint16_t postdiv1 = 1; //   See above
  uint16_t postdiv2 = 1; //   See above
  uint16_t postdiv3 = 1; //   See above
  uint16_t postdiv0_cfg =
      0;                     // bypass clkref until cgm is locked - Note that only clk0 is used
  uint16_t postdiv1_cfg = 3; // force clock gate
  uint16_t postdiv2_cfg = 3; // force clock gate
  uint16_t postdiv3_cfg = 3; // force clock gate
  uint16_t freq_lock_threshold = 0xB;

  program_cgm(pll_num, fcw_int, fcw_frac, prediv,
              postdiv0, postdiv1, postdiv2, postdiv3,
              postdiv0_cfg, postdiv1_cfg,
              postdiv2_cfg, postdiv3_cfg,
              freq_lock_threshold);
}

static inline void program_cgm1_functional(void)
{
  // -----------------------------
  // PROGRAM CGM 1, clk 0: SoC - 400 MHz
  // -----------------------------
  uint32_t pll_num = 1;
  uint16_t fcw_int = 16;
  uint16_t fcw_frac = 0;
  uint16_t prediv = 0;
  uint16_t postdiv0 = 2; // All output clocks share same frequency
  uint16_t postdiv1 = 2; //   See above
  uint16_t postdiv2 = 2; //   See above
  uint16_t postdiv3 = 2; //   See above
  uint16_t postdiv0_cfg =
      0;                     // bypass clkref until cgm is locked - Note that only clk0 is used
  uint16_t postdiv1_cfg = 3; // force clock gate
  uint16_t postdiv2_cfg = 3; // force clock gate
  uint16_t postdiv3_cfg = 3; // force clock gate
  uint16_t freq_lock_threshold = 0xB;

  program_cgm(pll_num, fcw_int, fcw_frac, prediv,
              postdiv0, postdiv1, postdiv2, postdiv3,
              postdiv0_cfg, postdiv1_cfg,
              postdiv2_cfg, postdiv3_cfg,
              freq_lock_threshold);
}

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

static inline void program_awm_freq_unit_floor(uint32_t awm_id, uint32_t freq_unit,
                                               uint32_t floor,
                                               uint8_t fcw_int, uint16_t fcw_frac,
                                               uint8_t watch_duration, uint8_t floor_duration)
{
  uint32_t freq_unit_base_offset =
      SMC_PLL_WRAP_AWM_0_AWM_FREQUENCY0_A_REG_MAP_BASE_ADDR - SMC_PLL_WRAP_AWM_0_REG_MAP_BASE_ADDR;

  uint32_t fcw_int_floor_reg_offset = SMC_PLL_WRAP_AWM_0_AWM_FREQUENCY0_A_FCW_INT0_REG_OFFSET;
  uint16_t fcw_int_floor_shift = (floor % 2) ? 8 : 0;
  uint16_t fcw_int_floor_mask = (floor % 2) ? 0xFF00 : 0x00FF;
  uint32_t fcw_frac_floor_reg_offset = SMC_PLL_WRAP_AWM_0_AWM_FREQUENCY0_A_FCW_FRAC_REG_OFFSET;
  uint32_t dynamic_scheme_reg_offset = SMC_PLL_WRAP_AWM_0_AWM_GLOBAL_A_DYNAMIC_SCHEME_2_REG_OFFSET;
  if (floor == 3)
  {
    fcw_int_floor_reg_offset = SMC_PLL_WRAP_AWM_0_AWM_FREQUENCY0_A_FCW_INT1_REG_OFFSET;
    fcw_frac_floor_reg_offset = SMC_PLL_WRAP_AWM_0_AWM_FREQUENCY0_A_FCW_FRAC3_REG_OFFSET;
    dynamic_scheme_reg_offset = SMC_PLL_WRAP_AWM_0_AWM_GLOBAL_A_DYNAMIC_SCHEME_4_REG_OFFSET;
  }
  else if (floor == 2)
  {
    fcw_int_floor_reg_offset = SMC_PLL_WRAP_AWM_0_AWM_FREQUENCY0_A_FCW_INT1_REG_OFFSET;
    fcw_frac_floor_reg_offset = SMC_PLL_WRAP_AWM_0_AWM_FREQUENCY0_A_FCW_FRAC2_REG_OFFSET;
    dynamic_scheme_reg_offset = SMC_PLL_WRAP_AWM_0_AWM_GLOBAL_A_DYNAMIC_SCHEME_3_REG_OFFSET;
  }
  else if (floor == 1)
  {
    fcw_int_floor_reg_offset = SMC_PLL_WRAP_AWM_0_AWM_FREQUENCY0_A_FCW_INT0_REG_OFFSET;
    fcw_frac_floor_reg_offset = SMC_PLL_WRAP_AWM_0_AWM_FREQUENCY0_A_FCW_FRAC1_REG_OFFSET;
    dynamic_scheme_reg_offset = SMC_PLL_WRAP_AWM_0_AWM_GLOBAL_A_DYNAMIC_SCHEME_2_REG_OFFSET;
  }
  else
  {
    fcw_int_floor_reg_offset = SMC_PLL_WRAP_AWM_0_AWM_FREQUENCY0_A_FCW_INT0_REG_OFFSET;
    fcw_frac_floor_reg_offset = SMC_PLL_WRAP_AWM_0_AWM_FREQUENCY0_A_FCW_FRAC_REG_OFFSET;
  }

  uint32_t fcw_int_reg_offset = freq_unit_base_offset +
                                fcw_int_floor_reg_offset +
                                freq_unit * 0x40;
  uint32_t fcw_frac_reg_offset = freq_unit_base_offset +
                                 fcw_frac_floor_reg_offset +
                                 freq_unit * 0x40;

  // Set multiplcation factor: 30
  uint16_t frequency0_a_fcw_int0;
  frequency0_a_fcw_int0 = read_awm_pll_reg(awm_id, fcw_int_reg_offset);
  uint16_t fcw_int_new_val = (frequency0_a_fcw_int0 & ~fcw_int_floor_mask) | (fcw_int << fcw_int_floor_shift);
  write_awm_pll_reg(awm_id, fcw_int_reg_offset, fcw_int_new_val);

  // Set fractional factor: 0
  FREQUENCY0_FCW_FRAC_reg_u frequency0_a_fcw_frac;
  frequency0_a_fcw_frac.val = read_awm_pll_reg(awm_id, fcw_frac_reg_offset);
  frequency0_a_fcw_frac.f.fcw_frac = fcw_frac;
  write_awm_pll_reg(awm_id, fcw_frac_reg_offset, frequency0_a_fcw_frac.val);

  if (floor != 0)
  {
    GLOBAL_DYNAMIC_SCHEME_2_reg_u global_dynamic_scheme;
    global_dynamic_scheme.val = read_awm_pll_reg(awm_id, dynamic_scheme_reg_offset);
    global_dynamic_scheme.f.watch_duration_1 = watch_duration;
    global_dynamic_scheme.f.floor_duration_1 = floor_duration;
    write_awm_pll_reg(awm_id, dynamic_scheme_reg_offset, global_dynamic_scheme.val);
  }
}

static inline void program_awm0_functional(void)
{
  // -----------------------------
  // PROGRAM AWM 0, clk 0: NoC - 1500 MHz
  //                clk 1: N/A
  //                clk 2: Static clock for Peripherals - 200 MHz
  // -----------------------------

  // CLOCK 0 - Dynamic w/ 2 DVFS Modes, 3 Floors per Mode

  // -- DVFS Mode 0 --
  // Mode 0 Main Frequency (F0) - 1500 Mhz
  uint16_t freq0_fcw_int = 30;
  uint16_t freq0_fcw_frac = 0;
  uint16_t freq0_prediv = 0;
  uint16_t freq0_postdiv = 1;
  uint16_t freq0_postdiv_config = 0;
  uint16_t freq0_freq_lock_threshold = 11;

  program_awm_freq_unit(0, 0, freq0_fcw_int, freq0_fcw_frac, freq0_prediv,
                        freq0_postdiv, freq0_postdiv_config,
                        freq0_freq_lock_threshold);

  // Setup 3 Floors for DVFS Mode 0
  // Mode 0 Floor 1 (F1) - 1450 Mhz
  uint8_t floor1_fcw_int = 29;
  uint16_t floor1_fcw_frac = 0;
  uint8_t floor1_watch_duration = 1;
  uint8_t floor1_floor_duration = 1;
  program_awm_freq_unit_floor(0, 0, 1, floor1_fcw_int, floor1_fcw_frac,
                              floor1_watch_duration, floor1_floor_duration);

  // Mode 0 Floor 2 (F2) - 1400 Mhz
  uint8_t floor2_fcw_int = 28;
  uint16_t floor2_fcw_frac = 0;
  uint8_t floor2_watch_duration = 1;
  uint8_t floor2_floor_duration = 1;
  program_awm_freq_unit_floor(0, 0, 2, floor2_fcw_int, floor2_fcw_frac,
                              floor2_watch_duration, floor2_floor_duration);

  // Mode 0 Floor 3 (F3) - 1350 Mhz
  uint8_t floor3_fcw_int = 27;
  uint16_t floor3_fcw_frac = 0;
  uint8_t floor3_watch_duration = 1;
  uint8_t floor3_floor_duration = 1;
  program_awm_freq_unit_floor(0, 0, 3, floor3_fcw_int, floor3_fcw_frac,
                              floor3_watch_duration, floor3_floor_duration);

  // -- DVFS Mode 1 --
  // Mode 1 Main Frequency (F0) -  - 1300 Mhz
  uint16_t freq1_fcw_int = 26;
  uint16_t freq1_fcw_frac = 0;
  uint16_t freq1_prediv = 0;
  uint16_t freq1_postdiv = 1;
  uint16_t freq1_postdiv_config = 0;
  uint16_t freq1_freq_lock_threshold = 11;

  program_awm_freq_unit(0, 1, freq1_fcw_int, freq1_fcw_frac, freq1_prediv,
                        freq1_postdiv, freq1_postdiv_config,
                        freq1_freq_lock_threshold);

  // Mode 1 Floor 1 (F1) - 1250 Mhz
  floor1_fcw_int = 25;
  floor1_fcw_frac = 0;
  floor1_watch_duration = 1;
  floor1_floor_duration = 1;
  program_awm_freq_unit_floor(0, 1, 1, floor1_fcw_int, floor1_fcw_frac,
                              floor1_watch_duration, floor1_floor_duration);

  // Mode 1 Floor 2 (F2) - 1200 Mhz
  floor2_fcw_int = 24;
  floor2_fcw_frac = 0;
  floor2_watch_duration = 1;
  floor2_floor_duration = 1;
  program_awm_freq_unit_floor(0, 1, 2, floor2_fcw_int, floor2_fcw_frac,
                              floor2_watch_duration, floor2_floor_duration);

  // Mode 1 Floor 3 (F3) - 1150 Mhz
  floor3_fcw_int = 23;
  floor3_fcw_frac = 0;
  floor3_watch_duration = 1;
  floor3_floor_duration = 1;
  program_awm_freq_unit_floor(0, 1, 3, floor3_fcw_int, floor3_fcw_frac,
                              floor3_watch_duration, floor3_floor_duration);

  // CLOCK 2 - Static Clock for Peripherals
  uint16_t freq2_fcw_int = 16;
  uint16_t freq2_fcw_frac = 0;
  uint16_t freq2_prediv = 0;
  uint16_t freq2_postdiv = 3;
  uint16_t freq2_postdiv_config = 0;
  uint16_t freq2_freq_lock_threshold = 11;

  program_awm_freq_unit(0, 2, freq2_fcw_int, freq2_fcw_frac, freq2_prediv,
                        freq2_postdiv, freq2_postdiv_config,
                        freq2_freq_lock_threshold);

  // Enable Clock Generation Moduel and the Oscillator
  CGM2_ENABLES_reg_u awm_cgm2_config;
  awm_cgm2_config.val = read_reg(SMC_PLL_WRAP_AWM_0_AWM_CGM2_A_ENABLES_REG_ADDR);
  awm_cgm2_config.f.static_cgm_enable = 1;
  write_reg(SMC_PLL_WRAP_AWM_0_AWM_CGM2_A_ENABLES_REG_ADDR, awm_cgm2_config.val);

  // Programming AWM 0 as 1 Dynamic clock w/ 2-DVFS Modes (Hop-based) + 1 Static Clock
  GLOBAL_RESOURCE_CONFIGURATION_ENABLES_reg_u global_resource_configuration_enables = {0};
  global_resource_configuration_enables.f.resource_configuration_dynamic_ramp = 0;
  global_resource_configuration_enables.f.resource_configuration_dynamic_hop = 2;
  global_resource_configuration_enables.f.resource_configuration_static = 1;
  global_resource_configuration_enables.f.droop_response_enable = 1;
  write_reg(SMC_PLL_WRAP_AWM_0_AWM_GLOBAL_A_RESOURCE_CONFIGURATION_ENABLES_REG_ADDR, global_resource_configuration_enables.val);

  GLOBAL_DYNAMIC_SCHEME_0_reg_u awm_global_dynamic_scheme_0;
  awm_global_dynamic_scheme_0.f.dvfs_mode = 0; // 2 DVFS Hop
  write_reg(SMC_PLL_WRAP_AWM_0_AWM_GLOBAL_A_DYNAMIC_SCHEME_0_REG_ADDR, awm_global_dynamic_scheme_0.val);

  // Out clock selection
  PLL_CNTL_AWM_CTRL_reg_u awm_0_ctrl;
  awm_0_ctrl.f.freq_sel_one_hot_clk0 = 1; // out 0 select clock 0
  awm_0_ctrl.f.freq_sel_one_hot_clk1 = 1;
  awm_0_ctrl.f.freq_sel_one_hot_clk2 = 4; // out 2 select clock 2 (100)
  write_pll_ctrl_reg(SMC_PLL_WRAP_PLL_CNTL_AWM_0_CTRL_REG_OFFSET, awm_0_ctrl.val);

  // All register writes done above become effective only after toggling
  // reg_update. reg_update is self-cleared
  write_reg(SMC_PLL_WRAP_AWM_0_AWM_GLOBAL_A_REG_UPDATE_REG_ADDR, 1);

  // Poll for lock
  PLL_CNTL_AWM_STATUS_reg_u pll_ctrl_awm_status;
  do
  {
    pll_ctrl_awm_status.val =
        read_pll_ctrl_reg(SMC_PLL_WRAP_PLL_CNTL_AWM_0_STATUS_REG_OFFSET);
  } while (pll_ctrl_awm_status.f.lock_detect != 7); // lock = 111 - All three CGMs are used and need to lock
}

static inline void program_awm1_functional(void)
{
  // -----------------------------
  // PROGRAM AWM 1, clk 0: DM - 2000 MHz
  // -----------------------------

  uint16_t freq0_fcw_int = 40;
  uint16_t freq0_fcw_frac = 0;
  uint16_t freq0_prediv = 0;
  uint16_t freq0_postdiv = 1;
  uint16_t freq0_postdiv_config = 0;
  uint16_t freq0_freq_lock_threshold = 11;

  program_awm_freq_unit(1, 0, freq0_fcw_int, freq0_fcw_frac, freq0_prediv,
                        freq0_postdiv, freq0_postdiv_config,
                        freq0_freq_lock_threshold);

  // -- DVFS Mode 1 --
  // Mode 1 Main Frequency (F0) -  - 1950 Mhz
  uint16_t freq1_fcw_int = 39;
  uint16_t freq1_fcw_frac = 0;
  uint16_t freq1_prediv = 0;
  uint16_t freq1_postdiv = 1;
  uint16_t freq1_postdiv_config = 0;
  uint16_t freq1_freq_lock_threshold = 11;

  program_awm_freq_unit(1, 1, freq1_fcw_int, freq1_fcw_frac, freq1_prediv,
                        freq1_postdiv, freq1_postdiv_config,
                        freq1_freq_lock_threshold);

  // -- DVFS Mode 2 --
  // Mode 2 Main Frequency (F0) -  - 1900 Mhz
  uint16_t freq2_fcw_int = 38;
  uint16_t freq2_fcw_frac = 0;
  uint16_t freq2_prediv = 0;
  uint16_t freq2_postdiv = 1;
  uint16_t freq2_postdiv_config = 0;
  uint16_t freq2_freq_lock_threshold = 11;

  program_awm_freq_unit(1, 2, freq2_fcw_int, freq2_fcw_frac, freq2_prediv,
                        freq2_postdiv, freq2_postdiv_config,
                        freq2_freq_lock_threshold);

  // -- DVFS Mode 3 --
  // Mode 3 Main Frequency (F0) -  - 1850 Mhz
  uint16_t freq3_fcw_int = 37;
  uint16_t freq3_fcw_frac = 0;
  uint16_t freq3_prediv = 0;
  uint16_t freq3_postdiv = 1;
  uint16_t freq3_postdiv_config = 0;
  uint16_t freq3_freq_lock_threshold = 11;

  program_awm_freq_unit(1, 3, freq3_fcw_int, freq3_fcw_frac, freq3_prediv,
                        freq3_postdiv, freq3_postdiv_config,
                        freq3_freq_lock_threshold);

  // -- DVFS Mode 4 --
  // Mode 4 Main Frequency (F0) -  - 1850 Mhz
  uint16_t freq4_fcw_int = 36;
  uint16_t freq4_fcw_frac = 0;
  uint16_t freq4_prediv = 0;
  uint16_t freq4_postdiv = 1;
  uint16_t freq4_postdiv_config = 0;
  uint16_t freq4_freq_lock_threshold = 11;

  program_awm_freq_unit(1, 4, freq4_fcw_int, freq4_fcw_frac, freq4_prediv,
                        freq4_postdiv, freq4_postdiv_config,
                        freq4_freq_lock_threshold);

  // Programming AWM 1 as 1 Dynamic clock w/ 5-DVFS Modes (Ramp-based)
  GLOBAL_RESOURCE_CONFIGURATION_ENABLES_reg_u global_resource_configuration_enables = {0};
  global_resource_configuration_enables.f.resource_configuration_dynamic_ramp = 5;
  global_resource_configuration_enables.f.resource_configuration_dynamic_hop = 0;
  global_resource_configuration_enables.f.resource_configuration_static = 0;
  global_resource_configuration_enables.f.droop_response_enable = 1;
  write_reg(SMC_PLL_WRAP_AWM_1_AWM_GLOBAL_A_RESOURCE_CONFIGURATION_ENABLES_REG_ADDR, global_resource_configuration_enables.val);

  GLOBAL_DYNAMIC_SCHEME_0_reg_u awm_global_dynamic_scheme_0;
  awm_global_dynamic_scheme_0.f.dvfs_mode = 0; // 2 DVFS Hop
  write_reg(SMC_PLL_WRAP_AWM_1_AWM_GLOBAL_A_DYNAMIC_SCHEME_0_REG_ADDR, awm_global_dynamic_scheme_0.val);

  PLL_CNTL_AWM_CTRL_reg_u awm_0_ctrl;
  awm_0_ctrl.f.freq_sel_one_hot_clk0 = 1;
  awm_0_ctrl.f.freq_sel_one_hot_clk1 = 1;
  awm_0_ctrl.f.freq_sel_one_hot_clk2 = 1;
  write_pll_ctrl_reg(SMC_PLL_WRAP_PLL_CNTL_AWM_1_CTRL_REG_OFFSET, awm_0_ctrl.val);

  // All register writes done above become effective only after toggling
  // reg_update. reg_update is self-cleared
  write_reg(SMC_PLL_WRAP_AWM_1_AWM_GLOBAL_A_REG_UPDATE_REG_ADDR, 1);

  // Poll for lock
  PLL_CNTL_AWM_STATUS_reg_u pll_ctrl_awm_1_status;
  do
  {
    pll_ctrl_awm_1_status.val =
        read_pll_ctrl_reg(SMC_PLL_WRAP_PLL_CNTL_AWM_1_STATUS_REG_OFFSET);
  } while (pll_ctrl_awm_1_status.f.lock_detect != 1);
}

static inline void program_clocks_quasar(void)
{
  program_cgm0_functional(); // SYS CLOCK
  program_cgm1_functional(); // SoC CLOCK

  program_awm0_functional(); // Noc and Peripheral
  program_awm1_functional(); // DM

  switch_pll_mux_functional(); // Select pll as functional clock
}

#endif
