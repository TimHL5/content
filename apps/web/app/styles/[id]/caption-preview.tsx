import type { StyleProfile } from "@stylecut/schemas";
import { Anton, Bebas_Neue, Inter, Montserrat, Poppins } from "next/font/google";
import type { CSSProperties } from "react";

type Captions = StyleProfile["captions"];

// The same OFL families the renderer bundles. Analysis maps what it sees to the nearest one.
const montserrat = Montserrat({ subsets: ["latin"], weight: "800", display: "swap" });
const inter = Inter({ subsets: ["latin"], weight: "700", display: "swap" });
const anton = Anton({ subsets: ["latin"], weight: "400", display: "swap" });
const poppins = Poppins({ subsets: ["latin"], weight: "600", display: "swap" });
const bebas = Bebas_Neue({ subsets: ["latin"], weight: "400", display: "swap" });

const FONT_CLASS: Record<string, string> = {
  "Montserrat ExtraBold": montserrat.className,
  "Inter Bold": inter.className,
  Anton: anton.className,
  "Poppins SemiBold": poppins.className,
  "Bebas Neue": bebas.className,
};

const SAMPLE = ["this", "is", "how", "your", "captions", "look"];

function applyCase(word: string, mode: Captions["case"], first: boolean): string {
  if (mode === "upper") return word.toUpperCase();
  if (mode === "lower") return word.toLowerCase();
  if (mode === "title") return word.charAt(0).toUpperCase() + word.slice(1);
  return first ? word.charAt(0).toUpperCase() + word.slice(1) : word;
}

/** A 9:16 frame showing one caption chunk in the profile's style, second word active. */
export function CaptionPreview({ captions }: { captions: Captions }) {
  const [, maxWords] = captions.words_per_chunk;
  const words = SAMPLE.slice(0, Math.min(Math.max(maxWords, 1), SAMPLE.length));
  const activeIndex = Math.min(1, words.length - 1);
  const stroke = captions.stroke ?? undefined;
  const base: CSSProperties = {
    color: captions.fill,
    WebkitTextStroke: stroke ? `${Math.max(captions.stroke_px / 3, 0.5)}px ${stroke}` : undefined,
    paintOrder: "stroke fill",
    textShadow: captions.shadow ? "0 2px 6px rgba(0,0,0,0.65)" : undefined,
  };

  return (
    <div
      className="relative mx-auto aspect-[9/16] w-full max-w-[200px] overflow-hidden rounded-lg bg-gradient-to-b from-stone-600 to-stone-800"
      role="img"
      aria-label={`Caption preview: ${captions.font_family}, ${captions.case} case, ${captions.highlight} highlight`}
    >
      {captions.present ? (
        <p
          className={`absolute inset-x-2 -translate-y-1/2 text-center text-[19px] leading-tight ${FONT_CLASS[captions.font_family] ?? montserrat.className}`}
          style={{ top: `${captions.position_y_pct * 100}%`, ...base }}
        >
          {words.map((word, i) => {
            const active = i === activeIndex && captions.highlight !== "none";
            const style: CSSProperties = {};
            if (active && captions.highlight === "color") style.color = captions.highlight_color ?? captions.fill;
            if (active && captions.highlight === "box") {
              style.background = captions.highlight_color ?? "#000000";
              style.borderRadius = 4;
              style.padding = "0 4px";
            }
            if (active && captions.highlight === "scale") {
              style.display = "inline-block";
              style.transform = "scale(1.15)";
            }
            return (
              <span key={word}>
                <span style={style}>{applyCase(word, captions.case, i === 0)}</span>
                {i < words.length - 1 ? " " : ""}
              </span>
            );
          })}
        </p>
      ) : (
        <p className="absolute inset-0 flex items-center justify-center px-4 text-center text-xs text-stone-300">
          This video has no captions
        </p>
      )}
    </div>
  );
}
