#!/usr/bin/env bash
# Run from the consuming project. Pass the entire command, including nix develop
# if shell realization/download time should be included. No cache is deleted.
set -u
if [ "$#" -eq 0 ]; then
    echo "Usage: $0 nix develop .#v21 --command cargo build --timings -vv [build options]" >&2
    exit 2
fi

NVVM_TIMING_DIR=${NVVM_TIMING_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/rust-cuda-traces/$(date -u +%Y%m%dT%H%M%SZ)-$$}
mkdir -p "$NVVM_TIMING_DIR" || exit 1
NVVM_TIMING_DIR=$(cd "$NVVM_TIMING_DIR" && pwd -P) || exit 1
export NVVM_TIMING_DIR
build_log="$NVVM_TIMING_DIR/build.log"
printf 'Build trace: %s\n' "$build_log"
{
    printf 'start_utc=%s cwd=%q command=' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$PWD"
    printf '%q ' "$@"
    printf '\n'
} >> "$build_log"
SECONDS=0
if "$@" >> "$build_log" 2>&1; then
    build_status=0
else
    build_status=$?
fi
printf 'end_utc=%s elapsed_seconds=%s exit_status=%s\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$SECONDS" "$build_status" >> "$build_log"
printf 'Build exit status: %s; trace: %s\n' "$build_status" "$build_log"
exit "$build_status"
