# 设计文档 09 — checkpoint 写无原子性/锁

> 对应 `implementation_plan.md` 第 11 节问题 9（P2）

## 1. 问题现状

- `checkpoint.py:118-120` 直接 `open(path, "w")` 覆盖写，**无临时文件 + rename 原子替换**。若进程在写一半时崩溃，会留下损坏 JSON（`load_checkpoint` 只能捕获后返回 None，`checkpoint.py:130-136`，数据丢失）。
- **无跨进程锁**，多进程/多线程并发写同一 session 会互相覆盖。

## 2. 目标设计

1. **原子写入**：临时文件 + `os.replace()` 原子替换，崩溃不损坏原文件。
2. **并发安全**：进程内锁 + 跨进程文件锁，防止并发写互相覆盖。
3. 保留旧版本备份，崩溃可恢复。

## 3. 模块/接口设计

### 3.1 原子写入（`checkpoint.py`）

```python
def _atomic_write(path: Path, data: dict):
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())      # 刷盘
    os.replace(tmp, path)          # 原子替换
```

### 3.2 进程内锁

- 用 `threading.Lock` 保护同一进程内对同一 checkpoint 的写。

### 3.3 跨进程文件锁

- 用 `fcntl`（Unix）/ `msvcrt`（Windows）对 `.lock` 文件加锁，防止多进程并发写。

```python
class CheckpointLock:
    def __enter__(self):
        self._lock = open(path.with_suffix(".lock"), "w")
        msvcrt.locking(self._lock.fileno(), msvcrt.LK_LOCK, 1)  # Windows
        return self
    def __exit__(self, *a):
        msvcrt.locking(self._lock.fileno(), msvcrt.LK_UNLCK, 1)
        self._lock.close()
```

### 3.4 备份

- 写入前将旧文件备份为 `.bak`，`load_checkpoint` 主文件损坏时尝试 `.bak`。

## 4. 接入方式

```
save_checkpoint(data)
  → 进程内锁 + 跨进程文件锁
  → _atomic_write(tmp) → os.replace
  → 备份旧文件 .bak
load_checkpoint()
  → 主文件损坏 → 尝试 .bak
```

## 5. 验证方式

- **单元测试**：写入后文件完整可读；模拟崩溃（写入中断）不损坏原文件。
- **集成测试**：多线程并发写同一 checkpoint，最终文件完整。
- **端到端**：分析中断后 `resume()` 能从最近 checkpoint 恢复。

## 6. 实现优先级与工作量

- 优先级：**中**（P2，可靠性）。
- 工作量：约 0.5-1 天。
- 建议先做原子写入（收益最大），再做跨进程锁。
