# -*- coding: utf-8 -*-
"""검수지를 장마다 HTML 파일로 떨군다 — SME 에게 그대로 보낼 것.

    .venv-app\\Scripts\\python tools\\dump_review.py          전체 HTML
    .venv-app\\Scripts\\python tools\\dump_review.py 3 7      3~7장만
    .venv-app\\Scripts\\python tools\\dump_review.py --pdf    PDF 도 함께(장당 10초쯤)

★ **왜 도구로 두는가.** 2026-09-20 에 같은 일을 세션의 임시 스크립트로 했다가
  레포에 안 남아, 다음 레포에서 웹 단추로 뽑으니 **한 장이 75MB 컬러**로
  나왔다(2026-09-22 실측). 이제 여기 있다 — 다시 잃지 않는다.
★ **그림을 글자로 바꿔 넣는다**(data URI). 주소로 두면 이 앱이 없는 데서
  열었을 때 빈 칸만 나온다 — 받는 쪽은 서버가 없다.
★ **작게·흑백으로** 넣는다(`render.review.small_img` — 서버의 PDF 창구와
  같은 함수다). 검수는 라벨 자리를 눈으로 가늠하는 일이라 화질이 필요 없다.
  실측: 원본 PNG 2.3MB → 640px 흑백 JPEG 25KB. 17장 합계 23MB.
★ **맨 앞에 표지 한 장**이 붙는다(`build`). 양면 상철로 뽑으면 한 씬의
  그림·대사가 펼친 면에 같이 온다 — 표지가 없으면 앞뒤로 갈린다.
★ **한 폴더에 모은다**(`_검수지/`). 장마다 `11_완성` 에 흩어 두면 SME 에게
  보낼 때 열여덟 폴더를 돌아야 한다.
★ **소리는 안 넣는다.** 저자에게 음성 파일을 따로 보내므로 검수지는 글만
  담는다. 소리를 실으면 한 장이 150MB 를 넘긴다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))
sys.stdout.reconfigure(encoding="utf-8")

import server                                    # noqa: E402
from core import workspace as ws                 # noqa: E402
from render.review import build, small_img, to_pdf   # noqa: E402

OUT = ws.ROOT / "_검수지"   # 한 폴더에 모은다 — 보낼 때 여기만 집으면 된다

PICS = True           # 그림을 넣을까 — 빼면 장당 150KB


def main() -> None:
    nums = [int(a) for a in sys.argv[1:] if a.isdigit()]
    lo, hi = (nums[0], nums[1]) if len(nums) >= 2 else (1, 999)
    pdf = "--pdf" in sys.argv
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
                cache[rel] = small_img(p) if p.is_file() else ""
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
        line = (f"  {d.name:<20} {out.name:<28} {mb:>6.1f}MB  "
                f"쪽 {html.count('class=\"sheet')}")
        if pdf:
            pp = to_pdf(html, out.with_suffix(".pdf"))
            pmb = pp.stat().st_size / 1e6
            tot_mb += pmb
            line += f"  · PDF {pmb:.1f}MB"
        print(line)
    print(f"\n  합계 {tot_mb:.0f}MB → {OUT}")


if __name__ == "__main__":
    main()
