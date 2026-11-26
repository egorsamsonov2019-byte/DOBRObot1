"""Поиск по базе вопросов-ответов. Без тяжёлых зависимостей: TF-IDF по основам слов
+ сходство по символьным триграммам (устойчиво к опечаткам и падежам)."""
import json, math, re
from collections import Counter
from pathlib import Path

STOP = set("""и в во не что он на я с со как а то все она так его но да ты к у же вы за бы по только ее мне было вот от меня
еще нет о из ему теперь когда даже ну вдруг ли если уже или ни быть был него до вас нибудь опять уж вам ведь там потом себя
ничего ей может они тут где есть надо ней для мы тебя их чем была сам чтоб без будто чего раз тоже себе под будет ж тогда кто
этот того потому этого какой совсем ним здесь этом один почти мой тем чтобы нее сейчас были куда зачем всех никогда можно при
наконец два об другой хоть после над больше тот через эти нас про всего них какая много разве три эту моя впрочем хорошо свою
этой перед иногда лучше чуть том нельзя такой им более всегда конечно всю между это мои мой нужно надо можно ли какие какой
какая какое каким какими какого каких кого кому чём чем сколько""".split())

# синонимы/просторечия -> каноническая основа
SYN = {
    "потеря": "утер", "потерял": "утер", "потеряла": "утер", "потерян": "утер", "утеря": "утер", "утерял": "утер", "утеряна": "утер",
    "украли": "утер", "кража": "утер",
    "прописк": "регис", "прописа": "регис", "регист": "регис",
    "военко": "воинс", "призыв": "воинс", "армия": "воинс", "армию": "воинс", "служб": "воинс",
    "безраб": "безра", "биржа": "цзн", "бирже": "цзн", "биржу": "цзн", "занято": "цзн",
    "больни": "поликл", "врач": "поликл", "доктор": "поликл",
    "квартир": "жилье", "жильё": "жилье", "жилья": "жилье", "жилье": "жилье", "жилом": "жилье", "жилое": "жилье",
    "общага": "общеж", "общежи": "общеж",
    "стипенд": "стипен", "стипуха": "стипен",
    "детдом": "сирот", "сирота": "сирот", "сироты": "сирот",
    "инвалид": "инвал",
    "пенси": "пенс",
    "платят": "пособ", "платит": "пособ", "пособи": "пособ", "выплат": "пособ", "деньги": "пособ", "денег": "пособ",
    "учебник": "литер", "учебн": "литер", "книги": "литер", "книг": "литер",
    "замен": "замен", "меня": "замен", "поменя": "замен", "смени": "замен", "сменя": "замен",
    "работ": "работ", "трудоустр": "работ",
}

def _norm(s: str) -> str:
    return s.lower().replace("ё", "е")

def stems(text: str):
    out = []
    for w in re.findall(r"[a-zа-я0-9]+", _norm(text)):
        if w in STOP or len(w) < 2:
            continue
        key = next((v for k, v in SYN.items() if w.startswith(k)), None)
        out.append(key or (w[:6] if len(w) > 6 else w))
    return out

def trigrams(text: str):
    t = " " + " ".join(re.findall(r"[a-zа-я0-9]+", _norm(text))) + " "
    return {t[i:i + 3] for i in range(len(t) - 2)}


class FAQ:
    def __init__(self, path="data/faq.json"):
        self.sections = json.loads(Path(path).read_text(encoding="utf-8"))
        self.items = {}
        for sec in self.sections:
            for it in sec["items"]:
                it["section"] = sec["title"]
                self.items[it["id"]] = it
        self._build()

    def _build(self):
        self.docs = {}
        df = Counter()
        for i, it in self.items.items():
            q = Counter(stems(it["q"])); a = Counter(stems(it["a"] or ""))
            self.docs[i] = (q, a, trigrams(it["q"]))
            df.update(set(q) | set(a))
        n = len(self.items)
        self.idf = {w: math.log(1 + n / c) for w, c in df.items()}

    def search(self, query: str, top=3):
        qs = stems(query)
        if not qs:
            return []
        qtri = trigrams(query)
        res = []
        for i, (q, a, tri) in self.docs.items():
            s = 0.0; hit = 0
            for w in set(qs):
                idf = self.idf.get(w, 1.5)
                if w in q: s += 3.0 * idf; hit += 1
                elif w in a: s += 0.7 * idf; hit += 0.4
            denom = sum(self.idf.get(w, 1.5) for w in set(qs)) * 3.0
            lex = s / denom if denom else 0
            jac = len(qtri & tri) / len(qtri | tri) if qtri | tri else 0
            res.append((0.8 * lex + 0.2 * jac, i))
        res.sort(reverse=True)
        return [(sc, self.items[i]) for sc, i in res[:top] if sc > 0]
