/** Word-level diff (LCS) between an original line and its rewrite: removed words struck through, added words highlighted. */
export function diffWords(a: string, b: string): { text: string; op: "same" | "add" | "del" }[] {
  const x = a.split(/(\s+)/).filter(Boolean);
  const y = b.split(/(\s+)/).filter(Boolean);
  const n = x.length;
  const m = y.length;
  const dp: number[][] = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--) dp[i][j] = x[i] === y[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  const out: { text: string; op: "same" | "add" | "del" }[] = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (x[i] === y[j]) {
      out.push({ text: x[i], op: "same" });
      i++;
      j++;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) out.push({ text: x[i++], op: "del" });
    else out.push({ text: y[j++], op: "add" });
  }
  while (i < n) out.push({ text: x[i++], op: "del" });
  while (j < m) out.push({ text: y[j++], op: "add" });
  return out;
}

export function WordDiff({ original, rewritten, mode }: { original: string; rewritten: string; mode: "before" | "after" }) {
  const parts = diffWords(original, rewritten);
  return (
    <span>
      {parts.map((p, i) =>
        p.op === "same" ? (
          <span key={i}>{p.text}</span>
        ) : p.op === "del" && mode === "before" ? (
          /\s/.test(p.text) ? <span key={i}>{p.text}</span> : (
            <del key={i} className="rounded-[3px] bg-[color-mix(in_oklab,var(--error)_14%,transparent)] px-0.5 text-[var(--error)] decoration-[var(--error)]/60">
              {p.text}
            </del>
          )
        ) : p.op === "add" && mode === "after" ? (
          /\s/.test(p.text) ? <span key={i}>{p.text}</span> : (
            <ins key={i} className="rounded-[3px] bg-[color-mix(in_oklab,var(--done)_16%,transparent)] px-0.5 text-[var(--done)] no-underline">
              {p.text}
            </ins>
          )
        ) : null,
      )}
    </span>
  );
}
