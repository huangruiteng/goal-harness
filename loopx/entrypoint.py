from __future__ import annotations

import sys

from . import __version__


def main(argv: list[str] | None = None) -> int:
	"""Keep the version path tiny, then load the selected CLI runtime."""

	raw_argv = sys.argv[1:] if argv is None else list(argv)
	if raw_argv == ["--version"]:
		print(f"loopx {__version__}")
		return 0

	from .cli_runtime import main as runtime_main

	return runtime_main(argv)


if __name__ == "__main__":
	raise SystemExit(main())
