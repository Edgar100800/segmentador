import asyncio, base64, json, time, os
from playwright.async_api import async_playwright

URL = "http://localhost:8000/"
DUR = json.load(open("duraciones.json"))
os.makedirs("frames", exist_ok=True)
for f in os.listdir("frames"): os.remove("frames/" + f)
frames, escenas = [], []

CURSOR_JS = r"""
window.addEventListener('DOMContentLoaded', () => {
  const st = document.createElement('style');
  st.textContent = `#__cur{position:fixed;left:0;top:0;width:28px;height:28px;z-index:2147483647;pointer-events:none;transform:translate(-3px,-2px);filter:drop-shadow(0 2px 3px rgba(0,0,0,.6))}
  .__rip{position:fixed;width:44px;height:44px;margin:-22px 0 0 -22px;border-radius:50%;border:3px solid #ffd24f;z-index:2147483646;pointer-events:none;animation:__r .55s ease-out forwards}
  @keyframes __r{from{transform:scale(.3);opacity:1}to{transform:scale(1.4);opacity:0}}
  #__slide{position:fixed;inset:0;z-index:2147483600;display:flex;align-items:center;justify-content:center;background:rgba(10,12,16,.975);color:#e8eaed;font-family:Inter,Segoe UI,Arial,sans-serif;opacity:0;transition:opacity .6s}
  #__slide.on{opacity:1}
  #__cap{position:fixed;left:50%;bottom:28px;transform:translateX(-50%);z-index:2147483500;background:rgba(10,12,16,.88);color:#fff;font:600 24px Inter,Arial,sans-serif;padding:10px 22px;border-radius:10px;border-left:5px solid #c58cff;opacity:0;transition:opacity .4s;pointer-events:none}
  #__cap.on{opacity:1}`;
  document.head.appendChild(st);
  const c = document.createElement('div'); c.id='__cur';
  c.innerHTML = '<svg viewBox="0 0 24 24" width="28" height="28"><path d="M3 2l7 19 2.6-7.6L20 11z" fill="#fff" stroke="#000" stroke-width="1.6" stroke-linejoin="round"/></svg>';
  document.body.appendChild(c);
  const cap = document.createElement('div'); cap.id='__cap'; document.body.appendChild(cap);
  addEventListener('mousemove', e => { c.style.left=e.clientX+'px'; c.style.top=e.clientY+'px'; }, true);
  addEventListener('mousedown', e => { const r=document.createElement('div'); r.className='__rip'; r.style.left=e.clientX+'px'; r.style.top=e.clientY+'px'; document.body.appendChild(r); setTimeout(()=>r.remove(),600); }, true);
  window.__caption = (t) => { cap.textContent = t || ''; cap.classList.toggle('on', !!t); };
  window.__slide = (html) => {
    let s = document.getElementById('__slide');
    if (!html) { if (s) { s.classList.remove('on'); setTimeout(()=>s.remove(), 700); } return; }
    if (!s) { s = document.createElement('div'); s.id='__slide'; document.body.appendChild(s); }
    s.innerHTML = html; requestAnimationFrame(()=>requestAnimationFrame(()=>s.classList.add('on')));
  };
});
"""

TITULO = """<div style="text-align:center">
<div style="font-size:22px;letter-spacing:6px;color:#c58cff;text-transform:uppercase">Tesis · UTEC</div>
<div style="font-size:76px;font-weight:800;margin:18px 0">Segmentador de videos por temas</div>
<div style="font-size:30px;color:#9aa0a6">Persona · Claude Opus · Codex · CAVA</div>
<div style="margin-top:40px;display:flex;gap:14px;justify-content:center">
<span style="width:120px;height:14px;border-radius:7px;background:#ffd24f"></span>
<span style="width:120px;height:14px;border-radius:7px;background:#c58cff"></span>
<span style="width:120px;height:14px;border-radius:7px;background:#4fd1c5"></span>
<span style="width:120px;height:14px;border-radius:7px;background:#ff8c69"></span></div></div>"""

def barra(pct, color, label):
    return f"""<div style="display:flex;align-items:center;gap:14px;margin:9px 0"><div style="width:220px;text-align:right;font-size:22px;color:#c9ccd1">{label}</div>
<div style="width:430px;height:30px;background:#23262d;border-radius:6px;overflow:hidden"><div style="width:{pct}%;height:100%;background:{color}"></div></div>
<div style="width:90px;font-size:24px;font-weight:700">{pct}%</div></div>"""

def resultados(titulo, filas, recall, f1, nota):
    tabla = "".join(f"<tr><td style='padding:10px 26px'><b style='color:{c}'>{n}</b></td><td style='padding:10px 26px'>{m}</td><td style='padding:10px 26px;text-align:center'>{s}</td><td style='padding:10px 26px;text-align:center'>{d}</td></tr>" for n,c,m,s,d in filas)
    barras = "".join(barra(p, c, l) for l, p, c in recall)
    return f"""<div style="width:1640px">
<div style="font-size:22px;letter-spacing:5px;color:#c58cff;text-transform:uppercase">Resultados</div>
<div style="font-size:54px;font-weight:800;margin:6px 0 26px">{titulo}</div>
<div style="display:flex;gap:50px;align-items:flex-start">
<div><table style="border-collapse:collapse;font-size:24px;background:#16191f;border-radius:12px;white-space:nowrap">
<tr style="color:#8a9099;font-size:19px"><td style='padding:12px 26px'>Fuente</td><td style='padding:12px 26px'>Modelo</td><td style='padding:12px 26px'>Segmentos</td><td style='padding:12px 26px'>Dur. media</td></tr>{tabla}</table>
<div style="margin-top:30px;font-size:26px;white-space:nowrap">Coincidencia Codex vs Claude (±15 s): <b style="color:#4fd1c5;font-size:40px">F1 {f1}</b></div></div>
<div><div style="font-size:24px;color:#9aa0a6;margin-bottom:10px">Recall sobre los cortes de Claude</div>{barras}
<div style="font-size:19px;color:#8a9099;margin-top:16px;max-width:900px">{nota}</div></div></div></div>"""

RES_END = resultados("Avengers: Endgame (2019) · 3:02:06",
    [("Claude","#c58cff","Opus","45","4:02"),("Codex","#4fd1c5","gpt-6.1-sol","41","4:25"),("CAVA","#ff8c69","CAVA film","349","0:31")],
    [("Codex", 66, "#4fd1c5"), ("CAVA", 86, "#ff8c69"), ("Azar (348 cortes)", 62, "#5f6368")], "0.69",
    "Azar = misma cantidad de cortes que CAVA, ubicados al azar. Análisis de cada modelo ≈ 1 minuto, solo con la transcripción.")
RES_SPI = resultados("Spider-Man: Brand New Day (2026) · 2:25:01",
    [("Claude","#c58cff","Opus","34","4:16"),("Codex","#4fd1c5","gpt-6.1-sol","29","5:00"),("CAVA","#ff8c69","CAVA film","287","0:30")],
    [("Codex", 45, "#4fd1c5"), ("CAVA", 79, "#ff8c69"), ("Azar (286 cortes)", 62, "#5f6368")], "0.49",
    "Tolerancia ±15 s. CAVA, al ser mucho más fino, tiene alto recall pero baja precisión (≈9 %).")
CIERRE = """<div style="text-align:center;max-width:1300px">
<div style="font-size:60px;font-weight:800;margin-bottom:30px">Solo con la transcripción…</div>
<div style="font-size:32px;line-height:1.6;color:#c9ccd1">los modelos de lenguaje producen segmentaciones temáticas coherentes,<br>y el segmentador permite <b style="color:#ffd24f">verlas</b>, <b style="color:#c58cff">compararlas</b>, <b style="color:#4fd1c5">corregirlas</b> y <b style="color:#ff8c69">exportar los clips</b>.</div></div>"""

async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(channel="chrome", headless=True, args=["--autoplay-policy=no-user-gesture-required"])
        ctx = await b.new_context(viewport={"width":1920,"height":1080})
        await ctx.add_init_script(CURSOR_JS)
        pg = await ctx.new_page()
        cdp = await ctx.new_cdp_session(pg)
        await pg.goto(URL); await pg.wait_for_timeout(2500)
        # precarga: abrir el video de YouTube primero
        await pg.click("#videos .vid:has-text('split flap')"); await pg.wait_for_timeout(2500)
        await pg.evaluate("document.getElementById('video').muted = true")
        await pg.evaluate("window.__slide(arguments[0])" if False else f"window.__slide({json.dumps(TITULO)})")
        await pg.wait_for_timeout(900)

        def on_frame(ev):
            frames.append((ev["metadata"]["timestamp"], ev["data"]))
            asyncio.ensure_future(cdp.send("Page.screencastFrameAck", {"sessionId": ev["sessionId"]}))
        cdp.on("Page.screencastFrame", on_frame)
        await cdp.send("Page.startScreencast", {"format":"jpeg","quality":88,"maxWidth":1920,"maxHeight":1080,"everyNthFrame":1})
        t0 = time.time()
        # forzar repintado continuo para que haya frames aunque la pantalla esté quieta
        await pg.evaluate("""(()=>{const d=document.createElement('div');d.style.cssText='position:fixed;right:0;bottom:0;width:1px;height:1px;z-index:2147483647;pointer-events:none';document.body.appendChild(d);let i=0;(function f(){d.style.background=(i++%2)?'rgba(0,0,0,.01)':'rgba(0,0,0,.02)';requestAnimationFrame(f)})()})()""")

        pos = [960, 540]
        async def mover(x, y, ms=700):
            n = max(8, ms // 16)
            x0, y0 = pos
            for i in range(1, n + 1):
                k = i / n; k = k * k * (3 - 2 * k)
                await pg.mouse.move(x0 + (x - x0) * k, y0 + (y - y0) * k)
                await asyncio.sleep(ms / 1000 / n)
            pos[:] = [x, y]
        async def caja(sel):
            return await pg.locator(sel).first.bounding_box()
        async def ir(sel, fx=.5, fy=.5, ms=700):
            bb = await caja(sel)
            await mover(bb["x"] + bb["width"] * fx, bb["y"] + bb["height"] * fy, ms)
            return bb
        async def clic(sel=None, fx=.5, fy=.5, ms=700):
            if sel: await ir(sel, fx, fy, ms)
            await pg.mouse.down(); await asyncio.sleep(.08); await pg.mouse.up()
        async def esperar(s): await asyncio.sleep(s)
        async def cap(t): await pg.evaluate(f"window.__caption({json.dumps(t)})")

        async def escena(nombre, acciones, extra=0.8):
            ini = time.time()
            escenas.append((nombre, ini - t0))
            await acciones()
            resto = DUR[nombre] + extra - (time.time() - ini)
            if resto > 0: await asyncio.sleep(resto)

        async def s_intro():
            await mover(960, 700, 1200); await esperar(DUR["intro"] - 2.0)
            await pg.evaluate("window.__slide(null)")
        async def s_lista():
            await cap("Biblioteca de videos")
            await ir("#urlNueva", .4, .5, 900); await esperar(1.6)
            await ir("#videos .vid:nth-child(2)", .5, .5, 600); await esperar(.4)
            await ir("#videos .vid:nth-child(5)", .5, .5, 600); await esperar(.4)
            await ir("#videos .vid:has-text('Endgame')", .5, .4, 800); await esperar(1.6)
            await ir("#videos .vid:has-text('Spider-Man')", .5, .4, 700); await esperar(1.2)
            await ir("#videos .vid:has-text('split flap')", .5, .4, 900)
        async def s_franjas():
            await cap("El selector: línea de tiempo con franjas")
            await clic("#videos .vid:has-text('split flap')", .5, .4, 300)
            await pg.evaluate("document.getElementById('video').currentTime = 40; document.getElementById('video').play()")
            await esperar(2.5)
            await ir("#capitulos", .1, .5, 1000); await mover(pos[0] + 900, pos[1], 2200); await esperar(1.0)
            await ir("#sugIA", .9, .5, 700); await mover(pos[0] - 1000, pos[1], 2400); await esperar(.8)
            await ir("#sugCodex", .1, .5, 600); await mover(pos[0] + 1000, pos[1], 2400); await esperar(1.5)
            await ir("#timeline", .5, .5, 900)
        async def s_hover():
            await cap("Hover: tema, rango, resumen y razón del corte")
            await ir("#sugIA .guiab:nth-child(3)", .5, .5, 900); await esperar(3.2)
            await ir("#sugIA .guiab:nth-child(5)", .5, .5, 700); await esperar(3.0)
            await clic("#sugIA .guiab:nth-child(5)", .5, .5, 200); await esperar(1)
        async def s_manual():
            await cap("Segmentar a mano:  I = inicio · O = fin")
            await clic("#timeline", .03, .5, 900)
            await pg.evaluate("document.getElementById('video').currentTime = 0")
            await esperar(.8); await pg.keyboard.press("i"); await esperar(1.6)
            await clic("#timeline", .028 + .0, .5, 400)
            await pg.evaluate("document.getElementById('video').currentTime = 37")
            await esperar(.6); await pg.keyboard.press("o"); await esperar(1.0)
            await pg.keyboard.press("Control+a")
            await pg.keyboard.type("Introducción: el split-flap", delay=70); await pg.keyboard.press("Enter")
            await esperar(.5)
            await ir("#filas tr", .3, .5, 900)
        async def s_tabla():
            await cap("Cortes sugeridos por cada fuente")
            await pg.evaluate("document.getElementById('sugFilas').closest('table').scrollIntoView({behavior:'smooth', block:'center'})")
            await esperar(1.2)
            await clic(".fuente[data-f=codex]", .5, .5, 800); await esperar(1.6)
            await clic(".fuente[data-f=creador]", .5, .5, 600); await esperar(1.4)
            await clic(".fuente[data-f=ia]", .5, .5, 600); await esperar(.6)
            await ir("#sugFilas tr:nth-child(2) [data-a=add]", .5, .5, 900)
        async def s_pelicula():
            await cap("Películas: Avengers Endgame (3 h)")
            await pg.evaluate("document.querySelector('.reproductor').scrollIntoView({behavior:'smooth', block:'start'})")
            await esperar(1.0)
            await clic("#videos .vid:has-text('Endgame')", .5, .4, 900)
            await esperar(2.2)
            await pg.evaluate("document.getElementById('video').currentTime = 5200; document.getElementById('video').play()")
            await ir("#sugCava", .05, .5, 900); await mover(pos[0] + 1400, pos[1], 3500)
        async def s_capas():
            await cap("Capas CAVA: hover resalta todo el tópico")
            await ir("#pistas .capa >> nth=0", .3, .5, 900)
            for fx in (.31, .45, .62, .78):
                await ir(f"#pistas .capa >> nth=0", fx, .5, 700); await esperar(1.1)
            await ir("#pistas .capa >> nth=4", .55, .5, 800); await esperar(1.6)
            await ir("#timeline", .55, .5, 700)
            await pg.keyboard.down("Control")
            for _ in range(6):
                await pg.mouse.wheel(0, -120); await esperar(.35)
            await pg.keyboard.up("Control"); await esperar(1.2)
            for _ in range(4):
                await pg.mouse.wheel(0, 200); await esperar(.3)
            await esperar(.6)
            await clic("#zAjustar", .5, .5, 800)
        async def s_recop():
            await cap("Recopilación: reproducir un tópico de corrido")
            await ir("#recSel", .4, .5, 900); await esperar(.4)
            opts = await pg.eval_on_selector("#recSel", "s => [...s.options].map(o=>o.value)")
            await pg.select_option("#recSel", opts[min(3, len(opts)-1)]); await esperar(.8)
            await clic("#recPlay", .5, .5, 700); await esperar(3.0)
            await clic("#recNext", .5, .5, 600); await esperar(1.5)
        async def s_res_end():
            await cap("")
            await clic("#recSalir", .5, .5, 500)
            await pg.evaluate("document.getElementById('video').pause()")
            await pg.evaluate(f"window.__slide({json.dumps(RES_END)})")
            await mover(1300, 900, 1500)
        async def s_res_spi():
            await pg.evaluate(f"window.__slide({json.dumps(RES_SPI)})")
        async def s_cierre():
            await pg.evaluate(f"window.__slide({json.dumps(CIERRE)})")

        await escena("intro", s_intro, 0.6)
        await escena("lista", s_lista)
        await escena("franjas", s_franjas)
        await escena("hover", s_hover)
        await escena("manual", s_manual)
        await escena("tabla", s_tabla)
        await escena("pelicula", s_pelicula)
        await escena("capas", s_capas)
        await escena("recop", s_recop)
        await escena("res_endgame", s_res_end, 1.2)
        await escena("res_spider", s_res_spi, 1.0)
        await escena("cierre", s_cierre, 2.0)
        await cdp.send("Page.stopScreencast")
        await b.close()

    # guardar frames
    lista = []
    for i, (ts, data) in enumerate(frames):
        fn = f"frames/{i:06d}.jpg"; open(fn, "wb").write(base64.b64decode(data)); lista.append((ts, fn))
    fin = t0 + sum(1 for _ in []) 
    with open("frames.txt", "w") as f:
        for i, (ts, fn) in enumerate(lista):
            nxt = lista[i + 1][0] if i + 1 < len(lista) else ts + 0.5
            f.write(f"file '{os.path.abspath(fn)}'\nduration {max(nxt - ts, 0.001):.4f}\n")
        f.write(f"file '{os.path.abspath(lista[-1][1])}'\n")
    primer = lista[0][0]
    json.dump({"offset_primer_frame": primer - t0, "escenas": escenas}, open("escenas.json", "w"), indent=1)
    print(len(lista), "frames;", escenas)

asyncio.run(main())
