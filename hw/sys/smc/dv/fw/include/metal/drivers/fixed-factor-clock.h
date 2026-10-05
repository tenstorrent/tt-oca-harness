/* Copyright 2018 SiFive, Inc */

#ifndef METAL__DRIVERS__FIXED_FACTOR_CLOCK_H
#define METAL__DRIVERS__FIXED_FACTOR_CLOCK_H

struct __metal_driver_fixed_factor_clock;

#include <metal/clock.h>
#include <metal/compiler.h>

struct __metal_driver_vtable_fixed_factor_clock {
    struct __metal_clock_vtable clock;
};

__METAL_DECLARE_VTABLE(__metal_driver_vtable_fixed_factor_clock)

struct __metal_driver_fixed_factor_clock {
    struct metal_clock clock;
};

#endif
