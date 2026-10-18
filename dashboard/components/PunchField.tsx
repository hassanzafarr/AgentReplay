import { hollerith, punchText, ROWS } from "@/lib/punch";

const COL_W = 8;
const ROW_H = 6.5;
const PRINT_H = 10; // interpreter line: the punched characters printed along the top edge

/* The punched band of a card: one column per character, tall slots in Hollerith code, and
   the characters printed above their columns the way a keypunch interprets a card.
   Holes use --hole (the dark below the card), so they read on manila in either theme. */
export default function PunchField({
  source,
  columns = 12,
  className = "",
}: {
  source: string;
  columns?: number;
  className?: string;
}) {
  const text = punchText(source, columns);
  const width = columns * COL_W;
  const height = PRINT_H + ROWS.length * ROW_H;
  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      width={width}
      height={height}
      aria-hidden="true"
      focusable="false"
      className={`punch-grid shrink-0 ${className}`}
      style={{ backgroundSize: `${COL_W}px ${ROW_H}px`, backgroundPosition: `0 ${PRINT_H}px` }}
    >
      <title>{text ? `Card punched ${text}` : "Blank card"}</title>
      {[...text].map((ch, col) => (
        <text
          key={`p${col}`}
          x={col * COL_W + COL_W / 2}
          y={7.5}
          textAnchor="middle"
          fontSize={7.5}
          fill="var(--ink)"
          style={{ fontFamily: "var(--font-fragment-mono), monospace" }}
        >
          {ch}
        </text>
      ))}
      {[...text].flatMap((ch, col) =>
        hollerith(ch).map((row) => (
          <rect
            key={`${col}-${row}`}
            x={col * COL_W + 2.2}
            y={PRINT_H + row * ROW_H + 0.65}
            width={3.6}
            height={5.2}
            rx={0.5}
            fill="var(--hole)"
          />
        ))
      )}
    </svg>
  );
}
