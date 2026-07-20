"""降级分析器：LLM 不可用时基于规则生成数据摘要"""
from typing import List, Dict, Any

from post_match_review.analyzers.base import BaseRuleReviewAnalyzer
from post_match_review.types.analysis import AnalysisContext, Conclusion
from post_match_review.types.match_data import MatchData
from post_match_review.observability.logger import get_logger

logger = get_logger("pmr.analyzers.fallback")


class FallbackAnalyzer(BaseRuleReviewAnalyzer):
    """降级分析器

    当 LLM 不可用时，基于规则生成数据摘要。
    输出简化版 AnalysisResult，置信度较低但结构完整。
    """

    def __init__(self, phase: str = "fallback") -> None:
        self._phase = phase
        logger.info("降级分析器初始化: phase=%s", phase)

    @property
    def phase_name(self) -> str:
        return self._phase

    def analyze_with_rules(
        self,
        match_data: MatchData,
        context: AnalysisContext,
    ) -> List[Conclusion]:
        dispatch = {
            "laning": self._analyze_laning,
            "teamfight": self._analyze_teamfight,
            "economy": self._analyze_economy,
            "decisions": self._analyze_decisions,
            "vision": self._analyze_vision,
        }
        handler = dispatch.get(self._phase, self._analyze_generic)
        conclusions = handler(match_data)
        logger.info("降级分析器 [%s] 生成 %d 条结论", self._phase, len(conclusions))
        return conclusions

    def _get_user_player(self, match_data: MatchData):
        for player in match_data.players:
            if player.is_user:
                return player
        return None

    def _analyze_generic(self, match_data: MatchData) -> List[Conclusion]:
        """通用兜底：比赛结果 + 用户表现"""
        conclusions: List[Conclusion] = []
        winner = "天辉" if match_data.radiant_win else "夜魇"
        conclusions.append(Conclusion(
            title="比赛结果",
            content=f"{winner}获胜，比分 {match_data.radiant_score}-{match_data.dire_score}，"
                    f"时长 {match_data.duration // 60} 分钟。",
            evidence=[
                f"duration={match_data.duration}s",
                f"score={match_data.radiant_score}-{match_data.dire_score}",
            ],
            has_evidence=True,
            impact="high",
        ))
        user = self._get_user_player(match_data)
        if user:
            conclusions.append(self._user_summary_conclusion(user))
        return conclusions

    def _analyze_laning(self, match_data: MatchData) -> List[Conclusion]:
        """对线期分析：0-10 分钟补刀、伤害、净经济"""
        conclusions: List[Conclusion] = []
        lane = match_data.lane_data

        if lane and lane.lh_at_10:
            user = self._get_user_player(match_data)
            user_lh = None
            user_deny = None
            if user and user.account_id:
                user_lh = lane.lh_at_10.get(user.account_id)
                user_deny = lane.denies_at_10.get(user.account_id)

            # 用户补刀表现
            if user_lh is not None:
                verdict = "达标" if user_lh >= 60 else "偏低"
                conclusions.append(Conclusion(
                    title="10分钟补刀",
                    content=f"用户 10 分钟补刀 {user_lh}，反补 {user_deny or 0}，"
                            f"补刀效率{verdict}。",
                    evidence=[f"lh@10={user_lh}", f"denies@10={user_deny or 0}"],
                    has_evidence=True,
                    impact="high",
                    suggestion="补刀不足时优先保证兵线安全，避免无意义游走。"
                    if user_lh < 60 else None,
                ))

            # 分路信息
            if user and user.account_id and lane.player_lane:
                lane_name = {1: "安全路", 2: "中路", 3: "劣势路", 4: "野区", 5: "游走"}.get(
                    lane.player_lane.get(user.account_id, 0), "未知"
                )
                conclusions.append(Conclusion(
                    title="对线分路",
                    content=f"用户分路：{lane_name}。",
                    evidence=[f"lane={lane.player_lane.get(user.account_id)}"],
                    has_evidence=True,
                    impact="medium",
                ))

            # 双方对线经济对比
            if lane.networth_at_10 and user and user.account_id:
                user_nw = lane.networth_at_10.get(user.account_id)
                if user_nw is not None:
                    conclusions.append(Conclusion(
                        title="10分钟净经济",
                        content=f"用户 10 分钟净经济 {user_nw}。",
                        evidence=[f"networth@10={user_nw}"],
                        has_evidence=True,
                        impact="medium",
                    ))
        else:
            conclusions.append(Conclusion(
                title="对线数据缺失",
                content="未获取到 10 分钟对线数据，无法进行对线期分析。",
                evidence=[],
                has_evidence=False,
                impact="low",
            ))

        return conclusions

    def _analyze_teamfight(self, match_data: MatchData) -> List[Conclusion]:
        """团战分析：次数、死亡、经济收益"""
        conclusions: List[Conclusion] = []
        tfs = match_data.teamfight_data or []

        if not tfs:
            conclusions.append(Conclusion(
                title="无团战数据",
                content="本场比赛未记录到团战数据。",
                evidence=[],
                has_evidence=False,
                impact="low",
            ))
            return conclusions

        total_fights = len(tfs)
        total_deaths = sum(tf.deaths for tf in tfs)
        radiant_delta = sum(tf.radiant_gold_delta for tf in tfs)

        conclusions.append(Conclusion(
            title="团战总览",
            content=f"共 {total_fights} 次团战，总死亡 {total_deaths}，"
                    f"天辉团战累计经济变化 {radiant_delta:+d}。",
            evidence=[
                f"teamfights={total_fights}",
                f"total_deaths={total_deaths}",
                f"radiant_gold_delta={radiant_delta:+d}",
            ],
            has_evidence=True,
            impact="high",
        ))

        # 关键团战（死亡 >= 4 或经济变化绝对值 >= 3000）
        key_fights = [
            tf for tf in tfs
            if tf.deaths >= 4 or abs(tf.radiant_gold_delta - tf.dire_gold_delta) >= 3000
        ]
        if key_fights:
            sample = key_fights[0]
            minutes = sample.start // 60
            conclusions.append(Conclusion(
                title="关键团战",
                content=f"第 {minutes} 分钟团战死亡 {sample.deaths} 人，"
                        f"经济差 {sample.radiant_gold_delta - sample.dire_gold_delta:+d}。",
                evidence=[
                    f"start={sample.start}s",
                    f"deaths={sample.deaths}",
                    f"gold_delta={sample.radiant_gold_delta - sample.dire_gold_delta:+d}",
                ],
                has_evidence=True,
                impact="high",
                suggestion="关键团战的参与与撤退时机直接影响胜负，建议复盘技能释放顺序。",
            ))

        return conclusions

    def _analyze_economy(self, match_data: MatchData) -> List[Conclusion]:
        """经济分析：团队 GPM 对比、个人 GPM/XPM"""
        conclusions: List[Conclusion] = []
        radiant = [p for p in match_data.players if p.is_radiant]
        dire = [p for p in match_data.players if not p.is_radiant]

        if radiant and dire:
            avg_r = sum(p.gpm for p in radiant) // len(radiant)
            avg_d = sum(p.gpm for p in dire) // len(dire)
            delta = avg_r - avg_d
            conclusions.append(Conclusion(
                title="团队经济对比",
                content=f"天辉平均 GPM {avg_r}，夜魇平均 GPM {avg_d}，差距 {delta:+d}。",
                evidence=[f"radiant_avg_gpm={avg_r}", f"dire_avg_gpm={avg_d}"],
                has_evidence=True,
                impact="high",
            ))

        user = self._get_user_player(match_data)
        if user:
            teammates = [p for p in match_data.players if p.is_radiant == user.is_radiant and p is not user]
            if teammates:
                avg_team_gpm = sum(p.gpm for p in teammates) // len(teammates)
                user_delta = user.gpm - avg_team_gpm
                conclusions.append(Conclusion(
                    title="用户经济对比队友",
                    content=f"用户 GPM {user.gpm}，队友平均 GPM {avg_team_gpm}，"
                            f"差值 {user_delta:+d}。",
                    evidence=[
                        f"user_gpm={user.gpm}",
                        f"teammate_avg_gpm={avg_team_gpm}",
                    ],
                    has_evidence=True,
                    impact="high",
                    suggestion="经济落后时需优先保证自身发育，减少无效游走。"
                    if user_delta < -50 else None,
                ))

        return conclusions

    def _analyze_decisions(self, match_data: MatchData) -> List[Conclusion]:
        """决策分析：关键目标、推塔节奏、Roshan"""
        conclusions: List[Conclusion] = []
        raw = match_data.raw_metadata or {}
        objectives = raw.get("objectives") or []

        if objectives:
            # 分类关键目标
            roshan_count = sum(1 for o in objectives if o.get("type") == "CHATED_ROSHAN")
            tower_count = sum(1 for o in objectives if o.get("type") == "BUILDING_KILL")
            conclusions.append(Conclusion(
                title="关键目标事件",
                content=f"比赛共记录 {len(objectives)} 个关键事件，"
                        f"其中 Roshan {roshan_count} 次，防御塔 {tower_count} 座。",
                evidence=[
                    f"objectives={len(objectives)}",
                    f"roshan={roshan_count}",
                    f"towers={tower_count}",
                ],
                has_evidence=True,
                impact="high",
                suggestion="Roshan 时机与推塔节奏是胜负关键，建议结合时间线复盘。",
            ))
        else:
            conclusions.append(Conclusion(
                title="目标事件数据缺失",
                content="未获取到关键目标事件数据，无法进行决策分析。",
                evidence=[],
                has_evidence=False,
                impact="low",
            ))

        # 比赛时长与节奏
        duration_min = match_data.duration // 60
        total_kills = match_data.radiant_score + match_data.dire_score
        kill_per_min = total_kills / max(duration_min, 1)
        conclusions.append(Conclusion(
            title="比赛节奏",
            content=f"比赛时长 {duration_min} 分钟，总击杀 {total_kills}，"
                    f"每分钟击杀 {kill_per_min:.2f}。",
            evidence=[f"duration={match_data.duration}s", f"total_kills={total_kills}"],
            has_evidence=True,
            impact="medium",
        ))

        return conclusions

    def _analyze_vision(self, match_data: MatchData) -> List[Conclusion]:
        """视野分析：守卫放置、反野"""
        conclusions: List[Conclusion] = []
        raw = match_data.raw_metadata or {}
        vision = raw.get("vision") or {}

        if not vision:
            conclusions.append(Conclusion(
                title="视野数据缺失",
                content="未获取到守卫放置数据，无法进行视野分析。",
                evidence=[],
                has_evidence=False,
                impact="low",
            ))
            return conclusions

        obs = vision.get("obs") or {}
        sen = vision.get("sen") or {}
        obs_count = sum(len(v) if isinstance(v, list) else v for v in obs.values())
        sen_count = sum(len(v) if isinstance(v, list) else v for v in sen.values())

        conclusions.append(Conclusion(
            title="守卫放置统计",
            content=f"全场共放置 {obs_count} 个守卫，{sen_count} 个真眼。",
            evidence=[f"obs={obs_count}", f"sen={sen_count}"],
            has_evidence=True,
            impact="medium",
        ))

        user = self._get_user_player(match_data)
        if user and user.account_id:
            user_obs = obs.get(user.account_id, 0)
            user_sen = sen.get(user.account_id, 0)
            if isinstance(user_obs, list):
                user_obs = len(user_obs)
            if isinstance(user_sen, list):
                user_sen = len(user_sen)
            conclusions.append(Conclusion(
                title="用户视野贡献",
                content=f"用户放置 {user_obs} 个守卫，{user_sen} 个真眼。",
                evidence=[f"user_obs={user_obs}", f"user_sen={user_sen}"],
                has_evidence=True,
                impact="high",
                suggestion="视野是 Dota 的核心，建议保持每 5 分钟一组守卫的节奏。",
            ))

        return conclusions

    def _user_summary_conclusion(self, user) -> Conclusion:
        kda_ratio = (user.kills + user.assists) / max(user.deaths, 1)
        return Conclusion(
            title="用户表现摘要",
            content=f"使用 {user.hero_name}，KDA {user.kills}/{user.deaths}/"
                    f"{user.assists}，GPM {user.gpm}，XPM {user.xpm}。",
            evidence=[
                f"hero={user.hero_name}",
                f"kda={kda_ratio:.1f}",
                f"gpm={user.gpm}",
                f"xpm={user.xpm}",
            ],
            has_evidence=True,
            impact="high",
            suggestion="建议查看详细回放以了解具体操作细节。",
        )
