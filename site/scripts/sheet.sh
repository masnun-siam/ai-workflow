#!/bin/sh
# Contact sheet (one frame every 2 s, 3x2) for reviewing a clip: sheet.sh IN.mp4 OUT.png
ffmpeg -loglevel error -y -i "$1" -vf "fps=1/2,scale=640:-1,tile=3x2" -frames:v 1 "$2"
ffprobe -v error -show_entries format=duration -of csv=p=0 "$1"
