from __future__ import annotations
import os, re, sqlite3, hashlib
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, HttpUrl
from connectors import google_news_rss, rss, eis_notice_xml, eis_service_info, b2b_info, ConnectorError

ROOT=Path(__file__).parent; DB=ROOT/'market_intel.db'
app=FastAPI(title='Market Intel',version='1.0.0')

def db():
 c=sqlite3.connect(DB);c.row_factory=sqlite3.Row;return c

def setup():
 with closing(db()) as c:
  c.executescript('''CREATE TABLE IF NOT EXISTS leads (id INTEGER PRIMARY KEY, source TEXT NOT NULL, external_id TEXT NOT NULL UNIQUE, title TEXT NOT NULL, url TEXT NOT NULL, body TEXT, published TEXT, collected_at TEXT NOT NULL, category TEXT, brands TEXT, score INTEGER, status TEXT NOT NULL DEFAULT 'new');''');c.commit()
setup()
BRANDS=['Schneider Electric','Schneider','Siemens','ABB','Finder','Omron','Phoenix Contact','Eaton','Weidmüller','WAGO','Legrand','Allen-Bradley']
CATS={'Промежуточные реле':['промежуточн','реле 24','finder','omron'],'Интерфейсные реле':['интерфейсн','phoenix contact','plc-rsc'],'Контакторы':['контактор','пускател'],'Реле контроля и защиты':['контроля фаз','реле напряжения','реле времени'],'Тепловые реле':['тепловое реле','реле перегруз']}
AN={'Промежуточные реле':'РЭК77 / Реле и автоматика','Интерфейсные реле':'ОВЕН: интерфейсные реле DIN','Контакторы':'КМИ / IEK или КЭАЗ','Реле контроля и защиты':'Новатек-Электро: реле контроля','Тепловые реле':'КЭАЗ: тепловые реле'}
def analyse(text):
 low=text.lower(); cat=max(CATS,key=lambda k:sum(x in low for x in CATS[k])); hits=sum(x in low for x in CATS[cat]); brands=[x for x in BRANDS if x.lower() in low]
 spec=re.findall(r'(?i)\b(?:12|24|48|110|220|230|380)\s*(?:в|v)|\b\d+(?:[,.]\d+)?\s*(?:а|a)\b',text)
 score=min(100,20+20*bool(brands)+15*min(hits,2)+10*min(len(spec),3)+20*any(x in low for x in ['закуп','поставка','техническ','тз','спецификац']))
 return cat,brands,spec,score

def upsert(items):
 added=0
 with closing(db()) as c:
  for x in items:
   cat,b,s,score=analyse(x['title']+' '+x.get('body',''))
   cur=c.execute('INSERT OR IGNORE INTO leads(source,external_id,title,url,body,published,collected_at,category,brands,score) VALUES(?,?,?,?,?,?,?,?,?,?)',(x['source'],x['external_id'],x['title'],x['url'],x.get('body',''),x.get('published',''),datetime.now(timezone.utc).isoformat(),cat,', '.join(b),score));added+=cur.rowcount
  c.commit()
 return added
class Discover(BaseModel): query:str
class Feed(BaseModel): url:str; name:str='Custom RSS'
class Notice(BaseModel): reg_number:str
class TextLead(BaseModel): title:str; text:str; url:str=''
@app.get('/api/leads')
def leads(q:str='',min_score:int=0):
 with closing(db()) as c: rows=c.execute("SELECT * FROM leads WHERE score>=? AND (title||' '||body) LIKE ? ORDER BY collected_at DESC,score DESC",(min_score,'%'+q+'%')).fetchall()
 return {'items':[dict(x) for x in rows],'total':len(rows),'real_data_only':True}
@app.post('/api/discover')
def discover(p:Discover):
 try: items=google_news_rss(p.query); return {'found':len(items),'added':upsert(items),'connector':'Google News RSS — discovery only; open original source before outreach'}
 except Exception as e: raise HTTPException(502,f'Источник временно недоступен: {e}')
@app.post('/api/rss')
def add_rss(p:Feed):
 try: items=rss(p.url,p.name);return {'found':len(items),'added':upsert(items)}
 except Exception as e: raise HTTPException(502,str(e))
@app.post('/api/eis/notice')
def eis(p:Notice):
 try: x=eis_notice_xml(p.reg_number); return {'added':upsert([x]),'url':x['url']}
 except ConnectorError as e: raise HTTPException(422,str(e))
 except Exception as e: raise HTTPException(502,f'ЕИС не ответила: {e}')
@app.post('/api/manual')
def manual(p:TextLead):
 if len(p.text)<30: raise HTTPException(422,'Нужно не менее 30 символов текста документа.')
 x={'source':'Пользовательский первоисточник','external_id':p.url or 'manual:'+hashlib.sha256((p.title+p.text).encode()).hexdigest(),'title':p.title,'url':p.url or 'about:blank','body':p.text,'published':''};return {'added':upsert([x])}
@app.get('/api/config')
def config(): return {'eis':eis_service_info(),'b2b_center':b2b_info(),'docs':'/docs'}
@app.get('/api/lead/{lead_id}')
def lead(lead_id:int):
 with closing(db()) as c: x=c.execute('SELECT * FROM leads WHERE id=?',(lead_id,)).fetchone()
 if not x: raise HTTPException(404,'Не найдено')
 d=dict(x);d['analogue']=AN.get(d['category']);d['requirements']=['Открыть первичный документ и подтвердить актуальность процедуры.','Сверить артикул, напряжение катушки, ток/категорию применения, контакты, монтаж, сертификаты.','Уточнить: допускается ли эквивалент и как требуется доказать соответствие.'];return d
@app.get('/',response_class=HTMLResponse)
def home(): return HTML
HTML='''<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Market Intel</title><style>body{margin:0;background:#08111e;color:#ebf2fc;font:14px system-ui}.wrap{max-width:1200px;margin:auto;padding:36px 24px}h1{font-size:40px;margin:10px 0}.k{color:#73dfb7;text-transform:uppercase;letter-spacing:1.5px;font-size:11px;font-weight:bold}.sub{color:#9fb0c9;max-width:760px;line-height:1.6;font-size:16px}.grid{display:grid;grid-template-columns:360px 1fr;gap:16px;margin-top:30px}.card{background:#101c2f;border:1px solid #233a58;border-radius:14px;padding:18px}h2{font-size:15px;margin:0 0 13px}input,textarea{background:#091524;border:1px solid #2c4666;border-radius:8px;padding:11px;color:white;box-sizing:border-box;width:100%;margin:4px 0 9px}button{background:#73dfb7;border:0;border-radius:8px;padding:11px 13px;color:#062016;font-weight:750;cursor:pointer}.small{color:#9fb0c9;font-size:12px;line-height:1.5}.notice{border-left:3px solid #e9bf5b;background:#1b273b;padding:13px;margin-top:15px;border-radius:6px;line-height:1.5}table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:11px;border-bottom:1px solid #233a58;vertical-align:top}th{color:#9fb0c9;font-size:11px;text-transform:uppercase}.score{color:#73dfb7;font-weight:bold}a{color:#73dfb7}.row{margin-top:13px}@media(max-width:800px){.grid{grid-template-columns:1fr}h1{font-size:30px}}</style><main class="wrap"><div class="k">Реальные публичные сигналы · без демо-данных</div><h1>Market Intel: спрос на промышленные реле</h1><p class="sub">Собирает только записи, полученные сейчас из подключённого источника или вставленного вами первичного документа. Никаких вымышленных компаний, закупок или контактов.</p><div class="grid"><aside class="card"><h2>1 · Обнаружение</h2><input id="q" value="промежуточное реле закупка"><button onclick="discover()">Искать в открытой выдаче</button><p class="small">No-key discovery: Google News RSS. Результат — наводка; перед действием обязательно откройте оригинальную карточку.</p><div class="row"><h2>2 · ЕИС по номеру</h2><input id="n" placeholder="19 цифр извещения"><button onclick="eis()">Импортировать карточку</button></div><div class="row"><h2>3 · RSS источника</h2><input id="feed" placeholder="https://…/feed.xml"><button onclick="feed()">Подключить RSS</button></div><div class="row"><h2>Документ вручную</h2><input id="t" placeholder="Название"><textarea id="body" placeholder="Вставьте текст ТЗ или спецификации"></textarea><button onclick="manual()">Квалифицировать</button></div></aside><section><div class="card"><h2>Реестр найденных сигналов <span id="total" class="small"></span></h2><div id="msg" class="small">Запустите поиск или импортируйте номер ЕИС.</div><div style="overflow:auto"><table><thead><tr><th>Документ / источник</th><th>Категория</th><th>Западный бренд</th><th>Оценка</th></tr></thead><tbody id="rows"></tbody></table></div></div><div class="notice"><b>Этика и точность.</b> Упоминание бренда или слова «реле» не доказывает намерение купить. Сервис оценивает текст, а решение о контакте принимает человек после проверки URL, статуса, ТЗ и разрешения на эквивалент.</div></section></div></main><script>const msg=x=>document.querySelector('#msg').textContent=x;async function req(url,body){let r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});let d=await r.json();if(!r.ok)throw Error(d.detail||'Ошибка');return d}async function load(){let d=await fetch('/api/leads').then(x=>x.json());total.textContent='· '+d.total;rows.innerHTML=d.items.map(x=>`<tr><td><a target="_blank" href="${x.url}">${x.title}</a><br><span class="small">${x.source}</span></td><td>${x.category||'—'}</td><td>${x.brands||'—'}</td><td class="score">${x.score}/100</td></tr>`).join('')}async function discover(){try{msg('Идёт запрос к источнику…');let d=await req('/api/discover',{query:q.value});msg(`Получено ${d.found}; добавлено новых: ${d.added}. ${d.connector}`);load()}catch(e){msg(e.message)}}async function eis(){try{let d=await req('/api/eis/notice',{reg_number:n.value});msg('Карточка получена.');load()}catch(e){msg(e.message)}}async function feed(){try{let d=await req('/api/rss',{url:feed.value});msg(`RSS: получено ${d.found}, добавлено ${d.added}`);load()}catch(e){msg(e.message)}}async function manual(){try{await req('/api/manual',{title:t.value,text:body.value});msg('Первичный документ добавлен.');load()}catch(e){msg(e.message)}}load()</script>'''
