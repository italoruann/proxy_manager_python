"""Workers em background (QThread) para operações de rede que não podem travar a GUI."""
from __future__ import annotations

import asyncio

from PySide6.QtCore import QThread, Signal

from ..core import httpproxy, socks5
from ..core.config import ProxyProfile

CANARY_HOST = "1.1.1.1"
CANARY_PORT = 443


class ProxyTestWorker(QThread):
    finished_test = Signal(bool, str)

    def __init__(self, profile: ProxyProfile, parent=None):
        super().__init__(parent)
        self.profile = profile

    def run(self) -> None:
        try:
            ok, message = asyncio.run(self._test())
        except Exception as exc:  # pragma: no cover - rede é imprevisível
            ok, message = False, f"Falha inesperada: {exc}"
        self.finished_test.emit(ok, message)

    async def _test(self) -> tuple[bool, str]:
        profile = self.profile
        if not profile.host or not profile.port:
            return False, "Preencha host e porta antes de testar."
        try:
            if profile.type == "socks5":
                reader, writer = await socks5.dial_upstream_socks5(
                    profile.host, profile.port, CANARY_HOST, CANARY_PORT,
                    profile.username, profile.password, timeout=8.0)
            else:
                reader, writer = await httpproxy.dial_upstream_http_connect(
                    profile.host, profile.port, CANARY_HOST, CANARY_PORT,
                    profile.username, profile.password, timeout=8.0)
            writer.close()
            return True, "Conexão e autenticação OK — o proxy respondeu corretamente."
        except (socks5.Socks5Error, httpproxy.HttpProxyError) as exc:
            return False, f"O proxy recusou a conexão: {exc}"
        except (OSError, asyncio.TimeoutError) as exc:
            return False, f"Não foi possível conectar ao proxy: {exc}"
