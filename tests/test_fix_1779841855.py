import pytest
import torch
from vHeat_UNet import Heat2D  # assuming the module is named vHeat_UNet


class TestHeat2DInferMode:
    """Regression test for missing k_exp attribute in Heat2D infer_mode forward."""

    @pytest.fixture
    def input_tensor(self):
        # typical feature map: batch=2, channels=96, height=56, width=56
        return torch.randn(2, 96, 56, 56)

    def test_infer_mode_forward_without_init_should_not_raise(self, input_tensor):
        """
        Original bug: in infer_mode, if k_exp has not been initialised,
        `self.k_exp` raises AttributeError.
        The fix adds a fallback to identity (no decay).
        """
        heat2d = Heat2D(infer_mode=True, res=56, dim=96, hidden_dim=96)
        # No call to infer_init_heat2d
        try:
            out = heat2d(input_tensor)
        except AttributeError as e:
            pytest.fail(f"Forward raised AttributeError due to missing k_exp: {e}")
        except Exception as e:
            pytest.fail(f"Forward raised unexpected exception: {e}")

        assert out.shape == input_tensor.shape, (
            f"Output shape {out.shape} does not match input shape {input_tensor.shape}"
        )

    def test_infer_mode_forward_after_init_should_work(self, input_tensor):
        """
        Ensure that the normal path still works after init.
        """
        heat2d = Heat2D(infer_mode=True, res=56, dim=96, hidden_dim=96)
        freq = torch.randn(96)
        heat2d.infer_init_heat2d(freq)
        out = heat2d(input_tensor)
        assert out.shape == input_tensor.shape

    def test_infer_mode_different_resolutions(self):
        """
        Edge case: different spatial dimensions that may trigger cached weights,
        still should not fail without init.
        """
        heat2d = Heat2D(infer_mode=True, res=14, dim=192, hidden_dim=192)
        x = torch.randn(1, 192, 28, 28)   # H,W differ from res (14) but that's fine for dynamic weight calc
        out = heat2d(x)
        assert out.shape == x.shape

    def test_infer_mode_minimal_input(self):
        """Minimal edge case: 1x1 spatial size."""
        heat2d = Heat2D(infer_mode=True, res=1, dim=32, hidden_dim=32)
        x = torch.randn(1, 32, 1, 1)
        out = heat2d(x)
        assert out.shape == x.shape

    def test_training_mode_unaffected(self):
        """Training mode (not infer) should still require freq_embed."""
        heat2d = Heat2D(infer_mode=False, res=56, dim=96, hidden_dim=96)
        x = torch.randn(2, 96, 56, 56)
        freq = torch.randn(96)   # training mode expects freq_embed
        # Should not raise AttributeError
        out = heat2d(x, freq_embed=freq)
        assert out.shape == x.shape