"""内製事例の発信機能(Phase 4-A)。

古谷さんが #hajime-case-input に自由文で事例を投稿 → Bot が自動取り込み
→ Claude が「課題 / 実装 / 成果 / 数字 / 出典」に構造化して DB 保存。
週 1(火曜 09:00 JST)cron が未配信事例から 1 件 pickup → 3 パターン
(story / numbers / introspection)の投稿案を生成 → #hajime-cases。
"""
