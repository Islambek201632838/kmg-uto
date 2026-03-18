from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import BigInteger, Index, Integer, Numeric, String, Text, Float
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class RoadNode(Base):
    __tablename__ = "road_nodes"
    __table_args__ = (
        Index("ix_road_nodes_node_id", "node_id", unique=True),
        Index("ix_road_nodes_lon_lat", "lon", "lat"),
        {"schema": "references"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    node_id: Mapped[int] = mapped_column(Integer, nullable=False)
    lon: Mapped[Decimal] = mapped_column(Numeric(12, 8), nullable=False)
    lat: Mapped[Decimal] = mapped_column(Numeric(12, 8), nullable=False)


class RoadEdge(Base):
    __tablename__ = "road_edges"
    __table_args__ = (
        Index("ix_road_edges_source", "source"),
        Index("ix_road_edges_target", "target"),
        Index("ix_road_edges_source_target", "source", "target"),
        {"schema": "references"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[int] = mapped_column(Integer, nullable=False)
    target: Mapped[int] = mapped_column(Integer, nullable=False)
    weight: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)


class Well(Base):
    __tablename__ = "wells"
    __table_args__ = (
        Index("ix_wells_uwi", "uwi", unique=True),
        Index("ix_wells_lat_lon", "latitude", "longitude"),
        {"schema": "references"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    uwi: Mapped[str] = mapped_column(String(50), nullable=False)
    latitude: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 8), nullable=True)
    longitude: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 8), nullable=True)
    well_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)


class WialonSnapshot1(Base):
    __tablename__ = "wialon_units_snapshot_1"
    __table_args__ = (
        Index("ix_wialon_snap1_wialon_id", "wialon_id"),
        {"schema": "references"},
    )

    wialon_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    nm: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    cls: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    mu: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    pos_t: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    pos_y: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    pos_x: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    registration_plate: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    payload_json: Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)


class WialonSnapshot2(Base):
    __tablename__ = "wialon_units_snapshot_2"
    __table_args__ = (
        Index("ix_wialon_snap2_wialon_id", "wialon_id"),
        {"schema": "references"},
    )

    wialon_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    nm: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    cls: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    mu: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    pos_t: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    pos_y: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    pos_x: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    registration_plate: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    payload_json: Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)


class WialonSnapshot3(Base):
    __tablename__ = "wialon_units_snapshot_3"
    __table_args__ = (
        Index("ix_wialon_snap3_wialon_id", "wialon_id"),
        {"schema": "references"},
    )

    wialon_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    nm: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    cls: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    mu: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    pos_t: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    pos_y: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    pos_x: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    registration_plate: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    payload_json: Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)


class Dictionary(Base):
    __tablename__ = "dictionaries"
    __table_args__ = (
        Index("ix_dictionaries_code", "code"),
        Index("ix_dictionaries_active", "active"),
        {"schema": "dct"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[Any] = mapped_column(JSONB, nullable=False)
    description: Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)
    code: Mapped[str] = mapped_column(String(128), nullable=False)
    active: Mapped[bool] = mapped_column(nullable=False)
    type: Mapped[str] = mapped_column(String(4), nullable=False)


class Element(Base):
    __tablename__ = "elements"
    __table_args__ = (
        Index("ix_elements_dictionary_id", "dictionary_id"),
        Index("ix_elements_code", "code"),
        Index("ix_elements_parent_id", "parent_id"),
        {"schema": "dct"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    short_name: Mapped[Any] = mapped_column(JSONB, nullable=False)
    full_name: Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)
    code: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    active: Mapped[bool] = mapped_column(nullable=False)
    dictionary_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    parent_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    index_sort: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
