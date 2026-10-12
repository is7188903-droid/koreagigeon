"""업계 뉴스 RSS 제목·링크 수집. 입찰공고가 아니므로 화면에서 별도 탭으로만 표시."""
import urllib.request, urllib.parse, xml.etree.ElementTree as ET, datetime as dt
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo('Asia/Seoul')
QUERIES = ('금속창호 공사', '지붕 판금 공사', '학교 시설 창호 교체', '건설 협력업체 모집', '전문건설 입찰 제도')


def fetch(q):
    url = 'https://news.google.com/rss/search?' + urllib.parse.urlencode(
        {'q': q + ' when:14d', 'hl': 'ko', 'gl': 'KR', 'ceid': 'KR:ko'})
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (compatible; HKG-BidOffice/1.1)'})
    with urllib.request.urlopen(req, timeout=20) as r:
        return ET.fromstring(r.read()).findall('./channel/item')


def collect():
    now = dt.datetime.now(TZ).isoformat(timespec='minutes')
    items, seen, errors = [], set(), 0
    for q in QUERIES:
        try:
            nodes = fetch(q)
        except Exception:
            errors += 1
            continue
        for n in nodes[:8]:
            title = (n.findtext('title') or '').strip()
            link = (n.findtext('link') or '').strip()
            if not title or not link.startswith('https://') or title in seen:
                continue
            seen.add(title)
            try:
                date = parsedate_to_datetime(n.findtext('pubDate') or '').astimezone(TZ).isoformat(timespec='minutes')
            except Exception:
                date = ''
            press = (n.findtext('source') or '').strip()
            items.append({'title': title, 'url': link, 'date': date, 'press': press, 'topic': q})
    items.sort(key=lambda x: x['date'], reverse=True)
    status = '정상' if items else ('수집 실패' if errors == len(QUERIES) else '해당 기사 없음')
    return {'updated_at': now, 'status': status, 'items': items[:30]}
