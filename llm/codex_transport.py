# -*- coding: utf-8 -*-
"""Codex 전송 계층 — ChatGPT 구독 OAuth. **API 키를 쓰지 않는다.**

`~/.codex/auth.json` 의 ChatGPT OAuth 토큰을 읽어
`https://chatgpt.com/backend-api/codex/responses` 에 직접 POST 하고 SSE 를 파싱한다.
헤더의 `originator: codex_cli_rs` 가 말하듯 **Codex CLI 가 쓰는 내부(비공식)
엔드포인트**다. 공개 SDK 가 아니므로 바뀔 수 있다.

★ 이 파일은 원래 `imgstudio/services/codex_image.py` 안에 있었다. 그림 수백 장을
  이 길로 구웠고 동작이 검증돼 있다 — **로직은 자리만 옮겼다.** 버전 탐지 하나만
  손봤다(아래 `_detect_codex_version` 주석).

  옮긴 이유는 의존 방향이다. 파이프라인(`llm/codex_provider.py`)도 같은 전송을
  써야 하는데, `llm/` 이 `imgstudio/` 를 import 하면 거꾸로다. 여기로 내리고
  `codex_image.py` 가 re-export 하면 imgstudio 쪽은 한 줄도 안 고쳐도 된다.

  엔드포인트가 바뀌면 **이 파일 하나만** 고치면 된다. 그것이 한곳에 모은 값이다.
"""
from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import time
import uuid
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Iterator, List, Optional, Tuple

# ── 상수 (chatgpt-imagegen 차용) ─────────────────────────────────────────────
CODEX_BACKEND = "https://chatgpt.com/backend-api/codex/responses"
OAUTH_TOKEN_URL = "https://auth.openai.com/oauth/token"
OAUTH_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"  # Codex CLI 공개 client id
FALLBACK_VERSION = "0.130.0"
FALLBACK_UA = f"codex_cli_rs/{FALLBACK_VERSION} (Windows 11; x64) image-studio"
AUTH_PATH = Path(os.environ.get("CODEX_AUTH_PATH", str(Path.home() / ".codex" / "auth.json")))
VERSION_PATH = Path.home() / ".codex" / "version.json"

# 요청에 싣는 추론 모델. 그림은 이 모델 안의 `image_generation` 툴이 만든다.
CODEX_MODEL = os.environ.get("CODEX_IMAGE_MODEL", "gpt-5.5")

JsonDict = dict


class CodexHTTPError(RuntimeError):
    """전송 계층 실패. `status` 에 HTTP 코드가 있으면 호출부가 갈라 쓴다."""

    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.status = status


class CodexAuthError(CodexHTTPError):
    """로그인이 없거나 만료. → `codex login`."""


# imgstudio 가 쓰던 이름 — 그대로 산다.
ImageEngineError = CodexHTTPError
NotAuthenticated = CodexAuthError


# ── 원자적 쓰기 ──────────────────────────────────────────────────────────────
def _atomic_write_json(path: str, data: Any, *, indent: Optional[int] = 2) -> None:
    """`imgstudio/core/atomic_io.py` 와 같은 것. `llm/` 이 imgstudio 를 import 하지
    않으려고 여기 둔다 — auth.json 을 쓰다 끊기면 로그인이 통째로 날아간다."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = f"{path}.tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=indent, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


# ── 토큰 로드/추출/갱신 ───────────────────────────────────────────────────────
def _load_auth() -> JsonDict:
    try:
        with open(AUTH_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        raise NotAuthenticated(
            "~/.codex/auth.json 이 없습니다. 터미널에서 `codex login` 으로 "
            "ChatGPT 계정에 로그인하세요."
        )
    except Exception as e:
        raise ImageEngineError(f"auth.json 읽기 실패: {e}")


def _extract_tokens(auth: JsonDict) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    tokens = auth.get("tokens") if isinstance(auth.get("tokens"), dict) else {}
    access = tokens.get("access_token") if isinstance(tokens.get("access_token"), str) else None
    account_id = tokens.get("account_id") if isinstance(tokens.get("account_id"), str) else None
    refresh = tokens.get("refresh_token") if isinstance(tokens.get("refresh_token"), str) else None
    return access, account_id, refresh


def _refresh_access_token(refresh_token: str, timeout: int = 30) -> JsonDict:
    data = urllib.parse.urlencode({
        "client_id": OAUTH_CLIENT_ID,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "scope": "openid profile email",
    }).encode("utf-8")
    req = urllib.request.Request(
        OAUTH_TOKEN_URL, data=data, method="POST",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": FALLBACK_UA,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        oauth_err = ""
        try:
            parsed = json.loads(body)
            if isinstance(parsed, dict) and isinstance(parsed.get("error"), str):
                oauth_err = parsed["error"]
        except Exception:
            pass
        if oauth_err == "invalid_grant":
            raise NotAuthenticated(
                "refresh_token 이 만료되었습니다 — `codex login` 으로 다시 로그인하세요.",
                status=e.code,
            )
        raise ImageEngineError(
            f"토큰 갱신 실패: HTTP {e.code}" + (f" ({oauth_err})" if oauth_err else ""),
            status=e.code,
        )


def _persist_refreshed_auth(original: JsonDict, refreshed: JsonDict) -> None:
    tokens = original.get("tokens")
    if not isinstance(tokens, dict):
        tokens = {}
        original["tokens"] = tokens
    for k in ("access_token", "refresh_token", "id_token"):
        if isinstance(refreshed.get(k), str):
            tokens[k] = refreshed[k]
    original["last_refresh"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    try:
        _atomic_write_json(str(AUTH_PATH), original, indent=2)
    except Exception:
        pass  # 갱신 저장이 실패해도 이번 요청은 새 토큰으로 진행


# ── 헤더/버전 ────────────────────────────────────────────────────────────────
def _parse_semver(v: str) -> Optional[Tuple[int, ...]]:
    return tuple(int(p) for p in v.split(".")) if re.fullmatch(r"\d+\.\d+\.\d+", v) else None


_version_cache: Optional[str] = None


def _probe_cli_version() -> Optional[str]:
    """`codex --version` 한 번. **shutil.which 로 먼저 푼다** — 윈도우에서 npm 전역
    명령은 `codex.cmd` 라 이름만으로는 subprocess 가 못 찾는다(PATHEXT 를 안 본다).
    `tools/doctor.py:_ver()` 와 같은 이유다."""
    exe = shutil.which("codex")
    if not exe:
        return None
    try:
        r = subprocess.run([exe, "--version"], capture_output=True, text=True,
                           timeout=20, encoding="utf-8", errors="replace")
    except Exception:
        return None
    out = (r.stdout or r.stderr or "").strip()
    m = re.search(r"\d+\.\d+\.\d+", out)
    return m.group(0) if m else None


def _detect_codex_version() -> str:
    """사칭 헤더에 실을 CLI 버전.

    ★ 예전에는 `~/.codex/version.json` 만 봤는데 **그 파일은 없을 수 있다**
      (자동 업데이트 확인을 한 번도 안 한 PC). 그러면 설치본이 0.153.x 인데도
      헤더에는 하한값 0.130.0 이 나갔다. 실제 CLI 를 먼저 물어보고, 안 되면
      예전 길(파일 → 하한값)로 떨어진다. 한 번 물어보고 캐시한다.
    """
    global _version_cache
    if _version_cache:
        return _version_cache

    floor = FALLBACK_VERSION
    pf = _parse_semver(floor)

    best = _probe_cli_version()
    if not best:
        try:
            if VERSION_PATH.exists():
                data = json.loads(VERSION_PATH.read_text(encoding="utf-8"))
                v = data.get("latest_version")
                if isinstance(v, str):
                    best = v
        except Exception:
            pass

    pv = _parse_semver(best) if best else None
    if pv and pf:
        _version_cache = best if pv >= pf else floor
    elif pv:
        _version_cache = best
    else:
        _version_cache = floor
    return _version_cache


def _build_headers(token: str, account_id: Optional[str], version: str) -> dict:
    sid = str(uuid.uuid4())
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
        "Accept": "text/event-stream",
        "Connection": "Keep-Alive",
        "version": version,
        "session_id": sid,
        "x-client-request-id": sid,
        "User-Agent": f"codex_cli_rs/{version} (Windows 11; x64) image-studio",
        "originator": "codex_cli_rs",
    }
    if account_id:
        headers["chatgpt-account-id"] = account_id
    return headers


# ── 참조 이미지 ───────────────────────────────────────────────────────────────
def _sniff_mime(data: bytes) -> Optional[str]:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:2] == b"\xff\xd8":
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _encode_ref(raw: bytes) -> Tuple[str, str]:
    mime = _sniff_mime(raw) or "image/png"
    return base64.b64encode(raw).decode("ascii"), mime


# ── SSE 스트림 파싱 ───────────────────────────────────────────────────────────
def _loosen_read_timeout(resp: Any, timeout: float) -> None:
    try:
        resp.fp.raw._sock.settimeout(timeout)  # type: ignore[attr-defined]
    except Exception:
        pass


def _stream(headers: dict, body: JsonDict, deadline: float,
            stall_timeout: float) -> Iterator[JsonDict]:
    req = urllib.request.Request(
        CODEX_BACKEND, data=json.dumps(body).encode("utf-8"),
        headers=headers, method="POST",
    )
    initial = max(1.0, min(30.0, deadline - time.monotonic()))
    resp = urllib.request.urlopen(req, timeout=initial)
    _loosen_read_timeout(resp, min(stall_timeout, max(1.0, deadline - time.monotonic())))
    try:
        data_buf: List[str] = []
        for raw in resp:
            if time.monotonic() >= deadline:
                raise ImageEngineError("스트림이 전체 시간 예산을 초과했습니다.")
            line = raw.decode("utf-8", errors="ignore").rstrip("\r\n")
            if line == "":
                if not data_buf:
                    continue
                payload = "\n".join(data_buf)
                data_buf = []
                if payload == "[DONE]":
                    return
                try:
                    yield json.loads(payload)
                except Exception:
                    pass
                continue
            if line.startswith(":") or line.startswith("event:"):
                continue
            if line.startswith("data:"):
                chunk = line[len("data:"):]
                if chunk.startswith(" "):
                    chunk = chunk[1:]
                data_buf.append(chunk)
    finally:
        resp.close()
