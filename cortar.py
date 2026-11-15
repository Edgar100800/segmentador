#!/usr/bin/env python3
"""Corta los segmentos de segmentos.json en clips/.

Uso:
  python3 cortar.py            # rápido, sin recodificar (corta en keyframes)
  python3 cortar.py --exacto   # recodifica, corte exacto al frame (más lento)
  python3 cortar.py --id FY1Xa1kbLwk   # solo un video
"""
import argparse
import json
import re
import subprocess
from pathlib import Path

BASE = Path(__file__).resolve().parent
CLIPS = BASE / "clips"


def slug(texto):
    texto = re.sub(r"[^\w\s-]", "", texto or "sin_tema", flags=re.UNICODE).strip().lower()
    return re.sub(r"[\s-]+", "_", texto)[:60] or "sin_tema"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--exacto", action="store_true")
    ap.add_argument("--id")
    args = ap.parse_args()

    datos = json.loads((BASE / "segmentos.json").read_text(encoding="utf-8"))
    CLIPS.mkdir(exist_ok=True)
    total = 0
    for vid, item in datos.items():
        if args.id and vid != args.id:
            continue
        origen = BASE / item["archivo"]
        segs = sorted(item.get("segmentos", []), key=lambda s: s["inicio"])
        for n, s in enumerate(segs, 1):
            if s.get("fin") is None or s["fin"] <= s["inicio"]:
                print(f"  [salto] {vid} #{n}: segmento sin fin válido")
                continue
            salida = CLIPS / f"{vid}_{n:02d}_{slug(s.get('tema'))}.mp4"
            codec = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac"] if args.exacto else ["-c", "copy"]
            cmd = ["ffmpeg", "-y", "-loglevel", "error", "-ss", str(s["inicio"]), "-to", str(s["fin"]),
                   "-i", str(origen), *codec, "-avoid_negative_ts", "make_zero", str(salida)]
            subprocess.run(cmd, check=True)
            print(f"  ✓ {salida.name}")
            total += 1
    print(f"{total} clips generados en {CLIPS}")


if __name__ == "__main__":
    main()
