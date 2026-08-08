TEST = sep_smc_xbar
export TEST

EXT_C_FLAGS += -march=rv32imc -mabi=ilp32
EXT_INCS = -I$(OCH_ROOT)/meta/registers/c -I$(OCH_ROOT)/fw/smc/tests/smc_sep_xbar/src

include $(OCH_ROOT)/fw/sep/tests/common/common.mk

all: $(TEST).elf

.PHONY: clean
clean:
	rm -f *.o *.elf *.hex *.dis *.sym *.su *.map *.cpp.s
