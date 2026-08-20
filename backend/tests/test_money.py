import unittest

from app.domain.errors import MoneyError
from app.domain.money import Money


class TestMoney(unittest.TestCase):
    def test_rupees_to_paise(self):
        self.assertEqual(Money.from_rupees(100).paise, 10000)
        self.assertEqual(Money.from_rupees("8499.99").paise, 849999)
        self.assertEqual(Money.from_rupees("0.01").paise, 1)

    def test_floats_are_refused(self):
        # Risk R4: a silent factor-of-100 or rounding error in a revenue
        # system is catastrophic, so float construction must fail loudly.
        with self.assertRaises(MoneyError):
            Money.from_rupees(8499.99)
        with self.assertRaises(MoneyError):
            Money(100.5)

    def test_negative_refused(self):
        with self.assertRaises(MoneyError):
            Money(-1)
        with self.assertRaises(MoneyError):
            Money.from_rupees("-5")

    def test_sub_paisa_precision_refused(self):
        with self.assertRaises(MoneyError):
            Money.from_rupees("10.999")

    def test_arithmetic(self):
        self.assertEqual((Money(100) + Money(50)).paise, 150)
        self.assertEqual((Money(100) - Money(50)).paise, 50)
        with self.assertRaises(MoneyError):
            Money(50) - Money(100)

    def test_percent_and_scale(self):
        self.assertEqual(Money.from_rupees(1000).percent(10).paise, 10000)
        self.assertEqual(Money(101).scaled(0.5).paise, 51)

    def test_no_drift_over_many_additions(self):
        total = Money(0)
        for _ in range(10000):
            total = total + Money.from_rupees("0.01")
        self.assertEqual(total.paise, 10000)
        self.assertEqual(total.rupees_str, "100.00")

    def test_display(self):
        self.assertEqual(Money(849999).rupees_str, "8499.99")
        self.assertEqual(Money(5).rupees_str, "0.05")
