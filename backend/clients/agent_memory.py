"""
Agent Memory Manager
Provides database and memory management for agents.

Agent storage lives in Postgres, in tables Agno creates on first use:
  public.agent_sessions  chat sessions (history, runs, session name)
  public.agent_memories  long-term user memories
"""

import threading
from typing import List, Optional
from agno.db.postgres import PostgresDb
from agno.db.schemas import UserMemory
from agno.memory.manager import MemoryManager
from agno.models.message import Message
from app.settings import settings
from app.logger import logger
from clients.ultimate_llm import get_llm_agno

# Fixed model for extracting memories, so it doesn't depend on (or get pinned
# to) whichever chat model the first agent happened to use.
MEMORY_MODEL = "google/gemini-3-flash-preview"
MAX_MEMORIES_PER_USER = 20
MEMORY_TABLE = "agent_memories"
SESSION_TABLE = "agent_sessions"


# Patch for legacy memory format compatibility
_orig_user_memory_from_dict = UserMemory.from_dict.__func__


def _user_memory_from_dict_with_alias(cls, data):
    """Handle both old 'id' and new 'memory_id' formats"""
    data = dict(data)
    if "id" in data and "memory_id" not in data:
        data["memory_id"] = data.pop("id")

    allowed_keys = {
        "memory",
        "memory_id",
        "topics",
        "user_id",
        "input",
        "created_at",
        "updated_at",
        "feedback",
        "agent_id",
        "team_id",
    }
    data = {k: v for k, v in data.items() if k in allowed_keys}
    return _orig_user_memory_from_dict(cls, data)


UserMemory.from_dict = classmethod(_user_memory_from_dict_with_alias)


MEMORY_CAPTURE_INSTRUCTIONS = """
You are helping users find and work with their knowledge base. Focus on capturing meaningful information to provide personalized, context-aware assistance.

PROFESSIONAL & WORK CONTEXT:
- Job role, responsibilities, and team structure
- Current projects, initiatives, and their priorities
- Client needs, stakeholder requirements, and deadlines
- Work processes, workflows, and methodologies they follow
- Areas of expertise and professional domains
- Tools, technologies, and platforms they use

COMMUNICATION & STYLE PREFERENCES:
- Preferred communication tone (formal, casual, technical)
- How they like information presented (detailed vs. concise, visual vs. text)
- Response format preferences (bullet points, paragraphs, tables)
- Language complexity and terminology they use
- Their approach to problem-solving and decision-making

DOCUMENT & CONTENT PATTERNS:
- Types of documents they work with frequently (PDFs, videos, presentations, spreadsheets)
- Specific folders, projects, or content areas they reference often
- Topics and subjects they regularly search for
- Key files or videos they return to repeatedly
- Document organization and naming conventions they use
- Preferred file formats and content types

PROJECT & TASK MEMORY:
- Ongoing projects and their objectives
- Project-specific context and requirements
- Tasks and deliverables they're working on
- Project timelines and milestones
- Project team members and stakeholders

KNOWLEDGE & LEARNING PATTERNS:
- Recurring questions and information requests
- Topics they're learning about or researching
- Knowledge gaps and areas where they seek help
- Subject matter they're building expertise in
- Research interests and learning goals

PERSONAL CONTEXT (Work-Relevant):
- Important dates, deadlines, and recurring events
- Time zone and working hours patterns
- Key people, team members, or contacts they mention frequently
- Personal preferences that affect work (e.g., dietary restrictions for catering docs)
- Interests that inform their professional work

PRIORITIES & GOALS:
- What matters most to them in their work
- Short-term and long-term objectives
- Success criteria and how they measure progress
- Challenges and obstacles they're facing
- Strategic priorities that guide decisions

BEHAVIORAL PATTERNS:
- How they typically search for information
- Query patterns and common search terms
- Content consumption habits (prefer videos over text documents, etc.)
- Time-sensitive information needs or recurring requests
- Patterns that indicate future needs

IMPORTANT CONTEXT:
- Significant conversations, decisions, or insights
- Context that eliminates need to re-explain things
- Information that makes future interactions more efficient
- Historical patterns that help anticipate needs
- Long-term context that shapes recommendations

DO NOT CAPTURE UNLESS EXPLICITLY PROVIDED:
- Sensitive personal information (health, financial details)
- Confidential or privileged business information without clear work context
- Casual greetings or small talk without meaningful context
- Temporary one-off questions without lasting relevance
- Repetitive confirmations or basic acknowledgments
- Information the user explicitly asks not to remember

GUIDING PRINCIPLES:
- Remember information that makes you more helpful over time
- Capture context that personalizes the experience
- Focus on patterns that help anticipate user needs
- Prioritize professional and productivity-related details
- Respect privacy and only remember what's useful for assistance
- Store information that reduces friction in future interactions
"""


class CachedTablePostgresDb(PostgresDb):
    """PostgresDb that looks each table up once.

    Agno re-checks that a table exists, validates its schema and re-reflects it
    on every call — several round-trips each time, which over a remote
    Postgres made a single memory read take ~8s. Once a table is found it
    doesn't change shape, so keep the Table object.
    """

    def _get_table(self, table_type: str, create_table_if_not_found: Optional[bool] = False):
        cache = self.__dict__.setdefault("_table_cache", {})
        if table_type in cache:
            return cache[table_type]
        table = super()._get_table(table_type, create_table_if_not_found=create_table_if_not_found)
        if table is not None:
            cache[table_type] = table
        return table


class LimitedMemoryManager(MemoryManager):
    """
    Memory manager that scopes memories to an organization and caps how many
    are stored per user.

    Agno keys memories by user_id only. A user can belong to several orgs, so
    memories are stored under "<org_id>:<user_id>" to keep one org's context
    out of another org's chats.
    """

    def __init__(
        self,
        max_memories_per_user: int = MAX_MEMORIES_PER_USER,
        organization_id: Optional[str] = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.max_memories_per_user = max_memories_per_user
        self.organization_id = organization_id

    def _scoped(self, user_id: Optional[str]) -> str:
        user_id = user_id or "default"
        return f"{self.organization_id}:{user_id}" if self.organization_id else user_id

    def _enforce_limit(self, scoped_user_id: str) -> None:
        """Delete the oldest memories beyond max_memories_per_user"""
        if not self.db:
            return
        memories = self.db.get_user_memories(user_id=scoped_user_id)
        if isinstance(memories, tuple):
            memories = memories[0]
        if not memories or len(memories) <= self.max_memories_per_user:
            return

        oldest_first = sorted(memories, key=lambda m: m.updated_at or 0)
        for stale_memory in oldest_first[: -self.max_memories_per_user]:
            if stale_memory.memory_id:
                self.db.delete_user_memory(memory_id=stale_memory.memory_id)

    def get_user_memories(self, user_id: Optional[str] = None) -> Optional[List[UserMemory]]:
        return super().get_user_memories(user_id=self._scoped(user_id))

    async def aget_user_memories(self, user_id: Optional[str] = None) -> Optional[List[UserMemory]]:
        return await super().aget_user_memories(user_id=self._scoped(user_id))

    def add_user_memory(
        self, memory: UserMemory, user_id: Optional[str] = None
    ) -> Optional[str]:
        scoped_user_id = self._scoped(user_id or memory.user_id)
        memory_id = super().add_user_memory(memory, scoped_user_id)
        if memory_id:
            self._enforce_limit(scoped_user_id)
        return memory_id

    # Agno calls these after each run (update_memory_on_run) — they write
    # through the db directly, so the cap has to be enforced here too.
    def create_user_memories(
        self,
        message: Optional[str] = None,
        messages: Optional[List[Message]] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> str:
        scoped_user_id = self._scoped(user_id)
        response = super().create_user_memories(
            message=message, messages=messages, agent_id=agent_id, team_id=team_id, user_id=scoped_user_id
        )
        self._enforce_limit(scoped_user_id)
        return response

    async def acreate_user_memories(
        self,
        message: Optional[str] = None,
        messages: Optional[List[Message]] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> str:
        scoped_user_id = self._scoped(user_id)
        response = await super().acreate_user_memories(
            message=message, messages=messages, agent_id=agent_id, team_id=team_id, user_id=scoped_user_id
        )
        self._enforce_limit(scoped_user_id)
        return response


class AgentMemoryManager:
    """
    Singleton manager for agent memory and database
    Thread-safe lazy initialization
    """

    _instance: Optional["AgentMemoryManager"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "AgentMemoryManager":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if hasattr(self, "_initialized") and self._initialized:
            return

        self._db_cache: Optional[CachedTablePostgresDb] = None
        self._memory_managers: dict[str, LimitedMemoryManager] = {}
        self._db_lock = threading.Lock()
        self._memory_lock = threading.Lock()
        self._initialized = True

    def get_db(self) -> CachedTablePostgresDb:
        """Get or create the shared Postgres db for agent sessions and memories"""
        if self._db_cache is None:
            with self._db_lock:
                if self._db_cache is None:
                    logger.info("Initializing PostgresDb for agent storage")
                    url = settings.POSTGRES_URL
                    # SQLAlchemy needs the driver named; psycopg (v3) is installed.
                    for prefix in ("postgresql://", "postgres://"):
                        if url.startswith(prefix):
                            url = "postgresql+psycopg://" + url[len(prefix):]
                            break
                    self._db_cache = CachedTablePostgresDb(
                        db_url=url,
                        db_schema="public",
                        session_table=SESSION_TABLE,
                        memory_table=MEMORY_TABLE,
                    )
        return self._db_cache

    def get_memory_manager(self, organization_id: Optional[str] = None) -> LimitedMemoryManager:
        """Get or create the memory manager for an organization"""
        key = organization_id or ""
        if key not in self._memory_managers:
            with self._memory_lock:
                if key not in self._memory_managers:
                    logger.info(f"Initializing memory manager for org: {organization_id or '-'}")
                    self._memory_managers[key] = LimitedMemoryManager(
                        organization_id=organization_id,
                        model=get_llm_agno(model=MEMORY_MODEL, provider="openrouter"),
                        db=self.get_db(),
                        memory_capture_instructions=MEMORY_CAPTURE_INSTRUCTIONS,
                    )
        return self._memory_managers[key]

    def clear_cache(self):
        """Clear cached instances"""
        with self._db_lock, self._memory_lock:
            self._db_cache = None
            self._memory_managers = {}

    @classmethod
    def reset_singleton(cls):
        """Reset singleton instance"""
        with cls._lock:
            if cls._instance:
                cls._instance.clear_cache()
                cls._instance = None


# Singleton instance
_agent_memory_manager: Optional[AgentMemoryManager] = None
_manager_lock = threading.Lock()


def get_agent_memory_manager() -> AgentMemoryManager:
    """Get or create singleton AgentMemoryManager instance"""
    global _agent_memory_manager

    if _agent_memory_manager is None:
        with _manager_lock:
            if _agent_memory_manager is None:
                _agent_memory_manager = AgentMemoryManager()

    return _agent_memory_manager


def get_agent_db() -> CachedTablePostgresDb:
    """Get the agent database (Postgres: sessions + memories)"""
    return get_agent_memory_manager().get_db()


def get_memory_manager(organization_id: Optional[str] = None) -> LimitedMemoryManager:
    """Get the memory manager for an organization"""
    return get_agent_memory_manager().get_memory_manager(organization_id)


def get_memory_db() -> CachedTablePostgresDb:
    """Get the Postgres db that holds long-term user memories (same as get_agent_db)"""
    return get_agent_memory_manager().get_db()


# Indexes for the queries the app runs on these tables. Agno only indexes
# user_id on memories and nothing on sessions, but every session query
# (list / load / rename / delete) filters on user_id and the list sorts by
# updated_at. Idempotent; run at startup once the tables exist.
AGENT_TABLE_INDEXES = (
    f"CREATE INDEX IF NOT EXISTS idx_{SESSION_TABLE}_user_updated "
    f"ON public.{SESSION_TABLE} (user_id, updated_at DESC)",
    f"CREATE INDEX IF NOT EXISTS idx_{MEMORY_TABLE}_user_updated "
    f"ON public.{MEMORY_TABLE} (user_id, updated_at DESC)",
)


def ensure_agent_indexes() -> None:
    from sqlalchemy import text

    with get_agent_db().db_engine.begin() as conn:
        for stmt in AGENT_TABLE_INDEXES:
            conn.execute(text(stmt))
