import { render, screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { server } from "../test/server";
import RequireAuth from "./RequireAuth";

const ok = (data: unknown) => HttpResponse.json({ code: 200, message: "ok", data });

function renderGuard() {
  return render(
    <MemoryRouter initialEntries={["/history"]}>
      <Routes>
        <Route element={<RequireAuth />}>
          <Route path="/history" element={<div>protected-page</div>} />
        </Route>
        <Route path="/login" element={<div>login-page</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("RequireAuth", () => {
  it("me 返回 401 -> 重定向登录页", async () => {
    server.use(
      http.get("/api/auth/me", () =>
        HttpResponse.json({ code: 401, message: "未授权", data: null }),
      ),
    );
    renderGuard();

    expect(await screen.findByText("login-page")).toBeInTheDocument();
    expect(screen.queryByText("protected-page")).not.toBeInTheDocument();
  });

  it("me 返回 200（降级模式）-> 放行受保护页面", async () => {
    server.use(http.get("/api/auth/me", () => ok({ user_id: "default" })));
    renderGuard();

    expect(await screen.findByText("protected-page")).toBeInTheDocument();
  });
});
