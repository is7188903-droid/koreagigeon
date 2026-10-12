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

def convert(x,now):
    title=str(x.get('bidNtceNm') or '').strip()
    if not any(w in title for w in WORDS):return None
    d=str(x.get('bidClseDt') or '').strip()
    try: deadline=dt.datetime.fromisoformat(d.replace(' ','T')).replace(tzinfo=TZ)
    except ValueError:return None
    if deadline<=now:return None
    code=str(x.get('bidNtceNo') or '')
    if not code:return None
    inst=str(x.get('ntceInsttNm') or x.get('dminsttNm') or '')
    category='학교' if any(w in title+inst for w in ('학교','교육청','교육지원청','대학교')) else '공공'
    return {'id':code+'-'+str(x.get('bidNtceOrd') or '00'),'title':title,'agency':inst,'category':category,'deadline':d,'amount':x.get('presmptPrce') or x.get('asignBdgtAmt') or None,'url':str(x.get('bidNtceDtlUrl') or ''),'status':'점검필요'}

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
    result={'updated_at':now.isoformat(timespec='minutes'),'scanned':len(rows),'status':'참가자격 및 필수 현장설명회 미검증','bids':sorted(candidates.values(),key=lambda b:b['deadline'])}
    f=pathlib.Path('docs/data.json');f.parent.mkdir(exist_ok=True)
    f.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print('scanned',len(rows),'candidates',len(candidates))
if __name__=='__main__':main()
