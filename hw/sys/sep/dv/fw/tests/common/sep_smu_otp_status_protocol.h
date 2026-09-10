/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */
#ifndef SEP_SMU_OTP_STATUS_PROTOCOL_H
#define SEP_SMU_OTP_STATUS_PROTOCOL_H

/*
 * smu_sep_otp_status_test firmware <-> cocotb tokens.
 * Cold scratch6 = publish/fail; cold scratch7 = otp_status_ref (0x10930400).
 */
#define OTP_STATUS_PUBLISH 0x019A0001u
#define OTP_STATUS_FAIL 0x019FA11Eu

#endif /* SEP_SMU_OTP_STATUS_PROTOCOL_H */
