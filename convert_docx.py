"""Конвертер базы знаний: ГУАП_все_вопросы.docx -> data/faq.json + data/images/*.jpg
Запуск: python convert_docx.py путь/к/файлу.docx
"""
import io, json, re, sys
from pathlib import Path
import docx
from docx.oxml.ns import qn
from PIL import Image

SRC = sys.argv[1] if len(sys.argv) > 1 else "ГУАП_все_вопросы.docx"
OUT = Path("data"); IMG = OUT / "images"; IMG.mkdir(parents=True, exist_ok=True)

d = docx.Document(SRC)
rels = d.part.rels
table = d.tables[0]

# ссылки-редиректы google.com/url не восстановить -> подставляем известные адреса по тексту
KNOWN = {"госуслуг": "https://www.gosuslugi.ru", "мфц": "https://gu.spb.ru/mfc/"}

def clean(s):
    s = s.replace("\xa0", " ").replace("\u200b", "")
    s = re.sub(r"[ \t]+", " ", s)
    return s.strip()

def para_text(p):
    """Текст абзаца с гиперссылками: 'текст (url)' для рабочих ссылок."""
    parts = []
    for node in p._p.iterchildren():
        if node.tag == qn("w:r"):
            parts.append("".join(t.text or "" for t in node.iter(qn("w:t"))))
        elif node.tag == qn("w:hyperlink"):
            txt = "".join(t.text or "" for t in node.iter(qn("w:t")))
            rid = node.get(qn("r:id")); url = rels[rid].target_ref if rid in rels else ""
            if "google.com/url" in url or not url:
                url = next((v for k, v in KNOWN.items() if k in txt.lower()), "")
            if url and url.strip("/") != txt.strip().strip("/"):
                txt = f"{txt} ({url})"
            parts.append(txt)
    return clean("".join(parts))

def cell_to_text(cell):
    lines = []
    for p in cell.paragraphs:
        t = para_text(p)
        if not t:
            if lines and lines[-1] != "": lines.append("")
            continue
        if p._p.find(".//" + qn("w:numPr")) is not None and not re.match(r"^(\d+[.)]|[•\-–])", t):
            t = "• " + t
        # "1.Паспорт" -> "1. Паспорт"
        t = re.sub(r"^(\d+\.)(?=\S)", r"\1 ", t)
        lines.append(t)
    text = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", text).strip()

# Ответы, которых нет в .docx или которые нужно заменить (id -> текст)
OVERRIDES = {
    39: """Абилитация и реабилитация — разные процессы. Основные отличия:

1. Суть процесса
• Абилитация — формирование новых, ранее отсутствовавших способностей и навыков.
• Реабилитация — восстановление утраченных или нарушенных функций и способностей.

2. Когда чаще применяется
• Абилитация — в раннем возрасте, когда навыки ещё не сформировались.
• Реабилитация — после травмы или заболевания, когда человек уже обладал определёнными умениями.

3. Цель
• Абилитация — помочь человеку интегрироваться в общество, приобрести самостоятельность.
• Реабилитация — вернуть человека к прежнему уровню функционирования.""",
}

img_counter = 0
def cell_images(cell):
    global img_counter
    names = []
    for rid in cell._tc.xpath(".//a:blip/@r:embed"):
        blob = rels[rid].target_part.blob
        im = Image.open(io.BytesIO(blob)).convert("RGB")
        im.thumbnail((1600, 1600))
        img_counter += 1
        name = f"img_{img_counter:02d}.jpg"
        im.save(IMG / name, "JPEG", quality=85, optimize=True)
        names.append(name)
    return names

sections, cur = [], None
for i, row in enumerate(table.rows):
    if i == 0: continue
    c = row.cells
    first = clean(c[0].text)
    if first and not first.isdigit():          # строка-заголовок раздела
        if first.upper() != (cur or {}).get("title"):
            cur = {"title": first.upper(), "items": []}; sections.append(cur)
        continue
    q = clean(c[1].text).replace("\n", " ")
    if not first.isdigit() or not q: continue   # пустые строки
    a = cell_to_text(c[2]); extra = cell_to_text(c[3])
    imgs = cell_images(c[2]) + cell_images(c[3])
    if extra and extra not in a: a = (a + "\n\n" + extra).strip()
    a = OVERRIDES.get(int(first), a)
    cur["items"].append({"id": int(first), "q": q, "a": a, "images": imgs})

# Пустой раздел (после "ЗДОРОВЬЕ" есть пустая строка) убираем; нет ответа -> заглушка
sections = [s for s in sections if s["items"]]
for s in sections:
    for it in s["items"]:
        if not it["a"]:
            it["a"] = None   # бот скажет: ответ уточняется, и передаст оператору

json.dump(sections, open(OUT / "faq.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("Разделов:", len(sections), "| вопросов:", sum(len(s["items"]) for s in sections), "| картинок:", img_counter)
for s in sections: print(f"  {s['title']}: {len(s['items'])}")
print("Без ответа:", [it["id"] for s in sections for it in s["items"] if it["a"] is None])
print("Самый длинный ответ, симв.:", max(len(it["a"] or "") for s in sections for it in s["items"]))
