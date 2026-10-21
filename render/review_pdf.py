# -*- coding: utf-8 -*-
"""검수지 PDF — 크롬 헤드리스로 찍고, **양면 짝을 실제 장수로 맞춘다.**

★ HTML 은 장수를 어림으로 나눈다(`review._paginate`). 어림이 한 줄 빗나가면
  씬이 석 장이 되고 다음 씬이 홀수 쪽으로 밀린다 — 양면 인쇄에서 그림과 대사가
  다른 펼침에 갈린다. 그래서 **두 번 찍는다.** 첫 판의 쪽마다 숨은 표식
  (`@@S{씬}@@`, 흰 글자)을 읽어 씬별 장수를 세고, 홀수인 씬에 빈 면을 끼워
  다시 찍는다. 둘째 판은 반드시 짝수다.
★ 크롬은 있는 것을 쓴다 — 시스템 크롬이 없으면 Playwright 가 받아 둔
  chromium(영상 렌더가 이미 쓰는 것). 둘 다 없으면 `None` 을 돌려 주고 화면이
  「브라우저에서 Ctrl+P」로 안내한다.
★ 그림은 **1600px 컬러 JPEG 로 줄여** `file://` 로 문다. 원본 PNG 를 그대로 물면
  32씬에 62MB, 줄이면 7MB 다(실측 7장). 인쇄용이라 HTML(640px 흑백)보다는 크다.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict

from render.review import build

_MARK = re.compile(r"@@S(\d+)@@")


def find_chrome() -> str | None:
    """크롬 실행 파일 — 환경변수 → 시스템 → Playwright 순."""
    env = os.environ.get("CHROME") or os.environ.get("CHROME_PATH")
    if env and Path(env).is_file():
        return env
    cands = []
    if sys.platform == "win32":
        for base in (os.environ.get("PROGRAMFILES", r"C:\Program Files"),
                     os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
                     os.environ.get("LOCALAPPDATA", "")):
            if base:
                cands.append(Path(base) / "Google/Chrome/Application/chrome.exe")
                cands.append(Path(base) / "Microsoft/Edge/Application/msedge.exe")
    elif sys.platform == "darwin":
        cands.append(Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"))
    for name in ("google-chrome", "google-chrome-stable", "chromium",
                 "chromium-browser", "chrome", "msedge"):
        w = shutil.which(name)
        if w:
            return w
    for c in cands:
        if c.is_file():
            return str(c)
    # Playwright 의 chromium — 영상 렌더(HyperFrames)가 쓰는 것과 같은 것
    try:
        root = Path(__file__).resolve().parent.parent
        out = subprocess.run(
            ["node", "-e",
             "console.log(require('playwright').chromium.executablePath())"],
            cwd=str(root), capture_output=True, text=True, timeout=20,
            encoding="utf-8", errors="replace")
        p = (out.stdout or "").strip()
        if p and Path(p).is_file():
            return p
    except Exception:                                          # noqa: BLE001
        pass
    return None


def _print(chrome: str, html: Path, pdf: Path) -> None:
    cmd = [chrome, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
           "--no-first-run", "--no-default-browser-check",
           f"--print-to-pdf={pdf}", html.resolve().as_uri()]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300,
                       encoding="utf-8", errors="replace")
    if not pdf.is_file():
        raise RuntimeError(f"크롬이 PDF 를 못 만들었습니다: {(r.stderr or '')[-400:]}")


def pages_by_scene(pdf: Path) -> Dict[int, int]:
    """쪽마다 숨은 표식을 읽어 씬별 장수를 센다. 표지는 0."""
    from pypdf import PdfReader

    n: Dict[int, int] = {}
    for pg in PdfReader(str(pdf)).pages:
        m = _MARK.search(pg.extract_text() or "")
        if m:
            k = int(m.group(1))
            n[k] = n.get(k, 0) + 1
    return n


def _jpeg(src: Path, out: Path, width: int) -> Path | None:
    """PNG → 줄인 JPEG. ffmpeg 로 한다(.venv-app 에 PIL 이 없다). 실패하면 None."""
    r = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(src), "-vf", f"scale={width}:-1",
         "-q:v", "8", str(out), "-y"], capture_output=True)
    return out if r.returncode == 0 and out.is_file() else None


def make_pdf(deck: Dict[str, Any], *, img_path: Callable[[str], Path | None],
             out: Path, chrome: str | None = None,
             build_kw: Dict[str, Any] | None = None,
             img_px: int | None = 1600) -> Path | None:
    """덱 → PDF. 크롬이 없으면 None.

    `img_path(rel)` 는 그림 파일의 절대경로(없으면 None). `build_kw` 는
    `review.build` 에 그대로 넘긴다(`pics=False` 등). `img_px` 가 있으면 그림을
    그 너비의 JPEG 로 줄여 문다(None 이면 원본 그대로 — 크다).
    """
    chrome = chrome or find_chrome()
    if not chrome:
        return None
    kw = dict(build_kw or {})
    kw.setdefault("cover", True)      # 표지·양면 짝은 PDF 에서만
    shrunk: Dict[str, Path | None] = {}

    def img_url(rel: str) -> str:
        p = img_path(rel)
        if not (p and p.is_file()):
            return ""
        if img_px:
            if rel not in shrunk:
                shrunk[rel] = _jpeg(p, Path(td) / f"{len(shrunk)}.jpg", img_px)
            p = shrunk[rel] or p
        return p.resolve().as_uri()

    def render(pad: Dict[int, int]) -> str:
        return build(deck, img_url=img_url, audio_url=lambda no: "",
                     pad=pad, **kw)

    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="review-pdf-") as td:
        html = Path(td) / "review.html"
        html.write_text(render({}), encoding="utf-8")
        _print(chrome, html, out)

        # ★ 둘째 패스 — 홀수 장인 씬에만 한 장씩 더 끼운다. 어림이 맞았으면
        #   `pad` 가 비어 그대로 끝난다.
        pad = {k: 1 for k, v in pages_by_scene(out).items() if k and v % 2}
        if pad:
            html.write_text(render(pad), encoding="utf-8")
            _print(chrome, html, out)
            bad = {k: v for k, v in pages_by_scene(out).items() if k and v % 2}
            if bad:   # 두 번 해도 안 맞으면 알려만 준다 — 그림이 없는 씬 등
                print(f"[review_pdf] 홀수 장 남음: {bad}", file=sys.stderr)
    return out
