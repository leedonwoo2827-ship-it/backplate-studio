#!/usr/bin/env bash
# Developer Present Agent - start the local console (macOS / Linux)
set -u
cd "$(dirname "$0")"

if [ ! -x ".venv-app/bin/python" ]; then
  echo "[ERROR] Not set up yet. Run ./setup.sh first."
  exit 1
fi

# 포트의 단일 출처는 showcase.config.json 이다. 아래 숫자는 파이썬이 답하지
# 못할 때의 폴백일 뿐이다. 5278 인 이유 — 이 앱의 이전 세대(260918)가 5178 을
# 쓰고 있어서 둘이 나란히 떠 있을 수 있어야 한다.
PORT="$(.venv-app/bin/python -c "import core.config as c;print(c.load()['port'])" 2>/dev/null || echo 5278)"
[ -n "${SHOWCASE_PORT:-}" ] && PORT="$SHOWCASE_PORT"
export SHOWCASE_OPEN_BROWSER=1
export PYTHONIOENCODING=utf-8
export PYTHONUNBUFFERED=1

echo "Developer Present Agent  >  http://localhost:${PORT}"
echo "Press Ctrl+C to stop."
echo
exec .venv-app/bin/python -m uvicorn server:app --host 127.0.0.1 --port "${PORT}"
