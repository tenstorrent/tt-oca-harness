/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */
/*
 * PCs the CLA matches on. Regenerated from the built SEP .sym with
 * `make ocah-lint-fw-symbol-pins-update`. The #error guards catch zero,
 * a LOW16 mismatch, and a trace16 collision. A rebuilt image that moves a
 * PC to another plausible address is caught by check_fw_symbol_pins.py.
 */
#ifndef SEP_DEBUG_BUS_SYMBOLS_H
#define SEP_DEBUG_BUS_SYMBOLS_H

#define DEBUG_BUS_WAIT_PC 0xc00001deu
#define DEBUG_BUS_MARKER_PC 0xc00001f6u
#define DEBUG_BUS_WAIT_LOW16 0x01deu
#define DEBUG_BUS_MARKER_LOW16 0x01f6u
#define DEBUG_BUS_BOGUS_LOW16 0x81f6u
/* CLA snapshot[63:48] is (LOW16 << 2): marker 0xc00001f6 packs as 0x07d8.
 * (full_pc >> 2) & 0xFFFF is 0x007d and does not match this RTL's packed
 * trace_rv_i_address_ip[15:0]. */
#define DEBUG_BUS_WAIT_TRACE16 ((DEBUG_BUS_WAIT_LOW16 << 2) & 0xFFFFu)
#define DEBUG_BUS_MARKER_TRACE16 ((DEBUG_BUS_MARKER_LOW16 << 2) & 0xFFFFu)
#define DEBUG_BUS_BOGUS_TRACE16 (DEBUG_BUS_MARKER_TRACE16 ^ 0x8000u)

#if DEBUG_BUS_MARKER_PC == 0 || DEBUG_BUS_WAIT_PC == 0
#error sep_debug_bus_symbols.h not generated from SEP ELF/.sym
#endif
#if DEBUG_BUS_WAIT_LOW16 != (DEBUG_BUS_WAIT_PC & 0xFFFFu)
#error DEBUG_BUS_WAIT_LOW16 does not match DEBUG_BUS_WAIT_PC
#endif
#if DEBUG_BUS_MARKER_LOW16 != (DEBUG_BUS_MARKER_PC & 0xFFFFu)
#error DEBUG_BUS_MARKER_LOW16 does not match DEBUG_BUS_MARKER_PC
#endif
#if DEBUG_BUS_MARKER_TRACE16 == DEBUG_BUS_WAIT_TRACE16
#error marker and wait trace16 collide
#endif
#if (DEBUG_BUS_BOGUS_TRACE16 == DEBUG_BUS_MARKER_TRACE16) || \
    (DEBUG_BUS_BOGUS_TRACE16 == DEBUG_BUS_WAIT_TRACE16)
#error bogus match collides with marker or wait trace16
#endif

#endif /* SEP_DEBUG_BUS_SYMBOLS_H */
