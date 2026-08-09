/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * SPI pad mux helper.
 *
 * The SEP shares one set of SPI pads between the Cadence xSPI controller and
 * the OpenTitan SPI host. SPI_MUX_CTRL.spi_sel picks which one drives them, and
 * cs_force_high holds CS# high until software is ready. Out of reset the mux
 * points at Cadence with CS# forced high, so an OT test that does not move it
 * drives its transactions into pads the OT host does not own: the flash model
 * never sees CS# fall, and every status read comes back 0x00.
 *
 * The mux is a nonfree shim block inside sep_external, so it is only
 * visible when the register overlay supplies it. A pure-open SEP has no mux and
 * needs no switching, hence the same #ifdef gating sep.h uses for the vendor
 * block reset constants.
 */
#ifndef SPI_MUX_H
#define SPI_MUX_H

#include "och_sep_common.h"
#include "sep.h"

#ifdef OCH_SEP_SPI_MUX_CTRL__SPI_MUX_CTRL__SPI_SEL_bm

/* Route the SPI pads to the OpenTitan host and release CS#. */
static inline void spi_mux_select_ot(void) {
    och_sep_spi_mux_ctrl__SPI_MUX_CTRL_t spi_mux;
    spi_mux.w = OCH_SEP_SPI_MUX_CTRL__SPI_MUX_CTRL_reset;
    spi_mux.f.spi_sel = 1;
    spi_mux.f.cs_force_high = 0;
    WRITE_REG(OCH_SEP_TOP_SEP_EXTERNAL_OCH_SEP_SPI_MUX_CTRL_SPI_MUX_CTRL_BASE_ADDR, spi_mux.w);
}

#else

static inline void spi_mux_select_ot(void) {
}

#endif /* OCH_SEP_SPI_MUX_CTRL__SPI_MUX_CTRL__SPI_SEL_bm */

#endif /* SPI_MUX_H */
