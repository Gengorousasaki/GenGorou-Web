# G3 -GenGorouGames- 公式サイト

https://gengorougames.com/

- `index.html` … トップページ
- `estimate/index.html` … 簡単お見積り
- `img/` … 画像（ゲーム画面、げんちゃん）
- `genchan.js` … トップの3Dげんちゃん（glTFをbase64化したもの）
- `content/〇〇.en.json` など … 英語(en)・中国語簡体字(zh)・韓国語(ko)の翻訳。管理画面で言語を切り替えて編集。空欄の所は日本語が出る
- 見積りページは日本語・英語のみ（`content/estimate.en.json` / `estimate-page.en.json`）。Googleフォームには英語ページからでも日本語の値で入る
- 自動翻訳：日本語を保存すると GitHub Actions（`.github/workflows/auto-translate.yml`）が空いている翻訳を埋める。中身は `tools/auto_translate.py`。キーは Secrets の `ANTHROPIC_API_KEY` か `DEEPL_API_KEY`。手で直した翻訳は、日本語が変わらない限り上書きしない
- 言語はトップ右上のメニューか `?lang=en` で切り替え（選んだ言語は記憶。初回はブラウザの言語）
- `CNAME` … 独自ドメインの設定（消さないこと）

GitHub Pages（main ブランチの / ）で公開。
