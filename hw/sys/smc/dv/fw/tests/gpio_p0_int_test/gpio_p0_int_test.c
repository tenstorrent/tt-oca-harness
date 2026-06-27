/* SPDX-License-Identifier: Apache-2.0 */
/* (c) 2026 Tenstorrent USA Inc */

#include <stdint.h>

#include "metal/atomic.h"
#include "metal/lock.h"
#include "smc_io.h"
#include "smc_test.h"

#define TOTAL_GPIOS 68
#define GPIO_SKIP_COOL_RESET 64  // GPIO_64 is cool_reset_in, will reset chip if toggled
#define PAD2SOC_MASK 0x80000000

void test_interrupt_type_high_level(uint32_t gpio_num) {
  gpio_intf__DATA_CTRL_t gpio_control;

  gpio_control.w = read_gpio(gpio_num, (SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)));

  gpio_control.f.enable_rx_tx = 2;
  gpio_control.f.interrupt_enable = 1;
  gpio_control.f.interrupt_type = 0;
  gpio_control.f.interface_enable = 1;

  write_gpio(gpio_num, (SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)), gpio_control.w);

  uint32_t read_data = read_gpio(gpio_num, (SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)));

  write_scratch(1, (gpio_num << 16) | 0x0001);
  write_scratch(2, read_data);

  gpio_control.w = read_data;
  if (gpio_control.f.interrupt_enable != 1 || gpio_control.f.interrupt_type != 0) {
    write_scratch(1, (gpio_num << 16) | 0xDEAD);
    test_fail(0);
  }
}

void test_interrupt_type_low_level(uint32_t gpio_num) {
  gpio_intf__DATA_CTRL_t gpio_control;

  gpio_control.w = read_gpio(gpio_num, (SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)));

  gpio_control.f.enable_rx_tx = 2;
  gpio_control.f.interrupt_enable = 1;
  gpio_control.f.interrupt_type = 1;
  gpio_control.f.interface_enable = 1;

  write_gpio(gpio_num, (SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)), gpio_control.w);

  uint32_t read_data = read_gpio(gpio_num, (SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)));

  write_scratch(1, (gpio_num << 16) | 0x0002);
  write_scratch(2, read_data);

  gpio_control.w = read_data;
  if (gpio_control.f.interrupt_enable != 1 || gpio_control.f.interrupt_type != 1) {
    write_scratch(1, (gpio_num << 16) | 0xDEAD);
    test_fail(0);
  }
}

void test_interrupt_type_rising_edge(uint32_t gpio_num) {
  gpio_intf__DATA_CTRL_t gpio_control;

  gpio_control.w = read_gpio(gpio_num, (SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)));

  gpio_control.f.enable_rx_tx = 2;
  gpio_control.f.interrupt_enable = 1;
  gpio_control.f.interrupt_type = 2;
  gpio_control.f.interface_enable = 1;

  write_gpio(gpio_num, (SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)), gpio_control.w);

  uint32_t read_data = read_gpio(gpio_num, (SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)));

  write_scratch(1, (gpio_num << 16) | 0x0003);
  write_scratch(2, read_data);

  gpio_control.w = read_data;
  if (gpio_control.f.interrupt_enable != 1 || gpio_control.f.interrupt_type != 2) {
    write_scratch(1, (gpio_num << 16) | 0xDEAD);
    test_fail(0);
  }
}

void test_interrupt_type_falling_edge(uint32_t gpio_num) {
  gpio_intf__DATA_CTRL_t gpio_control;

  gpio_control.w = read_gpio(gpio_num, (SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)));

  gpio_control.f.enable_rx_tx = 2;
  gpio_control.f.interrupt_enable = 1;
  gpio_control.f.interrupt_type = 3;
  gpio_control.f.interface_enable = 1;

  write_gpio(gpio_num, (SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)), gpio_control.w);

  uint32_t read_data = read_gpio(gpio_num, (SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)));

  write_scratch(1, (gpio_num << 16) | 0x0004);
  write_scratch(2, read_data);

  gpio_control.w = read_data;
  if (gpio_control.f.interrupt_enable != 1 || gpio_control.f.interrupt_type != 3) {
    write_scratch(1, (gpio_num << 16) | 0xDEAD);
    test_fail(0);
  }
}

void test_gpio_interrupt_types(uint32_t gpio_num) {
  // Test all four interrupt types for this GPIO
  test_interrupt_type_high_level(gpio_num);
  test_interrupt_type_low_level(gpio_num);
  test_interrupt_type_rising_edge(gpio_num);
  test_interrupt_type_falling_edge(gpio_num);
}

int main(void) {

  // Initialize peripherals
  // peripherals_out_of_reset();  // Function is not available

  // Test all GPIOs (0-67), skipping GPIO 64 (cool_reset_in)
  for (uint32_t gpio_num = 0; gpio_num < TOTAL_GPIOS; gpio_num++) {
    if (gpio_num == GPIO_SKIP_COOL_RESET) {
      // Skip GPIO 64 as it is cool_reset_in and will reset chip if toggled
      continue;
    }

    // Test all interrupt types for this GPIO
    test_gpio_interrupt_types(gpio_num);
  }

  test_pass(0);

  while (true) {
    __asm__("wfi");
  }

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
