# ホロスコープ鑑定支援（公開・試験運用用）

このフォルダは Streamlit Community Cloud で試験公開するための、単独で動く一式です。
`ホロスコープ/jyotish_web/`（普段の開発・動作確認用）とは別の、公開専用コピーです。
（`jyotish_web/` 側を改良したときは、変更した箇所をこちらにも手動でコピーしてください）

## ローカルでの動作確認

```
cd ホロスコープ/jyotish_web_deploy
mkdir -p .streamlit
cp ../jyotish_web/.streamlit/secrets.toml .streamlit/secrets.toml
streamlit run app.py
```

（`.streamlit/secrets.toml` はGit管理対象外です。試験運用用の合言葉を使う場合は、
このファイルに `APP_PASSWORD = "好きな合言葉"` の行も追加してください）

## 公開の手順（試験運用）

### 1. GitHubに新しいリポジトリを作る

1. https://github.com/new を開く
2. リポジトリ名を決める（例：`jyotish-web`）
3. **Private** を選ぶ（他の人に中身を見られないように）
4. 「Create repository」を押す（README等は追加しなくてOK）

### 2. このフォルダの中身をGitHubへ送る

作った直後の画面に出てくる「…or push an existing repository from the command line」の
案内どおりに、ターミナルでこのフォルダに移動してから実行します
（`<あなたのURL>` の部分は、GitHubの画面に出ているものに置き換えてください）：

```
cd ホロスコープ/jyotish_web_deploy
git init
git add .
git commit -m "初回公開"
git branch -M main
git remote add origin <あなたのURL>
git push -u origin main
```

### 3. Streamlit Community Cloudでデプロイする

1. https://share.streamlit.io を開き、GitHubアカウントでログイン
2. 「New app」→ 先ほど作ったリポジトリを選択
3. Main file path に `app.py` を指定してデプロイ

### 4. Secrets（APIキー・合言葉）を設定する

デプロイ後、アプリの管理画面 →「Settings」→「Secrets」に、次の形式で貼り付けます
（`.streamlit/secrets.toml` と同じ書き方です）：

```
ANTHROPIC_API_KEY = "sk-ant-..."
APP_PASSWORD = "好きな合言葉"
```

保存すると自動で反映されます。`APP_PASSWORD` を設定した場合のみ、
アプリを開いたときに合言葉を聞かれるようになります（設定しなければ誰でも入れます）。

## 同梱しているファイルについて

- `career/` … 鑑定文の執筆ロジック・執筆プロンプト・象意辞典・文体メモ
  （元は `01_Claudeホロスコープ仕事案/`）
- `sheet/` … PDFワークシートの本文流し込み・綴じ処理・フォント
  （元は `02_jyotish_sheet/`）

どちらも公開用に複製（vendoring）したものです。元フォルダ側は今までどおり
仕事鑑定スキルの手元運用に使い続けられます。
