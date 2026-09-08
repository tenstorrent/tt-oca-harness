// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Environment base. A bench <dut>_env composes: it reads its <dut>_env_cfg
// and the TB interface from uvm_config_db, fills one VIP config per agent
// (interface, geometry, name_tag) and publishes it to that agent's subtree,
// builds the VIP environments and agents, the virtual sequencer, the
// scoreboard, the subscribers, and the aggregate evidence recorder; it
// wires analysis ports in connect_phase and finalizes evidence once in
// check_phase. It drives nothing and checks no protocol. The cocotb twin is
// ocah_lib.OcahEnv.

class ocah_env extends uvm_env;
  `uvm_component_utils(ocah_env)

  function new(string name = "ocah_env", uvm_component parent = null);
    super.new(name, parent);
  endfunction

endclass : ocah_env
