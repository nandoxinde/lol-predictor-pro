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
        min-height:100vh!important;
        background:#050814!important;
        color:#EDE9FE!important;
        font-family:'Inter',sans-serif!important;
        overflow-x:hidden!important;}
    [data-testid="stAppViewContainer"]::before{
        content:"";
        position:fixed;
        inset:0;
        z-index:0;
        pointer-events:none;
        background:
            radial-gradient(circle at 50% 50%,rgba(21,101,192,.18),transparent 28%),
            linear-gradient(90deg,rgba(5,8,20,.92) 0%,rgba(5,8,20,.42) 36%,rgba(5,8,20,.42) 64%,rgba(5,8,20,.92) 100%),
            linear-gradient(180deg,rgba(5,8,20,.35) 0%,rgba(5,8,20,.88) 100%),
            url("https://e1.pxfuel.com/desktop-wallpaper/853/468/desktop-wallpaper-4-summoner-s-rift-rifty.jpg");
        background-size:cover;
        background-position:center center;
        background-repeat:no-repeat;
        filter:saturate(1.08) contrast(1.08) brightness(.78);}
    [data-testid="stAppViewContainer"]::after{
        content:"";
        position:fixed;
        inset:0;
        z-index:0;
        pointer-events:none;
        background:
            radial-gradient(circle at 15% 12%,rgba(59,130,246,.20),transparent 24%),
            radial-gradient(circle at 86% 12%,rgba(168,85,247,.22),transparent 24%),
            linear-gradient(180deg,rgba(0,0,0,.12) 0%,rgba(0,0,0,.62) 100%);}
    .stApp::before{
        content:"";
        position:fixed;
        left:0;
        top:0;
        width:min(34vw,440px);
        height:min(34vw,440px);
        z-index:1;
        pointer-events:none;
        background:url("https://wiki.leagueoflegends.com/en-us/Special:Redirect/file/Mountain_Drake_Render.png") top left/contain no-repeat;
        opacity:.82;
        filter:drop-shadow(0 0 32px rgba(59,130,246,.32));}
    .stApp::after{
        content:"";
        position:fixed;
        right:0;
        top:0;
        width:min(35vw,460px);
        height:min(35vw,460px);
        z-index:1;
        pointer-events:none;
        background:url("https://wiki.leagueoflegends.com/en-us/Special:Redirect/file/Baron_Nashor_Render.png") top right/contain no-repeat;
        opacity:.82;
        filter:drop-shadow(0 0 34px rgba(168,85,247,.36));}
    .main .block-container{
        min-height:100vh!important;
        position:relative!important;
        z-index:2!important;
        max-width:430px!important;
        padding:0!important;
        display:flex!important;
        align-items:center!important;
        justify-content:center!important;}
    section[data-testid="stSidebar"],footer,#MainMenu{display:none!important;}
    [data-testid="stForm"]{
        position:relative;
        width:390px;
        max-width:calc(100vw - 32px);
        margin:0 auto;
        background:
            linear-gradient(180deg,rgba(18,24,38,.96),rgba(7,10,18,.98));
        border:1px solid rgba(200,155,60,.72);
        box-shadow:0 22px 70px rgba(0,0,0,.68),0 0 42px rgba(124,58,237,.22),inset 0 0 0 1px rgba(247,231,178,.08);
        border-radius:10px;
        padding:24px 24px 20px!important;
        backdrop-filter:blur(8px);
        clip-path:polygon(7% 0,93% 0,100% 12%,100% 88%,93% 100%,7% 100%,0 88%,0 12%);}
    [data-testid="stForm"]::before{
        content:"";
        position:absolute;
        inset:-10px;
        z-index:-1;
        border:1px solid rgba(200,155,60,.40);
        clip-path:polygon(8% 0,92% 0,100% 12%,100% 88%,92% 100%,8% 100%,0 88%,0 12%);
        box-shadow:0 0 30px rgba(200,155,60,.18);}
    [data-testid="stForm"]::after{
        content:"";
        position:absolute;
        left:-90px;
        right:-90px;
        top:48%;
        z-index:-1;
        height:1px;
        background:linear-gradient(90deg,transparent,rgba(200,155,60,.55),transparent);
        box-shadow:0 0 22px rgba(168,85,247,.42);}
    .login-title{
        text-align:center;
        color:#F7E7B2;
        font-size:18px;
        line-height:1.25;
        font-weight:900;
        letter-spacing:.2px;
        text-shadow:0 0 18px rgba(200,155,60,.45);
        margin:4px 0 18px;}
    .login-owner-note{
        color:#BDAE7F;
        font-size:11px;
        line-height:1.55;
        text-align:center;
        margin-top:12px;}
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
    @media(max-width:900px){
        .stApp::before,.stApp::after{width:180px;height:180px;opacity:.42;}
    }
    </style>""", unsafe_allow_html=True)

    with st.form("login_form"):
        st.markdown(
            '<div class="login-title">Acesso Exclusivo:<br>O Reino do Preditor</div>',
            unsafe_allow_html=True,
        )
        username = st.text_input(
            "Usuário",
            placeholder="Fernando",
            key="login_user",
        )
        password = st.text_input(
            "Senha",
            type="password",
            placeholder="Digite sua senha...",
            key="login_pass",
        )
        submitted = st.form_submit_button(
            "Login", use_container_width=True, type="primary")
        st.markdown(
            '<div class="login-owner-note">Dono: usuário Fernando — acesso total</div>',
            unsafe_allow_html=True,
        )

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
                st.success("Bem-vindo, " + profile["display_name"] + "!")
                st.rerun()

            elif guest_ok:
                st.session_state.authenticated    = True
                st.session_state.role             = "guest"
                st.session_state.profile          = {"display_name": "Convidado"}
                st.session_state.banca_ini        = 0.0
                st.session_state.banca_meta       = 1000.0
                st.session_state.banca_atual_sync = 0.0
                st.success("Bem-vindo, Convidado! Acesso somente leitura.")
                st.rerun()

            else:
                st.error("Usuário ou senha incorretos.")

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
