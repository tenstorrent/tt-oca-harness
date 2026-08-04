// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// DTP SV-UVM environment package (`<DUT>_env_pkg` convention). Everything in
// uvm/env/ is REUSABLE across tests: the environment owns the virtual
// interfaces today and grows agents/scoreboards as the flow matures.

`timescale 1ns/1ps

package dtp_env_pkg;

    import uvm_pkg::*;
    `include "uvm_macros.svh"

    `include "dtp_uvm_env.svh"

endpackage : dtp_env_pkg
