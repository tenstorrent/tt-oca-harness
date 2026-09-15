#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Print one sha256 over an ordered list of files.

The blob manifest and the run-time provenance check in sep_base_test both call
this, so the two cannot drift apart on how the digest is formed. The order of
the arguments is part of the digest; callers must pass the same list.
"""
import hashlib
import sys


def digest(paths: list[str]) -> str:
    h = hashlib.sha256()
    for p in paths:
        with open(p, "rb") as fh:
            # Length-prefix each file so concatenation cannot be ambiguous.
            data = fh.read()
        h.update(str(len(data)).encode())
        h.update(b"\0")
        h.update(data)
    return h.hexdigest()


if __name__ == "__main__":
    print(digest(sys.argv[1:]))
