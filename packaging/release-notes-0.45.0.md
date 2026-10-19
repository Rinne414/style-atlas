## 简体中文

**Style Atlas 0.45.0**：下载更快、模型不再占用 C 盘、有 NVIDIA 显卡时计算更快。

- **自动选最快的下载来源**：下载前先测官方和国内镜像（清华、阿里云、南京大学、上海交大、hf-mirror）哪个快；画风模型下载到一半卡住会换另一个来源接着下。每个文件都核对 SHA256，从镜像下载一样安全。
- **模型和缓存放在程序文件夹里**（`data`），解压到哪个磁盘就放在哪里；开始页面下方显示占用多少，按“更改位置…”可以搬到别的磁盘，不用重新下载。旧版下载过的模型会继续用。
- **有 NVIDIA 显卡时，第一次计算快约 30%**（RTX 3090 每秒 41 张 → 53 张），结果和以前一样。
- 安装时不再在 C 盘留下 2.7 GB 的 torch 安装包。

从 0.44.0 按“更新”升级后，之后第一次从快捷方式打开时会弹出一次命令窗口检查组件（几秒到一分钟，只有这一次），这是正常的。

## English

**Style Atlas 0.45.0**: faster downloads, the model off drive C:, faster first computation with
an NVIDIA card.

- **The fastest download source is picked for you**: the original sites and mirrors are measured
  first; a stalled style-model download carries on from another source. Every file is checked
  against its SHA256, so a mirror is as safe as the original.
- **The model and caches live in the program's folder** (`data`), on the drive you unpacked to.
  The bottom of the start page shows how much space they take; **Move…** moves them to another
  drive without downloading anything again. A model an older version downloaded is still used.
- **About 30% faster first computation with an NVIDIA card** (RTX 3090: 41 → 53 pictures a
  second), with the same results.
- Installing no longer leaves a 2.7 GB copy of torch on drive C:.

After updating from 0.44.0 with Update, the first start from the shortcut afterwards opens a
console window once to check the packages (a few seconds to a minute); that is expected.

## 下载 / Download

| 系统 / System | 文件 / File | 怎么开始 / How to start |
|---|---|---|
| Windows 10 / 11 (64-bit) | `StyleAtlas-0.45.0-windows.zip` | 解压，双击 `Style Atlas.bat` / unzip, double-click `Style Atlas.bat` |
| Linux x86-64 | `StyleAtlas-0.45.0-linux.tar.gz` | `tar xzf …`，然后 / then `./style-atlas.sh` |

第一次启动会下载 torch（有 NVIDIA 显卡约 2.5 GB，没有约 200 MB）；第一次打开文件夹会下载画风模型
（2.4 GB）。The first start downloads torch (about 2.5 GB with an NVIDIA card, 200 MB without);
the first folder downloads the style model (2.4 GB).

`style-atlas-app-0.45.0.zip` 和 `update.json` 是程序内更新用的，不需要手动下载。
`style-atlas-app-0.45.0.zip` and `update.json` are for the in-program update; you do not need
them. Checksums: `SHA256SUMS.txt`.

完整说明 / Full guide: [README（简体中文）](https://github.com/Rinne414/style-atlas/blob/main/README.zh-CN.md) ·
[README (English)](https://github.com/Rinne414/style-atlas/blob/main/README.md)
