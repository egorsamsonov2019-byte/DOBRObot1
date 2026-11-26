"""Чат-бот ГУАП для сообщества ВКонтакте (Bots Long Poll API)."""
import csv, json, logging, os, random, re, time
from datetime import datetime
from pathlib import Path

import vk_api
from dotenv import load_dotenv
from vk_api.bot_longpoll import VkBotEventType, VkBotLongPoll
from vk_api.keyboard import VkKeyboard, VkKeyboardColor
from vk_api.upload import VkUpload

import texts as T
from faq_engine import FAQ

load_dotenv()
TOKEN = os.environ["VK_TOKEN"]
GROUP_ID = int(os.environ["VK_GROUP_ID"])
CONFIDENT, SUGGEST = 0.60, 0.25     # пороги уверенности поиска
MSG_LIMIT = 3500                    # лимит VK — 4096 символов, берём с запасом

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("guap-bot")

faq = FAQ("data/faq.json")
vk_session = vk_api.VkApi(token=TOKEN)
vk = vk_session.get_api()
uploader = VkUpload(vk_session)
Path("logs").mkdir(exist_ok=True)

# user_id -> {"section": index|None, "last_q": id|None}
state = {}
PHOTO_CACHE_FILE = Path("data/photo_cache.json")
photo_cache = json.loads(PHOTO_CACHE_FILE.read_text()) if PHOTO_CACHE_FILE.exists() else {}


# ---------- вспомогательное ----------
def log_csv(name, *row):
    with open(f"logs/{name}.csv", "a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow([datetime.now().isoformat(timespec="seconds"), *row])


def send(uid, text="", keyboard=None, attachment=None):
    vk.messages.send(user_id=uid, random_id=random.randint(1, 2**31), message=text or "",
                     keyboard=keyboard.get_keyboard() if keyboard else None, attachment=attachment,
                     dont_parse_links=0)


def split_text(text, limit=MSG_LIMIT):
    """Режем длинный ответ по абзацам, не ломая слова."""
    parts, cur = [], ""
    for para in text.split("\n"):
        while len(para) > limit:
            cut = para.rfind(" ", 0, limit)
            cut = cut if cut > 0 else limit
            if len(cur) + cut > limit and cur: parts.append(cur.rstrip()); cur = ""
            parts.append(para[:cut]); para = para[cut:].lstrip()
        if len(cur) + len(para) + 1 > limit:
            parts.append(cur.rstrip()); cur = ""
        cur += para + "\n"
    if cur.strip(): parts.append(cur.rstrip())
    return parts


def photo_attachment(name):
    """Загружаем картинку один раз и дальше используем её id из кэша."""
    if name in photo_cache:
        return photo_cache[name]
    ph = uploader.photo_messages(f"data/images/{name}")[0]
    att = f"photo{ph['owner_id']}_{ph['id']}"
    photo_cache[name] = att
    PHOTO_CACHE_FILE.write_text(json.dumps(photo_cache))
    return att


def sec_title(sec):
    short = T.SECTION_SHORT.get(sec["title"])
    icon = next((v for k, v in T.SECTION_ICONS.items() if sec["title"].startswith(k)), "📁")
    return f"{icon} {short or sec['title'].capitalize()}"


# ---------- клавиатуры ----------
def kb_main():
    kb = VkKeyboard(one_time=False)
    for i, sec in enumerate(faq.sections):
        kb.add_button(sec_title(sec)[:40], VkKeyboardColor.PRIMARY, {"cmd": "section", "i": i})
        if i % 2 == 1 and i != len(faq.sections) - 1: kb.add_line()   # без пустого ряда в конце
    return kb


def kb_numbers(ids, back_section=None):
    """Кнопки с номерами вопросов (до 5 в ряд, всего ≤ 40 кнопок)."""
    kb = VkKeyboard(one_time=False)
    for n, qid in enumerate(ids, 1):
        kb.add_button(str(qid), VkKeyboardColor.SECONDARY, {"cmd": "q", "id": qid})
        if n % 5 == 0 and n != len(ids): kb.add_line()
    kb.add_line()
    kb.add_button(T.BTN_MENU, VkKeyboardColor.PRIMARY, {"cmd": "menu"})
    return kb


def kb_after_answer(section_idx):
    kb = VkKeyboard(one_time=False)
    kb.add_button(T.BTN_YES, VkKeyboardColor.POSITIVE, {"cmd": "fb", "v": 1})
    kb.add_button(T.BTN_NO, VkKeyboardColor.NEGATIVE, {"cmd": "fb", "v": 0})
    kb.add_line()
    if section_idx is not None:
        kb.add_button(T.BTN_BACK, VkKeyboardColor.SECONDARY, {"cmd": "section", "i": section_idx})
    kb.add_button(T.BTN_MENU, VkKeyboardColor.PRIMARY, {"cmd": "menu"})
    return kb


# ---------- сценарий ----------
def show_menu(uid, text=T.WELCOME):
    state.setdefault(uid, {}).update(section=None, last_q=None)
    send(uid, text, kb_main())


def show_section(uid, idx):
    sec = faq.sections[idx]
    state.setdefault(uid, {}).update(section=idx, last_q=None)
    lines = [f"{it['id']}. {it['q']}" for it in sec["items"]]
    head = T.SECTION_HEAD.format(title=sec["title"].capitalize())
    chunks = split_text(head + "\n".join(lines))
    for c in chunks[:-1]: send(uid, c)
    send(uid, chunks[-1], kb_numbers([it["id"] for it in sec["items"]]))


def section_index_of(qid):
    for i, sec in enumerate(faq.sections):
        if any(it["id"] == qid for it in sec["items"]): return i


def show_answer(uid, qid):
    it = faq.items.get(qid)
    if not it: return send(uid, T.NOT_FOUND, kb_main())
    sec_idx = section_index_of(qid)
    state.setdefault(uid, {}).update(section=sec_idx, last_q=qid)
    log_csv("answers", uid, qid)
    if it["a"] is None:
        send(uid, f"❓ {it['q']}\n\n{T.EMPTY_ANSWER}", kb_after_answer(sec_idx))
        return
    chunks = split_text(f"❓ {it['q']}\n\n{it['a']}")
    for c in chunks[:-1]: send(uid, c)
    atts = []
    for name in it["images"]:
        try: atts.append(photo_attachment(name))
        except Exception:
            log.exception("не удалось загрузить картинку %s", name)
    kb = kb_after_answer(sec_idx)
    if atts:                                   # картинки — отдельным сообщением (до 10 вложений)
        send(uid, chunks[-1])
        send(uid, "", attachment=",".join(atts[:10]))
        send(uid, T.ASK_FEEDBACK, kb)
    else:
        send(uid, f"{chunks[-1]}\n\n{T.ASK_FEEDBACK}", kb)


def handle_text(uid, text):
    low = re.sub(r"[^\w\s/]", "", text.lower()).strip()
    if low in T.GREETINGS: return show_menu(uid)
    if low in T.THANKS: return send(uid, T.THANKS_YES, kb_main())
    if low.isdigit():                                  # пользователь ввёл номер вопроса
        qid = int(low)
        if qid in faq.items: return show_answer(uid, qid)
    results = faq.search(text, top=3)
    if not results or results[0][0] < SUGGEST:
        log_csv("unanswered", uid, text)
        return send(uid, T.NOT_FOUND, kb_main())
    best = results[0]
    second = results[1][0] if len(results) > 1 else 0
    if best[0] >= CONFIDENT and (best[0] - second >= 0.08 or best[0] >= 0.95):
        return show_answer(uid, best[1]["id"])
    log_csv("suggested", uid, text, [r[1]["id"] for r in results])
    ids = [r[1]["id"] for r in results if r[0] >= SUGGEST]
    body = T.OPTIONS_HEAD + "\n".join(f"{i}. {faq.items[i]['q']}" for i in ids)
    send(uid, body, kb_numbers(ids))


def handle_message(msg):
    uid = msg["from_id"]
    payload = json.loads(msg["payload"]) if msg.get("payload") else None
    if payload:
        cmd = payload.get("cmd")
        if cmd == "menu": return show_menu(uid, T.MENU_HINT)
        if cmd == "section": return show_section(uid, payload["i"])
        if cmd == "q": return show_answer(uid, payload["id"])
        if cmd == "fb":
            log_csv("feedback", uid, state.get(uid, {}).get("last_q"), payload["v"])
            send(uid, T.THANKS_YES if payload["v"] else T.THANKS_NO, kb_main())
            return
        if payload.get("command") == "start": return show_menu(uid)   # кнопка «Начать»
    text = (msg.get("text") or "").strip()
    if not text:
        return send(uid, T.MENU_HINT, kb_main())
    handle_text(uid, text)


def main():
    longpoll = VkBotLongPoll(vk_session, GROUP_ID)
    log.info("Бот запущен, слушаю сообщения сообщества %s", GROUP_ID)
    for event in longpoll.listen():
        if event.type == VkBotEventType.MESSAGE_NEW and not event.from_chat:
            msg = event.obj.message
            try:
                handle_message(msg)
            except Exception:
                log.exception("ошибка при обработке сообщения")
                try: send(msg["from_id"], T.ERROR, kb_main())
                except Exception: pass


if __name__ == "__main__":
    while True:                     # автоперезапуск при обрыве соединения
        try: main()
        except Exception:
            log.exception("падение long poll, перезапуск через 5 с"); time.sleep(5)
