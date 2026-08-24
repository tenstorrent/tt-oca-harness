/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */
/*
 * Generated from sep_smu_debug_bus.tcm.sym before compiling SMC DFD-arm FW.
 * Do not hand-edit PCs; regenerate after the SEP image is rebuilt.
 */
#ifndef SEP_DEBUG_BUS_SYMBOLS_H
#define SEP_DEBUG_BUS_SYMBOLS_H

#define DBG017_WAIT_PC 0xc00001deu
#define DBG017_MARKER_PC 0xc00001f6u
#define DBG017_WAIT_LOW16 0x01deu
#define DBG017_MARKER_LOW16 0x01f6u
#define DBG017_BOGUS_LOW16 0x81f6u
/* Kept-log always-on CLA [63:48] at marker was 0x07d8 == (LOW16 << 2).
 * (full_pc >> 2) & 0xFFFF is 0x007d (0xC prefix shifts in) and does not match
 * this RTL's packed trace_rv_i_address_ip[15:0]. */
#define DBG017_WAIT_TRACE16 ((DBG017_WAIT_LOW16 << 2) & 0xFFFFu)
#define DBG017_MARKER_TRACE16 ((DBG017_MARKER_LOW16 << 2) & 0xFFFFu)
#define DBG017_BOGUS_TRACE16 (DBG017_MARKER_TRACE16 ^ 0x8000u)

#if DBG017_MARKER_PC == 0 || DBG017_WAIT_PC == 0
#error sep_debug_bus_symbols.h not generated from SEP ELF/.sym
#endif
#if DBG017_MARKER_TRACE16 == DBG017_WAIT_TRACE16
#error marker and wait trace16 collide
#endif
#if (DBG017_BOGUS_TRACE16 == DBG017_MARKER_TRACE16) || (DBG017_BOGUS_TRACE16 == DBG017_WAIT_TRACE16)
#error bogus match collides with marker or wait trace16
#endif

#endif /* SEP_DEBUG_BUS_SYMBOLS_H */
