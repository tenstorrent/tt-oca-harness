#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

#
# Create a version string for the OCH SEP BL0 firmware.
#
# The version is a semantic version string of the form: X.Y.Z+buildmetadata
# Where X is the major version, Y is the minor version, Z is the patch version.
# The version identifies the source code used to build the firmware.
#
# The build metadata contains information about how the firmware was built.
#
# If the build metadata contains "release", then the firmware is a release build.
# If the build metadata contains "test", then the firmware uses test keys.
# If the build metadata contains "dev", then the firmware is a development build.
#
# Version-string generation for this ROM.

import argparse
import re
import os
import sys
from subprocess import run, check_output
import logging

TAG_PREFIX  = 'SEP_BL0_v'
TAG_PATTERN = f'{TAG_PREFIX}*'


def check_semver(value):
    pattern = re.compile(f'^{TAG_PREFIX}(?P<major>0|[1-9]\\d*)\\.(?P<minor>0|[1-9]\\d*)\\.(?P<patch>0|[1-9]\\d*)(?:-(?P<prerelease>(?:0|[1-9]\\d*|\\d*[a-zA-Z-][0-9a-zA-Z-]*)(?:\\.(?:0|[1-9]\\d*|\\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?(?:\\+(?P<buildmetadata>[0-9a-zA-Z-]+(?:\\.[0-9a-zA-Z-]+)*))?$')
    match = pattern.match(value)
    if not match:
        logging.warning(f"SEP version '{value}' is not a semver, missing tags?")
        return

    logging.debug(f"Major: {match.group('major')}")
    logging.debug(f"Minor: {match.group('minor')}")
    logging.debug(f"Patch: {match.group('patch')}")
    logging.debug(f"Prerelease: {match.group('prerelease')}")
    logging.debug(f"Build metadata: {match.group('buildmetadata')}")


def main():
    parser = argparse.ArgumentParser(description='Generate the OCH SEP version string')
    parser.add_argument('--build-type', '-t', action='store', default='test',
                        help='Build type from Makefile', choices=['test', 'release'])
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    args = parser.parse_args()

    logging.basicConfig(format='%(levelname)s: %(message)s',
                        level=logging.DEBUG if args.verbose else logging.INFO)

    # Check if the current commit is tagged with a SEP version tag.
    exact_tag = False
    p = run(['git', 'describe', '--exact-match', '--match', TAG_PATTERN], capture_output=True)
    if p.returncode == 0:
        logging.debug(f"Exact tag found: {p.stdout.decode('utf-8').strip()}")
        exact_tag = True

    # Run git describe to get the details.
    version = check_output(
        ['git', 'describe', '--abbrev=16', '--long', '--always', '--dirty',
         '--match', TAG_PATTERN]
    ).decode('utf-8').strip()
    logging.debug(f"Git describe: {version}")

    parts = version.split('-')
    base = parts[0]
    tail = parts[1:]

    dirty_tree = 'dirty' in version
    if dirty_tree:
        logging.debug("Dirty build")

    if args.build_type == 'test':
        tail.insert(0, 'test')

    if args.build_type == 'release' and exact_tag and not dirty_tree:
        tail.insert(0, 'release')
    else:
        tail.insert(0, 'dev')

    tail = '.'.join(tail)
    version = f"{base}+{tail}"

    logging.debug(f"SEP version: {version}")
    check_semver(version)

    print(version)

    return 0

if __name__ == '__main__':
    sys.exit(main())
