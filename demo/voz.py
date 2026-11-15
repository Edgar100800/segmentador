import asyncio, json, subprocess, edge_tts
g = json.load(open("guion.json"))
async def main():
    for k, t in g.items():
        await edge_tts.Communicate(t, "es-PE-CamilaNeural", rate="+4%").save(f"voz/{k}.mp3")
asyncio.run(main())
dur = {}
for k in g:
    r = subprocess.run(["ffprobe","-v","error","-show_entries","format=duration","-of","csv=p=0",f"voz/{k}.mp3"],capture_output=True,text=True)
    dur[k] = float(r.stdout)
json.dump(dur, open("duraciones.json","w"), indent=1); print(dur, sum(dur.values()))
