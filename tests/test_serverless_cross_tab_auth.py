from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "serverless_web"


def read(name):
    return (WEB / name).read_text(encoding="utf-8")


def test_every_staging_workflow_reads_shared_member_tokens():
    clients = (
        "index.html",
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
    assert "sessionStorage.getItem('guest_access_token')" in read("index.html")
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


def test_login_keeps_pkce_verifier_and_redirect_on_the_same_origin():
    shell = read("staging-shell.js")
    index = read("index.html")

    assert 'const redirectUri = new URL("/", location.origin).href' in shell
    assert 'sessionStorage.setItem("pkce_redirect_uri", redirectUri)' in shell
    assert 'redirect_uri: redirectUri' in shell
    assert 'const logoutUri = new URL("/", location.origin).href' in shell
    assert 'logout_uri: logoutUri' in shell
    assert "sessionStorage.getItem('pkce_redirect_uri')||new URL('/',location.origin).href" in index
    assert "redirect_uri:redirectUri" in index
    assert "sessionStorage.removeItem('pkce_redirect_uri')" in index
    assert "redirect_uri: config.callback_url" not in shell
    assert "redirect_uri:config.callback_url" not in index


def test_failed_code_exchange_clears_one_use_callback_and_exposes_cognito_error():
    index = read("index.html")

    assert "if(!verifier){discardCallback();throw new Error" in index
    assert "sessionStorage.removeItem('pkce_verifier')" in index
    assert "history.replaceState({},'',location.pathname)" in index
    assert "result.error_description||result.error||`HTTP ${response.status}`" in index
    assert "if(!response.ok||!result.id_token)" in index
    assert "message.startsWith('Cognito sign-in')" in index


def test_community_set_build_uses_shared_tokens_and_refreshes_expired_sessions():
    builder = (ROOT / "dev_setup" / "build_serverless_community.py").read_text(encoding="utf-8")

    assert "localStorage.getItem('id_token')||sessionStorage.getItem('id_token')" in builder
    assert "localStorage.getItem('refresh_token')||sessionStorage.getItem('refresh_token')" in builder
    assert "if(response.status===401&&refreshToken)" in builder
    assert "localStorage.setItem('id_token',token)" in builder
    assert "Session expired. Sign in again." in builder


def test_changed_auth_assets_have_cache_busting_revisions():
    expected = {
        "index.html": ('/staging-shell.js?v=3',),
        "vault.html": ('/staging-shell.js?v=3', '/vault.js?v=13'),
        "history.html": ('/staging-shell.js?v=3', '/history.js?v=10'),
        "admin.html": ('/staging-shell.js?v=3', '/admin.js?v=4'),
        "color-lab.html": ('/staging-shell.js?v=3', '/color-lab.js?v=8'),
        "holographic.html": ('/staging-shell.js?v=3', '/holographic.js?v=6'),
    }

    for filename, revisions in expected.items():
        page = read(filename)
        for revision in revisions:
            assert revision in page

    depthmap_builder = (ROOT / "dev_setup" / "build_serverless_depthmap.py").read_text(encoding="utf-8")
    assert '/staging-shell.js?v=3' in depthmap_builder
    assert '/depthmap_bootstrap.js?v=5' in depthmap_builder
