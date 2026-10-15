// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SEP OpenTitan SPI-host firmware helpers for the SEP DV tests. Header-only.
// Addresses and field masks come from generated sep_addr.h / spi_controller.h
// (via sep.h). Do not alias those symbols — call them by their PeakRDL names.

#ifndef SEP_SPI_H
#define SEP_SPI_H

#include <stdint.h>

#include "sep.h"

// CFG: CPOL/CPHA = 0 (Mode 0). CS timing CSNIDLE/TRAIL/LEAD=2 matches the testbench
// flash BFM (composed from generated field positions, not a packed hex constant).
#define SPI_CFG_CSN_TIMING \
    ((2u << SPI_CONTROLLER__CONFIGOPTS__CSNIDLE_bp) | \
     (2u << SPI_CONTROLLER__CONFIGOPTS__CSNTRAIL_bp) | \
     (2u << SPI_CONTROLLER__CONFIGOPTS__CSNLEAD_bp))
#define SPI_CFG_CSN(clkdiv) \
    (SPI_CFG_CSN_TIMING | (((uint32_t)(clkdiv) << SPI_CONTROLLER__CONFIGOPTS__CLKDIV_bp) & \
                           SPI_CONTROLLER__CONFIGOPTS__CLKDIV_bm))
#define SPI_CFG_CLKDIV9_CSN SPI_CFG_CSN(9u)

// CMD.DIRECTION encodings (not named in PeakRDL). A dummy segment runs LEN+1
// sck cycles and drives no data lane.
#define SPI_CMD_DIR_DUMMY 0u
#define SPI_CMD_DIR_RX 1u
#define SPI_CMD_DIR_TX 2u

// CMD.SPEED encodings (not named in PeakRDL): standard (one lane), dual, quad.
#define SPI_CMD_SPEED_STD 0u
#define SPI_CMD_SPEED_DUAL 1u
#define SPI_CMD_SPEED_QUAD 2u

/*
 * Composed register reset values (OCH_SEP_FIELD_RESET from sep.h).
 * Keep SPI-only reset aggregates here rather than growing common sep.h.
 */
#define SPI_CONTROLLER__INTR_STATE_reset \
    (OCH_SEP_FIELD_RESET(SPI_CONTROLLER__INTR_STATE, ERROR) | \
     OCH_SEP_FIELD_RESET(SPI_CONTROLLER__INTR_STATE, SPI_EVENT))

#define SPI_CONTROLLER__INTR_ENABLE_reset \
    (OCH_SEP_FIELD_RESET(SPI_CONTROLLER__INTR_ENABLE, ERROR) | \
     OCH_SEP_FIELD_RESET(SPI_CONTROLLER__INTR_ENABLE, SPI_EVENT))

#define SPI_CONTROLLER__INTR_TEST_reset \
    (OCH_SEP_FIELD_RESET(SPI_CONTROLLER__INTR_TEST, ERROR) | \
     OCH_SEP_FIELD_RESET(SPI_CONTROLLER__INTR_TEST, SPI_EVENT))

#define SPI_CONTROLLER__CSID_reset (OCH_SEP_FIELD_RESET(SPI_CONTROLLER__CSID, CSID))

#define SPI_CONTROLLER__EVENT_ENABLE_reset \
    (OCH_SEP_FIELD_RESET(SPI_CONTROLLER__EVENT_ENABLE, RXFULL) | \
     OCH_SEP_FIELD_RESET(SPI_CONTROLLER__EVENT_ENABLE, TXEMPTY) | \
     OCH_SEP_FIELD_RESET(SPI_CONTROLLER__EVENT_ENABLE, RXWM) | \
     OCH_SEP_FIELD_RESET(SPI_CONTROLLER__EVENT_ENABLE, TXWM) | \
     OCH_SEP_FIELD_RESET(SPI_CONTROLLER__EVENT_ENABLE, READY) | \
     OCH_SEP_FIELD_RESET(SPI_CONTROLLER__EVENT_ENABLE, IDLE))

/*
 * ERROR_STATUS field macros are PeakRDL-mangled in blocks/spi_controller.h.
 * Every field resets to 0.
 */
#define SPI_CONTROLLER__ERROR_STATUS_reset 0u

static inline uint32_t spi_rd(uint32_t addr) {
    return *(volatile uint32_t *)addr;
}

static inline void spi_wr(uint32_t addr, uint32_t value) {
    *(volatile uint32_t *)addr = value;
}

static inline int spi_wait_ready(int timeout) {
    /* Bounded so a wedged host surfaces as a firmware timeout. */
    while (timeout-- > 0) {
        if (spi_rd(SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR) & SPI_CONTROLLER__STATUS__READY_bm) {
            return 0;
        }
    }
    return -1;
}

// Spin until the controller is idle (no active segment).
static inline int spi_wait_idle(int timeout) {
    while (timeout-- > 0) {
        if (!(spi_rd(SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR) &
              SPI_CONTROLLER__STATUS__ACTIVE_bm)) {
            return 0;
        }
    }
    return -1;
}

/*
 * Flash command helpers. Each helper returns 0 on success and a negative value
 * when the host does not complete the command within SEP_SPI_TIMEOUT polls.
 * The checks and their FAIL lines stay in the tests. A test may define
 * SEP_SPI_TIMEOUT before it includes this header.
 */
#ifndef SEP_SPI_TIMEOUT
#define SEP_SPI_TIMEOUT 200000
#endif

// Opcodes of the flash commands the helpers issue.
#define SEP_SPI_OP_WREN 0x06u
#define SEP_SPI_OP_WRDI 0x04u
#define SEP_SPI_OP_RDSR 0x05u
#define SEP_SPI_OP_RDSR2 0x35u
#define SEP_SPI_OP_JEDEC 0x9Fu
#define SEP_SPI_OP_PP 0x02u       // page program, 1-1-1
#define SEP_SPI_OP_QPP 0x32u      // quad page program, 1-1-4
#define SEP_SPI_OP_READ 0x03u     // read, 1-1-1
#define SEP_SPI_OP_FAST 0x0Bu     // fast read, 1-1-1, 8 dummy clocks
#define SEP_SPI_OP_DREAD 0x3Bu    // dual output read, 1-1-2, 8 dummy clocks
#define SEP_SPI_OP_QREAD 0x6Bu    // quad output read, 1-1-4, 8 dummy clocks
#define SEP_SPI_OP_DIO_READ 0xBBu // dual I/O read, 1-2-2, 4 dummy clocks
#define SEP_SPI_OP_QIO_READ 0xEBu // quad I/O read, 1-4-4, 6 dummy clocks
#define SEP_SPI_OP_ERASE 0x20u    // 4 KiB sector erase
#define SEP_SPI_SR_WIP (1u << 0)
#define SEP_SPI_SR_WEL (1u << 1)

// COMMAND word. len is the byte count of a TX or RX segment, or the sck cycle
// count of a dummy segment; the LEN field holds len - 1.
static inline uint32_t sep_spi_cmd_word(uint32_t direction, uint32_t len, int csaat,
                                        uint32_t speed) {
    uint32_t v =
        ((direction << SPI_CONTROLLER__COMMAND__DIRECTION_bp) &
         SPI_CONTROLLER__COMMAND__DIRECTION_bm) |
        ((speed << SPI_CONTROLLER__COMMAND__SPEED_bp) & SPI_CONTROLLER__COMMAND__SPEED_bm) |
        (((len - 1u) << SPI_CONTROLLER__COMMAND__LEN_bp) & SPI_CONTROLLER__COMMAND__LEN_bm);
    if (csaat) {
        v |= SPI_CONTROLLER__COMMAND__CSAAT_bm;
    }
    return v;
}

// COMMAND.SPEED for a segment on 1, 2 or 4 lanes.
static inline uint32_t sep_spi_speed(uint32_t lanes) {
    return lanes == 4u ? SPI_CMD_SPEED_QUAD
                       : (lanes == 2u ? SPI_CMD_SPEED_DUAL : SPI_CMD_SPEED_STD);
}

// Opcode and 24-bit address in one TXDATA word. The host sends TXDATA[7:0]
// first (ByteOrder 1), so the address goes most significant byte first.
static inline uint32_t sep_spi_pack_hdr(uint32_t opcode, uint32_t addr) {
    return (opcode & 0xFFu) | (((addr >> 16) & 0xFFu) << 8) | (((addr >> 8) & 0xFFu) << 16) |
           ((addr & 0xFFu) << 24);
}

// The 24-bit address alone, most significant byte first, for an address
// segment of its own.
static inline uint32_t sep_spi_pack_addr(uint32_t addr) {
    return ((addr >> 16) & 0xFFu) | (((addr >> 8) & 0xFFu) << 8) | ((addr & 0xFFu) << 16);
}

// SPIEN and OUTPUT_EN plus control_extra (for example the watermarks), clock
// divider 9 with the CS timing above, chip select 0, error status cleared.
static inline void sep_spi_host_init(uint32_t control_extra) {
    spi_wr(SEP_TOP_SPI_CONTROLLER_CONTROL_BASE_ADDR, control_extra |
                                                         SPI_CONTROLLER__CONTROL__SPIEN_bm |
                                                         SPI_CONTROLLER__CONTROL__OUTPUT_EN_bm);
    spi_wr(SEP_TOP_SPI_CONTROLLER_CONFIGOPTS_BASE_ADDR, SPI_CFG_CLKDIV9_CSN);
    spi_wr(SEP_TOP_SPI_CONTROLLER_CSID_BASE_ADDR, 0);
    spi_wr(SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR, 0xFFFFFFFFu);
}

// Words in the RX FIFO (STATUS.RXQD).
static inline uint32_t sep_spi_rxqd(void) {
    return (spi_rd(SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR) & SPI_CONTROLLER__STATUS__RXQD_bm) >>
           SPI_CONTROLLER__STATUS__RXQD_bp;
}

// A one-byte command with no address and no data (WREN, WRDI).
static inline int sep_spi_flash_op(uint32_t opcode) {
    if (spi_wait_ready(SEP_SPI_TIMEOUT)) return -1;
    spi_wr(SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR(0), opcode & 0xFFu);
    spi_wr(SEP_TOP_SPI_CONTROLLER_COMMAND_BASE_ADDR,
           sep_spi_cmd_word(SPI_CMD_DIR_TX, 1, 0, SPI_CMD_SPEED_STD));
    return spi_wait_idle(SEP_SPI_TIMEOUT);
}

static inline int sep_spi_flash_wren(void) {
    return sep_spi_flash_op(SEP_SPI_OP_WREN);
}

// A register read: the opcode, then nbytes (1 to 4) of response on one lane.
// *out is the RXDATA word, the first byte received in bits 7:0. Returns -2 when
// the RX FIFO is empty after the command, so a timeout never reads as data.
static inline int sep_spi_flash_rdreg(uint32_t opcode, uint32_t nbytes, uint32_t *out) {
    if (spi_wait_ready(SEP_SPI_TIMEOUT)) return -1;
    spi_wr(SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR(0), opcode & 0xFFu);
    spi_wr(SEP_TOP_SPI_CONTROLLER_COMMAND_BASE_ADDR,
           sep_spi_cmd_word(SPI_CMD_DIR_TX, 1, 1, SPI_CMD_SPEED_STD)); // hold CS
    if (spi_wait_ready(SEP_SPI_TIMEOUT)) return -1;
    spi_wr(SEP_TOP_SPI_CONTROLLER_COMMAND_BASE_ADDR,
           sep_spi_cmd_word(SPI_CMD_DIR_RX, nbytes, 0, SPI_CMD_SPEED_STD)); // release CS
    if (spi_wait_idle(SEP_SPI_TIMEOUT)) return -1;
    if (sep_spi_rxqd() < 1u) return -2;
    *out = spi_rd(SEP_TOP_SPI_CONTROLLER_RXDATA_BASE_ADDR(0));
    return 0;
}

// Status register 1. A failed read is a negative return, never 0xFF: WEL is
// bit 1, so 0xFF would read as WEL set.
static inline int sep_spi_flash_rdsr(uint8_t *out) {
    uint32_t w = 0;
    int rc = sep_spi_flash_rdreg(SEP_SPI_OP_RDSR, 1, &w);
    if (rc == 0) *out = (uint8_t)(w & 0xFFu);
    return rc;
}

// Polls status register 1 until WIP clears. Returns 0, the negative return of
// a failed status read, or -3 when WIP stays set.
static inline int sep_spi_flash_wait_wip_clear(void) {
    for (int i = 0; i < SEP_SPI_TIMEOUT; i++) {
        uint8_t sr = 0;
        int rc = sep_spi_flash_rdsr(&sr);
        if (rc) return rc;
        if (!(sr & SEP_SPI_SR_WIP)) return 0;
    }
    return -3;
}

// 4 KiB sector erase: the opcode and the address, then CS released.
static inline int sep_spi_flash_erase(uint32_t addr) {
    if (spi_wait_ready(SEP_SPI_TIMEOUT)) return -1;
    spi_wr(SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR(0), sep_spi_pack_hdr(SEP_SPI_OP_ERASE, addr));
    spi_wr(SEP_TOP_SPI_CONTROLLER_COMMAND_BASE_ADDR,
           sep_spi_cmd_word(SPI_CMD_DIR_TX, 4, 0, SPI_CMD_SPEED_STD));
    return spi_wait_idle(SEP_SPI_TIMEOUT);
}

// Data lanes of a read or program opcode the helpers issue; 0 for any other.
static inline uint32_t sep_spi_flash_data_lanes(uint32_t opcode) {
    switch (opcode) {
    case SEP_SPI_OP_READ:
    case SEP_SPI_OP_FAST:
    case SEP_SPI_OP_PP:
        return 1u;
    case SEP_SPI_OP_DREAD:
    case SEP_SPI_OP_DIO_READ:
        return 2u;
    case SEP_SPI_OP_QREAD:
    case SEP_SPI_OP_QIO_READ:
    case SEP_SPI_OP_QPP:
        return 4u;
    default:
        return 0u;
    }
}

// Page program (SEP_SPI_OP_PP or SEP_SPI_OP_QPP) of nwords data words, each sent
// least significant byte first. All TXDATA words are queued before the first
// command. PP is one standard TX segment. QPP is a standard TX segment of the
// opcode and address with CS held, then a quad TX segment of the data. A TX
// segment drops the unused bytes of its last word, so each segment has its own
// words. The flash needs its write enable set first.
static inline int sep_spi_flash_program(uint32_t opcode, uint32_t addr, const uint32_t *data,
                                        uint32_t nwords) {
    if (opcode != SEP_SPI_OP_PP && opcode != SEP_SPI_OP_QPP) return -2;
    if (spi_wait_ready(SEP_SPI_TIMEOUT)) return -1;
    spi_wr(SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR(0), sep_spi_pack_hdr(opcode, addr));
    for (uint32_t i = 0; i < nwords; i++) {
        spi_wr(SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR(0), data[i]);
    }
    if (opcode == SEP_SPI_OP_PP) {
        spi_wr(SEP_TOP_SPI_CONTROLLER_COMMAND_BASE_ADDR,
               sep_spi_cmd_word(SPI_CMD_DIR_TX, 4u + nwords * 4u, 0, SPI_CMD_SPEED_STD));
    } else {
        spi_wr(SEP_TOP_SPI_CONTROLLER_COMMAND_BASE_ADDR,
               sep_spi_cmd_word(SPI_CMD_DIR_TX, 4, 1, SPI_CMD_SPEED_STD)); // hold CS
        if (spi_wait_ready(SEP_SPI_TIMEOUT)) return -1;
        spi_wr(SEP_TOP_SPI_CONTROLLER_COMMAND_BASE_ADDR,
               sep_spi_cmd_word(SPI_CMD_DIR_TX, nwords * 4u, 0, SPI_CMD_SPEED_QUAD));
    }
    return spi_wait_idle(SEP_SPI_TIMEOUT);
}

// Issues the segments of a flash read of nbytes bytes and returns once the
// last COMMAND is queued; the caller (or a DMA) drains RXDATA. The opcode sets
// the phases:
//   READ        opcode + address on 1 lane, data on 1 lane;
//   FAST        opcode + address + one zero byte (the 8 dummy clocks) on 1 lane,
//               data on 1 lane;
//   DREAD/QREAD opcode + address on 1 lane, an 8-clock dummy segment, data on
//               2/4 lanes;
//   DIO_READ/QIO_READ opcode on 1 lane, the address in its own word on 2/4
//               lanes, a 4/6-clock dummy segment, data on 2/4 lanes.
// Every segment but the last holds CS. Returns -2 for another opcode.
static inline int sep_spi_flash_read_issue(uint32_t opcode, uint32_t addr, uint32_t nbytes) {
    uint32_t addr_lanes = 1u;
    uint32_t dummy = 0u;
    switch (opcode) {
    case SEP_SPI_OP_READ:
    case SEP_SPI_OP_FAST:
        break;
    case SEP_SPI_OP_DREAD:
    case SEP_SPI_OP_QREAD:
        dummy = 8u;
        break;
    case SEP_SPI_OP_DIO_READ:
        addr_lanes = 2u;
        dummy = 4u;
        break;
    case SEP_SPI_OP_QIO_READ:
        addr_lanes = 4u;
        dummy = 6u;
        break;
    default:
        return -2;
    }
    uint32_t data_speed = sep_spi_speed(sep_spi_flash_data_lanes(opcode));
    if (spi_wait_ready(SEP_SPI_TIMEOUT)) return -1;
    if (addr_lanes == 1u) {
        uint32_t tx_len = 4u;
        spi_wr(SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR(0), sep_spi_pack_hdr(opcode, addr));
        if (opcode == SEP_SPI_OP_FAST) {
            spi_wr(SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR(0), 0); // dummy byte
            tx_len = 5u;
        }
        spi_wr(SEP_TOP_SPI_CONTROLLER_COMMAND_BASE_ADDR,
               sep_spi_cmd_word(SPI_CMD_DIR_TX, tx_len, 1, SPI_CMD_SPEED_STD));
    } else {
        spi_wr(SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR(0), opcode & 0xFFu);
        spi_wr(SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR(0), sep_spi_pack_addr(addr));
        spi_wr(SEP_TOP_SPI_CONTROLLER_COMMAND_BASE_ADDR,
               sep_spi_cmd_word(SPI_CMD_DIR_TX, 1, 1, SPI_CMD_SPEED_STD));
        if (spi_wait_ready(SEP_SPI_TIMEOUT)) return -1;
        spi_wr(SEP_TOP_SPI_CONTROLLER_COMMAND_BASE_ADDR,
               sep_spi_cmd_word(SPI_CMD_DIR_TX, 3, 1, sep_spi_speed(addr_lanes)));
    }
    if (dummy) {
        if (spi_wait_ready(SEP_SPI_TIMEOUT)) return -1;
        spi_wr(SEP_TOP_SPI_CONTROLLER_COMMAND_BASE_ADDR,
               sep_spi_cmd_word(SPI_CMD_DIR_DUMMY, dummy, 1, data_speed));
    }
    if (spi_wait_ready(SEP_SPI_TIMEOUT)) return -1;
    spi_wr(SEP_TOP_SPI_CONTROLLER_COMMAND_BASE_ADDR,
           sep_spi_cmd_word(SPI_CMD_DIR_RX, nbytes, 0, data_speed)); // release CS
    return 0;
}

// Flash read of nwords words into out, the first byte received in bits 7:0 of
// out[0] (phases as sep_spi_flash_read_issue). Returns -2 for an opcode the
// helpers do not issue and -3 when the RX FIFO holds fewer than nwords words
// at the end.
static inline int sep_spi_flash_read(uint32_t opcode, uint32_t addr, uint32_t *out,
                                     uint32_t nwords) {
    int rc = sep_spi_flash_read_issue(opcode, addr, nwords * 4u);
    if (rc) return rc;
    if (spi_wait_idle(SEP_SPI_TIMEOUT)) return -1;
    if (sep_spi_rxqd() < nwords) return -3;
    for (uint32_t i = 0; i < nwords; i++) {
        out[i] = spi_rd(SEP_TOP_SPI_CONTROLLER_RXDATA_BASE_ADDR(0));
    }
    return 0;
}

#endif // SEP_SPI_H
