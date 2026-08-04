TEST = sep_smc_interop
export TEST

EXT_C_FLAGS += -march=rv32imc -mabi=ilp32
EXT_INCS = -I$(OCH_ROOT)/meta/registers/c -I$(OCH_ROOT)/fw/smc/tests/sep_interop/src

include $(OCH_ROOT)/fw/sep/tests/common/common.mk

all: $(TEST).elf

# clean target is provided by fw/sep/tests/common/common.mk
