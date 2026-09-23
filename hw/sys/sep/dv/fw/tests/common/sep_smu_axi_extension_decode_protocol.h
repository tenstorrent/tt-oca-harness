/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */
/*
 * smu_sep_axi_extension_decode_test  -- shared protocol.
 *
 * The page at 0x2000_0000 is the eFuse shim; SPI_MUX_CTRL is the generated
 * 0x20001000 (sep_addr.h / sep_addrmap_pkg.sv). Firmware and the monitor use
 * the generated base.
 * XIP physical word is generated XIP base + 0x4000 (0x30004000).
 *
 * PASS token on SEP cold scratch6 is written only after the XIP load
 * compares equal to AXI_EXT_XIP_WORD.
 */
#ifndef SEP_SMU_AXI_EXTENSION_DECODE_PROTOCOL_H
#define SEP_SMU_AXI_EXTENSION_DECODE_PROTOCOL_H

#define AXI_EXT_SMC_IMAGE_FIRST_WORD 0x41014081
#define AXI_EXT_SMC_ENTRY 0x00000000C00601B2ULL
#define AXI_EXT_FW_POLL_LIMIT 4000000
#define AXI_EXT_HW2_OVRD_BIT 24u
#define AXI_EXT_SMC_SCRATCH1 0xC0039088u
#define AXI_EXT_SMC_SCRATCH2 0xC0039090u
#define AXI_EXT_SMC_SCRATCH9 0xC00390C8u
#define AXI_EXT_GPIO_OVRD_ALIAS 0x40039090u

#define AXI_EXT_AXI_BOUND_CYC 256
#define AXI_EXT_MMIO_BOUND_CYC 4096
#define AXI_EXT_XIP_BOUND_CYC 2000000
#define AXI_EXT_PASS_BOUND_CYC 2000000

#define AXI_EXT_SPI_SEL 1
#define AXI_EXT_XIP_OFF 0x4000
#define AXI_EXT_XIP_WORD 0xA1B2C3D4
#define AXI_EXT_SEL_SPI_MUX 0
#define AXI_EXT_SEL_XIP 2

#define AXI_EXT_S0_FAIL 0x00720FA1
#define AXI_EXT_BRINGUP_OK 0x00720000
#define AXI_EXT_MUX_DONE 0x00720001
#define AXI_EXT_GPIO_OVRD_OK 0x00720010
#define AXI_EXT_XIP_OK 0x00720002
#define AXI_EXT_SMC_FAIL 0x007CFFEE

#define AXI_EXT_PASS 0x007A0001
#define AXI_EXT_FAIL 0x007AFFEE

#endif /* SEP_SMU_AXI_EXTENSION_DECODE_PROTOCOL_H */
