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
#include "secure_dma.h"
#include "aon_timer.h"
#include "sep_efuse_map.h"
#include "efuse_interface_ctrl.h"
#include "efuse_mmr.h"
#include "efuse_shim_ctrl.h"
#include "sep_lifecycle_ctrl.h"
#include "km_mailbox_sep.h"
#include "output_remap.h"
#include "alias_remap.h"
#include "filter_ctrl.h"
#include "axil_mailbox_sep_wrap.h"
#include "sep_cpu_ctrl.h"
#include "sep_reset_ctrl.h"
#include "spi_controller.h"
#include "sep_axi_extension.h"
#include "sep_scratch.h"
#include "el2_pic.h"

/*
 * The vendor SPI shim blocks (och_sep_cdns_spi_ctrl, och_sep_spi_mux_ctrl) have
 * no include line of their own: they are sub-blocks of sep_axi_extension, and
 * the nonfree variant of that header - which the register overlay puts ahead of
 * the open one - carries them inline. Including the per-block headers as well
 * would redeclare every type. A pure-open build resolves the open
 * sep_axi_extension.h, which has neither block, so firmware that touches them
 * needs the overlay, exactly as before.
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

#define SPI_CONTROLLER__CTRL_reset \
    (OCH_SEP_FIELD_RESET(SPI_CONTROLLER__CTRL, RX_WATERMARK) | \
     OCH_SEP_FIELD_RESET(SPI_CONTROLLER__CTRL, TX_WATERMARK) | \
     OCH_SEP_FIELD_RESET(SPI_CONTROLLER__CTRL, OUTPUT_EN) | \
     OCH_SEP_FIELD_RESET(SPI_CONTROLLER__CTRL, SW_RST) | \
     OCH_SEP_FIELD_RESET(SPI_CONTROLLER__CTRL, SPIEN))

/* Keyed off a generated field constant: the vendor blocks below are only
 * visible when the overlay supplies them. */
#ifdef OCH_SEP_SPI_MUX_CTRL__SPI_MUX_CTRL__SPI_SEL_bm
#define OCH_SEP_SPI_MUX_CTRL__SPI_MUX_CTRL_reset \
    (OCH_SEP_FIELD_RESET(OCH_SEP_SPI_MUX_CTRL__SPI_MUX_CTRL, SPI_SEL) | \
     OCH_SEP_FIELD_RESET(OCH_SEP_SPI_MUX_CTRL__SPI_MUX_CTRL, CS_FORCE_HIGH) | \
     OCH_SEP_FIELD_RESET(OCH_SEP_SPI_MUX_CTRL__SPI_MUX_CTRL, CDNS_BUSY) | \
     OCH_SEP_FIELD_RESET(OCH_SEP_SPI_MUX_CTRL__SPI_MUX_CTRL, OT_BUSY) | \
     OCH_SEP_FIELD_RESET(OCH_SEP_SPI_MUX_CTRL__SPI_MUX_CTRL, CDNS_IRQ) | \
     OCH_SEP_FIELD_RESET(OCH_SEP_SPI_MUX_CTRL__SPI_MUX_CTRL, OT_IRQ))
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
#endif

#endif /* SEP_H */
