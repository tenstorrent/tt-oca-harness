/* Copyright 2019 SiFive, Inc */
/* SPDX-License-Identifier: Apache-2.0 */
/* ----------------------------------- */
/* ----------------------------------- */

#ifndef ASSEMBLY

#include <metal/machine/platform.h>

#ifdef __METAL_MACHINE_MACROS

#ifndef MACROS_IF_METAL_H
#define MACROS_IF_METAL_H

#define __METAL_CLINT_NUM_PARENTS 8

#ifndef __METAL_CLINT_NUM_PARENTS
#define __METAL_CLINT_NUM_PARENTS 0
#endif
#define __METAL_PLIC_SUBINTERRUPTS 337

#define __METAL_PLIC_NUM_PARENTS 8

#ifndef __METAL_PLIC_SUBINTERRUPTS
#define __METAL_PLIC_SUBINTERRUPTS 0
#endif
#ifndef __METAL_PLIC_NUM_PARENTS
#define __METAL_PLIC_NUM_PARENTS 0
#endif
#ifndef __METAL_CLIC_SUBINTERRUPTS
#define __METAL_CLIC_SUBINTERRUPTS 0
#endif

#endif /* MACROS_IF_METAL_H*/

#else /* ! __METAL_MACHINE_MACROS */

#ifndef MACROS_ELSE_METAL_H
#define MACROS_ELSE_METAL_H

#define __METAL_CLINT_C8000000_INTERRUPTS 8

#define METAL_MAX_CLINT_INTERRUPTS 8

#define __METAL_CLINT_NUM_PARENTS 8

#define __METAL_INTERRUPT_CONTROLLER_C4000000_INTERRUPTS 8

#define __METAL_PLIC_SUBINTERRUPTS 337

#define METAL_MAX_PLIC_INTERRUPTS 8

#define __METAL_PLIC_NUM_PARENTS 8

#define __METAL_CLIC_SUBINTERRUPTS 0
#define METAL_MAX_CLIC_INTERRUPTS 0

#define METAL_MAX_LOCAL_EXT_INTERRUPTS 0

#define METAL_MAX_GLOBAL_EXT_INTERRUPTS 0

#define METAL_MAX_GPIO_INTERRUPTS 0

#define METAL_MAX_I2C0_INTERRUPTS 0

#define METAL_MAX_PWM0_INTERRUPTS 0

#define METAL_MAX_PWM0_NCMP 0

#define METAL_MAX_UART_INTERRUPTS 0

#define METAL_MAX_SIMUART_INTERRUPTS 0

#include <metal/drivers/fixed-clock.h>
#include <metal/memory.h>
#include <metal/drivers/riscv_clint0.h>
#include <metal/drivers/riscv_cpu.h>
#include <metal/drivers/riscv_plic0.h>
#include <metal/pmp.h>
#include <metal/drivers/sifive_buserror0.h>
#include <metal/drivers/sifive_wdog0.h>

/* From cbus_clock */
extern struct __metal_driver_fixed_clock __metal_dt_cbus_clock;

/* From fbus_clock */
extern struct __metal_driver_fixed_clock __metal_dt_fbus_clock;

/* From mbus_clock */
extern struct __metal_driver_fixed_clock __metal_dt_mbus_clock;

/* From pbus_clock */
extern struct __metal_driver_fixed_clock __metal_dt_pbus_clock;

/* From sbus_clock */
extern struct __metal_driver_fixed_clock __metal_dt_sbus_clock;

extern struct metal_memory __metal_dt_mem_memory_c0060000;

extern struct metal_memory __metal_dt_mem_memory_c0080000;

extern struct metal_memory __metal_dt_mem_memory_c00a0000;

extern struct metal_memory __metal_dt_mem_memory_c00c0000;

extern struct metal_memory __metal_dt_mem_memory_c00e0000;

extern struct metal_memory __metal_dt_mem_memory_c0100000;

extern struct metal_memory __metal_dt_mem_memory_c0120000;

extern struct metal_memory __metal_dt_mem_memory_c0140000;

/* From clint@c8000000 */
extern struct __metal_driver_riscv_clint0 __metal_dt_clint_c8000000;

/* From cpu@0 */
extern struct __metal_driver_cpu __metal_dt_cpu_0;

/* From cpu@1 */
extern struct __metal_driver_cpu __metal_dt_cpu_1;

/* From cpu@2 */
extern struct __metal_driver_cpu __metal_dt_cpu_2;

/* From cpu@3 */
extern struct __metal_driver_cpu __metal_dt_cpu_3;

extern struct __metal_driver_riscv_cpu_intc __metal_dt_cpu_0_interrupt_controller;

extern struct __metal_driver_riscv_cpu_intc __metal_dt_cpu_1_interrupt_controller;

extern struct __metal_driver_riscv_cpu_intc __metal_dt_cpu_2_interrupt_controller;

extern struct __metal_driver_riscv_cpu_intc __metal_dt_cpu_3_interrupt_controller;

/* From interrupt_controller@c4000000 */
extern struct __metal_driver_riscv_plic0 __metal_dt_interrupt_controller_c4000000;

extern struct metal_pmp __metal_dt_pmp;

/* From bus_error_unit@c8010000 */
extern struct metal_buserror __metal_dt_bus_error_unit_c8010000;

/* From bus_error_unit@c8011000 */
extern struct metal_buserror __metal_dt_bus_error_unit_c8011000;

/* From bus_error_unit@c8012000 */
extern struct metal_buserror __metal_dt_bus_error_unit_c8012000;

/* From bus_error_unit@c8013000 */
extern struct metal_buserror __metal_dt_bus_error_unit_c8013000;

/* From wdt@c0000000 */
extern struct __metal_driver_sifive_wdog0 __metal_dt_wdt_c0000000;

/* From wdt@c0000400 */
extern struct __metal_driver_sifive_wdog0 __metal_dt_wdt_c0000400;

/* From wdt@c0000800 */
extern struct __metal_driver_sifive_wdog0 __metal_dt_wdt_c0000800;

/* From wdt@c0000c00 */
extern struct __metal_driver_sifive_wdog0 __metal_dt_wdt_c0000c00;

/* --------------------- fixed_clock ------------ */
static __inline__ unsigned long __metal_driver_fixed_clock_rate(const struct metal_clock *clock) {
    if ((uintptr_t)clock == (uintptr_t)&__metal_dt_cbus_clock) {
        return METAL_FIXED_CLOCK__CBUS_CLOCK_CLOCK_FREQUENCY;
    } else if ((uintptr_t)clock == (uintptr_t)&__metal_dt_fbus_clock) {
        return METAL_FIXED_CLOCK__FBUS_CLOCK_CLOCK_FREQUENCY;
    } else if ((uintptr_t)clock == (uintptr_t)&__metal_dt_mbus_clock) {
        return METAL_FIXED_CLOCK__MBUS_CLOCK_CLOCK_FREQUENCY;
    } else if ((uintptr_t)clock == (uintptr_t)&__metal_dt_pbus_clock) {
        return METAL_FIXED_CLOCK__PBUS_CLOCK_CLOCK_FREQUENCY;
    } else if ((uintptr_t)clock == (uintptr_t)&__metal_dt_sbus_clock) {
        return METAL_FIXED_CLOCK__SBUS_CLOCK_CLOCK_FREQUENCY;
    } else {
        return 0;
    }
}

/* --------------------- fixed_factor_clock ------------ */

/* --------------------- sifive_clint0 ------------ */
static __inline__ unsigned long
__metal_driver_sifive_clint0_control_base(struct metal_interrupt *controller) {
    if ((uintptr_t)controller == (uintptr_t)&__metal_dt_clint_c8000000) {
        return METAL_RISCV_CLINT0_C8000000_BASE_ADDRESS;
    } else {
        return 0;
    }
}

static __inline__ unsigned long
__metal_driver_sifive_clint0_control_size(struct metal_interrupt *controller) {
    if ((uintptr_t)controller == (uintptr_t)&__metal_dt_clint_c8000000) {
        return METAL_RISCV_CLINT0_C8000000_SIZE;
    } else {
        return 0;
    }
}

static __inline__ int
__metal_driver_sifive_clint0_num_interrupts(struct metal_interrupt *controller) {
    if ((uintptr_t)controller == (uintptr_t)&__metal_dt_clint_c8000000) {
        return METAL_MAX_CLINT_INTERRUPTS;
    } else {
        return 0;
    }
}

static __inline__ struct metal_interrupt *
__metal_driver_sifive_clint0_interrupt_parents(struct metal_interrupt *controller, int idx) {
    if (idx == 0) {
        return (struct metal_interrupt *)&__metal_dt_cpu_0_interrupt_controller.controller;
    } else if (idx == 1) {
        return (struct metal_interrupt *)&__metal_dt_cpu_0_interrupt_controller.controller;
    } else if (idx == 2) {
        return (struct metal_interrupt *)&__metal_dt_cpu_1_interrupt_controller.controller;
    } else if (idx == 3) {
        return (struct metal_interrupt *)&__metal_dt_cpu_1_interrupt_controller.controller;
    } else if (idx == 4) {
        return (struct metal_interrupt *)&__metal_dt_cpu_2_interrupt_controller.controller;
    } else if (idx == 5) {
        return (struct metal_interrupt *)&__metal_dt_cpu_2_interrupt_controller.controller;
    } else if (idx == 6) {
        return (struct metal_interrupt *)&__metal_dt_cpu_3_interrupt_controller.controller;
    } else if (idx == 7) {
        return (struct metal_interrupt *)&__metal_dt_cpu_3_interrupt_controller.controller;
    } else {
        return NULL;
    }
}

static __inline__ int
__metal_driver_sifive_clint0_interrupt_lines(struct metal_interrupt *controller, int idx) {
    if (idx == 0) {
        return 3;
    } else if (idx == 1) {
        return 7;
    } else if (idx == 2) {
        return 3;
    } else if (idx == 3) {
        return 7;
    } else if (idx == 4) {
        return 3;
    } else if (idx == 5) {
        return 7;
    } else if (idx == 6) {
        return 3;
    } else if (idx == 7) {
        return 7;
    } else {
        return 0;
    }
}

/* --------------------- cpu ------------ */
static __inline__ int __metal_driver_cpu_hartid(struct metal_cpu *cpu) {
    if ((uintptr_t)cpu == (uintptr_t)&__metal_dt_cpu_0) {
        return 0;
    } else if ((uintptr_t)cpu == (uintptr_t)&__metal_dt_cpu_1) {
        return 1;
    } else if ((uintptr_t)cpu == (uintptr_t)&__metal_dt_cpu_2) {
        return 2;
    } else if ((uintptr_t)cpu == (uintptr_t)&__metal_dt_cpu_3) {
        return 3;
    } else {
        return -1;
    }
}

static __inline__ int __metal_driver_cpu_timebase(struct metal_cpu *cpu) {
    if ((uintptr_t)cpu == (uintptr_t)&__metal_dt_cpu_0) {
        return 1000;
    } else if ((uintptr_t)cpu == (uintptr_t)&__metal_dt_cpu_1) {
        return 1000;
    } else if ((uintptr_t)cpu == (uintptr_t)&__metal_dt_cpu_2) {
        return 1000;
    } else if ((uintptr_t)cpu == (uintptr_t)&__metal_dt_cpu_3) {
        return 1000;
    } else {
        return 0;
    }
}

static __inline__ struct metal_interrupt *
__metal_driver_cpu_interrupt_controller(struct metal_cpu *cpu) {
    if ((uintptr_t)cpu == (uintptr_t)&__metal_dt_cpu_0) {
        return &__metal_dt_cpu_0_interrupt_controller.controller;
    } else if ((uintptr_t)cpu == (uintptr_t)&__metal_dt_cpu_1) {
        return &__metal_dt_cpu_1_interrupt_controller.controller;
    } else if ((uintptr_t)cpu == (uintptr_t)&__metal_dt_cpu_2) {
        return &__metal_dt_cpu_2_interrupt_controller.controller;
    } else if ((uintptr_t)cpu == (uintptr_t)&__metal_dt_cpu_3) {
        return &__metal_dt_cpu_3_interrupt_controller.controller;
    } else {
        return NULL;
    }
}

static __inline__ int __metal_driver_cpu_num_pmp_regions(struct metal_cpu *cpu) {
    if ((uintptr_t)cpu == (uintptr_t)&__metal_dt_cpu_0) {
        return 8;
    } else if ((uintptr_t)cpu == (uintptr_t)&__metal_dt_cpu_1) {
        return 8;
    } else if ((uintptr_t)cpu == (uintptr_t)&__metal_dt_cpu_2) {
        return 8;
    } else if ((uintptr_t)cpu == (uintptr_t)&__metal_dt_cpu_3) {
        return 8;
    } else {
        return 0;
    }
}

static __inline__ struct metal_buserror *__metal_driver_cpu_buserror(struct metal_cpu *cpu) {
    if ((uintptr_t)cpu == (uintptr_t)&__metal_dt_cpu_0) {
        return &__metal_dt_bus_error_unit_c8010000;
    } else if ((uintptr_t)cpu == (uintptr_t)&__metal_dt_cpu_1) {
        return &__metal_dt_bus_error_unit_c8011000;
    } else if ((uintptr_t)cpu == (uintptr_t)&__metal_dt_cpu_2) {
        return &__metal_dt_bus_error_unit_c8012000;
    } else if ((uintptr_t)cpu == (uintptr_t)&__metal_dt_cpu_3) {
        return &__metal_dt_bus_error_unit_c8013000;
    } else {
        return NULL;
    }
}

/* --------------------- sifive_plic0 ------------ */
static __inline__ unsigned long
__metal_driver_sifive_plic0_control_base(struct metal_interrupt *controller) {
    if ((uintptr_t)controller == (uintptr_t)&__metal_dt_interrupt_controller_c4000000) {
        return METAL_RISCV_PLIC0_C4000000_BASE_ADDRESS;
    } else {
        return 0;
    }
}

static __inline__ unsigned long
__metal_driver_sifive_plic0_control_size(struct metal_interrupt *controller) {
    if ((uintptr_t)controller == (uintptr_t)&__metal_dt_interrupt_controller_c4000000) {
        return METAL_RISCV_PLIC0_C4000000_SIZE;
    } else {
        return 0;
    }
}

static __inline__ int
__metal_driver_sifive_plic0_num_interrupts(struct metal_interrupt *controller) {
    if ((uintptr_t)controller == (uintptr_t)&__metal_dt_interrupt_controller_c4000000) {
        return METAL_RISCV_PLIC0_C4000000_RISCV_NDEV;
    } else {
        return 0;
    }
}

static __inline__ int __metal_driver_sifive_plic0_max_priority(struct metal_interrupt *controller) {
    if ((uintptr_t)controller == (uintptr_t)&__metal_dt_interrupt_controller_c4000000) {
        return METAL_RISCV_PLIC0_C4000000_RISCV_MAX_PRIORITY;
    } else {
        return 0;
    }
}

static __inline__ struct metal_interrupt *
__metal_driver_sifive_plic0_interrupt_parents(struct metal_interrupt *controller, int idx) {
    if (idx == 0) {
        return (struct metal_interrupt *)&__metal_dt_cpu_0_interrupt_controller.controller;
    } else if (idx == 1) {
        return (struct metal_interrupt *)&__metal_dt_cpu_1_interrupt_controller.controller;
    } else if (idx == 2) {
        return (struct metal_interrupt *)&__metal_dt_cpu_2_interrupt_controller.controller;
    } else if (idx == 3) {
        return (struct metal_interrupt *)&__metal_dt_cpu_3_interrupt_controller.controller;
    } else if (idx == 4) {
        return (struct metal_interrupt *)&__metal_dt_cpu_0_interrupt_controller.controller;
    } else if (idx == 5) {
        return (struct metal_interrupt *)&__metal_dt_cpu_1_interrupt_controller.controller;
    } else if (idx == 6) {
        return (struct metal_interrupt *)&__metal_dt_cpu_2_interrupt_controller.controller;
    } else if (idx == 7) {
        return (struct metal_interrupt *)&__metal_dt_cpu_3_interrupt_controller.controller;
    } else {
        return NULL;
    }
}

static __inline__ int
__metal_driver_sifive_plic0_interrupt_lines(struct metal_interrupt *controller, int idx) {
    if (idx == 0) {
        return 11;
    } else if (idx == 1) {
        return 11;
    } else if (idx == 2) {
        return 11;
    } else if (idx == 3) {
        return 11;
    } else if (idx == 4) {
        return 9;
    } else if (idx == 5) {
        return 9;
    } else if (idx == 6) {
        return 9;
    } else if (idx == 7) {
        return 9;
    } else {
        return 0;
    }
}

static __inline__ int __metal_driver_sifive_plic0_context_ids(int hartid) {
    if (hartid == 0) {
        return 0;
    } else if (hartid == 1) {
        return 1;
    } else if (hartid == 2) {
        return 2;
    } else if (hartid == 3) {
        return 3;
    } else {
        return -1;
    }
}

/* --------------------- sifive_buserror0 ------------ */
static __inline__ uintptr_t
__metal_driver_sifive_buserror0_control_base(const struct metal_buserror *buserror) {
    if ((uintptr_t)buserror == (uintptr_t)&__metal_dt_bus_error_unit_c8010000) {
        return METAL_SIFIVE_BUSERROR0_C8010000_BASE_ADDRESS;
    } else if ((uintptr_t)buserror == (uintptr_t)&__metal_dt_bus_error_unit_c8011000) {
        return METAL_SIFIVE_BUSERROR0_C8011000_BASE_ADDRESS;
    } else if ((uintptr_t)buserror == (uintptr_t)&__metal_dt_bus_error_unit_c8012000) {
        return METAL_SIFIVE_BUSERROR0_C8012000_BASE_ADDRESS;
    } else if ((uintptr_t)buserror == (uintptr_t)&__metal_dt_bus_error_unit_c8013000) {
        return METAL_SIFIVE_BUSERROR0_C8013000_BASE_ADDRESS;
    } else {
        return 0;
    }
}

static __inline__ struct metal_interrupt *
__metal_driver_sifive_buserror0_interrupt_parent(const struct metal_buserror *buserror) {
    if ((uintptr_t)buserror == (uintptr_t)&__metal_dt_bus_error_unit_c8010000) {
        return (struct metal_interrupt *)&__metal_dt_interrupt_controller_c4000000.controller;
    } else if ((uintptr_t)buserror == (uintptr_t)&__metal_dt_bus_error_unit_c8011000) {
        return NULL;
    } else if ((uintptr_t)buserror == (uintptr_t)&__metal_dt_bus_error_unit_c8012000) {
        return NULL;
    } else if ((uintptr_t)buserror == (uintptr_t)&__metal_dt_bus_error_unit_c8013000) {
        return NULL;
    } else {
        return NULL;
    }
}

static __inline__ int
__metal_driver_sifive_buserror0_interrupt_id(const struct metal_buserror *buserror) {
    if ((uintptr_t)buserror == (uintptr_t)&__metal_dt_bus_error_unit_c8010000) {
        return 333;
    } else if ((uintptr_t)buserror == (uintptr_t)&__metal_dt_bus_error_unit_c8011000) {
        return 334;
    } else if ((uintptr_t)buserror == (uintptr_t)&__metal_dt_bus_error_unit_c8012000) {
        return 335;
    } else if ((uintptr_t)buserror == (uintptr_t)&__metal_dt_bus_error_unit_c8013000) {
        return 336;
    } else {
        return 0;
    }
}

/* --------------------- sifive_clic0 ------------ */

/* --------------------- sifive_local_external_interrupts0 ------------ */

/* --------------------- sifive_global_external_interrupts0 ------------ */

/* --------------------- sifive_gpio0 ------------ */

/* --------------------- sifive_gpio_button ------------ */

/* --------------------- sifive_gpio_led ------------ */

/* --------------------- sifive_gpio_switch ------------ */

/* --------------------- sifive_i2c0 ------------ */

/* --------------------- sifive_prci0 ------------ */

/* --------------------- sifive_pwm0 ------------ */

/* --------------------- sifive_remapper2 ------------ */

/* --------------------- sifive_rtc0 ------------ */

/* --------------------- sifive_test0 ------------ */

/* --------------------- sifive_trace ------------ */

/* --------------------- sifive_uart0 ------------ */

/* --------------------- sifive_simuart0 ------------ */

/* --------------------- sifive_wdog0 ------------ */
static __inline__ unsigned long
__metal_driver_sifive_wdog0_control_base(const struct metal_watchdog *const watchdog) {
    if ((uintptr_t)watchdog == (uintptr_t)&__metal_dt_wdt_c0000000) {
        return METAL_SIFIVE_WDT0_C0000000_BASE_ADDRESS;
    } else if ((uintptr_t)watchdog == (uintptr_t)&__metal_dt_wdt_c0000400) {
        return METAL_SIFIVE_WDT0_C0000400_BASE_ADDRESS;
    } else if ((uintptr_t)watchdog == (uintptr_t)&__metal_dt_wdt_c0000800) {
        return METAL_SIFIVE_WDT0_C0000800_BASE_ADDRESS;
    } else if ((uintptr_t)watchdog == (uintptr_t)&__metal_dt_wdt_c0000c00) {
        return METAL_SIFIVE_WDT0_C0000C00_BASE_ADDRESS;
    } else {
        return 0;
    }
}

static __inline__ unsigned long
__metal_driver_sifive_wdog0_control_size(const struct metal_watchdog *const watchdog) {
    if ((uintptr_t)watchdog == (uintptr_t)&__metal_dt_wdt_c0000000) {
        return METAL_SIFIVE_WDT0_C0000000_SIZE;
    } else if ((uintptr_t)watchdog == (uintptr_t)&__metal_dt_wdt_c0000400) {
        return METAL_SIFIVE_WDT0_C0000400_SIZE;
    } else if ((uintptr_t)watchdog == (uintptr_t)&__metal_dt_wdt_c0000800) {
        return METAL_SIFIVE_WDT0_C0000800_SIZE;
    } else if ((uintptr_t)watchdog == (uintptr_t)&__metal_dt_wdt_c0000c00) {
        return METAL_SIFIVE_WDT0_C0000C00_SIZE;
    } else {
        return 0;
    }
}

static __inline__ struct metal_interrupt *
__metal_driver_sifive_wdog0_interrupt_parent(const struct metal_watchdog *const watchdog) {
    if ((uintptr_t)watchdog == (uintptr_t)&__metal_dt_wdt_c0000000) {
        return (struct metal_interrupt *)&__metal_dt_interrupt_controller_c4000000.controller;
    } else if ((uintptr_t)watchdog == (uintptr_t)&__metal_dt_wdt_c0000400) {
        return NULL;
    } else if ((uintptr_t)watchdog == (uintptr_t)&__metal_dt_wdt_c0000800) {
        return NULL;
    } else if ((uintptr_t)watchdog == (uintptr_t)&__metal_dt_wdt_c0000c00) {
        return NULL;
    } else {
        return 0;
    }
}

static __inline__ int
__metal_driver_sifive_wdog0_interrupt_line(const struct metal_watchdog *const watchdog) {
    if ((uintptr_t)watchdog == (uintptr_t)&__metal_dt_wdt_c0000000) {
        return 329;
    } else if ((uintptr_t)watchdog == (uintptr_t)&__metal_dt_wdt_c0000400) {
        return 330;
    } else if ((uintptr_t)watchdog == (uintptr_t)&__metal_dt_wdt_c0000800) {
        return 331;
    } else if ((uintptr_t)watchdog == (uintptr_t)&__metal_dt_wdt_c0000c00) {
        return 332;
    } else {
        return 0;
    }
}

static __inline__ struct metal_clock *
__metal_driver_sifive_wdog0_clock(const struct metal_watchdog *const watchdog) {
    if ((uintptr_t)watchdog == (uintptr_t)&__metal_dt_wdt_c0000000) {
        return (struct metal_clock *)&__metal_dt_pbus_clock.clock;
    } else if ((uintptr_t)watchdog == (uintptr_t)&__metal_dt_wdt_c0000400) {
        return (struct metal_clock *)&__metal_dt_pbus_clock.clock;
    } else if ((uintptr_t)watchdog == (uintptr_t)&__metal_dt_wdt_c0000800) {
        return (struct metal_clock *)&__metal_dt_pbus_clock.clock;
    } else if ((uintptr_t)watchdog == (uintptr_t)&__metal_dt_wdt_c0000c00) {
        return (struct metal_clock *)&__metal_dt_pbus_clock.clock;
    } else {
        return 0;
    }
}

/* --------------------- sifive_fe310_g000_hfrosc ------------ */

/* --------------------- sifive_fe310_g000_hfxosc ------------ */

/* --------------------- sifive_fe310_g000_lfrosc ------------ */

/* --------------------- sifive_fe310_g000_pll ------------ */

/* --------------------- sifive_fe310_g000_prci ------------ */

#define __METAL_DT_MAX_MEMORIES 8

struct metal_memory *__metal_memory_table[]
    __attribute__((weak)) = {&__metal_dt_mem_memory_c0060000, &__metal_dt_mem_memory_c0080000,
                             &__metal_dt_mem_memory_c00a0000, &__metal_dt_mem_memory_c00c0000,
                             &__metal_dt_mem_memory_c00e0000, &__metal_dt_mem_memory_c0100000,
                             &__metal_dt_mem_memory_c0120000, &__metal_dt_mem_memory_c0140000};

/* From clint@c8000000 */
#define __METAL_DT_RISCV_CLINT0_HANDLE (&__metal_dt_clint_c8000000.controller)

#define __METAL_DT_CLINT_C8000000_HANDLE (&__metal_dt_clint_c8000000.controller)

#define __METAL_DT_MAX_HARTS 4

#define __METAL_CPU_0_ICACHE_HANDLE 1

#define __METAL_CPU_0_DCACHE_HANDLE 1

#define __METAL_CPU_1_ICACHE_HANDLE 1

#define __METAL_CPU_1_DCACHE_HANDLE 1

#define __METAL_CPU_2_ICACHE_HANDLE 1

#define __METAL_CPU_2_DCACHE_HANDLE 1

#define __METAL_CPU_3_ICACHE_HANDLE 1

#define __METAL_CPU_3_DCACHE_HANDLE 1

struct __metal_driver_cpu *__metal_cpu_table[] __attribute__((weak)) = {
    &__metal_dt_cpu_0, &__metal_dt_cpu_1, &__metal_dt_cpu_2, &__metal_dt_cpu_3};

/* From interrupt_controller@c4000000 */
#define __METAL_DT_RISCV_PLIC0_HANDLE (&__metal_dt_interrupt_controller_c4000000.controller)

#define __METAL_DT_INTERRUPT_CONTROLLER_C4000000_HANDLE \
    (&__metal_dt_interrupt_controller_c4000000.controller)

#define __METAL_DT_PMP_HANDLE (&__metal_dt_pmp)

#define __MEE_DT_MAX_GPIOS 0

struct __metal_driver_sifive_gpio0 *__metal_gpio_table[] __attribute__((weak)) = {NULL};
#define __METAL_DT_MAX_BUTTONS 0

struct __metal_driver_sifive_gpio_button *__metal_button_table[] __attribute__((weak)) = {NULL};
#define __METAL_DT_MAX_LEDS 0

struct __metal_driver_sifive_gpio_led *__metal_led_table[] __attribute__((weak)) = {NULL};
#define __METAL_DT_MAX_SWITCHES 0

struct __metal_driver_sifive_gpio_switch *__metal_switch_table[] __attribute__((weak)) = {NULL};
#define __METAL_DT_MAX_I2CS 0

struct __metal_driver_sifive_i2c0 *__metal_i2c_table[] __attribute__((weak)) = {NULL};
#define __METAL_DT_MAX_PWMS 0

struct __metal_driver_sifive_pwm0 *__metal_pwm_table[] __attribute__((weak)) = {NULL};
#define __METAL_DT_MAX_RTCS 0

struct __metal_driver_sifive_rtc0 *__metal_rtc_table[] __attribute__((weak)) = {NULL};
#define __METAL_DT_MAX_SPIS 0

struct __metal_driver_sifive_spi0 *__metal_spi_table[] __attribute__((weak)) = {NULL};
#define __METAL_DT_MAX_UARTS 0

struct __metal_driver_sifive_uart0 *__metal_uart_table[] __attribute__((weak)) = {NULL};
#define __METAL_DT_MAX_SIMUARTS 0

struct __metal_driver_sifive_simuart0 *__metal_simuart_table[] __attribute__((weak)) = {NULL};
#define __METAL_DT_MAX_WDOGS 4

struct __metal_driver_sifive_wdog0 *__metal_wdog_table[]
    __attribute__((weak)) = {&__metal_dt_wdt_c0000000, &__metal_dt_wdt_c0000400,
                             &__metal_dt_wdt_c0000800, &__metal_dt_wdt_c0000c00};

#endif /* MACROS_ELSE_METAL_H*/

#endif /* ! __METAL_MACHINE_MACROS */

#endif /* ! ASSEMBLY */
