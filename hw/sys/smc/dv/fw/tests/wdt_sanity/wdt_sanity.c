#include <stdint.h>

#include "metal/interrupt.h"
#include "metal/watchdog.h"
#include "metal/cpu.h"
#include "metal/drivers/riscv_cpu.h"
#include "smc_io.h"
#include "smc_test.h"
#include "virt_console.h"

static int wdog_interrupt_id;

void wdt_interrupt_handler(int id, void *priv){
  write_scratch(1, id);
  write_scratch(7, 0x1); // indicate that we hit the first interrupt handler
  metal_watchdog_feed((struct metal_watchdog *)priv);
  metal_watchdog_clear_interrupt((struct metal_watchdog *)priv);
}

void wdt_interrupt_handler_stuck(int id, void *priv){
  uint32_t useless_count = 0;
  write_scratch(1, id + 0x1000);
  write_scratch(7, 0x2); // indicate that we hit the second interrupt handler

  while (true) { // loop "forever" -- 2nd wdt should hit and reset the cluster
    useless_count++;
    // write_scratch(3, useless_count);
    // Add small delay to prevent overwhelming AXI bus and causing queue overflow
    // in AXI4UserYanker. This throttles write rate while still allowing watchdog
    // to trigger reset in a timely manner.
    for (volatile int i = 0; i < 50; i++) {
      __asm__("nop");
    }
  }

}

int main(void) {
  struct metal_interrupt * plic_controller;
  struct metal_cpu * cpu;
  struct metal_interrupt * cpu_controller;
  struct metal_watchdog *wdog, *wdog1, *wdog2, *wdog3;

  uint32_t revived = 0x0;

  revived = read_scratch(7);

  if (revived != 0x2) {
    // get PLIC interrupt controller
    plic_controller = metal_interrupt_get_controller(METAL_PLIC_CONTROLLER, 0);

    cpu = metal_cpu_get(0);
    cpu_controller = metal_cpu_interrupt_controller(cpu);

    write_reg(SMC_TOP_SMC_CPU_CTRL_WDT_TIMEOUT_BASE_ADDR, 0x400); // set 2nd stage wdt timeout counter
    write_reg(SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_SCRATCH_BASE_ADDR(7), 0xC0FFEE); //replace
    write_reg(SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_WARM_SCRATCH_BASE_ADDR(7), 0xC0FFEE); //replace

    // get the all watchdog devices
    wdog = metal_watchdog_get_device(0);
    wdog1 = metal_watchdog_get_device(1);
    wdog2 = metal_watchdog_get_device(2);
    wdog3 = metal_watchdog_get_device(3);

    // get interrupt id for wdog
    wdog_interrupt_id = metal_watchdog_get_interrupt_id(wdog);

    // enable interrupts in the cpu
    metal_interrupt_init(cpu_controller);
    metal_interrupt_enable(cpu_controller, METAL_INTERRUPT_ID_BASE);

    // register a interrupt handler
    metal_interrupt_register_handler(cpu_controller, METAL_INTERRUPT_ID_EXT, wdt_interrupt_handler, wdog);

    // set values to other wdogs to disable their interrupts
    metal_watchdog_set_timeout(wdog1, 0x4000);
    metal_watchdog_set_timeout(wdog2, 0x4000);
    metal_watchdog_set_timeout(wdog3, 0x4000);
    metal_watchdog_clear_interrupt(wdog1);
    metal_watchdog_clear_interrupt(wdog2);
    metal_watchdog_clear_interrupt(wdog3);

    // setup watchdog settings
    // - 1.5GHz rate
    // - timeout after 0x4000 cycles
    // - interrupt on timeout
    // - also report reset
    // - clear any existing interrupts
    metal_watchdog_set_rate(wdog, 1500000000);
    metal_watchdog_set_timeout(wdog, 0x4000);
    metal_watchdog_set_result(wdog, METAL_WATCHDOG_INTERRUPT);
    metal_watchdog_set_result(wdog, METAL_WATCHDOG_FULL_RESET);
    metal_watchdog_clear_interrupt(wdog);

    // init the plic and register interrupt handler
    metal_interrupt_init(plic_controller);
    metal_interrupt_register_handler(plic_controller, wdog_interrupt_id, wdt_interrupt_handler, wdog);

    // start wdog
    metal_watchdog_run(wdog, METAL_WATCHDOG_RUN_AWAKE);

    // clear any existing wdt interrupt in the PLIC
    uint32_t read_int_id = *(uint32_t*)(uintptr_t)(SMC_TOP_SMC_CLUSTER_PLIC_CORE0_MEIP_CLAIM_COMPLETE_BASE_ADDR);
    *(uint32_t*)(uintptr_t)(SMC_TOP_SMC_CLUSTER_PLIC_CORE0_MEIP_CLAIM_COMPLETE_BASE_ADDR) = read_int_id;

    // enable the interrupt for PLIC
    metal_interrupt_enable(plic_controller, wdog_interrupt_id);

    // do some dummy commands
    int dummy_count = 5;
    while (dummy_count > 0){
      write_scratch(5, dummy_count);
      dummy_count = dummy_count - 1;
    }

    // wait for the first interrupt
    __asm__("wfi");

    // register new interrupt handler
    metal_interrupt_register_handler(cpu_controller, METAL_INTERRUPT_ID_EXT, wdt_interrupt_handler_stuck, wdog);

    // do some dummy commands
    dummy_count = 29;
    simputshex32("New commands, count from ", dummy_count);

    while (dummy_count > 0){
      write_scratch(6, dummy_count);
      dummy_count = dummy_count - 1;
    }

    // wait for the second interrupt
    __asm__("wfi");

  } else {
    // warm reset has been completed
    write_scratch(7, 0x3);
  }

  // this should only bhe reached after the second wdt interrupt
  write_scratch(0, 0xacafaca1);

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
    /* Ensure that the lock is initialized before any readers of
     * _start_other */
    __asm__("fence rw,w"); /* Release semantics */

    return main();
  } else {
    return other_main(hartid);
  }
}