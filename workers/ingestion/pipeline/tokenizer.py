import tiktoken

_original_get_encoding = tiktoken.get_encoding


class FallbackEncoding:
    def encode(self, text: str) -> list[str]:
        return text.split()

    def decode(self, tokens: list[str]) -> str:
        return " ".join(tokens)


def get_encoding(name: str):
    try:
        return _original_get_encoding(name)
    except Exception:
        return FallbackEncoding()


tiktoken.get_encoding = get_encoding
