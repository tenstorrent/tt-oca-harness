# OCAH Nix Infrastructure

## `flake.nix`

This is the root of the nix infrastructure, defining the inputs and accessible outputs. 

Currently the flake defines the following outputs:

- `lib` - Several nix functions, defined in `nix/lib.nix`. These are exported to be looped back in for cleaner code.
- `overlays` - Exports a `default` package overlay, which provides the custom packages declared in `nix/packages/*.nix`. This overlay is constructed in `nix/package-overlay.nix`.
- `devShells.${system}` - Defines several development shells for different host platforms - these may be accessed by running `nix develop $REPO_ROOT#<shell>
  - `without_uv_deps` - Bundles all packages used for developing OCAH, minus the packages installed via UV. This should be preferred in most cases, especially when the development involves modifying the UV dependencies.
  - `with_uv_deps` - This includes the above, as well as bundling in the UV dependencies defined in `uv.lock` - this is mostly for use on NixOS, where venv-installed packages can occasionally fail due to hardcoded system paths.
  - `default` - an alias for `without_uv_deps` - `nix develop $REPO_ROOT` will activate this shell.
- `dockerContainers.${system}` - Defines builds of x86_64-linux Docker containers for different build platforms, the containers able to be built are as follows:
  - `without_uv_deps` - Corresponds roughly to the `without_uv_deps` shell - a container including all package dependencies of OCAH, minus UV packages.
  - `with_uv_deps` - Corresponds similarly to the `with_uv_deps` shell - contains all dependencies of OCAH, including UV Packages. This may be useful in an airgapped system, as it provides all dependencies in a single image.
- `formatter.${system}` - Declares a formatter able to be run with `nix fmt`
    

### `.envrc`

This provides integration with [direnv](https://github.com/direnv/direnv), to automatically load the default development shell upon entering the project directory. To enable this, install direnv, enter the directory and run `direnv allow`.

### Updating Inputs

The `flake.lock` file in the repository root locks the flake inputs to provide a reproducible build. However, this means that the inputs must be updated manually to move to newer versions of packages. This can be achieved by running the following command - note that this will update the hashes of the containers - see [Containers](#containers).

```bash
# leave input to update blank for all inputs
nix flake update [optional input to update]
```

## Dependencies

The package dependencies of OCAH are defined in [`ocah_deps.nix`](../ocah_deps.nix). This file uses the following structure:

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

This should be straightforward to modify when needed to allow additional packages/environment variables to be set.

### Source Dependencies

OCAH depends on pinned versions of several packages, which are defined in `nix/packages/<package>.nix`. These files provide nix derivations (reproducible build scripts) for each package. These shouldn't need modification, other than if the versions are to be updated. See [the included details](./packages/README.md) for more information. Source dependencies are automatically constructed into an overlay, and can then be listed in the above `ocah_pkgs` as `<package>`.

## Containers

The repository is able to build two different containers (`ocah-container` and `ocah-uv-container`). The container builds are defined in [nix/container.nix](./container.nix). This Loads the OCAH Dependencies described [above](#dependencies), and outputs a container configuration and hash. The container hashes are pinned to the x86_64-linux build hash for all build platforms, for consistency.

The containers also include some standard utilities, allowing development to proceed in the container. The containers may be accessed using the `docker-run.sh` script.

The `OCAH_NIX_IMAGE_WITH_UV=true` environment variable may optionally be set to bundle UV dependencies in the build container - defaults to `false`


### Reproducibility

The container configurations are hashed in a similar manner to a traditional `dockerFile`. The container hashes may be printed using the following command:

```bash
# Without UV Deps
nix eval $REPO_ROOT#containerHashes.without_uv_deps | tr -d '"'

# With UV Deps
nix eval $REPO_ROOT#containerHashes.with_uv_deps | tr -d '"'
```

If you don't have `nix` installed, this may be run in a NixOS container shell, accessed using the following:

```bash
$REPO_ROOT/scripts/docker-run.sh nixos-shell
```

When using an external container file, you can check it is up-to-date by running:

```bash
tar -xOf <nix-container-image> manifest.json | jq -r '.[0].RepoTags[0]'
# Or, in the container shell, as `jq` isn't already installed
tar -xOf <nix-container-image> manifest.json | nix run nixpkgs#jq -- -r '.[0].RepoTags[0]'
```

Note that container tags and names may be trivially faked - so this is not a security check. A trusted image may only be obtained by building it yourself.
