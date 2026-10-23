#!/bin/sh
# Turn raw captures (site/raw, not committed) into the compressed media the page loads (site/public/media).
# usage: site/scripts/make-media.sh   (run from the repo root)
set -e
raw=site/raw; out=site/public/media
mkdir -p "$out"

img() { cwebp -quiet -q 82 -resize 1600 0 "$raw/$1" -o "$out/$2.webp"; }
img new-feature-filled.png new-feature
img prd-questions.png prd-questions
img peer-review-rounds.png peer-review
img feature-issues.png board
img refined-issue.png refined-issue
img pr-files.png pr

# vid IN OUT: muted H.264 loop, 1280 wide, small enough to commit; poster from the first frame.
vid() {
  ffmpeg -loglevel error -y -i "$1" -an -vf "scale=1280:-2:flags=lanczos,format=yuv420p" \
    -c:v libx264 -preset slow -crf 30 -movflags +faststart "$out/$2.mp4"
  ffmpeg -loglevel error -y -ss 1.5 -i "$out/$2.mp4" -frames:v 1 -f image2pipe -vcodec png - | cwebp -quiet -q 80 -o "$out/$2.webp" -- -
}

# lapse DIR OUT FPS: stitch timelapse frames into a sped-up clip.
lapse() {
  ffmpeg -loglevel error -y -framerate "$3" -pattern_type glob -i "$raw/$1/*.png" -an \
    -vf "scale=1280:-2:flags=lanczos,format=yuv420p" -c:v libx264 -preset slow -crf 30 -movflags +faststart "$out/$2.mp4"
  ffmpeg -loglevel error -y -ss 1.5 -i "$out/$2.mp4" -frames:v 1 -f image2pipe -vcodec png - | cwebp -quiet -q 80 -o "$out/$2.webp" -- -
}

for f in "$raw"/clips/*.mp4; do [ -f "$f" ] && vid "$f" "$(basename "$f" .mp4)"; done
[ -d "$raw/tl-impl" ] && lapse tl-impl implement 12
[ -f "$raw/run.mp4" ] && vid "$raw/run.mp4" run
# hero: a 1.4x highlights reel of the board, a live session and a dispatch preview
c=$raw/clips
ffmpeg -loglevel error -y -ss 1 -t 11 -i "$c/tour-board.mp4" -ss 0.5 -t 7 -i "$c/tour-session.mp4" -ss 1 -t 13 -i "$c/tour-dispatch.mp4" \
  -filter_complex "[0][1][2]concat=n=3:v=1,setpts=PTS/1.4" -an "$raw/hero.mp4"
vid "$raw/hero.mp4" hero
ls -la "$out"
