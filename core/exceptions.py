class URLShortenerError(Exception):
    """Base class for this application's domain errors."""

class URLNotFoundError(URLShortenerError):
    """No URL corresponds to the given short code."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(f"no URL for code {code!r}")
