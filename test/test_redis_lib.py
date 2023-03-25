import pytest
from pkg.redis_lib import RedisHandler
from pkg.config import WorkerConfig

@pytest.fixture(scope='module')
def redis_handler():
    conf = WorkerConfig()
    handler = RedisHandler(conf.redis_url)
    yield handler

def test_send_info_to_redis(redis_handler):
    message = {
            "job_name": "test_job",
            "worker_status": "success",
            "timestamp": "2022-01-01T00:00:00",
            "db_name": "test_db",
            "db_host": "test_host"
        }
    redis_handler.send_info_to_redis(0, "test_key", message)
    result = redis_handler.redis_connection.hgetall("test_key")
    assert result["job_name"] == "test_job"
    assert result["worker_status"] == "success"
    assert result["timestamp"] == "2022-01-01T00:00:00"
    assert result["db_name"] == "test_db"
    assert result["db_host"] == "test_host"

def test_del_info_into_redis(redis_handler):
    redis_handler.del_info_into_redis(0, "test_key")
    result = redis_handler.redis_connection.exists("test_key")
    assert result == 0

def test_send_error_to_redis(redis_handler):
    redis_handler.send_error_to_redis(0, "test_job", "2022-01-01T00:00:00", "An error occurred")
    key = len(redis_handler.redis_connection.keys())
    result = redis_handler.redis_connection.hgetall(str(key))
    assert result["job_name"] == "test_job"
    assert result["timestamp"] == "2022-01-01T00:00:00"
    assert result["error"] == "An error occurred"

def test_del_all_keys_into_redis(redis_handler):
    message = {
            "job_name": "test_job",
            "worker_status": "success",
            "timestamp": "2022-01-01T00:00:00",
            "db_name": "test_db",
            "db_host": "test_host"
        }
    redis_handler.send_info_to_redis(0, "test_key_1", message)
    redis_handler.send_info_to_redis(0, "test_key_2", message)

    assert redis_handler.redis_connection.exists("test_key_1") == 1
    assert redis_handler.redis_connection.exists("test_key_2") == 1

    redis_handler.del_all_keys_into_redis(0)
    assert redis_handler.redis_connection.exists("test_key_1") == 0
    assert redis_handler.redis_connection.exists("test_key_2") == 0