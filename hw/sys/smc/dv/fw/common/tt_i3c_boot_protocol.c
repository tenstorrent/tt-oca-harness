#include "tt_i3c_boot_protocol.h"
#include <string.h>
#include "virt_console.h"  // For simputs(), simputshex32(), etc.

// Dummy memory access helpers
static inline void write_memory(uint64_t addr, const uint8_t *data, size_t len) {
    volatile uint8_t *dest = (volatile uint8_t *)(uintptr_t)addr;
    for (uint8_t i = 0; i < len; i++) {
        dest[i] = data[i];
    }
}

static inline void read_memory(uint64_t addr, uint8_t *buf, size_t len) {
    volatile uint8_t *src = (volatile uint8_t *)(uintptr_t)addr;
    for (uint8_t i = 0; i < len; i++) {
        buf[i] = src[i];
    }
}

static inline uint32_t read_memory32(uint32_t addr) {
    volatile uint32_t *src = (volatile uint32_t *)(uintptr_t)addr;
    return *src;
}

// -------------------------------------------------------------------
// Handlers
// -------------------------------------------------------------------
static BootResult boot_handle_write(I3C_Driver *drv) {
    uint8_t header[9];
    size_t bytes_received;
    if (drv->receive_payload(drv, header, sizeof(header), &bytes_received) != I3C_OK ||
        bytes_received != sizeof(header)) {
        simputs("CMD_WRITE: Error reading header\n");
        return INVALID_CMD;
    }
    uint64_t addr;
    memcpy(&addr, header, 8);
    uint8_t data_len = header[8];

    uint8_t data_buf[256] = {0};
    size_t data_size = (data_len == 0) ? 256 : data_len;
    if (drv->receive_payload_stream(drv, data_buf, data_size, &bytes_received) != I3C_OK ||
        bytes_received != data_size) {
        simputs("CMD_WRITE: Error reading payload\n");
        return INVALID_CMD;
    }
    for (int i = 0; i < data_size/8; i++) {
        uint64_t data_word = ((uint64_t) data_buf[(i*8) + 0]) |
                            (((uint64_t) data_buf[(i*8) + 1]) << 8) |
                            (((uint64_t) data_buf[(i*8) + 2]) << 16) |
                            (((uint64_t) data_buf[(i*8) + 3]) << 24) |
                            (((uint64_t) data_buf[(i*8) + 4]) << 32) |
                            (((uint64_t) data_buf[(i*8) + 5]) << 40) |
                            (((uint64_t) data_buf[(i*8) + 6]) << 48) |
                            (((uint64_t) data_buf[(i*8) + 7]) << 56);
        write64_reg(addr + (i*8), data_word);
    }
    // if there are remaining bytes to write:
    if ((data_size % 8) > 0) {
        uint64_t data_word = 0;
        for (int i = 0; i < (data_size % 8); i++) {
          data_word |= (uint64_t) data_buf[(data_size-(8+i))] << (8*i);
        }
        write64_reg(addr + (data_size/8), data_word);
    }
    //write_memory(addr, data_buf, data_size);
    simputs("CMD_WRITE executed successfully\n");
    return CMD_SUCCESS;
}

static BootResult boot_handle_write32(I3C_Driver *drv) {
    uint8_t buf[8];
    size_t bytes_received;
    if (drv->receive_payload(drv, buf, sizeof(buf), &bytes_received) != I3C_OK ||
        bytes_received != sizeof(buf)) {
        simputs("CMD_WRITE_32: Error reading payload\n");
        return INVALID_CMD;
    }
    uint32_t addr_be, data_be;
    memcpy(&addr_be, buf, sizeof(addr_be));
    memcpy(&data_be, buf + 4, sizeof(data_be));
    uint32_t addr = __builtin_bswap32(addr_be);
    uint32_t data = __builtin_bswap32(data_be);
    // uint32_t addr, data;
    // memcpy(&addr, buf, sizeof(addr));
    // memcpy(&data, buf + 4, sizeof(data));
    simputshex32("CMD_WRITE_32: Writing data ", data);
    simputshex32(" to address ", addr);
    write_memory((uint64_t)addr, (uint8_t *)&data, sizeof(data));
    simputs("CMD_WRITE_32 executed successfully\n");
    return CMD_SUCCESS;
}

static BootResult boot_handle_write64(I3C_Driver *drv) {
    uint8_t buf[12];
    size_t bytes_received;
    if (drv->receive_payload(drv, buf, sizeof(buf), &bytes_received) != I3C_OK ||
        bytes_received != sizeof(buf)) {
        simputs("CMD_WRITE_64: Error reading payload\n");
        return INVALID_CMD;
    }
    uint32_t addr32;
    memcpy(&addr32, buf, sizeof(addr32));
    uint64_t data;
    memcpy(&data, buf + 4, sizeof(data));

    write_memory((uint64_t)addr32, (uint8_t *)&data, sizeof(data));
    simputs("CMD_WRITE_64 executed successfully\n");
    return CMD_SUCCESS;
}

static BootResult boot_handle_read(I3C_Driver *drv) {
    uint8_t header[9];
    size_t bytes_received;
    if (drv->receive_payload(drv, header, sizeof(header), &bytes_received) != I3C_OK ||
        bytes_received != sizeof(header)) {
        simputs("CMD_READ: Error reading header\n");
        return INVALID_CMD;
    }
    uint64_t addr;
    memcpy(&addr, header, 8);
    uint8_t data_len = header[8];

    uint8_t data_buf[256] = {0};
    read_memory(addr, data_buf, data_len);
    if (drv->fifo_write(drv, data_buf, data_len) != I3C_OK) {
        simputs("CMD_READ: Error sending data\n");
        return INVALID_CMD;
    }
    simputs("CMD_READ executed successfully\n");
    return CMD_SUCCESS;
}

static BootResult boot_handle_read32(I3C_Driver *drv) {
    uint8_t buf[4];
    size_t bytes_received;
    if (drv->receive_payload(drv, buf, sizeof(buf), &bytes_received) != I3C_OK ||
        bytes_received != sizeof(buf)) {
        simputs("CMD_READ_32: Error reading payload\n");
        return INVALID_CMD;
    }

    CDNSI3C_REG_SLV_CTRL_reg_u slv_ctrl;
    slv_ctrl.f.pr_pl = 4;
    write_i3c(drv->ctx.controller_id, SMC_AXIL_EXTENSION_CDNS_I3C_WRAP_0_CADENCE_I3C_CDNSI3C_REG_A_SLV_CTRL_REG_OFFSET, slv_ctrl.val);

    uint32_t addr;
    memcpy(&addr, buf, sizeof(addr));
    uint32_t data = read_memory32(addr);
    simputshex32("CMD_READ_32: Data read = ", data);
    simputs("\n");
    if (drv->fifo_write(drv, (uint8_t *)&data, sizeof(data)) != I3C_OK) {
        simputs("CMD_READ_32: Error sending response\n");
        return INVALID_CMD;
    }

    CDNSI3C_REG_SLV_STATUS1_reg_u slv_status1, slv_status1_read;
    slv_status1.f.nack_nxt_pr = 1;
    write_i3c(drv->ctx.controller_id, SMC_AXIL_EXTENSION_CDNS_I3C_WRAP_0_CADENCE_I3C_CDNSI3C_REG_A_SLV_STATUS1_REG_OFFSET, slv_status1.val);
    simputs("unblock\n");

    simputs("CMD_READ_32 executed successfully\n");
    return CMD_SUCCESS;
}

static BootResult boot_handle_read64(I3C_Driver *drv) {
    uint8_t buf[8];
    size_t bytes_received;
    if (drv->receive_payload(drv, buf, sizeof(buf), &bytes_received) != I3C_OK ||
        bytes_received != sizeof(buf)) {
        simputs("CMD_READ_64: Error reading address\n");
        return INVALID_CMD;
    }

    CDNSI3C_REG_SLV_CTRL_reg_u slv_ctrl;
    slv_ctrl.f.pr_pl = 8;
    write_i3c(drv->ctx.controller_id, SMC_AXIL_EXTENSION_CDNS_I3C_WRAP_0_CADENCE_I3C_CDNSI3C_REG_A_SLV_CTRL_REG_OFFSET, slv_ctrl.val);

    uint64_t addr;
    memcpy(&addr, buf, sizeof(addr));
    uint64_t data;
    read_memory(addr, (uint8_t *)&data, sizeof(data));
    simputshex32("CMD_READ_64: addr = ", addr);
    simputshex32("CMD_READ_64: data = ", data);
    if (drv->fifo_write(drv, (uint8_t *)&data, sizeof(data)) != I3C_OK) {
        simputs("CMD_READ_64: Error sending response\n");
        return INVALID_CMD;
    }

    CDNSI3C_REG_SLV_STATUS1_reg_u slv_status1, slv_status1_read;
    slv_status1.f.nack_nxt_pr = 1;
    write_i3c(drv->ctx.controller_id, SMC_AXIL_EXTENSION_CDNS_I3C_WRAP_0_CADENCE_I3C_CDNSI3C_REG_A_SLV_STATUS1_REG_OFFSET, slv_status1.val);
    simputs("unblock\n");

    simputs("CMD_READ_64 executed successfully\n");
    return CMD_SUCCESS;
}

// -------------------------------------------------------------------
// Dispatcher
// -------------------------------------------------------------------
BootResult boot_process_command(I3C_Driver *drv, uint8_t cmd) {
    simputshex16("Processing command: ", cmd);
    switch ((BootCommand)cmd) {
        case CMD_WRITE:
            return boot_handle_write(drv);
        case CMD_WRITE_32:
            return boot_handle_write32(drv);
        case CMD_WRITE_64:
            return boot_handle_write64(drv);
        case CMD_READ:
            return boot_handle_read(drv);
        case CMD_READ_32:
            return boot_handle_read32(drv);
        case CMD_READ_64:
            return boot_handle_read64(drv);
        default:
            simputs("Unknown boot command received\n");
            return INVALID_CMD;
    }
}

// -------------------------------------------------------------------
// Main Loop (Receiver Side)
// -------------------------------------------------------------------
void boot_run(I3C_Driver *drv) {
    const size_t buffer_size = 1;
    uint8_t buffer[buffer_size];
    size_t bytes_received;
    while (1) {
        if (drv->receive_payload(drv, buffer, buffer_size, &bytes_received) != I3C_OK ||
            bytes_received != 1) {
            simputs("Error receiving command byte\n");
            continue;
        }
        uint8_t cmd = buffer[0];
        simputs("Command received: ");
        simputshex32("", cmd);
        simputs("\n");

        BootResult result = boot_process_command(drv, cmd);
        if (result != CMD_SUCCESS) {
            simputs("Boot command processing error\n");
        }
    }
}

// -------------------------------------------------------------------
// Sender Functions (Master Side)
// -------------------------------------------------------------------
I3C_Status boot_send_write(I3C_Driver *drv, uint8_t dynamic_addr,
                           uint64_t addr, const uint8_t *data, uint8_t length) {
    // for longer writes, we will send data as a fixed length stream following the command to greatly increase bandwidth
    uint8_t command[10] = {0};
    uint8_t cmd_bytes = get_write_cmd(addr, data, length, command);
    I3C_Status retval = drv->send_payload(drv, dynamic_addr, command, cmd_bytes);
    if (retval != I3C_OK)
        return retval;
    return drv->send_payload_stream(drv, dynamic_addr, data, ((length == 0) ? 256 : length));
}

I3C_Status boot_send_write32(I3C_Driver *drv, uint8_t dynamic_addr,
                             uint32_t addr, uint32_t data) {
    uint8_t command[WRITE32_CMD_LENGTH] = {0};
    uint8_t cmd_bytes = get_write32_cmd(addr, data, command);
    return drv->send_payload(drv, dynamic_addr, command, cmd_bytes);
}

I3C_Status boot_send_write64(I3C_Driver *drv, uint8_t dynamic_addr,
                             uint32_t addr, uint64_t data) {
    uint8_t command[13] = {0};
    command[0] = CMD_WRITE_64;
    memcpy(command + 1, &addr, sizeof(uint32_t));
    memcpy(command + 5, &data, sizeof(uint64_t));
    return drv->send_payload(drv, dynamic_addr, command, 13);
}

I3C_Status boot_send_read(I3C_Driver *drv, uint8_t dynamic_addr,
                          uint64_t addr, uint8_t length) {
    uint8_t command[READ_CMD_LENGTH] = {0};
    uint8_t cmd_bytes = get_read_cmd(addr, length, command);
    return drv->send_payload(drv, dynamic_addr, command, cmd_bytes);
}

I3C_Status boot_send_read32(I3C_Driver *drv, uint8_t dynamic_addr,
                            uint32_t addr, uint32_t *data) {
    uint8_t command[READ32_CMD_LENGTH] = {0};
    uint8_t cmd_bytes = get_read32_cmd(addr, command);
    I3C_Status status = drv->send_payload(drv, dynamic_addr, command, cmd_bytes);
    if (status != I3C_OK) {
        return status;
    }

    uint8_t buffer[4] = {0};
    do {
        // might get NACK if write op not completed at target
        status = drv->read(drv, dynamic_addr, buffer, 4);
        if ((status != I3C_OK) && (status != I3C_ERR_CMD_FAILED))
            return status;
    } while (status != I3C_OK);

    memcpy(data, buffer, 4);
    return I3C_OK;
}

I3C_Status boot_send_read64(I3C_Driver *drv, uint8_t dynamic_addr,
                            uint64_t addr, uint64_t *data) {
    uint8_t command[READ64_CMD_LENGTH] = {0};
    uint8_t cmd_bytes = get_read64_cmd(addr, command);
    I3C_Status status = drv->send_payload(drv, dynamic_addr, command, cmd_bytes);
    if (status != I3C_OK) {
        return status;
    }

    uint8_t buffer[8] = {0};
    do {
        // might get NACK if write op not completed at target
        status = drv->read(drv, dynamic_addr, buffer, 8);
        if ((status != I3C_OK) && (status != I3C_ERR_CMD_FAILED))
            return status;
    } while (status != I3C_OK);

    memcpy(data, buffer, 8);
    return I3C_OK;
}

I3C_Status boot_send_status(I3C_Driver *drv, uint8_t dynamic_addr) {
    uint8_t command[STATUS_CMD_LENGTH] = {0};
    uint8_t cmd_bytes = get_status_cmd(command);
    return drv->send_payload(drv, dynamic_addr, command, cmd_bytes);
}

I3C_Status boot_send_set_bar0(I3C_Driver *drv, uint8_t dynamic_addr, uint64_t addr) {
    uint8_t command[BAR_CMD_LENGTH] = {0};
    uint8_t cmd_bytes = get_set_bar0_cmd(addr, command);
    return drv->send_payload(drv, dynamic_addr, command, cmd_bytes);
}

// Optional: a more robust state-machine could go here
void boot_run_state_machine(I3C_Driver *drv) {
    // Not implemented here
}
