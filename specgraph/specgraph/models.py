"""Доменная модель.

Изделие (Product) — иерархия (система → подсистема → блок → деталь).
Требование (Requirement) — иерархия (раздел → подтребование) + атрибуты верификации.
Связи типизированы, чтобы LLM могла тянуть только нужный подграф.
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from specgraph.db import Base


class DocumentKind(str, enum.Enum):
    DOCX = "docx"
    DOC = "doc"
    MACRO_DOC = "macro_doc"  # .docm / документ со скриптами
    PARSED_JSON = "parsed_json"
    XLSX = "xlsx"
    OTHER = "other"


class RequirementKind(str, enum.Enum):
    FUNCTIONAL = "functional"
    INTERFACE = "interface"
    PERFORMANCE = "performance"
    SAFETY = "safety"
    RELIABILITY = "reliability"
    ENVIRONMENT = "environment"
    REGULATORY = "regulatory"
    DESIGN = "design"
    UNKNOWN = "unknown"


class RelationType(str, enum.Enum):
    APPLIES_TO = "applies_to"  # требование → изделие
    COMPOSED_OF = "composed_of"  # изделие → изделие
    REFINES = "refines"  # требование → более общее требование
    DEPENDS_ON = "depends_on"
    CONFLICTS_WITH = "conflicts_with"
    ILLUSTRATED_BY = "illustrated_by"
    DERIVED_FROM = "derived_from"
    VERIFIED_BY = "verified_by"
    IMPLEMENTS = "implements"  # модуль ПО → требование (TPO/OPPO)


class EntityType(str, enum.Enum):
    PRODUCT = "product"
    REQUIREMENT = "requirement"
    ILLUSTRATION = "illustration"
    DOCUMENT = "document"


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    filename: Mapped[str] = mapped_column(String(512))
    kind: Mapped[DocumentKind] = mapped_column(Enum(DocumentKind), default=DocumentKind.DOCX)
    storage_path: Mapped[str] = mapped_column(String(1024))
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    parse_meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="uploaded")
    uploaded_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    products: Mapped[list[Product]] = relationship(back_populates="document")
    requirements: Mapped[list[Requirement]] = relationship(back_populates="document")
    illustrations: Mapped[list[Illustration]] = relationship(back_populates="document")


class Product(Base):
    """Изделие / составная часть. Дерево parent_id отражает состав изделия."""

    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"))
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"), nullable=True)
    code: Mapped[str] = mapped_column(String(128), index=True)
    name: Mapped[str] = mapped_column(String(512))
    level: Mapped[int] = mapped_column(Integer, default=0)
    section_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    extra: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    document: Mapped[Document] = relationship(back_populates="products")
    parent: Mapped[Product | None] = relationship(remote_side=[id], back_populates="children")
    children: Mapped[list[Product]] = relationship(back_populates="parent")
    attributes: Mapped[list[ProductAttribute]] = relationship(back_populates="product", cascade="all, delete-orphan")
    requirements: Mapped[list[Requirement]] = relationship(back_populates="product")


class ProductAttribute(Base):
    __tablename__ = "product_attributes"
    __table_args__ = (UniqueConstraint("product_id", "key", name="uq_product_attr"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    key: Mapped[str] = mapped_column(String(128))
    value: Mapped[str] = mapped_column(Text)
    unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source: Mapped[str | None] = mapped_column(String(256), nullable=True)

    product: Mapped[Product] = relationship(back_populates="attributes")


class Requirement(Base):
    __tablename__ = "requirements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"))
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"), nullable=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("requirements.id"), nullable=True)
    code: Mapped[str] = mapped_column(String(256), index=True)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    text: Mapped[str] = mapped_column(Text)
    kind: Mapped[RequirementKind] = mapped_column(Enum(RequirementKind), default=RequirementKind.UNKNOWN)
    section_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    extra: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    base_code: Mapped[str] = mapped_column(String(256), index=True, default="")
    revision: Mapped[str | None] = mapped_column(String(32), nullable=True)
    is_current: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    document: Mapped[Document] = relationship(back_populates="requirements")
    product: Mapped[Product | None] = relationship(back_populates="requirements")
    parent: Mapped[Requirement | None] = relationship(remote_side=[id], back_populates="children")
    children: Mapped[list[Requirement]] = relationship(back_populates="parent")
    attributes: Mapped[list[RequirementAttribute]] = relationship(
        back_populates="requirement", cascade="all, delete-orphan"
    )


class RequirementAttribute(Base):
    __tablename__ = "requirement_attributes"
    __table_args__ = (UniqueConstraint("requirement_id", "key", name="uq_req_attr"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    requirement_id: Mapped[int] = mapped_column(ForeignKey("requirements.id"))
    key: Mapped[str] = mapped_column(String(128))
    value: Mapped[str] = mapped_column(Text)

    requirement: Mapped[Requirement] = relationship(back_populates="attributes")


class RequirementRevision(Base):
    """Старая ревизия. Пайплайны смотрят только is_current=True."""

    __tablename__ = "requirement_revisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    requirement_id: Mapped[int] = mapped_column(ForeignKey("requirements.id"), index=True)
    document_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    code: Mapped[str] = mapped_column(String(256))
    revision: Mapped[str | None] = mapped_column(String(32), nullable=True)
    text: Mapped[str] = mapped_column(Text)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    superseded_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Illustration(Base):
    """Рисунок/схема, извлечённые Tika/docx (в Word-парсере картинки обычно теряются)."""

    __tablename__ = "illustrations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"))
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"), nullable=True)
    filename: Mapped[str] = mapped_column(String(512))
    storage_path: Mapped[str] = mapped_column(String(1024))
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_type: Mapped[str] = mapped_column(String(128), default="image/png")
    blob: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    page_hint: Mapped[str | None] = mapped_column(String(64), nullable=True)

    document: Mapped[Document] = relationship(back_populates="illustrations")


class EntityRelation(Base):
    __tablename__ = "entity_relations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rel_type: Mapped[RelationType] = mapped_column(Enum(RelationType), index=True)
    src_type: Mapped[EntityType] = mapped_column(Enum(EntityType))
    src_id: Mapped[int] = mapped_column(Integer, index=True)
    dst_type: Mapped[EntityType] = mapped_column(Enum(EntityType))
    dst_id: Mapped[int] = mapped_column(Integer, index=True)
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    extra: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Attachment(Base):
    """Файл-приложение к требованию (записка, xlsx)."""

    __tablename__ = "attachments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"))
    requirement_id: Mapped[int | None] = mapped_column(ForeignKey("requirements.id"), nullable=True)
    code: Mapped[str | None] = mapped_column(String(256), index=True, nullable=True)
    filename: Mapped[str] = mapped_column(String(512))
    storage_path: Mapped[str] = mapped_column(String(1024))
    text_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    extra: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Role(Base):
    """Koseven/Kohana: roles.name уникален (login, admin, pipeline, …)."""

    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(32), unique=True)
    description: Mapped[str] = mapped_column(String(255), default="")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    username: Mapped[str] = mapped_column(String(32), unique=True)
    password: Mapped[str] = mapped_column(String(128))
    logins: Mapped[int] = mapped_column(Integer, default=0)
    last_login: Mapped[int | None] = mapped_column(Integer, nullable=True)

    roles: Mapped[list[Role]] = relationship(secondary="roles_users", lazy="selectin")


class RoleUser(Base):
    __tablename__ = "roles_users"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True)


class UserToken(Base):
    __tablename__ = "user_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    user_agent: Mapped[str] = mapped_column(String(40), default="")
    token: Mapped[str] = mapped_column(String(64), unique=True)
    created: Mapped[int] = mapped_column(Integer)
    expires: Mapped[int] = mapped_column(Integer)


class IndexBatch(Base):
    """Один пакет индексации (история)."""

    __tablename__ = "index_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    uploaded_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    files: Mapped[dict[str, Any]] = mapped_column(JSON, default=list)
    totals: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    document_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(32), default="done")


class Embedding(Base):
    """Векторный индекс сущностей для семантического поиска."""

    __tablename__ = "embeddings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity_type: Mapped[EntityType] = mapped_column(Enum(EntityType), index=True)
    entity_id: Mapped[int] = mapped_column(Integer, index=True)
    text: Mapped[str] = mapped_column(Text)
    vector: Mapped[list[float]] = mapped_column(JSON)
