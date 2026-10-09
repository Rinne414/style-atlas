# 用 style-atlas 整理畫風 LoRA 資料集

這是一份實務流程。工具會做的事附上指令。一般建議附上來源，這些來源是 2026-10 查的，請自行判斷是否適用你的模型。

## 1. 先檢查

```bash
style-atlas audit "D:\lora\artistX" --min-side 768
```

修掉或移除下列幾類圖：

- 太小的圖：短邊小於訓練解析度。
- 長寬比極端的圖。
- 截斷的檔案。
- 動圖。
- 缺標註或標註是空的。

## 2. 看一遍，再決定怎麼分

```bash
style-atlas serve "D:\lora\artistX" --time name
```

在網頁介面裡依序看這幾頁：

- **重複**：同一張圖、裁切、表情差分、同場景連續畫面。重複圖會讓模型過度學那一張。
- **離群**：草稿、漫畫頁、截圖這類通常不合群的圖。不要的按 X 排除。
- **畫風群**：每群旁邊的時間分佈，可以看出哪一群是早期、哪一群是近期。
  - 想按時期拆，把顆粒度切到「時期」（門檻 0.35）。
  - 分錯的圖可以手動移到別群、合併兩群，或把一群拆成兩群。
- **口味**（選用）：在評分模式下一直按 L／D，評約 10 張就能得到粗略的偏好排序。

## 3. 匯出成 kohya 資料夾

```bash
style-atlas cluster "D:\lora\artistX" --layout kohya --name artistX --dedupe --drop-outliers 5 --export copy
```

- 每群會匯出成 `<repeats>_artistX_styleNN\` 資料夾，標註檔一起複製。
- repeats 會自動調成「張數 × repeats ≈ 100」，也可以用 `--repeats N` 指定。
- 被排除的圖放在 `_duplicates\`、`_outliers\`、`_unassigned\`、`_excluded\` 這幾個資料夾。它們沒有數字前綴，所以 kohya 不會拿來訓練。
- 想**一群訓一個 LoRA**（例如早期、近期畫風分開）：把那一群的資料夾單獨當 train_data_dir。
- 想**同一個 LoRA 裡分成幾個概念**：保留全部資料夾，並讓每群有自己的觸發詞。注意兩點：
  - kohya 只有在**沒有標註檔**時，才會拿資料夾名（`artistX_styleNN`）當標註。
  - 有標註檔時，要把觸發詞寫進每個標註的開頭（可搭配 `keep_tokens`）。加 `--trigger-captions` 會自動幫你做：
    - 匯出的每個標註開頭會加上 `artistX_styleNN, `；
    - 沒標註的圖會新建一個只含觸發詞的標註；
    - 原始標註不會被改。

## 4. 一般實務建議（非本工具的測量結果）

- **張數**：畫風 LoRA 的常見建議是 15–30 張就夠，超過約 50 張效果遞減，8–15 張可以先試。畫風要一致，主題（角色、場景、構圖）反而要多樣。
  - 來源：https://help.scenario.com/en/articles/training-a-style-lora 、https://apatero.com/blog/ultimate-guide-lora-training-2025
- **標註寫內容，不寫畫風**：標註描述畫了什麼，畫風交給 LoRA 去學。2026 年有一篇研究特地把標註改寫成只描述客觀內容，因為描述畫風的字眼會「漏」到標註裡。
  - 來源：https://arxiv.org/pdf/2603.16649
  - Illustrious 一類模型可以用 Danbooru 式 tag：https://offlinecreator.com/guide/illustrious-lora-training-guide
- **kohya 的 repeats 與標註選項**：資料夾前綴 `N_name`（或 TOML 的 `num_repeats`）決定 repeats；`shuffle_caption` 與 `keep_tokens` 是常用的標註選項。
  - 來源：https://www.mintlify.com/kohya-ss/sd-scripts/quickstart
- **其他過濾工具**：deepghs 的 imgutils／waifuc 能濾掉單色圖、漫畫頁、多角色圖，也能用 CCIP 認角色，可以和本工具搭配使用。
  - 來源：https://github.com/deepghs

## 5. 要知道的限制

- 不同畫師混在一起時，分群和畫師的吻合度約 ARI 0.5。同一畫師拆時期時，13 位測試畫師中有 9 位的分群和發表時間顯著對應。所以分群是**初步整理**，請在地圖上確認。
- 同一個角色出現在很多畫風時，畫風向量會被角色外觀拉走。遇到這種收藏可以加 `--neutralize 1`；但不要用在混了不同畫師的資料夾。
- 近重複門檻刻意設得保守（0.95）。在 0.92～0.95 之間，常常是同角色換了姿勢的不同圖，對訓練來說那是有效的圖。

詳細數字見 [BENCHMARKS.md](BENCHMARKS.md)。
