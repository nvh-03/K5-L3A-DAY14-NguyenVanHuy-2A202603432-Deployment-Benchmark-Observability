"""
Structured logging (tiêu chí 10): mỗi dòng log của app là đúng 1 JSON object.

Chỉ cấu hình logger "agent" của app (không đụng root logger), nên:
  • log của uvicorn giữ nguyên định dạng riêng;
  • không bị lỗi "basicConfig thành no-op" như Part 1 (root logger bị cấu hình trước).
"""
import json
import logging
import sys
from datetime import datetime, timezone

# Thuộc tính có sẵn của LogRecord — không đưa vào JSON
_STD_ATTRS = set(vars(logging.makeLogRecord({}))) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(timespec="milliseconds"),
            "lvl": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        # Trường bổ sung truyền qua extra={...}
        for key, value in vars(record).items():
            if key not in _STD_ATTRS and not key.startswith("_"):
                entry[key] = value
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        # default=str: giá trị lạ (Exception, Path...) vẫn ra JSON hợp lệ; ensure_ascii giữ 1 dòng an toàn
        return json.dumps(entry, default=str, ensure_ascii=True)


def get_logger(level: str = "INFO") -> logging.Logger:
    logger = logging.getLogger("agent")
    if not logger.handlers:  # tránh gắn handler 2 lần khi module bị import lại
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
        logger.propagate = False  # không đẩy lên root → không bị in lần 2 với định dạng khác
    logger.setLevel(level)
    return logger
