import numpy as np
import torch
from typing import Dict, Any
from ..logger import Logger
from ..protocol import AudioFormat


def parse_audio(audio: Any) -> Dict[str, Any]:
    """
    解析 ComfyUI 音频格式

    支持格式:
    - dict: {"waveform": tensor, "sample_rate": int}
    - tuple: (tensor, sample_rate)
    - tensor: 直接波形数据
    """
    log = Logger("Audio")
    result = {
        "has_audio": False,
        "data": None,
        "sample_rate": 44100,
        "channels": 2,
        "samples": 0,
        "duration": 0.0,
        "format": AudioFormat.PCM_F32LE,
    }

    if audio is None:
        return result

    try:
        waveform = None
        sample_rate = 44100

        if isinstance(audio, dict):
            waveform = audio.get("waveform")
            sr = audio.get("sample_rate")
            if sr is not None:
                if isinstance(sr, (int, float)):
                    sample_rate = int(sr)
                elif hasattr(sr, "__int__"):
                    sample_rate = int(sr)
        elif isinstance(audio, (tuple, list)) and len(audio) >= 2:
            waveform = audio[0]
            sr = audio[1]
            if isinstance(sr, (int, float)):
                sample_rate = int(sr)
            elif hasattr(sr, "__int__"):
                sample_rate = int(sr)
        else:
            waveform = audio

        if waveform is None:
            log.debug("No waveform data found in audio")
            return result

        if isinstance(waveform, torch.Tensor):
            audio_np = waveform.cpu().numpy()
        elif isinstance(waveform, dict):
            audio_np = waveform.get("waveform")
            if audio_np is not None and isinstance(audio_np, torch.Tensor):
                audio_np = audio_np.cpu().numpy()
            else:
                return result
        else:
            audio_np = np.array(waveform)

        if audio_np.dtype != np.float32:
            if np.issubdtype(audio_np.dtype, np.integer):
                max_val = np.iinfo(audio_np.dtype).max
                audio_np = audio_np.astype(np.float32) / max_val
            else:
                audio_np = audio_np.astype(np.float32)

        if len(audio_np.shape) == 1:
            channels, samples = 1, audio_np.shape[0]
        elif len(audio_np.shape) == 2:
            channels, samples = audio_np.shape[0], audio_np.shape[1]
        elif len(audio_np.shape) == 3:
            audio_np = audio_np[0]
            channels, samples = audio_np.shape[0], audio_np.shape[1]
        else:
            log.warning(f"Unexpected audio shape: {audio_np.shape}")
            return result

        audio_np = np.ascontiguousarray(audio_np)

        result = {
            "has_audio": True,
            "data": audio_np.tobytes(),
            "sample_rate": sample_rate,
            "channels": channels,
            "samples": samples,
            "duration": samples / sample_rate,
            "format": AudioFormat.PCM_F32LE,
        }

        log.debug(
            f"Audio: {channels}ch, {sample_rate}Hz, "
            f"{samples} samples ({result['duration']:.2f}s)"
        )

    except Exception as e:
        log.debug(f"Audio parse failed: {e}")

    return result
