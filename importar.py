#!/usr/bin/env python3
"""Agrega a la app un video local (mkv, mp4, …) que no viene de YouTube.

Uso:
  python3 importar.py ARCHIVO ID --titulo "Título"   [--idioma eng]
Resultado: videos/<ID>.mp4 (h264 720p hecho en la GPU, audio estéreo en el idioma pedido), videos/<ID>.info.json
           y videos/<ID>.en.vtt si el archivo trae subtítulos de texto en ese idioma.
Después se procesa igual que los de YouTube: transcribir.py ID y analizar.py --motor claude|codex ID
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
VIDEOS = BASE / "videos"
# Todo en la GPU: NVDEC decodifica, libplacebo (Vulkan) escala y pasa HDR10 -> SDR bt709, NVENC codifica.
# La RTX 2060 (Turing) no decodifica AV1 por hardware: ese códec lo decodifica la CPU (dav1d).
NVDEC = {"h264", "hevc", "vp9", "mpeg2video", "vc1"}
SDR = ":colorspace=bt709:color_primaries=bt709:color_trc=bt709:range=tv"


def pistas(ruta):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(ruta)],
                       capture_output=True, text=True, check=True)
    return json.loads(r.stdout)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("archivo")
    ap.add_argument("id")
    ap.add_argument("--titulo", required=True)
    ap.add_argument("--idioma", default="eng", help="idioma de la pista de audio/subtítulos (ISO 639-2)")
    args = ap.parse_args()
    origen = Path(args.archivo).expanduser().resolve()
    if "." in args.id or args.id.startswith("-"):
        sys.exit("ERROR: el ID no puede tener puntos ni empezar con '-'")

    info = pistas(origen)
    streams = info["streams"]
    video = next(s for s in streams if s["codec_type"] == "video" and s.get("disposition", {}).get("attached_pic") != 1)
    audios = [s for s in streams if s["codec_type"] == "audio"]
    audio = next((s for s in audios if s.get("tags", {}).get("language") == args.idioma), audios[0])
    subs = [s for s in streams if s["codec_type"] == "subtitle" and s["codec_name"] in ("subrip", "ass", "mov_text")
            and s.get("tags", {}).get("language") == args.idioma]
    subs.sort(key=lambda s: "SDH" in s.get("tags", {}).get("title", ""))  # primero los que no son SDH
    hdr = video.get("color_transfer") == "smpte2084"

    destino = VIDEOS / f"{args.id}.mp4"
    tmp = destino.with_suffix(".tmp.mp4")
    alto = round(1280 * video["height"] / video["width"] / 2) * 2
    vf = f"libplacebo=w=1280:h={alto}:format=yuv420p{SDR if hdr else ''}"
    hw = ["-hwaccel", "cuda"] if video["codec_name"] in NVDEC else []
    print(f"Convirtiendo {origen.name} (audio #{audio['index']}, {'HDR→SDR' if hdr else 'SDR'}, "
          f"decodifica {'GPU' if hw else 'CPU'})", flush=True)
    # El audio va en un paso aparte: junto con el video, el E-AC3 de Endgame se cortó a la mitad sin dar error
    solo_video, solo_audio = destino.with_suffix(".v.mp4"), destino.with_suffix(".a.m4a")
    subprocess.run(["ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-stats", *hw, "-i", str(origen),
                    "-map", f"0:{video['index']}", "-vf", vf,
                    "-c:v", "h264_nvenc", "-preset", "p5", "-cq", "23", "-b:v", "0", str(solo_video)], check=True)
    subprocess.run(["ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-i", str(origen), "-map", f"0:{audio['index']}",
                    "-c:a", "aac", "-b:a", "160k", "-ac", "2", str(solo_audio)], check=True)
    subprocess.run(["ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-i", str(solo_video), "-i", str(solo_audio),
                    "-map", "0:v", "-map", "1:a", "-c", "copy", "-movflags", "+faststart", str(tmp)], check=True)
    solo_video.unlink(); solo_audio.unlink()
    durs = {s["codec_type"]: float(s["duration"]) for s in pistas(tmp)["streams"]}
    if durs["audio"] < durs["video"] - 5:
        sys.exit(f"ERROR: el audio dura {durs['audio']:.0f}s y el video {durs['video']:.0f}s")
    tmp.replace(destino)

    if subs:
        vtt = VIDEOS / f"{args.id}.en.vtt"
        subprocess.run(["ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-i", str(origen),
                        "-map", f"0:{subs[0]['index']}", str(vtt)], check=True)
        print(f"Subtítulos -> {vtt.name}", flush=True)

    (VIDEOS / f"{args.id}.info.json").write_text(json.dumps({
        "id": args.id, "title": args.titulo, "duration": round(float(info["format"]["duration"]), 2),
        "webpage_url": origen.as_uri(), "origen_local": str(origen), "chapters": [],
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"OK {args.id} -> {destino.relative_to(BASE)}", flush=True)


if __name__ == "__main__":
    main()
