import os
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class Environment(StrEnum):
    LOCAL = "local"
    STAGING = "staging"
    PRODUCTION = "production"


@dataclass(frozen=True)
class DatabaseConfig:
    host: str = "localhost"
    port: int = 5432
    name: str = "app"
    pool_min: int = 2
    pool_max: int = 10

    @property
    def url(self) -> str:
        return f"postgresql://{self.host}:{self.port}/{self.name}"


@dataclass(frozen=True)
class RedisConfig:
    host: str = "localhost"
    port: int = 6379
    db: int = 0
    prefix: str = "app"

    @property
    def url(self) -> str:
        return f"redis://{self.host}:{self.port}/{self.db}"


@dataclass(frozen=True)
class AppConfig:
    env: Environment = Environment.LOCAL
    debug: bool = False
    log_level: str = "INFO"
    db: DatabaseConfig = field(default_factory=DatabaseConfig)
    redis: RedisConfig = field(default_factory=RedisConfig)

    @classmethod
    def from_env(cls) -> "AppConfig":
        env = Environment(os.environ.get("APP_ENV", "local"))
        return cls(
            env=env,
            debug=env == Environment.LOCAL,
            log_level=os.environ.get("LOG_LEVEL", "INFO"),
            db=DatabaseConfig(
                host=os.environ.get("DB_HOST", "localhost"),
                port=int(os.environ.get("DB_PORT", "5432")),
                name=os.environ.get("DB_NAME", "app"),
                pool_min=int(os.environ.get("DB_POOL_MIN", "2")),
                pool_max=int(os.environ.get("DB_POOL_MAX", "10")),
            ),
            redis=RedisConfig(
                host=os.environ.get("REDIS_HOST", "localhost"),
                port=int(os.environ.get("REDIS_PORT", "6379")),
                db=int(os.environ.get("REDIS_DB", "0")),
                prefix=os.environ.get("REDIS_PREFIX", "app"),
            ),
        )


def load_config(config_dir: str | Path = ".") -> AppConfig:
    env_file = Path(config_dir) / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())
    return AppConfig.from_env()
