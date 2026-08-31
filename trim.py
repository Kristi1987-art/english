#!/usr/bin/env python3
"""
Границы речи в записях — измеряются браузером, один раз.

edge-tts кладёт в mp3 длинный хвост тишины: «puh» звучит полсекунды, а файл идёт
полторы. Его собственные метки речи включают эту тишину, то есть бесполезны.
Обрезать mp3 нечем: ffmpeg в системе нет, numpy тоже.

Зато декодер звука есть в любом браузере. Скрипт раскладывает записи по нескольким
маленьким html-страницам (целиком они в предпросмотр не влезают), каждая умеет
декодировать свои записи через Web Audio и вернуть, где в них громче порога.
Числа кладутся в audio/phonemes/_marks.json, откуда их забирает voice.py embed.

    python trim.py pages     # разложить записи по страницам _trim1.html…
    python trim.py save '<json>'   # сохранить измеренное
    python trim.py clean     # убрать страницы
"""

import base64, json, pathlib, sys

ROOT   = pathlib.Path(__file__).parent
FOLDER = ROOT / "audio" / "phonemes"
PER    = 14                       # записей на страницу

PAGE = """<meta charset="utf-8"><title>trim</title>
<body style="font:14px monospace;padding:12px">измеряю…</body>
<script>
const CLIPS = %s;

/* Где в записи речь: первый и последний отсчёт громче порога.
   Порог низкий — у /s/ и /f/ хвост тихий, но он часть звука. */
async function measure(){
  const ctx = new (window.AudioContext||window.webkitAudioContext)();
  const out = {};
  for(const [key, uri] of Object.entries(CLIPS)){
    const bytes = Uint8Array.from(atob(uri.split(',')[1]), c => c.charCodeAt(0));
    const buf   = await ctx.decodeAudioData(bytes.buffer);
    const d     = buf.getChannelData(0);
    const win   = Math.round(buf.sampleRate * 0.01);        /* окно 10 мс */
    const loud  = [];
    for(let i = 0; i < d.length; i += win){
      let peak = 0;
      for(let j = i; j < Math.min(i + win, d.length); j++){
        const v = Math.abs(d[j]); if(v > peak) peak = v;
      }
      loud.push(peak);
    }
    const TH = 0.012;
    let a = loud.findIndex(v => v > TH);
    let b = loud.length - 1 - [...loud].reverse().findIndex(v => v > TH);
    if(a < 0){ out[key] = null; continue; }
    const start = Math.max(0, a * 0.01 - 0.03);
    const end   = Math.min(buf.duration, (b + 1) * 0.01 + 0.10);
    out[key] = [+start.toFixed(3), +end.toFixed(3), +buf.duration.toFixed(3)];
  }
  document.body.textContent = JSON.stringify(out);
  return out;
}
</script>
"""

def pages():
    clips = sorted(p for p in FOLDER.glob("*.mp3") if p.stat().st_size)
    made = []
    for n in range(0, len(clips), PER):
        part = clips[n:n+PER]
        data = {p.stem: "data:audio/mpeg;base64," + base64.b64encode(p.read_bytes()).decode()
                for p in part}
        f = ROOT / f"_trim{n//PER + 1}.html"
        f.write_text(PAGE % json.dumps(data), encoding="utf-8")
        made.append(f.name)
    print(f"записей {len(clips)}, страниц {len(made)}: {' '.join(made)}")

def save(blob):
    got = json.loads(blob)
    marks_file = FOLDER / "_marks.json"
    marks = json.loads(marks_file.read_text(encoding="utf-8")) if marks_file.exists() else {}
    kept = 0
    for k, v in got.items():
        if not v:
            continue
        start, end, full = v
        marks[k] = [start, end]
        kept += 1
    marks_file.write_text(json.dumps(marks, indent=0, sort_keys=True), encoding="utf-8")
    print(f"сохранено границ: {kept}, всего в файле {len(marks)}")

def clean():
    for f in ROOT.glob("_trim*.html"):
        f.unlink()
    print("страницы убраны")

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "pages"
    if cmd == "pages": pages()
    elif cmd == "save": save(sys.argv[2])
    elif cmd == "clean": clean()
