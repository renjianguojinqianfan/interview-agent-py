import { useCallback, useState } from "react";
import {
  AdaptiveAnswerResultDTO,
  AdaptiveSessionDTO,
  agentInterviewApi,
} from "../api/agentInterview";
import { streamSse } from "../api/stream";
import { getToken } from "../auth/token";
import QuestionApprovalDialog from "../components/QuestionApprovalDialog";

interface SseEvent {
  event: string;
  data: Record<string, unknown>;
}

export default function AgentInterviewPage() {
  const [session, setSession] = useState<AdaptiveSessionDTO | null>(null);
  const [answer, setAnswer] = useState("");
  const [eventLog, setEventLog] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [approval, setApproval] = useState<Record<string, unknown> | null>(null);
  const [approvalLoading, setApprovalLoading] = useState(false);

  const startInterview = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const created = await agentInterviewApi.createSession({ skill_id: "java-backend" });
      setSession(created);
      setApproval(created.pending_approval ?? null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "创建会话失败");
    } finally {
      setLoading(false);
    }
  }, []);

  const submitAnswer = useCallback(async () => {
    if (!session || !answer.trim()) return;
    setLoading(true);
    setError("");
    setEventLog([]);
    const token = getToken();
    await streamSse({
      url: `/api/agent/interview/sessions/${session.session_id}/answer/stream`,
      init: {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ answer }),
      },
      parseMode: "event",
      onMessage: (chunk) => {
        try {
          const parsed = JSON.parse(chunk) as SseEvent;
          if (parsed.event === "on_interrupt") {
            setApproval((parsed.data.payload as Record<string, unknown>) ?? {});
            return;
          }
          if (parsed.event === "on_result") {
            const data = parsed.data as unknown as AdaptiveAnswerResultDTO;
            setSession((prev) =>
              prev
                ? {
                    ...prev,
                    current_question: data.next_question ?? prev.current_question,
                    finished: data.finished,
                    pending_approval: data.pending_approval ?? null,
                  }
                : prev,
            );
            return;
          }
          setEventLog((prev) => [...prev, chunk]);
        } catch {
          setEventLog((prev) => [...prev, chunk]);
        }
      },
      onComplete: () => setLoading(false),
      onError: (err) => {
        setError(err.message);
        setLoading(false);
      },
    });
  }, [session, answer]);

  const handleApproval = useCallback(
    async (approved: boolean) => {
      if (!session) return;
      setApprovalLoading(true);
      setError("");
      try {
        await agentInterviewApi.resumeSession(session.session_id, { approved });
        setApproval(null);
        const fresh = await agentInterviewApi.getSession(session.session_id);
        setSession(fresh);
        setApproval(fresh.pending_approval ?? null);
      } catch (err) {
        setError(err instanceof Error ? err.message : "审批提交失败");
      } finally {
        setApprovalLoading(false);
      }
    },
    [session],
  );

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-slate-900 dark:text-white">Agent 自适应面试</h1>
        {!session && (
          <button
            onClick={startInterview}
            disabled={loading}
            className="px-5 py-2.5 bg-gradient-to-r from-primary-500 to-primary-600 text-white rounded-xl font-semibold disabled:opacity-50"
          >
            {loading ? "创建中..." : "开始面试"}
          </button>
        )}
      </div>

      {error && <p className="text-sm text-red-500" role="alert">{error}</p>}

      {session?.current_question && (
        <div className="bg-white dark:bg-slate-800 rounded-2xl shadow p-6">
          <span className="inline-block px-2.5 py-1 bg-primary-100 dark:bg-primary-900/30 text-primary-700 dark:text-primary-300 text-xs font-medium rounded-full mb-3">
            {session.current_question.category} · {session.current_question.difficulty}
          </span>
          <p className="text-slate-800 dark:text-slate-200 leading-relaxed whitespace-pre-wrap">
            {session.current_question.question}
          </p>
        </div>
      )}

      {session && !session.finished && (
        <div className="bg-white dark:bg-slate-800 rounded-2xl shadow p-6 space-y-4">
          <textarea
            value={answer}
            onChange={(e) => setAnswer(e.target.value)}
            rows={5}
            className="w-full px-4 py-3 rounded-xl border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-700 text-slate-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-primary-500"
            placeholder="输入你的回答..."
          />
          <button
            onClick={submitAnswer}
            disabled={loading || !answer.trim()}
            className="px-5 py-2.5 bg-primary-500 text-white rounded-xl font-semibold disabled:opacity-50"
          >
            {loading ? "思考中..." : "提交回答"}
          </button>
        </div>
      )}

      {session?.finished && (
        <p className="text-lg font-semibold text-slate-700 dark:text-slate-200">面试已完成</p>
      )}

      {eventLog.length > 0 && (
        <div className="bg-slate-50 dark:bg-slate-800/50 rounded-xl p-4 max-h-64 overflow-y-auto text-xs text-slate-500 space-y-1">
          {eventLog.map((line, index) => (
            <p key={index}>{line}</p>
          ))}
        </div>
      )}

      <QuestionApprovalDialog
        open={approval !== null}
        approvalData={approval}
        loading={approvalLoading}
        onApprove={() => handleApproval(true)}
        onReject={() => handleApproval(false)}
        onClose={() => setApproval(null)}
      />
    </div>
  );
}
