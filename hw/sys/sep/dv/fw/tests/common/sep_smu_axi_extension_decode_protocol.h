/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */
/*
 * smu_sep_axi_extension_decode_test  -- shared protocol.
 *
 * Card text still names SPI_MUX_CTRL @ 0x2000_0000. This RTL maps that page
 * to the eFuse shim; generated SPI_MUX_CTRL is 0x20001000 (sep_addr.h /
 * sep_addrmap_pkg.sv). Firmware and the monitor use the generated base.
 * XIP physical word is generated XIP base + 0x4000 (0x30004000).
 *
 * PASS token on SEP cold scratch6 is written only after the XIP load
 * compares equal to SMU007_XIP_WORD.
 */
#ifndef SEP_SMU_AXI_EXTENSION_DECODE_PROTOCOL_H
#define SEP_SMU_AXI_EXTENSION_DECODE_PROTOCOL_H

#define SMU007_SMC_IMAGE_FIRST_WORD 0x41014081
#define SMU007_SMC_ENTRY 0x00000000C00601B2ULL
#define SMU007_FW_POLL_LIMIT 4000000
#define SMU007_HW2_OVRD_BIT 24u
#define SMU007_SMC_SCRATCH1 0xC0039088u
#define SMU007_SMC_SCRATCH2 0xC0039090u
#define SMU007_SMC_SCRATCH9 0xC00390C8u
#define SMU007_GPIO_OVRD_ALIAS 0x40039090u

#define SMU007_AXI_BOUND_CYC 256
#define SMU007_MMIO_BOUND_CYC 4096
#define SMU007_CDNS_BOUND_CYC 2000000
#define SMU007_PASS_BOUND_CYC 2000000

/* Stimulus field for the AXI-extension decode check. Was spi_sel until that
 * field was retired; cs_force_high is the surviving RW bit in SPI_MUX_CTRL,
 * and 0 differs from its POR of 1 so the write is observable. */
#define SMU007_CS_FORCE_HIGH 0
#define SMU007_XIP_OFF 0x4000
#define SMU007_XIP_WORD 0xA1B2C3D4
#define SMU007_SEL_SPI_MUX 0
#define SMU007_SEL_XIP 2

#define SMU007_S0_FAIL 0x00720FA1
#define SMU007_BRINGUP_OK 0x00720000
#define SMU007_MUX_DONE 0x00720001
#define SMU007_GPIO_OVRD_OK 0x00720010
#define SMU007_CDNS_OK 0x00720002
#define SMU007_SMC_FAIL 0x007CFFEE

#define SMU007_PASS 0x007A0001
#define SMU007_FAIL 0x007AFFEE

#endif /* SEP_SMU_AXI_EXTENSION_DECODE_PROTOCOL_H */
