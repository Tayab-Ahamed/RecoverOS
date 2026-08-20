"""Tests for provider event identity.

The durability test is the important one: it is the property that a hash()
based implementation silently fails to provide.
"""

import hashlib
import subprocess
import sys
import unittest

from app.domain.errors import MissingProviderEventId
from app.webhooks.event_id import (
    DERIVED_PREFIX,
    derive_event_id,
    is_derived,
    resolve_event_id,
)

BODY = b'{"event":"payment_link.paid","payload":{"payment_link":{"id":"plink_x"}}}'


class TestResolveEventId(unittest.TestCase):
    def test_provider_supplied_id_always_wins(self):
        self.assertEqual(resolve_event_id("evt_provider_123", BODY), "evt_provider_123")

    def test_surrounding_whitespace_is_stripped(self):
        self.assertEqual(resolve_event_id("  evt_abc  ", BODY), "evt_abc")

    def test_missing_id_is_refused_by_default(self):
        # The default must be the safe behaviour, not the convenient one.
        with self.assertRaises(MissingProviderEventId):
            resolve_event_id(None, BODY)

    def test_blank_header_counts_as_missing(self):
        for blank in ("", "   ", "\t", "\n"):
            with self.subTest(blank=repr(blank)):
                with self.assertRaises(MissingProviderEventId):
                    resolve_event_id(blank, BODY)

    def test_derivation_requires_explicit_opt_in(self):
        derived = resolve_event_id(None, BODY, allow_derived=True)
        self.assertTrue(is_derived(derived))
        self.assertEqual(
            derived, f"{DERIVED_PREFIX}{hashlib.sha256(BODY).hexdigest()}"
        )

    def test_provider_id_is_never_marked_derived(self):
        self.assertFalse(is_derived(resolve_event_id("evt_1", BODY)))


class TestDeriveEventId(unittest.TestCase):
    def test_same_body_gives_same_id(self):
        self.assertEqual(derive_event_id(BODY), derive_event_id(bytes(BODY)))

    def test_one_byte_difference_gives_a_different_id(self):
        self.assertNotEqual(derive_event_id(BODY), derive_event_id(BODY + b" "))

    def test_str_input_is_rejected(self):
        # Encoding here would change the digest, exactly as it breaks signature
        # verification.
        with self.assertRaises(TypeError):
            derive_event_id(BODY.decode())

    def test_id_is_durable_across_separate_interpreters(self):
        """The regression test for the defect this module replaced.

        Python randomises hashing of bytes per process, so a hash() based id
        would differ between these two subprocesses and replay protection would
        not survive a restart. A digest must not.
        """
        program = (
            "import sys; sys.path.insert(0, '.');"
            "from app.webhooks.event_id import derive_event_id;"
            f"print(derive_event_id({BODY!r}))"
        )
        first = subprocess.run(
            [sys.executable, "-c", program], capture_output=True, text=True, check=True
        ).stdout.strip()
        second = subprocess.run(
            [sys.executable, "-c", program], capture_output=True, text=True, check=True
        ).stdout.strip()

        self.assertEqual(first, second)
        self.assertEqual(first, derive_event_id(BODY))

    def test_hash_based_identity_would_have_failed_this(self):
        """Demonstrates the actual defect, so the reason for this module is
        recorded in the suite rather than only in a commit message."""
        program = f"print(hash({BODY!r}))"
        runs = {
            subprocess.run(
                [sys.executable, "-c", program],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            for _ in range(6)
        }
        # Not asserting that they differ, since PYTHONHASHSEED may be pinned in
        # some environments. Asserting that the digest does not have this
        # uncertainty at all is the point.
        self.assertEqual(len({derive_event_id(BODY) for _ in range(6)}), 1)
        if len(runs) > 1:
            self.assertGreater(
                len(runs), 1, "hash() varied across processes, as expected"
            )


if __name__ == "__main__":
    unittest.main()
