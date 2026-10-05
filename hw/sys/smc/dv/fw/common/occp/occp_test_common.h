/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * Protocol types, encoders and helper declarations shared by the OCCP controller-side tests.
 */

#ifndef OCCP_TEST_COMMON_H
#define OCCP_TEST_COMMON_H

#include <stddef.h>
#include <stdint.h>
#include <stdbool.h>

#include "cpu.h"
#include "smc_defines.h"
#include "smc_test.h"
#include "i3c_controller_driver.h"
#include "i2c_controller_driver.h"
#include "smc_occp_error_codes.h"

// Select which occp_master test categories are built.
#define RUN_TEST_GET_COMMANDS \
    1                          // Tests 1-4: GET_VERSION, GET_STATUS, GET_SEP_STATUS, GET_SMC_STATUS
#define RUN_TEST_BASIC_RW 1    // Test 5: Basic READ/WRITE operations (8-byte, 4-byte, 1-byte)
#define RUN_TEST_ALIGNMENT 0   // Test 6: Address alignment testing
#define RUN_TEST_LARGE_DATA 1  // Test 7: Large data transfer (16 bytes)
#define RUN_TEST_ZERO_LENGTH 1 // Test 8: Zero length transfer edge case
#define RUN_TEST_PATTERNS 1    // Test 9: Pattern verification test
#define RUN_TEST_BOUNDARIES 1  // Test 10: Memory boundary testing
#define RUN_TEST_SIZE_LIMITS 1 // Test 11: I3C Transfer size limits
#define RUN_TEST_STATUS_DUMP 1 // Test 12: Ring buffer status dumping

#define I3C_RECOVERY_CONTROLLER_ID 0
#define I3C_CONTROLLER_ID 1
#define I3C_BACKUP_CONTROLLER_ID 3
#define SMC_SCRATCHPAD_SIM_PASS_CODE 0xacafaca1
#define SMC_SCRATCHPAD_SIM_FAIL_CODE 0xffffffff
#define MAX_WRITES 25 // Maximum number of write transactions to scoreboard
// MAX_OCCP_READ_SIZE less the 12-byte address/length header a write body carries
#define MAX_OCCP_WRITE_SIZE 2035
#define MAX_OCCP_READ_SIZE 2047

// Standardized OCCP test address range
#define SMC_SRAM_BASE_ADDR ((uint64_t)SMC_TOP_SPM_MEMORY_BASE_ADDR)
#define OCCP_TEST_BASE_ADDR 0xC0066400ULL              // First OCCP-accessible SRAM address
#define OCCP_TEST_BUFFER_SAFE_UPPER_ADDR 0xC0157000ULL // Exclusive bound for random test addresses
#define OCCP_TEST_UPPER_ADDR \
    (SMC_SRAM_BASE_ADDR + SMC_TOP_SPM_MEMORY_SIZE) // End of SRAM, exclusive

// OCCP Command definitions
typedef enum {
    OCCP_GET_VERSION = 0,
    OCCP_GET_VERSION_BOOT = 1,
    OCCP_GET_SEP_STATUS = 2,
    OCCP_GET_SMC_STATUS = 3,
    OCCP_GET_OCCP_BOOT_STATUS = 4,
    OCCP_GET_OCCP_INTERFACE_STATUS = 5,
    OCCP_GET_OCCP_COMMAND_COUNT = 6,
    OCCP_GET_OCCP_ERROR_CODE = 7,
    OCCP_READ = 8,
    OCCP_WRITE = 9,
    OCCP_JUMP = 10,
    OCCP_VALIDATE_BOOT = 11,
    OCCP_GET_STATUS = 12,
} occp_command_t;

typedef enum {
    OCCP_ERROR_NONE = 0x0,
    OCCP_INVALID_APPID = 0x1,
    OCCP_INVALID_MSGID = 0x2,
    OCCP_INVALID_HEADER = 0x3,
    OCCP_CORRUPT_HEADER = 0x4,
    OCCP_CORRUPT_DATA = 0x5,
    OCCP_INVALID_ADDRESS = 0x6,
    OCCP_UNSUPPORTED_STATUS = 0x7,
    OCCP_INVALID_REQ_LEN = 0x8,
    OCCP_INVALID_REQUEST = 0x9,
    OCCP_INCOMPLETE_MSG = 0x10000,
    OCCP_OVERSIZE_MSG = 0x10001,
    OCCP_TRANSPORT_CRC = 0x10002,
} occp_error_code_t;

static inline int print_error_code(occp_error_code_t error_code) {
    simputs("OCCP Error Code: ");
    int retval = 0;
    switch (error_code) {
    case OCCP_INVALID_APPID:
        simputs("OCCP_INVALID_APPID\n");
        break;
    case OCCP_INVALID_MSGID:
        simputs("OCCP_INVALID_MSGID\n");
        break;
    case OCCP_INVALID_HEADER:
        simputs("OCCP_INVALID_HEADER\n");
        break;
    case OCCP_CORRUPT_HEADER:
        simputs("OCCP_CORRUPT_HEADER\n");
        break;
    case OCCP_CORRUPT_DATA:
        simputs("OCCP_CORRUPT_DATA\n");
        break;
    case OCCP_INVALID_ADDRESS:
        simputs("OCCP_INVALID_ADDRESS\n");
        break;
    case OCCP_INVALID_REQ_LEN:
        simputs("OCCP_INVALID_REQ_LEN\n");
        break;
    case OCCP_INVALID_REQUEST:
        simputs("OCCP_INVALID_REQUEST\n");
        break;
    case OCCP_UNSUPPORTED_STATUS:
        simputs("OCCP_UNSUPPORTED_STATUS\n");
        break;
    case OCCP_INCOMPLETE_MSG:
        simputs("OCCP_INCOMPLETE_MSG\n");
        break;
    case OCCP_OVERSIZE_MSG:
        simputs("OCCP_OVERSIZE_MSG\n");
        break;
    case OCCP_TRANSPORT_CRC:
        simputs("OCCP_TRANSPORT_CRC\n");
        break;
    default:
        simputshex32("Unknown error Code: ", error_code);
        retval = -1;
        break;
    }
    return retval;
}

typedef enum {
    OCCP_SUCCESS = 0,
    OCCP_INVALID_CMD,
    OCCP_INVALID_ARG,
    OCCP_MEM_ACCESS_ERR,
    OCCP_UNALIGNED_ADDR_ERR,
    OCCP_INTERFACE_ERR,
    OCCP_READ_UNDERFLOW,
    OCCP_ERR,
    OCCP_TIMEOUT,
} occp_result_t;

typedef enum {
    OCCP_CRC_INJECT_NONE = 0,
    OCCP_CRC_INJECT_DETECTABLE,
    OCCP_CRC_INJECT_UNDETECTABLE,
    /* Corrupt only the CRC field of the header (always detectable) */
    OCCP_CORRUPT_CRC
} occp_crc_inject_mode_t;

typedef enum {
    OCCP_INVALID_HDR_INJECT_NONE = 0,
    OCCP_INVALID_HDR_INVALID_MSGID,
    OCCP_INVALID_HDR_INVALID_APPID,
    OCCP_INVALID_HDR_INVALID_BOTH
} occp_invalid_header_inject_mode_t;

/* Status message layout (status-coordination.adoc): [31:24] message type,
 * [23:16] firmware ID, [15:0] message value. */

typedef enum {
    OCCP_STATUS_MSG_STATUS = 0x01,
    OCCP_STATUS_MSG_WARNING = 0x08,
    OCCP_STATUS_MSG_ERROR = 0x0F,
} occp_status_msg_type_t;

typedef enum {
    OCCP_FW_ID_SEP_BL0 = 0x01,
    OCCP_FW_ID_SEP_BL1 = 0x02,
    OCCP_FW_ID_SMC_BL0 = 0x03,
    OCCP_FW_ID_SMC_BL1 = 0x04,
} occp_fw_id_t;

/* Selected SMC ROM status/error codes from specification (16-bit Message Value)
 * Names are prefixed to avoid collision with ROM header macros.
 */
typedef enum {
    /* Boot sequence status codes */
    OCCP_SPEC_STATUS_ROM_STARTED = 0x001,
    OCCP_SPEC_STATUS_BOOT_START = 0x010,
    OCCP_SPEC_STATUS_RECOVERY_MODE = 0x020,
    OCCP_SPEC_STATUS_PRIMARY_MODE = 0x021,
    OCCP_SPEC_STATUS_SECONDARY_MODE = 0x022,
    OCCP_SPEC_STATUS_INVALID_SEC_MODE = 0x025,
    OCCP_SPEC_STATUS_OCCP_INIT_FAILED = 0x030,
    OCCP_SPEC_STATUS_OCCP_READY = 0x031,
    OCCP_SPEC_STATUS_COORDINATION_ACTIVE = 0x040,
    OCCP_SPEC_STATUS_BOOT_COMPLETE = 0x050,
    OCCP_SPEC_STATUS_UNEXPECTED_EXIT = 0x0FF,

    /* OCCP command processing codes (errors and status) */
    OCCP_SPEC_ERROR_CMD_READ = 0x100,
    OCCP_SPEC_ERROR_CMD_UNKNOWN = 0x101,
    OCCP_SPEC_ERROR_CMD_FAILED = 0x110,
    OCCP_SPEC_ERROR_READ_OVERFLOW = 0x120,
    OCCP_SPEC_ERROR_READ_ACCESS_DENIED = 0x121,
    OCCP_SPEC_ERROR_WRITE_OVERFLOW = 0x130,
    OCCP_SPEC_ERROR_WRITE_ACCESS_DENIED = 0x131,
    OCCP_SPEC_ERROR_VALIDATE_SECURITY = 0x140,
    OCCP_SPEC_ERROR_VALIDATE_ADDRESS_FAILED = 0x141,
    OCCP_SPEC_STATUS_JUMP_EXECUTED = 0x200,
    OCCP_SPEC_ERROR_JUMP_SECURITY = 0x201,
    OCCP_SPEC_ERROR_JUMP_READ_FAILED = 0x202,
} smc_status_code_t;

#define OCCP_STATUS_EXTRACT_MSG_TYPE(v) ((uint8_t)(((v) >> 24) & 0xFF))
#define OCCP_STATUS_EXTRACT_FW_ID(v) ((uint8_t)(((v) >> 16) & 0xFF))
#define OCCP_STATUS_EXTRACT_VALUE(v) ((uint16_t)((v)&0xFFFF))

typedef enum {
    OCCP_APP_BASE = 0x0,
    OCCP_APP_BOOT = 0x1,
} occp_app_id_t;

typedef enum {
    OCCP_BASE_MSG_GET_VERSION = 0x0,
    OCCP_BASE_MSG_GET_STATUS = 0x1,
    OCCP_BASE_MSG_WRITE = 0x2,
    OCCP_BASE_MSG_READ = 0x3,
} occp_base_msg_id_t;

typedef enum {
    OCCP_BOOT_MSG_GET_VERSION = 0x0,
    OCCP_BOOT_MSG_EXECUTE_IMAGE = 0x1,
    OCCP_BOOT_MSG_AUTHENTICATE = 0x2,
} occp_boot_msg_id_t;

typedef struct {
    uint8_t app_id : 8;
    uint8_t msg_id : 8;
    uint8_t flags : 5;
    uint16_t length : 11;
} __attribute__((packed)) occp_req_header_word_t;

typedef struct {
    uint8_t header_crc : 8;
    bool body_crc_present : 1;
    uint32_t reserved : 23;
    occp_req_header_word_t header_word;
} __attribute__((packed)) occp_req_header_t;

typedef struct {
    uint8_t header_crc : 8;
    bool body_crc_present : 1;
    uint32_t reserved : 23;
    uint8_t app_id : 8;
    uint8_t msg_id : 8;
    uint8_t flags : 4;
    bool error : 1;
    uint16_t length : 11;
} __attribute__((packed)) occp_resp_header_t;

typedef struct {
    occp_req_header_t header;
    uint64_t addr : 64;
    uint16_t write_length : 11;
    uint8_t rwrite_attr : 5;
    uint16_t reserved : 16;
} __attribute__((packed)) occp_write_header_t;

typedef struct {
    occp_req_header_t header;
    uint64_t addr : 64;
    uint16_t read_length : 11;
    uint8_t read_attr : 5;
    uint16_t reserved : 16;
} __attribute__((packed)) occp_read_header_t;

typedef struct {
    occp_req_header_t header;
    uint64_t start_addr : 64;
    uint8_t cpu_id : 8;
    uint8_t reserved : 3;
    uint8_t addr_attr : 5;
} __attribute__((packed)) occp_exec_header_t;

static inline uint8_t calculate_crc8(uint8_t *data, size_t length) {
    uint8_t crc = 0xFF;
    const uint8_t poly = 0xD3u; /* x^8 + x^7 + x^6 + x^4 + x + 1 */
    for (int i = 0; i < length; i++) {
        uint8_t data_byte = data[i];
        for (int j = 0; j < 8; j++) {
            uint8_t data_bit = (data_byte & 0x80u) ? 1u : 0u;
            uint8_t crc_msb = (crc & 0x80u) ? 1u : 0u;

            crc = (uint8_t)(crc << 1);
            if ((uint8_t)(data_bit ^ crc_msb)) {
                crc ^= poly;
            }
            data_byte <<= 1;
        }
    }

    return crc;
}

static inline uint32_t calculate_crc32(uint8_t *data, size_t length) {
    uint32_t crc = 0xFFFFFFFF;
    const uint32_t poly = 0x992c1a4c;

    for (int i = 0; i < length; i++) {
        uint32_t data_word = (uint32_t)data[i] << 24;
        for (int j = 0; j < 8; j++) {
            uint32_t data_bit = (data_word & 0x80000000u) ? 1u : 0u;
            uint32_t crc_msb = (crc & 0x80000000u) ? 1u : 0u;

            crc = crc << 1;
            if (data_bit ^ crc_msb) {
                crc ^= poly;
            }
            data_word <<= 1;
        }
    }

    return ~crc;
}
/*
 * Build a request header and its CRC-8. Header word layout, sent little-endian:
 *  bits  0.. 7: app_id
 *  bits  8..15: msg_id
 *  bits 16..20: flags
 *  bits 21..31: length
 */
static inline occp_req_header_t occp_encode_header_word(occp_command_t command,
                                                        uint16_t data_length, bool has_body_crc) {
    occp_req_header_t header;
    occp_req_header_word_t header_word;
    uint16_t length = data_length;
    switch (command) {
    case OCCP_GET_VERSION:
        header_word.app_id = OCCP_APP_BASE;
        header_word.msg_id = OCCP_BASE_MSG_GET_VERSION;
        length = 0;
        break;
    case OCCP_GET_STATUS:
    case OCCP_GET_OCCP_BOOT_STATUS:
    case OCCP_GET_OCCP_INTERFACE_STATUS:
    case OCCP_GET_OCCP_COMMAND_COUNT:
    case OCCP_GET_OCCP_ERROR_CODE:
        header_word.app_id = OCCP_APP_BASE;
        header_word.msg_id = OCCP_BASE_MSG_GET_STATUS;
        length = 2;
        break;
    case OCCP_GET_SEP_STATUS:
        header_word.app_id = OCCP_APP_BASE;
        header_word.msg_id = OCCP_BASE_MSG_GET_STATUS;
        length = 2;
        break;
    case OCCP_GET_SMC_STATUS:
        header_word.app_id = OCCP_APP_BASE;
        header_word.msg_id = OCCP_BASE_MSG_GET_STATUS;
        length = 2;
        break;
    case OCCP_READ:
        header_word.app_id = OCCP_APP_BASE;
        header_word.msg_id = OCCP_BASE_MSG_READ;
        length = sizeof(occp_read_header_t) - sizeof(occp_req_header_t);
        break;
    case OCCP_WRITE:
        header_word.app_id = OCCP_APP_BASE;
        header_word.msg_id = OCCP_BASE_MSG_WRITE;
        length = data_length;
        break;
    case OCCP_GET_VERSION_BOOT:
        header_word.app_id = OCCP_APP_BOOT;
        header_word.msg_id = OCCP_BOOT_MSG_GET_VERSION;
        length = 0;
        break;
    case OCCP_JUMP:
        header_word.app_id = OCCP_APP_BOOT;
        header_word.msg_id = OCCP_BOOT_MSG_EXECUTE_IMAGE;
        length = sizeof(occp_exec_header_t) - sizeof(occp_req_header_t);
        break;
    case OCCP_VALIDATE_BOOT:
        header_word.app_id = OCCP_APP_BOOT;
        header_word.msg_id = OCCP_BOOT_MSG_AUTHENTICATE;
        length = sizeof(occp_exec_header_t) - sizeof(occp_req_header_t);
        break;
    default:
        return (occp_req_header_t){0, 0, 0, {0, 0, 0, 0}};
    }

    header_word.flags = 0;
    header_word.length = length & 0x7FF;
    header.body_crc_present = has_body_crc;
    header.reserved = 0;
    header.header_word = header_word;

    // The header CRC covers every header byte after the CRC byte itself.
    header.header_crc = calculate_crc8(((uint8_t *)&header) + 1, sizeof(header) - 1);
    simputshex32("Sending header crc: ", header.header_crc);
    simputshex32("Sending length: ", header.header_word.length);
    simputshex32("Sending body crc present: ", header.body_crc_present);
    return header;
}

static inline void occp_write_le32(uint8_t *dst, uint32_t w) {
    dst[0] = (uint8_t)(w & 0xFF);
    dst[1] = (uint8_t)((w >> 8) & 0xFF);
    dst[2] = (uint8_t)((w >> 16) & 0xFF);
    dst[3] = (uint8_t)((w >> 24) & 0xFF);
}

static inline void occp_write_be64(uint8_t *dst, uint64_t w) {
    dst[0] = (uint8_t)((w >> 56) & 0xFF);
    dst[1] = (uint8_t)((w >> 48) & 0xFF);
    dst[2] = (uint8_t)((w >> 40) & 0xFF);
    dst[3] = (uint8_t)((w >> 32) & 0xFF);
    dst[4] = (uint8_t)((w >> 24) & 0xFF);
    dst[5] = (uint8_t)((w >> 16) & 0xFF);
    dst[6] = (uint8_t)((w >> 8) & 0xFF);
    dst[7] = (uint8_t)(w & 0xFF);
}

static inline void occp_write_le64(uint8_t *dst, uint64_t w) {
    dst[0] = (uint8_t)(w & 0xFF);
    dst[1] = (uint8_t)((w >> 8) & 0xFF);
    dst[2] = (uint8_t)((w >> 16) & 0xFF);
    dst[3] = (uint8_t)((w >> 24) & 0xFF);
    dst[4] = (uint8_t)((w >> 32) & 0xFF);
    dst[5] = (uint8_t)((w >> 40) & 0xFF);
    dst[6] = (uint8_t)((w >> 48) & 0xFF);
    dst[7] = (uint8_t)((w >> 56) & 0xFF);
}

typedef struct {
    uint64_t address;
    uint16_t len;
    uint8_t data[MAX_OCCP_WRITE_SIZE];
} scoreboard_entry_t;

typedef enum { DRIVER_TYPE_I3C, DRIVER_TYPE_I2C } driver_type_t;

typedef struct {
    driver_type_t type;
    union {
        I3C_Driver *i3c_drv;
        I2C_Driver *i2c_drv;
    } drv;
    uint64_t slave_addr;
    uint64_t test_base_addr;
    uint64_t test_upper_addr_bound;
    bool overall_result;
    int sram_scoreboard_idx;
    scoreboard_entry_t sram_scoreboard[MAX_WRITES];
    int cmd_count;
    occp_error_code_t exp_response_code;
    int exp_occp_last_error;
    int timeout;
    bool exp_timeout;
    I3C_DeviceInfo discovered_devices[I3C_MAX_DEVICES];
    occp_crc_inject_mode_t header_crc_err_inject_mode;
    occp_crc_inject_mode_t body_crc_err_inject_mode;
    occp_invalid_header_inject_mode_t invalid_header_inject_mode;
    /* Send a request whose body length is invalid for its command */
    bool invalid_len_err_inject_enable;
    bool inject_undersize_header_err;
    bool inject_undersize_body_err;
    bool inject_oversize_body_err;
    /* Force zero-length message body when length injection is enabled */
    bool invalid_message_length_zero_inject_enable;
    /* Unsupported status ID injection for GET_STATUS family */
    bool unsupported_status_id_inject_enable;
    /* Latched STATUS_RPT_DISABLE strap value from DUT */
    bool status_reporting_disabled;
} test_context_t;

// Controller bring-up for the I3C or I2C interface
bool initialize_interface(test_context_t *ctx);
bool initialize_i3c_controller(I3C_Driver **drv);
bool initialize_i2c_controller(I2C_Driver **drv);
bool discover_devices(I3C_Driver *drv, I3C_DeviceInfo *discovered_devices);

bool is_secure_mode(void);

// Function declarations for OCCP commands
int occp_send_write_command(test_context_t *ctx, uint64_t i3c_addr, uint64_t addr,
                            const uint8_t *data, uint16_t byte_length);
int occp_send_read_command(test_context_t *ctx, uint64_t i3c_addr, uint64_t addr, uint8_t *recv,
                           uint16_t byte_length);
int occp_send_get_version_command(test_context_t *ctx, uint64_t i3c_addr, uint32_t *version);
int occp_send_get_version_boot_command(test_context_t *ctx, uint64_t i3c_addr, uint32_t *version);
int occp_send_get_status_command(test_context_t *ctx, uint64_t i3c_addr, uint32_t *status);
int occp_send_get_sep_status_command(test_context_t *ctx, uint64_t i3c_addr, uint32_t *status);
int occp_send_get_smc_status_command(test_context_t *ctx, uint64_t i3c_addr, uint32_t *status);
int occp_send_get_occp_boot_status_command(test_context_t *ctx, uint64_t i3c_addr,
                                           uint32_t *status);
int occp_send_get_occp_interface_status_command(test_context_t *ctx, uint64_t i3c_addr,
                                                uint32_t *status);
int occp_send_get_occp_command_count_command(test_context_t *ctx, uint64_t i3c_addr,
                                             uint32_t *status);
int occp_send_get_occp_error_code_command(test_context_t *ctx, uint64_t i3c_addr, uint32_t *status);
int occp_send_jump_command(test_context_t *ctx, uint64_t i3c_addr, uint64_t addr);
int occp_send_validate_boot_command(test_context_t *ctx, uint64_t i3c_addr, uint64_t addr);
/* Send a header corrupted per ctx->invalid_header_inject_mode, then random body bytes. */
int occp_send_invalid_header_command(test_context_t *ctx, uint64_t i3c_addr);

int occp_get_response_header(test_context_t *ctx, uint64_t i3c_addr,
                             /*out*/ occp_resp_header_t *resp_hdr);

// Status decoding functions
void print_status_message(uint32_t status);
void dump_ring_buffer_status(test_context_t *ctx, uint64_t slave_addr, const char *buffer_name,
                             int (*get_status_func)(test_context_t *, uint64_t, uint32_t *));

void check_occp_status_data(test_context_t *ctx, uint32_t status_data, int exp_interface_status,
                            int exp_boot_status);

/* Return true when status_value matches the expected fields. Unless match_full_status_data is
 * set, an SMC BL0 error code that carries data is compared under its per-code mask. */
bool occp_status_matches_expected(uint32_t status_value, occp_fw_id_t expected_fw_id,
                                  occp_status_msg_type_t expected_msg_type,
                                  uint16_t expected_status_data, bool match_full_status_data);
bool occp_is_smc_error_code(uint32_t status_value);
uint16_t get_random_occp_write_size(void);
uint16_t get_random_occp_read_size(void);
void send_random_occp_write(test_context_t *ctx, uint64_t addr_range);
void send_random_occp_read(test_context_t *ctx, uint64_t addr_range);
void execute_random_commands(test_context_t *ctx, int num_commands);
void send_max_size_occp_write(test_context_t *ctx, uint64_t addr_range);
void send_max_size_occp_read(test_context_t *ctx, uint64_t addr_range);
void execute_max_size_rw_commands(test_context_t *ctx, int num_commands);
void send_min_size_occp_write(test_context_t *ctx, uint64_t addr_range);
void send_min_size_occp_read(test_context_t *ctx, uint64_t addr_range);
void execute_min_size_rw_commands(test_context_t *ctx, int num_commands);
void increment_cmd_count(test_context_t *ctx);

#endif // OCCP_TEST_COMMON_H
