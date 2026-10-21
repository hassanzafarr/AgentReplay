/* One stroke icon family (24px grid, 1.75 stroke) so every page draws icons the same way.
   All icons are decorative by default; give the surrounding control its accessible name. */

type IconProps = { className?: string };

function Icon({ className = "h-4 w-4", children }: IconProps & { children: React.ReactNode }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.75}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      className={className}
    >
      {children}
    </svg>
  );
}

export function FileUpIcon(p: IconProps) {
  return (
    <Icon {...p}>
      <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-5-5Z" />
      <path d="M14 3v5h5" />
      <path d="M12 17.5v-6" />
      <path d="m9.5 14 2.5-2.5 2.5 2.5" />
    </Icon>
  );
}

export function CloseIcon(p: IconProps) {
  return (
    <Icon {...p}>
      <path d="M17 7 7 17M7 7l10 10" />
    </Icon>
  );
}

export function ExternalIcon(p: IconProps) {
  return (
    <Icon {...p}>
      <path d="M7 17 17 7M8.5 7H17v8.5" />
    </Icon>
  );
}

export function ArrowRightIcon(p: IconProps) {
  return (
    <Icon {...p}>
      <path d="M5 12h14M13 6l6 6-6 6" />
    </Icon>
  );
}

export function SunIcon(p: IconProps) {
  return (
    <Icon {...p}>
      <circle cx="12" cy="12" r="3.75" />
      <path d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.3 5.3l1.4 1.4M17.3 17.3l1.4 1.4M5.3 18.7l1.4-1.4M17.3 6.7l1.4-1.4" />
    </Icon>
  );
}

export function MoonIcon(p: IconProps) {
  return (
    <Icon {...p}>
      <path d="M20.5 14.2A8.5 8.5 0 1 1 9.8 3.5a6.8 6.8 0 0 0 10.7 10.7Z" />
    </Icon>
  );
}

/** Empty event-detail state: "pick something on the left". */
export function PointerIcon(p: IconProps) {
  return (
    <Icon {...p}>
      <path d="m4.5 4.5 6.8 15.5 2.3-6.4 6.4-2.3L4.5 4.5Z" />
    </Icon>
  );
}

/** Empty diff state: two traces side by side. */
export function CompareIcon(p: IconProps) {
  return (
    <Icon {...p}>
      <path d="M9 3.5H5.5a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2H9M15 3.5h3.5a2 2 0 0 1 2 2v13a2 2 0 0 1-2 2H15M12 2v20" />
    </Icon>
  );
}

export function CheckIcon(p: IconProps) {
  return (
    <Icon {...p}>
      <path d="m5 12.5 4.5 4.5L19 7.5" />
    </Icon>
  );
}

export function CrossIcon(p: IconProps) {
  return (
    <Icon {...p}>
      <path d="M17 7 7 17M7 7l10 10" />
    </Icon>
  );
}

export function HelpIcon(p: IconProps) {
  return (
    <Icon {...p}>
      <circle cx="12" cy="12" r="9" />
      <path d="M9.4 9.3a2.7 2.7 0 0 1 5.2.9c0 1.8-2.6 2.4-2.6 2.4M12 16.5h.01" />
    </Icon>
  );
}
