"""Pydantic schemas for probe groups."""

import uuid

from pydantic import BaseModel, Field


class ProbeGroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None


class ProbeGroupUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None


class ProbeGroupOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    probe_ids: list[uuid.UUID]
    user_ids: list[uuid.UUID]

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_obj(cls, obj: object) -> "ProbeGroupOut":
        def _to_list(val: object) -> list:
            if val is None:
                return []
            if isinstance(val, list):
                return val
            return [val]  # single ORM object returned instead of collection

        return cls(
            id=obj.id,  # type: ignore[attr-defined]
            name=obj.name,  # type: ignore[attr-defined]
            description=obj.description,  # type: ignore[attr-defined]
            probe_ids=[p.id for p in _to_list(obj.probes)],  # type: ignore[attr-defined]
            user_ids=[u.id for u in _to_list(obj.users)],  # type: ignore[attr-defined]
        )
