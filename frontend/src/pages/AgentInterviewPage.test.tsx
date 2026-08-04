import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { agentInterviewApi } from "../api/agentInterview";
import AgentInterviewPage from "./AgentInterviewPage";

vi.mock("../api/agentInterview", () => ({
  agentInterviewApi: {
    createSession: vi.fn(),
    getSession: vi.fn(),
    resumeSession: vi.fn(),
  },
}));

vi.mock("../api/stream", () => ({
  streamSse: vi.fn(),
}));

const mockedCreate = vi.mocked(agentInterviewApi.createSession);
const mockedGet = vi.mocked(agentInterviewApi.getSession);
const mockedResume = vi.mocked(agentInterviewApi.resumeSession);
const sessionWithApproval = {
  session_id: "s1",
  skill_id: "java-backend",
  difficulty: "mid",
  turn_count: 0,
  max_turns: 6,
  current_question: null,
  finished: false,
  category_scores: {},
  pending_approval: { question: "Q2", category: "JAVA", type: "generate_question_approval" },
};

describe("AgentInterviewPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("创建会话后展示换题确认对话框", async () => {
    mockedCreate.mockResolvedValue(sessionWithApproval as never);
    const user = userEvent.setup();
    render(<AgentInterviewPage />);

    await user.click(screen.getByRole("button", { name: "开始面试" }));

    expect(await screen.findByText("题目审批")).toBeInTheDocument();
    expect(screen.getByText("Q2")).toBeInTheDocument();
  });

  it("点击通过 -> 调用 resumeSession(approved=true) 并关闭对话框", async () => {
    mockedCreate.mockResolvedValue(sessionWithApproval as never);
    mockedResume.mockResolvedValue({ finished: false, score: null, feedback: null, next_question: null, difficulty_changed: false, new_difficulty: null, pending_approval: null } as never);
    mockedGet.mockResolvedValue({ ...sessionWithApproval, pending_approval: null } as never);
    const user = userEvent.setup();
    render(<AgentInterviewPage />);

    await user.click(screen.getByRole("button", { name: "开始面试" }));
    await user.click(await screen.findByRole("button", { name: "通过" }));

    expect(mockedResume).toHaveBeenCalledWith("s1", { approved: true });
    expect(screen.queryByText("题目审批")).not.toBeInTheDocument();
  });

  it("点击驳回 -> 调用 resumeSession(approved=false)", async () => {
    mockedCreate.mockResolvedValue(sessionWithApproval as never);
    mockedResume.mockResolvedValue({ finished: false, score: null, feedback: null, next_question: null, difficulty_changed: false, new_difficulty: null, pending_approval: null } as never);
    mockedGet.mockResolvedValue({ ...sessionWithApproval, pending_approval: null } as never);
    const user = userEvent.setup();
    render(<AgentInterviewPage />);

    await user.click(screen.getByRole("button", { name: "开始面试" }));
    await user.click(await screen.findByRole("button", { name: "驳回" }));

    expect(mockedResume).toHaveBeenCalledWith("s1", { approved: false });
  });
});
