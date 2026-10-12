#!/usr/bin/env python3
"""HEAT 1 board watcher. No AI. Usage: watch.py [--dry-run]
X source: public api.fxtwitter.com conversation endpoint (no login, no token)."""
import hashlib,json,os,re,sys,time,subprocess,datetime,urllib.request,urllib.parse,fcntl
HERE=os.path.dirname(os.path.abspath(__file__))
CONV="2108488390089801956"
REPO=os.path.dirname(HERE); BOARD=f"{REPO}/heat0.json"
POSTER=f"{HERE}/post_heatmap.py"
STATE=f"{HERE}/state.json"; KNOWN=f"{HERE}/known_accounts.json"
RUNS="/dev/stdout"; FLAGS=f"{HERE}/flags.log"
DRY="--dry-run" in sys.argv
H=lambda s:hashlib.sha256(("heats:"+s.lower()).encode()).hexdigest()[:16]   # handles stored hashed only
JAY="6384dacc9aa7f599"
SPAM={"9b3926fe5f6197f4","61e5404d574b28b1","5445fbedd444aa16","fcaa1d44f7ee2d05"}
EXCL_CA={"FDciMucQ6c13L6g6PpSEuqkr7n3yiREEXyvk3CxZbgKj","3T9bWKDNLgcuCnWECwxtSpcu4e4cgsFnt8o6KuLXwCdW","4L3Ha45J2JDvi7p65yRwUMe8nXmLredQk7i8TGfiX5si"}
EXCL_TICK={"$NO"}
HEAT_CA="D9Tp9J3rVEzHPKAKLCE85ZAoWru1FPRhp1HfpnextvJL"
CA_RE=re.compile(r"(?<![1-9A-HJ-NP-Za-km-z])[1-9A-HJ-NP-Za-km-z]{32,44}(?![1-9A-HJ-NP-Za-km-z])")
REFRESH_SEC=3*3600
UA={"User-Agent":"heats-watch/1.0"}

def now(): return datetime.datetime.now(datetime.timezone.utc)
def log(f,msg):
    with open(f,"a") as h: h.write(f"{datetime.datetime.now().astimezone().isoformat(timespec='seconds')} {'[DRY] ' if DRY else ''}{msg}\n")
def get(url,tries=3):
    for i in range(tries):
        try: return json.load(urllib.request.urlopen(urllib.request.Request(url,headers=UA),timeout=25))
        except Exception as e:
            err=e; time.sleep(2*(i+1))
    raise err
def jload(p,d):
    try: return json.load(open(p))
    except Exception: return d

def fetch_replies():
    out,seen,cur=[],set(),None
    for _ in range(20):
        try: d=get(f"https://api.fxtwitter.com/2/conversation/{CONV}?ranking_mode=recency"+(f"&cursor={urllib.parse.quote(cur)}" if cur else ""))
        except Exception:
            if cur: break   # later pages 404 when exhausted
            raise
        if d.get("code")!=200: raise RuntimeError(f"fxtwitter code {d.get('code')}")
        for t in d.get("replies") or []:
            if t["id"] not in seen: seen.add(t["id"]); out.append(t)
        cur=(d.get("cursor") or {}).get("bottom")
        if not cur or not d.get("replies"): break
    return out

_dex={}
def dex(ca):
    if ca in _dex: return _dex[ca]
    r=None
    try:
        ps=get(f"https://api.dexscreener.com/tokens/v1/solana/{ca}")
        if ps:
            p=max(ps,key=lambda p:(p.get("liquidity") or {}).get("usd") or 0)
            bt=p["baseToken"] if p["baseToken"]["address"]==ca else p["quoteToken"]
            r={"ticker":"$"+bt["symbol"],"pfp":(p.get("info") or {}).get("imageUrl")}
    except Exception as e: log(RUNS,f"dexscreener error {ca}: {e}")
    _dex[ca]=r; return r

def compute(replies,old,known):
    oldby={c["ca"]:c for c in old}
    agg={}; perday=set(); flags=[]
    for t in sorted(replies,key=lambda t:t["created_timestamp"]):
        a=t["author"]
        if a["screen_name"].lower()=="heats_fun": continue
        h=H(a["screen_name"])
        cas=[c for c in dict.fromkeys(CA_RE.findall(t.get("text",""))) if c not in EXCL_CA]
        if not cas: continue
        day=datetime.datetime.fromtimestamp(t["created_timestamp"],datetime.timezone.utc).date()
        if h!=JAY:
            if (h,day) in perday: continue
            perday.add((h,day)); cas=cas[:1]
        for ca in cas:
            if ca in oldby: tick,pfp=oldby[ca]["ticker"],oldby[ca].get("pfp")
            else:
                info=dex(ca)
                if not info: continue   # not a token (wallet / unknown)
                tick,pfp=info["ticker"],info["pfp"]
            if tick.upper() in EXCL_TICK: continue
            c=agg.setdefault(ca,{"ticker":tick,"ca":ca,"pfp":pfp,"base":0,"media":False,"blue":False,"by":[]})
            c["by"].append(h)
            if h in SPAM: continue
            # self-reposts: fxtwitter doesn't expose reposter ids; reposts counted as reported
            c["base"]+=t.get("likes",0)+3*t.get("reposts",0)+min(t.get("replies",0),10)
            if t.get("media"): c["media"]=True
            v=a.get("verification") or {}
            if v.get("verified") or v.get("type") in ("blue","individual","business","government"): c["blue"]=True
            if h not in known and h!=JAY:
                flags.append(f"new account @{a['screen_name']} posted {tick} {ca} https://x.com/i/status/{t['id']} (likes {t.get('likes')}, followers {a.get('followers')})")
    board={c["ca"]:dict(c) for c in old}
    for ca,c in agg.items():
        s=c["base"]+(10 if c["media"] else 0)+(5 if c["blue"] else 0)
        prev=board.get(ca)
        if prev: prev["score"]=max(prev["score"],s)
        elif s>0 or any(b not in SPAM for b in c["by"]):
            board[ca]={"ticker":c["ticker"],"ca":ca,"score":s,"pfp":c["pfp"]}
    coins=sorted(board.values(),key=lambda c:-c["score"])
    return [{"ticker":c["ticker"],"ca":c["ca"],"score":c["score"],"pfp":c.get("pfp")} for c in coins],flags,agg

def git(*a): return subprocess.run(["git","-C",REPO,*a],capture_output=True,text=True,timeout=90)

def main():
    lk=open(f"{HERE}/.lock","w")
    try: fcntl.flock(lk,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except OSError: return
    st=jload(STATE,{}); known=set(jload(KNOWN,[]))
    if not DRY: git("pull","-q","--rebase","origin","main")
    cur=jload(BOARD,{"updatedAt":None,"coins":[]})
    try: replies=fetch_replies()
    except Exception as e: log(RUNS,f"ERROR fetch: {e}"); return 1
    coins,flags,agg=compute(replies,cur["coins"],known)
    oldsig=[(c["ca"],c["score"]) for c in cur["coins"]]; newsig=[(c["ca"],c["score"]) for c in coins]
    changed=sorted(oldsig)!=sorted(newsig) or [c["ca"] for c in cur["coins"]]!=[c["ca"] for c in coins]
    t=now(); last=st.get("last_push",0)
    refresh=not changed and time.time()-last>=REFRESH_SEC
    summary=" ".join(f"{c['ticker']}:{c['score']}" for c in coins)
    for f in flags:
        log(RUNS,"FLAG "+f)   # job log only; nothing about accounts is committed
    if DRY:
        print(json.dumps({"updatedAt":t.isoformat(timespec='milliseconds').replace('+00:00','Z'),"coins":coins},indent=2))
        print("computed (pre-max) per coin:",{v['ticker']:v['base']+(10 if v['media'] else 0)+(5 if v['blue'] else 0) for v in agg.values()})
        print("flags:",flags)
        log(RUNS,f"replies={len(replies)} changed={changed} board={summary} (no write/push/post)"); return 0
    if not changed and not refresh:
        log(RUNS,f"replies={len(replies)} no change"); json.dump(st,open(STATE,"w")); return 0
    git("pull","-q","--rebase","origin","main"); cur2=jload(BOARD,cur)
    if [(c["ca"],c["score"]) for c in cur2["coins"]]!=oldsig:   # remote changed meanwhile: recompute on top
        coins,flags,agg=compute(replies,cur2["coins"],known); summary=" ".join(f"{c['ticker']}:{c['score']}" for c in coins)
    json.dump({"updatedAt":t.isoformat(timespec='milliseconds').replace('+00:00','Z'),"coins":coins},open(BOARD,"w"),indent=2)
    git("add","heat0.json",".watch")
    msg="HEAT1 board: "+summary if changed else "HEAT1 board: refresh updatedAt"
    c=git("commit","-q","-m",msg); git("pull","-q","--rebase","origin","main"); p=git("push","-q","origin","HEAD:main")
    if p.returncode: log(RUNS,f"ERROR push: {p.stderr.strip()}"); return 1
    st["last_push"]=time.time()
    known|=set(agg_h for v in agg.values() for agg_h in v["by"]); json.dump(sorted(known),open(KNOWN,"w"),indent=0)
    post=""
    if changed:
        r=subprocess.run([sys.executable,POSTER,"auto"],capture_output=True,text=True,timeout=120)
        post=f" tg_rc={r.returncode} {(r.stdout+r.stderr).strip()[-200:]}"
        json.dump(st,open(STATE,"w"))
        git("add",".watch"); git("commit","-q","-m","HEAT1 watcher: telegram state")
        git("pull","-q","--rebase","origin","main"); git("push","-q","origin","HEAD:main")
    json.dump(st,open(STATE,"w"))
    log(RUNS,f"replies={len(replies)} {'CHANGED' if changed else 'refresh'} pushed board={summary}{post} | sheet heat1_replies/heat1_runs skipped (MCP-only)")
    return 0
if __name__=="__main__": sys.exit(main() or 0)
