"""
API Key authentication (tiêu chí 6).

  • Client gửi header  X-API-Key: <key>
  • Key phải trùng biến môi trường AGENT_API_KEY
  • Thiếu hoặc sai key → HTTP 401 (không phải 403 hay 422)
  • Nếu server chưa cấu hình AGENT_API_KEY thì từ chối mọi request (an toàn mặc định)
"""
import hmac

from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader

from app.config import settings

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

_UNAUTHORIZED = HTTPException(
    status_code=401,
    detail="Missing or invalid API key. Include header: X-API-Key: <key>",
    headers={"WWW-Authenticate": "ApiKey"},
)


def verify_api_key(api_key: str | None = Security(api_key_header)) -> str:
    """Dependency cho FastAPI — dùng trong /ask: Depends(verify_api_key)."""
    expected = settings.agent_api_key
    if not api_key or not expected:
        raise _UNAUTHORIZED
    # So sánh hằng thời gian: không lộ độ dài phần khớp qua thời gian phản hồi
    if not hmac.compare_digest(api_key.encode(), expected.encode()):
        raise _UNAUTHORIZED
    return api_key
