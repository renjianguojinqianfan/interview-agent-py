# ruff: noqa: N815  LLM 输出模型字段须 camelCase 对齐 prompt 的 Output Format
import logging

from pydantic import BaseModel

from app.domain.errors import BusinessException, ErrorCode
from app.infrastructure.ai.llm_registry import LlmProviderRegistry
from app.infrastructure.ai.prompt_loader import load_prompt
from app.infrastructure.ai.prompt_sanitizer import PromptSanitizer
from app.infrastructure.ai.structured_output import StructuredOutputInvoker

logger = logging.getLogger(__name__)


class Suggestion(BaseModel):
    category: str
    priority: str
    issue: str
    recommendation: str


class ScoreDetail(BaseModel):
    projectScore: int
    skillMatchScore: int
    contentScore: int
    structureScore: int
    expressionScore: int


class ResumeAnalysisResult(BaseModel):
    """LLM 简历分析输出模型，字段名严格对应 resume-analysis-system.st 的 Output Format。"""

    overallScore: int
    scoreDetail: ScoreDetail
    summary: str
    strengths: list[str]
    suggestions: list[Suggestion]


class ResumeAnalysisService:
    """简历 LLM 分析服务：加载 prompt -> 结构化输出调用 -> 映射结果；LLM 失败时降级。"""

    def __init__(
        self,
        llm_registry: LlmProviderRegistry,
        invoker: StructuredOutputInvoker,
        sanitizer: PromptSanitizer | None = None,
    ) -> None:
        self._llm_registry = llm_registry
        self._invoker = invoker
        self._sanitizer = sanitizer or PromptSanitizer()

    async def analyze_resume(self, resume_text: str) -> ResumeAnalysisResult:
        try:
            system_tpl = await load_prompt("resume-analysis-system")
            user_tpl = await load_prompt("resume-analysis-user")
            system_prompt = system_tpl.format()
            sanitized_text = self._sanitizer.sanitize(resume_text) or ""
            wrapped_text = self._sanitizer.wrap_with_delimiters("简历内容", sanitized_text)
            user_prompt = user_tpl.format(resumeText=wrapped_text)

            llm = await self._llm_registry.get_chat_client()
            result = await self._invoker.invoke(
                llm=llm,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                output_model=ResumeAnalysisResult,
                error_code=ErrorCode.RESUME_ANALYSIS_FAILED,
                error_prefix="简历分析失败：",
                log_context="简历分析",
            )
            logger.info("简历分析完成: overallScore=%s", result.overallScore)
            return result
        except BusinessException as e:
            logger.error("简历分析 LLM 调用失败，返回降级结果: %s", e)
            return self._degraded_result()

    def _degraded_result(self) -> ResumeAnalysisResult:
        return ResumeAnalysisResult(
            overallScore=0,
            scoreDetail=ScoreDetail(
                projectScore=0,
                skillMatchScore=0,
                contentScore=0,
                structureScore=0,
                expressionScore=0,
            ),
            summary="分析过程中出现错误，请稍后重试",
            strengths=[],
            suggestions=[
                Suggestion(
                    category="系统",
                    priority="高",
                    issue="AI分析服务暂时不可用",
                    recommendation="请稍后重试，或检查AI服务是否正常运行",
                )
            ],
        )
