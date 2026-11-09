"""Retry helper shared by the HTTP providers."""

from collections.abc import Awaitable, Callable

import httpx
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.providers.base import ProviderError

ATTEMPTS = 3


class Transient(Exception):
    """A response worth retrying: 5xx for reads, 429 for anything."""

    def __init__(self, response: httpx.Response) -> None:
        super().__init__(f"HTTP {response.status_code}")
        self.response = response


async def with_retries[T](
    call: Callable[[], Awaitable[T]], *, service: str, what: str, wait: float
) -> T:
    """Run `call` up to 3 times with exponential backoff on Transient and network errors."""
    retrying = AsyncRetrying(
        retry=retry_if_exception_type((Transient, httpx.TransportError)),
        stop=stop_after_attempt(ATTEMPTS),
        wait=wait_exponential(multiplier=wait, max=10 * wait),
        reraise=True,
    )
    try:
        async for attempt in retrying:
            with attempt:
                return await call()
    except Transient as e:
        raise ProviderError(
            f"{service} returned HTTP {e.response.status_code} for {what} after {ATTEMPTS} tries"
        ) from e
    except httpx.TransportError as e:
        raise ProviderError(f"Could not reach {service} ({type(e).__name__})") from e
    raise AssertionError("unreachable")  # pragma: no cover
