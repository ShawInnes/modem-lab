"""Streaming spectra with shared calibrated digital amplitude normalization."""
import struct
import numpy as np
from .dsp import RATE

STREAMS = ("caller_tx", "answerer_tx", "caller_rx", "answerer_rx")
HEADER = struct.Struct("<4sHHIIQIIII")
WINDOW = 2048
HOP = 480
BINS = 171


class Spectrum:
    def __init__(self):
        self.buffer = np.empty((4, 0))
        self.start = 0
        self.window = np.hanning(WINDOW)

    def process(self, streams):
        self.buffer = np.concatenate((self.buffer, np.stack([streams[k] for k in STREAMS])), axis=1)
        timestamps, columns = [], []
        while self.buffer.shape[1] >= WINDOW:
            amplitudes = 2 * np.abs(np.fft.rfft(self.buffer[:, :WINDOW] * self.window, axis=1)) / self.window.sum()
            amplitudes[:, 0] /= 2
            db = 20 * np.log10(np.maximum(amplitudes[:, :BINS], 1e-12))
            columns.append(np.rint(np.clip((db+90)/90, 0, 1)*255).astype(np.uint8))
            timestamps.append(self.start + WINDOW//2)
            self.buffer = self.buffer[:, HOP:]
            self.start += HOP
        data = np.stack(columns, axis=1) if columns else np.empty((4, 0, BINS), np.uint8)
        return np.asarray(timestamps, dtype="<u8"), data

    def packet(self, result, generation, sequence):
        timestamps, spectra = self.process(result["streams"])
        count = len(result["streams"][STREAMS[0]])
        header = HEADER.pack(b"MLAB", 1, 1, generation, sequence, result["start_sample"], RATE,
                             count, len(timestamps), BINS)
        pcm = np.stack([result["streams"][k] for k in STREAMS]).astype("<f4").tobytes()
        return header + pcm + timestamps.tobytes() + spectra.tobytes()
