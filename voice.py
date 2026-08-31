#!/usr/bin/env python3
"""
Голос для «Звуков и Блоков».

Синтезатор Android читает выдуманные слоги как аббревиатуры: `puh` он произносит
«пи-ю-эйч». Нейронный голос Microsoft читает их как слоги — то, что и нужно.
Поэтому звуки и слова синтезируются один раз здесь, кладутся в mp3 и зашиваются
в index.html как data:-ссылки. Приложение остаётся одним файлом без сети и сборки:
`Sound.file()` в блоке 2 и так предпочитает запись синтезатору.

    pip install edge-tts

    python voice.py sounds     # 52 звука   -> audio/phonemes/
    python voice.py words      # слова      -> audio/words/
    python voice.py embed      # зашить всё, что есть в audio/, в index.html
    python voice.py            # всё сразу

Голос — en-US-AnaNeural, детский: восьмилетнему он ближе взрослого диктора.
Если какой-то звук на слух вышел неправильным, поправь строку в SOUND_TEXT,
удали его mp3 и прогони заново — перезапишется только он.

Про тишину. edge-tts возвращает mp3 с длинным хвостом: «puh» занимает полсекунды,
а файл длится полторы. Слияние s—a—t из-за этого растягивалось на шесть секунд
пустоты. Обрезать нечем — ffmpeg в системе нет, — но edge-tts вместе со звуком
отдаёт события WordBoundary с точным началом и концом речи. Их и записываем
рядом с файлом, а приложение по ним обрывает воспроизведение.
"""

import asyncio, base64, json, re, sys, pathlib

VOICE = "en-US-AnaNeural"
RATE_SOUND = "-10%"
RATE_WORD  = "-15%"          # слово читаем медленнее звука: его надо разобрать
ROOT   = pathlib.Path(__file__).parent
INDEX  = ROOT / "index.html"

HEAD_PAD = 0.03              # запас перед речью, чтобы не срезать атаку согласной
TAIL_PAD = 0.12              # и после: у /s/ и /f/ хвост тише порога, но он нужен

# ---------------------------------------------------------------- как звучит

# Пары «звук → что произнести». Взято из таблицы SAY в index.html, но живёт
# отдельно: там строки для синтезатора телефона, здесь — для нейронного голоса,
# и правки одному не должны ломать другой.
SOUND_TEXT = {
    "s":"sss", "a":"ah",   "t":"tuh", "i":"ih",  "p":"puh", "n":"nnn",
    "c":"kuh", "k":"kuh",  "e":"eh",  "h":"huh", "r":"rrr", "m":"mmm", "d":"duh",
    "g":"guh", "o":"awh",  "u":"uh",  "l":"lll", "f":"fff", "b":"buh",
    "j":"juh", "z":"zzz",  "w":"wuh", "v":"vvv", "y":"yuh", "x":"ks",
    "ai":"ay", "oa":"oh",  "ie":"eye","ee":"ee", "or":"or", "oo":"oo", "ng":"ng",
    "ch":"chuh","sh":"shh","th":"thuh",
    "qu":"kwuh","ou":"ow", "oi":"oy", "ue":"you","er":"er", "ar":"ar",
    "a_e":"ay","i_e":"eye","o_e":"oh","u_e":"you","e_e":"ee",
    "oo2":"uu",
    "ck":"kuh","ss":"sss", "ll":"lll","ff":"fff","gg":"guh",
}

# ------------------------------------------------------- что вытащить из кода

def read_index():
    return INDEX.read_text(encoding="utf-8")

def words_from_index(src):
    """Слова групп и слова-невидимки — ровно те, что приложение умеет озвучить."""
    out = []
    for block in (r"const GROUPS = \[(.*?)\n\];", r"const TRICKY = \[(.*?)\n\];"):
        m = re.search(block, src, re.S)
        if m:
            out += re.findall(r"\{\s*w:'([a-zA-Z']+)'", m.group(1))
    seen, uniq = set(), []
    for w in out:
        if w not in seen:
            seen.add(w); uniq.append(w)
    return uniq

# ------------------------------------------------------------------ синтез

async def synth(text, path, rate):
    """Пишет mp3 и возвращает [начало, конец] речи в секундах — или None."""
    import edge_tts
    audio, marks = b"", []
    async for chunk in edge_tts.Communicate(text, VOICE, rate=rate).stream():
        if chunk["type"] == "audio":
            audio += chunk["data"]
        elif chunk["type"] == "WordBoundary":
            marks.append((chunk["offset"], chunk["duration"]))
    if not audio:
        raise RuntimeError("пустой ответ")
    path.write_bytes(audio)
    if not marks:
        return None
    start = max(0.0, marks[0][0] / 1e7 - HEAD_PAD)
    end   = (marks[-1][0] + marks[-1][1]) / 1e7 + TAIL_PAD
    return [round(start, 3), round(end, 3)]

def marks_path(folder):
    return folder / "_marks.json"

def load_marks(folder):
    p = marks_path(folder)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}

async def make(jobs, folder, rate):
    """jobs: [(имя файла без расширения, что произнести)]"""
    folder.mkdir(parents=True, exist_ok=True)
    marks = load_marks(folder)
    done = skip = 0
    for name, text in jobs:
        p = folder / f"{name}.mp3"
        if p.exists() and p.stat().st_size > 0 and name in marks:
            skip += 1
            continue
        try:
            cut = await synth(text, p, rate)
            if cut:
                marks[name] = cut
            done += 1
            print(f"  {name:8} <- «{text}»  {p.stat().st_size} б  речь {cut}", flush=True)
        except Exception as e:
            print(f"  !! {name}: {e}", flush=True)
    marks_path(folder).write_text(json.dumps(marks, indent=0, sort_keys=True),
                                 encoding="utf-8")
    print(f"готово: новых {done}, уже было {skip}, всего {len(jobs)}")

# ------------------------------------------------------------------ вшивание

START = "/* ---- AUDIO-EMBED-START (пишет voice.py, руками не трогать) ---- */"
END   = "/* ---- AUDIO-EMBED-END ---- */"

def embed():
    src = read_index()
    if START not in src or END not in src:
        sys.exit("В index.html нет маркеров AUDIO-EMBED — вставь их в блок 1 рядом с AUDIO.")

    lines, total, cuts = [], 0, 0
    for kind, folder in (("ph", ROOT/"audio"/"phonemes"), ("word", ROOT/"audio"/"words")):
        if not folder.is_dir():
            continue
        marks = load_marks(folder)
        for p in sorted(folder.glob("*.mp3")):
            if not p.stat().st_size:
                continue
            b64 = base64.b64encode(p.read_bytes()).decode()
            key = f"{kind}:{p.stem}"
            lines.append(f"AUDIO['{key}']='data:audio/mpeg;base64,{b64}';")
            if p.stem in marks:
                a, b = marks[p.stem]
                lines.append(f"AUDIO_CUT['{key}']=[{a},{b}];")
                cuts += 1
            total += p.stat().st_size

    body = "\n".join(lines) if lines else "/* пока пусто: запусти python voice.py */"
    i, j = src.index(START), src.index(END)
    INDEX.write_text(src[:i] + START + "\n" + body + "\n" + src[j:],
                     encoding="utf-8", newline="")
    print(f"вшито записей: {cuts} с обрезкой из {len(lines)-cuts}, "
          f"звука {total/1024:.0f} КБ, index.html теперь {INDEX.stat().st_size/1024:.0f} КБ")

# -------------------------------------------------------------------- запуск

def main():
    what = sys.argv[1] if len(sys.argv) > 1 else "all"

    if what in ("sounds", "all"):
        print("ЗВУКИ")
        asyncio.run(make(sorted(SOUND_TEXT.items()), ROOT/"audio"/"phonemes", RATE_SOUND))

    if what in ("words", "all"):
        ws = words_from_index(read_index())
        print(f"СЛОВА ({len(ws)})")
        asyncio.run(make([(w, w) for w in ws], ROOT/"audio"/"words", RATE_WORD))

    if what in ("embed", "all"):
        print("ВШИВАЕМ")
        embed()

if __name__ == "__main__":
    main()
