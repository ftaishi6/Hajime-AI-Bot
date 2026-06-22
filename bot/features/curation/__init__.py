"""バズキュレーション機能。

watchlist (config.yaml + DB) の AI 系発信者の直近 24h 投稿を取得し、
Claude で古谷さん文脈に刺さる top 3 を抽出。各 highlight に
「引用 RT 案」と「自分の角度からの別投稿案」を付けて #hajime-curation
に Embed で投下する。
"""
