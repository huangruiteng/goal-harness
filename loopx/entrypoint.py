from __future__ import annotations

import sys

from . import __version__


def main(argv: list[str] | None = None) -> int:
	raw_argv = sys.argv[1:] if argv is None else list(argv)
	if raw_argv == ["--version"]:
		print(f"loopx {__version__}")
		return 0

	from .cli import main as cli_main

	return cli_main(raw_argv)
