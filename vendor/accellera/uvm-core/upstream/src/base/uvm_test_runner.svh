//
//------------------------------------------------------------------------------
// Copyright 2007-2009 Cadence Design Systems, Inc.
// Copyright 2007-2009 Mentor Graphics Corporation
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
//------------------------------------------------------------------------------

//----------------------------------------------------------------------
// Git details (see DEVELOPMENT.md):
//
// $File:     src/base/uvm_test_runner.svh $
// $Rev:      2026-08-10 12:49:20 -0700 $
// $Hash:     6b8f3b5a4142eb222fd01ec0f2faeb1b3f825924 $
//
//---------------------------------------------------------------------- 

typedef class uvm_object_registry;
typedef class uvm_shared;
typedef class uvm_process_guard_base;
typedef class uvm_objection;

// Class: uvm_test_runner
//
// The UVM test runner is responsible for the execution of the UVM test.
//
// The UVM core service is responsible for instantiating the test runner.
// The test runner is responsible for executing the test.
//
// @uvm-contrib For potential contribution to the 1800.2 standard
class uvm_test_runner extends uvm_object;

  `uvm_object_utils(uvm_test_runner)

  // Function: new
  // Creates a new uvm_test_runner instance with ~name~.
  //
  // @uvm-contrib For potential contribution to the 1800.2 standard
  extern function new(string name="uvm_test_runner");
  
  
  // Group: Singleton Accessors
  
  // Function: get_global_runner
  // Returns the global test runner.
  //
  // @uvm-contrib For potential contribution to the 1800.2 standard
  extern static function uvm_test_runner get_global_runner();
  
  // Group: Test Execution
  
  // Function: get_uvm_testname
  // Returns the name of the test that was specified, if any.
  //
  // Calling this method before <run_test> has been called will result in a fatal error.
  //
  // @uvm-contrib For potential contribution to the 1800.2 standard
  extern virtual function string get_uvm_testname();

  // Task: run_test
  // Executes the test.
  //
  // The following operations are performed in order:
  // a) The UVM core state is set to `UVM_CORE_PRE_RUN` via <set_core_state>.
  // b) If the command-line plusarg `+UVM_TESTNAME=<TEST_NAME>` is found, then the
  //    implementation shall call <create_component_by_name> on the current factory
  //    with ~requested_type_name~ set to the plusarg defined ~<TEST_NAME>~ and ~name~
  //    set to `uvm_test_top`.
  // c) If ~test_name~ is not an ~empty string~ ("") and no name was provided via the 
  //    command-line plusarg, then the implementation shall call <create_component_by_name>
  //    on the current factory with ~requested_type_name~ set to ~test_name~ and ~name~ set
  //    to `uvm_test_top`.
  // d) If no components other than <uvm_root> have been created at this point, either by 
  //    <run_test> or by the user, then the implementation shall generate a fatal message
  //    and <run_test> shall return immediately.
  // e) The UVM core state is set to `UVM_CORE_RUNNING` via <set_core_state>.
  // f) All components are phased through all registered phases (see <uvm_phase_hopper>).
  // g) The UVM core state is set to `UVM_CORE_POST_RUN` via <set_core_state>.
  // h) The <uvm_report_server::report_summarize> method is called on the current report server.
  // i) The UVM core state is set to `UVM_CORE_FINISHED` via <set_core_state>.
  // j) If <uvm_root::get_finish_on_completion> returns `1`, then `$finish` is called; otherwise,
  //    <run_test> shall return.
  // 
  // @uvm-contrib For potential contribution to the 1800.2 standard
  extern virtual task run_test(string test_name="");

  // Function: die
  //
  // This method is called by the report server if a report reaches the maximum
  // quit count or has a UVM_EXIT action associated with it, e.g., as with
  // fatal errors.
  //
  // If the UVM core state is already `UVM_CORE_PRE_ABORT` or `UVM_CORE_ABORTED`,
  // then the method shall return immediately.
  //
  // Otherwise, the following operations are performed in order:
  // a) The UVM core state is set to `UVM_CORE_PRE_ABORT` via <set_core_state>.
  // b) The <uvm_component::pre_abort> method is called on the entire <uvm_component>
  //    hierarchy in a bottom-up fashion.
  // c) The <uvm_report_server::report_summarize> method is called on the current report server.
  // d) The UVM core state is set to `UVM_CORE_ABORTED` via <set_core_state>.
  // e) The simulation is terminated with ~$finish~.
  //
  // @uvm-contrib For potential contribution to the 1800.2 standard
  extern virtual function void die();

  
  // Implementation Artifacts
  local uvm_shared#(string) m_test_name;
endclass

// Implementation details

function uvm_test_runner::new(string name="uvm_test_runner");
  super.new(name);
endfunction

function uvm_test_runner uvm_test_runner::get_global_runner();
  uvm_coreservice_t cs;
  cs = uvm_coreservice_t::get();
  return cs.get_test_runner();
endfunction

function string uvm_test_runner::get_uvm_testname();
  if (m_test_name == null) begin
    `uvm_fatal("UVM/TEST_NAME/EARLY", "get_uvm_testname called before run_test, test name is not set!")
  end
  return m_test_name.value;
endfunction

task uvm_test_runner::run_test(string test_name="");
    uvm_coreservice_t cs;
    uvm_report_server rs;
    uvm_root top;
    string child_name;

    uvm_factory factory;
    bit testname_plusarg;
    int test_name_count;
    string test_names[$];
    string msg;
    uvm_component uvm_test_top;
    uvm_cmdline_processor clp;

    process phase_runner_proc; // store thread forked below for final cleanup

    // Advance the core state to UVM_CORE_PRE_RUN
    cs = uvm_coreservice_t::get();
    cs.set_core_state(UVM_CORE_PRE_RUN);

    factory=uvm_factory::get();
    testname_plusarg = 0;

  // dump cmdline args BEFORE the args are being used
    top = uvm_root::get();
    top.m_do_dump_args();

    m_test_name = new();
    m_test_name.value = test_name;

`ifndef UVM_NO_DPI

    // Retrieve the test names provided on the command line.  Command line
    // overrides the argument.
    clp = uvm_cmdline_processor::get_inst();
    test_name_count = clp.get_arg_values("+UVM_TESTNAME=", test_names);

    // If at least one, use first in queue.
    if (test_name_count > 0) begin
      m_test_name.value = test_names[0];
      testname_plusarg = 1;
    end

    // If multiple, provided the warning giving the number, which one will be
    // used and the complete list.
    if (test_name_count > 1) begin
      string test_list;
      string sep;
      for (int i = 0; i < test_names.size(); i++) begin
        if (i != 0) begin
                
          sep = ", ";
        end

        test_list = {test_list, sep, test_names[i]};
      end
      uvm_report_warning("MULTTST",
            $sformatf("Multiple (%0d) +UVM_TESTNAME arguments provided on the command line.  '%s' will be used.  Provided list: %s.", test_name_count, m_test_name.value, test_list), UVM_NONE);
    end

`else

    `uvm_warning("NO_DPI_USED", "We are thinking of removing support for UVM_NO_DPI.  Please try this test without it and evaluate the impact")
    // plusarg overrides argument
    if ($value$plusargs("UVM_TESTNAME=%s", m_test_name.value)) begin
        `uvm_info("NO_DPI_TSTNAME", "UVM_NO_DPI defined--getting UVM_TESTNAME directly, without DPI", UVM_NONE)
        testname_plusarg = 1;
    end

`endif

    // if test now defined, create it using common factory
    if (get_uvm_testname() != "") begin
        if (top.get_first_child(child_name)) begin
            do begin
                if (child_name == "uvm_test_top") begin
                    uvm_report_fatal("TTINST",
                    "A uvm_test_top already exists via a previous call to run_test", UVM_NONE);
                    #0; // forces shutdown because $finish is forked
                end
            end while (top.get_next_child(child_name));
        end

        $cast(uvm_test_top, factory.create_component_by_name(get_uvm_testname(),
                    "", "uvm_test_top", null));

        if (uvm_test_top == null) begin
            msg = testname_plusarg ? {"command line +UVM_TESTNAME=",get_uvm_testname()} :
                {"call to run_test(",get_uvm_testname(),")"};
            uvm_report_fatal("INVTST",
                    {"Requested test from ",msg, " not found." }, UVM_NONE);
        end
    end

    if (!top.get_first_child(child_name)) begin
      uvm_report_fatal("NOCOMP",
            {"No components instantiated. You must either instantiate",
                " at least one component before calling run_test or use",
                " run_test to do so. To run a test using run_test,",
                " use +UVM_TESTNAME or supply the test name in",
                " the argument to run_test(). Exiting simulation."}, UVM_NONE);
      return;
    end

    begin
      if(get_uvm_testname()=="") begin
            
        uvm_report_info("RNTST", "Running test ...", UVM_LOW);
      end

      else if (get_uvm_testname() == uvm_test_top.get_type_name()) begin
            
        uvm_report_info("RNTST", {"Running test ",get_uvm_testname(),"..."}, UVM_LOW);
      end

      else begin
            
        uvm_report_info("RNTST", {"Running test ",uvm_test_top.get_type_name()," (via factory override for test \"",get_uvm_testname(),"\")..."}, UVM_LOW);
      end

    end

    // phase runner, isolated from calling process
    // Note: Using a fork here may not be necessary.  If the calling
    // process is disabled, then this process continues,
    // but if the calling process is killed then this
    // process is killed.  
    fork 
      begin
        // spawn the phase runner task
        uvm_phase_hopper hopper;
        hopper = uvm_phase_hopper::get_global_hopper();
        cs.set_core_state(UVM_CORE_RUNNING);
        hopper.run_phases();
      end
    join

    cs.set_core_state(UVM_CORE_POST_RUN);

    rs = uvm_report_server::get_server();


    // TODO: Mantis 8579
    // Move this method (and call) to a more appropriate place
    top.m_do_cmdline_checks();
  
    rs.report_summarize();

    cs.set_core_state(UVM_CORE_FINISHED);

    if (top.get_finish_on_completion()) begin
    
        $finish;
    end


endtask

function void uvm_test_runner::die();
  uvm_coreservice_t cs;
  uvm_root top;
  uvm_report_server rs;

  // Only die once
  if (get_core_state() inside {UVM_CORE_PRE_ABORT, UVM_CORE_ABORTED}) begin
    return;
  end

  cs = uvm_coreservice_t::get();
  top = uvm_root::get();
  rs = uvm_report_server::get_server();

  cs.set_core_state(UVM_CORE_PRE_ABORT);
  top.m_do_pre_abort();
  rs.report_summarize();
  cs.set_core_state(UVM_CORE_ABORTED);

  $finish;
endfunction

