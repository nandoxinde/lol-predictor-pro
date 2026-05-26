"""
ui_components.py v2.1 — LoL Predictor Pro
Visual escuro profissional. Logos via Special:FilePath (sem hash).
Lista estilo BetBoom com logos reais + fallback inicial colorido.
"""
import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
from datetime import datetime, timezone, timedelta
from html import escape

TZ_BRT = timezone(timedelta(hours=-3))

def _now():
    return datetime.now(tz=TZ_BRT)

_TEAM_COLORS = {
    "t1": "#C89B3C", "t1 esports": "#C89B3C",
    "gen.g": "#B8000A", "geng": "#B8000A",
    "cloud9": "#1A9FFF", "c9": "#1A9FFF",
    "flyquest": "#00CC66",
    "loud": "#22CC44",
    "g2 esports": "#00FF99", "g2": "#00FF99",
    "fnatic": "#FF6600",
    "pain gaming": "#FF0066", "pain": "#FF0066", "pain gaming": "#FF0066",
    "red canids": "#CC0000",
    "fluxo": "#0066FF", "fluxo w7m": "#0066FF",
    "furia esports": "#FF6600", "furia": "#FF6600",
    "kt rolster": "#CC0000", "kt": "#CC0000",
    "dplus kia": "#0044CC", "dk": "#0044CC",
    "drx": "#1A6DD4",
    "hanwha life esports": "#FF3B2F", "hanwha life": "#FF3B2F",
    "brion": "#00AA44",
    "bnk fearx": "#FF6B35", "fearx": "#FF6B35",
    "nongshim redforce": "#FF0000", "nongshim": "#FF0000",
    "team liquid": "#00AAFF",
    "100 thieves": "#CC0000",
    "jdg": "#1A6DD4",
    "blg": "#0088FF", "bilibili gaming": "#0088FF",
    "edward gaming": "#0044AA", "edg": "#0044AA",
}

def _team_color(team_name: str, fallback: str) -> str:
    n = (team_name or "").lower().strip()
    if n in _TEAM_COLORS:
        return _TEAM_COLORS[n]
    for key, value in _TEAM_COLORS.items():
        if key in n or n in key:
            return value
    return fallback

# ─── Logo — escudo SVG puro (sem URLs externas que podem quebrar) ─────
def _logo_html(team_name: str, tier_color: str, size: int = 32, image_url: str = "") -> str:
    """
    Escudo circular com gradiente neon + inicial do time.
    Sem dependência de URL externa — nunca quebra.
    """
    init = team_name[:2].upper()
    sz   = str(size)
    fs   = str(max(10, int(size * 0.40)))
    # Gradiente baseado na cor do tier
    c1   = _team_color(team_name, tier_color)
    # Escurece o gradiente
    c2   = "#090C14"
    fallback = (
        f'<div style="width:{sz}px;height:{sz}px;border-radius:50%;'
        f'flex-shrink:0;overflow:hidden;'
        f'background:linear-gradient(135deg,{c1}55 0%,{c2} 100%);'
        f'border:1.5px solid {c1}88;'
        f'display:flex;align-items:center;justify-content:center;'
        f'font-size:{fs}px;font-weight:900;color:{c1};'
        f'font-family:Inter,sans-serif;'
        f'text-shadow:0 0 8px {c1}99;'
        f'box-shadow:0 0 10px {c1}33 inset;">'
        f'{init}</div>'
    )
    if not image_url:
        return fallback
    return (
        f'<div style="position:relative;width:{sz}px;height:{sz}px;flex-shrink:0;">'
        f'<img src="{image_url}" loading="lazy" '
        f'onerror="this.style.display=\'none\';this.nextElementSibling.style.display=\'flex\';" '
        f'style="width:{sz}px;height:{sz}px;border-radius:50%;object-fit:contain;display:block;" />'
        f'<div style="display:none;width:{sz}px;height:{sz}px;border-radius:50%;'
        f'background:linear-gradient(135deg,{c1}55 0%,{c2} 100%);border:1.5px solid {c1}88;'
        f'align-items:center;justify-content:center;font-size:{fs}px;font-weight:900;color:{c1};">'
        f'{init}</div></div>'
    )

# ─── Tempo helpers ────────────────────────────────────────────────────
def _fmt_time(match: dict) -> tuple:
    """Retorna (label, cor, is_live)."""
    if match.get("state") == "inProgress":
        return "🔴 AO VIVO", "#EF4444", True
    dt_str = match.get("datetime", "")
    if not dt_str:
        return match.get("datetime_brt", "--"), "#5A7090", False
    try:
        s   = dt_str.replace("Z", "+00:00").replace(" ", "T")
        dt  = datetime.fromisoformat(s).astimezone(TZ_BRT)
        diff = (dt - _now()).total_seconds()
        if diff <= 0:
            return "Agora", "#F59E0B", False
        h = int(diff // 3600); m = int((diff % 3600) // 60)
        if diff <= 3600:
            return f"⏱ {h}h {m:02d}min" if h else f"⏱ {m}min", "#F59E0B", False
        hoje   = _now().date()
        amanha = hoje + timedelta(days=1)
        if dt.date() == hoje:
            return "Hoje " + dt.strftime("%H:%M"), "#5A7090", False
        elif dt.date() == amanha:
            return "Amanhã " + dt.strftime("%H:%M"), "#5A7090", False
        return dt.strftime("%d/%m %H:%M"), "#5A7090", False
    except Exception:
        return match.get("datetime_brt", "--"), "#5A7090", False

# ─── CSS ──────────────────────────────────────────────────────────────
_CSS = """<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap');
html,body,.stApp,[data-testid="stAppViewContainer"]{
    background:#0B0D11!important;
    font-family:'Inter',sans-serif!important;
    color:#C8D4E8!important;}
[data-testid="stAppViewContainer"]{
    padding-left:74px!important;
    margin-top:0!important;
    padding-top:0!important;
    transition:padding-left .24s ease!important;}
body:has(section[data-testid="stSidebar"]:hover) [data-testid="stAppViewContainer"]{
    padding-left:270px!important;}
.main .block-container{
    padding-top:8px!important;
    padding-left:18px!important;
    padding-right:18px!important;
    max-width:1580px!important;}
footer,#MainMenu,[data-testid="stDecoration"],.stDeployButton{display:none!important;}
section[data-testid="stSidebar"]{
    position:fixed!important;
    top:0!important;
    left:0!important;
    margin-top:0!important;
    padding-top:0!important;
    height:100vh!important;
    z-index:999999!important;
    display:block!important;
    width:74px!important;
    min-width:74px!important;
    max-width:74px!important;
    transform:none!important;
    visibility:visible!important;
    overflow:hidden!important;
    background-color:#0b1426!important;
    border-right:none!important;
    box-shadow:8px 0 30px rgba(0,0,0,.32)!important;
    transition:width .24s ease,max-width .24s ease,min-width .24s ease!important;}
section[data-testid="stSidebar"]:hover{
    width:270px!important;
    min-width:270px!important;
    max-width:270px!important;}
section[data-testid="stSidebar"] [data-testid="stSidebarContent"]{
    width:260px!important;
    padding:0 12px 16px!important;
    overflow-x:hidden!important;}
[data-testid="collapsedControl"],[data-testid="stSidebarCollapseButton"]{
    display:none!important;}
section[data-testid="stSidebar"] .stButton>button{
    width:236px!important;
    justify-content:flex-start!important;
    min-height:50px!important;
    border-radius:15px!important;
    padding-left:13px!important;
    margin:3px 0!important;
    font-size:14px!important;
    font-weight:800!important;
    letter-spacing:.1px!important;
    white-space:nowrap!important;
    overflow:hidden!important;
    transition:all .20s ease!important;}
section[data-testid="stSidebar"]:not(:hover) .stButton>button{
    width:50px!important;
    min-width:50px!important;
    max-width:50px!important;
    padding-left:12px!important;
    padding-right:0!important;
    letter-spacing:20px!important;}
section[data-testid="stSidebar"] .stButton>button[kind="primary"]{
    background:linear-gradient(90deg,rgba(34,211,238,.20),rgba(29,78,216,.12))!important;
    color:#67E8F9!important;
    border:1px solid rgba(34,211,238,.54)!important;
    box-shadow:inset 0 0 0 1px rgba(34,211,238,.10),0 0 18px rgba(34,211,238,.16)!important;}
section[data-testid="stSidebar"] .stButton>button[kind="secondary"]{
    background:#0D1624!important;
    color:#9DB1C9!important;
    border:1px solid #1A2A40!important;}
section[data-testid="stSidebar"] .stButton>button[kind="secondary"]:hover{
    background:#121D2E!important;
    color:#E0F2FE!important;
    border-color:#22D3EE!important;}
.sidebar-brand{
    display:flex;
    gap:12px;
    align-items:center;
    padding:4px 0 18px;
    border-bottom:1px solid #24344A;
    margin-bottom:14px;}
.sidebar-logo{
    width:46px;height:46px;border-radius:14px;
    background:linear-gradient(135deg,#FF8A2A,#F97316);
    display:flex;align-items:center;justify-content:center;
    color:#fff;font-size:20px;font-weight:900;}
.sidebar-name{font-size:17px;font-weight:900;color:#fff;line-height:1.04;}
.sidebar-sub{font-size:12px;font-weight:900;color:#FF7A1A;letter-spacing:1px;}
section[data-testid="stSidebar"]:not(:hover) .sidebar-brand{
    width:50px;gap:0;border-bottom-color:rgba(34,211,238,.18);}
section[data-testid="stSidebar"]:not(:hover) .sidebar-name,
section[data-testid="stSidebar"]:not(:hover) .sidebar-sub,
section[data-testid="stSidebar"]:not(:hover) .sidebar-hint,
section[data-testid="stSidebar"]:not(:hover) .sidebar-league-title{
    opacity:0!important;
    pointer-events:none!important;}
.sidebar-hint{
    margin-top:18px;
    padding:14px 16px;
    border-radius:15px;
    background:linear-gradient(90deg,rgba(249,115,22,.14),rgba(15,23,42,.88));
    border:1px solid rgba(249,115,22,.48);}
.sidebar-hint-title{color:#FF7A1A;font-size:15px;font-weight:900;margin-bottom:4px;}
.sidebar-hint-text{color:#C5D1E3;font-size:13px;line-height:1.35;}
.sidebar-spacer{height:8px;}
.sidebar-league-title{
    color:#FF7A1A;
    font-size:15px;
    font-weight:900;
    margin:4px 0 8px;}
.stButton>button{
    font-family:'Inter',sans-serif!important;
    font-weight:700!important;font-size:13px!important;
    border-radius:6px!important;border:none!important;
    transition:all .15s ease!important;}
.stButton>button[kind="primary"]{
    background:#1565C0!important;color:#fff!important;}
.stButton>button[kind="primary"]:hover{
    background:#1976D2!important;
    box-shadow:0 0 14px rgba(21,101,192,.5)!important;}
.stButton>button[kind="secondary"]{
    background:#131926!important;color:#7A8FAA!important;
    border:1px solid #1E2D45!important;}
.stButton>button[kind="secondary"]:hover{
    background:#1A2235!important;color:#C8D4E8!important;
    border-color:#1565C0!important;}
.stTextInput input,.stNumberInput input{
    background:#0F1520!important;border:1px solid #1E2D45!important;
    color:#C8D4E8!important;font-family:'Inter',sans-serif!important;
    border-radius:5px!important;padding:7px 12px!important;}
.stTextInput input:focus{border-color:#1565C0!important;outline:none!important;}
.stSelectbox>div>div{
    background:#0F1520!important;border:1px solid #1E2D45!important;
    color:#C8D4E8!important;border-radius:5px!important;}
[data-testid="metric-container"]{
    background:#0F1520!important;border:1px solid #1E2D45!important;
    border-radius:7px!important;padding:10px!important;}
[data-testid="metric-container"] label{
    color:#3A4D65!important;font-size:10px!important;
    letter-spacing:.8px!important;text-transform:uppercase!important;}
details summary{
    background:#0F1520!important;border:1px solid #1E2D45!important;
    border-radius:5px!important;color:#7A8FAA!important;}
.stDataFrame{border:1px solid #1E2D45!important;border-radius:12px!important;overflow:hidden!important;}
::-webkit-scrollbar{width:4px;height:4px;}
::-webkit-scrollbar-track{background:#0B0D11;}
::-webkit-scrollbar-thumb{background:#1E2D45;border-radius:2px;}
.twitch-sticky-shell{position:sticky;top:8px;z-index:10;}
iframe[title="streamlit.components.v1.html"]{position:sticky!important;top:8px!important;z-index:10!important;}
hr{border-color:#1A2235!important;margin:6px 0!important;}
@keyframes live-pulse{0%,100%{opacity:1;}50%{opacity:.25;}}
.live-dot{animation:live-pulse 1.2s ease infinite;}
.bb-panel{background:#11151D;border:1px solid #202733;border-radius:12px;padding:12px;}
.bb-panel-title{font-size:13px;font-weight:900;color:#F5F7FA;margin-bottom:10px;}
.bb-side-row{display:flex;align-items:center;justify-content:space-between;gap:8px;
    background:#181D26;border:1px solid #222A36;border-radius:10px;padding:9px 10px;margin:6px 0;}
.bb-side-row-active{background:#242A36;border-color:#1565C0;box-shadow:inset 3px 0 0 #1565C0;}
.bb-count{color:#C8D4E8;font-size:11px;background:#2A303B;border-radius:999px;padding:2px 7px;}
.bb-coupon-empty{height:260px;display:flex;flex-direction:column;align-items:center;justify-content:center;
    text-align:center;color:#6F7888;background:#181C23;border-radius:14px;}
::-webkit-scrollbar{width:4px;height:4px;}
::-webkit-scrollbar-track{background:#0B0D11;}
::-webkit-scrollbar-thumb{background:#1E2D45;border-radius:2px;}
.app-card{
    background:linear-gradient(180deg,#111827 0%,#0F1520 100%);
    border:1px solid #1A2235;
    border-radius:16px;
    padding:16px;
    box-shadow:0 18px 44px rgba(0,0,0,.28);
    margin-bottom:14px;}
.app-card-title{color:#F5F7FA;font-size:16px;font-weight:900;letter-spacing:.2px;margin-bottom:4px;}
.app-card-subtitle{color:#5A7090;font-size:12px;margin-bottom:12px;}
.market-chip{
    background:#121A2A;
    border:1px solid #1A2235;
    border-radius:999px;
    color:#7A8FAA;
    font-size:11px;
    font-weight:800;
    padding:5px 10px;
    display:inline-block;
    margin:3px 4px 3px 0;}
</style>"""

def apply_custom_css():
    st.markdown(_CSS, unsafe_allow_html=True)

def render_sidebar_navigation(current: str, bankroll: float = 0.0, username: str = "Fernando"):
    with st.sidebar:
        st.markdown(
            f'<div class="sidebar-brand">'
            f'<div class="sidebar-logo">LP</div>'
            f'<div><div class="sidebar-name">LoL Predictor</div>'
            f'<div class="sidebar-sub">PRO</div></div>'
            f'</div>',
            unsafe_allow_html=True,
        )

        items = [
            ("operacao", "🎮 Jogos de Hoje"),
            ("stats_t1_dk", "📊 Estatísticas"),
            ("analise_apostas", "🎯 Análise de Apostas"),
            ("banca", "⚙️ Painel de Controle"),
        ]
        for key, label in items:
            if st.button(label, key=f"side_nav_{key}", use_container_width=True,
                         type="primary" if current == key else "secondary"):
                st.session_state.aba = key
                st.session_state.selected_match = None
                st.rerun()

        st.markdown('<div class="sidebar-spacer"></div>', unsafe_allow_html=True)

# ─── Header ───────────────────────────────────────────────────────────
def render_header(banca_atual, banca_ini, meta, username="Fernando"):
    pct   = min(100., max(0., (banca_atual - banca_ini) / max(meta - banca_ini, 1) * 100))
    lucro = banca_atual - banca_ini
    lc    = "#22C55E" if lucro >= 0 else "#EF4444"
    ls    = f"+R${lucro:.2f}" if lucro >= 0 else f"-R${abs(lucro):.2f}"

    c_logo, _, c_meta, c_user = st.columns([2, 3, 3, 3])
    with c_logo:
        st.markdown(
            '<span style="font-size:20px;font-weight:900;color:#fff;">Lol</span>'
            '<span style="font-size:20px;font-weight:900;color:#1565C0;"> Pro</span>'
            '<span style="background:#1565C0;color:#fff;font-size:9px;font-weight:700;'
            'padding:1px 5px;border-radius:3px;margin-left:4px;vertical-align:middle;">v2.0</span>',
            unsafe_allow_html=True)
    with c_meta:
        st.markdown(
            f'<div style="text-align:right;line-height:1.6;">'
            f'<span style="font-size:10px;color:#3A4D65;letter-spacing:.5px;">META R$ {meta:.0f}</span><br>'
            f'<div style="background:#131926;border-radius:3px;height:4px;overflow:hidden;margin:3px 0;">'
            f'<div style="background:#22C55E;height:100%;width:{pct:.1f}%;border-radius:3px;"></div></div>'
            f'<span style="font-size:10px;color:{lc};">{pct:.0f}% · {ls}</span>'
            f'</div>', unsafe_allow_html=True)
    with c_user:
        st.markdown(
            f'<div style="display:flex;align-items:center;justify-content:flex-end;gap:10px;">'
            f'<div style="text-align:right;">'
            f'<div style="font-size:14px;font-weight:700;color:#1A9FFF;">R$ {banca_atual:.2f}</div>'
            f'<div style="font-size:10px;color:{lc};">{ls}</div></div>'
            f'<div style="width:32px;height:32px;border-radius:50%;'
            f'background:linear-gradient(135deg,#1565C0,#0D3A7A);'
            f'display:flex;align-items:center;justify-content:center;'
            f'font-size:14px;font-weight:900;color:#fff;flex-shrink:0;">'
            f'{username[0].upper()}</div>'
            f'<div>'
            f'<div style="font-size:12px;font-weight:700;color:#C8D4E8;">{username}</div>'
            f'<div style="font-size:10px;color:#3A4D65;">{pct:.0f}% da meta</div>'
            f'</div></div>', unsafe_allow_html=True)
    st.markdown('<hr style="margin:8px 0 0;">', unsafe_allow_html=True)

# ─── Nav ──────────────────────────────────────────────────────────────
def render_nav(current: str):
    tabs = [("operacao","🚀  Operação"),("banca","💰  Gestão de Banca"),("wiki","🔍  Wiki-Pro")]
    cols = st.columns([1,1,1,5])
    for i,(k,label) in enumerate(tabs):
        with cols[i]:
            if st.button(label, key="nav_"+k, use_container_width=True,
                         type="primary" if current==k else "secondary"):
                st.session_state.aba = k
                st.session_state.selected_match = None
                st.rerun()

# ─── Hero ─────────────────────────────────────────────────────────────
_STADIUM = "https://cdnb.artstation.com/p/assets/images/images/059/542/327/large/kevin-tran-elder-dragon.jpg?1676601959"

def render_hero(n_live: int, n_next: int, source: str = ""):
    live_txt = f"🔴 {n_live} ao vivo  ·  " if n_live > 0 else ""
    demo_txt = "  · ⚠️ Dados demo (PandaScore indisponível)" if source == "demo" else ""
    source_label = "Agenda demo" if source == "demo" else (source or "Agenda real")
    st.markdown(
        f'<div style="background:linear-gradient(90deg,'
        f'rgba(3,7,18,.94) 0%,rgba(3,7,18,.42) 48%,rgba(3,7,18,.94) 100%),'
        f'linear-gradient(180deg,rgba(3,7,18,.10) 0%,rgba(3,7,18,.88) 100%),'
        f'url({_STADIUM}) center 42%/cover no-repeat;'
        f'border-radius:14px;padding:18px 18px 14px;margin-bottom:8px;min-height:82px;'
        f'border:1px solid rgba(200,155,60,.70);box-shadow:0 18px 42px rgba(0,0,0,.42),'
        f'inset 0 0 0 1px rgba(247,231,178,.08);overflow:hidden;">'
        f'<div style="font-size:24px;font-weight:900;color:#fff;'
        f'text-shadow:0 2px 10px rgba(0,0,0,.9);">League of Legends</div>'
        f'<div style="font-size:11px;color:#A89B73;margin-top:6px;">'
        f'{live_txt}📅 {n_next} próximos · {source_label} · cache 60s{demo_txt}</div>'
        f'</div>', unsafe_allow_html=True)

def render_league_sidebar(leagues: list, counts: dict, current: str):
    st.markdown(
        '<div class="bb-panel">'
        '<div class="bb-panel-title">Ligas com jogos</div>'
        '<div style="display:flex;gap:8px;align-items:center;background:#0B0D11;'
        'border:1px solid #202733;border-radius:10px;padding:8px 10px;margin-bottom:10px;">'
        '<span style="color:#6F7888;font-size:13px;">Filtrar calendário</span>'
        '</div>',
        unsafe_allow_html=True)

    total = sum(counts.values())
    rows = [("all", "Todos os jogos", total)] + [
        (code, label, counts.get(code, 0)) for code, label in leagues if counts.get(code, 0) > 0
    ]
    for idx, (code, label, count) in enumerate(rows):
        active = current == code if idx != 0 else current == "all"
        suffix = "jogo" if count == 1 else "jogos"
        btn_label = f"{label} - {count} {suffix}"
        if st.button(btn_label, key=f"league_side_{idx}_{code}", use_container_width=True,
                     type="primary" if active else "secondary"):
            st.session_state.league_filter = code
            st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)

def render_coupon_panel(selected_match=None, bankroll=0.0):
    st.markdown(
        '<div class="bb-panel">'
        '<div class="bb-panel-title">Cupom</div>',
        unsafe_allow_html=True)
    if not selected_match:
        st.markdown(
            '<div class="bb-coupon-empty">'
            '<div style="font-size:46px;margin-bottom:12px;">🎟️</div>'
            '<div style="font-size:16px;font-weight:900;color:#F5F7FA;">Ainda não há eventos</div>'
            '<div style="font-size:12px;margin-top:8px;max-width:210px;">'
            'Clique em qualquer odd ou partida para preparar sua análise.</div>'
            '</div>',
            unsafe_allow_html=True)
    else:
        t1 = selected_match.get("team1", "Time 1")
        t2 = selected_match.get("team2", "Time 2")
        st.markdown(
            f'<div style="background:#181C23;border:1px solid #202733;border-radius:12px;padding:12px;">'
            f'<div style="font-size:12px;color:#6F7888;">Partida selecionada</div>'
            f'<div style="font-size:14px;font-weight:900;color:#F5F7FA;margin-top:4px;">{t1} vs {t2}</div>'
            f'<div style="font-size:12px;color:#1565C0;margin-top:10px;">Banca: R$ {bankroll:.2f}</div>'
            f'</div>',
            unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

# ─── Filtros de tempo ─────────────────────────────────────────────────
def filter_matches_by_time(matches: list, time_filter: str) -> list:
    if time_filter == "live":
        return [m for m in matches if m.get("state") == "inProgress"]
    if time_filter == "all":
        return matches
    limits = {"1h":60,"3h":180,"6h":360,"12h":720,"1d":1440,"2d":2880,"3d":4320}
    max_min = limits.get(time_filter, 9999)
    result = []
    for m in matches:
        if m.get("state") == "inProgress":
            result.append(m); continue
        dt_str = m.get("datetime","")
        if not dt_str: continue
        try:
            s   = dt_str.replace("Z","+00:00").replace(" ","T")
            dt  = datetime.fromisoformat(s).astimezone(TZ_BRT)
            mins = (dt - _now()).total_seconds() / 60
            if 0 <= mins <= max_min:
                result.append(m)
        except Exception:
            pass
    return result

# ─── Lista de partidas estilo BetBoom ─────────────────────────────────
def render_match_list(matches: list, analysis_map: dict,
                       bankroll_mgr, selected_id=None):
    """Legado desativado.

    O fluxo atual usa exclusivamente os cards premium definidos em
    `app.py::_render_premium_match_board()` para evitar duplicidade visual.
    A funcao permanece apenas para compatibilidade com imports antigos.
    """
    return None

# ─── Sala de Operação ─────────────────────────────────────────────────
def render_operation_room(match, analysis, bankroll_mgr, fixed_stake,
                           roster_t1, roster_t2, bankroll, target,
                           twitch_channel="", live_stats=None):
    from modules.data_fetcher import generate_decision_card
    t1  = match["team1"]; t2 = match["team2"]
    lg  = match.get("league_display", match.get("league",""))
    lc  = match.get("league_code","_unknown")
    bo  = match.get("best_of","3")
    is_live = (match.get("state") == "inProgress")
    tl, tc_col, _ = _fmt_time(match)
    tc  = {"S":"#F59E0B","A":"#1A9FFF","B":"#3A4D65"}
    t1t = __import__('modules.data_fetcher', fromlist=['DataFetcher']).DataFetcher.resolve_tier(t1)
    t2t = __import__('modules.data_fetcher', fromlist=['DataFetcher']).DataFetcher.resolve_tier(t2)

    # Voltar
    col_bk, col_hd = st.columns([1,10])
    with col_bk:
        if st.button("← Voltar", key="back_op", type="secondary"):
            st.session_state.selected_match = None; st.rerun()
    with col_hd:
        live_b = ('<span style="background:#EF444422;color:#EF4444;border:1px solid #EF444455;'
                  'padding:2px 9px;border-radius:12px;font-size:11px;font-weight:700;margin-right:8px;">'
                  '🔴 AO VIVO</span>' if is_live else "")
        st.markdown(
            f'<div style="padding:4px 0;">{live_b}'
            f'<span style="font-size:17px;font-weight:800;color:#C8D4E8;">{t1}</span>'
            f'<span style="color:#1A2D4A;font-size:15px;margin:0 10px;">vs</span>'
            f'<span style="font-size:17px;font-weight:800;color:#C8D4E8;">{t2}</span>'
            f'<span style="font-size:11px;color:#3A4D65;margin-left:12px;">'
            f'{lg} · Bo{bo}</span></div>', unsafe_allow_html=True)

    st.markdown('<hr style="margin:8px 0 12px;">', unsafe_allow_html=True)

    dc = generate_decision_card(
        t1, analysis["team1_stats"], analysis.get("team1_form",{}),
        t2, analysis["team2_stats"], analysis.get("team2_form",{}),
        lc, bankroll)

    # Split: player (L) | mercados (R)
    col_v, col_m = st.columns([3,2])
    with col_v:
        _render_video_player(twitch_channel or lc, t1, t2, lg, match=match)
    with col_m:
        _render_markets(dc, analysis, bankroll_mgr, fixed_stake, bankroll, t1, t2)

    st.markdown('<hr style="margin:12px 0;">', unsafe_allow_html=True)
    _render_lolesports_live_stats(match, live_stats or {})
    if live_stats:
        st.markdown('<hr style="margin:12px 0;">', unsafe_allow_html=True)
    _render_series_memory(analysis, t1, t2)

    # Stats + Rosters
    cs, cr = st.columns(2)
    with cs:
        with st.expander("📊 Comparativo de Stats", expanded=True):
            _render_stats(t1, analysis["team1_stats"], t2, analysis["team2_stats"])
    with cr:
        with st.expander("🧠 Análise do Sistema", expanded=False):
            cmt = analysis.get("analyst_comment","")
            if cmt:
                st.markdown(
                    f'<p style="font-size:13px;color:#7A8FAA;line-height:1.6;margin:0;">{cmt}</p>',
                    unsafe_allow_html=True)
    with st.expander(f"👥 Rosters — {t1} vs {t2}", expanded=False):
        r1, r2 = st.tabs([f"👥 {t1}", f"👥 {t2}"])
        with r1: _render_roster(roster_t1)
        with r2: _render_roster(roster_t2)


def _render_lolesports_live_stats(match: dict, live_stats: dict) -> None:
    if not live_stats:
        if match.get("state") == "inProgress" and match.get("source") == "LoLEsports":
            st.caption("Stats ao vivo: LoLEsports ainda não liberou um game_id para este mapa.")
        return

    status = live_stats.get("status")
    if status != "ok":
        st.info(live_stats.get("message", "Stats ao vivo ainda indisponíveis para este mapa."))
        return

    blue = live_stats.get("blue") or {}
    red = live_stats.get("red") or {}
    blue_name = escape(match.get("blue_team") or "Blue side")
    red_name = escape(match.get("red_team") or "Red side")
    timestamp = escape(str(live_stats.get("timestamp") or ""))
    patch = escape(str(live_stats.get("patch") or ""))

    st.markdown(
        f'<div style="background:#090C14;border:1px solid #1565C055;border-radius:10px;'
        f'padding:12px 14px;margin-bottom:10px;">'
        f'<div style="display:flex;justify-content:space-between;gap:10px;align-items:center;">'
        f'<div style="font-size:13px;font-weight:900;color:#C8D4E8;">Dados ao vivo oficiais LoLEsports</div>'
        f'<div style="font-size:10px;color:#5A7090;">Patch {patch} · {timestamp}</div>'
        f'</div></div>',
        unsafe_allow_html=True,
    )

    blue_col, red_col = st.columns(2)

    def render_side(col, side_name: str, data: dict, color: str) -> None:
        dragons = data.get("dragons") or []
        with col:
            st.markdown(
                f'<div style="border:1px solid {color}66;border-radius:10px;padding:10px;'
                f'background:linear-gradient(180deg,{color}22,#0F1520);">'
                f'<div style="font-size:14px;font-weight:900;color:#F5F7FA;margin-bottom:8px;">{side_name}</div>'
                f'<div style="display:grid;grid-template-columns:repeat(5,1fr);gap:6px;text-align:center;">'
                f'<div><b>{data.get("kills",0)}</b><br><span>Kills</span></div>'
                f'<div><b>{data.get("total_gold",0)/1000:.1f}k</b><br><span>Gold</span></div>'
                f'<div><b>{data.get("towers",0)}</b><br><span>Torres</span></div>'
                f'<div><b>{len(dragons)}</b><br><span>Dragões</span></div>'
                f'<div><b>{data.get("barons",0)}</b><br><span>Barões</span></div>'
                f'</div></div>',
                unsafe_allow_html=True,
            )

            rows = []
            for player in data.get("players") or []:
                rows.append({
                    "Jogador": player.get("name", ""),
                    "Champ": player.get("champion", ""),
                    "Role": player.get("role", ""),
                    "K/D/A": f'{player.get("kills",0)}/{player.get("deaths",0)}/{player.get("assists",0)}',
                    "CS": player.get("cs", 0),
                    "Gold": f'{player.get("gold",0)/1000:.1f}k',
                    "Lvl": player.get("level", 0),
                })
            if rows:
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True, height=210)

    render_side(blue_col, blue_name, blue, "#1565C0")
    render_side(red_col, red_name, red, "#F59E0B")


def _render_series_memory(analysis: dict, t1: str, t2: str) -> None:
    memory = analysis.get("series_memory") or {}
    if memory.get("status") != "ok":
        return

    score = memory.get("series_score", {})
    momentum = memory.get("momentum", {})
    last = memory.get("last_map", {})
    totals = memory.get("totals", {})
    dragons = totals.get("dragons", {})
    kills = totals.get("kills", {})

    st.markdown(
        f'<div style="background:#090C14;border:1px solid #F59E0B55;border-radius:10px;'
        f'padding:10px 12px;margin-bottom:10px;">'
        f'<div style="font-size:12px;font-weight:900;color:#F59E0B;margin-bottom:6px;">'
        f'🧠 Memória dinâmica da série · {memory.get("maps_played", 0)} mapa(s) jogado(s)</div>'
        f'<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px;text-align:center;">'
        f'<div><b>{score.get("team1",0)} x {score.get("team2",0)}</b><br><span>Série</span></div>'
        f'<div><b>{momentum.get("team1",0.5)*100:.0f}% / {momentum.get("team2",0.5)*100:.0f}%</b><br><span>Momentum</span></div>'
        f'<div><b>{kills.get("team1",0)} / {kills.get("team2",0)}</b><br><span>Abates</span></div>'
        f'<div><b>{dragons.get("team1",0)} / {dragons.get("team2",0)}</b><br><span>Dragões</span></div>'
        f'</div>'
        f'<div style="font-size:10px;color:#5A7090;margin-top:6px;">'
        f'Último mapa: FB {last.get("first_blood") or "-"} · FD {last.get("first_dragon") or "-"} · '
        f'{t1} vs {t2}</div></div>',
        unsafe_allow_html=True,
    )

# ─── Player / Transmissões ─────────────────────────────────────────────
_TWITCH_CHANNELS = {
    "lck":"lck","lpl":"lpl","lec":"lec","lcs":"lcs",
    "cblol":"cblol","cblol_acad":"cblol","lck_cl":"lck",
    "tcl":"tcl","vcs":"vcs","lla":"lla","ljl":"ljl",
    "msi":"riotgames","ewc":"riotgames",
    "_unknown":"baiano","_default":"baiano",
}

def _resolve_channel(code_or_name: str) -> str:
    # Código de liga → canal Twitch
    if code_or_name in _TWITCH_CHANNELS:
        return _TWITCH_CHANNELS[code_or_name]
    # URL ou nome direto
    ch = (code_or_name
          .replace("https://www.twitch.tv/","")
          .replace("https://twitch.tv/","")
          .replace("twitch.tv/","")
          .split("?")[0].split("/")[0].strip())
    return ch or "baiano"

def _default_video_platform(match: dict) -> str:
    provider = (match.get("stream_provider") or "").lower()
    if provider in {"afreecatv", "soop"}:
        return "SOOP"
    if provider == "youtube":
        return "YouTube"
    if provider == "twitch":
        return "Twitch"
    if match.get("league_code") in {"ewc", "lck_cl"}:
        return "SOOP"
    return st.session_state.get("video_platform", "Twitch")


def _default_stream_value(platform: str, channel_or_code: str, match: dict) -> str:
    parameter = (match.get("stream_parameter") or "").strip()
    if platform == "SOOP":
        return parameter or ("afchall" if match.get("league_code") == "lck_cl" else "aflol")
    if platform == "Twitch":
        return st.session_state.get("twitch_custom", "") or parameter or _resolve_channel(channel_or_code)
    if platform == "YouTube":
        return st.session_state.get("youtube_custom", "")
    if platform == "Kick":
        return st.session_state.get("kick_custom", "")
    return st.session_state.get("external_stream_custom", "")


def _extract_youtube_embed(value: str) -> tuple[str, str]:
    raw = (value or "").strip()
    if not raw:
        return "", ""
    if "youtube.com/embed/" in raw:
        video_id = raw.split("youtube.com/embed/", 1)[1].split("?")[0].split("/")[0]
        return f"https://www.youtube.com/embed/{video_id}?autoplay=0&rel=0", f"https://www.youtube.com/watch?v={video_id}"
    if "youtu.be/" in raw:
        video_id = raw.split("youtu.be/", 1)[1].split("?")[0].split("/")[0]
        return f"https://www.youtube.com/embed/{video_id}?autoplay=0&rel=0", f"https://www.youtube.com/watch?v={video_id}"
    if "watch?v=" in raw:
        video_id = raw.split("watch?v=", 1)[1].split("&")[0]
        return f"https://www.youtube.com/embed/{video_id}?autoplay=0&rel=0", raw
    if raw.startswith("UC") and len(raw) > 10:
        return f"https://www.youtube.com/embed/live_stream?channel={raw}", f"https://www.youtube.com/channel/{raw}/live"
    if raw.startswith("http"):
        return "", raw
    return f"https://www.youtube.com/embed/{raw}?autoplay=0&rel=0", f"https://www.youtube.com/watch?v={raw}"


def _iframe_player(src: str, height: int = 340) -> None:
    safe_src = escape(src, quote=True)
    components.html(
        f'''<!DOCTYPE html><html><head><style>
        *{{margin:0;padding:0;box-sizing:border-box;}}
        html,body{{background:#000;width:100%;height:100%;overflow:hidden;}}
        iframe{{width:100%;height:{height}px;border:0;display:block;background:#000;}}
        </style></head><body>
        <iframe src="{safe_src}" allow="autoplay; encrypted-media; fullscreen; picture-in-picture" allowfullscreen="true"></iframe>
        </body></html>''',
        height=height + 4,
        scrolling=False,
    )


def _render_twitch_iframe(channel: str, height: int = 340) -> None:
    ch = _resolve_channel(channel)
    components.html(
        f'''<!DOCTYPE html><html><head>
        <style>
        *{{margin:0;padding:0;box-sizing:border-box;}}
        html,body{{background:#000;width:100%;height:100%;overflow:hidden;}}
        iframe{{width:100%;height:{height}px;border:0;display:block;background:#000;}}
        .fallback{{position:absolute;inset:auto 14px 14px 14px;color:#c8d4e8;font:12px Inter,Arial,sans-serif;
          background:rgba(9,12,20,.86);border:1px solid #1A2D4A;border-radius:8px;padding:10px;}}
        .fallback a{{color:#9146FF;font-weight:800;}}
        </style></head><body>
        <div id="player"></div>
        <div class="fallback">Se o player continuar bloqueado pelo navegador, abra direto:
          <a href="https://www.twitch.tv/{ch}" target="_blank" rel="noopener">twitch.tv/{ch}</a>
        </div>
        <script>
        function getParentHost() {{
          try {{
            if (document.referrer) return new URL(document.referrer).hostname;
          }} catch (e) {{}}
          try {{
            if (window.parent && window.parent.location && window.parent.location.hostname) {{
              return window.parent.location.hostname;
            }}
          }} catch (e) {{}}
          return window.location.hostname || "localhost";
        }}
        const parent = getParentHost();
        const channel = "{ch}";
        const parents = new Set([parent, window.location.hostname, "localhost", "127.0.0.1"]);
        let parentParams = "";
        parents.forEach((host) => {{
          if (host) parentParams += "&parent=" + encodeURIComponent(host);
        }});
        const src = "https://player.twitch.tv/?channel=" + encodeURIComponent(channel)
          + parentParams
          + "&autoplay=false&muted=false";
        document.getElementById("player").innerHTML =
          '<iframe src="' + src + '" allow="autoplay; fullscreen; picture-in-picture" allowfullscreen="true"></iframe>';
        </script></body></html>''',
        height=height + 4,
        scrolling=False,
    )


def _render_video_player(channel_or_code: str, t1="", t2="", lg="", height=340, match=None):
    match = match or {}
    default_platform = _default_video_platform(match)
    options = ["SOOP", "YouTube", "Twitch", "Kick", "Link externo"]
    if default_platform not in options:
        default_platform = "Twitch"

    label_match = f" · {t1} vs {t2}" if t1 and t2 else ""
    provider_note = ""
    if match.get("stream_provider") or match.get("stream_parameter"):
        provider_note = f' · Oficial: {escape(match.get("stream_provider", ""))}/{escape(match.get("stream_parameter", ""))}'

    st.markdown(
        f'<div style="background:#090C14;border:1px solid #1A2D4A;'
        f'border-radius:8px 8px 0 0;padding:7px 13px;'
        f'display:flex;justify-content:space-between;align-items:center;">'
        f'<span style="font-size:11px;font-weight:700;color:#9146FF;">Central de transmissão{label_match}</span>'
        f'<span style="font-size:10px;color:#3A4D65;">{escape(lg)}{provider_note}</span></div>',
        unsafe_allow_html=True)

    st.markdown(
        '<div style="background:#090C14;border:1px solid #1A2D4A;border-top:none;'
        'border-radius:0 0 8px 8px;padding:5px 12px;">', unsafe_allow_html=True)
    platform_key = f"video_platform_{match.get('lolesports_event_id') or match.get('panda_id') or t1[:4] + t2[:4]}"
    stored_platform = st.session_state.get(platform_key, default_platform)
    if stored_platform not in options:
        stored_platform = default_platform
    platform = st.selectbox(
        "Plataforma",
        options,
        index=options.index(stored_platform),
        key=platform_key,
        label_visibility="collapsed",
    )
    value_key = f"video_value_{platform}_{match.get('lolesports_event_id') or match.get('panda_id') or t1[:4] + t2[:4]}"
    default_value = _default_stream_value(platform, channel_or_code, match)
    value = st.text_input(
        "",
        value=st.session_state.get(value_key, default_value),
        key=value_key,
        placeholder="Canal ou link da transmissão",
        label_visibility="collapsed",
    ).strip()
    st.markdown('</div>', unsafe_allow_html=True)

    if platform == "SOOP":
        channel = value or "afchall"
        src = channel if channel.startswith("http") else f"https://play.sooplive.com/{channel}"
        direct = src
        _iframe_player(src, height)
        st.link_button("Abrir SOOP em nova aba", direct, use_container_width=True)
    elif platform == "YouTube":
        embed_url, direct = _extract_youtube_embed(value)
        if embed_url:
            _iframe_player(embed_url, height)
        else:
            st.info("Cole o link do vídeo/live do YouTube ou o ID do vídeo para embutir aqui.")
        if direct:
            st.link_button("Abrir YouTube em nova aba", direct, use_container_width=True)
    elif platform == "Kick":
        channel = value.replace("https://kick.com/", "").replace("kick.com/", "").split("?")[0].strip("/")
        if channel:
            _iframe_player(f"https://player.kick.com/{channel}?autoplay=false", height)
            st.link_button("Abrir Kick em nova aba", f"https://kick.com/{channel}", use_container_width=True)
        else:
            st.info("Informe o canal da Kick.")
    elif platform == "Link externo":
        if value.startswith("http"):
            st.info("Esta plataforma pode bloquear iframe. Use o botão abaixo para abrir direto.")
            st.link_button("Abrir transmissão", value, use_container_width=True)
        else:
            st.info("Cole o link completo da transmissão.")
    else:
        ch = _resolve_channel(value or channel_or_code)
        _render_twitch_iframe(ch, height)
        st.link_button("Abrir Twitch em nova aba", f"https://www.twitch.tv/{ch}", use_container_width=True)
        st.session_state.twitch_custom = ch

# ─── Painel de Mercados ───────────────────────────────────────────────
def _render_markets(dc, analysis, bankroll_mgr, fixed_stake, bankroll, t1, t2):
    top   = dc.get("top_pick")
    safe  = dc.get("safe_picks", [])
    risky = dc.get("risky_picks", [])
    preds = analysis.get("predictions", [])

    st.markdown(
        '<div style="background:#090C14;border:1px solid #1A2D4A;border-radius:7px;'
        'padding:9px 13px;margin-bottom:8px;">'
        '<span style="font-size:11px;font-weight:700;color:#1565C0;letter-spacing:1px;">'
        '🎯 MERCADOS DE APOSTA</span></div>', unsafe_allow_html=True)

    if top:
        conf = top["confidence"]
        cc   = "#22C55E" if conf>=80 else ("#F59E0B" if conf>=65 else "#EF4444")
        si   = bankroll_mgr.calculate_stake(top["probability"], 1.80, fixed_stake)
        ordem = _fmt_order(top)

        st.markdown(
            f'<div style="background:#0F1520;border:2px solid {cc}44;'
            f'border-radius:9px;padding:14px;margin-bottom:10px;">'
            f'<div style="font-size:16px;font-weight:800;color:{cc};'
            f'text-align:center;margin-bottom:3px;">{ordem}</div>'
            f'<div style="font-size:10px;color:#3A4D65;text-align:center;'
            f'margin-bottom:10px;">{top.get("market","")}</div>'
            f'<div style="display:flex;justify-content:space-between;'
            f'align-items:center;margin-bottom:10px;">'
            f'<div style="text-align:center;">'
            f'<div style="font-size:30px;font-weight:900;color:{cc};">{conf:.0f}%</div>'
            f'<div style="font-size:9px;color:#3A4D65;">Confiança</div></div>'
            f'<div style="background:#090C14;border-radius:7px;'
            f'padding:10px 14px;text-align:center;">'
            f'<div style="font-size:22px;font-weight:800;color:#F59E0B;">'
            f'R$ {si["stake"]:.2f}</div>'
            f'<div style="font-size:9px;color:#3A4D65;">{si["stake_pct"]}% da banca · Odd justa {top.get("fair_odds", 1/top["probability"]):.2f}</div>'
            f'</div></div></div>', unsafe_allow_html=True)

        if si["stake"] > bankroll * 0.10:
            st.warning("⚠️ Stake >10% da banca.")

        # Link BetBoom editável
        bb_key = f"bb_{t1[:3]}{t2[:3]}"
        bb_link = st.text_input(
            "🔗 Link da partida na BetBoom:",
            value="https://betboom.com/sport/esports",
            key=bb_key,
            placeholder="Cole o link direto aqui...")
        bet_url = bb_link.strip() if bb_link.strip().startswith("http") else "https://betboom.com"
        st.markdown(
            f'<a href="{bet_url}" target="_blank" style="text-decoration:none;">'
            f'<div style="background:linear-gradient(135deg,#1A5C32,#0D3520);'
            f'border:1px solid #22C55E44;border-radius:7px;'
            f'padding:10px;text-align:center;margin-bottom:10px;">'
            f'<span style="font-size:14px;font-weight:800;color:#22C55E;">'
            f'🎲 APOSTAR NA BETBOOM</span></div></a>', unsafe_allow_html=True)

    # Apostas Seguras / Risco
    if safe or risky:
        c1, c2 = st.columns(2)
        with c1:
            st.markdown(
                '<div style="font-size:10px;font-weight:700;color:#22C55E;'
                'letter-spacing:1px;margin-bottom:5px;text-transform:uppercase;">'
                '✅ APOSTAS SEGURAS</div>', unsafe_allow_html=True)
            for d in safe[:3]:
                cc2 = "#22C55E" if d["confidence"]>=80 else "#F59E0B"
                st.markdown(
                    f'<div style="background:#090C14;border-left:2px solid {cc2};'
                    f'border-radius:0 5px 5px 0;padding:6px 10px;margin:3px 0;">'
                    f'<div style="font-size:11px;color:#C8D4E8;font-weight:700;">'
                    f'{d.get("icon","")} {_fmt_order(d)[:24]}</div>'
                    f'<div style="display:flex;justify-content:space-between;margin-top:2px;">'
                    f'<span style="font-size:9px;color:#3A4D65;">{d["market"][:20]} · odd {d.get("fair_odds", 1/d["probability"]):.2f}</span>'
                    f'<span style="color:{cc2};font-weight:800;font-size:12px;">'
                    f'{d["confidence"]:.0f}%</span></div></div>', unsafe_allow_html=True)
        with c2:
            st.markdown(
                '<div style="font-size:10px;font-weight:700;color:#F59E0B;'
                'letter-spacing:1px;margin-bottom:5px;text-transform:uppercase;">'
                '⚡ APOSTAS DE RISCO</div>', unsafe_allow_html=True)
            for d in risky[:3]:
                cc2 = "#F59E0B" if d["confidence"]>=65 else "#EF4444"
                st.markdown(
                    f'<div style="background:#090C14;border-left:2px solid {cc2};'
                    f'border-radius:0 5px 5px 0;padding:6px 10px;margin:3px 0;">'
                    f'<div style="font-size:11px;color:#C8D4E8;font-weight:700;">'
                    f'{d.get("icon","")} {_fmt_order(d)[:24]}</div>'
                    f'<div style="display:flex;justify-content:space-between;margin-top:2px;">'
                    f'<span style="font-size:9px;color:#3A4D65;">{d["market"][:20]} · odd {d.get("fair_odds", 1/d["probability"]):.2f}</span>'
                    f'<span style="color:{cc2};font-weight:800;font-size:12px;">'
                    f'{d["confidence"]:.0f}%</span></div></div>', unsafe_allow_html=True)

    # Calculadora de stake
    if preds:
        st.markdown(
            '<div style="background:#090C14;border:1px solid #1A2D4A;'
            'border-radius:6px;padding:8px 12px;margin:8px 0 6px;">'
            '<span style="font-size:10px;font-weight:700;color:#1565C0;'
            'letter-spacing:1px;">💹 CALCULADORA DE STAKE</span></div>',
            unsafe_allow_html=True)
        sel  = st.selectbox("", [p["market"] for p in preds],
                             key="oc_sel", label_visibility="collapsed")
        pred = next((p for p in preds if p["market"]==sel), preds[0])
        fp   = pred["probability"]; fo = pred.get("fair_odds", round(1/fp, 2))
        ho   = st.number_input("Odd da casa:", min_value=1.01, value=fo,
                                step=0.05, key="oc_inp", label_visibility="collapsed")
        ev   = (fp*ho) - 1
        si   = bankroll_mgr.calculate_stake(fp, ho, fixed_stake)
        bc   = "#22C55E" if ev>=.05 else ("#F59E0B" if ev>=.01 else "#EF4444")
        bl   = "✅ VALOR" if ev>=.05 else ("⚠️ MARGINAL" if ev>=.01 else "❌ SEM VALOR")
        bw   = f"{min(100,max(4,ev*400)) if ev>0 else 4:.0f}"
        st.markdown(
            f'<div style="background:#131926;border-radius:4px;'
            f'height:5px;margin:5px 0;overflow:hidden;">'
            f'<div style="background:{bc};height:100%;width:{bw}%;border-radius:4px;"></div></div>'
            f'<div style="display:flex;justify-content:space-between;">'
            f'<span style="font-size:12px;font-weight:700;color:{bc};">{bl}</span>'
            f'<span style="font-size:10px;color:#3A4D65;">EV {ev*100:+.1f}%</span></div>',
            unsafe_allow_html=True)
        cc1, cc2 = st.columns(2)
        cc1.metric("Odd Justa", f"{fo:.2f}")
        cc2.metric("Stake", f"R${si['stake']:.2f}")

# ─── Stats comparativo ────────────────────────────────────────────────
def _positive_stat(stats: dict, key: str, fallback: float) -> float:
    value = stats.get(key)
    try:
        value = float(value)
    except (TypeError, ValueError):
        value = 0.0
    if value > 0:
        return value

    if key == "avg_towers":
        winrate = _positive_stat(stats, "winrate", 0.5)
        return round(4.9 + winrate * 3.0, 1)
    if key == "avg_dragons":
        first_dragon = _positive_stat(stats, "first_dragon_rate", 0.5)
        return round(1.4 + first_dragon * 2.0, 1)
    if key == "avg_barons":
        winrate = _positive_stat(stats, "winrate", 0.5)
        return round(0.35 + winrate * 0.75, 1)

    return fallback


def _render_stats(t1n, t1, t2n, t2):
    metrics = [
        ("Win Rate",        "winrate",           True,  "{:.0%}",   0.5),
        ("Média de kills",  "avg_kills",         True,  "{:.1f}",   14.5),
        ("Duração média",   "avg_game_length",   False, "{:.1f}min", 31.5),
        ("Torres/jogo",     "avg_towers",        True,  "{:.1f}",   6.4),
        ("Dragões/jogo",    "avg_dragons",       True,  "{:.1f}",   2.4),
        ("Barons/jogo",     "avg_barons",        True,  "{:.1f}",   0.8),
        ("First Blood",     "first_blood_rate",  True,  "{:.0%}",   0.5),
        ("First Dragon",    "first_dragon_rate", True,  "{:.0%}",   0.5),
    ]
    rows = ""
    for label, key, hib, fmt, fallback in metrics:
        v1 = _positive_stat(t1, key, fallback)
        v2 = _positive_stat(t2, key, fallback)
        a1 = (v1>v2) if hib else (v1<v2); a2 = (v2>v1) if hib else (v2<v1)
        c1 = "#22C55E" if a1 else ("#EF4444" if a2 else "#C8D4E8")
        c2 = "#22C55E" if a2 else ("#EF4444" if a1 else "#C8D4E8")
        rows += (
            f'<tr>'
            f'<td style="text-align:right;padding:4px 10px;">'
            f'<span style="color:{c1};font-weight:600;">{fmt.format(v1)}</span></td>'
            f'<td style="text-align:center;font-size:10px;color:#1E2D45;'
            f'padding:4px 6px;text-transform:uppercase;">{label}</td>'
            f'<td style="text-align:left;padding:4px 10px;">'
            f'<span style="color:{c2};font-weight:600;">{fmt.format(v2)}</span></td>'
            f'</tr>'
        )
    st.markdown(
        f'<table style="width:100%;border-collapse:collapse;font-size:13px;'
        f'background:#090C14;border-radius:7px;overflow:hidden;border:1px solid #1A2D4A;">'
        f'<thead><tr style="background:#0F1520;">'
        f'<th style="text-align:right;padding:7px 10px;color:#1565C0;">{t1n}</th>'
        f'<th style="text-align:center;padding:7px;color:#3A4D65;">Stat</th>'
        f'<th style="text-align:left;padding:7px 10px;color:#1565C0;">{t2n}</th>'
        f'</tr></thead><tbody style="color:#C8D4E8;">{rows}</tbody></table>',
        unsafe_allow_html=True)

# ─── Roster ───────────────────────────────────────────────────────────
def _render_roster(roster):
    from modules.stats_engine import get_mvp
    if not roster: st.info("Roster indisponível."); return
    mvp = get_mvp(roster)
    for p in roster:
        is_mvp = p["name"] == mvp.get("name","")
        fc     = p.get("form_class","neutral")
        fcc    = {"hot":"#F97316","good":"#22C55E","neutral":"#5A7090",
                  "bad":"#F59E0B","cold":"#EF4444"}.get(fc,"#5A7090")
        with st.expander(
            f"{p['role']} · {p['name']}{'👑' if is_mvp else ''}"
            f" — KDA {p['kda']} {p['form']}", expanded=is_mvp):
            c1, c2 = st.columns(2)
            with c1:
                st.markdown(
                    f'<div style="font-size:13px;line-height:1.9;">'
                    f'K/D/A: <span style="color:#22C55E;">{p["kills"]}</span>/'
                    f'<span style="color:#EF4444;">{p["deaths"]}</span>/'
                    f'<span style="color:#1A9FFF;">{p["assists"]}</span><br>'
                    f'WR: <span style="color:#C8D4E8;">{p["winrate"]*100:.0f}%</span>'
                    f'&nbsp;<span style="color:{fcc};">{p["form"]}</span>'
                    f'</div>', unsafe_allow_html=True)
            with c2:
                for champ in p.get("comfort_picks",[]):
                    bwr = p["champ_wr"].get(champ,.5)
                    wc  = "#22C55E" if bwr>=.55 else ("#F59E0B" if bwr>=.45 else "#EF4444")
                    st.markdown(
                        f'<div style="background:#090C14;border-radius:4px;'
                        f'padding:3px 8px;margin:2px 0;'
                        f'display:flex;justify-content:space-between;">'
                        f'<span style="font-size:12px;color:#C8D4E8;">{champ}</span>'
                        f'<span style="color:{wc};font-weight:700;font-size:11px;">'
                        f'{bwr*100:.0f}%</span></div>', unsafe_allow_html=True)

# ─── Ordem de entrada ─────────────────────────────────────────────────
def _fmt_order(top: dict) -> str:
    m = top.get("market","").upper()
    e = top.get("entry", top.get("suggestion",""))
    if "VENCEDOR" in m or "ML" in m or "MONEYLINE" in m or "VITÓRIA" in m:
        fav = e.replace("vence a partida","").replace("🏆","").replace("Vences","").strip()
        fav = fav.split()[0] if fav.split() else "TIME"
        return f"ENTRAR: {fav[:14]} ML"
    if "HANDICAP" in m:
        part = m.split("—")[-1].strip() if "—" in m else m.split("HANDICAP")[-1].strip()
        return f"HCAP {part[:16]}"
    if "PRIMEIRO ABATE" in m or "FIRST BLOOD" in m:
        return f"🩸 FIRST BLOOD"
    if "PRIMEIRO DRAGÃO" in m or "FIRST DRAGON" in m:
        return f"🐉 PRIMEIRO DRAGÃO"
    if "DURAÇÃO" in m and "27" in m: return "⏱ DURAÇÃO >27MIN"
    if "DURAÇÃO" in m and "30" in m: return "⏳ DURAÇÃO >30MIN"
    if "DURAÇÃO" in m: return "⏱ DURAÇÃO DO MAPA"
    if "TORRES" in m:
        line = m.split("OVER")[-1].strip()[:6] if "OVER" in m else ""
        return f"🏰 OVER {line} TORRES"
    if "TOTAL KILLS" in m or "KILLS O/U" in m:
        return f"🎯 {m[:22]}"
    if "GOLD" in m or "GD" in m: return "💰 GOLD DIFF @15"
    return m[:24]

# ─── Gestão de Banca ──────────────────────────────────────────────────
def render_bankroll_tab(history, save_fn, calc_fn):
    st.markdown(
        '<h3 style="color:#C8D4E8;font-family:Inter,sans-serif;margin-bottom:8px;">'
        '💰 Gestão de Banca</h3>', unsafe_allow_html=True)

    ci1, ci2, ci3 = st.columns(3)
    with ci1:
        ni = st.number_input("💵 Banca Inicial (R$)", min_value=0.,
                              value=float(st.session_state.banca_ini), step=10., key="cfg_ini")
    with ci2:
        nm = st.number_input("🎯 Meta (R$)", min_value=ni+1.,
                              value=max(float(st.session_state.banca_meta),ni+1.),
                              step=50., key="cfg_meta")
    with ci3:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("✅ Aplicar", key="btn_cfg", use_container_width=True, type="primary"):
            st.session_state.banca_ini  = ni
            st.session_state.banca_meta = nm
            st.rerun()

    banca_ini  = st.session_state.banca_ini
    banca_meta = st.session_state.banca_meta
    banca      = calc_fn(history, banca_ini)
    wins       = [b for b in history if b.get("result")=="WIN"]
    losses     = [b for b in history if b.get("result")=="LOSS"]
    lucro      = banca - banca_ini
    roi        = (lucro/banca_ini*100) if banca_ini>0 else 0

    m1,m2,m3,m4,m5 = st.columns(5)
    m1.metric("💰 Banca",    f"R${banca:.2f}")
    m2.metric("📈 Lucro",   f"R${lucro:+.2f}", delta=f"{roi:+.1f}%")
    m3.metric("✅ Vitórias", len(wins))
    m4.metric("❌ Derrotas", len(losses))
    m5.metric("🎯 WR",       f"{len(wins)/max(len(history),1)*100:.0f}%")
    st.markdown("<hr>", unsafe_allow_html=True)

    if history:
        df = pd.DataFrame(history)
        for c in ["date","match","market","odds","stake","result","profit"]:
            if c not in df.columns: df[c] = ""
        st.dataframe(
            df[["date","match","market","odds","stake","result","profit"]].rename(columns={
                "date":"Data","match":"Partida","market":"Mercado",
                "odds":"Odd","stake":"Valor","result":"Resultado","profit":"Lucro"}),
            use_container_width=True,
            height=min(380, 40+35*len(df)))
        if st.button("🗑️ Limpar Histórico", key="btn_del"):
            save_fn([]); st.success("Limpo!"); st.rerun()
    else:
        st.markdown(
            '<div style="background:#090C14;border:1px dashed #1A2D4A;border-radius:8px;'
            'padding:24px;text-align:center;">'
            '<span style="color:#1E2D45;">Nenhuma aposta registrada.</span></div>',
            unsafe_allow_html=True)

    st.markdown("<hr>", unsafe_allow_html=True)

    with st.form("form_bet", clear_on_submit=True):
        r1, r2, r3 = st.columns(3)
        with r1:
            bm  = st.text_input("Partida", key="fb_m", placeholder="ex: T1 vs NS")
            bmk = st.text_input("Mercado", key="fb_mk", placeholder="ex: Duração >30min")
        with r2:
            bo  = st.number_input("Odd", min_value=1.01, value=1.80, step=0.01, key="fb_o")
            bs  = st.number_input("Valor (R$)", min_value=0.01,
                                   value=round(banca*0.02,2), step=1., key="fb_s")
        with r3:
            br  = st.selectbox("Resultado", ["WIN","LOSS","VOID"], key="fb_r")
            st.markdown("<br>", unsafe_allow_html=True)
            sub = st.form_submit_button("💾 Salvar", use_container_width=True, type="primary")
        if sub:
            if not bm or not bmk:
                st.error("Preencha Partida e Mercado.")
            else:
                pf = bs*(bo-1) if br=="WIN" else (-bs if br=="LOSS" else 0.)
                history.append({
                    "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "match":bm,"market":bmk,"odds":bo,
                    "stake":bs,"result":br,"profit":round(pf,2)})
                save_fn(history)
                st.success(f"✅ Salvo! Banca: R${calc_fn(history,banca_ini):.2f}")
                st.rerun()

# ─── Wiki-Pro ─────────────────────────────────────────────────────────
def render_wiki_tab():
    from modules.stats_engine import search_player_wiki
    st.markdown(
        '<h3 style="color:#C8D4E8;font-family:Inter,sans-serif;margin-bottom:4px;">'
        '🔍 Wiki-Pro</h3>', unsafe_allow_html=True)
    q = st.text_input("", placeholder="ID do jogador (ex: Faker, Zeus, Tinowns)...",
                       key="wiki_q", label_visibility="collapsed")
    st.caption("💡 Use letras ocidentais: 'Ruler', não '룰러'.")
    if not q or len(q) < 2: return
    qc = "".join(c for c in q if ord(c)<256).strip()
    if not qc: st.warning("Use caracteres latinos."); return
    with st.spinner(f"Buscando '{qc}'..."):
        data = search_player_wiki(qc)
    if "error" in data:
        st.markdown(
            f'<div style="background:#1a0a0a;border:1px solid #EF444444;border-radius:8px;'
            f'padding:14px 16px;">'
            f'<span style="color:#EF4444;font-weight:700;">Jogador não encontrado no banco local.</span><br>'
            f'<span style="color:#7A8FAA;font-size:12px;">'
            f'Tente: faker, zeus, chovy, ruler, caps, showmaker, tinowns, gumayusi, keria, peyz, route'
            f'</span></div>',
            unsafe_allow_html=True)
        return
    c1, c2, c3 = st.columns([3,1,1])
    with c1:
        st.markdown(
            f'<div style="background:#090C14;border:1px solid #1A2D4A;'
            f'border-radius:8px;padding:14px;">'
            f'<div style="font-size:18px;font-weight:700;color:#1565C0;margin-bottom:8px;">'
            f'{data["name"]}</div>'
            f'<div style="font-size:13px;color:#7A8FAA;line-height:1.9;">'
            f'Time: <b style="color:#C8D4E8;">{data.get("team","—")}</b><br>'
            f'Role: <b style="color:#C8D4E8;">{data.get("role","—")}</b><br>'
            f'País: <b style="color:#C8D4E8;">{data.get("nationality","—")}</b>'
            f'</div></div>', unsafe_allow_html=True)
    with c2:
        t = data.get("titles",[])
        st.markdown(
            f'<div style="background:#1565C022;border:1px solid #1565C044;'
            f'border-radius:8px;padding:12px;text-align:center;">'
            f'<div style="font-size:28px;font-weight:700;color:#1565C0;">{len(t)}</div>'
            f'<div style="font-size:10px;color:#3A4D65;letter-spacing:1px;">TÍTULOS</div>'
            f'</div>', unsafe_allow_html=True)
    with c3:
        wu = f"https://liquipedia.net/leagueoflegends/{qc.replace(' ','_')}"
        st.markdown(
            f'<a href="{wu}" target="_blank" style="text-decoration:none;">'
            f'<div style="background:#131926;border:1px solid #1A2D4A;border-radius:8px;'
            f'padding:12px;text-align:center;">'
            f'<span style="font-size:13px;font-weight:700;color:#1A9FFF;">📖 Liquipedia</span>'
            f'</div></a>', unsafe_allow_html=True)

# ─── Stubs de compatibilidade ─────────────────────────────────────────
def render_goal_bar(*a, **kw): pass
def render_match_row_fast(*a, **kw): pass
def render_event_grid(*a, **kw): pass
def render_bankroll_panel(*a, **kw): pass
def render_wiki_panel(): render_wiki_tab()
def render_live_section(*a, **kw): pass
def render_schedule_section(*a, **kw): pass
