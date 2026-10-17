//----------------------------------------------------------------------
// Copyright 2015 Analog Devices, Inc.
// Copyright 2010-2018 Cadence Design Systems, Inc.
// Copyright 2014-2017 Cisco Systems, Inc.
// Copyright 2018 Intel Corporation
// Copyright 2021-2022 Marvell International Ltd.
// Copyright 2014-2018 Mentor Graphics Corporation
// Copyright 2013-2026 NVIDIA Corporation
// Copyright 2014 Semifore
// Copyright 2018 Synopsys, Inc.
// Copyright 2017 Verific
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
// $File:     src/base/uvm_coreservice.svh $
// $Rev:      2026-08-10 12:49:20 -0700 $
// $Hash:     6b8f3b5a4142eb222fd01ec0f2faeb1b3f825924 $
//
//----------------------------------------------------------------------

typedef class uvm_factory;
typedef class uvm_default_factory;
typedef class uvm_report_server;
typedef class uvm_default_report_server;
typedef class uvm_root;
typedef class uvm_visitor;
typedef class uvm_component_name_check_visitor;
typedef class uvm_component;
typedef class uvm_comparer;
typedef class uvm_copier;
typedef class uvm_packer;
typedef class uvm_printer;
typedef class uvm_table_printer;
typedef class uvm_phase_hopper;
typedef class uvm_tr_database;
typedef class uvm_text_tr_database;
typedef class uvm_resource_pool;
typedef class uvm_resource_base;
typedef class uvm_test_runner;
typedef class uvm_core_state_callback;

typedef class uvm_default_coreservice_t;

// Title: Core Service

  
// 
// Class: uvm_coreservice_t
//
// The library implements the following public API in addition to what
// is documented in IEEE 1800.2.
//

// @uvm-ieee 1800.2-2020 auto F.4.1.1
virtual class uvm_coreservice_t extends uvm_void;

    // @uvm-ieee 1800.2-2020 auto F.4.1.4.2
    pure virtual function uvm_factory get_factory();


    // @uvm-ieee 1800.2-2020 auto F.4.1.4.3
    pure virtual function void set_factory(uvm_factory f);


    // @uvm-ieee 1800.2-2020 auto F.4.1.4.4
    pure virtual function uvm_report_server get_report_server();


    // @uvm-ieee 1800.2-2020 auto F.4.1.4.5
    pure virtual function void set_report_server(uvm_report_server server);


    // @uvm-ieee 1800.2-2020 auto F.4.1.4.6
    pure virtual function uvm_tr_database get_default_tr_database();


    // @uvm-ieee 1800.2-2020 auto F.4.1.4.7
    pure virtual function void set_default_tr_database(uvm_tr_database db);


    // @uvm-ieee 1800.2-2020 auto F.4.1.4.9
    pure virtual function void set_component_visitor(uvm_visitor#(uvm_component) v);

    pure virtual function uvm_visitor#(uvm_component) get_component_visitor();


    // @uvm-ieee 1800.2-2020 auto F.4.1.4.1
    pure virtual function uvm_root get_root();

    // @uvm-ieee 1800.2-2020 auto F.4.1.4.10
    pure virtual function void set_phase_max_ready_to_end(int max);

    // @uvm-ieee 1800.2-2020 auto F.4.1.4.11
    pure virtual function int get_phase_max_ready_to_end();

    // @uvm-ieee 1800.2-2020 auto F.4.1.4.12
    pure virtual function void set_default_printer(uvm_printer printer);
    
    // @uvm-ieee 1800.2-2020 auto F.4.1.4.13
    pure virtual function uvm_printer get_default_printer();

    // @uvm-ieee 1800.2-2020 auto F.4.1.4.14
    pure virtual function void set_default_packer(uvm_packer packer);

    // @uvm-ieee 1800.2-2020 auto F.4.1.4.15
    pure virtual function uvm_packer get_default_packer();

    // @uvm-ieee 1800.2-2020 auto F.4.1.4.16
    pure virtual function void set_default_comparer(uvm_comparer comparer);

    // @uvm-ieee 1800.2-2020 auto F.4.1.4.17
    pure virtual function uvm_comparer get_default_comparer();

    pure virtual function int unsigned get_global_seed();


    // @uvm-ieee 1800.2-2020 auto F.4.1.4.18
    pure virtual function void set_default_copier(uvm_copier copier);

    // @uvm-ieee 1800.2-2020 auto F.4.1.4.19
    pure virtual function uvm_copier get_default_copier();



        // @uvm-ieee 1800.2-2020 auto F.4.1.4.25
        pure virtual function bit get_uvm_seeding();

        // @uvm-ieee 1800.2-2020 auto F.4.1.4.26
        pure virtual function void set_uvm_seeding(bit enable);
   
    // @uvm-ieee 1800.2-2020 auto F.4.1.4.21
    pure virtual function void set_resource_pool (uvm_resource_pool pool);

    // @uvm-ieee 1800.2-2020 auto F.4.1.4.22
    pure virtual function uvm_resource_pool get_resource_pool();

    // @uvm-ieee 1800.2-2020 auto F.4.1.4.23
    pure virtual function void set_resource_pool_default_precedence(int unsigned precedence);

    pure virtual function int unsigned get_resource_pool_default_precedence();

    // Function: get_phase_hopper
    //
    // Returns the <uvm_phase_hopper> (singleton) instance for this environment
    //
    // @uvm-contrib For potential contribution to 1800.2
    pure virtual function uvm_phase_hopper get_phase_hopper();

    // Function: get_test_runner
    //
    // Returns the <uvm_test_runner> (singleton) instance for this environment
    //
    // @uvm-contrib For potential contribution to 1800.2
    pure virtual function uvm_test_runner get_test_runner();
    
    // Function: set_core_state
    //
    // This method is used to set the UVM core state and trigger the appropriate
    // <uvm_run_test_callback> methods.
    //
    // If this method is called on an instance of the <uvm_coreservice_t> class that
    // is not global core service, then the method shall generate a fatal error
    // and return immediately.
    //
    // @uvm-contrib For potential contribution to the 1800.2 standard
    pure virtual function void set_core_state(uvm_core_state state);
    

    // Function: initialize
    // Initializes the core service and any internal state.
    //
    // This method is called automatically by the <uvm_init> method 
    // after the core service has been determined.  It is not intended
    // to be called by the user. except as `super.initialize()` in a
    // subclass.
    //
    // @uvm-contrib For potential contribution to the 1800.2 standard
    pure virtual function void initialize();

    local static uvm_coreservice_t inst;

    // @uvm-ieee 1800.2-2020 auto F.4.1.3
    static function uvm_coreservice_t get();
        if(inst==null) begin
            
          uvm_init(null);
        end

        
        return inst;
    endfunction // get

    static function void set(uvm_coreservice_t cs);
        inst=cs;
    endfunction
endclass

// Class: uvm_default_coreservice_t
// Implementation of the uvm_default_coreservice_t as defined in
// section F.4.2.1 of 1800.2-2020.
//
//| class uvm_default_coreservice_t extends uvm_coreservice_t
//
 
// @uvm-ieee 1800.2-2020 auto F.4.2.1
class uvm_default_coreservice_t extends uvm_coreservice_t;
    local uvm_factory factory;

    // Function --NODOCS-- get_factory
    //
    // Returns the currently enabled uvm factory.
    // When no factory has been set before, instantiates a uvm_default_factory
    virtual function uvm_factory get_factory();
        if(factory==null) begin
          uvm_default_factory f;
          f=new;
          factory=f;
        end

        return factory;
    endfunction

    // Function --NODOCS-- set_factory
    //
    // Sets the current uvm factory.
    // Please note: it is up to the user to preserve the contents of the original factory or delegate calls to the original factory
    virtual function void set_factory(uvm_factory f);
        factory = f;
    endfunction

    local uvm_tr_database tr_database;
    // Function --NODOCS-- get_default_tr_database
    // returns the current default record database
    //
    // If no default record database has been set before this method
    // is called, returns an instance of <uvm_text_tr_database>
    virtual function uvm_tr_database get_default_tr_database();
        if (tr_database == null) begin
          process p = process::self();
          uvm_text_tr_database tx_db;
          string s;
          if(p != null) begin
                
            s = p.get_randstate();
          end


          tx_db = new("default_tr_database");
          tr_database = tx_db;

          if(p != null) begin
                
            p.set_randstate(s);
          end

        end
        return tr_database;
    endfunction : get_default_tr_database

    // Function --NODOCS-- set_default_tr_database
    // Sets the current default record database to ~db~
    virtual function void set_default_tr_database(uvm_tr_database db);
        tr_database = db;
    endfunction : set_default_tr_database

    local uvm_report_server report_server;
    // Function --NODOCS-- get_report_server
    // returns the current global report_server
    // if no report server has been set before, returns an instance of
    // uvm_default_report_server
    virtual function uvm_report_server get_report_server();
        if(report_server==null) begin
          uvm_default_report_server f;
          f=new;
          report_server=f;
        end

        return report_server;
    endfunction

    // Function --NODOCS-- set_report_server
    // sets the central report server to ~server~
    virtual function void set_report_server(uvm_report_server server);
        report_server=server;
    endfunction

    virtual function uvm_root get_root();
        return uvm_root::m_uvm_get_root();
    endfunction

    local uvm_visitor#(uvm_component) _visitor;
    // Function --NODOCS-- set_component_visitor
    // sets the component visitor to ~v~
    // (this visitor is being used for the traversal at end_of_elaboration_phase
    // for instance for name checking)
    virtual function void set_component_visitor(uvm_visitor#(uvm_component) v);
        _visitor=v;
    endfunction

    // Function --NODOCS-- get_component_visitor
    // retrieves the current component visitor
    // if unset(or ~null~) returns a <uvm_component_name_check_visitor> instance
    virtual function uvm_visitor#(uvm_component) get_component_visitor();
        if(_visitor==null) begin
          uvm_component_name_check_visitor v = new("name-check-visitor");
          _visitor=v;
        end
        return _visitor;
    endfunction

    virtual function void set_default_printer(uvm_printer printer);
           // using field in uvm_object_globals for backward compatibility
        uvm_default_printer = printer ;
    endfunction

    // Function: get_default_printer
    // Implementation of the get_default_printer method, as defined in
    // section F.4.1.4.13 of 1800.2-2020.
    //
    // The default printer type returned by this function is 
    // a uvm_table_printer, unless the default printer has been set to
    // another printer type
    //
    // @uvm-accellera The details of this API are specific to the Accellera implementation, and are not being considered for contribution to 1800.2

    virtual function uvm_printer get_default_printer();
           // using field in uvm_object_globals for backward compatibility
        if (uvm_default_printer == null) begin
          uvm_default_printer =  uvm_table_printer::get_default() ;
        end
        return uvm_default_printer ;
    endfunction

    virtual function void set_default_packer(uvm_packer packer);
           // using field in uvm_object_globals for backward compatibility
       uvm_default_packer = packer ;
    endfunction

    virtual function uvm_packer get_default_packer();
           // using field in uvm_object_globals for backward compatibility
       if (uvm_default_packer == null) begin
         uvm_default_packer =  new("uvm_default_packer") ;
       end
       return uvm_default_packer ;
    endfunction

    virtual function void set_default_comparer(uvm_comparer comparer);
           // using field in uvm_object_globals for backward compatibility
       uvm_default_comparer = comparer ;
    endfunction
    virtual function uvm_comparer get_default_comparer();
           // using field in uvm_object_globals for backward compatibility
       if (uvm_default_comparer == null) begin
         uvm_default_comparer =  new("uvm_default_comparer") ;
       end
       return uvm_default_comparer ;
    endfunction

    local int m_default_max_ready_to_end_iters = 20;
    virtual function void set_phase_max_ready_to_end(int max);
        m_default_max_ready_to_end_iters = max;
    endfunction

    virtual function int get_phase_max_ready_to_end();
        return m_default_max_ready_to_end_iters;
    endfunction

    local uvm_resource_pool m_rp ;
    virtual function void set_resource_pool (uvm_resource_pool pool);
        m_rp = pool;
    endfunction

    virtual function uvm_resource_pool get_resource_pool();
        if(m_rp == null) begin
            
          m_rp = new();
        end

        return m_rp;
    endfunction

    virtual function void set_resource_pool_default_precedence(int unsigned precedence);
        uvm_resource_base::default_precedence = precedence;
    endfunction

    virtual function int unsigned get_resource_pool_default_precedence();
        return uvm_resource_base::default_precedence;
    endfunction

    local uvm_phase_hopper m_hopper;

    virtual function uvm_phase_hopper get_phase_hopper();
      if (m_hopper == null) begin
        m_hopper = uvm_phase_hopper::type_id::create("default_hopper");
      end
      return m_hopper;
    endfunction // get_phase_hopper

    local uvm_test_runner m_runner;

    virtual function uvm_test_runner get_test_runner();
      if (m_runner == null) begin
        m_runner = uvm_test_runner::type_id::create("default_runner");
      end
      return m_runner;
    endfunction // get_test_runner

    // Helper function to check valid state transitions
    protected function bit is_valid_state_transition(uvm_core_state new_state, uvm_core_state current_state);
      case(new_state)
        UVM_CORE_PRE_INIT:      return (current_state == UVM_CORE_UNINITIALIZED);
        UVM_CORE_INITIALIZING:  return (current_state == UVM_CORE_PRE_INIT);
        UVM_CORE_INITIALIZED:   return (current_state == UVM_CORE_INITIALIZING);
        UVM_CORE_PRE_RUN:       return (current_state == UVM_CORE_INITIALIZED);
        UVM_CORE_RUNNING:       return (current_state == UVM_CORE_PRE_RUN);
        UVM_CORE_POST_RUN:      return (current_state == UVM_CORE_RUNNING);
        UVM_CORE_FINISHED:      return (current_state == UVM_CORE_POST_RUN);
        UVM_CORE_PRE_ABORT:     return 1; // Always allowed
        UVM_CORE_ABORTED:       return (current_state == UVM_CORE_PRE_ABORT);
        default:                return 0;
      endcase
    endfunction

    virtual function void set_core_state(uvm_core_state state);
      uvm_core_state current_state;
      current_state = get_core_state();

      // Check if the state transition is valid
      if (state == UVM_CORE_PRE_INIT) begin
        uvm_report_fatal("UVM_CORE_STATE", "Cannot set core state to UVM_CORE_PRE_INIT from uvm_coreservice_t instance, only from uvm_init");
      end

      if (!is_valid_state_transition(state, current_state)) begin
        uvm_report_fatal("UVM_CORE_STATE", 
          $sformatf("Invalid state transition from %s to %s", 
                    current_state.name(), state.name()));
      end
      
      m_uvm_core_state.push_front(state);

      // Call the appropriate callback methods
      uvm_core_state_callback::m_do_core_state_change(state, current_state);

    endfunction

    // Function: initialize
    //
    // Initializes the core service and any internal state.
    //
    // This method is called automatically by the <uvm_init> method 
    // after the core service has been determined.  It is not intended
    // to be called by the user. except as `super.initialize()` in a
    // subclass.
    //
    // @uvm-contrib For potential contribution to the 1800.2 standard
    virtual function void initialize();
      // After this point, it should be safe to query the
      // corservice for anything.  We're not done with
      // initialization, but the coreservice (and the
      // various elements it controls) are 'stable'.
      //
      // Note that a user could have something silly
      // in their own space, like a specialization of
      // uvm_root with a constructor that relies on a
      // specialization of uvm_factory with a
      // constructor that relies on the specialized
      // root being constructed...  but there's not
      // really anything that can be done about that.
      
      begin
        uvm_root top;
        top = uvm_root::get();
        // These next calls were moved to uvm_init from uvm_root,
        // because they could emit messages, resulting in the
        // report server being queried, which causes uvm_init.
        top.report_header();
        top.m_check_uvm_field_flag_size();
        // This sets up the global verbosity. Other command line args may
        // change individual component verbosity.
        top.m_check_verbosity();
      end


      // initialize compat fields from uvm_object_globals
      uvm_default_table_printer = new();
      uvm_default_tree_printer = new();
      uvm_default_line_printer = new();
      uvm_default_printer = uvm_default_table_printer;
      uvm_default_packer = new();
      uvm_default_comparer = new();
    endfunction

    local int unsigned m_uvm_global_seed = $urandom;
    virtual function int unsigned get_global_seed();
        return m_uvm_global_seed;
    endfunction

   virtual function bit get_uvm_seeding();
      return uvm_object::use_uvm_seeding;
   endfunction : get_uvm_seeding

   virtual function void set_uvm_seeding(bit enable);
      uvm_object::use_uvm_seeding = enable;
   endfunction : set_uvm_seeding

    local uvm_copier m_copier ;

    virtual function void set_default_copier(uvm_copier copier);
        m_copier = copier ;
    endfunction
    virtual function uvm_copier get_default_copier();
        if (m_copier == null) begin
          m_copier =  new("uvm_default_copier") ;
        end
        return m_copier ;
    endfunction

endclass
