# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
# Host unit tests for ROM drivers. Needs only a host C compiler: the drivers' MMIO
# goes to a fake register file through mock/rom_mmio.h, which shadows the ROM's own.

HOST_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
PROD_DIR := $(abspath $(HOST_DIR)/../..)
SEP_REGS := $(abspath $(PROD_DIR)/../../regs/gen/c)
BUILD    ?= $(HOST_DIR)/build

CFLAGS := -std=c99 -Wall -Wextra -Werror -pedantic -O1 -g -MMD -MP
SANITIZE ?= -fsanitize=address,undefined -fno-sanitize-recover=all
CPPFLAGS := -DABR_DRV_EXPOSE_STEPS -I$(HOST_DIR)/mock -I$(HOST_DIR) -I$(PROD_DIR)/include -I$(SEP_REGS)

ABR_SRCS := $(HOST_DIR)/test_abr_driver.c $(HOST_DIR)/fake_abr.c $(PROD_DIR)/src/abr_driver.c
ABR_TEST := $(BUILD)/test_abr_driver

# Drivers that include sep.h need the ROM's full register include set, and C11 for
# the static_assert the generated headers close with. The mock is force-included
# so that it, not include/rom_mmio.h, defines the MMIO accessors whichever header
# a source includes first.
OCAH_ROOT := $(abspath $(PROD_DIR)/../../../../..)
include $(OCAH_ROOT)/hw/common/dv/fw/reg_includes.mk
ROM_BUILD := $(BUILD)/rom
ROM_CFLAGS := -std=c11 -Wall -Wextra -Werror -pedantic -O1 -g -MMD -MP
ROM_CPPFLAGS := -DDEBUG -include $(HOST_DIR)/mock/rom_mmio.h -I$(HOST_DIR)/mock -I$(HOST_DIR) \
	-I$(PROD_DIR)/include -I$(ROM_BUILD) $(call ocah_fw_reg_includes,sep) $(call ocah_fw_reg_includes,smc)

DMA_SRCS := $(HOST_DIR)/test_sep_dma.c $(HOST_DIR)/fake_sep_dma.c $(PROD_DIR)/src/sep_dma.c
DMA_TEST := $(BUILD)/test_sep_dma
DMA_OBJS := $(patsubst %.c,$(ROM_BUILD)/%.o,$(notdir $(DMA_SRCS)))

# rom_mem_clear.c is built once per scrub length: off, the whole of SEP SRAM, and
# longer than SEP SRAM (clamped). Each build links its own copy of the clear and
# of its test, with the shared driver and fake.
SCRUB_LENS := 0 0x40000 0x40004
CLEAR_TESTS := $(foreach n,$(SCRUB_LENS),$(BUILD)/test_rom_mem_clear_$(n))
CLEAR_SHARED_OBJS := $(ROM_BUILD)/fake_sep_dma.o $(ROM_BUILD)/sep_dma.o

.PHONY: all clean
all: $(ABR_TEST) $(DMA_TEST) $(CLEAR_TESTS) scrub-length-must-be-words
	$(ABR_TEST)
	$(DMA_TEST)
	$(foreach t,$(CLEAR_TESTS),$(t) &&) true

# The flags are part of the build: a change to them rebuilds the test.
$(BUILD)/cflags: FORCE | $(BUILD)
	@echo '$(CC) $(CFLAGS) $(SANITIZE) $(CPPFLAGS)' | cmp -s - $@ || echo '$(CC) $(CFLAGS) $(SANITIZE) $(CPPFLAGS)' > $@

ABR_OBJS := $(patsubst %.c,$(BUILD)/%.o,$(notdir $(ABR_SRCS)))
vpath %.c $(HOST_DIR) $(PROD_DIR)/src

$(ABR_TEST): $(ABR_OBJS)
	$(CC) $(SANITIZE) -o $@ $^

$(BUILD)/%.o: %.c $(BUILD)/cflags | $(BUILD)
	$(CC) $(CFLAGS) $(SANITIZE) $(CPPFLAGS) -c -o $@ $<

-include $(ABR_OBJS:.o=.d)

$(ROM_BUILD)/cflags: FORCE | $(ROM_BUILD)
	@echo '$(CC) $(ROM_CFLAGS) $(SANITIZE) $(ROM_CPPFLAGS)' | cmp -s - $@ || echo '$(CC) $(ROM_CFLAGS) $(SANITIZE) $(ROM_CPPFLAGS)' > $@

# The same macro-only header the ROM build extracts for vector.S.
SMC_BASE_CONFIG_H := $(firstword $(wildcard $(addsuffix /smc_base_config.h,$(patsubst -I%,%,$(call ocah_fw_reg_includes,smc)))))
ifeq ($(SMC_BASE_CONFIG_H),)
$(error smc_base_config.h not found on the SMC register include path; run make regen-regs)
endif
$(ROM_BUILD)/smc_local_base.h: $(SMC_BASE_CONFIG_H) | $(ROM_BUILD)
	grep -E '^#define SMC_BASE_CONFIG__LOCAL_BASE__BASE_reset 0x[0-9a-fA-F]+$$' "$<" > "$@"

$(DMA_TEST): $(DMA_OBJS)
	$(CC) $(SANITIZE) -o $@ $^

$(ROM_BUILD)/%.o: %.c $(ROM_BUILD)/cflags $(ROM_BUILD)/smc_local_base.h | $(ROM_BUILD)
	$(CC) $(ROM_CFLAGS) $(SANITIZE) $(ROM_CPPFLAGS) -c -o $@ $<

-include $(DMA_OBJS:.o=.d)

define clear_test
$(ROM_BUILD)/scrub_$(1):
	mkdir -p $$@
$(ROM_BUILD)/scrub_$(1)/%.o: %.c $(ROM_BUILD)/cflags $(ROM_BUILD)/smc_local_base.h | $(ROM_BUILD)/scrub_$(1)
	$$(CC) $$(ROM_CFLAGS) $$(SANITIZE) $$(ROM_CPPFLAGS) -DSRAM_SCRUB_BYTES=$(1) -c -o $$@ $$<
$(BUILD)/test_rom_mem_clear_$(1): $(ROM_BUILD)/scrub_$(1)/test_rom_mem_clear.o \
		$(ROM_BUILD)/scrub_$(1)/rom_mem_clear.o $(CLEAR_SHARED_OBJS)
	$$(CC) $$(SANITIZE) -o $$@ $$^
-include $(ROM_BUILD)/scrub_$(1)/*.d
endef
$(foreach n,$(SCRUB_LENS),$(eval $(call clear_test,$(n))))

# A scrub length that is not whole words must not build.
.PHONY: scrub-length-must-be-words
scrub-length-must-be-words: $(ROM_BUILD)/smc_local_base.h
	@if $(CC) $(ROM_CFLAGS) $(ROM_CPPFLAGS) -MF /dev/null -DSRAM_SCRUB_BYTES=0x3 -fsyntax-only \
		$(PROD_DIR)/src/rom_mem_clear.c 2>&1 | grep -q 'must be a whole number of 32-bit words'; then \
		echo "ok   rom_mem_clear.c refuses SRAM_SCRUB_BYTES=0x3"; \
	else echo "FAIL rom_mem_clear.c does not refuse SRAM_SCRUB_BYTES=0x3"; exit 1; fi

$(BUILD) $(ROM_BUILD):
	mkdir -p $@

clean:
	rm -rf $(BUILD)

.PHONY: FORCE
FORCE:
