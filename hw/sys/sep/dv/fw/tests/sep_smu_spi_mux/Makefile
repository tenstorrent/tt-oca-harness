TEST = sep_smu_spi_mux
export TEST

EXT_C_FLAGS += -march=rv32imc -mabi=ilp32 -fno-ipa-icf -fno-ipa-cp
EXT_LD_FLAGS += -Wl,--undefined=smu_sep_spi_mux_fail_loop
EXT_INCS = -I$(OCH_ROOT)/meta/registers/c
EXT_INCS += -I$(OCH_ROOT)/fw/sep/tests/common

include $(OCH_ROOT)/fw/sep/tests/common/common.mk

all: $(TEST).elf

.PHONY: clean
clean:
	rm -f *.o *.elf *.hex *.dis *.sym *.su *.map *.cpp.s *.itcm.hex *.dtcm.hex
