/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * OCAH SEP ROM - OpenTitan SPI Host driver.
 *
 * The OpenTitan SPI host (block "SPI_CONTROLLER") is a command + FIFO controller:
 * it has no memory-mapped flash window. To read flash we push an opcode/address
 * into TXDATA, issue a COMMAND segment, and drain the returned bytes from RXDATA
 * — by CPU programmed I/O (ot_spi_flash_read) or the secure DMA on the RX-watermark
 * handshake (ot_spi_flash_read_dma); boot_flash.h selects which at build time. A
 * read is chunked to the RX-FIFO depth (OT_SPI_RX_FIFO_BYTES) and larger reads loop
 * over CSAAT-chained segments.
 *
 * Freestanding ROM environment (no libc). Register access uses the absolute
 * addresses and field unions from sep.h via the ROM MMIO helpers.
 * All timing/device parameters come from the active entry of the parameter table
 * (sep_ot_spi_profiles.h) so a new attached flash part is a one-row table edit.
 */

#include <stdbool.h>
#include <stdint.h>

#include "errors.h" /* status codes + simputs/simputshex32 helpers */
#include "rom_mmio.h"
#include "harden.h" /* fault-injection value launder (harden_u32)  */
#include "sep.h"

#include "sep_ot_spi.h"
#include "sep_ot_flash_opcodes.h"
#include "sep_ot_spi_profiles.h"
#include "sep_helpers.h" /* contains_range: 32-bit bounded-memory check   */

/* CMD.direction encodings. */
#define OT_DIR_DUMMY 0u
#define OT_DIR_RX 1u
#define OT_DIR_TX 2u
#define OT_DIR_BIDIR 3u

/* Upper bound on a status-poll spin. The boot flow is single-threaded and must
 * not spin unbounded on a stuck controller; on expiry the caller maps this to a
 * transport error rather than hanging. */
#define OT_SPI_POLL_MAX 2000000u

/* ── Driver state ─────────────────────────────────────────────────────────── */

static uint16_t g_sysclk_mhz;
static const ot_spi_params_t *g_profile = &ot_spi_profiles[0];

/* ── Small helpers ────────────────────────────────────────────────────────── */

/* CFG.CLKDIV so that f_sck = f_sys / (2 * (CLKDIV + 1)). */
static uint16_t ot_calc_clkdiv(uint16_t sysclk_mhz, uint16_t sck_mhz) {
    if (sck_mhz == 0u) {
        sck_mhz = 25u;
    }
    if (sysclk_mhz == 0u) {
        return 0u;
    }
    uint32_t div = (uint32_t)sysclk_mhz / (2u * (uint32_t)sck_mhz);
    if (div > 0u) {
        div -= 1u;
    }
    if (div > 0xFFFFu) {
        div = 0xFFFFu;
    }
    return (uint16_t)div;
}

static bool ot_rx_wait_data(void) {
    spi_controller__STATUS_t status;
    for (uint32_t i = 0u; i < OT_SPI_POLL_MAX; i++) {
        status.w = mmio_read32(OCH_SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
        if (!status.f.RXEMPTY) {
            return true;
        }
    }
    return false;
}

/* Flush the TX and RX FIFOs (and reset the datapath), preserving the enabled
 * config. Used to start every read from a known-empty state so residual bytes
 * from a prior or aborted transfer can never leak into the next one.
 *
 * CONTROL.SW_RST is a level: the core, both data FIFOs and the command queue stay
 * held in reset until software clears it, so the release below is what makes the
 * controller usable again. The CDC FIFOs drain rather than reset, so both must
 * read empty before that release. The drain poll is bounded; a controller that
 * never drains is released anyway and surfaces as a timeout in the transfer that
 * follows. */
static void ot_spi_flush_fifos(void) {
    spi_controller__CONTROL_t ctrl;
    ctrl.w = mmio_read32(OCH_SEP_TOP_SPI_CONTROLLER_CONTROL_BASE_ADDR);
    ctrl.f.SW_RST = 1u;
    mmio_write32(OCH_SEP_TOP_SPI_CONTROLLER_CONTROL_BASE_ADDR, ctrl.w);

    spi_controller__STATUS_t status;
    for (uint32_t i = 0u; i < OT_SPI_POLL_MAX; i++) {
        status.w = mmio_read32(OCH_SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
        if (status.f.TXEMPTY && status.f.RXEMPTY && !status.f.ACTIVE) {
            break;
        }
    }

    ctrl.f.SW_RST = 0u;
    mmio_write32(OCH_SEP_TOP_SPI_CONTROLLER_CONTROL_BASE_ADDR, ctrl.w);
}

/* ── Configuration + bring-up ─────────────────────────────────────────────── */

void ot_spi_set_sysclk(uint16_t freq_mhz) {
    g_sysclk_mhz = freq_mhz;
}

void ot_spi_select_profile(uint32_t index) {
    if (index < OT_SPI_PROFILE_COUNT) {
        g_profile = &ot_spi_profiles[index];
    } else {
        g_profile = &ot_spi_profiles[0];
    }
}

/* RX watermark (in FIFO words) for a profile, clamped to what the RX FIFO can
 * reach. The controller raises the watermark event when the FIFO level is
 * >= rx_watermark (spi_controller_data_fifos.sv), and the FIFO is OT_SPI_RX_FIFO_WORDS
 * deep, so a larger value would never fire and the DMA drain would stall; zero
 * would fire on an empty FIFO. Used for both the CTRL watermark and the matching
 * DMA chunk size so the two always agree. */
static uint32_t ot_rx_watermark_words(const ot_spi_params_t *p) {
    uint32_t wm = (uint32_t)p->rx_watermark;
    if (wm == 0u) {
        return 1u;
    }
    if (wm > OT_SPI_RX_FIFO_WORDS) {
        return OT_SPI_RX_FIFO_WORDS;
    }
    return wm;
}

/* Controller-ready poll (defined with the transaction primitives below). */
static int ot_spi_wait_ready(void);

/* Program controller registers from a parameter set and wait for ready. */
static uint32_t ot_apply_profile(const ot_spi_params_t *p) {

    /* Clock / mode / chip-select timing. */
    spi_controller__CONFIGOPTS_t cfg = {.w = 0u};
    cfg.f.CLKDIV = ot_calc_clkdiv(g_sysclk_mhz, p->sck_mhz);
    cfg.f.CPOL = p->cpol ? 1u : 0u;
    cfg.f.CPHA = p->cpha ? 1u : 0u;
    cfg.f.FULLCYC = p->full_cyc ? 1u : 0u;
    cfg.f.CSNIDLE = p->csnidle;
    cfg.f.CSNLEAD = p->csnlead;
    cfg.f.CSNTRAIL = p->csntrail;
    mmio_write32(OCH_SEP_TOP_SPI_CONTROLLER_CONFIGOPTS_BASE_ADDR, cfg.w);

    /* Single chip-select (CS0). */
    mmio_write32(OCH_SEP_TOP_SPI_CONTROLLER_CSID_BASE_ADDR, 0u);

    /* Enable the controller and its output drivers; set the RX watermark used to
     * pace the DMA drain of the RX FIFO. */
    uint32_t rx_wm = ot_rx_watermark_words(p);
    if (rx_wm != (uint32_t)p->rx_watermark) {
        simputshex32("OT_SPI: rx_watermark out of range, clamped from=", (uint32_t)p->rx_watermark);
    }
    spi_controller__CONTROL_t ctrl = {.w = 0u};
    ctrl.f.SPIEN = 1u;
    ctrl.f.OUTPUT_EN = 1u;
    ctrl.f.RX_WATERMARK = rx_wm;
    mmio_write32(OCH_SEP_TOP_SPI_CONTROLLER_CONTROL_BASE_ADDR, ctrl.w);

    /* Clear any latched error bits (write-1-to-clear). */
    mmio_write32(OCH_SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR, 0xFFFFFFFFu);

    if (ot_spi_wait_ready() != 0) {
        return SEP_MSG_SPI_OT_INIT_FAILED;
    }
    return OT_SPI_OK;
}

__attribute__((weak)) void ot_spi_select_pad_mux(void) {
}

uint32_t ot_spi_init(void) {
    ot_spi_select_pad_mux();
    /* Select the boot profile: build-time default BOOT_OT_SPI_PROFILE (0 = safe
     * default). Deferred runtime auto-selection (device probe / OTP fuse) will
     * replace this fixed choice here. */
    ot_spi_select_profile(BOOT_OT_SPI_PROFILE);
    uint32_t rc = ot_apply_profile(g_profile);
    if (rc != OT_SPI_OK) {
        simputs("OT_SPI: controller not ready\n");
        return rc;
    }
    simputs("OT_SPI: init ok\n");
    return OT_SPI_OK;
}

uint32_t ot_spi_reinit(void) {
    return ot_apply_profile(g_profile ? g_profile : &ot_spi_profiles[0]);
}

/* ── Transaction primitives (internal) ────────────────────────────────────── */

static int ot_spi_wait_ready(void) {
    spi_controller__STATUS_t status;
    for (uint32_t i = 0u; i < OT_SPI_POLL_MAX; i++) {
        status.w = mmio_read32(OCH_SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
        if (status.f.READY) {
            return 0;
        }
    }
    return -1;
}

static int ot_spi_segment(uint8_t dir, uint8_t speed, uint16_t len_bytes, bool csaat) {
    if (len_bytes == 0u || len_bytes > OT_SPI_SEG_MAX_BYTES) {
        return -1;
    }
    if (ot_spi_wait_ready() != 0) {
        return -1;
    }
    spi_controller__COMMAND_t cmd = {.w = 0u};
    cmd.f.LEN = (uint32_t)(len_bytes - 1u); /* LEN encodes count - 1 */
    cmd.f.CSAAT = csaat ? 1u : 0u;
    cmd.f.SPEED = (uint32_t)speed & 0x3u;
    cmd.f.DIRECTION = (uint32_t)dir & 0x3u;
    mmio_write32(OCH_SEP_TOP_SPI_CONTROLLER_COMMAND_BASE_ADDR, cmd.w);
    return 0;
}

static int ot_spi_tx_word(uint32_t w) {
    spi_controller__STATUS_t status;
    for (uint32_t i = 0u; i < OT_SPI_POLL_MAX; i++) {
        status.w = mmio_read32(OCH_SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
        if (!status.f.TXFULL) {
            mmio_write32(OCH_SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR(0), w);
            return 0;
        }
    }
    return -1; /* TX FIFO stayed full: controller stuck, don't push blindly */
}

static uint32_t ot_spi_error_status(void) {
    uint32_t v = mmio_read32(OCH_SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR);
    if (v != 0u) {
        mmio_write32(OCH_SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR, v); /* write-1-to-clear */
    }
    return v;
}

/* ── Destination policy (extension point) ─────────────────────────────────────
 *
 * The single place that knows which SEP locations a flash read may target and how
 * the DMA reaches each one. The boot ROM only stages into SEP SRAM, so that is the
 * sole destination declared here. To repurpose the driver for another destination
 * (ICCM, SMC SRAM, a SoC window, …):
 *   1. add its {base, size, dst_asid} row to ot_spi_dst_regions[]; and
 *   2. if the target needs bus-specific DMA handling beyond range + ASID — e.g. a
 *      non-OtInternal ASID (whose enabled-range IS hardware-enforced), or the ICCM
 *      address-remap workaround in sep_dma.c — add its case to ot_spi_dma_dst_setup().
 *
 * The transport code below is destination-agnostic: both the PIO and DMA paths
 * validate dst against this table before touching any CSR, and the DMA path drives
 * the hardware from the matched row. */

/* SECURE_DMA address-space-id nibble. The flash-read source is always the fixed
 * OT-internal RXDATA FIFO; only the destination nibble varies per region. */
#define OT_DMA_ASID_OT_INTERNAL 0x7u

typedef struct {
    uint32_t base;    /* region base (byte address)                     */
    uint32_t size;    /* region size (bytes)                            */
    uint8_t dst_asid; /* SECURE_DMA destination ASID nibble to reach it */
} ot_spi_dst_region_t;

static const ot_spi_dst_region_t ot_spi_dst_regions[] = {
    {(uint32_t)OCH_SEP_TOP_SEP_SRAM_BASE_ADDR, (uint32_t)OCH_SEP_TOP_SEP_SRAM_SIZE,
     OT_DMA_ASID_OT_INTERNAL},
};
#define OT_SPI_DST_REGION_COUNT (sizeof(ot_spi_dst_regions) / sizeof(ot_spi_dst_regions[0]))

/* Return the declared destination region wholly containing [dst, dst+len), or NULL
 * if none does. Single evaluation — used to drive destination-specific DMA setup
 * after the transfer has been validated by ot_spi_dst_valid(). */
static const ot_spi_dst_region_t *ot_spi_dst_region(uint32_t dst, uint32_t len) {
    for (uint32_t i = 0u; i < OT_SPI_DST_REGION_COUNT; i++) {
        if (contains_range(ot_spi_dst_regions[i].base, ot_spi_dst_regions[i].size, dst, len)) {
            return &ot_spi_dst_regions[i];
        }
    }
    return NULL;
}

/* Destination bound-checking layer. True iff [dst, dst+len) lies wholly within one
 * declared region. Called at the driver entry, before any CSR is touched, so an
 * out-of-range destination never reaches the hardware. Fault-injection hardened:
 * the lookup is evaluated twice over optimizer-opaque operands (harden_u32) and
 * both evaluations must resolve to the same region, so a single fault cannot carry
 * a bad destination past the gate (mirrors the caller's boot_flash_bounds_ok). */
static bool ot_spi_dst_valid(uint32_t dst, uint32_t len) {
    const ot_spi_dst_region_t *r1 = ot_spi_dst_region(dst, len);

    uint32_t dst2 = harden_u32(dst);
    uint32_t len2 = harden_u32(len);
    const ot_spi_dst_region_t *r2 = ot_spi_dst_region(dst2, len2);

    if (r1 != r2) {
        return false;
    }
    return r1 != NULL;
}

/* ── Flash read transport - PIO FIFO drain ────────────────────────────────── */

/* Issue the command header (opcode + address, optional dummy) for a read at
 * `addr`, keeping CS asserted so the RX segment can follow. Returns 0 on success. */
static int ot_issue_read_cmd(uint32_t addr) {
    const ot_spi_params_t *p = g_profile;

    /* Only 3- and 4-byte addressing is supported; reject anything else up front so
     * it cannot overrun the header buffer below (addr_bytes is a profile-table
     * value — treat it as untrusted). */
    if (p->addr_bytes != 3u && p->addr_bytes != 4u) {
        simputshex32("OT_SPI: unsupported addr_bytes=", (uint32_t)p->addr_bytes);
        return -1;
    }

    /* Assemble opcode + address bytes, most-significant address byte first. */
    uint8_t hdr[8];
    _Static_assert(sizeof(hdr) >= (1u + 4u), "hdr must hold opcode + up to a 4-byte address");
    uint32_t n = 0u;
    hdr[n++] = p->read_opcode;
    for (uint32_t k = 0u; k < (uint32_t)p->addr_bytes; k++) {
        uint32_t shift = 8u * ((uint32_t)p->addr_bytes - 1u - k);
        hdr[n++] = (uint8_t)((addr >> shift) & 0xFFu);
    }

    /* Push the header into TXDATA as little-endian words (byte 0 in bits [7:0]). */
    uint32_t nwords = (n + 3u) / 4u;
    for (uint32_t w = 0u; w < nwords; w++) {
        uint32_t word = 0u;
        for (uint32_t b = 0u; b < 4u; b++) {
            uint32_t idx = (w * 4u) + b;
            if (idx < n) {
                word |= (uint32_t)hdr[idx] << (8u * b);
            }
        }
        if (ot_spi_tx_word(word) != 0) {
            return -1;
        }
    }

    /* Send the header (TX), keep CS asserted. */
    if (ot_spi_segment(OT_DIR_TX, OT_SPI_WIDTH_STD, (uint16_t)n, true) != 0) {
        return -1;
    }

    /* Optional dummy cycles between address and data (fast/dual/quad reads). */
    if (p->dummy_cycles > 0u) {
        if (ot_spi_segment(OT_DIR_DUMMY, OT_SPI_WIDTH_STD, (uint16_t)p->dummy_cycles, true) != 0) {
            return -1;
        }
    }
    return 0;
}

uint32_t ot_spi_flash_read(uint32_t flash_off, uint32_t dst_sram, uint32_t len) {
    if (len == 0u) {
        return OT_SPI_OK;
    }

    /* Bound-checking layer: refuse a destination outside the declared regions
     * before writing a single byte. */
    if (!ot_spi_dst_valid(dst_sram, len)) {
        return SEP_MSG_SPI_OT_BOUNDS_ERROR;
    }

    /* Start from empty FIFOs and no stale error state. */
    ot_spi_flush_fifos();
    (void)ot_spi_error_status();

    uint32_t done = 0u;
    while (done < len) {
        uint32_t chunk = len - done;
        if (chunk > OT_SPI_RX_FIFO_BYTES) {
            chunk = OT_SPI_RX_FIFO_BYTES;
        }

        if (ot_issue_read_cmd(flash_off + done) != 0) {
            return SEP_MSG_SPI_OT_TRANSPORT_ERROR;
        }

        /* Data phase: read `chunk` bytes, release CS at the end of this command. */
        if (ot_spi_segment(OT_DIR_RX, g_profile->data_width, (uint16_t)chunk, false) != 0) {
            return SEP_MSG_SPI_OT_TRANSPORT_ERROR;
        }

        uint32_t rxdone = 0u;
        while (rxdone < chunk) {
            if (!ot_rx_wait_data()) {
                return SEP_MSG_SPI_OT_TRANSPORT_ERROR;
            }
            uint32_t word = mmio_read32(OCH_SEP_TOP_SPI_CONTROLLER_RXDATA_BASE_ADDR(0));
            uint32_t remain = chunk - rxdone;
            uint32_t nb = (remain < 4u) ? remain : 4u;
            for (uint32_t b = 0u; b < nb; b++) {
                mmio_write8(dst_sram + done + rxdone + b, (uint8_t)((word >> (8u * b)) & 0xFFu));
            }
            rxdone += nb;
        }
        done += chunk;
    }

    uint32_t err = ot_spi_error_status();
    if (err != 0u) {
        simputshex32("OT_SPI: read error status=", err);
        return SEP_MSG_SPI_OT_TRANSPORT_ERROR;
    }
    ot_spi_flush_fifos(); /* leave the FIFOs empty after the transfer */
    return OT_SPI_OK;
}

/* ── Flash read transport - DMA-streamed drain ────────────────────────────── */

/* SECURE_DMA field values for draining the fixed RXDATA FIFO into a destination
 * region. Written as raw register values, matching the sibling DMA code
 * (sep_dma.c). The address-space-id is composed per destination in
 * ot_spi_dma_dst_setup() from the region's dst_asid. */
#define OT_DMA_WIDTH_4B 0x2u  /* 4-byte transfer width                  */
#define OT_DMA_SRC_FIXED 0x2u /* wrap set, increment clear -> fixed src */
#define OT_DMA_DST_INCR 0x1u  /* increment -> walk the destination      */
#define OT_DMA_CTRL_GO (1u << 31)
#define OT_DMA_CTRL_INITIAL (1u << 8)
#define OT_DMA_CTRL_HSHAKE (1u << 4) /* hardware_handshake_enable              */
#define OT_DMA_CTRL_ABORT (1u << 27) /* abort: forces idle; NOT cfg_regwen-gated */
#define OT_DMA_STATUS_BUSY (1u << 0)
#define OT_DMA_STATUS_DONE (1u << 1)
#define OT_DMA_STATUS_ABORTED (1u << 2)
#define OT_DMA_STATUS_ERROR (1u << 3)
/* Latched W1C status bits (done/aborted/error) that survive a transfer until
 * explicitly cleared; cleared before arming so a poll can't see a stale value. */
#define OT_DMA_STATUS_CLEAR (OT_DMA_STATUS_DONE | OT_DMA_STATUS_ABORTED | OT_DMA_STATUS_ERROR)

/* Clear the latched DMA status left by a prior transfer or aborted attempt. In
 * hardware-handshake mode the engine stays in idle until the first watermark
 * trigger, so it does not auto-clear these bits until data actually starts
 * moving — without a pre-arm clear, the completion poll could observe a stale
 * STATUS.done from the previous read (e.g. the header before the payload) and
 * report a false early success. STATUS is W1C and the engine is idle at every
 * call site, so the write sticks. */
static void ot_spi_dma_cleanup(void) {
    mmio_write32(OCH_SEP_TOP_SECURE_DMA_STATUS_BASE_ADDR, OT_DMA_STATUS_CLEAR);
}

/* Return the DMA to a clean idle state after a failed streamed read. A failed
 * transfer can leave the engine armed, still busy (which locks every config CSR
 * behind cfg_regwen), or parked in DmaError waiting for its error bit to clear —
 * so a bare retry would write locked CSRs onto stale state and never recover.
 * CONTROL.abort is the one control not gated by cfg_regwen, so it works even
 * while busy: it forces the state machine back to idle and clears `busy`, which
 * unlocks the CSRs; the residual status bits are then cleared by the hardware
 * when the next transfer starts. Once idle we disable the DMA handshake and the
 * SPI RX-watermark event that drives it, and flush the SPI FIFOs, so no stale
 * trigger or byte survives into the next attempt. */
static void ot_dma_teardown(void) {
    /* Abort is honoured regardless of cfg_regwen, then wait (bounded) for the
     * engine to drop out of busy so the config CSRs unlock. */
    mmio_write32(OCH_SEP_TOP_SECURE_DMA_CONTROL_BASE_ADDR, OT_DMA_CTRL_ABORT);
    for (uint32_t i = 0u; i < OT_SPI_POLL_MAX; i++) {
        if (!(mmio_read32(OCH_SEP_TOP_SECURE_DMA_STATUS_BASE_ADDR) & OT_DMA_STATUS_BUSY)) {
            break;
        }
    }

    /* Disarm the handshake at both ends. CONTROL is always writable and clearing
     * it drops hardware_handshake_enable even if the abort could not clear busy;
     * the SPI EVENT_ENABLE is a controller register, unaffected by DMA regwen. */
    mmio_write32(OCH_SEP_TOP_SECURE_DMA_HANDSHAKE_INTR_ENABLE_BASE_ADDR, 0u);
    mmio_write32(OCH_SEP_TOP_SECURE_DMA_CONTROL_BASE_ADDR, 0u);
    mmio_write32(OCH_SEP_TOP_SPI_CONTROLLER_EVENT_ENABLE_BASE_ADDR, 0u);

    ot_spi_flush_fifos();
    (void)ot_spi_error_status();
}

/* Program the source and destination-side DMA CSRs for a transfer into `region`.
 * The source is always the fixed OT-internal RXDATA FIFO; the destination is an
 * incrementing buffer at `dst` reached with the region's ASID. This is the one
 * place that encodes how the DMA reaches a given destination — the extension point
 * for new targets.
 *
 * The enabled memory range is matched to the region: every transfer requires a
 * valid range (RANGE_VALID + limit >= base) or the engine faults. For an
 * OtInternal destination the hardware does not enforce this range (its
 * out-of-bounds check fires only on transfers that touch a SoC bus — the software
 * bound in ot_spi_dst_valid is what protects such a destination); matching it to
 * the region makes it a genuine hardware bound should a repurposer target a
 * SoC-bus destination. */
static void ot_spi_dma_dst_setup(const ot_spi_dst_region_t *region, uint32_t dst) {
    mmio_write32(OCH_SEP_TOP_SECURE_DMA_ENABLED_MEMORY_RANGE_BASE_BASE_ADDR, region->base);
    mmio_write32(OCH_SEP_TOP_SECURE_DMA_ENABLED_MEMORY_RANGE_LIMIT_BASE_ADDR,
                 region->base + region->size - 1u);
    mmio_write32(OCH_SEP_TOP_SECURE_DMA_RANGE_VALID_BASE_ADDR, 0x1u);

    mmio_write32(OCH_SEP_TOP_SECURE_DMA_SRC_ADDR_LO_BASE_ADDR,
                 OCH_SEP_TOP_SPI_CONTROLLER_RXDATA_BASE_ADDR(0));
    mmio_write32(OCH_SEP_TOP_SECURE_DMA_SRC_ADDR_HI_BASE_ADDR, 0u);
    mmio_write32(OCH_SEP_TOP_SECURE_DMA_DST_ADDR_LO_BASE_ADDR, dst);
    mmio_write32(OCH_SEP_TOP_SECURE_DMA_DST_ADDR_HI_BASE_ADDR, 0u);
    mmio_write32(OCH_SEP_TOP_SECURE_DMA_ADDR_SPACE_ID_BASE_ADDR,
                 ((uint32_t)region->dst_asid << 4) | OT_DMA_ASID_OT_INTERNAL);

    /* TODO(repurpose): destination-specific setup — e.g. the ICCM address-remap
     * workaround (SEP_REGION_SIZE=0) from sep_dma.c — keyed on `region`, goes here. */
}

/* Stream `dma_len` bytes (a whole multiple of `chunk_bytes`) from flash into SRAM
 * with hardware-handshake DMA: the flash streams continuously across CSAAT-chained
 * RX segments while the DMA drains the RX FIFO one chunk per watermark trigger.
 * The controller stalls SCK if the FIFO fills, so the segments cannot overflow it.
 * On any failure the DMA is torn down (see ot_dma_teardown) before returning, so
 * the caller can retry from a clean engine state. */
static uint32_t ot_dma_stream(uint32_t flash_off, uint32_t dst, uint32_t dma_len,
                              uint32_t chunk_bytes) {
    uint32_t rc = OT_SPI_OK;

    ot_spi_flush_fifos();        /* start from empty FIFOs */
    (void)ot_spi_error_status(); /* clear stale controller errors */

    /* Clear latched DMA status from a prior transfer so the completion poll below
     * cannot observe a stale STATUS.done and report a false early success. */
    ot_spi_dma_cleanup();

    /* Resolve the destination region. The caller-facing entry already validated the
     * transfer (ot_spi_dst_valid); re-resolve here, close to the CSR writes, both to
     * drive destination-specific setup and as a fault-injection backstop — a NULL
     * here means dst was corrupted after the gate, so refuse to arm. */
    const ot_spi_dst_region_t *region = ot_spi_dst_region(dst, dma_len);
    if (region == NULL) {
        rc = SEP_MSG_SPI_OT_BOUNDS_ERROR;
        goto cleanup;
    }

    /* Enable the controller's RX-watermark event, which drives the DMA trigger. */
    spi_controller__EVENT_ENABLE_t ev = {.w = 0u};
    ev.f.RXWM = 1u;
    mmio_write32(OCH_SEP_TOP_SPI_CONTROLLER_EVENT_ENABLE_BASE_ADDR, ev.w);

    /* Program the source + destination CSRs (range, addresses, ASID) for the region. */
    ot_spi_dma_dst_setup(region, dst);

    mmio_write32(OCH_SEP_TOP_SECURE_DMA_TRANSFER_WIDTH_BASE_ADDR, OT_DMA_WIDTH_4B);
    mmio_write32(OCH_SEP_TOP_SECURE_DMA_SRC_CONFIG_BASE_ADDR, OT_DMA_SRC_FIXED);
    mmio_write32(OCH_SEP_TOP_SECURE_DMA_DST_CONFIG_BASE_ADDR, OT_DMA_DST_INCR);
    mmio_write32(OCH_SEP_TOP_SECURE_DMA_TOTAL_DATA_SIZE_BASE_ADDR, dma_len);
    mmio_write32(OCH_SEP_TOP_SECURE_DMA_CHUNK_DATA_SIZE_BASE_ADDR, chunk_bytes);
    mmio_write32(OCH_SEP_TOP_SECURE_DMA_HANDSHAKE_INTR_ENABLE_BASE_ADDR, 0x1u);

    /* Arm the DMA; it now drains one chunk per RX-watermark trigger. */
    mmio_write32(OCH_SEP_TOP_SECURE_DMA_CONTROL_BASE_ADDR,
                 OT_DMA_CTRL_GO | OT_DMA_CTRL_INITIAL | OT_DMA_CTRL_HSHAKE);

    /* Issue the read command, then feed the FIFO with CSAAT-chained RX segments. */
    if (ot_issue_read_cmd(flash_off) != 0) {
        rc = SEP_MSG_SPI_OT_TRANSPORT_ERROR;
        goto cleanup;
    }
    uint32_t remaining = dma_len;
    while (remaining > 0u) {
        uint32_t chunk = (remaining > OT_SPI_RX_FIFO_BYTES) ? OT_SPI_RX_FIFO_BYTES : remaining;
        bool last = (remaining - chunk) == 0u;
        if (ot_spi_segment(OT_DIR_RX, g_profile->data_width, (uint16_t)chunk, !last) != 0) {
            rc = SEP_MSG_SPI_OT_TRANSPORT_ERROR;
            goto cleanup;
        }
        remaining -= chunk;
    }

    /* Wait (bounded) for the DMA to finish draining. */
    bool done = false;
    for (uint32_t i = 0u; i < OT_SPI_POLL_MAX; i++) {
        uint32_t st = mmio_read32(OCH_SEP_TOP_SECURE_DMA_STATUS_BASE_ADDR);
        if (st & OT_DMA_STATUS_ERROR) {
            simputshex32("OT_SPI: dma error code=",
                         mmio_read32(OCH_SEP_TOP_SECURE_DMA_ERROR_CODE_BASE_ADDR));
            rc = SEP_MSG_SPI_OT_TRANSPORT_ERROR;
            goto cleanup;
        }
        if (st & OT_DMA_STATUS_DONE) {
            done = true;
            break;
        }
    }
    if (!done) {
        rc = SEP_MSG_SPI_OT_TRANSPORT_ERROR;
        goto cleanup;
    }
    if (ot_spi_error_status() != 0u) {
        rc = SEP_MSG_SPI_OT_TRANSPORT_ERROR;
        goto cleanup;
    }
    return OT_SPI_OK; /* success: DMA drained to idle, no teardown needed */

cleanup:
    ot_dma_teardown();
    return rc;
}

/* One read attempt: DMA the chunk-aligned bulk, then read the small remainder by
 * PIO (a partial final chunk and any sub-word tail). */
static uint32_t ot_dma_read_once(uint32_t flash_off, uint32_t dst, uint32_t len) {
    uint32_t chunk_bytes = ot_rx_watermark_words(g_profile) * 4u;

    /* DMA only whole chunks, so every drain is driven by a full watermark; the
     * remainder (less than one chunk, including any sub-word tail) goes via PIO. */
    uint32_t dma_len = (len / chunk_bytes) * chunk_bytes;

    if (dma_len > 0u) {
        uint32_t rc = ot_dma_stream(flash_off, dst, dma_len, chunk_bytes);
        if (rc != OT_SPI_OK) {
            return rc;
        }
    }
    if (len > dma_len) {
        uint32_t rc = ot_spi_flash_read(flash_off + dma_len, dst + dma_len, len - dma_len);
        if (rc != OT_SPI_OK) {
            return rc;
        }
    }
    return OT_SPI_OK;
}

uint32_t ot_spi_flash_read_dma(uint32_t flash_off, uint32_t dst_sram, uint32_t len) {
    if (len == 0u) {
        return OT_SPI_OK;
    }

    /* Bound-checking layer: refuse a destination outside the declared regions
     * before any DMA CSR is programmed. */
    if (!ot_spi_dst_valid(dst_sram, len)) {
        return SEP_MSG_SPI_OT_BOUNDS_ERROR;
    }

    /* Retry a transient controller/DMA fault a bounded number of times, re-bringing
     * up the controller between attempts, before reporting the failure. */
    for (uint32_t attempt = 0u; attempt <= OT_SPI_READ_RETRY_MAX; attempt++) {
        uint32_t rc = ot_dma_read_once(flash_off, dst_sram, len);
        if (rc == OT_SPI_OK) {
            ot_spi_flush_fifos(); /* leave the FIFOs empty after the transfer */
            return OT_SPI_OK;
        }
        (void)ot_spi_reinit();
    }

    simputs("OT_SPI: dma read failed after retries\n");
    return SEP_MSG_SPI_OT_TRANSPORT_ERROR;
}
