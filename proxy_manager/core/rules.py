"""Motor de regras: parser do DSL de texto, modelo estruturado e o matcher usado pelo engine."""
from __future__ import annotations

import fnmatch
import ipaddress
import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Rule:
    apps: list[str] = field(default_factory=list)  # vazio = qualquer aplicativo
    pattern: str = ""
    action: str = "proxy"  # "direct" | "block" | "proxy" | "proxy:<nome>"
    enabled: bool = True
    line_no: int = 0
    raw_line: str = ""

    @property
    def action_kind(self) -> str:
        if self.action == "direct":
            return "direct"
        if self.action == "block":
            return "block"
        return "proxy"

    @property
    def proxy_name(self) -> Optional[str]:
        if self.action.startswith("proxy:"):
            return self.action.split(":", 1)[1]
        return None

    def apps_label(self) -> str:
        return ", ".join(self.apps) if self.apps else "Qualquer aplicativo"


def _normalize_app(name: str) -> str:
    base = os.path.basename(name.strip())
    return base.lower()


def app_matches(rule_apps: list[str], app_name: str, app_path: str) -> bool:
    if not rule_apps:
        return True
    candidates = {_normalize_app(app_name)}
    if app_path:
        candidates.add(_normalize_app(app_path))
        candidates.add(_normalize_app(os.path.splitext(app_path)[0]))
    if app_name:
        candidates.add(_normalize_app(os.path.splitext(app_name)[0]))
    for wanted in rule_apps:
        w = _normalize_app(wanted)
        w_noext = os.path.splitext(w)[0]
        if w in candidates or w_noext in candidates:
            return True
    return False


def pattern_matches(pattern: str, host: Optional[str], ip: Optional[str]) -> bool:
    pattern = pattern.strip()
    if not pattern:
        return False

    # CIDR ou IP explicito
    if ip:
        try:
            if "/" in pattern:
                network = ipaddress.ip_network(pattern, strict=False)
                if ipaddress.ip_address(ip) in network:
                    return True
            else:
                try:
                    if ipaddress.ip_address(pattern) == ipaddress.ip_address(ip):
                        return True
                except ValueError:
                    pass
        except ValueError:
            pass

    if not host:
        return False
    host_l = host.lower().rstrip(".")

    if pattern.startswith("*."):
        suffix = pattern[2:].lower()
        return host_l == suffix or host_l.endswith("." + suffix)

    if "*" in pattern or "?" in pattern:
        return fnmatch.fnmatch(host_l, pattern.lower())

    return host_l == pattern.lower()


@dataclass
class MatchResult:
    action_kind: str  # "direct" | "block" | "proxy"
    proxy_name: Optional[str]
    rule: Optional[Rule]


class RuleSet:
    def __init__(self, rules: Optional[list[Rule]] = None):
        self.rules: list[Rule] = rules or []

    def match(self, app_name: str, app_path: str, host: Optional[str], ip: Optional[str],
              default_action: str = "direct") -> MatchResult:
        for rule in self.rules:
            if not rule.enabled:
                continue
            if not app_matches(rule.apps, app_name, app_path):
                continue
            if not pattern_matches(rule.pattern, host, ip):
                continue
            return MatchResult(action_kind=rule.action_kind, proxy_name=rule.proxy_name, rule=rule)
        return MatchResult(action_kind=default_action if default_action in ("direct", "block") else "direct",
                            proxy_name=None, rule=None)

    @staticmethod
    def parse(text: str) -> "RuleSet":
        rules: list[Rule] = []
        current_apps: list[str] = []
        for line_no, raw_line in enumerate(text.splitlines(), start=1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.lower().startswith("apps:"):
                value = line.split(":", 1)[1].strip()
                if value == "*" or value == "":
                    current_apps = []
                else:
                    current_apps = [v.strip() for v in value.split(",") if v.strip()]
                continue

            parts = line.split()
            target = parts[0]
            action = "proxy"
            enabled = True
            if target.startswith("!"):
                enabled = False
                target = target[1:]
            for extra in parts[1:]:
                if extra.startswith("+"):
                    action = extra[1:]
            rules.append(Rule(apps=list(current_apps), pattern=target, action=action,
                               enabled=enabled, line_no=line_no, raw_line=raw_line))
        return RuleSet(rules)

    def to_text(self) -> str:
        lines: list[str] = []
        last_apps: Optional[list[str]] = []  # estado inicial = qualquer app
        for rule in self.rules:
            if rule.apps != last_apps:
                if rule.apps:
                    lines.append(f"apps: {', '.join(rule.apps)}")
                else:
                    lines.append("apps: *")
                last_apps = list(rule.apps)
            prefix = "!" if not rule.enabled else ""
            if rule.action == "proxy":
                lines.append(f"{prefix}{rule.pattern}")
            else:
                lines.append(f"{prefix}{rule.pattern} +{rule.action}")
        return "\n".join(lines) + ("\n" if lines else "")
