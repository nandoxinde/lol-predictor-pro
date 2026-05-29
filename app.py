"""LoL Predictor Pro.

Clean orchestration for the rebuilt Streamlit app.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from html import escape
from urllib.parse import urlparse

import pandas as pd
import streamlit as st

from modules.config import load_local_env
from modules.analyzer import MatchAnalyzer

load_local_env()
from modules.auth import (
    _load_profile,
    check_auth,
    is_guest,
    render_guest_banner,
    render_profile_settings,
    sync_banca_to_profile,
)
from modules.bankroll import (
    BankrollManager,
    pending_exposure,
    register_pending_bet,
    settle_pending_bets,
)
from modules.data_fetcher import DataFetcher, LEAGUE_CONFIDENCE_CAP, now_brt
from modules.odds_fetcher import OddsPapiClient, odds_pair_key
from modules.stats_engine import get_roster
from modules.ui_components import (
    apply_custom_css,
    filter_matches_by_time,
    render_bankroll_tab,
    render_coupon_panel,
    render_header,
    render_hero,
    render_match_list,
    render_operation_room,
    render_sidebar_navigation,
    render_wiki_tab,
)

st.set_page_config(
    page_title="LoL Predictor Pro v2.0",
    page_icon="⚔️",
    layout="wide",
    initial_sidebar_state="expanded",
)
apply_custom_css()

if not check_auth():
    st.stop()

DEFAULT_STATE = {
    "aba": "operacao",
    "selected_match": None,
    "matches": [],
    "matches_source": "",
    "time_filter": "all",
    "league_filter": "all",
    "twitch_custom": "",
}
DATA_VERSION = "series-memory-odds-v14"
AUTO_REFRESH_SECONDS = 60
MATCHES_CACHE_LIVE_SECONDS = 60
MATCHES_CACHE_IDLE_SECONDS = 300

if "state_initialized" not in st.session_state:
    profile = _load_profile()
    st.session_state.banca_ini = float(profile.get("banca_ini", 0.0))
    st.session_state.banca_meta = float(profile.get("banca_meta", 1000.0))
    st.session_state.banca_atual_sync = float(profile.get("banca_atual", 0.0))
    st.session_state.state_initialized = True

for key, value in DEFAULT_STATE.items():
    st.session_state.setdefault(key, value)

if st.session_state.get("data_version") != DATA_VERSION:
    st.cache_data.clear()
    st.session_state.matches = []
    st.session_state.matches_source = ""
    st.session_state.selected_match = None
    st.session_state.data_version = DATA_VERSION

HISTORY_FILE = "data/bet_history.json"


def _load_history() -> list[dict]:
    try:
        with open(HISTORY_FILE, encoding="utf-8") as file:
            data = json.load(file)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save_history(history: list[dict]) -> None:
    os.makedirs("data", exist_ok=True)
    with open(HISTORY_FILE, "w", encoding="utf-8") as file:
        json.dump(history, file, indent=2, ensure_ascii=False)


def _calc_bankroll(history: list[dict], initial: float) -> float:
    profit = sum(float(item.get("profit", 0) or 0) for item in history if isinstance(item, dict))
    return round(initial + profit, 2)


def _available_bankroll(balance: float, history: list[dict]) -> float:
    return round(max(0.0, float(balance) - pending_exposure(history)), 2)


def _register_pending_from_click(match: dict, pick: dict, stake_info: dict, odds: float, bet_url: str) -> tuple[bool, str]:
    if float(stake_info.get("stake", 0) or 0) <= 0:
        return False, "Stake calculada zerada. Ajuste a banca/odd antes de registrar."
    history_now = _load_history()
    updated, bet, created = register_pending_bet(history_now, match, pick, stake_info, odds, bet_url)
    _save_history(updated)
    st.session_state.last_bet_history_update = now_brt().isoformat()
    stake = float(bet.get("stake", 0) or 0)
    if created:
        return True, f"Aposta registrada como Pendente. Exposição: R$ {stake:.2f}."
    return False, "Essa aposta já está registrada como Pendente."


def _auto_settle_pending_bets(matches: list[dict], current_balance: float) -> tuple[list[dict], float, list[dict]]:
    history_now = _load_history()
    updated, balance_delta, settled = settle_pending_bets(history_now, matches)
    if not settled:
        return history_now, current_balance, []

    _save_history(updated)
    new_balance = round(max(0.0, float(current_balance) + balance_delta), 2)
    st.session_state.banca_atual_sync = new_balance
    sync_banca_to_profile(
        float(st.session_state.banca_ini),
        float(st.session_state.banca_meta),
        new_balance,
    )
    st.session_state.last_bet_history_update = now_brt().isoformat()
    return updated, new_balance, settled


def _minute_key() -> str:
    return now_brt().strftime("%Y%m%d%H%M")


def _five_minute_key() -> str:
    now = now_brt()
    return now.strftime("%Y%m%d%H") + str(now.minute // 5)


def _time_bucket(seconds: int) -> str:
    return str(int(time.time()) // max(1, int(seconds)))


def _matches_window_seconds() -> int:
    current = st.session_state.get("matches") or []
    has_live = any(str(item.get("state", "")).lower() in {"inprogress", "in_progress", "live"} for item in current)
    return MATCHES_CACHE_LIVE_SECONDS if has_live else MATCHES_CACHE_IDLE_SECONDS


@st.cache_data(ttl=MATCHES_CACHE_IDLE_SECONDS, show_spinner=False)
def _load_matches_cached(cache_key: str, query: str = "") -> tuple[list[dict], str]:
    return DataFetcher().cargo_search(query)


@st.cache_data(ttl=300, show_spinner=False)
def _load_stats_cached(cache_key: str, team: str) -> dict:
    return DataFetcher().fetch_team_stats_cargo(team)


@st.cache_data(ttl=300, show_spinner=False)
def _load_oddspapi_cached(cache_key: str, matches: list[dict]) -> dict[str, dict]:
    return OddsPapiClient().fetch_lol_odds_for_matches(matches)


def _apply_premium_frontend_css() -> None:
    """Visual premium da tela principal sem tocar na lógica de dados."""
    st.markdown(
        """
        <style>
        html, body, .stApp, [data-testid="stAppViewContainer"] {
            background-color: #030712 !important;
            background-image:
                linear-gradient(90deg, rgba(3,7,18,.90) 0%, rgba(3,7,18,.48) 24%, rgba(3,7,18,.48) 76%, rgba(3,7,18,.90) 100%),
                linear-gradient(180deg, rgba(3,7,18,.44) 0%, rgba(3,7,18,.84) 100%),
                url("https://e1.pxfuel.com/desktop-wallpaper/853/468/desktop-wallpaper-4-summoner-s-rift-rifty.jpg") !important;
            background-size: cover !important;
            background-position: center center !important;
            background-attachment: fixed !important;
            background-blend-mode: overlay !important;
        }
        [data-testid="stAppViewContainer"] {
            padding-left:74px !important;
            margin-top:0 !important;
            padding-top:0 !important;
            transition:padding-left .24s ease !important;
        }
        body:has(section[data-testid="stSidebar"]:hover) [data-testid="stAppViewContainer"] {
            padding-left:270px !important;
        }
        section[data-testid="stSidebar"] {
            position:fixed !important;
            top:0 !important;
            left:0 !important;
            margin-top:0 !important;
            padding-top:0 !important;
            height:100vh !important;
            z-index:999999 !important;
            background-color:#0b1426 !important;
            border-right:none !important;
        }
        [data-testid="stAppViewContainer"]::before {
            content:"";
            position:fixed;
            inset:0;
            z-index:0;
            pointer-events:none;
            background:
                radial-gradient(circle at 50% 20%, rgba(21,101,192,.18), transparent 38%),
                linear-gradient(90deg, rgba(3,7,18,.90) 0%, rgba(3,7,18,.30) 28%, rgba(3,7,18,.30) 72%, rgba(3,7,18,.90) 100%),
                linear-gradient(180deg, rgba(3,7,18,.18) 0%, rgba(3,7,18,.76) 100%),
                url("https://e1.pxfuel.com/desktop-wallpaper/853/468/desktop-wallpaper-4-summoner-s-rift-rifty.jpg");
            background-size:cover;
            background-position:center 42%;
            background-attachment:fixed;
            opacity:.74;
            filter:saturate(1.12) contrast(1.06);
            transform:scale(1.035);
        }
        [data-testid="stAppViewContainer"] > .main {
            position:relative;
            z-index:1;
            background:transparent !important;
        }
        .main .block-container {
            background:transparent !important;
        }
        .premium-title {
            text-align:center;
            color:#F7E7B2;
            font-family: Georgia, 'Times New Roman', serif;
            font-size:34px;
            font-weight:900;
            letter-spacing:2px;
            text-shadow:0 0 14px rgba(200,155,60,.45), 0 2px 0 #05070D;
            margin:8px 0 2px;
        }
        .premium-api-status {
            text-align:center;
            color:#C8D4E8;
            font-size:12px;
            margin-bottom:14px;
        }
        .premium-section-title {
            color:#F7E7B2;
            font-family: Georgia, 'Times New Roman', serif;
            font-size:20px;
            font-weight:800;
            margin:12px 0 8px;
            text-shadow:0 0 10px rgba(200,155,60,.30);
        }
        div[data-testid="stVerticalBlockBorderWrapper"] {
            background:linear-gradient(180deg, rgba(15,21,32,.92), rgba(8,12,20,.94)) !important;
            border:1px solid rgba(200,155,60,.74) !important;
            border-radius:16px !important;
            box-shadow:0 0 0 1px rgba(247,231,178,.10), 0 18px 42px rgba(0,0,0,.44) !important;
            padding:2px !important;
        }
        div[data-testid="stVerticalBlockBorderWrapper"]:hover {
            border-color:rgba(247,231,178,.92) !important;
            box-shadow:0 0 20px rgba(200,155,60,.18), 0 18px 42px rgba(0,0,0,.50) !important;
        }
        .premium-live-pill {
            display:inline-block;
            background:linear-gradient(180deg,#1D9BF0,#075985);
            border:1px solid #7DD3FC;
            color:#E0F2FE;
            padding:5px 18px;
            border-radius:999px;
            font-size:12px;
            font-weight:900;
            letter-spacing:.8px;
            box-shadow:0 0 18px rgba(56,189,248,.42);
        }
        .premium-upcoming-pill {
            display:inline-block;
            background:linear-gradient(180deg,#1D4ED8,#0B1F45);
            border:1px solid #38BDF8;
            color:#E0F2FE;
            padding:5px 18px;
            border-radius:999px;
            font-size:12px;
            font-weight:900;
            letter-spacing:.8px;
            box-shadow:0 0 16px rgba(56,189,248,.26);
        }
        .premium-team-name {
            color:#F5F7FA;
            font-size:15px;
            font-weight:900;
            text-align:center;
            min-height:40px;
            display:flex;
            align-items:center;
            justify-content:center;
        }
        .premium-center-time {
            color:#F7E7B2;
            font-family: Georgia, 'Times New Roman', serif;
            font-size:24px;
            font-weight:900;
            text-align:center;
            text-shadow:0 0 12px rgba(200,155,60,.35);
        }
        .premium-vs {
            color:#5A7090;
            text-align:center;
            font-size:12px;
            font-weight:900;
            letter-spacing:2px;
        }
        .premium-card-status {
            text-align:center;
            margin:-2px 0 14px;
        }
        .premium-card-league {
            color:#8FA2BA;
            font-size:11px;
            font-weight:800;
            text-align:center;
            margin-top:5px;
            min-height:16px;
        }
        .premium-card-source {
            color:#6B7C93;
            font-size:11px;
            font-weight:700;
            text-align:center;
            margin-top:8px;
        }
        .premium-odd {
            background:linear-gradient(180deg,#2D2414,#15100A);
            border:1px solid rgba(200,155,60,.55);
            border-radius:9px;
            color:#F7E7B2;
            text-align:center;
            font-size:13px;
            font-weight:900;
            padding:6px 8px;
        }
        .premium-logo-fallback {
            width:82px;
            height:82px;
            border-radius:18px;
            margin:0 auto 8px;
            display:flex;
            align-items:center;
            justify-content:center;
            background:radial-gradient(circle at 30% 20%, #1A9FFF55, #090C14 70%);
            border:1px solid rgba(200,155,60,.60);
            color:#F7E7B2;
            font-size:24px;
            font-weight:900;
        }
        div[data-testid="stImage"] {
            display:flex;
            justify-content:center;
        }
        .app-card, .bb-panel {
            background:linear-gradient(180deg, rgba(15,21,32,.90), rgba(8,12,20,.94)) !important;
            border:1px solid rgba(200,155,60,.58) !important;
            box-shadow:0 12px 32px rgba(0,0,0,.42), inset 0 0 0 1px rgba(247,231,178,.06) !important;
        }
        .priority-card {
            background:linear-gradient(180deg, rgba(15,21,32,.96), rgba(8,12,20,.98));
            border:1px solid rgba(200,155,60,.62);
            border-radius:14px;
            padding:10px 12px;
            min-height:96px;
            box-shadow:0 12px 30px rgba(0,0,0,.32);
        }
        .priority-league {
            color:#F7E7B2;
            font-size:11px;
            font-weight:900;
            letter-spacing:.7px;
            text-transform:uppercase;
        }
        .priority-teams {
            color:#F5F7FA;
            font-size:13px;
            font-weight:900;
            line-height:1.25;
            margin-top:5px;
            min-height:34px;
        }
        .priority-meta {
            color:#8FA2BA;
            font-size:11px;
            margin-top:5px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _logo_url(match: dict, index: int) -> str:
    """Pega a logo dinâmica da estrutura normalizada ou da resposta bruta, se existir."""
    if index == 0:
        direct = match.get("team1_image", "")
    else:
        direct = match.get("team2_image", "")
    if direct:
        return _safe_logo_url(direct)

    teams = match.get("teams") or match.get("opponents") or []
    try:
        team = teams[index]
        if isinstance(team, dict):
            return _safe_logo_url(
                team.get("image_url")
                or team.get("image")
                or (team.get("opponent") or {}).get("image_url")
                or ""
            )
    except Exception:
        return ""
    return ""


def _safe_logo_url(url: str) -> str:
    value = (url or "").strip()
    if value.startswith("http://static.lolesports.com/"):
        value = value.replace("http://", "https://", 1)
    if "team-tbd.png" in value:
        return ""
    try:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return ""
    except Exception:
        return ""
    return value


def _match_time_label(match: dict) -> str:
    if match.get("state") == "inProgress":
        return "AO VIVO"
    return match.get("datetime_brt") or match.get("datetime", "--")


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


def _render_logo_or_fallback(match: dict, team_name: str, index: int) -> None:
    logo = _logo_url(match, index)
    initials = escape(team_name[:2].upper() or "??")
    fallback_style = (
        "width:50px;height:50px;border-radius:12px;margin:0 auto 8px;"
        "align-items:center;justify-content:center;background:transparent;"
        "border:1px solid rgba(200,155,60,.45);color:#F7E7B2;"
        "font-size:16px;font-weight:900;"
    )
    if logo:
        st.markdown(
            f'''
            <div style="position:relative;width:70px;height:62px;margin:0 auto 8px;display:flex;align-items:center;justify-content:center;">
              <img src="{escape(logo)}" loading="lazy"
                   onerror="this.style.display='none';this.nextElementSibling.style.display='flex';"
                   style="width:50px;height:50px;object-fit:contain;border-radius:12px;display:block;background:transparent;" />
              <div class="premium-logo-fallback" style="display:none;{fallback_style}">{initials}</div>
            </div>
            ''',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f'<div class="premium-logo-fallback" style="display:flex;{fallback_style}">{initials}</div>',
            unsafe_allow_html=True,
        )


def _render_premium_match_card(
    match: dict,
    analysis: dict,
    card_key: str,
    bankroll_mgr: BankrollManager | None = None,
    on_bet_click=None,
) -> None:
    t1 = match.get("team1", "Time 1")
    t2 = match.get("team2", "Time 2")
    is_live = match.get("state") == "inProgress"
    badge_class = "premium-live-pill" if is_live else "premium-upcoming-pill"
    badge_text = "Live" if is_live else "Próximo"
    league_label = escape(match.get("league_display", match.get("league", "League of Legends")))

    with st.container(border=True):
        st.markdown(
            f'<div class="premium-card-status"><span class="{badge_class}">{badge_text}</span></div>',
            unsafe_allow_html=True,
        )

        left, center, right = st.columns([1.35, .9, 1.35], gap="small", vertical_alignment="center")
        with left:
            _render_logo_or_fallback(match, t1, 0)
            st.markdown(f'<div class="premium-team-name">{escape(t1)}</div>', unsafe_allow_html=True)
        with center:
            st.markdown(f'<div class="premium-center-time">{escape(_match_time_label(match))}</div>', unsafe_allow_html=True)
            st.markdown('<div class="premium-vs">VS</div>', unsafe_allow_html=True)
            st.markdown(f'<div class="premium-card-league">{league_label}</div>', unsafe_allow_html=True)
        with right:
            _render_logo_or_fallback(match, t2, 1)
            st.markdown(f'<div class="premium-team-name">{escape(t2)}</div>', unsafe_allow_html=True)

        t1_stats = analysis.get("team1_stats", {})
        t2_stats = analysis.get("team2_stats", {})
        if match.get("odds_team1") and match.get("odds_team2"):
            odd1 = float(match["odds_team1"])
            odd2 = float(match["odds_team2"])
            odds_source = match.get("odds_source", "OddsPapi")
        else:
            t1_wr = max(float(t1_stats.get("winrate", 0.5) or 0.5), 0.01)
            t2_wr = max(float(t2_stats.get("winrate", 0.5) or 0.5), 0.01)
            total_wr = t1_wr + t2_wr
            odd1 = total_wr / t1_wr
            odd2 = total_wr / t2_wr
            odds_source = "Modelo"
        odd_col1, open_col, odd_col2 = st.columns([1, 1.2, 1])
        with odd_col1:
            st.markdown(f'<div class="premium-odd">1&nbsp;&nbsp;{odd1:.2f}</div>', unsafe_allow_html=True)
        with open_col:
            if st.button("Abrir análise", key=f"premium_open_{card_key}", use_container_width=True, type="primary"):
                st.session_state.selected_match = match
                st.rerun()
        with odd_col2:
            st.markdown(f'<div class="premium-odd">2&nbsp;&nbsp;{odd2:.2f}</div>', unsafe_allow_html=True)
        st.markdown(
            f'<div class="premium-card-source">Fonte: {escape(str(match.get("source", "Agenda")))} · '
            f'Odds: {escape(str(odds_source))}</div>',
            unsafe_allow_html=True,
        )
        top_pick = (analysis.get("predictions") or [None])[0]
        if top_pick and bankroll_mgr and on_bet_click:
            stake_info = bankroll_mgr.calculate_stake(float(top_pick.get("probability", 0.55)), 1.80, None)
            if st.button("Registrar aposta", key=f"premium_bet_{card_key}", use_container_width=True, type="secondary"):
                created, message = on_bet_click(match, top_pick, stake_info, 1.80, "https://betboom.com/sport/esports")
                if created:
                    st.success(message)
                else:
                    st.info(message)


def _render_premium_match_board(
    matches: list[dict],
    analysis_map: dict,
    bankroll_mgr: BankrollManager | None = None,
    on_bet_click=None,
) -> None:
    priority = {
        "msi": 0,
        "lpl": 1,
        "cblol": 2,
        "lck": 3,
        "lck_cl": 4,
        "lec": 5,
        "lcs": 6,
        "ewc": 7,
        "tcl": 8,
        "vcs": 9,
        "pcs": 10,
        "_unknown": 99,
    }
    live_matches = [match for match in matches if match.get("state") == "inProgress"]
    upcoming_matches = sorted(
        [match for match in matches if match.get("state") != "inProgress"],
        key=lambda item: (priority.get(item.get("league_code", "_unknown"), 50), item.get("datetime", "")),
    )
    ordered = live_matches + upcoming_matches

    if not ordered:
        st.info("Nenhum jogo encontrado neste filtro.")
        return

    if live_matches:
        st.markdown('<div class="premium-section-title">Partidas Ao Vivo</div>', unsafe_allow_html=True)
        for index, match in enumerate(live_matches[:8]):
            key = f"{match.get('team1', '')}|{match.get('team2', '')}"
            _render_premium_match_card(match, analysis_map.get(key, {}), f"live_{index}_{hashlib.md5(key.encode()).hexdigest()[:8]}", bankroll_mgr, on_bet_click)

    if upcoming_matches:
        st.markdown('<div class="premium-section-title">Próximos Jogos</div>', unsafe_allow_html=True)
        visible_upcoming = upcoming_matches[:24]
        if len(upcoming_matches) > len(visible_upcoming):
            st.caption(
                f"Mostrando {len(visible_upcoming)} de {len(upcoming_matches)} jogos. "
                "Use o menu Linhas/Ligas para focar em LPL, CBLOL, LCK ou outra liga."
            )
        for row_start in range(0, len(visible_upcoming), 2):
            cols = st.columns(2)
            for offset, col in enumerate(cols):
                item_index = row_start + offset
                if item_index >= len(visible_upcoming):
                    continue
                match = visible_upcoming[item_index]
                key = f"{match.get('team1', '')}|{match.get('team2', '')}"
                with col:
                    _render_premium_match_card(match, analysis_map.get(key, {}), f"next_{item_index}_{hashlib.md5(key.encode()).hexdigest()[:8]}", bankroll_mgr, on_bet_click)


def _priority_sort_key(match: dict) -> tuple:
    priority = {
        "msi": 0,
        "lpl": 1,
        "cblol": 2,
        "lck": 3,
        "lck_cl": 4,
        "ewc": 5,
        "lec": 6,
        "lcs": 7,
        "tcl": 8,
        "_unknown": 99,
    }
    return (priority.get(match.get("league_code", "_unknown"), 50), match.get("datetime", ""))


def _render_priority_strip(matches: list[dict]) -> None:
    if not matches:
        return

    ordered = sorted(matches, key=_priority_sort_key)
    highlights = ordered[:4]
    if not highlights:
        return

    st.markdown('<div class="premium-section-title">Destaques para operar</div>', unsafe_allow_html=True)
    cols = st.columns(len(highlights))
    for index, match in enumerate(highlights):
        key_text = f"{match.get('team1', '')}|{match.get('team2', '')}|{match.get('datetime', '')}"
        with cols[index]:
            st.markdown(
                f'<div class="priority-card">'
                f'<div class="priority-league">{match.get("league_display", match.get("league", "LoL"))}</div>'
                f'<div class="priority-teams">{match.get("team1", "Time 1")}<br>vs {match.get("team2", "Time 2")}</div>'
                f'<div class="priority-meta">{match.get("datetime_brt", "--")} · {match.get("source", "Agenda")}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
            if st.button(
                "Abrir",
                key=f"priority_open_{index}_{hashlib.md5(key_text.encode()).hexdigest()[:8]}",
                use_container_width=True,
                type="primary",
            ):
                st.session_state.selected_match = match
                st.rerun()


def _render_sidebar_league_hamburger(leagues: list[tuple[str, str]], counts: dict[str, int], current: str, bankroll: float = 0.0) -> None:
    """Menu lateral compacto para não poluir a área de jogos."""
    total = sum(counts.values())
    official_order = [("cblol", "🇧🇷 CBLOL"), ("lck", "🇰🇷 LCK"), ("lpl", "🇨🇳 LPL"), ("lec", "🇪🇺 LEC")]
    official_codes = {code for code, _ in official_order}
    visible_leagues = [
        (code, label, counts.get(code, 0))
        for code, label in leagues
        if counts.get(code, 0) > 0 and code not in official_codes
    ]

    with st.sidebar:
        st.markdown('<div class="sidebar-spacer"></div>', unsafe_allow_html=True)
        with st.expander("🏆 Ligas Oficiais", expanded=False):
            st.markdown('<div class="sidebar-league-title">Ligas Oficiais</div>', unsafe_allow_html=True)
            if st.button(
                f"🌎 Todos ({total})",
                key="hamburger_league_all",
                use_container_width=True,
                type="primary" if current == "all" else "secondary",
            ):
                st.session_state.league_filter = "all"
                st.rerun()

            for code, label in official_order:
                count = counts.get(code, 0)
                suffix = "jogo" if count == 1 else "jogos"
                if st.button(
                    f"{label} ({count} {suffix})",
                    key=f"hamburger_official_{code}",
                    use_container_width=True,
                    type="primary" if current == code else "secondary",
                ):
                    st.session_state.league_filter = code
                    st.rerun()

        if visible_leagues:
            st.markdown('<div class="sidebar-league-title">Outras linhas</div>', unsafe_allow_html=True)
            for code, label, count in visible_leagues:
                suffix = "jogo" if count == 1 else "jogos"
                if st.button(
                    f"{label} ({count} {suffix})",
                    key=f"hamburger_league_{code}",
                    use_container_width=True,
                    type="primary" if current == code else "secondary",
                ):
                    st.session_state.league_filter = code
                    st.rerun()

        st.markdown(
            f'<div class="sidebar-hint">'
            f'<div class="sidebar-hint-title">Insights estatísticos</div>'
            f'<div class="sidebar-hint-text">Não garante lucro ou resultados.<br>'
            f'Banca atual: <b style="color:#fff;">R$ {bankroll:.2f}</b></div>'
            f'</div>',
            unsafe_allow_html=True,
        )


@st.fragment(run_every=AUTO_REFRESH_SECONDS)
def _run_auto_refresh_cycle() -> None:
    """Reexecuta o app a cada 60s para atualizar agenda/cards sem ação manual."""
    # Nunca interromper a sala de operação com vídeo ativo.
    if st.session_state.get("selected_match"):
        return

    now_ts = int(time.time())
    last_cycle = int(st.session_state.get("auto_refresh_last_cycle_ts", 0) or 0)
    if last_cycle == 0:
        st.session_state.auto_refresh_last_cycle_ts = now_ts
        return
    if now_ts - last_cycle >= AUTO_REFRESH_SECONDS:
        st.session_state.auto_refresh_last_cycle_ts = now_ts
        st.session_state.auto_refresh_reason = "interval_60s"
        st.rerun()


_run_auto_refresh_cycle()


profile = st.session_state.get("profile") or _load_profile()
display_name = profile.get("display_name", "Fernando")
banca_ini = float(st.session_state.banca_ini)
banca_meta = float(st.session_state.banca_meta)
banca_atual = float(st.session_state.banca_atual_sync)
history = _load_history()
banca_disponivel = _available_bankroll(banca_atual, history)

_apply_premium_frontend_css()
render_header(banca_disponivel, banca_ini, banca_meta, display_name)
render_sidebar_navigation(st.session_state.aba, banca_disponivel, display_name)
render_guest_banner()

if st.session_state.aba == "wiki":
    render_wiki_tab()
    st.stop()

if st.session_state.aba == "stats_t1_dk":
    with st.container():
        st.markdown(
            '<div class="app-card">'
            '<div class="app-card-title">Estatísticas da T1/DK</div>'
            '<div class="app-card-subtitle">Comparativo rápido para leitura de força, ritmo e mercados prováveis.</div>',
            unsafe_allow_html=True,
        )
        stats_fetcher = DataFetcher()
        teams = [("T1 Esports", "lck"), ("Dplus KIA", "lck")]
        rows = []
        for team, league in teams:
            stats = stats_fetcher.get_team_stats(team, league)
            rows.append({
                "Time": team,
                "Tier": stats.get("tier", "-"),
                "Win Rate": f"{_positive_stat(stats, 'winrate', 0.5) * 100:.0f}%",
                "Média de kills": f"{_positive_stat(stats, 'avg_kills', 14.5):.1f}",
                "Duração média": f"{_positive_stat(stats, 'avg_game_length', 31.5):.1f} min",
                "Torres/jogo": f"{_positive_stat(stats, 'avg_towers', 6.4):.1f}",
                "Dragões/jogo": f"{_positive_stat(stats, 'avg_dragons', 2.4):.1f}",
                "Barons/jogo": f"{_positive_stat(stats, 'avg_barons', 0.8):.1f}",
                "First Blood": f"{_positive_stat(stats, 'first_blood_rate', 0.5) * 100:.0f}%",
                "First Dragon": f"{_positive_stat(stats, 'first_dragon_rate', 0.5) * 100:.0f}%",
            })

        c1, c2, c3 = st.columns(3)
        with c1:
            st.metric("T1 Win Rate", rows[0]["Win Rate"])
        with c2:
            st.metric("DK Win Rate", rows[1]["Win Rate"])
        with c3:
            st.metric("Liga", "LCK")

        stat_lines = [
            "Win Rate",
            "Média de kills",
            "Duração média",
            "Torres/jogo",
            "Dragões/jogo",
            "Barons/jogo",
            "First Blood",
            "First Dragon",
        ]
        compare_rows = [
            {
                "Linha": line,
                rows[0]["Time"]: rows[0][line],
                rows[1]["Time"]: rows[1][line],
            }
            for line in stat_lines
        ]
        st.dataframe(pd.DataFrame(compare_rows), use_container_width=True, hide_index=True)
        st.markdown(
            '<span class="market-chip">Duração >27min</span>'
            '<span class="market-chip">Moneyline</span>'
            '<span class="market-chip">First Dragon</span>'
            '<span class="market-chip">Gold @15</span>',
            unsafe_allow_html=True,
        )
        st.markdown('</div>', unsafe_allow_html=True)
    st.stop()

if st.session_state.aba == "banca":
    if is_guest():
        st.info("Gestão de banca disponível apenas para o dono.")
        st.stop()

    with st.container():
        st.markdown(
            '<div class="app-card">'
            '<div class="app-card-title">Painel de Controle</div>'
            '<div class="app-card-subtitle">Sincronize a banca manualmente e acompanhe o histórico de apostas.</div>',
            unsafe_allow_html=True,
        )

        col_balance, col_goal, col_button = st.columns([2, 2, 1.1])
        with col_balance:
            new_balance = st.number_input(
                "💵 Saldo atual na BetBoom (R$)",
                min_value=0.0,
                value=banca_atual,
                step=5.0,
                key="sync_balance",
            )
        with col_goal:
            new_goal = st.number_input(
                "🎯 Meta (R$)",
                min_value=0.0,
                value=banca_meta,
                step=50.0,
                key="sync_goal",
            )
        with col_button:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("✅ Sincronizar", use_container_width=True, type="primary", key="sync_btn"):
                st.session_state.banca_atual_sync = float(new_balance)
                st.session_state.banca_meta = float(new_goal)
                sync_banca_to_profile(banca_ini, float(new_goal), float(new_balance))
                st.success(f"Banca sincronizada: R$ {new_balance:.2f}")
                st.rerun()

        st.markdown('</div>', unsafe_allow_html=True)

    if banca_atual <= 0:
        st.info("Insira seu saldo da BetBoom para calcular stakes.")

    render_bankroll_tab(history, _save_history, _calc_bankroll)
    render_profile_settings()
    st.stop()

fetcher = DataFetcher()
analyzer = MatchAnalyzer()
bankroll_mgr = BankrollManager(banca_disponivel, banca_meta, "Kelly (Recomendado)")

if banca_disponivel <= 0:
    st.info("Banca zerada ou não sincronizada. Vá em Gestão de Banca e informe seu saldo para liberar stakes.")

if st.session_state.selected_match:
    match = st.session_state.selected_match
    markets = {
        "Vitória (ML)": True,
        "First Blood": True,
        "First Dragon": True,
        "First Baron": True,
        "Total de Kills (O/U)": True,
        "Duração do Mapa": True,
        "Gold Diff @15min": True,
    }
    cap = LEAGUE_CONFIDENCE_CAP.get(match.get("league_tier", 2), 0.9)
    analysis = analyzer.analyze_match(match, markets, min(70, cap * 100))
    roster1 = get_roster(match["team1"], match.get("league_code", "_unknown"))
    roster2 = get_roster(match["team2"], match.get("league_code", "_unknown"))
    twitch_channel = st.session_state.twitch_custom or match.get("league_code", "_unknown")
    live_stats = {}
    if match.get("state") == "inProgress" and match.get("lolesports_game_id"):
        live_stats = fetcher.fetch_lolesports_live_stats(match.get("lolesports_game_id"))
    render_operation_room(
        match,
        analysis,
        bankroll_mgr,
        None,
        roster1,
        roster2,
        banca_disponivel,
        banca_meta,
        twitch_channel,
        live_stats,
        _register_pending_from_click,
    )
    st.stop()

current_query = st.session_state.get("match_query", "")
with st.spinner("Carregando agenda oficial..."):
    matches_window = _matches_window_seconds()
    matches_bucket = _time_bucket(matches_window)
    st.session_state.matches, st.session_state.matches_source = _load_matches_cached(
        f"{matches_window}:{matches_bucket}",
        current_query,
    )

all_matches = list(st.session_state.matches)
oddspapi_odds = _load_oddspapi_cached(_five_minute_key(), all_matches)
if oddspapi_odds:
    enriched_matches = []
    for match in all_matches:
        odds = oddspapi_odds.get(odds_pair_key(match.get("team1", ""), match.get("team2", "")))
        if odds:
            enriched_matches.append({
                **match,
                "odds_team1": odds.get("team1"),
                "odds_team2": odds.get("team2"),
                "odds_source": odds.get("source", "OddsPapi"),
                "odds_bookmaker": odds.get("bookmaker", ""),
            })
        else:
            enriched_matches.append(match)
    all_matches = enriched_matches

history, banca_atual, settled_bets = _auto_settle_pending_bets(all_matches, banca_atual)
if settled_bets:
    st.toast(f"{len(settled_bets)} aposta(s) pendente(s) liquidada(s).")
    st.rerun()

banca_disponivel = _available_bankroll(banca_atual, history)
bankroll_mgr = BankrollManager(banca_disponivel, banca_meta, "Kelly (Recomendado)")

source_counts = Counter(match.get("source", "Agenda") for match in all_matches)
source_summary = " + ".join(f"{source} ({count})" for source, count in source_counts.most_common())
markets = {
    "Vitória (ML)": True,
    "First Blood": True,
    "First Dragon": True,
    "First Baron": True,
    "Total de Kills (O/U)": True,
    "Duração do Mapa": True,
    "Gold Diff @15min": True,
}


def _analyze(match: dict) -> tuple[str, dict]:
    try:
        cap = LEAGUE_CONFIDENCE_CAP.get(match.get("league_tier", 2), 0.9)
        result = analyzer.analyze_match(match, markets, min(70, cap * 100))
        return f"{match['team1']}|{match['team2']}", result
    except Exception:
        return f"{match.get('team1', '')}|{match.get('team2', '')}", {}


analysis_map = {}
if all_matches:
    with ThreadPoolExecutor(max_workers=6) as pool:
        analysis_map = dict(pool.map(_analyze, all_matches))

live_count = sum(1 for match in all_matches if match.get("state") == "inProgress")
next_count = max(0, len(all_matches) - live_count)
with st.container():
    st.markdown('<div class="premium-title">LOL PREDICTOR PRO</div>', unsafe_allow_html=True)
    odds_status = "OddsPapi conectado 🟢" if oddspapi_odds else "OddsPapi sem odds para estes jogos 🟡"
    st.markdown(f'<div class="premium-api-status">Agenda: {source_summary or st.session_state.matches_source} · {odds_status}</div>', unsafe_allow_html=True)
    render_hero(live_count, next_count, source_summary or st.session_state.matches_source)

LEAGUE_FILTERS = [
    ("msi", "MSI"),
    ("cblol", "CBLOL"),
    ("cblol_acad", "CBLOL Academy"),
    ("lck", "LCK"),
    ("lck_cl", "LCK Challengers"),
    ("lpl", "LPL"),
    ("lec", "LEC"),
    ("lcs", "LCS"),
    ("lcs_acad", "NACL"),
    ("lla", "LLA"),
    ("vcs", "VCS"),
    ("tcl", "TCL"),
    ("pcs", "PCS/LCP"),
    ("ewc", "EWC"),
]

league_counts: dict[str, int] = {}
for match in all_matches:
    code = match.get("league_code", "_unknown")
    league_counts[code] = league_counts.get(code, 0) + 1

_render_sidebar_league_hamburger(LEAGUE_FILTERS, league_counts, st.session_state.league_filter, banca_disponivel)

if st.session_state.aba == "analise_apostas":
    st.markdown('<div class="premium-title">ANÁLISE DE APOSTAS</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="app-card">'
        '<div class="app-card-title">Mercados sugeridos</div>'
        '<div class="app-card-subtitle">Análises geradas com os mesmos jogos reais carregados da PandaScore.</div>',
        unsafe_allow_html=True,
    )

    visible_matches = filter_matches_by_time(all_matches, st.session_state.time_filter)
    if st.session_state.league_filter != "all":
        visible_matches = [m for m in visible_matches if m.get("league_code") == st.session_state.league_filter]

    if not visible_matches:
        st.info("Nenhum jogo disponível para análise neste filtro.")
    else:
        for index, match in enumerate(visible_matches[:8]):
            key = f"{match.get('team1', '')}|{match.get('team2', '')}"
            analysis = analysis_map.get(key, {})
            predictions = analysis.get("predictions", [])
            top_pick = predictions[0] if predictions else None
            with st.container(border=True):
                c_match, c_pick, c_action = st.columns([2.2, 2.6, 1])
                with c_match:
                    st.markdown(
                        f'**{match.get("team1", "Time 1")} vs {match.get("team2", "Time 2")}**  \n'
                        f'{match.get("league_display", match.get("league", "LoL"))} · {match.get("datetime_brt", "")}'
                    )
                with c_pick:
                    if top_pick:
                        st.markdown(
                            f'**{top_pick.get("market", "Mercado")}**  \n'
                            f'{top_pick.get("suggestion", "")} · confiança **{top_pick.get("confidence", 0):.0f}%**'
                        )
                    else:
                        st.caption("Sem pick acima do corte de confiança para este jogo.")
                with c_action:
                    if st.button("Abrir", key=f"analysis_open_{index}_{hashlib.md5(key.encode()).hexdigest()[:8]}", use_container_width=True, type="primary"):
                        st.session_state.selected_match = match
                        st.rerun()

    st.markdown('</div>', unsafe_allow_html=True)
    st.stop()

top_a, top_b, top_c = st.columns(3)
with top_a:
    st.markdown(
        f'<div class="app-card"><div class="app-card-title">{live_count}</div>'
        '<div class="app-card-subtitle">Jogos ao vivo reais</div></div>',
        unsafe_allow_html=True,
    )
with top_b:
    st.markdown(
        f'<div class="app-card"><div class="app-card-title">{next_count}</div>'
        '<div class="app-card-subtitle">Próximos jogos no calendário</div></div>',
        unsafe_allow_html=True,
    )
with top_c:
    st.markdown(
        f'<div class="app-card"><div class="app-card-title">R$ {banca_disponivel:.2f}</div>'
        f'<div class="app-card-subtitle">Banca disponível · Exposição R$ {pending_exposure(history):.2f}</div></div>',
        unsafe_allow_html=True,
    )

main_col, coupon_col = st.columns([5.2, 1.35], gap="medium")

with main_col:
    st.markdown(
        '<div class="app-card">'
        '<div class="app-card-title">Jogos de Hoje</div>'
        '<div class="app-card-subtitle">Busque partidas, filtre horários e abra a sala de operação.</div>',
        unsafe_allow_html=True,
    )
    _render_priority_strip(all_matches)
    search_col, search_btn_col, t1_col, t2_col, manual_btn_col, refresh_col = st.columns([3, .8, 1.2, 1.2, .95, .5])
    with search_col:
        query = st.text_input(
            "",
            placeholder="🔍 Buscar time ou evento (KaBuM, T1, LOUD...)",
            key="match_query",
            label_visibility="collapsed",
        )
    with search_btn_col:
        if st.button("Buscar", use_container_width=True, type="primary", key="search_btn"):
            st.cache_data.clear()
            with st.spinner("Buscando jogos..."):
                st.session_state.matches, st.session_state.matches_source = fetcher.cargo_search(query)
            st.rerun()
    with t1_col:
        manual_t1 = st.text_input("", placeholder="Time 1", key="manual_t1", label_visibility="collapsed")
    with t2_col:
        manual_t2 = st.text_input("", placeholder="Time 2", key="manual_t2", label_visibility="collapsed")
    with manual_btn_col:
        if st.button("Analisar", use_container_width=True, type="primary", key="manual_btn"):
            if manual_t1.strip() and manual_t2.strip():
                match = fetcher.build_manual_match(manual_t1.strip(), manual_t2.strip())
                match["_stats_t1_override"] = _load_stats_cached(_five_minute_key(), manual_t1.strip()) or None
                match["_stats_t2_override"] = _load_stats_cached(_five_minute_key(), manual_t2.strip()) or None
                st.session_state.selected_match = match
                st.rerun()
            else:
                st.error("Preencha os dois times.")
    with refresh_col:
        if st.button("↻", use_container_width=True, help="Recarregar agenda", key="refresh_btn"):
            st.cache_data.clear()
            st.session_state.matches = []
            st.rerun()

    filter_labels = [
        ("live", "Ao Vivo"),
        ("all", "Todos"),
        ("1h", "1h"),
        ("3h", "3h"),
        ("6h", "6h"),
        ("12h", "12h"),
        ("24h", "24h"),
        ("2d", "2d"),
        ("3d", "3d"),
    ]
    filter_cols = st.columns(len(filter_labels))
    for index, (key, label) in enumerate(filter_labels):
        with filter_cols[index]:
            if st.button(
                label,
                use_container_width=True,
                key=f"time_filter_{key}",
                type="primary" if st.session_state.time_filter == key else "secondary",
            ):
                st.session_state.time_filter = key
                st.rerun()

    filtered_matches = filter_matches_by_time(all_matches, st.session_state.time_filter)
    if st.session_state.league_filter != "all":
        filtered_matches = [m for m in filtered_matches if m.get("league_code") == st.session_state.league_filter]

    selected_id = None
    if st.session_state.selected_match:
        selected = st.session_state.selected_match
        selected_id = hashlib.md5((selected["team1"] + selected["team2"]).encode()).hexdigest()[:8]

    _render_premium_match_board(filtered_matches, analysis_map, bankroll_mgr, _register_pending_from_click)
    st.markdown('</div>', unsafe_allow_html=True)

with coupon_col:
    render_coupon_panel(st.session_state.selected_match, banca_disponivel)
