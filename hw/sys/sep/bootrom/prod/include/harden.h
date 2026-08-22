/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * harden.h — fault-injection hardening primitives (shared, header-only).
 *
 * Small dependency-free helpers for making security-critical decisions resistant
 * to single-fault (glitch) attacks. Freestanding: no libc, no heap, no state.
 *
 * The core primitive is a value "launder": an empty volatile asm that emits no
 * instruction but forces the compiler to treat a value as freshly produced. This
 * defeats common-subexpression elimination, so a decision that is deliberately
 * evaluated twice (and rejected on disagreement) survives -Os instead of being
 * folded back into a single computation. Launder the operands of the second
 * evaluation:
 *
 *     uint32_t a2 = harden_u32(a);        // typed workhorse
 *     void    *p2 = harden_ptr(p);        // pointer, type-preserving
 *     x2          = HARDEN_VAL(x);         // generic (any GPR-sized scalar/ptr)
 *
 * These raise the cost of a fault (a single glitch can no longer merge or
 * optimize away a redundant check); they are defense-in-depth and do not replace
 * the primary validation they harden.
 *
 * Scope: operands must fit a general-purpose register (integers up to the
 * register width, and pointers). On a 32-bit target a 64-bit value does not fit
 * one register — launder its halves, or the already-narrowed 32-bit value.
 */
#ifndef HARDEN_H
#define HARDEN_H

#include <stdint.h>

/* Generic launder: returns x unchanged but opaque to the optimizer. Evaluates x
 * exactly once. GNU statement expression + __typeof__ (GCC/Clang). */
#define HARDEN_VAL(x) \
    __extension__({ \
        __typeof__(x) _harden_v = (x); \
        __asm__ volatile("" : "+r"(_harden_v)); \
        _harden_v; \
    })

/* Typed convenience wrappers — read well at call sites and are usable where a
 * function (not a macro) is preferred. */
static inline uint32_t harden_u32(uint32_t v) {
    __asm__ volatile("" : "+r"(v));
    return v;
}

static inline uintptr_t harden_uptr(uintptr_t v) {
    __asm__ volatile("" : "+r"(v));
    return v;
}

/* Launder a pointer, preserving its type. */
#define harden_ptr(p) ((__typeof__(p))harden_uptr((uintptr_t)(p)))

#endif /* HARDEN_H */
