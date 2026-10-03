from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "serverless_web"


def read(name):
    return (WEB / name).read_text(encoding="utf-8")


def test_every_staging_workflow_reads_shared_member_tokens():
    rasterizer_session = read("rasterizer/session-api-v1.js")
    assert "localStore.getItem('id_token')" in rasterizer_session
    assert "localStore.getItem('refresh_token')" in rasterizer_session
    assert "localStore.setItem('id_token'" in rasterizer_session
    assert "sessionStore.setItem('id_token'" not in rasterizer_session

    clients = (
        "vault.js",
        "history.js",
        "admin.js",
        "color-lab.js",
        "holographic.js",
        "depthmap_bootstrap.js",
    )

    for filename in clients:
        source = read(filename)
        assert 'localStorage.getItem("id_token")' in source or "localStorage.getItem('id_token')" in source
        assert 'localStorage.getItem("refresh_token")' in source or "localStorage.getItem('refresh_token')" in source
        assert 'localStorage.setItem("id_token"' in source or "localStorage.setItem('id_token'" in source
        assert 'sessionStorage.setItem("id_token"' not in source
        assert "sessionStorage.setItem('id_token'" not in source


def test_guest_capabilities_remain_tab_scoped():
    assert "sessionStore.getItem('guest_access_token')" in read("rasterizer/session-api-v1.js")
    assert 'sessionStorage.getItem("color_lab_guest_access_token")' in read("color-lab.js")
    assert 'sessionStorage.getItem("holographic_guest_access_token")' in read("holographic.js")


def test_shell_migrates_existing_session_and_synchronizes_login_state():
    shell = read("staging-shell.js")

    assert 'for (const key of ["id_token", "refresh_token"])' in shell
    assert 'const signedIn = Boolean(localStorage.getItem("id_token"))' in shell
    assert 'event.storageArea !== localStorage || event.key !== "id_token"' in shell
    assert 'Boolean(event.oldValue) !== Boolean(event.newValue)' in shell
    assert 'localStorage.removeItem("id_token")' in shell
    assert 'localStorage.removeItem("refresh_token")' in shell


def test_shell_reconciles_restored_edge_pages_without_a_timing_delay():
    shell = read("staging-shell.js")

    assert 'const reconcileAuthIndicator = () =>' in shell
    assert 'addEventListener("pageshow", reconcileAuthIndicator)' in shell
    assert 'addEventListener("focus", reconcileAuthIndicator)' in shell
    assert 'document.addEventListener("visibilitychange", () =>' in shell
    assert 'if (!document.hidden) reconcileAuthIndicator()' in shell
    assert 'authenticated && !account.classList.contains("authorized")' in shell
    assert "setTimeout" not in shell[shell.index('const reconcileAuthIndicator = () =>'):shell.index('const beginLogin = async () =>')]


def test_login_keeps_pkce_verifier_and_redirect_on_the_same_origin():
    shell = read("staging-shell.js")
    session = read("rasterizer/session-api-v1.js")

    assert 'const redirectUri = new URL("/", location.origin).href' in shell
    assert 'sessionStorage.setItem("pkce_redirect_uri", redirectUri)' in shell
    assert 'redirect_uri: redirectUri' in shell
    assert 'const logoutUri = new URL("/", location.origin).href' in shell
    assert 'logout_uri: logoutUri' in shell
    assert "sessionStore.getItem('pkce_redirect_uri') || new URL('/', locationRoot.origin).href" in session
    assert "redirect_uri: redirectUri" in session
    assert "sessionStore.removeItem('pkce_redirect_uri')" in session
    assert "redirect_uri: config.callback_url" not in shell
    assert "redirect_uri: config.callback_url" not in session


def test_failed_code_exchange_clears_one_use_callback_and_exposes_cognito_error():
    session = read("rasterizer/session-api-v1.js")

    assert "if (!verifier)" in session
    assert "sessionStore.removeItem('pkce_verifier')" in session
    assert "historyRoot.replaceState({}, '', locationRoot.pathname)" in session
    assert "result.error_description || result.error || `HTTP ${response.status}`" in session
    assert "if (!response.ok || !result.id_token)" in session
    assert "Cognito sign-in could not complete" in session


def test_community_set_build_uses_shared_tokens_and_refreshes_expired_sessions():
    client = (ROOT / "static" / "community-set-v1.js").read_text(encoding="utf-8")

    assert "localStorage.getItem('id_token')||sessionStorage.getItem('id_token')" in client
    assert "localStorage.getItem('refresh_token')||sessionStorage.getItem('refresh_token')" in client
    assert "if(response.status===401&&refreshToken)" in client
    assert "localStorage.setItem('id_token',token)" in client
    assert "Session expired. Sign in again." in client


def test_changed_auth_assets_have_cache_busting_revisions():
    expected = {
        "index.html": ('/staging-shell.js?v=4',),
        "vault.html": ('/staging-shell.js?v=4', '/vault.js?v=17'),
        "history.html": ('/staging-shell.js?v=4', '/history.js?v=10'),
        "admin.html": ('/staging-shell.js?v=4', '/admin.js?v=5'),
        "color-lab.html": ('/staging-shell.js?v=4', '/color-lab.js?v=11'),
        "holographic.html": ('/staging-shell.js?v=4', '/holographic.js?v=6'),
    }

    for filename, revisions in expected.items():
        page = read(filename)
        for revision in revisions:
            assert revision in page

    depthmap_builder = (ROOT / "dev_setup" / "build_serverless_depthmap.py").read_text(encoding="utf-8")
    assert '/staging-shell.js?v=4' in depthmap_builder
    assert '/depthmap_bootstrap.js?v=5' in depthmap_builder
