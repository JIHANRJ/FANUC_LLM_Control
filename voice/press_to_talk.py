"""Reusable press-to-talk voice input controller."""

from __future__ import annotations

import tempfile
import threading
from typing import Callable, Literal

VoiceEngine = Literal["google", "sphinx", "whisper"]


class PressToTalkVoiceController:
    """Listen for a key press and emit transcribed voice commands via callbacks."""

    def __init__(
        self,
        *,
        trigger_key: str = "r",
        always_listen: bool = False,
        engine: VoiceEngine = "whisper",
        sample_rate: int = 16000,
        phrase_time_limit: float = 3.0,
        listen_timeout: float = 0.5,
        ambient_noise_duration: float = 0.5,
        suppress_keyboard: bool = True,
        whisper_model_size: str = "small",
        whisper_device: str = "cpu",
        whisper_compute_type: str = "int8",
        whisper_beam_size: int = 3,
        whisper_language: str | None = "en",
        on_partial: Callable[[str], None] | None = None,
        on_final: Callable[[str], None] | None = None,
        on_error: Callable[[str], None] | None = None,
        on_recording_start: Callable[[], None] | None = None,
    ) -> None:
        if len(trigger_key) != 1:
            raise ValueError("trigger_key must be a single character")
        if engine not in {"google", "sphinx", "whisper"}:
            raise ValueError("engine must be 'google', 'sphinx', or 'whisper'")

        try:
            import speech_recognition as sr
            from pynput import keyboard
        except ImportError as exc:
            raise RuntimeError(
                "Voice input requires SpeechRecognition, pynput, and a working audio backend."
            ) from exc

        self._sr = sr
        self._keyboard = keyboard

        self._trigger_key = trigger_key.lower()
        self._always_listen = always_listen
        self._engine = engine
        self._suppress_keyboard = suppress_keyboard
        self._whisper_beam_size = whisper_beam_size
        self._whisper_language = whisper_language
        self._whisper_model = None

        self._recognizer = sr.Recognizer()
        self._microphone = sr.Microphone(sample_rate=sample_rate)
        self._phrase_time_limit = phrase_time_limit
        self._listen_timeout = listen_timeout
        self._ambient_noise_duration = ambient_noise_duration

        self._on_partial = on_partial
        self._on_final = on_final
        self._on_error = on_error
        self._on_recording_start = on_recording_start

        self._partial_transcript: list[str] = []
        self._recording = False
        self._recording_thread: threading.Thread | None = None
        self._continuous_thread: threading.Thread | None = None
        self._stop_recording = threading.Event()
        self._listener = None

        if self._engine == "whisper":
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise RuntimeError(
                    "Whisper mode dependencies are missing. Install with: "
                    "python -m pip install faster-whisper requests "
                    f"(details: {exc})"
                ) from exc

            self._whisper_model = WhisperModel(
                whisper_model_size,
                device=whisper_device,
                compute_type=whisper_compute_type,
            )

    @property
    def engine(self) -> VoiceEngine:
        return self._engine

    def start(self) -> None:
        if self._always_listen:
            if self._continuous_thread is not None:
                return

            self._stop_recording.clear()
            self._continuous_thread = threading.Thread(target=self._continuous_listen_loop, daemon=True)
            self._continuous_thread.start()
            return

        if self._listener is not None:
            return

        self._listener = self._keyboard.Listener(
            on_press=self._on_press,
            on_release=self._on_release,
            suppress=self._suppress_keyboard,
        )
        self._listener.start()

    def stop(self) -> None:
        self._stop_recording.set()
        self._recording = False

        if self._recording_thread is not None:
            self._recording_thread.join(timeout=1)
            self._recording_thread = None

        if self._continuous_thread is not None:
            self._continuous_thread.join(timeout=1)
            self._continuous_thread = None

        if self._listener is not None:
            self._listener.stop()
            self._listener = None

    def _recognize_chunk(self, audio: object) -> str:
        if self._engine == "whisper":
            if self._whisper_model is None:
                raise RuntimeError("Whisper model is not initialized.")

            wav_bytes = audio.get_wav_data()
            with tempfile.NamedTemporaryFile(suffix=".wav") as temp_wav:
                temp_wav.write(wav_bytes)
                temp_wav.flush()
                segments, _ = self._whisper_model.transcribe(
                    temp_wav.name,
                    beam_size=self._whisper_beam_size,
                    language=self._whisper_language,
                    vad_filter=True,
                )
                return " ".join(segment.text.strip() for segment in segments if segment.text).strip()

        if self._engine == "sphinx":
            return self._recognizer.recognize_sphinx(audio)
        return self._recognizer.recognize_google(audio)

    def _record_audio(self) -> None:
        with self._microphone as source:
            self._recognizer.adjust_for_ambient_noise(
                source,
                duration=self._ambient_noise_duration,
            )
            while self._recording and not self._stop_recording.is_set():
                try:
                    audio = self._recognizer.listen(
                        source,
                        timeout=self._listen_timeout,
                        phrase_time_limit=self._phrase_time_limit,
                    )
                except self._sr.WaitTimeoutError:
                    continue

                try:
                    chunk_text = self._recognize_chunk(audio)
                    if chunk_text:
                        self._partial_transcript.append(chunk_text)
                        if self._on_partial is not None:
                            self._on_partial(" ".join(self._partial_transcript))
                except self._sr.UnknownValueError:
                    continue
                except self._sr.RequestError as exc:
                    if self._on_error is not None:
                        self._on_error(str(exc))
                    break

    def _on_press(self, key: object) -> None:
        try:
            key_char = str(key.char).lower()
        except AttributeError:
            return

        if key_char != self._trigger_key or self._recording:
            return

        self._recording = True
        self._partial_transcript = []
        self._stop_recording.clear()

        if self._on_recording_start is not None:
            self._on_recording_start()

        self._recording_thread = threading.Thread(target=self._record_audio, daemon=True)
        self._recording_thread.start()

    def _on_release(self, key: object) -> None:
        try:
            key_char = str(key.char).lower()
        except AttributeError:
            return

        if key_char != self._trigger_key or not self._recording:
            return

        self._recording = False
        self._stop_recording.set()

        if self._recording_thread is not None:
            self._recording_thread.join()
            self._recording_thread = None

        full_text = " ".join(self._partial_transcript).strip()
        if not full_text:
            if self._on_error is not None:
                self._on_error("Could not understand audio")
            return

        if self._on_final is not None:
            self._on_final(full_text)

    def _continuous_listen_loop(self) -> None:
        with self._microphone as source:
            self._recognizer.adjust_for_ambient_noise(
                source,
                duration=self._ambient_noise_duration,
            )

            while not self._stop_recording.is_set():
                try:
                    audio = self._recognizer.listen(
                        source,
                        timeout=self._listen_timeout,
                        phrase_time_limit=self._phrase_time_limit,
                    )
                except self._sr.WaitTimeoutError:
                    continue
                except Exception as exc:
                    if self._on_error is not None:
                        self._on_error(str(exc))
                    continue

                try:
                    text = self._recognize_chunk(audio)
                    if not text:
                        continue
                    if self._on_final is not None:
                        self._on_final(text)
                except self._sr.UnknownValueError:
                    continue
                except self._sr.RequestError as exc:
                    if self._on_error is not None:
                        self._on_error(str(exc))
                except Exception as exc:
                    if self._on_error is not None:
                        self._on_error(str(exc))
