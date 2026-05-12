import sys
import os
import pytest
import torch

# Ensure the meanflow package is importable (mimicking the original test script)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'meanflow'))

from meanflow.models.unet3d import SongUNet3D, DhariwalUNet3D


# ---------- SongUNet3D tests ----------

def test_song_unet3d_forward_with_single_tensor():
    """SongUNet3D must accept a single noise tensor and produce correct output shape."""
    batch_size = 2
    in_channels = 1
    out_channels = 1
    img_resolution = (32, 32, 32)

    model = SongUNet3D(
        img_resolution=img_resolution,
        in_channels=in_channels,
        out_channels=out_channels,
        model_channels=64,
        channel_mult=[1, 2, 2],
        num_blocks=2,
        attn_resolutions=[16],
        dropout=0.1,
    )

    x = torch.randn(batch_size, in_channels, *img_resolution)
    time_steps = torch.rand(batch_size)          # single tensor, NOT a tuple

    with torch.no_grad():
        output = model(x, time_steps)

    assert output.shape == (batch_size, out_channels, *img_resolution), \
        f"Expected output shape ({batch_size},{out_channels},{img_resolution}), got {output.shape}"


def test_song_unet3d_rejects_tuple_time_steps():
    """SongUNet3D must raise an error when time_steps is a tuple (regression for the bug)."""
    model = SongUNet3D(
        img_resolution=(32, 32, 32),
        in_channels=1,
        out_channels=1,
        model_channels=64,
        channel_mult=[1, 2, 2],
        num_blocks=2,
        attn_resolutions=[16],
        dropout=0.1,
    )

    x = torch.randn(2, 1, 32, 32, 32)
    bad_time = (torch.rand(2), torch.rand(2))   # the exact buggy pattern

    with pytest.raises((TypeError, RuntimeError, ValueError)):
        model(x, bad_time)


# ---------- DhariwalUNet3D tests ----------

def test_dhariwal_unet3d_forward_with_correct_inputs():
    """DhariwalUNet3D forward pass with noise_labels and class_labels works correctly."""
    batch_size = 2
    in_channels = 1
    out_channels = 1
    img_resolution = (32, 32, 32)

    model = DhariwalUNet3D(
        img_resolution=img_resolution,
        in_channels=in_channels,
        out_channels=out_channels,
        model_channels=64,
        channel_mult=[1, 2, 2],
        num_blocks=2,
        attn_resolutions=[16],
        dropout=0.1,
    )

    x = torch.randn(batch_size, in_channels, *img_resolution)
    noise_labels = torch.rand(batch_size)
    class_labels = torch.randint(0, 10, (batch_size,))

    with torch.no_grad():
        output = model(x, noise_labels, class_labels)

    assert output.shape == (batch_size, out_channels, *img_resolution), \
        f"Expected output shape ({batch_size},{out_channels},{img_resolution}), got {output.shape}"


# ---------- Edge cases around the regression ----------

@pytest.mark.parametrize("img_resolution", [
    (16, 16, 16),
    (32, 32, 32),
    (64, 64, 64),
])
def test_song_unet3d_different_resolutions_single_tensor(img_resolution):
    """SongUNet3D works with various resolutions when given a single noise tensor."""
    model = SongUNet3D(
        img_resolution=img_resolution,
        in_channels=1,
        out_channels=1,
        model_channels=32,
        channel_mult=[1, 2],
        num_blocks=1,
        attn_resolutions=[8],
        dropout=0.1,
    )

    x = torch.randn(1, 1, *img_resolution)
    time_steps = torch.rand(1)   # single tensor

    with torch.no_grad():
        output = model(x, time_steps)

    assert output.shape == (1, 1, *img_resolution)


def test_song_unet3d_cubic_resolution_single_integer():
    """SongUNet3D accepts a single integer for img_resolution and treats it as a cube."""
    model = SongUNet3D(
        img_resolution=32,       # single int, should become (32,32,32)
        in_channels=1,
        out_channels=1,
        model_channels=32,
        channel_mult=[1, 2],
        num_blocks=1,
        attn_resolutions=[16],
        dropout=0.1,
    )

    # Model's internal resolution must reflect the cube
    assert model.img_resolution == (32, 32, 32)

    x = torch.randn(1, 1, 32, 32, 32)
    time_steps = torch.rand(1)

    with torch.no_grad():
        output = model(x, time_steps)

    assert output.shape == (1, 1, 32, 32, 32)