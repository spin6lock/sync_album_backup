# sync_album_backup

在 Windows 下使用 rsync over SSH 将本地相册备份到 Linux 服务器。

## 功能

- 将本地源目录下的子目录同步到两个远程目标目录
- 使用 rsync 进行增量同步，显示进度
- 自动清理超过 30 天的过期目录
- 支持 SSH 密钥认证

## 依赖

### Windows 端

需要在 Windows 上安装 rsync，推荐以下方式之一：

#### 方式一：WSL (Windows Subsystem for Linux)

```bash
# 安装 WSL (如果未安装)
wsl --install

# WSL 内置 rsync，直接使用
```

#### 方式二：cwRsync

1. 下载地址：https://www.itefix.net/cwrsync
2. 安装后添加到系统 PATH，或使用完整路径：
   ```python
   RSYNC_PATH = "C:/cwRsync/bin/rsync.exe"
   ```

#### 方式三：MSYS2

```bash
# 下载地址: https://www.msys2.org/
# 安装后执行：
pacman -S rsync
```

### Linux 服务器端

- SSH 服务正常运行
- SSH 密钥已配置好（无密码登录）

## 配置

编辑 `sync_album_backup.py` 顶部的配置区域：

```python
# Windows 本地源目录
SOURCE_BASE = Path("D:/你的相册路径")

# 远程 Linux 服务器配置
REMOTE_USER = "your_username"
REMOTE_HOST = "192.168.x.x"  # 你的 Linux 服务器 IP
REMOTE_PORT = 22

# 远程目标目录
REMOTE_TARGET_BASE = "/path/to/backup1"
REMOTE_TARGET_BASE2 = "/path/to/backup2"

# SSH 密钥路径 (Windows 格式)
SSH_KEY = Path("C:/Users/your_username/.ssh/id_rsa")

# rsync 路径
RSYNC_PATH = "rsync"  # 或 "C:/cwRsync/bin/rsync.exe"
```

## 视频切片 (split_video.py)

把超过 256MB 的大视频（如大疆拍摄）切成约 256MB 片段，方便手机上传网盘。

### 完整流程（双击 bat 自动执行）

1. **切片**：大视频切成 `*_part0001.mp4` 等片段（只保留视频+音频流，丢弃 dbgi/djmd/tmcd 私有数据流）
2. **rsync 同步**：源视频 + 切片全部同步到远端两块盘
3. **推送手机**（远端 `sync_to_pixel`）：只推切片到 PixelShare，源视频按大小过滤跳过（远端 `backup_media` 的 `max_file_size_mb = 256`）
4. **本地清理**：推送成功后删除本地切片（源视频保留），并记录到 `.parts_synced.json`，下次不会重切重传

### 依赖

- ffmpeg 9.0（放在本目录，`FFMPEG_PATH` 自动引用）

### 使用

```bash
python split_video.py --dry-run      # 先预览将要处理的文件
python split_video.py                # 执行切片（源视频保留）
```

### 说明

- `-c copy` 无损切割，不重新编码，速度快且画质无损
- 切片丢弃私有数据流（新版 ffmpeg 不支持写入，且手机上传用不到），视频/音频完整保留
- 切片在临时目录完成后校验（片数、总大小），通过才移入原目录，中断不留半成品
- 已切过或已完成全流程（状态文件记录）的自动跳过
- `SPLIT_MIN_DATE`：只切该日期及之后目录的视频（按目录名 YYYYMMDD 前缀判断），历史文件不动；设为 `None` 不限制

## 使用

```bash
python sync_album_backup.py
```

## 目录结构

```
sync_album_backup/
├── sync_album_backup.py  # 主脚本
└── README.md             # 本说明文件
```
