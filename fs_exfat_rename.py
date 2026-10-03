#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
修 fs/exfat 与 MTK connectivity 驱动的全局符号撞名。

背景（Run#16 build.log:6019-6021 实测）：
    ld.lld: error: duplicate symbol: buf_lock
    >>> defined at exfat_cache.c:703   fs/exfat/exfat_cache.o
    >>>            stp_uart.c   drivers/misc/mediatek/connectivity/common/common_main/linux/stp_uart.o

原因：exfat 的 `void buf_lock(struct super_block*, u32)` 是函数，
     MTK stp_uart.c:119 的 `spinlock_t buf_lock;` 是全局变量，
     两者都进 built-in.o，链接器撞名。

为什么不加 static：
    本地分析发现 exfat 有 48 个函数是【跨文件共享】的
    （exfat_cache.c 定义 + exfat_core.c 调用）。
    加 static 会触发 "static declaration follows non-static declaration"，
    并在调用点报 undefined —— Run#17 已经验证过这条路走不通。

所以采用改名：加 exfat_ 前缀，保留全局可见性，只改名字不改链接属性。
注意必须【同时】改 .c 和 .h（含调用点），否则链接期找不到符号。
"""

import glob
import os
import re
import sys

# 需要改名的符号（本地分析 fs/exfat 得出：跨文件共享，且都是过短的通用名）
# 已经是 exfat_ 前头的保持原样。
NAMES = [
    # exfat_cache.c 定义，exfat_core.c / exfat_api.c 调用
    "buf_lock", "buf_unlock", "buf_modify", "buf_release",
    "buf_release_all", "buf_sync", "buf_init", "buf_shutdown",
    # exfat_core.c 定义，exfat_api.c 调用
    "fs_sync", "fs_error", "fs_set_vol_flags", "fs_init", "fs_shutdown",
    # exfat_blkdev.c 定义，exfat_core.c 调用
    "bdev_open", "bdev_close", "bdev_read", "bdev_write",
    "bdev_init", "bdev_shutdown", "bdev_sync",
]

EXFAT_DIR = os.environ.get("EXFAT_DIR", "fs/exfat")


def main():
    if not os.path.isdir(EXFAT_DIR):
        sys.stderr.write("!! 找不到 exfat 目录: %s\n" % EXFAT_DIR)
        return 1

    files = sorted(glob.glob(os.path.join(EXFAT_DIR, "*.c"))) + \
            sorted(glob.glob(os.path.join(EXFAT_DIR, "*.h")))
    if not files:
        sys.stderr.write("!! %s 下没有 .c/.h 文件\n" % EXFAT_DIR)
        return 1

    total_hits = 0
    changed = []
    for path in files:
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            continue

        original = text
        hits = 0
        for name in NAMES:
            new = "exfat_" + name
            pattern = r"\b" + re.escape(name) + r"\b"
            text, n = re.subn(pattern, new, text)
            hits += n

        if text != original:
            try:
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(text)
                changed.append((path, hits))
                total_hits += hits
                print("  patched %-40s (%d 处)" % (path, hits))
            except OSError as exc:
                sys.stderr.write("!! 写入失败 %s: %s\n" % (path, exc))

    print("== 改名完成: %d 个文件, %d 处替换 ==" % (len(changed), total_hits))

    # 自检：确认不再有裸 buf_lock
    leftovers = []
    for path in files:
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                for i, line in enumerate(fh, 1):
                    if re.search(r"(?<!exfat_)\bbuf_lock\b", line):
                        leftovers.append("%s:%d" % (path, i))
        except OSError:
            pass
    if leftovers:
        sys.stderr.write("!! 仍有未改名的 buf_lock: %s\n" % leftovers[:5])
        return 2

    print("== 自检通过: 无裸 buf_lock 残留 ==")
    return 0


if __name__ == "__main__":
    sys.exit(main())
