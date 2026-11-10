/** Open a ready-to-send email: the user's own mail client or Gmail web. Nothing is sent by JobPilot. */

export interface Mail {
  to?: string | null;
  cc?: string | null;
  subject: string;
  body: string;
}

export function mailtoUrl({ to, cc, subject, body }: Mail) {
  const ccPart = cc ? `&cc=${encodeURIComponent(cc)}` : "";
  return `mailto:${encodeURIComponent(to ?? "")}?subject=${encodeURIComponent(subject)}${ccPart}&body=${encodeURIComponent(body)}`;
}

export function gmailUrl({ to, cc, subject, body }: Mail) {
  const q = new URLSearchParams({ view: "cm", fs: "1", to: to ?? "", ...(cc ? { cc } : {}), su: subject, body });
  return `https://mail.google.com/mail/?${q}`;
}

/** Popup blockers only allow window.open inside the click handler, so reserve the tab first and
 *  point it at the destination once async work (approving the draft) has finished. */
export function reserveTab(): Window | null {
  const w = window.open("about:blank", "_blank");
  if (w) w.opener = null;
  return w;
}

export function sendTo(tab: Window | null, url: string) {
  if (url.startsWith("mailto:")) {
    tab?.close();
    window.location.href = url;
  } else if (tab) {
    tab.location.href = url;
  } else {
    window.open(url, "_blank", "noopener");
  }
}

export const SOURCE_LABEL: Record<string, string> = {
  greenhouse: "Greenhouse",
  lever: "Lever",
  ashby: "Ashby",
  themuse: "The Muse",
  remotive: "Remotive",
  jobicy: "Jobicy",
  adzuna: "Adzuna",
  demo: "Demo",
};
