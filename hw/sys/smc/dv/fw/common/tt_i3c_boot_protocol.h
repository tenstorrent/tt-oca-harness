#ifndef TT_I3C_BOOT_PROTOCOL_H
#define TT_I3C_BOOT_PROTOCOL_H

#include <stdbool.h>
#include <stdint.h>
#include <string.h>  // for memcpy

#include "tt_i3c.h"

// Boot Command IDs
typedef enum {
  CMD_SET_BAR0 = 0x0,
  CMD_SET_BAR1 = 0x1,
  CMD_SET_BAR2 = 0x2,
  CMD_SET_BAR3 = 0x3,
  CMD_GET_STATUS = 0x4,
  CMD_WRITE = 0x5,
  CMD_WRITE_32 = 0x6,
  CMD_WRITE_64 = 0x7,
  CMD_READ = 0x8,
  CMD_READ_32 = 0x9,
  CMD_READ_64 = 0xA
} BootCommand;

// Packet Length Definitions
#define BAR_CMD_LENGTH 9
#define STATUS_CMD_LENGTH 1
#define WRITE_CMD_LENGTH 10
#define WRITE32_CMD_LENGTH 9
#define WRITE64_CMD_LENGTH 13
#define READ_CMD_LENGTH 10
#define READ32_CMD_LENGTH 5
#define READ64_CMD_LENGTH 9

// Boot Status Structure
typedef struct __attribute__((packed)) {
  uint8_t last_command;
  uint8_t first_error_command;
} BootStatus;

// Boot Result Codes
typedef enum {
  CMD_SUCCESS,
  INVALID_CMD,
  CMD_ERR,
} BootResult;

// Inline Command Builders
static inline uint8_t get_write_cmd(uint64_t addr, const uint8_t *restrict data,
                                    uint8_t length, uint8_t *restrict buffer) {
  buffer[0] = CMD_WRITE;
  memcpy(buffer + 1, &addr, sizeof(addr));
  buffer[9] = length;
  return WRITE_CMD_LENGTH;
}

static inline uint8_t get_write32_cmd(uint32_t addr, uint32_t data, uint8_t *restrict buffer) {
  buffer[0] = CMD_WRITE_32;
  uint32_t addr_be = __builtin_bswap32(addr);
  uint32_t data_be = __builtin_bswap32(data);
  memcpy(buffer + 1, &addr_be, sizeof(addr_be));
  memcpy(buffer + 5, &data_be, sizeof(data_be));
  return WRITE32_CMD_LENGTH;
}

static inline uint8_t get_write64_cmd(uint32_t addr, uint64_t data,
                                      uint8_t *restrict buffer) {
  buffer[0] = CMD_WRITE_64;
  memcpy(buffer + 1, &addr, sizeof(addr));
  memcpy(buffer + 5, &data, sizeof(data));
  return WRITE64_CMD_LENGTH;
}

static inline uint8_t get_read_cmd(uint64_t addr, uint8_t length,
                                   uint8_t *restrict buffer) {
  buffer[0] = CMD_READ;
  memcpy(buffer + 1, &addr, sizeof(addr));
  buffer[9] = length;
  return READ_CMD_LENGTH;
}

static inline uint8_t get_read32_cmd(uint32_t addr, uint8_t *restrict buffer) {
  buffer[0] = CMD_READ_32;
  memcpy(buffer + 1, &addr, sizeof(addr));
  return READ32_CMD_LENGTH;
}

static inline uint8_t get_read64_cmd(uint64_t addr, uint8_t *restrict buffer) {
  buffer[0] = CMD_READ_64;
  memcpy(buffer + 1, &addr, sizeof(addr));
  return READ64_CMD_LENGTH;
}

static inline uint8_t get_status_cmd(uint8_t *restrict buffer) {
  buffer[0] = CMD_GET_STATUS;
  return STATUS_CMD_LENGTH;
}

#define DEFINE_SET_BAR_CMD(num)                                            \
  static inline uint8_t get_set_bar##num##_cmd(uint64_t addr,              \
                                               uint8_t *restrict buffer) { \
    buffer[0] = CMD_SET_BAR##num;                                          \
    memcpy(buffer + 1, &addr, sizeof(addr));                               \
    return BAR_CMD_LENGTH;                                                 \
  }

DEFINE_SET_BAR_CMD(0)
DEFINE_SET_BAR_CMD(1)
DEFINE_SET_BAR_CMD(2)
DEFINE_SET_BAR_CMD(3)

// Sender Function Prototypes
I3C_Status boot_send_write(I3C_Driver *drv, uint8_t dynamic_addr, uint64_t addr,
                           const uint8_t *data, uint8_t length);

I3C_Status boot_send_write32(I3C_Driver *drv, uint8_t dynamic_addr,
                             uint32_t addr, uint32_t data);

I3C_Status boot_send_write64(I3C_Driver *drv, uint8_t dynamic_addr,
                             uint32_t addr, uint64_t data);

I3C_Status boot_send_read(I3C_Driver *drv, uint8_t dynamic_addr, uint64_t addr,
                          uint8_t length);

I3C_Status boot_send_read32(I3C_Driver *drv, uint8_t dynamic_addr,
                            uint32_t addr, uint32_t *data);

I3C_Status boot_send_read64(I3C_Driver *drv, uint8_t dynamic_addr,
                            uint64_t addr, uint64_t *data);

I3C_Status boot_send_status(I3C_Driver *drv, uint8_t dynamic_addr);

I3C_Status boot_send_set_bar0(I3C_Driver *drv, uint8_t dynamic_addr,
                              uint64_t addr);

// Receiver (Handler) and Dispatcher Prototypes
// BootResult boot_process_command_packet(I3C_Driver *drv, const uint8_t *packet,
                                      //  size_t packet_length);
void boot_run(I3C_Driver *drv);
void boot_run_state_machine(I3C_Driver *drv);  // optional

#endif  // TT_I3C_BOOT_PROTOCOL_H
