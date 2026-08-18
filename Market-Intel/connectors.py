"""Legal, server-side collectors. No browser automation, rate-limit bypassing, or hidden APIs."""
from __future__ import annotations
import html, os, re, uuid, zipfile, io
from datetime import datetime
from urllib.parse import quote_plus
import httpx
from xml.etree import ElementTree as ET

UA = "MarketIntel/1.0 (+public-procurement-monitor; contact: admin@example.invalid)"

class ConnectorError(RuntimeError): pass

def clean(s: str) -> str: return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()

def parse_rss(xml: str, source: str) -> list[dict]:
    root=ET.fromstring(xml); rows=[]
    for item in root.findall('.//item'):
        get=lambda tag: (item.findtext(tag) or '').strip()
        title=clean(get('title')); link=get('link'); desc=clean(get('description'))
        if title and link: rows.append({'source':source,'external_id':link,'title':title,'url':link,'body':desc,'published':get('pubDate')})
    return rows

def google_news_rss(query: str) -> list[dict]:
    """A no-key discovery route. It only consumes Google's published RSS response."""
    url='https://news.google.com/rss/search?q='+quote_plus(query)+'&hl=ru&gl=RU&ceid=RU:ru'
    with httpx.Client(timeout=25,headers={'User-Agent':UA},follow_redirects=True) as c:
        r=c.get(url); r.raise_for_status()
    return parse_rss(r.text, 'Google News RSS (discovery)')

def rss(url: str, source='Custom RSS') -> list[dict]:
    if not url.startswith(('https://','http://')): raise ConnectorError('Разрешены только HTTP(S) URL.')
    with httpx.Client(timeout=30,headers={'User-Agent':UA},follow_redirects=True) as c:
        r=c.get(url); r.raise_for_status()
    return parse_rss(r.text,source)

def eis_notice_xml(reg_number: str) -> dict:
    """Public per-notice XML page. It is a user-driven lookup, not a bulk crawler."""
    if not re.fullmatch(r'\d{19}', reg_number): raise ConnectorError('Номер извещения ЕИС должен содержать 19 цифр.')
    url='https://zakupki.gov.ru/epz/order/notice/printForm/viewXml.html?regNumber='+reg_number
    with httpx.Client(timeout=35,headers={'User-Agent':UA},follow_redirects=True) as c:
        r=c.get(url); r.raise_for_status()
    return {'source':'ЕИС: карточка извещения','external_id':reg_number,'title':'Извещение ЕИС '+reg_number,'url':url,'body':clean(r.text),'published':''}

def eis_service_info() -> dict:
    return {'endpoint':'https://int44.zakupki.gov.ru/eis-integration/services/getDocsIP','token_env':'EIS_INDIVIDUAL_TOKEN','status':'needs_token' if not os.getenv('EIS_INDIVIDUAL_TOKEN') else 'configured'}

def b2b_info() -> dict:
    return {'endpoint':'https://www.b2b-center.ru/market/remote.html?wsdl','login_env':'B2B_CENTER_LOGIN','password_env':'B2B_CENTER_PASSWORD','status':'needs_credentials' if not os.getenv('B2B_CENTER_LOGIN') else 'configured'}
