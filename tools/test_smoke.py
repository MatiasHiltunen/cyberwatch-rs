import io
import json
import unittest
from unittest.mock import patch, MagicMock
from smoke import check


class SmokeScopeTests(unittest.TestCase):
    def test_external_or_credentialed_target_rejected_before_network(self):
        with patch("smoke.urllib.request.build_opener") as opener:
            for target in ("http://example.org", "http://localhost:8080", "http://user:pass@127.0.0.1:8080", "http://127.0.0.1:8080/path"):
                with self.subTest(target=target), self.assertRaises(ValueError):
                    check(target)
            opener.assert_not_called()

    def test_live_local_instance_stops_at_health_and_cannot_refresh(self):
        response = io.BytesIO(json.dumps({"demo_mode": False, "refresh_enabled": True}).encode())
        response.status = 200
        response.headers = {"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "default-src 'self'"}
        opener = MagicMock()
        opener.open.return_value = response
        with patch("smoke.urllib.request.build_opener", return_value=opener), self.assertRaisesRegex(RuntimeError, "DEMO_MODE"):
            check("http://127.0.0.1:8080")
        self.assertEqual(opener.open.call_count, 1)
        self.assertEqual(opener.open.call_args.args[0].full_url, "http://127.0.0.1:8080/health")


if __name__ == "__main__":
    unittest.main()
