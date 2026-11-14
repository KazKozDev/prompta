"""Local Whisper worker: microphone audio stays in memory; JSON events on stdout.

Events: recording → partial (text so far, while speaking) … → transcribing → done (final text) | error.
Partial text is a quick pass over what was recorded so far; the final pass after stop is the accurate one.
"""

import json
from pathlib import Path
import sys
from threading import Event, Lock, Thread

MODEL = Path(__file__).resolve().parents[1] / '.whisper-models' / 'small'
RATE = 16000
PARTIAL_EVERY = 1.2  # seconds between live passes
COMMIT_AFTER = 20.0  # older speech is settled, so live passes stay short on long dictation


def emit(state, **fields):
    print(json.dumps(dict(state=state, **fields)), flush=True)


def load_model():
    from faster_whisper import WhisperModel

    return WhisperModel(str(MODEL), device='cpu', compute_type='int8', local_files_only=True)


def transcribe(model, audio, beam_size=5):
    segments, _ = model.transcribe(
        audio, task='transcribe', beam_size=beam_size, vad_filter=True, condition_on_previous_text=False
    )
    return [(segment.end, segment.text.strip()) for segment in segments if segment.text.strip()]


def joined(parts):
    return ' '.join(text for _, text in parts).strip()


def main():
    import numpy as np
    import sounddevice as sd

    if not (MODEL / 'model.bin').is_file():
        raise RuntimeError('Whisper model is missing. Run the voice-input setup described in desktop/README.md.')
    stopped = Event()
    Thread(target=lambda: (sys.stdin.readline(), stopped.set()), daemon=True).start()
    chunks = []
    lock = Lock()
    overflow = Event()
    model_box = {}
    loader = Thread(target=lambda: model_box.setdefault('model', load_model()), daemon=True)
    loader.start()  # load while the user starts speaking, not after they stop

    def capture(data, frames, time, status):
        if status:
            overflow.set()
        with lock:
            chunks.append(data[:, 0].copy())

    def recorded():
        with lock:
            return np.concatenate(chunks) if chunks else np.zeros(0, dtype='float32')

    committed_text, committed_samples, last_partial = '', 0, ''
    with sd.InputStream(samplerate=RATE, channels=1, dtype='float32', callback=capture):
        emit('recording')
        while not stopped.wait(PARTIAL_EVERY):
            if 'model' not in model_box:
                continue
            audio = recorded()[committed_samples:]
            if len(audio) < RATE * 0.8 or not np.any(audio):
                continue
            parts = transcribe(model_box['model'], audio, beam_size=1)
            if len(audio) > RATE * COMMIT_AFTER and len(parts) > 1:
                # Settle everything but the last segment; later passes start after it.
                settled = parts[:-1]
                committed_text = (committed_text + ' ' + joined(settled)).strip()
                committed_samples += int(settled[-1][0] * RATE)
                parts = parts[-1:]
            text = (committed_text + ' ' + joined(parts)).strip()
            if text and text != last_partial:
                emit('partial', text=text)
                last_partial = text
    if overflow.is_set():
        raise RuntimeError('Microphone audio was interrupted. Please record again.')
    audio = recorded()
    if not len(audio):
        emit('done', text='')
        return
    # Diagnostics for the app's log (stderr): which input was used and how loud it was. No audio leaves memory.
    print(
        f"input: {sd.query_devices(kind='input')['name']} · {len(audio) / RATE:.1f}s · "
        f"peak {float(np.abs(audio).max()):.4f}",
        file=sys.stderr,
        flush=True,
    )
    if not np.any(audio):
        # Exact digital silence is not a quiet room: macOS hands zeros to apps without microphone access.
        device = sd.query_devices(kind='input')['name']
        raise RuntimeError(
            f'The microphone ({device}) sent only silence. Allow Prompta in System Settings → '
            'Privacy & Security → Microphone, or choose another input in Sound settings.'
        )
    emit('transcribing')
    loader.join()
    rest = transcribe(model_box['model'], audio[committed_samples:])
    emit('done', text=(committed_text + ' ' + joined(rest)).strip())


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        emit('error', message=str(exc)[:400])
        sys.exit(1)
