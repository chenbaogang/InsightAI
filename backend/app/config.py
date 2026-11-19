from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    database_url: str

    datasource_dialect: str
    datasource_url: str = ""

    starrocks_host: str = ""
    starrocks_port: int = 9030
    starrocks_db: str = ""
    starrocks_user: str = ""
    starrocks_password: str = ""

    llm_base_url: str = ""
    llm_model: str = "qwen-local"
    llm_api_key: str = "EMPTY"
    llm_timeout: int = 60
    llm_temperature: float = 0.0
    llm_max_tokens: int = 8192
    llm_enable_thinking: bool = False
    self_correct_retries: int = 2

    query_row_limit: int = 1000
    query_timeout: int = 10

    admin_init_password: str = ""

    token_secret: str = ""
    token_ttl_minutes: int = 480
    login_max_fails: int = 5
    login_lock_minutes: int = 15
    login_rate_per_minute: int = 5

    redis_url: str = ""

    lance_dir: str = str(DATA / "lance").replace("\\", "/")
    embedding_provider: str = "bge-m3"
    embedding_model_dir: str = ""

    @property
    def effective_datasource_url(self) -> str:
        if self.datasource_dialect == "starrocks":
            from sqlalchemy.engine import URL

            return URL.create(
                "mysql+pymysql",
                username=self.starrocks_user,
                password=self.starrocks_password,
                host=self.starrocks_host,
                port=self.starrocks_port,
                database=self.starrocks_db,
            ).render_as_string(hide_password=False)
        return self.datasource_url


@lru_cache
def get_settings() -> Settings:
    return Settings()

