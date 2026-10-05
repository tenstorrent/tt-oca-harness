<!--SPDX-License-Identifier: CC-BY-4.0-->
<!--SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.-->
# OCAH Nix Infrastructure

If you are new to Nix, see [`nix/glossary.md`](./glossary.md) for an
explanation of the terms used here (flake, derivation, overlay, dev shell,
etc.).

## `flake.nix`

This is the root of the Nix infrastructure, declaring what this repo depends
on (inputs) and what it provides (outputs).

`${system}` in output names is a Nix placeholder for the host platform (e.g.
`x86_64-linux`, `aarch64-darwin`). Nix fills it in automatically.

Currently the flake defines the following outputs:

- `lib` — Helper Nix functions defined in `nix/lib.nix`. Re-exported as a
  flake output so other parts of the flake can reference them without circular
  imports.
- `overlays` — A `default` package overlay that makes the custom packages in
  `nix/packages/*.nix` available by name alongside standard nixpkgs packages.
  Constructed in `nix/package-overlay.nix`.
- `devShells.${system}` — Development shells activated with
  `nix develop $REPO_ROOT#<name>`. Three variants:
  - `without_uv_deps` — All OCAH build and development tools, excluding Python
    packages managed by `uv`. Preferred in most cases, especially when
    modifying Python dependencies.
  - `with_uv_deps` — The above plus `uv`-managed Python packages baked in.
    Primarily for NixOS hosts, where venv-installed packages can fail due to
    hardcoded system paths.
  - `default` — Alias for `without_uv_deps`. `nix develop $REPO_ROOT` (no
    `#name`) activates this.
- `dockerContainers.${system}` — OCI container images built by Nix (no
  Dockerfile). The image is always built for `x86_64-linux` regardless of the
  host platform. Two variants:
  - `without_uv_deps` — All dependencies except `uv` packages. The default
    image used by `docker-run.sh`.
  - `with_uv_deps` — All dependencies including `uv` packages. Useful for
    air-gapped systems where the image is the only package source.
- `formatter.${system}` — Code formatter run with `nix fmt`.

### `.envrc`

This provides integration with [direnv](https://github.com/direnv/direnv), to
automatically load the default development shell upon entering the project
directory. To enable this, install direnv, enter the directory and run
`direnv allow`.

### Updating Inputs

The `flake.lock` file in the repository root locks the flake inputs to provide
a reproducible build. However, this means that the inputs must be updated
manually to move to newer versions of packages. This can be achieved by
running the following command - note that this will update the hashes of the
containers - see [Containers](#containers).

```bash
# leave input to update blank for all inputs
nix flake update [optional input to update]
```

## Dependencies

The package dependencies of OCAH are defined in
[`ocah_deps.nix`](../ocah_deps.nix). This file uses the following structure:

```nix
...
{
  ocah_env = rec {
    # environment variables to always set
    # ...
  } // (if (bundle_uv) then rec {
    # environment variables to set only if uv dependencies are to be included
    # ...
  } else {
    # environment variables to set only if uv dependencies are not to be included
    # ...
  });
  ocah_pkgs = with pkgs; [
    # packages to always include
    # ...
  ] ++ (if (bundle_uv) then [
    # packages to include only if uv dependencies are to be included
    # ...
  ] else [
    # packages to include only if uv dependencies are not to be included
    # ...
  ]);
}
```

This should be straightforward to modify when needed to allow additional
packages/environment variables to be set.

### Custom packages

> **Reminder:** Nix only sees git-tracked files. Run `git add` on any new
> `.nix` file before attempting to build or evaluate.

Packages not available in `nixpkgs`, or needed at a specific version, are
defined as Nix derivations in `nix/packages/<package>.nix`. These are
automatically included in the overlay (see glossary) so they can be added to
`ocah_pkgs` by name just like any standard package. See
[`nix/packages/README.md`](./packages/README.md) for details. These files
rarely need editing — the main reason to touch them is to update a pinned
version.

## Containers

The repository is able to build two different containers (`ocah-container` and
`ocah-uv-container`). The container builds are defined in
[nix/container.nix](./container.nix). This Loads the OCAH Dependencies described
[above](#dependencies), and outputs a container configuration and hash. The
container hashes are pinned to the x86_64-linux build hash for all build
platforms, for consistency.

The containers also include standard utilities for interactive development.
Use `OCAH_IMAGE_WITH_UV=true` to select the `with_uv_deps` variant (default:
`false`). The containers are accessed via `scripts/docker-run.sh`; see
[`scripts/docker.md`](../scripts/docker.md) for usage.

### Reproducibility

Unlike a Dockerfile (hashed only by its text), a Nix container image is
content-addressed: the hash covers every input — package versions, env vars,
build steps. Any change to any input produces a new hash. The container hashes
can be printed with:

```bash
# Without UV Deps
nix eval $REPO_ROOT#containerHashes.without_uv_deps | tr -d '"'

# With UV Deps
nix eval $REPO_ROOT#containerHashes.with_uv_deps | tr -d '"'
```

If you don't have Nix installed, run these commands inside the NixOS shell
(a container that has Nix available):

```bash
$REPO_ROOT/scripts/docker-run.sh nixos-shell
# then run the nix eval commands above
```

To check whether a container tarball matches the expected hash, inspect its
embedded tag (`jq` is not in the OCAH container, so use `nix run` to get it
temporarily):

```bash
tar -xOf <nix-container-image.tar.gz> manifest.json | nix run nixpkgs#jq -- -r '.[0].RepoTags[0]'
```

Note that container tags and names may be trivially faked - so this is not a
security check. A trusted image may only be obtained by building it yourself.
