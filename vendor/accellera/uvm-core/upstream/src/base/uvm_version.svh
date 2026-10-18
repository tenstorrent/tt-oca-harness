//----------------------------------------------------------------------
// Copyright 2010 AMD
// Copyright 2007-2018 Cadence Design Systems, Inc.
// Copyright 2017 Cisco Systems, Inc.
// Copyright 2011-2012 Cypress Semiconductor Corp.
// Copyright 2007-2013 Mentor Graphics Corporation
// Copyright 2013-2024 NVIDIA Corporation
// Copyright 2012 Paradigm Works
// Copyright 2010-2011 Synopsys, Inc.
//   All Rights Reserved Worldwide
//
//   Licensed under the Apache License, Version 2.0 (the
//   "License"); you may not use this file except in
//   compliance with the License.  You may obtain a copy of
//   the License at
//
//       http://www.apache.org/licenses/LICENSE-2.0
//
//   Unless required by applicable law or agreed to in
//   writing, software distributed under the License is
//   distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR
//   CONDITIONS OF ANY KIND, either express or implied.  See
//   the License for the specific language governing
//   permissions and limitations under the License.
//----------------------------------------------------------------------

//----------------------------------------------------------------------
// Git details (see DEVELOPMENT.md):
//
// $File:     src/base/uvm_version.svh $
// $Rev:      2026-08-10 12:50:10 -0700 $
// $Hash:     2cc37c3a717aecdf676fc286dc24c64d17be6f1f $
//
//----------------------------------------------------------------------


`ifndef UVM_VERSION_SVH
`define UVM_VERSION_SVH

parameter string UVM_VERSION_STRING = "Accellera:1800.2:UVM:2020.3.2";

function string uvm_revision_string();
  return UVM_VERSION_STRING;
endfunction

`endif // UVM_VERSION_SVH
