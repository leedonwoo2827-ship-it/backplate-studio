# -*- coding: utf-8 -*-
"""사람이 확정한 라벨 자리를 **자동 배치의 예시**로 뽑아 둔다.

    .venv-app\\Scripts\\python tools\\export_label_examples.py <pid> <장번호> [<장번호> …]

`llm/prompts/label_fit_examples/` 에 장마다 격자 얹은 그림(jpg)과 라벨 자리(json)를
남긴다. 자동 배치(`pipeline/s3d_label_fit.py`)가 앞의 두 장을 예시로 싣는다.

★ 손편집(`deck.overrides.json`)이 있는 장만 뽑는다 — 사람이 확정한 것이 예시다.
★ 예시를 바꾸면 프롬프트 폴더가 바뀐 것이라, 자동 배치를 다시 돌릴 때 반영된다.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import workspace as ws                       # noqa: E402
from pipeline import s3d_label_fit as fit             # noqa: E402
from pipeline.registry import cached_data             # noqa: E402


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) < 2:
        print(__doc__)
        return 2
    pid, nos = int(args[0]), [int(a) for a in args[1:]]
    proj = next((p for p in ws.list_projects() if int(p.get("id") or 0) == pid), None)
    if proj is None:
        print(f"프로젝트 {pid} 를 찾지 못했습니다")
        return 1
    slug = proj["slug"]
    ov = ws.load_overrides(pid, slug).get("slides", {})
    imgs = (cached_data(pid, slug, "s3b-images") or {}).get("images") or {}
    root = ws.step_dir(pid, slug, "images").parent
    out = fit.EXAMPLES
    out.mkdir(parents=True, exist_ok=True)

    for no in nos:
        key = str(no)
        labs = (ov.get(key) or {}).get("labels")
        got = imgs.get(key) or {}
        if not labs or not got.get("file"):
            print(f"{no}장: 손편집 라벨이나 그림이 없어 건너뜁니다")
            continue
        jpg = fit.sheet(pid, slug, no, root / got["file"])
        name = f"{slug}-{no:03d}"
        shutil.copyfile(jpg, out / f"{name}.jpg")
        keep = [{k: l.get(k) for k in ("head", "sub", "x", "y", "w", "cell") if k in l}
                for l in labs]
        (out / f"{name}.json").write_text(
            json.dumps({"image": f"{name}.jpg", "labels": keep}, ensure_ascii=False, indent=2),
            encoding="utf-8")
        print(f"{no}장 → {out / name}.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
