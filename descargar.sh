#!/usr/bin/env bash
# Descarga los videos a ./videos (720p mp4) + metadata .info.json + subtítulos auto
cd "$(dirname "$0")"
IDS=(FY1Xa1kbLwk J_yPGvaamoc 8R7lcO-6Zns yrMpb_vemXA mqy3H4izN0g UytYrhYLOKI)
for id in "${IDS[@]}"; do
  yt-dlp "https://www.youtube.com/watch?v=$id" \
    -f "bv*[height<=720][ext=mp4]+ba[ext=m4a]/b[height<=720][ext=mp4]/b[height<=720]" \
    --merge-output-format mp4 \
    --write-info-json --write-auto-subs --sub-langs "es-orig,es,en-orig,en" --ignore-errors --sleep-subtitles 3 --sleep-requests 1 --sub-format vtt \
    --no-playlist -o "videos/%(id)s.%(ext)s" --no-overwrites --continue
done
