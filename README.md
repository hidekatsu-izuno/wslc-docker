# wslc-docker

Docker-style command wrappers and Compose support for Microsoft's WSL container CLI (`wslc`). This project includes a Debian package and a GitHub Actions workflow that tests the adapters and builds a `.deb` on pushes, tags, and pull requests.

This is a command-line compatibility layer, not a Docker Engine implementation. It does not provide the Docker Engine API, `docker.sock`, or compatibility with clients that require that API. Supported commands and limitations are documented in [README.ja.md](README.ja.md).

## Install the Debian package

Download the `.deb` from [the latest GitHub Release](https://github.com/hidekatsu-izuno/wslc-docker/releases/latest), then install it in Ubuntu on WSL:

```bash
sudo apt install ./wslc-docker_*.deb
docker run --rm hello-world
docker compose -f compose.yaml up -d
```

Installing the package registers `docker`, `docker-compose`, `docker-wslc`, `wslc-docker`, and `wslc-compose` in `/usr/bin`. No manual symlinks or PATH settings are needed. The implementation lives under `/usr/lib/wslc-docker/`; apt/dpkg owns and removes the command symlinks.

Packages that also provide these Docker commands (`docker.io`, `docker-cli`, `docker-ce-cli`, `podman-docker`, `moby-cli`, and `docker-compose`) are declared as conflicts. When installing, apt will propose removing installed conflicting packages and any packages that depend on them. Review its package removal list before accepting.

The Windows `wslc.exe` backend must already be available. The adapter and bundled Compose automatically search PATH and `/mnt/c/Program Files/WSL/wslc.exe`. Only custom installations need `WSLC_DOCKER_BIN` and `WSLC_COMPOSE_BIN` overrides. `wslc-compose` is bundled from [bacarndiaye/wslc-compose](https://github.com/bacarndiaye/wslc-compose) at the pinned revision in [UPSTREAM.md](UPSTREAM.md), with its MIT license included.

If you created aliases or user-local Docker wrappers during an earlier installation, those can take precedence over `/usr/bin/docker`. Remove the earlier aliases/wrappers once when switching to the Debian package.

To uninstall:

```bash
sudo apt remove wslc-docker
```

## Build and test locally

On Ubuntu or another Debian-based Linux with `dpkg-dev`, Python 3, PyYAML, and pytest:

```bash
sudo apt install dpkg-dev python3-yaml python3-pytest
scripts/test.sh
scripts/build-deb.sh 0.2.0
```

Local builds write the package and SHA-256 checksum to `dist/`. GitHub Actions runs the adapter, Compose and isolated package installation tests, then publishes the `.deb` and checksum to GitHub Releases on successful main-branch or `v*` tag builds. Pull requests run the tests without publishing a Release.

## License

The adapter is MIT licensed. See [LICENSE](LICENSE) and [debian/copyright](debian/copyright) for attribution and bundled dependency details.
