from proxy_manager.core.rules import RuleSet, pattern_matches, app_matches

SAMPLE = """
# comentário deve ser ignorado
*.example.com
*.example.net

*.paypal.com +direct
*.stripe.com +direct

apps: chrome.exe, msedge.exe
*.internal.corp +proxy:vpn
ads.tracker.com +block
"""


def test_parse_basic_rules():
    rs = RuleSet.parse(SAMPLE)
    assert len(rs.rules) == 6
    assert rs.rules[0].pattern == "*.example.com"
    assert rs.rules[0].action == "proxy"
    assert rs.rules[0].apps == []


def test_direct_suffix():
    rs = RuleSet.parse(SAMPLE)
    match = rs.match("firefox", "/usr/bin/firefox", "checkout.stripe.com", None)
    assert match.action_kind == "direct"


def test_default_proxy_when_no_suffix():
    rs = RuleSet.parse(SAMPLE)
    match = rs.match("firefox", "/usr/bin/firefox", "westus.example.com", None)
    assert match.action_kind == "proxy"
    assert match.proxy_name is None  # usa o proxy padrão


def test_named_proxy_suffix():
    rs = RuleSet.parse(SAMPLE)
    match = rs.match("chrome.exe", "C:/chrome.exe", "vpn.internal.corp", None)
    assert match.action_kind == "proxy"
    assert match.proxy_name == "vpn"


def test_block_suffix():
    rs = RuleSet.parse(SAMPLE)
    match = rs.match("chrome.exe", "C:/chrome.exe", "ads.tracker.com", None)
    assert match.action_kind == "block"


def test_app_scoping_restricts_match():
    rs = RuleSet.parse(SAMPLE)
    # ads.tracker.com só está no escopo "chrome.exe, msedge.exe"; firefox não deve casar
    match = rs.match("firefox", "/usr/bin/firefox", "ads.tracker.com", None, default_action="direct")
    assert match.action_kind == "direct"  # cai no default, não bate a regra de bloqueio


def test_no_match_falls_back_to_default():
    rs = RuleSet.parse(SAMPLE)
    match = rs.match("curl", "/usr/bin/curl", "example.org", None, default_action="block")
    assert match.action_kind == "block"


def test_wildcard_domain_matches_base_and_subdomain():
    assert pattern_matches("*.example.com", "example.com", None)
    assert pattern_matches("*.example.com", "sub.example.com", None)
    assert not pattern_matches("*.example.com", "notexample.com", None)


def test_cidr_pattern_matches_ip():
    assert pattern_matches("10.0.0.0/8", None, "10.1.2.3")
    assert not pattern_matches("10.0.0.0/8", None, "11.1.2.3")


def test_exact_ip_pattern():
    assert pattern_matches("1.2.3.4", None, "1.2.3.4")
    assert not pattern_matches("1.2.3.4", None, "1.2.3.5")


def test_app_matches_by_basename_case_insensitive():
    assert app_matches(["chrome.exe"], "Chrome.exe", "C:/Program Files/Chrome.exe")
    assert app_matches(["chrome"], "chrome.exe", "/usr/bin/chrome")
    assert not app_matches(["firefox"], "chrome.exe", "/usr/bin/chrome")


def test_disabled_rule_is_ignored():
    rs = RuleSet.parse("!*.disabled.com +direct\n*.disabled.com +block")
    match = rs.match("app", "", "sub.disabled.com", None)
    assert match.action_kind == "block"


def test_app_scoped_catch_all_sends_only_that_app_via_proxy():
    """Cenário real de uso: 'todo o tráfego do Chrome vai pelo proxy, o resto vai direto' — sem
    precisar de uma regra por domínio, só declarando o app uma vez com um alvo coringa."""
    rs = RuleSet.parse("apps: chrome.exe\n*\n")

    chrome_match = rs.match("chrome.exe", "C:/Program Files/Google/Chrome/chrome.exe",
                             "example.org", None, default_action="direct")
    assert chrome_match.action_kind == "proxy"

    other_match = rs.match("spotify.exe", "C:/Program Files/Spotify/Spotify.exe",
                            "example.org", None, default_action="direct")
    assert other_match.action_kind == "direct"


def test_round_trip_to_text_reparses_equivalently():
    rs = RuleSet.parse(SAMPLE)
    text2 = rs.to_text()
    rs2 = RuleSet.parse(text2)
    assert len(rs.rules) == len(rs2.rules)
    for r1, r2 in zip(rs.rules, rs2.rules):
        assert r1.pattern == r2.pattern
        assert r1.action == r2.action
        assert r1.apps == r2.apps


def test_app_matches_linux_launcher_aliases():
    # /usr/bin/google-chrome é um script que faz exec de /opt/google/chrome/chrome
    assert app_matches(["google-chrome"], "chrome", "/opt/google/chrome/chrome")
    # Chromium em snap (Ubuntu): /snap/bin/chromium roda um processo "chrome"
    assert app_matches(["chromium"], "chrome", "/snap/chromium/3000/usr/lib/chromium-browser/chrome")
    assert app_matches(["microsoft-edge"], "msedge", "/opt/microsoft/msedge/msedge")
    assert not app_matches(["google-chrome"], "firefox", "/usr/lib/firefox/firefox")
