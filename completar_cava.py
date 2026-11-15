#!/usr/bin/env python3
"""Completa un paquete de CAVA al que le faltan source.json y run_manifest.json (p. ej. los "paquetes textuales").

Uso:
  python3 completar_cava.py cava/texto/Avengers_Endgame --referencia cava/Avengers_Endgame --corrida texto-2026-11-09
Escribe en la carpeta del paquete (sin tocar sus archivos originales):
  source.json        copiado de la referencia (misma película) si la duración del topic_map coincide
  run_manifest.json  schema cava-run-v1 armado con lo que trae el propio topic_map; lo que el paquete no dice
                     (commit, modelos, tiempos) queda en null y se lista en "campos_desconocidos"
Ambos llevan "reconstruido": true para que nunca se confundan con los que genera CAVA en el servidor.
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("paquete")
    ap.add_argument("--referencia", required=True, help="carpeta de otra corrida de la MISMA película con source.json")
    ap.add_argument("--corrida", required=True, help="nombre de esta corrida, p. ej. texto-2026-11-09")
    ap.add_argument("--forzar", action="store_true", help="reescribir aunque ya existan")
    args = ap.parse_args()
    paq, ref = Path(args.paquete), Path(args.referencia)

    tm = json.loads((paq / "topic_map.json").read_text(encoding="utf-8"))
    tm_ref = json.loads((ref / "topic_map.json").read_text(encoding="utf-8"))
    if abs(tm["duration_s"] - tm_ref["duration_s"]) > 1:
        sys.exit(f"ERROR: duraciones distintas ({tm['duration_s']} vs {tm_ref['duration_s']}): no parece la misma película")
    for nombre in ("source.json", "run_manifest.json"):
        if (paq / nombre).exists() and not args.forzar:
            sys.exit(f"ERROR: {paq / nombre} ya existe (usa --forzar)")

    nota = f"Reconstruido en el segmentador el {datetime.now():%Y-%m-%d}: el paquete no traía este archivo."
    fuente = json.loads((ref / "source.json").read_text(encoding="utf-8"))
    fuente.update({"reconstruido": True, "copiado_de": str(ref), "nota": nota})
    (paq / "source.json").write_text(json.dumps(fuente, ensure_ascii=False, indent=2), encoding="utf-8")

    man_ref = json.loads((ref / "run_manifest.json").read_text(encoding="utf-8"))
    nivel = tm["levels"]["default"]
    # fecha: la del topic_map dentro del zip (hora local del servidor, sin zona)
    fecha = datetime.fromtimestamp((paq / "topic_map.json").stat().st_mtime).isoformat(timespec="seconds")
    manifiesto = {
        "schema": "cava-run-v1",
        "corrida": args.corrida,
        "reconstruido": True,
        "nota": nota,
        "created_utc": None,
        "fecha_archivos": fecha,
        "video": {"path": man_ref["video"]["path"], "sha256": man_ref["video"]["sha256"], "duration_s": tm["duration_s"]},
        "audio": None,
        "code": {"git_commit": None, "git_dirty": None, "python": None},
        "profile": {"unit_s": round(tm["duration_s"] / tm["n_units"], 2), **tm["params"]},
        "models": None,
        "outputs": {"n_units": tm["n_units"], "n_topics": nivel["n_topics"], "n_returning": nivel["n_returning"],
                    "voice_identities": tm.get("voice_identities"), "voice_identity_kind": tm.get("voice_identity_kind"),
                    "files": sorted(p.name for p in paq.iterdir() if p.is_file())},
        "campos_inferidos": {"video": f"copiado de {ref}/run_manifest.json (misma película, misma duración)",
                             "profile.unit_s": "duration_s / n_units del topic_map",
                             "fecha_archivos": "fecha del topic_map.json en el zip"},
        "campos_desconocidos": ["created_utc", "code.git_commit", "models", "timings_s"],
    }
    (paq / "run_manifest.json").write_text(json.dumps(manifiesto, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"OK {paq}: source.json + run_manifest.json (corrida {args.corrida}, {nivel['n_topics']} tópicos)", flush=True)


if __name__ == "__main__":
    main()
