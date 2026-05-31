from __future__ import annotations

import re
from pathlib import Path

TOKEN_PATTERNS = {
    "telegram_bot_token": re.compile(r"\b\d{8,12}:[A-Za-z0-9_-]{25,}\b"),
    "jwt_like": re.compile(r"\beyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\b"),
    "long_secret": re.compile(r"\b[A-Za-z0-9_-]{40,}\b"),
}


def audit(root: Path) -> list[str]:
    findings: list[str] = []
    for path in root.rglob("*"):
        if path.is_dir() or ".git" in path.parts or "node_modules" in path.parts:
            continue
        if path.suffix.lower() not in {".md", ".ts", ".tsx", ".js", ".json", ".env", ".example"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for name, pattern in TOKEN_PATTERNS.items():
            if pattern.search(text):
                findings.append(f"{name}: {path}")
    return findings


if __name__ == "__main__":
    target = Path(r"C:\Users\vanto\Documents\code\sms-forwarder")
    for finding in audit(target):
        print(finding)
