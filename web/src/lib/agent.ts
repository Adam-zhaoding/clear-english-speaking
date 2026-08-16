import type { AgentStatus } from "./types";

const base = "http://127.0.0.1:8765";
const tokenKey = "clear-english-agent-token";
const headers = () => ({ "X-Clear-English-Token": sessionStorage.getItem(tokenKey) || "" });

export const isAgentPaired = () => Boolean(sessionStorage.getItem(tokenKey));

export async function agentStatus(): Promise<AgentStatus> {
  try {
    const response = await fetch(`${base}/status`, { signal: AbortSignal.timeout(1000) });
    if (!response.ok) throw new Error("unavailable");
    return { connected: true, ...(await response.json() as Omit<AgentStatus, "connected">) };
  } catch {
    return { connected: false };
  }
}

export async function runAgent(): Promise<string> {
  const response = await fetch(`${base}/run`, { method: "POST", headers: headers(), signal: AbortSignal.timeout(3000) });
  if (!response.ok) throw new Error("本地备课服务未启动或拒绝请求。");
  const result = await response.json() as { result: string };
  return result.result;
}

export async function pairAgent(code: string): Promise<void> {
  const response = await fetch(`${base}/pair`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ code }), signal: AbortSignal.timeout(3000) });
  if (!response.ok) throw new Error("配对码无效。请查看本地服务启动窗口。 ");
  sessionStorage.setItem(tokenKey, (await response.json() as { token: string }).token);
  window.dispatchEvent(new Event("clear-english-agent-paired"));
}

export async function fetchAgentCourses(): Promise<File[]> {
  const response = await fetch(`${base}/courses`, { headers: headers(), signal: AbortSignal.timeout(3000) });
  if (!response.ok) return [];
  const body = await response.json() as { courses: { id: string; filename: string }[] };
  return Promise.all(body.courses.map(async (course) => new File([await (await fetch(`${base}/courses/${course.id}`, { headers: headers() })).blob()], course.filename, { type: "application/zip" })));
}

export async function saveAgentSchedule(schedule: { days: number[]; time: string; timezone: string }): Promise<string> {
  const response = await fetch(`${base}/settings`, { method: "POST", headers: { ...headers(), "Content-Type": "application/json" }, body: JSON.stringify({ schedule }), signal: AbortSignal.timeout(3000) });
  if (!response.ok) throw new Error("无法保存本地备课计划。");
  return (await response.json() as { result: string }).result;
}
