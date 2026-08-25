"""MCP Server — GitHub API 工具

通过 GitHub REST API 查询仓库信息（stars/releases/commits）。
Token 经 SecretVault 获取，无需硬编码。
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from competitor_agent.secret_vault import vault

logger = logging.getLogger("competitor_agent.mcp_server.tools.github_tools")

_GITHUB_API = "https://api.github.com"


def _headers() -> dict[str, str]:
    """构造请求头（含可选的 GitHub Token）"""
    token = vault.get("GITHUB_TOKEN", owner="mcp_server.github_tools")
    headers: dict[str, str] = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "competitor_agent/0.1.0",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _get(path: str) -> dict[str, Any] | list[Any]:
    """GitHub API GET 请求"""
    resp = httpx.get(
        f"{_GITHUB_API}{path}",
        headers=_headers(),
        timeout=15.0,
    )
    resp.raise_for_status()
    return resp.json()


def github_stars(repo: str) -> str:
    """查询 GitHub 仓库的 star 数"""
    try:
        data = _get(f"/repos/{repo}")
        if isinstance(data, dict):
            return (
                f"## {repo}\n\n"
                f"- Stars: {data.get('stargazers_count', 'N/A')}\n"
                f"- Forks: {data.get('forks_count', 'N/A')}\n"
                f"- 语言: {data.get('language', 'N/A')}\n"
                f"- 描述: {data.get('description', 'N/A')}\n"
                f"- 最近更新: {data.get('updated_at', 'N/A')}\n"
                f"- 开源许可: {data.get('license', {}).get('spdx_id', 'N/A') if data.get('license') else 'N/A'}\n"
            )
        return f"⚠ 无法解析 {repo} 的信息"
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return f"⚠ 仓库 {repo} 不存在"
        if e.response.status_code == 403:
            return "⚠ API 限流，请配置 GITHUB_TOKEN"
        return f"⚠ HTTP {e.response.status_code}: {repo}"
    except httpx.RequestError as e:
        return f"⚠ 请求失败: {e}"
    except Exception as e:  # noqa: BLE001
        logger.warning("github_stars(%s) 异常: %s", repo, e)
        return f"⚠ 查询异常: {e}"


def github_releases(repo: str, limit: int = 5) -> str:
    """查询 GitHub 仓库的发布版本"""
    try:
        data = _get(f"/repos/{repo}/releases?per_page={limit}")
        if isinstance(data, list) and data:
            lines = [f"## {repo} 版本发布（最近 {len(data)} 个）\n"]
            for r in data:
                tag = r.get("tag_name", "N/A")
                name = r.get("name", "") or tag
                published = r.get("published_at", "N/A")[:10]
                body = (r.get("body", "") or "")[:200].replace("\n", " ").strip()
                lines.append(f"- **{name}** ({published})\n  {body}")
            return "\n".join(lines)
        return f"{repo} 暂无公开版本发布"
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return f"⚠ 仓库 {repo} 不存在"
        return f"⚠ HTTP {e.response.status_code}"
    except httpx.RequestError as e:
        return f"⚠ 请求失败: {e}"
    except Exception as e:  # noqa: BLE001
        logger.warning("github_releases(%s) 异常: %s", repo, e)
        return f"⚠ 查询异常: {e}"


def github_commits(repo: str, days: int = 30) -> str:
    """查询 GitHub 仓库近期提交"""
    try:
        data = _get(f"/repos/{repo}/commits?per_page=20")
        if isinstance(data, list) and data:
            lines = [f"## {repo} 近期提交（最近 {len(data)} 条）\n"]
            for c in data:
                commit = c.get("commit", {})
                author = commit.get("author", {})
                message = (commit.get("message", "") or "").split("\n")[0][:80]
                date = (author.get("date", "") or "")[:10]
                lines.append(f"- {date} {message}")
            return "\n".join(lines)
        return f"{repo} 暂无提交记录"
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return f"⚠ 仓库 {repo} 不存在"
        return f"⚠ HTTP {e.response.status_code}"
    except httpx.RequestError as e:
        return f"⚠ 请求失败: {e}"
    except Exception as e:  # noqa: BLE001
        logger.warning("github_commits(%s) 异常: %s", repo, e)
        return f"⚠ 查询异常: {e}"
