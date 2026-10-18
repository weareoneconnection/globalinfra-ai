#!/usr/bin/env python3
"""Build a deterministic AI Outbound competition submission archive."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SUBMISSION = ROOT / "submission"
FINAL = SUBMISSION / "final"
PACKAGE_ROOT = "GlobalInfra_AI_AI出海赛道_提交材料"
ZIP_PATH = FINAL / "GlobalInfra_AI_交融杯_AI出海赛道_提交包.zip"
MANIFEST_PATH = FINAL / "FINAL_SUBMISSION_MANIFEST.json"
HASH_PATH = FINAL / "SHA256SUMS.txt"
RELEASE_TIME = "2026-10-18T21:53:31+08:00"
ZIP_TIME = (2026, 10, 18, 21, 53, 30)

FILES = [
    FINAL / "GlobalInfra_AI_AI出海应用设计报告.docx",
    FINAL / "GlobalInfra_AI_AI出海应用设计报告.pdf",
    SUBMISSION / "02_五分钟演示脚本与分镜.md",
    SUBMISSION / "03_证据真实性与数据边界清单.md",
    SUBMISSION / "04_模型与算法评测报告.md",
    SUBMISSION / "05_一键复现与开源说明.md",
    SUBMISSION / "06_最终提交检查表.md",
    SUBMISSION / "07_参赛版本发布说明.md",
    SUBMISSION / "08_第三方组件清单.md",
    SUBMISSION / "README.md",
    ROOT / "LICENSE",
    ROOT / "NOTICE.md",
    ROOT / "NOTICE.zh-CN.md",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def archive_name(path: Path) -> str:
    if path.parent == FINAL:
        relative = Path(path.name)
    elif path.parent == ROOT:
        relative = Path("开源许可") / path.name
    else:
        relative = path.relative_to(SUBMISSION)
    return f"{PACKAGE_ROOT}/{relative.as_posix()}"


def build() -> Path:
    FINAL.mkdir(parents=True, exist_ok=True)
    missing = [str(path) for path in FILES if not path.is_file()]
    if missing:
        raise FileNotFoundError("Missing submission files:\n" + "\n".join(missing))

    entries = [
        {
            "path": archive_name(path),
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
        }
        for path in FILES
    ]
    manifest = {
        "package": "GlobalInfra AI 第二届交融杯 AI出海赛道提交材料",
        "release": "V5.1 最终参赛提交版",
        "release_time": RELEASE_TIME,
        "data_boundary": "系统、评测与数字孪生示例使用合成数据；尚无真实客户生产验收记录。",
        "manual_items_remaining": [
            "完整团队成员",
            "平台报名编号",
            "约四分钟且不超过五分钟的最终录屏",
            "平台提交回执",
        ],
        "files": entries,
    }
    MANIFEST_PATH.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    HASH_PATH.write_text(
        "".join(f"{entry['sha256']}  {entry['path']}\n" for entry in entries),
        encoding="utf-8",
    )

    package_files = FILES + [MANIFEST_PATH, HASH_PATH]
    with zipfile.ZipFile(ZIP_PATH, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in package_files:
            info = zipfile.ZipInfo(archive_name(path), ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes())
    return ZIP_PATH


if __name__ == "__main__":
    print(build())

