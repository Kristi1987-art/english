#!/usr/bin/env python3
"""
Иконки приложения для «на главный экран».

    python icons.py        # icon-192.png, icon-512.png

Рисуются, а не лежат картинкой, по двум причинам. Первая: чтобы иконку можно
было поправить вместе с палитрой, а не искать редактор. Вторая: в системе нет
ни Pillow, ни чего-либо ещё для картинок, а PNG собирается из zlib и struct
за тридцать строк — это дешевле, чем ставить библиотеку ради одного файла.

Рисунок — блок из Майнкрафта, каким его видит приложение: травяная крышка,
светлая страница книги под ней и чёрная буква S. S потому, что это первый звук
первой группы: с него начинается всё обучение.

Сетка 16×16, каждая клетка — квадрат. Размеры кратны шестнадцати (192 = 16×12,
512 = 16×32), поэтому пиксели остаются ровными и ничего не размывается.
"""

import zlib, struct, pathlib

ROOT = pathlib.Path(__file__).parent

SKY       = (0x8F, 0xC7, 0xEE)
GRASS     = (0x6C, 0xBF, 0x3F)
GRASS_D   = (0x46, 0x8A, 0x26)
GRASS_INK = (0x2F, 0x63, 0x18)
PAPER     = (0xFF, 0xFD, 0xF6)
PAPER_2   = (0xF2, 0xEB, 0xD8)
INK       = (0x2B, 0x21, 0x18)

# Буква S, 6×7. Точка — фон, решётка — чернила.
LETTER = [
    ".####.",
    "#....#",
    "#.....",
    ".####.",
    ".....#",
    "#....#",
    ".####.",
]

def grid():
    """16×16 клеток: рамка, травяная крышка, страница, буква."""
    g = [[PAPER for _ in range(16)] for _ in range(16)]

    for y in range(16):
        for x in range(16):
            if x == 0 or x == 15 or y == 0 or y == 15:
                g[y][x] = GRASS_INK          # рамка блока
            elif y <= 3:
                g[y][x] = GRASS              # трава
            elif y == 4:
                g[y][x] = GRASS_D if x % 2 else GRASS   # бахрома травы
            elif (x * 7 + y * 5) % 23 == 0:
                g[y][x] = PAPER_2            # редкие крапины на странице

    for r, row in enumerate(LETTER):         # буква по центру страницы
        for c, ch in enumerate(row):
            if ch == "#":
                g[6 + r][5 + c] = INK
    return g

def png(path, size):
    cells, n = grid(), size // 16
    rows = []
    for y in range(16):
        line = []
        for x in range(16):
            line.extend([cells[y][x]] * n)
        rows.extend([line] * n)
    raw = b"".join(b"\x00" + bytes(v for px in row for v in px) for row in rows)

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    head = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)   # 8 бит, truecolor
    path.write_bytes(b"\x89PNG\r\n\x1a\n"
                     + chunk(b"IHDR", head)
                     + chunk(b"IDAT", zlib.compress(raw, 9))
                     + chunk(b"IEND", b""))
    print(f"{path.name}: {size}×{size}, {path.stat().st_size} б")

if __name__ == "__main__":
    for s in (192, 512):
        png(ROOT / f"icon-{s}.png", s)
