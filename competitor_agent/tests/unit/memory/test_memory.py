"""memory 四层记忆 + knowledge_base 单测"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from competitor_agent.interfaces.context import AnalysisSession, Skill
from competitor_agent.knowledge_base.competitor_store import CompetitorStore, TextChunk, chunk_text, tokenize
from competitor_agent.knowledge_base.ingester import Ingester
from competitor_agent.knowledge_base.retriever import Retriever
from competitor_agent.memory import (
    EvolutionMemory,
    FourLayerMemory,
    PersistentNotes,
    SessionArchive,
    SkillStore,
)


def _iso(days_ago: int) -> str:
    dt = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _tmp_dir(tmp_path: Path) -> Path:
    return tmp_path / "memory"


class TestChunkText:
    def test_short_text_single_chunk(self):
        assert chunk_text("short") == ["short"]

    def test_long_text_splits(self):
        text = "word " * 2000
        chunks = chunk_text(text, size=1200, overlap=200)
        assert len(chunks) > 1
        assert "".join(chunks).startswith("word")


class TestTokenize:
    def test_english_and_chinese(self):
        toks = tokenize("Cursor Pricing 定价 $20")
        assert "cursor" in toks
        assert "pricing" in toks
        assert "定价" in toks


class TestSessionArchive:
    def test_archive_and_retrieve(self, tmp_path):
        arch = SessionArchive(_tmp_dir(tmp_path))
        s = AnalysisSession(task="分析 Cursor", competitor_name="cursor", session_id="s1", created_at=_iso(0))
        arch.archive(s)
        got = arch.retrieve("cursor")
        assert len(got) == 1
        assert got[0].session_id == "s1"

    def test_dedupe_same_session_id(self, tmp_path):
        arch = SessionArchive(_tmp_dir(tmp_path))
        s1 = AnalysisSession(task="t", competitor_name="cursor", session_id="x", created_at=_iso(2), raw={"a": 1})
        s2 = AnalysisSession(task="t2", competitor_name="cursor", session_id="x", created_at=_iso(1), raw={"a": 2})
        arch.archive(s1)
        arch.archive(s2)
        got = arch.retrieve("cursor")
        assert len(got) == 1
        assert got[0].raw == {"a": 2}

    def test_aging_out(self, tmp_path):
        arch = SessionArchive(_tmp_dir(tmp_path), ttl_days=1)
        old = AnalysisSession(task="t", competitor_name="cursor", session_id="old", created_at=_iso(100))
        new = AnalysisSession(task="t", competitor_name="cursor", session_id="new", created_at=_iso(0))
        arch.archive(old)
        arch.archive(new)
        got = arch.retrieve("cursor")
        assert [s.session_id for s in got] == ["new"]

    def test_persist_across_instances(self, tmp_path):
        d = _tmp_dir(tmp_path)
        SessionArchive(d).archive(AnalysisSession(task="t", competitor_name="cursor", session_id="s1", created_at=_iso(0)))
        got = SessionArchive(d).retrieve("cursor")
        assert got[0].session_id == "s1"


class TestPersistentNotes:
    def test_save_retrieve(self, tmp_path):
        notes = PersistentNotes(_tmp_dir(tmp_path))
        notes.save_note("cursor", "定价走 pricing 页")
        got = notes.retrieve_notes("cursor")
        assert got == ["定价走 pricing 页"]

    def test_dedupe(self, tmp_path):
        notes = PersistentNotes(_tmp_dir(tmp_path))
        notes.save_note("cursor", "same")
        notes.save_note("cursor", "same")
        assert len(notes.retrieve_notes("cursor")) == 1

    def test_max_cap(self, tmp_path):
        notes = PersistentNotes(_tmp_dir(tmp_path), max_per_competitor=3)
        for i in range(10):
            notes.save_note("cursor", f"note-{i}")
        got = notes.retrieve_notes("cursor")
        assert len(got) == 3


class TestSkillStore:
    def test_record_and_retrieve(self, tmp_path):
        store = SkillStore(_tmp_dir(tmp_path))
        store.record_success("cursor", "pricing", "official_pricing")
        skills = store.retrieve_skills("cursor")
        assert len(skills) == 1
        assert skills[0].gap_field == "pricing"
        assert skills[0].success is True

    def test_weight_accumulates(self, tmp_path):
        store = SkillStore(_tmp_dir(tmp_path))
        store.record_success("cursor", "pricing", "official_pricing")
        store.record_success("cursor", "pricing", "official_pricing")
        skills = store.retrieve_skills("cursor")
        assert len(skills) == 1  # 合并
        assert skills[0].weight > 1.0

    def test_failure_decays(self, tmp_path):
        store = SkillStore(_tmp_dir(tmp_path))
        store.record_success("cursor", "pricing", "official_pricing")
        store.record_failure("cursor", "pricing", "official_pricing")
        skills = store.retrieve_skills("cursor")
        assert skills[0].weight < 1.0

    def test_max_cap(self, tmp_path):
        store = SkillStore(_tmp_dir(tmp_path), max_per_competitor=2)
        for i in range(5):
            store.record_success("cursor", "pricing", f"source{i}")
        assert len(store.retrieve_skills("cursor")) == 2


class TestEvolutionMemory:
    def test_success_rate(self, tmp_path):
        evo = EvolutionMemory(_tmp_dir(tmp_path))
        evo.record_outcome("official_pricing", True)
        evo.record_outcome("official_pricing", True)
        evo.record_outcome("official_pricing", False)
        rates = evo.source_success_rates()
        assert 0.5 < rates["official_pricing"] < 1.0

    def test_unknown_source_default(self, tmp_path):
        evo = EvolutionMemory(_tmp_dir(tmp_path))
        assert evo.source_success_rates() == {}

    def test_top_sources(self, tmp_path):
        evo = EvolutionMemory(_tmp_dir(tmp_path))
        evo.record_outcome("a", True)
        evo.record_outcome("a", True)
        evo.record_outcome("b", False)
        top = evo.top_sources(2)
        assert top[0][0] == "a"


class TestFourLayerMemory:
    def test_full_protocol(self, tmp_path):
        mem = FourLayerMemory(_tmp_dir(tmp_path))
        mem.archive_session(AnalysisSession(task="t", competitor_name="cursor", session_id="s1"))
        mem.save_note("cursor", "note1")
        mem.record_skill(Skill(competitor_name="cursor", gap_field="pricing", source_name="official_pricing", success=True))
        mem.record_outcome("official_pricing", True)

        assert len(mem.recent_sessions()) == 1
        assert mem.retrieve_notes("cursor") == ["note1"]
        assert mem.retrieve_skills("cursor")[0].gap_field == "pricing"
        assert "official_pricing" in mem.source_success_rates()

    def test_memory_isolated_by_competitor(self, tmp_path):
        mem = FourLayerMemory(_tmp_dir(tmp_path))
        mem.save_note("cursor", "cursor note")
        mem.save_note("copilot", "copilot note")
        assert mem.retrieve_notes("cursor") == ["cursor note"]
        assert mem.retrieve_notes("copilot") == ["copilot note"]


class TestKnowledgeBase:
    def test_ingest_and_retrieve(self, tmp_path):
        store = CompetitorStore(tmp_path / "kb")
        ingester = Ingester(store)
        n = ingester.ingest(
            "cursor",
            "pricing",
            "Cursor Pro is 20 dollars per month. Teams is 40 dollars per month.",
            source_url="https://cursor.com/pricing",
        )
        assert n >= 1
        retriever = Retriever(store)
        hits = retriever.retrieve("Cursor Pro price", competitor="cursor", dimension="pricing", top_k=3)
        assert hits
        assert "20" in hits[0].text or "dollars" in hits[0].text

    def test_retrieve_prioritizes_same_competitor(self, tmp_path):
        store = CompetitorStore(tmp_path / "kb")
        store.add(TextChunk("a", "copilot", "pricing", "Copilot costs 10 dollars monthly."))
        store.add(TextChunk("b", "cursor", "pricing", "Cursor Pro costs 20 dollars monthly."))
        retriever = Retriever(store)
        hits = retriever.retrieve("Cursor price monthly", competitor="cursor", top_k=5)
        assert hits[0].competitor == "cursor"

    def test_retrieve_by_dimension(self, tmp_path):
        store = CompetitorStore(tmp_path / "kb")
        store.add(TextChunk("a", "cursor", "pricing", "pricing text"))
        store.add(TextChunk("b", "cursor", "feature", "feature text"))
        hits = Retriever(store).retrieve_by_dimension("cursor", "feature")
        assert [c.dimension for c in hits] == ["feature"]

    def test_persist_across_instances(self, tmp_path):
        d = tmp_path / "kb"
        store = CompetitorStore(d)
        store.add(TextChunk("a", "cursor", "pricing", "some pricing info"))
        store2 = CompetitorStore(d)
        assert len(store2.by_competitor("cursor")) == 1

    def test_chunk_persistence_json(self, tmp_path):
        d = tmp_path / "kb"
        store = CompetitorStore(d)
        store.add(TextChunk("a", "cursor", "pricing", "some pricing info"))
        file = d / "memory" / "knowledge_base.json"
        assert file.exists()
        data = json.loads(file.read_text(encoding="utf-8"))
        assert data["chunks"][0]["competitor"] == "cursor"