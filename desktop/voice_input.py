"""Local Whisper worker: microphone audio stays in memory; JSON events on stdout."""
import json
from pathlib import Path
import sys
from threading import Event, Thread

MODEL = Path(__file__).resolve().parents[1] / '.whisper-models' / 'small'


def emit(state, **fields):
    print(json.dumps(dict(state=state, **fields)), flush=True)


def transcribe(audio):
    from faster_whisper import WhisperModel
    model = WhisperModel(str(MODEL), device='cpu', compute_type='int8', local_files_only=True)
    segments, _ = model.transcribe(audio, task='transcribe', beam_size=5, vad_filter=True,
                                   condition_on_previous_text=False)
    return ' '.join(segment.text.strip() for segment in segments).strip()


def main():
    import numpy as np
    import sounddevice as sd
    if not (MODEL / 'model.bin').is_file():
        raise RuntimeError('Whisper model is missing. Run the voice-input setup described in desktop/README.md.')
    stopped = Event()
    Thread(target=lambda: (sys.stdin.readline(), stopped.set()), daemon=True).start()
    chunks = []
    overflow = Event()

    def capture(data, frames, time, status):
        if status:
            overflow.set()
        chunks.append(data[:, 0].copy())

    with sd.InputStream(samplerate=16000, channels=1, dtype='float32', callback=capture):
        emit('recording')
        stopped.wait(300)
    if overflow.is_set():
        raise RuntimeError('Microphone audio was interrupted. Please record again.')
    if not chunks:
        emit('done', text='')
        return
    emit('transcribing')
    text = transcribe(np.concatenate(chunks))
    emit('done', text=text)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        emit('error', message=str(exc)[:400])
        sys.exit(1)
