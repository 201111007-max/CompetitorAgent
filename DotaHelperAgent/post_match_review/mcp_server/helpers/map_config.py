"""地图/区域配置与几何计算辅助函数

从 dota2_fastmcp.py 提取的区域匹配、几何计算、地图路径解析等功能。
"""

import json
import math
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

# 资源目录：所有静态资源相对于本模块的 resources/ 目录
RESOURCES_DIR = Path(__file__).parent.parent / "resources"
MAPS_DIR = RESOURCES_DIR / "maps"
MAP_VERSION = "740"


def format_time_mmss(seconds: int) -> str:
    """格式化时间为 M:SS（支持负数）

    Args:
        seconds: 秒数

    Returns:
        str: 格式化的时间字符串
    """
    sign = "-" if seconds < 0 else ""
    seconds = abs(int(seconds))
    minutes, secs = divmod(seconds, 60)
    return f"{sign}{minutes}:{secs:02d}"


def load_region_template() -> List[Dict[str, Any]]:
    """加载地图区域模板

    Returns:
        List[Dict[str, Any]]: 区域列表
    """
    template_path = RESOURCES_DIR / "ward_region_template.json"
    if not template_path.exists():
        return []
    try:
        with open(str(template_path), "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return []
    regions = data.get("regions")
    if regions is not None:
        return regions
    merged_regions: List[Dict[str, Any]] = []
    for side in ("radiant", "dire"):
        for key, info in data.get(side, {}).items():
            merged = dict(info)
            merged.setdefault("key", key)
            merged.setdefault("side", side)
            merged_regions.append(merged)
    return merged_regions


def point_in_bbox(x: float, y: float, area: Dict[str, Any]) -> bool:
    """判断点是否在矩形区域内

    Args:
        x: X 坐标
        y: Y 坐标
        area: 矩形区域定义 (x_min, x_max, y_min, y_max)

    Returns:
        bool: 是否在区域内
    """
    return (
        x >= float(area.get("x_min", 0))
        and x <= float(area.get("x_max", 0))
        and y >= float(area.get("y_min", 0))
        and y <= float(area.get("y_max", 0))
    )


def point_in_polygon(x: float, y: float, points: List[List[float]]) -> bool:
    """判断点是否在多边形内部（射线法）

    Args:
        x: X 坐标
        y: Y 坐标
        points: 多边形顶点列表

    Returns:
        bool: 是否在多边形内
    """
    inside = False
    if not points:
        return False
    j = len(points) - 1
    for i in range(len(points)):
        xi, yi = points[i]
        xj, yj = points[j]
        intersect = (yi > y) != (yj > y) and (
            x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-9) + xi
        )
        if intersect:
            inside = not inside
        j = i
    return inside


def polygon_area(points: List[List[float]]) -> float:
    """计算多边形面积

    Args:
        points: 多边形顶点列表

    Returns:
        float: 面积值
    """
    if len(points) < 3:
        return float("inf")
    area = 0.0
    j = len(points) - 1
    for i in range(len(points)):
        xi, yi = points[i]
        xj, yj = points[j]
        area += (xj + xi) * (yj - yi)
        j = i
    return abs(area) / 2.0


def distance_point_to_segment(
    px: float,
    py: float,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
) -> float:
    """计算点到线段的距离

    Args:
        px, py: 点坐标
        x1, y1: 线段起点
        x2, y2: 线段终点

    Returns:
        float: 点到线段的最短距离
    """
    dx = x2 - x1
    dy = y2 - y1
    if dx == 0 and dy == 0:
        return math.hypot(px - x1, py - y1)
    t = ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    proj_x = x1 + t * dx
    proj_y = y1 + t * dy
    return math.hypot(px - proj_x, py - proj_y)


def distance_to_bbox(x: float, y: float, area: Dict[str, Any]) -> float:
    """计算点到矩形的距离

    Args:
        x: X 坐标
        y: Y 坐标
        area: 矩形区域定义

    Returns:
        float: 点到矩形的最短距离
    """
    x_min = float(area.get("x_min", 0))
    x_max = float(area.get("x_max", 0))
    y_min = float(area.get("y_min", 0))
    y_max = float(area.get("y_max", 0))
    dx = 0.0
    if x < x_min:
        dx = x_min - x
    elif x > x_max:
        dx = x - x_max
    dy = 0.0
    if y < y_min:
        dy = y_min - y
    elif y > y_max:
        dy = y - y_max
    return math.hypot(dx, dy)


def distance_to_polygon(x: float, y: float, points: List[List[float]]) -> float:
    """计算点到多边形的距离

    Args:
        x: X 坐标
        y: Y 坐标
        points: 多边形顶点列表

    Returns:
        float: 点到多边形的最短距离
    """
    if not points:
        return float("inf")
    if point_in_polygon(x, y, points):
        return 0.0
    min_dist = float("inf")
    j = len(points) - 1
    for i in range(len(points)):
        x1, y1 = points[j]
        x2, y2 = points[i]
        min_dist = min(min_dist, distance_point_to_segment(x, y, x1, y1, x2, y2))
        j = i
    return min_dist


def match_region_with_distance(
    x: float,
    y: float,
    regions: List[Dict[str, Any]],
    allow_nearest: bool = True,
) -> Tuple[Optional[str], Optional[str], List[str], float, bool]:
    """匹配点所在的地图区域（带距离信息）

    Args:
        x: X 坐标
        y: Y 坐标
        regions: 区域列表
        allow_nearest: 是否允许最近区域匹配

    Returns:
        Tuple[primary_key, primary_label, labels, distance, is_matched]
    """
    matches: List[Tuple[float, str, str]] = []
    for region in regions:
        label = str(region.get("label") or region.get("key") or "未知区域")
        key = str(region.get("key") or label)
        for area in region.get("areas", []):
            area_type = area.get("type")
            if area_type == "bbox":
                if point_in_bbox(x, y, area):
                    size = abs(
                        (float(area.get("x_max", 0)) - float(area.get("x_min", 0)))
                        * (float(area.get("y_max", 0)) - float(area.get("y_min", 0)))
                    )
                    matches.append((size, key, label))
            elif area_type == "polygon":
                pts = area.get("points") or []
                if point_in_polygon(x, y, pts):
                    size = polygon_area(pts)
                    matches.append((size, key, label))
    if matches:
        matches.sort(key=lambda item: item[0])
        primary_key = matches[0][1]
        primary_label = matches[0][2]
        labels = [item[2] for item in matches]
        return primary_key, primary_label, labels, 0.0, True
    if not allow_nearest:
        return None, None, [], float("inf"), False
    nearest_key: Optional[str] = None
    nearest_label: Optional[str] = None
    nearest_dist = float("inf")
    for region in regions:
        label = str(region.get("label") or region.get("key") or "未知区域")
        key = str(region.get("key") or label)
        for area in region.get("areas", []):
            area_type = area.get("type")
            if area_type == "bbox":
                dist = distance_to_bbox(x, y, area)
            elif area_type == "polygon":
                pts = area.get("points") or []
                dist = distance_to_polygon(x, y, pts)
            else:
                continue
            if dist < nearest_dist:
                nearest_dist = dist
                nearest_key = key
                nearest_label = label
    if nearest_key is None:
        return None, None, [], float("inf"), False
    return nearest_key, nearest_label, [nearest_label], nearest_dist, False


def match_region(
    x: float,
    y: float,
    regions: List[Dict[str, Any]],
) -> Tuple[Optional[str], Optional[str], List[str]]:
    """匹配点所在的地图区域

    Args:
        x: X 坐标
        y: Y 坐标
        regions: 区域列表

    Returns:
        Tuple[primary_key, primary_label, labels]
    """
    primary_key, primary_label, labels, _dist, _matched = match_region_with_distance(
        x,
        y,
        regions,
        allow_nearest=True,
    )
    return primary_key, primary_label, labels


def gaussian_blur(data: np.ndarray, sigma: float) -> np.ndarray:
    """高斯模糊（FFT 卷积实现）

    Args:
        data: 输入数据矩阵
        sigma: 高斯核标准差

    Returns:
        np.ndarray: 模糊后的数据
    """
    if sigma <= 0:
        return data
    size = int(max(3, round(sigma * 6)))
    if size % 2 == 0:
        size += 1
    half = size // 2
    ax = np.arange(-half, half + 1, dtype=float)
    xx, yy = np.meshgrid(ax, ax)
    kernel = np.exp(-(xx ** 2 + yy ** 2) / (2 * sigma ** 2))
    kernel = kernel / kernel.sum()

    # zero-pad kernel to data shape
    pad_kernel = np.zeros(data.shape, dtype=float)
    kh, kw = kernel.shape
    pad_kernel[:kh, :kw] = kernel
    pad_kernel = np.roll(pad_kernel, -half, axis=0)
    pad_kernel = np.roll(pad_kernel, -half, axis=1)

    fdata = np.fft.rfft2(data)
    fkernel = np.fft.rfft2(pad_kernel)
    blurred = np.fft.irfft2(fdata * fkernel, data.shape)
    return np.clip(blurred, 0, None).astype(np.float32)


def parse_tower_key(key: Optional[str]) -> Dict[str, Optional[str]]:
    """解析防御塔键名

    Args:
        key: 塔键名（如 npc_dota_goodguys_tower2_top）

    Returns:
        Dict[str, Optional[str]]: {team, lane, tier}
    """
    info: Dict[str, Optional[str]] = {"team": None, "lane": None, "tier": None}
    if not key:
        return info
    match = re.match(r"npc_dota_(goodguys|badguys)_tower(\d)_(top|mid|bot)", key)
    if not match:
        return info
    side = "radiant" if match.group(1) == "goodguys" else "dire"
    info["team"] = side
    info["tier"] = match.group(2)
    info["lane"] = match.group(3)
    return info


def get_map_path(version: str) -> Optional[str]:
    """获取地图文件路径

    Args:
        version: 地图版本号

    Returns:
        Optional[str]: 地图文件路径，不存在返回 None
    """
    map_file = MAPS_DIR / f"{version}.jpeg"
    if map_file.exists():
        return str(map_file)

    # 尝试其他扩展名
    for ext in [".jpg", ".png"]:
        alt_file = MAPS_DIR / f"{version}{ext}"
        if alt_file.exists():
            return str(alt_file)

    return None
