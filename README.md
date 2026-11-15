# Segmentador de videos

1. `./descargar.sh` — descarga los videos (720p) a `videos/` con yt-dlp.
2. `python3 servidor.py` y abrir http://localhost:8000
3. Marcar segmentos (se guardan solos en `segmentos.json`).
4. `python3 cortar.py` — genera los clips en `clips/` (`--exacto` para corte al frame, `--id ID` para un solo video).

## Análisis con IA (solo texto)
El modelo recibe **únicamente la transcripción** (no ve los capítulos del creador, ni el título, ni la imagen).

1. **Transcripción local** con faster-whisper (`large-v3-turbo`) → `videos/<ID>.whisper.json`
   - **GPU automática**: el servidor usa el venv que tenga `faster-whisper` + librerías `nvidia/cublas` y `nvidia/cudnn`
     (hoy `~/Projects/ONG-SinLimites/.venv-whisper`, el mismo enfoque que `UTEC/SO/Clases Grabadas/Herramientas/transcribir_clases.py`).
     `transcribir.py` pone esas librerías en `LD_LIBRARY_PATH` y se relanza; si la GPU falla, sigue en CPU.
   - Forzar otro Python: `WHISPER_PY=/ruta/bin/python python3 servidor.py`
2. **Análisis** con Claude CLI (`claude -p --model opus`, sin herramientas, salida JSON con esquema) → `sugerencias/<ID>.json`
3. En la interfaz se ven como una franja **violeta** (la del creador es **amarilla**), con hover que muestra tema, rango, resumen y el porqué del corte.

Desde la interfaz: botón **🤖 Analizar con IA** (transcribe si falta y analiza). Por terminal, en lote:
```
~/.venv-videoia/bin/python transcribir.py          # todos los que falten
python3 analizar.py                                # todos los transcritos sin sugerencia
python3 analizar.py ID --modelo sonnet             # rehacer uno con otro modelo
```
### Codex y entrada "a mano"
```
python3 analizar.py ID --solo-entrada        # escribe la entrada exacta: entradas/ID.prompt.md + entradas/esquema.json
python3 analizar.py ID --motor codex         # Codex CLI -> sugerencias/ID.codex.json (franja turquesa, tecla X)
python3 comparar.py ID                       # creador vs Claude vs Codex -> comparaciones/ID.md
```
Lo mismo a mano, con la misma entrada para los dos modelos:
```
cd entradas
codex exec --skip-git-repo-check --ephemeral -s read-only --output-schema esquema.json -o codex.json - < ID.prompt.md
claude -p --model opus --tools "" --output-format json --json-schema "$(cat esquema.json)" < ID.prompt.md > claude.json
```

El **criterio de corte** está en `prompt_analisis.md`: edítalo para cambiar cómo segmenta el modelo (y cítalo en la metodología).

## Atajos
| Tecla | Acción |
|---|---|
| `I` | marca inicio |
| `O` | marca fin y pasa a escribir el tema (si no hubo `I`, empieza donde terminó el segmento anterior) |
| `K` | corta aquí: cierra el segmento actual y abre otro en el mismo punto |
| `Esc` | cancela el inicio pendiente |
| `Espacio` | play / pausa |
| `←` `→` | ±5 s (`Shift` ±1 s, `Ctrl` ±30 s) |
| `,` `.` | frame atrás / adelante |
| `[` `]` | velocidad |
| `J` `L` | segmento anterior / siguiente |
| `G` / `M` | mostrar/ocultar guía del creador / sugerencia IA |
| `Supr` | borra el segmento seleccionado |

Los tiempos, el tema y las notas se pueden editar en la tabla (formato `m:ss.s` o `h:mm:ss`).
Las líneas amarillas en la barra son los capítulos de YouTube (si el video los tiene); "Importar capítulos YT" los convierte en segmentos.

## segmentos.json
```json
{
  "VIDEO_ID": {
    "titulo": "...", "url": "...", "archivo": "videos/VIDEO_ID.mp4", "duracion": 1834,
    "segmentos": [{ "id": 1, "tema": "Introducción", "inicio": 0.0, "fin": 125.4, "notas": "" }]
  }
}
```

## Videos locales y resultados de CAVA

Películas u otros archivos que no vienen de YouTube (todo en la GPU: NVDEC + libplacebo + NVENC):
```
python3 importar.py ~/Downloads/pelicula.mkv mi_id --titulo "Título"
~/Projects/ONG-SinLimites/.venv-whisper/bin/python transcribir.py --idioma en mi_id
python3 analizar.py --motor claude -- mi_id ; python3 analizar.py --motor codex -- mi_id
```

Resultados de CAVA (el zip del servidor se descomprime en `cava/`, una carpeta por película):
```
python3 importar_cava.py cava/Avengers_Endgame cava/Spider_Man   # -> sugerencias/<ID>.cava.<corrida>.json
python3 comparar.py endgame_2019                                 # incluye CAVA y una referencia de azar
```
El video se reconoce solo por el archivo original (`source.json` ↔ `origen_local` de `importar.py`); si no, `--id`.
En la app: 4ª franja **CAVA** (un color por tópico; los que vuelven repiten color, tecla `C`), barra inferior
**Capas CAVA** con los niveles default/fine y las versiones full_chapters, recap60, highlights10pct, threads y
speaker_threads en paralelo (tecla `V`; al pasar el mouse se resaltan todos los tramos del tópico), botón
**Solo CAVA** (tecla `S`) que esconde las guías de creador/Opus/Codex, y la fuente **CAVA** en "Cortes sugeridos".

Zoom de la línea de tiempo (cualquier video): `Ctrl`+rueda acerca/aleja donde está el mouse, la rueda desplaza en
horizontal, `+`/`-`/`0` desde el teclado. La barra de arriba (franjas + línea de tiempo) y las capas de CAVA
comparten zoom y desplazamiento; "seguir cabezal" mueve la vista sola mientras se reproduce.

Recopilación de tópicos (videos con CAVA): debajo de las capas se elige un tópico (todos sus tramos en orden
cronológico) o una versión/playlist de CAVA (en el orden en que CAVA la armó) y se reproduce de corrido, saltando
solo de un tramo al siguiente; la barra amarilla muestra la recopilación como una sola línea continua (clic = ir a
ese punto). Doble clic sobre cualquier tramo de CAVA recopila su tópico (o su playlist); tecla `R` reproduce/pausa.

Varias corridas de CAVA por video: cada una queda en `sugerencias/<ID>.cava.<corrida>.json` y en la app se elige
en el selector de "Capas CAVA" (por defecto la más nueva). Si un paquete no trae `source.json`/`run_manifest.json`
(p. ej. los paquetes textuales), primero se completan con los de otra corrida de la misma película; quedan
marcados `"reconstruido": true` y lo que no se sabe (commit, modelos, fecha exacta) queda en null:
```
python3 completar_cava.py cava/texto/Avengers_Endgame --referencia cava/Avengers_Endgame --corrida texto-2026-11-09
python3 importar_cava.py cava/texto/Avengers_Endgame cava/texto/Spider_Man
```
Si el paquete trae `transcripcion.jsonl`, el diálogo exacto de cada tramo se ve en el recuadro y en la tabla de la
recopilación. `comparar.py` compara cada corrida con Claude/Codex (más su referencia de azar) y las corridas entre sí.

Paquetes EXP-035/EXP-036 (zip con `EXP-035/<película>/` y `EXP-036/F1|F2/<película>/`): se descomprimen en `cava/`
y se importan como otra corrida; el importador encuentra solo las escenas F2, los briefs F1, `scene_briefs.json` y
las etiquetas de `work_registry` (si falta `source.json`, usa el de otra corrida de la misma película):
```
python3 importar_cava.py cava/EXP035_036_texto_20261114/EXP-035/Avengers_Endgame \
                         cava/EXP035_036_texto_20261114/EXP-035/Spider_Man --corrida exp035-2026-11-10
```
En la app aparece la fila "Escenas F2" (escenas contiguas, color = tópico dominante) y los briefs en el recuadro;
`comparar.py` compara las escenas F2 con Claude/Codex como `escenas:<corrida>`.
