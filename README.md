# wslc-docker

Docker-style command wrappers and Compose support for Microsoft's WSL container CLI (`wslc`). This project includes a Debian package and a GitHub Actions workflow that tests the adapters and builds a `.deb` on pushes, tags, and pull requests.

This is a command-line compatibility layer, not a Docker Engine implementation. It does not provide the Docker Engine API, `docker.sock`, or compatibility with clients that require that API. Supported commands and limitations are documented in [README.ja.md](README.ja.md).

## Install the Debian package

Download the `.deb` from the latest successful workflow run's **Artifacts** section, then install it in Ubuntu on WSL:

```bash
sudo apt install ./wslc-docker_0.1.*_all.deb
wslc-compose --version
```

The package installs `wslc-docker` and `wslc-compose` in `/usr/bin`. It keeps `docker` and `docker-compose` under `/usr/lib/wslc-docker/bin` so it does not replace an existing Docker installation. To opt in to these commands for your user:

```bash
mkdir -p "$HOME/.local/bin"
ln -s /usr/lib/wslc-docker/bin/docker "$HOME/.local/bin/docker"
ln -s /usr/lib/wslc-docker/bin/docker-compose "$HOME/.local/bin/docker-compose"
export PATH="$HOME/.local/bin:$PATH"
docker-wslc doctor
docker compose version
```

Set `WSLC_COMPOSE_BIN` to the Windows `wslc.exe` path if it is not detected automatically. `wslc-compose` is bundled from [bacarndiaye/wslc-compose](https://github.com/bacarndiaye/wslc-compose) at the pinned revision in [UPSTREAM.md](UPSTREAM.md), and its MIT license is included in the package.

## Build and test locally

On Ubuntu or another Debian-based Linux with `dpkg-dev`, Python 3, PyYAML, and pytest:

```bash
sudo apt install dpkg-dev python3-yaml python3-pytest
scripts/test.sh
scripts/build-deb.sh 0.1.0
```

The package and SHA-256 checksum are written to `dist/`. GitHub Actions runs the same tests and package checks, then publishes the `.deb` and checksum as a workflow artifact.

## License

The adapter is MIT licensed. See [LICENSE](LICENSE) and [debian/copyright](debian/copyright) for attribution and bundled dependency details.
