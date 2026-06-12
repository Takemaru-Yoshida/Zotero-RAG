// Generates docs/pptx/Zotero-RAG.pptx — an illustrated walkthrough of the
// Zotero-RAG pipeline. Run: node make_pptx.js
const path = require("path");
const pptxgen = require("pptxgenjs");

const pptx = new pptxgen();
pptx.defineLayout({ name: "WIDE", width: 13.333, height: 7.5 });
pptx.layout = "WIDE";
pptx.author = "Zotero-RAG";
pptx.title = "Zotero-RAG: Semantic Search for Your Library";

// ---- palette ----
const C = {
  bg: "F5F6F8",
  ink: "1C1E21",
  sub: "5A5F66",
  blue: "3B6FD4",
  blueDk: "1F3A78",
  green: "2E9E5B",
  amber: "F5A623",
  red: "E0556B",
  white: "FFFFFF",
  card: "FFFFFF",
  line: "C7D0DD",
};
const FONT = "Helvetica Neue";

function bgFill(slide) { slide.background = { color: C.bg }; }

function title(slide, text, sub) {
  slide.addText(text, {
    x: 0.6, y: 0.35, w: 12.1, h: 0.8, fontFace: FONT,
    fontSize: 30, bold: true, color: C.blueDk,
  });
  if (sub) slide.addText(sub, {
    x: 0.62, y: 1.05, w: 12.1, h: 0.5, fontFace: FONT,
    fontSize: 15, color: C.sub,
  });
}

function chip(slide, x, y, w, h, label, color, sub) {
  slide.addShape(pptx.ShapeType.roundRect, {
    x, y, w, h, rectRadius: 0.12,
    fill: { color: C.card }, line: { color, width: 2 },
    shadow: { type: "outer", blur: 6, offset: 2, angle: 90, opacity: 0.18 },
  });
  slide.addText(label, {
    x: x + 0.1, y: y + 0.12, w: w - 0.2, h: sub ? h - 0.5 : h - 0.24,
    align: "center", valign: "middle", fontFace: FONT, fontSize: 14,
    bold: true, color: C.ink,
  });
  if (sub) slide.addText(sub, {
    x: x + 0.1, y: y + h - 0.5, w: w - 0.2, h: 0.4,
    align: "center", valign: "middle", fontFace: FONT, fontSize: 10,
    color: C.sub,
  });
}

function arrow(slide, x, y, w) {
  slide.addShape(pptx.ShapeType.rightArrow, {
    x, y, w, h: 0.28, fill: { color: C.blue }, line: { color: C.blue },
  });
}

// ===================================================================== //
// Slide 1 — Title
// ===================================================================== //
let s = pptx.addSlide();
s.background = { color: C.blueDk };
s.addShape(pptx.ShapeType.rect, { x: 0, y: 6.2, w: 13.333, h: 1.3, fill: { color: C.blue } });
s.addText("Zotero-RAG", {
  x: 0.8, y: 2.1, w: 11.7, h: 1.2, fontFace: FONT, fontSize: 54, bold: true, color: C.white,
});
s.addText("Search your Zotero library by meaning — English & 日本語", {
  x: 0.82, y: 3.3, w: 11.7, h: 0.7, fontFace: FONT, fontSize: 22, color: "C7D6F2",
});
s.addText("Retrieval-Augmented semantic search powered by multilingual-e5-large + FAISS", {
  x: 0.82, y: 4.0, w: 11.7, h: 0.5, fontFace: FONT, fontSize: 15, color: "9FB6E6",
});
const iconPath = path.join(__dirname, "..", "..", "assets", "icon.png");
s.addImage({ path: iconPath, x: 10.4, y: 0.5, w: 2.2, h: 2.2 });

// ===================================================================== //
// Slide 2 — Overview: two phases
// ===================================================================== //
s = pptx.addSlide(); bgFill(s);
title(s, "Two phases", "初回起動時にインデックスを構築（1–4）。毎回の検索で問い合わせ（5–7）。");

s.addText("Phase A — Index build (first launch & on new papers)", {
  x: 0.6, y: 1.7, w: 12, h: 0.4, fontFace: FONT, fontSize: 16, bold: true, color: C.green,
});
const ax = [0.6, 3.55, 6.5, 9.45];
const aLabels = [
  ["1·2  Connect & extract", "Zotero API / DB"],
  ["3  Embed full text", "multilingual-e5-large"],
  ["4  Store vectors", "FAISS index on disk"],
  ["↻  Incremental sync", "dateModified check"],
];
aLabels.forEach((l, i) => {
  chip(s, ax[i], 2.2, 2.65, 1.1, l[0], C.green, l[1]);
  if (i < 3) arrow(s, ax[i] + 2.7, 2.62, 0.75);
});

s.addText("Phase B — Query (every search)", {
  x: 0.6, y: 4.1, w: 12, h: 0.4, fontFace: FONT, fontSize: 16, bold: true, color: C.blue,
});
const bLabels = [
  ["5  Embed query", "same model + 'query:'"],
  ["6  Cosine similarity", "vs stored vectors"],
  ["7  Rank & display", "top-K + threshold"],
];
const bx = [0.6, 4.0, 7.4];
bLabels.forEach((l, i) => {
  chip(s, bx[i], 4.6, 3.0, 1.1, l[0], C.blue, l[1]);
  if (i < 2) arrow(s, bx[i] + 3.05, 5.02, 0.85);
});
s.addText("Same embedding model in step 3 and step 5 — this is what makes the vectors comparable.", {
  x: 0.6, y: 6.4, w: 12, h: 0.5, fontFace: FONT, fontSize: 13, italic: true, color: C.sub,
});

// ===================================================================== //
// Slide 3 — Index build detail
// ===================================================================== //
s = pptx.addSlide(); bgFill(s);
title(s, "Phase A · Building the index", "各論文の本文をチャンク化し、潜在ベクトルへ変換して保存します。");

chip(s, 0.6, 2.0, 2.4, 1.2, "Zotero", C.blueDk, "API or read-only DB");
arrow(s, 3.1, 2.5, 0.6);
chip(s, 3.85, 2.0, 2.6, 1.2, "Paper full text", C.sub, "title + abstract + body");
arrow(s, 6.55, 2.5, 0.6);
chip(s, 7.3, 2.0, 2.5, 1.2, "Chunking", C.amber, "512-token windows, overlap");
arrow(s, 9.9, 2.5, 0.6);
chip(s, 10.65, 2.0, 2.1, 1.2, "e5-large", C.green, "passage: …");

// vectors -> faiss
s.addShape(pptx.ShapeType.line, { x: 11.7, y: 3.2, w: 0, h: 0.7, line: { color: C.blue, width: 2, endArrowType: "triangle" } });
chip(s, 9.6, 3.95, 3.15, 1.2, "FAISS index (.faiss)", C.blue, "L2-normalised vectors = cosine");
chip(s, 5.9, 3.95, 3.15, 1.2, "metadata.json", C.sub, "title · authors · dateModified");

s.addText([
  { text: "Why chunking?  ", options: { bold: true, color: C.ink } },
  { text: "Papers are long; a relevant passage anywhere should match. Each chunk is embedded separately and a paper's score is the best (max) chunk similarity.", options: { color: C.sub } },
], { x: 0.6, y: 5.5, w: 12.1, h: 1.0, fontFace: FONT, fontSize: 14 });

// ===================================================================== //
// Slide 4 — Query detail with similarity illustration
// ===================================================================== //
s = pptx.addSlide(); bgFill(s);
title(s, "Phase B · Answering a query", "問い合わせ文を同じモデルでベクトル化し、コサイン類似度で並べ替えます。");

chip(s, 0.6, 2.1, 3.0, 1.0, '"contrastive learning"', C.blue, "query text");
arrow(s, 3.7, 2.42, 0.7);
chip(s, 4.55, 2.1, 2.3, 1.0, "e5-large", C.green, "query: …");
arrow(s, 6.95, 2.42, 0.7);
chip(s, 7.8, 2.1, 2.4, 1.0, "query vector", C.blueDk, "1024-dim");

// similarity diagram
s.addText("cosine similarity", { x: 9.7, y: 3.4, w: 3, h: 0.3, fontFace: FONT, fontSize: 12, italic: true, color: C.sub });
const cx = 10.9, cy = 5.0, r = 1.2;
s.addShape(pptx.ShapeType.line, { x: cx, y: cy, w: r, h: -r * 0.2, line: { color: C.blueDk, width: 3, endArrowType: "triangle" } });
s.addText("q", { x: cx + r, y: cy - r * 0.2 - 0.3, w: 0.4, h: 0.3, color: C.blueDk, bold: true, fontFace: FONT, fontSize: 13 });
const docs = [[r * 0.95, -r * 0.45, C.green, "0.86"], [r * 0.8, -r * 0.75, C.amber, "0.71"], [r * 0.5, -r * 1.1, C.red, "0.42"]];
docs.forEach(d => {
  s.addShape(pptx.ShapeType.line, { x: cx, y: cy, w: d[0], h: d[1], line: { color: d[2], width: 2, endArrowType: "triangle" } });
  s.addText(d[3], { x: cx + d[0], y: cy + d[1] - 0.25, w: 0.6, h: 0.3, color: d[2], bold: true, fontFace: FONT, fontSize: 11 });
});

// ranked list
s.addText("Ranked results (≥ threshold)", { x: 0.6, y: 3.5, w: 6, h: 0.4, fontFace: FONT, fontSize: 16, bold: true, color: C.ink });
const rows = [["0.86", "A Survey on Contrastive Self-Supervised Learning", C.green],
              ["0.71", "Understanding Contrastive Representation Learning", C.amber],
              ["0.42", "(below threshold — hidden)", C.red]];
rows.forEach((row, i) => {
  const yy = 4.0 + i * 0.75;
  const dim = i === 2;
  s.addShape(pptx.ShapeType.roundRect, { x: 0.6, y: yy, w: 8.6, h: 0.62, rectRadius: 0.08,
    fill: { color: dim ? "ECEEF1" : C.card }, line: { color: C.line, width: 1 } });
  s.addText(row[0], { x: 0.75, y: yy + 0.06, w: 0.85, h: 0.5, align: "center", valign: "middle",
    fontFace: FONT, fontSize: 13, bold: true, color: C.white, fill: { color: row[2] } });
  s.addText(row[1], { x: 1.8, y: yy, w: 7.3, h: 0.62, valign: "middle", fontFace: FONT,
    fontSize: 13, color: dim ? C.sub : C.ink, italic: dim });
});

// ===================================================================== //
// Slide 5 — Incremental sync
// ===================================================================== //
s = pptx.addSlide(); bgFill(s);
title(s, "Keeping in sync with Zotero", "起動時・検索時・更新時に、新しい論文が無いか確認し、必要分だけ再処理します。");

chip(s, 0.6, 2.2, 2.8, 1.1, "Fetch current items", C.blueDk, "keys + dateModified");
arrow(s, 3.5, 2.62, 0.7);
chip(s, 4.35, 2.2, 3.0, 1.1, "Compare to index", C.amber, "new / changed / removed");
arrow(s, 7.45, 2.62, 0.7);
chip(s, 8.3, 2.2, 4.4, 1.1, "Re-embed only the delta", C.green, "steps 2–4 for changed papers");

s.addText([
  { text: "New paper", options: { bold: true, color: C.green } },
  { text: "  → embed & add.    ", options: { color: C.sub } },
  { text: "Changed (dateModified differs)", options: { bold: true, color: C.amber } },
  { text: "  → re-embed & replace.    ", options: { color: C.sub } },
  { text: "Removed from Zotero", options: { bold: true, color: C.red } },
  { text: "  → drop from index.", options: { color: C.sub } },
], { x: 0.6, y: 3.8, w: 12.1, h: 1.2, fontFace: FONT, fontSize: 14, lineSpacingMultiple: 1.3 });

s.addText("Unchanged papers are skipped, so re-syncs are fast even for large libraries.", {
  x: 0.6, y: 5.2, w: 12, h: 0.5, fontFace: FONT, fontSize: 14, italic: true, color: C.sub,
});

// ===================================================================== //
// Slide 6 — Design choices & security
// ===================================================================== //
s = pptx.addSlide(); bgFill(s);
title(s, "Design choices & security", "無料・軽量・多言語のモデル選定と、ローカル完結・読み取り専用の安全設計。");

function bullets(x, y, w, head, items, color) {
  s.addText(head, { x, y, w, h: 0.4, fontFace: FONT, fontSize: 16, bold: true, color });
  s.addText(items.map(t => ({ text: t, options: { bullet: { code: "2022" } } })), {
    x, y: y + 0.45, w, h: 2.6, fontFace: FONT, fontSize: 13, color: C.ink,
    lineSpacingMultiple: 1.25, valign: "top",
  });
}
bullets(0.6, 1.8, 5.9, "Model & retrieval", [
  "multilingual-e5-large — free, ~1.1 GB, EN+JA, offline",
  "Downloaded from Hugging Face Hub only",
  "FAISS inner-product = cosine similarity",
  "Auto IVF (ANN) index above ~4k chunks for speed",
  "Apple MPS / CUDA / CPU auto-detected",
], C.green);
bullets(6.8, 1.8, 5.9, "Security", [
  "Read-only: copies zotero.sqlite, never writes",
  "Local-only; sole network call is the model download",
  "No secrets/credentials stored",
  "Parameterised SQL; query text never executed",
  "Virtual environment isolates dependencies",
], C.red);

// ===================================================================== //
// Slide 7 — How to run
// ===================================================================== //
s = pptx.addSlide(); bgFill(s);
title(s, "Running the app", "仮想環境を作成し、アイコンから起動できる .app を生成します。");

s.addShape(pptx.ShapeType.roundRect, { x: 0.6, y: 1.8, w: 12.1, h: 2.4, rectRadius: 0.1,
  fill: { color: "11151C" }, line: { color: "11151C" } });
s.addText([
  { text: "# one-time setup\n", options: { color: "7FD08A" } },
  { text: "python3 -m venv venv\n", options: { color: "E6E6E6" } },
  { text: "venv/bin/pip install -r requirements.txt\n", options: { color: "E6E6E6" } },
  { text: "venv/bin/python scripts/make_icon.py\n", options: { color: "E6E6E6" } },
  { text: "bash scripts/build_app.sh\n\n", options: { color: "E6E6E6" } },
  { text: "# launch\n", options: { color: "7FD08A" } },
  { text: "open Zotero-RAG.app", options: { color: "9FD0FF" } },
], { x: 0.9, y: 2.0, w: 11.5, h: 2.0, fontFace: "Courier New", fontSize: 15, lineSpacingMultiple: 1.15 });

s.addText("Double-click Zotero-RAG.app in Finder to launch the GUI. " +
  "First run downloads the model and builds the index; later runs only sync new papers.", {
  x: 0.6, y: 4.5, w: 12.1, h: 0.8, fontFace: FONT, fontSize: 14, color: C.sub });

s.addImage({ path: iconPath, x: 5.7, y: 5.3, w: 1.6, h: 1.6 });

// ---- save ----
const out = path.join(__dirname, "Zotero-RAG.pptx");
pptx.writeFile({ fileName: out }).then(() => {
  console.log("wrote " + out);
});
