"""
Generic repository providing common CRUD operations. Concrete
repositories subclass this and add model-specific query methods,
keeping data-access logic out of the service/business layer.
"""
from typing import Generic, TypeVar, Type, Optional, List

from sqlalchemy.orm import Session

ModelType = TypeVar("ModelType")


class BaseRepository(Generic[ModelType]):
    def __init__(self, model: Type[ModelType], db: Session):
        self.model = model
        self.db = db

    def get(self, id_: int) -> Optional[ModelType]:
        return self.db.query(self.model).filter(self.model.id == id_).first()

    def get_all(self, skip: int = 0, limit: int = 1000) -> List[ModelType]:
        return self.db.query(self.model).offset(skip).limit(limit).all()

    def create(self, obj: ModelType) -> ModelType:
        self.db.add(obj)
        self.db.commit()
        self.db.refresh(obj)
        return obj

    def update(self, obj: ModelType) -> ModelType:
        self.db.commit()
        self.db.refresh(obj)
        return obj

    def delete(self, obj: ModelType) -> None:
        self.db.delete(obj)
        self.db.commit()

    def count(self) -> int:
        return self.db.query(self.model).count()
