"""cw2dt entrypoint (minimal dispatcher only).

Core implementation lives in:
  * cw2dt_core.py  - headless CLI + cloning pipeline + helpers
  * cw2dt_gui.py   - Qt GUI frontend using the core pipeline

This file intentionally remains tiny so headless usage avoids importing Qt.
For programmatic use, import needed symbols directly from cw2dt_core.
"""
from __future__ import annotations

import sys
from cw2dt_core import headless_main


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if '--headless' in args:
        # Strip the marker and delegate entirely to core CLI
        return headless_main([a for a in args if a != '--headless'])
    # Lazy import so regular import of this module stays light
    try:
        import cw2dt_gui  # type: ignore
    except ModuleNotFoundError as e:
        if 'PySide6' in str(e) or 'cw2dt_gui' in str(e):
            print('GUI components not installed. Install with: pip install cw2dt[gui]')
            return 1
        raise
    cw2dt_gui.launch()
    return 0


if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())

# End of dispatcher file.
