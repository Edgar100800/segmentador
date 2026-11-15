#!/usr/bin/env python3
"""Pide a un modelo (Claude CLI o Codex CLI) que sugiera los cortes usando SOLO la transcripción de whisper.

Uso:
  python3 analizar.py ID [ID ...]      # o sin IDs para todos los transcritos sin sugerencia
  opciones: --motor claude|codex  --modelo opus|sonnet|<modelo codex>  --forzar
            --solo-entrada   escribe la entrada exacta (entradas/<ID>.prompt.md + esquema.json) y no llama al modelo
Resultado: sugerencias/<ID>.json (claude) o sugerencias/<ID>.codex.json (codex); el criterio está en prompt_analisis.md
"""
import argparse
import json
import subprocess
import sys
import tempfile
import tomllib
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
VIDEOS = BASE / "videos"
SUGERENCIAS = BASE / "sugerencias"
ENTRADAS = BASE / "entradas"

ESQUEMA = {
    "type": "object",
    "properties": {"segmentos": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "tema": {"type": "string"}, "inicio": {"type": "number"}, "fin": {"type": "number"},
            "resumen": {"type": "string"}, "razon": {"type": "string"},
        },
        "required": ["tema", "inicio", "fin", "resumen", "razon"],
        "additionalProperties": False,
    }}},
    "required": ["segmentos"],
    "additionalProperties": False,
}


def mmss(s):
    s = int(s)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def construir_prompt(trans):
    lineas = [f"[{f['inicio']:.1f}s | {mmss(f['inicio'])}] {f['texto']}" for f in trans["segmentos"]]
    criterio = (BASE / "prompt_analisis.md").read_text(encoding="utf-8")
    return (f"{criterio}\n\n## Transcripción\nIdioma: {trans['idioma']} · Duración total: "
            f"{trans['duracion']:.1f}s ({mmss(trans['duracion'])})\n\n" + "\n".join(lineas))


def limpiar(segs, dur):
    """Ordena, recorta a la duración y descarta segmentos vacíos."""
    out = []
    for s in sorted(segs, key=lambda x: x["inicio"]):
        ini, fin = max(0.0, float(s["inicio"])), min(dur, float(s["fin"]))
        if fin - ini >= 1:
            out.append({**s, "inicio": round(ini, 2), "fin": round(fin, 2)})
    return out


def destino(vid, motor):
    return SUGERENCIAS / (f"{vid}.json" if motor == "claude" else f"{vid}.{motor}.json")


def con_claude(prompt, modelo):
    r = subprocess.run(
        ["claude", "-p", "--model", modelo, "--output-format", "json", "--tools", "",
         "--json-schema", json.dumps(ESQUEMA)],
        input=prompt, capture_output=True, text=True, cwd=BASE, timeout=1200,
    )
    try:
        resp = json.loads(r.stdout)
    except ValueError:
        sys.exit(f"ERROR: respuesta inválida de claude: {(r.stderr or r.stdout)[-300:]}")
    if resp.get("is_error") or not resp.get("structured_output"):
        sys.exit(f"ERROR: claude falló: {str(resp.get('result'))[-300:]}")
    return resp["structured_output"], modelo


def con_codex(prompt, modelo):
    """codex exec sin herramientas útiles: carpeta vacía, sandbox de solo lectura, salida con esquema."""
    with tempfile.TemporaryDirectory() as tmp:
        esquema, salida = Path(tmp) / "esquema.json", Path(tmp) / "salida.json"
        esquema.write_text(json.dumps(ESQUEMA))
        cmd = ["codex", "exec", "--skip-git-repo-check", "--ephemeral", "-s", "read-only", "-C", tmp,
               "--output-schema", str(esquema), "-o", str(salida), "-"]
        if modelo:
            cmd[2:2] = ["-m", modelo]
        r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=1800)
        if r.returncode or not salida.exists():
            sys.exit(f"ERROR: codex falló: {(r.stderr or r.stdout)[-300:]}")
        try:
            return json.loads(salida.read_text()), modelo or modelo_codex()
        except ValueError:
            sys.exit(f"ERROR: respuesta inválida de codex: {salida.read_text()[-300:]}")


def modelo_codex():
    """Modelo por defecto de ~/.codex/config.toml (para dejarlo registrado en la sugerencia)."""
    try:
        cfg = tomllib.loads((Path.home() / ".codex/config.toml").read_text())
        return f"{cfg.get('model', 'codex')} ({cfg.get('model_reasoning_effort', 'default')})"
    except (OSError, tomllib.TOMLDecodeError):
        return "codex"


def analizar(vid, motor, modelo, solo_entrada=False):
    trans_path = VIDEOS / f"{vid}.whisper.json"
    if not trans_path.exists():
        sys.exit(f"ERROR: {vid} no está transcrito (corre transcribir.py primero)")
    trans = json.loads(trans_path.read_text(encoding="utf-8"))
    prompt = construir_prompt(trans)
    if solo_entrada:
        ENTRADAS.mkdir(exist_ok=True)
        (ENTRADAS / f"{vid}.prompt.md").write_text(prompt, encoding="utf-8")
        (ENTRADAS / "esquema.json").write_text(json.dumps(ESQUEMA, indent=2), encoding="utf-8")
        print(f"OK {vid}: entrada en entradas/{vid}.prompt.md ({len(prompt)} caracteres) + entradas/esquema.json")
        return
    print(f"Analizando {vid} con {motor} {modelo or ''} ({len(trans['segmentos'])} frases)…", flush=True)
    t0 = datetime.now()
    resp, modelo = (con_claude if motor == "claude" else con_codex)(prompt, modelo)

    segs = limpiar(resp["segmentos"], trans["duracion"])
    SUGERENCIAS.mkdir(exist_ok=True)
    destino(vid, motor).write_text(json.dumps({
        "video": vid, "motor": motor, "modelo": modelo, "fecha": datetime.now().isoformat(timespec="seconds"),
        "segundos": round((datetime.now() - t0).total_seconds()),
        "transcripcion": trans["modelo"], "criterio": "prompt_analisis.md", "segmentos": segs,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"OK {vid}: {len(segs)} segmentos sugeridos -> {destino(vid, motor).relative_to(BASE)}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="*")
    ap.add_argument("--motor", choices=["claude", "codex"], default="claude")
    ap.add_argument("--modelo", help="claude: opus (defecto)|sonnet; codex: el de ~/.codex/config.toml si se omite")
    ap.add_argument("--forzar", action="store_true")
    ap.add_argument("--solo-entrada", action="store_true")
    args = ap.parse_args()
    modelo = args.modelo or ("opus" if args.motor == "claude" else None)
    ids = args.ids or [p.name.split(".")[0] for p in sorted(VIDEOS.glob("*.whisper.json"))]
    for vid in ids:
        if args.solo_entrada or args.forzar or args.ids or not destino(vid, args.motor).exists():
            analizar(vid, args.motor, modelo, args.solo_entrada)


if __name__ == "__main__":
    main()
