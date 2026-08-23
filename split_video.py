#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
大视频切片脚本
把超过阈值的大视频（大疆等）切成约 256MB 的片段，方便上传备份

流程:
  1. 递归扫描 SOURCE_BASE 下超过 SPLIT_MIN_SIZE_MB 的视频
  2. 只保留视频/音频流切片(丢弃 dbgi/djmd/tmcd 等私有数据流, 手机上传用不到)
  3. 原视频永远保留, 不删除; 切片校验通过后才移到原目录
  4. 已切过的文件(存在 xxx_part0001.mp4)自动跳过
  5. sync_album_backup.py 同步成功并推送手机后, 会删除本地切片

用法:
  python split_video.py --dry-run      # 只列出将要处理的文件
  python split_video.py                # 执行切片(保留原视频)
"""

import argparse
import json
import math
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from config import (
    SOURCE_BASE,
    FFMPEG_PATH,
    SPLIT_TARGET_SIZE_MB,
    SPLIT_MIN_SIZE_MB,
    SPLIT_SIZE_RATIO,
    SPLIT_MIN_DATE,
    SPLIT_TMP_BASE,
    VIDEO_EXTENSIONS,
)

LOG_DIR_NAME = "logs"
LOG_GLOB = "split_*.log"
LOG_KEEP = 7
TMP_SUFFIX = ".splitting"
PART_MARK = "_part"
STATUS_FILE = Path(__file__).resolve().parent / ".parts_synced.json"


class Tee:
    """同时写入控制台与日志文件"""

    def __init__(self, *streams):
        self.streams = streams

    def write(self, data: str) -> int:
        for s in self.streams:
            s.write(data)
            s.flush()
        return len(data)

    def flush(self) -> None:
        for s in self.streams:
            s.flush()


def setup_run_logging():
    log_dir = Path(__file__).resolve().parent / LOG_DIR_NAME
    log_dir.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    log_path = log_dir / f"split_{stamp}.log"
    log_file = open(log_path, "w", encoding="utf-8")
    sys.stdout = Tee(sys.__stdout__, log_file)
    sys.stderr = Tee(sys.__stderr__, log_file)
    print(f"日志文件: {log_path}")
    return log_path, log_file


def prune_old_logs(keep: int = LOG_KEEP) -> None:
    log_dir = Path(__file__).resolve().parent / LOG_DIR_NAME
    if not log_dir.is_dir():
        return
    files = sorted(log_dir.glob(LOG_GLOB), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in files[keep:]:
        try:
            old.unlink()
        except OSError:
            pass


def probe_file(path: Path) -> tuple[float | None, float | None]:
    """用 ffmpeg -i 解析时长(秒)和内容码率(视频+音频, bps)
    内容码率解析失败时返回 None (调用方回退用文件平均码率)"""
    result = subprocess.run(
        [str(FFMPEG_PATH), "-hide_banner", "-i", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    err = result.stderr
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", err)
    duration = None
    if m:
        duration = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))

    content_bps = 0
    found = False
    for sm in re.finditer(r"Stream #0:\d+.*?: (Video|Audio): .*?(\d+) kb/s", err):
        found = True
        content_bps += int(sm.group(2)) * 1000
    return duration, (content_bps if found and content_bps > 0 else None)


def has_existing_parts(path: Path) -> bool:
    """检查是否已有切片输出(说明之前切过)"""
    return any(path.parent.glob(f"{path.stem}{PART_MARK}*{path.suffix}"))


def folder_date(path: Path):
    """从文件所在目录名开头的 YYYYMMDD 解析日期 (如 '20260824家里装柜子...')
    找不到返回 None"""
    for d in path.parents:
        if d == SOURCE_BASE:
            break
        name = d.name
        if len(name) >= 8 and name[:8].isdigit():
            try:
                return datetime.strptime(name[:8], "%Y%m%d").date()
            except ValueError:
                continue
    return None


def _status_key(path: Path) -> str:
    """源视频的唯一标识: 相对路径 + 大小"""
    rel = path.relative_to(SOURCE_BASE).as_posix()
    return f"{rel}:{path.stat().st_size}"


def load_status() -> set:
    try:
        return set(json.loads(STATUS_FILE.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return set()


def mark_synced(videos: list) -> None:
    """记录切片已完成全流程(同步远端+推送手机+本地清理)的源视频"""
    status = load_status()
    for v in videos:
        status.add(_status_key(v))
    STATUS_FILE.write_text(json.dumps(sorted(status), ensure_ascii=False, indent=1),
                           encoding="utf-8")


def synced_videos() -> list:
    """所有超过阈值的源视频(不管是否已切), 用于全流程完成后统一标记"""
    return find_big_videos(ignore_parts=True)


def find_big_videos(ignore_parts: bool = False) -> list[Path]:
    """所有超过切片阈值且未切过的原视频(不限日期)
    供 rsync 排除和切片扫描共用"""
    videos = []
    for p in sorted(SOURCE_BASE.rglob("*")):
        if not p.is_file():
            continue
        if p.suffix.lower() not in VIDEO_EXTENSIONS:
            continue
        if PART_MARK in p.stem or p.stem.startswith("."):
            continue
        if p.stat().st_size <= SPLIT_MIN_SIZE_MB * 1024 * 1024:
            continue
        if not ignore_parts and has_existing_parts(p):
            continue
        videos.append(p)
    return videos


def collect_videos() -> list[Path]:
    """待切片的视频: 在 find_big_videos 基础上按目录日期过滤,
    并跳过已完成全流程的(状态文件记录)"""
    done = load_status()
    videos = []
    for p in find_big_videos():
        fdate = folder_date(p)
        if SPLIT_MIN_DATE and (fdate is None or fdate < SPLIT_MIN_DATE):
            continue
        if _status_key(p) in done:
            continue
        videos.append(p)
    return videos


def split_one(path: Path) -> bool:
    """切换单个视频(保留原视频), 返回是否成功"""
    if has_existing_parts(path):
        print(f"  已存在切片, 跳过: {path.name}")
        return True

    # 临时目录: 优先用 SSD 暂存盘(读写分盘提速), 否则切到源文件旁边
    if SPLIT_TMP_BASE:
        tmp_dir = SPLIT_TMP_BASE / (path.stem + TMP_SUFFIX)
        if tmp_dir.is_dir():
            print(f"  发现残留暂存目录, 清理: {tmp_dir}")
            shutil.rmtree(tmp_dir, ignore_errors=True)
    else:
        tmp_dir = path.with_name(path.name + TMP_SUFFIX)
        if tmp_dir.is_dir():
            print(f"  发现残留临时目录, 清理: {tmp_dir.name}")
            shutil.rmtree(tmp_dir, ignore_errors=True)

    size_bytes = path.stat().st_size
    duration, content_bps = probe_file(path)
    if not duration or duration <= 0:
        print(f"  无法读取时长, 跳过: {path.name}")
        return False

    # 切片只保留视频+音频流, 用内容码率估算每段时长(解析不到则用文件平均码率, 宁短勿大)
    file_bps = size_bytes * 8 / duration
    bps = content_bps if content_bps else file_bps
    seg_seconds = SPLIT_TARGET_SIZE_MB * 1024 * 1024 * 8 / bps * SPLIT_SIZE_RATIO
    expected_parts = max(2, math.ceil(duration / seg_seconds))
    expect_bytes = bps / 8 * duration

    print(f"  大小: {size_bytes / 1024 / 1024:.1f}MB, 时长: {duration:.1f}s, "
          f"文件码率: {file_bps / 1e6:.1f}Mbps, 内容码率: {bps / 1e6:.1f}Mbps")
    print(f"  每段约 {seg_seconds:.1f}s, 预计 {expected_parts} 片")

    tmp_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(FFMPEG_PATH), "-y", "-hide_banner", "-loglevel", "error", "-stats",
        "-i", str(path),
        # 只保留视频和音频, 丢弃 dbgi/djmd/tmcd 等私有数据流
        # (数据流手机播放/上传用不到, 且新版 ffmpeg mp4 复用器不支持写入)
        "-map", "0:v", "-map", "0:a", "-c", "copy",
        "-f", "segment", "-segment_time", f"{seg_seconds:.3f}",
        "-reset_timestamps", "1",
        str(tmp_dir / f"part%04d{path.suffix}"),
    ]
    print(f"  命令: {' '.join(cmd)}")
    if SPLIT_TMP_BASE:
        print(f"  暂存盘: {tmp_dir.anchor}")
    result = subprocess.run(cmd)

    if result.returncode != 0:
        print(f"  ffmpeg 失败(返回码 {result.returncode}): {path.name}")
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return False

    parts = sorted(tmp_dir.glob(f"part*{path.suffix}"))
    total_parts_size = sum(p.stat().st_size for p in parts)

    # 校验: 片数足够, 总大小接近按内容码率的估算值
    ok_count = len(parts) >= expected_parts - 1 and len(parts) >= 2
    ok_size = total_parts_size >= expect_bytes * 0.85
    if not (ok_count and ok_size):
        print(f"  校验失败(片数 {len(parts)}/{expected_parts}, "
              f"总大小 {total_parts_size / 1024 / 1024:.1f}MB/"
              f"{expect_bytes / 1024 / 1024:.1f}MB): {path.name}")
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return False

    # 分片移到原目录并重命名 (跨盘时为复制, 稍慢)
    if SPLIT_TMP_BASE:
        print(f"  校验通过, 从暂存盘拷回 {total_parts_size / 1024 / 1024:.0f}MB...")
    for i, part in enumerate(parts, start=1):
        dest = path.with_name(f"{path.stem}{PART_MARK}{i:04d}{path.suffix}")
        size_mb = part.stat().st_size / 1024 / 1024
        shutil.move(str(part), dest)
        print(f"  完成: {dest.name} ({size_mb:.1f}MB)")
    tmp_dir.rmdir()
    print(f"  保留原视频: {path.name}")
    return True


def list_pending_videos() -> list[Path]:
    """扫描并列出待切片的大视频 (dry-run 用)"""
    videos = collect_videos()
    if videos:
        print(f"找到 {len(videos)} 个大于 {SPLIT_MIN_SIZE_MB}MB 的视频:\n")
        total_size = 0
        for v in videos:
            total_size += v.stat().st_size
            print(f"  {v} ({v.stat().st_size / 1024 / 1024:.1f}MB)")
        print(f"\n合计: {total_size / 1024 / 1024 / 1024:.2f}GB")
    else:
        print("没有需要切片的大视频")
    return videos


def run_split() -> bool:
    """扫描并切片所有待处理的大视频, 返回是否全部成功
    (供 sync_album_backup.py 在同步前调用)"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] 开始视频切片...")
    print(f"源目录: {SOURCE_BASE}")
    date_note = f", 只处理 {SPLIT_MIN_DATE} 及之后新增的文件" if SPLIT_MIN_DATE else ""
    print(f"目标片段大小: {SPLIT_TARGET_SIZE_MB}MB, 只处理大于 {SPLIT_MIN_SIZE_MB}MB 的视频{date_note}")
    print(f"原视频保留不删除, 切片仅含视频+音频流")
    print("-" * 50)

    if not SOURCE_BASE.exists():
        print(f"错误：源目录 {SOURCE_BASE} 不存在")
        return False

    videos = collect_videos()
    if not videos:
        print("没有需要切片的大视频")
        return True

    list_pending_videos()
    print()

    success, failed = 0, 0
    for i, v in enumerate(videos, start=1):
        print(f"\n[{i}/{len(videos)}] {v}")
        try:
            if split_one(v):
                success += 1
            else:
                failed += 1
        except Exception as e:
            print(f"  异常: {e}")
            failed += 1

    print("\n" + "-" * 50)
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 切片完成: 成功 {success}, 失败 {failed}")
    return failed == 0


def delete_local_parts() -> int:
    """删除本地所有切片文件(远端备份和手机推送完成后调用), 返回删除数量"""
    count = 0
    for p in SOURCE_BASE.rglob(f"*{PART_MARK}*"):
        if not p.is_file() or p.suffix.lower() not in VIDEO_EXTENSIONS:
            continue
        try:
            p.unlink()
            count += 1
        except OSError as e:
            print(f"  删除失败: {p} - {e}")
    return count


def finish_sync() -> int:
    """全流程成功后调用: 标记大视频为已完成, 删除本地切片, 返回删除数量
    (标记后下次运行不会重新切片, 源视频保留本地)"""
    mark_synced(synced_videos())
    return delete_local_parts()


def main():
    parser = argparse.ArgumentParser(description="把大视频切成约256MB片段(保留原视频)")
    parser.add_argument("--dry-run", action="store_true", help="只列出将要处理的文件, 不实际执行")
    args = parser.parse_args()

    if not SOURCE_BASE.exists():
        print(f"错误：源目录 {SOURCE_BASE} 不存在")
        return 1

    if args.dry_run:
        list_pending_videos()
        print("\n[dry-run] 未实际执行")
        return 0

    ok = run_split()
    return 0 if ok else 1


if __name__ == "__main__":
    _, log_fp = setup_run_logging()
    try:
        code = main()
    finally:
        sys.stdout = sys.__stdout__
        sys.stderr = sys.__stderr__
        log_fp.close()
        prune_old_logs()
    raise SystemExit(code)
