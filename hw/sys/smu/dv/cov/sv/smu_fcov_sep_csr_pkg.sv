// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// The generated SEP register header (hw/sys/sep/regs/gen/svh/sep_reg.svh,
// rdlsvh.py over the SystemRDL sources) as a package: the register reset
// values and field positions the functional-coverage collectors read come
// from these symbols by explicit import. The SMC header declares the same
// names for the IP blocks both subsystems instantiate, so each header has a
// package of its own. The header carries a global include guard, which an
// earlier include elsewhere in the compilation unit would leave defined and
// empty this package; the guard is cleared first so the package declares
// its own copy whatever the source order.

package smu_fcov_sep_csr_pkg;
  `undef SEP_TOP_REG_SVH
  `include "sep_reg.svh"
endpackage : smu_fcov_sep_csr_pkg
