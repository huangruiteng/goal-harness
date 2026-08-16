from __future__ import annotations

from pathlib import Path, PurePosixPath

from capability_docs import documentation_maps, render_markdown


_, SOURCE_TO_SITE = documentation_maps()


def on_page_markdown(markdown, *, page, config, files):  # type: ignore[no-untyped-def]
    source = Path(config.docs_dir) / page.file.src_uri
    if not source.is_file():
        return markdown
    return render_markdown(
        markdown,
        source=source,
        site=PurePosixPath(page.file.src_uri),
        source_to_site=SOURCE_TO_SITE,
    )
