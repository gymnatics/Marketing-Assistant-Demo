"""Tests for MLflow bootstrap — autolog configuration."""
import os
from unittest.mock import patch, MagicMock
import pytest


class TestEnsureMlflowInitialized:
    def _fresh_import(self):
        """Re-import the module with _initialized reset to False."""
        import importlib
        import shared.mlflow_bootstrap as mod
        mod._initialized = False
        return mod

    @patch.dict(os.environ, {"MLFLOW_TRACKING_URI": "http://mlflow:5000", "MLFLOW_EXPERIMENT_NAME": "test-exp"})
    @patch("mlflow.openai.autolog")
    @patch("mlflow.set_experiment")
    @patch("mlflow.set_tracking_uri")
    def test_openai_autolog_called_when_uri_set(self, mock_set_uri, mock_set_exp, mock_openai_autolog):
        mod = self._fresh_import()
        mod.ensure_mlflow_initialized()

        mock_set_uri.assert_called_once_with("http://mlflow:5000")
        mock_set_exp.assert_called_once_with("test-exp")
        mock_openai_autolog.assert_called_once()

    @patch.dict(os.environ, {"MLFLOW_TRACKING_URI": ""})
    @patch("mlflow.openai.autolog")
    @patch("mlflow.set_tracking_uri")
    def test_no_autolog_when_uri_empty(self, mock_set_uri, mock_openai_autolog):
        mod = self._fresh_import()
        mod.ensure_mlflow_initialized()

        mock_set_uri.assert_not_called()
        mock_openai_autolog.assert_not_called()

    @patch.dict(os.environ, {}, clear=False)
    @patch("mlflow.openai.autolog")
    @patch("mlflow.set_tracking_uri")
    def test_no_autolog_when_uri_missing(self, mock_set_uri, mock_openai_autolog):
        os.environ.pop("MLFLOW_TRACKING_URI", None)
        mod = self._fresh_import()
        mod.ensure_mlflow_initialized()

        mock_set_uri.assert_not_called()
        mock_openai_autolog.assert_not_called()

    @patch.dict(os.environ, {"MLFLOW_TRACKING_URI": "http://mlflow:5000"})
    @patch("mlflow.openai.autolog")
    @patch("mlflow.set_experiment")
    @patch("mlflow.set_tracking_uri")
    def test_idempotency(self, mock_set_uri, mock_set_exp, mock_openai_autolog):
        mod = self._fresh_import()
        mod.ensure_mlflow_initialized()
        mod.ensure_mlflow_initialized()

        assert mock_set_uri.call_count == 1
        assert mock_openai_autolog.call_count == 1

    @patch.dict(os.environ, {"MLFLOW_TRACKING_URI": "http://mlflow:5000"})
    @patch("mlflow.openai.autolog")
    @patch("mlflow.set_experiment")
    @patch("mlflow.set_tracking_uri")
    def test_default_experiment_name(self, mock_set_uri, mock_set_exp, mock_openai_autolog):
        os.environ.pop("MLFLOW_EXPERIMENT_NAME", None)
        mod = self._fresh_import()
        mod.ensure_mlflow_initialized()

        mock_set_exp.assert_called_once_with("default")
