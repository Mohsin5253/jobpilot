/** Share of a dictated take's words that are missing (in order) from the submitted answer. */
export function editRatio(dictated: string, final: string): number {
  const a = dictated.toLowerCase().match(/[\p{L}\p{N}'+#-]+/gu) ?? [];
  const b = final.toLowerCase().match(/[\p{L}\p{N}'+#-]+/gu) ?? [];
  if (!a.length) return 0;
  const dp = new Array(b.length + 1).fill(0);
  for (let i = 1; i <= a.length; i++) {
    let prev = 0;
    for (let j = 1; j <= b.length; j++) {
      const tmp = dp[j];
      dp[j] = a[i - 1] === b[j - 1] ? prev + 1 : Math.max(dp[j], dp[j - 1]);
      prev = tmp;
    }
  }
  return Math.round((1 - dp[b.length] / a.length) * 1000) / 1000;
}
