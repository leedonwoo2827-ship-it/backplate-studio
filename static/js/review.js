/* 영상 보며 검수 — 완성 영상을 보다가 M 을 누르면 그 장·문장이 검수표에 쌓인다.
 *
 * ★ 왜 있나 — 59분 영상을 처음부터 끝까지 들으며 장마다 발음을 고치면 검수가
 *   끝나지 않는다. 이상하게 들리는 곳만 찍고, 표를 눌러 **그 장의 발음 칸**으로
 *   바로 간다. 해설북 스튜디오(`261103-new-etest-ebook`)에서 먼저 해 본 방식이다.
 *
 * ★ 덱 화면 **안에** 붙는다 — 표를 누르면 아래 편집기가 그 장으로 바뀌고 영상은
 *   그대로 남는다. 다른 화면으로 가면 듣던 자리를 잃는다.
 *
 * ★ 시각 → 장·문장 표는 서버가 **그 영상을 구운 컴포지션**에서 만든다
 *   (`render/review_video.py`). 음성을 다시 합성해도 이미 구운 영상과 어긋나지 않는다.
 *
 * ★ 다른 PC 에서 들은 검수표(`…-검수표.json`)를 여기서 불러온다. 그 파일은
 *   영상 옆의 `…-영상검수.html` 이 만든다(서버 없이 열린다).
 */
"use strict";

import { el, api, icon, toast } from "./util.js";
import { state } from "./store.js";

const LAG = 1.5;      // 듣고 누르기까지 늦는 만큼 — 그 앞 문장을 찍는다
const fmt = (t) => `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, "0")}`;

/** 패널을 만든다. `goto(no)` = 그 장의 발음 칸으로 가기. 닫을 때 `destroy()`. */
export function reviewPanel(goto) {
  const box = el("div", "rv");
  const pid = state.projectId;
  let C = null;            // {video, cues, marks, stale}
  let marks = [];

  const at = (t) => {
    const c = C.cues;
    let k = -1;
    for (let i = 0; i < c.length && c[i].start <= t; i++) k = i;
    return k < 0 ? 0 : k;
  };
  const save = async () => {
    try {
      const r = await api(`/api/projects/${pid}/review-marks`,
                          {method: "PUT", body: {marks}});
      marks = r.marks;
    } catch (e) { toast("검수표를 저장하지 못했습니다: " + e.message, "err"); }
  };

  const v = el("video", "rv-video");
  v.controls = true;
  v.preload = "metadata";
  const now = el("div", "rv-now", "재생하면 지금 읽는 문장이 여기 뜹니다.");
  const keys = el("div", "rv-keys");
  keys.innerHTML = "<kbd>M</kbd> 여기 표시 · <kbd>←</kbd><kbd>→</kbd> 5초 · "
    + "<kbd>Space</kbd> 재생·멈춤 · <kbd>R</kbd> 지금 문장 처음부터";
  const left = el("div", "rv-left");
  left.append(v, now, keys);

  const cnt = el("b", "rv-cnt", "검수표 0줄");
  const mk = (ic, label, tip) => {
    const b = el("button", "btn sm");
    b.type = "button";
    if (ic) b.appendChild(icon(ic, 12));
    b.appendChild(el("span", null, label));
    b.title = tip;
    return b;
  };
  const bMark = mk("target", "여기 표시", "지금 듣는 문장을 검수표에 넣습니다 (M)");
  const bImport = mk("folder", "검수표 불러오기",
    `다른 PC 의 «영상검수.html» 에서 저장한 …-검수표.json 을 불러옵니다
지금 검수표에 더합니다`);
  const bExport = mk("upload", "드라이브로 보내기",
    `영상(mp4)과 «…-영상검수.html» 을 구글 드라이브 «영상검수» 폴더에 복사합니다
집 노트북에서 그 폴더의 html 을 더블클릭해 검수합니다
영상은 바뀌었을 때만 다시 복사합니다 (모션 영상을 구우면 저절로 보냅니다)`);
  const bClear = mk(null, "비우기", "검수표를 비웁니다");
  const file = el("input");
  file.type = "file";
  file.accept = ".json,application/json";
  file.hidden = true;
  const bar = el("div", "rv-bar");
  bar.append(cnt, bMark, bImport, bExport, bClear, file);
  /* 드라이브에 집에서 찍은 검수표가 새로 있으면 맨 위에 한 줄로 알린다 */
  const inbox = el("div", "rv-inbox");
  inbox.hidden = true;
  const chips = el("div", "rv-chips");
  const list = el("ul", "rv-list");
  const right = el("div", "rv-right");
  right.append(bar, inbox, chips, list);
  box.append(left, right);

  function draw(flash) {
    cnt.textContent = `검수표 ${marks.length}줄`;
    list.textContent = "";
    chips.textContent = "";
    if (!marks.length) {
      list.appendChild(el("li", "rv-empty", "이상하게 들리는 곳에서 M 을 누르세요."));
      return;
    }
    // 장 번호 칩 — 한 장에 여러 줄을 찍어도 고칠 장은 하나다
    const nos = [...new Set(marks.map((m) => m.no))].sort((a, b) => a - b);
    chips.appendChild(el("span", "rv-chips-lb", `고칠 장 ${nos.length}개`));
    for (const no of nos) {
      const c = el("button", "num-chip");
      c.type = "button";
      c.textContent = String(no);
      c.onclick = () => goto(no);
      chips.appendChild(c);
    }
    for (const m of marks) {
      const li = el("li", "rv-row" + (flash === `${m.no}:${m.i}` ? " flash" : ""));
      const t = el("a", "rv-t", fmt(m.t));
      t.title = "그 2초 앞부터 다시 듣기";
      t.onclick = () => { v.currentTime = Math.max(0, m.t - 2); v.play(); };
      const tx = el("a", "rv-tx");
      tx.append(el("b", null, `${m.no}장`), el("span", null, m.text || ""));
      tx.title = "그 장의 발음 칸으로 갑니다";
      tx.onclick = () => goto(m.no);
      const x = el("button", "rv-x", "✕");
      x.type = "button";
      x.title = "빼기";
      x.onclick = () => { marks = marks.filter((y) => y !== m); draw(); save(); };
      li.append(t, tx, x);
      if (m.memo) li.appendChild(el("div", "rv-memo", m.memo));
      list.appendChild(li);
    }
  }

  function mark() {
    if (!C || !C.cues.length) return;
    const c = C.cues[at(Math.max(0, v.currentTime - LAG))];
    const k = `${c.no}:${c.i}`;
    if (!marks.some((m) => `${m.no}:${m.i}` === k)) {
      marks.push({no: c.no, i: c.i, t: Math.round(v.currentTime * 10) / 10,
                  text: c.text, memo: ""});
      marks.sort((a, b) => a.t - b.t);
      save();
    }
    draw(k);
  }
  const paintNow = () => {
    if (!C || !C.cues.length) return;
    const c = C.cues[at(v.currentTime)];
    now.textContent = "";
    now.append(el("b", null, `${c.no}장`), el("span", null, c.text));
  };
  v.addEventListener("timeupdate", paintNow);
  v.addEventListener("seeked", paintNow);

  /* 버튼을 누른 뒤 포커스를 뺀다 — 안 빼면 Space 가 그 버튼을 또 누른다 */
  const once = (b, fn) => { b.onclick = (e) => { e.currentTarget.blur(); fn(); }; };
  once(bMark, mark);
  once(bClear, () => {
    if (marks.length && confirm("검수표를 비울까요?")) { marks = []; draw(); save(); }
  });
  once(bImport, () => file.click());
  file.onchange = async () => {
    const f = file.files[0];
    file.value = "";
    if (!f) return;
    try {
      const got = JSON.parse(await f.text());
      const add = Array.isArray(got) ? got : (got.marks || []);
      if (!add.length) { toast("검수표가 비어 있습니다"); return; }
      const r = await api(`/api/projects/${pid}/review-marks`,
                          {method: "PUT", body: {marks: add, merge: true}});
      marks = r.marks;
      draw();
      toast(`${add.length}줄을 불러왔습니다 — 장 번호를 눌러 고치세요`);
    } catch (e) { toast("불러오지 못했습니다: " + e.message, "err"); }
  };
  once(bExport, async () => {
    const lab = bExport.querySelector("span:last-child");
    bExport.disabled = true;
    lab.textContent = "복사 중…";
    try {
      const r = await api(`/api/projects/${pid}/review-export`, {method: "POST"});
      toast(r.video_copied
        ? `드라이브에 영상(${r.mb}MB)과 검수 파일을 보냈습니다 — 동기화가 끝나면 집에서 열립니다`
        : "검수 파일을 새로 보냈습니다 — 영상은 이미 드라이브에 있습니다");
    } catch (e) { toast("보내지 못했습니다: " + e.message, "err"); }
    finally { lab.textContent = "드라이브로 보내기"; bExport.disabled = false; }
  });

  function paintInbox(d) {
    const files = (d && d.files) || [];
    inbox.textContent = "";
    inbox.hidden = !files.length;
    if (!files.length) return;
    const n = files.reduce((a, f) => a + (f.n || 0), 0);
    inbox.append(el("span", null,
      `드라이브에 새 검수표 ${files.length}개 · ${n}줄 (${files.map((f) => f.at).join(", ")})`));
    const b = el("button", "btn sm primary", "가져오기");
    b.type = "button";
    b.onclick = async () => {
      b.disabled = true;
      try {
        const r = await api(`/api/projects/${pid}/review-drive/import`, {method: "POST"});
        marks = r.marks;
        paintInbox(null);
        draw();
        toast(`${r.added}줄을 가져왔습니다 — 장 번호를 눌러 고치세요`);
      } catch (e) { toast("가져오지 못했습니다: " + e.message, "err"); b.disabled = false; }
    };
    inbox.appendChild(b);
  }

  /* 키 — 캡처 단계에서 먼저 받아 덱의 ←/→(장 넘김)보다 앞선다. 입력칸 안에서는 양보.
     e.code 로 본다: 한글 자판이면 M 이 「ㅡ」로 온다. */
  const onKey = (e) => {
    if (!box.isConnected || !C || !C.video) return;
    const t = e.target;
    if (e.ctrlKey || e.altKey || e.metaKey) return;
    if (t && (t.tagName === "TEXTAREA" || t.tagName === "INPUT" || t.tagName === "SELECT")) return;
    const k = e.code;
    if (k === "KeyM") mark();
    else if (k === "ArrowLeft") v.currentTime = Math.max(0, v.currentTime - 5);
    else if (k === "ArrowRight") v.currentTime += 5;
    else if (k === "Space") { if (v.paused) v.play(); else v.pause(); }
    else if (k === "KeyR" && C.cues.length) { v.currentTime = C.cues[at(v.currentTime)].start; v.play(); }
    else return;
    e.preventDefault();
    e.stopImmediatePropagation();
  };
  addEventListener("keydown", onKey, true);

  api(`/api/projects/${pid}/review-cues`).then((r) => {
    C = r;
    marks = r.marks || [];
    paintInbox(r.drive);
    if (!r.video) {
      left.textContent = "";
      left.appendChild(el("div", "rv-none",
        "모션 영상이 아직 없습니다 — «영상 렌더링» 화면에서 모션 영상(s12h)을 먼저 구우세요."));
      bExport.disabled = true;
    } else {
      v.src = `/api/projects/${pid}/file/${encodeURI(r.video)}`;
      if (r.stale) {
        left.appendChild(el("div", "rv-stale",
          "영상을 구운 뒤 덱이 바뀌었습니다 — 시각은 맞지만 문장 글은 지금 덱 기준일 수 있습니다."));
      }
    }
    draw();
  }).catch((e) => {
    left.textContent = "";
    left.appendChild(el("div", "rv-none", "읽지 못했습니다: " + e.message));
  });

  return {
    el: box,
    destroy() {
      v.pause();
      removeEventListener("keydown", onKey, true);
      box.remove();
    },
  };
}
