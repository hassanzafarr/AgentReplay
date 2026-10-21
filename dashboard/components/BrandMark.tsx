/* The mark is a punched card whose holes spell "AR" in Hollerith code (A = 12+1, R = 11+9).
   Shared by both page headers so it stays identical everywhere. */
export default function BrandMark() {
  return (
    <span className="flex items-center gap-2.5">
      <svg viewBox="0 0 30 22" width="30" height="22" aria-hidden="true" focusable="false" className="shrink-0">
        <path d="M5 0H30V22H0V5Z" fill="var(--card)" />
        {/* 12 rows span y 3–20 (≈1.42 each). Column 1: A → rows 12, 1. Column 2: R → rows 11, 9. */}
        <rect x="10" y="3" width="3" height="2.6" rx="0.4" fill="var(--hole)" />
        <rect x="10" y="7.3" width="3" height="2.6" rx="0.4" fill="var(--hole)" />
        <rect x="17" y="4.4" width="3" height="2.6" rx="0.4" fill="var(--hole)" />
        <rect x="17" y="18.6" width="3" height="2.6" rx="0.4" fill="var(--hole)" />
        <rect x="24" y="3" width="3" height="16" fill="var(--print)" opacity="0.85" />
      </svg>
      <span className="text-lg font-extrabold tracking-tight text-on-desk">AgentReplay</span>
    </span>
  );
}
