import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import Mock

from instagram_publisher import PublishResult

REPO = Path(__file__).resolve().parents[1]


def outside(code, tmp_path, *args):
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    result = subprocess.run(
        [sys.executable, "-I", "-c", code, *map(str, args)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_installed_import_and_cli_help_work_outside_checkout(tmp_path):
    output = outside(
        "import instagram_publisher, upload_photo; print(instagram_publisher.__file__); assert upload_photo.PublishResult is instagram_publisher.PublishResult; from instagram_publisher.__main__ import main; main(['--help'])",
        tmp_path,
    )
    assert str(REPO / "src/instagram_publisher") in output
    assert "reconcile" in output and "cleanup" in output


def test_namespace_submodule_import_uses_that_checkout(tmp_path):
    (tmp_path / "vendored_publisher").symlink_to(REPO, target_is_directory=True)
    output = outside(
        "import sys; sys.path.insert(0, sys.argv[1]); from vendored_publisher import upload_photo; print(upload_photo.PublishResult.__module__); assert callable(upload_photo.publish_image)",
        tmp_path,
        tmp_path,
    )
    assert "vendored_publisher.src.instagram_publisher.models" in output


def test_built_wheel_contains_package_and_legacy_import(tmp_path):
    build = subprocess.run(
        [
            sys.executable,
            "-m",
            "build",
            "--wheel",
            "--no-isolation",
            "--outdir",
            str(tmp_path),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert build.returncode == 0, build.stderr
    wheel = next(tmp_path.glob("*.whl"))
    output = outside(
        "import sys; sys.path.insert(0, sys.argv[1]); import instagram_publisher, upload_photo; assert upload_photo.PublishResult is instagram_publisher.PublishResult; assert sys.argv[1] in instagram_publisher.__file__; print(instagram_publisher.__file__)",
        tmp_path,
        wheel,
    )
    assert str(wheel) in output


def test_post_random_photo_uses_new_orchestration(monkeypatch, image):
    import instagram_publisher.service as service
    import upload_photo

    mock = Mock()
    mock.publish.return_value = PublishResult("789", "456", "a" * 64)
    monkeypatch.setattr(service, "configured_publisher", Mock(return_value=mock))
    assert (
        upload_photo.post_random_photo(
            str(image), "caption", operation_key="quote-1"
        ).media_id
        == "789"
    )
    mock.publish.assert_called_once_with(
        str(image), "caption", operation_key="quote-1", resume=False
    )


def test_cli_preflight_error_is_redacted_and_nonzero(tmp_path):
    env = dict(os.environ)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "instagram_publisher",
            "publish",
            str(tmp_path / "missing.jpg"),
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 1
    assert "JPEG" in json.loads(result.stderr)["error"]
    assert "secret" not in result.stderr
