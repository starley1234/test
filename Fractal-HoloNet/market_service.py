"""Market radar for finding buyers of industrial switching equipment.

Run: uvicorn market_service:app --host 0.0.0.0 --port 8080
The app deliberately keeps a human verification step: a public mention is a lead,
not evidence of a completed purchase.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Literal
from urllib.parse import quote_plus

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

app = FastAPI(title="Контур · Радар рынка", version="0.1.0")

# These are clearly demo rows so no synthetic company is ever shown as a real buyer.
LEADS = [
    {"id": 1, "company": "Демонстрационный завод №1", "industry": "Машиностроение", "region": "Свердловская область", "signal": "Запрос на промежуточные реле 24 V DC", "brand": "Finder / Omron", "category": "Промежуточные реле", "score": 87, "status": "Новый", "source": "ЕИС / открытая закупка", "url": "https://zakupki.gov.ru/epz/order/extendedsearch/results.html?searchString=%D0%BF%D1%80%D0%BE%D0%BC%D0%B5%D0%B6%D1%83%D1%82%D0%BE%D1%87%D0%BD%D0%BE%D0%B5+%D1%80%D0%B5%D0%BB%D0%B5", "updated": "18.08.2026"},
    {"id": 2, "company": "Демонстрационная водоканальная служба", "industry": "Водоснабжение", "region": "Республика Татарстан", "signal": "В спецификации упомянуты модульные контакторы", "brand": "Schneider Electric", "category": "Контакторы", "score": 81, "status": "В работе", "source": "ЕИС / открытая закупка", "url": "https://zakupki.gov.ru/epz/order/extendedsearch/results.html?searchString=%D0%BC%D0%BE%D0%B4%D1%83%D0%BB%D1%8C%D0%BD%D1%8B%D0%B9+%D0%BA%D0%BE%D0%BD%D1%82%D0%B0%D0%BA%D1%82%D0%BE%D1%80", "updated": "17.08.2026"},
    {"id": 3, "company": "Демонстрационный пищевой комбинат", "industry": "Пищевая промышленность", "region": "Московская область", "signal": "Ремонт шкафа управления; требуются интерфейсные реле", "brand": "Phoenix Contact", "category": "Интерфейсные реле", "score": 74, "status": "Проверка", "source": "Корпоративная закупка", "url": "https://www.b2b-center.ru/market/", "updated": "16.08.2026"},
    {"id": 4, "company": "Демонстрационный нефтесервис", "industry": "Нефтегаз", "region": "ХМАО", "signal": "Поставка реле контроля фаз для КИПиА", "brand": "Siemens", "category": "Реле контроля", "score": 92, "status": "Новый", "source": "Фабрикант / открытая площадка", "url": "https://www.fabrikant.ru/trades", "updated": "18.08.2026"},
    {"id": 5, "company": "Демонстрационный горно-обогатительный комбинат", "industry": "Горнодобыча", "region": "Красноярский край", "signal": "ЗИП: тепловые реле и основания", "brand": "ABB", "category": "Тепловые реле", "score": 69, "status": "Архив", "source": "ЕИС / открытая закупка", "url": "https://zakupki.gov.ru/epz/order/extendedsearch/results.html?searchString=%D1%82%D0%B5%D0%BF%D0%BB%D0%BE%D0%B2%D0%BE%D0%B5+%D1%80%D0%B5%D0%BB%D0%B5", "updated": "11.08.2026"},
]

ANALOGUES = {
    "Промежуточные реле": {"product": "РЭК77 / Реле и автоматика", "fit": "Катушка 24 V DC, 2CO/4CO; сверить ток контактов и цоколь", "confidence": 82},
    "Контакторы": {"product": "КМИ / IEK", "fit": "Подобрать по AC-3, напряжению катушки, доп. контактам", "confidence": 76},
    "Интерфейсные реле": {"product": "Реле на DIN-рейку ОВЕН", "fit": "Сверить тип контакта, LED-индикацию, габарит и клеммы", "confidence": 72},
    "Реле контроля": {"product": "Реле контроля фаз РКФ / Новатек-Электро", "fit": "Сверить сеть, пороги и задержки срабатывания", "confidence": 78},
    "Тепловые реле": {"product": "РТЛ / КЭАЗ", "fit": "Подобрать диапазон тока, класс расцепления и стыковку с пускателем", "confidence": 70},
}

class ScanRequest(BaseModel):
    query: str = Field(min_length=2, max_length=180)
    sources: list[str] = []
    regions: list[str] = []

class QualifyRequest(BaseModel):
    title: str = Field(min_length=5, max_length=500)
    text: str = Field(min_length=10, max_length=10000)
    source_url: str = ""

TERMS = {
    "Промежуточные реле": ["промежуточн", "finder", "omron", "реле 24"],
    "Контакторы": ["контактор", "schneider", "telemecanique", "abb"],
    "Интерфейсные реле": ["интерфейсн", "phoenix contact", "plc-rsc"],
    "Реле контроля": ["контроля фаз", "реле напряжения", "siemens"],
    "Тепловые реле": ["тепловое реле", "перегрузк"],
}

def classify(text: str):
    low = text.lower()
    found = [(cat, sum(t in low for t in terms)) for cat, terms in TERMS.items()]
    category, hits = max(found, key=lambda x: x[1])
    if not hits:
        category = "Промежуточные реле"
    return category

@app.get("/api/leads")
def leads(status: str | None = None, q: str | None = None):
    result = LEADS
    if status and status != "Все": result = [x for x in result if x["status"] == status]
    if q:
        needle = q.lower(); result = [x for x in result if needle in " ".join(map(str, x.values())).lower()]
    return {"items": result, "demo": True, "total": len(result)}

@app.post("/api/scan")
def scan(payload: ScanRequest):
    """Returns the source search links and matching demo signals.
    Production adapters should ingest official feeds/API exports then call /qualify.
    """
    q = quote_plus(payload.query)
    sources = [
        {"name": "ЕИС — реестр закупок", "kind": "Госзакупки", "url": f"https://zakupki.gov.ru/epz/order/extendedsearch/results.html?searchString={q}", "note": "Ищите ТЗ, спецификации и протоколы. Учитывайте 44‑ФЗ и 223‑ФЗ."},
        {"name": "B2B-Center", "kind": "Коммерческие закупки", "url": f"https://www.b2b-center.ru/market/?search={q}", "note": "Открытые коммерческие запросы и аккредитации."},
        {"name": "Фабрикант", "kind": "Коммерческие закупки", "url": f"https://www.fabrikant.ru/trades?search={q}", "note": "Проверяйте актуальность публикации и условия доступа."},
        {"name": "Контур.Закупки", "kind": "Агрегатор", "url": f"https://zakupki.kontur.ru/search?query={q}", "note": "Удобный вторичный поиск; первоисточник обязателен для верификации."},
    ]
    matched = [x for x in LEADS if any(word in (x["signal"]+x["brand"]+x["category"]).lower() for word in payload.query.lower().split())]
    return {"query": payload.query, "sources": sources, "matches": matched, "message": "Поиск по источникам сформирован. Результаты из демо-набора не являются фактом закупки."}

@app.post("/api/qualify")
def qualify(payload: QualifyRequest):
    text = (payload.title + " " + payload.text).lower()
    category = classify(text)
    spec = []
    for label, pattern in [("напряжение", r"\b(?:12|24|110|220|230|380)\s*[вv]"), ("ток", r"\b\d+(?:[.,]\d+)?\s*[аa]\b"), ("артикул", r"\b[A-ZА-Я]{2,}[\w/-]{2,}\b")]:
        values = re.findall(pattern, payload.title + " " + payload.text, re.I)
        if values: spec.append(f"{label}: {', '.join(values[:3])}")
    foreign = [b for b in ["Schneider", "Siemens", "ABB", "Finder", "Omron", "Phoenix Contact", "Eaton"] if b.lower() in text]
    score = min(95, 45 + 12 * len(spec) + 13 * bool(foreign) + 10 * ("поставка" in text or "закуп" in text))
    return {"category": category, "score": score, "foreign_brands": foreign, "specifications": spec or ["Не извлечены — запросите спецификацию/опросный лист"], "analogue": ANALOGUES[category], "verdict": "Приоритетный лид" if score >= 75 else "Нужна ручная проверка", "checks": ["Откройте первоисточник и подтвердите статус процедуры.", "Проверьте срок, объём, допуски и совместимость в ТЗ.", "Не используйте упоминание бренда как подтверждение покупки."]}

@app.get("/", response_class=HTMLResponse)
def home():
    return HTML

HTML = r'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Контур — Радар рынка</title><style>
*{box-sizing:border-box}body{margin:0;background:#09111f;color:#eaf0fb;font:14px Inter,ui-sans-serif,system-ui,sans-serif}.shell{max-width:1440px;margin:auto;padding:28px 32px 60px}.top{display:flex;justify-content:space-between;align-items:center}.brand{font-weight:750;font-size:20px;letter-spacing:-.5px}.brand b{color:#72e0b8}.badge{color:#9eb0c9;background:#132137;border:1px solid #263b58;padding:7px 11px;border-radius:99px;font-size:12px}.hero{display:flex;justify-content:space-between;gap:30px;align-items:end;padding:58px 0 32px}.eyebrow{color:#72e0b8;text-transform:uppercase;font-size:11px;letter-spacing:1.4px;font-weight:700}.hero h1{font-size:42px;line-height:1.07;max-width:740px;letter-spacing:-1.5px;margin:12px 0}.hero p{color:#9eb0c9;max-width:670px;font-size:16px;line-height:1.55}.stats{display:flex;gap:12px}.stat,.card{background:#101b2d;border:1px solid #233753;border-radius:14px}.stat{min-width:135px;padding:15px}.stat strong{display:block;font-size:25px}.muted{color:#8fa3c0;font-size:12px}.grid{display:grid;grid-template-columns:340px 1fr;gap:16px}.card{padding:19px}.card h2{font-size:15px;margin:0 0 16px}.search{display:flex;gap:8px}.search input,.field textarea{background:#091423;border:1px solid #29415f;border-radius:9px;padding:11px;color:white;width:100%;outline:none}.search input:focus,.field textarea:focus{border-color:#72e0b8}button{border:0;border-radius:9px;background:#72e0b8;color:#082018;font-weight:750;padding:11px 14px;cursor:pointer}button.secondary{background:#1a2c45;color:#cee0fa}.sources{margin-top:18px}.source{padding:13px 0;border-bottom:1px solid #22334d}.source:last-child{border:0}.source a{color:#dce9fc;font-weight:650;text-decoration:none;display:block}.source small{display:block;color:#8fa3c0;line-height:1.4;margin-top:4px}.table-card{padding:0;overflow:hidden}.table-head{padding:19px;display:flex;justify-content:space-between;align-items:center}.filters button{padding:6px 9px;font-size:11px;margin-left:4px}.filters .active{background:#72e0b8;color:#082018}table{border-collapse:collapse;width:100%;text-align:left}th{font-size:11px;color:#8fa3c0;text-transform:uppercase;letter-spacing:.6px;background:#0c1728;padding:11px 15px}td{padding:13px 15px;border-top:1px solid #20324d;vertical-align:top}.company{font-weight:700}.signal{max-width:300px;color:#c7d3e7}.pill{padding:4px 8px;border-radius:30px;font-size:11px;display:inline-block;background:#1c304a;color:#c5d8ef}.score{font-weight:800;color:#72e0b8}.notice{margin-top:16px;padding:13px 15px;background:#16233a;border-left:3px solid #f4c766;border-radius:7px;color:#b9c8dc;line-height:1.45}.wide{margin-top:16px}.qualify{display:grid;grid-template-columns:1fr 1fr;gap:16px}.field label{display:block;color:#aabbd2;margin:0 0 7px;font-size:12px}.field textarea{resize:vertical;min-height:120px}.result{background:#0b1728;border:1px dashed #375170;border-radius:10px;padding:16px;line-height:1.6}.result strong{font-size:16px}.hidden{display:none}@media(max-width:950px){.grid{grid-template-columns:1fr}.hero{display:block}.stats{margin-top:22px}.hero h1{font-size:34px}.shell{padding:20px}.table-card{overflow:auto}.qualify{grid-template-columns:1fr}}
</style></head><body><main class="shell"><header class="top"><div class="brand"><b>●</b> Контур / Радар рынка</div><span class="badge">public intelligence · human verified</span></header><section class="hero"><div><div class="eyebrow">B2B-поиск для российских производителей</div><h1>Найдите спрос на реле и коммутационную аппаратуру</h1><p>Собирайте публичные сигналы из закупок, выделяйте западные бренды в ТЗ и сопоставляйте их с российскими аналогами — до первого звонка.</p></div><div class="stats"><div class="stat"><strong>5</strong><span class="muted">демо-сигналов</span></div><div class="stat"><strong>4</strong><span class="muted">источника</span></div><div class="stat"><strong>79</strong><span class="muted">ср. потенциал</span></div></div></section><section class="grid"><aside class="card"><h2>Запустить разведку</h2><div class="search"><input id="query" value="промежуточное реле 24V" aria-label="Поисковый запрос"><button onclick="scan()">Искать</button></div><div class="sources" id="sources"><div class="source"><b>Как это работает</b><small>Сервис создаёт воспроизводимые поисковые маршруты по открытым источникам. Подтверждение закупки — только после открытия первоисточника.</small></div></div></aside><section class="card table-card"><div class="table-head"><h2>Очередь на квалификацию</h2><div class="filters"><button class="secondary active" onclick="loadLeads('Все',this)">Все</button><button class="secondary" onclick="loadLeads('Новый',this)">Новые</button><button class="secondary" onclick="loadLeads('В работе',this)">В работе</button></div></div><table><thead><tr><th>Организация / отрасль</th><th>Сигнал</th><th>Западный образец</th><th>Потенциал</th><th>Источник</th></tr></thead><tbody id="rows"></tbody></table></section></section><div class="notice"><b>Режим демонстрации.</b> Карточки организаций синтетические и показывают формат результата, а не сведения о реальных покупках. Для рабочего контура подключайте разрешённые API/выгрузки площадок, соблюдайте их условия использования и фиксируйте URL, дату и текст первоисточника.</div><section class="card wide"><h2>Квалификатор документа</h2><div class="qualify"><div><div class="field"><label>Название закупки или лота</label><input id="title" value="Поставка интерфейсных реле Phoenix Contact 24 V" style="width:100%;background:#091423;border:1px solid #29415f;border-radius:9px;padding:11px;color:#fff"></div><div class="field" style="margin-top:12px"><label>Фрагмент ТЗ / спецификации</label><textarea id="text">Требуется поставка реле на DIN-рейку, катушка 24 В DC, для шкафа автоматики. Допускается эквивалент при подтверждении характеристик.</textarea></div><button style="margin-top:12px" onclick="qualify()">Проанализировать фрагмент</button></div><div id="result" class="result">Вставьте фрагмент публичного документа. Система извлечёт признаки, предложит класс российского аналога и список обязательных проверок.</div></div></section></main><script>
function esc(s){return String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
async function loadLeads(status='Все',btn){let d=await fetch('/api/leads?status='+encodeURIComponent(status)).then(r=>r.json());document.querySelector('#rows').innerHTML=d.items.map(x=>`<tr><td><div class="company">${esc(x.company)}</div><span class="muted">${esc(x.industry)} · ${esc(x.region)}</span></td><td class="signal">${esc(x.signal)}</td><td><span class="pill">${esc(x.brand)}</span><div class="muted" style="margin-top:5px">${esc(x.category)}</div></td><td><span class="score">${x.score}/100</span><div class="muted">${esc(x.status)}</div></td><td><a href="${esc(x.url)}" target="_blank" rel="noopener" style="color:#72e0b8">Открыть ↗</a><div class="muted">${esc(x.source)}</div></td></tr>`).join('');if(btn){document.querySelectorAll('.filters button').forEach(b=>b.classList.remove('active'));btn.classList.add('active')}}
async function scan(){let q=document.querySelector('#query').value;let d=await fetch('/api/scan',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({query:q})}).then(r=>r.json());document.querySelector('#sources').innerHTML=d.sources.map(s=>`<div class="source"><a href="${s.url}" target="_blank" rel="noopener">${esc(s.name)} ↗</a><small>${esc(s.kind)} · ${esc(s.note)}</small></div>`).join('')}
async function qualify(){let out=document.querySelector('#result');out.textContent='Анализируем признаки…';let d=await fetch('/api/qualify',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title:title.value,text:text.value})}).then(r=>r.json());out.innerHTML=`<span class="pill">${esc(d.verdict)} · ${d.score}/100</span><br><strong>${esc(d.category)} → ${esc(d.analogue.product)}</strong><br><span class="muted">Совместимость: ${esc(d.analogue.fit)} · уверенность ${d.analogue.confidence}%</span><br><b>Найдены бренды:</b> ${d.foreign_brands.length?d.foreign_brands.map(esc).join(', '):'не выделены'}<br><b>Признаки:</b> ${d.specifications.map(esc).join('; ')}<br><span class="muted">${d.checks.map(esc).join(' ')}</span>`}
loadLeads();</script></body></html>'''
