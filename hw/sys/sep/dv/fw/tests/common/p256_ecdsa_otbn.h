/* SPDX-License-Identifier: Apache-2.0 */
/* (c) 2026 Tenstorrent USA Inc */

#ifndef P256_ECDSA_OTBN_H
#define P256_ECDSA_OTBN_H
#include <stddef.h>
#include <stdint.h>
#ifndef OTBN_ADDR_T_INIT
#define OTBN_ADDR_T_INIT(app, sym) 0u
#endif
static const uint32_t otbn_p256_ecdsa_imem[] = {0u};
static const uint32_t otbn_p256_ecdsa_dmem[] = {0u};
static const size_t otbn_p256_ecdsa_imem_words = 1u;
static const size_t otbn_p256_ecdsa_dmem_words = 1u;
#define OTBN_P256_ECDSA_EXPECTED_CRC 0u

#endif /* P256_ECDSA_OTBN_H */
