"use client";

import { FileText, UploadCloud } from "lucide-react";
import { useRef, useState } from "react";

import { useUploadResume } from "@/lib/queries";
import { cn } from "@/lib/utils";

export function ResumeDropzone({ filename, className }: { filename?: string | null; className?: string }) {
  const upload = useUploadResume();
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const send = (f?: File) => f && upload.mutate(f);

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => input.current?.click()}
      onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && input.current?.click()}
      onDragOver={(e) => {
        e.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setOver(false);
        send(e.dataTransfer.files?.[0]);
      }}
      className={cn(
        "relative flex cursor-pointer flex-col items-center justify-center rounded-[var(--radius-card)] border border-dashed px-6 py-10 text-center transition-all",
        over ? "border-accent bg-accent-soft" : "border-border-strong bg-surface-2/40 hover:border-accent/60 hover:bg-accent-soft/50",
        upload.isPending && "pointer-events-none",
        className,
      )}
    >
      <input ref={input} type="file" accept=".pdf,.docx,.txt,.md" hidden onChange={(e) => send(e.target.files?.[0])} />
      <div className={cn("mb-3 grid size-12 place-items-center rounded-[var(--radius-card)] bg-surface text-accent shadow-card", upload.isPending && "animate-pulse-soft")}>
        {upload.isPending ? <FileText className="size-5" /> : <UploadCloud className="size-5" />}
      </div>
      <div className="text-sm font-semibold">{upload.isPending ? "Parsing your resume…" : filename ? "Replace resume" : "Drop your resume here"}</div>
      <div className="mt-1 text-[13px] text-muted">
        {upload.isPending ? "Extracting skills, roles and bullets" : filename ? `Current: ${filename}` : "PDF, DOCX, TXT or MD · up to 5 MB"}
      </div>
    </div>
  );
}
