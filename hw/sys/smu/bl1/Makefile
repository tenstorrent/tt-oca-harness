# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

# SMU first-stage boot: the SEP BL1 to SMC BL1 contract, its host tests, and the boot images
# that carry both BL1s.

BL1_SMU_DIR := $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))
SMC_BL1_DIR := $(abspath $(BL1_SMU_DIR)/../../smc/bl1)
BUILD_TYPE  ?= debug
BUILD_DIR   ?= $(BL1_SMU_DIR)/build

# SMC BL1 variants that misbehave on purpose, for the SEP BL1's negative scenarios.
FIXTURES := silent bad_tag wrong_challenge self_modify

.PHONY: host-test fixtures clean
host-test:
	$(MAKE) -C $(BL1_SMU_DIR)/test host-test

fixtures:
ifeq ($(BUILD_TYPE),release)
	$(error release builds refuse the SMC BL1 test fixtures)
endif
	@for f in $(FIXTURES); do \
	  $(MAKE) -f $(SMC_BL1_DIR)/Makefile BUILD_TYPE=$(BUILD_TYPE) NAME=smc_bl1_$$f \
	    MAIN_SRC=$(BL1_SMU_DIR)/test/fixtures/$$f/main.c BUILD_DIR=$(BUILD_DIR) \
	    OUT_DIR=$(BUILD_DIR)/$(BUILD_TYPE)/fixtures toolchain-images || exit 1; \
	done

clean:
	rm -rf $(BUILD_DIR)
