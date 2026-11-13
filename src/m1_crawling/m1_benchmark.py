"""Đo benchmark chung cho M1: wall time, RAM (cả cây tiến trình), disk, theo từng pha.

Hai cách dùng.

1) Trong notebook Colab (khuyên dùng, vì phần Semantic Scholar chạy trong notebook):

    from m1_benchmark import Benchmark
    with Benchmark(dirs=["/content/work", "/content/drive/MyDrive/bench_out"],
                   meta={"ids": "sample_100.txt", "workers": 1, "cache": "empty"}) as bm:
        bm.mark("discovery_and_arxiv_start")
        ...   # chạy bước arXiv (vd !python -m src.m1_crawling.run_arxiv_only ...)
        bm.mark("arxiv_done")
        ...   # chạy bước Semantic Scholar
        bm.mark("s2_done")
        ...   # tích hợp, xuất bảng, validation
    bm.save("bench_m1.json", "bench_m1_series.csv")

2) Dòng lệnh, bọc một lệnh duy nhất:

    python m1_benchmark.py --dirs /content/work --out bench.json --series series.csv -- python my_pipeline.py

Quy ước đo (ghi vào JSON để đưa vào báo cáo):
  - RAM: tổng RSS của tiến trình gốc và mọi tiến trình con, lấy mẫu mỗi --interval giây
    (mặc định 0.5). Trong notebook, tiến trình gốc là kernel Python. Peak = đỉnh của tổng
    đồng thời, KHÔNG phải tổng các peak riêng. Average = trung bình các mẫu (chu kỳ đều).
  - Disk: tổng bytes các file trong các thư mục --dirs, lấy mẫu mỗi --disk-interval giây
    (mặc định 5). Peak là đỉnh của tổng đó trong lúc chạy; thêm bytes lúc bắt đầu và kết thúc.
    Thư mục nào không liệt kê sẽ không được tính, nên hãy liệt kê đủ (làm việc, cache,
    checkpoint, output, Drive).
  - Đơn vị gốc là bytes. MiB = bytes / 1048576.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import platform
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import psutil


def dir_bytes(path: str) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


class Benchmark:
    def __init__(self, dirs=None, interval: float = 0.5, disk_interval: float = 5.0,
                 root_pid: int | None = None, meta: dict | None = None):
        self.dirs = [str(d) for d in (dirs or [])]
        self.interval = interval
        self.disk_interval = disk_interval
        self.root = psutil.Process(root_pid or os.getpid())
        self.meta = dict(meta or {})
        self.marks: list[tuple[str, float]] = []
        self.series: list[dict] = []
        self.disk_series: list[dict] = []
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self.result: dict | None = None

    # ---- sampling
    def _tree_rss(self) -> int:
        total = 0
        try:
            procs = [self.root] + self.root.children(recursive=True)
        except psutil.Error:
            return 0
        for p in procs:
            try:
                total += p.memory_info().rss
            except psutil.Error:
                pass
        return total

    def _ram_loop(self):
        while not self._stop.is_set():
            self.series.append({"t": time.perf_counter() - self._t0,
                                "tree_rss_bytes": self._tree_rss(),
                                "system_used_bytes": psutil.virtual_memory().used})
            self._stop.wait(self.interval)

    def _disk_loop(self):
        while not self._stop.is_set():
            per = {d: dir_bytes(d) for d in self.dirs}
            self.disk_series.append({"t": time.perf_counter() - self._t0,
                                     "total_bytes": sum(per.values()), "per_dir": per})
            self._stop.wait(self.disk_interval)

    # ---- control
    def mark(self, name: str):
        self.marks.append((name, time.perf_counter() - self._t0))

    def start(self):
        self._start_utc = datetime.now(timezone.utc).isoformat()
        self._disk_start = {d: dir_bytes(d) for d in self.dirs}
        self._t0 = time.perf_counter()
        self._threads = [threading.Thread(target=self._ram_loop, daemon=True)]
        if self.dirs:
            self._threads.append(threading.Thread(target=self._disk_loop, daemon=True))
        for t in self._threads:
            t.start()
        return self

    def stop(self) -> dict:
        wall = time.perf_counter() - self._t0
        self._stop.set()
        for t in self._threads:
            t.join(timeout=30)
        end_per = {d: dir_bytes(d) for d in self.dirs}
        rss = [s["tree_rss_bytes"] for s in self.series] or [0]
        sysu = [s["system_used_bytes"] for s in self.series] or [0]
        disk_totals = [s["total_bytes"] for s in self.disk_series] + [sum(self._disk_start.values()), sum(end_per.values())]
        phases, prev = {}, 0.0
        for name, t in self.marks:
            phases[name] = {"at_seconds": round(t, 3), "since_previous_seconds": round(t - prev, 3)}
            prev = t
        self.result = {
            "started_utc": self._start_utc,
            "wall_seconds": round(wall, 3),
            "phases": phases,
            "ram": {
                "scope": f"tổng RSS cây tiến trình (gốc pid {self.root.pid} và tiến trình con)",
                "interval_seconds": self.interval, "samples": len(rss),
                "peak_tree_rss_bytes": max(rss), "average_tree_rss_bytes": round(sum(rss) / len(rss)),
                "peak_system_used_bytes": max(sysu), "average_system_used_bytes": round(sum(sysu) / len(sysu)),
            },
            "disk": {
                "dirs": self.dirs, "interval_seconds": self.disk_interval,
                "samples": len(self.disk_series),
                "start_bytes": sum(self._disk_start.values()), "final_bytes": sum(end_per.values()),
                "peak_total_bytes_sampled": max(disk_totals) if disk_totals else 0,
                "final_per_dir_bytes": end_per,
                "note": "Peak là đỉnh của các mẫu; có thể bỏ lỡ đỉnh ngắn hơn chu kỳ lấy mẫu.",
            },
            "environment": {"python": sys.version.split()[0], "platform": platform.platform(),
                            "cpu_count": psutil.cpu_count(), "total_ram_bytes": psutil.virtual_memory().total},
            "meta": self.meta,
        }
        return self.result

    def save(self, json_path: str, series_csv: str | None = None):
        Path(json_path).write_text(json.dumps(self.result, ensure_ascii=False, indent=2), encoding="utf-8")
        if series_csv:
            with open(series_csv, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=["t", "tree_rss_bytes", "system_used_bytes"])
                w.writeheader()
                w.writerows(self.series)

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description="Đo wall time, RAM, disk cho một lệnh")
    ap.add_argument("--dirs", nargs="*", default=[])
    ap.add_argument("--interval", type=float, default=0.5)
    ap.add_argument("--disk-interval", type=float, default=5.0)
    ap.add_argument("--out", default="bench.json")
    ap.add_argument("--series", default=None)
    ap.add_argument("--meta", nargs="*", default=[], help="key=value")
    ap.add_argument("cmd", nargs=argparse.REMAINDER)
    a = ap.parse_args()
    cmd = a.cmd[1:] if a.cmd and a.cmd[0] == "--" else a.cmd
    if not cmd:
        ap.error("thiếu lệnh cần đo (đặt sau dấu --)")
    proc = subprocess.Popen(cmd)
    bm = Benchmark(a.dirs, a.interval, a.disk_interval, root_pid=proc.pid,
                   meta=dict(m.split("=", 1) for m in a.meta)).start()
    code = proc.wait()
    res = bm.stop()
    res["exit_code"] = code
    res["command"] = cmd
    bm.save(a.out, a.series)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
