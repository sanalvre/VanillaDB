/**
 * Logo — VanillaDB wordmark with vanilla flower/plant icon.
 */

import { memo } from "react";

interface LogoProps {
  variant?: "full" | "icon";
  size?: "sm" | "md" | "lg";
}

export const Logo = memo(function Logo({
  variant = "full",
  size = "md",
}: LogoProps) {
  const iconSize = size === "sm" ? 20 : size === "md" ? 26 : 34;
  const textSize =
    size === "sm" ? "text-sm" : size === "md" ? "text-base" : "text-lg";
  const gap = size === "sm" ? "gap-1.5" : size === "md" ? "gap-2" : "gap-2.5";

  return (
    <div className={`flex items-center ${gap}`}>
      {/* Vanilla flower plant icon */}
      <svg
        width={iconSize}
        height={iconSize}
        viewBox="0 0 32 32"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
      >
        {/* Stem */}
        <path
          d="M16 28 C16 28 16 20 16 14"
          stroke="#57534e"
          strokeWidth="1.6"
          strokeLinecap="round"
        />

        {/* Left leaf */}
        <path
          d="M16 22 C13 20 10 21 9 19 C10 17 13 18 16 20"
          fill="#78716c"
          opacity="0.7"
        />

        {/* Right leaf */}
        <path
          d="M16 18 C19 16 22 17 23 15 C22 13 19 14 16 16"
          fill="#78716c"
          opacity="0.7"
        />

        {/* Vanilla bean pod (hanging) */}
        <path
          d="M14.5 26 C14 27.5 14.5 29.5 16 30 C17.5 29.5 18 27.5 17.5 26"
          stroke="#a8956a"
          strokeWidth="1.4"
          strokeLinecap="round"
          fill="none"
        />

        {/* Flower — 5 petals around centre */}
        {/* Top petal */}
        <ellipse
          cx="16"
          cy="10"
          rx="2"
          ry="3.5"
          fill="#d6d3d1"
          stroke="#a8a29e"
          strokeWidth="0.6"
        />
        {/* Top-right petal */}
        <ellipse
          cx="19.3"
          cy="12"
          rx="2"
          ry="3.5"
          fill="#d6d3d1"
          stroke="#a8a29e"
          strokeWidth="0.6"
          transform="rotate(72 19.3 12)"
        />
        {/* Bottom-right petal */}
        <ellipse
          cx="18"
          cy="15.8"
          rx="2"
          ry="3.5"
          fill="#d6d3d1"
          stroke="#a8a29e"
          strokeWidth="0.6"
          transform="rotate(144 18 15.8)"
        />
        {/* Bottom-left petal */}
        <ellipse
          cx="14"
          cy="15.8"
          rx="2"
          ry="3.5"
          fill="#d6d3d1"
          stroke="#a8a29e"
          strokeWidth="0.6"
          transform="rotate(216 14 15.8)"
        />
        {/* Top-left petal */}
        <ellipse
          cx="12.7"
          cy="12"
          rx="2"
          ry="3.5"
          fill="#d6d3d1"
          stroke="#a8a29e"
          strokeWidth="0.6"
          transform="rotate(288 12.7 12)"
        />

        {/* Flower centre */}
        <circle cx="16" cy="13" r="2.2" fill="#f59e0b" opacity="0.9" />
        <circle cx="16" cy="13" r="1" fill="#d97706" />
      </svg>

      {/* Wordmark */}
      {variant === "full" && (
        <span
          className={`font-semibold tracking-tight ${textSize} text-stone-800 dark:text-zinc-100`}
        >
          VanillaDB
        </span>
      )}
    </div>
  );
});
