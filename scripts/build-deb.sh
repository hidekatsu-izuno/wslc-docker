#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
version="${1:-0.2.0}"
if [[ ! "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+([+~.-][A-Za-z0-9.+~:-]+)?$ ]]; then
    echo "Invalid Debian package version: $version" >&2
    exit 2
fi
command -v dpkg-deb >/dev/null || { echo "dpkg-deb is required (install dpkg-dev)." >&2; exit 127; }
command -v python3 >/dev/null || { echo "python3 is required." >&2; exit 127; }

stage="$repo_root/.build/wslc-docker_${version}_all"
rm -rf -- "$stage"
install -d "$stage/DEBIAN" "$stage/usr/lib/wslc-docker/bin" \
    "$stage/usr/lib/wslc-docker/lib" "$stage/usr/lib/wslc-docker/vendor/wslc-compose/src" \
    "$stage/usr/bin" "$stage/usr/share/doc/wslc-docker/vendor"

install -m 755 "$repo_root/bin/docker" "$stage/usr/lib/wslc-docker/bin/docker"
install -m 755 "$repo_root/bin/docker-compose" "$stage/usr/lib/wslc-docker/bin/docker-compose"
install -m 755 "$repo_root/bin/docker-wslc" "$stage/usr/lib/wslc-docker/bin/docker-wslc"
install -m 755 "$repo_root/bin/wslc-compose" "$stage/usr/lib/wslc-docker/bin/wslc-compose"
cp -a "$repo_root/lib/." "$stage/usr/lib/wslc-docker/lib/"
cp -a "$repo_root/vendor/wslc-compose/src/wslc_compose" \
    "$stage/usr/lib/wslc-docker/vendor/wslc-compose/src/"
find "$stage/usr/lib/wslc-docker" -type d -name __pycache__ -prune -exec rm -rf -- {} +
find "$stage/usr/lib/wslc-docker" -type f -name '*.py[co]' -delete
install -m 644 "$repo_root/vendor/wslc-compose/LICENSE" \
    "$stage/usr/share/doc/wslc-docker/vendor/wslc-compose.LICENSE"
install -m 644 "$repo_root/README.md" "$stage/usr/share/doc/wslc-docker/README.md"
install -m 644 "$repo_root/README.ja.md" "$stage/usr/share/doc/wslc-docker/README.ja.md"
install -m 644 "$repo_root/UPSTREAM.md" "$stage/usr/share/doc/wslc-docker/UPSTREAM.md"
install -m 644 "$repo_root/debian/copyright" "$stage/usr/share/doc/wslc-docker/copyright"
ln -s ../lib/wslc-docker/bin/docker "$stage/usr/bin/docker"
ln -s ../lib/wslc-docker/bin/docker-compose "$stage/usr/bin/docker-compose"
ln -s ../lib/wslc-docker/bin/docker-wslc "$stage/usr/bin/docker-wslc"
ln -s ../lib/wslc-docker/bin/docker-wslc "$stage/usr/bin/wslc-docker"
ln -s ../lib/wslc-docker/bin/wslc-compose "$stage/usr/bin/wslc-compose"

cat > "$stage/DEBIAN/control" <<CONTROL
Package: wslc-docker
Version: $version
Section: utils
Priority: optional
Architecture: all
Maintainer: Hidekatsu Iizuno <1091860+hidekatsu-izuno@users.noreply.github.com>
Depends: python3 (>= 3.9), python3-yaml
Conflicts: docker.io, docker-cli, docker-ce-cli, podman-docker, moby-cli, docker-compose
Description: Docker CLI adapter and Compose support for WSL containers
 Docker-style CLI wrappers route common docker commands to Microsoft's wslc
 container CLI. Includes the wslc-compose service orchestrator.
CONTROL

mkdir -p "$repo_root/dist"
package="$repo_root/dist/wslc-docker_${version}_all.deb"
dpkg-deb --root-owner-group --build "$stage" "$package"
(cd "$repo_root/dist" && sha256sum "wslc-docker_${version}_all.deb") \
    > "$package.sha256"
printf 'Built %s\n' "$repo_root/dist/wslc-docker_${version}_all.deb"
