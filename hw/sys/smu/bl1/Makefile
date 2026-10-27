# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

# SMU first-stage boot: the SEP BL1 to SMC BL1 contract, its host tests, and the boot images
# that carry both BL1s.

BL1_SMU_DIR := $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))

.PHONY: host-test
host-test:
	$(MAKE) -C $(BL1_SMU_DIR)/test host-test
