"""
data_fetcher.py v2.0 — BetBoom Edition
Agenda organizada por faixas: AO VIVO, 1h, 3h, 6h, 12h, 1d, 2d, 3d
Cache 5min. Demo rico com 30+ jogos reais.
"""

import requests, re, numpy as np
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

TZ_BRT = timezone(timedelta(hours=-3))
def now_brt(): return datetime.now(tz=TZ_BRT)
def parse_to_brt(s):
    if not s: return None
    try: return datetime.fromisoformat(s.replace("Z","+00:00").replace(" ","T")).astimezone(TZ_BRT)
    except: return None
def minutes_until(dt_str):
    dt=parse_to_brt(dt_str)
    return None if dt is None else (dt-now_brt()).total_seconds()/60

PANDA_TOKEN = "HA0qUDvZ17UqzeicwCYaH95T_OYBJkEBVUwdqn7sI41D1dyFASw"
PANDA_BASE = "https://api.pandascore.co"
PANDA_HEADERS = {"Authorization": f"Bearer {PANDA_TOKEN}"}

_NAME_FIX = {
    "equipe líquida": "Team Liquid",
    "equipe liquid": "Team Liquid",
    "100 ladrões": "100 Thieves",
    "100 ladroes": "100 Thieves",
    "nuvem 9": "Cloud9",
    "equipe vitality": "Team Vitality",
    "time vitality": "Team Vitality",
    "voo de busca": "FlyQuest",
}

def _fix_name(name: str) -> str:
    return _NAME_FIX.get((name or "").lower().strip(), name or "")

def _league_from_name(name: str) -> str:
    n = (name or "").lower()
    mapping = [
        ("lck challengers", "lck_cl"),
        ("cblol academy", "cblol_acad"),
        ("lck", "lck"), ("lpl", "lpl"), ("lec", "lec"),
        ("lcs", "lcs"), ("cblol", "cblol"), ("lla", "lla"),
        ("vcs", "vcs"), ("ljl", "ljl"), ("tcl", "tcl"),
        ("pcs", "pcs"), ("ewc", "ewc"),
    ]
    for key, code in mapping:
        if key in n:
            return code
    return "_unknown"

# ── Canais de stream ──────────────────────────────────────────────────
STREAM_CHANNELS = {
    "lck":"lck","lpl":"lpl","lec":"lec","lcs":"lcs","cblol":"cblol",
    "cblol_acad":"cblol","lck_cl":"lck","tcl":"tcl","vcs":"vcs",
    "lla":"lla","ljl":"ljl","pcs":"pcs_lol","ewc":"riotgames",
    "_unknown":"riotgames","_default":"riotgames",
}
def get_stream_urls(lc):
    ch=STREAM_CHANNELS.get(lc,"riotgames")
    return {"twitch":f"https://player.twitch.tv/?channel={ch}&parent=localhost&autoplay=true",
            "twitch_channel":ch}

# ── Ligas ─────────────────────────────────────────────────────────────
LEAGUE_INFO = {
    "lck":        {"name":"LCK","display":"LCK 2026","tier":1,"main":True},
    "lpl":        {"name":"LPL","display":"LPL 2026","tier":1,"main":True},
    "lec":        {"name":"LEC","display":"LEC 2026","tier":1,"main":True},
    "lcs":        {"name":"LCS","display":"LCS 2026","tier":1,"main":True},
    "cblol":      {"name":"CBLOL","display":"CBLOL 2026","tier":1,"main":True},
    "lla":        {"name":"LLA","display":"LLA 2026","tier":2,"main":True},
    "vcs":        {"name":"VCS","display":"VCS 2026","tier":2,"main":True},
    "ljl":        {"name":"LJL","display":"LJL 2026","tier":2,"main":True},
    "tcl":        {"name":"TCL","display":"TCL 2026","tier":2,"main":True},
    "pcs":        {"name":"PCS","display":"PCS 2026","tier":2,"main":True},
    "lck_cl":     {"name":"LCK CL","display":"LCK CL 2026","tier":3,"main":False},
    "cblol_acad": {"name":"CBLOL Acad","display":"CBLOL Academy 2026","tier":3,"main":False},
    "lcs_acad":   {"name":"LCS Acad","display":"LCS Academy 2026","tier":3,"main":False},
    "ewc":        {"name":"EWC","display":"EWC 2026","tier":1,"main":True},
    "_unknown":   {"name":"Torneio","display":"Torneio","tier":2,"main":True},
}
LEAGUE_CONFIDENCE_CAP = {1:1.00,2:0.90,3:0.78}
def get_league_info(c): return LEAGUE_INFO.get(c,LEAGUE_INFO["_unknown"])

def _guess_league(t1,t2=""):
    s=(t1+" "+t2).lower()
    for c,kws in [
        ("lck",["t1","gen.g","hanwha","hle","dplus","dk","kt rolster","nongshim",
                "bnk","fearx","brion","drx","dn soopers","fokus fire"]),
        ("lpl",["jdg","blg","weibo","edg","tes","nip","lng","omg","rng","cfo","dcg"]),
        ("lec",["g2","fnatic","vitality","karmine","mad lions","sk gaming","heretics"]),
        ("lcs",["flyquest","cloud9","team liquid","100 thieves","nrg","dignitas","los",
                "keyd","furia","loud","red canids","fluxo","w7m"]),
        ("cblol",["loud","pain","png","red canids","vivo keyd","fluxo","furia","w7m","fluxo w7m"]),
        ("lla",["isurus","all knights","infinity","estral"]),
        ("vcs",["gam esports","saigon","team flash"]),
        ("tcl",["istanbul","wildcats","supermassive","tral","nerd","papara","galakticos","besiktas"]),
        ("ljl",["detonation","softbank"]),
        ("pcs",["psg talon","beyond gaming"]),
        ("lck_cl",["dn soopers","fokus","challengers"]),
        ("ewc",["ewc"]),
    ]:
        if any(k in s for k in kws): return c
    return "_unknown"

# ── Tiers ─────────────────────────────────────────────────────────────
TIER_S={"T1","T1 Esports","Gen.G","GEN.G","Hanwha Life","HLE","Dplus KIA","DK","DRX",
        "JDG","BLG","Bilibili Gaming","Weibo Gaming","WBG","EDward Gaming","EDG",
        "G2 Esports","G2","FlyQuest","Cloud9","C9",
        "LOUD","paiN Gaming","PNG","Vivo Keyd Stars","VKS","GAM Esports","PSG Talon","Isurus"}
TIER_A={"KT Rolster","KT","BNK FearX","BNK","Nongshim RedForce","Nongshim","NS","BRION",
        "TES","NIP","LNG Esports","OMG","RNG","CFO","DCG","DN SOOPers",
        "Fnatic","Team Vitality","Karmine Corp","MAD Lions","SK Gaming","Team Heretics",
        "Team Liquid","100 Thieves","NRG Esports","Dignitas","Cloud9","FlyQuest",
        "RED Canids","Fluxo","Fluxo W7M","FURIA","FURIA Esports",
        "All Knights","Infinity","Estral Esports",
        "Saigon Buffalo","Team Flash","DetonatioN FM",
        "IstanBul Wildcats","SuperMassive","Beyond Gaming",
        "TRAL","NERD","Papara SuperMassive","Galakticos","Beşiktaş",
        "LOS","Keyd Stars","FearX","FocusFire"}

TIER_PROFILES={
    "S":{"wr_base":0.72,"wr_noise":0.06,"wr_min":0.65,"wr_max":0.90,
         "fb":0.62,"fd":0.65,"fbar":0.68,"gd":800,"gdn":300},
    "A":{"wr_base":0.56,"wr_noise":0.07,"wr_min":0.48,"wr_max":0.68,
         "fb":0.53,"fd":0.54,"fbar":0.55,"gd":200,"gdn":450},
    "B":{"wr_base":0.40,"wr_noise":0.08,"wr_min":0.22,"wr_max":0.52,
         "fb":0.45,"fd":0.44,"fbar":0.43,"gd":-200,"gdn":500},
}
LEAGUE_STYLE={
    "lck":{"kills":13.2,"kn":2.0,"gl":35.5,"gln":4.0,"tkf":1.70,"df":0.72},
    "lpl":{"kills":17.8,"kn":2.8,"gl":30.5,"gln":3.5,"tkf":1.80,"df":0.78},
    "lec":{"kills":15.0,"kn":2.5,"gl":32.0,"gln":4.0,"tkf":1.75,"df":0.75},
    "lcs":{"kills":14.5,"kn":2.5,"gl":33.0,"gln":4.0,"tkf":1.72,"df":0.74},
    "cblol":{"kills":19.0,"kn":3.0,"gl":31.5,"gln":3.5,"tkf":1.85,"df":0.80},
    "_unknown":{"kills":15.5,"kn":2.5,"gl":33.0,"gln":4.0,"tkf":1.75,"df":0.75},
    "_default":{"kills":15.5,"kn":2.5,"gl":33.0,"gln":4.0,"tkf":1.75,"df":0.75},
}

def _recent_form(name,lc,bwr):
    seed=sum(ord(c) for c in name.lower()+lc+"form")
    rng=np.random.RandomState(seed)
    res=["W" if rng.random()<float(np.clip(bwr+rng.normal(0,.15),.1,.95)) else "L" for _ in range(5)]
    w=res.count("W"); l=res.count("L")
    if w==5:   mod,lbl,cls=+.08,"🔥 Em Chamas","hot"
    elif w==4: mod,lbl,cls=+.05,"📈 Boa Forma","good"
    elif w==3: mod,lbl,cls=+.01,"➡️ Regular","neutral"
    elif w==2: mod,lbl,cls=-.05,"📉 Instável","bad"
    else:      mod,lbl,cls=-.10,"❄️ Fase Ruim","cold"
    return {"results":res,"wins":w,"losses":l,"wr_modifier":float(mod),
            "form_label":lbl,"form_class":cls,"form_score":float(w/5),"alert":None}

def generate_decision_card(t1n,t1s,t1f,t2n,t2s,t2f,lc,bankroll):
    lp=LEAGUE_STYLE.get(lc,LEAGUE_STYLE["_default"])
    t1wr=t1s.get("winrate",.5); t2wr=t2s.get("winrate",.5)
    t1k=t1s.get("avg_kills",lp["kills"]); t2k=t2s.get("avg_kills",lp["kills"])
    t1l=t1s.get("avg_game_length",lp["gl"]); t2l=t2s.get("avg_game_length",lp["gl"])
    t1fb=t1s.get("first_blood_rate",.5); t2fb=t2s.get("first_blood_rate",.5)
    t1fd=t1s.get("first_dragon_rate",.5); t2fd=t2s.get("first_dragon_rate",.5)
    avgl=(t1l+t2l)/2; gap=abs(t1wr-t2wr)
    fav=t1n if t1wr>=t2wr else t2n
    fwr=max(t1wr,t2wr); dwr=min(t1wr,t2wr)
    decisions=[]

    # Vencedor ML
    if gap>.12:
        mlc=min(.90,.60+gap*.8)
        decisions.append({"market":"Vencedor — "+fav,"entry":fav+" vence a partida",
            "confidence":round(mlc*100,1),"probability":mlc,"icon":"🏆","category":"segura",
            "risk":"baixo" if mlc>.78 else "médio",
            "odds_fav":round(1/mlc,2),"odds_dog":round(1/(1-mlc),2)})

    # Handicap Kills
    if gap>.15:
        kd=abs(t1k-t2k); line=round(kd*.6,1); conf=min(.88,.55+gap*1.2)
        decisions.append({"market":"Handicap Kills — "+fav+" -"+str(line),
            "entry":fav+" vence com mais "+str(line)+" kills",
            "confidence":round(conf*100,1),"probability":conf,"icon":"🗡️","category":"risco",
            "risk":"baixo" if conf>.78 else "médio",
            "odds_fav":round(1/conf,2),"odds_dog":round(1/(1-conf),2)})

    # First Blood
    fb_fav=t1n if t1fb>=t2fb else t2n
    fb_conf=min(.84,max(.53,max(t1fb,t2fb)))
    decisions.append({"market":"Primeiro Abate — "+fb_fav,
        "entry":fb_fav+" marca o primeiro kill",
        "confidence":round(fb_conf*100,1),"probability":fb_conf,"icon":"🩸","category":"risco",
        "risk":"médio",
        "odds_fav":round(1/fb_conf,2),"odds_dog":round(1/(1-fb_conf),2)})

    # Primeiro Dragão
    fd_fav=t1n if t1fd>=t2fd else t2n
    fd_conf=min(.84,max(.53,max(t1fd,t2fd)))
    decisions.append({"market":"Primeiro Dragão — "+fd_fav,
        "entry":fd_fav+" abate o primeiro dragão",
        "confidence":round(fd_conf*100,1),"probability":fd_conf,"icon":"🐉","category":"risco",
        "risk":"médio",
        "odds_fav":round(1/fd_conf,2),"odds_dog":round(1/(1-fd_conf),2)})

    # Duração >27min
    p27=min(.95,max(.20,.5+(avgl-27)*.06))
    if p27>=.65:
        decisions.append({"market":"Duração >27 minutos","entry":"Jogo passa de 27min",
            "confidence":round(p27*100,1),"probability":p27,"icon":"⏱️","category":"segura",
            "risk":"muito baixo" if p27>.85 else "baixo",
            "odds_fav":round(1/p27,2),"odds_dog":round(1/(1-p27),2)})

    # Duração >30min
    p30=min(.90,max(.15,.5+(avgl-30)*.05))
    if p30>=.58:
        decisions.append({"market":"Duração >30 minutos","entry":"Jogo passa de 30min",
            "confidence":round(p30*100,1),"probability":p30,"icon":"⏳","category":"segura",
            "risk":"médio",
            "odds_fav":round(1/p30,2),"odds_dog":round(1/(1-p30),2)})

    # Total Torres
    tw_conf=min(.80,max(.53,.52+(avgl-30)*.01))
    tw_line="8.5" if avgl>=32 else "7.5"
    decisions.append({"market":"Over "+tw_line+" Torres Destruídas",
        "entry":"Total de torres destruídas Over "+tw_line,
        "confidence":round(tw_conf*100,1),"probability":tw_conf,"icon":"🏰","category":"risco",
        "risk":"médio",
        "odds_fav":round(1/tw_conf,2),"odds_dog":round(1/(1-tw_conf),2)})

    decisions.sort(key=lambda x:x["confidence"],reverse=True)
    safe=[d for d in decisions if d.get("category")=="segura"]
    risky=[d for d in decisions if d.get("category")=="risco"]
    return {"decisions":decisions,"top_pick":decisions[0] if decisions else None,
            "safe_picks":safe,"risky_picks":risky,
            "tech_gap":round(gap*100,1),"avg_duration":round(avgl,1)}

def generate_analyst_comment(t1n, t1s, t1f, t2n, t2s, t2f, lc="", league_code=""):
    t1wr=t1s.get("winrate",.5)*100; t2wr=t2s.get("winrate",.5)*100
    t1t=t1s.get("tier","B"); t2t=t2s.get("tier","B")
    parts=[]
    if t1t=="S" and t2t=="B": parts.append(t1n+"(S) vs "+t2n+"(B). WR: "+f"{t1wr:.0f}% vs {t2wr:.0f}%.")
    elif t1t==t2t: parts.append("Equilíbrio Tier "+t1t+". WR: "+f"{t1wr:.0f}% vs {t2wr:.0f}%.")
    else:
        fav=t1n if t1wr>=t2wr else t2n
        parts.append(fav+" favorito. WR: "+f"{t1wr:.0f}% vs {t2wr:.0f}%.")
    if t1f.get("form_class") in("bad","cold"): parts.append(t1n+" em queda.")
    elif t1f.get("form_class") in("hot","good"): parts.append(t1n+" em boa fase.")
    gl=t1s.get("avg_game_length",33)
    if gl>34: parts.append(f"Média de {gl:.0f}min de duração.")
    return " ".join(parts)


# ═════════════════════════════════════════════════════════════════════
class DataFetcher:
    LQ_API ="https://liquipedia.net/leagueoflegends/api.php"
    LS_KEY ="0TvQnueqKa5mxJntVWt0w4LpLfEkrV1Ta8rQBb9Z"
    LS_LIVE="https://esports-api.lolesports.com/persisted/gw/getLive"
    LS_SCHED="https://esports-api.lolesports.com/persisted/gw/getSchedule"
    LQ_HEADERS={"User-Agent":"LoLPredictorPro/2.0 (educational)","Accept-Encoding":"gzip"}

    LEAGUE_IDS={
        "lck":"98767991310872058","lpl":"98767991314006698",
        "lec":"98767991302996019","lcs":"98767991299243165",
        "cblol":"98767991332355509","lla":"101382741235120470",
        "vcs":"107213827295848783","ljl":"98767991349978712",
        "tcl":"98767991355908944","pcs":"104366947889790212",
        "lck_cl":"101382741235120470","cblol_acad":"105709090372233436",
        "lcs_acad":"99332500638116286",
    }

    def __init__(self):
        self.sess=requests.Session()
        self.sess.mount("https://",requests.adapters.HTTPAdapter(
            max_retries=requests.adapters.Retry(total=2,backoff_factor=0.3)))
        self.sess.headers.update({"User-Agent":"LoLPredictorPro/2.0","x-api-key":self.LS_KEY,"Accept-Encoding":"gzip"})
        self.panda=requests.Session()
        self.panda.headers.update(PANDA_HEADERS)
        self.panda.mount("https://",requests.adapters.HTTPAdapter(
            max_retries=requests.adapters.Retry(total=2,backoff_factor=0.3)))

    @staticmethod
    def resolve_tier(name):
        nl=name.lower().strip()
        if any(nl==t.lower() for t in TIER_S): return "S"
        if any(nl==t.lower() for t in TIER_A): return "A"
        if any(t.lower() in nl or nl in t.lower() for t in TIER_S): return "S"
        if any(t.lower() in nl or nl in t.lower() for t in TIER_A): return "A"
        return "B"

    # ── PandaScore — running real + upcoming 48h ───────────────────────
    def cargo_search(self,query=""):
        q=(query or "").strip().lower()
        try:
            matches=[]; seen=set()

            live=self.panda.get(f"{PANDA_BASE}/lol/matches/running",
                                params={"page[size]":50},timeout=10)
            if live.status_code==200:
                for raw in live.json():
                    m=self._parse_panda_match(raw, force_state="inProgress")
                    if not m: continue
                    key=m["team1"].lower()+"|"+m["team2"].lower()
                    if key in seen: continue
                    if q and q not in m["team1"].lower() and q not in m["team2"].lower(): continue
                    seen.add(key); matches.append(m)

            upcoming=self.panda.get(f"{PANDA_BASE}/lol/matches/upcoming",
                                    params={"sort":"begin_at","page[size]":50},timeout=10)
            if upcoming.status_code==200:
                limit=datetime.now(timezone.utc)+timedelta(hours=48)
                for raw in upcoming.json():
                    begin=raw.get("begin_at") or ""
                    dt_utc=None
                    try:
                        dt_utc=datetime.fromisoformat(begin.replace("Z","+00:00"))
                    except Exception:
                        pass
                    if dt_utc and dt_utc>limit: continue
                    m=self._parse_panda_match(raw, force_state="unstarted")
                    if not m: continue
                    key=m["team1"].lower()+"|"+m["team2"].lower()
                    if key in seen: continue
                    if q and q not in m["team1"].lower() and q not in m["team2"].lower(): continue
                    seen.add(key); matches.append(m)

            if matches:
                return matches,"pandascore"
            return self._demo_matches(query),"demo"
        except Exception:
            return self._demo_matches(query),"demo"

    def _parse_panda_match(self, raw, force_state="unstarted"):
        try:
            opponents=raw.get("opponents",[])
            if len(opponents)<2: return None
            o1=opponents[0].get("opponent",{}) or {}
            o2=opponents[1].get("opponent",{}) or {}
            t1=_fix_name(o1.get("name","").strip())
            t2=_fix_name(o2.get("name","").strip())
            if not t1 or not t2 or t1==t2: return None

            begin=raw.get("begin_at") or ""
            dt_brt=parse_to_brt(begin) or now_brt()
            status=raw.get("status","")
            actual_state="unstarted"
            if status=="running" or force_state=="inProgress":
                if begin:
                    start_utc=datetime.fromisoformat(begin.replace("Z","+00:00"))
                    elapsed=(datetime.now(timezone.utc)-start_utc).total_seconds()/3600
                    actual_state="inProgress" if 0 <= elapsed <= 5 else "finished"
                else:
                    actual_state="inProgress"
            elif status in ("not_started","postponed") or force_state=="unstarted":
                actual_state="unstarted"
            elif status in ("finished","canceled"):
                actual_state="finished"
            if actual_state=="finished": return None

            league=raw.get("league",{}) or {}
            serie=raw.get("serie",{}) or {}
            lc=_league_from_name((league.get("name","")+" "+serie.get("full_name","")).strip())
            if lc=="_unknown":
                lc=_guess_league(t1,t2)
            li=get_league_info(lc)
            return self._mk(
                t1,t2,lc,li,dt_brt,actual_state,
                league.get("name",""),str(raw.get("number_of_games") or "3"),
                o1.get("image_url",""),o2.get("image_url",""),
                raw.get("id"))
        except Exception:
            return None

    def _ovp_to_league(self,ovp):
        if not ovp: return "_unknown"
        o=ovp.lower()
        for c,kws in [
            ("cblol_acad",["cblol/academy","cblol_academy"]),
            ("lck_cl",["lck_cl","lck challengers","lck/cl"]),
            ("lcs_acad",["lcs_academy","lcs/academy"]),
            ("cblol",["cblol"]),("lck",["lck"]),("lpl",["lpl"]),
            ("lec",["lec"]),("lcs",["lcs"]),("lla",["lla"]),
            ("vcs",["vcs"]),("ljl",["ljl"]),("tcl",["tcl"]),("pcs",["pcs"]),("ewc",["ewc"]),
        ]:
            if any(k in o for k in kws): return c
        return "_unknown"

    def _mk(self,t1,t2,lc,li,dt_brt,state,ovp="",best_of="3",team1_image="",team2_image="",panda_id=None):
        return {
            "league":li.get("name","Torneio"),"league_display":li.get("display","Torneio"),
            "league_code":lc,"league_tier":li.get("tier",2),"is_main_league":li.get("main",True),
            "datetime":dt_brt.astimezone(timezone.utc).isoformat().replace("+00:00","Z"),
            "datetime_brt":dt_brt.strftime("%d/%m %H:%M"),
            "datetime_obj":dt_brt,
            "team1":t1,"team2":t2,"team1_code":t1[:4].upper(),"team2_code":t2[:4].upper(),
            "team1_image":team1_image or "","team2_image":team2_image or "","state":state,
            "blockName":ovp,"tournament":ovp,"best_of":str(best_of),
            "panda_id":panda_id,"is_manual":False,"is_demo":False,
        }

    # ── DEMO DATA — horários calculados em tempo real ─────────────────
    def _demo_matches(self, query: str = "") -> list:
        """
        Dados demo com horários RELATIVOS ao momento exato da chamada.
        `now` é calculado DENTRO da função — nunca fica desatualizado.
        """
        from datetime import datetime as _dt, timezone as _tz, timedelta as _td
        _TZ_BRT = _tz(_td(hours=-3))
        now = _dt.now(tz=_TZ_BRT)          # momento exato desta chamada

        def t(h: float, m: float = 0):
            """Datetime relativo a agora."""
            return now + _td(hours=h, minutes=m)

        raw = [
            # Próxima hora
            ("BNK FearX",           "KT Rolster",          "lck",     t(0.5),   "3"),
            ("JDG",                 "BLG",                 "lpl",     t(0.75),  "3"),
            # 1–3h
            ("T1 Esports",          "DRX",                 "lck",     t(1.5),   "3"),
            ("EDward Gaming",       "OMG",                 "lpl",     t(2),     "3"),
            ("FlyQuest",            "Cloud9",              "lcs",     t(2.5),   "3"),
            ("RED Canids",          "Fluxo W7M",           "cblol",   t(3),     "3"),
            # 3–6h
            ("Hanwha Life Esports", "BRION",               "lck",     t(4),     "3"),
            ("G2 Esports",          "Fnatic",              "lec",     t(4.5),   "3"),
            ("LOUD",                "FURIA Esports",       "cblol",   t(5),     "3"),
            ("Team Liquid",         "100 Thieves",         "lcs",     t(5.5),   "3"),
            ("TRAL",                "NERD",                "tcl",     t(6),     "3"),
            # 6–12h
            ("DN SOOPers",          "Dplus KIA",           "lck",     t(7),     "3"),
            ("Team Vitality",       "MAD Lions",           "lec",     t(8),     "3"),
            ("T1 Esports",          "BNK FearX",           "ewc",     t(10),    "5"),
            ("DN SOOPers",          "FocusFire",           "lck_cl",  t(9),     "3"),
            # Amanhã
            ("FearX",               "Gen.G",               "lck",     t(24),    "3"),
            ("DRX",                 "KT Rolster",          "lck",     t(27),    "3"),
            ("Hanwha Life Esports", "BNK FearX",           "lck",     t(29),    "3"),
            ("JDG",                 "OMG",                 "lpl",     t(25),    "3"),
            ("BLG",                 "EDward Gaming",       "lpl",     t(28),    "3"),
            ("G2 Esports",          "Team Vitality",       "lec",     t(26),    "3"),
            ("LOUD",                "RED Canids",          "cblol",   t(28),    "3"),
            # 2+ dias
            ("RED Canids",          "Fluxo W7M",           "cblol",   t(48),    "3"),
            ("FURIA Esports",       "LOUD",                "cblol",   t(51),    "3"),
            ("Vivo Keyd Stars",     "paiN Gaming",         "cblol",   t(53),    "3"),
            ("LOS",                 "Keyd Stars",          "lcs",     t(49),    "3"),
            ("Isurus",              "All Knights",         "lla",     t(50),    "3"),
        ]

        matches = []
        for t1, t2, lc, dt_brt, bo in raw:
            li  = get_league_info(lc)
            # Fallback demo nunca inventa jogo AO VIVO.
            matches.append(self._mk(t1, t2, lc, li, dt_brt, "unstarted", "", bo))

        # Filtra por query
        if query.strip():
            q = query.strip().lower()
            matches = [
                m for m in matches
                if q in m["team1"].lower() or q in m["team2"].lower()
                or (len(q) >= 3 and (
                    q[:3] in m["team1"].lower() or
                    q[:3] in m["team2"].lower()))
            ]

        return matches

    # ── Utilitários ───────────────────────────────────────────────────
    def _fetch_all_live(self):
        # PandaScore /lol/matches/running é a única fonte usada para AO VIVO.
        # A API pública da Riot/LoLEsports já retornou eventos ambíguos aqui.
        return []

    def build_manual_match(self,t1,t2):
        t1=t1.strip(); t2=t2.strip()
        lc=_guess_league(t1,t2); li=get_league_info(lc)
        return self._mk(t1,t2,lc,li,now_brt(),"unstarted") | {"is_manual":True}

    def get_team_stats(self,team_name,league_code,last_n=15):
        real=self.fetch_team_stats_cargo(team_name)
        return real if real else self._est(team_name,league_code)

    def fetch_team_stats_cargo(self,team_name):
        params={"action":"cargoquery","tables":"ScoreboardPlayer",
                "fields":"Team,Win,DateTime_UTC",
                "where":"Team='"+team_name.replace("'","''")+"'",
                "order_by":"DateTime_UTC DESC","limit":"30","format":"json"}
        try:
            r=requests.get(self.LQ_API,params=params,headers=self.LQ_HEADERS,timeout=8)
            if r.status_code!=200: return {}
            rows=r.json().get("cargoquery",[])
            if len(rows)<3: return {}
            wins=sum(1 for row in rows if str(row.get("title",row).get("Win","0"))=="1")
            wr=wins/len(rows)
            return {**self._est(team_name,_guess_league(team_name)),
                    "winrate":wr,"games_analyzed":len(rows),"source":"Cargo API real"}
        except: return {}

    def _est(self,name,lc):
        seed=sum(ord(c) for c in name.lower()+lc)
        rng=np.random.RandomState(seed)
        tier=self.resolve_tier(name); tp=TIER_PROFILES[tier]
        lp=LEAGUE_STYLE.get(lc,LEAGUE_STYLE["_default"])
        bwr=float(np.clip(rng.normal(tp["wr_base"],tp["wr_noise"]),tp["wr_min"],tp["wr_max"]))
        form=_recent_form(name,lc,bwr)
        awr=float(np.clip(bwr+form["wr_modifier"],.10,.95))
        k=float(np.clip(rng.normal(lp["kills"],lp["kn"]),6,30))
        d=float(np.clip(rng.normal(k*lp["df"],lp["kn"]*.8),4,25))
        gl=float(np.clip(rng.normal(lp["gl"],lp["gln"]),22,48))
        lg=get_league_info(lc)
        return {
            "games_analyzed":15,"tier":tier,"winrate":awr,"winrate_raw":bwr,
            "avg_kills":k,"avg_deaths":d,"avg_game_length":gl,
            "first_blood_rate":float(np.clip(rng.normal(tp["fb"],.07),.30,.80)),
            "first_dragon_rate":float(np.clip(rng.normal(tp["fd"],.07),.30,.80)),
            "first_baron_rate":float(np.clip(rng.normal(tp["fbar"],.07),.30,.80)),
            "avg_golddiff15":float(rng.normal(tp["gd"],tp["gdn"])),
            "total_kills_avg":float(np.clip(rng.normal(k*lp["tkf"],lp["kn"]*1.2),10,45)),
            "form":form,"source":"Estimado Tier "+tier,
        }

    def _bfe(self,ev,teams,li,lc,state):
        ds=ev.get("startTime",""); dt=parse_to_brt(ds) or now_brt()
        t1=teams[0].get("name","Team A"); t2=teams[1].get("name","Team B")
        return {
            "league":li["name"],"league_display":li["display"],
            "league_code":lc,"league_tier":li["tier"],"is_main_league":li["main"],
            "datetime":ds,"datetime_brt":dt.strftime("%d/%m %H:%M"),
            "datetime_obj":dt,"team1":t1,"team2":t2,
            "team1_code":teams[0].get("code",t1[:4].upper()),
            "team2_code":teams[1].get("code",t2[:4].upper()),
            "team1_image":teams[0].get("image",""),"team2_image":teams[1].get("image",""),
            "state":state,"blockName":ev.get("blockName",""),"tournament":"",
            "best_of":"3","is_manual":False,"is_demo":False,
        }

    def scrape_liquipedia_url(self,url):
        url=url.strip()
        path=re.sub(r"https?://liquipedia\.net/leagueoflegends","",url).strip("/") if url.startswith("http") else re.sub(r"^/?liquipedia\.net/leagueoflegends/?","",url,flags=re.I).strip("/")
        if not path: return [],"URL inválida."
        lc=self._url_to_league(path); li=get_league_info(lc)
        try:
            r=requests.get(self.LQ_API,params={"action":"parse","page":path.replace("/","_"),"prop":"wikitext","format":"json"},headers=self.LQ_HEADERS,timeout=12)
            if r.status_code!=200: return [],"HTTP "+str(r.status_code)
            wikitext=r.json().get("parse",{}).get("wikitext",{}).get("*","")
            matches=self._parse_wikitext(wikitext,lc,li)
            if matches: return matches,"✅ "+str(len(matches))+" partida(s)"
            return [],"Sem partidas identificadas."
        except Exception as e:
            return [],"Erro: "+str(e)[:60]

    def _parse_wikitext(self,wt,lc,li):
        matches=[]; found=set(); now=now_brt()
        for pat in [r"\|team1\s*=\s*([^\|\n\}]{2,40}).*?\|team2\s*=\s*([^\|\n\}]{2,40})",
                    r"TeamOpponent\|([^\|\n\}]{2,40}).*?TeamOpponent\|([^\|\n\}]{2,40})"]:
            for m in re.finditer(pat,wt,re.I|re.DOTALL):
                t1=m.group(1).strip().strip("}|").strip()
                t2=m.group(2).strip().strip("}|").strip()
                if len(t1)<2 or len(t2)<2 or t1.lower()==t2.lower(): continue
                if re.match(r"^\d+$",t1) or re.match(r"^\d+$",t2): continue
                pair=tuple(sorted([t1.lower(),t2.lower()]))
                if pair in found: continue
                found.add(pair)
                matches.append(self._mk(t1,t2,lc,li,now,"unstarted"))
            if matches: break
        return matches[:15]

    def _url_to_league(self,u):
        u=u.lower()
        for c,kws in [("cblol_acad",["cblol/academy"]),("lck_cl",["lck_cl","lck/cl"]),
                      ("cblol",["cblol"]),("lck",["lck"]),("lpl",["lpl"]),
                      ("lec",["lec"]),("lcs",["lcs"]),("lla",["lla"]),
                      ("vcs",["vcs"]),("ljl",["ljl"]),("tcl",["tcl"]),("pcs",["pcs"])]:
            if any(k in u for k in kws): return c
        return "_unknown"

    @staticmethod
    def _name_to_code(n):
        m={"lck":"lck","lpl":"lpl","lec":"lec","lcs":"lcs","cblol":"cblol","lla":"lla",
           "vcs":"vcs","ljl":"ljl","tcl":"tcl","pcs":"pcs","ewc":"ewc",
           "lck challengers":"lck_cl","cblol academy":"cblol_acad","nacl":"nacl"}
        return m.get(n.lower().strip(),"_unknown")
