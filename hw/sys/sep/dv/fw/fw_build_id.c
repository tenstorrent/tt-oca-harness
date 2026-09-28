// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Build identity of this image: "FW-BUILD-ID:" plus the digest that
// fw/fw_src_digest.py computed over the firmware sources when the image was
// built. One copy is linked into ICCM and one into DCCM, so each of the two
// hex images the simulation loads carries it. Nothing references them at run
// time; link/modes/tcm.ld keeps both sections, and sep_base_test requires
// both images to carry the digest of the committed source (CHK-FW-IDENTITY).

#include "fw_build_id.h"

__attribute__((used, section(".fw_build_id_itcm")))
const char sep_fw_build_id_itcm[] = "FW-BUILD-ID:" SEP_FW_SRC_DIGEST;

__attribute__((used, section(".fw_build_id_dtcm")))
const char sep_fw_build_id_dtcm[] = "FW-BUILD-ID:" SEP_FW_SRC_DIGEST;
