"""Read-only access to Blocky's query log database.

Everything here is synchronous and must run in an executor. Every statement
is built with SQLAlchemy Core, so values are always bound parameters. Text
read from the log is attacker-controlled (any client can put arbitrary names
into a DNS query) and is cleaned before it leaves this module.
"""

from __future__ import annotations

import importlib.util
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    case,
    create_engine,
    distinct,
    func,
    inspect,
    select,
    text,
)
from sqlalchemy.engine import URL, Engine
from sqlalchemy.exc import NoSuchTableError, SQLAlchemyError

LOG_TABLE_NAME: Final = "log_entries"

LOG_TABLE: Final = Table(
    LOG_TABLE_NAME,
    MetaData(),
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("request_ts", DateTime, nullable=False),
    Column("client_ip", String(255)),
    Column("client_name", String(255)),
    Column("duration_ms", BigInteger),
    Column("reason", Text),
    Column("response_type", String(255)),
    Column("question_type", String(255)),
    Column("question_name", Text),
    Column("effective_tldp", Text),
    Column("answer", Text),
    Column("response_code", String(255)),
    Column("hostname", String(255)),
)

# Columns this integration reads; the table must have at least these.
REQUIRED_COLUMNS: Final = frozenset(
    {"id", "request_ts", "client_ip", "duration_ms", "response_type", "question_name"}
)

# Response types Blocky uses for a query it refused to answer.
BLOCKED_RESPONSE_TYPES: Final = ("BLOCKED", "REBIND")

# Privileges that let an account change data or structure.
WRITE_PRIVILEGES: Final = frozenset(
    {
        "ALL PRIVILEGES",
        "ALTER",
        "ALTER ROUTINE",
        "CREATE",
        "CREATE ROUTINE",
        "CREATE USER",
        "DELETE",
        "DELETE HISTORY",
        "DROP",
        "EVENT",
        "FILE",
        "GRANT OPTION",
        "INDEX",
        "INSERT",
        "SUPER",
        "TRIGGER",
        "UPDATE",
    }
)

MAX_TEXT_LENGTH: Final = 253
MAX_TOP_ITEMS: Final = 10
STATEMENT_TIMEOUT_SECONDS: Final = 10
CONNECT_TIMEOUT_SECONDS: Final = 5

_HOST_RE: Final = re.compile(r"[A-Za-z0-9]([A-Za-z0-9._-]{0,251}[A-Za-z0-9])?")
_DATABASE_RE: Final = re.compile(r"[A-Za-z0-9_$-]{1,64}")
# The characters the Home Assistant MariaDB app accepts in a user name; the
# value is passed to the driver as a quoted URL component, never spliced
# into SQL.
_USERNAME_RE: Final = re.compile(
    r"[A-Za-z0-9_.@$-]([A-Za-z0-9_.@$ -]{0,126}[A-Za-z0-9_.@$-])?"
)
_GRANT_RE: Final = re.compile(r"^GRANT\s+(?P<privileges>.+?)\s+ON\s+", re.IGNORECASE)
_PAREN_RE: Final = re.compile(r"\([^)]*\)")


class BlockyDbError(Exception):
    """The query log database could not be used."""


class BlockyDbSettingsError(BlockyDbError):
    """The connection settings are not acceptable."""


class BlockyDbDriverError(BlockyDbError):
    """No MySQL driver is installed."""


class BlockyDbSchemaError(BlockyDbError):
    """The database does not contain Blocky's query log table."""


class BlockyDbNotReadOnlyError(BlockyDbError):
    """The account can change data; a read-only account is required."""


@dataclass(frozen=True, slots=True)
class DbSettings:
    """Validated connection settings."""

    host: str
    port: int
    database: str
    username: str
    password: str


@dataclass(frozen=True, slots=True)
class Counts:
    """Rows added after a cursor position."""

    max_id: int
    queries: int
    blocked: int


@dataclass(frozen=True, slots=True)
class Summary:
    """Aggregates over a time window."""

    queries: int
    blocked: int
    clients: int
    avg_duration_ms: float | None
    latest_request: datetime | None


@dataclass(frozen=True, slots=True)
class TopItem:
    """One row of a top list."""

    name: str
    count: int


def validate_settings(
    host: object, port: object, database: object, username: object, password: object
) -> DbSettings:
    """Validate connection settings entered by the user."""
    if not isinstance(host, str) or _HOST_RE.fullmatch(host.strip()) is None:
        raise BlockyDbSettingsError("host")
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise BlockyDbSettingsError("port")
    if not isinstance(database, str) or _DATABASE_RE.fullmatch(database) is None:
        raise BlockyDbSettingsError("database")
    if not isinstance(username, str) or _USERNAME_RE.fullmatch(username) is None:
        raise BlockyDbSettingsError("username")
    if (
        not isinstance(password, str)
        or not 1 <= len(password) <= 256
        or any(ord(char) < 0x20 or ord(char) == 0x7F for char in password)
    ):
        raise BlockyDbSettingsError("password")
    return DbSettings(host.strip(), port, database, username, password)


def _mysql_driver() -> str:
    """Return the SQLAlchemy driver name of an installed MySQL driver."""
    if importlib.util.find_spec("MySQLdb") is not None:
        return "mysql+mysqldb"
    if importlib.util.find_spec("pymysql") is not None:
        return "mysql+pymysql"
    raise BlockyDbDriverError("no MySQL driver installed")


def build_url(settings: DbSettings) -> URL:
    """Build the connection URL; SQLAlchemy quotes every component."""
    return URL.create(
        _mysql_driver(),
        username=settings.username,
        password=settings.password,
        host=settings.host,
        port=settings.port,
        database=settings.database,
        query={"charset": "utf8mb4"},
    )


def privileges_allow_writes(grants: list[str]) -> bool:
    """Return whether any ``SHOW GRANTS`` line carries a write privilege."""
    for grant in grants:
        match = _GRANT_RE.match(grant.strip())
        if match is None:
            # Not a privilege grant (for example a role); treat as unsafe.
            return True
        if "GRANT OPTION" in grant.upper():
            return True
        privileges = _PAREN_RE.sub("", match.group("privileges"))
        for privilege in privileges.split(","):
            if privilege.strip().upper() in WRITE_PRIVILEGES:
                return True
    return False


def clean_text(value: object) -> str:
    """Make a string read from the log safe to show: no controls, bounded."""
    if not isinstance(value, str):
        return ""
    cleaned = "".join(char for char in value if char.isprintable())
    return cleaned[:MAX_TEXT_LENGTH]


class QueryLogDatabase:
    """A lazily connected, read-only view of the query log."""

    def __init__(self, url: URL) -> None:
        """Remember where the database is; nothing is opened yet."""
        self._url = url
        self._engine: Engine | None = None

    @property
    def dialect(self) -> str:
        """Return the database dialect name."""
        return self._url.get_backend_name()

    def _create_engine(self) -> Engine:
        if self.dialect == "sqlite":
            return create_engine(self._url)
        return create_engine(
            self._url,
            pool_size=1,
            max_overflow=1,
            pool_pre_ping=True,
            pool_recycle=1800,
            connect_args={"connect_timeout": CONNECT_TIMEOUT_SECONDS},
        )

    def connect(self) -> None:
        """Open the database and verify it is Blocky's log, read-only."""
        if self._engine is not None:
            return
        try:
            engine = self._create_engine()
        except (SQLAlchemyError, ImportError) as err:
            raise BlockyDbError(type(err).__name__) from err

        try:
            with engine.connect() as connection:
                connection.execute(select(1))
                try:
                    columns = {
                        column["name"]
                        for column in inspect(connection).get_columns(LOG_TABLE_NAME)
                    }
                except NoSuchTableError as err:
                    raise BlockyDbSchemaError("table missing") from err
                if not columns >= REQUIRED_COLUMNS:
                    raise BlockyDbSchemaError("columns missing")
                if self.dialect == "mysql":
                    grants = [
                        str(row[0])
                        for row in connection.execute(
                            text("SHOW GRANTS FOR CURRENT_USER")
                        )
                    ]
                    if privileges_allow_writes(grants):
                        raise BlockyDbNotReadOnlyError("account can write")
        except BlockyDbError:
            engine.dispose()
            raise
        except SQLAlchemyError as err:
            engine.dispose()
            raise BlockyDbError(type(err).__name__) from err
        self._engine = engine

    def close(self) -> None:
        """Close all connections."""
        if self._engine is not None:
            self._engine.dispose()
            self._engine = None

    def _run(self, statement, *, one: bool = True):  # type: ignore[no-untyped-def]
        """Execute a read statement with a bounded run time."""
        self.connect()
        engine = self._engine
        if engine is None:
            raise BlockyDbError("not connected")
        try:
            with engine.connect() as connection:
                if self.dialect == "mysql":
                    try:
                        connection.execute(
                            text("SET SESSION max_statement_time = :seconds"),
                            {"seconds": STATEMENT_TIMEOUT_SECONDS},
                        )
                    except SQLAlchemyError:
                        # Not MariaDB; run without a statement timeout.
                        connection.rollback()
                result = connection.execute(statement)
                return result.one() if one else result.all()
        except SQLAlchemyError as err:
            # Drop the engine so the next call reconnects and re-validates.
            self.close()
            raise BlockyDbError(type(err).__name__) from err

    def max_id(self) -> int:
        """Return the highest row id, or 0 for an empty table."""
        row = self._run(select(func.max(LOG_TABLE.c.id)))
        return int(row[0] or 0)

    def counts_since(self, last_id: int) -> Counts:
        """Count rows with an id above ``last_id``."""
        blocked = case(
            (LOG_TABLE.c.response_type.in_(BLOCKED_RESPONSE_TYPES), 1), else_=0
        )
        row = self._run(
            select(func.max(LOG_TABLE.c.id), func.count(), func.sum(blocked)).where(
                LOG_TABLE.c.id > last_id
            )
        )
        return Counts(
            max_id=int(row[0] or last_id),
            queries=int(row[1] or 0),
            blocked=int(row[2] or 0),
        )

    def summary(self, since: datetime) -> Summary:
        """Aggregate the rows newer than ``since`` (naive UTC)."""
        blocked = case(
            (LOG_TABLE.c.response_type.in_(BLOCKED_RESPONSE_TYPES), 1), else_=0
        )
        row = self._run(
            select(
                func.count(),
                func.sum(blocked),
                func.count(distinct(LOG_TABLE.c.client_ip)),
                func.avg(LOG_TABLE.c.duration_ms),
                func.max(LOG_TABLE.c.request_ts),
            ).where(LOG_TABLE.c.request_ts >= since)
        )
        latest = row[4]
        if isinstance(latest, str):
            latest = datetime.fromisoformat(latest)
        return Summary(
            queries=int(row[0] or 0),
            blocked=int(row[1] or 0),
            clients=int(row[2] or 0),
            avg_duration_ms=float(row[3]) if row[3] is not None else None,
            latest_request=latest if isinstance(latest, datetime) else None,
        )

    def _top(self, column, since: datetime, *, blocked_only: bool) -> list[TopItem]:  # type: ignore[no-untyped-def]
        count = func.count().label("hits")
        statement = (
            select(column, count)
            .where(LOG_TABLE.c.request_ts >= since)
            .where(column.is_not(None))
            .where(column != "")
            .group_by(column)
            .order_by(count.desc(), column)
            .limit(MAX_TOP_ITEMS)
        )
        if blocked_only:
            statement = statement.where(
                LOG_TABLE.c.response_type.in_(BLOCKED_RESPONSE_TYPES)
            )
        items = []
        for name, hits in self._run(statement, one=False):
            cleaned = clean_text(name)
            if cleaned:
                items.append(TopItem(cleaned, int(hits)))
        return items

    def top_domains(self, since: datetime) -> list[TopItem]:
        """Return the most queried domains."""
        return self._top(LOG_TABLE.c.question_name, since, blocked_only=False)

    def top_blocked_domains(self, since: datetime) -> list[TopItem]:
        """Return the most blocked domains."""
        return self._top(LOG_TABLE.c.question_name, since, blocked_only=True)

    def top_clients(self, since: datetime) -> list[TopItem]:
        """Return the clients with the most queries."""
        return self._top(LOG_TABLE.c.client_ip, since, blocked_only=False)
