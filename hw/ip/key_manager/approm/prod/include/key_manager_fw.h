/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * Key Manager firmware register umbrella.
 *
 * The PeakRDL top header (key_manager.h) is generated with --bitfields none
 * (wide registers), so it has no km_*__*_reg_t unions. Leaf headers keep
 * bitfields; firmware that needs typed accessors includes this instead.
 */
#ifndef KEY_MANAGER_FW_H
#define KEY_MANAGER_FW_H

#include "key_manager_addr.h"
#include "km_csr.h"
#include "km_drbg_sampler.h"
#include "km_kpv.h"
#include "km_mailbox_km.h"
#include "km_mailbox_sep.h"
#include "aes_wrapper_key.h"
#include "hmac_wrapper_key.h"
#include "kmac_wrapper_key.h"
#include "otbn_wrapper_key.h"
#include "abr_wrapper_key.h"

#endif /* KEY_MANAGER_FW_H */
