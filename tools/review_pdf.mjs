/* 검수지 HTML → PDF. `render/review.to_pdf()` 가 부른다.
 *
 *   node tools/review_pdf.mjs <in.html> <out.pdf>
 *
 * ★ **용지는 CSS 가 정한다**(`@page { size: A4 landscape }`) — 여기서 다시
 *   적으면 둘이 갈라진다. `preferCSSPageSize` 가 그 뜻이다.
 * ★ **레포 폴더에서 돌린다.** 다른 폴더에서 부르면 node 가 다른 playwright 를
 *   물어 「브라우저가 없다」고 한다(2026-09-22 실측 — 임시 폴더에서 그랬다).
 *   부르는 쪽(`to_pdf`)이 cwd 를 레포 뿌리로 준다. */
import { chromium } from "playwright";
import { pathToFileURL } from "node:url";

const [src, out] = process.argv.slice(2);
if (!src || !out) {
  console.error("사용: node tools/review_pdf.mjs <in.html> <out.pdf>");
  process.exit(2);
}
const browser = await chromium.launch();
try {
  const page = await browser.newPage();
  await page.goto(pathToFileURL(src).href, { waitUntil: "load" });
  await page.evaluate(() => document.fonts.ready);
  await page.pdf({ path: out, preferCSSPageSize: true, printBackground: true });
} finally {
  await browser.close();
}
