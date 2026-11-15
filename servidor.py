#!/usr/bin/env python3
"""Servidor local del segmentador. Uso: python3 servidor.py [puerto]"""
import json
import os
import re
import subprocess
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BASE = Path(__file__).resolve().parent
VIDEOS = BASE / "videos"
SEGMENTOS = BASE / "segmentos.json"

# Mismas opciones que descargar.sh
YTDLP = [
    "yt-dlp", "-f", "bv*[height<=720][ext=mp4]+ba[ext=m4a]/b[height<=720][ext=mp4]/b[height<=720]",
    "--merge-output-format", "mp4", "--write-info-json", "--write-auto-subs",
    "--sub-langs", "es-orig,es,en-orig,en", "--sub-format", "vtt", "--ignore-errors",
    "--sleep-subtitles", "3", "--no-playlist", "--no-overwrites", "--continue", "--newline",
    "-o", str(VIDEOS / "%(id)s.%(ext)s"),
]
def elegir_whisper_py():
    """Python con faster-whisper; prefiere un venv que traiga cuBLAS/cuDNN (GPU). Forzable con WHISPER_PY."""
    if os.environ.get("WHISPER_PY"):
        return os.environ["WHISPER_PY"]
    candidatos = [Path.home() / "Projects/ONG-SinLimites/.venv-whisper", Path.home() / ".venv-videoia"]
    validos = [v for v in candidatos if any(v.glob("lib/python3*/site-packages/faster_whisper"))]
    con_gpu = [v for v in validos if any(v.glob("lib/python3*/site-packages/nvidia/cublas/lib"))]
    elegido = (con_gpu or validos or [None])[0]
    return str(elegido / "bin/python") if elegido else "python3"


WHISPER_PY = elegir_whisper_py()
SUGERENCIAS = BASE / "sugerencias"
TRABAJOS = []  # [{id, tipo, url, estado: en_curso|listo|error, etapa, progreso, video, error}]
LOCK = threading.Lock()
GPU_LOCK = threading.Lock()  # transcripciones/análisis de a uno


def nuevo_trabajo(tipo, **extra):
    with LOCK:
        job = {"id": len(TRABAJOS) + 1, "tipo": tipo, "url": None, "estado": "en_curso",
               "etapa": "en cola", "progreso": 0, "video": None, "error": None, **extra}
        TRABAJOS.append(job)
    return job


def correr(job, cmd, etapa):
    """Ejecuta un paso, leyendo 'PROGRESO n' del script. Devuelve las últimas líneas si falla."""
    with LOCK:
        job["etapa"], job["progreso"] = etapa, 0
    ultimas = []
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=BASE)
        for linea in proc.stdout:
            m = re.match(r"PROGRESO ([\d.]+)", linea)
            d = re.match(r"DISPOSITIVO (\w+)", linea)
            if m:
                with LOCK:
                    job["progreso"] = float(m.group(1))
            elif d:
                with LOCK:
                    job["etapa"] = f"transcribiendo con {d.group(1).upper()}"
            elif linea.strip():
                ultimas = (ultimas + [linea.strip()])[-5:]
        if proc.wait() == 0:
            return None
    except OSError as e:
        ultimas = [str(e)]
    return next((l for l in reversed(ultimas) if "ERROR" in l), ultimas[-1] if ultimas else "falló")


def procesar(job):
    """Transcribe con whisper (si falta) y, si se pidió, analiza con el modelo."""
    vid = job["video"]
    with GPU_LOCK:
        error = None
        if job["tipo"] == "transcribir" or not (VIDEOS / f"{vid}.whisper.json").exists():
            extra = ["--forzar"] if job["tipo"] == "transcribir" else []
            error = correr(job, [WHISPER_PY, "transcribir.py", *extra, "--", vid], "transcribiendo (whisper)")
        if not error and job["tipo"] == "analizar":
            nombre = {"claude": "Opus", "codex": "Codex"}[job["motor"]]
            error = correr(job, [sys.executable, "analizar.py", "--motor", job["motor"], "--", vid], f"analizando con {nombre}")
    with LOCK:
        job["estado"] = "error" if error else "listo"
        job["error"], job["etapa"], job["progreso"] = error, "", 100


def descargar(job):
    """Corre yt-dlp en segundo plano y va actualizando el progreso del trabajo."""
    ultimas = []
    try:
        proc = subprocess.Popen([*YTDLP, "--", job["url"]], stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True)
        for linea in proc.stdout:
            ultimas = (ultimas + [linea.strip()])[-5:]
            m = re.search(r"\[download\]\s+([\d.]+)%", linea)
            v = re.search(r"videos/([\w-]+)\.mp4", linea)  # ignora intermedios ID.f398.mp4
            with LOCK:
                if m:
                    job["progreso"] = float(m.group(1))
                if v:
                    job["video"] = v.group(1)
        proc.wait()
    except OSError as e:
        ultimas = [str(e)]
    with LOCK:
        if job["video"] and (VIDEOS / f"{job['video']}.mp4").exists():
            job["estado"], job["progreso"] = "listo", 100
        else:
            job["estado"] = "error"
            job["error"] = next((l for l in reversed(ultimas) if "ERROR" in l), ultimas[-1] if ultimas else "falló")


def cargar_segmentos():
    if SEGMENTOS.exists():
        return json.loads(SEGMENTOS.read_text(encoding="utf-8"))
    return {}


def listar_videos():
    """Une los mp4 descargados con su metadata de yt-dlp y los segmentos guardados."""
    datos = cargar_segmentos()
    for mp4 in sorted(VIDEOS.glob("*.mp4")):
        vid = mp4.stem
        if "." in vid:  # archivos intermedios de yt-dlp (ej. ID.f398.mp4)
            continue
        info_path = VIDEOS / f"{vid}.info.json"
        try:
            info = json.loads(info_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):  # falta o está a medio escribir
            info = {}
        item = datos.setdefault(vid, {"segmentos": []})
        item["titulo"] = info.get("title", item.get("titulo", vid))
        item["url"] = info.get("webpage_url", f"https://www.youtube.com/watch?v={vid}")
        item["archivo"] = f"videos/{mp4.name}"
        item["duracion"] = info.get("duration", item.get("duracion"))
        subs = [VIDEOS / f"{vid}.{l}.vtt" for l in ("es-orig", "es", "en-orig", "en")]
        item["subtitulos"] = next((f"videos/{s.name}" for s in subs if s.exists()), None)
        item["transcrito"] = (VIDEOS / f"{vid}.whisper.json").exists()
        for clave, archivo in (("sugerencias_modelo", f"{vid}.json"), ("sugerencias_codex", f"{vid}.codex.json")):
            try:
                sug = json.loads((SUGERENCIAS / archivo).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                sug = {}
            item[clave] = sug.get("segmentos", [])
            item[clave.replace("sugerencias", "info")] = {k: sug.get(k) for k in ("modelo", "fecha", "transcripcion")} if sug else None
        item["sugerencias_info"] = item.pop("info_modelo")
        # CAVA: solo las rutas de cada corrida; la app trae el archivo (grande) al abrirlo, así no entra a segmentos.json
        item.pop("cava", None)
        corridas = []
        for f in SUGERENCIAS.glob(f"{vid}.cava.*.json"):
            corrida = f.name[len(vid) + len(".cava."):-len(".json")]
            fecha = re.search(r"\d{4}-\d{2}-\d{2}", corrida)
            corridas.append({"id": corrida, "fecha": fecha.group() if fecha else "",
                             "url": f"sugerencias/{f.name}?v={int(f.stat().st_mtime)}"})
        item["cava_corridas"] = sorted(corridas, key=lambda c: (c["fecha"], c["id"]))  # la última es la más nueva
        item["capitulos_youtube"] = [
            {"tema": c.get("title"), "inicio": c.get("start_time"), "fin": c.get("end_time")}
            for c in (info.get("chapters") or [])
        ]
    return datos


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(BASE), **kwargs)

    def log_message(self, fmt, *args):
        pass

    def enviar_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/videos":
            return self.enviar_json(listar_videos())
        if self.path == "/api/trabajos":
            with LOCK:
                return self.enviar_json(TRABAJOS)
        if self.path.split("?")[0].endswith(".mp4"):
            return self.servir_rango()
        return super().do_GET()

    def do_POST(self):
        largo = int(self.headers.get("Content-Length", 0))
        datos = json.loads(self.rfile.read(largo) or b"{}")
        if self.path == "/api/descargar":
            url = str(datos.get("url", "")).strip()
            if not re.match(r"https?://\S+$", url):
                return self.enviar_json({"error": "URL no válida"}, 400)
            job = nuevo_trabajo("descargar", url=url, etapa="descargando")
            threading.Thread(target=descargar, args=(job,), daemon=True).start()
            return self.enviar_json(job)
        if self.path == "/api/procesar":
            vid, tipo, motor = str(datos.get("id", "")), datos.get("tipo"), datos.get("motor", "claude")
            if tipo not in ("transcribir", "analizar") or motor not in ("claude", "codex") \
                    or not (VIDEOS / f"{vid}.mp4").is_file() or not re.fullmatch(r"[\w-]+", vid):
                return self.enviar_json({"error": "petición no válida"}, 400)
            job = nuevo_trabajo(tipo, video=vid, motor=motor)
            threading.Thread(target=procesar, args=(job,), daemon=True).start()
            return self.enviar_json(job)
        if self.path == "/api/borrar":
            return self.borrar_video(str(datos.get("id", "")))
        if self.path != "/api/segmentos":
            return self.send_error(404)
        tmp = SEGMENTOS.with_suffix(".tmp")
        tmp.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, SEGMENTOS)
        self.enviar_json({"ok": True})

    def borrar_video(self, vid):
        """Elimina el video, sus subtítulos/metadata, sus clips y sus segmentos."""
        if not re.fullmatch(r"[\w-]+", vid):
            return self.enviar_json({"error": "id no válido"}, 400)
        archivos = [*VIDEOS.glob(f"{vid}.*"), *(BASE / "clips").glob(f"{vid}_*.mp4"),
                    *SUGERENCIAS.glob(f"{vid}.json"), *SUGERENCIAS.glob(f"{vid}.codex.json"),
                    *SUGERENCIAS.glob(f"{vid}.cava.*.json")]
        for f in archivos:
            f.unlink(missing_ok=True)
        datos = cargar_segmentos()
        if datos.pop(vid, None) is not None:
            tmp = SEGMENTOS.with_suffix(".tmp")
            tmp.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, SEGMENTOS)
        self.enviar_json({"ok": True, "borrados": len(archivos)})

    def servir_rango(self):
        """Soporte de HTTP Range para poder adelantar/retroceder el video."""
        ruta = Path(self.translate_path(self.path))
        if not ruta.is_file() or BASE not in ruta.resolve().parents:
            return self.send_error(404)
        total = ruta.stat().st_size
        inicio, fin = 0, total - 1
        m = re.match(r"bytes=(\d*)-(\d*)", self.headers.get("Range", ""))
        if m:
            if m.group(1):
                inicio = int(m.group(1))
                if m.group(2):
                    fin = min(int(m.group(2)), total - 1)
            elif m.group(2):
                inicio = max(0, total - int(m.group(2)))
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {inicio}-{fin}/{total}")
        else:
            self.send_response(200)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(fin - inicio + 1))
        self.end_headers()
        with open(ruta, "rb") as f:
            f.seek(inicio)
            restante = fin - inicio + 1
            try:
                while restante > 0:
                    chunk = f.read(min(1 << 20, restante))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    restante -= len(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass


if __name__ == "__main__":
    # python3 servidor.py [puerto] [--cookies chrome|chromium|firefox]
    args = sys.argv[1:]
    if "--cookies" in args:
        i = args.index("--cookies")
        YTDLP += ["--cookies-from-browser", args[i + 1]]
        print(f"yt-dlp usará las cookies de {args[i + 1]}")
        del args[i:i + 2]
    puerto = int(args[0]) if args else 8000
    print(f"Segmentador en http://localhost:{puerto}")
    print(f"Whisper: {WHISPER_PY}")
    ThreadingHTTPServer(("127.0.0.1", puerto), Handler).serve_forever()
