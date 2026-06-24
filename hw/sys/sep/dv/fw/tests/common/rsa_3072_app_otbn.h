/* SPDX-License-Identifier: Apache-2.0 */
#ifndef RSA_3072_APP_OTBN_H
#define RSA_3072_APP_OTBN_H
#include <stddef.h>
#include <stdint.h>
#ifndef OTBN_ADDR_T_INIT
#define OTBN_ADDR_T_INIT(app, sym) 0u
#endif
static const uint32_t otbn_rsa_3072_app_imem[] = {0u};
static const uint32_t otbn_rsa_3072_app_dmem[] = {0u};
static const size_t otbn_rsa_3072_app_imem_words = 1u;
static const size_t otbn_rsa_3072_app_dmem_words = 1u;
#define OTBN_RSA_3072_APP_EXPECTED_CRC 0u

#endif /* RSA_3072_APP_OTBN_H */
