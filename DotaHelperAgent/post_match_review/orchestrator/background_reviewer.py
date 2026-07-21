"""后台自我审查器"""
import asyncio
import json
from typing import Any, Dict, List, Optional

from post_match_review.interfaces.llm import ILLMClient
from post_match_review.memory.four_layer_memory import FourLayerMemory
from post_match_review.memory.dream_recap import DreamRecap
from post_match_review.prompt.loader import get_prompt_loader
from post_match_review.observability.logger import get_logger

logger = get_logger("pmr.orchestrator.background")


class BackgroundReviewer:
    """后台自我审查器

    在复盘报告生成后异步启动，评估分析质量、提取可复用模式，
    并将结果沉淀到四层记忆系统中。
    """

    def __init__(
        self,
        llm_client: ILLMClient,
        memory: FourLayerMemory,
        config: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._llm_client = llm_client
        self._memory = memory
        self._config = config or {}
        self._confidence_threshold: float = self._config.get("confidence_threshold", 0.7)
        self._prompt_loader = get_prompt_loader()
        self._dream_recap = DreamRecap(
            llm_client=llm_client,
            persistent_notes=memory.persistent_notes,
            skill_store=memory.skill_store,
        )
        self._task: Optional[asyncio.Task[None]] = None

    def spawn(
        self,
        match_data: Any,
        report: Any,
    ) -> None:
        """启动后台审查任务（不阻塞主流程）

        Args:
            match_data: 比赛数据
            report: 复盘报告
        """
        try:
            match_id = getattr(match_data, "match_id", "unknown")
            report_length = len(getattr(report, "markdown_report", "")) if hasattr(report, "markdown_report") else 0
            findings_count = len(getattr(report, "key_findings", [])) if hasattr(report, "key_findings") else 0
            
            logger.info(
                f"[spawn] 准备启动后台审查任务: match_id={match_id}, "
                f"报告长度={report_length}字符, 关键发现数={findings_count}"
            )
            
            # 使用 get_running_loop() 替代已弃用的 get_event_loop()
            loop = asyncio.get_running_loop()
            self._task = loop.create_task(
                self._review_worker(match_data, report),
                name=f"background_review_{match_id}",
            )
            logger.info(f"[spawn] 后台审查任务已启动: task_name={self._task.get_name()}")
        except RuntimeError as e:
            # 如果没有运行中的事件循环，记录错误
            logger.error(f"[spawn] 无法启动后台任务: 没有运行中的事件循环 - {e}", exc_info=True)
        except Exception as e:
            logger.error(f"[spawn] 启动后台审查任务失败: {e}", exc_info=True)

    async def wait_for_completion(self) -> None:
        """等待后台审查完成（仅用于测试）"""
        if self._task and not self._task.done():
            await self._task

    async def _review_worker(
        self,
        match_data: Any,
        report: Any,
    ) -> None:
        """审查工作协程"""
        try:
            match_id = str(getattr(match_data, "match_id", "unknown"))
            logger.info(f"[_review_worker] 开始后台审查: match_id={match_id}")

            # 步骤1: 质量评估
            logger.info(f"[_review_worker] 步骤1/4: 开始质量评估")
            quality = await self._assess_quality(report)
            overall_score = quality.get("overall_score", 0.0)
            logger.info(
                f"[_review_worker] 质量评估完成: overall_score={overall_score:.2f}, "
                f"data_support={quality.get('data_support', 0):.2f}, "
                f"analysis_depth={quality.get('analysis_depth', 0):.2f}, "
                f"actionability={quality.get('actionability', 0):.2f}, "
                f"completeness={quality.get('completeness', 0):.2f}"
            )

            metadata = {
                "quality_score": overall_score,
                "quality_dimensions": quality,
            }

            # 步骤2: 归档会话
            logger.info(f"[_review_worker] 步骤2/4: 开始归档会话")
            serialized_report = self._serialize_report(report)
            logger.debug(f"[_review_worker] 报告序列化完成: 字段数={len(serialized_report)}")
            
            await self._memory.archive_session(
                match_id=match_id,
                report=serialized_report,
                metadata=metadata,
            )
            logger.info(f"[_review_worker] 会话归档完成: match_id={match_id}")

            # 步骤3: 模式提取
            logger.info(f"[_review_worker] 步骤3/4: 开始模式提取")
            patterns = await self._extract_patterns(match_data, report)
            logger.info(f"[_review_worker] 模式提取完成: 提取到 {len(patterns)} 个模式")
            
            for i, pattern in enumerate(patterns, 1):
                pattern_name = pattern.get("name", "unnamed")
                pattern_type = pattern.get("type", "unknown")
                confidence = pattern.get("confidence", 0)
                logger.info(
                    f"[_review_worker] 模式 {i}/{len(patterns)}: "
                    f"name={pattern_name}, type={pattern_type}, confidence={confidence:.2f}"
                )

            # 步骤4: 持久化高置信度模式
            logger.info(
                f"[_review_worker] 步骤4/4: 开始持久化 "
                f"(置信度阈值={self._confidence_threshold:.2f})"
            )
            persisted_count = 0
            for pattern in patterns:
                confidence = pattern.get("confidence", 0)
                pattern_name = pattern.get("name", "unnamed")
                
                if confidence >= self._confidence_threshold:
                    if pattern.get("type") == "skill":
                        logger.info(
                            f"[_review_worker] 沉淀技能: name={pattern_name}, "
                            f"confidence={confidence:.2f}"
                        )
                        self._memory.skill_store.save_skill(
                            name=pattern_name,
                            content=pattern.get("content", ""),
                            metadata={
                                "description": pattern.get("description", ""),
                                "confidence": confidence,
                                "source_match": match_id,
                                "tags": pattern.get("tags", []),
                            },
                        )
                        logger.info(f"[_review_worker] 技能沉淀完成: {pattern_name}")
                    else:
                        logger.info(
                            f"[_review_worker] 沉淀笔记: name={pattern_name}, "
                            f"category={pattern.get('category', 'general')}, "
                            f"confidence={confidence:.2f}"
                        )
                        await self._memory.add_persistent_note(
                            category=pattern.get("category", "general"),
                            content=pattern.get("content", ""),
                            evidence=pattern.get("evidence", []),
                        )
                        logger.info(f"[_review_worker] 笔记沉淀完成: {pattern_name}")
                    persisted_count += 1
                else:
                    logger.info(
                        f"[_review_worker] 跳过低置信度模式: name={pattern_name}, "
                        f"confidence={confidence:.2f} < threshold={self._confidence_threshold:.2f}"
                    )
            
            logger.info(
                f"[_review_worker] 持久化完成: "
                f"{persisted_count}/{len(patterns)} 个模式已沉淀"
            )

            # 步骤5: DreamRecap 整合
            logger.info(f"[_review_worker] 开始 DreamRecap 整合")
            recap_result = await self._dream_recap.integrate(
                match_data=match_data,
                report=report,
                quality_assessment=quality,
            )
            logger.info(
                f"[_review_worker] DreamRecap 整合完成: "
                f"insights={len(recap_result.get('insights', []))}, "
                f"patterns={len(recap_result.get('patterns', []))}, "
                f"persisted_notes={recap_result.get('persisted_notes', 0)}, "
                f"persisted_skills={recap_result.get('persisted_skills', 0)}"
            )

            logger.info(
                f"[_review_worker] 后台审查工作全部完成: match_id={match_id}, "
                f"quality_score={overall_score:.2f}, "
                f"patterns_extracted={len(patterns)}, "
                f"patterns_persisted={persisted_count}"
            )

        except Exception as e:
            logger.error(f"[_review_worker] 后台审查工作失败: {e}", exc_info=True)

    async def _assess_quality(self, report: Any) -> Dict[str, Any]:
        """评估分析质量

        评估维度：数据支撑度、分析深度、可操作性、完整性

        Returns:
            Dict[str, Any]: 各维度评分
        """
        try:
            logger.debug("[_assess_quality] 开始构建质量评估提示词")
            prompt = self._build_quality_prompt(report)
            logger.debug(f"[_assess_quality] 提示词构建完成: 长度={len(prompt)}字符")
            
            logger.debug("[_assess_quality] 调用 LLM 进行质量评估")
            response = await self._llm_client.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
            )
            logger.debug(f"[_assess_quality] LLM 响应接收: 长度={len(response)}字符")
            
            logger.debug("[_assess_quality] 开始解析 LLM 响应")
            result = self._parse_quality_response(response)
            logger.debug(f"[_assess_quality] 响应解析完成: overall_score={result.get('overall_score', 0):.2f}")
            
            return result
        except Exception as e:
            logger.error(f"[_assess_quality] 质量评估失败: {e}", exc_info=True)
            return {
                "data_support": 0.5,
                "analysis_depth": 0.5,
                "actionability": 0.5,
                "completeness": 0.5,
                "overall_score": 0.5,
            }

    async def _extract_patterns(
        self,
        match_data: Any,
        report: Any,
    ) -> List[Dict[str, Any]]:
        """提取可复用模式

        Returns:
            List[Dict[str, Any]]: 模式列表
        """
        try:
            prompt = self._build_patterns_prompt(match_data, report)
            response = await self._llm_client.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
            )
            return self._parse_patterns_response(response)
        except Exception as e:
            logger.error(f"模式提取失败: {e}")
            return []

    def _build_quality_prompt(self, report: Any) -> str:
        """构建质量评估提示词"""
        report_text = self._summarize_report_for_prompt(report)
        
        # 从 YAML 模板加载
        system_prompt = self._prompt_loader.render(
            "background_review",
            "quality_assessment.system",
        )
        user_prompt = self._prompt_loader.render(
            "background_review",
            "quality_assessment.user",
            match_id=getattr(report, "match_id", "unknown"),
            duration=getattr(report, "duration", "N/A"),
            winner="Radiant" if getattr(report, "radiant_win", False) else "Dire",
            report_summary=report_text,
        )
        
        return f"{system_prompt}\n\n{user_prompt}"

    def _build_patterns_prompt(self, match_data: Any, report: Any) -> str:
        """构建模式提取提示词"""
        report_text = self._summarize_report_for_prompt(report)
        
        # 从 YAML 模板加载
        system_prompt = self._prompt_loader.render(
            "background_review",
            "pattern_extraction.system",
        )
        
        # 提取关键发现和改进建议
        key_findings = getattr(report, "key_findings", [])
        key_findings_text = "\n".join([f"- {finding}" for finding in key_findings[:5]]) if key_findings else "无"
        
        improvement_areas = getattr(report, "improvement_areas", [])
        improvement_text = "\n".join([f"- {area}" for area in improvement_areas[:5]]) if improvement_areas else "无"
        
        user_prompt = self._prompt_loader.render(
            "background_review",
            "pattern_extraction.user",
            match_id=getattr(match_data, "match_id", "unknown"),
            duration=getattr(match_data, "duration", "N/A"),
            winner="Radiant" if getattr(match_data, "radiant_win", False) else "Dire",
            user_hero=getattr(match_data, "user_hero", "Unknown"),
            key_findings=key_findings_text,
            improvement_areas=improvement_text,
        )
        
        return f"{system_prompt}\n\n{user_prompt}"

    def _summarize_report_for_prompt(self, report: Any) -> str:
        """简化报告用于提示词"""
        if hasattr(report, "markdown_report") and report.markdown_report:
            return report.markdown_report[:2000]
        if hasattr(report, "key_findings"):
            return "\n".join(report.key_findings[:10])
        return "无报告内容"

    def _serialize_report(self, report: Any) -> Dict[str, Any]:
        """序列化报告用于归档"""
        if hasattr(report, "__dict__"):
            result: Dict[str, Any] = {}
            for key, value in report.__dict__.items():
                try:
                    # 直接序列化，避免重复序列化
                    serialized = json.dumps(value, ensure_ascii=False, default=str)
                    result[key] = json.loads(serialized)
                except (TypeError, ValueError):
                    result[key] = str(value)
            return result
        return {"raw": str(report)}

    def _parse_quality_response(self, response: str) -> Dict[str, Any]:
        """解析质量评估响应"""
        try:
            text = response
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            elif "```" in text:
                text = text.split("```")[1].split("```")[0]
            data = json.loads(text.strip())
            if "overall_score" not in data:
                scores = [
                    data.get("data_support", 0.5),
                    data.get("analysis_depth", 0.5),
                    data.get("actionability", 0.5),
                    data.get("completeness", 0.5),
                ]
                data["overall_score"] = sum(scores) / len(scores)
            return data
        except Exception as e:
            logger.error(f"解析质量评估响应失败: {e}")
            return {
                "data_support": 0.5,
                "analysis_depth": 0.5,
                "actionability": 0.5,
                "completeness": 0.5,
                "overall_score": 0.5,
            }

    def _parse_patterns_response(self, response: str) -> List[Dict[str, Any]]:
        """解析模式提取响应"""
        try:
            text = response
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            elif "```" in text:
                text = text.split("```")[1].split("```")[0]
            return json.loads(text.strip())
        except Exception as e:
            logger.error(f"解析模式提取响应失败: {e}")
            return []
