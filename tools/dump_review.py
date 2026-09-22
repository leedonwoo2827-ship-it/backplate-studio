# -*- coding: utf-8 -*-
"""검수지를 장마다 HTML 파일로 떨군다 — SME 에게 그대로 보낼 것.

    .venv-app\\Scripts\\python tools\\dump_review.py          전체
    .venv-app\\Scripts\\python tools\\dump_review.py 3 7      3~7장만

★ **왜 도구로 두는가.** 2026-09-20 에 같은 일을 세션의 임시 스크립트로 했다가
  레포에 안 남아, 다음 레포에서 웹 단추로 뽑으니 **한 장이 75MB 컬러**로
  나왔다(2026-09-22 실측). 이제 여기 있다 — 다시 잃지 않는다.
★ **그림을 글자로 바꿔 넣는다**(data URI). 주소로 두면 이 앱이 없는 데서
  열었을 때 빈 칸만 나온다 — 받는 쪽은 서버가 없다.
★ **작게·흑백으로** 넣는다. 검수는 라벨 자리를 눈으로 가늠하는 일이라
  화질이 필요 없다. 실측: 원본 PNG 2.3MB → 640px 흑백 JPEG 25KB.
  18장 전체가 1.3GB 에서 11MB 가 된다 — 메일에 한꺼번에 붙는 크기다.
★ **한 폴더에 모은다**(`_검수지/`). 장마다 `11_완성` 에 흩어 두면 SME 에게
  보낼 때 열여덟 폴더를 돌아야 한다.
★ **소리는 안 넣는다.** 저자에게 음성 파일을 따로 보내므로 검수지는 글만
  담는다. 소리를 실으면 한 장이 150MB 를 넘긴다.
"""
from __future__ import annotations

import base64
import json
import subprocess
import sys
import tempfile
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))
sys.stdout.reconfigure(encoding="utf-8")

import server                                    # noqa: E402
from core import workspace as ws                 # noqa: E402
from render.review import build                  # noqa: E402

OUT = ws.ROOT / "_검수지"   # 한 폴더에 모은다 — 보낼 때 여기만 집으면 된다

PICS = True           # 그림을 넣을까 — 빼면 장당 150KB
WIDTH = 640           # 그림 가로 픽셀
QUALITY = 8           # ffmpeg -q:v (낮을수록 좋음)
GRAY = True           # 흑백으로 — 컬러 대비 3분의 1


def small(src: Path) -> str:
    """PNG → 줄인 JPEG → data URI. ffmpeg 로 한다(.venv-app 에 PIL 이 없다)."""
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
        out = Path(f.name)
    try:
        subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(src), "-vf",
             f"scale={WIDTH}:-1" + (",format=gray" if GRAY else ""),
             "-q:v", str(QUALITY), str(out), "-y"],
            check=True, capture_output=True)
        b64 = base64.b64encode(out.read_bytes()).decode("ascii")
        return "data:image/jpeg;base64," + b64
    finally:
        out.unlink(missing_ok=True)


def main() -> None:
    lo, hi = (int(sys.argv[1]), int(sys.argv[2])) if len(sys.argv) > 2 else (1, 999)
    OUT.mkdir(parents=True, exist_ok=True)
    tot_mb = 0.0
    for d in sorted(ws.ROOT.iterdir()):
        if not d.is_dir() or not (d / "project.json").is_file():
            continue
        pj = json.loads((d / "project.json").read_text(encoding="utf-8"))
        pid = int(pj.get("id") or 0)
        if pid < lo or pid > hi:
            continue
        deck = server.get_deck(pid)
        if not deck.get("ready"):
            print(f"  {d.name:<20} 덱 없음 — 건너뜀")
            continue

        cache: dict = {}

        def img(rel: str) -> str:
            if not PICS:
                return ""
            if rel not in cache:
                p = d / rel
                cache[rel] = small(p) if p.is_file() else ""
            return cache[rel]

        # 소리 없음 — `build` 는 audio.file 이 없을 때만 「음성 없음」을 쓰므로
        # 빈 주소를 줘도 태그가 남는다. 그래서 덱에서 소리를 아예 걷는다.
        for sl in deck.get("slides") or []:
            sl["audio"] = {}
        html = build(deck, img_url=img, audio_url=lambda no: "", pics=PICS)
        out = OUT / f"{d.name}-검수지.html"
        out.write_text(html, encoding="utf-8")
        mb = out.stat().st_size / 1e6
        tot_mb += mb
        print(f"  {d.name:<20} {out.name:<28} {mb:>6.1f}MB  "
              f"쪽 {html.count('class=\"sheet')}")
    print(f"\n  합계 {tot_mb:.0f}MB → {OUT}")


if __name__ == "__main__":
    main()
