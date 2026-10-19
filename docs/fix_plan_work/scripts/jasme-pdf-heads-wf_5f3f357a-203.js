export const meta = {
  name: 'jasme-pdf-heads',
  description: '本誌の出版版 PDF 4 本の、ページの上下の行（ページ番号・柱など）を調べる',
  phases: [{ title: 'Read', detail: 'PDF ごとに 1 人' }],
}
const SCHEMA = {
  type: 'object',
  properties: {
    file: { type: 'string' },
    pages: { type: 'integer' },
    page_number_forms: { type: 'array', items: { type: 'string' }, description: 'ページ番号の行の書き方の実例（例: （77））と、ページの上か下か' },
    running_heads: { type: 'array', items: { type: 'string' }, description: '2 ページ目以降の各ページに繰り返し現れる、ページ番号以外の行（誌名・巻号・著者名・題目など）。実例そのまま。なければ空' },
    first_page_lines: { type: 'array', items: { type: 'string' }, description: '1 ページ目にだけある、本文でない行（誌名・巻号・ページ範囲・投稿受付日など）の実例' },
    other_page_lines: { type: 'array', items: { type: 'string' }, description: 'その他、本文の段落でない行で、ページの上下にあるもの（脚注線・受付日など）' },
    mid_paragraph_breaks: { type: 'array', items: { type: 'string' }, description: '段落の途中でページが変わる箇所の例（前の行の末尾 / ページの区切りの行 / 次の行の頭）を 3 つまで' },
    notes: { type: 'string', description: '照合に影響しそうなこと（2 段組の読み順の乱れ、図の中の文字、英文要旨のページの形、文字化けなど）' },
  },
  required: ['file', 'pages', 'page_number_forms', 'running_heads', 'first_page_lines', 'other_page_lines', 'mid_paragraph_breaks', 'notes'],
}
const results = await parallel(args.files.map(f => () => agent(`
Google Drive の PDF（fileId: ${f.id}、名前: ${f.name}）を、ToolSearch で mcp__Google_Drive__read_file_content を読み込んで呼び、文字として読んでください（ダウンロードはしない）。
これは学会誌『数学教育学研究』の出版版の論文 PDF です。論文 docx と PDF の文字を照合するツールのために、本文の段落ではない行
（ページ番号、柱＝各ページに繰り返し現れる誌名・巻号・著者名・題目、1 ページ目の誌名・巻号・ページ範囲、投稿受付日の行など）が、
どんな形でどこに現れるかを調べます。読み取り結果では、ページの区切りは "-----" と "Page N" の表で示されます。
各ページの区切りの直前・直後の行を必ず確かめ、実例をそのまま書き写してください（推測で書かない）。
本文の内容の要約は要りません。ファイルは変更しないでください。`, { label: f.name, phase: 'Read', schema: SCHEMA })))
return results.filter(Boolean)
