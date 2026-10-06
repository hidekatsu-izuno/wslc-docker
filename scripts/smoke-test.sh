#!/usr/bin/env bash
# Explicitly run on the user's WSL machine: creates and cleans up its own resources.
set -euo pipefail
package_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
docker_cmd=(python3 "$package_dir/bin/docker")
python3 "$package_dir/bin/docker-wslc" doctor
smoke_dir="$(mktemp -d -t wslc-docker-smoke-XXXXXXXX)"
smoke_token="${smoke_dir##*-}"
smoke_image="wslc-docker-smoke:${smoke_token,,}"
smoke_container="wslc-docker-smoke-${smoke_token,,}"
smoke_volume="wslc-docker-smoke-${smoke_token,,}"
cleanup() {
    local original_status=$?
    trap - EXIT
    "${docker_cmd[@]} rm -f "$smoke_container" >/dev/null 2>&1 || true
    "${docker_cmd[@]} volume rm "$smoke_volume" >/dev/null 2>&1 || true
    "${docker_cmd[@]} rmi "$smoke_image" >/dev/null 2>&1 || true
    rm -rf -- "$smoke_dir"
    exit "$original_status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
cat > "$smoke_dir/Dockerfile" <<'DOCKERFILE'
FROM alpine:3.22
RUN printf 'build-ok\n' > /built.txt
CMD ["cat", "/built.txt"]
DOCKERFILE
printf 'bind-ok\n' > "$smoke_dir/marker.txt"
printf 'TOKEN=env-file-ok\n' > "$smoke_dir/vars.env"
"${docker_cmd[@]} build -t "$smoke_image" "$smoke_dir"
"${docker_cmd[@]} run --rm "$smoke_image" sh -c 'test "$(cat /built.txt)" = build-ok'
"${docker_cmd[@]} run --rm -v "$smoke_dir:/probe:ro" "$smoke_image" \
    sh -c 'test "$(cat /probe/marker.txt)" = bind-ok && ! touch /probe/readonly-test'
"${docker_cmd[@]} run --rm --env-file "$smoke_dir/vars.env" "$smoke_image" \
    sh -c 'test "$TOKEN" = env-file-ok'
"${docker_cmd[@]} volume create "$smoke_volume"
"${docker_cmd[@]} run --rm -v "$smoke_volume:/data" "$smoke_image" \
    sh -c 'printf volume-ok > /data/marker'
"${docker_cmd[@]} run --rm -v "$smoke_volume:/data" "$smoke_image" \
    sh -c 'test "$(cat /data/marker)" = volume-ok'
"${docker_cmd[@]} run -d --name "$smoke_container" "$smoke_image" sleep 120
"${docker_cmd[@]} exec "$smoke_container" test -f /built.txt
"${docker_cmd[@]} cp "$smoke_container:/built.txt" "$smoke_dir/copied.txt"
test "$(tr -d '\r\n' < "$smoke_dir/copied.txt")" = build-ok
"${docker_cmd[@]} stop "$smoke_container"
"${docker_cmd[@]} save -o "$smoke_dir/image.tar" "$smoke_image"
"${docker_cmd[@]} load < "$smoke_dir/image.tar"
printf 'All WSL smoke checks passed. Interactive TTY: docker run --rm -it alpine:3.22 sh\n'
