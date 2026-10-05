/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Testbench mailbox address and completion magic words, shared by C and
 * crt0.s. */

#ifndef TB_H
#define TB_H

#ifdef __ASSEMBLER__
/* Assembly TUs (e.g. crt0.s) must not pull in the C register typedefs from the
 * umbrella sep.h: the generated block headers carry no __ASSEMBLER__ guard.
 * They only need address macros, so include the address-only generated header
 * instead. */
#include "sep_addr.h"
#else
#include "sep.h"
#endif

#define STDOUT 0x80000000

// Test completion magic protocol (2-word sequence to STDOUT)
// TB expects: 1) TEST_MAGIC0, then 2) TEST_MAGIC_PASS or TEST_MAGIC_FAIL
#define TEST_MAGIC0 0xA5A55A5A
#define TEST_MAGIC_PASS 0xCAFEBABE
#define TEST_MAGIC_FAIL 0xDEADBEEF

#define TRIGGER_NMI 0x80
#define LOAD_NMI_ADDR 0x81
#define TRIGGER_SOFT_INT 0x84
#define TRIGGER_TIMER_INT 0x85
#define TRIGGER_EXT_INT1 0x86
#define TRIGGER_DBUS_FAULT 0x87
#define TRIGGER_IBUS_FAULT 0x88

#endif // TB_H
