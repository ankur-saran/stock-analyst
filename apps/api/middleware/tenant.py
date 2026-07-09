from jose import JWTError
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from shared.config import Settings
from .auth import _decode_token

settings = Settings()

# Paths that bypass tenant injection — no JWT required
_SKIP_PREFIXES = ("/health", "/docs", "/openapi.json", "/redoc")


def _unauth(detail: str, status: int = 401) -> JSONResponse:
    titles = {401: "Unauthorized", 403: "Forbidden"}
    return JSONResponse(
        status_code=status,
        content={
            "type": f"https://stockanalyst.ai/errors/{titles[status].lower()}",
            "title": titles[status],
            "status": status,
            "detail": detail,
        },
    )


class TenantMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        if any(path == p or path.startswith(p + "/") for p in _SKIP_PREFIXES):
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return _unauth("Bearer token is required")

        token = auth_header[len("Bearer "):]
        try:
            payload = await _decode_token(token)
        except JWTError as exc:
            return _unauth(f"Invalid or expired token: {exc}")

        raw_tenant_id = payload.get("tenant_id")
        if not raw_tenant_id:
            return _unauth("Missing tenant_id claim in token", status=403)

        request.state.tenant_id = str(raw_tenant_id)
        return await call_next(request)
