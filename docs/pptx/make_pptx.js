// Generates docs/pptx/Zotero-RAG.pptx — an illustrated walkthrough of
// Zotero-RAG. Run: node make_pptx.js
// Zotero-RAG.pdf next to it is exported from the deck with PowerPoint
// (File > Export > PDF) after regenerating.
const path = require("path");
const pptxgen = require("pptxgenjs");

const pptx = new pptxgen();
pptx.defineLayout({ name: "WIDE", width: 13.333, height: 7.5 });
pptx.layout = "WIDE";
pptx.author = "Zotero-RAG";
pptx.title = "Zotero-RAG: 文献管理・意味検索・引用ファクトチェック";

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
  markAi: "C9E8D8",
  markQuery: "FFE870",
  markFocus: "D5DEFA",
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

function down(slide, x, y, h) {
  slide.addShape(pptx.ShapeType.line, {
    x, y, w: 0, h, line: { color: C.blue, width: 2, endArrowType: "triangle" },
  });
}

// A card with a heading and a few lines of body text.
function card(slide, x, y, w, h, head, body, color) {
  slide.addShape(pptx.ShapeType.roundRect, {
    x, y, w, h, rectRadius: 0.1,
    fill: { color: C.card }, line: { color: C.line, width: 1 },
    shadow: { type: "outer", blur: 6, offset: 2, angle: 90, opacity: 0.14 },
  });
  slide.addShape(pptx.ShapeType.rect, {
    x, y: y + 0.18, w: 0.09, h: h - 0.36, fill: { color }, line: { color },
  });
  slide.addText(head, {
    x: x + 0.3, y: y + 0.14, w: w - 0.45, h: 0.45, fontFace: FONT,
    fontSize: 15, bold: true, color: C.ink, valign: "middle",
  });
  slide.addText(body, {
    x: x + 0.3, y: y + 0.6, w: w - 0.45, h: h - 0.72, fontFace: FONT,
    fontSize: 12, color: C.sub, valign: "top", lineSpacingMultiple: 1.2,
  });
}

function bullets(slide, x, y, w, h, head, items, color) {
  slide.addText(head, { x, y, w, h: 0.4, fontFace: FONT, fontSize: 16, bold: true, color });
  slide.addText(items.map(t => ({ text: t, options: { bullet: { code: "2022" } } })), {
    x, y: y + 0.45, w, h, fontFace: FONT, fontSize: 13, color: C.ink,
    lineSpacingMultiple: 1.25, valign: "top",
  });
}

function note(slide, text, y) {
  slide.addText(text, {
    x: 0.6, y, w: 12.1, h: 0.5, fontFace: FONT, fontSize: 13, italic: true, color: C.sub,
  });
}

// A table with a coloured header row.
function table(slide, x, y, colW, rows, opts = {}) {
  const head = rows[0].map(t => ({
    text: t, options: { bold: true, color: C.white, fill: { color: C.blueDk } },
  }));
  const body = rows.slice(1).map(r => r.map(t => ({ text: t, options: { color: C.ink } })));
  slide.addTable([head, ...body], {
    x, y, colW, w: colW.reduce((a, b) => a + b, 0),
    fontFace: FONT, fontSize: opts.fontSize || 12,
    border: { type: "solid", color: C.line, pt: 1 },
    fill: { color: C.card }, valign: "middle", rowH: opts.rowH || 0.42,
    margin: [0.04, 0.1, 0.04, 0.1],
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
s.addText("Zotero ライブラリを「意味」で扱う — 文献管理・意味検索・引用ファクトチェック", {
  x: 0.82, y: 3.3, w: 11.9, h: 0.7, fontFace: FONT, fontSize: 20, color: "C7D6F2",
});
s.addText("Local desktop app · Qwen3-Embedding + FAISS · English & 日本語", {
  x: 0.82, y: 4.0, w: 11.7, h: 0.5, fontFace: FONT, fontSize: 15, color: "9FB6E6",
});
const iconPath = path.join(__dirname, "..", "..", "assets", "icon.png");
s.addImage({ path: iconPath, x: 10.4, y: 0.5, w: 2.2, h: 2.2 });

// ===================================================================== //
// Slide 2 — What the app does
// ===================================================================== //
s = pptx.addSlide(); bgFill(s);
title(s, "What it does", "キーワードの一致ではなく、文章の意味で文献を探し、読み、確かめます。");
const features = [
  ["ライブラリ", "Zotero の文献 + 追加した PDF。\nフォルダ・タグ・お気に入りで絞り込み。", C.blueDk],
  ["文献ビューア", "抽出テキストと元の PDF を切り替え。\nAI 重要文と「探したい文」にマーカー。", C.green],
  ["意味検索", "ライブラリ全体から、質問に意味の近い\n一節を類似度順に表示（日英横断）。", C.blue],
  ["引用ファクトチェック", "原稿の引用を原文と照合。\n支持 / 一部支持 / 矛盾 / 文献なし。", C.red],
  ["関連グラフ", "引用関係と内容の類似を可視化。", C.amber],
  ["ダッシュボード・設定", "文献数と要確認の引用数。\nモデル・しきい値の設定。", C.sub],
];
features.forEach((f, i) => {
  const x = 0.6 + (i % 3) * 4.1, y = 1.85 + Math.floor(i / 3) * 2.1;
  card(s, x, y, 3.9, 1.85, f[0], f[1], f[2]);
});
note(s, "すべてこの Mac の中で動作します。Zotero のデータベースは読み取り専用です。", 6.35);

// ===================================================================== //
// Slide 3 — Architecture
// ===================================================================== //
s = pptx.addSlide(); bgFill(s);
title(s, "Architecture", "画面と CLI は Services だけを呼び、モデルと索引の組み合わせは Services が持ちます。");

chip(s, 0.6, 1.8, 12.1, 0.85, "GUI (PyQt6) — dashboard / library / document / search / factcheck / graph / settings", C.blueDk);
down(s, 6.66, 2.65, 0.35);
chip(s, 4.6, 3.0, 4.1, 0.75, "Services（窓口）", C.blue);
down(s, 6.66, 3.75, 0.35);

const mid = [
  ["Indexer", "同期・索引"], ["SearchEngine", "意味検索"],
  ["Highlighter", "AI マーカー"], ["FactChecker", "NLI で判定"], ["graph", "引用・類似"],
];
mid.forEach((m, i) => chip(s, 0.6 + i * 2.45, 4.1, 2.3, 1.0, m[0], C.green, m[1]));

const low = [
  ["Zotero / 追加 PDF", "ZoteroClient · LocalLibrary"],
  ["Embedder", "Qwen3-Embedding / E5"],
  ["VectorStore (FAISS)", "index.faiss · metadata.json"],
  ["LibraryDB (SQLite)", "一節の本文・フォルダ・履歴"],
];
low.forEach((m, i) => chip(s, 0.6 + i * 3.07, 5.5, 2.9, 1.0, m[0], C.sub, m[1]));
note(s, "重い処理は QThread で実行し、画面は固まりません。", 6.7);

// ===================================================================== //
// Slide 4 — Index build
// ===================================================================== //
s = pptx.addSlide(); bgFill(s);
title(s, "Building the index", "本文を文単位の「一節」に分け、一節ごとに潜在ベクトルへ変換して保存します。");

chip(s, 0.6, 2.0, 2.3, 1.2, "Zotero", C.blueDk, "API / 読み取り専用 DB");
arrow(s, 2.98, 2.5, 0.5);
chip(s, 3.56, 2.0, 2.3, 1.2, "本文", C.sub, "全文キャッシュ / PDF 抽出");
arrow(s, 5.94, 2.5, 0.5);
chip(s, 6.52, 2.0, 2.6, 1.2, "一節に分割", C.amber, "文単位 · 256 トークン以内");
arrow(s, 9.2, 2.5, 0.5);
chip(s, 9.78, 2.0, 2.95, 1.2, "Embedding", C.green, "Qwen3-Embedding 4B / 0.6B");

down(s, 11.25, 3.2, 0.7);
down(s, 7.82, 3.2, 0.7);
chip(s, 9.78, 3.95, 2.95, 1.2, "FAISS (index.faiss)", C.blue, "正規化ベクトル = コサイン類似度");
chip(s, 6.2, 3.95, 3.25, 1.2, "library.db", C.sub, "一節の本文 · 開始ページ");

bullets(s, 0.6, 3.75, 5.3, 1.5, "一節の作り方", [
  "一節どうしは重ならない",
  "PDF の開始ページを記録",
  "参考文献リストは検索対象から外す",
], C.amber);

s.addText([
  { text: "実測（101 文献）  ", options: { bold: true, color: C.ink } },
  { text: "8,818 一節。4B で約 1 時間、0.6B で約 12 分（ダウンロード込み）。25 文献ごとに保存するので、途中で終了してもそこまでの分は残ります。", options: { color: C.sub } },
], { x: 0.6, y: 5.75, w: 12.1, h: 0.9, fontFace: FONT, fontSize: 14 });

// ===================================================================== //
// Slide 5 — Embedding model and the first-run choice
// ===================================================================== //
s = pptx.addSlide(); bgFill(s);
title(s, "Embedding model", "初回起動時に 4B か 0.6B を選びます。あとから設定画面で変更できます。");

table(s, 0.6, 1.85, [3.9, 1.2, 1.7, 1.6, 3.7], [
  ["モデル", "次元", "ダウンロード", "しきい値", "位置づけ"],
  ["Qwen/Qwen3-Embedding-4B", "2560", "約 8 GB", "0.45", "高精度（既定）· メモリ 16 GB 以上を推奨"],
  ["Qwen/Qwen3-Embedding-0.6B", "1024", "約 1.2 GB", "0.45", "軽量 · 索引が速い"],
  ["intfloat/multilingual-e5-large", "1024", "約 2.1 GB", "0.78", "従来の既定（設定画面で選択可）"],
]);

card(s, 0.6, 3.85, 5.9, 2.35, "初回起動時の選択",
  "メインウィンドウの前にダイアログを表示。\nメモリ 16 GB 以上なら 4B、未満なら 0.6B が選択済み。\n閉じると何もダウンロードせず、次回もう一度聞く。\nすでに索引がある環境では聞かない。", C.green);
card(s, 6.8, 3.85, 5.9, 2.35, "モデルを変えると",
  "再起動後に新しいモデルへ切り替え。\n索引は作成時のモデル名を記録しているので、\n次の同期で全文献を埋め込み直す。\nしきい値も新しいモデルの既定値に戻る。", C.amber);
note(s, "いずれも無料。Hugging Face からのみ取得し、ダウンロード後はオフラインで動作します。", 6.45);

// ===================================================================== //
// Slide 6 — Semantic search
// ===================================================================== //
s = pptx.addSlide(); bgFill(s);
title(s, "Semantic search", "質問文を同じモデルでベクトルにし、コサイン類似度の高い一節から表示します。");

chip(s, 0.6, 2.1, 3.0, 1.0, "「自己教師あり学習」", C.blue, "質問文（日本語でも英語でも）");
arrow(s, 3.7, 2.42, 0.7);
chip(s, 4.55, 2.1, 2.3, 1.0, "Embedding", C.green, "検索用の指示文を付加");
arrow(s, 6.95, 2.42, 0.7);
chip(s, 7.8, 2.1, 2.4, 1.0, "質問ベクトル", C.blueDk, "2560 次元（4B）");

s.addText("cosine similarity", { x: 9.7, y: 3.4, w: 3, h: 0.3, fontFace: FONT, fontSize: 12, italic: true, color: C.sub });
const cx = 10.9, cy = 5.0, r = 1.2;
// A vector from (cx, cy) up and to the right. PowerPoint rejects a negative
// height, so the box is given upright and the line is flipped inside it.
function vector(dx, dy, color, width) {
  s.addShape(pptx.ShapeType.line, { x: cx, y: cy - dy, w: dx, h: dy, flipV: true,
    line: { color, width, endArrowType: "triangle" } });
}
vector(r, r * 0.2, C.blueDk, 3);
s.addText("q", { x: cx + r, y: cy - r * 0.2 - 0.3, w: 0.4, h: 0.3, color: C.blueDk, bold: true, fontFace: FONT, fontSize: 13 });
const docs = [[r * 0.95, -r * 0.45, C.green, "0.83"], [r * 0.8, -r * 0.75, C.amber, "0.58"], [r * 0.5, -r * 1.1, C.red, "0.36"]];
docs.forEach(d => {
  vector(d[0], -d[1], d[2], 2);
  s.addText(d[3], { x: cx + d[0], y: cy + d[1] - 0.25, w: 0.6, h: 0.3, color: d[2], bold: true, fontFace: FONT, fontSize: 11 });
});

s.addText("一節単位の結果（しきい値 0.45 以上）", { x: 0.6, y: 3.5, w: 6, h: 0.4, fontFace: FONT, fontSize: 16, bold: true, color: C.ink });
const rows = [["0.83", "A Survey on Contrastive Self-Supervised Learning の一節", C.green],
              ["0.58", "関連する別の文献の一節", C.amber],
              ["0.36", "（しきい値未満 — 表示しない）", C.red]];
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
note(s, "結果をクリックすると、文献ビューアのその一節へ移動します。50,000 ベクトル以上では IVF 索引に自動で切り替わります。", 6.45);

// ===================================================================== //
// Slide 7 — Document viewer and markers
// ===================================================================== //
s = pptx.addSlide(); bgFill(s);
title(s, "Document viewer & markers", "抽出テキストでも元の PDF でも、同じマーカーを表示します。ボタンで切り替え。");

// a mock page with markers
s.addShape(pptx.ShapeType.rect, { x: 0.6, y: 1.85, w: 4.6, h: 4.75, fill: { color: C.white }, line: { color: C.line, width: 1 },
  shadow: { type: "outer", blur: 6, offset: 2, angle: 90, opacity: 0.18 } });
s.addShape(pptx.ShapeType.roundRect, { x: 0.85, y: 2.0, w: 0.95, h: 0.3, rectRadius: 0.1, fill: { color: C.card }, line: { color: C.line, width: 1 } });
s.addText("テキスト", { x: 0.85, y: 2.0, w: 0.95, h: 0.3, align: "center", valign: "middle", fontFace: FONT, fontSize: 9, color: C.ink });
s.addShape(pptx.ShapeType.roundRect, { x: 1.9, y: 2.0, w: 0.7, h: 0.3, rectRadius: 0.1, fill: { color: C.blueDk }, line: { color: C.blueDk } });
s.addText("PDF", { x: 1.9, y: 2.0, w: 0.7, h: 0.3, align: "center", valign: "middle", fontFace: FONT, fontSize: 9, bold: true, color: C.white });
const lines = [null, null, C.markAi, C.markAi, null, null, C.markQuery, null, null, C.markFocus, C.markFocus, null, null];
lines.forEach((mark, i) => {
  const yy = 2.55 + i * 0.3, w = i % 4 === 3 ? 2.9 : 4.1;
  if (mark) s.addShape(pptx.ShapeType.rect, { x: 0.82, y: yy - 0.07, w: w + 0.06, h: 0.24, fill: { color: mark }, line: { color: mark } });
  s.addShape(pptx.ShapeType.rect, { x: 0.85, y: yy, w, h: 0.1, fill: { color: "B9BEC7" }, line: { color: "B9BEC7" } });
});

table(s, 5.6, 1.85, [1.9, 1.0, 4.2], [
  ["マーカー", "色", "選び方"],
  ["AI 重要文", "緑", "文献の重心ベクトルに近い一節から 1 文ずつ（既定 5 文）"],
  ["探したい文", "黄", "入力した文に意味の近い一節"],
  ["開いた一節", "薄い青", "意味検索の結果などから開いた箇所"],
], { rowH: 0.5 });

bullets(s, 5.6, 4.15, 7.1, 2.0, "PDF 表示の仕組み", [
  "PyQt6 同梱の QtPdf で描画（追加の依存なし）",
  "マーカーの文を PDF のテキスト層から探して位置を決定",
  "実測: 100 文献・782 文のうち 780 文（99.7%）を特定",
  "スキャン PDF（テキスト層なし）はマーカーなしで表示",
], C.green);

// ===================================================================== //
// Slide 8 — Citation fact-check
// ===================================================================== //
s = pptx.addSlide(); bgFill(s);
title(s, "Citation fact-check", "原稿の (著者, 年) 引用ごとに、引用先の原文が主張を支持しているかを判定します。");

chip(s, 0.6, 1.95, 2.75, 1.15, "1  引用を抽出", C.blueDk, "(著者, 年) / 著者 (年)");
arrow(s, 3.42, 2.4, 0.5);
chip(s, 4.0, 1.95, 2.75, 1.15, "2  文献を照合", C.sub, "著者の姓 + 年");
arrow(s, 6.82, 2.4, 0.5);
chip(s, 7.4, 1.95, 2.55, 1.15, "3  一節を取得", C.amber, "主張に近い 4 件");
arrow(s, 10.02, 2.4, 0.5);
chip(s, 10.6, 1.95, 2.1, 1.15, "4  NLI で判定", C.green, "含意 / 矛盾");

table(s, 0.6, 3.5, [2.0, 10.1], [
  ["判定", "条件"],
  ["支持", "どれかの一節が主張を含意し、候補全体としては矛盾していない"],
  ["矛盾", "候補の矛盾スコアの中央値がしきい値以上で、含意する一節がない"],
  ["一部支持", "上のどちらでもない（信号が食い違う場合を含む）"],
  ["文献なし", "著者と年に合う文献がライブラリにない"],
]);
note(s, "NLI モデルはローカルで実行（mDeBERTa-v3、約 560 MB）。判定は目安で、根拠の一文と原文で最終確認します。", 6.3);

// ===================================================================== //
// Slide 9 — Sync and folders
// ===================================================================== //
s = pptx.addSlide(); bgFill(s);
title(s, "Sync with Zotero & folders", "起動時・ボタン・5 分ごとに Zotero を確認し、変わった文献だけを処理します。");

chip(s, 0.6, 1.95, 2.8, 1.1, "現在の一覧を取得", C.blueDk, "key + dateModified");
arrow(s, 3.5, 2.37, 0.7);
chip(s, 4.35, 1.95, 3.0, 1.1, "索引と比較", C.amber, "新規 / 変更 / 削除");
arrow(s, 7.45, 2.37, 0.7);
chip(s, 8.3, 1.95, 4.4, 1.1, "差分だけ埋め込み直す", C.green, "変更のない文献は何もしない");

s.addText([
  { text: "新規", options: { bold: true, color: C.green } },
  { text: " → 追加　　", options: { color: C.sub } },
  { text: "変更あり", options: { bold: true, color: C.amber } },
  { text: " → 置き換え　　", options: { color: C.sub } },
  { text: "削除", options: { bold: true, color: C.red } },
  { text: " → 索引から除く　　", options: { color: C.sub } },
  { text: "半分超が消えた", options: { bold: true, color: C.blueDk } },
  { text: " → 同期を中止（索引を守る）", options: { color: C.sub } },
], { x: 0.6, y: 3.3, w: 12.1, h: 0.5, fontFace: FONT, fontSize: 14 });

card(s, 0.6, 4.1, 5.9, 2.1, "Zotero コレクション",
  "入れ子も含めて、同期のたびにアプリへ写す。\n親を選ぶとサブコレクションの文献も表示。\n編集は Zotero 側のみ（アプリでは読み取り専用）。", C.blueDk);
card(s, 6.8, 4.1, 5.9, 2.1, "マイフォルダ",
  "アプリ内だけのフォルダ。作成・名前変更・削除が可能。\n1 つの文献を複数のフォルダに入れられる。\nZotero 側には書き込まない。", C.green);
note(s, "自動同期の間隔は config.json の auto_sync_minutes（0 で停止）。", 6.45);

// ===================================================================== //
// Slide 10 — Relation graph, design choices, security
// ===================================================================== //
s = pptx.addSlide(); bgFill(s);
title(s, "Relation graph · security", "引用と類似の 2 種類の関係、そしてローカル完結・読み取り専用の安全設計。");

bullets(s, 0.6, 1.8, 5.9, 1.6, "関連グラフ", [
  "引用（実線の矢印）: B のタイトルが A の本文に現れる",
  "類似（破線）: 平均ベクトルが互いに近傍 3 件に入る",
  "Zotero は引用関係を持たないため本文から検出",
], C.amber);
bullets(s, 0.6, 4.2, 5.9, 1.6, "検索の設計", [
  "FAISS の内積 = 正規化ベクトルのコサイン類似度",
  "50,000 ベクトル未満は厳密検索、以上は IVF に自動切替",
  "Apple MPS / CUDA / CPU を自動判定",
], C.green);
bullets(s, 6.8, 1.8, 5.9, 3.2, "セキュリティ", [
  "Zotero は読み取り専用（DB をコピーして読む）",
  "文献や原稿を外部に送信しない",
  "外向きの通信はモデルの初回ダウンロードのみ",
  "認証情報や秘密情報を保存しない",
  "SQL はパラメータ化。入力は実行しない",
  "仮想環境で依存を隔離",
], C.red);

// ===================================================================== //
// Slide 11 — How to run
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

s.addText("初回起動: Embedding モデルを選ぶ → モデルをダウンロード → ライブラリ全体を索引。" +
  "2 回目以降は新着分だけを同期します。", {
  x: 0.6, y: 4.4, w: 12.1, h: 0.6, fontFace: FONT, fontSize: 14, color: C.sub });
s.addText("CLI:  app.py --status  |  --sync  |  --search \"…\"  |  --factcheck draft.txt", {
  x: 0.6, y: 4.95, w: 12.1, h: 0.4, fontFace: "Courier New", fontSize: 13, color: C.ink });

s.addImage({ path: iconPath, x: 5.87, y: 5.55, w: 1.6, h: 1.6 });

// ---- save ----
const out = path.join(__dirname, "Zotero-RAG.pptx");
pptx.writeFile({ fileName: out }).then(() => {
  console.log("wrote " + out);
});
