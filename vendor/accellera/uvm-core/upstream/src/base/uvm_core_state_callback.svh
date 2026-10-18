//
//----------------------------------------------------------------------
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
//----------------------------------------------------------------------

//----------------------------------------------------------------------
// Git details (see DEVELOPMENT.md):
//
// $File:     src/base/uvm_core_state_callback.svh $
// $Rev:      2026-08-10 12:49:20 -0700 $
// $Hash:     6b8f3b5a4142eb222fd01ec0f2faeb1b3f825924 $
//
//----------------------------------------------------------------------

// Class: uvm_core_state_callback
//
// This class is used to notify the user when the core state changes.
//
// This is a virtual class and must be derived from.
//
// @uvm-contrib - For potential contributions to the 1800.2 standard.
virtual class uvm_core_state_callback extends uvm_callback;

  // Function: new
  // Initializes a new instance with ~name~.
  //
  // @uvm-contrib - For potential contributions to the 1800.2 standard.
  extern function new( string name="uvm_core_state_callback");

  // Function: core_state_change
  // This function is called when the core state changes.
  //
  // @uvm-contrib - For potential contributions to the 1800.2 standard.
  pure virtual function void core_state_change(uvm_core_state state, uvm_core_state prev_state);

  // Function: add
  // Adds a new core state callback to the list of callbacks.
  //
  // @uvm-contrib - For potential contributions to the 1800.2 standard.
  extern static function bit add( uvm_core_state_callback cb );

  // Function: delete
  // Deletes a core state callback from the list of callbacks.
  //
  // @uvm-contrib - For potential contributions to the 1800.2 standard.
  extern static function bit delete( uvm_core_state_callback cb );

  // Implementation details

  extern static function void m_do_core_state_change(uvm_core_state state, uvm_core_state prev_state);

  local static uvm_core_state_callback   m_registered_cbs[$];

endclass : uvm_core_state_callback

// Implementation details

function uvm_core_state_callback::new( string name="uvm_core_state_callback");
  super.new( name );
endfunction


// Adds cb to the list of callbacks to be processed. The method returns 1 if cb is not already in the list of
// callbacks; otherwise, a 0 is returned. If cb is null, 0 is returned.
function bit uvm_core_state_callback::add( uvm_core_state_callback cb );
  bit found;
  int unsigned i;

  if ( cb == null ) begin
    return 0;
  end

  while ( !found && ( i < m_registered_cbs.size() ) ) begin
    if ( m_registered_cbs[ i ] == cb ) begin
      found = 1;
    end
    ++i;
  end
  if ( !found ) begin
    m_registered_cbs.push_back( cb );
  end

  return !found;
endfunction

// Deletes cb from the list of callbacks to be processed. The method returns 1 if cb is in the list of callbacks;
// otherwise, a 0 is returned. If cb is null, 0 is returned.
function bit uvm_core_state_callback::delete( uvm_core_state_callback cb );
  int cb_idxs[$];

  if ( cb == null ) begin
    return 0;
  end

  cb_idxs = m_registered_cbs.find_index( item ) with ( item == cb );
  foreach ( cb_idxs[ i ] ) begin
    m_registered_cbs.delete( cb_idxs[i] );
  end
  return ( cb_idxs.size() > 0 );
endfunction

function void uvm_core_state_callback::m_do_core_state_change(uvm_core_state state, uvm_core_state prev_state);
  uvm_core_state_callback registered_cbs[$];
  int cb_idxs[$];

  // Callbacks may delete themselves while handling a state change.
  registered_cbs = m_registered_cbs;
  foreach ( registered_cbs[ i ] ) begin
    if ( registered_cbs[ i ] != null ) begin
      cb_idxs = m_registered_cbs.find_index( item ) with ( item == registered_cbs[ i ] );
      if ( cb_idxs.size() > 0 ) begin
        registered_cbs[ i ].core_state_change( state, prev_state );
      end
    end
  end
endfunction
  
  
