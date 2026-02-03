import logging
import socket
import subprocess
import time
from contextlib import contextmanager
from typing import Any, Iterator, Optional, Protocol

from pydantic import BaseModel

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor

    POSTGRES_AVAILABLE = True
except ImportError:
    psycopg2 = None  # type: ignore[assignment]
    RealDictCursor = None  # type: ignore[assignment]
    POSTGRES_AVAILABLE = False


logger = logging.getLogger(__name__)


POSTGRES_INSTALL_MESSAGE = (
    "PostgreSQL support requires the 'postgres' optional dependencies.\n"
    "Install with: pip install 'folio_data_import[postgres]'\n"
    "         or: uv add 'folio_data_import[postgres]'"
)


def require_postgres() -> None:
    """Raise ImportError with helpful message if psycopg2 is not available."""
    if not POSTGRES_AVAILABLE:
        raise ImportError(POSTGRES_INSTALL_MESSAGE)


class DatabaseCursor(Protocol):
    """Protocol describing the database cursor interface we use."""

    def execute(self, query: str, vars: Any = None) -> None: ...
    def fetchall(self) -> list[dict[str, Any]]: ...
    def fetchone(self) -> Optional[dict[str, Any]]: ...
    def close(self) -> None: ...


class DatabaseConnection(Protocol):
    """Protocol describing the database connection interface we use."""

    def cursor(self, cursor_factory: Any = None) -> DatabaseCursor: ...
    def commit(self) -> None: ...
    def rollback(self) -> None: ...
    def close(self) -> None: ...


class PostgresConfig(BaseModel):
    host: str
    port: int = 5432
    database: str
    user: str
    password: Optional[str] = None


class SSHTunnelConfig(BaseModel):
    ssh_path: Optional[str] = "ssh"
    ssh_tunnel: bool = False
    use_ssh_config: bool = False
    ssh_host: Optional[str] = None
    ssh_user: Optional[str] = None
    ssh_private_key_path: Optional[str] = None


def connect_postgres(cfg):
    require_postgres()
    return psycopg2.connect(
        host=cfg.host,
        port=cfg.port,
        dbname=cfg.database,
        user=cfg.user,
        password=cfg.password,
        connect_timeout=5,
        gssencmode="disable",
    )


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_port(host: str, port: int, timeout: float = 5.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.05)
    raise TimeoutError(f"SSH tunnel did not open port {port}")


@contextmanager
def ssh_tunnel(
    *,
    ssh_path: Optional[str],
    ssh_host: str,
    remote_host: str,
    remote_port: int,
) -> Iterator[int]:
    local_port = _free_port()

    proc = subprocess.Popen(  # noqa: S603
        [
            ssh_path or "ssh",
            "-N",
            "-L",
            f"{local_port}:{remote_host}:{remote_port}",
            "-o",
            "ExitOnForwardFailure=yes",
            ssh_host,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        _wait_for_port("127.0.0.1", local_port)
        yield local_port
    finally:
        proc.terminate()
        proc.wait()


@contextmanager
def db_session(
    *,
    db_config: PostgresConfig,
    ssh_tunnel_config: Optional[SSHTunnelConfig] = None,
) -> Iterator[DatabaseConnection]:
    conn: Optional[DatabaseConnection] = None

    try:
        if ssh_tunnel_config and ssh_tunnel_config.ssh_tunnel:
            if not ssh_tunnel_config.ssh_host:
                raise ValueError("ssh_host is required when ssh_tunnel is enabled")

            with ssh_tunnel(
                ssh_path=ssh_tunnel_config.ssh_path,
                ssh_host=ssh_tunnel_config.ssh_host,
                remote_host=db_config.host,
                remote_port=db_config.port,
            ) as local_port:
                pg_cfg = db_config.model_copy()
                pg_cfg.host = "127.0.0.1"
                pg_cfg.port = local_port
                logger.info("Tunnel listening on port %s", local_port)

                conn = connect_postgres(pg_cfg)
                yield conn
                conn.commit()
        else:
            conn = connect_postgres(db_config)
            yield conn
            conn.commit()

    except Exception:
        if conn:
            conn.rollback()
        raise

    finally:
        if conn:
            conn.close()
