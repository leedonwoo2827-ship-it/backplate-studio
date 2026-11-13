# -*- coding: utf-8 -*-
"""S6p AI 발음 교정 — 음성을 굽기 **전에** 발음 대본 전체를 Claude 가 소리대로 고친다.

    s6 발음(narration_text) + 자막  →  Claude  →  _cache/s6p-pron-ai.json

★ **왜 있나.** 발음 변환은 규칙(`core/honorific.for_speech` · 발음 사전)인데, 규칙이
  모르는 것이 장마다 나온다. 2과목(스프레드시트)은 `#N/A` · `$A$2` · `VLOOKUP` ·
  `F9` · `#,##0` 을 변환기가 지우거나 영문 그대로 두어서, 77장 발음을 손으로 짠
  변환 스크립트로 다시 만들었다(2026-11-01). 1과목은 2진수 `101101` 을
  「십만천백일」로 읽었다. 그 판단을 `llm/prompts/pron_fix.md` 에 옮겨 놓고 여기서
  한 번에 돌린다. 해설북 스튜디오(`261103-new-etest-ebook` `voicecheck.ai_fix_all`)
  에서 같은 일을 먼저 해 봤고, 그 지시문이 바탕이다.

★ **손편집은 언제나 이긴다.** 결과는 `deck.overrides.json` 이 아니라 이 단계의
  캐시에만 둔다. 읽는 쪽(`registry.narration_of` · 조립 · 덱 화면)이
  s6 → AI 교정 → 손편집 순서로 얹는다. 손으로 발음을 고친 장은 **보내지도 않는다.**

★ **이미 고친 장은 다시 안 묻는다.** 장마다 고칠 때의 s6 발음(`src`)을 같이 적어
  두고, 그것이 그대로면 건너뛴다. 원고가 바뀐 장만 다시 간다 — 두 번째부터는
  대개 $0 이다. `--force` 면 손편집 없는 장을 전부 다시 묻는다.

★ **여러 장을 한 콜에 묶는다.** 호출 한 번에 최소 $0.24 다(`s3d_label_fit` 과 같다).
"""
from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from core import config, workspace as ws
from llm.claude_provider import ClaudeProvider
from pipeline.registry import PROMPTS, STAGES, cached_data, read_cache, write_cache

KEY = "s6p-pron-ai"
BATCH = 10                      # 한 콜에 보낼 장 수

# 고친 발음에 남으면 안 되는 것 — 로마자 · 숫자 · 수식 기호 · 괄호
LEFTOVER = re.compile(r"[A-Za-z0-9²³√∑Σ≤≥≠×÷±∞π^%=<>+*/()（）#$@_\[\]{}|\\]")

SCHEMA = {
    "type": "object",
    "properties": {
        "slides": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "no": {"type": "integer"},
                    "text": {"type": "string"},
                },
                "required": ["no", "text"],
            },
        },
    },
    "required": ["slides"],
}


def provider(project: Dict[str, Any], on_activity: Optional[Callable[[str], None]] = None
             ) -> ClaudeProvider:
    cfg = config.load()
    models = project.get("models") or {}
    return ClaudeProvider(
        model=models.get("pron") or cfg["models"].get("pron") or "claude-sonnet-5",
        effort=cfg["effort"].get("pron") or "medium",
        allowed_tools=[], max_turns=1,
        budget_usd=cfg["budget_usd"]["per_stage"],
        on_activity=on_activity,
    )


def _brief(items: List[Dict[str, Any]], again: str = "") -> str:
    out = [f"슬라이드 {len(items)}장의 발음 대본을 고쳐라."]
    for t in items:
        out.append(f"\n## {t['no']}장\n[자막] {t['srt']}\n[발음] {t['text']}")
    if again:
        out.append(f"\n(앞 답에 로마자 · 숫자 · 기호가 남았거나 빠진 장이 있었다: {again}"
                   " — 그 장을 다시 전부 한글로.)")
    return "\n".join(out)


def ask(items: List[Dict[str, Any]], p: ClaudeProvider,
        log: Callable[[str], None] = lambda _m: None) -> Tuple[Dict[int, str], float, List[int]]:
    """`items` = [{no, srt, text}] 를 한 콜에 보내고, 남은 것은 한 번 더 묻는다.

    돌려주는 값 = (장 → 고친 발음, 든 돈, 끝내 못 고친 장).
    로마자·숫자가 남은 답은 **버린다** — 그 장은 원래 발음으로 나간다.
    """
    system = (PROMPTS / "pron_fix.md").read_text(encoding="utf-8")
    want = {int(t["no"]): t for t in items}
    got: Dict[int, str] = {}
    cost = 0.0
    todo = list(items)
    for attempt in range(2):
        if not todo:
            break
        again = ", ".join(f"{t['no']}장" for t in todo) if attempt else ""
        raw = p.structured(system, [{"role": "user", "content": _brief(todo, again)}],
                           schema=SCHEMA)
        cost += p.last_cost_usd
        ans = {int(r.get("no") or 0): (r.get("text") or "").strip()
               for r in raw.get("slides") or []}
        # 한 장만 물었는데 번호를 다르게 달아 오면 그 답이 그 장이다
        if len(todo) == 1 and len(ans) == 1 and todo[0]["no"] not in ans:
            ans = {int(todo[0]["no"]): next(iter(ans.values()))}
        bad: List[Dict[str, Any]] = []
        for t in todo:
            a = ans.get(int(t["no"]))
            if a and not LEFTOVER.search(a):
                got[int(t["no"])] = a
            else:
                bad.append(t)
                if a:
                    left = "".join(sorted(set(LEFTOVER.findall(a))))[:20]
                    log(f"{t['no']}장: 아직 남은 글자 {left!r}")
        todo = bad
    failed = [n for n in want if n not in got]
    return got, cost, failed


# ── 실행 ───────────────────────────────────────────────────────────────────
def run(job, pid: int, slug: str, project: Dict[str, Any], *, force: bool = False):
    stage = STAGES[KEY]
    script = (cached_data(pid, slug, "s6-script") or {}).get("slides") or {}
    if not script:
        raise RuntimeError("대본(s6-script)이 아직 없습니다")
    ov = ws.load_overrides(pid, slug).get("slides", {}) or {}
    prev = ((read_cache(pid, slug, KEY) or {}).get("data") or {}).get("slides") or {}
    keep: Dict[str, Dict[str, Any]] = dict(prev)

    todo: List[Dict[str, Any]] = []
    hand = same = 0
    for k in sorted(script, key=lambda x: int(x)):
        sc = script[k] or {}
        src = (sc.get("narration_text") or "").strip()
        if not src:
            continue
        if "text" in ((ov.get(k) or {}).get("narration") or {}):
            hand += 1                       # 사람이 가져간 장 — 묻지 않는다
            continue
        if not force and (prev.get(k) or {}).get("src") == src:
            same += 1
            continue
        todo.append({"no": int(k), "srt": (sc.get("srt_text") or "").strip(), "text": src})

    job.add_log(f"AI 발음 교정할 장 {len(todo)}개 · 손편집이라 건너뜀 {hand}개 · "
                f"이미 고쳐서 건너뜀 {same}개")

    p = provider(project, job.add_log) if todo else None
    batches = [todo[i:i + BATCH] for i in range(0, len(todo), BATCH)]
    warn: List[str] = []
    cost = 0.0
    changed = 0
    for bi, batch in enumerate(batches):
        if getattr(job, "canceled", False):
            raise RuntimeError("사람이 멈췄습니다")
        job.progress(bi, len(batches), f"{batch[0]['no']}~{batch[-1]['no']}장")
        try:
            got, c, failed = ask(batch, p, job.add_log)
        except Exception as e:                         # noqa: BLE001
            warn.append(f"{batch[0]['no']}~{batch[-1]['no']}장 묶음 실패: "
                        f"{type(e).__name__}: {str(e)[:160]}")
            job.add_log(warn[-1])
            continue
        cost += c
        for t in batch:
            k = str(t["no"])
            if t["no"] in got:
                if got[t["no"]] != t["text"]:
                    changed += 1
                keep[k] = {"text": got[t["no"]], "src": t["text"]}
        if failed:
            warn.append("못 고친 장(원래 발음으로 나갑니다): "
                        + ", ".join(map(str, failed)))
            job.add_log(warn[-1])
        # 묶음마다 저장 — 중간에 끊겨도 받은 만큼은 남는다
        _save(pid, slug, project, stage, keep, p, cost, warn)

    job.progress(len(batches), len(batches), "정리")
    if changed:
        # ★ 음성·자막(s10·s11)은 `narration_rev`, 조립(s8)은 `overrides_rev` 를 읽는다.
        #   AI 가 발음을 바꾸면 둘 다 다시 돌아야 한다.
        project["narration_rev"] = int(project.get("narration_rev") or 0) + 1
        project["overrides_rev"] = int(project.get("overrides_rev") or 0) + 1
        ws.save_project(pid, slug, project)
    job.add_log(f"AI 발음 교정 {len(todo)}장 중 {changed}장 바뀜 · ${cost:.3f}")
    return _save(pid, slug, project, stage, keep, p, cost, warn)


def _save(pid: int, slug: str, project: Dict[str, Any], stage, keep, p, cost, warn):
    return write_cache(pid, slug, KEY,
                       input_hash=stage.input_hash(pid, slug, project),
                       data={"slides": keep},
                       code_version=stage.code_version, model=p.model if p else "",
                       cost_usd=cost,
                       status="degraded" if warn else "ok", warnings=warn[:10])


STAGES[KEY].run = run
