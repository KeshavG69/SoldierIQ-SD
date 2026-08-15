// Type declarations for Calendly widget
interface CalendlyOptions {
  url: string;
  prefill?: {
    name?: string;
    email?: string;
    firstName?: string;
    lastName?: string;
    customAnswers?: Record<string, string>;
  };
  utm?: Record<string, string>;
}

interface CalendlyWidget {
  initPopupWidget: (options: CalendlyOptions) => void;
  closePopupWidget: () => void;
  initInlineWidget: (options: CalendlyOptions & { parentElement: HTMLElement }) => void;
  initBadgeWidget: (options: CalendlyOptions & { text: string; color: string; textColor: string; branding: boolean }) => void;
  showPopupWidget: (url: string) => void;
}

interface Window {
  Calendly?: CalendlyWidget;
}
