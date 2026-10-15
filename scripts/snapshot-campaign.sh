#!/bin/bash
# snapshot-campaign.sh PREFIX SRC_DATA_ROOT [DEST] : read-only copy of one Mu2eBO campaign's records for the reporter.
# Needed because Mu2eBO's readers take flocks that need write access, so another user's data root cannot be read live.
set -euo pipefail
prefix=${1:?usage: snapshot-campaign.sh PREFIX SRC_DATA_ROOT [DEST]}
src=${2:?usage: snapshot-campaign.sh PREFIX SRC_DATA_ROOT [DEST]}
dst=${3:-/exp/mu2e/data/users/$USER/mu2ebo_snapshots/$prefix}
[[ $prefix =~ ^[A-Za-z0-9_]+$ ]] || { echo "bad prefix" >&2; exit 2; }
mkdir -p "$dst"/{autoresearch_leaderboards,autoresearch_graph_data/closed_loop_logs,autoresearch_grid}
mkdir -p "$dst/autoresearch_leaderboards/locks"
rsync -a --exclude locks "$src/autoresearch_leaderboards/" "$dst/autoresearch_leaderboards/"
rsync -a --exclude '*.lock' --exclude lock "$src/autoresearch_graph_data/$prefix/" "$dst/autoresearch_graph_data/$prefix/"
rsync -a --include "${prefix}R*.log" --exclude '*' "$src/autoresearch_graph_data/closed_loop_logs/" "$dst/autoresearch_graph_data/closed_loop_logs/"
for d in "$src"/autoresearch_grid/"${prefix}"R*/; do
  c=$(basename "$d"); [[ -d $d/state ]] || continue
  mkdir -p "$dst/autoresearch_grid/$c"
  rsync -a --exclude '*.lock' "$d/state/" "$dst/autoresearch_grid/$c/state/"
done
date -u +%Y-%m-%dT%H:%M:%SZ > "$dst/SNAPSHOT_TIME"
echo "$src" > "$dst/SNAPSHOT_SOURCE"
du -sh "$dst"
