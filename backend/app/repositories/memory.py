from __future__ import annotations

from app.domain.entities import Customer, RecoveryCase


class InMemoryCaseRepository:
    def __init__(self) -> None:
        self._by_id: dict[str, RecoveryCase] = {}

    def add(self, case: RecoveryCase) -> RecoveryCase:
        self._by_id[case.id] = case
        return case

    def get(self, case_id: str) -> RecoveryCase | None:
        return self._by_id.get(case_id)

    def all(self) -> list[RecoveryCase]:
        return list(self._by_id.values())

    def __len__(self) -> int:
        return len(self._by_id)


class InMemoryCustomerRepository:
    def __init__(self) -> None:
        self._by_id: dict[str, Customer] = {}

    def add(self, customer: Customer) -> Customer:
        self._by_id[customer.id] = customer
        return customer

    def get(self, customer_id: str) -> Customer | None:
        return self._by_id.get(customer_id)

    def as_dict(self) -> dict[str, Customer]:
        return dict(self._by_id)
