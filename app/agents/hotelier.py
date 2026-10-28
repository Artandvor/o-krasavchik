"""Агент диалога с отельером.

1. plan_questions: решает, ЧТО спросить. Не спрашивает всё подряд, а ранжирует вопросы
   по ценности информации: спрос пользователей на характеристику × неуверенность системы
   (× 1.5, если источники спорят). Бюджет — 3 вопроса на отель за раунд.
   Где есть расчёт, вопрос формулируется как гипотеза на подтверждение в один клик.
2. answer: принимает ответ в свободной форме, раскладывает по полям (LLM или правила),
   записывает факт с источником «отельер» и сводит с остальными источниками.
3. simulate_answer: имитация отельера для демо (по заданию отельера можно имитировать).
"""
import hashlib
import random
import re

from .. import truth
from ..llm import get_llm
from ..registry import get_registry
from ..store import get_store
from ..tools import PARSER_RU

AGENT = "hotelier"
BUDGET = 3


def demand_weights(store, reg):
    counts = store.demand()
    total = sum(counts.values())
    out = {}
    for s in reg.all():
        d = s.get("demand", 0.05)
        if total >= 20:
            d = 0.5 * d + 0.5 * counts.get(s["key"], 0) / total
        out[s["key"]] = d
    return out


def plan_questions(hotel, store=None, reg=None, budget=BUDGET):
    store = store or get_store()
    reg = reg or get_registry()
    dw = demand_weights(store, reg)
    cands = []
    open_conf = {c["key"] for c in store.conflicts(hotel["id"])}
    for spec in reg.all():
        hcfg = spec.get("hotelier")
        if not hcfg or spec["scope"] == "region":
            continue
        facts = store.facts(hotel["id"], spec["key"])
        res = truth.resolve(spec, facts)
        conf = res["confidence"] if res else 0.0
        has_hotelier = any(f["source_type"] == "hotelier" for f in facts)
        conflict = spec["key"] in open_conf
        need = conf < hcfg.get("ask_below", 0.7) or conflict or (hcfg.get("ask_if_true") and res and res["value"] is True)
        if has_hotelier and not conflict:
            need = False
        if not need:
            continue
        prio = dw[spec["key"]] * (1 - conf) * (1.5 if conflict else 1.0)
        if hcfg.get("ask_if_true") and res and res["value"] is True:
            prio = max(prio, dw[spec["key"]] * 0.8)
        if conflict:
            c = [c for c in store.conflicts(hotel["id"]) if c["key"] == spec["key"]][0]
            text = f"{spec['title']}: у нас расходятся данные — {c['description']}. Как на самом деле?"
            calc = [f for f in facts if f["source_type"] in ("geo", "osm_tag", "open_api")]
            calc = calc[-1] if calc else None
            hyp = {"value": calc["value"] if calc else None, "scope": calc["scope"] if calc else "",
                   "detail": {"from_floor_min": (calc.get("detail") or {}).get("from_floor_min")} if calc else {}}
            opts = ["Верно по расчёту", "Верно по анкете", "Уточню текстом"]
            reason = "противоречие источников"
        elif res and hcfg.get("hypothesis"):
            text = hcfg["hypothesis"].format(summary=res["scope"])
            hyp = {"value": res["value"], "scope": res["scope"], "detail": _hyp_detail(res)}
            opts = ["Да, верно", "Нет", "Частично — уточню"]
            reason = f"уверенность {conf:.0%} ниже порога {hcfg.get('ask_below', 0.7):.0%}"
        else:
            text = hcfg["question"]
            hyp = None
            opts = ["Да", "Нет"] if spec["type"] == "bool" else []
            reason = "нет данных в открытых источниках" if not res else f"уверенность {conf:.0%}"
        cands.append((prio, spec, text, hyp, opts, reason))
    cands.sort(key=lambda c: -c[0])
    made = []
    for prio, spec, text, hyp, opts, reason in cands[:budget]:
        qid = store.add_question(hotel["id"], spec["key"], text, hyp, opts, round(prio, 4), reason)
        store.log(AGENT, "ask", f"вопрос отельеру ({reason}, приоритет {prio:.3f}): {text}", hotel["id"], spec["key"],
                  {"question_id": qid})
        made.append(qid)
    store.commit()
    return made


def _hyp_detail(res):
    d = res.get("detail") or {}
    out = {}
    if "from_floor_min" in d:
        out["from_floor_min"] = d["from_floor_min"]
    if "by_side" in d and isinstance(d["by_side"], dict):
        out["sides"] = list(d["by_side"].keys())
    return out


# ------------------------------------------------------------------ разбор ответа

YES = re.compile(r"^\s*(да|есть|конечно|верно|так|можно|разрешен|пускаем|принимаем|yes|угу|ага)\b|\bда[,.!]", re.I)
NO = re.compile(r"^\s*(нет|не\s|никак|к сожалению|no\b)|\bнельзя\b|\bне (пускаем|принимаем|размещаем|разрешаем)|"
                r"\bнет\b", re.I)
SIDES = {"север": "С", "северо-восток": "СВ", "восток": "В", "юго-восток": "ЮВ", "юг": "Ю", "юго-запад": "ЮЗ",
         "запад": "З", "северо-запад": "СЗ", "на море": "море", "на горы": "горы", "во двор": "двор"}


def rule_parse(spec, text, hyp):
    t = text.strip().lower()
    out = {"_parser": "rules"}
    yes, no = bool(YES.search(t)), bool(NO.search(t))
    if t.startswith("частично"):
        yes, no = False, False
    if spec["type"] == "bool":
        if yes and not no:
            out["value"] = True
        elif no and not yes:
            out["value"] = False
        elif yes and no:  # «да, но не для собак больше 10 кг»
            out["value"] = True
    if hyp is not None:
        if t.startswith(("да", "верно", "так", "верно по расчёту")):
            out["confirmed"] = True
            out.setdefault("value", hyp.get("value"))
        elif t.startswith(("нет", "неверно")):
            out["confirmed"] = False
            if isinstance(hyp.get("value"), bool):
                out["value"] = not hyp["value"]
    m = re.search(r"(?:с|от|начиная с)\s*(\d{1,2})[- ]?(?:го|ого|ая|й)?\s*этаж", t)
    if m:
        out["from_floor"] = int(m.group(1))
        if spec["scope"] == "room":
            out["value"] = True
    m = re.search(r"(\d+[.,]?\d*)\s*кг", t)
    if m:
        out["max_weight_kg"] = float(m.group(1).replace(",", "."))
    m = re.search(r"(\d[\d\s]*)\s*(?:₽|руб|р\b)", t)
    if m:
        out["fee_rub"] = int(re.sub(r"\s", "", m.group(1)))
    if re.search(r"бесплатн", t):
        out["fee_rub"] = 0
    m = re.search(r"(\d{1,2})\s*мин", t)
    if m and spec["type"] == "number":
        out["value"] = float(m.group(1))
    sides = [v for k, v in SIDES.items() if k in t]
    if sides:
        out["sides"] = sides
    if spec["type"] == "enum":
        for v in spec.get("values", []):
            if v in t:
                out["value"] = v
                break
        if spec["key"] == "wheelchair" and "value" not in out:
            out["value"] = "да" if yes and not no else "нет" if no else None
    if "стеклопакет" in t or "шумоизоляц" in t:
        out["soundproof_windows"] = not bool(re.search(r"нет\s+(шумоизоляц|стеклопакет)", t))
    if "лифт" in t:
        out["elevator"] = not bool(re.search(r"(нет|без)\s+лифт", t))
    for a, w in (("собак", "собаки"), ("кош", "кошки"), ("птиц", "птицы")):
        if a in t:
            out.setdefault("animals", []).append(w)
    if "закончил" in t or "завершил" in t or "уже нет" in t:
        if spec["key"] == "construction_nearby":
            out["value"] = False
    return out


def llm_parse(spec, text, hyp):
    llm = get_llm()
    if not llm.available:
        return None
    fields = spec.get("hotelier", {}).get("fields", {"value": spec["type"]})
    sys_p = ("Ты раскладываешь ответ отельера по полям анкеты. Не придумывай значения: если в ответе "
             "чего-то нет — не включай поле. value — главный ответ на вопрос. confirmed — подтвердил ли "
             "отельер гипотезу (true/false/null).")
    user = (f"Характеристика: {spec['title']} ({spec.get('description', '')}).\n"
            f"Поля: {fields}. Тип value: {spec['type']}" + (f", варианты {spec.get('values')}" if spec.get("values") else "") +
            (f"\nГипотеза системы: {hyp}" if hyp else "") + f"\nОтвет отельера: «{text}»")
    js = llm.json(sys_p, user)
    if isinstance(js, dict):
        js["_parser"] = f"llm:{llm.model}"
        return js
    return None


def answer(qid, text, store=None, reg=None):
    store = store or get_store()
    reg = reg or get_registry()
    q = store.question(qid)
    if q is None:
        raise ValueError("нет такого вопроса")
    spec = reg.get(q["key"])
    hyp = q.get("hypothesis")
    parsed = llm_parse(spec, text, hyp) or rule_parse(spec, text, hyp)
    # ответ на конфликт кнопкой
    if text.startswith("Верно по расчёту") and hyp:
        parsed = {"value": hyp.get("value"), "confirmed": True, "_parser": "button"}
    store.answer_question(qid, text, parsed)
    if parsed.get("value") is None:
        store.log(AGENT, "unparsed", f"не удалось разобрать ответ: «{text}» — нужен уточняющий вопрос",
                  q["hotel_id"], q["key"], parsed)
        store.commit()
        return {"parsed": parsed, "fact_id": None}
    detail = {k: v for k, v in parsed.items() if not k.startswith("_") and k not in ("value", "confirmed")}
    if parsed.get("from_floor"):
        detail["from_floor_min"] = parsed["from_floor"]
    elif parsed.get("confirmed") and hyp and hyp.get("detail", {}).get("from_floor_min"):
        detail["from_floor_min"] = hyp["detail"]["from_floor_min"]
    scope = _scope_text(spec, parsed, text)
    if parsed.get("confirmed") and hyp and hyp.get("scope") and hyp.get("value") == parsed.get("value"):
        scope = f"{hyp['scope']} — подтвердил отельер"
    conf = 0.9 if parsed.get("confirmed") is not None or spec["type"] != "bool" else 0.85
    fid = store.add_fact(q["hotel_id"], q["key"], parsed["value"], conf, "hotelier",
                         f"ответ отельера на вопрос #{qid}", scope, detail,
                         f"ответ отельера, разобран {PARSER_RU.get(parsed.get('_parser'), parsed.get('_parser'))}", spec["ttl_days"],
                         note=text[:500])
    res = truth.resolve(spec, store.facts(q["hotel_id"], q["key"]), store, q["hotel_id"])
    trust = spec.get("trust", {})
    if res and not res["conflict"]:
        for c in store.conflicts(q["hotel_id"]):
            if c["key"] == q["key"]:
                store.resolve_conflict(c["id"], f"отельер ответил: {text[:200]}")
    elif res and res["conflict"]:
        other = res["conflict"]["with_source"] if res["source_type"] == "hotelier" else res["source_type"]
        gap = trust.get("hotelier", 0.6) - trust.get(other, 0.6)
        for c in store.conflicts(q["hotel_id"]):
            if c["key"] != q["key"]:
                continue
            if gap >= 0.149:
                store.resolve_conflict(c["id"], f"приоритет ответа отельера: доверие {trust.get('hotelier')} против "
                                                f"{trust.get(other)} у источника «{truth.source_name(other)}»")
                store.log(AGENT, "resolve", f"конфликт решён в пользу отельера (разница доверия {gap:.2f})",
                          q["hotel_id"], q["key"])
            else:
                store.log(AGENT, "conflict", f"противоречие с источником «{truth.source_name(other)}» — "
                                             f"оставляем открытым, расчёт поставлен на перепроверку", q["hotel_id"], q["key"])
        # что бы ни было — пересчитать автоматический факт: вдруг изменилась застройка
        for f in store.facts(q["hotel_id"], q["key"]):
            if f["source_type"] in ("geo", "osm_tag"):
                store.expire_fact(f["id"])
        res = truth.resolve(spec, store.facts(q["hotel_id"], q["key"]), store, q["hotel_id"])
    store.log(AGENT, "answer", f"ответ отельера разобран {PARSER_RU.get(parsed.get('_parser'), parsed.get('_parser'))}: {truth.fmt(parsed['value'])}; {scope}",
              q["hotel_id"], q["key"], {"fact_id": fid, "parsed": parsed,
                                        "conflict": bool(res and res["conflict"])})
    store.commit()
    return {"parsed": parsed, "fact_id": fid, "resolved": res}


def _scope_text(spec, p, text=""):
    bits = []
    if p.get("sides"):
        bits.append("стороны: " + ", ".join(p["sides"]))
    if p.get("from_floor"):
        bits.append(f"с {p['from_floor']}-го этажа")
    if p.get("max_weight_kg") is not None:
        bits.append(f"до {p['max_weight_kg']:g} кг")
    if p.get("fee_rub") is not None:
        bits.append("бесплатно" if p["fee_rub"] == 0 else f"{p['fee_rub']} ₽")
    if p.get("animals"):
        bits.append(", ".join(p["animals"]))
    if p.get("elevator") is not None:
        bits.append("есть лифт" if p["elevator"] else "без лифта")
    if p.get("soundproof_windows") is not None:
        bits.append("шумоизоляция окон" if p["soundproof_windows"] else "без шумоизоляции")
    if bits:
        return "; ".join(bits)
    t = text.strip()
    return f"отельер: «{t[:140]}{'…' if len(t) > 140 else ''}»" if t else "со слов отельера"


# ------------------------------------------------------------------ симулятор отельера

def _rng(hotel_id, key):
    return random.Random(int(hashlib.md5(f"{hotel_id}:{key}".encode()).hexdigest()[:8], 16))


def simulate_answer(q, store=None):
    """Отельер-симулятор: у каждого отеля есть детерминированная «скрытая правда».
    В ~20% случаев она расходится с расчётом — чтобы показать работу с противоречиями."""
    store = store or get_store()
    r = _rng(q["hotel_id"], q["key"])
    k = q["key"]
    hyp = q.get("hypothesis") or {}
    llm = get_llm()
    truth_desc = None
    if k == "pets":
        if r.random() < 0.45:
            w, fee = r.choice([5, 7, 10, 15]), r.choice([0, 500, 700, 1000, 1500])
            txt = r.choice([f"Да, с собаками можно, до {w} кг. Доплата {fee} руб в сутки." if fee else
                            f"Да, пускаем небольших собак до {w} кг, бесплатно.",
                            f"Можно с питомцем весом до {w} кг, {fee} ₽ за ночь, кошек тоже берём." if fee else
                            f"Можно, до {w} кг, бесплатно"])
        else:
            txt = r.choice(["К сожалению, с животными не размещаем.", "Нет, с питомцами нельзя."])
    elif k == "blackout":
        txt = r.choice(["Да, во всех номерах плотные шторы блэкаут.", "Есть в номерах категории Комфорт и выше.",
                        "Нет, обычные шторы.", "Нет, только тюль и жалюзи."])
    elif k == "wheelchair":
        txt = r.choice(["Да, есть пандус и лифт, номер для маломобильных гостей.", "Частично: пандус есть, лифта нет.",
                        "Нет, у нас лестница без лифта."])
    elif k == "car_access":
        txt = r.choice(["Да, подъезд к входу есть, своя парковка, бесплатно.",
                        "Подъехать можно, парковка платная 500 руб в сутки.",
                        "Нет, отель в пешеходной зоне, парковка в 200 м."])
    elif k == "construction_nearby":
        txt = r.choice(["Нет, стройка уже закончилась.", "Да, строят жилой дом напротив, днём шумно.",
                        "Стройка закончилась весной."])
    elif k == "quiet_night":
        txt = r.choice(["Да, верно. Во всех номерах двойные стеклопакеты.",
                        "Верно, самые тихие номера — во двор, со стороны улицы летом шумно.",
                        "Нет, у нас тихо со всех сторон — ночью машин почти нет, тихо."])
    elif k == "beach_walk":
        txt = f"{r.choice([3, 5, 7, 10, 15])} минут пешком."
    elif hyp and q["options"] and q["options"][0] in ("Да, верно", "Верно по расчёту"):
        roll = r.random()
        if roll < 0.7:
            txt = r.choice(["Да, верно.", "Да, так и есть.", "Верно"])
        elif roll < 0.85 and k in ("sea_view", "sunset_view", "mountain_view"):
            f = (hyp.get("detail") or {}).get("from_floor_min") or 3
            txt = f"Частично: на самом деле с {f + r.choice([2, 3, 4])}-го этажа, ниже закрывают деревья."
        else:
            txt = r.choice(["Нет, это не так.", "Нет, вид закрыл новый дом."]) if hyp.get("value") is True else \
                "Нет, на самом деле есть — с верхних этажей видно."
    else:
        txt = r.choice(["Да.", "Нет."])
    if llm.available:
        try:
            alt = llm.complete("Ты владелец небольшого отеля в Адлере. Перепиши ответ своими словами, коротко, "
                               "по-разговорному, сохранив смысл, все факты и числа. Начни с того же слова "
                               "(Да/Нет/Частично), если оно есть.",
                               f"Вопрос: {q['text']}\nОтвет: {txt}", max_tokens=200, temperature=0.7)
            if alt and alt.strip():
                txt = alt.strip()
        except Exception as e:  # noqa: BLE001
            print(f"[hotelier-sim] LLM недоступна: {e}")
    return txt
