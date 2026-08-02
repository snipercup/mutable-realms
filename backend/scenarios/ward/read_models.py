from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class WardReadModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WardOccupantRead(WardReadModel):
    id: str
    name: str
    role: str
    condition: str | None
    disposition: str


class WardBedRead(WardReadModel):
    id: str
    name: str
    occupant: WardOccupantRead | None


class WardLocationRead(WardReadModel):
    world_id: str
    location_id: str
    revision: int = Field(ge=0)
    beds: list[WardBedRead]
    bed_count: int = Field(ge=0)
    occupied_bed_count: int = Field(ge=0)
