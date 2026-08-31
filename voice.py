#!/usr/bin/env python3
"""
Голос для «Звуков и Блоков».

Синтезатор Android читает выдуманные слоги как аббревиатуры: `puh` он произносит
«пи-ю-эйч». Нейронный голос Microsoft читает их как слоги — то, что и нужно.
Поэтому звуки и слова синтезируются один раз здесь, кладутся в mp3 и зашиваются
в index.html как data:-ссылки. Приложение остаётся одним файлом без сети и сборки:
`Sound.file()` в блоке 2 и так предпочитает запись синтезатору.

    pip install edge-tts

    python voice.py sounds     # 52 звука      -> audio/phonemes/
    python voice.py words      # слова         -> audio/words/
    python voice.py record     # живой голос   -> audio/phonemes_home/
    python voice.py embed      # зашить всё, что есть в audio/, в index.html
    python voice.py            # синтез и вшивание

Голос — en-US-AnaNeural, детский: восьмилетнему он ближе взрослого диктора.
Если какой-то звук на слух вышел неправильным, поправь строку в SOUND_TEXT,
удали его mp3 и прогони заново — перезапишется только он.

Про тишину. edge-tts возвращает mp3 с длинным хвостом: «puh» занимает полсекунды,
а файл длится полторы. Слияние s—a—t из-за этого растягивалось на шесть секунд
пустоты. Обрезать нечем — ffmpeg в системе нет, — но edge-tts вместе со звуком
отдаёт события WordBoundary с точным началом и концом речи. Их и записываем
рядом с файлом, а приложение по ним обрывает воспроизведение.

Про предел синтеза. Тянущиеся звуки нейронному голосу не даются вовсе: «sss» он
читает как три отдельных «с», а не как одно долгое /s/, и правкой текста это не
лечится — движок читает слоги и не умеет фонемы. Поэтому есть `record`: человек
наговаривает звуки в микрофон, страница сама обрезает тишину и ровняет громкость,
записи ложатся в audio/phonemes_home/ и при вшивании перебивают синтез.
"""

import asyncio, base64, json, os, re, sys, pathlib

VOICE = "en-US-AnaNeural"
RATE_SOUND = "-10%"
RATE_WORD  = "-15%"          # слово читаем медленнее звука: его надо разобрать
ROOT   = pathlib.Path(__file__).parent
INDEX  = ROOT / "index.html"
SYNTH_DIR = ROOT / "audio" / "phonemes"        # что наговорил синтезатор
HOME_DIR  = ROOT / "audio" / "phonemes_home"   # что наговорил живой человек

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

# Как произнести звук голосом. Главная ошибка взрослого — добавить гласную:
# сказать «пы» вместо /p/. Ребёнок потом читает pin как «пы-и-нн», и слово не
# складывается. Вторая ошибка — раздробить тянущийся звук: /s/ должно быть одним
# долгим шипением, а не тремя короткими «с».
HOW = {
 "s":  "Тяни одно долгое шипение: ссссс, секунду. Не «с-с-с» тремя толчками.",
 "ss": "То же, что s: одно долгое ссссс.",
 "a":  "Коротко и широко, рот как перед укусом: /æ/ в cat. Между «э» и «а».",
 "t":  "Один щелчок языка о нёбо и сразу тишина. Не «ты» и не «тэ».",
 "i":  "Коротко, будто торопишься: /ɪ/ в sit. Не длинное «и».",
 "p":  "Хлопок губами, почти без голоса. Не «пы».",
 "n":  "Тяни ннннн через нос, секунду.",
 "c":  "Короткий удар в горле: /k/. Без гласной на конце.",
 "k":  "То же, что c: короткое /k/, без «ы».",
 "ck": "То же, что k: одно короткое /k/, хотя букв две.",
 "e":  "Коротко, рот чуть приоткрыт: /e/ в pen.",
 "h":  "Короткий выдох на ладонь, без голоса. Не «ха».",
 "r":  "Тяни английское рррр: язык загнут назад и нёба не касается. Не раскатистое русское.",
 "m":  "Тяни ммммм с закрытыми губами, секунду.",
 "d":  "Один удар языка о нёбо, с голосом. Не «ды».",
 "g":  "Короткий удар в горле с голосом. Не «гы».",
 "gg": "То же, что g: одно короткое /g/.",
 "o":  "Коротко, губы округлить: /ɒ/ в dog.",
 "u":  "Коротко, ближе к русскому «а»: /ʌ/ в cup.",
 "l":  "Тяни лллл, кончик языка за верхними зубами.",
 "ll": "То же, что l: одно долгое лллл.",
 "f":  "Тяни фффф: верхние зубы на нижней губе, воздух без голоса.",
 "ff": "То же, что f: одно долгое фффф.",
 "b":  "Хлопок губами с голосом. Не «бы».",
 "j":  "Коротко /dʒ/, как первый звук в jam. Не «джы».",
 "z":  "Тяни зззз, как жужжание, секунду.",
 "w":  "Губы трубочкой и разжать: /w/ в win. Не русское «в».",
 "v":  "Тяни вввв: зубы на нижней губе, с голосом.",
 "y":  "Коротко /j/, первый звук в yes.",
 "x":  "Два звука слитно, одним движением: кс, как конец box.",
 "ai": "Тяни «эй» одним звуком: /eɪ/ в rain.",
 "oa": "Тяни «оу» одним звуком: /əʊ/ в boat.",
 "ie": "Тяни «ай» одним звуком: /aɪ/ в pie.",
 "ee": "Тяни длинное «и»: /iː/ в see.",
 "or": "Тяни «оо» с округлыми губами: /ɔː/ в fork.",
 "oo": "Тяни длинное «у»: /uː/ в moon.",
 "oo2":"Короткое «у», быстро: /ʊ/ в book. Долготы здесь нет.",
 "ng": "Тяни носом /ŋ/ из song: язык поднят сзади. Без «г» на конце.",
 "ch": "Коротко «ч», как начало chips. Не «чы».",
 "sh": "Тяни шшшш, как «тише», секунду.",
 "th": "Кончик языка между зубами, тяни воздух: /θ/ в three. Не «с» и не «з».",
 "qu": "Слитно /kw/, одним движением: начало queen.",
 "ou": "Тяни «ау» одним звуком: /aʊ/ в cloud.",
 "oi": "Тяни «ой» одним звуком: /ɔɪ/ в coin.",
 "ue": "Тяни «ю»: /juː/ в blue.",
 "er": "Тяни неясное «ё» без «й»: /ɜː/ в sister.",
 "ar": "Тяни длинное открытое «а»: /ɑː/ в car.",
 "a_e":"Как ai — тяни «эй». Это a с немой e: make.",
 "i_e":"Как ie — тяни «ай»: like.",
 "o_e":"Как oa — тяни «оу»: nose.",
 "u_e":"Как ue — тяни «ю»: cube.",
 "e_e":"Как ee — тяни длинное «и»: these.",
}

# Сколько звук должен длиться. Не придирка: слияние проигрывает звуки подряд,
# и секундный /t/ растягивает трёхзвуковое слово на четыре секунды — ребёнок
# успевает забыть начало. А ещё длина выдаёт главную ошибку: взрывной звук
# физически не может тянуться, и если /t/ идёт секунду, значит к нему приписали
# гласную и получилось «ту».
KIND = {
 "взрывной":        (0.08, 0.30, "p b t d c k g ck gg"),
 "тянущийся":       (0.35, 0.90, "s ss f ff m n ng l ll r z sh th v"),
 "выдох":           (0.12, 0.45, "h"),
 "слитный":         (0.12, 0.45, "ch j x qu"),
 "короткий гласный":(0.15, 0.45, "a e i o u oo2"),
 "скольжение":      (0.15, 0.50, "w y"),
 "долгий гласный":  (0.30, 0.85, "ai oa ie ee or oo er ar ou oi ue "
                                 "a_e i_e o_e u_e e_e"),
}
KIND_OF = {k: (name, lo, hi)
           for name, (lo, hi, keys) in KIND.items() for k in keys.split()}

# Два знака — один звук, поэтому запись должна быть той же длины, что у одиночного.
# Если ll вдвое длиннее l, значит его сказали дважды.
SAME = {"ss":"s", "ff":"f", "ll":"l", "gg":"g", "ck":"k", "c":"k"}

# Сколько кусков звука допустимо. Обычный звук один, слитные — стоп плюс шипение.
PARTS = {"ch":2, "j":2, "x":2, "qu":2}

# Для звуков, у которых нет отдельной карточки в GROUPS, — запись и пример.
EXTRA = {
 "ck": ("/k/", "pick"), "ss": ("/s/", "glass"), "ll": ("/l/", "doll"),
 "ff": ("/f/", "off"),  "gg": ("/g/", "egg"),   "oo2": ("/ʊ/", "book"),
 "k":  ("/k/", "key"),  "e_e": ("/iː/", "these"),
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

def letters_from_index(src):
    """Порядок звуков и примеры к ним — прямо из карточек букв, чтобы страница
       записи и приложение не разъезжались."""
    m = re.search(r"const GROUPS = \[(.*?)\n\];", src, re.S)
    found = re.findall(r"\{\s*l:'([a-z_0-9]+)',\s*ipa:'([^']*)',\s*word:'([a-z]+)',\s*ru:'([^']*)'",
                       m.group(1) if m else "")
    known = {l: (ipa, word, ru) for l, ipa, word, ru in found}
    order = [l for l, _, _, _ in found]
    for k in SOUND_TEXT:                       # ck, ss, ll, ff, gg, oo2 — в конец
        if k not in known and k not in order:
            order.append(k)
    out = []
    for k in order:
        if k in known:
            ipa, word, ru = known[k]
        else:
            ipa, word = EXTRA.get(k, ("", ""))
            ru = ""
        kind, lo, hi = KIND_OF.get(k, ("звук", 0.1, 0.9))
        out.append({"k": k, "ipa": ipa, "word": word, "ru": ru,
                    "how": HOW.get(k, ""), "say": SOUND_TEXT.get(k, k),
                    "kind": kind, "lo": lo, "hi": hi, "parts": PARTS.get(k, 1)})
    return out

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

MIME = {".mp3":"audio/mpeg", ".wav":"audio/wav", ".webm":"audio/webm",
        ".m4a":"audio/mp4",  ".ogg":"audio/ogg"}

def collect(folder, kind, into):
    """Кладёт записи папки в общий словарь. Позже вызванная папка перебивает
       раньше вызванную: живой голос важнее синтезированного."""
    if not folder.is_dir():
        return 0
    marks, n = load_marks(folder), 0
    for p in sorted(folder.iterdir()):
        if p.suffix.lower() not in MIME or not p.stat().st_size:
            continue
        into[f"{kind}:{p.stem}"] = (p, marks.get(p.stem))
        n += 1
    return n

def embed():
    src = read_index()
    if START not in src or END not in src:
        sys.exit("В index.html нет маркеров AUDIO-EMBED — вставь их в блок 1 рядом с AUDIO.")

    clips = {}
    n_synth = collect(SYNTH_DIR, "ph", clips)
    n_home  = collect(HOME_DIR,  "ph", clips)          # позже — значит важнее
    collect(ROOT / "audio" / "words", "word", clips)

    lines, total, cuts = [], 0, 0
    for key in sorted(clips):
        p, cut = clips[key]
        b64 = base64.b64encode(p.read_bytes()).decode()
        lines.append(f"AUDIO['{key}']='data:{MIME[p.suffix.lower()]};base64,{b64}';")
        if cut:
            lines.append(f"AUDIO_CUT['{key}']=[{cut[0]},{cut[1]}];")
            cuts += 1
        total += p.stat().st_size

    body = "\n".join(lines) if lines else "/* пока пусто: запусти python voice.py */"
    i, j = src.index(START), src.index(END)
    INDEX.write_text(src[:i] + START + "\n" + body + "\n" + src[j:],
                     encoding="utf-8", newline="")
    msg = (f"вшито записей {len(clips)}: живым голосом {n_home}, синтезом {n_synth - n_home}, "
           f"с обрезкой {cuts}; звука {total/1024:.0f} КБ, "
           f"index.html теперь {INDEX.stat().st_size/1024:.0f} КБ")
    print(msg)
    return msg

# ------------------------------------------------------------ живой голос

PAGE = ROOT / "_record.html"

def save_takes(data):
    """data: {звук: 'data:audio/wav;base64,…'} — то, что записала страница.
       Тишину она обрезала и громкость выровняла сама, поэтому меток нет:
       файл начинается и кончается ровно там, где звук."""
    HOME_DIR.mkdir(parents=True, exist_ok=True)
    n = 0
    for key, uri in data.items():
        if key not in SOUND_TEXT or not isinstance(uri, str) or "," not in uri:
            continue
        head, b64 = uri.split(",", 1)
        ext = ".wav" if "wav" in head else ".webm"
        (HOME_DIR / f"{key}{ext}").write_bytes(base64.b64decode(b64))
        n += 1
    marks_path(HOME_DIR).write_text("{}", encoding="utf-8")
    msg = f"сохранено звуков: {n} -> audio/{HOME_DIR.name}/"
    print(msg)
    return msg

def build_page():
    letters = letters_from_index(read_index())
    have = {}
    if HOME_DIR.is_dir():
        for p in sorted(HOME_DIR.iterdir()):
            if p.suffix.lower() in MIME and p.stat().st_size:
                have[p.stem] = (f"data:{MIME[p.suffix.lower()]};base64,"
                                + base64.b64encode(p.read_bytes()).decode())
    synth, marks = {}, load_marks(SYNTH_DIR)
    if SYNTH_DIR.is_dir():
        for p in sorted(SYNTH_DIR.glob("*.mp3")):
            if p.stat().st_size:
                synth[p.stem] = ["data:audio/mpeg;base64,"
                                 + base64.b64encode(p.read_bytes()).decode(),
                                 marks.get(p.stem)]
    html = (RECORD_HTML
            .replace("__LETTERS__", json.dumps(letters, ensure_ascii=False))
            .replace("__HAVE__",    json.dumps(have))
            .replace("__SYNTH__",   json.dumps(synth)))
    PAGE.write_text(html, encoding="utf-8", newline="")
    return len(letters), len(have)

def record(port=8000):
    """Микрофон браузер даёт только на localhost или https — открыть файл
       двойным щелчком не выйдет, поэтому поднимаем свой сервер."""
    import http.server, webbrowser, threading
    total, done = build_page()
    os.chdir(ROOT)

    class Handler(http.server.SimpleHTTPRequestHandler):
        def answer(self, code, obj):
            b = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(n)
            try:
                if self.path == "/save":
                    msg = save_takes(json.loads(body))
                elif self.path == "/embed":
                    msg = embed()
                else:
                    raise ValueError("неизвестный адрес " + self.path)
                self.answer(200, {"ok": True, "msg": msg})
            except Exception as e:
                self.answer(500, {"ok": False, "msg": str(e)})

        def log_message(self, *a):
            pass

    # Поток на запрос обязателен: страница весит под мегабайт, браузер тянет её
    # несколькими соединениями сразу, и однопоточный сервер на этом встаёт.
    class Server(http.server.ThreadingHTTPServer):
        allow_reuse_address = True
        daemon_threads = True

    url = f"http://localhost:{port}/_record.html"
    print(f"звуков всего {total}, уже записано {done}", flush=True)
    print(f"открой {url}   (закончить — Ctrl+C)", flush=True)
    threading.Timer(0.7, lambda: webbrowser.open(url)).start()
    with Server(("127.0.0.1", port), Handler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nсервер остановлен")

def import_file(path):
    """Запасной путь: страницу открыли не с нашего сервера и она скачала файл."""
    return save_takes(json.loads(pathlib.Path(path).read_text(encoding="utf-8")))

# ------------------------------------------------------------ проверка записей

def measure(path):
    """Длительность и число кусков звука. Куском считаем участок громче четверти
       пика; куски, разделённые паузой короче 60 мс, — это один звук с провалом
       внутри, а не два."""
    import wave, array
    w = wave.open(str(path))
    n, sr = w.getnframes(), w.getframerate()
    a = array.array("h"); a.frombytes(w.readframes(n)); w.close()
    win = max(1, sr // 100)                       # окно 10 мс
    env = [max((abs(v) for v in a[i:i+win]), default=0) / 32768
           for i in range(0, len(a), win)]
    peak = max(env) if env else 0
    if peak <= 0:
        return n / sr, 0
    # Пауза короче 100 мс — это провал внутри звука, а не вторая попытка:
    # у взрывного перед выхлопом стоит смычка, у дифтонга есть перегиб.
    th, parts, gap, inside = peak * 0.25, 0, 0, False
    for e in env:
        if e > th:
            if not inside: parts += 1; inside = True
            gap = 0
        else:
            gap += 1
            if gap > 10: inside = False
    return n / sr, parts

def check():
    """Что не так с записями. Слышать это не нужно — длина и дробление ловят
       ровно те два дефекта, которые портят слияние: приписанную гласную
       и звук, сказанный дважды."""
    if not HOME_DIR.is_dir():
        print("живых записей нет — сделай python voice.py record"); return ""
    got = {p.stem: p for p in sorted(HOME_DIR.glob("*.wav"))}
    if not got:
        print("в audio/phonemes_home нет wav"); return ""

    order = [l["k"] for l in letters_from_index(read_index()) if l["k"] in got]
    seen = {k: measure(got[k]) for k in order}

    redo, meh = [], []
    print(f"{'звук':7}{'сек':>6}{'кусков':>8}  что не так")
    for key in order:
        sec, parts = seen[key]
        name, lo, hi = KIND_OF.get(key, ("звук", 0.1, 0.9))
        note, hard = [], False
        if sec > hi:
            note.append(f"длинно для «{name}», ждём до {hi:.2f}"
                        + (" — приписана гласная?" if name == "взрывной" else ""))
            hard = sec > hi * 1.35          # чуть за край — терпимо, вдвое — нет
        elif sec < lo:
            note.append(f"коротко для «{name}», ждём от {lo:.2f}")
            hard = sec < lo * 0.7
        if parts > PARTS.get(key, 1):
            note.append(f"разорван на {parts} — сказан дважды?")
            hard = True
        twin = SAME.get(key)
        if twin in seen and seen[twin][0] > 0:
            r = sec / seen[twin][0]
            if r > 1.8 or r < 0.55:
                note.append(f"тот же звук, что «{twin}», а длина в "
                            f"{max(r, 1/r):.1f} раза другая")
                hard = True
        if hard: redo.append(key)
        elif note: meh.append(key)
        mark = "!!" if hard else ("· " if note else "  ")
        print(f"{key:7}{sec:6.2f}{parts:8d} {mark}{'; '.join(note)}")

    msg = f"в норме {len(seen) - len(redo) - len(meh)} из {len(seen)}"
    if redo: msg += f"; перезаписать: {' '.join(redo)}"
    if meh:  msg += f"; на грани, можно оставить: {' '.join(meh)}"
    print(msg)
    return msg

# ------------------------------------------------------------ страница записи

# Отдельная страница, а не кусок приложения: микрофон нужен один раз в жизни
# проекта, и тащить его в index.html незачем. Всё, что она делает с записью —
# обрезать тишину, выровнять громкость и отдать wav, — делает браузер: ffmpeg
# в системе нет, а декодер и OfflineAudioContext есть везде.
RECORD_HTML = r"""<meta charset="utf-8">
<title>Мамин голос — запись звуков</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{ --ink:#2B2118; --dim:#6E6152; --paper:#FFFDF6; --line:#D9CFB6;
       --ok:#468A26; --hot:#B3341C; --sky:#8FC7EE; }
*{box-sizing:border-box}
body{margin:0;font:16px/1.5 system-ui,Segoe UI,sans-serif;color:var(--ink);
     background:var(--paper);padding:16px;max-width:760px;margin:0 auto}
h1{font-size:22px;margin:0 0 4px}
.lead{color:var(--dim);margin:0 0 14px;font-size:14px}
.lead b{color:var(--ink)}
.chips{display:flex;flex-wrap:wrap;gap:4px;margin-bottom:16px}
.chip{border:2px solid var(--line);background:#fff;padding:2px 6px;font:13px monospace;
      cursor:pointer;color:var(--dim)}
.chip.done{border-color:var(--ok);color:var(--ok);background:#F0F7EC}
.chip.warn{border-color:var(--hot);color:var(--hot);background:#FBEEEA}
.chip.now{border-color:var(--ink);color:var(--ink);font-weight:700}
.card{border:3px solid var(--ink);padding:18px;background:#fff}
.big{font-size:58px;font-weight:700;line-height:1;letter-spacing:2px}
.ipa{font-size:20px;color:var(--dim);margin-left:10px}
.ex{margin:6px 0 0;color:var(--dim)}
.how{margin:14px 0 0;padding:12px;background:#F5F0E1;border-left:5px solid var(--sky)}
.row{display:flex;flex-wrap:wrap;gap:8px;margin-top:16px}
button{font:15px/1 system-ui,sans-serif;padding:12px 14px;border:2px solid var(--ink);
       background:#fff;cursor:pointer}
button:disabled{opacity:.35;cursor:default}
.rec{background:var(--hot);color:#fff;border-color:var(--hot);font-weight:700;flex:1;
     min-width:220px;padding:16px;touch-action:none;user-select:none}
.rec.on{background:#7A2213;animation:pulse .7s infinite alternate}
@keyframes pulse{to{opacity:.6}}
.status{margin-top:12px;min-height:24px;font-size:14px;color:var(--dim)}
.status.bad{color:var(--hot)}
.status.good{color:var(--ok)}
footer{margin-top:22px;border-top:2px solid var(--line);padding-top:14px}
.count{font-size:14px;color:var(--dim);margin-bottom:10px}
.noise{border:2px dashed var(--line);padding:10px 12px;margin-bottom:14px}
.noise .row{margin-top:0;align-items:center}
.opt{font-size:14px;color:var(--dim);display:flex;align-items:center;gap:6px}
</style>
<body>
<h1>Мамин голос</h1>
<p class="lead">Держи кнопку — говори звук — отпусти. Страница сама отрежет тишину
и выровняет громкость. Главное: <b>не добавляй гласную</b> — /p/, а не «пы».
Микрофон в 10–15 см и чуть сбоку от рта, говори спокойно и не громко.</p>

<div class="noise">
  <div class="row">
    <button id="mkNoise">Измерить шум комнаты (2 с)</button>
    <label class="opt"><input type="checkbox" id="useNoise" checked> вычитать шум</label>
  </div>
  <div class="status" id="noiseStatus"></div>
</div>

<div class="chips" id="chips"></div>

<div class="card">
  <div><span class="big" id="letter"></span><span class="ipa" id="ipa"></span></div>
  <p class="ex" id="ex"></p>
  <div class="how" id="how"></div>
  <div class="row">
    <button class="rec" id="rec">● Держи и говори</button>
  </div>
  <div class="row">
    <button id="play">▶ Моя запись</button>
    <button id="synth">▶ Как сейчас в приложении</button>
    <button id="drop">✕ Убрать</button>
  </div>
  <div class="row">
    <button id="prev">← Назад</button>
    <button id="next">Дальше →</button>
    <button id="skip">К незаписанному →</button>
  </div>
  <div class="status" id="status"></div>
</div>

<footer>
  <div class="count" id="count"></div>
  <div class="row">
    <button id="save">Сохранить в проект</button>
    <button id="embed">Вшить в приложение</button>
    <button id="down">Скачать файлом</button>
  </div>
  <div class="status" id="footStatus"></div>
</footer>

<script>
const LETTERS = __LETTERS__;
const HAVE    = __HAVE__;
const SYNTH   = __SYNTH__;

const RATE = 16000;              /* речи хватает: у /s/ вся энергия ниже 8 кГц */
const REC  = Object.assign({}, HAVE);
const BAD  = {};                 /* звук -> что с ним не так */
let idx = 0;

/* Черновик живёт в браузере: закрыть вкладку на середине — обычное дело,
   а начинать полсотни звуков заново обидно. */
try{
  const kept = JSON.parse(localStorage.getItem('voice-takes') || '{}');
  for(const k in kept) if(!REC[k]) REC[k] = kept[k];
}catch(e){}
function keep(){ try{ localStorage.setItem('voice-takes', JSON.stringify(REC)); }catch(e){} }

const $ = id => document.getElementById(id);
const cur = () => LETTERS[idx];
const label = k => k.endsWith('_e') ? k[0] + '–e' : (k === 'oo2' ? 'oo' : k);

function say(msg, kind){ $('status').textContent = msg || ''; $('status').className = 'status ' + (kind||''); }
function foot(msg, kind){ $('footStatus').textContent = msg || ''; $('footStatus').className = 'status ' + (kind||''); }

function paint(){
  const c = cur();
  $('letter').textContent = label(c.k);
  $('ipa').textContent    = c.ipa || '';
  $('ex').textContent     = c.word ? ('как в слове ' + c.word + (c.ru ? ' — ' + c.ru : '')) : '';
  $('how').textContent    = c.how;
  $('play').disabled = $('drop').disabled = !REC[c.k];
  $('synth').disabled = !SYNTH[c.k];
  const done = LETTERS.filter(l => REC[l.k]).length;
  const warn = LETTERS.filter(l => REC[l.k] && BAD[l.k]).length;
  $('count').textContent = 'записано ' + done + ' из ' + LETTERS.length +
        (warn ? ', из них ' + warn + ' с замечанием — они красные' : '') +
        (done === LETTERS.length && !warn ? ' — можно сохранять' : '');
  $('chips').innerHTML = '';
  LETTERS.forEach((l, i) => {
    const b = document.createElement('button');
    b.className = 'chip' + (REC[l.k] ? (BAD[l.k] ? ' warn' : ' done') : '') +
                  (i === idx ? ' now' : '');
    b.textContent = label(l.k);
    if(BAD[l.k]) b.title = BAD[l.k];
    b.onclick = () => { idx = i; say(''); paint(); };
    $('chips').appendChild(b);
  });
}

/* ---- проигрывание ---------------------------------------------------- */

let playing = null;
function play(uri, cut){
  if(playing){ try{ playing.pause(); }catch(e){} }
  const a = new Audio(uri);
  playing = a;
  if(cut){
    a.currentTime = cut[0];
    setTimeout(() => { try{ a.pause(); }catch(e){} }, (cut[1] - cut[0]) * 1000 + 60);
  }
  a.play().catch(() => {});
}

/* ---- запись ---------------------------------------------------------- */

let stream = null, mr = null, chunks = [], on = false, mode = 'sound';

async function mic(){
  if(stream) return stream;
  if(!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia)
    throw new Error('Браузер не даёт микрофон. Страницу надо открывать по адресу ' +
                    'http://localhost:8000/_record.html, а не двойным щелчком по файлу.');
  /* Обработку выключаем: подавление шума первым делом съедает шипящие,
     а громкость мы ровняем сами и точнее. */
  stream = await navigator.mediaDevices.getUserMedia({ audio:{
    channelCount:1, echoCancellation:false, noiseSuppression:false, autoGainControl:false
  }});
  return stream;
}

async function start(){
  if(on) return;
  try{
    const s = await mic();
    chunks = [];
    mr = new MediaRecorder(s);
    mr.ondataavailable = e => { if(e.data && e.data.size) chunks.push(e.data); };
    mr.onstop = () => finish(new Blob(chunks, { type: mr.mimeType }));
    mr.start();
    on = true;
    $('rec').classList.add('on');
    $('rec').textContent = '● говори…';
    say('пишу');
  }catch(e){ say(e.message || String(e), 'bad'); }
}

function stop(){
  if(!on) return;
  on = false;
  $('rec').classList.remove('on');
  $('rec').textContent = '● Держи и говори';
  try{ mr.stop(); }catch(e){}
}

/* ---- обработка записи ------------------------------------------------ */

/* Приводим к моно 16 кГц и заодно срезаем низ: гул ноутбука, кулер и топот
   по столу живут ниже сотни герц, а у речи там нет ничего нужного даже
   у женского голоса. Два фильтра подряд — чтобы срез был крутым. */
async function mono(buf){
  const len = Math.max(1, Math.ceil(buf.duration * RATE));
  const off = new OfflineAudioContext(1, len, RATE);
  const src = off.createBufferSource();
  src.buffer = buf;
  const hp1 = off.createBiquadFilter(), hp2 = off.createBiquadFilter();
  hp1.type = hp2.type = 'highpass';
  hp1.frequency.value = hp2.frequency.value = 90;
  hp1.Q.value = hp2.Q.value = 0.7;
  src.connect(hp1); hp1.connect(hp2); hp2.connect(off.destination);
  src.start();
  return (await off.startRendering()).getChannelData(0);
}

/* ---- вычитание шума комнаты ------------------------------------------
   Гул кулера и комнаты ровный: его спектр почти не меняется во времени.
   Значит, его можно измерить один раз на двух секундах тишины и вычесть
   из каждой записи по частотам. Отдельный микрофон это заменяет не
   полностью, но ровный фон убирает целиком.

   Встроенное подавление шума браузера не годится: оно первым делом ест
   шипящие, а /s/, /f/ и /sh/ — ровно то, ради чего всё затевалось. */

const N = 512, HOP = 128;                    /* окно 32 мс, перекрытие 75% */
const HANN = new Float32Array(N);
for(let i = 0; i < N; i++) HANN[i] = 0.5 - 0.5 * Math.cos(2 * Math.PI * i / N);

let NOISE = null;
try{
  const kept = JSON.parse(localStorage.getItem('voice-noise') || 'null');
  if(kept && kept.length === N / 2 + 1) NOISE = Float32Array.from(kept);
}catch(e){}

function fft(re, im, inv){
  const n = re.length;
  for(let i = 1, j = 0; i < n; i++){
    let bit = n >> 1;
    for(; j & bit; bit >>= 1) j ^= bit;
    j ^= bit;
    if(i < j){ let t = re[i]; re[i] = re[j]; re[j] = t; t = im[i]; im[i] = im[j]; im[j] = t; }
  }
  for(let len = 2; len <= n; len <<= 1){
    const ang = (inv ? 2 : -2) * Math.PI / len;
    const wr = Math.cos(ang), wi = Math.sin(ang), half = len >> 1;
    for(let i = 0; i < n; i += len){
      let cr = 1, ci = 0;
      for(let k = 0; k < half; k++){
        const ur = re[i+k], ui = im[i+k];
        const br = re[i+k+half], bi = im[i+k+half];
        const vr = br * cr - bi * ci, vi = br * ci + bi * cr;
        re[i+k] = ur + vr; im[i+k] = ui + vi;
        re[i+k+half] = ur - vr; im[i+k+half] = ui - vi;
        const nr = cr * wr - ci * wi; ci = cr * wi + ci * wr; cr = nr;
      }
    }
  }
  if(inv) for(let i = 0; i < n; i++){ re[i] /= n; im[i] /= n; }
}

/* Средняя громкость каждой частоты за всю запись — портрет шума. */
function profile(d){
  const acc = new Float32Array(N / 2 + 1);
  const re = new Float32Array(N), im = new Float32Array(N);
  let frames = 0;
  for(let p = 0; p + N <= d.length; p += HOP){
    for(let i = 0; i < N; i++){ re[i] = d[p+i] * HANN[i]; im[i] = 0; }
    fft(re, im, false);
    for(let k = 0; k <= N / 2; k++) acc[k] += Math.sqrt(re[k]*re[k] + im[k]*im[k]);
    frames++;
  }
  if(frames) for(let k = 0; k < acc.length; k++) acc[k] /= frames;
  return frames ? acc : null;
}

/* Вычитаем портрет с запасом, но не в ноль: если убрать частоту полностью,
   на её месте заводится бульканье. Порог 0.08 оставляет фон еле слышным
   и ровным, что уху приятнее вычищенной пустоты. */
function denoise(d){
  if(!NOISE || !$('useNoise').checked) return d;
  const A = 1.7, FLOOR = 0.08, pad = N;
  const L = d.length + 2 * pad;
  const x = new Float32Array(L); x.set(d, pad);
  const out = new Float32Array(L), win = new Float32Array(L);
  const re = new Float32Array(N), im = new Float32Array(N);
  for(let p = 0; p + N <= L; p += HOP){
    for(let i = 0; i < N; i++){ re[i] = x[p+i] * HANN[i]; im[i] = 0; }
    fft(re, im, false);
    for(let k = 0; k <= N / 2; k++){
      const mag = Math.sqrt(re[k]*re[k] + im[k]*im[k]);
      const g = mag > 1e-10 ? Math.max(FLOOR, (mag - A * NOISE[k]) / mag) : FLOOR;
      re[k] *= g; im[k] *= g;
      if(k > 0 && k < N / 2){ re[N-k] *= g; im[N-k] *= g; }
    }
    fft(re, im, true);
    for(let i = 0; i < N; i++){ out[p+i] += re[i] * HANN[i]; win[p+i] += HANN[i] * HANN[i]; }
  }
  const y = new Float32Array(d.length);
  for(let i = 0; i < d.length; i++){
    const w = win[i + pad];
    y[i] = w > 1e-6 ? out[i + pad] / w : 0;
  }
  return y;
}

const dB = v => v > 0 ? Math.round(20 * Math.log10(v)) : -99;

function noiseLevel(){
  if(!NOISE) return null;
  let s = 0;
  for(let k = 0; k < NOISE.length; k++) s += NOISE[k] * NOISE[k];
  return Math.sqrt(s / NOISE.length) / (N / 4);      /* грубо, но сравнимо */
}

function showNoise(){
  const b = $('mkNoise');
  if(!NOISE){
    $('noiseStatus').textContent = 'шум не измерен — нажми кнопку и две секунды помолчи';
    $('noiseStatus').className = 'status';
    b.textContent = 'Измерить шум комнаты (2 с)';
  } else {
    $('noiseStatus').textContent = 'шум комнаты измерен: ' + dB(noiseLevel()) + ' дБ';
    $('noiseStatus').className = 'status good';
    b.textContent = 'Измерить заново';
  }
}

/* Где в записи звук. Порог считаем от самого громкого места, а не абсолютный:
   микрофоны разные, а тихий /f/ и громкое /a/ должны обрезаться одинаково. */
function bounds(d){
  const win = Math.round(RATE * 0.01), loud = [];
  let peak = 0;
  for(let i = 0; i < d.length; i += win){
    let p = 0;
    for(let j = i; j < Math.min(i + win, d.length); j++){ const v = Math.abs(d[j]); if(v > p) p = v; }
    loud.push(p); if(p > peak) peak = p;
  }
  if(peak < 0.01) return null;
  const th = Math.max(0.008, peak * 0.09);
  let a = loud.findIndex(v => v > th);
  let b = loud.length - 1 - [...loud].reverse().findIndex(v => v > th);
  if(a < 0) return null;
  const from = Math.max(0, Math.round((a * 0.01 - 0.03) * RATE));
  const to   = Math.min(d.length, Math.round(((b + 1) * 0.01 + 0.09) * RATE));
  return [from, to];
}

/* Ровняем громкость и гасим щелчки на срезе: без затухания обрезанный /a/
   кончается ударом, и в слиянии это слышно. */
function polish(x){
  const out = Float32Array.from(x);
  let peak = 0;
  for(let i = 0; i < out.length; i++){ const v = Math.abs(out[i]); if(v > peak) peak = v; }
  const g = peak > 0 ? 0.9 / peak : 1;
  const inN = Math.min(Math.round(RATE * 0.008), out.length >> 1);
  const outN = Math.min(Math.round(RATE * 0.015), out.length >> 1);
  for(let i = 0; i < out.length; i++){
    let k = g;
    if(i < inN) k *= i / inN;
    const tail = out.length - 1 - i;
    if(tail < outN) k *= tail / outN;
    out[i] *= k;
  }
  return out;
}

/* Два дефекта, которые слышно только в приложении и поздно: приписанная
   к согласному гласная («ту» вместо /t/) и звук, сказанный дважды. Оба видны
   по длине и по числу кусков, поэтому говорим о них сразу после дубля. */
function verdict(clip, c, sr){
  sr = sr || RATE;
  const sec = clip.length / sr;
  const win = Math.round(sr * 0.01), env = [];
  let peak = 0;
  for(let i = 0; i < clip.length; i += win){
    let p = 0;
    for(let j = i; j < Math.min(i + win, clip.length); j++){
      const v = Math.abs(clip[j]); if(v > p) p = v;
    }
    env.push(p); if(p > peak) peak = p;
  }
  let parts = 0, gap = 0, inside = false;
  const th = peak * 0.25;
  for(const e of env){
    if(e > th){ if(!inside){ parts++; inside = true; } gap = 0; }
    else { gap++; if(gap > 10) inside = false; }      /* провал короче 100 мс — не разрыв */
  }
  if(parts > (c.parts || 1)) return 'звук разорван на ' + parts + ' — сказан дважды?';
  if(sec > c.hi * 1.35)
    return 'длинно для «' + c.kind + '», ждём до ' + c.hi.toFixed(2) + ' с' +
           (c.kind === 'взрывной' ? ': не приписалась ли гласная?' : '');
  if(sec < c.lo * 0.7) return 'коротко для «' + c.kind + '», ждём от ' + c.lo.toFixed(2) + ' с';
  return null;
}

function wav(d){
  const bytes = 44 + d.length * 2, ab = new ArrayBuffer(bytes), v = new DataView(ab);
  const tag = (o, t) => { for(let i = 0; i < t.length; i++) v.setUint8(o + i, t.charCodeAt(i)); };
  tag(0, 'RIFF'); v.setUint32(4, bytes - 8, true); tag(8, 'WAVE');
  tag(12, 'fmt '); v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
  v.setUint32(24, RATE, true); v.setUint32(28, RATE * 2, true);
  v.setUint16(32, 2, true); v.setUint16(34, 16, true);
  tag(36, 'data'); v.setUint32(40, d.length * 2, true);
  for(let i = 0; i < d.length; i++){
    const x = Math.max(-1, Math.min(1, d[i]));
    v.setInt16(44 + i * 2, x < 0 ? x * 0x8000 : x * 0x7FFF, true);
  }
  return ab;
}

function b64(ab){
  const u = new Uint8Array(ab);
  let s = '';
  for(let i = 0; i < u.length; i += 0x8000)
    s += String.fromCharCode.apply(null, u.subarray(i, i + 0x8000));
  return btoa(s);
}

async function finish(blob){
  const noiseRun = (mode === 'noise');
  mode = 'sound';
  say(noiseRun ? 'меряю шум…' : 'обрабатываю…');
  try{
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const buf = await ctx.decodeAudioData(await blob.arrayBuffer());
    ctx.close && ctx.close();
    const raw = await mono(buf);

    if(noiseRun){
      const p = profile(raw);
      if(!p){ say('запись вышла короче окна — попробуй ещё раз', 'bad'); return; }
      NOISE = p;
      try{ localStorage.setItem('voice-noise', JSON.stringify(Array.from(p))); }catch(e){}
      showNoise();
      say('шум запомнен, теперь он вычитается из каждой записи', 'good');
      return;
    }

    const d = denoise(raw);
    const b = bounds(d);
    if(!b){ say('тишина: микрофон не слышит или звук слишком тихий', 'bad'); return; }
    let peak = 0;
    for(let i = b[0]; i < b[1]; i++){ const v = Math.abs(d[i]); if(v > peak) peak = v; }
    const clip = polish(d.subarray(b[0], b[1]));
    REC[cur().k] = 'data:audio/wav;base64,' + b64(wav(clip));
    keep();
    const nl = noiseLevel();
    const snr = nl ? ', запас над шумом ' + (dB(peak) - dB(nl)) + ' дБ' : '';
    const bad = verdict(clip, cur(), RATE);
    if(bad) BAD[cur().k] = bad; else delete BAD[cur().k];
    say('готово, ' + (clip.length / RATE).toFixed(2) + ' с' + snr +
        (bad ? ' — ' + bad : ' — слушай'), bad ? 'bad' : 'good');
    paint();
    play(REC[cur().k]);
  }catch(e){ say('не разобрал запись: ' + (e.message || e), 'bad'); }
}

/* ---- кнопки ---------------------------------------------------------- */

const rec = $('rec');
rec.addEventListener('pointerdown', e => { e.preventDefault(); start(); });
rec.addEventListener('pointerup',   e => { e.preventDefault(); stop(); });
rec.addEventListener('pointercancel', stop);
rec.addEventListener('pointerleave',  stop);
addEventListener('keydown', e => { if(e.code === 'Space' && !e.repeat){ e.preventDefault(); start(); } });
addEventListener('keyup',   e => { if(e.code === 'Space'){ e.preventDefault(); stop(); } });

$('mkNoise').onclick = async () => {
  if(on) return;
  mode = 'noise';
  await start();
  if(!on){ mode = 'sound'; return; }          /* микрофон не дали */
  $('rec').textContent = '● молчи, меряю шум…';
  say('две секунды тишины: не говори, не двигай ноутбук');
  setTimeout(stop, 2000);
};
$('useNoise').onchange = () => showNoise();

$('play').onclick  = () => play(REC[cur().k]);
$('synth').onclick = () => { const s = SYNTH[cur().k]; if(s) play(s[0], s[1]); };
$('drop').onclick  = () => { delete REC[cur().k]; delete BAD[cur().k]; keep(); say('убрано'); paint(); };
$('prev').onclick  = () => { idx = (idx - 1 + LETTERS.length) % LETTERS.length; say(''); paint(); };
$('next').onclick  = () => { idx = (idx + 1) % LETTERS.length; say(''); paint(); };
$('skip').onclick  = () => {
  const n = LETTERS.findIndex((l, i) => i > idx && !REC[l.k]);
  idx = n >= 0 ? n : LETTERS.findIndex(l => !REC[l.k]);
  if(idx < 0) idx = 0;
  say(''); paint();
};

async function post(path, body){
  foot('…');
  try{
    const r = await fetch(path, { method:'POST', headers:{ 'Content-Type':'application/json' },
                                 body: JSON.stringify(body || {}) });
    const j = await r.json();
    foot(j.msg, j.ok ? 'good' : 'bad');
  }catch(e){
    foot('сервер не ответил — страница открыта не через python voice.py record?', 'bad');
  }
}
$('save').onclick  = () => post('/save', REC);
$('embed').onclick = () => post('/embed');
$('down').onclick  = () => {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([JSON.stringify(REC)], { type:'application/json' }));
  a.download = '_voice.json';
  a.click();
  foot('скачано; дальше: python voice.py import _voice.json');
};

/* Записи с прошлого раза приходят готовыми файлами, а замечания к ним нигде
   не хранятся: считаем их заново при открытии, чтобы сразу было видно, что
   переписать. То же самое делает python voice.py check. */
async function auditAll(){
  const ctx = new (window.AudioContext || window.webkitAudioContext)();
  for(const l of LETTERS){
    const uri = REC[l.k];
    if(!uri || l.k in BAD) continue;
    try{
      const bin = Uint8Array.from(atob(uri.split(',')[1]), ch => ch.charCodeAt(0));
      const buf = await ctx.decodeAudioData(bin.buffer);
      const v = verdict(buf.getChannelData(0), l, buf.sampleRate);
      if(v) BAD[l.k] = v;
    }catch(e){}
  }
  ctx.close && ctx.close();
  paint();
}

showNoise();
paint();
auditAll();
</script>
"""

# -------------------------------------------------------------------- запуск

def main():
    what = sys.argv[1] if len(sys.argv) > 1 else "all"

    if what in ("sounds", "all"):
        print("ЗВУКИ")
        asyncio.run(make(sorted(SOUND_TEXT.items()), SYNTH_DIR, RATE_SOUND))

    if what in ("words", "all"):
        ws = words_from_index(read_index())
        print(f"СЛОВА ({len(ws)})")
        asyncio.run(make([(w, w) for w in ws], ROOT / "audio" / "words", RATE_WORD))

    if what == "record":
        record(int(sys.argv[2]) if len(sys.argv) > 2 else 8000)

    if what == "import":
        import_file(sys.argv[2] if len(sys.argv) > 2 else "_voice.json")

    if what == "check":
        check()

    if what in ("embed", "all"):
        print("ВШИВАЕМ")
        embed()

if __name__ == "__main__":
    main()
