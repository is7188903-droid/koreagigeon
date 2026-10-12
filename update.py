"""나라장터 공사 키워드 후보 모니터링. 참가 가능 자격은 확인되지 않았음."""
import datetime as dt, json, os, pathlib, urllib.parse, urllib.request
from zoneinfo import ZoneInfo

TZ=ZoneInfo('Asia/Seoul')
API='https://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoCnstwkPPSSrch'
WORDS=('금속','창호','커튼월','샷시','새시','지붕','판금','판넬','패널','캐노피','차양','난간','알루미늄','건축물조립','금속구조물','루버','온실')

def fetch(key,begin,end,page):
    params={'serviceKey':key,'type':'json','pageNo':page,'numOfRows':100,'inqryDiv':'1','inqryBgnDt':begin,'inqryEndDt':end}
    url=API+'?'+urllib.parse.urlencode(params)
    with urllib.request.urlopen(url,timeout=50) as resp: data=json.load(resp)
    response=data.get('response') or {}
    header=response.get('header') or {}
    code=str(header.get('resultCode','00'))
    if code not in ('00','0'):raise RuntimeError('API 오류: '+str(header.get('resultMsg',code)))
    body=response.get('body') or {}
    items=body.get('items') or []
    if isinstance(items,dict):items=items.get('item',[])
    if isinstance(items,dict):items=[items]
    return items,int(body.get('totalCount') or 0)


def permitted_region(x):
    """보수적 표시 규칙: 지역제한을 명시적으로 확인 가능한 공고만 노출."""
    # '공사현장 위치'와 '입찰 참가 업체 소재지'는 서로 다릅니다.
    fields=('prtcptLmtRgnNm','prtcptLmtRgnNms','bidPrtcptLmtRgnNm',
            'rgnLmtNm','rgnLmtRgnNm','rgnLmtInfo','bidPrtcptLmtRgn')
    raw=' '.join(str(x.get(k) or '').strip() for k in fields).strip()
    if raw:
        tokens=raw.replace('，',',').replace('·',',').replace(';',',')
        parts=[p.strip() for p in tokens.split(',') if p.strip()]
        if not parts:return None
        # 조건에 제외·예외·다중 관할 등이 있으면 자동 확정하지 않음
        if any(w in raw for w in ('제외','단,','단 ','예외','본점이전')):return None
        if any(p.replace(' ','') in ('전국','지역제한없음','제한없음') for p in parts):return '전국'
        # 수원시 등 다른 경기도 시군으로 좁게 제한된 건은 포함하지 않음
        if any(p.replace(' ','') in ('경기','경기도','평택','평택시','경기도평택시','경기평택시') for p in parts):return '경기·평택'
        return None
    # 데이터에서 제한 없음이 명확히 드러난 경우만 전국 후보로 허용
    if str(x.get('rgnLmtYn') or '').strip().upper()=='N':
        return '전국(지역제한 없음 표시)'
    return None

def convert(x,now):
    title=str(x.get('bidNtceNm') or '').strip()
    if not any(w in title for w in WORDS):return None
    region=permitted_region(x)
    if not region:return None
    d=str(x.get('bidClseDt') or '').strip()
    try: deadline=dt.datetime.fromisoformat(d.replace(' ','T')).replace(tzinfo=TZ)
    except ValueError:return None
    if deadline<=now:return None
    code=str(x.get('bidNtceNo') or '')
    if not code:return None
    inst=str(x.get('ntceInsttNm') or x.get('dminsttNm') or '')
    category='학교' if any(w in title+inst for w in ('학교','교육청','교육지원청','대학교')) else '공공'
    return {'id':code+'-'+str(x.get('bidNtceOrd') or '00'),'title':title,'agency':inst,'category':category,'region':region,'deadline':d,'amount':x.get('presmptPrce') or x.get('asignBdgtAmt') or None,'url':str(x.get('bidNtceDtlUrl') or ''),'status':'점검필요','eligible_verified':False,'eligibility_checks':{'지역':region,'면허':'원문 검증필요','무실적':'원문 검증필요','업력':'원문 검증필요','여성기업·중소기업':'해당 공고 요구사항 확인필요','자본금·재무요건':'원문 검증필요','현장설명·사전신청':'원문 검증필요'}}

def main():
    key=os.environ.get('G2B_API_KEY','').strip()
    if not key:raise RuntimeError('G2B_API_KEY secret이 없습니다.')
    now=dt.datetime.now(TZ)
    begin=(now-dt.timedelta(days=3)).strftime('%Y%m%d%H%M')
    end=now.strftime('%Y%m%d%H%M')
    rows=[]
    for page in range(1,11):
        batch,total=fetch(key,begin,end,page)
        rows+=batch
        if len(batch)==0 or 100*page>=total:break
    candidates={}
    for row in rows:
        b=convert(row,now)
        if b:candidates[b['id']]=b
    result={'updated_at':now.isoformat(timespec='minutes'),'scanned':len(rows),'status':'경기·평택·전국 명시 공고만 후보 표시; 실적·면허·현장설명회 미검증','bids':[], 'review_count':len(candidates), 'review_candidates':sorted(candidates.values(),key=lambda b:b['deadline'])}
    f=pathlib.Path('docs/data.json');f.parent.mkdir(exist_ok=True)
    f.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print('scanned',len(rows),'review_candidates',len(candidates),'verified_eligible',0)
if __name__=='__main__':main()
