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
from typing import Any, Final

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
    not_,
    or_,
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

# Every query falls into exactly one category, so the categories of a
# period add up to its total. Unknown response types count as other.
CATEGORY_RESOLVED: Final = "resolved"
CATEGORY_CACHED: Final = "cached"
CATEGORY_LOCAL: Final = "local"
CATEGORY_BLOCKED: Final = "blocked"
CATEGORY_OTHER: Final = "other"
CATEGORIES: Final = (
    CATEGORY_RESOLVED,
    CATEGORY_CACHED,
    CATEGORY_LOCAL,
    CATEGORY_BLOCKED,
    CATEGORY_OTHER,
)
_RESPONSE_CATEGORY: Final = {
    "RESOLVED": CATEGORY_RESOLVED,
    "CACHED": CATEGORY_CACHED,
    "CONDITIONAL": CATEGORY_LOCAL,
    "CUSTOMDNS": CATEGORY_LOCAL,
    "HOSTSFILE": CATEGORY_LOCAL,
    "SPECIAL": CATEGORY_LOCAL,
    "SYNTHESIZED": CATEGORY_LOCAL,
    **dict.fromkeys(BLOCKED_RESPONSE_TYPES, CATEGORY_BLOCKED),
}


def response_category(response_type: object) -> str:
    """Return the category a response type is counted in."""
    if not isinstance(response_type, str):
        return CATEGORY_OTHER
    return _RESPONSE_CATEGORY.get(response_type, CATEGORY_OTHER)


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
    categories: dict[str, int]


@dataclass(frozen=True, slots=True)
class Summary:
    """Aggregates over a time window."""

    queries: int
    blocked: int
    clients: int
    avg_duration_ms: float | None
    latest_request: datetime | None


@dataclass(frozen=True, slots=True)
class LogRow:
    """The few columns of a log row the request tracker needs, uncleaned.

    The values are hostile text; the caller validates every one of them.
    """

    id: int
    client: str | None
    domain: str | None
    response_type: str | None
    requested: datetime | None


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
        """Count rows with an id above ``last_id``, by category."""
        rows = self._run(
            select(
                LOG_TABLE.c.response_type,
                func.count(),
                func.max(LOG_TABLE.c.id),
            )
            .where(LOG_TABLE.c.id > last_id)
            .group_by(LOG_TABLE.c.response_type),
            one=False,
        )
        categories = dict.fromkeys(CATEGORIES, 0)
        max_id = last_id
        for response_type, count, highest in rows:
            categories[response_category(response_type)] += int(count or 0)
            max_id = max(max_id, int(highest or 0))
        return Counts(
            max_id=max_id,
            queries=sum(categories.values()),
            blocked=categories[CATEGORY_BLOCKED],
            categories=categories,
        )

    def rows_after(self, last_id: int, limit: int) -> list[LogRow]:
        """Return up to ``limit`` rows with an id above ``last_id``, oldest first."""
        table = LOG_TABLE.c
        statement = (
            select(
                table.id,
                table.client_ip,
                table.question_name,
                table.response_type,
                table.request_ts,
            )
            .where(table.id > last_id)
            .order_by(table.id)
            .limit(max(1, min(int(limit), 10000)))
        )
        rows: list[LogRow] = []
        for row_id, client, domain, response_type, requested in self._run(
            statement, one=False
        ):
            if isinstance(requested, str):
                try:
                    requested = datetime.fromisoformat(requested)
                except ValueError:
                    requested = None
            rows.append(
                LogRow(
                    id=int(row_id),
                    client=client if isinstance(client, str) else None,
                    domain=domain if isinstance(domain, str) else None,
                    response_type=(
                        response_type if isinstance(response_type, str) else None
                    ),
                    requested=requested if isinstance(requested, datetime) else None,
                )
            )
        return rows

    def client_domains(
        self, client: str, since: datetime, limit: int
    ) -> list[str | None]:
        """Return the distinct names a client asked for since ``since``.

        ``since`` is naive UTC. Raw values: the caller validates them.
        """
        table = LOG_TABLE.c
        statement = (
            select(distinct(table.question_name))
            .where(table.client_ip == client)
            .where(table.request_ts >= since)
            .where(table.question_name.is_not(None))
            .limit(max(1, min(int(limit), 5000)))
        )
        return [
            name if isinstance(name, str) else None
            for (name,) in self._run(statement, one=False)
        ]

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

    def client_counts(
        self, since: datetime, limit: int = 5000
    ) -> list[tuple[str, int, int]]:
        """Return (client address, queries, blocked) per client since ``since``."""
        blocked = case(
            (LOG_TABLE.c.response_type.in_(BLOCKED_RESPONSE_TYPES), 1), else_=0
        )
        total = func.count().label("total")
        statement = (
            select(LOG_TABLE.c.client_ip, total, func.sum(blocked))
            .where(LOG_TABLE.c.request_ts >= since)
            .where(LOG_TABLE.c.client_ip.is_not(None))
            .group_by(LOG_TABLE.c.client_ip)
            .order_by(total.desc(), LOG_TABLE.c.client_ip)
            .limit(max(1, min(int(limit), 5000)))
        )
        counts: list[tuple[str, int, int]] = []
        for address, queries, blocked_queries in self._run(statement, one=False):
            cleaned = clean_text(address)
            if cleaned:
                counts.append((cleaned, int(queries or 0), int(blocked_queries or 0)))
        return counts

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

    def query_log(
        self,
        *,
        since: datetime,
        client: str | None = None,
        domain: str | None = None,
        blocked: bool | None = None,
        before_id: int | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Return log rows, newest first, as plain cleaned values.

        ``domain`` matches anywhere in the name; the pattern characters ``%``
        and ``_`` in it are escaped, so it is always a literal search.
        """
        table = LOG_TABLE.c
        is_blocked = table.response_type.in_(BLOCKED_RESPONSE_TYPES)
        statement = select(
            table.id,
            table.request_ts,
            table.client_ip,
            table.question_name,
            table.question_type,
            table.response_type,
            table.response_code,
            table.duration_ms,
            table.reason,
        ).where(table.request_ts >= since)
        if before_id is not None:
            statement = statement.where(table.id < before_id)
        if client:
            statement = statement.where(table.client_ip == client)
        if domain:
            statement = statement.where(
                table.question_name.contains(domain, autoescape=True)
            )
        if blocked is True:
            statement = statement.where(is_blocked)
        elif blocked is False:
            statement = statement.where(
                or_(table.response_type.is_(None), not_(is_blocked))
            )
        statement = statement.order_by(table.id.desc()).limit(limit)

        rows: list[dict[str, Any]] = []
        for row in self._run(statement, one=False):
            requested = row[1]
            if isinstance(requested, str):
                requested = datetime.fromisoformat(requested)
            response_type = clean_text(row[5])
            rows.append(
                {
                    "id": int(row[0]),
                    "time": (
                        f"{requested.isoformat(timespec='seconds')}+00:00"
                        if isinstance(requested, datetime)
                        else None
                    ),
                    "client": clean_text(row[2]),
                    "domain": clean_text(row[3]),
                    "query_type": clean_text(row[4])[:16],
                    "response_type": response_type[:32],
                    "response_code": clean_text(row[6])[:32],
                    "duration_ms": int(row[7] or 0),
                    "reason": clean_text(row[8]),
                    "blocked": response_type in BLOCKED_RESPONSE_TYPES,
                }
            )
        return rows
