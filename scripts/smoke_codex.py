"""스모크 — `codex login` 하나로 (1) 텍스트 (2) 증분 스트림 (3) 구조화 출력
(4) 비전+구조화가 되는가.

이 레포에서 **가장 위험한 미지수**를 여기서 먼저 끝낸다. 그림은 이미 같은 길로
수백 장을 구웠으니 전송 자체는 검증돼 있다. 확인 안 된 것은 하나다 —
`chatgpt.com/backend-api/codex/responses` 가 **`text.format` 의 json_schema 를
받아 주는가.** 비공식 엔드포인트라 문서가 없다.

받아 주면 ③④가 `json_schema` 로 통과한다. 거부하면 프로바이더가 스키마를 지시문에
적는 길로 자동으로 떨어지고 `prompt` 로 통과한다. **어느 쪽인지 반드시 눈으로
본다** — 폴백으로 도는 중이면 JSON 이 깨질 확률이 올라가므로 17장을 돌리기 전에
알고 있어야 한다.

③④는 **실제 파이프라인 스키마**를 쓴다. 장난감 스키마로는 `_strictify()` 가
진짜 스키마(중첩 배열·enum·선택 칸)를 감당하는지 알 수 없다.

사용:
    .venv-app\\Scripts\\python scripts\\smoke_codex.py
    .venv-app\\Scripts\\python scripts\\smoke_codex.py --only structured
    .venv-app\\Scripts\\python scripts\\smoke_codex.py --image 09_이미지\\003.webp
"""
from __future__ import annotations

import argparse
import struct
import sys
import time
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 한국어 콘솔(CP949)에서 죽지 않게 — doctor.py 와 같은 이유
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

from llm.codex_provider import CodexProvider  # noqa: E402

_results: list[tuple[bool, str, str]] = []


def report(ok: bool, name: str, note: str = "") -> None:
    _results.append((ok, name, note))
    print(f"  {'✓' if ok else '✗'} {name}" + (f"  — {note}" if note else ""))


# ── 시험용 이미지 ───────────────────────────────────────────────────────────
def _solid_png(w: int = 96, h: int = 96, rgb: tuple = (246, 241, 232)) -> bytes:
    """진짜 슬라이드가 없는 PC 에서도 비전 경로를 시험할 수 있게 PNG 하나를 짓는다.

    Pillow 는 엔진 venv 에만 있다 — 여기서는 zlib+struct 로 직접 만든다.
    """
    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return (struct.pack(">I", len(data)) + body
                + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw))
            + chunk(b"IEND", b""))


def find_image(explicit: str | None) -> tuple[Path, bool]:
    """(경로, 진짜 슬라이드인가). 산출물 폴더에 구운 그림이 있으면 그것을 쓴다."""
    if explicit:
        p = Path(explicit)
        if not p.is_file():
            raise SystemExit(f"이미지를 찾지 못했습니다: {p}")
        return p, True
    for parent in sorted(ROOT.parent.glob("showcase-out-*"), reverse=True):
        for pat in ("*/09_*/*.webp", "*/09_*/*.png", "*/01_*/vision/*.webp"):
            if hits := sorted(parent.glob(pat)):
                return hits[0], True
    tmp = ROOT / "_tmp" / "smoke.png"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_bytes(_solid_png())
    return tmp, False


# ── ① 텍스트 ───────────────────────────────────────────────────────────────
def t_text() -> None:
    p = CodexProvider(effort="none")
    t0 = time.monotonic()
    try:
        out = p.generate("You are a connection tester.",
                         [{"role": "user", "content": "Respond with exactly: OK"}])
    except Exception as e:  # noqa: BLE001
        report(False, "텍스트", f"{type(e).__name__}: {str(e)[:140]}")
        return
    report(bool(out.strip()), "텍스트",
           f"{time.monotonic() - t0:.1f}s · {p.last_usage.get('total', 0)} tok "
           f"· {out.strip()[:30]!r}")


# ── ② 증분 스트림 ──────────────────────────────────────────────────────────
def t_stream() -> None:
    p = CodexProvider(effort="none")
    t0 = time.monotonic()
    n, first = 0, 0.0
    try:
        for chunk in p.stream("너는 한국어로 답한다.",
                              [{"role": "user",
                                "content": "1부터 10까지 쉼표로 나열하라."}]):
            n += 1
            if n == 1:
                first = time.monotonic() - t0
    except Exception as e:  # noqa: BLE001
        report(False, "증분 스트림", f"{type(e).__name__}: {str(e)[:140]}")
        return
    # 델타가 1개면 폴백(전문 한 덩어리)으로 온 것이다 — 돌긴 돌지만 진행 표시가 죽는다.
    report(n >= 2, "증분 스트림",
           f"조각 {n}개 · 첫 조각 {first:.1f}s"
           + ("" if n >= 2 else "  ← 델타가 안 온다. 전문 폴백으로 돌고 있다"))


# ── ③ 구조화 (실제 s6-script 스키마) ────────────────────────────────────────
def t_structured() -> None:
    from pipeline.s6_script import SCHEMA

    p = CodexProvider(effort="low")
    brief = ("아래 한 장에 대한 내레이션을 써라.\n"
             "no=1 · 제목「배경판이란 무엇인가」 · 12초 분량.\n"
             "글자를 그림에 굽지 않고 화면이 텍스트를 얹는 방식이라는 점을 말한다.")
    t0 = time.monotonic()
    try:
        raw = p.structured("너는 강의 영상 대본 작가다. 한국어로 쓴다.",
                           [{"role": "user", "content": brief}], schema=SCHEMA)
    except Exception as e:  # noqa: BLE001
        report(False, "구조화(s6-script)", f"{type(e).__name__}: {str(e)[:140]}")
        return
    slides = raw.get("slides") or []
    ok = bool(slides) and bool((slides[0] or {}).get("srt_text"))
    report(ok, "구조화(s6-script)",
           f"[{p.last_schema_mode}] {time.monotonic() - t0:.1f}s · 장 {len(slides)}개"
           + (f" · {str((slides[0] or {}).get('srt_text'))[:40]!r}" if slides else ""))


# ── ④ 비전 + 구조화 (실제 s13c 스키마) ──────────────────────────────────────
def t_vision(image: str | None) -> None:
    from pipeline.s13c_zones import SCHEMA, SYSTEM

    img, real = find_image(image)
    p = CodexProvider(effort="low")
    intro = ("슬라이드 한 장이다. 적혀 있어야 할 라벨은 1번「배경판」 하나다.\n"
             "그림에서 그 글자를 찾아 상태와 위치를 적어라.")
    t0 = time.monotonic()
    try:
        raw = p.vision(SYSTEM, [{"text": "슬라이드 1번", "image": img}],
                       schema=SCHEMA, intro=intro)
    except Exception as e:  # noqa: BLE001
        report(False, "비전+구조화(s13c)", f"{type(e).__name__}: {str(e)[:140]}")
        return
    labels = raw.get("labels") or []
    # ★ 통과 기준은 **스키마대로 왔는가**다. 빈 판을 줬으면 verdict=missing 이
    #   정답이므로 내용의 옳고 그름으로는 판정하지 않는다.
    ok = bool(labels) and "verdict" in (labels[0] or {})
    report(ok, "비전+구조화(s13c)",
           f"[{p.last_schema_mode}] {time.monotonic() - t0:.1f}s · 라벨 {len(labels)}개 "
           f"· {img.name}{'' if real else ' (합성 이미지)'}"
           + (f" · verdict={labels[0].get('verdict')}" if labels else ""))


TESTS = {"text": t_text, "stream": t_stream, "structured": t_structured}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=list(TESTS) + ["vision"])
    ap.add_argument("--image", help="비전 시험에 쓸 이미지 (기본: 산출물에서 자동 탐색)")
    a = ap.parse_args()

    print("\n  Codex 스모크 — codex login 하나로 파이프라인이 도는가\n")
    for name, fn in TESTS.items():
        if a.only in (None, name):
            fn()
    if a.only in (None, "vision"):
        t_vision(a.image)

    bad = [n for ok, n, _ in _results if not ok]
    print()
    if bad:
        print(f"  {len(bad)}개 실패: {', '.join(bad)}")
        print("  → 401/token_revoked 면 `codex login`. 429 면 할당량입니다.")
    else:
        print("  전부 통과.")
    modes = {n: note for ok, n, note in _results if note.startswith("[")}
    if modes:
        print("  구조화 경로: "
              + " · ".join(f"{n}={note.split(']')[0][1:]}" for n, note in modes.items()))
        print("  (prompt 로 나오면 백엔드가 json_schema 를 거부한 것 —"
              " 돌긴 돌지만 JSON 이 깨질 확률이 올라갑니다)")
    print()
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
