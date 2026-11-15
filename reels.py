#!/usr/bin/env python3
"""Arma reels verticales (1080x1920, < 60 s) a partir de tramos de un video, con título y subtítulos en español.

Uso:
  python3 reels.py planes/-C8_AtxEEQc.json            # todos los reels del plan
  python3 reels.py planes/-C8_AtxEEQc.json --reel 2   # solo uno
Resultado: reels/<ID>/reel_<n>.mp4

Plan (JSON): {"video": ID, "credito": "...", "reels": [{"titulo": "...", "clips": [
  {"inicio": s, "fin": s, "subs": [[ini, fin, "texto"], ...], "notas": [[ini, fin, "texto"], ...]}]}]}
Los tiempos de subs/notas son los del video original (los de la transcripción); el script los traslada al reel.
"""
import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

BASE = Path(__file__).resolve().parent
VIDEOS = BASE / "videos"

ANCHO, ALTO = 1080, 1920
FADE = 0.06  # s de fundido de audio en cada corte (evita clics)

ASS_CABECERA = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {ANCHO}
PlayResY: {ALTO}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Titulo,Montserrat,74,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,5,0,2,70,70,1310
Style: Sub,Poppins,54,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,4,0,8,80,80,1310
Style: Nota,Poppins,50,&H0040D8FF,&H0040D8FF,&H00000000,&H64000000,-1,-1,0,0,100,100,0,0,1,4,0,8,80,80,1310
Style: Credito,Poppins,30,&H00C8C8C8,&H00C8C8C8,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,0,2,60,60,120

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def t_ass(s):
    s = max(0.0, s)
    return f"{int(s // 3600)}:{int(s % 3600 // 60):02d}:{s % 60:05.2f}"


def evento(ini, fin, estilo, texto):
    return f"Dialogue: 0,{t_ass(ini)},{t_ass(fin)},{estilo},,0,0,0,,{texto}"


def construir_ass(reel, credito):
    """Título fijo arriba del video, subtítulos/notas debajo, crédito al pie."""
    total = sum(c["fin"] - c["inicio"] for c in reel["clips"])
    lineas = [evento(0, total, "Titulo", reel["titulo"].replace("\n", "\\N")),
              evento(0, total, "Credito", credito)]
    t0 = 0.0
    for c in reel["clips"]:
        for estilo, items in (("Sub", c.get("subs", [])), ("Nota", c.get("notas", []))):
            for ini, fin, texto in items:
                a, b = max(ini, c["inicio"]), min(fin, c["fin"])  # recorta al clip
                if b > a:
                    lineas.append(evento(t0 + a - c["inicio"], t0 + b - c["inicio"], estilo, texto))
        t0 += c["fin"] - c["inicio"]
    return ASS_CABECERA + "\n".join(lineas) + "\n", total


def correr(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        sys.exit(f"ERROR ffmpeg: {r.stderr[-800:]}")


def armar(plan, n, reel, destino):
    origen = VIDEOS / f"{plan['video']}.mp4"
    ass, total = construir_ass(reel, plan["credito"])
    if total >= 60:
        sys.exit(f"ERROR reel {n}: dura {total:.1f} s (debe ser < 60)")
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        partes = []
        for i, c in enumerate(reel["clips"]):
            d = c["fin"] - c["inicio"]
            parte = tmp / f"p{i:02d}.mp4"
            correr(["ffmpeg", "-nostdin", "-y", "-ss", str(c["inicio"]), "-i", str(origen), "-t", f"{d:.3f}",
                    "-vf", "scale=1280:720,fps=30,setsar=1",
                    "-af", f"aresample=48000,afade=t=in:d={FADE},afade=t=out:st={d - FADE:.3f}:d={FADE}",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-c:a", "aac", "-b:a", "192k", str(parte)])
            partes.append(parte)
        lista = tmp / "lista.txt"
        lista.write_text("".join(f"file '{p}'\n" for p in partes))
        (tmp / "reel.ass").write_text(ass, encoding="utf-8")
        filtro = (f"[0:v]split[a][b];"
                  f"[a]scale={ANCHO}:{ALTO}:force_original_aspect_ratio=increase,crop={ANCHO}:{ALTO},"
                  f"gblur=sigma=40,eq=brightness=-0.18[fondo];"
                  f"[b]scale={ANCHO}:-2[frente];"
                  f"[fondo][frente]overlay=0:(H-h)/2,ass={tmp / 'reel.ass'}[v]")
        correr(["ffmpeg", "-nostdin", "-y", "-f", "concat", "-safe", "0", "-i", str(lista),
                "-filter_complex", filtro, "-map", "[v]", "-map", "0:a",
                "-af", "loudnorm=I=-14:TP=-1.5:LRA=11",
                "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", str(destino)])
    print(f"OK reel {n}: {total:.1f} s -> {destino.relative_to(BASE)}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("plan")
    ap.add_argument("--reel", type=int)
    args = ap.parse_args()
    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    salida = BASE / "reels" / plan["video"]
    salida.mkdir(parents=True, exist_ok=True)
    for n, reel in enumerate(plan["reels"], 1):
        if args.reel in (None, n):
            armar(plan, n, reel, salida / f"reel_{n}.mp4")


if __name__ == "__main__":
    main()
