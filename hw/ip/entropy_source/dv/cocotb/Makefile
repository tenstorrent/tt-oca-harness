# Try git first, fall back to OCH_ROOT, fail if neither available
_OCH_ROOT_GIT := $(shell git rev-parse --show-toplevel 2>/dev/null)
ifneq ($(_OCH_ROOT_GIT),)
  OCH_ROOT := $(_OCH_ROOT_GIT)
else ifndef OCH_ROOT
  $(error Not in a git repository and OCH_ROOT is not set)
endif

TOPLEVEL_LANG = verilog

SIM ?= vcs
WAVES ?= 1
DEBUG ?= 0

COCOTB_HDL_TIMEUNIT = 1ns
COCOTB_HDL_TIMEPRECISION = 1ps

# Packages
VERILOG_SOURCES += $(OCH_ROOT)/hw/comp/entropy_source/data/registers/rtl/entropy_source_reg_pkg.sv
VERILOG_SOURCES += $(OCH_ROOT)/hw/comp/entropy_source/rtl/entropy_source_pkg.sv
# Level 0
VERILOG_SOURCES += $(OCH_ROOT)/hw/comp/entropy_source/rtl/gcells.sv
VERILOG_SOURCES += $(OCH_ROOT)/hw/comp/entropy_source/rtl/gf_muladd.sv
# Level 1
VERILOG_SOURCES += $(OCH_ROOT)/hw/comp/entropy_source/data/registers/rtl/entropy_source_reg.sv
VERILOG_SOURCES += $(OCH_ROOT)/hw/comp/entropy_source/rtl/entropy_ring_oscillator.sv
# Level 2
VERILOG_SOURCES += $(OCH_ROOT)/hw/comp/entropy_source/rtl/entropy_decorrelator.sv
VERILOG_SOURCES += $(OCH_ROOT)/hw/comp/entropy_source/rtl/entropy_noise_source.sv
VERILOG_SOURCES += $(OCH_ROOT)/hw/comp/entropy_source/rtl/entropy_rosc_tune_fsm.sv
# Level 3
VERILOG_SOURCES += $(OCH_ROOT)/hw/comp/entropy_source/rtl/entropy_adaptive_proportion_test.sv
VERILOG_SOURCES += $(OCH_ROOT)/hw/comp/entropy_source/rtl/entropy_generator.sv
VERILOG_SOURCES += $(OCH_ROOT)/hw/comp/entropy_source/rtl/entropy_markov_test.sv
VERILOG_SOURCES += $(OCH_ROOT)/hw/comp/entropy_source/rtl/entropy_repetition_test.sv
VERILOG_SOURCES += $(OCH_ROOT)/hw/comp/entropy_source/rtl/entropy_sampler_clocks.sv
# Level 4
VERILOG_SOURCES += $(OCH_ROOT)/hw/comp/entropy_source/rtl/entropy_debug_monitor.sv
VERILOG_SOURCES += $(OCH_ROOT)/hw/comp/entropy_source/rtl/entropy_fifo.sv
VERILOG_SOURCES += $(OCH_ROOT)/hw/comp/entropy_source/rtl/entropy_generator_complex.sv
VERILOG_SOURCES += $(OCH_ROOT)/hw/comp/entropy_source/rtl/entropy_health_test.sv
# Top Level
VERILOG_SOURCES += $(OCH_ROOT)/hw/comp/entropy_source/rtl/entropy_source.sv
# Testbench
VERILOG_SOURCES += $(OCH_ROOT)/hw/comp/entropy_source/tb_cocotb/tb_entropy_source.sv

DUT      = tb_entropy_source
TOPLEVEL = $(DUT)
MODULE   = test_entropy_source

COMPILE_ARGS += +define+USE_PROTECTED_FILE
COMPILE_ARGS += +define+MVLS_VOLTAGE_MODEL
COMPILE_ARGS += -lca +rad -kdb +nospecify
COMPILE_ARGS += -debug_access+r+w+cbk -debug_access+thread+class+cbkd+dmpt+dmpf+idents_db
COMPILE_ARGS += -l vcs.log +define+NO_LIBCELL +define+DISABLE_ASSERT +define+SIM+USE_VERILOG_MEM_ARRAY
COMPILE_ARGS += +define+VCS -assert svaext +define+LOADMEM +define+SOTP_SET_PWR_ON=50 +define+SOTP_PRG_CNT_CHECK=0
COMPILE_ARGS += +lint=TFIPC-L +lint=PCWM
# TODO # COMPILE_ARGS += -f $(OCH_ROOT)/hw/comp/entropy_source/tb_vcs/entropy_source.f

SIM_ARGS += -assert nopostproc +vcs+dumparrays +vcs+lic+wait +embedded_skipper_debug +initRandMem=1

STRESS ?= 0

ifeq ($(STRESS), 1)
    PLUSARGS += +stress
endif

ifeq ($(WAVES), 1)
    SIM_ARGS += +waves +fsdb+delta +vcs+dumparrays
endif

ifeq ($(DEBUG), 0)
    COMPILE_ARGS += -debug_access-memcbk
endif

# include cocotb's make rules to take care of the simulator setup
include $(shell cocotb-config --makefiles)/Makefile.sim

clean:: # cocotb's own `clean` uses double colon
	rm -rf __pycache__

# TODO # filelist:
# TODO # 	bender script flist-plus -t common_cells_rtl -t apb_rtl -t axi_rtl -t component > entropy_source.f
