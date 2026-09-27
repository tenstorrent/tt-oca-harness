/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*============================================================================
 *  i3c_controller_driver.c — master_bfm / tests_rom HCI (OCA i3c-core) driver.
 *
 *  Controller-mode driver for the MIPI HCI programming model (PIO command /
 *  response / data ports + DAT + DCT), implementing the transport-agnostic
 *  I3C_Driver API declared in i3c_controller_driver.h. The whole file is gated
 *  by I3C_USE_HCI_CORE, so a build that leaves it undefined supplies these
 *  symbols from a platform driver instead.
 *
 *  Lives in common/ (linked ONLY by the tests_rom/master build, not prod_rom).
 *
 *  Controller mode only, polled (no IBI).
 *==========================================================================*/
#if defined(I3C_USE_HCI_CORE)

/* The transport-agnostic driver vtable + platform hooks. */
#include "i3c_controller_driver.h"
/* read_reg / write_reg (via smc_reg_access.h). */
#include "smc_defines.h"
/* Only the wrapper base address is needed here; smc_addr.h supplies it without
 * the I3C register types of the boot ROM's smc_top_regs.h. */
#include "smc_addr.h"

#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wconversion"

/*--------------------------------------------------------------------------
 *  Addressing. The I3CCSR block starts at the wrap base (CSR sub-offset 0);
 *  instance 1 is instance 0 + 0x1000. So any instance-N register =
 *  <instance-0 absolute addr from smc_top_regs.h> + N*0x1000.
 *------------------------------------------------------------------------*/
#define I3C_INST_STRIDE 0x1000u
#define I3C_A(id, abs0) ((uint64_t)(abs0) + (uint64_t)(id)*I3C_INST_STRIDE)

static inline void hw(uint8_t id, uint64_t abs0, uint32_t v) {
    write_reg(I3C_A(id, abs0), v);
}
static inline uint32_t hr(uint8_t id, uint64_t abs0) {
    return read_reg(I3C_A(id, abs0));
}

/* Instance-0 register addresses as offsets from the wrapper base (the generated
 * headers expose only the base), matching
 * hw/sys/smc/bootrom/prod/drivers/src/i3c_hci_driver.c. */
#define I3C0_CSR_BASE SMC_TOP_OCA_I3C_WRAP_I3C_CSR_BASE_ADDR(0)
#define R_WRAP_BASE (I3C0_CSR_BASE + 0x000u) /* wrapper reset/enable lives at +0x0 */
#define R_HC_CONTROL (I3C0_CSR_BASE + 0x004u)
#define R_RESET_CONTROL (I3C0_CSR_BASE + 0x010u)
#define RC_RX_FIFO_RST (1u << 4) /* RESET_CONTROL.RX_FIFO_RST (base_registers.rdl, sw=rw level) */
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
#define STBYCR_ENABLE_INIT(v) ((uint32_t)(v) << 30) /* 3 = MODE_CONTROLLER (active) */
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
#define DBTC_TX_START_SHIFT \
    16 /* TX_START_THLD[18:16]: HW delays a write until TX queue \
        * holds this many DWORDs (or the whole transfer, if less) */
#define DBTC_RX_START_SHIFT \
    24 /* RX_START_THLD[26:24]: HW delays a read until RX queue has \
        * this much ROOM (or the whole transfer, if less) */
#define QTC_CMD_EMPTY_SHIFT 0
#define QTC_RESP_BUF_SHIFT 8

/* RESPONSE_PORT descriptor decode */
#define RESP_ERR(r) (((r) >> 28) & 0xFu)
#define RESP_LEN(r) ((r)&0xFFFFu)

/* OCA HCI RESPONSE err_status values (i3c_pkg.sv i3c_resp_err_status_e) we special-case below. */
#define HCI_RESP_NACK 0x5u /* target NACK'ed the read (e.g. TX not yet armed) */
#define HCI_RESP_SHORT_READ \
    0x7u /* I3cShortReadErr: target ended (end-of-data) before the \
          * commanded length -> EXPECTED for a deliberate over-read */

/* Over-read length for the OCCP response read. Uses the MRL+1 over-read idiom (
 * 2081): command a length far larger than any response so the *target* terminates the read via its
 * end-of-data T-bit (flow_active.sv I3CRead: ~fmt_bit_i). One bus transaction then delivers the
 * whole response into the RX FIFO; the OCCP layer's header-then-body reads just drain that FIFO (no
 * STOP between them, so the OCA target's single TX descriptor is never re-checked -> no read#2
 * NACK). */
#define HCI_OVERREAD_LEN 2081u

/* Controller half of the API: the target/TTI registers, fields, and the static-address /
 * rx-pending state live in the target implementation
 * (hw/sys/smc/bootrom/prod/drivers/src/i3c_hci_driver.c). */

/* Command-descriptor (cmd_lo) attribute field [2:0] */
#define ATTR_REGULAR 0x0u     /* regular transfer (data in TX/RX data port) */
#define ATTR_IMMEDIATE 0x1u   /* immediate data transfer (<=4 B in cmd_hi) */
#define ATTR_ADDR_ASSIGN 0x2u /* address-assignment CCC (e.g. SETDASA) */
/* cmd_lo bit fields (mirrors hw/ip/i3ccore_wrap/dv/tb/i3c_api.py) */
#define CMD_RNW (1u << 29)
#define CMD_WROC (1u << 30)
#define CMD_TOC (1u << 31)
#define CMD_SRE \
    (1u << 24) /* regular_trans_dat_desc_t.sre (DWORD0[24]): report a \
                * target-terminated short read as a RESPONSE. Without it, \
                * flow_active.sv I3CRead goes Idle on end-of-data and never \
                * writes a RESPONSE -> a deliberate over-read would hang. */
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

/* API-compatible wait_command: HCI has a single response queue (no cmd_id),
 * so command_id is accepted for signature parity and ignored. */
static I3C_Status wait_command(I3C_Driver *drv, uint8_t command_id, uint32_t timeout) {
    (void)command_id;
    (void)timeout;
    if (drv == NULL || !drv->ctx.initialized) {
        return I3C_ERR_HW;
    }
    return hci_wait_response(drv->ctx.controller_id, NULL);
}

/*--------------------------------------------------------------------------
 *  Release reset / enable.
 *  Mirrors hw/ip/i3ccore_wrap/dv/tb/i3c_api.py initialize() step 0: wrap_base+0x0 =
 *  i3c_reset_n | reg_reset_n | i3c_enable.
 *------------------------------------------------------------------------*/
void i3c_release_reset(uint8_t i3c_controller) {
    hw(i3c_controller, R_WRAP_BASE, (1u << 0) | (1u << 1) | (1u << 8));
}

/*--------------------------------------------------------------------------
 *  cfg_ps — API hook with no HCI action: the HCI controller has no PINSTRAPS
 *  flow; role/PID are set via STBY_CR + the DAT/own-address in
 *  init_i3c_ctrl / I3C_Start.
 *------------------------------------------------------------------------*/
void cfg_ps(uint8_t i3c_controller, uint8_t device_id, I3C_Role role) {
    (void)i3c_controller;
    (void)device_id;
    (void)role;
}

/*--------------------------------------------------------------------------
 *  init_i3c_ctrl — release reset (full controller bring-up is in I3C_Start,
 *  keeping the init/start split the API requires).
 *------------------------------------------------------------------------*/
void init_i3c_ctrl(uint8_t controller_id, uint64_t device_id, I3C_Role role) {
    (void)device_id;
    (void)role;
    i3c_release_reset(controller_id);
}

static I3C_Status I3C_Init(I3C_Driver *drv, uint8_t controller_id, uint64_t device_id,
                           I3C_Role role) {
    if (drv == NULL || controller_id >= I3C_MAX_DEVICES) {
        return I3C_ERR_INVALID_ARG;
    }
    drv->ctx.role = role;
    drv->ctx.controller_id = controller_id;
    init_i3c_ctrl(controller_id, device_id, role);
    drv->ctx.initialized = true;
    return I3C_OK;
}

/*--------------------------------------------------------------------------
 *  Open-drain bus timing (shared by controller + target start). Mirrors
 *  hw/ip/i3ccore_wrap/dv/tb/i3c_api.py configure_timing_od_i3c() — required to drive/track SCL.
 *------------------------------------------------------------------------*/
static void hci_program_od_timing(uint8_t id) {
    hw(id, R_T_R, 0);
    hw(id, R_T_F, 0);
    hw(id, R_T_SU_DAT, 2);
    hw(id, R_T_HD_DAT, 2);
    /* OD SCL high/low compressed for sim feasibility: the i3c-core clock is ~100MHz
     * (1 cycle ~= 10ns), so the stock 70/70/20 give ~700ns half-periods => ~1.4us/bit,
     * making a full ENTDAA (~120 bits @ OD) ~170us of sim-time under the controller's
     * busy-poll. 8 cycles (~80ns) keeps wide margin over SU_DAT/HD_DAT=2 (20ns) while
     * running the OD bus ~9x faster; the OCA target tracks this OD rate. */
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
 *  Controller bring-up.
 *  Mirrors hw/ip/i3ccore_wrap/dv/tb/i3c_api.py initialize() + configure_timing_od_i3c() +
 *  configure_thresholds(). Polled: signal-enable is optional, but we set the
 *  status-enable bits so PIO_INTR_STATUS reflects tx/rx/resp/cmd-queue.
 *------------------------------------------------------------------------*/
static I3C_Status I3C_Start(I3C_Driver *drv, int sys_clk_freq) {
    (void)sys_clk_freq; /* API parity; HCI uses fixed boot-time bus timing */
    if (!drv->ctx.initialized) {
        return I3C_ERR_HW;
    }
    uint8_t id = drv->ctx.controller_id;

    /* --- CONTROLLER (MANAGER) role: PIO bring-up --- */
    /* HC_CONTROL: enable bus + PIO mode */
    hw(id, R_HC_CONTROL, HC_BUS_ENABLE | HC_MODE_PIO);

    /* Active Controller Mode (Table-5 encoding = 3) + target-xact enable */
    hw(id, R_STBY_CR, STBYCR_ENABLE_INIT(3u) | STBYCR_TARGET_XACT);

    /* PIO interrupt STATUS enables (so PIO_INTR_STATUS reflects the events we poll) */
    hw(id, R_PIO_INTR_SE, PI_TX_THLD | PI_RX_THLD | PI_RESP_READY | PI_CMD_QUEUE_READY);

    /* Open-drain bus timing (boot defaults; required to drive SCL) */
    hci_program_od_timing(id);

    /* Thresholds: tx_buf=1, rx_buf=1; cmd_empty=1, resp=1. The START thresholds arm the
     * START_THLD gates in flow_active: a write waits until the TX queue holds the threshold (or
     * the whole message) before starting, and a read waits for that much RX room, so command
     * and data enqueue order cannot race. The PIO DATA queues are instantiated with ThldIsPow(1)
     * in queues.sv, so this field carries the HCI Table-42 2^(N+1) encoding, not a DWORD count,
     * and the decoded value must not exceed the 64-DWORD queue (write_queue.sv computes
     * `1 << (N+1)` in 7-bit width, so an oversize N truncates to 0 and disables the gate).
     * 2 -> 2^3 = 8 DWORDs (32 B); small transfers are released by the whole-message term. */
    hw(id, R_DBTC,
       (1u << DBTC_TX_BUF_SHIFT) | (1u << DBTC_RX_BUF_SHIFT) | (2u << DBTC_TX_START_SHIFT) |
           (2u << DBTC_RX_START_SHIFT));
    hw(id, R_QTC, (1u << QTC_CMD_EMPTY_SHIFT) | (1u << QTC_RESP_BUF_SHIFT));

    /* Enable PIO queues (RS=1) */
    hw(id, R_PIO_CONTROL, PIO_EN | PIO_RS);
    return I3C_OK;
}

/*--------------------------------------------------------------------------
 *  DAT entry. (HCI-specific; controller transfers reference a
 *  DAT index, not an inline address.)  Mirrors hw/ip/i3ccore_wrap/dv/tb/i3c_api.py set_dat_entry.
 *------------------------------------------------------------------------*/
/* ibi_payload -> DAT.IBI_PAYLOAD (bit 12 of the low word; dat_entry_t in controller_pkg.sv). It
 * must mirror the target's BCR[2] (IBI Payload capability): the controller HW gates the IBI data
 * phase on `ibi_abort = ibi_reject | ~ibi_payload` (flow_active.sv), so a BCR[2]=1 target's payload
 * IBI would be aborted right after the address if this bit is left 0. BCR is only known after
 * ENTDAA (read from the DCT), so the DAA preload passes ibi_payload=0 and I3C_ProcessDevices
 * rewrites the entry once BCR is available. */
static void set_dat_entry(uint8_t id, uint8_t idx, uint8_t static_addr, uint8_t dynamic_addr,
                          uint8_t ibi_payload) {
    uint32_t dat_lo = ((uint32_t)(static_addr & 0x7Fu)) | (((uint32_t)(ibi_payload & 0x1u)) << 12) |
                      (((uint32_t)(dynamic_addr & 0x7Fu)) << 16);
    write_reg(I3C_A(id, R_DAT_BASE) + (uint64_t)idx * 8u, dat_lo);
    write_reg(I3C_A(id, R_DAT_BASE) + (uint64_t)idx * 8u + 4u, 0u);
}

/*--------------------------------------------------------------------------
 *  SETDASA (static -> dynamic).  Mirrors hw/ip/i3ccore_wrap/dv/tb/i3c_api.py send_setdasa.
 *  Dedicated helper; the API's issue_setgrpa slot carries the SETGRPA CCC below.
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
 *  Generic CCC (SETGRPA et al). For an address-assign/CCC with one
 *  operand byte, push the operand to TX then issue an AddrAssign descriptor.
 *  (API parity: issue_setgrpa.)
 *------------------------------------------------------------------------*/
static I3C_Status I3C_IssueSETGRPA(I3C_Driver *drv, uint8_t da, uint8_t group_addr) {
    if (!drv->ctx.initialized) {
        return I3C_ERR_HW;
    }
    uint8_t id = drv->ctx.controller_id;
    /* one-byte operand (group address) as immediate CCC payload */
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

    /* HCI DAA hands out DAT[i].dynamic_address to each responding target
     * (flow_active.sv emits {dat_rdata.dynamic_address, parity}); static_addr=0 (DAA has
     * no static addr). Without a preload the core would assign DA=0. Mirrors hci_setdasa.
     * dev_count MUST equal the number of targets on the bus: with more, the core runs extra
     * broadcast/NACK rounds after the last assignment and ends them holding SDA low (no
     * STOP/release), so the next directed transfer cannot issue a START. The occp bus has
     * exactly ONE target, so provision one DA (0x08) and assign one device. */
    const uint8_t daa_dev_count = 1u;
    for (uint8_t i = 0; i < daa_dev_count; i++) {
        /* IBI_PAYLOAD=0 here; it is rewritten from the discovered BCR[2] in I3C_ProcessDevices. */
        set_dat_entry(id, i, 0u, (uint8_t)(0x08u + i), 0u);
    }

    /* AddrAssign descriptor: dev_count in DWORD0[29:26] (DWORD1 is reserved), wroc+toc set.
     * flow_active.sv returns NotSupported(0xA) if dev_count==0 | ~wroc | ~toc. */
    uint32_t cmd_lo = ATTR_ADDR_ASSIGN | CMD_CCC(0x07u) | CMD_DEVIDX(0u) |
                      CMD_DEVCOUNT(daa_dev_count) | CMD_WROC | CMD_TOC;
    simputshex32("[I3C_HCI] ENTDAA command descriptor: ", cmd_lo);
    hw(id, R_CMD_PORT, cmd_lo);
    hw(id, R_CMD_PORT, 0u); /* DWORD1 reserved */
    /* Issue-only: post the descriptor and return. The occp flow (discover_devices)
     * calls wait_command() right after, which does the single hci_wait_response that
     * consumes the DAA RESPONSE. Waiting here too would consume the lone RESPONSE and
     * leave wait_command's second wait to busy-poll to timeout (semantics:
     * issue=kick, wait=poll-completion). */
    return I3C_OK;
}

static I3C_Status I3C_ProcessDevices(I3C_Driver *drv, I3C_DeviceInfo *devices, size_t max_devices) {
    if (!drv->ctx.initialized) {
        return I3C_ERR_HW;
    }
    uint8_t id = drv->ctx.controller_id;
    /* occp convention (mirrors the retaining-register table): index [0] is the
     * controller's own entry and discovered targets start at [1] — discover_devices reads
     * discovered_devices[1].dynamic_addr and requires num_devices>=2. The HCI DCT holds only
     * discovered targets, so seed [0] as the controller self-entry and store DCT targets from [1].
     * (occp reads only [1].dynamic_addr; [0] is never dereferenced for addressing.) */
    I3C_DeviceInfo self = {0};
    self.controller_id = id;
    self.active = true;
    drv->ctx.discovered_devices[0] = self;
    if (devices && max_devices > 0) {
        devices[0] = self;
    }
    drv->ctx.num_devices = 1;
    /* DCT entry = 4 words: [PID_HI][PID_LO][BCR/DCR][dynamic_addr] (MIPI HCI).
     * Walk until a zero dynamic-address entry. */
    for (uint8_t i = 0; i < I3C_MAX_DEVICES; i++) {
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
        /* Now that BCR is known, program DAT.IBI_PAYLOAD from BCR[2] (IBI Payload capability) so
         * the controller accepts the IBI data phase for devices that advertise an MDB+payload. DAT
         * idx == DCT idx for sequential ENTDAA assignment (DAT[i] was preloaded with DA 0x08+i and
         * assigned in order); DAA-assigned devices have static_addr=0 and dynamic_addr=dyn (the
         * assigned DA). */
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
 *  Private write. Mirrors hw/ip/i3ccore_wrap/dv/tb/i3c_api.py private_write:
 *  regular write descriptor (attr=0, data_len in cmd_hi[31:16]) + push bytes
 *  to TX_DATA_PORT while TX_THLD has space, then read RESPONSE_PORT.
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

    /* The TX payload must be queued before the controller's BusTX FSM runs: with an empty format
     * FIFO the FSM stalls in BusTX (fmt_fifo_rready_i=0) and clocks SCL forever. PI_TX_THLD is a
     * threshold-crossing trigger (hci.sv: hci_tx_ready_thld_trig_o) and never asserts while the
     * TX FIFO starts empty, so the first fill cannot wait on it; only payloads larger than the
     * ~64-DWORD TX FIFO wait for PI_TX_THLD (space) between bursts. */
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
        /* every 128 bytes (well under the 64-DWORD/256-B TX FIFO) wait for space before continuing
         */
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
 *  Private read. Mirrors hw/ip/i3ccore_wrap/dv/tb/i3c_api.py private_read controller side:
 *  regular read descriptor (rnw=1, data_len in cmd_hi) + drain RX_DATA_PORT;
 *  the true byte count is RESPONSE_PORT.data_length.
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

    /* Poll for the RESPONSE (transfer complete), pulling RX words as they appear. The TRUE received
     * byte count is RESPONSE_PORT.data_length — do NOT blindly drain `length` words. A short/NACKed
     * read (data_length < length, e.g. 0 when the OCA target NACKs an empty read because its TX
     * queue is not yet armed) would over-read an EMPTY RX FIFO and the AXI read STALLS forever. So:
     * capture RESP first, then drain exactly its data_length. */
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

    /* drain exactly the bytes the response says arrived but we have not pulled yet (never the empty
     * FIFO) */
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
 *  Public API bodies.
 *  da is the target's dynamic address; this driver maps it to DAT index 0
 *  (single-target bus).
 *------------------------------------------------------------------------*/
static I3C_Status I3C_Write(I3C_Driver *drv, uint8_t da, const uint8_t *data, size_t length) {
    if (!drv->ctx.initialized) {
        return I3C_ERR_HW;
    }
    (void)da;
    return hci_write_xfer(drv, 0u, data, length);
}

/*--------------------------------------------------------------------------
 *  OCCP response read — decoupled over-read + FIFO drain.
 *
 *  The OCCP layer reads a response in two `read()` calls (header, then body)
 *  because it must parse the header to learn the body length. hci_read_xfer
 *  issues a STOP per call (TOC), so a naive two-call read is TWO bus
 *  transactions; after read#1 consumes the OCA target's single TX descriptor,
 *  read#2's fresh START is NACK'ed (i3c_target_fsm CheckFByte: ~tx_desc_avail).
 *  A single over-read (MRL+1) avoids this by issuing one read that
 *  the TARGET terminates at its real length, then draining the RX FIFO across
 *  calls. We mirror that here. A 3-byte stage carries the leftover of a partial
 *  FIFO word across calls so any header/body split keeps byte alignment.
 *------------------------------------------------------------------------*/
static uint16_t g_rx_fifo_bytes[I3C_MAX_DEVICES]; /* response bytes still in the HW RX FIFO   */
static uint8_t g_rx_stage[I3C_MAX_DEVICES][4];    /* leftover bytes of a partly-consumed word */
static uint8_t g_rx_stage_len[I3C_MAX_DEVICES];
static uint8_t g_rx_stage_pos[I3C_MAX_DEVICES];

/* Over-read state: an over-read is IN FLIGHT between command issue and the RESPONSE descriptor.
 * While in flight the total byte count is unknown; the drain loop in I3C_Read pops words as they
 * arrive and g_rx_consumed tracks them so the post-RESPONSE remainder can be computed. */
static bool g_rx_inflight[I3C_MAX_DEVICES];
static uint16_t g_rx_consumed[I3C_MAX_DEVICES];

/* Reap a still-open over-read flight: the streaming I3C_Read returns as soon as the caller's
 * bytes are served, which can leave the transfer's RESPONSE descriptor UNCLAIMED (data words
 * arrive slightly before the RESPONSE). Any NEW command issued with that flight open would then
 * consume the stale RESPONSE as its own -> off-by-one response pairing and phantom errors on
 * good transfers. Wait the old RESPONSE out (draining RX meanwhile so the transfer can finish),
 * book the leftover byte count, and only then let the caller proceed. */
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

/* Issue ONE over-read and return IMMEDIATELY (streaming drain). The target ends the read at its
 * actual length; the RESPONSE (err_status=I3cShortReadErr, data_length=actual) arrives at the END
 * of the transfer. I3C_Read drains the RX FIFO DURING the flight, so a response larger than the
 * 64-DWORD (256 B) PIO RX queue does not overflow it (err_status=0x6 OVL). */
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

    /* 1. Serve any staged leftover from a previously popped partial word. */
    while (out < length && g_rx_stage_pos[id] < g_rx_stage_len[id]) {
        buffer[out++] = g_rx_stage[id][g_rx_stage_pos[id]++];
    }
    if (out < length) {
        g_rx_stage_len[id] = 0u;
        g_rx_stage_pos[id] = 0u;
    }

    /* 2. STREAMING drain while the over-read is in flight: pop whole words as they arrive so the
     * 64-DWORD RX queue never overflows on large responses. PI_RX_THLD asserts at >= 4 entries
     * (init writes DATA_BUFFER_THLD_CTRL rx_buf threshold n=1 -> 2^(n+1) = 4), so a pop here
     * always leaves >= 3 entries behind and can never grab the transfer's FINAL (possibly
     * partial) word early -- that word is drained in step 3 with the RESPONSE's exact count. */
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
                    /* NACK (target TX not armed yet) or a real error: flush the junk the failed
                     * read leaves in the RX FIFO so the next attempt starts clean; OCCP layer
                     * retries. */
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
                /* >= 2 whole words buffered: pop one (4 valid bytes guaranteed, see above). */
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
    /* controller: rx fill reflected by RX_THLD (exact level is in a queue-status reg) */
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
    static I3C_Driver instances[I3C_MAX_DEVICES];
    static bool initialized[I3C_MAX_DEVICES] = {false};

    if (controller_id >= I3C_MAX_DEVICES) {
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

/* hci_setdasa is exposed for callers that assign a dynamic address before any
 * private transfer; reference it so -Werror=unused does not fire if a build
 * does not call it directly. */
I3C_Status (*const i3c_hci_setdasa_ref)(I3C_Driver *, uint8_t, uint8_t, uint8_t) = hci_setdasa;

#pragma GCC diagnostic pop

#endif /* I3C_USE_HCI_CORE */
