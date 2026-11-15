#!/usr/bin/env python3
"""Transcribe los videos localmente con faster-whisper -> videos/<ID>.whisper.json

Uso (con el entorno que tiene faster-whisper):
  ~/.venv-videoia/bin/python transcribir.py            # todos los que falten
  ~/.venv-videoia/bin/python transcribir.py ID1 ID2    # solo esos
  opciones: --modelo large-v3-turbo|medium|small  --forzar  --idioma es|en
"""
import argparse
import json
import os
import site
import subprocess
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
VIDEOS = BASE / "videos"


def activar_cuda():
    """Si el venv trae cuBLAS/cuDNN (paquetes nvidia-*), los pone en LD_LIBRARY_PATH.

    Igual que en SO/Clases Grabadas/Herramientas/transcribir_clases.py, pero relanzando el
    proceso: el cargador de librerías solo lee LD_LIBRARY_PATH al arrancar.
    """
    sp = Path(site.getsitepackages()[0])
    libs = [str(p) for p in (sp / "nvidia/cublas/lib", sp / "nvidia/cudnn/lib") if p.is_dir()]
    actual = os.environ.get("LD_LIBRARY_PATH", "")
    if libs and not all(l in actual.split(":") for l in libs):
        os.environ["LD_LIBRARY_PATH"] = ":".join(libs + ([actual] if actual else []))
        os.execv(sys.executable, [sys.executable, *sys.argv])


def leer_audio(ruta):
    """Audio mono 16 kHz con ffmpeg (evita el decodificador PyAV de faster-whisper)."""
    import numpy as np
    r = subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-i", str(ruta), "-f", "s16le",
                        "-ac", "1", "-ar", "16000", "-"], capture_output=True)
    if r.returncode:
        sys.exit(f"ERROR: el audio de {ruta.name} está dañado (descarga incompleta): bórralo y vuelve a agregar el link")
    crudo = r.stdout
    return np.frombuffer(crudo, np.int16).astype(np.float32) / 32768.0


def cargar_modelo(nombre):
    import ctranslate2
    import numpy as np
    from faster_whisper import WhisperModel
    if ctranslate2.get_cuda_device_count() > 0:
        try:
            # int8_float16: como en el script de SO, entra holgado en los 6 GB de la RTX 2060
            model = WhisperModel(nombre, device="cuda", compute_type="int8_float16")
            list(model.transcribe(np.zeros(16000, np.float32))[0])  # cuBLAS/cuDNN se cargan recién aquí
            return model, "gpu"
        except Exception as e:  # GPU presente pero faltan librerías CUDA
            print(f"GPU detectada pero no se pudo usar ({e}); usando CPU", flush=True)
    return WhisperModel(nombre, device="cpu", compute_type="int8", cpu_threads=os.cpu_count()), "cpu"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="*")
    ap.add_argument("--modelo", default="large-v3-turbo")
    ap.add_argument("--idioma", default=None, help="por defecto lo detecta solo")
    ap.add_argument("--forzar", action="store_true")
    args = ap.parse_args()

    ids = args.ids or [p.stem for p in sorted(VIDEOS.glob("*.mp4")) if "." not in p.stem]
    pendientes = [i for i in ids if args.forzar or not (VIDEOS / f"{i}.whisper.json").exists()]
    if not pendientes:
        print("Nada que transcribir", flush=True)
        return
    model, dispositivo = cargar_modelo(args.modelo)
    print(f"DISPOSITIVO {dispositivo}", flush=True)

    for vid in pendientes:
        origen = VIDEOS / f"{vid}.mp4"
        print(f"Transcribiendo {vid} ({args.modelo}, {dispositivo})", flush=True)
        t0 = time.time()
        segmentos, info = model.transcribe(leer_audio(origen), language=args.idioma, vad_filter=True, beam_size=5)
        salida = []
        for s in segmentos:
            salida.append({"inicio": round(s.start, 2), "fin": round(s.end, 2), "texto": s.text.strip()})
            print(f"PROGRESO {min(100, s.end / info.duration * 100):.1f}", flush=True)
        destino = VIDEOS / f"{vid}.whisper.json"
        tmp = destino.with_suffix(".tmp")
        tmp.write_text(json.dumps({
            "video": vid, "modelo": args.modelo, "dispositivo": dispositivo, "idioma": info.language,
            "duracion": round(info.duration, 2), "segmentos": salida,
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(destino)
        print(f"OK {vid}: {len(salida)} frases en {time.time() - t0:.0f}s -> {destino.name}", flush=True)


if __name__ == "__main__":
    activar_cuda()
    main()
