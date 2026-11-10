"use client";

import { FlipHorizontal2, Minus, Pause, Play, Plus, RotateCcw, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { markEmphasis, teleprompterMs } from "@/lib/plan";

const SPEEDS = { min: 0.8, max: 1.2, step: 0.05 };

interface PromptLine {
  text: string;
  emphasis: string[];
  note: string | null;
}

/**
 * Full-screen teleprompter. Text scrolls at the style's speaking pace (adjustable ±20%),
 * sits near the top of the screen so the eyes stay close to a phone's front camera, and
 * can be mirrored for use with a reflector.
 */
export function Teleprompter({
  title,
  lines,
  wpm,
  onClose,
}: {
  title: string;
  lines: PromptLine[];
  wpm: number;
  onClose: () => void;
}) {
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [mirror, setMirror] = useState(false);
  const [progress, setProgress] = useState(0); // 0-1 through the text
  const text = useRef<HTMLDivElement>(null);
  const progressRef = useRef(0);

  const fullText = lines.map((l) => l.text).join(" ");
  const durationMs = teleprompterMs(fullText, wpm, speed);

  useEffect(() => {
    if (!playing || durationMs === 0) return;
    let frame = 0;
    let last = performance.now();
    const tick = (now: number) => {
      const next = Math.min(progressRef.current + (now - last) / durationMs, 1);
      last = now;
      progressRef.current = next;
      setProgress(next);
      if (next >= 1) setPlaying(false);
      else frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [playing, durationMs]);

  // Keep the page behind from scrolling while the prompter is open.
  useEffect(() => {
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
    };
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (e.key === " ") {
        e.preventDefault();
        setPlaying((p) => !p);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  // Scroll exactly the height of the text: the last line reaches the reading line as time runs out.
  const travel = text.current?.offsetHeight ?? 0;
  const restart = () => {
    progressRef.current = 0;
    setProgress(0);
    setPlaying(false);
  };
  const changeSpeed = (delta: number) =>
    setSpeed((s) => Math.round(Math.min(Math.max(s + delta, SPEEDS.min), SPEEDS.max) * 100) / 100);

  const control =
    "flex min-h-12 min-w-12 items-center justify-center rounded-full bg-white/10 text-white outline-white hover:bg-white/20 focus-visible:outline-2 disabled:opacity-40";

  return (
    <div role="dialog" aria-modal="true" aria-label={`Teleprompter: ${title}`} className="fixed inset-0 z-50 flex flex-col bg-black text-white">
      <div className="flex items-center justify-between gap-3 px-4 pt-[max(env(safe-area-inset-top),0.75rem)]">
        <p className="min-w-0 truncate text-sm text-white/60">{title}</p>
        <button type="button" onClick={onClose} aria-label="Close teleprompter" className={control}>
          <X className="size-5" aria-hidden />
        </button>
      </div>

      <div className="relative flex-1 overflow-hidden">
        {/* Reading line: keep your eyes here, just below the camera. */}
        <div className="pointer-events-none absolute inset-x-0 top-[14%] z-10 h-px bg-white/25" aria-hidden />
        <div
          className="px-5 pt-[14vh] text-[2rem] font-semibold leading-snug will-change-transform sm:text-[2.75rem]"
          style={{ transform: `translateY(${-progress * travel}px) scaleX(${mirror ? -1 : 1})` }}
        >
          <div ref={text}>
          {lines.map((line, i) => (
            <p key={i} className="pb-8">
              {line.note !== null && <span className="mb-2 block text-base font-normal text-white/50">({line.note})</span>}
              {markEmphasis(line.text, line.emphasis).map((part, j) => (
                <span key={j} className={part.strong ? "text-yellow-300" : undefined}>
                  {part.word}{" "}
                </span>
              ))}
            </p>
          ))}
          </div>
          <div className="h-[60vh]" aria-hidden />
        </div>
      </div>

      <div className="flex items-center justify-between gap-2 px-4 pb-[max(env(safe-area-inset-bottom),1rem)] pt-3">
        <div className="flex items-center gap-2">
          <button type="button" onClick={() => changeSpeed(-SPEEDS.step)} disabled={speed <= SPEEDS.min} aria-label="Slower" className={control}>
            <Minus className="size-5" aria-hidden />
          </button>
          <span className="w-20 text-center text-sm tabular-nums" aria-live="polite">
            {Math.round(wpm * speed)} wpm
          </span>
          <button type="button" onClick={() => changeSpeed(SPEEDS.step)} disabled={speed >= SPEEDS.max} aria-label="Faster" className={control}>
            <Plus className="size-5" aria-hidden />
          </button>
        </div>
        <div className="flex items-center gap-2">
          <button type="button" onClick={() => setMirror((m) => !m)} aria-pressed={mirror} aria-label="Mirror text" className={control}>
            <FlipHorizontal2 className="size-5" aria-hidden />
          </button>
          <button type="button" onClick={restart} aria-label="Back to start" className={control}>
            <RotateCcw className="size-5" aria-hidden />
          </button>
          <button
            type="button"
            onClick={() => {
              if (progress >= 1) restart();
              setPlaying((p) => !p);
            }}
            aria-label={playing ? "Pause" : "Start scrolling"}
            className="flex min-h-14 min-w-14 items-center justify-center rounded-full bg-white text-black outline-white focus-visible:outline-2 focus-visible:outline-offset-2"
          >
            {playing ? <Pause className="size-6" aria-hidden /> : <Play className="size-6" aria-hidden />}
          </button>
        </div>
      </div>
    </div>
  );
}
