"""Job files: a YAML document describing one batch of prompts and where to send them."""

from __future__ import annotations

import pathlib
from typing import List, Optional

import yaml
from pydantic import BaseModel, Field, field_validator

from . import compat


class BudgetConfig(BaseModel):
    tokens_per_minute: int = Field(90_000, gt=0)


class ClientConfig(BaseModel):
    endpoint: str = "http://127.0.0.1:8000/v1/completions"
    max_in_flight: int = Field(8, ge=1)
    max_attempts: int = Field(4, ge=1)
    backoff: float = Field(0.5, ge=0)
    timeout: float = Field(60.0, gt=0)


class ServerConfig(BaseModel):
    command: Optional[List[str]] = None  # "{port}" in an argument is replaced by the replica's port
    replicas: int = Field(1, ge=1)
    base_port: int = 8000
    host: str = "127.0.0.1"
    startup_timeout: float = Field(120.0, gt=0)
    poll_interval: float = Field(0.5, gt=0)

    def port(self, replica: int) -> int:
        return self.base_port + replica

    def command_for(self, replica: int) -> List[str]:
        return [arg.replace("{port}", str(self.port(replica))) for arg in self.command or []]


class JobConfig(BaseModel):
    name: str
    model: str
    prompts: pathlib.Path
    output: pathlib.Path
    log_dir: pathlib.Path = pathlib.Path("runs")
    budget: BudgetConfig = BudgetConfig()
    client: ClientConfig = ClientConfig()
    server: ServerConfig = ServerConfig()

    @field_validator("name")
    @classmethod
    def _name_is_a_file_name(cls, value: str) -> str:
        if not value or "/" in value or value.startswith("."):
            raise ValueError("name must be usable as a file name")
        return value


def load_config(path) -> JobConfig:
    """Read a job file. Relative paths in it are relative to the job file's directory."""
    path = pathlib.Path(path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: a job file must be a mapping")
    config = JobConfig.model_validate(compat.upgrade(raw))
    base = path.parent
    for field in ("prompts", "output", "log_dir"):
        value = getattr(config, field)
        if not value.is_absolute():
            setattr(config, field, base / value)
    return config
