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

PROFILE_FILE = "data/profile.json"
DATA_DIR     = "data"

# ── Credenciais fixas ─────────────────────────────────────────────────────
# Convidados: um usuário, qualquer um que souber a senha entra como convidado
GUEST_USERNAME = "convidado"
GUEST_PASSWORD = "lolpro2025"   # ← mude aqui para a senha dos convidados

# ── Perfil padrão do dono ─────────────────────────────────────────────────
DEFAULT_PROFILE = {
    "username":      "Fernando",
    "display_name":  "Fernando",
    "password_hash": hashlib.sha256(b"LolPredictor2025!").hexdigest(),
    "banca_ini":     100.0,
    "banca_meta":    1000.0,
    "banca_atual":   100.0,
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
    html,body,.stApp{background:#0B0D11!important;}
    .main .block-container{padding-top:60px!important;}
    section[data-testid="stSidebar"],footer,#MainMenu{display:none!important;}
    .stButton>button{font-family:'Inter',sans-serif!important;font-weight:700!important;
        border-radius:6px!important;border:none!important;}
    .stButton>button[kind="primary"]{background:#1565C0!important;color:#fff!important;}
    .stTextInput input{background:#0F1520!important;border:1px solid #1E2D45!important;
        color:#C8D4E8!important;border-radius:6px!important;padding:10px 14px!important;
        font-size:15px!important;}
    </style>""", unsafe_allow_html=True)

    _, col, _ = st.columns([1, 1.4, 1])
    with col:
        st.markdown("""
        <div style="text-align:center;padding:0 0 28px;">
          <div style="font-size:48px;margin-bottom:8px;">⚔️</div>
          <div style="font-size:24px;font-weight:900;color:#fff;letter-spacing:-0.5px;">
            Lol<span style="color:#1565C0;"> Pro</span>
            <span style="background:#1565C0;color:#fff;font-size:10px;font-weight:700;
              padding:2px 6px;border-radius:4px;margin-left:6px;vertical-align:middle;">v2.0</span>
          </div>
          <div style="font-size:12px;color:#3A4D65;margin-top:6px;letter-spacing:.5px;">
            PLATAFORMA DE ANÁLISE PREDITIVA · ACESSO RESTRITO
          </div>
        </div>""", unsafe_allow_html=True)

        st.markdown(
            '<div style="background:#0F1520;border:1px solid #1E2D45;border-radius:10px;'
            'padding:28px 24px;">', unsafe_allow_html=True)

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
                owner_ok = (
                    u == profile["username"].lower() and
                    _hash(p) == profile["password_hash"]
                )
                # Verifica convidado
                guest_ok = (
                    u == GUEST_USERNAME and
                    p == GUEST_PASSWORD
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
                    st.session_state.banca_ini        = 100.0
                    st.session_state.banca_meta       = 1000.0
                    st.session_state.banca_atual_sync = 100.0
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
            '🔑 <b style="color:#5A7090;">Dono:</b> usuário <code>Fernando</code> '
            '— acesso total<br>'
            '👥 <b style="color:#5A7090;">Convidado:</b> usuário <code>convidado</code> '
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

        # Senha dos convidados
        st.markdown("---")
        st.markdown(
            '<span style="font-size:12px;color:#5A7090;">👥 Senha atual dos convidados: '
            f'<code>{GUEST_PASSWORD}</code> '
            '(altere diretamente no código: <code>GUEST_PASSWORD</code> no auth.py)</span>',
            unsafe_allow_html=True)

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
