# -*- coding: utf-8 -*-
"""영상 보며 검수 — 완성 영상의 **몇 초가 몇 장 몇 번째 문장인가.**

★ **왜 있나.** 59분짜리 영상을 처음부터 끝까지 들으며 발음을 고치면 검수가 끝나지
  않는다. 듣다가 이상한 곳에서 M 만 누르고, 나중에 그 장만 열어 고친다 — 해설북
  스튜디오(`261103-new-etest-ebook` 「영상 보며 검수」)에서 먼저 해 본 방식이다.

★ **시간의 출처는 그 영상을 구운 컴포지션이다**(`11_완성/_hyper/index.html` 의
  `<section id="scNNN" data-start data-duration>`). 덱을 다시 조립하거나 음성을 다시
  합성하면 길이가 바뀌므로, 지금 캐시로 계산하면 이미 구운 영상과 어긋난다.
  장 안의 문장은 `render.slides.cue_map` 과 같은 규칙(= 08_자막 SRT)으로 나눈다.

★ **검수는 다른 PC 에서도 한다**(2026-11-14 — 회사에서 굽고 집 노트북에서 듣는다).
  그래서 영상 옆에 서버 없이 열리는 `<영상>-영상검수.html` 을 같이 낸다.

★ **오가는 길은 구글 드라이브 폴더 하나다** — `<드라이브>/영상검수/<프로젝트 폴더>/`.
  회사 PC 가 영상(mp4)과 검수 html 을 거기 복사하고(`to_drive`), 집 노트북은
  드라이브 데스크톱으로 그 html 을 열어 듣고 「검수표 저장」으로 **같은 폴더에**
  `…-검수표.json` 을 둔다. 회사 PC 의 검수 패널이 그 폴더를 보고 새 검수표를
  알려 준다(`drive_inbox`). 파일을 손으로 옮길 일이 없다.

검수표 = `10_덱/review_marks.json` — `{"marks": [{no, i, t, text, memo}]}`
    no   덱 화면의 장 번호(구조 번호 · 손편집 키와 같다)
    i    그 장의 몇 번째 자막 문장(0부터)
    t    영상 시각(초)
"""
from __future__ import annotations

import html
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import os
import shutil

from core import config, workspace as ws

F_MARKS = "review_marks.json"
_SEC = re.compile(r'<section id="sc(\d+)"[^>]*?data-start="([\d.]+)"[^>]*?'
                  r'data-duration="([\d.]+)"')


def video_path(pid: int, slug: str) -> Path:
    return ws.step_dir(pid, slug, "dist") / f"{ws.ascii_slug(slug)}-motion.mp4"


def cues(pid: int, slug: str) -> Dict[str, Any]:
    """영상 시각 → 장·문장 표. 영상이 없으면 `video` 가 빈다."""
    from vendor.vw_srt import auto_time_cues, split_into_cues

    dist = ws.step_dir(pid, slug, "dist")
    mp4 = video_path(pid, slug)
    comp = dist / "_hyper" / "index.html"
    deck_p = ws.step_dir(pid, slug, "deck") / ws.F_DECK
    if not (mp4.is_file() and comp.is_file() and deck_p.is_file()):
        return {"video": "", "cues": [], "stale": False}

    deck = json.loads(deck_p.read_text(encoding="utf-8"))
    by_no = {int(s.get("no") or 0): s for s in deck.get("slides") or []}
    out: List[Dict[str, Any]] = []
    for m in _SEC.finditer(comp.read_text(encoding="utf-8")):
        no, start, dur = int(m.group(1)), float(m.group(2)), float(m.group(3))
        s = by_no.get(no) or {}
        key = int(s.get("src_no") or no)
        title = s.get("title") or ""
        srt = (s.get("narration") or {}).get("srt_text") or ""
        au = float((s.get("audio") or {}).get("sec") or 0)
        pieces = auto_time_cues(split_into_cues(srt), au) if srt and au > 0 else []
        if not pieces:
            out.append({"start": round(start, 2), "end": round(start + dur, 2),
                        "no": key, "i": 0, "title": title, "text": title})
            continue
        for i, c in enumerate(pieces):
            # 마지막 문장은 장 끝(숨 TAIL_SEC 포함)까지 — 틈이 생기면 표시가 앞 장으로 간다
            end = start + (dur if i == len(pieces) - 1 else c.end)
            out.append({"start": round(start + c.start, 2), "end": round(end, 2),
                        "no": key, "i": i, "title": title, "text": c.text})
    # ★ 굽고 난 뒤 덱을 다시 조립했으면 글(자막)이 영상과 다를 수 있다 — 시각은 맞다
    stale = deck_p.stat().st_mtime > mp4.stat().st_mtime + 5
    rel = mp4.relative_to(ws.project_dir(pid, slug)).as_posix()
    return {"video": rel, "name": mp4.name, "cues": out, "stale": stale}


def _marks_doc(pid: int, slug: str) -> Dict[str, Any]:
    return ws.read_json(ws.step_dir(pid, slug, "deck") / F_MARKS, {}) or {}


def load_marks(pid: int, slug: str) -> List[Dict[str, Any]]:
    return list(_marks_doc(pid, slug).get("marks") or [])


def save_marks(pid: int, slug: str, marks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    clean: List[Dict[str, Any]] = []
    seen: Dict[Any, Dict[str, Any]] = {}
    for m in marks or []:
        try:
            no, i, t = int(m.get("no")), int(m.get("i") or 0), float(m.get("t") or 0)
        except (TypeError, ValueError):
            continue
        memo = str(m.get("memo") or "")[:300]
        if (no, i) in seen:
            # 같은 자리를 두 PC 에서 찍었으면 하나로 — 적어 둔 메모는 살린다
            if memo and not seen[(no, i)]["memo"]:
                seen[(no, i)]["memo"] = memo
            continue
        one = {"no": no, "i": i, "t": round(t, 1),
               "text": str(m.get("text") or "")[:200], "memo": memo}
        seen[(no, i)] = one
        clean.append(one)
    clean.sort(key=lambda m: m["t"])
    doc = _marks_doc(pid, slug)
    doc.update({"marks": clean, "at": datetime.now().isoformat(timespec="seconds")})
    ws.write_json(ws.step_dir(pid, slug, "deck") / F_MARKS, doc)
    return clean


# ── 구글 드라이브 ─────────────────────────────────────────────────────────
def drive_root() -> Optional[Path]:
    """드라이브 데스크톱의 「내 드라이브」. 설정(`review_drive`) → 환경변수 → G: 순으로 찾는다."""
    want = (os.environ.get("SHOWCASE_DRIVE") or config.load().get("review_drive") or "").strip()
    cands = [want] if want else ["G:/내 드라이브", "G:/My Drive"]
    for c in cands:
        p = Path(c)
        if p.is_dir():
            return p
    return None


def drive_dir(pid: int, slug: str, *, create: bool = False) -> Optional[Path]:
    root = drive_root()
    if root is None:
        return None
    d = root / "영상검수" / ws.project_dir(pid, slug).name
    if create:
        d.mkdir(parents=True, exist_ok=True)
    return d


def to_drive(pid: int, slug: str, title: str = "") -> Dict[str, Any]:
    """검수 html 을 새로 만들고, 영상과 함께 드라이브 폴더에 복사한다.

    ★ 영상은 **바뀌었을 때만** 다시 복사한다(크기·시각). 300MB 를 매번 올리면
      드라이브가 동기화를 끝내기 전에 또 덮는다.
    """
    page = export(pid, slug, title)
    if page is None:
        return {"ok": False, "why": "모션 영상(s12h)이 아직 없습니다"}
    d = drive_dir(pid, slug, create=True)
    if d is None:
        return {"ok": False, "why": "구글 드라이브(G:/내 드라이브)를 찾지 못했습니다 — "
                                    "드라이브 데스크톱에 로그인하세요"}
    mp4 = video_path(pid, slug)
    dst = d / mp4.name
    st = mp4.stat()
    copied = False
    if not (dst.is_file() and dst.stat().st_size == st.st_size
            and dst.stat().st_mtime >= st.st_mtime - 2):
        shutil.copy2(mp4, dst)
        copied = True
    shutil.copy2(page, d / page.name)
    return {"ok": True, "dir": str(d), "video_copied": copied,
            "mb": round(st.st_size / 1e6, 1), "page": page.name}


def drive_inbox(pid: int, slug: str) -> Dict[str, Any]:
    """드라이브 폴더에 **아직 안 가져온** 검수표가 있나."""
    d = drive_dir(pid, slug)
    if d is None or not d.is_dir():
        return {"dir": str(d) if d else "", "files": []}
    seen = _marks_doc(pid, slug).get("drive_seen") or {}
    files = []
    for f in sorted(d.glob("*검수표*.json")):
        mt = round(f.stat().st_mtime, 1)
        if seen.get(f.name) == mt:
            continue
        try:
            got = json.loads(f.read_text(encoding="utf-8"))
            n = len(got if isinstance(got, list) else got.get("marks") or [])
        except (OSError, ValueError):
            continue
        files.append({"name": f.name, "n": n, "mtime": mt,
                      "at": datetime.fromtimestamp(mt).strftime("%m-%d %H:%M")})
    return {"dir": str(d), "files": files}


def drive_import(pid: int, slug: str) -> Dict[str, Any]:
    """드라이브의 새 검수표를 지금 검수표에 더하고, 가져온 파일을 적어 둔다."""
    box = drive_inbox(pid, slug)
    d = Path(box["dir"]) if box["dir"] else None
    add: List[Dict[str, Any]] = []
    for f in box["files"]:
        got = json.loads((d / f["name"]).read_text(encoding="utf-8"))
        add += got if isinstance(got, list) else (got.get("marks") or [])
    marks = save_marks(pid, slug, load_marks(pid, slug) + add)
    doc = _marks_doc(pid, slug)
    seen = dict(doc.get("drive_seen") or {})
    seen.update({f["name"]: f["mtime"] for f in box["files"]})
    doc["drive_seen"] = seen
    ws.write_json(ws.step_dir(pid, slug, "deck") / F_MARKS, doc)
    return {"marks": marks, "added": len(add), "files": [f["name"] for f in box["files"]]}


# ── 서버 없이 여는 검수 파일 ──────────────────────────────────────────────
def export(pid: int, slug: str, title: str = "") -> Optional[Path]:
    """`11_완성/<영상>-영상검수.html` — 영상과 같은 폴더에 두고 더블클릭으로 연다."""
    c = cues(pid, slug)
    if not c["video"]:
        return None
    mp4 = video_path(pid, slug)
    out = mp4.with_name(mp4.stem + "-영상검수.html")
    data = {"video": mp4.name, "title": title or slug, "cues": c["cues"],
            "marks": load_marks(pid, slug),
            "at": datetime.now().strftime("%Y-%m-%d %H:%M")}
    page = (_PAGE.replace("__TITLE__", html.escape(title or slug))
            .replace("__DATA__", json.dumps(data, ensure_ascii=False)
                     .replace("</", "<\\/")))
    out.write_text(page, encoding="utf-8")
    return out


_PAGE = r"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__ · 영상 검수</title>
<style>
:root{--bg:#f6f4ef;--card:#fff;--ink:#22201c;--mut:#7a746a;--line:#e3ded4;--acc:#9a4d33;--hl:#fff3c4}
@media (prefers-color-scheme:dark){:root{--bg:#1c1b19;--card:#262421;--ink:#eee9e0;--mut:#a39c90;--line:#3a3732;--acc:#e08a63;--hl:#4a3f1c}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 system-ui,"Malgun Gothic",sans-serif}
header{padding:14px 20px;border-bottom:1px solid var(--line);display:flex;gap:12px;align-items:baseline;flex-wrap:wrap}
header h1{font-size:18px;margin:0}header span{color:var(--mut);font-size:13px}
main{display:grid;grid-template-columns:minmax(0,1.6fr) minmax(300px,1fr);gap:16px;padding:16px 20px}
@media (max-width:900px){main{grid-template-columns:1fr}}
video{width:100%;background:#000;border-radius:8px;aspect-ratio:16/9}
.now{margin-top:8px;padding:8px 10px;background:var(--card);border:1px solid var(--line);border-radius:8px;min-height:44px}
.now b{color:var(--acc);margin-right:6px}
.keys{color:var(--mut);font-size:12.5px;margin-top:6px}
kbd{border:1px solid var(--line);border-bottom-width:2px;border-radius:4px;padding:0 5px;font-size:12px;background:var(--card)}
.side{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px;align-self:start}
.bar{display:flex;gap:6px;flex-wrap:wrap;align-items:center;margin-bottom:8px}
.bar h2{font-size:16px;margin:0 auto 0 0}
button{font:inherit;font-size:13px;padding:5px 10px;border-radius:6px;border:1px solid var(--line);background:var(--card);color:var(--ink);cursor:pointer}
button.pri{background:var(--acc);border-color:var(--acc);color:#fff}
ul{list-style:none;margin:0;padding:0;max-height:70vh;overflow:auto}
li{border-top:1px solid var(--line);padding:7px 2px;display:grid;grid-template-columns:auto 1fr auto;gap:4px 8px;align-items:start}
li.flash{animation:f 1.2s}@keyframes f{from{background:var(--hl)}to{background:transparent}}
li a{color:var(--acc);cursor:pointer;font-variant-numeric:tabular-nums;text-decoration:underline}
li .tx{font-size:13.5px}li .tx b{margin-right:4px}
li input{grid-column:2/4;font:inherit;font-size:13px;padding:4px 6px;border:1px solid var(--line);border-radius:5px;background:var(--bg);color:var(--ink)}
li .x{border:0;background:none;color:var(--mut);padding:0 4px}
.empty{color:var(--mut);font-size:13px;padding:8px 0}
.how{color:var(--mut);font-size:12.5px;margin-top:10px;border-top:1px solid var(--line);padding-top:8px}
</style></head><body>
<header><h1>__TITLE__</h1><span id="sub"></span></header>
<main>
<section>
  <video id="v" controls preload="metadata"></video>
  <div class="now" id="now">재생하면 지금 읽는 문장이 여기 뜹니다.</div>
  <div class="keys"><kbd>M</kbd> 여기 표시 · <kbd>←</kbd><kbd>→</kbd> 5초 · <kbd>Space</kbd> 재생·멈춤 · <kbd>R</kbd> 지금 문장 처음부터</div>
</section>
<aside class="side">
  <div class="bar"><h2 id="cnt">검수표 0줄</h2>
    <button id="mark">📌 여기 표시</button>
    <button class="pri" id="save">검수표 저장</button>
    <button id="clear">비우기</button></div>
  <ul id="list"></ul>
  <div class="how">이상하게 들리는 곳에서 <kbd>M</kbd> 을 누르고, 칸에 무엇이 이상한지 적어 두세요.<br>
  다 들었으면 «검수표 저장» — 저장 창에서 <b>이 html 이 있는 드라이브 폴더</b>를 고르세요.
  회사 PC 덱 화면의 «영상 보며 검수» 에 「드라이브에 새 검수표」로 뜹니다.<br>
  표시는 이 브라우저에도 남으므로 창을 닫았다 열어도 이어서 할 수 있습니다.</div>
</aside>
</main>
<script>
const D = __DATA__;
const LAG = 1.5, KEY = "review:" + D.video;
const v = document.getElementById("v"), $ = (id) => document.getElementById(id);
v.src = encodeURI(D.video);
v.onerror = () => { $("now").textContent = "영상을 못 찾았습니다 — 이 파일과 " + D.video + " 를 같은 폴더에 두세요."; };
$("sub").textContent = `${D.cues.length}문장 · ${D.at} 에 만듦`;
let marks = D.marks || [];
try { const s = JSON.parse(localStorage.getItem(KEY) || "null"); if (s && s.length >= marks.length) marks = s; } catch {}
const fmt = (t) => `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, "0")}`;
const at = (t) => { let k = -1; for (let i = 0; i < D.cues.length && D.cues[i].start <= t; i++) k = i; return k < 0 ? 0 : k; };
const keep = () => { try { localStorage.setItem(KEY, JSON.stringify(marks)); } catch {} };
function draw(flashKey) {
  $("cnt").textContent = `검수표 ${marks.length}줄`;
  const ul = $("list"); ul.textContent = "";
  if (!marks.length) { ul.innerHTML = '<div class="empty">아직 없습니다.</div>'; return; }
  for (const m of marks) {
    const li = document.createElement("li");
    if (flashKey === m.no + ":" + m.i) li.className = "flash";
    const a = document.createElement("a"); a.textContent = fmt(m.t);
    a.onclick = () => { v.currentTime = Math.max(0, m.t - 2); v.play(); };
    const tx = document.createElement("div"); tx.className = "tx";
    const b = document.createElement("b"); b.textContent = m.no + "장";
    tx.append(b, document.createTextNode(m.text || ""));
    const x = document.createElement("button"); x.className = "x"; x.textContent = "✕"; x.title = "빼기";
    x.onclick = () => { marks = marks.filter((y) => y !== m); keep(); draw(); };
    const memo = document.createElement("input"); memo.placeholder = "무엇이 이상한가 (예: 니은 디귿으로 읽어야)";
    memo.value = m.memo || ""; memo.oninput = () => { m.memo = memo.value; keep(); };
    li.append(a, tx, x, memo); ul.appendChild(li);
  }
}
function mark() {
  if (!D.cues.length) return;
  const c = D.cues[at(Math.max(0, v.currentTime - LAG))];
  const k = c.no + ":" + c.i;
  if (!marks.some((m) => m.no + ":" + m.i === k)) {
    marks.push({no: c.no, i: c.i, t: Math.round(v.currentTime * 10) / 10, text: c.text, memo: ""});
    marks.sort((a, b) => a.t - b.t); keep();
  }
  draw(k);
}
function now() {
  if (!D.cues.length) return;
  const c = D.cues[at(v.currentTime)];
  $("now").innerHTML = ""; const b = document.createElement("b"); b.textContent = c.no + "장";
  $("now").append(b, document.createTextNode(c.text));
}
v.addEventListener("timeupdate", now); v.addEventListener("seeked", now);
$("mark").onclick = (e) => { e.currentTarget.blur(); mark(); };
$("clear").onclick = (e) => { e.currentTarget.blur(); if (marks.length && confirm("검수표를 비울까요?")) { marks = []; keep(); draw(); } };
/* 검수표 저장 — 저장 창이 뜨면 **이 html 이 있는 드라이브 폴더**를 고른다(한 번 고르면
   다음부터 그 자리에서 열린다). 저장 창을 못 쓰는 브라우저는 내려받기로 — 그때는
   받은 파일을 이 폴더로 옮긴다. 회사 PC 가 이 폴더를 보고 새 검수표를 알려 준다. */
$("save").onclick = async (e) => {
  e.currentTarget.blur();
  const name = D.video.replace(/\.mp4$/i, "") + "-검수표.json";
  const text = JSON.stringify({video: D.video, saved: new Date().toISOString(), marks}, null, 1);
  if (window.showSaveFilePicker) {
    try {
      const h = await showSaveFilePicker({id: "review", suggestedName: name,
        types: [{description: "검수표", accept: {"application/json": [".json"]}}]});
      const w = await h.createWritable(); await w.write(text); await w.close();
      $("now").textContent = `저장했습니다 — ${h.name} (${marks.length}줄). 회사 PC 검수 패널에 뜹니다.`;
      return;
    } catch (err) { if (err && err.name === "AbortError") return; }
  }
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], {type: "application/json"}));
  a.download = name; a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  $("now").textContent = "내려받았습니다 — 받은 파일을 이 html 이 있는 드라이브 폴더로 옮기세요.";
};
/* 키는 e.code 로 본다 — 한글 자판이면 M 이 「ㅡ」로 온다. 캡처 단계에서 받아
   영상에 포커스가 있을 때 브라우저 기본 동작(스페이스 재생)과 두 번 겹치지 않게 한다. */
addEventListener("keydown", (e) => {
  const t = e.target; if (e.ctrlKey || e.altKey || e.metaKey) return;
  if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA")) return;
  const k = e.code;
  if (k === "KeyM") mark();
  else if (k === "ArrowLeft") v.currentTime = Math.max(0, v.currentTime - 5);
  else if (k === "ArrowRight") v.currentTime += 5;
  else if (k === "Space") v.paused ? v.play() : v.pause();
  else if (k === "KeyR" && D.cues.length) { v.currentTime = D.cues[at(v.currentTime)].start; v.play(); }
  else return;
  e.preventDefault(); e.stopPropagation();
}, true);
draw();
</script></body></html>
"""
