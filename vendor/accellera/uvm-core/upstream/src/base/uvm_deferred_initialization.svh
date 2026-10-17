// 
//------------------------------------------------------------------------------
// Copyright 2007-2009 Cadence Design Systems, Inc.
// Copyright 2007-2009 Mentor Graphics Corporation
// Copyright 2025-2026 NVIDIA Corporation
// Copyright 2025 Siemens
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
//------------------------------------------------------------------------------

//----------------------------------------------------------------------
// Git details (see DEVELOPMENT.md):
//
// $File:     src/base/uvm_deferred_initialization.svh $
// $Rev:      2026-08-10 12:49:20 -0700 $
// $Hash:     6b8f3b5a4142eb222fd01ec0f2faeb1b3f825924 $
//
//----------------------------------------------------------------------

// Class -- NODOCS -- uvm_builtin_init_callback
//
// This class is used to defer the initialization of certain services until
// the core service has been determined.  It is an extension of the 
// uvm_core_state_callback class that self-registers during static initialization,
// and deregisters after UVM_CORE_INITIALIZING.
class uvm_builtin_init_callback extends uvm_core_state_callback;

    // Function -- NODOCS -- new
    //
    // Constructor
    extern local function new(string name="uvm_builtin_init_callback");

    // Function -- NODOCS -- core_state_change
    //
    // This function is called when the core state changes.
    extern function void core_state_change(uvm_core_state state, uvm_core_state prev_state);

    // Implementation artifacts
    local static uvm_builtin_init_callback m_instance = new("uvm_builtin_init_callback");

    // Function -- NODOCS -- action
    //
    // This function is called to execute the appropriate actions.
    extern function void action();
endclass

// Implementation details for uvm_builtin_init_callback
function uvm_builtin_init_callback::new(string name="uvm_builtin_init_callback");
    super.new(name);
    if (get_core_state() inside {UVM_CORE_UNINITIALIZED, UVM_CORE_PRE_INIT}) begin
      void'(uvm_core_state_callback::add(this));
    end
    else begin
        // Somehow the user statically initialized uvm_init before we registered.  Need to catch-up.
        action();
    end
endfunction

function void uvm_builtin_init_callback::core_state_change(uvm_core_state state, uvm_core_state prev_state);
    if (state == UVM_CORE_INITIALIZING) begin
        action();
    end
endfunction

function void uvm_builtin_init_callback::action();
    foreach(uvm_deferred_init[idx]) begin
        uvm_deferred_init[idx].initialize();
    end
    uvm_deferred_init.delete();

    uvm_sequence_library_adder_base::initialize();
endfunction

// Class -- NODOCS -- uvm_builtin_pre_run_callback
//
// This class is used to defer the initialization of certain time-consuming services until
// the core service has been determined.  It is an extension of the 
// uvm_core_state_callback class that self-registers during static initialization,
// and deregisters after UVM_CORE_PRE_RUN.
class uvm_builtin_pre_run_callback extends uvm_core_state_callback;

    // Function -- NODOCS -- new
    //
    // Constructor
    extern local function new(string name="uvm_builtin_pre_run_callback");

    // Function -- NODOCS -- core_state_change
    //
    // This function is called when the core state changes.
    extern function void core_state_change(uvm_core_state state, uvm_core_state prev_state);
    
    // Implementation artifacts
    local static uvm_builtin_pre_run_callback m_instance = new("uvm_builtin_pre_run_callback");

    // Unlike uvm_builtin_init_callback, we don't need an ~action~ function because it's 
    // not possible for UVM_CORE_PRE_RUN to race static initialization.
endclass

// Implementation details for uvm_builtin_pre_run_callback
function uvm_builtin_pre_run_callback::new(string name="uvm_builtin_pre_run_callback");
    super.new(name);
    void'(uvm_core_state_callback::add(this));
endfunction

function void uvm_builtin_pre_run_callback::core_state_change(uvm_core_state state, uvm_core_state prev_state);
    if (state == UVM_CORE_PRE_RUN) begin
        // Note that these all fork internally, so we don't need to fork here.

        // Set up the process that decouples the thread that drops objections from
        // the process that processes drop/all_dropped objections. Thus, if the
        // original calling thread (the "dropper") gets killed, it does not affect
        // drain-time and propagation of the drop up the hierarchy.
        // Needs to be done in run_test since it needs to be in an
        // initial block to fork a process.
        uvm_objection::m_init_objections();

        // Do the same for uvm_process_guard
        uvm_process_guard_base::m_init_process_guards();
    end
endfunction
