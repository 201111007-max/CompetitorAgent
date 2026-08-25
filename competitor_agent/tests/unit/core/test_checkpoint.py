"""问题 9 修复测试：checkpoint 原子写入 + 并发锁 + 备份回退

覆盖设计文档 09 验证方式：
- 单元：写入后文件完整可读；模拟写入中断不损坏原文件
- 集成：多线程并发写同一 checkpoint，最终文件完整
- 可靠性：主文件损坏回退 .bak；跨进程文件锁串行化写
"""

from __future__ import annotations

import json
import threading
import time

import pytest

from competitor_agent.core.checkpoint import (
    _CHECKPOINT_DIR,
    Checkpoint,
    CheckpointLock,
    _atomic_write,
    _backup_path,
    _checkpoint_path,
    _session_locks,
    delete_checkpoint,
    load_checkpoint,
    save_checkpoint,
)


@pytest.fixture(autouse=True)
def _isolated_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("competitor_agent.core.checkpoint._CHECKPOINT_DIR", tmp_path)
    _session_locks.clear()
    yield
    _session_locks.clear()


def _save(session_id: str, marker: str = "tried", **overrides) -> Checkpoint:
    return save_checkpoint(
        session_id=session_id,
        task="分析 Cursor",
        competitor_name="Cursor",
        gaps=[],
        dimension_results=[],
        iterations_used=3,
        max_iterations=10,
        sources_tried=[marker],
        **overrides,
    )


class TestAtomicWrite:
    def test_roundtrip_and_no_stale_tmp(self, tmp_path):
        path = tmp_path / "s1.json"
        _atomic_write(path, {"a": 1, "b": [2, 3]})
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data == {"a": 1, "b": [2, 3]}
        assert list(tmp_path.glob("*.tmp")) == []
        assert list(tmp_path.glob(".*.tmp")) == []

    def test_interrupted_write_keeps_original(self, tmp_path):
        path = tmp_path / "s2.json"
        _atomic_write(path, {"version": 1})
        stale = tmp_path / ".s2.1234.deadbeef.tmp"
        stale.write_text("{broken json", encoding="utf-8")
        _atomic_write(path, {"version": 2})
        assert json.loads(path.read_text(encoding="utf-8")) == {"version": 2}
        assert not stale.exists(), "陈旧 tmp 应被清理"

    def test_update_creates_backup(self, tmp_path):
        path = tmp_path / "s3.json"
        _atomic_write(path, {"version": 1})
        _atomic_write(path, {"version": 2})
        bak = _backup_path(path)
        assert bak.exists()
        assert json.loads(bak.read_text(encoding="utf-8")) == {"version": 1}


class TestSaveLoadDelete:
    @pytest.mark.parametrize("session_id", ["cp-roundtrip-1", "cp-roundtrip-2"])
    def test_save_load_roundtrip(self, session_id):
        _save(session_id)
        try:
            assert _checkpoint_path(session_id).exists()
            cp = load_checkpoint(session_id)
            assert cp is not None
            assert cp.session_id == session_id
            assert cp.sources_tried == ["tried"]
            assert cp.iterations_used == 3
        finally:
            delete_checkpoint(session_id)
        assert not _checkpoint_path(session_id).exists()

    def test_load_falls_back_to_backup(self, tmp_path):
        session_id = "cp-bak"
        path = _checkpoint_path(session_id)
        _save(session_id, marker="new")
        _atomic_write(
            _backup_path(path),
            {
                "session_id": session_id,
                "task": "t",
                "competitor_name": "Cursor",
                "created_at": "2026-01-01",
                "updated_at": "2026-01-01",
                "gaps": [],
                "dimension_results": [],
                "iterations_used": 1,
                "max_iterations": 10,
                "sources_tried": ["backup"],
            },
        )
        path.write_text("{corrupted json", encoding="utf-8")
        try:
            cp = load_checkpoint(session_id)
            assert cp is not None
            assert cp.sources_tried == ["backup"]
        finally:
            delete_checkpoint(session_id)

    def test_load_backup_when_main_missing(self, tmp_path):
        session_id = "cp-missing"
        path = _checkpoint_path(session_id)
        _atomic_write(
            _backup_path(path),
            {
                "session_id": session_id,
                "task": "t",
                "competitor_name": "Cursor",
                "created_at": "2026-01-01",
                "updated_at": "2026-01-01",
                "gaps": [],
                "dimension_results": [],
                "iterations_used": 1,
                "max_iterations": 10,
                "sources_tried": ["backup"],
            },
        )
        try:
            cp = load_checkpoint(session_id)
            assert cp is not None
            assert cp.sources_tried == ["backup"]
        finally:
            delete_checkpoint(session_id)

    def test_delete_removes_bak_and_lock_and_tmp(self, tmp_path):
        session_id = "cp-clean"
        _save(session_id)
        with CheckpointLock(_checkpoint_path(session_id)):
            pass
        path = _checkpoint_path(session_id)
        stale = tmp_path / f".{path.stem}.1234.deadbeef.tmp"
        stale.write_text("x", encoding="utf-8")
        delete_checkpoint(session_id)
        assert not path.exists()
        assert not _backup_path(path).exists()
        assert not path.with_suffix(".json.lock").exists()
        assert not stale.exists()


class TestConcurrency:
    def test_concurrent_thread_writes_stay_consistent(self):
        session_id = "cp-concurrent"
        markers = [f"writer-{i}" for i in range(8)]
        barrier = threading.Barrier(len(markers))
        errors: list[Exception] = []

        def _writer(marker: str) -> None:
            try:
                barrier.wait(timeout=5)
                _save(session_id, marker=marker)
            except Exception as e:  # noqa: BLE001 - 收集子线程失败供主线程断言
                errors.append(e)

        threads = [threading.Thread(target=_writer, args=(m,)) for m in markers]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)

        try:
            assert not errors
            cp = load_checkpoint(session_id)
            assert cp is not None
            assert cp.sources_tried[0] in markers
            assert cp.iterations_used == 3
            baked = json.loads(_checkpoint_path(session_id).read_text(encoding="utf-8"))
            assert baked["session_id"] == session_id
        finally:
            delete_checkpoint(session_id)
        assert list(_CHECKPOINT_DIR.glob(".*.tmp")) == []

    def test_cross_process_lock_serializes(self, tmp_path):
        path = tmp_path / "lock.json"
        order: list[str] = []
        a_holds = threading.Event()

        def _a() -> None:
            with CheckpointLock(path):
                order.append("A-enter")
                a_holds.set()
                time.sleep(0.3)
                order.append("A-exit")

        def _b() -> None:
            with CheckpointLock(path):
                order.append("B-enter")

        ta = threading.Thread(target=_a)
        tb = threading.Thread(target=_b)
        ta.start()
        assert a_holds.wait(timeout=5), "A 应能获得锁"
        tb.start()
        time.sleep(0.1)
        assert "B-enter" not in order, "A 持有锁时 B 应阻塞"
        ta.join(timeout=5)
        tb.join(timeout=5)
        assert order == ["A-enter", "A-exit", "B-enter"]

    def test_sequential_lock_acquire_release_ok(self, tmp_path):
        path = tmp_path / "seq.json"
        lock_file = path.with_suffix(".json.lock")
        with CheckpointLock(path):
            assert lock_file.exists()
        with CheckpointLock(path):  # 释放后再获取应无死锁
            assert lock_file.exists()
