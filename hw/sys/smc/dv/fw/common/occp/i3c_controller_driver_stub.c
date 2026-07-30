/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * Default weak stub for the I3C controller driver.
 * Link this file when building without a real I3C driver.
 */

#include "i3c_controller_driver.h"
#include "virt_console.h"

__attribute__((weak)) I3C_Driver *I3C_GetDriverInstance(uint8_t controller_id) {
    (void)controller_id;
    simputs("[i3c_stub] No I3C driver linked — I3C_GetDriverInstance returns NULL\n");
    return NULL;
}

/*
 * Weak stubs for the low-level platform hooks declared in
 * i3c_controller_driver.h.  Platform drivers override these with strong symbols.
 */
__attribute__((weak)) void i3c_release_reset(uint8_t i3c_controller) {
    (void)i3c_controller;
}

__attribute__((weak)) void cfg_ps(uint8_t i3c_controller, uint8_t device_id, I3C_Role role) {
    (void)i3c_controller;
    (void)device_id;
    (void)role;
}

__attribute__((weak)) void init_i3c_ctrl(uint8_t controller_id, uint64_t device_id, I3C_Role role) {
    (void)controller_id;
    (void)device_id;
    (void)role;
}
