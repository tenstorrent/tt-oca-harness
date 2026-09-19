# scripts/docker-run.sh

Helper for running repo commands inside the OCAH container. The container
image is built by Nix and identified by a hash derived from the flake output,
so every host runs the same image as CI.

## Commands

```bash
docker-run.sh build
docker-run.sh ensure
docker-run.sh verify
docker-run.sh run CMD...
docker-run.sh run-here CMD...
docker-run.sh shell
docker-run.sh shell-here
docker-run.sh nixos-shell
docker-run.sh doc-html [trm|integrator|programmer|appnotes|home|starting|all]
docker-run.sh doc-pdf  [trm|integrator|programmer|appnotes|starting]
docker-run.sh doc-stage
```

| Command | Description |
|---------|-------------|
| `build` | Build the container image via Nix and publish it to the shared tarball cache (if `OCAH_DOCKER_CACHE_DIR` is set), or `local/nix-container-image.tar.gz` otherwise. |
| `ensure` | Make the image available locally: reuse a matching loaded image, load the cached tarball, or build. Called automatically by `run`/`run-here`/`shell`/`verify`. |
| `verify` | Print `riscv64-unknown-elf-gcc --version` and `-print-multi-lib` as a quick sanity check. |
| `run CMD` | Run `CMD` inside the container with the repo mounted at `/work`. |
| `run-here CMD` | Run `CMD` with the repo mounted at its own host-absolute path and the caller's `cwd` preserved. Use this when commands embed absolute paths (e.g. bender-generated filelists). |
| `shell` | Interactive bash shell inside the container (`run`-style, repo at `/work`). |
| `shell-here` | Interactive bash shell with 1:1 host paths (`run-here`-style). |
| `nixos-shell` | Interactive shell in the NixOS build image (for debugging the container build itself). |
| `doc-html [PRODUCT\|all]` | Build HTML docs with Antora. `all` builds the combined multi-book site (`antora-playbook.yml`). |
| `doc-pdf [PRODUCT]` | Build a PDF with Asciidoctor-pdf. |
| `doc-stage` | Copy PDFs and add `.nojekyll` into an already-built combined HTML site. No container needed — run after `doc-html all` + `doc-pdf`. |

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OCAH_NIXOS_IMAGE` | `docker.io/nixos/nix:latest` | NixOS image used to run Nix on hosts without a local Nix install. |
| `OCAH_IMAGE_WITH_UV` | `false` | When `true`, uses the `ocah-uv-container` image (with uv-installed Python deps bundled) instead of `ocah-container`. |
| `OCAH_DOCKER_CACHE_DIR` | _(unset)_ | Directory for the shared tarball image cache. When set, `build` publishes there and `ensure` checks it before building. CI sets this via its environment setup. |
| `OCAH_DOCKER_UIDGID` | _(auto)_ | `--user` passed to the container engine. Defaults to empty for rootless podman (identity already mapped), or `uid:gid` for docker. Set to empty to run as the image's own default user. |
| `OCAH_PODMAN_DIR` | _(unset)_ | Explicit base for Podman runtime and storage. When unset, `/tmp/ocah-podman-<uid>` is used only if `XDG_RUNTIME_DIR` is unwritable. |
| `OCAH_SKIP_GID_FIXUP` | `0` | Set to `1` to skip the automatic re-exec under the passwd primary group (see [GID fixup](#gid-fixup) below). |
| `OCAH_TOOLCHAIN_ROOTFS` | _(unset)_ | Path to a rootfs extracted from the container image. When set and `bwrap` is present, `run`/`run-here`/`shell`/`verify` use bubblewrap instead of podman/docker (see [Bubblewrap backend](#bubblewrap-backend)). |
| `OCAH_BWRAP_EXTRA_BINDS` | _(unset)_ | Space-separated list of extra host paths to bind into the bubblewrap sandbox at their own paths. |

## Nix integration

The container image is a Nix flake output — see
[`nix/nix-infrastructure.md`](../nix/nix-infrastructure.md) for the full
picture of the flake structure, dependency definitions, and how the two image
variants are built. If you are new to Nix, [`nix/glossary.md`](../nix/glossary.md)
explains the key terms.

The relevant flake outputs are:

| Flake output | Image name | When used |
|---|---|---|
| `dockerContainers.x86_64-linux.without_uv_deps` | `ocah-container` | Default (`OCAH_IMAGE_WITH_UV=false`) |
| `dockerContainers.x86_64-linux.with_uv_deps` | `ocah-uv-container` | `OCAH_IMAGE_WITH_UV=true` |

The image tag is computed at runtime by evaluating
`#containerHashes.{without,with}_uv_deps` from the flake:

```bash
nix eval $REPO_ROOT#containerHashes.without_uv_deps | tr -d '"'
```

`build` runs `nix build` against the matching flake output. `ensure` evaluates
the hash and checks whether a loaded image with that tag already exists before
triggering a build.

On hosts **without Nix installed**, all nix operations (`build`, `ensure`,
`image_hash`) are transparently proxied through a container running
`OCAH_NIXOS_IMAGE` (default `docker.io/nixos/nix:latest`). The `nixos-shell`
command opens an interactive shell in that same image, which is useful for
debugging the container build without a local Nix install.

### Adding packages to the container

The container has no package manager — `apt`, `yum`, and similar tools are not
available. To add a package, edit [`ocah_deps.nix`](../ocah_deps.nix) (for
packages that should also appear in the dev shell) or
[`nix/container.nix`](../nix/container.nix) (for container-only additions),
then rebuild with `./scripts/docker-run.sh build`. See
[`nix/nix-infrastructure.md`](../nix/nix-infrastructure.md) for details on
the dependency structure.

## Image identity

The image name is `ocah-container` (or `ocah-uv-container` when
`OCAH_IMAGE_WITH_UV=true`), tagged with a hash computed from the flake output.
`ensure` matches against this hash so a stale locally-loaded image is never
silently reused.

## Bubblewrap backend

When `OCAH_TOOLCHAIN_ROOTFS` is set and `bwrap` is available, `run` /
`run-here` / `shell` / `verify` bypass the container engine entirely and run
inside a bubblewrap sandbox. This avoids the rootless-podman user-namespace
setup that fails on some CI/LSF nodes (GID mismatch, no `XDG_RUNTIME_DIR`).

The sandbox mounts the rootfs directories read-only under a tmpfs root, then
binds the repo at its real host path so absolute paths work unchanged. `/tmp`
is shared with the host; `/dev` and `/proc` are fresh.

To extract a rootfs from the container image:

```bash
./scripts/docker-run.sh ensure
mkdir -p local/rootfs
podman export $(podman create ocah-container:<hash>) | tar -xC local/rootfs
export OCAH_TOOLCHAIN_ROOTFS=$PWD/local/rootfs
```

## GID fixup

Rootless podman's `newuidmap`/`newgidmap` require the process's primary GID to
match the account's `/etc/passwd` primary GID. CI/LSF nodes sometimes launch
jobs under an inherited SGID directory group, breaking this. The script
detects the mismatch and re-execs itself under the correct group via `sg`
before podman starts. Set `OCAH_SKIP_GID_FIXUP=1` to disable this.
