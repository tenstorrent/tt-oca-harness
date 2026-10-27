# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

# Host unit tests for the SEP BL1 decision logic. The logic sources build unchanged for the
# host; manifest fixtures are packed with the same tool and validator configuration as the
# SEP Boot ROM.

TEST_DIR  := $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))
OCAH_ROOT := $(abspath $(TEST_DIR)/../../../../..)
SEP_BL1   := $(OCAH_ROOT)/hw/sys/sep/bl1
ROM_DIR   := $(OCAH_ROOT)/hw/sys/sep/bootrom/prod
BUILD_DIR ?= $(TEST_DIR)/build

include $(ROM_DIR)/pack.mk
include $(ROM_DIR)/oca_config.mk

CC       ?= cc
SANITIZE ?= -fsanitize=address,undefined -fno-sanitize-recover=all
CFLAGS   := -std=c11 -Wall -Wextra -Werror -O1 -g -MMD -MP
CPPFLAGS := -I$(TEST_DIR) -I$(SEP_BL1)/include -I$(OCAH_ROOT)/hw/sys/smu/bl1/include \
	-I$(ROM_DIR)/include $(OCA_CFLAGS) \
	-I$(OCAH_ROOT)/hw/sys/sep/regs/gen/c -I$(OCAH_ROOT)/hw/sys/smc/regs/gen/c \
	-DUNIT_FIXTURE_DIR='"$(BUILD_DIR)"'

TEST_SRCS  := $(addprefix $(TEST_DIR)/,run_all.c host_sha256.c test_zones.c test_message.c \
	test_secure_state.c test_record.c test_handoff.c)
LOGIC_SRCS := $(addprefix $(SEP_BL1)/src/,zones.c message.c secure_state_cmp.c measure.c \
	handoff.c)

OBJS := $(patsubst $(TEST_DIR)/%.c,$(BUILD_DIR)/test/%.o,$(TEST_SRCS)) \
	$(patsubst $(SEP_BL1)/src/%.c,$(BUILD_DIR)/logic/%.o,$(LOGIC_SRCS)) \
	$(patsubst $(OCA_LIB_DIR)/%.c,$(BUILD_DIR)/oca/%.o,$(OCA_LIB_SRCS))

FIXTURES := $(addprefix $(BUILD_DIR)/,one.bin none.bin two.bin)
RECORD_VECTORS := $(BUILD_DIR)/record_vectors.h

.PHONY: host-test check-consts clean
host-test: $(BUILD_DIR)/run_all $(FIXTURES) check-consts
	$(BUILD_DIR)/run_all

$(BUILD_DIR)/run_all: $(OBJS)
	$(CC) $(SANITIZE) -o $@ $^

$(BUILD_DIR)/test/%.o: $(TEST_DIR)/%.c $(RECORD_VECTORS)
	@mkdir -p $(dir $@)
	$(CC) $(CFLAGS) $(SANITIZE) $(CPPFLAGS) -I$(BUILD_DIR) -c -o $@ $<

$(BUILD_DIR)/logic/%.o: $(SEP_BL1)/src/%.c
	@mkdir -p $(dir $@)
	$(CC) $(CFLAGS) $(SANITIZE) $(CPPFLAGS) -c -o $@ $<

$(BUILD_DIR)/oca/%.o: $(OCA_LIB_DIR)/%.c
	@mkdir -p $(dir $@)
	$(CC) $(CFLAGS) -Wno-pedantic $(SANITIZE) $(CPPFLAGS) -c -o $@ $<

$(RECORD_VECTORS): $(TEST_DIR)/gen_record_vectors.py
	@mkdir -p $(dir $@)
	python3 $< > $@

# Deterministic image bytes, so the packed fixtures are reproducible.
$(BUILD_DIR)/sep_image.bin:
	@mkdir -p $(dir $@)
	python3 -c 'import sys; sys.stdout.buffer.write(bytes(i & 0xFF for i in range(512)))' > $@
$(BUILD_DIR)/smc_image.bin:
	@mkdir -p $(dir $@)
	python3 -c 'import sys; sys.stdout.buffer.write(bytes((i * 7) & 0xFF for i in range(1024)))' > $@

$(BUILD_DIR)/%.bin: $(TEST_DIR)/fixtures/manifests/%.yaml $(BUILD_DIR)/sep_image.bin \
		$(BUILD_DIR)/smc_image.bin | ensure-pack-deps
	cd $(BUILD_DIR) && $(PACK_RUN) --config "$<" --out "$@"

# Compile-only cross-check of the contract against the SMC Boot ROM's definitions.
check-consts:
	@mkdir -p $(BUILD_DIR)
	$(CC) -std=c11 -fsyntax-only $(CPPFLAGS) \
		-I$(OCAH_ROOT)/hw/sys/smc/bootrom/prod/include \
		-I$(OCAH_ROOT)/hw/sys/smc/bootrom/prod/lib/include \
		-I$(OCAH_ROOT)/hw/sys/smc/regs/gen/c/blocks \
		$(TEST_DIR)/check_smc_rom_consts.c

clean:
	rm -rf $(BUILD_DIR)

-include $(OBJS:.o=.d)
