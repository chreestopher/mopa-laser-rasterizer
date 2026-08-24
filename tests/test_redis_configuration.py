import os
import unittest
from unittest.mock import patch

import services


class RedisConfigurationTests(unittest.TestCase):
    def test_host_configuration_remains_backwards_compatible(self):
        environment = {
            "REDIS_HOST": "redis.internal",
            "REDIS_PORT": "6380",
            "REDIS_SSL": "true",
            "REDIS_USERNAME": "worker",
            "REDIS_PASSWORD": "token",
        }
        with patch.dict(os.environ, environment, clear=True), patch.object(
            services.redis, "Redis"
        ) as redis_constructor:
            services.create_redis_client()

        redis_constructor.assert_called_once_with(
            host="redis.internal",
            port=6380,
            ssl=True,
            username="worker",
            password="token",
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=10,
            health_check_interval=30,
        )

    def test_url_configuration_takes_precedence(self):
        with patch.dict(
            os.environ,
            {"REDIS_URL": "rediss://redis.internal:6379/0", "REDIS_HOST": "ignored"},
            clear=True,
        ), patch.object(services.redis.Redis, "from_url") as from_url:
            services.create_redis_client()

        from_url.assert_called_once_with(
            "rediss://redis.internal:6379/0",
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=10,
            health_check_interval=30,
        )


if __name__ == "__main__":
    unittest.main()
