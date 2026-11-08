"""Internal service authentication.

Every route except /healthz requires the shared `X-Service-Token` header,
compared in constant time.
"""

import hmac
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status

from app.config import Settings, get_settings


def require_service_token(
    settings: Annotated[Settings, Depends(get_settings)],
    x_service_token: Annotated[str | None, Header()] = None,
) -> None:
    expected = settings.service_token.get_secret_value().encode()
    provided = (x_service_token or "").encode()
    # compare_digest is constant-time for equal-length inputs and safe for unequal ones.
    if not expected or not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthorized")
