import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";

import { server } from "../test/server";
import LoginPage from "./LoginPage";

const ok = (data: unknown) => HttpResponse.json({ code: 200, message: "ok", data });

function renderLogin() {
  return render(
    <MemoryRouter initialEntries={["/login"]}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/" element={<div>home-page</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

async function fillAndSubmit(username: string, password: string) {
  const user = userEvent.setup();
  await user.type(screen.getByPlaceholderText("admin"), username);
  await user.type(screen.getByPlaceholderText("••••••••"), password);
  await user.click(screen.getByRole("button", { name: "登录" }));
}

describe("LoginPage", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("登录成功 -> 保存 token 并跳转首页", async () => {
    server.use(
      http.post("/api/auth/login", () => ok({ access_token: "token-1", token_type: "bearer" })),
    );
    renderLogin();

    await fillAndSubmit("admin", "secret");

    expect(await screen.findByText("home-page")).toBeInTheDocument();
    expect(localStorage.getItem("interview_agent_token")).toBe("token-1");
  });

  it("登录失败 -> 展示错误信息", async () => {
    server.use(
      http.post("/api/auth/login", () =>
        HttpResponse.json({ code: 401, message: "用户名或密码错误", data: null }),
      ),
    );
    renderLogin();

    await fillAndSubmit("admin", "wrong");

    expect(await screen.findByRole("alert")).toHaveTextContent("用户名或密码错误");
  });
});
