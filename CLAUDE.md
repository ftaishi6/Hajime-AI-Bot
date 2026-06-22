# Hajime-AI-Bot

「**はじめの一歩 AI 塾**」(古谷太嗣 主宰、東大阪・有限会社古谷商店)の
X / Threads / Instagram 用 投稿案 生成・配信 Bot。

## プロジェクト概要

| 項目 | 内容 |
|---|---|
| 目的 | AI 塾事業の認知拡大 + 集客動線(@hajime_ai_juku の 3 媒体で発信) |
| アカウント主 | 古谷太嗣(同じ人だが、リサイクル本業の @ftaishi6 とは別文脈) |
| 立場 | エンジニアじゃない中小経営者 / 「俺でもできた」を伝える講師 |
| 投稿頻度 | キュレーション(毎朝)+ 基礎用語(毎日 1 単語)+ バズ案(週 1) |
| 投稿手段 | Discord に案 → 古谷さんが X / Threads / IG に手動投稿(半自動) |
| ホスティング | ConoHa VPS(既存 Xapp と同居、別 systemd service) |
| 想定月額コスト | 約 $1〜3(Claude + X API、VPS は Xapp と按分) |

## アカウント主・古谷太嗣について(AI 塾講師としての顔)

リサイクル本業(ftaishi6/Xapp)の古谷さんと **同一人物だが文脈が違う**。
本リポでの発信は **AI 塾講師としての顔** に振る。

### 基本情報

- 29 歳、有限会社古谷商店 取締役
- 家業は曽祖父創業の金属リサイクル業(操業 75 年、東大阪・衣摺)
- 約 6 年前から ケミカルリサイクル開発(リサイクル本業の側で発信)
- **AI 内製の実績**(これが本リポの発信源):
  - 金属盗対策法施行当日の届出完了・身分証確認 AI(業界誌掲載)
  - 現場日報 / 運転日報のデジタル化システム
  - 金属相場価格表 Web ビューワー
- すべて **Claude Code で内製、エンジニアを社内に持たないまま実用化**
- 2026 年 7 月 4 日 体験会開始予定(東大阪市衣摺の事務所、対面、6 名)

### AI 塾講師としてのスタンス

- 「**俺でもできた、地域の経営者もできるようになって地域を活況に**」
- 化学・工学だけでなく、AI も「専門家ではない」立場
- 失敗談・つまずきを正直に出す(完璧な成功者像にしない)
- 「同じ立場の中小経営者」「内製の現場感」がフックワード

## ペルソナ・文体ルール

詳細は `prompts/persona.yaml` の `system_prompt` 参照。要約:

- 一人称は「僕」
- 「エンジニアじゃないけど」「専門家じゃないけど」を恥じずに使う
- 「あなたも」より「同じ立場の」「俺でもできた」
- 文末は「〜と思います」基本、断定しない
- 各媒体の文字数を守る(X = 140、Threads = 500、IG = 200-400)

### 禁止事項

- 誇張・断言・煽り表現
- 特定企業・個人への批判
- 政治的に偏った表現
- 化学の細部断定(化学はリサイクル本業側、本リポでは AI 中心)
- 「AI で何でもできる」過信を煽る表現

## システム構成

```
ConoHa VPS (既存 Xapp と同居)
└── hajime-ai-bot.service (新規 systemd service)
    ├── discord.py 常駐 Bot(Bot Application「Hajime AI Juku」)
    ├── APScheduler:
    │   ├─ daily 07:00 JST  キュレーション digest    → #hajime-curation
    │   ├─ daily 12:00 JST  基礎用語 1 単語          → #hajime-basics
    │   └─ weekly 月曜 09:30 バズ案(将来追加)        → #hajime-buzz
    └── SQLite (/opt/hajime-ai-bot/hajime.db)
        ├─ watch_accounts
        ├─ basics_history
        └─ curation_history(将来)
```

## ディレクトリ構成

```
Hajime-AI-Bot/
├── README.md
├── CLAUDE.md              # 本ファイル
├── .env.template
├── .gitignore
├── requirements.txt
├── config.yaml            # watchlist + 各機能閾値
├── prompts/
│   └── persona.yaml       # AI 塾講師ペルソナ + 各機能プロンプト + 34 語カタログ
├── bot/
│   ├── __init__.py
│   ├── main.py            # エントリポイント、/ping /health
│   ├── db.py
│   ├── scheduler.py       # Phase 3 で実装
│   ├── features/          # Phase 3 で curation/ basics/ など追加
│   └── migrations/
│       └── 001_initial.sql
├── deploy/
│   └── hajime-ai-bot.service
└── .github/workflows/
    └── deploy.yml
```

## VPS 配置(完成形)

```
/opt/hajime-ai-bot/
├── repo/                   # git clone https://github.com/ftaishi6/Hajime-AI-Bot.git
├── venv/                   # Python 3.12 venv
├── .env                    # secrets(コミットしない)
└── hajime.db               # SQLite
```

systemd unit(`/etc/systemd/system/hajime-ai-bot.service`)は
`/opt/hajime-ai-bot/repo/deploy/hajime-ai-bot.service` から symlink。

## 関連プロジェクト

- [ftaishi6/Xapp](https://github.com/ftaishi6/Xapp) — リサイクル本業 Bot(縮小運用中)
- 既存メモリ: `xapp_sns_editor_w2_progress.md`(リサイクル版運用状況)

## Claude Code への作業指示

### コーディング時の方針

- ペルソナの **文体ルール** に厳密に従う(誇張・断定を避ける)
- `prompts/persona.yaml` を **編集してプロンプトを変える**(コード変更最小)
- 文字数制約は各機能で厳格に(X 140 / Threads 500 / IG 200-400)
- セキュリティ:
  - Bot Token・API キーは会話に出さない、`.env` のみで管理
  - `.env` は `.gitignore` 済み

### 実装フェーズ

- **Phase 1**(完了)アカウント / Discord Bot / GitHub リポ / watchlist 確定
- **Phase 2**(本リポ初期)最小骨組み(/ping /health)+ VPS デプロイ
- **Phase 3-A**(次セッション)キュレーション機能(W2-C 拡張)
- **Phase 3-B**(次セッション)基礎用語解説機能(34 語ループ)
- **Phase 4**(将来)バズ案・自社事例・AI 塾告知の追加

### 開発ルール

- 完全自動投稿はしない(半自動原則を維持、Discord 案 → 古谷さん手動投稿)
- スクレイピング前に robots.txt 確認(本リポでは X API のみ、スクレイピングしない)
- API キーは `.env` のみ。`.env.template` だけをコミット
- プロンプト変更後は必ずローカルで複数回テスト出力してからコミット
- ハッシュタグ:
  - X: 付けない(リサイクル版と同じ判断、エンゲージメント率重視)
  - IG: 5-15 個使う(IG はハッシュタグが実際に効く媒体)
  - Threads: 0-1 個まで(spam 扱い回避)
