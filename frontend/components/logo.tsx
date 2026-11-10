/** The JobPilot mark: a cobalt squircle with a north-star glint (the crew pin, as an app icon). */
export function Logo({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden>
      <rect width="32" height="32" rx="9" fill="#4C7DFF" />
      <rect width="32" height="32" rx="9" fill="url(#jp-sheen)" />
      <defs>
        <linearGradient id="jp-sheen" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#fff" stopOpacity="0.22" />
          <stop offset="1" stopColor="#fff" stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d="M16 6.5 18.3 13.7 25.5 16l-7.2 2.3L16 25.5l-2.3-7.2L6.5 16l7.2-2.3Z" fill="#fff" />
    </svg>
  );
}
