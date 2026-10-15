# -*- coding: utf-8 -*-
"""S3d 라벨 자동 배치 — 구운 그림을 **보고** 라벨 자리를 잡는다.

    그림(09_이미지/NNN.png) + 원장의 라벨  →  Claude 비전  →  10_덱/labels.auto.json

★ **왜 있나.** 라벨의 처음 자리는 그림을 보지 않고 고정표(`s3a_imgprompt.PLACE_XY`)
  에서 나온다. 그림 모델은 비워 달라는 자리를 안 지키므로(그 실패 기록이
  `s3a_imgprompt` 머리말에 있다) 결국 사람이 「라벨 자리」 화면에서 장마다 옮겼다
  — 2과목 4~39장에 한 시간(2026-10-15). 그때 사람과 Claude 가 대화로 내린 판단
  (그림과 짝 맞추기 · 핵심을 가리지 않기 · 선이 지나가면 판 · 여백 · 줄바꿈)을
  `llm/prompts/label_fit.md` 에 규칙으로 옮겨 놓고 여기서 돌린다. 사람은 이제
  **심하게 어긋난 장만** 고친다. 그 장을 고르라고 `warn` 을 남긴다.

★ **손편집은 언제나 이긴다.** 결과는 `deck.overrides.json` 이 아니라 따로
  `labels.auto.json` 에 쓴다. 덱을 세울 때 원장 → 자동 → 손편집 순서로 덮는다
  (`merge_auto`). 그래서 이 단계를 몇 번 다시 돌려도 사람이 옮긴 자리는 안 움직인다.
  사람이 이미 손댄 장은 **돈을 안 쓰려고 건너뛴다**(`--force` 면 돌리되, 손편집에
  가려 화면에는 안 보인다 — 사람 결과와 견줘 보는 용도다).

★ **여러 장을 한 콜에 묶는다.** 비전 호출은 한 번에 최소 $0.24 다.

★ 앱의 `.venv-app` 에는 Pillow 가 없다(`s13b_order` 주석). 그림 줄이기와 격자
  긋기는 ffmpeg 가 한다.
"""
from __future__ import annotations

import hashlib
import json
import math
import shutil
import subprocess
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from core import config, workspace as ws
from llm.claude_provider import ClaudeProvider
from pipeline.registry import PROMPTS, STAGES, cached_data, write_cache
from pipeline.s3a_imgprompt import labels_of, slide_id

BATCH = 5                       # 한 콜에 보낼 장 수
SHEET_W, SHEET_H = 1280, 720    # 보낼 그림 크기 — 화면과 같은 16:9
EXAMPLES = PROMPTS / "label_fit_examples"   # 사람이 확정한 장(few-shot) — 없으면 안 싣는다

# ── 화면 글자 크기 — `static/css/app.css` `.lb-box` · `render/slides.py` `.lbl` 과 같은 값 ──
# 모두 화면 높이(H)의 % 다. 가로 % 로 바꿀 때는 9/16 을 곱한다.
HEAD_PX, HEAD_LH = 4.0, 1.25
SUB_PX, SUB_LH = 2.6, 1.42
SUB_GAP = 0.35                  # 설명 위 간격(em)
TITLE_PX = 5.4
H2W = 9 / 16
MIN_W, MAX_W = 8.0, 46.0        # `labels.js` 와 같은 범위


# ── 글자 폭 어림 ───────────────────────────────────────────────────────────
def _em(ch: str) -> float:
    """글자 하나의 폭(em). 한글·한자는 거의 정사각, 영문·숫자는 그 절반 남짓."""
    if ch == " ":
        return 0.28
    if unicodedata.east_asian_width(ch) in ("W", "F"):
        return 0.98
    if ch.isupper():
        return 0.66
    if ch.isalnum():
        return 0.56
    return 0.36


def text_w(text: str, px: float) -> float:
    """글 한 줄의 폭 — 화면 **가로 %**."""
    return sum(_em(c) for c in text) * px * H2W


def _lines(text: str, px: float, w: float) -> int:
    """폭 w 에서 몇 줄이 되나. 한국어는 단어째 넘어가므로 1.12 배 여유를 준다."""
    n = 0
    for part in (text or "").split("\n"):
        n += max(1, math.ceil(text_w(part, px) * 1.12 / max(w, 1)))
    return n if text else 0


def est_box(l: Dict[str, Any]) -> Dict[str, float]:
    """라벨 상자의 어림 크기(%) — 겹침·가장자리 점검에 쓴다."""
    w = float(l.get("w") or 23)
    hl = _lines(l.get("head") or "", HEAD_PX, w)
    sl = _lines(l.get("sub") or "", SUB_PX, w)
    h = hl * HEAD_PX * HEAD_LH + (SUB_GAP * SUB_PX + sl * SUB_PX * SUB_LH if sl else 0)
    return {"x": float(l.get("x") or 0), "y": float(l.get("y") or 0), "w": w, "h": h}


def title_box(title: str) -> Dict[str, float]:
    """화면이 얹는 슬라이드 제목의 자리 — `.lb-title` (3.2%, 2.1%, 5.4cqh)."""
    return {"x": 3.2, "y": 1.0, "w": text_w(title or "", TITLE_PX) + 1.0, "h": 8.5}


def _hit(a: Dict[str, float], b: Dict[str, float]) -> bool:
    return (a["x"] < b["x"] + b["w"] and b["x"] < a["x"] + a["w"]
            and a["y"] < b["y"] + b["h"] and b["y"] < a["y"] + a["h"])


# ── 그림 ───────────────────────────────────────────────────────────────────
def sheet(pid: int, slug: str, no: int, src: Path) -> Path:
    """그림을 1280×720 으로 줄이고 10% 빨간 격자를 긋는다(ffmpeg)."""
    ff = shutil.which("ffmpeg")
    if not ff:
        raise RuntimeError("ffmpeg 를 찾지 못했습니다")
    d = ws.cache_dir(pid, slug) / "_labelfit"
    d.mkdir(parents=True, exist_ok=True)
    out = d / f"{no:03d}.jpg"
    if out.is_file() and out.stat().st_mtime >= src.stat().st_mtime:
        return out
    vf = (f"scale={SHEET_W}:{SHEET_H},"
          f"drawgrid=w={SHEET_W // 10}:h={SHEET_H // 10}:t=2:c=red@0.55")
    r = subprocess.run([ff, "-v", "error", "-y", "-i", str(src), "-vf", vf,
                        "-frames:v", "1", "-q:v", "3", str(out)],
                       capture_output=True, text=True, timeout=60)
    if r.returncode != 0 or not out.is_file():
        raise RuntimeError(f"{no}장 그림을 못 줄였습니다: {(r.stderr or '')[:160]}")
    return out


# ── 응답 꼴 ────────────────────────────────────────────────────────────────
SCHEMA = {
    "type": "object",
    "properties": {
        "slides": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "no": {"type": "integer"},
                    "warn": {"type": "array", "items": {"type": "string"}},
                    "labels": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "i": {"type": "integer"},
                                "x": {"type": "number"},
                                "y": {"type": "number"},
                                "w": {"type": "number"},
                                "cell": {"type": "string", "enum": ["line", "box"]},
                                "pair": {"type": "string"},
                                "sub": {"type": "string"},
                            },
                            "required": ["i", "x", "y", "w", "cell", "pair", "sub"],
                        },
                    },
                },
                "required": ["no", "warn", "labels"],
            },
        },
    },
    "required": ["slides"],
}


def _bare(s: str) -> str:
    return "".join((s or "").split())


def _brief(no: int, title: str, labs: List[Dict[str, Any]]) -> str:
    t = title_box(title)
    rows = [f"── 슬라이드 {no} · 제목 「{title}」",
            f"제목 자리(피할 것): x {t['x']:.1f}~{t['x'] + t['w']:.1f}, y 1~9",
            f"줄 높이: 제목 {HEAD_PX * HEAD_LH:.1f} · 설명 {SUB_PX * SUB_LH:.1f} "
            f"(설명 위 간격 {SUB_GAP * SUB_PX:.1f})",
            f"라벨 {len(labs)}개:"]
    for i, l in enumerate(labs, 1):
        rows.append(f'{i}. 제목 "{l.get("head") or ""}" '
                    f'(한 줄 최소 폭 {text_w(l.get("head") or "", HEAD_PX) + 0.5:.1f})'
                    f' / 설명 "{l.get("sub") or ""}" '
                    f'(글자 폭 합 {text_w(l.get("sub") or "", SUB_PX):.1f})')
    return "\n".join(rows)


def _examples() -> List[Dict[str, Any]]:
    """사람이 확정한 장 — `tools/export_label_examples.py` 가 뽑아 둔 것."""
    if not EXAMPLES.is_dir():
        return []
    parts: List[Dict[str, Any]] = []
    for js in sorted(EXAMPLES.glob("*.json"))[:2]:
        ex = json.loads(js.read_text(encoding="utf-8"))
        img = EXAMPLES / ex.get("image", "")
        if not img.is_file():
            continue
        parts.append({"text": ("── 예시: 사람이 확정한 자리 (답이 아니라 참고) ──\n"
                               + json.dumps(ex.get("labels") or [], ensure_ascii=False)),
                      "image": img})
    return parts


def _sig(labs: List[Dict[str, Any]], img: Path) -> str:
    raw = json.dumps([[l.get("head"), l.get("sub")] for l in labs], ensure_ascii=False)
    raw += f"|{img.name}|{int(img.stat().st_mtime)}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


# ── 덱에 얹기 ──────────────────────────────────────────────────────────────
def merge_auto(s: Dict[str, Any], key: str, auto: Dict[str, Any]) -> None:
    """원장 라벨 위에 자동 자리를 얹는다. **손편집보다 먼저** 부른다.

    ★ 원장이 그 뒤로 바뀌었으면(라벨 제목이 달라졌으면) 얹지 않는다 — 낡은 자리를
      새 글에 씌우면 짝이 통째로 어긋난다.
    """
    a = auto.get(key) or {}
    cur = s.get("labels") or []
    got = a.get("labels") or []
    if not got or [l.get("head") for l in got] != [l.get("head") for l in cur]:
        return
    s["labels"] = [dict(l) for l in got]
    s["labels_auto"] = True
    s["labels_warn"] = list(a.get("warn") or [])


# ── 실행 ───────────────────────────────────────────────────────────────────
def run(job, pid: int, slug: str, project: Dict[str, Any], *, force: bool = False,
        only: Optional[List[int]] = None):
    stage = STAGES["s3d-label-fit"]
    cfg = config.load()

    outline = cached_data(pid, slug, "s2b-outline") or {}
    imgs = (cached_data(pid, slug, "s3b-images") or {}).get("images") or {}
    led = (ws.load_ledger(pid, slug) or {}).get("by_id", {})
    ov = ws.load_overrides(pid, slug).get("slides", {}) or {}
    auto = ws.load_labels_auto(pid, slug)
    root = ws.step_dir(pid, slug, "images").parent

    todo: List[Dict[str, Any]] = []
    skipped_hand = skipped_same = 0
    for sl in outline.get("slides") or []:
        no = int(sl["no"])
        key = str(no)
        if only and no not in only:
            continue
        labs = labels_of(led.get(sl.get("data_id") or slide_id(slug, sl)) or {})
        got = imgs.get(key) or {}
        if not labs or not got.get("file"):
            continue
        img = root / got["file"]
        if not img.is_file():
            continue
        if (ov.get(key) or {}).get("labels") and not (force or only):
            skipped_hand += 1
            continue
        sig = _sig(labs, img)
        if (auto.get(key) or {}).get("sig") == sig and not (force or only):
            skipped_same += 1
            continue
        todo.append({"no": no, "key": key, "title": sl.get("title") or "",
                     "labs": labs, "img": img, "sig": sig})

    job.add_log(f"자동 배치할 장 {len(todo)}개 · 손편집이라 건너뜀 {skipped_hand}개 · "
                f"그대로라 건너뜀 {skipped_same}개")

    system = (PROMPTS / "label_fit.md").read_text(encoding="utf-8")
    examples = _examples()
    warn: List[str] = []
    cost = 0.0
    done = 0
    batches = [todo[i:i + BATCH] for i in range(0, len(todo), BATCH)]
    p = None
    if batches:
        models = project.get("models") or {}
        p = ClaudeProvider(
            model=models.get("labelfit") or cfg["models"].get("labelfit")
            or cfg["models"]["imgprompt"],
            effort=cfg["effort"].get("labelfit") or "medium",
            budget_usd=cfg["budget_usd"]["per_stage"],
            on_activity=job.add_log,
        )
    for bi, batch in enumerate(batches):
        if getattr(job, "canceled", False):
            raise RuntimeError("사람이 멈췄습니다")
        job.progress(bi, len(batches), f"{batch[0]['no']}~{batch[-1]['no']}장")
        parts = list(examples)
        try:
            for t in batch:
                parts.append({"text": _brief(t["no"], t["title"], t["labs"]),
                              "image": sheet(pid, slug, t["no"], t["img"])})
            raw = p.vision(system, parts, schema=SCHEMA,
                           intro=f"슬라이드 {len(batch)}장의 라벨 자리를 잡아라. "
                                 "그림에는 10% 간격 빨간 격자가 있다.")
        except Exception as e:                         # noqa: BLE001
            warn.append(f"{batch[0]['no']}~{batch[-1]['no']}장 묶음 실패: "
                        f"{type(e).__name__}: {e}")
            job.add_log(warn[-1])
            continue
        cost += p.last_cost_usd
        by_no = {int(r.get("no") or 0): r for r in raw.get("slides") or []}
        for t in batch:
            r = by_no.get(t["no"])
            if not r:
                warn.append(f"{t['no']}장: 답이 없습니다")
                continue
            res = _settle(t, r)
            if res is None:
                warn.append(f"{t['no']}장: 라벨 수가 맞지 않아 버렸습니다")
                continue
            auto[t["key"]] = res
            done += 1
            if res["warn"]:
                job.add_log(f"{t['no']}장 확인 필요: " + " / ".join(res["warn"]))
        # 묶음마다 저장 — 중간에 끊겨도 받은 만큼은 남는다
        ws.save_labels_auto(pid, slug, auto)

    job.progress(len(batches), len(batches), "정리")
    if done:
        # 덱 조립(s8)이 이 값을 읽는다 — 자동 자리가 바뀌면 덱을 다시 세워야 한다
        project["labels_auto_rev"] = int(project.get("labels_auto_rev") or 0) + 1
        ws.save_project(pid, slug, project)

    flagged = sorted((int(k) for k, v in auto.items() if v.get("warn")))
    job.add_log(f"자동 배치 {done}장 · 확인 필요 {len(flagged)}장 · ${cost:.3f}")
    if flagged:
        job.add_log("확인 필요한 장: " + ", ".join(map(str, flagged[:40])))

    return write_cache(pid, slug, "s3d-label-fit",
                       input_hash=stage.input_hash(pid, slug, project),
                       data={"placed": sorted(int(k) for k in auto),
                             "flagged": flagged, "done": done,
                             "skipped_hand": skipped_hand},
                       code_version=stage.code_version, model=p.model if p else "",
                       cost_usd=cost, status="degraded" if warn else "ok",
                       warnings=warn[:10])


def _settle(t: Dict[str, Any], r: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """비전이 준 자리를 화면 규칙에 맞춰 자르고, 겹침을 어림으로 다시 본다."""
    labs = t["labs"]
    got = {int(x.get("i") or 0): x for x in r.get("labels") or []}
    if sorted(got) != list(range(1, len(labs) + 1)):
        return None
    out: List[Dict[str, Any]] = []
    pairs: List[str] = []
    for i, base in enumerate(labs, 1):
        g = got[i]
        w = min(MAX_W, max(MIN_W, float(g.get("w") or base.get("w") or 23)))
        x = min(100 - w, max(0.0, float(g.get("x") or 0)))
        y = min(96.0, max(0.0, float(g.get("y") or 0)))
        lab = {**base, "x": round(x, 1), "y": round(y, 1), "w": round(w, 1),
               "cell": "box" if g.get("cell") == "box" else "line"}
        # ★ 줄바꿈만 받는다. 글자가 하나라도 다르면 원문을 둔다 — 글은 사람이 쓴 것이다.
        sub = (g.get("sub") or "").strip()
        if sub and sub != base.get("sub") and _bare(sub) == _bare(base.get("sub") or ""):
            lab["sub"] = sub
        out.append(lab)
        pairs.append((g.get("pair") or "").strip())

    warn = [w.strip() for w in (r.get("warn") or []) if (w or "").strip()]
    # 어림으로 다시 본다 — 비전이 높이를 짧게 잡는 일이 있다
    boxes = [est_box(l) for l in out]
    tb = title_box(t["title"])
    for i, a in enumerate(boxes):
        if a["y"] + a["h"] > 99:
            warn.append(f"「{out[i]['head']}」 아래가 화면 밖으로 나갈 수 있음")
        if _hit(a, tb):
            warn.append(f"「{out[i]['head']}」 이 제목과 겹칠 수 있음")
        for j in range(i + 1, len(boxes)):
            if _hit(a, boxes[j]):
                warn.append(f"「{out[i]['head']}」·「{out[j]['head']}」 이 겹칠 수 있음")
    return {"labels": out, "warn": warn, "pairs": pairs, "sig": t["sig"],
            "at": datetime.now().isoformat(timespec="seconds")}


STAGES["s3d-label-fit"].run = run
