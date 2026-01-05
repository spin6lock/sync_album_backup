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
