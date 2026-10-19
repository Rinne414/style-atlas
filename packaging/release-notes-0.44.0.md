## 简体中文

**Style Atlas 0.44.0**：把图片文件夹按画风分组、找画风相近的图、整理 LoRA 训练集，全部在你的电脑上运行。

这是第一个不需要先安装 Python 的版本：

- 解压后双击一个文件就能用；第一次启动会自动安装需要的组件。
- 有新版本时程序会提示，按“更新”才会更新（只下载程序代码，并用 SHA256 校验）。
- 界面改为简体中文。
- 可以同时开好几个文件夹，每个窗口一个。

## English

**Style Atlas 0.44.0**: group a folder of pictures by art style, find pictures in a similar
style, and prepare LoRA training sets, all on your own computer.

The first version that needs no Python installed:

- Unzip, double-click one file; the first start installs what it needs.
- The program tells you about new versions, and updates only when you press Update (program
  code only, checked against SHA256).
- Several folders at once, one per window.

## 下载 / Download

| 系统 / System | 文件 / File | 怎么开始 / How to start |
|---|---|---|
| Windows 10 / 11 (64-bit) | `StyleAtlas-0.44.0-windows.zip` | 解压，双击 `Style Atlas.bat` / unzip, double-click `Style Atlas.bat` |
| Linux x86-64 | `StyleAtlas-0.44.0-linux.tar.gz` | `tar xzf …`，然后 / then `./style-atlas.sh` |

第一次启动会下载 torch（有 NVIDIA 显卡约 2.5 GB，没有约 200 MB）；第一次打开文件夹会下载画风模型
（2.4 GB）。The first start downloads torch (about 2.5 GB with an NVIDIA card, 200 MB without);
the first folder downloads the style model (2.4 GB).

`style-atlas-app-0.44.0.zip` 和 `update.json` 是程序内更新用的，不需要手动下载。
`style-atlas-app-0.44.0.zip` and `update.json` are for the in-program update; you do not need
them. Checksums: `SHA256SUMS.txt`.

完整说明 / Full guide: [README（简体中文）](https://github.com/Rinne414/style-atlas/blob/main/README.zh-CN.md) ·
[README (English)](https://github.com/Rinne414/style-atlas/blob/main/README.md)
