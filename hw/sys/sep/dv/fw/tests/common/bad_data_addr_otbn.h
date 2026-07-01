/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#ifndef BAD_DATA_ADDR_OTBN_H
#define BAD_DATA_ADDR_OTBN_H
#include <stddef.h>
#include <stdint.h>
#ifndef OTBN_ADDR_T_INIT
#define OTBN_ADDR_T_INIT(app, sym) 0u
#endif
static const uint32_t otbn_bad_data_addr_imem[] = {0u};
static const uint32_t otbn_bad_data_addr_dmem[] = {0u};
static const size_t otbn_bad_data_addr_imem_words = 1u;
static const size_t otbn_bad_data_addr_dmem_words = 1u;
#define OTBN_BAD_DATA_ADDR_EXPECTED_CRC 0u
static const uint32_t otbn_bad_insn_addr_imem[] = {0u};
static const uint32_t otbn_bad_insn_addr_dmem[] = {0u};
static const size_t otbn_bad_insn_addr_imem_words = 1u;
static const size_t otbn_bad_insn_addr_dmem_words = 1u;
#define OTBN_BAD_INSN_ADDR_EXPECTED_CRC 0u
static const uint32_t otbn_illegal_insn_imem[] = {0u};
static const uint32_t otbn_illegal_insn_dmem[] = {0u};
static const size_t otbn_illegal_insn_imem_words = 1u;
static const size_t otbn_illegal_insn_dmem_words = 1u;
#define OTBN_ILLEGAL_INSN_EXPECTED_CRC 0u
static const uint32_t otbn_call_stack_imem[] = {0u};
static const uint32_t otbn_call_stack_dmem[] = {0u};
static const size_t otbn_call_stack_imem_words = 1u;
static const size_t otbn_call_stack_dmem_words = 1u;
#define OTBN_CALL_STACK_EXPECTED_CRC 0u
static const uint32_t otbn_loop_error_imem[] = {0u};
static const uint32_t otbn_loop_error_dmem[] = {0u};
static const size_t otbn_loop_error_imem_words = 1u;
static const size_t otbn_loop_error_dmem_words = 1u;
#define OTBN_LOOP_ERROR_EXPECTED_CRC 0u

#endif /* BAD_DATA_ADDR_OTBN_H */
