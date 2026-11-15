#!/usr/bin/env python3
"""Compara los cortes del creador (capítulos de YouTube), de Claude, de Codex y de CAVA para un video.

Uso:
  python3 comparar.py ID [--tolerancia 15]
Un corte "coincide" si hay otro corte a <= tolerancia segundos (emparejamiento 1 a 1, el más cercano primero).
CAVA (sugerencias/ID.cava.<corrida>.json, de importar_cava.py) entra con los tramos del nivel default de cada
corrida (fuente "cava:<corrida>"); un tópico que vuelve genera varios tramos, así que sus cortes son muchos más y
su precisión baja por diseño. Con dos o más corridas también se comparan entre sí.
Resultado: comparaciones/<ID>.md (también se imprime)
"""
import argparse
import json
import random
from pathlib import Path

BASE = Path(__file__).resolve().parent
VIDEOS = BASE / "videos"
SUGERENCIAS = BASE / "sugerencias"


def mmss(s):
    s = int(round(s))
    return f"{s // 60}:{s % 60:02d}"


def cargar(vid):
    """{fuente: [segmentos {tema, inicio, fin}]} con las fuentes que existan."""
    fuentes = {}
    info = json.loads((VIDEOS / f"{vid}.info.json").read_text(encoding="utf-8"))
    if info.get("chapters"):
        fuentes["creador"] = [{"tema": c["title"], "inicio": c["start_time"], "fin": c["end_time"]}
                              for c in info["chapters"]]
    archivos = [("claude", SUGERENCIAS / f"{vid}.json"), ("codex", SUGERENCIAS / f"{vid}.codex.json")]
    archivos += [("cava:" + p.name[len(vid) + 6:-5], p) for p in sorted(SUGERENCIAS.glob(f"{vid}.cava.*.json"))]
    for nombre, p in archivos:
        if p.exists():
            d = json.loads(p.read_text(encoding="utf-8"))
            fuentes[nombre] = d["segmentos"]
            fuentes[nombre + "_meta"] = d
            if d.get("segmentos_escenas"):  # escenas F2 (EXP-036): contiguas, comparables con Claude/Codex
                esc = "escenas:" + nombre.split(":", 1)[1]
                fuentes[esc] = d["segmentos_escenas"]
                fuentes[esc + "_meta"] = {"modelo": f"EXP-036 F2 ({nombre.split(':', 1)[1]})"}
    return info, fuentes


def cortes(segs):
    """Instantes de corte internos (sin el 0 inicial)."""
    return [s["inicio"] for s in segs if s["inicio"] > 1]


def emparejar(a, b, tol):
    """Pares (x, y) con |x-y| <= tol, 1 a 1, los más cercanos primero."""
    candidatos = sorted((abs(x - y), i, j) for i, x in enumerate(a) for j, y in enumerate(b) if abs(x - y) <= tol)
    usados_a, usados_b, pares = set(), set(), []
    for _, i, j in candidatos:
        if i not in usados_a and j not in usados_b:
            usados_a.add(i), usados_b.add(j)
            pares.append((a[i], b[j]))
    return sorted(pares)


def metricas(pred, ref, tol):
    pares = emparejar(pred, ref, tol)
    p = len(pares) / len(pred) if pred else 0
    r = len(pares) / len(ref) if ref else 0
    f1 = 2 * p * r / (p + r) if p + r else 0
    desfase = sum(abs(x - y) for x, y in pares) / len(pares) if pares else 0
    return {"coinciden": len(pares), "precision": p, "recall": r, "f1": f1, "desfase": desfase}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("id")
    ap.add_argument("--tolerancia", type=float, default=15)
    args = ap.parse_args()
    vid, tol = args.id, args.tolerancia
    info, f = cargar(vid)
    cavas = [k for k in f if k.startswith("cava:") and not k.endswith("_meta")]
    escenas = [k for k in f if k.startswith("escenas:") and not k.endswith("_meta")]
    modelos = [m for m in ("claude", "codex") if m in f] + escenas + cavas
    md = [f"# Comparación de cortes — {info['title']}", "",
          f"Video `{vid}` · duración {mmss(info['duration'])} · tolerancia ±{tol:g} s", ""]

    md += ["## Resumen", "", "| Fuente | Modelo | Segmentos | Duración media | Tiempo de análisis |", "|---|---|---|---|---|"]
    for nombre in ["creador", *modelos]:
        segs = f.get(nombre)
        if not segs:
            continue
        meta = f.get(nombre + "_meta", {})
        media = sum(s["fin"] - s["inicio"] for s in segs) / len(segs)
        seg = f"{meta['segundos']} s" if "segundos" in meta else "—"
        md.append(f"| {nombre} | {meta.get('modelo', 'capítulos YouTube')} | {len(segs)} | {mmss(media)} | {seg} |")

    md += ["", "## Coincidencia de cortes", "",
           "Precisión = cortes del modelo que coinciden con la referencia · Recall = cortes de la referencia que el modelo encontró.", "",
           "| Modelo | Referencia | Coinciden | Precisión | Recall | F1 | Desfase medio |", "|---|---|---|---|---|---|---|"]
    pares_ref = [(m, "creador") for m in modelos if "creador" in f]
    if "codex" in f and "claude" in f:
        pares_ref.append(("codex", "claude"))
    pares_ref += [(e, ref) for e in escenas for ref in ("claude", "codex") if ref in f]
    pares_ref += [(c, ref) for c in cavas for ref in ("claude", "codex") if ref in f]
    pares_ref += [(b, a) for i, a in enumerate(cavas) for b in cavas[i + 1:]]  # corrida nueva vs anterior
    for m, ref in pares_ref:
        r = metricas(cortes(f[m]), cortes(f[ref]), tol)
        md.append(f"| {m} | {ref} | {r['coinciden']} | {r['precision']:.0%} | {r['recall']:.0%} | {r['f1']:.2f} | {r['desfase']:.1f} s |")

    for c in escenas + cavas:
        # con tantos cortes, parte del recall sale por pura densidad: misma cantidad de cortes al azar (semilla fija)
        rng, n = random.Random(0), len(cortes(f[c]))
        for ref in ("claude", "codex"):
            if ref in f:
                azar = [metricas(sorted(rng.uniform(0, info["duration"]) for _ in range(n)), cortes(f[ref]), tol)
                        for _ in range(200)]
                md.append(f"| azar ({n} cortes, como {c}) | {ref} | — | {sum(a['precision'] for a in azar) / 200:.0%} | "
                          f"{sum(a['recall'] for a in azar) / 200:.0%} | {sum(a['f1'] for a in azar) / 200:.2f} | — |")

    # línea de tiempo: todos los cortes ordenados, una columna por fuente (CAVA no: son cientos de tramos)
    fuentes = [n for n in ("creador", *modelos) if n in f and not n.startswith("cava")]
    eventos = sorted({round(s["inicio"]) for n in fuentes for s in f[n]})
    grupos = []  # agrupa cortes cercanos (<= tol) en una misma fila
    for t in eventos:
        if grupos and t - grupos[-1][-1] <= tol:
            grupos[-1].append(t)
        else:
            grupos.append([t])
    md += ["", "## Línea de tiempo (cortes a ≤ tolerancia en la misma fila)", "",
           "| " + " | ".join(fuentes) + " |", "|" + "---|" * len(fuentes)]
    for g in grupos:
        celdas = []
        for n in fuentes:
            hit = [s for s in f[n] if g[0] - 0.5 <= s["inicio"] <= g[-1] + 0.5]
            celdas.append("<br>".join(f"**{mmss(s['inicio'])}** {s['tema']}" for s in hit) or "·")
        md.append("| " + " | ".join(celdas) + " |")

    texto = "\n".join(md) + "\n"
    (BASE / "comparaciones").mkdir(exist_ok=True)
    (BASE / "comparaciones" / f"{vid}.md").write_text(texto, encoding="utf-8")
    print(texto)


if __name__ == "__main__":
    main()
