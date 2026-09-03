/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */
#ifndef SEP_SMU_FUSE_SENSE_PROTOCOL_H
#define SEP_SMU_FUSE_SENSE_PROTOCOL_H

/*
 * smu_sep_fuse_sense_test firmware <-> cocotb contract.
 *
 * Cold scratch4 = first SMC_FUSE_SENSE_STATUS (0x10A30140)
 * Cold scratch5 = first EFUSE_INTERFACE_CTRL_STATUS (0x10930400)
 * Cold scratch6 = FS010_PUBLISH / FS010_FAIL
 * Cold scratch7 = first SEP_FUSE_SENSE_STATUS (0x10A30150)
 *
 * Keep values on the same line as #define (cocotb single-line regex).
 */
#define FS010_PUBLISH 0x010A0001u
#define FS010_FAIL 0x010FA11Eu
#define FS010_SMC_STATUS_ADDR 0x10A30140u
#define FS010_SEP_IFC_STATUS_ADDR 0x10930400u
#define FS010_SEP_STATUS_ADDR 0x10A30150u

#endif /* SEP_SMU_FUSE_SENSE_PROTOCOL_H */
