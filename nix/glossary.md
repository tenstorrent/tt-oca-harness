<!--SPDX-License-Identifier: CC-BY-4.0-->
<!--SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.-->
# Nix glossary

A quick reference for Nix concepts used in this repo. No prior Nix knowledge
assumed.

## Nix

A package manager and build system where every package is built
reproducibly: the same inputs always produce exactly the same output. Packages
are stored in `/nix/store/<hash>-<name>/` and never modify the rest of the
system, so multiple versions coexist without conflict and there is no global
`/usr/local` to pollute.

Unlike `apt` or `brew`, Nix does not have a concept of "installing" a package
into the system. Instead, packages are made available in specific contexts
(dev shells, container images) and the rest of the system is unaffected.

## Flake (`flake.nix` / `flake.lock`)

The standard Nix project format used by this repo. `flake.nix` declares:

- **Inputs** — external dependencies (e.g. `nixpkgs`, the main Nix package
  collection). Analogous to entries in a `package.json` or `requirements.txt`.
- **Outputs** — what this repo provides: packages, dev shells, container
  images. Accessed with the `#<name>` selector, e.g.
  `nix build .#ocah-container`.

`flake.lock` pins every input to an exact revision so every checkout of the
repo builds identically, on any machine. Run `nix flake update` to pull in
newer versions of inputs.

> **Important:** Nix flakes only see files that Git knows about. Any new file
> must be staged with `git add` before Nix will find it — an untracked file
> is invisible to the build even if it exists on disk.

## Dev shell (`nix develop`)

A sandboxed shell environment that puts a specific set of tools on `PATH`
without installing anything system-wide. Closing the shell restores your
original environment exactly as it was.

```bash
nix develop          # activates the default dev shell (without_uv_deps)
nix develop .#with_uv_deps   # activates the uv-deps variant
```

With [direnv](https://github.com/direnv/direnv) installed and `direnv allow`
run once, the dev shell activates automatically when you `cd` into the repo.

## Derivation

A Nix build recipe: declares source inputs, build steps, and expected outputs.
Every package in `nix/packages/*.nix` is a derivation. Derivations are
content-addressed — if any input changes, the output hash changes and Nix
rebuilds from scratch rather than reusing a stale artifact.

## Overlay

A layer applied on top of `nixpkgs` that adds or overrides packages. Used
here (`nix/package-overlay.nix`) to make the custom derivations in
`nix/packages/` available by name alongside standard nixpkgs packages, so
they can be listed in `ocah_deps.nix` like any other package.

## nixpkgs

The main Nix package collection — tens of thousands of packages maintained by
the Nix community. The version of nixpkgs used is pinned in `flake.lock`.
Standard tools like `curl`, `git`, `python3` are referenced by their nixpkgs
name in `ocah_deps.nix`.

## `nix eval`

Evaluates a Nix expression and prints its value without building anything.
Used by `docker-run.sh` to compute the container image hash:

```bash
nix eval $REPO_ROOT#containerHashes.without_uv_deps | tr -d '"'
```

## `nix build`

Builds a flake output and places a symlink to the result at `./result`. Used by
`docker-run.sh build` to produce the container image tarball:

```bash
nix build .#dockerContainers.x86_64-linux.without_uv_deps
```

## `nix fmt`

Runs the project formatter declared in `flake.nix` (`formatter.${system}`).
Equivalent to running a project-specific `prettier` or `black`.
