/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * Polled MIPI HCI controller driver (PIO ports, DAT, DCT) for the OCCP master BFM, implementing
 * the I3C_Driver API of i3c_controller_driver.h. Controller mode only; no IBI. Without
 * I3C_USE_HCI_CORE the file is empty and a platform driver supplies these symbols.
 */
#if defined(I3C_USE_HCI_CORE)

/* The transport-agnostic driver vtable + platform hooks. */
#include "i3c_controller_driver.h"
/* read_reg / write_reg (via smc_reg_access.h). */
#include "smc_defines.h"
/* smc_addr.h supplies the wrapper base without smc_top_regs.h and its conflicting I3C types. */
#include "smc_addr.h"

#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wconversion"

/*--------------------------------------------------------------------------
 *  Addressing: an instance-N register is its instance-0 address + N * I3C_INST_STRIDE.
 *------------------------------------------------------------------------*/
#define I3C_INST_STRIDE 0x1000u
#define I3C_A(id, abs0) ((uint64_t)(abs0) + (uint64_t)(id)*I3C_INST_STRIDE)

static inline void hw(uint8_t id, uint64_t abs0, uint32_t v) {
    write_reg(I3C_A(id, abs0), v);
}
static inline uint32_t hr(uint8_t id, uint64_t abs0) {
    return read_reg(I3C_A(id, abs0));
}

/* Instance-0 register addresses (I3CCSR offsets from the wrapper base). */
#define I3C0_CSR_BASE SMC_TOP_OCA_I3C_WRAP_I3C_CSR_BASE_ADDR(0)
#define R_HC_CONTROL (I3C0_CSR_BASE + 0x004u)
#define R_RESET_CONTROL (I3C0_CSR_BASE + 0x010u)
#define RC_RX_FIFO_RST (1u << 4) /* RESET_CONTROL.RX_FIFO_RST; self-clears once RX is empty */
#define R_STBY_CR (I3C0_CSR_BASE + 0x184u)
#define R_PIO_CONTROL (I3C0_CSR_BASE + 0x0B0u)
#define R_PIO_INTR (I3C0_CSR_BASE + 0x0A0u)
#define R_PIO_INTR_SE (I3C0_CSR_BASE + 0x0A4u)
#define R_PIO_INTR_GE (I3C0_CSR_BASE + 0x0A8u)
#define R_CMD_PORT (I3C0_CSR_BASE + 0x080u)
#define R_RESP_PORT (I3C0_CSR_BASE + 0x084u)
#define R_TX_PORT (I3C0_CSR_BASE + 0x088u)
#define R_RX_PORT (I3C0_CSR_BASE + 0x088u)
#define R_DBTC (I3C0_CSR_BASE + 0x094u)
#define R_QTC (I3C0_CSR_BASE + 0x090u)
#define R_DAT_BASE (I3C0_CSR_BASE + 0x400u)
#define R_DCT_BASE (I3C0_CSR_BASE + 0x800u)
#define OCCP_DAA_DEV_COUNT 1u
/* SOC management interface bus-timing registers (open-drain init set) */
#define R_T_R (I3C0_CSR_BASE + 0x32Cu)
#define R_T_F (I3C0_CSR_BASE + 0x330u)
#define R_T_SU_DAT (I3C0_CSR_BASE + 0x334u)
#define R_T_HD_DAT (I3C0_CSR_BASE + 0x33Cu)
#define R_T_HIGH (I3C0_CSR_BASE + 0x340u)
#define R_T_HIGH_OD (I3C0_CSR_BASE + 0x344u)
#define R_T_HIGH_INIT_OD (I3C0_CSR_BASE + 0x348u)
#define R_T_LOW (I3C0_CSR_BASE + 0x350u)
#define R_T_LOW_OD (I3C0_CSR_BASE + 0x354u)
#define R_T_HD_STA (I3C0_CSR_BASE + 0x35Cu)
#define R_T_SU_STA (I3C0_CSR_BASE + 0x368u)
#define R_T_SU_STO (I3C0_CSR_BASE + 0x370u)
#define R_T_HD_RSTA (I3C0_CSR_BASE + 0x364u)
#define R_T_DS_OD (I3C0_CSR_BASE + 0x378u)
#define R_T_FREE (I3C0_CSR_BASE + 0x37Cu)
#define R_T_AVAL (I3C0_CSR_BASE + 0x384u)
#define R_T_IDLE (I3C0_CSR_BASE + 0x388u)

/*--------------------------------------------------------------------------
 *  Field positions (vendor/chipsalliance/i3c-core/upstream/src/csr/I3CCSR_pkg.sv)
 *------------------------------------------------------------------------*/
#define HC_BUS_ENABLE (1u << 31)
#define HC_MODE_PIO (1u << 6)                       /* mode_selector = 1 (PIO) */
#define STBYCR_ENABLE_INIT(v) ((uint32_t)(v) << 30) /* 1 ACM_INIT, 3 SCM_HOT_JOIN */
#define STBYCR_TARGET_XACT (1u << 12)
#define PIO_EN (1u << 0)
#define PIO_RS (1u << 1)
/* PIO_INTR_STATUS bits (same layout as PIO_INTR_STATUS_ENABLE) */
#define PI_TX_THLD (1u << 0)
#define PI_RX_THLD (1u << 1)
#define PI_CMD_QUEUE_READY (1u << 3)
#define PI_RESP_READY (1u << 4)
/* DATA_BUFFER_THLD_CTRL / QUEUE_THLD_CTRL field shifts */
#define DBTC_TX_BUF_SHIFT 0
#define DBTC_RX_BUF_SHIFT 8
/* TX_START_THLD[18:16] / RX_START_THLD[26:24]: a write waits for 2^(N+1) queued TX DWORDs and a
 * read for 2^(N+1) DWORDs of RX room, or for the whole transfer if smaller. */
#define DBTC_TX_START_SHIFT 16
#define DBTC_RX_START_SHIFT 24
#define QTC_CMD_EMPTY_SHIFT 0
#define QTC_RESP_BUF_SHIFT 8

/* RESPONSE_PORT descriptor decode */
#define RESP_ERR(r) (((r) >> 28) & 0xFu)
#define RESP_LEN(r) ((r)&0xFFFFu)

/* RESPONSE err_status values (i3c_resp_err_status_e) that the read path handles specially. */
#define HCI_RESP_NACK 0x5u       /* target NACK'ed the read (e.g. TX not yet armed) */
#define HCI_RESP_SHORT_READ 0x7u /* target ended the read early; expected for an over-read */

/* Commanded length of the OCCP response read (MRL + 1). The target ends the read at its real
 * length, so one bus transaction delivers the whole response and the header and body reads
 * drain one RX FIFO with no STOP between them. */
#define HCI_OVERREAD_LEN 2081u

/* Controller half only; the target (TTI) half is in the boot ROM's i3c_hci_driver.c. */

/* Command-descriptor (cmd_lo) attribute field [2:0] */
#define ATTR_REGULAR 0x0u     /* regular transfer (data in TX/RX data port) */
#define ATTR_IMMEDIATE 0x1u   /* immediate data transfer (<=4 B in cmd_hi) */
#define ATTR_ADDR_ASSIGN 0x2u /* address-assignment CCC (e.g. SETDASA) */
/* cmd_lo bit fields */
#define CMD_RNW (1u << 29)
#define CMD_WROC (1u << 30)
#define CMD_TOC (1u << 31)
/* DWORD0[24] SRE: report a target-terminated short read as a RESPONSE; without it an over-read
 * never completes. */
#define CMD_SRE (1u << 24)
#define CMD_DEVIDX(i) (((uint32_t)(i)&0x1Fu) << 16)
#define CMD_CCC(c) (((uint32_t)(c)&0xFFu) << 7)
#define CMD_DTT(n) (((uint32_t)(n)&0x7u) << 23)      /* immediate byte count */
#define CMD_DEVCOUNT(n) (((uint32_t)(n)&0xFu) << 26) /* addr-assign dev_count @ DWORD0[29:26] */

#define I3C_POLL_LIMIT 2000000u /* generous busy-poll bound for ROM */
#define I3C_FIFO_WORD 4u

typedef union {
    uint32_t word;
    uint8_t bytes[4];
} i3c_word_u;

/*--------------------------------------------------------------------------
 *  Wait for a command's RESPONSE_PORT and decode the error.
 *------------------------------------------------------------------------*/
static I3C_Status hci_wait_response(uint8_t id, uint32_t *resp_out) {
    simputshex16("[I3C_HCI] Waiting for response on controller: ", id);
    for (uint32_t i = 0; i < I3C_POLL_LIMIT; i++) {
        if (hr(id, R_PIO_INTR) & PI_RESP_READY) {
            uint32_t resp = hr(id, R_RESP_PORT);
            simputshex32("[I3C_HCI] Response descriptor: ", resp);
            if (resp_out) {
                *resp_out = resp;
            }
            if (RESP_ERR(resp) != 0u) {
                decode_cmdr_error((uint8_t)RESP_ERR(resp));
                return I3C_ERR_CMD_FAILED;
            }
            return I3C_OK;
        }
    }
    simputs("[I3C_HCI] Response wait timed out\n");
    return I3C_ERR_TIMEOUT;
}

/* HCI has one response queue and no command ID, so command_id and timeout are ignored; the wait
 * is bounded by I3C_POLL_LIMIT. */
static I3C_Status wait_command(I3C_Driver *drv, uint8_t command_id, uint32_t timeout) {
    (void)command_id;
    (void)timeout;
    if (drv == NULL || !drv->ctx.initialized) {
        return I3C_ERR_HW;
    }
    return hci_wait_response(drv->ctx.controller_id, NULL);
}

/* The wrapper has no reset or enable register: rst_ni follows the SMC primary reset. */
void i3c_release_reset(uint8_t i3c_controller) {
    (void)i3c_controller;
}

/*--------------------------------------------------------------------------
 *  cfg_ps: no-op; the HCI controller has no pin-strap configuration.
 *------------------------------------------------------------------------*/
void cfg_ps(uint8_t i3c_controller, uint8_t device_id, I3C_Role role) {
    (void)i3c_controller;
    (void)device_id;
    (void)role;
}

/*--------------------------------------------------------------------------
 *  init_i3c_ctrl only releases reset; I3C_Start does the controller bring-up.
 *------------------------------------------------------------------------*/
void init_i3c_ctrl(uint8_t controller_id, uint64_t device_id, I3C_Role role) {
    (void)device_id;
    (void)role;
    i3c_release_reset(controller_id);
}

static I3C_Status I3C_Init(I3C_Driver *drv, uint8_t controller_id, uint64_t device_id,
                           I3C_Role role) {
    if (drv == NULL || controller_id >= I3C_NUM_CONTROLLERS) {
        return I3C_ERR_INVALID_ARG;
    }
    drv->ctx.role = role;
    drv->ctx.controller_id = controller_id;
    init_i3c_ctrl(controller_id, device_id, role);
    drv->ctx.initialized = true;
    return I3C_OK;
}

/*--------------------------------------------------------------------------
 *  Open-drain bus timing, in i3c-core clock cycles; required before the controller drives SCL.
 *------------------------------------------------------------------------*/
static void hci_program_od_timing(uint8_t id) {
    hw(id, R_T_R, 0);
    hw(id, R_T_F, 0);
    hw(id, R_T_SU_DAT, 2);
    hw(id, R_T_HD_DAT, 2);
    /* OD SCL high/low are 8 cycles (the cocotb API uses 20-70) so ENTDAA runs several times
     * faster in simulation; 8 still exceeds SU_DAT/HD_DAT = 2, and the target tracks it. */
    hw(id, R_T_HIGH, 14);
    hw(id, R_T_HIGH_OD, 8);
    hw(id, R_T_HIGH_INIT_OD, 8);
    hw(id, R_T_LOW, 14);
    hw(id, R_T_LOW_OD, 8);
    hw(id, R_T_HD_STA, 13);
    hw(id, R_T_SU_STA, 9);
    hw(id, R_T_SU_STO, 8);
    hw(id, R_T_HD_RSTA, 9);
    hw(id, R_T_DS_OD, 24);
    hw(id, R_T_FREE, 13);
    hw(id, R_T_AVAL, 40);
    hw(id, R_T_IDLE, 66600);
}

/*--------------------------------------------------------------------------
 *  Controller bring-up (polled; no interrupt signals are enabled).
 *------------------------------------------------------------------------*/
static I3C_Status I3C_Start(I3C_Driver *drv, int sys_clk_freq) {
    (void)sys_clk_freq; /* API parity; HCI uses fixed boot-time bus timing */
    if (!drv->ctx.initialized) {
        return I3C_ERR_HW;
    }
    uint8_t id = drv->ctx.controller_id;

    hw(id, R_HC_CONTROL, HC_BUS_ENABLE | HC_MODE_PIO);

    /* ENABLE_INIT 1 or 3 with BUS_ENABLE makes the core the active controller. */
    hw(id, R_STBY_CR, STBYCR_ENABLE_INIT(3u) | STBYCR_TARGET_XACT);

    /* Status enables make PIO_INTR_STATUS report the events this driver polls. */
    hw(id, R_PIO_INTR_SE, PI_TX_THLD | PI_RX_THLD | PI_RESP_READY | PI_CMD_QUEUE_READY);

    hci_program_od_timing(id);

    /* START thresholds make a write wait for queued TX data and a read for RX room, so command and
     * data enqueue order cannot race. N means 2^(N+1) DWORDs (N=2: 8), or the whole transfer if
     * smaller; 2^(N+1) above the 64-DWORD queue wraps to 0 and disables the gate. */
    hw(id, R_DBTC,
       (1u << DBTC_TX_BUF_SHIFT) | (1u << DBTC_RX_BUF_SHIFT) | (2u << DBTC_TX_START_SHIFT) |
           (2u << DBTC_RX_START_SHIFT));
    hw(id, R_QTC, (1u << QTC_CMD_EMPTY_SHIFT) | (1u << QTC_RESP_BUF_SHIFT));

    hw(id, R_PIO_CONTROL, PIO_EN | PIO_RS);
    return I3C_OK;
}

/*--------------------------------------------------------------------------
 *  DAT entry: controller transfers address a target by DAT index, not by address.
 *------------------------------------------------------------------------*/
/* ibi_payload must match the target's BCR[2]; with it clear, the controller aborts a payload IBI
 * after the address. BCR is known only after ENTDAA, so I3C_ProcessDevices rewrites the entry. */
static void set_dat_entry(uint8_t id, uint8_t idx, uint8_t static_addr, uint8_t dynamic_addr,
                          uint8_t ibi_payload) {
    uint32_t dat_lo = ((uint32_t)(static_addr & 0x7Fu)) | (((uint32_t)(ibi_payload & 0x1u)) << 12) |
                      (((uint32_t)(dynamic_addr & 0x7Fu)) << 16);
    write_reg(I3C_A(id, R_DAT_BASE) + (uint64_t)idx * 8u, dat_lo);
    write_reg(I3C_A(id, R_DAT_BASE) + (uint64_t)idx * 8u + 4u, 0u);
}

/*--------------------------------------------------------------------------
 *  SETDASA: assign a dynamic address to a target that has a static address.
 *------------------------------------------------------------------------*/
static I3C_Status hci_setdasa(I3C_Driver *drv, uint8_t static_addr, uint8_t dynamic_addr,
                              uint8_t dat_idx) {
    uint8_t id = drv->ctx.controller_id;
    /* SETDASA does not read BCR; default IBI_PAYLOAD=0. If a SETDASA target needs payload IBIs,
     * issue GETBCR and rewrite the DAT entry with set_dat_entry(...,(bcr>>2)&1) afterward. */
    set_dat_entry(id, dat_idx, static_addr, dynamic_addr, 0u);
    uint32_t cmd_lo =
        ATTR_ADDR_ASSIGN | CMD_CCC(0x87u) | CMD_DEVIDX(dat_idx) | (1u << 26) | CMD_WROC | CMD_TOC;
    hw(id, R_CMD_PORT, cmd_lo);
    hw(id, R_CMD_PORT, 0u); /* cmd_hi */
    return hci_wait_response(id, NULL);
}

/*--------------------------------------------------------------------------
 *  SETGRPA: immediate-data CCC to the DAT index 0 target; the group address is the operand.
 *------------------------------------------------------------------------*/
static I3C_Status I3C_IssueSETGRPA(I3C_Driver *drv, uint8_t da, uint8_t group_addr) {
    if (!drv->ctx.initialized) {
        return I3C_ERR_HW;
    }
    uint8_t id = drv->ctx.controller_id;
    uint32_t cmd_lo =
        ATTR_IMMEDIATE | CMD_CCC(CCC_SETGRPA) | CMD_DEVIDX(0u) | CMD_DTT(1u) | CMD_WROC | CMD_TOC;
    uint32_t cmd_hi = (uint32_t)(group_addr << 1); /* operand byte 0 */
    (void)da; /* address comes from the DAT entry for dev_idx */
    hw(id, R_CMD_PORT, cmd_lo);
    hw(id, R_CMD_PORT, cmd_hi);
    return hci_wait_response(id, NULL);
}

/*--------------------------------------------------------------------------
 *  ENTDAA + DCT discovery, implemented to the MIPI HCI model.
 *------------------------------------------------------------------------*/
static I3C_Status I3C_IssueENTDAA(I3C_Driver *drv) {
    if (!drv->ctx.initialized) {
        return I3C_ERR_HW;
    }
    uint8_t id = drv->ctx.controller_id;

    /* DAA assigns each responding target the dynamic address preloaded in DAT[i], or 0 without a
     * preload. dev_count must equal the number of targets: extra rounds end with SDA held low and
     * no STOP, so the next transfer cannot START. The OCCP bus has one target. */
    for (uint8_t i = 0; i < OCCP_DAA_DEV_COUNT; i++) {
        /* IBI_PAYLOAD=0 here; it is rewritten from the discovered BCR[2] in I3C_ProcessDevices. */
        set_dat_entry(id, i, 0u, (uint8_t)(0x08u + i), 0u);
    }

    /* AddrAssign descriptor: dev_count in DWORD0[29:26] (DWORD1 is reserved), wroc+toc set.
     * flow_active.sv returns NotSupported(0xA) if dev_count==0 | ~wroc | ~toc. */
    uint32_t cmd_lo = ATTR_ADDR_ASSIGN | CMD_CCC(0x07u) | CMD_DEVIDX(0u) |
                      CMD_DEVCOUNT(OCCP_DAA_DEV_COUNT) | CMD_WROC | CMD_TOC;
    simputshex32("[I3C_HCI] ENTDAA command descriptor: ", cmd_lo);
    hw(id, R_CMD_PORT, cmd_lo);
    hw(id, R_CMD_PORT, 0u); /* DWORD1 reserved */
    /* Issue only: the caller's wait_command() consumes the single DAA RESPONSE. */
    return I3C_OK;
}

static I3C_Status I3C_ProcessDevices(I3C_Driver *drv, I3C_DeviceInfo *devices, size_t max_devices) {
    if (!drv->ctx.initialized) {
        return I3C_ERR_HW;
    }
    uint8_t id = drv->ctx.controller_id;
    /* The OCCP layer takes the target from entry [1]; entry [0] stands for the controller. */
    I3C_DeviceInfo self = {0};
    self.controller_id = id;
    self.active = true;
    drv->ctx.discovered_devices[0] = self;
    if (devices && max_devices > 0) {
        devices[0] = self;
    }
    drv->ctx.num_devices = 1;
    /* DCT entry = 4 words: [PID_HI][PID_LO][BCR/DCR][dynamic_addr] (MIPI HCI). ENTDAA writes
     * exactly OCCP_DAA_DEV_COUNT entries; the remaining SRAM entries have no reset value. */
    for (uint8_t i = 0; i < OCCP_DAA_DEV_COUNT; i++) {
        uint64_t e = I3C_A(id, R_DCT_BASE) + (uint64_t)i * 16u;
        uint32_t w3 = read_reg(e + 12u);
        /* DCT word3 = entry bits[127:96]; dct_entry_t.dynamic_address in controller_pkg.sv is
         * bits[103:96] = word3[7:0] = {7-bit DA, parity}, so the DA is word3[7:1]. */
        uint8_t dyn = (uint8_t)((w3 >> 1) & 0x7Fu);
        simputshex16("[I3C_HCI] DCT index: ", i);
        simputshex32("[I3C_HCI] DCT word 3: ", w3);
        simputshex16("[I3C_HCI] DCT dynamic address: ", dyn);
        if (dyn == 0u) {
            continue;
        }
        uint32_t w0 = read_reg(e + 0u);
        uint32_t w1 = read_reg(e + 4u);
        uint32_t w2 = read_reg(e + 8u);
        I3C_DeviceInfo *info = &drv->ctx.discovered_devices[drv->ctx.num_devices];
        info->controller_id = id;
        info->dynamic_addr = dyn;
        info->pid = ((uint64_t)w0 << 16) | (uint64_t)(w1 & 0xFFFFu);
        info->bcr = (uint8_t)((w2 >> 8) & 0xFFu);
        info->dcr = (uint8_t)(w2 & 0xFFu);
        /* Program DAT.IBI_PAYLOAD from BCR[2] now that BCR is known. DAT index equals DCT index
         * because ENTDAA assigns the preloaded DAT entries in order. */
        set_dat_entry(id, i, 0u, dyn, (uint8_t)((info->bcr >> 2) & 0x1u));
        info->active = true;
        if (devices && drv->ctx.num_devices < max_devices) {
            devices[drv->ctx.num_devices] = *info;
        }
        drv->ctx.num_devices++;
    }
    if (drv->ctx.num_devices < 2) {
        simputs("No devices found\n");
        return I3C_ERR_NO_DEVICES;
    }
    return I3C_OK;
}

/*--------------------------------------------------------------------------
 *  Private write: regular descriptor (length in cmd_hi[31:16]), TX payload, then RESPONSE.
 *------------------------------------------------------------------------*/
static void hci_overread_reap(uint8_t id); /* defined with the over-read machinery below */

static I3C_Status hci_write_xfer(I3C_Driver *drv, uint8_t dat_idx, const uint8_t *data,
                                 size_t length) {
    uint8_t id = drv->ctx.controller_id;

    /* A write starts a NEW transaction: claim any over-read RESPONSE still in flight first,
     * or this write would pair with the stale response (see hci_overread_reap). */
    hci_overread_reap(id);

    /* wait for command-queue space */
    for (uint32_t i = 0; i < I3C_POLL_LIMIT; i++) {
        if (hr(id, R_PIO_INTR) & PI_CMD_QUEUE_READY) {
            break;
        }
    }

    uint32_t cmd_lo = ATTR_REGULAR | CMD_DEVIDX(dat_idx) | CMD_WROC | CMD_TOC;
    uint32_t cmd_hi = (uint32_t)length << 16;
    hw(id, R_CMD_PORT, cmd_lo);
    hw(id, R_CMD_PORT, cmd_hi);

    /* Push the payload right after the command; the START threshold holds the write until
     * enough TX data is queued, and back-pressure paces anything beyond the FIFO. */
    size_t written = 0;
    while (written < length) {
        i3c_word_u w;
        w.word = 0;
        size_t rem = length - written;
        size_t n = (rem > I3C_FIFO_WORD) ? I3C_FIFO_WORD : rem;
        for (size_t b = 0; b < n; b++) {
            w.bytes[b] = data[written + b];
        }
        hw(id, R_TX_PORT, w.word);
        written += n;
        /* Every 128 bytes, wait until at least 4 TX DWORDs are free (TX_BUF_THLD=1). */
        if ((written & 0x7Fu) == 0u && written < length) {
            for (uint32_t s = 0; s < I3C_POLL_LIMIT; s++) {
                uint32_t st = hr(id, R_PIO_INTR);
                if (st & (PI_TX_THLD | PI_RESP_READY)) {
                    break;
                }
            }
        }
    }

    uint32_t resp = 0;
    for (uint32_t i = 0; i < I3C_POLL_LIMIT; i++) {
        if (hr(id, R_PIO_INTR) & PI_RESP_READY) {
            resp = hr(id, R_RESP_PORT);
            break;
        }
    }
    if (RESP_ERR(resp) != 0u) {
        decode_cmdr_error((uint8_t)RESP_ERR(resp));
        return I3C_ERR_CMD_FAILED;
    }
    return I3C_OK;
}

/*--------------------------------------------------------------------------
 *  Private read: regular read descriptor; RESPONSE data_length is the received byte count.
 *------------------------------------------------------------------------*/
static I3C_Status hci_read_xfer(I3C_Driver *drv, uint8_t dat_idx, uint8_t *buffer, size_t length,
                                size_t *got) {
    uint8_t id = drv->ctx.controller_id;

    /* New command: claim any over-read RESPONSE still in flight first (see hci_overread_reap). */
    hci_overread_reap(id);

    for (uint32_t i = 0; i < I3C_POLL_LIMIT; i++) {
        if (hr(id, R_PIO_INTR) & PI_CMD_QUEUE_READY) {
            break;
        }
    }

    uint32_t cmd_lo = ATTR_REGULAR | CMD_DEVIDX(dat_idx) | CMD_RNW | CMD_WROC | CMD_TOC;
    uint32_t cmd_hi = (uint32_t)length << 16;
    hw(id, R_CMD_PORT, cmd_lo);
    hw(id, R_CMD_PORT, cmd_hi);

    /* Drain RX while waiting for the RESPONSE, then read only its data_length bytes: a short or
     * NACKed read leaves the RX FIFO empty, and reading an empty RX_PORT stalls the AXI read. */
    size_t read = 0;
    uint32_t resp = 0;
    for (uint32_t spin = 0; spin < I3C_POLL_LIMIT; spin++) {
        uint32_t st = hr(id, R_PIO_INTR);
        if ((st & PI_RX_THLD) && (read < length)) {
            i3c_word_u w;
            w.word = hr(id, R_RX_PORT);
            size_t rem = length - read;
            size_t n = (rem > I3C_FIFO_WORD) ? I3C_FIFO_WORD : rem;
            for (size_t b = 0; b < n; b++) {
                buffer[read + b] = w.bytes[b];
            }
            read += n;
        }
        if (st & PI_RESP_READY) {
            resp = hr(id, R_RESP_PORT);
            break;
        }
    }

    /* Drain the bytes the RESPONSE reports that the loop above has not read yet. */
    size_t actual = RESP_LEN(resp);
    if (actual > length) {
        actual = length;
    }
    while (read < actual) {
        i3c_word_u w;
        w.word = hr(id, R_RX_PORT);
        size_t rem = actual - read;
        size_t n = (rem > I3C_FIFO_WORD) ? I3C_FIFO_WORD : rem;
        for (size_t b = 0; b < n; b++) {
            buffer[read + b] = w.bytes[b];
        }
        read += n;
    }
    if (got) {
        *got = read;
    }
    if (RESP_ERR(resp) != 0u) {
        /* Flush the junk word a NACKed read leaves in the controller RX FIFO so the next retry's
         * real data lands at the front of the FIFO. Flush ONLY on error. */
        hw(id, R_RESET_CONTROL, RC_RX_FIFO_RST);
        hw(id, R_RESET_CONTROL, 0u);
        decode_cmdr_error((uint8_t)RESP_ERR(resp));
        return I3C_ERR_CMD_FAILED;
    }
    return I3C_OK;
}

/*--------------------------------------------------------------------------
 *  Public API: da is ignored; every transfer uses DAT index 0 (single-target bus).
 *------------------------------------------------------------------------*/
static I3C_Status I3C_Write(I3C_Driver *drv, uint8_t da, const uint8_t *data, size_t length) {
    if (!drv->ctx.initialized) {
        return I3C_ERR_HW;
    }
    (void)da;
    return hci_write_xfer(drv, 0u, data, length);
}

/*--------------------------------------------------------------------------
 *  OCCP response read. The OCCP layer calls read() for the header and then the body, but the
 *  target has one TX descriptor and NACKs a second bus read, so one over-read is drained across
 *  calls; g_rx_stage keeps the unread bytes of a partly consumed FIFO word between calls.
 *------------------------------------------------------------------------*/
static uint16_t g_rx_fifo_bytes[I3C_NUM_CONTROLLERS]; /* response bytes still in the HW RX FIFO   */
static uint8_t g_rx_stage[I3C_NUM_CONTROLLERS][4];    /* leftover bytes of a partly-consumed word */
static uint8_t g_rx_stage_len[I3C_NUM_CONTROLLERS];
static uint8_t g_rx_stage_pos[I3C_NUM_CONTROLLERS];

/* Over-read state: an over-read is IN FLIGHT between command issue and the RESPONSE descriptor.
 * While in flight the total byte count is unknown; the drain loop in I3C_Read pops words as they
 * arrive and g_rx_consumed tracks them so the post-RESPONSE remainder can be computed. */
static bool g_rx_inflight[I3C_NUM_CONTROLLERS];
static uint16_t g_rx_consumed[I3C_NUM_CONTROLLERS];

/* I3C_Read can return before the over-read's RESPONSE arrives. Claim it and record the unread
 * byte count before any new command, or that command pairs with the stale RESPONSE. */
static void hci_overread_reap(uint8_t id) {
    if (!g_rx_inflight[id]) {
        return;
    }
    uint32_t resp = 0;
    for (uint32_t i = 0; i < I3C_POLL_LIMIT; i++) {
        uint32_t st = hr(id, R_PIO_INTR);
        if (st & PI_RESP_READY) {
            resp = hr(id, R_RESP_PORT);
            break;
        }
        if (st & PI_RX_THLD) { /* keep draining so a still-streaming transfer completes */
            (void)hr(id, R_RX_PORT);
            g_rx_consumed[id] += (uint16_t)I3C_FIFO_WORD;
        }
    }
    g_rx_inflight[id] = false;
    uint8_t err = (uint8_t)RESP_ERR(resp);
    if (err != 0u && err != HCI_RESP_SHORT_READ) {
        hw(id, R_RESET_CONTROL, RC_RX_FIFO_RST);
        hw(id, R_RESET_CONTROL, 0u);
        g_rx_fifo_bytes[id] = 0u;
        g_rx_consumed[id] = 0u;
        return;
    }
    uint16_t total = (uint16_t)RESP_LEN(resp);
    g_rx_fifo_bytes[id] = (total > g_rx_consumed[id]) ? (uint16_t)(total - g_rx_consumed[id]) : 0u;
    g_rx_consumed[id] = 0u;
}

/* Issue one over-read and return at once. I3C_Read drains RX during the transfer, so a response
 * larger than the 64-DWORD RX queue does not overflow it; the RESPONSE arrives at the end. */
static I3C_Status hci_overread_start(uint8_t id) {
    for (uint32_t i = 0; i < I3C_POLL_LIMIT; i++) {
        if (hr(id, R_PIO_INTR) & PI_CMD_QUEUE_READY) {
            break;
        }
    }
    /* CMD_SRE: the over-read commands HCI_OVERREAD_LEN but the target ends early (end-of-data); SRE
     * makes the core emit a RESPONSE for that short read instead of silently returning to Idle. */
    uint32_t cmd_lo = ATTR_REGULAR | CMD_DEVIDX(0u) | CMD_RNW | CMD_SRE | CMD_WROC | CMD_TOC;
    uint32_t cmd_hi = (uint32_t)HCI_OVERREAD_LEN << 16;
    hw(id, R_CMD_PORT, cmd_lo);
    hw(id, R_CMD_PORT, cmd_hi);

    g_rx_inflight[id] = true;
    g_rx_consumed[id] = 0u;
    g_rx_fifo_bytes[id] = 0u;
    g_rx_stage_len[id] = 0u;
    g_rx_stage_pos[id] = 0u;
    return I3C_OK;
}

static I3C_Status I3C_Read(I3C_Driver *drv, uint8_t da, uint8_t *buffer, size_t length) {
    if (!drv->ctx.initialized) {
        return I3C_ERR_HW;
    }
    (void)da;
    uint8_t id = drv->ctx.controller_id;
    size_t out = 0;

    /* Fresh transaction (nothing buffered, nothing in flight): launch the over-read. */
    if (!g_rx_inflight[id] && g_rx_stage_pos[id] >= g_rx_stage_len[id] &&
        g_rx_fifo_bytes[id] == 0u) {
        I3C_Status st = hci_overread_start(id);
        if (st != I3C_OK) {
            return st;
        }
    }

    /* 1. Serve staged bytes left from a partly consumed word. */
    while (out < length && g_rx_stage_pos[id] < g_rx_stage_len[id]) {
        buffer[out++] = g_rx_stage[id][g_rx_stage_pos[id]++];
    }
    if (out < length) {
        g_rx_stage_len[id] = 0u;
        g_rx_stage_pos[id] = 0u;
    }

    /* 2. While the over-read is in flight, pop whole words as they arrive so the RX queue cannot
     * overflow. PI_RX_THLD asserts at >= 4 entries (N=1), so a pop never takes the final, possibly
     * partial word; step 3 reads that with the RESPONSE's exact count. */
    while (out < length && g_rx_inflight[id]) {
        uint32_t spin;
        for (spin = 0; spin < I3C_POLL_LIMIT; spin++) {
            uint32_t st = hr(id, R_PIO_INTR);
            if (st & PI_RESP_READY) {
                /* Transfer complete: total is now known; leave the tail to step 3. */
                uint32_t resp = hr(id, R_RESP_PORT);
                uint8_t err = (uint8_t)RESP_ERR(resp);
                g_rx_inflight[id] = false;
                if (err != 0u && err != HCI_RESP_SHORT_READ) {
                    /* NACK (target TX not armed) or error: flush RX; the OCCP layer retries. */
                    hw(id, R_RESET_CONTROL, RC_RX_FIFO_RST);
                    hw(id, R_RESET_CONTROL, 0u);
                    g_rx_consumed[id] = 0u;
                    if (err != HCI_RESP_NACK) {
                        decode_cmdr_error(err);
                    }
                    return I3C_ERR_CMD_FAILED;
                }
                uint16_t total = (uint16_t)RESP_LEN(resp);
                g_rx_fifo_bytes[id] =
                    (total > g_rx_consumed[id]) ? (uint16_t)(total - g_rx_consumed[id]) : 0u;
                g_rx_consumed[id] = 0u;
                break;
            }
            if (st & PI_RX_THLD) {
                /* RX threshold reached: this word has 4 valid bytes (see step 2). */
                i3c_word_u w;
                w.word = hr(id, R_RX_PORT);
                g_rx_consumed[id] += (uint16_t)I3C_FIFO_WORD;
                for (uint8_t b = 0; b < I3C_FIFO_WORD; b++) {
                    if (out < length) {
                        buffer[out++] = w.bytes[b];
                    } else {
                        g_rx_stage[id][g_rx_stage_len[id]++] = w.bytes[b];
                    }
                }
                break;
            }
        }
        if (spin >= I3C_POLL_LIMIT) {
            g_rx_inflight[id] = false;
            g_rx_consumed[id] = 0u;
            return I3C_ERR_TIMEOUT;
        }
        if (out >= length && g_rx_inflight[id]) {
            /* Caller satisfied while the transfer is still streaming (e.g. the 8-byte OCCP header
             * read of a large response): keep the flight open for the next I3C_Read call. */
            return I3C_OK;
        }
    }

    /* 3. Post-RESPONSE: pop the known remainder (handles the final partial word + staging). */
    while (out < length && g_rx_fifo_bytes[id] > 0u) {
        i3c_word_u w;
        w.word = hr(id, R_RX_PORT);
        uint8_t valid = (g_rx_fifo_bytes[id] >= I3C_FIFO_WORD) ? (uint8_t)I3C_FIFO_WORD
                                                               : (uint8_t)g_rx_fifo_bytes[id];
        g_rx_fifo_bytes[id] -= valid;
        for (uint8_t b = 0; b < valid; b++) {
            if (out < length) {
                buffer[out++] = w.bytes[b];
            } else {
                g_rx_stage[id][g_rx_stage_len[id]++] = w.bytes[b];
            }
        }
    }

    return (out == length) ? I3C_OK : I3C_ERR_CMD_FAILED;
}

/* fifo_write/fifo_read: thin shims over the transfer helpers (HCI has no
 * separately-addressable FIFO outside a command). */
static I3C_Status fifo_write(I3C_Driver *drv, const uint8_t *data, size_t length) {
    if (drv == NULL || !drv->ctx.initialized) {
        return I3C_ERR_HW;
    }
    return hci_write_xfer(drv, 0u, data, length);
}

static I3C_Status fifo_read(I3C_Driver *drv, uint8_t *buffer, size_t length, size_t *bytes_read) {
    if (drv == NULL || !drv->ctx.initialized || buffer == NULL) {
        return I3C_ERR_HW;
    }
    return hci_read_xfer(drv, 0u, buffer, length, bytes_read);
}

static I3C_Status I3C_SendPayload(I3C_Driver *drv, const uint8_t addr, const uint8_t *data,
                                  size_t length) {
    if (drv == NULL || !drv->ctx.initialized) {
        return I3C_ERR_HW;
    }
    (void)addr;
    return hci_write_xfer(drv, 0u, data, length);
}

static I3C_Status I3C_SendPayloadStream(I3C_Driver *drv, const uint8_t addr, const uint8_t *data,
                                        size_t length) {
    return I3C_SendPayload(drv, addr, data, length);
}

static uint32_t I3C_CheckRxFifo(I3C_Driver *drv) {
    if (drv == NULL || !drv->ctx.initialized) {
        return 0;
    }
    uint8_t id = drv->ctx.controller_id;
    /* Reports only whether RX reached its threshold, not the exact level. */
    return (hr(id, R_PIO_INTR) & PI_RX_THLD) ? 1u : 0u;
}

static I3C_Status I3C_ReceivePayload(I3C_Driver *drv, uint8_t *buffer, size_t buffer_length,
                                     size_t *bytes_received) {
    if (drv == NULL || !drv->ctx.initialized || buffer == NULL) {
        return I3C_ERR_HW;
    }
    return hci_read_xfer(drv, 0u, buffer, buffer_length, bytes_received);
}

static I3C_Status I3C_ReceivePayloadStream(I3C_Driver *drv, uint8_t *buffer, size_t buffer_length,
                                           size_t *bytes_received) {
    return I3C_ReceivePayload(drv, buffer, buffer_length, bytes_received);
}

/*--------------------------------------------------------------------------
 *  Driver instance factory.
 *------------------------------------------------------------------------*/
I3C_Driver *I3C_GetDriverInstance(uint8_t controller_id) {
    static I3C_Driver instances[I3C_NUM_CONTROLLERS];
    static bool initialized[I3C_NUM_CONTROLLERS] = {false};

    if (controller_id >= I3C_NUM_CONTROLLERS) {
        return NULL;
    }
    I3C_Driver *drv = &instances[controller_id];

    if (!initialized[controller_id]) {
        drv->init = I3C_Init;
        drv->start = I3C_Start;
        drv->issue_entdaa = I3C_IssueENTDAA;
        drv->issue_setgrpa = I3C_IssueSETGRPA;
        drv->wait_command = wait_command;
        drv->process_devices = I3C_ProcessDevices;
        drv->write = I3C_Write;
        drv->read = I3C_Read;
        drv->fifo_write = fifo_write;
        drv->fifo_read = fifo_read;
        drv->send_payload = I3C_SendPayload;
        drv->send_payload_stream = I3C_SendPayloadStream;
        drv->check_rx_fifo = I3C_CheckRxFifo;
        drv->receive_payload = I3C_ReceivePayload;
        drv->receive_payload_stream = I3C_ReceivePayloadStream;
        initialized[controller_id] = true;
    }
    return drv;
}

/* Keeps hci_setdasa linked for -Wunused-function; nothing calls it through this pointer yet. */
I3C_Status (*const i3c_hci_setdasa_ref)(I3C_Driver *, uint8_t, uint8_t, uint8_t) = hci_setdasa;

#pragma GCC diagnostic pop

#endif /* I3C_USE_HCI_CORE */
