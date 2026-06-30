from __future__ import annotations

import tkinter as tk

try:
    from .gui import build_app
except ImportError:
    # PyInstaller may execute this file as a top-level script, so keep
    # an absolute-import fallback for frozen builds.
    from eztrans.gui import build_app


def main() -> None:
    root = tk.Tk()
    build_app(root)
    root.mainloop()


if __name__ == "__main__":
    main()
