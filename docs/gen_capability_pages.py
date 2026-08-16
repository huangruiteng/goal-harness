from __future__ import annotations

from pathlib import PurePosixPath

import mkdocs_gen_files

from capability_docs import REPOSITORY_ROOT, documentation_maps, render_markdown


site_to_source, source_to_site = documentation_maps()

for site_path, source_path in sorted(site_to_source.items()):
    with mkdocs_gen_files.open(site_path.as_posix(), "w", encoding="utf-8") as output:
        output.write(
            render_markdown(
                source_path.read_text(encoding="utf-8"),
                source=source_path,
                site=PurePosixPath(site_path),
                source_to_site=source_to_site,
            )
        )
    source_relative = source_path.relative_to(REPOSITORY_ROOT).as_posix()
    mkdocs_gen_files.set_edit_path(site_path.as_posix(), f"../{source_relative}")
