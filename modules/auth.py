"""
modules/auth.py v2.1
Dois níveis de acesso:
  - Dono (Fernando): acesso total — banca, configurações, tudo
  - Convidado: acesso somente leitura — vê os jogos e análises, não mexe na banca
"""

import streamlit as st
import hashlib
import json
import os
from modules.config import get_secret

PROFILE_FILE = "data/profile.json"
DATA_DIR     = "data"

OWNER_USERNAME = get_secret("LOL_OWNER_USERNAME", "Fernando")
OWNER_PASSWORD = get_secret("LOL_OWNER_PASSWORD")
OWNER_PASSWORD_HASH = get_secret("LOL_OWNER_PASSWORD_HASH") or (
    hashlib.sha256(OWNER_PASSWORD.encode()).hexdigest() if OWNER_PASSWORD else ""
)
GUEST_USERNAME = get_secret("LOL_GUEST_USERNAME", "convidado")
GUEST_PASSWORD = get_secret("LOL_GUEST_PASSWORD")
GUEST_PASSWORD_HASH = get_secret("LOL_GUEST_PASSWORD_HASH") or (
    hashlib.sha256(GUEST_PASSWORD.encode()).hexdigest() if GUEST_PASSWORD else ""
)

# ── Perfil padrão do dono ─────────────────────────────────────────────────
DEFAULT_PROFILE = {
    "username":      OWNER_USERNAME,
    "display_name":  "Fernando",
    "password_hash": OWNER_PASSWORD_HASH,
    "banca_ini":     0.0,
    "banca_meta":    1000.0,
    "banca_atual":   0.0,
    "strategy":      "Kelly (Recomendado)",
}

def _load_profile() -> dict:
    try:
        with open(PROFILE_FILE) as f:
            p = json.load(f)
        for k, v in DEFAULT_PROFILE.items():
            p.setdefault(k, v)
        return p
    except Exception:
        return dict(DEFAULT_PROFILE)

def _save_profile(p: dict):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(PROFILE_FILE, "w") as f:
        json.dump(p, f, indent=2, ensure_ascii=False)

def _hash(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()

def is_guest() -> bool:
    """Retorna True se o usuário logado é convidado (somente leitura)."""
    return st.session_state.get("role") == "guest"

def is_owner() -> bool:
    """Retorna True se o usuário logado é o dono (acesso total)."""
    return st.session_state.get("role") == "owner"

# ── check_auth ────────────────────────────────────────────────────────────
def check_auth() -> bool:
    """Retorna True se autenticado (dono ou convidado)."""
    if st.session_state.get("authenticated"):
        return True
    _render_login()
    return False

# ── Tela de Login ─────────────────────────────────────────────────────────
def _render_login():
    profile = _load_profile()

    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800;900&display=swap');
    html,body,.stApp,[data-testid="stAppViewContainer"]{
        background:#06030D!important;
        color:#EDE9FE!important;
        font-family:'Inter',sans-serif!important;
        overflow-x:hidden!important;}
    [data-testid="stAppViewContainer"]::before{
        content:"";
        position:fixed;
        inset:-4%;
        z-index:0;
        pointer-events:none;
        background:
            radial-gradient(circle at 50% 34%,rgba(216,180,254,.22),transparent 22%),
            linear-gradient(90deg,rgba(5,3,13,.98) 0%,rgba(16,8,31,.28) 42%,rgba(5,3,13,.96) 100%),
            linear-gradient(180deg,rgba(5,3,13,.10) 0%,rgba(5,3,13,.70) 72%,#05030D 100%),
            url("https://wiki.leagueoflegends.com/en-us/Special:Redirect/file/Baron_Nashor_Splash_concept_01.jpg");
        background-size:cover;
        background-position:center 34%;
        filter:saturate(1.18) contrast(1.12) brightness(.86);
        animation:baronBreath 14s ease-in-out infinite alternate;}
    [data-testid="stAppViewContainer"]::after{
        content:"";
        position:fixed;
        inset:0;
        z-index:0;
        pointer-events:none;
        background:
            radial-gradient(circle at 50% 30%,rgba(216,180,254,.16),transparent 16%),
            radial-gradient(circle at 34% 58%,rgba(124,58,237,.14),transparent 24%),
            linear-gradient(180deg,transparent 0%,rgba(8,4,18,.72) 100%);
        animation:voidMist 9s ease-in-out infinite alternate;}
    .main .block-container{
        position:relative!important;
        z-index:1!important;
        padding-top:34px!important;
        max-width:1040px!important;}
    section[data-testid="stSidebar"],footer,#MainMenu{display:none!important;}
    .baron-hero{
        text-align:center;
        padding:0 0 10px;
        position:relative;}
    .baron-mark{
        width:84px;height:84px;margin:0 auto 8px;
        border-radius:18px;
        background:
            linear-gradient(135deg,rgba(216,180,254,.18),rgba(15,23,42,.88)),
            radial-gradient(circle at 50% 35%,rgba(250,245,255,.60),rgba(168,85,247,.22) 36%,transparent 72%);
        border:1px solid rgba(200,155,60,.58);
        box-shadow:0 0 28px rgba(168,85,247,.48),inset 0 0 20px rgba(250,245,255,.10);
        display:flex;align-items:center;justify-content:center;
        transform:rotate(45deg);
        animation:baronPulse 2.8s ease-in-out infinite;}
    .baron-mark span{
        font-size:42px;
        filter:drop-shadow(0 0 16px rgba(216,180,254,.85));
        transform:rotate(-45deg) translateY(-1px);}
    .baron-title{
        font-size:18px;
        line-height:1;
        font-weight:900;
        color:#F7E7B2;
        letter-spacing:-.8px;
        text-shadow:0 0 18px rgba(200,155,60,.45),0 2px 0 #05030D;}
    .baron-title b{color:#C084FC;}
    .baron-badge{
        background:linear-gradient(135deg,#7C3AED,#2563EB);
        color:#fff;
        font-size:10px;
        font-weight:900;
        padding:2px 6px;
        border-radius:5px;
        margin-left:6px;
        vertical-align:middle;}
    .baron-subtitle{
        color:#BDAE7F;
        font-size:10px;
        font-weight:800;
        letter-spacing:1.8px;
        margin-top:8px;
        text-transform:uppercase;}
    .baron-login-panel{
        position:relative;
        max-width:360px;
        margin:0 auto;
        background:
            linear-gradient(180deg,rgba(27,31,43,.94),rgba(8,10,18,.96));
        border:1px solid rgba(200,155,60,.72);
        box-shadow:0 22px 70px rgba(0,0,0,.68),0 0 42px rgba(124,58,237,.22),inset 0 0 0 1px rgba(247,231,178,.08);
        border-radius:10px;
        padding:22px 24px 18px;
        backdrop-filter:blur(8px);}
    .baron-login-panel::before{
        content:"";
        position:absolute;
        inset:-10px;
        z-index:-1;
        border:1px solid rgba(200,155,60,.40);
        clip-path:polygon(8% 0,92% 0,100% 12%,100% 88%,92% 100%,8% 100%,0 88%,0 12%);
        box-shadow:0 0 30px rgba(200,155,60,.18);}
    .baron-login-panel::after{
        content:"";
        position:absolute;
        left:-90px;
        right:-90px;
        top:48%;
        z-index:-1;
        height:1px;
        background:linear-gradient(90deg,transparent,rgba(200,155,60,.55),transparent);
        box-shadow:0 0 22px rgba(168,85,247,.42);}
    .stButton>button{
        font-family:'Inter',sans-serif!important;
        font-weight:900!important;
        border-radius:10px!important;
        border:1px solid rgba(216,180,254,.36)!important;
        min-height:46px!important;
        transition:all .18s ease!important;}
    .stButton>button[kind="primary"]{
        background:linear-gradient(135deg,#0E7490,#1D4ED8)!important;
        color:#fff!important;
        border-color:rgba(103,232,249,.55)!important;
        box-shadow:0 0 28px rgba(34,211,238,.30)!important;}
    .stButton>button[kind="primary"]:hover{
        transform:translateY(-1px)!important;
        box-shadow:0 0 42px rgba(34,211,238,.46)!important;}
    .stTextInput input{
        background:rgba(10,12,24,.86)!important;
        border:1px solid rgba(168,85,247,.34)!important;
        color:#F5F3FF!important;
        border-radius:10px!important;
        padding:11px 14px!important;
        font-size:15px!important;}
    .stTextInput input:focus{
        border-color:#C084FC!important;
        box-shadow:0 0 0 1px rgba(192,132,252,.35),0 0 20px rgba(124,58,237,.24)!important;}
    @keyframes baronBreath{
        0%{transform:scale(1.00) translate3d(0,0,0);background-position:center 34%;}
        100%{transform:scale(1.055) translate3d(-12px,-10px,0);background-position:center 29%;}}
    @keyframes voidMist{
        0%{opacity:.56;transform:translateX(-16px);}
        100%{opacity:.86;transform:translateX(18px);}}
    @keyframes baronPulse{
        0%,100%{transform:scale(1);box-shadow:0 0 34px rgba(168,85,247,.62),inset 0 0 22px rgba(250,245,255,.18);}
        50%{transform:scale(1.045);box-shadow:0 0 58px rgba(216,180,254,.78),inset 0 0 30px rgba(250,245,255,.28);}}
    </style>""", unsafe_allow_html=True)

    _, col, _ = st.columns([1, 1.05, 1])
    with col:
        st.markdown("""
        <div class="baron-hero">
          <div class="baron-mark"><span>♛</span></div>
          <div class="baron-title">Lol Predictor<b> Pro</b><span class="baron-badge">v2.0</span></div>
          <div class="baron-subtitle">Log in to your account</div>
        </div>""", unsafe_allow_html=True)

        st.markdown(
            '<div class="baron-login-panel">', unsafe_allow_html=True)

        with st.form("login_form"):
            username = st.text_input("👤 Usuário",
                placeholder="Fernando ou convidado",
                key="login_user")
            password = st.text_input("🔑 Senha",
                type="password",
                placeholder="Digite sua senha...",
                key="login_pass")
            submitted = st.form_submit_button(
                "ENTRAR →", use_container_width=True, type="primary")

            if submitted:
                u = username.strip().lower()
                p = password.strip()

                # Verifica dono
                owner_hash = OWNER_PASSWORD_HASH or profile.get("password_hash", "")
                owner_ok = (
                    u == profile["username"].lower() and
                    bool(owner_hash) and
                    _hash(p) == owner_hash
                )
                # Verifica convidado
                guest_ok = (
                    u == GUEST_USERNAME and
                    bool(GUEST_PASSWORD_HASH) and
                    _hash(p) == GUEST_PASSWORD_HASH
                )

                if owner_ok:
                    st.session_state.authenticated    = True
                    st.session_state.role             = "owner"
                    st.session_state.profile          = profile
                    st.session_state.banca_ini        = float(profile["banca_ini"])
                    st.session_state.banca_meta       = float(profile["banca_meta"])
                    st.session_state.banca_atual_sync = float(profile["banca_atual"])
                    st.success("✅ Bem-vindo, " + profile["display_name"] + "!")
                    st.rerun()

                elif guest_ok:
                    st.session_state.authenticated    = True
                    st.session_state.role             = "guest"
                    st.session_state.profile          = {"display_name": "Convidado"}
                    st.session_state.banca_ini        = 0.0
                    st.session_state.banca_meta       = 1000.0
                    st.session_state.banca_atual_sync = 0.0
                    st.success("✅ Bem-vindo, Convidado! Acesso somente leitura.")
                    st.rerun()

                else:
                    st.error("❌ Usuário ou senha incorretos.")

        st.markdown('</div>', unsafe_allow_html=True)

        # Dica de usuários disponíveis
        st.markdown(
            '<div style="background:#0d1520;border:1px solid #1E2D4555;border-radius:8px;'
            'padding:12px 16px;margin-top:12px;">'
            '<div style="font-size:11px;color:#3A4D65;line-height:1.8;">'
            '🔑 <b style="color:#5A7090;">Dono:</b> usuário configurado no <code>.env</code> '
            '— acesso total<br>'
            '👥 <b style="color:#5A7090;">Convidado:</b> opcional via <code>LOL_GUEST_PASSWORD</code> '
            '— somente análises'
            '</div></div>',
            unsafe_allow_html=True)

# ── Banner de convidado ───────────────────────────────────────────────────
def render_guest_banner():
    """Exibe aviso quando logado como convidado."""
    if is_guest():
        st.markdown(
            '<div style="background:#1a1200;border:1px solid #F59E0B44;border-radius:6px;'
            'padding:7px 14px;margin-bottom:8px;">'
            '<span style="font-size:12px;color:#F59E0B;font-weight:600;">'
            '👥 Modo Convidado — somente leitura. '
            'Gestão de Banca e configurações disponíveis apenas para o dono.'
            '</span></div>',
            unsafe_allow_html=True)

# ── Painel de Configurações de Perfil ────────────────────────────────────
def render_profile_settings():
    """Configurações do dono. Bloqueado para convidados."""
    if is_guest():
        st.info("⚠️ Configurações disponíveis apenas para o dono.")
        if st.button("🚪 Sair", key="btn_logout_guest", type="secondary"):
            st.session_state.authenticated = False
            st.session_state.role = None
            st.rerun()
        return

    profile = _load_profile()

    st.markdown(
        '<div style="background:#0F1520;border:1px solid #1565C044;border-radius:8px;'
        'padding:14px 16px;margin-bottom:16px;">'
        '<span style="font-size:11px;font-weight:700;color:#1565C0;letter-spacing:1px;">'
        '⚙️ CONFIGURAÇÕES DE PERFIL</span>'
        '</div>', unsafe_allow_html=True)

    with st.form("profile_form"):
        c1, c2 = st.columns(2)
        with c1:
            new_name = st.text_input("👤 Nome de exibição",
                value=profile["display_name"], key="pf_name")
            new_user = st.text_input("🔑 Usuário de login",
                value=profile["username"], key="pf_user")
        with c2:
            new_pass  = st.text_input("🔒 Nova senha do dono",
                type="password", placeholder="Nova senha...", key="pf_pass")
            new_pass2 = st.text_input("🔒 Confirmar nova senha",
                type="password", placeholder="Confirmar...", key="pf_pass2")

        if st.form_submit_button("💾 Salvar Perfil",
                                  use_container_width=True, type="primary"):
            if new_pass and new_pass != new_pass2:
                st.error("As senhas não coincidem.")
            else:
                profile["display_name"] = new_name.strip() or profile["display_name"]
                profile["username"]     = new_user.strip() or profile["username"]
                if new_pass:
                    profile["password_hash"] = _hash(new_pass)
                _save_profile(profile)
                st.session_state.profile = profile
                st.success("✅ Perfil atualizado!")

    st.markdown("---")
    if st.button("🚪 Sair (Logout)", key="btn_logout", type="secondary"):
        st.session_state.authenticated = False
        st.session_state.role = None
        st.rerun()

# ── Salva banca ───────────────────────────────────────────────────────────
def sync_banca_to_profile(banca_ini: float, banca_meta: float, banca_atual: float):
    """Persiste banca. Só funciona para o dono."""
    if is_guest():
        return  # convidados não alteram a banca
    profile = _load_profile()
    profile["banca_ini"]   = banca_ini
    profile["banca_meta"]  = banca_meta
    profile["banca_atual"] = banca_atual
    _save_profile(profile)
