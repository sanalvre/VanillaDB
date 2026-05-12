/**
 * AgentVoiceButton — microphone button for voice-to-text input.
 *
 * Uses MediaRecorder to capture audio, then POSTs to /voice/transcribe
 * (OpenAI Whisper, server-side). No local model required.
 *
 * If no OpenAI key is configured the server returns 501 and the button
 * shows a prompt to add a key in Settings — Web Speech API is NOT used
 * because WebView2 does not support it.
 *
 * Props:
 *   onTranscript(text) — called with the final transcript string
 *   disabled           — disable the button while the agent is busy
 */

import { useRef, useState, useCallback, useEffect } from "react";
import { getTranscribeMode, transcribeBlob } from "@/api/agent";

interface Props {
  onTranscript: (text: string) => void;
  disabled?: boolean;
}

export function AgentVoiceButton({ onTranscript, disabled }: Props) {
  const [isRecording, setIsRecording] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // null = not yet checked, true = Whisper available, false = no key configured
  const [whisperAvailable, setWhisperAvailable] = useState<boolean | null>(null);

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const streamRef = useRef<MediaStream | null>(null);

  // Check transcription mode once on mount
  useEffect(() => {
    getTranscribeMode().then((m) => setWhisperAvailable(m.available));
  }, []);

  const startRecording = useCallback(async () => {
    if (whisperAvailable === false) {
      setError("Voice requires an OpenAI key — add one in Settings.");
      return;
    }

    setError(null);

    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      setError("Microphone access denied — check system permissions.");
      return;
    }

    streamRef.current = stream;
    chunksRef.current = [];

    const recorder = new MediaRecorder(stream, {
      mimeType: MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
        ? "audio/webm;codecs=opus"
        : "audio/webm",
    });
    mediaRecorderRef.current = recorder;

    recorder.ondataavailable = (e) => {
      if (e.data.size > 0) chunksRef.current.push(e.data);
    };

    recorder.start(250); // chunk every 250 ms
    setIsRecording(true);
  }, [whisperAvailable]);

  const stopRecording = useCallback(async () => {
    const recorder = mediaRecorderRef.current;
    if (!recorder || recorder.state === "inactive") return;

    setIsRecording(false);

    await new Promise<void>((resolve) => {
      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };
      recorder.onstop = () => resolve();
      recorder.stop();
    });

    // Release mic
    streamRef.current?.getTracks().forEach((t) => t.stop());

    const chunks = chunksRef.current;
    chunksRef.current = [];

    if (chunks.length === 0) {
      setError("No audio captured — try again.");
      return;
    }

    const blob = new Blob(chunks, { type: "audio/webm" });

    try {
      const transcript = await transcribeBlob(blob);

      if (transcript === null) {
        // Server returned 501 — no OpenAI key configured
        setWhisperAvailable(false);
        setError("Voice requires an OpenAI key — add one in Settings.");
        return;
      }

      setError(null);
      onTranscript(transcript);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Transcription failed.");
    }
  }, [onTranscript]);

  const handleClick = useCallback(async () => {
    if (isRecording) {
      await stopRecording();
    } else {
      await startRecording();
    }
  }, [isRecording, startRecording, stopRecording]);

  const modeLabel =
    whisperAvailable === false
      ? "Voice requires an OpenAI key (see Settings)"
      : whisperAvailable === true
        ? "Whisper — click to record"
        : "Voice input";

  return (
    <div className="flex items-center gap-1.5">
      <button
        onClick={handleClick}
        disabled={disabled}
        title={isRecording ? "Click to stop" : modeLabel}
        aria-label={isRecording ? "Stop recording" : "Start voice input"}
        className={`relative flex h-8 w-8 items-center justify-center rounded-lg transition-colors
          ${isRecording
            ? "bg-red-100 text-red-600 hover:bg-red-200 dark:bg-red-900/30 dark:text-red-400"
            : "text-stone-400 hover:bg-stone-100 hover:text-stone-600 dark:text-zinc-500 dark:hover:bg-zinc-800 dark:hover:text-zinc-300"
          } disabled:cursor-not-allowed disabled:opacity-40`}
      >
        {isRecording && (
          <span className="absolute right-1 top-1 h-1.5 w-1.5 animate-pulse rounded-full bg-red-500" />
        )}
        {/* Microphone icon */}
        <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
          <rect x="5.5" y="1.5" width="5" height="8" rx="2.5" stroke="currentColor" strokeWidth="1.3" />
          <path d="M3 8c0 2.76 2.24 5 5 5s5-2.24 5-5" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
          <line x1="8" y1="13" x2="8" y2="15" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
        </svg>
      </button>

      {error && (
        <p className="max-w-[140px] text-[10px] leading-tight text-red-500 dark:text-red-400">
          {error}
        </p>
      )}
    </div>
  );
}
