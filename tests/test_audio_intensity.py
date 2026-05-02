import unittest
import math

from server.audio_intensity import calculate_band_intensity


class AudioIntensityTests(unittest.TestCase):
    def test_silent_audio_has_zero_intensity(self):
        samples = [0.0] * (22050 * 2)

        intensity = calculate_band_intensity(samples, sample_rate=22050)

        self.assertEqual(intensity, 0.0)

    def test_low_frequency_tone_has_more_intensity_than_out_of_band_tone(self):
        sample_rate = 22050
        duration = 2.0
        low_tone = [
            0.5 * math.sin(2 * math.pi * 100 * i / sample_rate)
            for i in range(int(sample_rate * duration))
        ]
        high_tone = [
            0.5 * math.sin(2 * math.pi * 400 * i / sample_rate)
            for i in range(int(sample_rate * duration))
        ]

        low_intensity = calculate_band_intensity(low_tone, sample_rate=sample_rate)
        high_intensity = calculate_band_intensity(high_tone, sample_rate=sample_rate)

        self.assertGreater(low_intensity, high_intensity * 10)


if __name__ == "__main__":
    unittest.main()
