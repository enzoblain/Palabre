type Props = { size?: number };

function Svg({ size = 18, children }: Props & { children: React.ReactNode }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {children}
    </svg>
  );
}

export const PlusIcon = (p: Props) => <Svg {...p}><path d="M12 5v14M5 12h14" /></Svg>;
export const MenuIcon = (p: Props) => <Svg {...p}><path d="M4 6h16M4 12h16M4 18h16" /></Svg>;
export const BackIcon = (p: Props) => <Svg {...p}><path d="M15 18l-6-6 6-6" /></Svg>;
export const InfoIcon = (p: Props) => <Svg {...p}><circle cx="12" cy="12" r="9" /><path d="M12 11v5M12 8h.01" /></Svg>;
export const GearIcon = (p: Props) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="3" />
    <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
  </Svg>
);
export const ListIcon = (p: Props) => <Svg {...p}><path d="M9 6h12M9 12h12M9 18h12M4 6h.01M4 12h.01M4 18h.01" /></Svg>;
export const HashIcon = (p: Props) => <Svg {...p}><path d="M4 9h16M4 15h16M10 3 8 21M16 3l-2 18" /></Svg>;
export const SendIcon = (p: Props) => <Svg {...p}><path d="M22 2 11 13M22 2l-7 20-4-9-9-4 20-7z" /></Svg>;
export const ShuffleIcon = (p: Props) => (
  <Svg {...p}><path d="M16 3h5v5M4 20 21 3M21 16v5h-5M15 15l6 6M4 4l5 5" /></Svg>
);
export const ConversationIcon = (p: Props) => (
  <Svg {...p}><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" /></Svg>
);
export const ProjectsIcon = (p: Props) => (
  <Svg {...p}><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" /></Svg>
);
export const TeamIcon = (p: Props) => (
  <Svg {...p}><circle cx="9" cy="8" r="3.5" /><path d="M2 20c0-3.3 3.1-6 7-6s7 2.7 7 6M16 4.6a3.5 3.5 0 0 1 0 6.8M18 14.4c2.3.7 4 2.5 4 5.6" /></Svg>
);
export const CheckIcon = (p: Props) => <Svg {...p}><circle cx="12" cy="12" r="9" /><path d="m8 12.5 3 3 5-6" /></Svg>;
export const CrossIcon = (p: Props) => <Svg {...p}><circle cx="12" cy="12" r="9" /><path d="m9 9 6 6M15 9l-6 6" /></Svg>;
export const WarningIcon = (p: Props) => <Svg {...p}><path d="M12 3 2 20h20z" /><path d="M12 10v5M12 18h.01" /></Svg>;
export const ClockIcon = (p: Props) => <Svg {...p}><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></Svg>;
export const SpinnerIcon = (p: Props) => <Svg {...p}><path d="M12 3a9 9 0 1 0 9 9" /></Svg>;
export const DotFilledIcon = (p: Props) => <Svg {...p}><circle cx="12" cy="12" r="6" fill="currentColor" /></Svg>;
export const DotEmptyIcon = (p: Props) => <Svg {...p}><circle cx="12" cy="12" r="6" /></Svg>;
