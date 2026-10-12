"""나라장터 공사입찰 수집 → 한국기건 맞춤 후보 판정.

판정 원칙
- 공사명 키워드가 맞는 접수 중 공고는 모두 '후보'로 남긴다(지역정보가 없다고 버리지 않음).
- 참가가능지역·면허제한 상세 API를 공고별로 조회해 '적합 / 확인필요 / 불가'를 매긴다.
- 상세 조회 실패나 정보 누락은 '확인필요'로 표시하고, 명시적으로 다른 지역 전용인 공고만 '불가'로 숨긴다.
- 어떤 경우에도 '참가 확정'은 사람이 원문을 확인한 뒤에만 가능하다.
"""
import datetime as dt, json, os, pathlib, urllib.parse, urllib.request
from zoneinfo import ZoneInfo
from kapt import collect as collect_kapt
from news import collect as collect_news

TZ = ZoneInfo('Asia/Seoul')
BASE = 'https://apis.data.go.kr/1230000/ad/BidPublicInfoService/'
LIST_OP = 'getBidPblancListInfoCnstwkPPSSrch'
REGION_OP = 'getBidPblancListInfoPrtcptPsblRgn'   # 참가가능지역
LICENSE_OP = 'getBidPblancListInfoLicenseLimit'   # 면허제한
WORDS = ('금속', '창호', '커튼월', '샷시', '새시', '지붕', '판금', '판넬', '패널', '캐노피',
         '차양', '난간', '알루미늄', '건축물조립', '금속구조물', '루버', '온실')
OK_REGION = ('전국', '경기', '평택')
OUR_LICENSE = ('금속창호', '지붕', '건축물조립', '금속구조물')
NEAR_SITE = ('경기', '평택', '서울', '인천', '충청남도 아산', '충청남도 천안', '충남 아산', '충남 천안')
# 지역제한 공고는 대개 '공고일 현재 본점 소재지 전입일 다음 날부터 90일 이상'을 요구한다.
# 한국기건: 법인 설립(본점 등기) 2026-08-20, 건설업 등록 2026-09-23.
COMPANY_BASE_DATE = dt.date(2026, 8, 20)
RESIDENCY_DAYS = 90


def call(op, **params):
    q = {'serviceKey': KEY, 'type': 'json', 'pageNo': 1, 'numOfRows': 100}
    q.update(params)
    with urllib.request.urlopen(BASE + op + '?' + urllib.parse.urlencode(q), timeout=40) as r:
        data = json.load(r)
    resp = data.get('response') or {}
    code = str((resp.get('header') or {}).get('resultCode', '00'))
    if code not in ('00', '0'):
        raise RuntimeError(f'{op} 응답 {code} {(resp.get("header") or {}).get("resultMsg", "")}')
    body = resp.get('body') or {}
    items = body.get('items') or []
    if isinstance(items, dict):
        items = items.get('item', [])
    if isinstance(items, dict):
        items = [items]
    return [x for x in items if isinstance(x, dict)], int(body.get('totalCount') or 0)


DETAIL = {REGION_OP: {}, LICENSE_OP: {}}


def bulk(op, begin, end, diag):
    """조회기간 전체의 상세(지역·면허)를 한 번에 받아 공고번호별로 묶는다."""
    out = DETAIL[op]
    try:
        for page in range(1, 41):
            items, total = call(op, inqryDiv='1', inqryBgnDt=begin, inqryEndDt=end, pageNo=page, numOfRows=999)
            if page == 1:
                diag[op + '_total'] = total
                if items:
                    diag[op + '_fields'] = ','.join(list(items[0].keys())[:12])
            for x in items:
                out.setdefault(str(x.get('bidNtceNo') or ''), []).append(x)
            if not items or 999 * page >= total:
                break
    except Exception as e:
        diag['last_error'] = f'{op}: {str(e)[:120]}'


def detail(op, row, diag, ok_key, fail_key):
    no = str(row.get('bidNtceNo') or '')
    if no in DETAIL[op]:
        diag[ok_key] += 1
        return DETAIL[op][no]
    try:  # 일괄 조회에 없으면 공고번호로 한 번 더
        items, _ = call(op, inqryDiv='2', bidNtceNo=no)
        diag[ok_key] += 1
        return items
    except Exception as e:
        diag[fail_key] += 1
        diag['last_error'] = str(e)[:120]
        return None


def region_check(row, diag):
    """참가가능지역 판정. 반환: (상태, 표시문구)"""
    if str(row.get('rgnLmtYn') or '').upper() == 'N':
        return '적합', '지역제한 없음'
    items = detail(REGION_OP, row, diag, 'region_api_ok', 'region_api_fail')
    if items is None:
        return '확인필요', '참가지역 조회 실패 · 원문 확인'
    ord_ = str(row.get('bidNtceOrd') or '')
    names = sorted({str(x.get('prtcptPsblRgnNm') or '').strip() for x in items
                    if not ord_ or str(x.get('bidNtceOrd') or ord_) == ord_} - {''})
    if not names:
        return '확인필요', '참가지역 정보 없음 · 원문 확인'
    text = ', '.join(names)
    # 평택 업체가 들어갈 수 있는 경우만 통과: 전국 / 경기도 전체 / 평택시가 포함된 제한
    def ok(n):
        n = ''.join(n.split())
        return n in ('전국', '경기도', '경기') or '평택' in n
    if any(ok(n) for n in names):
        return '적합', text
    return '불가', text


def notice_date(row):
    for k in ('bidNtceDt', 'rgstDt'):
        v = str(row.get(k) or '').strip()[:10]
        try:
            return dt.date.fromisoformat(v)
        except ValueError:
            continue
    return None


def residency_check(row, region_status, region_text):
    """지역제한 공고에서 본점 소재 기간(90일) 요건을 아직 못 채웠을 수 있으면 '확인필요'로 낮춘다."""
    if region_status != '적합' or str(row.get('rgnLmtYn') or '').upper() == 'N':
        return region_status, region_text
    day = notice_date(row)
    if day is None:
        return '확인필요', region_text + ' · 공고일 미확인(본점 소재 90일 요건 확인)'
    days = (day - COMPANY_BASE_DATE).days
    if days < RESIDENCY_DAYS:
        return '확인필요', region_text + f' · 공고일 기준 본점 소재 {days}일(90일 요건 있으면 미달)'
    return region_status, region_text


def needs_our_license(row):
    """공사명과 무관하게 우리 면허(금속창호·지붕건축물조립 등)를 요구하는 공고인지."""
    for x in DETAIL[LICENSE_OP].get(str(row.get('bidNtceNo') or ''), []):
        if any(k in str(x.get('lcnsLmtNm') or '') for k in OUR_LICENSE):
            return True
    return False


def license_check(row, diag):
    if str(row.get('indstrytyLmtYn') or '').upper() == 'N':
        return '적합', '업종제한 없음'
    items = detail(LICENSE_OP, row, diag, 'license_api_ok', 'license_api_fail')
    if items is None:
        return '확인필요', '면허조건 조회 실패 · 원문 확인'
    names = sorted({str(x.get('lcnsLmtNm') or '').strip() for x in items} - {''})
    if not names:
        return '확인필요', '면허조건 정보 없음 · 원문 확인'
    text = ', '.join(n.split('/')[0] for n in names)
    if any(any(k in n for k in OUR_LICENSE) for n in names):
        return '적합', text
    return '확인필요', text  # 복수·대체 면허 가능성이 있어 숨기지 않음


def convert(row, now, diag):
    title = str(row.get('bidNtceNm') or '').strip()
    if not any(w in title for w in WORDS) and not needs_our_license(row):
        return None
    code = str(row.get('bidNtceNo') or '')
    try:
        deadline = dt.datetime.fromisoformat(str(row.get('bidClseDt') or '').strip().replace(' ', 'T')).replace(tzinfo=TZ)
    except ValueError:
        diag['bad_deadline'] += 1
        return None
    if not code or deadline <= now:
        diag['closed'] += 1
        return None
    region_status, region_text = region_check(row, diag)
    if region_status == '불가':
        diag['region_rejected'] += 1
        return None
    region_status, region_text = residency_check(row, region_status, region_text)
    license_status, license_text = license_check(row, diag)
    inst = str(row.get('ntceInsttNm') or row.get('dminsttNm') or '')
    site = str(row.get('cnstrtsiteRgnNm') or '').strip()
    fit = '적합' if region_status == license_status == '적합' else '확인필요'
    return {
        'id': code + '-' + str(row.get('bidNtceOrd') or '00'),
        'title': title, 'agency': inst,
        'category': '학교' if any(w in title + inst for w in ('학교', '교육청', '교육지원청', '대학교')) else '공공',
        'deadline': deadline.isoformat(timespec='minutes'),
        'amount': row.get('presmptPrce') or row.get('asignBdgtAmt') or None,
        'url': str(row.get('bidNtceDtlUrl') or ''),
        'site': site, 'near': any(k in site for k in NEAR_SITE),
        'region_status': region_status, 'region': region_text,
        'license_status': license_status, 'license': license_text,
        'fit': fit, 'source': '나라장터',
    }


def main():
    global KEY
    KEY = os.environ.get('G2B_API_KEY', '').strip()
    if not KEY:
        raise RuntimeError('G2B_API_KEY secret이 없습니다.')
    now = dt.datetime.now(TZ)
    begin = (now - dt.timedelta(days=10)).strftime('%Y%m%d0000')
    end = now.strftime('%Y%m%d%H%M')
    rows = []
    for page in range(1, 41):
        batch, total = call(LIST_OP, inqryDiv='1', inqryBgnDt=begin, inqryEndDt=end, pageNo=page)
        rows += batch
        if not batch or 100 * page >= total:
            break
    diag = {'scanned': len(rows), 'keyword_match': 0, 'closed': 0, 'bad_deadline': 0, 'region_rejected': 0,
            'region_api_ok': 0, 'region_api_fail': 0, 'license_api_ok': 0, 'license_api_fail': 0, 'last_error': ''}
    bulk(REGION_OP, begin, end, diag)
    bulk(LICENSE_OP, begin, end, diag)
    found = {}
    for row in rows:
        if any(w in str(row.get('bidNtceNm') or '') for w in WORDS):
            diag['keyword_match'] += 1
        elif needs_our_license(row):
            diag['license_match'] = diag.get('license_match', 0) + 1
        b = convert(row, now, diag)
        if b:
            found[b['id'].rsplit('-', 1)[0]] = b  # 정정공고는 최신 차수만
    try:
        apartment, apartment_status = collect_kapt()
    except Exception as e:
        apartment, apartment_status = [], 'K-apt 수집 오류: ' + type(e).__name__
    bids = sorted(found.values(), key=lambda b: (b['fit'] != '적합', not b['near'], b['deadline']))
    result = {
        'updated_at': now.isoformat(timespec='minutes'),
        'g2b_status': '정상' if rows else '수집 0건',
        'apartment_status': apartment_status,
        'diagnostics': diag,
        'bids': bids,
        'apartment_bids': apartment,
    }
    out = pathlib.Path('docs/data.json')
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    pathlib.Path('docs/news.json').write_text(json.dumps(collect_news(), ensure_ascii=False, indent=2), encoding='utf-8')
    print('diagnostics', json.dumps(diag, ensure_ascii=False))
    print('bids', len(bids), 'fit', sum(b['fit'] == '적합' for b in bids), 'apartment', len(apartment), apartment_status)


if __name__ == '__main__':
    main()
