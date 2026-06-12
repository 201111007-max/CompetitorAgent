"""数据导入脚本 - 导入英雄、物品和攻略数据到知识库"""

import json
import os
import sys
from pathlib import Path
from typing import Dict, Any, List

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from knowledge.vector_store import VectorStore
from utils.log_config import get_logger

logger = get_logger("import_knowledge", component="scripts")


def load_hero_data(file_path: str) -> List[Dict[str, Any]]:
    """加载英雄数据

    Args:
        file_path: 英雄数据文件路径

    Returns:
        英雄数据列表
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            logger.info(f"加载英雄数据: {len(data)} 个英雄")
            return data
    except Exception as e:
        logger.error(f"加载英雄数据失败: {e}")
        return []


def load_item_data(file_path: str) -> List[Dict[str, Any]]:
    """加载物品数据

    Args:
        file_path: 物品数据文件路径

    Returns:
        物品数据列表
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            logger.info(f"加载物品数据: {len(data)} 个物品")
            return data
    except Exception as e:
        logger.error(f"加载物品数据失败: {e}")
        return []


def load_guides(directory: str) -> List[Dict[str, Any]]:
    """加载攻略文档

    Args:
        directory: 攻略文档目录

    Returns:
        攻略文档列表
    """
    guides = []
    guide_dir = Path(directory)

    if not guide_dir.exists():
        logger.warning(f"攻略目录不存在: {directory}")
        return guides

    # 遍历所有 markdown 文件
    for md_file in guide_dir.rglob("*.md"):
        try:
            with open(md_file, 'r', encoding='utf-8') as f:
                content = f.read()

            # 提取元数据（从文件名）
            file_name = md_file.stem
            category = md_file.parent.name

            guides.append({
                'id': f"guide_{file_name}",
                'text': content,
                'metadata': {
                    'title': file_name,
                    'category': category,
                    'source': 'local_guide'
                }
            })

        except Exception as e:
            logger.error(f"加载攻略失败: {md_file}, 错误: {e}")

    logger.info(f"加载攻略文档: {len(guides)} 个")
    return guides


def import_to_vector_store(
    vector_store: VectorStore,
    documents: List[Dict[str, Any]]
) -> int:
    """导入文档到向量数据库

    Args:
        vector_store: 向量数据库客户端
        documents: 文档列表

    Returns:
        成功导入的数量
    """
    if not documents:
        logger.warning("没有文档需要导入")
        return 0

    count = vector_store.add_documents_batch(documents)
    logger.info(f"成功导入 {count} 个文档到向量数据库")
    return count


def create_sample_data():
    """创建示例数据文件"""
    # 创建数据目录
    data_dir = project_root / "data"
    knowledge_base_dir = data_dir / "knowledge_base"
    guides_dir = data_dir / "guides" / "hero_guides"

    knowledge_base_dir.mkdir(parents=True, exist_ok=True)
    guides_dir.mkdir(parents=True, exist_ok=True)

    # 创建英雄示例数据
    heroes_data = [
        {
            "id": 1,
            "name": "幻影刺客",
            "localized_name": "Phantom Assassin",
            "description": "幻影刺客是一个高爆发的物理输出英雄，擅长秒杀敌方脆皮英雄",
            "roles": ["carry", "escape"],
            "win_rate": 0.52
        },
        {
            "id": 2,
            "name": "主宰",
            "localized_name": "Juggernaut",
            "description": "主宰是一个全能型英雄，拥有强大的输出和生存能力",
            "roles": ["carry", "pusher"],
            "win_rate": 0.51
        }
    ]

    heroes_file = knowledge_base_dir / "heroes.json"
    with open(heroes_file, 'w', encoding='utf-8') as f:
        json.dump(heroes_data, f, ensure_ascii=False, indent=2)
    logger.info(f"创建英雄数据文件: {heroes_file}")

    # 创建物品示例数据
    items_data = [
        {
            "id": 1,
            "name": "BKB",
            "localized_name": "Black King Bar",
            "description": "黑皇杖，提供魔法免疫，是PA的核心装备",
            "cost": 4050
        },
        {
            "id": 2,
            "name": "蝴蝶",
            "localized_name": "Butterfly",
            "description": "蝴蝶，提供攻击速度和闪避，增强PA的输出和生存",
            "cost": 5275
        }
    ]

    items_file = knowledge_base_dir / "items.json"
    with open(items_file, 'w', encoding='utf-8') as f:
        json.dump(items_data, f, ensure_ascii=False, indent=2)
    logger.info(f"创建物品数据文件: {items_file}")

    # 创建攻略示例数据
    pa_guide = """# 幻影刺客 (Phantom Assassin) 攻略

## 英雄定位
幻影刺客（PA）是一个高爆发的物理输出英雄，擅长秒杀敌方脆皮英雄。

## 出装推荐

### 核心装备
- **BKB (黑皇杖)**: 提供魔法免疫，是PA的核心装备
- **蝴蝶**: 提供攻击速度和闪避，增强输出和生存
- **撒旦**: 提供吸血和生存能力

### 可选装备
- **圣剑**: 极致输出
- **金箍棒**: 针对闪避英雄
- **大炮**: 增加暴击伤害

## 技能加点

1. **恩赐解脱** (大招) - 有大点大
2. **模糊** - 优先点满
3. **窒息之刃** - 次要点满
4. **幻影突袭** - 最后点满

## 克制英雄

### PA 克制的英雄
- 狙击手
- 卓尔游侠
- 露娜

### 克制 PA 的英雄
- 血魔
- 斧王
- 军团指挥官

## 游戏策略

### 对线期
- 利用窒息之刃补刀和消耗
- 保持血量健康
- 尽快出到相位鞋

### 中期
- 积极参团，寻找秒杀机会
- 优先击杀敌方脆皮英雄
- 注意走位，避免被控制

### 后期
- 团战时等待时机切入
- 优先击杀敌方核心英雄
- 注意BKB的使用时机
"""

    pa_guide_file = guides_dir / "PA.md"
    with open(pa_guide_file, 'w', encoding='utf-8') as f:
        f.write(pa_guide)
    logger.info(f"创建攻略文件: {pa_guide_file}")


def main():
    """主函数"""
    logger.info("开始数据导入...")

    # 创建示例数据
    create_sample_data()

    # 初始化向量数据库
    config = {
        'persist_directory': str(project_root / 'data' / 'chroma_db'),
        'collection_name': 'dota_guides',
        'embedding_model': 'text-embedding-3-small',
        'embedding_dimension': 1536
    }

    vector_store = VectorStore(config)

    # 1. 导入英雄数据
    hero_data = load_hero_data(str(project_root / 'data' / 'knowledge_base' / 'heroes.json'))
    hero_documents = [
        {
            'id': f"hero_{hero['id']}",
            'text': f"{hero['name']}: {hero.get('description', '')}",
            'metadata': {
                'type': 'hero',
                'name': hero['name'],
                'source': 'opendota'
            }
        }
        for hero in hero_data
    ]
    import_to_vector_store(vector_store, hero_documents)

    # 2. 导入物品数据
    item_data = load_item_data(str(project_root / 'data' / 'knowledge_base' / 'items.json'))
    item_documents = [
        {
            'id': f"item_{item['id']}",
            'text': f"{item['name']}: {item.get('description', '')}",
            'metadata': {
                'type': 'item',
                'name': item['name'],
                'source': 'opendota'
            }
        }
        for item in item_data
    ]
    import_to_vector_store(vector_store, item_documents)

    # 3. 导入攻略文档
    guides = load_guides(str(project_root / 'data' / 'guides'))
    import_to_vector_store(vector_store, guides)

    # 4. 验证导入结果
    stats = vector_store.get_stats()
    logger.info(f"数据导入完成: {stats}")

    print(f"\n✅ 数据导入成功！")
    print(f"📊 向量数据库统计:")
    print(f"  - 集合名称: {stats['collection_name']}")
    print(f"  - 文档数量: {stats['document_count']}")
    print(f"  - 存储位置: {stats['persist_directory']}")


if __name__ == "__main__":
    main()
