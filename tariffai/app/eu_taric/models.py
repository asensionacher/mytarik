"""Modelos de la nomenclatura aduanera de la Unión Europea.

La fuente es la Goods Nomenclature de TARIC. Un registro puede ser:

- 2 dígitos: capítulo.
- 4 dígitos: partida.
- 6 dígitos: subpartida del Sistema Armonizado.
- 8 dígitos: código CN de la Unión.
- 10 dígitos: código TARIC.

El flujo operativo de Mytarik solo usa CN8/TARIC10. Los niveles 2/4/6 se
conservan para construir la jerarquía, nunca como código de producto.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

CODE_PATTERN = r"^(?:\d{2}|\d{4}|\d{6}|\d{8}|\d{10})$"
DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"
CN8_PATTERN = r"^\d{8}$"
TARIC10_PATTERN = r"^\d{10}$"


class GoodsEntry(BaseModel):
    """Una fila normalizada de Goods Nomenclature."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(pattern=CODE_PATTERN)
    level: int = Field(ge=2, le=10)
    description: str = ""
    language: str | None = Field(default=None, max_length=8)
    parent_code: str | None = Field(default=None, pattern=CODE_PATTERN)

    cn8: str | None = Field(default=None, pattern=CN8_PATTERN)
    taric10: str | None = Field(default=None, pattern=TARIC10_PATTERN)

    start_date: str | None = Field(default=None, pattern=DATE_PATTERN)
    end_date: str | None = Field(default=None, pattern=DATE_PATTERN)
    description_start_date: str | None = Field(default=None, pattern=DATE_PATTERN)

    hierarchy_position: str | None = Field(default=None, max_length=128)
    indent: int | None = Field(default=None, ge=0)
    published: bool | None = None
    sequence_number: int | None = Field(default=None, ge=0)

    @field_validator("level")
    @classmethod
    def _level_matches_code_length(cls, value: int) -> int:
        if value not in {2, 4, 6, 8, 10}:
            raise ValueError("level debe ser 2, 4, 6, 8 o 10")
        return value
