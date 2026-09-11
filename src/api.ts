import { QueryClient } from "@tanstack/react-query";
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: false, staleTime: 15000, refetchOnWindowFocus: false },
  },
});
export async function api<T = any>(
  path: string,
  method = "GET",
  body?: unknown,
): Promise<T> {
  const response = await fetch("/api" + path, {
    method,
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-AMS-Client": "preview" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await response
    .json()
    .catch(() => ({ detail: "服務回應格式錯誤" }));
  if (!response.ok) {
    if (response.status === 401 && path != "/auth/me")
      queryClient.invalidateQueries({ queryKey: ["me"] });
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : "資料格式不正確，請檢查欄位",
    );
  }
  if (path === "/permissions/sync")
    await queryClient.invalidateQueries({ queryKey: ["me"] });
  return data;
}
export type User = {
  id: string;
  name: string;
  email: string;
  role: string;
  role_label: string;
  permissions: any;
};
export type Resource = {
  id: number;
  kind: string;
  label: string;
  [key: string]: any;
};
export type Booking = {
  id: string;
  kind: string;
  status: string;
  revision: number;
  created_at: string;
  updated_at: string;
  previous_id?: string;
  content: any;
  slots: { resource_id: number; start: string; end: string }[];
  stages?: any[];
  history?: any[];
  versions?: any[];
};
export const states: Record<string, string> = {
  PENDING: "已預約",
  DEPARTURE: "已發車",
  DEPARTURE_ARRIVED: "發車已抵達",
  RETURN: "已開始回程",
  RETURN_ARRIVED: "已完成",
};
export const nextStates: Record<string, string> = {
  PENDING: "填寫發車表",
  DEPARTURE: "填寫發車抵達",
  DEPARTURE_ARRIVED: "填寫還車表",
  RETURN: "填寫還車抵達",
};
export const kindNames: Record<string, string> = {
  A: "車輛借用",
  D: "作業區預約",
  E: "儀器借用",
};
// datetime-local values represent Taipei business time, regardless of browser zone.
export const businessDate = (value: string) =>
  new Date(
    /[zZ]$|[+-]\d{2}:\d{2}$/.test(value)
      ? value
      : value.length === 10
        ? value + "T00:00:00+08:00"
        : value + "+08:00",
  );
export const dateTime = (v: string) =>
  v
    ? new Intl.DateTimeFormat("zh-TW", {
        timeZone: "Asia/Taipei",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      }).format(businessDate(v))
    : "—";
export const localDate = (date = new Date()) =>
  new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Taipei",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(date);
export const localInput = (s: string) =>
  s
    ? `${localDate(businessDate(s))}T${new Intl.DateTimeFormat("en-GB", { timeZone: "Asia/Taipei", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }).format(businessDate(s))}`
    : "";
export function invalidate() {
  return queryClient.invalidateQueries({
    predicate: (q) => q.queryKey[0] !== "me",
  });
}
