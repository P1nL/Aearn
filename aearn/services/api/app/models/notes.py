from pydantic import BaseModel, Field, field_validator


class NoteSource(BaseModel):
    session_id: str | None = None
    attempt_id: str | None = None


class CreateNoteRequest(BaseModel):
    user_id: str = Field(min_length=1)
    knowledge_point_id: str = Field(min_length=1)
    title: str | None = None
    content_markdown: str = ""
    source: NoteSource | None = None

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class UpdateNoteRequest(BaseModel):
    title: str | None = None
    content_markdown: str | None = None
    is_user_edited: bool = True

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class AgentDraftRequest(BaseModel):
    user_id: str = Field(min_length=1)
    style: str = "concise"
    focus: str = "mistake_summary"
    source: NoteSource | None = None
