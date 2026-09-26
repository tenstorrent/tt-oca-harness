// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Name the test-mode persistence controller states from IEEE 1149.1 §6.2.
//
// Defines persistence-on and persistence-off constants for jtag_tmp and the status
// register.

package jtag_tmp_pkg;

  //--------------------------------------------------------------------------
  // TMP Controller States (IEEE 1149.1 Section 6.2)
  //--------------------------------------------------------------------------
  typedef enum logic {
    TMP_PERSISTENCE_OFF = 1'b0,     // Default state - normal operation.
    TMP_PERSISTENCE_ON  = 1'b1      // Test mode persistence active.
  } tmp_state_e;

endpackage : jtag_tmp_pkg

