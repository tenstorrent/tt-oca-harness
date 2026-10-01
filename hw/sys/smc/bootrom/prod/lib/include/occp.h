/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#ifndef OCCP_H
#define OCCP_H

#include <stdbool.h>
#include <stdint.h>

#define OCCP_VERSION_MAJOR 1
#define OCCP_VERSION_MINOR 0
#define OCCP_VERSION_PATCH 0

#define BOOT_VERSION_MAJOR 1
#define BOOT_VERSION_MINOR 0
#define BOOT_VERSION_PATCH 0 // Boot version is set to 1.0.0 for ROM 1.0.0

// Maximum size for read/write operations
// OCCP buffer size is set to 256 -1 for 0 based indexing. This is set independent of the underlying
// transport layer MTU. For I2C the FIFO depth is 8bytes. The I3C controller uses a 32-entry FIFO
// with 4-byte words, providing 128 bytes total capacity for data transfers
#define OCCP_MAX_MSG_SIZE 2047

#define WRITE_HEADER_LENGTH 12
#define READ_HEADER_LENGTH 12
#define EXEC_IMG_HEADER_LENGTH 10
#define AUTH_IMG_HEADER_LENGTH 10
#define GET_VER_HEADER_LENGTH 0
#define GET_STAT_HEADER_LENGTH 2

#define OCCP_MAX_WR_SIZE \
    (OCCP_MAX_MSG_SIZE - WRITE_HEADER_LENGTH) // Max read/write size accounting for header and CRC
#define OCCP_MAX_RD_SIZE \
    OCCP_MAX_MSG_SIZE // Max read size is same as max message size, there are no other fields in the
                      // read data response Body

// Maximum count in 64-bit units to prevent integer overflow
#define OCCP_MAX_COUNT_64BIT_UNITS (OCCP_MAX_RD_SIZE / 8)

// Bounds checking helper macros
#define OCCP_CHECK_OVERFLOW_MUL(count, multiplier, max_result) \
    ((count) > ((max_result) / (multiplier)))

#define CRC8_POLYNOMIAL 0xD3
#define CRC32_POLYNOMIAL 0x992C1A4C
#define PACKET_SIZE_FOR_CRC8 14
/**
 * Brings up the interface drivers based on map of smc_interface_map.
 *
 * Also sets interface status bits of the OCCP status register during initialization flow.
 *
 * Returns OCCP_ERROR_NONE if all interfaces initialized successfully,
 * or an appropriate error code.
 */
int smc_occp_init(void);

/**
 * Legacy alias for smc_occp_init used by existing ROM main().
 */
int occp_init(void);

/**
 * Loops polling the active interfaces and responds to OCCP commands.
 * Never returns.
 */
void smc_occp_process(void);

/**
 * Legacy alias for smc_occp_process used by existing ROM main().
 */
void occp_process(void);

/**
 * Forces unlatch of the current interface and returns to polling all interfaces.
 * Used for error recovery or when interface becomes unresponsive.
 * Safe to call even if no interface is currently latched.
 */
void smc_occp_force_unlatch(void);

// OCCP command header changes from occp spec 0.6
typedef enum {
    Base = 0x0,
    Boot = 0x1,
} OccpAppId;

// Base Application Message IDs
typedef enum {
    GetVersion_base = 0x0,
    GetStatus = 0x1,
    WriteData = 0x2,
    ReadData = 0x3,
    Base_max_command = 0x4, // Boundary marker for valid commands
} Occp_BaseMsgID;

// Boot Application Message IDs
typedef enum {
    GetVersion_boot = 0x0,
    ExecuteImage = 0x1,
    AuthenticateImage = 0x2,
    Train_d2d = 0x3,
    Boot_max_command = 0x4, // Boundary marker for valid commands
} Occp_BootMsgID;

// Error Message IDs
typedef enum
/**
 * 0x1: Invalid_Appid
 *   The message contained an AppID that is not recognized or supported by the target.
 *   This can occur if the initiating device attempts to use an application that the target does not
 * support.
 *
 * 0x2: Invalid_Msgid
 *   The message contained a MsgID that is not recognized or supported by the target.
 *   This may happen if the initiating device tries to use a message that the target does not
 * support, or if the MsgID is not valid for the given AppID.
 *
 * 0x3: Invalid_header
 *   The message length is not valid or the header is malformed.
 *   This error is reported when the OCCP header passes the CRC but is otherwise invalid,
 *   such as when the message length exceeds what the target supports.
 *
 * 0x4: Corrupt_header
 *   Reserved (not described in the specification).
 *
 * 0x5: Corrupt_Data
 *   The data in the message fails the integrity check defined in the OCCP transport binding
 * (Section 5.2.4).
 *
 * 0x6: Invalid_Address
 *   The address provided in the request is not valid.
 *
 * 0x7: Unsupported_StatusID
 *   The status ID passed in the get_status request is not supported by the target.
 *   Some applications may not support returning a status, so requesting status from those
 * applications will return this error.
 *
 * 0x8: Invalid_Request_Length
 *   The length of the message is not valid for the given AppID, MsgID, and request arguments.
 *   For example, in a write_data request, the length in the header and the length in the request
 * arguments do not match.
 *
 * 0x9: Invalid_Request
 *   The request is malformed or contains invalid arguments.
 */
{ Invalid_Appid = 0x1,          // 0x1: Invalid AppID
  Invalid_Msgid = 0x2,          // 0x2: Invalid MsgID
  Invalid_header = 0x3,         // 0x3: Invalid header
  Corrupt_header = 0x4,         // 0x4: Reserved (not described)
  Corrupt_Data = 0x5,           // 0x5: Corrupt data
  Invalid_Address = 0x6,        // 0x6: Invalid address
  Unsupported_StatusID = 0x7,   // 0x7: Unsupported status ID
  Invalid_Request_Length = 0x8, // 0x8: Invalid request length
  Invalid_Request = 0x9,        // 0x9: Invalid request
  NoErr = 0xF,                  // Marker for no error

  // Transport layer errors
  Incomplete_msg = 0x10000, // 0x10000: Incomplete OCCP message. The I3C transaction did not contain
                            // a complete OCCP message. Reported when OCCP header message length is
                            // shorter than I3C transaction length.
  Oversize_msg = 0x10001,  // 0x10001: Oversized transaction. The I3C transaction is larger than the
                           // OCCP message it contains. Reported when OCCP header message length is
                           // longer than I3C transaction length.
  Transport_crc = 0x10002, // 0x10002: Transport CRC error. The transport CRC of the transaction
                           // failed. Doesn't apply for I3C/I2C as it has no CRC.
                           // 0x10003 - 0x1FFFF: Reserved for future transport layer errors
} Occp_ErrMsgID;

// OCCP occp_header (common for all messages)
typedef struct {
    uint8_t app_id;       // 0-7
    uint8_t msg_id;       // 8-15
    uint8_t flags : 4;    // 16-19
    bool error : 1;       // 20
    uint16_t length : 11; // 21-31
} __attribute__((packed)) occp_header;

typedef struct {
    uint8_t hdr_crc : 8;       // 0-7
    bool body_crc_present : 1; // 8
    uint32_t i3c_flags : 23;   // 9-31 Reserved for future use
    // OCCP Header
    occp_header hdr;
} __attribute__((packed)) packet_header;

typedef struct {
    uint8_t hdr_crc : 8;       // 0-7
    bool body_crc_present : 1; // 8
    uint32_t i3c_flags : 23;   // 9-31 Reserved for future use
    // OCCP Header
    occp_header hdr; // 32-63
    // Status Response Body
    uint32_t status : 32; // 64-95
    uint8_t body_crc : 8; // 96-103
} __attribute__((packed)) get_status_response;

typedef struct {
    uint8_t hdr_crc : 8;       // 0-7
    bool body_crc_present : 1; // 8
    uint32_t i3c_flags : 23;   // 9-31 Reserved for future use
    // OCCP Header
    occp_header hdr;
    // Get Version Response Body
    uint8_t major_version : 8;
    uint8_t minor_version : 8;
    uint16_t patch_version : 16;
    uint8_t body_crc : 8;
} __attribute__((packed)) get_version_response;

typedef struct {
    uint8_t hdr_crc : 8;       // 0-7
    bool body_crc_present : 1; // 8
    uint32_t i3c_flags : 23;   // 9-31 Reserved for future use
    // OCCP Header
    occp_header hdr; // 32-63
    // Get Version Response Body
    uint32_t err_code : 32; // 64-95
    uint8_t body_crc : 8;   // 96-103
} __attribute__((packed)) error_response;

typedef struct {
    uint8_t hdr_crc : 8;       // 0-7
    bool body_crc_present : 1; // 8
    uint32_t i3c_flags : 23;   // 9-31 Reserved for future use
    // OCCP Header
    occp_header hdr;
    // Read Response Body
    uint8_t read_data[80]; // Returned read data (80 bytes = 80*8 = 640 bits)
    uint32_t body_crc;     // CRC32 of the read data
} __attribute__((packed)) occp_read_response;

#endif // OCCP_H
