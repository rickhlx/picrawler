#!/usr/bin/env bash
# Push the working tree to the Pi for hardware iteration. Not a deploy:
# commit and `git pull` on the Pi once the change is settled.
#
# Usage: scripts/sync-pi.sh [-n] [-r]
#   -n  dry run, show what would change
#   -r  restart the petronilo service after syncing
# Env:  PI_HOST (default: picrawler, from ~/.ssh/config)
#       PI_DIR  (default: picrawler, relative to the remote home)
#
# Needs the Pi to use an editable install, or library changes are ignored:
#   sudo pip3 install -e ~/picrawler --break-system-packages --no-deps
set -euo pipefail

host=${PI_HOST:-picrawler}
dir=${PI_DIR:-picrawler}
dry=()
restart=0

while getopts nr opt; do
  case $opt in
    n) dry=(--dry-run) ;;
    r) restart=1 ;;
    *) sed -n '5,9p' "$0"; exit 2 ;;
  esac
done

cd "$(git rev-parse --show-toplevel)"

# Excluded paths are Pi-local state; --delete never touches them.
rsync -az --delete --itemize-changes ${dry[@]+"${dry[@]}"} \
  --exclude .git \
  --exclude .claude/ \
  --exclude .vscode/ \
  --exclude __pycache__/ \
  --exclude '*.egg-info/' \
  --exclude build/ \
  --exclude 'secret*' \
  --exclude examples/petronilo_memory.json \
  --exclude examples/img_input.jpeg \
  --exclude examples/musics/reggaeton_dembow.wav \
  --exclude '.lgd-nfy*' \
  --exclude .DS_Store \
  ./ "$host:$dir/"

if (( restart )) && (( ${#dry[@]} == 0 )); then
  ssh "$host" sudo systemctl restart petronilo
  echo "restarted petronilo"
fi
