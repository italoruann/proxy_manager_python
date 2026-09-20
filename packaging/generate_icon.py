"""Gera os arquivos de ícone usados no empacotamento (icon.ico pro Windows, icon.png pro Linux)
a partir do mesmo desenho já usado em tempo de execução (proxy_manager.gui.icon.render_icon) —
assim o ícone do executável/atalho é sempre igual ao ícone mostrado na bandeja do sistema."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from proxy_manager.gui.icon import render_icon

OUTPUT_DIR = os.path.dirname(__file__)


def main() -> None:
    app = QApplication.instance() or QApplication([])
    icon = render_icon(active=False, size=256)

    ico_path = os.path.join(OUTPUT_DIR, "icon.ico")
    png_path = os.path.join(OUTPUT_DIR, "icon.png")

    pixmap_256 = icon.pixmap(256, 256)
    pixmap_256.save(ico_path, "ICO")
    pixmap_256.save(png_path, "PNG")

    print(f"Ícone gerado em:\n  {ico_path}\n  {png_path}")
    del app


if __name__ == "__main__":
    main()
