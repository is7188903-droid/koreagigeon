"""K-apt 공동주택 입찰공고 시범 연계. 검증되지 않은 공고는 적격 추천에서 제외."""
import os, json, urllib.request, urllib.parse, datetime as dt, re
from zoneinfo import ZoneInfo

ROOT='https://apis.data.go.kr/1613000/ApHusBidPblAncInfoOfferServiceV3/'
KEYWORDS=('창호','지붕','판넬','패널','금속','커튼월','캐노피','난간','온실','차양','샤시','새시')
TZ=ZoneInfo('Asia/Seoul')
def grab(key, term, page):
    # 공고명 검색 엔드포인트. 신청 API별 호출 파라미터 일치는 최초 실행 로그로 검증합니다.
    params={'serviceKey':key,'pageNo':page,'numOfRows':100,'type':'json','bidPblAncNm':term}
    url=ROOT+'getBidPblAncNmSearchV3?'+urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=25) as resp:
        data=json.load(resp)
    if not isinstance(data,dict):raise RuntimeError('응답이 JSON 객체가 아닙니다')
    return data
def parse_rows(data):
    if not isinstance(data,dict):return []
    body=data.get('response',{}).get('body',{})
    items=body.get('items',[]) if isinstance(body,dict) else []
    if isinstance(items,dict):items=items.get('item',[])
    if isinstance(items,dict):items=[items]
    return [x for x in items if isinstance(x,dict)]
def value(x,*keys):
    for k in keys:
        v=x.get(k)
        if v not in (None,''):return str(v).strip()
    return ''
def parse_close(value):
    if not value:return None
    digits=re.sub(r'\D','',str(value))
    try:
        if len(digits)>=12:
            return dt.datetime.strptime(digits[:12],'%Y%m%d%H%M').replace(tzinfo=TZ)
        if len(digits)==8:
            return dt.datetime.strptime(digits,'%Y%m%d').replace(hour=23,minute=59,tzinfo=TZ)
    except ValueError:pass
    try:return dt.datetime.fromisoformat(str(value).replace(' ','T')).replace(tzinfo=TZ)
    except ValueError:return None

def format_bid(x):
    title=value(x,'bidPblAncNm','bidTitle','bidNm','bidName')
    if not title or not any(w in title for w in KEYWORDS):return None
    no=value(x,'bidNum','bidNo','bidPblAncNo')
    apt=value(x,'hsmpNm','kaptName','aptNm','aptName')
    close=value(x,'bidClosDe','bidClseDt','bidEndDt','bidClosDt','bidEndDe')
    deadline=parse_close(close)
    if not deadline or deadline <= dt.datetime.now(TZ):return None
    # 단지 소재지역(bidArea 등)은 업체 참여 가능 지역이 아닙니다.
    region=value(x,'prtcptLmtRgnNm')
    # 주소/시공지역 정보는 참여업체의 소재지 제한을 의미하지 않음
    if region and region not in ('전국','경기','경기도','평택','평택시','제한없음'):
        return None
    url=value(x,'bidPblAncDtlUrl','bidDtlUrl','bidUrl','url')
    # 원문 URL 확인 불가능한 경우에는 공고 목록 링크로 안내
    if not url.startswith('https://'):url='https://www.k-apt.go.kr/bid/bidList.do'
    return {'id':'kapt-'+(no or re.sub(r'\W','',title+apt)[:55]),'title':title,'agency':apt,'category':'아파트','region':region or '지역제한 원문 점검필요','deadline':deadline.isoformat(timespec='minutes'),'amount':value(x,'bidAmt','bidAmount'),'url':url,'status':'점검필요','fit':'확인필요','region_status':'확인필요','license_status':'확인필요','license':'원문 확인','site':apt,'near':False,'source':'공동주택(K-apt)'}
def collect():
    key=os.getenv('KAPT_API_KEY','').strip()
    if not key:return [],'KAPT_API_KEY 비밀키 미등록'
    rows=[];errors=[]
    for term in ('창호','지붕','판넬','금속','커튼월','캐노피'):
        try:
            data=grab(key,term,1)
            items=parse_rows(data)
            rows.extend(items)
            if not items:
                errors.append(term+': 응답목록 0건 / 응답필드 '+','.join(str(k) for k in list(data.keys())[:6]))
            hdr=(data.get('response') or {}).get('header') or {}
            code=str(hdr.get('resultCode','00'))
            if code not in ('00','0'):errors.append(term+': API 응답 '+code+' '+str(hdr.get('resultMsg','')))
        except Exception as exc:errors.append(term+': '+type(exc).__name__+' '+str(exc)[:100])
    output={}
    for x in rows:
        v=format_bid(x)
        if v:output[v['id']]=v
    state='API 원시자료 '+str(len(rows))+'개 · 공사명 관련 '+str(len(output))+'건 (0건이면 정상 수집 미확인)'
    if errors:state+=' · 일부 호출 오류: '+' / '.join(errors[:2])
    return list(output.values()),state
if __name__=='__main__':
    print(json.dumps(collect(),ensure_ascii=False)[:1000])
