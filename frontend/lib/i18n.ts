"use client";

import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import type { User } from "@/lib/types";

/**
 * UI strings in English, Hindi and Marathi. A small dictionary instead of a routing i18n library keeps the public
 * pages static (cached, fast on 4G). The signed-in student's choice is saved on their account (it also sets the
 * language of WhatsApp digests); visitors' choice stays in this browser. Missing keys fall back to English.
 * Hindi and Marathi copy should be reviewed by a native speaker before a wide launch.
 */
export type Lang = "en" | "hi" | "mr";
export const LANGS: { v: Lang; label: string }[] = [
  { v: "en", label: "English" },
  { v: "hi", label: "हिन्दी" },
  { v: "mr", label: "मराठी" },
];

const D = {
  "nav.dashboard": { en: "Dashboard", hi: "डैशबोर्ड", mr: "डॅशबोर्ड" },
  "nav.matches": { en: "Matches", hi: "मैच", mr: "जुळणी" },
  "nav.approvals": { en: "Approvals", hi: "मंज़ूरी", mr: "मंजुरी" },
  "nav.skills": { en: "Skill check", hi: "स्किल जाँच", mr: "कौशल्य तपासणी" },
  "nav.tracker": { en: "Tracker", hi: "ट्रैकर", mr: "ट्रॅकर" },
  "nav.insights": { en: "Insights", hi: "इनसाइट्स", mr: "माहिती" },
  "nav.campus": { en: "Campus", hi: "कैंपस", mr: "कॅम्पस" },
  "nav.proof": { en: "Proof pack", hi: "प्रूफ़ पैक", mr: "पुरावा संच" },
  "nav.runs": { en: "Agent runs", hi: "एजेंट रन", mr: "एजंट रन" },
  "nav.settings": { en: "Settings", hi: "सेटिंग्स", mr: "सेटिंग्ज" },
  "approvals.title": { en: "Approvals", hi: "मंज़ूरी", mr: "मंजुरी" },
  "approvals.sub": {
    en: "The crew pauses here. Nothing is sent until you approve it.",
    hi: "टीम यहाँ रुकती है। आपकी मंज़ूरी के बिना कुछ नहीं भेजा जाता।",
    mr: "टीम इथे थांबते. तुम्ही मंजूर केल्याशिवाय काहीही पाठवले जात नाही.",
  },
  "approvals.left": { en: "{n} of {cap} sends left today", hi: "आज {cap} में से {n} भेजना बाकी", mr: "आज {cap} पैकी {n} पाठवणे बाकी" },
  "scam.title": { en: "Is this internship offer real?", hi: "क्या यह इंटर्नशिप ऑफ़र असली है?", mr: "ही इंटर्नशिप ऑफर खरी आहे का?" },
  "scam.message": { en: "The message or offer", hi: "मैसेज या ऑफ़र", mr: "मेसेज किंवा ऑफर" },
  "scam.placeholder": {
    en: "Paste the WhatsApp, Telegram or email message here…",
    hi: "WhatsApp, Telegram या ईमेल का मैसेज यहाँ पेस्ट करें…",
    mr: "WhatsApp, Telegram किंवा ईमेलचा मेसेज इथे पेस्ट करा…",
  },
  "scam.link": { en: "Link (optional)", hi: "लिंक (ज़रूरी नहीं)", mr: "लिंक (ऐच्छिक)" },
  "scam.file": { en: "Offer letter (PDF or image)", hi: "ऑफ़र लेटर (PDF या फ़ोटो)", mr: "ऑफर लेटर (PDF किंवा फोटो)" },
  "scam.check": { en: "Check it", hi: "जाँचें", mr: "तपासा" },
  "scam.private": {
    en: "Nothing you paste or upload is saved. We keep only an anonymous count of verdicts.",
    hi: "आप जो पेस्ट या अपलोड करते हैं, वह सेव नहीं होता। हम सिर्फ़ नतीजों की गिनती रखते हैं।",
    mr: "तुम्ही पेस्ट किंवा अपलोड केलेले काहीही जतन केले जात नाही. आम्ही फक्त निकालांची संख्या ठेवतो.",
  },
  "scam.todo": { en: "What to do", hi: "क्या करें", mr: "काय करावे" },
  "scam.share": { en: "Share", hi: "शेयर करें", mr: "शेअर करा" },
  "scam.risk": { en: "Risk score {n}/100", hi: "जोखिम स्कोर {n}/100", mr: "धोका गुण {n}/100" },
  "verdict.Likely scam": { en: "Likely scam", hi: "शायद धोखा", mr: "बहुधा फसवणूक" },
  "verdict.Suspicious": { en: "Suspicious", hi: "संदिग्ध", mr: "संशयास्पद" },
  "verdict.Likely safe": { en: "Likely safe", hi: "शायद सुरक्षित", mr: "बहुधा सुरक्षित" },
  "settings.language": { en: "Language", hi: "भाषा", mr: "भाषा" },
  "settings.language.sub": {
    en: "For the app’s main labels and your WhatsApp messages.",
    hi: "ऐप के मुख्य लेबल और आपके WhatsApp मैसेज के लिए।",
    mr: "अ‍ॅपची मुख्य लेबले आणि तुमच्या WhatsApp मेसेजसाठी.",
  },
} as const satisfies Record<string, Record<Lang, string>>;

export type Key = keyof typeof D;

export function translate(lang: Lang, key: Key, vars?: Record<string, string | number>): string {
  let s: string = D[key][lang] ?? D[key].en;
  for (const [k, v] of Object.entries(vars ?? {})) s = s.replace(`{${k}}`, String(v));
  return s;
}

const STORE = "jp-lang";

/** `account`: read the signed-in student's saved language (in the app). Public pages use this browser's choice only. */
export function useLang(account = true): [Lang, (l: Lang) => void] {
  const { data: me } = useQuery({ queryKey: ["me"], queryFn: () => api.get<User>("/auth/me"), staleTime: 5 * 60_000, enabled: account, retry: false });
  const [local, setLocal] = useState<Lang>("en");
  useEffect(() => {
    try {
      const v = localStorage.getItem(STORE);
      if (v === "hi" || v === "mr" || v === "en") setLocal(v);
    } catch {
      /* private mode: English */
    }
  }, []);
  const lang = ((me as { language?: Lang } | undefined)?.language ?? local) as Lang;
  const set = (l: Lang) => {
    setLocal(l);
    try {
      localStorage.setItem(STORE, l);
    } catch {
      /* ignore */
    }
  };
  return [lang, set];
}

export function useT(account = true) {
  const [lang] = useLang(account);
  return (key: Key, vars?: Record<string, string | number>) => translate(lang, key, vars);
}
