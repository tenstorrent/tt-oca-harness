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

.PHONY: all clean
all: $(ABR_TEST)
	$(ABR_TEST)

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

$(BUILD):
	mkdir -p $@

clean:
	rm -rf $(BUILD)

.PHONY: FORCE
FORCE:
