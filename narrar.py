#!/usr/bin/env python3
"""Videos verticales narrados por una voz digital (estilo comentarista) sobre clips del video original.

Uso (necesita edge-tts: ~/.venv-tts):
  ~/.venv-tts/bin/python narrar.py planes/-C8_AtxEEQc.narrado.json            # todos
  ~/.venv-tts/bin/python narrar.py planes/-C8_AtxEEQc.narrado.json --video 2  # solo uno
Resultado: reels/<ID>/narrado_<n>.mp4

Plan (JSON): {"video": ID, "credito": "...", "voz": "es-MX-JorgeNeural", "velocidad": "+12%", "tono": "-6Hz",
  "videos": [{"titulo": "...", "tomas": [
    {"src": s, "narracion": "texto", "despues": s},   # clip desde src mientras dura la narración (+ despues s con el audio original arriba)
    {"src": s, "fin": s, "original": "traducción"}    # el audio original a todo volumen, con subtítulo
  ]}]}
"""
import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import edge_tts

from reels import ALTO, ANCHO, ASS_CABECERA, BASE, FADE, VIDEOS, correr, evento

FONDO = 0.14       # volumen del audio original bajo la narración
ARRIBA = 0.9       # volumen del audio original cuando no habla el comentarista
PAUSA = 0.35       # silencio tras cada frase narrada
RETRASO = 0.15     # la voz entra un poco después del corte

ESTILOS = ("Style: Narra,Montserrat,76,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,6,0,8,70,70,1330\n"
           "Style: Chico,Poppins,52,&H0040D8FF,&H0040D8FF,&H00000000,&H00000000,-1,-1,0,0,100,100,0,0,1,4,0,8,80,80,1330\n")


def duracion(ruta):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(ruta)],
                       capture_output=True, text=True)
    return float(r.stdout)


def hablar(texto, plan, destino):
    """Genera la voz y devuelve [(inicio, palabra_con_puntuación)] alineado al texto original."""
    com = edge_tts.Communicate(texto, plan["voz"], rate=plan["velocidad"], pitch=plan["tono"], boundary="WordBoundary")
    marcas = []
    with open(destino, "wb") as f:
        for ch in com.stream_sync():
            if ch["type"] == "audio":
                f.write(ch["data"])
            elif ch["type"] == "WordBoundary":
                marcas.append((ch["offset"] / 1e7, ch["text"]))
    norm = lambda s: re.sub(r"[^\w]", "", s.lower())
    palabras, j = [], 0
    for tok in texto.split():
        k = next((i for i in range(j, min(j + 4, len(marcas))) if norm(marcas[i][1]) == norm(tok)), None)
        if k is not None:
            palabras.append((marcas[k][0], tok)); j = k + 1
        else:  # sin marca (número, signo raro): se pega a la palabra anterior
            palabras.append((palabras[-1][0] if palabras else 0.0, tok))
    return palabras


def trozos(palabras, fin_audio, max_palabras=4):
    """Agrupa palabras en subtítulos cortos; corta también en puntuación fuerte."""
    grupos, actual = [], []
    for p in palabras:
        actual.append(p)
        if len(actual) >= max_palabras or re.search(r"[.!?…:,;]$", p[1]):
            grupos.append(actual); actual = []
    if actual:
        grupos.append(actual)
    salida = []
    for i, g in enumerate(grupos):
        fin = grupos[i + 1][0][0] if i + 1 < len(grupos) else fin_audio
        salida.append((g[0][0], fin, " ".join(w for _, w in g)))
    return salida


def armar(plan, n, video, destino):
    origen = VIDEOS / f"{plan['video']}.mp4"
    eventos, t0 = [], 0.0
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        partes = []
        for i, toma in enumerate(video["tomas"]):
            parte = tmp / f"p{i:02d}.mp4"
            vf = "scale=1280:720,fps=30,setsar=1"
            if "original" in toma:
                d = toma["fin"] - toma["src"]
                correr(["ffmpeg", "-nostdin", "-y", "-ss", str(toma["src"]), "-i", str(origen), "-t", f"{d:.3f}", "-vf", vf,
                        "-af", f"aresample=48000,volume={ARRIBA},afade=t=in:d={FADE},afade=t=out:st={d - FADE:.3f}:d={FADE}",
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-c:a", "aac", "-b:a", "192k", str(parte)])
                eventos.append(evento(t0, t0 + d, "Chico", f"«{toma['original']}»"))
            else:
                voz = tmp / f"v{i:02d}.mp3"
                palabras = hablar(toma["narracion"], plan, voz)
                dv = duracion(voz)
                habla = RETRASO + dv + PAUSA
                d = habla + toma.get("despues", 0)
                correr(["ffmpeg", "-nostdin", "-y", "-ss", str(toma["src"]), "-i", str(origen), "-i", str(voz),
                        "-t", f"{d:.3f}", "-filter_complex",
                        f"[0:v]{vf}[v];"
                        f"[0:a]aresample=48000,volume='if(lt(t,{habla - 0.2:.2f}),{FONDO},{ARRIBA})':eval=frame[o];"
                        f"[1:a]aresample=48000,volume=1.4,adelay={int(RETRASO * 1000)}:all=1,apad[n];"
                        f"[o][n]amix=inputs=2:duration=first:normalize=0,"
                        f"afade=t=in:d={FADE},afade=t=out:st={d - FADE:.3f}:d={FADE}[a]",
                        "-map", "[v]", "-map", "[a]", "-t", f"{d:.3f}",
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-c:a", "aac", "-b:a", "192k", str(parte)])
                for a, b, texto in trozos(palabras, dv):
                    eventos.append(evento(t0 + RETRASO + a, t0 + RETRASO + b, "Narra", texto.upper()))
            partes.append(parte)
            t0 += d
        if t0 >= 60:
            sys.exit(f"ERROR video {n}: dura {t0:.1f} s (debe ser < 60); acorta la narración")
        cab = ASS_CABECERA.replace("\n[Events]", ESTILOS + "\n[Events]")
        ass = cab + "\n".join([evento(0, t0, "Titulo", video["titulo"].replace("\n", "\\N")),
                               evento(0, t0, "Credito", plan["credito"]), *eventos]) + "\n"
        (tmp / "v.ass").write_text(ass, encoding="utf-8")
        (tmp / "lista.txt").write_text("".join(f"file '{p}'\n" for p in partes))
        filtro = (f"[0:v]split[a][b];"
                  f"[a]scale={ANCHO}:{ALTO}:force_original_aspect_ratio=increase,crop={ANCHO}:{ALTO},"
                  f"gblur=sigma=40,eq=brightness=-0.18[fondo];"
                  f"[b]scale={ANCHO}:-2[frente];"
                  f"[fondo][frente]overlay=0:(H-h)/2,ass={tmp / 'v.ass'}[v]")
        correr(["ffmpeg", "-nostdin", "-y", "-f", "concat", "-safe", "0", "-i", str(tmp / "lista.txt"),
                "-filter_complex", filtro, "-map", "[v]", "-map", "0:a", "-af", "loudnorm=I=-14:TP=-1.5:LRA=11",
                "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", str(destino)])
    print(f"OK narrado {n}: {t0:.1f} s -> {destino}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("plan")
    ap.add_argument("--video", type=int)
    args = ap.parse_args()
    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    salida = BASE / "reels" / plan["video"]
    salida.mkdir(parents=True, exist_ok=True)
    for n, video in enumerate(plan["videos"], 1):
        if args.video in (None, n):
            armar(plan, n, video, salida / f"narrado_{n}.mp4")


if __name__ == "__main__":
    main()
