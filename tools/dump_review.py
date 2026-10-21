# -*- coding: utf-8 -*-
"""검수지를 장마다 파일로 떨군다 — SME 에게 그대로 보낼 것.

    .venv-app\\Scripts\\python tools\\dump_review.py              1~18장 HTML
    .venv-app\\Scripts\\python tools\\dump_review.py 7 9          7~9장만
    .venv-app\\Scripts\\python tools\\dump_review.py --pdf        PDF 도 함께(장당 40초쯤)

★ **한 폴더에 모은다**(`<작업 루트>/_검수지/`). 장마다 `11_완성` 에 흩어 두면
  SME 에게 보낼 때 열여덟 폴더를 돌아야 한다.
★ **HTML 은 그림을 글자로 바꿔 넣는다**(data URI) — 받는 쪽은 서버가 없다.
  작게·흑백으로 넣는다: 검수는 라벨 자리를 가늠하는 일이라 화질이 필요 없다.
  실측: 1920px 컬러 180KB → 640px 흑백 19KB, 18장이 156MB → 15MB.
★ **PDF 는 1600px 컬러 JPEG 로 줄여 문다**(render/review_pdf.py 가 한다) — 인쇄해서
  보는 것이라 HTML 보다 크게, 그러나 원본 PNG 는 아니다. 실측: PNG 그대로면 32씬에
  62MB, 줄이면 7MB. 양면 짝은 크롬으로 두 번 찍어 맞춘다.
★ **소리는 안 넣는다.** 저자에게 음성 파일을 따로 보낸다.
★ `--pdf` 면 표지만 모은 `_표지모음_<처음>-<끝>장.pdf` 도 만든다 — 인쇄해 놓고
  어느 장까지 봤는지 한눈에 표시하는 용도.
"""
from __future__ import annotations

import base64
import io
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import server                                    # noqa: E402
from core import workspace as ws                 # noqa: E402
from render.review import build                  # noqa: E402

OUT = ws.ROOT / "_검수지"

WIDTH = 640           # HTML 그림 가로 픽셀
QUALITY = 8           # ffmpeg -q:v (낮을수록 좋음)
GRAY = True           # 흑백 — 컬러 대비 3분의 1


def small(src: Path) -> str:
    """HTML 용 — 작은 흑백 JPEG 를 data URI 로. ffmpeg 로 한다(.venv-app 에 PIL 이 없다)."""
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
        out = Path(f.name)
    try:
        subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(src), "-vf",
             f"scale={WIDTH}:-1" + (",format=gray" if GRAY else ""),
             "-q:v", str(QUALITY), str(out), "-y"],
            check=True, capture_output=True)
        return "data:image/jpeg;base64," + base64.b64encode(out.read_bytes()).decode()
    finally:
        out.unlink(missing_ok=True)


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    want_pdf = "--pdf" in sys.argv
    lo, hi = (int(args[0]), int(args[1])) if len(args) > 1 else (1, 999)
    OUT.mkdir(parents=True, exist_ok=True)

    chrome = None
    if want_pdf:
        from render.review_pdf import find_chrome
        chrome = find_chrome()
        if not chrome:
            print("크롬을 못 찾았습니다 — PDF 는 건너뜁니다. 구글 크롬을 깔거나 CHROME=경로")
            want_pdf = False

    covers, tot_mb = [], 0.0
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
        for sl in deck.get("slides") or []:     # 소리 없음
            sl["audio"] = {}

        cache: dict = {}

        def img(rel: str) -> str:
            if rel not in cache:
                p = d / rel
                cache[rel] = small(p) if p.is_file() else ""
            return cache[rel]

        html = build(deck, img_url=img, audio_url=lambda no: "")
        out = OUT / f"{d.name}-검수지.html"
        out.write_text(html, encoding="utf-8")
        mb = out.stat().st_size / 1e6
        tot_mb += mb
        line = f"  {d.name:<20} {out.name:<26} {mb:>5.1f}MB"

        if want_pdf:
            from render.review_pdf import make_pdf, pages_by_scene
            pdf = OUT / f"{d.name}-검수지.pdf"
            make_pdf(deck, img_path=lambda rel, d=d: d / rel, out=pdf, chrome=chrome)
            n = pages_by_scene(pdf)
            odd = [k for k, v in n.items() if k and v % 2]
            line += (f"   {pdf.name:<26} {pdf.stat().st_size / 1e6:>5.1f}MB "
                     f"{sum(n.values())}쪽" + (f" 홀수씬 {odd}" if odd else ""))
            covers.append((pid, pdf))
        print(line, flush=True)

    if covers:
        from pypdf import PdfReader, PdfWriter
        w = PdfWriter()
        for _, p in sorted(covers):
            w.add_page(PdfReader(str(p)).pages[0])
        name = OUT / f"_표지모음_{covers[0][0]}-{covers[-1][0]}장.pdf"
        with open(name, "wb") as f:
            w.write(f)
        print(f"\n  {name.name} — {len(covers)}장")
    print(f"  HTML 합계 {tot_mb:.0f}MB")


if __name__ == "__main__":
    main()
