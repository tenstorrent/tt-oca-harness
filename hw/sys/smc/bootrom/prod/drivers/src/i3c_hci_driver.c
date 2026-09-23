/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*============================================================================
 *  i3c_hci_driver.c — ROM driver for the OCA i3c-core (MIPI I3C HCI / I3CCSR)
 *
 *  Implements the SAME public API as the Cadence driver (i3c_target_driver.h)
 *  but re-expressed against the HCI programming model (PIO command/response/
 *  data ports + DAT + DCT). Drop-in: select exactly ONE of {the nonfree
 *  Cadence strong override, this file} per build via I3C_CORE=swap.
 *
 *  This whole file is gated by I3C_USE_HCI_CORE so adding it to the build list
 *  is a no-op until that flag is defined (keeps the default ROM build intact:
 *  the weak stubs in i3c_target_driver.c, or the nonfree Cadence override,
 *  provide the driver instead).
 *
 *  Every register sequence below mirrors the proven cocotb controller driver
 *  (nonfree dv tb_wrap_cocotb common/i3c_api_smc.py, green on this RTL).
 *
 *  v1 scope: controller mode, POLLED (no IBI).
 *==========================================================================*/
#if defined(I3C_USE_HCI_CORE)

#include "i3c_target_driver.h"
#include "smc_defines.h" /* read_reg / write_reg and the generated register map */
#include "virt_console.h"

#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wconversion"

/*--------------------------------------------------------------------------
 *  Addressing. The I3CCSR block starts at the wrap base (CSR sub-offset 0);
 *  instance 1 is instance 0 + 0x1000. So any instance-N register =
 *  <instance-0 absolute addr> + N*0x1000.
 *
 *  The register map models the I3C CSR block as an opaque window (only
 *  OCA_I3C_WRAP_*_REG_MAP_BASE_ADDR is generated), so the per-register
 *  offsets below are spelled out locally. They are the I3CCSR offsets of the
 *  vendored i3c-core (verified against the address decode in
 *  vendor/chipsalliance/i3c-core/upstream/src/csr/I3CCSR.sv).
 *------------------------------------------------------------------------*/
#define I3C_INST_STRIDE 0x1000u
#define I3C_A(id, abs0) ((uint64_t)(abs0) + (uint64_t)(id)*I3C_INST_STRIDE)

static inline void hw(uint8_t id, uint64_t abs0, uint32_t v) {
    write_reg(I3C_A(id, abs0), v);
}
static inline uint32_t hr(uint8_t id, uint64_t abs0) {
    return read_reg(I3C_A(id, abs0));
}

/* instance-0 absolute register addresses (window base + I3CCSR offset) */
#define I3C0_CSR_BASE OCA_I3C_WRAP_0_REG_MAP_BASE_ADDR
#define R_HC_CONTROL (I3C0_CSR_BASE + 0x004u)  /* I3CBase HC_CONTROL */
#define R_STBY_CR (I3C0_CSR_BASE + 0x184u)     /* I3C_EC StdbyCtrlMode STBY_CR_CONTROL */
#define R_PIO_CONTROL (I3C0_CSR_BASE + 0x0B0u) /* PIOControl PIO_CONTROL */
#define R_PIO_INTR (I3C0_CSR_BASE + 0x0A0u)    /* PIOControl PIO_INTR_STATUS */
#define R_PIO_INTR_SE (I3C0_CSR_BASE + 0x0A4u) /* PIOControl PIO_INTR_STATUS_ENABLE */
#define R_PIO_INTR_GE (I3C0_CSR_BASE + 0x0A8u) /* PIOControl PIO_INTR_SIGNAL_ENABLE */
#define R_CMD_PORT (I3C0_CSR_BASE + 0x080u)    /* PIOControl COMMAND_PORT */
#define R_RESP_PORT (I3C0_CSR_BASE + 0x084u)   /* PIOControl RESPONSE_PORT */
#define R_TX_PORT (I3C0_CSR_BASE + 0x088u)     /* PIOControl TX_DATA_PORT */
#define R_RX_PORT (I3C0_CSR_BASE + 0x088u)     /* PIOControl RX_DATA_PORT (same port) */
#define R_DBTC (I3C0_CSR_BASE + 0x094u)        /* PIOControl DATA_BUFFER_THLD_CTRL */
#define R_QTC (I3C0_CSR_BASE + 0x090u)         /* PIOControl QUEUE_THLD_CTRL */
#define R_DAT_BASE (I3C0_CSR_BASE + 0x400u)    /* DAT table */
#define R_DCT_BASE (I3C0_CSR_BASE + 0x800u)    /* DCT table */
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
 *  Field positions (verified against the vendored i3c-core I3CCSR map)
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
#define QTC_CMD_EMPTY_SHIFT 0
#define QTC_RESP_BUF_SHIFT 8

/* RESPONSE_PORT descriptor decode */
#define RESP_ERR(r) (((r) >> 28) & 0xFu)
#define RESP_LEN(r) ((r)&0xFFFFu)

/* ---- Target (subordinate / TTI) registers + fields ---- */
#define R_STBY_DEV_ADDR (I3C0_CSR_BASE + 0x188u) /* StdbyCtrlMode STBY_CR_DEVICE_ADDR */
#define R_TTI_INTR (I3C0_CSR_BASE + 0x220u)      /* TTI INTERRUPT_STATUS */
#define R_TTI_INTR_EN (I3C0_CSR_BASE + 0x224u)   /* TTI INTERRUPT_ENABLE */
#define R_TTI_RX_DATA (I3C0_CSR_BASE + 0x274u)   /* TTI RX_DATA_PORT */
#define R_TTI_TX_DATA (I3C0_CSR_BASE + 0x27Cu)   /* TTI TX_DATA_PORT */
#define R_TTI_RX_DESC (I3C0_CSR_BASE + 0x270u)   /* TTI RX_DESC_QUEUE_PORT */
#define R_TTI_TX_DESC (I3C0_CSR_BASE + 0x278u)   /* TTI TX_DESC_QUEUE_PORT */
#define R_TTI_DBTC (I3C0_CSR_BASE + 0x290u)      /* TTI DATA_BUFFER_THLD_CTRL */
#define R_TTI_QTC (I3C0_CSR_BASE + 0x28Cu)       /* TTI QUEUE_THLD_CTRL */
/* TTI_QUEUE_STATUS: level/empty/full of the target queues (NOT edge-gated, unlike the
 * INTERRUPT_STATUS threshold bits) — used to drive RX draining like the Cadence fill-level read. */
#define R_TTI_QUEUE_STATUS (I3C0_CSR_BASE + 0x210u)
#define TTI_RX_DESC_QUEUE_EMPTY (1u << 1) /* QUEUE_STATUS.RX_DESC_QUEUE_EMPTY */
#define TTI_TX_DESC_QUEUE_FULL (1u << 2)  /* QUEUE_STATUS.TX_DESC_QUEUE_FULL  */
#define TTI_TX_DATA_QUEUE_FULL (1u << 6)  /* QUEUE_STATUS.TX_DATA_QUEUE_FULL  */
#define TTI_RX_DATA_QUEUE_EMPTY (1u << 5) /* QUEUE_STATUS.RX_DATA_QUEUE_EMPTY */
/* TTI_DATA_QUEUE_DEPTH: current DWORD (32-bit) entry counts of the target data queues — a true
 * level status (sw=r), the OCA analog of the Cadence RX_FIFO_STATUS.rx_fifo_fill_lvl. */
#define R_TTI_DATA_QUEUE_DEPTH (I3C0_CSR_BASE + 0x218u)
#define TTI_RX_DATA_QUEUE_DEPTH(d) ((d)&0xFFu) /* RX_DATA_QUEUE_DEPTH[7:0], in DWORDs */

/* STBY_CR_DEVICE_ADDR fields */
#define STBY_STATIC_ADDR(a) (((uint32_t)(a)&0x7Fu) << 0)
#define STBY_STATIC_ADDR_VALID (1u << 15)
/* STBY_CR_CONTROL extra fields (target) */
#define STBYCR_DAA_SETDASA_EN (1u << 14)
#define STBYCR_DAA_ENTDAA_EN (1u << 15)
#define STBYCR_SCM_RUNNING STBYCR_ENABLE_INIT(0x2u) /* enable_init = 0b10 (SCM_RUNNING) */

/* TTI INTERRUPT_STATUS bits */
#define TTI_TX_DATA_THLD (1u << 8)
#define TTI_RX_DATA_THLD (1u << 9)
#define TTI_TX_DESC_THLD (1u << 10)
#define TTI_RX_DESC_THLD (1u << 11)
#define TTI_TX_DESC_COMPLETE (1u << 26)
/* TTI RX descriptor: byte count [15:0], rx_error [31:20] */
#define TTI_RXDESC_LEN(d) ((d)&0xFFFFu)
#define TTI_RXDESC_ERR(d) (((d) >> 20) & 0xFFFu)

/* per-controller static address captured at init (target mode) */
static uint8_t g_i3c_static_addr[I3C_MAX_DEVICES];

/* per-controller RX accounting: bytes still owed from the current (already-popped) RX
 * descriptor. A single inbound I3C private write yields ONE descriptor covering the whole
 * frame (e.g. an OCCP header+body = 24 B), but the OCCP layer drains it across SEPARATE
 * receive calls (header, then body). So we must NOT re-wait for a fresh descriptor mid-frame:
 * pop the descriptor once to learn the transfer length, then keep draining the RX DATA queue
 * across calls until that length is consumed. (See hci_target_rx.) */
static size_t g_i3c_rx_pending[I3C_MAX_DEVICES];

/* Target RX streaming: staging buffer for bytes drained from the RX DATA queue
 * BEFORE the frame's descriptor has been written (the core writes the RX descriptor
 * only at frame END, descriptor_rx.sv transfer_ended). Draining while waiting serves two
 * purposes: (1) the wait becomes idle-based -- only polls where NOTHING arrives count
 * toward the timeout, matching the Cadence NO_DATA_THRESHOLD "consecutive empty polls"
 * semantics (a frame still in flight on the bus keeps resetting the window instead of
 * spuriously timing out mid-frame); (2) frames larger than the 64-DWORD (256 B) TTI RX
 * data queue no longer overflow-drop in RTL, because firmware keeps the queue drained
 * while the frame streams in. FIFO order guarantees the drained bytes are the HEAD of the
 * frame whose descriptor we are waiting for (staging only starts when the frame ledger is
 * clean and the DESC queue is empty). Single shared buffer (max OCCP frame ~2055 B; a
 * per-device array at I3C_MAX_DEVICES=11 would cost 23 KB): the OCCP layer serves one
 * channel at a time, so ownership is per-frame; a concurrent frame on another controller
 * simply does not get staging (falls back to the plain bounded wait). */
#define I3C_RX_STAGE_SIZE 2064u
static uint8_t g_i3c_rx_stage[I3C_RX_STAGE_SIZE];
static uint16_t g_i3c_rx_stage_len;  /* write index (bytes staged)          */
static uint16_t g_i3c_rx_stage_pos;  /* read index (bytes handed to caller) */
static uint8_t g_i3c_rx_stage_owner; /* controller id the staged frame belongs to */

/* Command-descriptor (cmd_lo) attribute field [2:0] */
#define ATTR_REGULAR 0x0u     /* regular transfer (data in TX/RX data port) */
#define ATTR_IMMEDIATE 0x1u   /* immediate data transfer (<=4 B in cmd_hi) */
#define ATTR_ADDR_ASSIGN 0x2u /* address-assignment CCC (e.g. SETDASA) */
/* cmd_lo bit fields (mirrors i3c_api_smc.py) */
#define CMD_RNW (1u << 29)
#define CMD_WROC (1u << 30)
#define CMD_TOC (1u << 31)
#define CMD_DEVIDX(i) (((uint32_t)(i)&0x1Fu) << 16)
#define CMD_CCC(c) (((uint32_t)(c)&0xFFu) << 7)
#define CMD_DTT(n) (((uint32_t)(n)&0x7u) << 23) /* immediate byte count */

#define I3C_POLL_LIMIT 2000000u /* generous busy-poll bound for ROM */
#define I3C_FIFO_WORD 4u

typedef union {
    uint32_t word;
    uint8_t bytes[4];
} i3c_word_u;

/*--------------------------------------------------------------------------
 *  Wait for a command's RESPONSE_PORT and decode the error.
 *  Replaces the Cadence MST_STATUS0.idle + CMDR poll.
 *------------------------------------------------------------------------*/
static I3C_Status hci_wait_response(uint8_t id, uint32_t *resp_out) {
    for (uint32_t i = 0; i < I3C_POLL_LIMIT; i++) {
        if (hr(id, R_PIO_INTR) & PI_RESP_READY) {
            uint32_t resp = hr(id, R_RESP_PORT);
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

/* The wrapper has no reset or enable register: rst_ni follows the SMC primary reset. */
void i3c_release_reset(uint8_t i3c_controller) {
    (void)i3c_controller;
}

/*--------------------------------------------------------------------------
 *  cfg_ps — kept for API parity. The HCI controller does not use the Cadence
 *  PINSTRAPS flow; role/PID are set via STBY_CR + the DAT/own-address in
 *  init_i3c_ctrl / I3C_Start. No-op placeholder (documented).
 *------------------------------------------------------------------------*/
void cfg_ps(uint8_t i3c_controller, uint8_t device_id, I3C_Role role) {
    (void)i3c_controller;
    (void)device_id;
    (void)role;
}

/*--------------------------------------------------------------------------
 *  init_i3c_ctrl — release reset (full controller bring-up is in I3C_Start,
 *  mirroring the Cadence init/start split).
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
    g_i3c_static_addr[controller_id] = (uint8_t)(device_id & 0x7Fu); /* target static addr */
    init_i3c_ctrl(controller_id, device_id, role);
    drv->ctx.initialized = true;
    return I3C_OK;
}

/*--------------------------------------------------------------------------
 *  Open-drain bus timing (shared by controller + target start). Mirrors
 *  i3c_api_smc.py configure_timing_od_i3c() — required to drive/track SCL.
 *------------------------------------------------------------------------*/
static void hci_program_od_timing(uint8_t id) {
    hw(id, R_T_R, 0);
    hw(id, R_T_F, 0);
    hw(id, R_T_SU_DAT, 2);
    hw(id, R_T_HD_DAT, 2);
    hw(id, R_T_HIGH, 14);
    hw(id, R_T_HIGH_OD, 20);
    hw(id, R_T_HIGH_INIT_OD, 70);
    hw(id, R_T_LOW, 14);
    hw(id, R_T_LOW_OD, 70);
    hw(id, R_T_HD_STA, 13);
    hw(id, R_T_SU_STA, 9);
    hw(id, R_T_SU_STO, 8);
    hw(id, R_T_HD_RSTA, 9);
    hw(id, R_T_DS_OD, 24);
    hw(id, R_T_FREE, 13);
    hw(id, R_T_AVAL, 333);
    hw(id, R_T_IDLE, 66600);
}

/*--------------------------------------------------------------------------
 *  TARGET (subordinate / TTI) bring-up.  Mirrors the proven cocotb
 *  I3CTargetSMC.initialize()/configure_thresholds() (i3c_api_smc.py).
 *  occp.c inits the i3c as SUBORDINATE, so this is the path it exercises.
 *------------------------------------------------------------------------*/
static I3C_Status hci_target_start(I3C_Driver *drv) {
    uint8_t id = drv->ctx.controller_id;
    g_i3c_rx_pending[id] = 0u;        /* no RX frame in flight after (re)start */
    if (g_i3c_rx_stage_owner == id) { /* drop any staged bytes of a pre-restart frame */
        g_i3c_rx_stage_len = 0u;
        g_i3c_rx_stage_pos = 0u;
    }
    /* HC_CONTROL: bus_enable gates the target PHY/ACK path (configuration.sv phy_en) */
    hw(id, R_HC_CONTROL, HC_BUS_ENABLE);
    /* static address + valid */
    hw(id, R_STBY_DEV_ADDR, STBY_STATIC_ADDR(g_i3c_static_addr[id]) | STBY_STATIC_ADDR_VALID);
    /* Standby Controller Mode = SCM_RUNNING; accept SETDASA *and* ENTDAA (the OCCP master uses
     * ENTDAA to assign the target's dynamic address), enable target transactions. The cocotb
     * reference only used SETDASA, hence ENTDAA was missing -> the master's ENTDAA NACKed (M2). */
    hw(id, R_STBY_CR,
       STBYCR_SCM_RUNNING | STBYCR_DAA_SETDASA_EN | STBYCR_DAA_ENTDAA_EN | STBYCR_TARGET_XACT);
    /* bus timing (must match the controller's) */
    hci_program_od_timing(id);
    /* TTI thresholds: tx_data=1, rx_data=1; tx_desc=1, rx_desc=1, ibi=1 */
    hw(id, R_TTI_DBTC, (1u << 0) | (1u << 8));
    hw(id, R_TTI_QTC, (1u << 0) | (1u << 8) | (1u << 24));
    /* TTI interrupt status enables (so we can poll the status bits). The TX threshold (watermark)
     * interrupts are intentionally NOT enabled: target TX arming uses the QUEUE_STATUS level
     * (see hci_target_tx), and leaving the level-triggered TX_*_THLD_STAT enabled would hold the
     * shared i3c irq_o asserted on an idle/empty TX queue. RX threshold + TX_DESC_COMPLETE
     * remain. */
    hw(id, R_TTI_INTR_EN, TTI_RX_DATA_THLD | TTI_RX_DESC_THLD | TTI_TX_DESC_COMPLETE);
    return I3C_OK;
}

/* Target sends a read-response: arm the TX descriptor (byte count) then pre-fill
 * the whole payload (descriptor_tx loads byte_counter only once the data is buffered). */
static I3C_Status hci_target_tx(I3C_Driver *drv, const uint8_t *data, size_t length) {
    uint8_t id = drv->ctx.controller_id;
    /* Wait for room in the TX descriptor queue using the LEVEL status
     * QUEUE_STATUS.TX_DESC_QUEUE_FULL, not the INTERRUPT_STATUS.TX_DESC_THLD watermark. "Is there
     * space to write a descriptor now?" is a current-occupancy (level) question; the
     * threshold-status bit is an edge/watermark event meant for batch refill and is
     * true-from-reset on an empty queue, so it carries no edge for the first write. This mirrors
     * the RX drain path, which already polls QUEUE_STATUS level bits for the same reason. */
    uint32_t i;
    for (i = 0; i < I3C_POLL_LIMIT; i++) {
        if (!(hr(id, R_TTI_QUEUE_STATUS) & TTI_TX_DESC_QUEUE_FULL)) {
            break;
        }
    }
    if (i >= I3C_POLL_LIMIT) {
        return I3C_ERR_TIMEOUT;
    }
    /* Push data words BEFORE the descriptor (doorbell-last). The descriptor is the "response
     * ready" advertisement: once visible the core may ACK a controller private-read, so data
     * must already be resident. Writing the descriptor first opened a race window (~13us for a
     * 100B response): a read landing mid-fill was ACKed with no byte-valid data and the bus FSM
     * re-transmitted the stale first byte -> corrupted frame.
     *
     * Streaming (responses larger than the TX data queue, 64 DWORD = 256B): the queue cannot
     * hold the whole message, so once the fill hits TX_DATA_QUEUE_FULL we arm the descriptor
     * EARLY and keep topping the queue up as HW drains it. This pairs with the RTL behavior in
     * descriptor_tx.sv (tx_start / tx_desc_avail also fire at a start-threshold, and reads that
     * arrive before the threshold are NACKed) and i3c_target_fsm.sv (a real producer underrun
     * ends the read legally via the T-bit instead of replaying stale bytes). */
    size_t written = 0;
    bool desc_written = false;
    while (written < length) {
        /* Level-poll for queue space; on first FULL, arm the descriptor so HW can start
         * draining (large-response streaming path). */
        for (i = 0; i < I3C_POLL_LIMIT; i++) {
            if (!(hr(id, R_TTI_QUEUE_STATUS) & TTI_TX_DATA_QUEUE_FULL)) {
                break;
            }
            if (!desc_written) {
                hw(id, R_TTI_TX_DESC, (uint32_t)length << 16);
                desc_written = true;
            }
        }
        if (i >= I3C_POLL_LIMIT) {
            return I3C_ERR_TIMEOUT;
        }
        i3c_word_u w;
        w.word = 0;
        size_t rem = length - written;
        size_t n = (rem > I3C_FIFO_WORD) ? I3C_FIFO_WORD : rem;
        for (size_t b = 0; b < n; b++) {
            w.bytes[b] = data[written + b];
        }
        hw(id, R_TTI_TX_DATA, w.word);
        written += n;
    }
    if (!desc_written) {
        hw(id, R_TTI_TX_DESC, (uint32_t)length << 16); /* byte count (== Cadence pr_pl) */
    }
    return I3C_OK;
}

/* Target receives an inbound write. The OCCP layer reads ONE I3C write frame across multiple
 * calls (header, then body), but the i3c-core emits a single RX descriptor for the whole
 * frame. Waiting for TTI_RX_DESC_THLD on EVERY call and capping the read at the descriptor
 * length would make call 1 consume the descriptor + read the header, and call 2 hang forever
 * waiting for a second descriptor that never comes (the body bytes sit in the RX DATA queue;
 * TTI_INTERRUPT_STATUS.RX_DESC_THLD is write-edge-gated and cannot re-assert for a tail).
 *
 * Instead (mirrors the Cadence target's fill-level read): pop the RX descriptor ONCE per frame
 * to learn its byte count, remember the remainder across calls (g_i3c_rx_pending), and drain the
 * RX DATA queue using TTI_QUEUE_STATUS (a true level/empty status, not the edge-gated IRQ).
 * Only wait for a new descriptor when the current frame is fully consumed. Bounded polls so a
 * short/aborted transfer returns I3C_ERR_INCOMPLETE instead of hanging. */
static I3C_Status hci_target_rx(I3C_Driver *drv, uint8_t *buffer, size_t buffer_length, size_t *got,
                                bool is_flush, bool expect_excess_bytes, uint32_t timeout) {
    uint8_t id = drv->ctx.controller_id;
    I3C_Status err = I3C_OK;
    size_t out = 0;
    /* Cadence-contract parity: honor the caller's timeout as the empty-wait poll bound,
     * exactly like the Cadence driver (NO_DATA_THRESHOLD = timeout; each poll = one CSR read).
     * timeout==0 keeps the legacy bound (non-stream API has no timeout in its signature). */
    uint32_t poll_limit = (timeout != 0u) ? timeout : I3C_POLL_LIMIT;

    if (is_flush) {
        /* FRAME-AWARE flush (replaces a drain-whatever-is-present policy): discard ONLY
         * bytes that belong to already-started or already-queued frames, using the frame LEDGER:
         *   (1) the remainder of the current (errored/abandoned) frame = g_i3c_rx_pending,
         *       waiting boundedly for bytes still in flight on the bus;
         *   (2) stale COMPLETE frames already sitting in the RX DESC queue: pop each descriptor
         *       and discard exactly its byte count.
         * Stop the moment the ledger is clean (got=0 tells the OCCP loop to exit). Never drain by
         * time or by "queue not empty": the RX data queue is FIFO, so ledgered bytes are always
         * at the head, and a NEW command arriving during the flush (its descriptor not yet
         * written, or beyond the counted bytes) is left untouched. A time-based policy can eat a
         * whole command that a compliant controller sends right after reading our error response
         * -> permanent mutual wait (smc_occp_zero_length_rw_test). buffer is NOT written
         * (discard only). */
        /* Staged bytes (see g_i3c_rx_stage) were already popped OFF the RX data queue and belong
         * to the OLDEST un-consumed frame (always a frame with pending==0, i.e. its descriptor
         * had not arrived when staging happened). Two cases here:
         *   - that frame's descriptor has ARRIVED by now -> it is a stale complete frame, dead
         *     per the ledger policy: credit the staged bytes against ITS descriptor when popped
         *     below (they are already off the queue -- draining the full descriptor count from
         *     the queue would over-run into the next frame) and drop them;
         *   - no descriptor yet -> it is a LIVE in-flight command: leave the stage untouched,
         *     exactly like the queue-resident bytes of a live frame (flush must not eat it). */
        bool stage_is_mine =
            (g_i3c_rx_stage_owner == id) && (g_i3c_rx_stage_pos < g_i3c_rx_stage_len);
        bool first_desc = true;
        /* Case 0 -- CURRENT frame partially served with its tail still staged (pending > 0 AND
         * staged bytes coexist: the normal read stops serving the stage the moment the caller
         * is satisfied). The staged tail is ledgered remainder that lives OFF the queue --
         * without this credit the queue-wait below finds nothing, reports the remainder as
         * "never arrived", and the staged bytes leak into the NEXT command's header
         * (observed: corrupt-header inject, then GET_VERSION answered Corrupt_header). */
        if (stage_is_mine && g_i3c_rx_pending[id] != 0u) {
            size_t credit = (size_t)(g_i3c_rx_stage_len - g_i3c_rx_stage_pos);
            size_t take = (credit > g_i3c_rx_pending[id]) ? g_i3c_rx_pending[id] : credit;
            g_i3c_rx_pending[id] -= take;
            out += take;
            g_i3c_rx_stage_len = 0u;
            g_i3c_rx_stage_pos = 0u;
            stage_is_mine = false;
        }
        while (out < buffer_length) {
            if (g_i3c_rx_pending[id] == 0u) {
                if ((hr(id, R_TTI_QUEUE_STATUS) & TTI_RX_DESC_QUEUE_EMPTY) != 0u) {
                    break; /* ledger clean */
                }
                uint32_t desc = hr(id, R_TTI_RX_DESC);
                g_i3c_rx_pending[id] = TTI_RXDESC_LEN(desc);
                if (first_desc && stage_is_mine) { /* staged head of this (oldest) frame */
                    size_t credit = (size_t)(g_i3c_rx_stage_len - g_i3c_rx_stage_pos);
                    size_t take = (credit > g_i3c_rx_pending[id]) ? g_i3c_rx_pending[id] : credit;
                    g_i3c_rx_pending[id] -= take;
                    out += take;
                    g_i3c_rx_stage_len = 0u;
                    g_i3c_rx_stage_pos = 0u;
                    stage_is_mine = false;
                }
                first_desc = false;
                if (g_i3c_rx_pending[id] == 0u) {
                    continue; /* zero-length stale frame */
                }
            }
            /* bounded wait: the owed bytes may still be crossing the bus */
            uint32_t j;
            for (j = 0; j < poll_limit; j++) {
                if ((hr(id, R_TTI_QUEUE_STATUS) & TTI_RX_DATA_QUEUE_EMPTY) == 0u) {
                    break;
                }
            }
            if (j >= poll_limit) {
                g_i3c_rx_pending[id] = 0u;
                break; /* owed bytes never arrived */
            }
            (void)hr(id, R_TTI_RX_DATA);
            {
                size_t inword =
                    (g_i3c_rx_pending[id] > I3C_FIFO_WORD) ? I3C_FIFO_WORD : g_i3c_rx_pending[id];
                g_i3c_rx_pending[id] -= inword;
                out += inword;
            }
        }
        if (got) {
            *got = out;
        }
        return err;
    }

    /* NORMAL receive: the RX descriptor's length is the ACTUAL received byte count ->
     * undersize-safe (a short transfer yields fewer bytes than the OCCP header claimed, so the
     * caller sees out < buffer_length and returns INCOMPLETE, exactly like the Cadence
     * xferred_bytes path). One descriptor per i3c frame; g_i3c_rx_pending carries the remainder
     * across the OCCP header-then-body reads so a multi-call read of one frame never re-waits
     * mid-frame. */
    /* Byte-exact oversize detection: the RX DATA queue is popped in 4-byte FIFO words, but
     * a read may want a non-word-multiple count (e.g. JUMP body=10). When `out` reaches
     * buffer_length mid-word, the remaining REAL frame bytes of that popped word are discarded
     * and still counted off g_i3c_rx_pending, so pending can reach 0 even though the frame
     * carried MORE bytes than requested. `pending != 0` alone then misses excess that fits the
     * last word's slack (JUMP desc=20=hdr8+body10+2excess: the 2 excess bytes sit in the body's
     * last-word slack -> undetected -> jump wrongly executed instead of Oversize_msg;
     * smc_occp_oversize_body_test). Accumulate those popped-not-delivered frame bytes and OR
     * them into the terminal-read overflow check below. */
    size_t excess_in_word = 0u;
    while (out < buffer_length) {
        if (g_i3c_rx_pending[id] == 0u) {
            /* Wait for the next frame's descriptor. Idle-based wait + RX streaming: the
             * descriptor is only written at frame END, so a frame still streaming on the bus can
             * outlast any fixed poll window (a plain poll bound can expire mid-frame -> spurious
             * INCOMPLETE -> an unsolicited error response desyncs the OCCP response stream;
             * smc_occp_invalid_cmd_test). Instead, drain arriving data words into the staging
             * buffer while waiting -- each drained word RESETS the window (Cadence "consecutive
             * empty polls" semantics) and, as a bonus, keeps the 256 B TTI RX data queue from
             * overflow-dropping on frames larger than the queue (smc_occp_unsecure_boot_test,
             * 1036 B bootcode writes). Only truly idle polls (no descriptor, nothing to drain)
             * count toward the timeout. */
            bool have_desc = false;
            uint32_t idle = 0;
            while (idle < poll_limit) {
                uint32_t st = hr(id, R_TTI_QUEUE_STATUS);
                if ((st & TTI_RX_DESC_QUEUE_EMPTY) == 0u) {
                    have_desc = true;
                    break;
                }
                if ((st & TTI_RX_DATA_QUEUE_EMPTY) == 0u) {
                    bool stage_free = (g_i3c_rx_stage_len == g_i3c_rx_stage_pos);
                    if (stage_free) { /* claim the (empty) stage for this controller */
                        g_i3c_rx_stage_len = 0u;
                        g_i3c_rx_stage_pos = 0u;
                        g_i3c_rx_stage_owner = id;
                    }
                    if (g_i3c_rx_stage_owner == id &&
                        (uint32_t)g_i3c_rx_stage_len + I3C_FIFO_WORD <= I3C_RX_STAGE_SIZE) {
                        i3c_word_u w;
                        w.word = hr(id, R_TTI_RX_DATA);
                        for (size_t b = 0; b < I3C_FIFO_WORD; b++) {
                            g_i3c_rx_stage[g_i3c_rx_stage_len++] = w.bytes[b];
                        }
                        idle = 0; /* progress: the frame is still arriving */
                        continue;
                    }
                }
                idle++;
            }
            if (!have_desc) {
                err = I3C_ERR_INCOMPLETE;
                break; /* no (more) frame -> short */
            }
            uint32_t desc = hr(id, R_TTI_RX_DESC);
            g_i3c_rx_pending[id] = TTI_RXDESC_LEN(desc);
            /* Cadence-contract parity: a descriptor error flag means the frame lost bytes
             * (RX queue overflow drop) -> the data is truncated. Report I3C_ERR_INCOMPLETE like
             * the Cadence short-read path. I3C_ERR_CMD_FAILED is NOT in occp's status map
             * (only OK/INCOMPLETE/OVERFLOW/TIMEOUT are) and would fall through as an interface
             * error instead of triggering the transport-recovery path. */
            if (TTI_RXDESC_ERR(desc) != 0u) {
                err = I3C_ERR_INCOMPLETE;
            }
            /* The staged bytes are the head of THIS frame. The final drained word may carry up
             * to 3 pad bytes beyond the frame length (word-granular pops) -- clamp them off. */
            if (g_i3c_rx_stage_owner == id &&
                (size_t)(g_i3c_rx_stage_len - g_i3c_rx_stage_pos) > g_i3c_rx_pending[id]) {
                g_i3c_rx_stage_len = (uint16_t)(g_i3c_rx_stage_pos + g_i3c_rx_pending[id]);
            }
            if (g_i3c_rx_pending[id] == 0u) {
                break; /* empty transfer */
            }
        }

        /* Serve staged bytes first (they are the oldest bytes of the current frame), in the
         * same word-granular chunks as the queue path so cross-call alignment is unchanged. */
        if (g_i3c_rx_stage_owner == id && g_i3c_rx_stage_pos < g_i3c_rx_stage_len) {
            size_t staged = (size_t)(g_i3c_rx_stage_len - g_i3c_rx_stage_pos);
            size_t chunk =
                (g_i3c_rx_pending[id] > I3C_FIFO_WORD) ? I3C_FIFO_WORD : g_i3c_rx_pending[id];
            if (chunk > staged) {
                chunk = staged;
            }
            size_t wrote = 0;
            for (size_t b = 0; b < chunk && out < buffer_length; b++) {
                buffer[out++] = g_i3c_rx_stage[g_i3c_rx_stage_pos + b];
                wrote++;
            }
            g_i3c_rx_stage_pos = (uint16_t)(g_i3c_rx_stage_pos + chunk);
            g_i3c_rx_pending[id] -= chunk;
            excess_in_word += (chunk - wrote); /* staged frame bytes past buffer_length = excess */
            if (g_i3c_rx_stage_pos == g_i3c_rx_stage_len) { /* stage drained: release it */
                g_i3c_rx_stage_len = 0u;
                g_i3c_rx_stage_pos = 0u;
            }
            continue;
        }

        uint32_t j;
        for (j = 0; j < poll_limit; j++) {
            if ((hr(id, R_TTI_QUEUE_STATUS) & TTI_RX_DATA_QUEUE_EMPTY) == 0u) {
                break;
            }
        }
        if (j >= poll_limit) {
            err = I3C_ERR_INCOMPLETE;
            break;
        }

        i3c_word_u w;
        w.word = hr(id, R_TTI_RX_DATA);
        size_t inword =
            (g_i3c_rx_pending[id] > I3C_FIFO_WORD) ? I3C_FIFO_WORD : g_i3c_rx_pending[id];
        size_t wrote = 0;
        for (size_t b = 0; b < inword && out < buffer_length; b++) {
            buffer[out++] = w.bytes[b];
            wrote++;
        }
        g_i3c_rx_pending[id] -= inword;
        excess_in_word += (inword - wrote); /* real frame bytes popped past buffer_length */
    }

    /* Oversize body / excess-byte contract (mirrors the Cadence driver): when the caller does
     * NOT expect the frame to continue (expect_excess_bytes=0, i.e. this read should consume the
     * frame exactly), any remaining frame remainder means the wire carried MORE bytes than the
     * protocol layer declared (oversize). If this parameter were ignored, the excess would stay
     * in g_i3c_rx_pending with no error and no flush (the command "succeeded"), so the NEXT
     * command's header would be consumed against a stale remainder and parsed shifted ->
     * OCCP_CORRUPT_HEADER (smc_occp_oversize_body_test). Discard the excess (it is already fully
     * resident: the RX descriptor is only written at frame end), clear the remainder, and report
     * OVERFLOW so the OCCP layer runs its transport-error recovery like the Cadence path does.
     * expect_excess_bytes=1 (e.g. a header read with the body still to come) keeps the remainder
     * across calls -- that is the undersize-safe mechanism, unchanged. */
    if (!expect_excess_bytes && (err == I3C_OK) &&
        (g_i3c_rx_pending[id] != 0u || excess_in_word != 0u)) {
        if (g_i3c_rx_stage_owner == id && g_i3c_rx_stage_pos < g_i3c_rx_stage_len) {
            /* part of the excess is already staged: discard it and discount the ledger */
            size_t staged = (size_t)(g_i3c_rx_stage_len - g_i3c_rx_stage_pos);
            g_i3c_rx_pending[id] -= (staged > g_i3c_rx_pending[id]) ? g_i3c_rx_pending[id] : staged;
            g_i3c_rx_stage_len = 0u;
            g_i3c_rx_stage_pos = 0u;
        }
        while (g_i3c_rx_pending[id] != 0u) {
            if ((hr(id, R_TTI_QUEUE_STATUS) & TTI_RX_DATA_QUEUE_EMPTY) != 0u) {
                break;
            }
            (void)hr(id, R_TTI_RX_DATA);
            g_i3c_rx_pending[id] -=
                (g_i3c_rx_pending[id] > I3C_FIFO_WORD) ? I3C_FIFO_WORD : g_i3c_rx_pending[id];
        }
        g_i3c_rx_pending[id] = 0u;
        err = I3C_ERR_OVERFLOW;
    }

    if (got) {
        *got = out;
    }
    return err;
}

/*--------------------------------------------------------------------------
 *  Controller bring-up.  (== Cadence I3C_Start)
 *  Mirrors i3c_api_smc.py initialize() + configure_timing_od_i3c() +
 *  configure_thresholds(). Polled: signal-enable is optional, but we set the
 *  status-enable bits so PIO_INTR_STATUS reflects tx/rx/resp/cmd-queue.
 *------------------------------------------------------------------------*/
static I3C_Status I3C_Start(I3C_Driver *drv) {
    if (!drv->ctx.initialized) {
        return I3C_ERR_HW;
    }
    uint8_t id = drv->ctx.controller_id;

    /* TARGET (subordinate) role -> TTI bring-up (the path occp.c uses) */
    if (drv->ctx.role == SUBORDINATE) {
        return hci_target_start(drv);
    }

    /* --- CONTROLLER (MANAGER) role: PIO bring-up --- */
    /* HC_CONTROL: enable bus + PIO mode */
    hw(id, R_HC_CONTROL, HC_BUS_ENABLE | HC_MODE_PIO);

    /* Active Controller Mode (Table-5 encoding = 3) + target-xact enable */
    hw(id, R_STBY_CR, STBYCR_ENABLE_INIT(3u) | STBYCR_TARGET_XACT);

    /* PIO interrupt STATUS enables (so PIO_INTR_STATUS reflects the events we poll) */
    hw(id, R_PIO_INTR_SE, PI_TX_THLD | PI_RX_THLD | PI_RESP_READY | PI_CMD_QUEUE_READY);

    /* Open-drain bus timing (boot defaults; required to drive SCL) */
    hci_program_od_timing(id);

    /* Thresholds: tx_buf=1, rx_buf=1; cmd_empty=1, resp=1 */
    hw(id, R_DBTC, (1u << DBTC_TX_BUF_SHIFT) | (1u << DBTC_RX_BUF_SHIFT));
    hw(id, R_QTC, (1u << QTC_CMD_EMPTY_SHIFT) | (1u << QTC_RESP_BUF_SHIFT));

    /* Enable PIO queues (RS=1) */
    hw(id, R_PIO_CONTROL, PIO_EN | PIO_RS);
    return I3C_OK;
}

/*--------------------------------------------------------------------------
 *  DAT entry. (new vs Cadence; controller transfers reference a DAT index,
 *  not an inline address.)  Mirrors i3c_api_smc.py set_dat_entry.
 *------------------------------------------------------------------------*/
static void set_dat_entry(uint8_t id, uint8_t idx, uint8_t static_addr, uint8_t dynamic_addr) {
    uint32_t dat_lo =
        ((uint32_t)(static_addr & 0x7Fu)) | (((uint32_t)(dynamic_addr & 0x7Fu)) << 16);
    write_reg(I3C_A(id, R_DAT_BASE) + (uint64_t)idx * 8u, dat_lo);
    write_reg(I3C_A(id, R_DAT_BASE) + (uint64_t)idx * 8u + 4u, 0u);
}

/*--------------------------------------------------------------------------
 *  SETDASA (static -> dynamic).  Mirrors i3c_api_smc.py send_setdasa.
 *------------------------------------------------------------------------*/
static I3C_Status hci_setdasa(I3C_Driver *drv, uint8_t static_addr, uint8_t dynamic_addr,
                              uint8_t dat_idx) {
    uint8_t id = drv->ctx.controller_id;
    set_dat_entry(id, dat_idx, static_addr, dynamic_addr);
    uint32_t cmd_lo =
        ATTR_ADDR_ASSIGN | CMD_CCC(0x87u) | CMD_DEVIDX(dat_idx) | (1u << 26) | CMD_WROC | CMD_TOC;
    hw(id, R_CMD_PORT, cmd_lo);
    hw(id, R_CMD_PORT, 0u); /* cmd_hi */
    return hci_wait_response(id, NULL);
}

/* The ROM is an OCCP target: controller-side DAA and CCCs are not supported. */
static I3C_Status I3C_IssueSETGRPA(I3C_Driver *drv, uint8_t da, uint8_t group_addr) {
    (void)drv;
    (void)da;
    (void)group_addr;
    return I3C_ERR_HW;
}

static I3C_Status I3C_IssueENTDAA(I3C_Driver *drv) {
    (void)drv;
    return I3C_ERR_HW;
}

static I3C_Status I3C_ProcessDevices(I3C_Driver *drv, I3C_DeviceInfo *devices, size_t max_devices) {
    (void)drv;
    (void)devices;
    (void)max_devices;
    return I3C_ERR_HW;
}

/*--------------------------------------------------------------------------
 *  Private write. Mirrors i3c_api_smc.py private_write:
 *  regular write descriptor (attr=0, data_len in cmd_hi[31:16]) + push bytes
 *  to TX_DATA_PORT while TX_THLD has space, then read RESPONSE_PORT.
 *------------------------------------------------------------------------*/
static I3C_Status hci_write_xfer(I3C_Driver *drv, uint8_t dat_idx, const uint8_t *data,
                                 size_t length) {
    uint8_t id = drv->ctx.controller_id;

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

    /* stream bytes; fill whenever TX threshold reports space, until response ready */
    size_t written = 0;
    for (uint32_t spin = 0; spin < I3C_POLL_LIMIT; spin++) {
        uint32_t st = hr(id, R_PIO_INTR);
        if (st & PI_RESP_READY) {
            break;
        }
        if (written < length && (st & PI_TX_THLD)) {
            i3c_word_u w;
            w.word = 0;
            size_t rem = length - written;
            size_t n = (rem > I3C_FIFO_WORD) ? I3C_FIFO_WORD : rem;
            for (size_t b = 0; b < n; b++) {
                w.bytes[b] = data[written + b];
            }
            hw(id, R_TX_PORT, w.word);
            written += n;
        }
    }

    /* Cadence-contract parity: if no RESPONSE ever arrives, return I3C_ERR_TIMEOUT like
     * the Cadence wait_command path. resp=0 is a legal descriptor value, so a poll-exhaust must
     * not fall through RESP_ERR(0)==0 into a false I3C_OK. */
    uint32_t resp = 0;
    bool have_resp = false;
    for (uint32_t i = 0; i < I3C_POLL_LIMIT; i++) {
        if (hr(id, R_PIO_INTR) & PI_RESP_READY) {
            resp = hr(id, R_RESP_PORT);
            have_resp = true;
            break;
        }
    }
    if (!have_resp) {
        return I3C_ERR_TIMEOUT;
    }
    if (RESP_ERR(resp) != 0u) {
        decode_cmdr_error((uint8_t)RESP_ERR(resp));
        return I3C_ERR_CMD_FAILED;
    }
    return I3C_OK;
}

/*--------------------------------------------------------------------------
 *  Private read. Mirrors i3c_api_smc.py private_read controller side:
 *  regular read descriptor (rnw=1, data_len in cmd_hi) + drain RX_DATA_PORT;
 *  the true byte count is RESPONSE_PORT.data_length.
 *------------------------------------------------------------------------*/
static I3C_Status hci_read_xfer(I3C_Driver *drv, uint8_t dat_idx, uint8_t *buffer, size_t length,
                                size_t *got) {
    uint8_t id = drv->ctx.controller_id;

    for (uint32_t i = 0; i < I3C_POLL_LIMIT; i++) {
        if (hr(id, R_PIO_INTR) & PI_CMD_QUEUE_READY) {
            break;
        }
    }

    uint32_t cmd_lo = ATTR_REGULAR | CMD_DEVIDX(dat_idx) | CMD_RNW | CMD_WROC | CMD_TOC;
    uint32_t cmd_hi = (uint32_t)length << 16;
    hw(id, R_CMD_PORT, cmd_lo);
    hw(id, R_CMD_PORT, cmd_hi);

    /* Cadence-contract parity: the TRUE byte count of a read is RESPONSE_PORT.data_length
     * (== Cadence xferred_bytes). Blindly draining RX_PORT until `read == length` on RESP_READY
     * would pop an empty queue (stale words) on a short/target-terminated read and make `got`
     * always equal `length`, so callers could never detect a short read. Stream RX words while
     * the transfer runs; once the RESPONSE arrives, pop it FIRST, then drain exactly
     * min(RESPONSE.data_length, length) (all data is resident by then). A poll-exhaust with no
     * RESPONSE returns I3C_ERR_TIMEOUT (not a false I3C_OK via RESP_ERR(0)==0). */
    size_t read = 0;
    uint32_t resp = 0;
    bool have_resp = false;
    for (uint32_t spin = 0; spin < I3C_POLL_LIMIT; spin++) {
        uint32_t st = hr(id, R_PIO_INTR);
        if (st & PI_RESP_READY) {
            resp = hr(id, R_RESP_PORT);
            have_resp = true;
            break;
        }
        if ((st & PI_RX_THLD) && read < length) {
            i3c_word_u w;
            w.word = hr(id, R_RX_PORT);
            size_t rem = length - read;
            size_t n = (rem > I3C_FIFO_WORD) ? I3C_FIFO_WORD : rem;
            for (size_t b = 0; b < n; b++) {
                buffer[read + b] = w.bytes[b];
            }
            read += n;
        }
    }
    if (!have_resp) {
        if (got) {
            *got = read;
        }
        return I3C_ERR_TIMEOUT;
    }

    size_t actual = (size_t)RESP_LEN(resp);
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
    if (read > actual) {
        read = actual; /* streamed words may overshoot a non-word-aligned tail */
    }

    if (got) {
        *got = read;
    }
    if (RESP_ERR(resp) != 0u) {
        decode_cmdr_error((uint8_t)RESP_ERR(resp));
        return I3C_ERR_CMD_FAILED;
    }
    return I3C_OK;
}

/*--------------------------------------------------------------------------
 *  Public API bodies (same signatures as the Cadence driver).
 *  da is the target's dynamic address; we map it 1:1 to DAT index 0 for v1
 *  (single-target ROM use). Multi-target: extend with a da->dat_idx table.
 *------------------------------------------------------------------------*/
static I3C_Status I3C_Write(I3C_Driver *drv, uint8_t da, const uint8_t *data, size_t length) {
    if (!drv->ctx.initialized) {
        return I3C_ERR_HW;
    }
    (void)da;
    return hci_write_xfer(drv, 0u, data, length);
}

static I3C_Status I3C_Read(I3C_Driver *drv, uint8_t da, uint8_t *buffer, size_t length,
                           uint32_t timeout) {
    if (!drv->ctx.initialized) {
        return I3C_ERR_HW;
    }
    (void)da;
    (void)timeout;
    size_t got = 0;
    I3C_Status st = hci_read_xfer(drv, 0u, buffer, length, &got);
    if (st != I3C_OK || got != length) {
        return I3C_ERR_CMD_FAILED;
    }
    return I3C_OK;
}

/* fifo_write/fifo_read: thin shims over the transfer helpers (HCI has no
 * separately-addressable FIFO outside a command, unlike Cadence). */
static I3C_Status fifo_write(I3C_Driver *drv, const uint8_t *data, size_t length) {
    if (drv == NULL || !drv->ctx.initialized) {
        return I3C_ERR_HW;
    }
    /* target mode: arm a read-response over the TTI (== Cadence target fifo_write) */
    if (drv->ctx.role == SUBORDINATE) {
        return hci_target_tx(drv, data, length);
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
                                        size_t length, uint32_t timeout) {
    (void)timeout;
    return I3C_SendPayload(drv, addr, data, length);
}

static uint32_t I3C_CheckRxFifo(I3C_Driver *drv) {
    if (drv == NULL || !drv->ctx.initialized) {
        return 0;
    }
    uint8_t id = drv->ctx.controller_id;
    if (drv->ctx.role == SUBORDINATE) {
        /* target: report the CURRENT RX data fill as a LEVEL, mirroring the Cadence driver's
         * RX_FIFO_STATUS.rx_fifo_fill_lvl read (and hci_target_rx's QUEUE_STATUS use).
         * INTERRUPT_STATUS.RX_DESC_THLD|RX_DATA_THLD are write-edge-gated watermark bits: after
         * the OCCP layer flushes the RX FIFO and/or the target sends an error response, the edge
         * does NOT re-assert for the next inbound command, so an edge-based gate returns 0
         * forever and the OCCP command loop wedges. RX_DATA_QUEUE_DEPTH is a true level
         * (current DWORD entries), re-readable and non-destructive; x4 -> bytes to match the
         * byte-count semantics the OCCP flush loop and the Cadence driver expect. */
        uint32_t rx_dwords = TTI_RX_DATA_QUEUE_DEPTH(hr(id, R_TTI_DATA_QUEUE_DEPTH));
        return rx_dwords * 4u;
    }
    /* controller: rx fill reflected by RX_THLD (exact level is in a queue-status reg) */
    return (hr(id, R_PIO_INTR) & PI_RX_THLD) ? 1u : 0u;
}

static I3C_Status I3C_ReceivePayload(I3C_Driver *drv, uint8_t *buffer, size_t buffer_length,
                                     size_t *bytes_received) {
    if (drv == NULL || !drv->ctx.initialized || buffer == NULL) {
        return I3C_ERR_HW;
    }
    /* target mode: drain an inbound write from the TTI RX queue (non-stream API is never the
     * flush path; it also has no excess-bytes contract, so keep the lenient legacy behavior). */
    if (drv->ctx.role == SUBORDINATE) {
        return hci_target_rx(drv, buffer, buffer_length, bytes_received, false, true, 0u);
    }
    return hci_read_xfer(drv, 0u, buffer, buffer_length, bytes_received);
}

static I3C_Status I3C_ReceivePayloadStream(I3C_Driver *drv, uint8_t *buffer, size_t buffer_length,
                                           size_t *bytes_received, uint32_t timeout,
                                           bool expect_excess_bytes, bool is_flush) {
    if (drv == NULL || !drv->ctx.initialized || buffer == NULL) {
        return I3C_ERR_HW;
    }
    /* target mode: is_flush distinguishes a residual-discard drain (no descriptor coming) from a
     * normal descriptor-based receive (undersize-safe); expect_excess_bytes tells us whether the
     * frame may legitimately continue past this read (header read) or must end exactly here
     * (body read -> leftover = oversize, see hci_target_rx). */
    if (drv->ctx.role == SUBORDINATE) {
        return hci_target_rx(drv, buffer, buffer_length, bytes_received, is_flush,
                             expect_excess_bytes, timeout);
    }
    return hci_read_xfer(drv, 0u, buffer, buffer_length, bytes_received);
}

/* set_payload_length: the OCCP layer calls this before fifo_write to advertise the
 * read-response byte count. On the Cadence core that programs SLV_CTRL.pr_pl; on the
 * HCI core the equivalent count is written as the TTI TX descriptor inside fifo_write()
 * (hci_target_tx), so there is nothing to program here. */
static void I3C_SetPayloadLength(I3C_Driver *drv, uint16_t length) {
    (void)drv;
    (void)length;
}

/*--------------------------------------------------------------------------
 *  Driver instance factory (same shape as the Cadence driver).
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
        drv->set_payload_length = I3C_SetPayloadLength;
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
