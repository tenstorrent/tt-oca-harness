// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Define typedefs for SEP lifecycle debug-disable control.
//
// dbg_disable_t packs the per-feature debug disable bits consumed by DTP.

package sep_lifecycle_ctrl_pkg;

  // Active-high: 1 = interface disabled.
  typedef struct packed {
    // I/O STAP: the outbound JTAG host-TAP interface that forwards the PTAP
    // debug-access path to downstream chiplets in the SiP chain.
    logic stap_io;
    // SMC Debug STAP: the sub-TAP providing JTAG scan-chain access to SMC local
    // debug assets.
    logic stap_smc;
    // SEP Debug STAP: the sub-TAP providing JTAG scan-chain access to SEP internal
    // state.
    logic stap_sep;
    // Extra STAPs: the parameterised array of adopter-defined additional sub-TAPs
    // beyond the standard SMC and SEP ones.
    logic stap_extra;
    // Host scan injection: the port by which an external host drives scan data
    // directly into the PTAP scan chain; when disabled the chain loops back
    // internally, preventing external scan injection.
    logic stap_host;
    // DFT Secure SIB: the Segment Insertion Bit gating the security-sensitive
    // Design-for-Test scan chain.
    logic dft_secure;
    // DFT Non-Secure SIB: the Segment Insertion Bit gating the non-security-
    // sensitive Design-for-Test scan chain.
    logic dft_nonsecure;
    // DFD SIB: the Segment Insertion Bit gating the Design-for-Debug
    // instrumentation scan chain.
    logic dfd;
    // SMC fabric JTAG-to-AXI bridge: enables JTAG-driven AXI read/write access
    // to the SMC fabric register space.
    logic smc_jtag2axi;
    // SMC OTP JTAG-to-AXI bridge. Ungated, so this stays 0: the path reaches the
    // whole SMC eFuse interface, and enforcement is the per-field LOCKS access
    // control plus the wrapper's LC-state access policy. Distinct from the
    // DFT-inserted SMC fuse path, which is gated by smc_fuse_dft_disable_o.
    logic smc_otp_jtag2axi;
    // SEP OTP JTAG-to-AXI bridge. Ungated for the same reason as the SMC one, and
    // likewise distinct from the DFT-inserted SEP fuse path gated by
    // sep_fuse_dft_disable_o.
    logic sep_otp_jtag2axi;
  } dbg_disable_t;

endpackage
