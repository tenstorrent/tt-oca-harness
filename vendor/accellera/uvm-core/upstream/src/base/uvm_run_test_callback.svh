//
//----------------------------------------------------------------------
// Copyright 2018 Cadence Design Systems, Inc.
// Copyright 2018-2026 NVIDIA Corporation
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
// $File:     src/base/uvm_run_test_callback.svh $
// $Rev:      2026-08-10 12:49:20 -0700 $
// $Hash:     6b8f3b5a4142eb222fd01ec0f2faeb1b3f825924 $
//
//----------------------------------------------------------------------


// @uvm-ieee 1800.2-2020 auto F.6.1
virtual class uvm_run_test_callback extends uvm_core_state_callback;

  // @uvm-ieee 1800.2-2020 auto F.6.2.1
  extern function new( string name="uvm_run_test_callback");

  // @uvm-ieee 1800.2-2020 auto F.6.2.2
  virtual function void pre_run_test();
  endfunction

  // @uvm-ieee 1800.2-2020 auto F.6.2.3
  virtual function void post_run_test();
  endfunction

  // @uvm-ieee 1800.2-2020 auto F.6.2.4
  virtual function void pre_abort();
  endfunction

  // @uvm-ieee 1800.2-2020 auto F.6.2.5
  extern static function bit add( uvm_run_test_callback cb );

  // @uvm-ieee 1800.2-2020 auto F.6.2.6
  extern static function bit delete( uvm_run_test_callback cb );

  // @uvm-contrib - For potential contributions to the 1800.2 standard.
  extern virtual function void core_state_change(uvm_core_state state, uvm_core_state prev_state);

endclass : uvm_run_test_callback

function uvm_run_test_callback::new( string name="uvm_run_test_callback");
  super.new( name );
endfunction

function void uvm_run_test_callback::core_state_change(uvm_core_state state, uvm_core_state prev_state);
  case ( state )
    UVM_CORE_PRE_RUN: pre_run_test();
    UVM_CORE_POST_RUN: post_run_test();
    UVM_CORE_PRE_ABORT: pre_abort();
  endcase
endfunction

function bit uvm_run_test_callback::add( uvm_run_test_callback cb );
  return uvm_core_state_callback::add( cb ) ;
endfunction

function bit uvm_run_test_callback::delete( uvm_run_test_callback cb );
  return uvm_core_state_callback::delete( cb );
endfunction


