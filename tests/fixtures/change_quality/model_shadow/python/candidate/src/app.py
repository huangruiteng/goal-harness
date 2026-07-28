class TagNormalizer:
    def normalize(self, tag: str) -> str:
        return tag.strip().lower()


def normalize_tag(tag: str) -> str:
    return TagNormalizer().normalize(tag)
