"""
app.py v2.0 Final — LoL Predictor Pro
Login Fernando. Banca dinâmica persistente. Layout BetBoom Elite.
Tabs: 🚀 Operação | 💰 Gestão de Banca | 🔍 Wiki-Pro
"""

import streamlit as st
import json, os, hashlib
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

from modules.auth import (
    check_auth, render_profile_settings, sync_banca_to_profile,
    _load_profile, render_guest_banner, is_guest, is_owner
)
from modules.data_fetcher import (
    DataFetcher, LEAGUE_CONFIDENCE_CAP, now_brt, get_league_info
)
from modules.analyzer import MatchAnalyzer
from modules.bankroll import BankrollManager
from modules.stats_engine import get_roster
from modules.ui_components import (
    apply_custom_css, render_header, render_nav, render_hero,
    filter_matches_by_time, render_match_list, render_operation_room,
    render_bankroll_tab, render_wiki_tab,
)

st.set_page_config(
    page_title="LoL Predictor Pro v2.0",
    page_icon="⚔️",
    layout="wide",
    initial_sidebar_state="collapsed",
)
apply_custom_css()

# ── Autenticação obrigatória ──────────────────────────────────────────
if not check_auth():
    st.stop()

# ══════════════════════════════════════════════════════════════════════
# STATE — carrega do perfil na primeira vez
# ══════════════════════════════════════════════════════════════════════
if "state_initialized" not in st.session_state:
    profile = _load_profile()
    st.session_state.banca_ini        = float(profile.get("banca_ini",   100.0))
    st.session_state.banca_meta       = float(profile.get("banca_meta", 1000.0))
    st.session_state.banca_atual_sync = float(profile.get("banca_atual", 100.0))
    st.session_state.state_initialized = True

for k, v in [
    ("aba",             "operacao"),
    ("selected_match",  None),
    ("cargo_matches",   []),
    ("cargo_source",    ""),
    ("is_searching",    False),
    ("time_filter",     "all"),
    ("twitch_custom",   ""),
]:
    if k not in st.session_state:
        st.session_state[k] = v

# ── Banca helpers ─────────────────────────────────────────────────────
HIST = "data/bet_history.json"

def _lh():
    try:
        with open(HIST) as f:
            d = json.load(f)
        return d if isinstance(d, list) else []
    except Exception:
        return []

def _sh(h):
    try:
        os.makedirs("data", exist_ok=True)
        with open(HIST, "w") as f:
            json.dump(h, f, indent=2, ensure_ascii=False)
    except Exception as e:
        st.error("Erro ao salvar: " + str(e))

def _cb(h, ini):
    """Calcula banca: inicial + lucros/perdas do histórico."""
    try:
        return round(ini + sum(float(b.get("profit", 0))
                               for b in h if isinstance(b, dict)), 2)
    except Exception:
        return ini

# ── Cache ─────────────────────────────────────────────────────────────
def _ts5():
    """Chave que muda a cada 5 minutos — para Cargo API real (evita 429)."""
    t = now_brt()
    return t.strftime("%Y%m%d%H") + str(t.minute // 5)

def _ts1():
    """Chave que muda a cada minuto — para live e dados demo."""
    return now_brt().strftime("%Y%m%d%H%M")

@st.cache_data(ttl=60, show_spinner=False)
def _cargo(ts, q):
    """
    Cache de 60s com chave por minuto.
    - API real: 60s é suficiente (Liquipedia atualiza a cada ~5min de qualquer forma)
    - Dados demo: horários recalculados a cada minuto — nunca ficam no passado
    """
    return DataFetcher().cargo_search(q)

@st.cache_data(ttl=60, show_spinner=False)
def _live(ts):     return DataFetcher()._fetch_all_live()

@st.cache_data(ttl=300, show_spinner=False)
def _stats(ts, t): return DataFetcher().fetch_team_stats_cargo(t)

# ── Dados base ────────────────────────────────────────────────────────
history     = _lh()
banca_ini   = st.session_state.banca_ini
banca_meta  = st.session_state.banca_meta
# Banca atual = sincronizada manualmente OU calculada pelo histórico
banca_sync  = st.session_state.banca_atual_sync
banca_hist  = _cb(history, banca_ini)
# Usa o maior dos dois (a que foi explicitamente sincronizada ou calculada)
banca_atual = banca_sync if abs(banca_sync - banca_ini) > abs(banca_hist - banca_ini) else banca_hist

profile = st.session_state.get("profile") or _load_profile()
display_name = profile.get("display_name", "Fernando")

# ══════════════════════════════════════════════════════════════════════
# HEADER + NAV
# ══════════════════════════════════════════════════════════════════════
render_header(banca_atual, banca_ini, banca_meta, display_name)
render_nav(st.session_state.aba)
render_guest_banner()
st.markdown("")

# ══════════════════════════════════════════════════════════════════════
# ABA WIKI
# ══════════════════════════════════════════════════════════════════════
if st.session_state.aba == "wiki":
    render_wiki_tab()
    st.stop()

# ══════════════════════════════════════════════════════════════════════
# ABA GESTÃO DE BANCA
# ══════════════════════════════════════════════════════════════════════
if st.session_state.aba == "banca":
    if is_guest():
        st.info("👥 Gestão de Banca disponível apenas para o dono.")
        st.stop()
    # ── Sincronização de saldo BetBoom ────────────────────────────────
    st.markdown(
        '<div style="background:#0F1520;border:2px solid #1565C044;border-radius:8px;'
        'padding:14px 16px;margin-bottom:16px;">'
        '<span style="font-size:12px;font-weight:700;color:#1565C0;letter-spacing:1px;">'
        '🔄 SINCRONIZAR SALDO BETBOOM</span>'
        '</div>', unsafe_allow_html=True)

    col_sync, col_btn, col_meta = st.columns([2, 1, 2])
    with col_sync:
        novo_saldo = st.number_input(
            "💵 Saldo atual na BetBoom (R$):",
            min_value=0.0, value=float(banca_atual),
            step=5.0, key="sync_val",
            help="Insira o valor exato da sua banca na casa de apostas.")
    with col_btn:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("✅ Sincronizar", key="btn_sync",
                     use_container_width=True, type="primary"):
            if novo_saldo <= 0:
                st.warning("⚠️ Banca zerada. Deposite na BetBoom antes de operar.")
            else:
                st.session_state.banca_atual_sync = novo_saldo
                sync_banca_to_profile(banca_ini, banca_meta, novo_saldo)
                st.success(f"✅ Banca sincronizada: R${novo_saldo:.2f}")
                st.rerun()
    with col_meta:
        novo_meta = st.number_input(
            "🎯 Meta de lucro (R$):",
            min_value=banca_ini + 1, value=float(banca_meta),
            step=50.0, key="meta_val")
        if st.button("Definir Meta", key="btn_meta", use_container_width=True):
            st.session_state.banca_meta = novo_meta
            sync_banca_to_profile(banca_ini, novo_meta, banca_atual)
            st.rerun()

    if banca_atual <= 0:
        st.error(
            "🚨 **BANCA ZERADA** — Não é possível calcular stakes. "
            "Sincronize seu saldo acima antes de operar.")

    st.markdown("<hr>", unsafe_allow_html=True)

    # ── Planilha de apostas + Kelly ───────────────────────────────────
    render_bankroll_tab(history, _sh, _cb)

    st.markdown("<hr>", unsafe_allow_html=True)

    # ── Configurações de perfil ───────────────────────────────────────
    render_profile_settings()

    st.stop()

# ══════════════════════════════════════════════════════════════════════
# ABA OPERAÇÃO
# ══════════════════════════════════════════════════════════════════════
fetcher  = DataFetcher()
analyzer = MatchAnalyzer()
bmgr     = BankrollManager(banca_atual, banca_meta, "Kelly (Recomendado)")

# Aviso de banca zerada
if banca_atual <= 0:
    st.warning(
        "⚠️ Banca zerada ou não sincronizada. "
        "Acesse **💰 Gestão de Banca** e insira seu saldo atual.")

# ── Sala de Operação ──────────────────────────────────────────────────
if st.session_state.selected_match:
    m   = st.session_state.selected_match
    lc  = m.get("league_code", "_unknown")
    cap = LEAGUE_CONFIDENCE_CAP.get(m.get("league_tier", 1), 1.0)
    mkt = {k: True for k in [
        "Vitória (ML)", "First Blood", "First Dragon", "First Baron",
        "Total de Kills (O/U)", "Duração do Mapa", "Gold Diff @15min"]}
    an  = MatchAnalyzer().analyze_match(m, mkt, min(70, cap * 100))
    r1  = get_roster(m["team1"], lc)
    r2  = get_roster(m["team2"], lc)
    twch = st.session_state.twitch_custom or lc

    if m.get("is_manual"):
        st.info(f"🔎 Análise manual: **{m['team1']} vs {m['team2']}**")

    render_operation_room(m, an, bmgr, None, r1, r2, banca_atual, banca_meta, twch)
    st.stop()

# ── Carrega agenda Cargo API ──────────────────────────────────────────
if not st.session_state.cargo_matches:
    with st.spinner("⚡ Carregando agenda global..."):
        ms, src = _cargo(_ts1(), "")
    st.session_state.cargo_matches = ms
    st.session_state.cargo_source  = src

# Combina com live API Riot
live_api = _live(_ts1())
seen = set(); all_ms = []
for m in live_api:
    k = m["team1"] + "|" + m["team2"]
    if k not in seen:
        seen.add(k); all_ms.append({**m, "_riot_live": True})
for m in st.session_state.cargo_matches:
    k = m["team1"] + "|" + m["team2"]
    if k not in seen:
        seen.add(k); all_ms.append(m)

# Análises em paralelo
mkt = {k: True for k in [
    "Vitória (ML)", "First Blood", "First Dragon", "First Baron",
    "Total de Kills (O/U)", "Duração do Mapa", "Gold Diff @15min"]}

def _an(m):
    try:
        cap = LEAGUE_CONFIDENCE_CAP.get(m.get("league_tier", 1), 1.0)
        an  = analyzer.analyze_match(m, mkt, min(70, cap * 100))
        return m["team1"] + "|" + m["team2"], an
    except Exception:
        return m["team1"] + "|" + m["team2"], {}

analysis_map = {}
if all_ms:
    with ThreadPoolExecutor(max_workers=6) as pool:
        analysis_map = dict(pool.map(_an, all_ms))

n_live = sum(1 for m in all_ms if m.get("state") == "inProgress" or m.get("_riot_live"))
n_next = len(all_ms) - n_live

render_hero(n_live, n_next, st.session_state.cargo_source)

# ── Barra de ferramentas ──────────────────────────────────────────────
c_q, c_s, _, c_t1, c_t2, c_go, c_ref = st.columns([3, 1, .15, 1.5, 1.5, 1.3, 0.6])

with c_q:
    cargo_q = st.text_input(
        "", placeholder="🔍 Buscar time (T1, Dplus, LOUD, Fluxo, W7M...)",
        key="cq", label_visibility="collapsed")
with c_s:
    do_search = st.button("Buscar", key="btn_s",
                           use_container_width=True, type="primary")
with c_t1:
    t1i = st.text_input("", placeholder="Time 1 (ex: T1)",
                         key="t1i", label_visibility="collapsed")
with c_t2:
    t2i = st.text_input("", placeholder="Time 2 (ex: Dplus KIA)",
                         key="t2i", label_visibility="collapsed")
with c_go:
    do_manual = st.button("⚔️ Analisar", key="btn_m",
                           use_container_width=True, type="primary")
with c_ref:
    if st.button("🔃", key="btn_ref", use_container_width=True, help="Recarregar"):
        st.cache_data.clear()
        st.session_state.cargo_matches = []
        st.rerun()

if do_search and not st.session_state.is_searching:
    st.session_state.is_searching = True
    st.session_state.cargo_matches = []
    st.cache_data.clear()
    with st.spinner("Buscando '" + cargo_q + "'..."):
        ms, src = fetcher.cargo_search(cargo_q.strip())
    st.session_state.cargo_matches = ms
    st.session_state.cargo_source  = src
    st.session_state.is_searching  = False
    st.rerun()

if do_manual:
    t1 = t1i.strip(); t2 = t2i.strip()
    if t1 and t2:
        with st.spinner("Buscando stats..."):
            s1 = _stats(_ts5(), t1)
            s2 = _stats(_ts5(), t2)
        m = fetcher.build_manual_match(t1, t2)
        m["_stats_t1_override"] = s1 if s1 else None
        m["_stats_t2_override"] = s2 if s2 else None
        st.session_state.selected_match = m
        st.rerun()
    else:
        st.error("Preencha os dois campos.")

# ── Filtros de tempo ──────────────────────────────────────────────────
time_filter = st.session_state.get("time_filter", "all")
filter_labels = [
    ("live", "🔴 Ao Vivo"), ("all", "Todos"),
    ("1h", "1h"), ("3h", "3h"), ("6h", "6h"),
    ("12h", "12h"), ("1d", "1d"), ("2d", "2d"), ("3d", "3d"),
]
st.markdown("<div style='margin:8px 0 4px;'>", unsafe_allow_html=True)
fcols = st.columns(len(filter_labels))
for i, (key, label) in enumerate(filter_labels):
    with fcols[i]:
        if st.button(label, key="tf_" + key, use_container_width=True,
                     type="primary" if time_filter == key else "secondary"):
            st.session_state.time_filter = key
            st.rerun()
st.markdown("</div>", unsafe_allow_html=True)

# ── Filtra e renderiza lista ──────────────────────────────────────────
filtered = filter_matches_by_time(all_ms, st.session_state.time_filter)

# Recalcula análises para filtrados se necessário
if filtered != all_ms:
    with ThreadPoolExecutor(max_workers=4) as pool:
        analysis_map.update(dict(pool.map(_an, filtered)))

sel_mid = None
if st.session_state.selected_match:
    sm = st.session_state.selected_match
    sel_mid = hashlib.md5((sm["team1"] + sm["team2"]).encode()).hexdigest()[:8]

render_match_list(filtered, analysis_map, bmgr, selected_id=sel_mid)

# ── URL específica ────────────────────────────────────────────────────
with st.expander("🔗 Colar URL da Liquipedia", expanded=False):
    cu, cub = st.columns([5, 1])
    with cu:
        url_inp = st.text_input(
            "", "", key="url_inp",
            placeholder="liquipedia.net/leagueoflegends/LCK/2026/...",
            label_visibility="collapsed")
    with cub:
        if st.button("🔍", key="btn_url", use_container_width=True, type="primary"):
            if url_inp.strip():
                st.cache_data.clear()
                st.session_state.cargo_matches = []
                with st.spinner("Lendo URL..."):
                    ms, msg = fetcher.scrape_liquipedia_url(url_inp.strip())
                st.session_state.cargo_matches = ms
                st.session_state.cargo_source  = "real"
                st.rerun()
