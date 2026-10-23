#!/bin/sh
# Screenshot a page every N seconds into OUT/NNNNN.png until killed; stitch with ffmpeg later.
# usage: timelapse.sh URL OUT [interval_seconds]
url=$1; out=$2; every=${3:-5}
s="tl-$(basename "$out")"
mkdir -p "$out"
agent-browser --session "$s" set viewport 1600 1000 >/dev/null
agent-browser --session "$s" open "$url" >/dev/null
i=$(find "$out" -name '*.png' | wc -l | tr -d ' ')
while :; do
  agent-browser --session "$s" screenshot "$out/$(printf %05d "$i").png" >/dev/null 2>&1
  i=$((i + 1))
  sleep "$every"
done
