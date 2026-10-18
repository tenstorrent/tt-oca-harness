//
//----------------------------------------------------------------------
// Copyright 2025-2026 NVIDIA Corporation
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
// $File:     src/macros/uvm_init_macros.svh $
// $Rev:      2026-08-10 12:49:20 -0700 $
// $Hash:     6b8f3b5a4142eb222fd01ec0f2faeb1b3f825924 $
//
//----------------------------------------------------------------------

`ifndef UVM_INIT_MACROS_SVH
`define UVM_INIT_MACROS_SVH

// Macro: `uvm_post_init_decl
//
// This macro is used to declare an ~ACTION~ to be taken after the UVM
// core service has been initialized, but before the <uvm_test_runner::run_test>
// method is called.
//
// | `uvm_post_init_decl(ACTION, SUFFIX= )
//
// The ~ACTION~ expression shall be any valid non-time consuming `void` expression.  
//
// Example:
// | package pkg;
// |   int my_value;
// |   static function void init_my_value();
// |     uvm_cmdline_processor clp;
// |     string my_value_str;
// |     clp = uvm_cmdline_processor::get_inst();
// |     if (clp.get_arg_value("+MY_VALUE=", my_value_str)) begin
// |       my_value = my_value_str.atoi();
// |     end
// |     else begin
// |       my_value = 10;
// |     end
// |   endfunction
// |
// |   `uvm_post_init_decl(init_my_value())
// | endpackage
//
// The optional SUFFIX argument provides the ability to uniquify the underlying code, 
// if necessary.  This allows for the macro to be called multiple times in the same scope.
//
// Note: As <uvm_init> may be triggered during static initialization, it is unsafe to fork
// off a new process within ~ACTION~.  For ~ACTION~s that require time, use the
// <`uvm_pre_run_decl macro instead.
//
// @uvm-contrib Potential contribution to a future 1800.2 standard
`define uvm_post_init_decl(ACTION, SUFFIX= ) \
  class uvm_post_init_callback``SUFFIX extends uvm_core_state_callback; \
    local function new(); \
      super.new(`"uvm_post_init_callback``SUFFIX`"); \
      if (uvm_pkg::get_core_state() == UVM_CORE_POST_INIT) begin \
        ACTION; \
      end \
      else begin \
        void'(uvm_core_state_callback::add(this)); \
      end \
    endfunction : new \
    virtual function void core_state_change(uvm_core_state state, uvm_core_state prev_state); \
      if (state == UVM_CORE_POST_INIT) begin \
        ACTION; \
        uvm_core_state_callback::delete(this); \
      end \
    endfunction : core_state_change \
    local static uvm_post_init_callback``SUFFIX m_instance = new(); \
  endclass : uvm_post_init_callback``SUFFIX


// Macro: `uvm_pre_run_decl
//
// This macro is used to declare an ~ACTION~ to be taken after the <uvm_test_runner::run_test>
// method has been called, but before the <uvm_phase_hopper::run_phases> method is called.
//
// Like the <`uvm_post_init_decl> macro, this macro avoids causing static initialization race conditions
// and accepts a `void` ~ACTION~ expression.  However, unlike <`uvm_post_init_decl>, this macro is called
// in the event region of the <uvm_test_runner::run_test> task, and therefore may consume time and fork off new processes.
//
// | `uvm_pre_run_decl(ACTION, SUFFIX= )
//
// Note: As <uvm_test_runner::run_test> may be invoked within either a ~module~ or a ~program~ context, i.e. the
// ~ACTIVE~ or ~REACTIVE~ event regions, care must be taken to ensure behavior that is correct in both contexts.
//
// @uvm-contrib Potential contribution to a future 1800.2 standard
`define uvm_pre_run_decl(ACTION, SUFFIX= ) \
  class uvm_pre_run_callback``SUFFIX extends uvm_core_state_callback; \
    local function new(); \
      super.new(`"uvm_pre_run_callback``SUFFIX`"); \
      void'(uvm_core_state_callback::add(this)); \
    endfunction : new \
    virtual function void core_state_change(uvm_core_state state, uvm_core_state prev_state); \
      if (state == UVM_CORE_PRE_RUN) begin \
        fork \
          ACTION; \
        join_none \
        uvm_core_state_callback::delete(this); \
      end \
    endfunction : core_state_change \
    local static uvm_pre_run_callback``SUFFIX m_instance = new(); \
  endclass : uvm_pre_run_callback``SUFFIX

`endif // UVM_INIT_MACROS_SVH
