import pytest
import jax
import jax.numpy as jnp
import numpy as np
from unittest.mock import MagicMock

# Import the function under test (assuming it's in `targets_shortcut.py`)
from targets_shortcut import get_targets

# Minimal mock of the FLAGS object with required attributes
class MockFlags:
    def __init__(self):
        self.batch_size = 16
        self.model = {
            'bootstrap_every': 2,
            'denoise_timesteps': 8,
            'bootstrap_dt_bias': 0,
            'bootstrap_ema': 0,
            'bootstrap_cfg': False,
            'num_classes': 10,
            'class_dropout_prob': 0.1,
            'cfg_scale': 1.0,
        }

@pytest.fixture
def dummy_data():
    """Create dummy inputs for the function."""
    key = jax.random.PRNGKey(0)
    images = jnp.zeros((16, 4, 4, 3), dtype=jnp.float32)
    labels = jnp.ones(16, dtype=jnp.int32)
    # Mock train state with callbacks that return zeros of appropriate shape
    def mock_model(x, t, dt, labels, train=False):
        return jnp.zeros_like(x)
    train_state = MagicMock()
    train_state.call_model = mock_model
    train_state.call_model_ema = mock_model
    return key, train_state, images, labels

def test_get_targets_with_force_dt_keeps_dt_base_as_integer(dummy_data):
    """Regression test: force_dt should not change dt_base to float."""
    key, train_state, images, labels = dummy_data
    flags = MockFlags()

    # force_dt != -1 triggers the bug in original code
    out = get_targets(flags, key, train_state, images, labels, force_t=-1, force_dt=2)

    # The fourth returned element is dt_base
    dt_base = out[3]
    # In the fixed code, dt_base must remain integer type after force_dt override.
    assert jnp.issubdtype(dt_base.dtype, jnp.integer), \
        f"dt_base dtype should be integer, got {dt_base.dtype}"

def test_get_targets_default_force_dt_minus_one(dummy_data):
    """Edge case: when force_dt=-1 (default), no override, so dt_base stays as computed."""
    key, train_state, images, labels = dummy_data
    flags = MockFlags()

    out = get_targets(flags, key, train_state, images, labels, force_t=-1, force_dt=-1)
    dt_base = out[3]
    assert jnp.issubdtype(dt_base.dtype, jnp.integer)