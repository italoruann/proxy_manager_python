"""Persistência leve do par (IP anterior, IP atual) de saída por perfil de proxy — sobrevive a
fechar e reabrir o app. Não é o histórico de conexões (isso já mora no LogStore/SQLite); é só o
suficiente pro indicador do Dashboard continuar mostrando "antes → depois" na próxima abertura,
em vez de resetar pra "sem dados ainda"."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import data_dir

EgressIpState = dict[str, tuple[str, str]]  # profile_id -> (ip_anterior, ip_atual)


def _state_file_path() -> Path:
    return data_dir() / "egress_ip_state.json"


def load_egress_ip_state() -> EgressIpState:
    path = _state_file_path()
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw: dict[str, Any] = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}
    state: EgressIpState = {}
    for profile_id, entry in raw.items():
        if isinstance(entry, dict) and entry.get("current"):
            state[profile_id] = (entry.get("previous", ""), entry["current"])
    return state


def save_egress_ip_state(state: EgressIpState) -> None:
    path = _state_file_path()
    data = {profile_id: {"previous": previous, "current": current}
            for profile_id, (previous, current) in state.items()}
    tmp_path = path.with_suffix(".json.tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
        tmp_path.replace(path)
    except OSError:
        pass  # não crítico — na pior das hipóteses, o indicador volta a "sem dados ainda"
