import os
from pathlib import Path
from unittest import mock

import pytest

from mu2ebo_reporter import config


def test_default_endpoint_is_fnal_vllm_keyless():
    with mock.patch.dict(os.environ, {}, clear=True):
        url, model, key_env, label = config.resolve_endpoint(None, None, None)
        assert (url, model, key_env, label) == ("https://vllm.fnal.gov/v1", "gpt-oss:120b", None, "fnal-vllm")
        assert config.resolve_api_key(key_env, None, None) == "none"


def test_openai_base_url_env_wins_over_default_but_not_explicit_preset():
    env = {"OPENAI_BASE_URL": "https://example/v1", "OPENAI_API_KEY": "k"}
    with mock.patch.dict(os.environ, env, clear=True):
        assert config.resolve_endpoint(None, None, "m")[:3] == ("https://example/v1", "m", "OPENAI_API_KEY")
        assert config.resolve_endpoint("alcf-sophia", None, None)[3] == "alcf-sophia"
        assert config.resolve_api_key("OPENAI_API_KEY", None, None) == "k"


def test_litellm_needs_its_key():
    with mock.patch.dict(os.environ, {}, clear=True):
        _, _, key_env, _ = config.resolve_endpoint("fnal-litellm", None, None)
        with pytest.raises(SystemExit, match="LITELLM_KEY"):
            config.resolve_api_key(key_env, None, None)


def test_mu2ebo_found_as_sibling(tmp_path):
    for name in ("autoresearch", "mu2ebo-reporter"):
        (tmp_path / name).mkdir()
    (tmp_path / "autoresearch" / "service").mkdir()
    (tmp_path / "autoresearch" / "service" / "server.py").write_text("")
    with mock.patch.object(config, "repo_root", return_value=tmp_path / "mu2ebo-reporter"), \
            mock.patch.dict(os.environ, {}, clear=True):
        assert config.mu2ebo_root() == tmp_path / "autoresearch"
    with mock.patch.object(config, "repo_root", return_value=Path("/nonexistent/x")), \
            mock.patch.dict(os.environ, {}, clear=True), pytest.raises(SystemExit, match="MU2EBO_ROOT"):
        config.mu2ebo_root()
