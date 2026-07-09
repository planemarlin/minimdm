from fastapi import Request

from app.config import settings


def client_ip(request: Request) -> str:
    """Return the client IP address.

    When TRUSTED_PROXY=true in settings the first value of X-Forwarded-For is
    used (set by a trusted reverse proxy). Otherwise the direct TCP peer address
    is returned, making IP logging resistant to header spoofing.
    """
    if settings.trusted_proxy:
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
