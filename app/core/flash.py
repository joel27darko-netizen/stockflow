"""
Lightweight flash-message helper.

Rather than pulling in a session/cookie-based flash framework, StockFlow
encodes a short message directly into the redirect URL's query string
(?flash=...&flash_type=...). base.html reads it and renders a dismissible
Bootstrap alert. This keeps "your action succeeded/failed" feedback
consistent across every create/update/delete flow without adding
server-side session state.
"""
from urllib.parse import quote
from fastapi.responses import RedirectResponse


def redirect_with_flash(url: str, message: str, flash_type: str = "success", status_code: int = 303) -> RedirectResponse:
    separator = "&" if "?" in url else "?"
    encoded = quote(message)
    return RedirectResponse(f"{url}{separator}flash={encoded}&flash_type={flash_type}", status_code=status_code)
