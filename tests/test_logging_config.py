from utils.logging_config import setup_logging


def test_setup_logging(tmp_path):
    log = setup_logging(log_dir=str(tmp_path))
    log.info("hello")
    assert any(p.suffix == ".log" for p in tmp_path.iterdir())
