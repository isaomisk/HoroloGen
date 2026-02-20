# TRUST_SOURCES 拡充リスト（Phase 0）

## ■ 方針
- カテゴリA：Eye Eye Isuzu取扱ブランドの公式ドメインを網羅
- カテゴリB：日本の主要正規店・並行店を追加
- カテゴリC：日本語・英語の主要時計メディアを追加
- カテゴリD・E：必要に応じて追加
- lang フィールドを新設（"ja" / "en" / "both"）
  → 英語記事自動補完のlang判定に使用

---

## ■ カテゴリA：ブランド公式

```python
# ===== カテゴリA：ブランド公式 =====

# --- 高級時計ブランド ---
"arminstrom.com":          {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
"arnoldandson.com":        {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
"audemarspiguet.com":      {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
"backesandstrauss.com":    {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
"ballwatch.com":           {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
"baume-et-mercier.com":    {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
"bellross.com":            {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
"blancpain.com":           {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
"breguet.com":             {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
"breitling.com":           {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
"bulgari.com":             {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
"cartier.com":             {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
"cartier.jp":              {"category": "A", "allowed_use": ["facts", "context"], "lang": "ja"},
"centurytime.com":         {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
"chanel.com":              {"category": "A", "allowed_use": ["facts", "context"], "lang": "both"},
"chopard.com":             {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
"chopard.jp":              {"category": "A", "allowed_use": ["facts", "context"], "lang": "ja"},
"chronoswiss.com":         {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
"corum.ch":                {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
"cvstos.com":              {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
"delma.ch":                {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
"eberhard-co-watches.ch":  {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
"edox.com":                {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
"franckmuller.com":        {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
"franckmuller-japan.com":  {"category": "A", "allowed_use": ["facts", "context"], "lang": "ja"},
"frederiqueconstant.com":  {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
"furlanmarri.com":         {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
"geraldcharles.com":       {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
"girard-perregaux.com":    {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
"glashuette-original.com": {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
"gorillawatches.com":      {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
"grand-seiko.com":         {"category": "A", "allowed_use": ["facts", "context"], "lang": "both"},
"h-moser.com":             {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
"hamiltonwatch.com":       {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
"harrywinston.com":        {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
"hautlence.com":           {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
"music-herbelin.com":      {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
"herbelin.jp":             {"category": "A", "allowed_use": ["facts", "context"], "lang": "ja"},
"hublot.com":              {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
"hysek.com":               {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
"hytwatches.com":          {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
"ikepod.com":              {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
"iwc.com":                 {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
"jaeger-lecoultre.com":    {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
"jaermann-stubi.com":      {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
"junghans.de":             {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
"lfreasonnance.com":       {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
"longines.com":            {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
"longines.jp":             {"category": "A", "allowed_use": ["facts", "context"], "lang": "ja"},
"louiserard.com":          {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
"luminox.com":             {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
"mauricelacroix.com":      {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
"montblanc.com":           {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
"moritz-grossmann.com":    {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
"nomos-glashuette.com":    {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
"norqain.com":             {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
"omegawatches.com":        {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
"omegawatches.jp":         {"category": "A", "allowed_use": ["facts", "context"], "lang": "ja"},
"oris.com":                {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
"oris.ch":                 {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
"panerai.com":             {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
"parmigiani.com":          {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
"piaget.com":              {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
"piaget.jp":               {"category": "A", "allowed_use": ["facts", "context"], "lang": "ja"},
"raymondweil.com":         {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
"music-herbelin.com":      {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
"ressencewatches.com":     {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
"rogerdubuis.com":         {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
"rolex.com":               {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
"rolex.org":               {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
"tagheuer.com":            {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
"tudorwatch.com":          {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
"ulysse-nardin.com":       {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
"zenith-watches.com":      {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
"tissotshop.com":          {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
"tissotwatches.com":       {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
"lfreasonnance.com":       {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
"renaudtixier.com":        {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},

# --- CASIO / CITIZEN グループ（公式日本語サイト）---
"casio.com":               {"category": "A", "allowed_use": ["facts", "context"], "lang": "both"},
"casio.co.jp":             {"category": "A", "allowed_use": ["facts", "context"], "lang": "ja"},
"g-shock.jp":              {"category": "A", "allowed_use": ["facts", "context"], "lang": "ja"},
"gshock.com":              {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
"baby-g.jp":               {"category": "A", "allowed_use": ["facts", "context"], "lang": "ja"},
"edifice-watches.com":     {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
"protrek.jp":              {"category": "A", "allowed_use": ["facts", "context"], "lang": "ja"},
"oceanus.casio.jp":        {"category": "A", "allowed_use": ["facts", "context"], "lang": "ja"},
"citizen.jp":              {"category": "A", "allowed_use": ["facts", "context"], "lang": "ja"},
"citizen.co.jp":           {"category": "A", "allowed_use": ["facts", "context"], "lang": "ja"},
"campanola.jp":            {"category": "A", "allowed_use": ["facts", "context"], "lang": "ja"},
"the-citizen.jp":          {"category": "A", "allowed_use": ["facts", "context"], "lang": "ja"},
"seikowatches.com":        {"category": "A", "allowed_use": ["facts", "context"], "lang": "both"},
"seikowatcheshop.com":     {"category": "A", "allowed_use": ["facts", "context"], "lang": "ja"},

# --- GARMIN ---
"garmin.com":              {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
"garmin.co.jp":            {"category": "A", "allowed_use": ["facts", "context"], "lang": "ja"},

# --- マイナー / 新興ブランド ---
"lfreasonnance.com":       {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
"lainewatches.com":        {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
"ossoitaly.com":           {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
"shellman.co.jp":          {"category": "A", "allowed_use": ["facts", "context"], "lang": "ja"},
"klasse14.com":            {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
"mauronmusy.com":          {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
"zerootime.com":           {"category": "A", "allowed_use": ["facts", "context"], "lang": "ja"},
"ztage.jp":                {"category": "A", "allowed_use": ["facts", "context"], "lang": "ja"},
```

## ■ カテゴリB：正規店 / 販売店

```python
# ===== カテゴリB：正規店 / 販売店 =====

# --- 既存 ---
"eye-eye-isuzu.co.jp":    {"category": "B", "allowed_use": ["context"], "lang": "ja"},
"rasin.co.jp":             {"category": "B", "allowed_use": ["context"], "lang": "ja"},
"evance.co.jp":            {"category": "B", "allowed_use": ["context"], "lang": "ja"},

# --- 追加：正規店（CSVデータ + 既知の主要店）---
"tgsakai.blogo.jp":        {"category": "B", "allowed_use": ["context"], "lang": "ja"},  # タイムズギア
"shopblog.tomiya.co.jp":   {"category": "B", "allowed_use": ["context"], "lang": "ja"},  # トミヤ
"e-ami.co.jp":             {"category": "B", "allowed_use": ["context"], "lang": "ja"},  # A.M.I
"nsdo.co.jp":              {"category": "B", "allowed_use": ["context"], "lang": "ja"},  # 日新堂
"basisspecies.jp":         {"category": "B", "allowed_use": ["context"], "lang": "ja"},  # ベイシススピーシーズ
"l-sakae.co.jp":           {"category": "B", "allowed_use": ["context"], "lang": "ja"},  # エルサカエ
"isana-w.jp":              {"category": "B", "allowed_use": ["context"], "lang": "ja"},  # イサナ
"hidakahonten.jp":         {"category": "B", "allowed_use": ["context"], "lang": "ja"},  # 日高本店
"hrd-web.com":             {"category": "B", "allowed_use": ["context"], "lang": "ja"},  # ハラダ
"kamine.co.jp":            {"category": "B", "allowed_use": ["context"], "lang": "ja"},  # カミネ
"kobayashi-tokeiten.com":  {"category": "B", "allowed_use": ["context"], "lang": "ja"},  # 小林時計店
"tompkins.jp":             {"category": "B", "allowed_use": ["context"], "lang": "ja"},  # トンプキンス
"anshindo-grp.co.jp":      {"category": "B", "allowed_use": ["context"], "lang": "ja"},  # 安心堂
"isseidostaff.blogspot.com": {"category": "B", "allowed_use": ["context"], "lang": "ja"},  # 一誠堂
"lian-sakai-onlineshop.jp": {"category": "B", "allowed_use": ["context"], "lang": "ja"},  # サカイ
"prive.co.jp":             {"category": "B", "allowed_use": ["context"], "lang": "ja"},  # プリベ石川
"koyanagi-tokei.com":      {"category": "B", "allowed_use": ["context"], "lang": "ja"},  # 小柳時計店
"hassin.co.jp":            {"category": "B", "allowed_use": ["context"], "lang": "ja"},  # HASSIN
"wing-rev.co.jp":          {"category": "B", "allowed_use": ["context"], "lang": "ja"},  # WING
"hf-age.com":              {"category": "B", "allowed_use": ["context"], "lang": "ja"},  # HF-AGE
"threec.jp":               {"category": "B", "allowed_use": ["context"], "lang": "ja"},  # THREEC
"j-paris.co.jp":           {"category": "B", "allowed_use": ["context"], "lang": "ja"},  # ジュエリーパリ
"koharu1977.com":          {"category": "B", "allowed_use": ["context"], "lang": "ja"},  # KOHARU
"jw-oomiya.co.jp":         {"category": "B", "allowed_use": ["context"], "lang": "ja"},  # oomiya
"ishida-watch.com":        {"category": "B", "allowed_use": ["context"], "lang": "ja"},  # イシダ
"tokia.co.jp":             {"category": "B", "allowed_use": ["context"], "lang": "ja"},  # ときあ
"hh-new.co.jp":            {"category": "B", "allowed_use": ["context"], "lang": "ja"},  # 日新堂本店
"yoshidaweb.com":          {"category": "B", "allowed_use": ["context"], "lang": "ja"},  # ヨシダ
"couronne.info":           {"category": "B", "allowed_use": ["context"], "lang": "ja"},  # クロンヌ

# --- 追加：並行店 / 中古店 ---
"jackroad.co.jp":          {"category": "B", "allowed_use": ["context"], "lang": "ja"},
"bettyroad.co.jp":         {"category": "B", "allowed_use": ["context"], "lang": "ja"},
"housekihiroba.jp":        {"category": "B", "allowed_use": ["context"], "lang": "ja"},
"komehyo.co.jp":           {"category": "B", "allowed_use": ["context"], "lang": "ja"},
"ginza-rasin.com":         {"category": "B", "allowed_use": ["context"], "lang": "ja"},
"gmt-j.com":               {"category": "B", "allowed_use": ["context"], "lang": "ja"},
"moonphase.jp":            {"category": "B", "allowed_use": ["context"], "lang": "ja"},
"kawano-watch.com":        {"category": "B", "allowed_use": ["context"], "lang": "ja"},
"galleryrare.jp":          {"category": "B", "allowed_use": ["context"], "lang": "ja"},
"watchnian.com":           {"category": "B", "allowed_use": ["context"], "lang": "ja"},
```

## ■ カテゴリC：時計専門メディア

```python
# ===== カテゴリC：時計専門メディア =====

# --- 既存（更新）---
"webchronos.net":            {"category": "C", "allowed_use": ["context", "opinion"], "lang": "ja"},
"hodinkee.com":              {"category": "C", "allowed_use": ["context", "opinion"], "lang": "en"},
"hodinkee.jp":               {"category": "C", "allowed_use": ["context", "opinion"], "lang": "ja"},  # ★追加
"monochrome-watches.com":    {"category": "C", "allowed_use": ["context", "opinion"], "lang": "en"},
"timeandtidewatches.com":    {"category": "C", "allowed_use": ["context", "opinion"], "lang": "en"},
"fratellowatches.com":       {"category": "C", "allowed_use": ["context", "opinion"], "lang": "en"},
"watchesbysjx.com":          {"category": "C", "allowed_use": ["context", "opinion"], "lang": "en"},
"revolutionwatch.com":       {"category": "C", "allowed_use": ["context", "opinion"], "lang": "en"},
"swisswatches-magazine.com": {"category": "C", "allowed_use": ["context", "opinion"], "lang": "en"},
"wornandwound.com":          {"category": "C", "allowed_use": ["context", "opinion"], "lang": "en"},

# --- 追加：ミサキさん確認済みメディア ---
"ablogtowatch.com":          {"category": "C", "allowed_use": ["context", "opinion"], "lang": "en"},
"watchtime.com":             {"category": "C", "allowed_use": ["context", "opinion"], "lang": "en"},
"waqt.com":                  {"category": "C", "allowed_use": ["context", "opinion"], "lang": "en"},  # ★新規

# --- 追加：日本語メディア ---
"watchmedia.co.jp":          {"category": "C", "allowed_use": ["context", "opinion"], "lang": "ja"},
"watch-media-online.com":    {"category": "C", "allowed_use": ["context", "opinion"], "lang": "ja"},
"pen-online.jp":             {"category": "C", "allowed_use": ["context", "opinion"], "lang": "ja"},
"tokeibegin.jp":             {"category": "C", "allowed_use": ["context", "opinion"], "lang": "ja"},
"watchfan.com":              {"category": "C", "allowed_use": ["context", "opinion"], "lang": "ja"},
"precious.jp":               {"category": "C", "allowed_use": ["context", "opinion"], "lang": "ja"},
"watch-tanaka.com":          {"category": "C", "allowed_use": ["context", "opinion"], "lang": "ja"},
"gressive.jp":               {"category": "C", "allowed_use": ["context", "opinion"], "lang": "ja"},
"watchlife.jp":              {"category": "C", "allowed_use": ["context", "opinion"], "lang": "ja"},
"tokeizanmai.com":           {"category": "C", "allowed_use": ["context", "opinion"], "lang": "ja"},
"esq-mag.jp":                {"category": "C", "allowed_use": ["context", "opinion"], "lang": "ja"},

# --- 追加：英語メディア ---
"thewatchbox.com":           {"category": "C", "allowed_use": ["context", "opinion"], "lang": "en"},
"deployant.com":             {"category": "C", "allowed_use": ["context", "opinion"], "lang": "en"},
"quillandpad.com":           {"category": "C", "allowed_use": ["context", "opinion"], "lang": "en"},
"sjx.com":                   {"category": "C", "allowed_use": ["context", "opinion"], "lang": "en"},
"thewatchpages.com":         {"category": "C", "allowed_use": ["context", "opinion"], "lang": "en"},
"timezone.com":              {"category": "C", "allowed_use": ["context", "opinion"], "lang": "en"},
"twobrokewatchsnobs.com":    {"category": "C", "allowed_use": ["context", "opinion"], "lang": "en"},
"watchlounge.com":           {"category": "C", "allowed_use": ["context", "opinion"], "lang": "en"},

# --- 追加：マガジン / アナリティクス系メディア ---
"chrono24.jp":               {"category": "C", "allowed_use": ["context", "opinion"], "lang": "ja"},  # Chrono24 Magazine
"chrono24.com":              {"category": "C", "allowed_use": ["context", "opinion"], "lang": "en"},  # Chrono24 Magazine
"watchanalytics.io":         {"category": "C", "allowed_use": ["context", "opinion"], "lang": "en"},  # Watch Analytics Blog
```

## ■ カテゴリD：マーケット系

```python
# ===== カテゴリD：マーケット系 =====
# ※ chrono24はマガジン機能があるためカテゴリCに移動済み
# （現在カテゴリDは空。今後マーケット専用サイトが必要になれば追加）
```

## ■ カテゴリE：UGC / 補助

```python
# ===== カテゴリE：UGC / 補助 =====
"wikipedia.org":             {"category": "E", "allowed_use": ["context"], "lang": "both"},
"note.com":                  {"category": "E", "allowed_use": ["context"], "lang": "ja"},
```

---

## ■ 変更サマリー

| カテゴリ | 現在 | 追加後 | 増加数 |
|---|---|---|---|
| A: ブランド公式 | 6 | 約90 | +84 |
| B: 正規店/販売店 | 3 | 約40 | +37 |
| C: 時計専門メディア | 9 | 約35 | +26 |
| D: マーケット系 | 1 | 0 | -1（Cに移動） |
| E: UGC/補助 | 2 | 2 | 0 |
| **合計** | **21** | **約167** | **+146** |

---

## ■ 注意事項

1. **langフィールドは新規追加**。既存コードの get_source_policy() に
   lang判定ロジックを追加する必要がある。

2. **ドメインの正確性は要検証**。一部ブランドは公式サイトのURLが
   変更されている可能性がある。実装前にアクセス確認推奨。

3. **CASIO/SEIKOグループはサブドメインが多い**。
   上記リストでは主要なものを記載しているが、
   サブドメイン対応（*.casio.co.jp 等）が必要になる可能性あり。

4. **このリストは初版**。運用しながら「フィルタで弾かれたURL」を
   モニタリングし、必要に応じて追加する運用が望ましい。
   → debug情報の filtered_reason をadminで定期確認する。
