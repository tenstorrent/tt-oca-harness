/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Decodes OCCP status messages and dumps a status ring buffer. */

#include "occp_test_common.h"

static const char *get_firmware_name(uint8_t fw_id) {
    switch (fw_id) {
    case 0x0:
        return "SEP_BL0";
    case 0x1:
        return "SEP_BL1";
    case 0x2:
        return "SMC_BL0";
    case 0x3:
        return "SMC_BL1";
    default:
        return "UNKNOWN";
    }
}

static const char *get_message_type(uint8_t msg_type) {
    switch (msg_type) {
    case 0x0:
        return "STATUS";
    case 0x1:
        return "WARNING";
    case 0x2:
        return "ERROR";
    default:
        return "UNKNOWN";
    }
}

static const char *decode_status_code(uint32_t msg_value) {
    switch (msg_value) {
    // Boot sequence codes
    case SMC_STATUS_ROM_STARTED:
        return "ROM started";
    case SMC_STATUS_BOOT_START:
        return "Boot sequence started";
    case SMC_STATUS_RECOVERY_MODE:
        return "Recovery mode detected";
    case SMC_STATUS_PRIMARY_MODE:
        return "Primary mode detected";
    case SMC_STATUS_SECONDARY_MODE:
        return "Secondary mode detected";
    case SMC_STATUS_OCCP_INIT_FAILED:
        return "OCCP initialization failed";
    case SMC_STATUS_OCCP_READY:
        return "OCCP ready and operational";
    case SMC_STATUS_COORDINATION_ACTIVE:
        return "Coordination active";
    case SMC_STATUS_BOOT_COMPLETE:
        return "Boot sequence completed";
    case SMC_STATUS_UNEXPECTED_EXIT:
        return "Unexpected exit from main loop";

    // OCCP command errors
    case SMC_OCCP_ERROR_CMD_READ:
        return "Command read error from bus";
    case SMC_OCCP_ERROR_READ_OVERFLOW:
        return "READ buffer overflow";
    case SMC_OCCP_ERROR_WRITE_OVERFLOW:
        return "WRITE buffer overflow";
    case SMC_OCCP_ERROR_VALIDATE_SECURITY:
        return "VALIDATE_BOOT security violation";
    case SMC_OCCP_STATUS_JUMP_EXECUTED:
        return "JUMP executed successfully";
    case SMC_OCCP_ERROR_JUMP_SECURITY:
        return "JUMP blocked - security violation";
    case SMC_OCCP_ERROR_JUMP_READ_FAILED:
        return "JUMP failed - read error";

    default:
        // Check for error codes with additional data
        if ((msg_value & 0xFF0) == (SMC_OCCP_ERROR_CMD_UNKNOWN & 0xFF0)) {
            return "Unknown command";
        } else if ((msg_value & 0xFF0) == (SMC_OCCP_ERROR_CMD_FAILED & 0xFF0)) {
            return "Command execution failed";
        } else if ((msg_value & 0xFF0) == (SMC_OCCP_ERROR_READ_ACCESS_DENIED & 0xFF0)) {
            return "READ access denied";
        } else if ((msg_value & 0xFF0) == (SMC_OCCP_ERROR_WRITE_ACCESS_DENIED & 0xFF0)) {
            return "WRITE access denied";
        }
        return "Unknown status code";
    }
}

void print_status_message(uint32_t status) {
    if (status == 0) {
        simputs("  [Empty ring buffer entry]\n");
        return;
    }

    uint8_t fw_id = (status >> 28) & 0xF;
    uint8_t msg_type = (status >> 24) & 0xF;
    uint32_t msg_value = status & 0xFFFFFF;

    simputs("  [");
    simputs(get_firmware_name(fw_id));
    simputs("|");
    simputs(get_message_type(msg_type));
    simputs("] 0x");
    simputshex32("", msg_value);
    simputs(" - ");
    simputs(decode_status_code(msg_value));

    // Decode the extra data that some codes carry.
    if ((msg_value & 0xFF0) == (SMC_OCCP_ERROR_CMD_UNKNOWN & 0xFF0)) {
        simputs(" (cmd=0x");
        simputshex16("", msg_value & 0xFF);
        simputs(")");
    } else if ((msg_value & 0xFF0) == (SMC_OCCP_ERROR_CMD_FAILED & 0xFF0)) {
        simputs(" (err=0x");
        simputshex16("", msg_value & 0xF);
        simputs(")");
    } else if ((msg_value & 0xFF0) == (SMC_OCCP_ERROR_READ_ACCESS_DENIED & 0xFF0) ||
               (msg_value & 0xFF0) == (SMC_OCCP_ERROR_WRITE_ACCESS_DENIED & 0xFF0)) {
        simputs(" (violation=0x");
        simputshex16("", (msg_value >> 8) & 0xF);
        simputs(")");
    } else if ((msg_value & 0xFF0) == (SMC_OCCP_STATUS_JUMP_EXECUTED & 0xFF0)) {
        simputs(" (addr[23:16]=0x");
        simputshex16("", msg_value & 0xFF);
        simputs(")");
    } else if ((msg_value & 0xFF0) == (SMC_STATUS_BOOT_START & 0xFF0)) {
        uint8_t strap_status = msg_value & 0xF;
        if (strap_status & 0x8) simputs(" PRIMARY");
        if (strap_status & 0x4) simputs(" RECOVERY");
        if (strap_status & 0x2) simputs(" I2C");
    }

    simputs("\n");
}

void dump_ring_buffer_status(test_context_t *ctx, uint64_t slave_addr, const char *buffer_name,
                             int (*get_status_func)(test_context_t *, uint64_t, uint32_t *)) {
    if (ctx->status_reporting_disabled) {
        simputs("STATUS_RPT_DISABLE strap active; skipping ring buffer dump\n");
        return;
    }

    simputs("=== ");
    simputs(buffer_name);
    simputs(" Ring Buffer Contents ===\n");

    uint32_t status;
    int count = 0;
    int max_entries = 512; // Ring buffer size

    while (count < max_entries) {
        int result = get_status_func(ctx, slave_addr, &status);
        if (result != 0) {
            simputs("Error reading status from ring buffer\n");
            break;
        }

        if (status == 0) {
            simputs("Ring buffer empty (reached end)\n");
            break;
        }

        print_status_message(status);
        count++;
    }

    if (count == 0) {
        simputs("No entries found in ring buffer\n");
    } else {
        simputs("Total entries read: ");
        simputshex16("", count);
        simputs("\n");
    }
    simputs("\n");
}
