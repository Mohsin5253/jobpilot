"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { agentToast } from "@/components/agents/agent-toast";

import { api } from "./api";
import type {
  DraftWithJob,
  Match,
  MatchDetail,
  Overview,
  Preferences,
  Profile,
  AnswersResult,
  AppConfig,
  AppNotification,
  ContactsOut,
  ResearchState,
  Reminder,
  Resume,
  SkillQuestion,
  Run,
  RunDetail,
  Stage,
  User,
  Usage,
  MailAccount,
  AdminMetrics,
  Campus,
  CollegeDashboard,
  ConsentState,
  MyProofLink,
  QuotaState,
  RightsRequest,
  RightsState,
  Evidence,
  ExtensionToken,
  Insights,
  Outcome,
  WhatsAppState,
} from "./types";

const ACTIVE: Run["status"][] = ["queued", "running", "resume_queued"];
export const isActive = (r?: Run | null) => !!r && ACTIVE.includes(r.status);

export const useMe = () => useQuery({ queryKey: ["me"], queryFn: () => api.get<User>("/auth/me"), staleTime: 5 * 60_000 });

export const useProfile = () => useQuery({ queryKey: ["profile"], queryFn: () => api.get<Profile>("/profile") });

export function useOverview() {
  return useQuery({
    queryKey: ["overview"],
    queryFn: () => api.get<Overview>("/stats/overview"),
    refetchInterval: (q) => (isActive(q.state.data?.last_run) ? 2500 : 30_000),
  });
}

export function useRuns(limit = 20) {
  return useQuery({
    queryKey: ["runs", limit],
    queryFn: () => api.get<Run[]>(`/runs?limit=${limit}`),
    refetchInterval: (q) => (q.state.data?.some(isActive) ? 2000 : 20_000),
  });
}

export function useRun(id: string) {
  return useQuery({
    queryKey: ["run", id],
    queryFn: () => api.get<RunDetail>(`/runs/${id}`),
    enabled: !!id,
    refetchInterval: (q) => (isActive(q.state.data) ? 2000 : false),
  });
}

export interface MatchFilters {
  stage?: Stage[];
  track?: "technical" | "non_technical";
  min_score?: number;
  q?: string;
  remote?: boolean;
  sort?: "score" | "recent" | "posted";
  limit?: number;
}

export function useMatches(f: MatchFilters = {}) {
  const params = new URLSearchParams();
  f.stage?.forEach((s) => params.append("stage", s));
  if (f.min_score) params.set("min_score", String(f.min_score));
  if (f.q) params.set("q", f.q);
  if (f.remote !== undefined) params.set("remote", String(f.remote));
  if (f.track) params.set("track", f.track);
  if (f.sort) params.set("sort", f.sort);
  params.set("limit", String(f.limit ?? 100));
  return useQuery({
    queryKey: ["matches", f],
    queryFn: () => api.get<{ items: Match[]; total: number }>(`/matches?${params}`),
    placeholderData: (prev) => prev,
    refetchInterval: 60_000,
  });
}

export const useMatch = (id: string) =>
  useQuery({ queryKey: ["match", id], queryFn: () => api.get<MatchDetail>(`/matches/${id}`) });

export const useSimilar = (id: string) =>
  useQuery({ queryKey: ["similar", id], queryFn: () => api.get<Match[]>(`/matches/${id}/similar`) });

export const useDrafts = (status: string = "pending") =>
  useQuery({ queryKey: ["drafts", status], queryFn: () => api.get<DraftWithJob[]>(`/drafts?status=${status}`) });

export const useReminders = () => useQuery({ queryKey: ["reminders"], queryFn: () => api.get<Reminder[]>("/reminders") });

function useInvalidate() {
  const qc = useQueryClient();
  return (...keys: string[]) => keys.forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
}

export function useStartRun() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: () => api.post<Run>("/runs"),
    onSuccess: () => {
      agentToast("scout", "On it. Fetching fresh postings now.");
      invalidate("runs", "overview");
    },
    onError: (e: Error) => toast.error(e.message),
  });
}

export function useRetryRun() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (id: string) => api.post<Run>(`/runs/${id}/retry`),
    onSuccess: () => {
      toast.success("Retrying from the last completed agent");
      invalidate("runs", "run", "overview");
    },
    onError: (e: Error) => toast.error(e.message),
  });
}

export function useUpdateMatch() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...body }: { id: string; stage?: Stage; notes?: string; user_rating?: number; ppo_status?: Match["ppo_status"] }) =>
      api.patch<Match>(`/matches/${id}`, body),
    onMutate: async ({ id, stage }) => {
      if (!stage) return;
      await qc.cancelQueries({ queryKey: ["matches"] });
      const snapshots = qc.getQueriesData<{ items: Match[]; total: number }>({ queryKey: ["matches"] });
      snapshots.forEach(([key, data]) => {
        if (data) qc.setQueryData(key, { ...data, items: data.items.map((m) => (m.id === id ? { ...m, stage } : m)) });
      });
      return { snapshots };
    },
    onError: (e: Error, _v, ctx) => {
      ctx?.snapshots.forEach(([key, data]) => qc.setQueryData(key, data));
      toast.error(e.message);
    },
    onSettled: (_d, _e, v) => {
      qc.invalidateQueries({ queryKey: ["matches"] });
      qc.invalidateQueries({ queryKey: ["match", v.id] });
      qc.invalidateQueries({ queryKey: ["overview"] });
    },
  });
}

export function useDecideDraft() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: ({ id, ...body }: { id: string; decision: "approve" | "reject"; to_email?: string; subject?: string; email_body?: string; linkedin_note?: string }) =>
      api.post<DraftWithJob>(`/drafts/${id}/decision`, body),
    onSuccess: (d) => {
      toast.success(d.status === "approved" ? `Approved · ${d.company} moved to Applied` : `Rejected draft for ${d.company}`);
      invalidate("drafts", "overview", "matches", "match", "runs", "quota");
    },
    onError: (e: Error) => toast.error(e.message),
  });
}

export function useMarkSent() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (id: string) => api.post<DraftWithJob>(`/drafts/${id}/mark-sent`),
    onSuccess: () => {
      toast.success("Marked as sent");
      invalidate("drafts", "match");
    },
  });
}

export function useSaveProfile() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { preferences?: Preferences; resume?: Resume }) => api.put<Profile>("/profile", body),
    onSuccess: (p) => {
      qc.setQueryData(["profile"], p);
      toast.success("Saved");
    },
    onError: (e: Error) => toast.error(e.message),
  });
}

export function useUploadResume() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (file: File) => {
      const fd = new FormData();
      fd.append("file", file);
      return api.post<Profile>("/profile/resume", fd);
    },
    onSuccess: (p) => {
      qc.setQueryData(["profile"], p);
      qc.invalidateQueries({ queryKey: ["overview"] });
      toast.success("Resume parsed", { description: `${p.resume.skills.length} skills · ${p.resume.experience.length + p.resume.projects.length} roles & projects` });
    },
    onError: (e: Error) => toast.error(e.message),
  });
}

export function useDismissReminder() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (id: string) => api.post<void>(`/reminders/${id}/dismiss`),
    onSuccess: () => invalidate("reminders", "overview"),
  });
}

export const useQuestions = () =>
  useQuery({ queryKey: ["questions"], queryFn: () => api.get<SkillQuestion[]>("/questions") });

export function useAnswerQuestions() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (answers: { id: string; has_skill: boolean; details: string }[]) => api.post<AnswersResult>("/questions/answers", { answers }),
    onSuccess: (r) => {
      if (r.rechecking_jobs)
        toast.success(`Added ${r.skills_added.join(", ")} to your profile`, { description: `Re-checking ${r.rechecking_jobs} job(s) with your new skills…` });
      else if (r.skills_added.length) toast.success(`Added ${r.skills_added.join(", ")} to your profile`, { description: "Your next run will use it." });
      else toast.success("Thanks — noted");
      invalidate("questions", "overview", "profile", "runs");
    },
    onError: (e: Error) => toast.error(e.message),
  });
}

export function useDismissQuestion() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (id: string) => api.post<void>(`/questions/${id}/dismiss`),
    onSuccess: () => invalidate("questions", "overview"),
  });
}

/** Accept or decline one of Tailor's rewrites. Optimistic: the toggle flips at once and rolls back on error. */
export function useDecideBullet(matchId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ sourceId, declined }: { sourceId: string; declined: boolean }) =>
      api.patch<NonNullable<MatchDetail["tailored"]>>(`/matches/${matchId}/tailored/bullets/${encodeURIComponent(sourceId)}`, { declined }),
    onMutate: async ({ sourceId, declined }) => {
      await qc.cancelQueries({ queryKey: ["match", matchId] });
      const prev = qc.getQueryData<MatchDetail>(["match", matchId]);
      if (prev?.tailored)
        qc.setQueryData<MatchDetail>(["match", matchId], {
          ...prev,
          tailored: { ...prev.tailored, bullets: prev.tailored.bullets.map((b) => (b.source_id === sourceId ? { ...b, declined } : b)) },
        });
      return { prev };
    },
    onError: (e: Error, _v, ctx) => {
      if (ctx?.prev) qc.setQueryData(["match", matchId], ctx.prev);
      toast.error(e.message);
    },
    onSettled: () => qc.invalidateQueries({ queryKey: ["match", matchId] }),
  });
}

export function useEditDraft() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: ({ id, ...body }: { id: string; to_email?: string; cc_email?: string; contact_id?: string; subject?: string; email_body?: string; linkedin_note?: string }) =>
      api.patch<DraftWithJob>(`/drafts/${id}`, body),
    onSuccess: () => invalidate("drafts", "match"),
    onError: (e: Error) => toast.error(e.message),
  });
}

export function useApply() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (id: string) => api.post<Match>(`/matches/${id}/apply`),
    onSuccess: (m) => {
      toast.success(`Marked as applied · ${m.job.company}`, { description: "Follow-up reminder set for 7 days." });
      invalidate("matches", "match", "overview");
    },
    onError: (e: Error) => toast.error(e.message),
  });
}

export function usePrepare() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (id: string) => api.post<Run>(`/matches/${id}/prepare`),
    onSuccess: () => {
      agentToast("tailor", "On it. Your tailored resume and draft email will appear here in a few seconds.");
      invalidate("runs", "overview", "match", "matches");
    },
    onError: (e: Error) => toast.error(e.message),
  });
}

export function useNotifications() {
  return useQuery({ queryKey: ["notifications"], queryFn: () => api.get<AppNotification[]>("/notifications?limit=30"), refetchInterval: 30_000 });
}

export function useMarkRead() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (ids?: string[]) => api.post<void>("/notifications/read", { ids: ids ?? null }),
    onSuccess: () => invalidate("notifications", "overview"),
  });
}

export const useConfig = () => useQuery({ queryKey: ["config"], queryFn: () => api.get<AppConfig>("/config"), staleTime: 5 * 60_000 });

export const useResearch = () => useQuery({ queryKey: ["research"], queryFn: () => api.get<ResearchState>("/research") });

export function useResearchNow() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: () => api.post<Run>("/research/run"),
    onSuccess: () => {
      agentToast("researcher", "On it. Finding companies that hire for your profile, then the whole crew runs.");
      invalidate("runs", "overview", "research");
    },
    onError: (e: Error) => toast.error(e.message),
  });
}

export function useSendApplication() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: ({ id, ...body }: { id: string; to_email?: string; subject?: string; email_body?: string; linkedin_note?: string }) =>
      api.post<DraftWithJob>(`/drafts/${id}/send`, body),
    onSuccess: (d) => {
      toast.success(`Application sent to ${d.to_email}`, { description: `${d.company} · tailored resume attached · moved to Applied` });
      invalidate("drafts", "overview", "matches", "match", "runs", "quota");
    },
    onError: (e: Error) => toast.error(e.message),
  });
}

export const useContacts = (matchId: string) =>
  useQuery({ queryKey: ["contacts", matchId], queryFn: () => api.get<ContactsOut>(`/matches/${matchId}/contacts`) });

export function useFindContacts(matchId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (refresh: boolean = false) => api.post<ContactsOut>(`/matches/${matchId}/contacts/find?refresh=${refresh}`),
    onSuccess: (data) => {
      qc.setQueryData(["contacts", matchId], data);
      toast.success(data.contacts.length ? `Found ${data.contacts.length} real contact${data.contacts.length === 1 ? "" : "s"}` : "No public contacts found for this company");
    },
    onError: (e: Error) => toast.error(e.message),
  });
}

// ---------- Account, plan, mail, admin ----------

export const useUsage = () => useQuery({ queryKey: ["usage"], queryFn: () => api.get<Usage>("/usage"), refetchInterval: 60_000 });

export const useMailAccount = () => useQuery({ queryKey: ["mail-account"], queryFn: () => api.get<MailAccount>("/mail-account") });

export function useConnectMail() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (body: { host: string; port: number; username: string; password: string; from_name: string }) => api.put<MailAccount>("/mail-account", body),
    onSuccess: (m) => {
      toast.success("Email connected", { description: `Applications you approve are sent from ${m.from_email}.` });
      invalidate("mail-account", "config");
    },
    onError: (e: Error) => toast.error("Couldn’t connect", { description: e.message }),
  });
}

export function useDisconnectMail() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: () => api.del("/mail-account"),
    onSuccess: () => {
      toast.success("Email disconnected");
      invalidate("mail-account", "config");
    },
  });
}

export function useProInterest() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: () => api.post<{ detail: string }>("/account/pro-interest"),
    onSuccess: (r) => {
      toast.success("Request sent", { description: r.detail });
      invalidate("usage");
    },
    onError: (e: Error) => toast.error(e.message),
  });
}

export const useAdminMetrics = () =>
  useQuery({ queryKey: ["admin-metrics"], queryFn: () => api.get<AdminMetrics>("/admin/metrics"), refetchInterval: 30_000, retry: false });

export function useSetPlan() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (body: { email: string; plan: "free" | "pro" }) => api.post<{ email: string; plan: string }>("/admin/plan", body),
    onSuccess: (r) => {
      toast.success(`${r.email} is now on ${r.plan}`);
      invalidate("admin-metrics");
    },
    onError: (e: Error) => toast.error(e.message),
  });
}

// ---------- v2 ----------

function useAct<TBody, TOut>(fn: (b: TBody) => Promise<TOut>, keys: string[], ok?: string | ((r: TOut) => string)) {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: fn,
    onSuccess: (r) => {
      if (ok) toast.success(typeof ok === "function" ? ok(r) : ok);
      invalidate(...keys);
    },
    onError: (e: Error) => toast.error(e.message),
  });
}

export const useEvidence = () => useQuery({ queryKey: ["evidence"], queryFn: () => api.get<Evidence>("/evidence") });
export const useLinkGithub = () => useAct((handle: string) => api.put<Evidence>("/evidence/github", { handle }), ["evidence"], "GitHub linked");
export const useVerifyGithub = () => useAct(() => api.post<Evidence>("/evidence/github/verify"), ["evidence"], "GitHub ownership verified");
export const useLinkCodeforces = () => useAct((handle: string) => api.put<Evidence>("/evidence/codeforces", { handle }), ["evidence"], "Codeforces linked");
export const useUnlinkEvidence = () => useAct((source: string) => api.del<Evidence>(`/evidence/${source}`), ["evidence"]);
export const useAddEvidenceItem = () => useAct((b: { kind: string; title: string; url: string }) => api.post<Evidence>("/evidence/items", b), ["evidence"], "Added to your proof pack");
export const useRemoveEvidenceItem = () => useAct((id: string) => api.del<Evidence>(`/evidence/items/${id}`), ["evidence"]);
export const usePublishProof = () =>
  useAct((pub: boolean) => api.put<Evidence>("/evidence/public", { public: pub }), ["evidence", "consents"], (r) => (r.public ? "Proof page published" : "Proof page unpublished"));

export const useInsights = () => useQuery({ queryKey: ["insights"], queryFn: () => api.get<Insights>("/insights") });
export const useSetOutcome = () =>
  useAct(
    (b: { id: string; outcome: Outcome; rejection_reason?: string }) => api.patch(`/matches/${b.id}`, { outcome: b.outcome, rejection_reason: b.rejection_reason }),
    ["insights", "matches", "match", "overview", "campus", "reminders"],
    "Outcome saved",
  );

export const useCampus = () => useQuery({ queryKey: ["campus"], queryFn: () => api.get<Campus>("/campus") });
export const useSaveAcademics = () => useAct((b: Record<string, unknown>) => api.put("/campus/academics", b), ["campus"], "Academics saved");
export const useAddDrive = (college = false) =>
  useAct((b: Record<string, unknown>) => api.post(college ? "/college/drives" : "/campus/drives", b), ["campus", "college"], "Drive added");
export const useDeleteDrive = (college = false) => useAct((id: string) => api.del(`${college ? "/college" : "/campus"}/drives/${id}`), ["campus", "college"]);
export const useDriveStatus = () => useAct((b: { id: string; status: string; round_index?: number }) => api.put(`/campus/drives/${b.id}/status`, b), ["campus"]);
export const useJoinCollege = () =>
  useAct((b: { invite_code: string; share_progress: boolean }) => api.post<{ college: string }>("/campus/join", b), ["campus", "consents"], (r) => `Joined ${r.college}`);
export const useLeaveCollege = () => useAct(() => api.post("/campus/leave"), ["campus", "consents"], "Left the college");
export const useShareProgress = () => useAct((share: boolean) => api.put("/campus/share", { share_progress: share }), ["campus", "consents"]);
export const useCollege = () => useQuery({ queryKey: ["college"], queryFn: () => api.get<CollegeDashboard>("/college"), retry: false });

export const useConsents = () => useQuery({ queryKey: ["consents"], queryFn: () => api.get<ConsentState>("/consents") });
export const useSetConsent = () =>
  useAct((b: { purpose: string; granted: boolean }) => api.put<ConsentState>(`/consents/${b.purpose}`, { granted: b.granted }), ["consents", "evidence", "whatsapp", "campus"]);

export const useProofLinks = () => useQuery({ queryKey: ["proof-links"], queryFn: () => api.get<MyProofLink[]>("/proof-links") });
export const useRevokeProofLink = () => useAct((id: string) => api.post<MyProofLink>(`/proof-links/${id}/revoke`), ["proof-links", "matches"], "Link revoked. It no longer opens.");

export const useQuota = () => useQuery({ queryKey: ["quota"], queryFn: () => api.get<QuotaState>("/quota") });
export const useSetQuota = () => useAct((b: { cap: number }) => api.put<QuotaState>("/quota", b), ["quota"], (q) => `Up to ${q.cap} approved sends a day`);

export const useRights = () => useQuery({ queryKey: ["rights"], queryFn: () => api.get<RightsState>("/rights") });
export const useCreateRight = () => useAct((b: { kind: string; details: string }) => api.post<RightsRequest>("/rights", b), ["rights"], "Request sent. We’ll reply within 30 days.");
export const useAdminRights = () => useQuery({ queryKey: ["admin-rights"], queryFn: () => api.get<RightsRequest[]>("/admin/rights") });
export const useResolveRight = () =>
  useAct((b: { id: string; response: string }) => api.post<RightsRequest>(`/admin/rights/${b.id}/resolve`, { response: b.response }), ["admin-rights"], "Answered");
export const useConfirmAge = () => useAct((b: { adult: boolean }) => api.post("/account/age", b), ["me"]);

export const useWhatsApp = () => useQuery({ queryKey: ["whatsapp"], queryFn: () => api.get<WhatsAppState>("/whatsapp") });
export const useSaveWhatsApp = () => useAct((b: { number: string; hour: number; consent: boolean }) => api.put<WhatsAppState>("/whatsapp", b), ["whatsapp", "consents"], "WhatsApp digest on");
export const useStopWhatsApp = () => useAct(() => api.del<WhatsAppState>("/whatsapp"), ["whatsapp", "consents"], "WhatsApp digest off");
export const useTestWhatsApp = () => useAct(() => api.post<{ detail: string }>("/whatsapp/test"), [], "Test digest sent");

export const useExtensionTokens = () => useQuery({ queryKey: ["ext-tokens"], queryFn: () => api.get<ExtensionToken[]>("/extension/tokens") });
export const useCreateToken = () => useAct((name: string) => api.post<{ token: string; prefix: string }>("/extension/tokens", { name }), ["ext-tokens"]);
export const useRevokeToken = () => useAct((id: string) => api.del(`/extension/tokens/${id}`), ["ext-tokens"], "Token revoked");

export const useAdminOrgs = () => useQuery({ queryKey: ["admin-orgs"], queryFn: () => api.get<{ id: string; name: string; invite_code: string; students: number; officers: string[] }[]>("/admin/orgs"), retry: false });
export const useCreateOrg = () => useAct((name: string) => api.post<{ name: string; invite_code: string }>("/admin/orgs", { name }), ["admin-orgs"], (r) => `${r.name} created · code ${r.invite_code}`);
export const useAddOfficer = () => useAct((b: { org: string; email: string }) => api.post(`/admin/orgs/${b.org}/officers`, { email: b.email }), ["admin-orgs"], "Officer added");
