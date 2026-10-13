"""나라장터 공사 낙찰(개찰결과) 수집 → 하도급 영업 대상 건설사 목록.

원리: 종합건설사가 학교·청사 같은 건축공사를 낙찰받으면 창호·지붕·판넬 공정은
전문건설업체에 하도급을 준다. 그래서 '최근 낙찰받은 건축공사 + 낙찰 건설사'가
곧 우리가 연락할 영업 대상이다. (산업의역군 같은 서비스의 '현장' 정보도 같은 원천)
"""
import datetime as dt, json, os, pathlib, urllib.parse, urllib.request
from zoneinfo import ZoneInfo

TZ = ZoneInfo('Asia/Seoul')
ENDPOINTS = (
    'https://apis.data.go.kr/1230000/as/ScsbidInfoService/getScsbidListSttusCnstwk',
    'https://apis.data.go.kr/1230000/ScsbidInfoService/getScsbidListSttusCnstwk',
)
# 창호·지붕·판넬 공정이 들어갈 가능성이 높은 건축공사
BUILD = ('신축', '증축', '개축', '리모델링', '건립', '그린스마트', '교사', '체육관', '강당', '청사',
         '센터', '복합', '도서관', '어린이집', '유치원', '기숙사', '창호', '지붕', '외벽', '외장',
         '판넬', '패널', '커튼월', '개선공사', '환경개선', '증개축', '대수선', '주택', '아파트', '공장', '창고')
SKIP = ('도로', '포장', '상수', '하수', '관로', '하천', '배수로', '전기', '통신', '소방', '조경', '정화조',
        '준설', '교량', '터널', '철도', '측량', '설계', '감리', '용역', '배관', '가로등', '신호', 'CCTV', '보도')
NEAR = ('경기', '평택', '서울', '인천', '아산', '천안', '충청남도', '충남')
MIN_AMOUNT = 300_000_000  # 3억 미만은 자체 시공이 많아 제외


def fetch(key, begin, end, page, diag):
    last = None
    for url in ([diag['endpoint']] if diag.get('endpoint') else ENDPOINTS):
        q = {'serviceKey': key, 'type': 'json', 'pageNo': page, 'numOfRows': 999,
             'inqryDiv': '1', 'inqryBgnDt': begin, 'inqryEndDt': end}
        try:
            with urllib.request.urlopen(url + '?' + urllib.parse.urlencode(q), timeout=50) as r:
                raw = r.read()
            data = json.loads(raw)
        except Exception as e:
            last = f'{url.split("/")[-2]}: {type(e).__name__} {str(e)[:90]}'
            continue
        resp = data.get('response') or {}
        hdr = resp.get('header') or {}
        if str(hdr.get('resultCode', '00')) not in ('00', '0'):
            last = f'{url.split("/")[-2]}: {hdr.get("resultCode")} {hdr.get("resultMsg", "")}'
            continue
        diag['endpoint'] = url
        body = resp.get('body') or {}
        items = body.get('items') or []
        if isinstance(items, dict):
            items = items.get('item', [])
        if isinstance(items, dict):
            items = [items]
        return [x for x in items if isinstance(x, dict)], int(body.get('totalCount') or 0)
    raise RuntimeError(last or '응답 없음')


def collect(days=45):
    key = os.environ.get('G2B_API_KEY', '').strip()
    now = dt.datetime.now(TZ)
    diag = {'scanned': 0, 'matched': 0, 'error': ''}
    if not key:
        return {'updated_at': now.isoformat(timespec='minutes'), 'status': 'G2B_API_KEY 없음', 'diagnostics': diag, 'projects': [], 'companies': []}
    rows = []
    try:
        # 기간이 길면 거부될 수 있어 7일 단위로 나눠 조회
        for k in range(0, days, 7):
            e = now - dt.timedelta(days=k)
            b = now - dt.timedelta(days=min(k + 7, days))
            for page in range(1, 11):
                items, total = fetch(key, b.strftime('%Y%m%d0000'), e.strftime('%Y%m%d%H%M'), page, diag)
                rows += items
                if not items or 999 * page >= total:
                    break
    except Exception as e:
        diag['error'] = str(e)[:200]
    diag['scanned'] = len(rows)
    if rows:
        diag['fields'] = ','.join(list(rows[0].keys())[:25])

    projects = {}
    for x in rows:
        title = str(x.get('bidNtceNm') or '').strip()
        winner = str(x.get('bidwinnrNm') or '').strip()
        if not title or not winner or any(s in title for s in SKIP) or not any(w in title for w in BUILD):
            continue
        try:
            amount = int(float(x.get('sucsfbidAmt') or 0))
        except ValueError:
            amount = 0
        if amount < MIN_AMOUNT:
            continue
        agency = str(x.get('dminsttNm') or '').strip()
        addr = str(x.get('bidwinnrAdrs') or '').strip()
        no = str(x.get('bidNtceNo') or '')
        projects[no or title] = {
            'title': title, 'agency': agency, 'amount': amount,
            'date': str(x.get('rlOpengDt') or x.get('fnlSucsfDate') or x.get('rgstDt') or '')[:10],
            'winner': winner, 'ceo': str(x.get('bidwinnrCeoNm') or '').strip(),
            'address': addr, 'phone': str(x.get('bidwinnrTelNo') or '').strip(),
            'bizno': str(x.get('bidwinnrBizno') or '').strip(),
            'near': any(n in agency + addr for n in NEAR),
            'url': 'https://www.g2b.go.kr/link/PNPE027_01/single/?bidPbancNo=' + no if no else '',
        }
    diag['matched'] = len(projects)
    plist = sorted(projects.values(), key=lambda p: (not p['near'], -p['amount']))

    comp = {}
    for p in plist:
        c = comp.setdefault(p['bizno'] or p['winner'], {'name': p['winner'], 'ceo': p['ceo'], 'address': p['address'],
                                                       'phone': p['phone'], 'near': p['near'], 'count': 0, 'total': 0, 'projects': []})
        c['count'] += 1
        c['total'] += p['amount']
        c['near'] = c['near'] or p['near']
        c['projects'].append(p['title'])
    clist = sorted(comp.values(), key=lambda c: (not c['near'], -c['total']))
    status = (f'최근 {days}일 낙찰 {len(rows)}건 중 건축공사 {len(plist)}건' if rows
              else '낙찰정보 수집 실패 · 공공데이터포털에서 낙찰정보서비스 활용신청 필요할 수 있음')
    return {'updated_at': now.isoformat(timespec='minutes'), 'status': status, 'diagnostics': diag,
            'projects': plist[:150], 'companies': clist[:80]}


if __name__ == '__main__':
    out = collect()
    pathlib.Path('docs/winners.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print('winners', out['status'], json.dumps(out['diagnostics'], ensure_ascii=False)[:600])
