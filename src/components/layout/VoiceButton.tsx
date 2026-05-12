/**
 * VoiceButton — global voice-to-cursor controller.
 *
 * Records audio in the browser and transcribes via:
 *   1. POST /voice/transcribe (server-side OpenAI Whisper, if key configured)
 *   2. Web Speech API fallback (browser-native, no key needed)
 *
 * Transcript is delivered by dispatching "vanilla:voice-transcript" on window.
 * useCodemirror listens for that event and inserts the text at cursor.
 *
 * Responds to three triggers:
 *   1. Tauri "voice:start" event (Ctrl+Shift+Space pressed)
 *   2. Tauri "voice:stop" event  (Ctrl+Shift+Space released)
 *   3. "vanilla:voice-toggle" DOM event (mic button click in SidebarRail)
 *
 * No visible UI — the recording indicator lives in SidebarRail.
 */

import { useEffect, useRef, useCallback } from "react";
import { useVoiceStore } from "@/stores/voiceStore";
import { getTranscribeMode, transcribeBlob } from "@/api/agent";

type UnlistenFn = () => void;

async function listenTauri(
  event: string,
  handler: () => void,
): Promise<UnlistenFn | null> {
  try {
    const { listen } = await import("@tauri-apps/api/event");
    return await listen(event, handler);
  } catch {
    return null;
  }
}

export function VoiceButton() {
  const { setRecording, setTranscript, setError } = useVoiceStore();
  const isRecordingRef = useRef(false);
  const useWhisperRef = useRef<boolean | null>(null); // null = not checked yet

  // Refs for MediaRecorder path
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const streamRef = useRef<MediaStream | null>(null);

  // Ref for Web Speech path
  const speechRecRef = useRef<any>(null);

  // Check transcription mode once
  useEffect(() => {
    getTranscribeMode().then((m) => { useWhisperRef.current = m.available; });
  }, []);

  const deliverTranscript = useCallback((text: string) => {
    setTranscript(text);
    window.dispatchEvent(
      new CustomEvent("vanilla:voice-transcript", { detail: { transcript: text } }),
    );
  }, [setTranscript]);

  // ── Web Speech path ─────────────────────────────────────────────────
  const startSpeechRec = useCallback(() => {
    const SR = (window as any).SpeechRecognition ?? (window as any).webkitSpeechRecognition;
    if (!SR) {
      setError("Voice not supported — add an OpenAI key in Settings.");
      isRecordingRef.current = false;
      setRecording(false);
      return;
    }

    const rec = new SR();
    rec.continuous = false;
    rec.interimResults = false;
    rec.lang = "en-US";

    rec.onresult = (e: any) => {
      const text = e.results[0]?.[0]?.transcript ?? "";
      if (text) { setError(null); deliverTranscript(text); }
      isRecordingRef.current = false;
      setRecording(false);
    };

    rec.onerror = (e: any) => {
      if (e.error !== "aborted") setError(`Speech error: ${e.error}`);
      isRecordingRef.current = false;
      setRecording(false);
    };

    rec.onend = () => {
      isRecordingRef.current = false;
      setRecording(false);
    };

    speechRecRef.current = rec;
    rec.start();
  }, [deliverTranscript, setError, setRecording]);

  const stopSpeechRec = useCallback(() => {
    speechRecRef.current?.stop();
    speechRecRef.current = null;
    isRecordingRef.current = false;
    setRecording(false);
  }, [setRecording]);

  // ── MediaRecorder / Whisper path ─────────────────────────────────────
  const startMediaRecorder = useCallback(async () => {
    setError(null);
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      setError("Microphone access denied.");
      isRecordingRef.current = false;
      setRecording(false);
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
    recorder.ondataavailable = (e) => { if (e.data.size > 0) chunksRef.current.push(e.data); };
    recorder.start(250);
  }, [setError, setRecording]);

  const stopMediaRecorder = useCallback(async () => {
    const recorder = mediaRecorderRef.current;
    if (!recorder || recorder.state === "inactive") return;

    await new Promise<void>((resolve) => {
      recorder.ondataavailable = (e) => { if (e.data.size > 0) chunksRef.current.push(e.data); };
      recorder.onstop = () => resolve();
      recorder.stop();
    });
    streamRef.current?.getTracks().forEach((t) => t.stop());

    const chunks = chunksRef.current;
    chunksRef.current = [];
    isRecordingRef.current = false;
    setRecording(false);

    if (!chunks.length) { setError("No audio captured."); return; }

    const blob = new Blob(chunks, { type: "audio/webm" });
    try {
      const transcript = await transcribeBlob(blob);
      if (transcript === null) {
        // 501 — fall back to speech recognition
        useWhisperRef.current = false;
        setError("Switched to browser speech — click mic and speak.");
        return;
      }
      setError(null);
      deliverTranscript(transcript);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Transcription failed.");
    }
  }, [deliverTranscript, setError, setRecording]);

  // ── Unified start/stop ───────────────────────────────────────────────
  const onStart = useCallback(async () => {
    if (isRecordingRef.current) return;
    isRecordingRef.current = true;
    setRecording(true);
    setError(null);

    if (useWhisperRef.current === false) {
      startSpeechRec();
    } else {
      await startMediaRecorder();
    }
  }, [setRecording, setError, startSpeechRec, startMediaRecorder]);

  const onStop = useCallback(async () => {
    if (!isRecordingRef.current) return;

    if (useWhisperRef.current === false) {
      stopSpeechRec();
    } else {
      await stopMediaRecorder();
    }
  }, [stopSpeechRec, stopMediaRecorder]);

  const onToggle = useCallback(() => {
    if (isRecordingRef.current) { onStop(); } else { onStart(); }
  }, [onStart, onStop]);

  useEffect(() => {
    let unlistenStart: UnlistenFn | null = null;
    let unlistenStop: UnlistenFn | null = null;

    Promise.all([
      listenTauri("voice:start", onStart),
      listenTauri("voice:stop", onStop),
    ]).then(([u1, u2]) => {
      unlistenStart = u1;
      unlistenStop = u2;
    });

    window.addEventListener("vanilla:voice-toggle", onToggle);

    return () => {
      unlistenStart?.();
      unlistenStop?.();
      window.removeEventListener("vanilla:voice-toggle", onToggle);
    };
  }, [onStart, onStop, onToggle]);

  return null;
}
