# Hajime-AI-Bot

「**はじめの一歩 AI 塾**」(古谷太嗣 主宰、東大阪・有限会社古谷商店)の
X / Threads / Instagram 用 投稿案 生成・配信 Bot。

リポ: <https://github.com/ftaishi6/Hajime-AI-Bot>

## 目的

エンジニアではない中小経営者・個人事業主向けに「AI を業務に取り入れる
第一歩」を提供する AI 塾の **認知拡大** と **集客動線** を、SNS 自動化で支える。

戦略:
- **A. AI バズキュレーション**:watchlist の他者バズ投稿を抽出 → 古谷さん視点で一言添える
- **B. AI 基礎用語解説**:34 語カタログから日次 1 単語、初心者向け 140 字解説
- (将来) **C. 自社内製事例 / D. AI 塾告知** を順次追加

3 媒体への投稿は **半自動**(Discord に案 → 古谷さんが手動投稿)。
リサイクル本業 Bot(`ftaishi6/Xapp`)とは **別リポ・別 systemd service**。

## 公開アカウント

- X       : <https://x.com/hajime_ai_juku>
- Threads : @hajime_ai_juku
- Instagram: @hajime_ai_juku
- Peatix  : <https://hajime-ai-juku.peatix.com>

## アーキテクチャ(2026-06 時点)

```
ConoHa VPS (既存 Xapp と同居、別 systemd service)
└── hajime-ai-bot.service
    ├── discord.py 常駐 Bot
    ├── APScheduler:
    │   ├─ daily 07:00 JST  キュレーション digest
    │   ├─ daily 12:00 JST  基礎用語 1 単語
    │   └─ weekly 月曜 09:30 バズ案(将来)
    └── SQLite (/opt/hajime-ai-bot/hajime.db)
```

## 開発・デプロイ

詳細は `docs/operations.md`(運用マニュアル、作成予定)を参照。

## ライセンス

私的運用 Bot のため未設定。

## 関連プロジェクト

- [ftaishi6/Xapp](https://github.com/ftaishi6/Xapp) — リサイクル本業用 X 自動運用 Bot(縮小運用中)
