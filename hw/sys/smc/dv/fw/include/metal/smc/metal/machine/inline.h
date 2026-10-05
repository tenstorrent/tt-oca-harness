/* Copyright 2019 SiFive, Inc */
/* SPDX-License-Identifier: Apache-2.0 */
/* ----------------------------------- */
/* ----------------------------------- */

#ifndef ASSEMBLY

#ifndef METAL_INLINE_H
#define METAL_INLINE_H

#include <metal/machine.h>

/* --------------------- fixed_clock ------------ */
extern __inline__ unsigned long __metal_driver_fixed_clock_rate(const struct metal_clock *clock);

/* --------------------- fixed_factor_clock ------------ */

/* --------------------- sifive_clint0 ------------ */
extern __inline__ unsigned long
__metal_driver_sifive_clint0_control_base(struct metal_interrupt *controller);
extern __inline__ unsigned long
__metal_driver_sifive_clint0_control_size(struct metal_interrupt *controller);
extern __inline__ int
__metal_driver_sifive_clint0_num_interrupts(struct metal_interrupt *controller);
extern __inline__ struct metal_interrupt *
__metal_driver_sifive_clint0_interrupt_parents(struct metal_interrupt *controller, int idx);
extern __inline__ int
__metal_driver_sifive_clint0_interrupt_lines(struct metal_interrupt *controller, int idx);

/* --------------------- cpu ------------ */
extern __inline__ int __metal_driver_cpu_hartid(struct metal_cpu *cpu);
extern __inline__ int __metal_driver_cpu_timebase(struct metal_cpu *cpu);
extern __inline__ struct metal_interrupt *
__metal_driver_cpu_interrupt_controller(struct metal_cpu *cpu);
extern __inline__ int __metal_driver_cpu_num_pmp_regions(struct metal_cpu *cpu);
extern __inline__ struct metal_buserror *__metal_driver_cpu_buserror(struct metal_cpu *cpu);

/* --------------------- sifive_plic0 ------------ */
extern __inline__ unsigned long
__metal_driver_sifive_plic0_control_base(struct metal_interrupt *controller);
extern __inline__ unsigned long
__metal_driver_sifive_plic0_control_size(struct metal_interrupt *controller);
extern __inline__ int
__metal_driver_sifive_plic0_num_interrupts(struct metal_interrupt *controller);
extern __inline__ int __metal_driver_sifive_plic0_max_priority(struct metal_interrupt *controller);
extern __inline__ struct metal_interrupt *
__metal_driver_sifive_plic0_interrupt_parents(struct metal_interrupt *controller, int idx);
extern __inline__ int
__metal_driver_sifive_plic0_interrupt_lines(struct metal_interrupt *controller, int idx);
extern __inline__ int __metal_driver_sifive_plic0_context_ids(int hartid);

/* --------------------- sifive_buserror0 ------------ */
extern __inline__ uintptr_t
__metal_driver_sifive_buserror0_control_base(const struct metal_buserror *beu);
extern __inline__ struct metal_interrupt *
__metal_driver_sifive_buserror0_interrupt_parent(const struct metal_buserror *beu);
extern __inline__ int
__metal_driver_sifive_buserror0_interrupt_id(const struct metal_buserror *beu);

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

/* --------------------- sifive_spi0 ------------ */

/* --------------------- sifive_test0 ------------ */

/* --------------------- sifive_trace ------------ */

/* --------------------- sifive_uart0 ------------ */

/* --------------------- sifive_simuart0 ------------ */

/* --------------------- sifive_wdog0 ------------ */
extern __inline__ unsigned long
__metal_driver_sifive_wdog0_control_base(const struct metal_watchdog *const watchdog);
extern __inline__ unsigned long
__metal_driver_sifive_wdog0_control_size(const struct metal_watchdog *const watchdog);
extern __inline__ struct metal_interrupt *
__metal_driver_sifive_wdog0_interrupt_parent(const struct metal_watchdog *const watchdog);
extern __inline__ int
__metal_driver_sifive_wdog0_interrupt_line(const struct metal_watchdog *const watchdog);
extern __inline__ struct metal_clock *
__metal_driver_sifive_wdog0_clock(const struct metal_watchdog *const watchdog);

/* --------------------- sifive_fe310_g000_hfrosc ------------ */

/* --------------------- sifive_fe310_g000_hfxosc ------------ */

/* --------------------- sifive_fe310_g000_lfrosc ------------ */

/* --------------------- sifive_fe310_g000_pll ------------ */

/* --------------------- fe310_g000_prci ------------ */

/* From cbus_clock */
struct __metal_driver_fixed_clock __metal_dt_cbus_clock = {
    .clock.vtable = &__metal_driver_vtable_fixed_clock.clock,
};

/* From fbus_clock */
struct __metal_driver_fixed_clock __metal_dt_fbus_clock = {
    .clock.vtable = &__metal_driver_vtable_fixed_clock.clock,
};

/* From mbus_clock */
struct __metal_driver_fixed_clock __metal_dt_mbus_clock = {
    .clock.vtable = &__metal_driver_vtable_fixed_clock.clock,
};

/* From pbus_clock */
struct __metal_driver_fixed_clock __metal_dt_pbus_clock = {
    .clock.vtable = &__metal_driver_vtable_fixed_clock.clock,
};

/* From sbus_clock */
struct __metal_driver_fixed_clock __metal_dt_sbus_clock = {
    .clock.vtable = &__metal_driver_vtable_fixed_clock.clock,
};

struct metal_memory __metal_dt_mem_memory_c0060000 = {
    ._base_address = 3221618688UL,
    ._size = 131072UL,
    ._attrs = {.R = 1, .W = 1, .X = 1, .C = 1, .A = 1},
};

struct metal_memory __metal_dt_mem_memory_c0080000 = {
    ._base_address = 3221749760UL,
    ._size = 131072UL,
    ._attrs = {.R = 1, .W = 1, .X = 1, .C = 1, .A = 1},
};

struct metal_memory __metal_dt_mem_memory_c00a0000 = {
    ._base_address = 3221880832UL,
    ._size = 131072UL,
    ._attrs = {.R = 1, .W = 1, .X = 1, .C = 1, .A = 1},
};

struct metal_memory __metal_dt_mem_memory_c00c0000 = {
    ._base_address = 3222011904UL,
    ._size = 131072UL,
    ._attrs = {.R = 1, .W = 1, .X = 1, .C = 1, .A = 1},
};

struct metal_memory __metal_dt_mem_memory_c00e0000 = {
    ._base_address = 3222142976UL,
    ._size = 131072UL,
    ._attrs = {.R = 1, .W = 1, .X = 1, .C = 1, .A = 1},
};

struct metal_memory __metal_dt_mem_memory_c0100000 = {
    ._base_address = 3222274048UL,
    ._size = 131072UL,
    ._attrs = {.R = 1, .W = 1, .X = 1, .C = 1, .A = 1},
};

struct metal_memory __metal_dt_mem_memory_c0120000 = {
    ._base_address = 3222405120UL,
    ._size = 131072UL,
    ._attrs = {.R = 1, .W = 1, .X = 1, .C = 1, .A = 1},
};

struct metal_memory __metal_dt_mem_memory_c0140000 = {
    ._base_address = 3222536192UL,
    ._size = 131072UL,
    ._attrs = {.R = 1, .W = 1, .X = 1, .C = 1, .A = 1},
};

/* From clint@c8000000 */
struct __metal_driver_riscv_clint0 __metal_dt_clint_c8000000 = {
    .controller.vtable = &__metal_driver_vtable_riscv_clint0.clint_vtable,
    .init_done = 0,
};

/* From cpu@0 */
struct __metal_driver_cpu __metal_dt_cpu_0 = {
    .cpu.vtable = &__metal_driver_vtable_cpu.cpu_vtable,
    .hpm_count = 0,
};

/* From cpu@1 */
struct __metal_driver_cpu __metal_dt_cpu_1 = {
    .cpu.vtable = &__metal_driver_vtable_cpu.cpu_vtable,
    .hpm_count = 0,
};

/* From cpu@2 */
struct __metal_driver_cpu __metal_dt_cpu_2 = {
    .cpu.vtable = &__metal_driver_vtable_cpu.cpu_vtable,
    .hpm_count = 0,
};

/* From cpu@3 */
struct __metal_driver_cpu __metal_dt_cpu_3 = {
    .cpu.vtable = &__metal_driver_vtable_cpu.cpu_vtable,
    .hpm_count = 0,
};

/* From interrupt_controller */
struct __metal_driver_riscv_cpu_intc __metal_dt_cpu_0_interrupt_controller = {
    .controller.vtable = &__metal_driver_vtable_riscv_cpu_intc.controller_vtable,
    .init_done = 0,
};

/* From interrupt_controller */
struct __metal_driver_riscv_cpu_intc __metal_dt_cpu_1_interrupt_controller = {
    .controller.vtable = &__metal_driver_vtable_riscv_cpu_intc.controller_vtable,
    .init_done = 0,
};

/* From interrupt_controller */
struct __metal_driver_riscv_cpu_intc __metal_dt_cpu_2_interrupt_controller = {
    .controller.vtable = &__metal_driver_vtable_riscv_cpu_intc.controller_vtable,
    .init_done = 0,
};

/* From interrupt_controller */
struct __metal_driver_riscv_cpu_intc __metal_dt_cpu_3_interrupt_controller = {
    .controller.vtable = &__metal_driver_vtable_riscv_cpu_intc.controller_vtable,
    .init_done = 0,
};

/* From interrupt_controller@c4000000 */
struct __metal_driver_riscv_plic0 __metal_dt_interrupt_controller_c4000000 = {
    .controller.vtable = &__metal_driver_vtable_riscv_plic0.plic_vtable,
    .init_done = 0,
};

struct metal_pmp __metal_dt_pmp;

/* From bus_error_unit@c8010000 */
struct metal_buserror __metal_dt_bus_error_unit_c8010000 = {
    .__no_empty_structs = 0,
};

/* From bus_error_unit@c8011000 */
struct metal_buserror __metal_dt_bus_error_unit_c8011000 = {
    .__no_empty_structs = 0,
};

/* From bus_error_unit@c8012000 */
struct metal_buserror __metal_dt_bus_error_unit_c8012000 = {
    .__no_empty_structs = 0,
};

/* From bus_error_unit@c8013000 */
struct metal_buserror __metal_dt_bus_error_unit_c8013000 = {
    .__no_empty_structs = 0,
};

/* From wdt@c0000000 */
struct __metal_driver_sifive_wdog0 __metal_dt_wdt_c0000000 = {
    .watchdog.vtable = &__metal_driver_vtable_sifive_wdog0.watchdog,
};

/* From wdt@c0000400 */
struct __metal_driver_sifive_wdog0 __metal_dt_wdt_c0000400 = {
    .watchdog.vtable = &__metal_driver_vtable_sifive_wdog0.watchdog,
};

/* From wdt@c0000800 */
struct __metal_driver_sifive_wdog0 __metal_dt_wdt_c0000800 = {
    .watchdog.vtable = &__metal_driver_vtable_sifive_wdog0.watchdog,
};

/* From wdt@c0000c00 */
struct __metal_driver_sifive_wdog0 __metal_dt_wdt_c0000c00 = {
    .watchdog.vtable = &__metal_driver_vtable_sifive_wdog0.watchdog,
};

#endif /* METAL_INLINE_H*/
#endif /* ! ASSEMBLY */
