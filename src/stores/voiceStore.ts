import { create } from "zustand";

type ModelSize = "tiny" | "base" | "small" | "medium";

interface VoiceState {
  isRecording: boolean;
  transcript: string | null;
  modelSize: ModelSize;
  error: string | null;

  setRecording: (v: boolean) => void;
  setTranscript: (t: string | null) => void;
  setModelSize: (s: ModelSize) => void;
  setError: (e: string | null) => void;
  reset: () => void;
}

export const useVoiceStore = create<VoiceState>((set) => ({
  isRecording: false,
  transcript: null,
  modelSize: "base",
  error: null,

  setRecording: (v) => set({ isRecording: v }),
  setTranscript: (t) => set({ transcript: t }),
  setModelSize: (s) => set({ modelSize: s }),
  setError: (e) => set({ error: e }),
  reset: () => set({ isRecording: false, transcript: null, error: null }),
}));
