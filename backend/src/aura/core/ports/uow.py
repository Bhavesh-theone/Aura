from typing import Protocol, runtime_checkable


@runtime_checkable
class UnitOfWork(Protocol):
    """One transaction. Repositories never commit; whoever owns the boundary does."""
    def commit(self) -> None: ...
    def rollback(self) -> None: ...
