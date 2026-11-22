import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { I18nProvider } from "./i18n";
import D0Controls from "./components/D0Controls";

// 1.4.15 (lot 6): D-0 pause block of the page "Lịch chạy dữ liệu". Backend mocked (unit, fake fetch, no network).
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
const wrap = (el: React.ReactNode) => <I18nProvider><MemoryRouter>{el}</MemoryRouter></I18nProvider>;
beforeEach(() => localStorage.clear());

const RUNNING = { paused: false, until: null, until_vn: null, by: "", remaining_minutes: 0, max_hours: 6 };
const PAUSED = { paused: true, until: "2026-11-23T09:00:00+00:00", until_vn: "23/11/2026 16:00", by: "UI", remaining_minutes: 130, max_hours: 6 };

interface Call { url: string; method: string; body: any }
function backend(o: { status?: any; pause?: (b: any) => Response; resume?: () => Response } = {}) {
  const calls: Call[] = [];
  globalThis.fetch = vi.fn(async (url: any, init?: any) => {
    const u = String(url);
    const method = init?.method ?? "GET";
    const body = init?.body ? JSON.parse(init.body) : undefined;
    calls.push({ url: u, method, body });
    if (u === "/api/d0/pause" && method === "GET") return json(o.status ?? RUNNING);
    if (u === "/api/d0/pause" && method === "POST") return o.pause ? o.pause(body) : json({ ...PAUSED, remaining_minutes: Math.round(body.hours * 60) });
    if (u === "/api/d0/resume" && method === "POST") return o.resume ? o.resume() : json(RUNNING);
    return json({ code: "TEST_UNAVAILABLE" }, 503);
  }) as any;
  return calls;
}
const posts = (calls: Call[]) => calls.filter((c) => c.method === "POST");
const mount = async () => { await act(async () => { render(wrap(<D0Controls />)); }); await screen.findByTestId("d0c-status"); };
const hours = () => screen.getByTestId("d0c-hours") as HTMLInputElement;

describe("1.4.15 D-0 pause controls", () => {
  it("not paused: says D-0 runs, hours default to 6, 'Bật lại' is off, and the auto-resume / monitoring-only sentence is written", async () => {
    const calls = backend();
    await mount();
    expect(screen.getByTestId("d0c-status").textContent).toBe("D-0 đang chạy theo lịch.");
    expect(hours().value).toBe("6");
    expect((screen.getByTestId("d0c-resume") as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByTestId("d0c-pause") as HTMLButtonElement).disabled).toBe(false);
    expect(screen.getByTestId("d0c-auto").textContent).toBe("Tự bật lại sau 6 giờ; D-0 chỉ để theo dõi.");
    expect(screen.getByTestId("d0c-intro").textContent).toContain("không dùng cho dự báo, học hay file Excel");
    expect(posts(calls)).toEqual([]);                                  // reading the status writes nothing
  });

  it("pause: POST {hours, by} with the hours chosen (default 6), then the status shows until when; no typed text is asked", async () => {
    const calls = backend();
    await mount();
    fireEvent.change(hours(), { target: { value: "3" } });
    expect(screen.getByTestId("d0c-auto").textContent).toBe("Tự bật lại sau 3 giờ; D-0 chỉ để theo dõi.");
    await act(async () => { fireEvent.click(screen.getByTestId("d0c-pause")); });
    expect(posts(calls)).toHaveLength(1);
    expect(posts(calls)[0]).toMatchObject({ url: "/api/d0/pause", body: { hours: 3, by: "UI" } });
    expect(await screen.findByText("Đã tạm dừng D-0 (backend xác nhận).")).toBeTruthy();
    expect(screen.getByTestId("d0c-status").textContent).toContain("đến 23/11/2026 16:00");
    expect((screen.getByTestId("d0c-resume") as HTMLButtonElement).disabled).toBe(false);
  });

  it("the default pause is 6 hours", async () => {
    const calls = backend();
    await mount();
    await act(async () => { fireEvent.click(screen.getByTestId("d0c-pause")); });
    expect(posts(calls)[0].body).toEqual({ hours: 6, by: "UI" });
  });

  it("hours outside 1..6 (or empty) lock the pause button with the reason", async () => {
    backend();
    await mount();
    const btn = screen.getByTestId("d0c-pause") as HTMLButtonElement;
    for (const v of ["0", "0.5", "7", ""]) {
      fireEvent.change(hours(), { target: { value: v } });
      expect(btn.disabled, v).toBe(true);
      expect(screen.getByTestId("d0c-hours-bad").textContent).toBe("Nhập số giờ từ 1 đến 6.");
    }
    fireEvent.change(hours(), { target: { value: "1" } });
    expect(btn.disabled).toBe(false);
  });

  it("paused: shows until when and the minutes left; 'Bật lại' posts the resume and the status goes back to running", async () => {
    const calls = backend({ status: PAUSED });
    await mount();
    const s = screen.getByTestId("d0c-status").textContent!;
    expect(s).toContain("D-0 đang tạm dừng đến 23/11/2026 16:00");
    expect(s).toContain("còn khoảng 130 phút");
    await act(async () => { fireEvent.click(screen.getByTestId("d0c-resume")); });
    expect(posts(calls)).toHaveLength(1);
    expect(posts(calls)[0]).toMatchObject({ url: "/api/d0/resume", body: { by: "UI" } });
    expect(await screen.findByText("Đã bật lại D-0 (backend xác nhận).")).toBeTruthy();
    expect(screen.getByTestId("d0c-status").textContent).toBe("D-0 đang chạy theo lịch.");
  });

  it("a pause set by someone else (an install chain): the owner is named and 'Bật lại' asks first; Cancel sends nothing, confirming sends the resume", async () => {
    const calls = backend({ status: { ...PAUSED, by: "cai_1415" } });
    await mount();
    expect(screen.getByTestId("d0c-other-owner").textContent).toContain("Đang do cai_1415 tạm dừng");
    await act(async () => { fireEvent.click(screen.getByTestId("d0c-resume")); });
    expect(screen.getByTestId("d0c-resume-confirm").textContent).toContain("cai_1415");
    expect(posts(calls)).toEqual([]);                                                       // nothing yet
    await act(async () => { fireEvent.click(screen.getByText("Hủy")); });
    expect(posts(calls)).toEqual([]);
    expect(screen.queryByTestId("d0c-resume-confirm")).toBeNull();
    await act(async () => { fireEvent.click(screen.getByTestId("d0c-resume")); });
    await act(async () => { fireEvent.click(screen.getByText("Vẫn bật lại D-0")); });
    expect(posts(calls)).toHaveLength(1);
    expect(posts(calls)[0]).toMatchObject({ url: "/api/d0/resume", body: { by: "UI" } });
    expect(await screen.findByText("Đã bật lại D-0 (backend xác nhận).")).toBeTruthy();
  });

  it("a pause set by this button (by = UI) shows no owner warning and resumes at once", async () => {
    const calls = backend({ status: PAUSED });
    await mount();
    expect(screen.queryByTestId("d0c-other-owner")).toBeNull();
    await act(async () => { fireEvent.click(screen.getByTestId("d0c-resume")); });
    expect(posts(calls)).toHaveLength(1);
  });

  it("an error from the server (D0_PAUSE_INVALID, 422) is shown with its own bilingual message and the status is not changed", async () => {
    backend({ pause: () => json({ code: "D0_PAUSE_INVALID", vi: "Thời gian tạm dừng D-0 không hợp lệ: từ 1 đến 6 giờ.", en: "Invalid pause", detail: "hours must be 1..6" }, 422) });
    await mount();
    await act(async () => { fireEvent.click(screen.getByTestId("d0c-pause")); });
    expect(await screen.findByText("Thời gian tạm dừng D-0 không hợp lệ: từ 1 đến 6 giờ.")).toBeTruthy();
    expect(screen.getByText("D0_PAUSE_INVALID")).toBeTruthy();
    expect(screen.getByTestId("d0c-status").textContent).toBe("D-0 đang chạy theo lịch.");
  });

  it("the load error and the refresh button", async () => {
    globalThis.fetch = vi.fn(async () => json({ code: "INTERNAL_ERROR", vi: "Lỗi máy chủ", en: "Server error" }, 500)) as any;
    await act(async () => { render(wrap(<D0Controls />)); });
    expect(await screen.findByText("Lỗi máy chủ")).toBeTruthy();
    const calls = backend({ status: PAUSED });
    await act(async () => { fireEvent.click(screen.getByText("Làm mới")); });
    await waitFor(() => expect(calls.filter((c) => c.method === "GET")).toHaveLength(1));
    expect((await screen.findByTestId("d0c-status")).textContent).toContain("đang tạm dừng");
  });
});
