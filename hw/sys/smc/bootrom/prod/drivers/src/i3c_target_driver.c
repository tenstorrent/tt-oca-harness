/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* I3C Target Driver — weak default implementation
 *
 * All symbols are marked __attribute__((weak)) so a platform-specific driver
 * can override them at link time without modifying ROM sources.
 *
 * When no override is linked the stub allows the ROM to boot normally on
 * platforms that do not use I3C (init/start succeed; data methods return
 * I3C_ERR_HW so the OCCP layer skips I3C channels gracefully).
 */

#include "i3c_target_driver.h"

/* -------------------------------------------------------------------------
 * Stub implementations — no register access, no vendor headers
 * ---------------------------------------------------------------------- */

static I3C_Status i3c_stub_init(I3C_Driver *drv, uint8_t controller_id, uint64_t device_id,
                                I3C_Role role) {
    (void)device_id;
    drv->ctx.controller_id = controller_id;
    drv->ctx.role = role;
    drv->ctx.initialized = true;
    return I3C_OK;
}

static I3C_Status i3c_stub_start(I3C_Driver *drv) {
    (void)drv;
    return I3C_OK;
}

static void i3c_stub_set_payload_length(I3C_Driver *drv, uint16_t length) {
    (void)drv;
    (void)length;
}

static I3C_Status i3c_stub_issue_entdaa(I3C_Driver *drv) {
    (void)drv;
    return I3C_ERR_HW;
}

static I3C_Status i3c_stub_issue_setgrpa(I3C_Driver *drv, uint8_t da, uint8_t group_addr) {
    (void)drv;
    (void)da;
    (void)group_addr;
    return I3C_ERR_HW;
}

static I3C_Status i3c_stub_wait_command(I3C_Driver *drv, uint8_t command_id, uint32_t timeout) {
    (void)drv;
    (void)command_id;
    (void)timeout;
    return I3C_ERR_HW;
}

static I3C_Status i3c_stub_process_devices(I3C_Driver *drv, I3C_DeviceInfo *devices,
                                           size_t max_devices) {
    (void)drv;
    (void)devices;
    (void)max_devices;
    return I3C_ERR_HW;
}

static I3C_Status i3c_stub_write(I3C_Driver *drv, uint8_t da, const uint8_t *data, size_t length) {
    (void)drv;
    (void)da;
    (void)data;
    (void)length;
    return I3C_ERR_HW;
}

static I3C_Status i3c_stub_read(I3C_Driver *drv, uint8_t da, uint8_t *buffer, size_t length,
                                uint32_t timeout) {
    (void)drv;
    (void)da;
    (void)buffer;
    (void)length;
    (void)timeout;
    return I3C_ERR_HW;
}

static I3C_Status i3c_stub_fifo_write(I3C_Driver *drv, const uint8_t *data, size_t length) {
    (void)drv;
    (void)data;
    (void)length;
    return I3C_ERR_HW;
}

static I3C_Status i3c_stub_fifo_read(I3C_Driver *drv, uint8_t *buffer, size_t length,
                                     size_t *bytes_read) {
    (void)drv;
    (void)buffer;
    (void)length;
    if (bytes_read) *bytes_read = 0;
    return I3C_ERR_HW;
}

static I3C_Status i3c_stub_send_payload(I3C_Driver *drv, const uint8_t addr, const uint8_t *data,
                                        size_t length) {
    (void)drv;
    (void)addr;
    (void)data;
    (void)length;
    return I3C_ERR_HW;
}

static I3C_Status i3c_stub_send_payload_stream(I3C_Driver *drv, const uint8_t addr,
                                               const uint8_t *data, size_t length,
                                               uint32_t timeout) {
    (void)drv;
    (void)addr;
    (void)data;
    (void)length;
    (void)timeout;
    return I3C_ERR_HW;
}

static uint32_t i3c_stub_check_rx_fifo(I3C_Driver *drv) {
    (void)drv;
    return 0;
}

static I3C_Status i3c_stub_receive_payload(I3C_Driver *drv, uint8_t *buffer, size_t buffer_length,
                                           size_t *bytes_received) {
    (void)drv;
    (void)buffer;
    (void)buffer_length;
    if (bytes_received) *bytes_received = 0;
    return I3C_ERR_HW;
}

static I3C_Status i3c_stub_receive_payload_stream(I3C_Driver *drv, uint8_t *buffer,
                                                  size_t buffer_length, size_t *bytes_received,
                                                  uint32_t timeout, bool expect_excess_bytes,
                                                  bool is_flush) {
    (void)drv;
    (void)buffer;
    (void)buffer_length;
    (void)timeout;
    (void)expect_excess_bytes;
    (void)is_flush;
    if (bytes_received) *bytes_received = 0;
    return I3C_ERR_HW;
}

/* -------------------------------------------------------------------------
 * Public weak symbols — overridable by a strong-symbol platform driver
 * ---------------------------------------------------------------------- */

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

__attribute__((weak)) I3C_Driver *I3C_GetDriverInstance(uint8_t controller_id) {
    static I3C_Driver instances[I3C_MAX_DEVICES];
    static bool initialized[I3C_MAX_DEVICES];

    if (controller_id >= I3C_MAX_DEVICES) {
        return NULL;
    }

    I3C_Driver *drv = &instances[controller_id];

    if (!initialized[controller_id]) {
        drv->init = i3c_stub_init;
        drv->start = i3c_stub_start;
        drv->issue_entdaa = i3c_stub_issue_entdaa;
        drv->issue_setgrpa = i3c_stub_issue_setgrpa;
        drv->wait_command = i3c_stub_wait_command;
        drv->process_devices = i3c_stub_process_devices;
        drv->write = i3c_stub_write;
        drv->read = i3c_stub_read;
        drv->fifo_write = i3c_stub_fifo_write;
        drv->fifo_read = i3c_stub_fifo_read;
        drv->send_payload = i3c_stub_send_payload;
        drv->send_payload_stream = i3c_stub_send_payload_stream;
        drv->check_rx_fifo = i3c_stub_check_rx_fifo;
        drv->receive_payload = i3c_stub_receive_payload;
        drv->receive_payload_stream = i3c_stub_receive_payload_stream;
        drv->set_payload_length = i3c_stub_set_payload_length;
        initialized[controller_id] = true;
    }

    return drv;
}
