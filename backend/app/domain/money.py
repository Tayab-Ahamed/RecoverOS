"""Money is an integer number of paise. Never a float.

Risk R4 in the risk register is a currency-unit bug: Razorpay's API speaks
paise, humans speak rupees, and a silent factor-of-100 error in a revenue
recovery system is both plausible and catastrophic. The mitigation is to make
the unit explicit in the type and refuse to accept ambiguous input.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.errors import MoneyError

PAISE_PER_RUPEE = 100


@dataclass(frozen=True, order=True)
class Money:
    """An exact amount of Indian currency, stored in paise."""

    paise: int
    currency: str = "INR"

    def __post_init__(self) -> None:
        if not isinstance(self.paise, int) or isinstance(self.paise, bool):
            raise MoneyError(
                f"paise must be an int, got {type(self.paise).__name__}. "
                "Floats are refused because they cannot represent money exactly."
            )
        if self.paise < 0:
            raise MoneyError(f"paise must be non-negative, got {self.paise}")
        if self.currency != "INR":
            raise MoneyError(f"only INR is supported (assumption A5), got {self.currency}")

    # ---- constructors ----

    @classmethod
    def from_paise(cls, paise: int) -> Money:
        return cls(int(paise))

    @classmethod
    def from_rupees(cls, rupees: int | str) -> Money:
        """Build from whole or decimal rupees, given as int or string.

        A float is refused deliberately: 8499.99 is not exactly representable,
        and rounding a customer's balance is never acceptable.
        """
        if isinstance(rupees, float):
            raise MoneyError(
                "refusing to build Money from a float; pass a str like '8499.99'"
            )
        text = str(rupees).strip()
        if text.startswith("-"):
            raise MoneyError(f"negative amount: {text}")
        if "." in text:
            whole, frac = text.split(".", 1)
            if len(frac) > 2:
                raise MoneyError(f"more precision than paise allows: {text}")
            frac = (frac + "00")[:2]
        else:
            whole, frac = text, "00"
        if not whole.isdigit() or not frac.isdigit():
            raise MoneyError(f"not a valid rupee amount: {text}")
        return cls(int(whole) * PAISE_PER_RUPEE + int(frac))

    # ---- arithmetic ----

    def __add__(self, other: Money) -> Money:
        self._same_currency(other)
        return Money(self.paise + other.paise)

    def __sub__(self, other: Money) -> Money:
        self._same_currency(other)
        if other.paise > self.paise:
            raise MoneyError("subtraction would produce a negative amount")
        return Money(self.paise - other.paise)

    def scaled(self, factor: float) -> Money:
        """Multiply by a ratio, rounding half-up to the nearest paisa."""
        if factor < 0:
            raise MoneyError(f"factor must be non-negative, got {factor}")
        return Money(int(self.paise * factor + 0.5))

    def percent(self, pct: float) -> Money:
        return self.scaled(pct / 100.0)

    def _same_currency(self, other: Money) -> None:
        if self.currency != other.currency:
            raise MoneyError(f"currency mismatch: {self.currency} vs {other.currency}")

    # ---- presentation ----

    @property
    def rupees_str(self) -> str:
        return f"{self.paise // PAISE_PER_RUPEE}.{self.paise % PAISE_PER_RUPEE:02d}"

    def __str__(self) -> str:
        return f"Rs {self.rupees_str}"

    def __repr__(self) -> str:
        return f"Money(paise={self.paise})"


ZERO = Money(0)


def total(amounts) -> Money:
    out = ZERO
    for a in amounts:
        out = out + a
    return out
