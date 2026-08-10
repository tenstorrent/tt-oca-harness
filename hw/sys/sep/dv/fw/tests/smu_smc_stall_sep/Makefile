TEST = smu_smc_stall_sep
export TEST

EXT_C_FLAGS += -march=rv32imc -mabi=ilp32
EXT_INCS = -I$(OCH_ROOT)/meta/registers/c -I$(OCH_ROOT)/fw/smc/tests/smu_smc_stall_sep/src

include $(OCH_ROOT)/fw/sep/tests/common/common.mk

all: $(TEST).elf

.PHONY: clean
clean:
	rm -f *.o *.elf *.hex *.dis *.sym *.su *.map *.cpp.s
