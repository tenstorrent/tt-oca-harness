/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * OCAH SEP ROM — OpenTitan SPI Host driver (public API).
 *
 * Flash is not memory-mapped: it is reached only through command/FIFO transactions.
 * The boot path links only bring-up and read; --gc-sections drops the optional
 * write/erase code (and PIO read when the DMA path is built).
 *
 * Register bindings come from sep.h. Freestanding: no libc, no heap.
 */
#ifndef SEP_OT_SPI_H
#define SEP_OT_SPI_H

#include <stdint.h>
#include <stdbool.h>

/* Success sentinel. On failure the driver returns a registered SEP_MSG_SPI_OT_*
 * status code (defined in status_values.h, via errors.h): INIT_FAILED for bring-up,
 * TRANSPORT_ERROR for a controller/DMA read fault. A transport error is retryable —
 * the caller may retry and, failing that, fall back to the backup slot. */
#define OT_SPI_OK 0x0u

/* A single SPI command segment carries at most 512 data bytes (CMD.LEN is 9
 * bits), so a larger read loops over multiple segments. On a transport fault the
 * read is retried up to OT_SPI_READ_RETRY_MAX times before it is reported. */
#define OT_SPI_SEG_MAX_BYTES 512u
#define OT_SPI_READ_RETRY_MAX 3u

/* Depth of the controller's RX FIFO in bytes (256 B / 64 words). A read segment
 * is filled and then drained rather than streamed word-by-word, so an RX segment
 * must not request more than the FIFO can hold at once; reads are chunked to this
 * bound. */
#define OT_SPI_RX_FIFO_BYTES 256u

/* RX FIFO depth in 32-bit words. A profile's rx_watermark must not exceed this:
 * the RX-watermark event only fires once the FIFO holds that many words, so a
 * larger value would never trigger the DMA drain (the driver clamps it). */
#define OT_SPI_RX_FIFO_WORDS (OT_SPI_RX_FIFO_BYTES / 4u)
_Static_assert(OT_SPI_RX_FIFO_BYTES % 4u == 0u,
               "RX FIFO byte depth must be a whole number of 32-bit words");

/* ── Timing / device parameter sets ───────────────────────────────────────── */

/* data_width encodings map to CMD.speed: 0=std, 1=dual, 2=quad. */
#define OT_SPI_WIDTH_STD 0u
#define OT_SPI_WIDTH_DUAL 1u
#define OT_SPI_WIDTH_QUAD 2u

/* profile flags */
#define OT_SPI_PF_CYCLE_ELIGIBLE 0x1u /* try this profile when probing devices */

/* One editable timing/device profile. Every tunable SPI parameter lives here, so
 * supporting a new flash part is a one-row table edit (no code changes). The
 * table is in sep_ot_spi_profiles.h; entry [0] is the safe default (standard
 * read, mode 0). */
typedef struct {
    uint16_t sck_mhz;     /* target SCK; CFG.CLKDIV is derived from it        */
    uint8_t cpol;         /* CFG.cpol                                         */
    uint8_t cpha;         /* CFG.cpha                                         */
    uint8_t full_cyc;     /* CFG.fullcyc: sample a full SCK cycle late to     */
                          /* absorb SCK->flash->data round-trip delay         */
    uint8_t csnidle;      /* CFG.csnidle (cycles)                             */
    uint8_t csnlead;      /* CFG.csnlead                                      */
    uint8_t csntrail;     /* CFG.csntrail                                     */
    uint8_t read_opcode;  /* 0x03 default; 0x0b/0x3b/0x6b/4-byte variants     */
    uint8_t dummy_cycles; /* 0 for standard read                             */
    uint8_t data_width;   /* OT_SPI_WIDTH_*                                   */
    uint8_t addr_bytes;   /* 3 or 4                                           */
    uint8_t rx_watermark; /* FIFO words per DMA drain; 1..64 (FIFO depth)     */
    uint8_t flags;        /* OT_SPI_PF_*                                      */
} ot_spi_params_t;

/* Select the active parameter set by table index (bounds-checked; an invalid
 * index falls back to the default [0]). ot_spi_init() calls this with the
 * build-time BOOT_OT_SPI_PROFILE; a future runtime selector would call it too. */
void ot_spi_select_profile(uint32_t index);

/*
 * NOTE: a fuse-driven profile selector is intentionally NOT implemented yet — its
 * fuse field, fuse-map allocation, and read path require a dedicated OTP-usage
 * evaluation first. Boot never depends on a programmed fuse: the default,
 * explicit-index, and cycle-through selection paths work with no OTP dependency.
 * When added, the fuse read will be isolated behind ot_spi_profile_from_fuse().
 */

/* ── Controller bring-up ──────────────────────────────────────────────────── */

/* Inform the driver of the sysclk (MHz); used to derive CFG.CLKDIV.
 * Call before ot_spi_init(). */
void ot_spi_set_sysclk(uint16_t freq_mhz);

/* Select the active parameter set and bring the OpenTitan controller up:
 * CTRL(SPIEN, OUTPUT_EN, watermark), CFG(CLKDIV, mode, CSN timing), CSID=0,
 * clear ERROR_STATUS. Returns OT_SPI_OK or an error. */
uint32_t ot_spi_init(void);

/* Re-run bring-up (between transport-fault retries / slot rotation). */
uint32_t ot_spi_reinit(void);

/* ── Flash read transport (boot-critical): PIO or DMA ─────────────────────── */

/* Standard read via PIO FIFO drain (opcode/width/addr/dummy per active profile).
 * Used for small/diagnostic reads and as a simple read-path check. len may be
 * any size (loops over <=512 B segments). Returns OT_SPI_OK or an error code. */
uint32_t ot_spi_flash_read(uint32_t flash_off, uint32_t dst_sram, uint32_t len);

/* Bulk read streamed RXDATA->SRAM via hardware-handshake secure-DMA (the flash
 * streams continuously while the DMA drains the RX FIFO on its watermark). The
 * boot path uses this for the manifest header and payload. Retries a transport
 * fault internally before reporting. Returns OT_SPI_OK or an error code. */
uint32_t ot_spi_flash_read_dma(uint32_t flash_off, uint32_t dst_sram, uint32_t len);

/* ── Optional flash write/erase (not built for boot) ───────────────────────── */
#if defined(OT_SPI_ENABLE_FLASH_WRITE)
uint32_t ot_spi_flash_wren(void);
uint32_t ot_spi_flash_rdsr(uint8_t *sr);
uint32_t ot_spi_flash_page_program(uint32_t off, const uint8_t *buf, uint32_t n);
uint32_t ot_spi_flash_sector_erase(uint32_t off);
#endif

#endif /* SEP_OT_SPI_H */
