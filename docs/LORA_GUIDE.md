# 用 style-atlas 整理畫風 LoRA 資料集

這是一份實務流程。工具會做的事附上指令。一般建議附上來源，這些來源是 2026-10 查的，請自行判斷是否適用你的模型。

下面的指令請在 `scripts\StyleAtlas-console.bat` 開出的視窗裡輸入，一次貼一行。步驟 2 也可以改成把資料夾拖到 `scripts\StyleAtlas.bat` 上直接開網頁介面；步驟 1、3 的指令則一定要在 console 視窗裡打。

## 1. 先檢查

```bat
style-atlas audit "D:\lora\artistX" --min-side 768
```

不想打指令的話，可以直接進步驟 2：網頁的「檢查」分頁按「開始檢查」會列出同樣的問題。

修掉或移除下列幾類圖：

- 太小的圖：短邊小於訓練解析度。
- 長寬比極端的圖。
- 截斷的檔案。
- 動圖。
- 缺標註或標註是空的。
- 混在彩色圖裡的黑白圖（例如草稿、漫畫頁）。整個資料夾大多是黑白時不會列出，因為那是畫師本身的風格。

## 2. 看一遍，再決定怎麼分

```bat
style-atlas serve "D:\lora\artistX" --time name
```

在網頁介面裡依序看這幾頁：

- **重複**：同一張圖、裁切、表情差分、同場景連續畫面。重複圖會讓模型過度學那一張。
- **檢查**：上方的「開始檢查」會列出步驟 1 的問題圖（和 `audit` 相同），下方是草稿、漫畫頁、截圖這類通常不合群的圖。不要的按 X 排除。
  - 混進了別的畫師的圖（例如抓 tag 時抓到的）：它們彼此很像，不一定會出現在不合群清單裡。先把看到的兩三張按 X 排除，再按排除清單上方的「找更多像這些的」，其餘的通常都會排在最前面，逐一點選後按 X。
- **畫風群**：每群旁邊的時間分佈，可以看出哪一群是早期、哪一群是近期；有標註時還會列出這群特別常見的標籤。
  - 預設的門檻是「自動」，會依圖片決定。想按時期拆，把左下的分群選單切到「時期（單一畫師）」，在旁邊填要分幾段（預設 3），再按「重新分群」。幾乎每張圖都會分進其中一段，連草稿這類不合群的圖也會，所以先在「檢查」分頁把不要的按 X 排除。圖少於約 100 張時，分段界線不太穩定。
  - 分錯的圖可以手動移到別群、合併兩群，或把一群拆成兩群。改錯了按「復原」或 Ctrl+Z。
  - 打開一群按「找更多像這群的」，可以把被分到別群或沒分到的同類圖找回來。
  - 幫每群取名（例如「早期」「線稿期」），匯出的資料夾和觸發詞就會用這個名字。
- **擴充資料集**（選用）：手上只有十幾張某種畫風的圖時，可以用 `style-atlas search 範例資料夾 --combine --in 大圖庫 --top 100 --copy-to 輸出資料夾` 從大圖庫裡找出更多同風格的圖。
- **口味**（選用）：在評分模式下一直按 L／D，評約 10 張就能得到粗略的偏好排序。

網頁開著時，這個 console 視窗會一直被占用。看完後按 Ctrl+C 停掉，或另開一個 `StyleAtlas-console.bat` 視窗做步驟 3。

## 3. 匯出成 kohya 資料夾

```bat
style-atlas cluster "D:\lora\artistX" --layout kohya --name artistX --dedupe --drop-outliers 5 --export copy
```

- **在網頁上做過移動、合併、拆群或取名時，請改用網頁的「匯出資料夾」**（選 kohya、填概念名稱，必要時勾「標註加觸發詞」）：只有它會用到這些手動修正。上面的 `cluster` 指令會重新分群，只沿用你按 X 排除的圖（放進 `_excluded\`）。
- 每群會匯出成 `<repeats>_artistX_styleNN\` 資料夾（取過名的群用名字），標註檔一起複製。
- 要按時期拆就加 `--granularity period --time name`。指令會在每群後面印出它在作品時間軸上的位置，例如 `when 9% [3%-28%]` 表示這群的中位數落在最早的 9%（中間一半落在 3%～28%），一看就知道哪群是早期、哪群是近期。
- repeats 會自動調成「張數 × repeats ≈ 100」，也可以用 `--repeats N` 指定。
- 某群太多張（例如 300 張）時，加 `--max-per-group 40`（網頁：「每群上限」）只保留 40 張能涵蓋整群變化的圖，其餘放到 `_trimmed\`。
- 匯出資料夾裡會一起寫一份 `dataset_config.toml`（kohya sd-scripts 用 `--dataset_config` 指定），列出每群的資料夾路徑與 repeats；有勾觸發詞時會設 `keep_tokens = 1`，讓觸發詞在打亂標籤時固定在最前面。解析度與 batch size 請依模型自行調整（SDXL／Illustrious 用 1024）。
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

- 2～5 位畫師混在一起時，分群和畫師的吻合度約 ARI 0.5；畫師越多越低（50 位時約 0.38）。同一畫師拆時期時，「時期」（分 3 段）和發表時間的吻合度明顯比預設的自動門檻好，但整體仍偏弱（13 位測試畫師的平均 AMI 約 0.12）；作品少時分段結果不太穩定。所以分群是**初步整理**，請在地圖上確認。
- 同一個角色出現在很多畫風時，畫風向量會被角色外觀拉走。遇到這種收藏可以加 `--ignore-characters`（或在網頁勾選「忽略角色軸」）；但不要用在混了不同畫師的資料夾。
- 近重複門檻刻意設得保守（0.95）。在 0.92～0.95 之間，常常是同角色換了姿勢的不同圖，對訓練來說那是有效的圖。

詳細數字見 [BENCHMARKS.md](BENCHMARKS.md)。
