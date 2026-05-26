import unittest

import numpy as np

from live_translator.audio.io import _resample_linear


class AudioIoTests(unittest.TestCase):
    def test_resample_48k_to_16k_uses_interpolation_path(self) -> None:
        samples = np.arange(6, dtype=np.float32)

        resampled = _resample_linear(np, samples, 48000, 16000)

        np.testing.assert_array_equal(resampled, np.array([0.0, 3.0], dtype=np.float32))


if __name__ == "__main__":
    unittest.main()
