"""관련 업계 뉴스 RSS 제목과 원문 링크를 수집합니다. 선정적 기사나 입찰공고로 오인하지 않도록 별도 표시."""
import urllib.request, urllib.parse, xml.etree.ElementTree as ET, datetime as dt
from zoneinfo import ZoneInfo
QUERY='금속창호 지붕판금 건설 입찰 OR 학교 시설 공사 OR 건설사 협력업체 모집'
def collect():
    url='https://news.google.com/rss/search?'+urllib.parse.urlencode({'q':QUERY,'hl':'ko','gl':'KR','ceid':'KR:ko'})
    try:
        req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0 (compatible; HKG-BidOffice/1.0)'})
        with urllib.request.urlopen(req,timeout=20) as r:root=ET.fromstring(r.read())
        items=[]
        for node in root.findall('./channel/item')[:18]:
            title=(node.findtext('title') or '').strip()
            link=(node.findtext('link') or '').strip()
            date=(node.findtext('pubDate') or '').strip()
            if not title or not link.startswith('https://'):continue
            items.append({'title':title,'url':link,'date':date,'source':'Google 뉴스 검색 RSS'})
        return {'updated_at':dt.datetime.now(ZoneInfo('Asia/Seoul')).isoformat(timespec='minutes'),'status':'Google 뉴스 검색 RSS · 제목/링크만 표시, 개별 기사 내용 미검증','items':items}
    except Exception as e:
        return {'updated_at':dt.datetime.now(ZoneInfo('Asia/Seoul')).isoformat(timespec='minutes'),'status':'뉴스 수집 실패: '+type(e).__name__,'items':[]}
