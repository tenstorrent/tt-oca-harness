# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

ifndef ocah_help_mk
ocah_help_mk := 1

.PHONY: help
# One shell command rather than a line per echo: an including makefile may set
# .ONESHELL with a SHELL make cannot identify as POSIX, and there make leaves
# the recipe-prefix characters of every line but the first for the shell to
# choke on.
help:
	@$(if $(HELP_TITLE),echo $(HELP_TITLE);) \
	$(if $(HELP_DESCRIPTION),echo $(HELP_DESCRIPTION);) \
	echo ""; \
	MAKEFILES="$(MAKEFILE_LIST)" bash "$(OCAH_ROOT)/scripts/generate-makefile-help.sh"

endif
