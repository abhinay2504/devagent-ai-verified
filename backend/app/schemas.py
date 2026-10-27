from pydantic import BaseModel, Field, field_validator


class TaskCreate(BaseModel):
    description: str = Field(min_length=8, max_length=2000)
    repo_path: str = Field(min_length=1, max_length=300, description="Path relative to workspace root")

    @field_validator("description")
    @classmethod
    def description_must_contain_text(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 8:
            raise ValueError("Task description must contain at least 8 non-whitespace characters.")
        return value

    @field_validator("repo_path")
    @classmethod
    def normalize_repo_path(cls, value: str) -> str:
        value = value.strip().replace("\\", "/")
        if not value:
            raise ValueError("Repository path cannot be empty.")
        return value


class TaskOut(BaseModel):
    id: str
    description: str
    repo_path: str
    status: str
    created_at: str
    updated_at: str
    error: str | None = None
    plan_json: str | None = None


class ApprovalRequest(BaseModel):
    approve: bool
    feedback: str | None = Field(default=None, max_length=1000)


class ModelStatus(BaseModel):
    available: bool
    model: str
    message: str
