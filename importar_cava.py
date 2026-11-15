#!/usr/bin/env python3
"""Convierte la salida de CAVA (topic_map.json + versions.json) al formato de la app.

Uso:
  python3 importar_cava.py cava/Avengers_Endgame [cava/Spider_Man ...]   [--id ID] [--corrida NOMBRE]
El video de la app se reconoce solo: source.json["original"] se compara con el origen_local que
importar.py dejó en videos/<ID>.info.json (o se fuerza con --id si es una sola carpeta).
A los paquetes sin source.json/run_manifest.json se les agregan antes con completar_cava.py.
Cada corrida va a su propio archivo y la app deja elegir cuál ver:
  corrida = run_manifest["corrida"] o "<perfil>-<fecha>" (p. ej. film-2026-11-07, texto-2026-11-09)
Resultado: sugerencias/<ID>.cava.<corrida>.json con
  segmentos: los tramos del nivel "default" (contiguos, cubren todo) -> 4ª franja y tabla de la app
  capas:     niveles default/fine y las versiones (full_chapters, recap60, highlights10pct, threads,
             speaker_threads) -> barra inferior "Capas CAVA", una fila por capa
  topicos:   etiqueta, personajes, retornos, voces y señales de cada tópico (por nivel)
  dialogo:   [inicio, fin, texto] de transcripcion.jsonl si el paquete la trae (diálogo exacto de cada tramo)
Extras que se buscan solos junto a la carpeta (paquetes EXP-035/EXP-036, ver extras()):
  escenas F2 (EXP-036/F2/<película>/escenas.json) -> capa "Escenas F2" y segmentos_escenas (contiguos)
  briefs F1 de escenas y tópicos (EXP-036/F1/<película>/briefs_f1_*.json), scene_briefs.json de EXP-035 y las
  etiquetas con nombres estables de work_registry -> se ven en el recuadro de cada tramo
"""
import argparse
import json
import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
VIDEOS = BASE / "videos"
SUGERENCIAS = BASE / "sugerencias"

CAPAS = [  # (clave, nombre, descripción) en el orden en que se muestran
    ("default", "Tópicos", "nivel default del mapa de tópicos: cada tramo con su tópico (los colores repetidos son tópicos que vuelven)"),
    ("fine", "Tópicos finos", "nivel fine: la misma película partida más fino"),
    ("full_chapters", "Capítulos", "full_chapters: el tramo más largo de cada tópico aceptado"),
    ("recap60", "Recap 60 s", "recap60: lo más temático hasta 60 s"),
    ("highlights10pct", "Highlights 10 %", "highlights10pct: lo más temático hasta el 10 % de la duración"),
    ("threads", "Hilos", "threads: sigue los tópicos con más retornos (una playlist por hilo)"),
    ("speaker_threads", "Hilos por voz", "speaker_threads: sigue a las voces con más tiempo dominante (una playlist por voz)"),
]


def partir_etiqueta(t):
    """'CHARACTERS: a | TOPIC: b' -> (b, a); si no tiene ese formato, (descripción, "")."""
    m = re.match(r"\s*CHARACTERS:\s*(.*?)\s*[|/]\s*TOPIC:\s*(.*)", t or "", re.S)
    return (m.group(2).strip(), m.group(1).strip()) if m else ((t or "").strip(), "")


def voces(speakers, n=3):
    return ", ".join(f"{s['id']} {s['share']:.0%}" for s in (speakers or [])[:n])


def senales(prov):
    nombres = {"visual": "imagen", "transcript": "texto", "voice": "voz", "vjudge": "juez visual"}
    return ", ".join(f"{nombres.get(k, k)} {v['agreement']:.2f}" for k, v in (prov or {}).items()
                     if v.get("agreement") is not None)


def topicos(nivel):
    out = {}
    for x in nivel["topics"]:
        tema, personajes = partir_etiqueta(x.get("topic_label") or x["label"])
        ctx = (x.get("context") or [{}])[0]
        out[str(x["topic_id"])] = {
            "tema": tema, "personajes": personajes, "descripcion": x["label"],
            "duracion": x["duration_s"], "tramos": len(x["spans"]), "retornos": x["returns"],
            "voces": voces(x.get("speakers"), 4), "senales": senales(x.get("provenance")),
            "revisar": bool((x.get("flags") or {}).get("needs_review")),
            "visto": " ".join(ctx.get("seen") or [])[:400], "dicho": (ctx.get("said") or "")[:400],
        }
    return out


def tramos(nivel):
    return sorted(({"inicio": a, "fin": b, "topico": x["topic_id"]} for x in nivel["topics"] for a, b in x["spans"]),
                  key=lambda s: s["inicio"])


def buscar_video(carpeta):
    fuente = carpeta / "source.json"
    if not fuente.exists():  # paquetes sin source.json: el de otra corrida de la misma película (misma carpeta)
        fuente = next((f for f in sorted((BASE / "cava").rglob(f"{carpeta.name}/source.json"))), None)
        if not fuente:
            sys.exit(f"ERROR: {carpeta} no trae source.json y no hay otra corrida de «{carpeta.name}»; usa --id")
    original = Path(json.loads(fuente.read_text(encoding="utf-8"))["original"]).name
    for info in VIDEOS.glob("*.info.json"):
        try:
            d = json.loads(info.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if Path(d.get("origen_local", "")).name == original:
            return info.name.split(".")[0]
    sys.exit(f"ERROR: ningún video de la app viene de «{original}»; impórtalo con importar.py o usa --id")


def leer(ruta):
    return json.loads(ruta.read_text(encoding="utf-8")) if ruta and ruta.exists() else None


def extras(carpeta):
    """Archivos de EXP-035/EXP-036 que acompañan a una carpeta <paquete>/EXP-035/<película>."""
    raiz, peli = carpeta.parent.parent, carpeta.name
    return {
        "escenas": leer(raiz / "EXP-036" / "F2" / peli / "escenas.json"),
        "f1_escenas": leer(raiz / "EXP-036" / "F1" / peli / "briefs_f1_escenas.json") or {},
        "f1_topicos": leer(raiz / "EXP-036" / "F1" / peli / "briefs_f1_topicos.json") or {},
        "scene_briefs": leer(carpeta / "scene_briefs.json") or {},
        "registro": leer(carpeta.parent / "work_registry" / peli / f"{peli}.topic_labels.json") or {},
    }


def resumir_f1(b):
    """Brief verificable de F1 -> (desarrollo, personajes con nombre o descripción)."""
    if not b or b.get("status") != "ok" or not b.get("brief"):
        return "", ""
    br = b["brief"]
    gente = ", ".join(c.get("name") or c.get("description", "") for c in br.get("characters", []))
    return br.get("development", ""), gente


def nombre_corrida(manifiesto):
    if manifiesto.get("corrida"):
        return manifiesto["corrida"]
    return f"{manifiesto['profile']['profile']}-{(manifiesto.get('created_utc') or '')[:10]}"


def convertir(carpeta, vid, corrida=None):
    tm = json.loads((carpeta / "topic_map.json").read_text(encoding="utf-8"))
    versiones = json.loads((carpeta / "versions.json").read_text(encoding="utf-8"))
    manifiesto = json.loads((carpeta / "run_manifest.json").read_text(encoding="utf-8"))
    info = json.loads((VIDEOS / f"{vid}.info.json").read_text(encoding="utf-8"))
    dur_app = info.get("duration") or tm["duration_s"]
    if abs(dur_app - tm["duration_s"]) > 60:
        print(f"AVISO {vid}: CAVA dura {tm['duration_s']:.0f}s y el video de la app {dur_app:.0f}s", flush=True)

    tops = {nivel: topicos(tm["levels"][nivel]) for nivel in ("default", "fine")}
    ex = extras(carpeta)
    # registro: Avengers usa claves "<tópico>", Spider-Man "<tópico>@<t0>-<t1>" (una por tramo): se toma la primera
    registro = {}
    for k, v in sorted(ex["registro"].items(), key=lambda kv: float(kv[0].split("@")[-1].split("-")[0]) if "@" in kv[0] else 0):
        registro.setdefault(k.split("@")[0], v)
    for tid, t in tops["default"].items():
        if tid in ex["scene_briefs"]:
            t["brief"] = ex["scene_briefs"][tid]
        if tid in registro:
            t["tema_registro"], t["personajes_registro"] = partir_etiqueta(registro[tid])
        dev, gente = resumir_f1(ex["f1_topicos"].get(tid))
        if dev:
            t["brief_f1"], t["personajes_f1"] = dev, gente
    segmentos = []
    for s in tramos(tm["levels"]["default"]):
        t = tops["default"][str(s["topico"])]
        vuelve = f"vuelve {t['retornos']} veces ({t['tramos']} tramos, {t['duracion'] / 60:.1f} min en total)" \
            if t["retornos"] else "no vuelve a aparecer"
        segmentos.append({
            "tema": t["tema"], "inicio": s["inicio"], "fin": s["fin"], "topico": s["topico"],
            "resumen": t["descripcion"] + (f" — Personajes: {t['personajes']}" if t["personajes"] else ""),
            "razon": f"Tópico {s['topico']} · {vuelve} · voces {t['voces']}" + (" · ⚠ revisar" if t["revisar"] else ""),
        })

    capas = []
    for clave, nombre, desc in CAPAS:
        if clave in ("default", "fine"):
            items = tramos(tm["levels"][clave])
            for it in items:
                it["tema"] = tops[clave][str(it["topico"])]["tema"]
            nivel = clave
        elif clave in versiones:
            v = versiones[clave]
            items = [{"inicio": c["t0"], "fin": c["t1"], "topico": c["topic_id"], "tema": partir_etiqueta(c["label"])[0],
                      "playlist": p, **({"voz": c["speaker"]} if c.get("speaker") else {})}
                     for p, lista in enumerate(v["playlists"]) for c in lista]
            if v.get("budget_s"):
                desc += f" · presupuesto {v['budget_s']:.0f} s"
            nivel = "default"
        else:
            continue
        capas.append({"clave": clave, "nombre": nombre, "descripcion": desc, "nivel": nivel, "items": items})

    segmentos_escenas = []
    if ex["escenas"]:
        e, items = ex["escenas"], []
        for sc in e["scenes"]:
            dev, gente = resumir_f1(ex["f1_escenas"].get(f"S{sc['scene_id']}"))
            items.append({"inicio": sc["t0"], "fin": sc["t1"], "topico": sc["topic_dominante"], "escena": sc["scene_id"],
                          "tema": f"Escena {sc['scene_id']}", "pureza": round(sc["pureza_topico"], 2),
                          **({"brief": dev, "personajes": gente} if dev else {})})
            segmentos_escenas.append({"tema": f"Escena {sc['scene_id']}", "inicio": sc["t0"], "fin": sc["t1"],
                                      "resumen": dev, "topico": sc["topic_dominante"]})
        r = e["resumen"]
        capas.insert(2, {"clave": "escenas", "nombre": "Escenas F2", "nivel": "default", "items": items,
                         "descripcion": f"EXP-036 F2 (sin calibrar): {r['n_escenas']} escenas contiguas, mediana "
                                        f"{r['dur_mediana_s']:.0f} s; color = tópico dominante (pureza mediana "
                                        f"{r['pureza_topico_mediana']:.0%})"})

    corrida = corrida or nombre_corrida(manifiesto)
    commit = (manifiesto.get("code") or {}).get("git_commit")
    dialogo = []
    if (carpeta / "transcripcion.jsonl").exists():
        for linea in (carpeta / "transcripcion.jsonl").read_text(encoding="utf-8").splitlines():
            if linea.strip():
                d = json.loads(linea)
                dialogo.append([round(d["t0_s"], 2), round(d["t1_s"], 2), d["texto"].strip()])
    salida = {
        "video": vid, "fuente": "CAVA", "corrida": corrida, "carpeta": str(carpeta.relative_to(BASE)),
        "reconstruido": bool(manifiesto.get("reconstruido")),
        "modelo": f"CAVA {corrida}" + (f" (git {commit[:7]})" if commit else " (procedencia reconstruida)"
                                       if manifiesto.get("reconstruido") else ""),
        "fecha": (manifiesto.get("created_utc") or manifiesto.get("fecha_archivos") or "")[:19], "duracion": tm["duration_s"],
        "modelos": {k: v[0] for k, v in (manifiesto.get("models") or {}).items()},
        "dialogo": dialogo,
        "voces": tm.get("voice_identities", []),
        "segmentos": segmentos, "segmentos_escenas": segmentos_escenas, "capas": capas, "topicos": tops,
    }
    destino = SUGERENCIAS / f"{vid}.cava.{corrida}.json"
    destino.write_text(json.dumps(salida, ensure_ascii=False), encoding="utf-8")
    extra = f"{len(segmentos_escenas)} escenas F2, {sum('brief' in t for t in tops['default'].values())} briefs de tópico, " \
        if ex["escenas"] or ex["scene_briefs"] else ""
    print(f"OK {carpeta.name} [{corrida}] -> {destino.relative_to(BASE)}: {len(segmentos)} tramos, {len(dialogo)} frases de diálogo, {extra}"
          f"{len(tops['default'])} tópicos, capas: " + ", ".join(f"{c['clave']} ({len(c['items'])})" for c in capas), flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("carpetas", nargs="+")
    ap.add_argument("--id", help="ID del video en la app (solo con una carpeta)")
    ap.add_argument("--corrida", help="nombre de la corrida (por defecto, el del run_manifest o <perfil>-<fecha>)")
    args = ap.parse_args()
    if args.id and len(args.carpetas) > 1:
        sys.exit("ERROR: --id solo sirve con una carpeta")
    for c in args.carpetas:
        carpeta = Path(c).resolve()
        convertir(carpeta, args.id or buscar_video(carpeta), args.corrida)


if __name__ == "__main__":
    main()
