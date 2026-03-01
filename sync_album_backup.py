#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
相册备份同步脚本 (Windows 版本)
使用 rsync over SSH 将本地目录同步到 Linux 服务器

依赖:
  - Windows: cwRsync, MSYS2, 或 WSL 中的 rsync
  - Linux 服务器: ssh 服务
"""

import os
import subprocess
import shutil
from pathlib import Path
from datetime import datetime
import time

from config import (
    SOURCE_BASE,
    REMOTE_USER,
    REMOTE_HOST,
    REMOTE_PORT,
    REMOTE_TARGET_BASE,
    REMOTE_TARGET_BASE2,
    RSYNC_PATH,
    SSH_PATH,
    EXCLUDE_CLEANUP_DIRS,
    REMOTE_SYNC_TO_PIXEL_CMD,
)


def build_ssh_command() -> str:
    """构建 SSH 命令 (使用 cwRsync 自带的 SSH)"""
    # 将 Windows 路径转换为正斜杠格式
    ssh_path_unix = SSH_PATH.replace("\\", "/")
    return f'"{ssh_path_unix}" -p {REMOTE_PORT} -o StrictHostKeyChecking=no'


def sync_with_rsync(src_dir: Path, remote_path: str, remote_user: str, remote_host: str) -> bool:
    """使用 rsync 同步目录到远程服务器"""
    ssh_cmd = build_ssh_command()
    src_str = str(src_dir).replace("\\", "/")

    # 在 Windows 上使用 /cygdrive/ 前缀格式
    if len(src_str) >= 2 and src_str[1] == ":":
        src_str = "/cygdrive/" + src_str[0] + src_str[2:]

    # rsync 命令: -a 归档模式, -v 详细, -P 显示进度
    cmd_str = f'{RSYNC_PATH} -avP -e "{ssh_cmd}" "{src_str}/" {remote_user}@{remote_host}:{remote_path}/'

    print(f"  从: {src_dir}")
    print(f"  到: {remote_user}@{remote_host}:{remote_path}")
    print(f"  命令: {cmd_str}")

    try:
        result = subprocess.run(cmd_str, shell=True, capture_output=False)
        return result.returncode == 0
    except Exception as e:
        print(f"  错误: {e}")
        return False


def sync_directory(src_dir: Path, remote_path: str) -> None:
    """同步单个目录"""
    success = sync_with_rsync(src_dir, remote_path, REMOTE_USER, REMOTE_HOST)
    if success:
        print(f"  完成: {src_dir.name}")
    else:
        print(f"  失败: {src_dir.name}")


def cleanup_old_dirs(source_base: Path, days: int = 30) -> None:
    """清理本地源目录中超过指定天数的日期子目录（source_base/*/*）"""
    print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 开始清理本地过期目录（超过{days}天）...")

    try:
        # 查找本地过期的日期子目录（例如: 相册备份/Mini4Pro/20260301）
        old_dirs = []
        now = time.time()
        cutoff_time = now - (days * 24 * 60 * 60)

        for parent_dir in source_base.iterdir():
            if not parent_dir.is_dir():
                continue
            if parent_dir.name in EXCLUDE_CLEANUP_DIRS:
                continue

            for child_dir in parent_dir.iterdir():
                if not child_dir.is_dir():
                    continue

                # 获取日期子目录的最后修改时间
                dir_mtime = child_dir.stat().st_mtime
                if dir_mtime < cutoff_time:
                    old_dirs.append(child_dir)

        if not old_dirs:
            print("  没有找到需要清理的过期目录")
            return

        print("找到以下过期目录：")
        for d in old_dirs:
            print(f"  - {d}")

        reply = input("\n是否删除这些目录？(y/N): ").strip().lower()
        if reply == "y":
            for d in old_dirs:
                try:
                    shutil.rmtree(d)
                    print(f"  已删除: {d}")
                except Exception as e:
                    print(f"  删除失败: {d} - {e}")
            print("过期目录清理完成！")
        else:
            print("取消清理操作")

    except Exception as e:
        print(f"  清理失败: {e}")


def sync_to_pixel():
    """同步到 Pixel 设备（通过 SSH 在远端执行）"""
    print("\n正在执行远端 sync_to_pixel...")

    # 将 SSH 路径转换为正斜杠格式
    ssh_path_unix = SSH_PATH.replace("\\", "/")

    cmd = [
        ssh_path_unix,
        "-p", str(REMOTE_PORT),
        f"{REMOTE_USER}@{REMOTE_HOST}",
        REMOTE_SYNC_TO_PIXEL_CMD
    ]

    print(f"  命令: {' '.join(cmd)}")

    try:
        result = subprocess.run(cmd, capture_output=False)
        if result.returncode == 0:
            print("  远端 sync_to_pixel 执行成功")
        else:
            print(f"  远端 sync_to_pixel 执行失败，返回码: {result.returncode}")
    except Exception as e:
        print(f"  错误: {e}")


def main():
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] 开始相册备份同步...")
    print(f"源目录: {SOURCE_BASE}")
    print(f"目标服务器: {REMOTE_USER}@{REMOTE_HOST}:{REMOTE_TARGET_BASE}")
    print(f"目标服务器2: {REMOTE_USER}@{REMOTE_HOST}:{REMOTE_TARGET_BASE2}")
    print("-" * 50)

    # 检查源目录是否存在
    if not SOURCE_BASE.exists():
        print(f"错误：源目录 {SOURCE_BASE} 不存在")
        return 1

    # 遍历源目录下的所有子目录
    for src_dir in SOURCE_BASE.iterdir():
        if src_dir.is_dir():
            print(f"\n正在同步: {src_dir.name}")

            # 同步到第一个目标
            remote_path1 = f"{REMOTE_TARGET_BASE}/{src_dir.name}"
            sync_directory(src_dir, remote_path1)

            # 同步到第二个目标
            remote_path2 = f"{REMOTE_TARGET_BASE2}/{src_dir.name}"
            sync_directory(src_dir, remote_path2)

            print("-" * 40)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] 所有相册备份同步完成！")

    # 清理源目录过期目录
    cleanup_old_dirs(SOURCE_BASE, days=30)

    sync_to_pixel()

    return 0


if __name__ == "__main__":
    exit(main())
