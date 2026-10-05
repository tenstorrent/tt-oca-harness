/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * Abstract I3C controller driver interface.
 * This header defines the transport-agnostic I3C driver vtable and supporting types.
 *
 * occp_test_common.h and occp_interfaces.c include this header directly.
 */

#ifndef I3C_CONTROLLER_DRIVER_H_
#define I3C_CONTROLLER_DRIVER_H_

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

#include "virt_console.h"

/* Maximum number of devices on the I3C bus. */
#define I3C_MAX_DEVICES 11

/* I3C controller instances in the SMC; must match smc_config_pkg::NumI3c. */
#define I3C_NUM_CONTROLLERS 6

/* Command wait bound; 0 = unbounded, which is what every caller gets today.
 *
 * The unit is NOT milliseconds despite the name. wait_command() (tt_i3c.c)
 * loads this straight into a counter that it decrements once per poll of
 * MST_STATUS0, so the unit is "number of status polls" and the wall-clock
 * meaning depends on the CPU clock and the MMIO read cost.
 *
 * Leaving this at 0 means a stalled I3C command does not fail -- it spins
 * until the outer simulation timeout, with nothing in the log naming the
 * command that hung.
 *
 * Setting it needs a measured figure that does not exist yet. For scale, the
 * i3c_error_abort_fifo test polls the same kind of completion with its own
 * bounds of 2,000,000 (response) and 200,000 (threshold) and reports
 * bounds_ok=1, i.e. neither expired in a real run -- but that only shows those
 * bounds are large enough, not how many polls a command actually consumes, so
 * it is not a basis for a tight bound here. Getting the real number means
 * instrumenting this loop to record its iteration count and re-running.
 *
 * Note the production bootrom's i3c_target_driver.h carries the same constant,
 * the same 0, and the same "in ms" comment. */
#define I3C_CMD_TIMEOUT_MS 0u

/* FIFO threshold (default) used during initialization. */
#define FIFO_DEPTH 32

/* Size of a FIFO word in bytes. */
#define I3C_FIFO_WORD_SIZE 4

/* Command IDs used by ENTDAA, WRITE and READ */
#define CMD_ID_ENTDAA (0xFA)
#define CMD_ID_SETGRPA (0xFB)
#define CMD_ID_WRITE (0xFD)
#define CMD_ID_READ (0xFE)
#define CCC_ENTDAA (0x07)
#define CCC_SETGRPA (0x9B)

/*----------------------------------------------------------------------------
 * Error status for I3C operations
 *--------------------------------------------------------------------------*/
typedef enum {
    I3C_OK,
    I3C_ERR_HW,
    I3C_ERR_INVALID_ARG,
    I3C_ERR_TIMEOUT,
    I3C_ERR_INCORRECT_CMD_ID,
    I3C_ERR_CMD_FAILED,
    I3C_ERR_NO_DEVICES,
} I3C_Status;

/*----------------------------------------------------------------------------
 * FIFO target definitions
 *--------------------------------------------------------------------------*/
typedef enum {
    TX_FIFO = 0U,
    RX_FIFO = 1U,
} I3C_CSR_TARGET;

/*----------------------------------------------------------------------------
 * Device information collected during ENTDAA discovery
 *--------------------------------------------------------------------------*/
typedef struct {
    uint8_t controller_id;
    uint8_t dynamic_addr;
    uint64_t pid;
    uint8_t bcr;
    uint8_t dcr;
    bool active;
} I3C_DeviceInfo;

/*----------------------------------------------------------------------------
 * Transmit modes
 *--------------------------------------------------------------------------*/
typedef enum {
    I3C_CMD_XMIT_MODE_SINGLE_CSR = 0U,
    I3C_CMD_XMIT_MODE_MULTI_BYTE_INC = 1U,
    I3C_CMD_XMIT_MODE_MULTI_BYTE_STATIC = 2U,
    I3C_CMD_XMIT_MODE_NCA = 3U,
} I3C_TransmitMode;

/*----------------------------------------------------------------------------
 * Bus mode
 *--------------------------------------------------------------------------*/
typedef enum {
    I3C_BUS_MODE_PURE = 0U,
    I3C_BUS_MODE_INVALID = 1U,
    I3C_BUS_MODE_MIXED_FAST = 2U,
    I3C_BUS_MODE_MIXED_SLOW = 3U,
} I3C_BusMode;

/*----------------------------------------------------------------------------
 * Role of this controller
 *--------------------------------------------------------------------------*/
typedef enum {
    MANAGER = 0U,
    SECONDARY_MGR = 1U,
    SUBORDINATE = 2U,
} I3C_Role;

/*----------------------------------------------------------------------------
 * Hardware command errors
 *--------------------------------------------------------------------------*/
typedef enum {
    CMDR_ERROR_NO_ERROR = 0x0,
    CMDR_ERROR_DDR_PREAMBLE = 0x1,
    CMDR_ERROR_DDR_PARITY = 0x2,
    CMDR_ERROR_DDR_RX_OVF = 0x3,
    CMDR_ERROR_DDR_TX_UNF = 0x4,
    CMDR_ERROR_M0 = 0x5,
    CMDR_ERROR_M1 = 0x6,
    CMDR_ERROR_M2 = 0x7,
    CMDR_ERROR_MST_ABORT = 0x8,
    CMDR_ERROR_NACK_RESP = 0x9,
    CMDR_ERROR_INVALID_DA = 0xA,
    CMDR_ERROR_DDR_DROPPED = 0xB,
} I3C_CMDR_ERROR;

static const char *const i3c_error_messages[] = {
    [CMDR_ERROR_NO_ERROR] = "No error\n",
    [CMDR_ERROR_DDR_PREAMBLE] = "ERR: DDR Preamble\n",
    [CMDR_ERROR_DDR_PARITY] = "ERR: DDR Parity\n",
    [CMDR_ERROR_DDR_RX_OVF] = "ERR: DDR RX Overflow\n",
    [CMDR_ERROR_DDR_TX_UNF] = "ERR: DDR TX Underflow\n",
    [CMDR_ERROR_M0] = "ERR: M0\n",
    [CMDR_ERROR_M1] = "ERR: M1\n",
    [CMDR_ERROR_M2] = "ERR: M2\n",
    [CMDR_ERROR_MST_ABORT] = "ERR: Master abort\n",
    [CMDR_ERROR_NACK_RESP] = "ERR: NACK response\n",
    [CMDR_ERROR_INVALID_DA] = "ERR: Invalid dynamic address\n",
    [CMDR_ERROR_DDR_DROPPED] = "ERR: DDR dropped\n",
};

static inline void decode_cmdr_error(const uint8_t err) {
    simputs(i3c_error_messages[err]);
}

/* Helper: calculate the I3C dynamic address parity bit. */
static inline uint8_t calculate_dynamic_addr(uint8_t addr) {
    uint8_t upper_bits = addr >> 1;
    uint8_t xor_result = 0;
    for (int j = 0; j < 7; j++) {
        xor_result ^= (upper_bits >> j) & 0x01;
    }
    return (uint8_t)((upper_bits << 1) | ((~xor_result) & 0x01));
}

/*----------------------------------------------------------------------------
 * I3C driver vtable
 *--------------------------------------------------------------------------*/
typedef struct I3C_Driver I3C_Driver;

struct I3C_Driver {
    I3C_Status (*init)(I3C_Driver *drv, uint8_t controller_id, uint64_t device_id, I3C_Role role);
    I3C_Status (*start)(I3C_Driver *drv, int sys_clk_freq);
    I3C_Status (*issue_entdaa)(I3C_Driver *drv);
    I3C_Status (*issue_setgrpa)(I3C_Driver *drv, uint8_t da, uint8_t group_addr);
    I3C_Status (*wait_command)(I3C_Driver *drv, uint8_t command_id, uint32_t timeout);
    I3C_Status (*process_devices)(I3C_Driver *drv, I3C_DeviceInfo *devices, size_t max_devices);
    I3C_Status (*write)(I3C_Driver *drv, uint8_t da, const uint8_t *data, size_t length);
    I3C_Status (*read)(I3C_Driver *drv, uint8_t da, uint8_t *buffer, size_t length);
    I3C_Status (*fifo_write)(I3C_Driver *drv, const uint8_t *data, size_t length);
    I3C_Status (*fifo_read)(I3C_Driver *drv, uint8_t *buffer, size_t length, size_t *bytes_read);
    I3C_Status (*send_payload)(I3C_Driver *drv, const uint8_t addr, const uint8_t *data,
                               size_t length);
    I3C_Status (*send_payload_stream)(I3C_Driver *drv, const uint8_t addr, const uint8_t *data,
                                      size_t length);
    uint32_t (*check_rx_fifo)(I3C_Driver *drv);
    I3C_Status (*receive_payload)(I3C_Driver *drv, uint8_t *buffer, size_t buffer_length,
                                  size_t *bytes_received);
    I3C_Status (*receive_payload_stream)(I3C_Driver *drv, uint8_t *buffer, size_t buffer_length,
                                         size_t *bytes_received);

    struct {
        uint8_t controller_id;
        I3C_Role role;
        bool initialized;
        I3C_DeviceInfo discovered_devices[I3C_MAX_DEVICES];
        uint8_t num_devices;
    } ctx;
};

/*
 * Obtain a driver instance for the given controller.
 *
 * Defined by i3c_controller_driver.c when I3C_USE_HCI_CORE is set; a build that
 * leaves it undefined must supply this symbol from a platform driver.
 */
I3C_Driver *I3C_GetDriverInstance(uint8_t controller_id);

/* Low-level platform hooks called by driver implementations. */
void i3c_release_reset(uint8_t i3c_controller);
void cfg_ps(uint8_t i3c_controller, uint8_t device_id, I3C_Role role);
void init_i3c_ctrl(uint8_t controller_id, uint64_t device_id, I3C_Role role);

#endif /* I3C_CONTROLLER_DRIVER_H_ */
