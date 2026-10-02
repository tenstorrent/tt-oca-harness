/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * SEP firmware register umbrella.
 *
 * Hand-maintained collection of #includes (NOT generated). It pulls in the SEP
 * address header and the per-block register headers so firmware can include a
 * single header. Each include resolves from a generated location on the build's
 * search path:
 *   - sep_addr.h, the local sub-block headers: hw/sys/sep/regs/gen/c[/blocks]
 *   - hw/ip block headers: each hw/ip/<block>/regs/gen/c
 * Add a line here when a sub-block is added to sep.rdl.
 */
#ifndef SEP_H
#define SEP_H

#include "sep_addr.h"
#include "otbn.h"
#include "hmac.h"
#include "aes.h"
#include "kmac.h"
#include "csrng.h"
#include "edn.h"
#include "entropy_source.h"
#include "secure_dma.h"
#include "aon_timer.h"
#include "sep_efuse_map.h"
#include "efuse_interface_ctrl.h"
#include "efuse_mmr.h"
#include "sep_lifecycle_ctrl.h"
#include "km_mailbox_sep.h"
#include "output_remap.h"
#include "alias_remap.h"
#include "filter_ctrl.h"
#include "axil_mailbox_sep_wrap.h"
#include "sep_cpu_ctrl.h"
#include "sep_reset_ctrl.h"
#include "spi_controller.h"
#include "sep_external.h"
#include "sep_scratch.h"
#include "el2_pic.h"

/*
 * Proprietary SPI shim blocks are not included here: they live in a nonfree
 * wrapper header that an overlay would put ahead of the open sep_external.h.
 * A pure-open build has neither block. Firmware that programs them belongs
 * with that wrapper, not in this tree.
 *
 * efuse_shim_ctrl is different: both variants of sep_external.h carry it, so
 * a pure-open build still sees the open model.
 */

/*
 * Whole-register reset values.
 *
 * The generated headers carry a per-field <BLOCK>__<REG>__<FIELD>_reset but no
 * aggregate for the register, so the firmware sites that seed a register from
 * its reset state compose one here out of those generated constants. Add an
 * entry only when firmware needs it; each is an OR over every field of the
 * register, so it stays correct as the RDL changes.
 */
#define OCH_SEP_FIELD_RESET(reg, field) \
    ((uint32_t)(reg##__##field##_reset) << (reg##__##field##_bp))

#define SPI_CONTROLLER__CONTROL_reset \
    (OCH_SEP_FIELD_RESET(SPI_CONTROLLER__CONTROL, RX_WATERMARK) | \
     OCH_SEP_FIELD_RESET(SPI_CONTROLLER__CONTROL, TX_WATERMARK) | \
     OCH_SEP_FIELD_RESET(SPI_CONTROLLER__CONTROL, OUTPUT_EN) | \
     OCH_SEP_FIELD_RESET(SPI_CONTROLLER__CONTROL, SW_RST) | \
     OCH_SEP_FIELD_RESET(SPI_CONTROLLER__CONTROL, SPIEN))

#define SPI_CONTROLLER__CONFIGOPTS_reset \
    (OCH_SEP_FIELD_RESET(SPI_CONTROLLER__CONFIGOPTS, CLKDIV) | \
     OCH_SEP_FIELD_RESET(SPI_CONTROLLER__CONFIGOPTS, CSNIDLE) | \
     OCH_SEP_FIELD_RESET(SPI_CONTROLLER__CONFIGOPTS, CSNTRAIL) | \
     OCH_SEP_FIELD_RESET(SPI_CONTROLLER__CONFIGOPTS, CSNLEAD) | \
     OCH_SEP_FIELD_RESET(SPI_CONTROLLER__CONFIGOPTS, FULLCYC) | \
     OCH_SEP_FIELD_RESET(SPI_CONTROLLER__CONFIGOPTS, CPHA) | \
     OCH_SEP_FIELD_RESET(SPI_CONTROLLER__CONFIGOPTS, CPOL))

#define SPI_CONTROLLER__ERROR_ENABLE_reset \
    (OCH_SEP_FIELD_RESET(SPI_CONTROLLER__ERROR_ENABLE, CMDBUSY) | \
     OCH_SEP_FIELD_RESET(SPI_CONTROLLER__ERROR_ENABLE, OVERFLOW) | \
     OCH_SEP_FIELD_RESET(SPI_CONTROLLER__ERROR_ENABLE, UNDERFLOW) | \
     OCH_SEP_FIELD_RESET(SPI_CONTROLLER__ERROR_ENABLE, CMDINVAL) | \
     OCH_SEP_FIELD_RESET(SPI_CONTROLLER__ERROR_ENABLE, CSIDINVAL))

#define SECURE_DMA__HANDSHAKE_INTR_ENABLE_reset \
    (OCH_SEP_FIELD_RESET(SECURE_DMA__HANDSHAKE_INTR_ENABLE, MASK))

/* HMAC_EN and SHA_EN reset to 0 and the generator emits no _reset for them. */
#define HMAC__CFG_reset \
    (OCH_SEP_FIELD_RESET(HMAC__CFG, ENDIAN_SWAP) | OCH_SEP_FIELD_RESET(HMAC__CFG, DIGEST_SWAP) | \
     OCH_SEP_FIELD_RESET(HMAC__CFG, KEY_SWAP) | OCH_SEP_FIELD_RESET(HMAC__CFG, DIGEST_SIZE) | \
     OCH_SEP_FIELD_RESET(HMAC__CFG, KEY_LENGTH))

#define FILTER_CTRL__FILTER_CONFIG_reset \
    (OCH_SEP_FIELD_RESET(FILTER_CTRL__FILTER_CONFIG, READ_ALLOWED) | \
     OCH_SEP_FIELD_RESET(FILTER_CTRL__FILTER_CONFIG, WRITE_ALLOWED) | \
     OCH_SEP_FIELD_RESET(FILTER_CTRL__FILTER_CONFIG, ENTRY_ENABLED) | \
     OCH_SEP_FIELD_RESET(FILTER_CTRL__FILTER_CONFIG, ALLOW_NS) | \
     OCH_SEP_FIELD_RESET(FILTER_CTRL__FILTER_CONFIG, ALLOW_BURST) | \
     OCH_SEP_FIELD_RESET(FILTER_CTRL__FILTER_CONFIG, DATA_BUS_WIDTH) | \
     OCH_SEP_FIELD_RESET(FILTER_CTRL__FILTER_CONFIG, GROUP_ID) | \
     OCH_SEP_FIELD_RESET(FILTER_CTRL__FILTER_CONFIG, SRC_ID) | \
     OCH_SEP_FIELD_RESET(FILTER_CTRL__FILTER_CONFIG, LOCKED))

#define SEP_RESET_CTRL__SW_RESET_N_reset \
    (OCH_SEP_FIELD_RESET(SEP_RESET_CTRL__SW_RESET_N, KM_SW_RST_N) | \
     OCH_SEP_FIELD_RESET(SEP_RESET_CTRL__SW_RESET_N, OTBN_SW_RST_N) | \
     OCH_SEP_FIELD_RESET(SEP_RESET_CTRL__SW_RESET_N, AES_SW_RST_N) | \
     OCH_SEP_FIELD_RESET(SEP_RESET_CTRL__SW_RESET_N, HMAC_SW_RST_N) | \
     OCH_SEP_FIELD_RESET(SEP_RESET_CTRL__SW_RESET_N, KMAC_SW_RST_N) | \
     OCH_SEP_FIELD_RESET(SEP_RESET_CTRL__SW_RESET_N, TRNG_SW_RST_N) | \
     OCH_SEP_FIELD_RESET(SEP_RESET_CTRL__SW_RESET_N, ABR_SW_RST_N))

#define SEP_CPU_CTRL__SEP_NMI_VEC_reset \
    (OCH_SEP_FIELD_RESET(SEP_CPU_CTRL__SEP_NMI_VEC_NMI_VEC_A3690E40, RSVD) | \
     OCH_SEP_FIELD_RESET(SEP_CPU_CTRL__SEP_NMI_VEC_NMI_VEC_A3690E40, NMI_VEC))

#define SEP_CPU_CTRL__CLOCK_GATE_CTRL_reset \
    (OCH_SEP_FIELD_RESET(SEP_CPU_CTRL__CLOCK_GATE_CTRL, PKA_CG_ENABLE))

#define SEP_CPU_CTRL__SEP_LOCAL_BASE_ADDR_reset \
    (OCH_SEP_FIELD_RESET(SEP_CPU_CTRL__SEP_LOCAL_BASE_ADDR, ADDR))

#define SEP_CPU_CTRL__SEP_REGION_SIZE_reset \
    (OCH_SEP_FIELD_RESET(SEP_CPU_CTRL__SEP_REGION_SIZE, SIZE))

#define SEP_CPU_CTRL__SMU_GLOBAL_BASE_ADDR_reset \
    (OCH_SEP_FIELD_RESET(SEP_CPU_CTRL__SMU_GLOBAL_BASE_ADDR, ADDR))

#define SEP_CPU_CTRL__SMU_REGION_SIZE_reset \
    (OCH_SEP_FIELD_RESET(SEP_CPU_CTRL__SMU_REGION_SIZE, SIZE))

#define FILTER_CTRL__START_ADDR_reset (OCH_SEP_FIELD_RESET(FILTER_CTRL__START_ADDR, START_ADDR))

#define FILTER_CTRL__END_ADDR_reset (OCH_SEP_FIELD_RESET(FILTER_CTRL__END_ADDR, END_ADDR))

/* Keyed off a generated field constant: the vendor blocks below are only
 * visible when the overlay supplies them. */
#ifdef OCH_SEP_EXT_SPI_CTRL__EXT_SPI_CTRL__CS_FORCE_HIGH_bm
#define OCH_SEP_EXT_SPI_CTRL__EXT_SPI_CTRL_reset \
    (OCH_SEP_FIELD_RESET(OCH_SEP_EXT_SPI_CTRL__EXT_SPI_CTRL, CS_FORCE_HIGH) | \
     OCH_SEP_FIELD_RESET(OCH_SEP_EXT_SPI_CTRL__EXT_SPI_CTRL, CDNS_BUSY) | \
     OCH_SEP_FIELD_RESET(OCH_SEP_EXT_SPI_CTRL__EXT_SPI_CTRL, CDNS_IRQ))
#endif

#ifdef OCH_SEP_CDNS_SPI_CTRL__SPI_CTRL__SPI_ENABLE_bm
#define OCH_SEP_CDNS_SPI_CTRL__SPI_CTRL_reset \
    (OCH_SEP_FIELD_RESET(OCH_SEP_CDNS_SPI_CTRL__SPI_CTRL, SPI_ENABLE) | \
     OCH_SEP_FIELD_RESET(OCH_SEP_CDNS_SPI_CTRL__SPI_CTRL, SPI_RESET_N_N0_SCAN) | \
     OCH_SEP_FIELD_RESET(OCH_SEP_CDNS_SPI_CTRL__SPI_CTRL, SPI_CTRL_REG_RESET_N_N0_SCAN) | \
     OCH_SEP_FIELD_RESET(OCH_SEP_CDNS_SPI_CTRL__SPI_CTRL, SPI_PHY_REG_RESET_N_N0_SCAN) | \
     OCH_SEP_FIELD_RESET(OCH_SEP_CDNS_SPI_CTRL__SPI_CTRL, SPI_AXI_RESET_N_N0_SCAN) | \
     OCH_SEP_FIELD_RESET(OCH_SEP_CDNS_SPI_CTRL__SPI_CTRL, SPI_PHY_RESET_N_N0_SCAN) | \
     OCH_SEP_FIELD_RESET(OCH_SEP_CDNS_SPI_CTRL__SPI_CTRL, SPI_REG_RESET_N_N0_SCAN) | \
     OCH_SEP_FIELD_RESET(OCH_SEP_CDNS_SPI_CTRL__SPI_CTRL, SPI_XSPI_REG_RESET_N_N0_SCAN) | \
     OCH_SEP_FIELD_RESET(OCH_SEP_CDNS_SPI_CTRL__SPI_CTRL, CLOCK_GATE_ENABLE))

#define OCH_SEP_CDNS_SPI_CTRL__SPI_CLK_DIV_CTRL_reset \
    (OCH_SEP_FIELD_RESET(OCH_SEP_CDNS_SPI_CTRL__SPI_CLK_DIV_CTRL, CLOCK_DIVIDER_VALUE) | \
     OCH_SEP_FIELD_RESET(OCH_SEP_CDNS_SPI_CTRL__SPI_CLK_DIV_CTRL, CLOCK_DUTYCYCLE) | \
     OCH_SEP_FIELD_RESET(OCH_SEP_CDNS_SPI_CTRL__SPI_CLK_DIV_CTRL, CLOCK_DIV_ENABLE) | \
     OCH_SEP_FIELD_RESET(OCH_SEP_CDNS_SPI_CTRL__SPI_CLK_DIV_CTRL, CLOCK_DIV_SET))

#define OCH_SEP_CDNS_SPI_CTRL__SPI_DISCOVERY_CTRL_reset \
    (OCH_SEP_FIELD_RESET(OCH_SEP_CDNS_SPI_CTRL__SPI_DISCOVERY_CTRL, DISCOVERY_ABNUM) | \
     OCH_SEP_FIELD_RESET(OCH_SEP_CDNS_SPI_CTRL__SPI_DISCOVERY_CTRL, DISCOVERY_BANK) | \
     OCH_SEP_FIELD_RESET(OCH_SEP_CDNS_SPI_CTRL__SPI_DISCOVERY_CTRL, DISCOVERY_CMD_TYPE) | \
     OCH_SEP_FIELD_RESET(OCH_SEP_CDNS_SPI_CTRL__SPI_DISCOVERY_CTRL, DISCOVERY_DUMMY_CNT) | \
     OCH_SEP_FIELD_RESET(OCH_SEP_CDNS_SPI_CTRL__SPI_DISCOVERY_CTRL, DISCOVERY_EXTOP_EN) | \
     OCH_SEP_FIELD_RESET(OCH_SEP_CDNS_SPI_CTRL__SPI_DISCOVERY_CTRL, DISCOVERY_EXTOP_VAL) | \
     OCH_SEP_FIELD_RESET(OCH_SEP_CDNS_SPI_CTRL__SPI_DISCOVERY_CTRL, DISCOVERY_INHIBIT) | \
     OCH_SEP_FIELD_RESET(OCH_SEP_CDNS_SPI_CTRL__SPI_DISCOVERY_CTRL, DISCOVERY_NUM_LINES) | \
     OCH_SEP_FIELD_RESET(OCH_SEP_CDNS_SPI_CTRL__SPI_DISCOVERY_CTRL, \
                         DISCOVERY_SEQ_CRC_CHUNK_SIZE) | \
     OCH_SEP_FIELD_RESET(OCH_SEP_CDNS_SPI_CTRL__SPI_DISCOVERY_CTRL, DISCOVERY_SEQ_CRC_EN) | \
     OCH_SEP_FIELD_RESET(OCH_SEP_CDNS_SPI_CTRL__SPI_DISCOVERY_CTRL, DISCOVERY_SEQ_CRC_OE) | \
     OCH_SEP_FIELD_RESET(OCH_SEP_CDNS_SPI_CTRL__SPI_DISCOVERY_CTRL, \
                         DISCOVERY_SEQ_CRC_UAL_CHUNK_CHK) | \
     OCH_SEP_FIELD_RESET(OCH_SEP_CDNS_SPI_CTRL__SPI_DISCOVERY_CTRL, \
                         DISCOVERY_SEQ_CRC_UAL_CHUNK_EN) | \
     OCH_SEP_FIELD_RESET(OCH_SEP_CDNS_SPI_CTRL__SPI_DISCOVERY_CTRL, DISCOVERY_SEQ_CRC_VARIANT))
#endif

#endif /* SEP_H */
